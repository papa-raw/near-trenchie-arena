"""The hosted arena's identity desk and chain mode (near/chain/identity.py, near/chain/hosted_live.py).

    python3 -I near/chain/test_identity_desk.py

The identity contract and the testnet inventory are small in-test fakes with the real contract's view shapes and
refusals (claim from custody only, paid_mint by the caller with a permit, mint_trenchie once per id, sale_ready).
No network, no key file outside a temp dir.
"""

import asyncio
import base64
import hashlib
import http.client
import json
import os
import struct
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "near" / "arena")]

from near.chain import identity, near_tx  # noqa: E402

NAMES = ("Brawler Swing", "Hunter Lunge", "Survivor Beam", "Looter Lob", "Brawler Zap")
ID_NFT, INV_NFT, MIRROR = "nft.id-test.testnet", "nft.inv-test.testnet", "custody.inv-test.testnet"
PLAYER = "player-one.testnet"


class FakeNft:
    """Views and calls of trenchie_nft that the desk uses."""

    def __init__(self, presets, custodian, held=(), mint_cost="10000000000000000000000"):
        self.presets, self.custodian, self.mint_cost = list(presets), custodian, mint_cost
        self.tokens = {}
        for tid, preset in held:
            self.tokens[tid] = {"owner": custodian, "preset_id": preset, "digest": "d" * 63 + str(len(self.tokens) % 10),
                                "sale_ready": True}

    def view(self, method, args):
        if method == "contract_state":
            held = sum(1 for t in self.tokens.values() if t["owner"] == self.custodian)
            return {"presets": self.presets, "custodian": self.custodian, "mint_cost": self.mint_cost,
                    "permit_epoch": "1", "premint": {"held": held}, "mint_cap": 300,
                    "minted_by_minter": sum(1 for t in self.tokens.values() if t["owner"] != self.custodian)}
        if method == "nft_token":
            t = self.tokens.get(args["token_id"])
            return t and {"token_id": args["token_id"], "owner_id": t["owner"]}
        if method == "trenchie":
            t = self.tokens.get(args["token_id"])
            return t and {"token_id": args["token_id"], "owner_id": t["owner"], "preset_id": t["preset_id"],
                          "persona_digest": t["digest"], "sale_ready": t["sale_ready"], "bag": [], "record": {}}
        if method == "nft_tokens_for_owner":
            return [{"token_id": k, "metadata": {}} for k, t in sorted(self.tokens.items())
                    if t["owner"] == args["account_id"]]
        raise AssertionError(method)

    def call(self, method, args):
        if method == "claim":
            t = self.tokens[args["token_id"]]
            if t["owner"] != self.custodian or t["digest"] != args["persona_hash"]:
                return False, "token is not held for claim"
            t["owner"] = args["to"]
            return True, None
        if method == "mint_trenchie":
            if args["token_id"] in self.tokens:
                return False, "Smart contract panicked: token id already minted"
            if args["preset_id"] not in self.presets:
                return False, "preset is not one fixed at init"
            self.tokens[args["token_id"]] = {"owner": args["owner_id"], "preset_id": args["preset_id"],
                                             "digest": args["persona_digest"], "sale_ready": False}
            return True, None
        raise AssertionError(method)


class FakeChain:
    """One network: contracts by id, full-access keys by account; `.view`/`.access_key` (Rpc) and `.call` (sender)."""

    def __init__(self, contracts, full_access=None):
        self.contracts, self.full_access, self.calls, self.n = contracts, full_access or {}, [], 0

    fail_views = ()             # methods whose next read raises RpcUnreachable (with a URL in its text)
    delay = 0.0

    def view(self, account, method, args=None):
        if self.delay:
            time.sleep(self.delay)
        if method in self.fail_views:
            raise identity.rpclib.RpcUnreachable("https://rpc.example/?apikey=SECRET timed out")
        return self.contracts[account].view(method, args or {})

    def access_key(self, account, public_key):
        if self.delay:
            time.sleep(self.delay)
        if public_key in self.full_access.get(account, ()):
            return {"nonce": 1, "permission": "FullAccess"}
        if public_key in self.full_access.get(account + "#fc", ()):
            return {"nonce": 1, "permission": {"FunctionCall": {"receiver_id": "market.x.testnet"}}}
        raise identity.rpclib.RpcError({"name": "HANDLER_ERROR", "cause": {"name": "UNKNOWN_ACCESS_KEY"}})

    def account(self, role):
        return "minter.inv-test.testnet"

    call_delay = 0.0

    def call(self, role, receiver, method, args, tgas, deposit=0):
        if self.call_delay:
            time.sleep(self.call_delay)
        self.n += 1
        ok, failure = self.contracts[receiver].call(method, args)
        self.calls.append((role, receiver, method, args))
        return {"landed": True, "ok": ok, "failure": failure, "tx": f"TX{self.n}"}


def wallet_key():
    sk = Ed25519PrivateKey.generate()
    return sk, "ed25519:" + near_tx.b58encode(sk.public_key().public_bytes_raw())


def b64url(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def nep413_sign(sk, ch, recipient):
    nonce = base64.urlsafe_b64decode(ch["nonce"] + "=" * (-len(ch["nonce"]) % 4))
    return base64.b64encode(sk.sign(identity.nep413_hash(ch["message"], nonce, recipient))).decode()


def settings(network="testnet", ident=ID_NFT, extra=""):
    tmp = tempfile.mkdtemp()
    env = Path(tmp) / "hosted.env"
    env.write_text(f"TRENCHIE_NETWORK=testnet\nTRENCHIE_ARENA_ID=arena.inv-test.testnet\n"
                   f"TRENCHIE_MARKET_ID=market.inv-test.testnet\nTRENCHIE_NFT_ID={INV_NFT}\n"
                   f"TRENCHIE_IDENTITY_NFT_ID={ident}\nTRENCHIE_INVENTORY_MIRROR={MIRROR}\n" + extra)
    os.chmod(env, 0o600)
    return identity.HostedSettings.from_env_file(env)


def fake_persona(sheet):
    """The desk cases' persona check: the host's real one (HostedRoom.check_persona) is used in HostedRegistration."""
    if not isinstance(sheet, dict) or "name" not in sheet:
        raise ValueError("send the trenchie's sheet")
    if any(w in sheet["name"].lower() for w in ("scam", "fraud", "jail")):
        raise ValueError("name or tag is blocked; choose an original spoof name")
    return sheet["name"], hashlib.sha256(json.dumps(sheet, sort_keys=True).encode()).hexdigest()


def desk(id_nft, inv_nft, full_access, recipient="https://arena.example", state_dir=None):
    s = settings()
    idc = FakeChain({ID_NFT: id_nft}, full_access)
    inv = FakeChain({INV_NFT: inv_nft})
    permit = Ed25519PrivateKey.generate()
    d = identity.IdentityDesk(s, idc, idc, inv, permit, recipient, names=NAMES, log=lambda line: None,
                              sleep=lambda s: None, check_persona=fake_persona, state_dir=state_dir)
    return d, idc, inv, permit


class Page:
    """A page with its own key; the wallet signs the NEP-413 message that names it; every later step is signed by it."""

    def __init__(self, d, sk, pk, account=PLAYER, address="127.0.0.1"):
        self.d, self.key, self.address = d, Ed25519PrivateKey.generate(), address
        self.pub = b64url(self.key.public_key().public_bytes_raw())
        ch = d.route("challenge", {"page_key": self.pub}, address)
        self.challenge = ch
        self.sin = d.route("signin", {"account_id": account, "public_key": pk, "nonce": ch["nonce"],
                                      "signature": nep413_sign(sk, ch, d.recipient)}, address)
        self.sid = self.sin["signin"]

    def env(self, op, payload, at=None, key=None):
        text = json.dumps(dict(payload, _n=b64url(os.urandom(12))))   # as identity.js does: no two envelopes alike
        at = str(at if at is not None else int(self.d.clock() * 1000))
        sig = b64url((key or self.key).sign(identity.envelope_bytes(op, self.sid, at, text)))
        return {"op": op, "signin": self.sid, "at": at, "payload": text, "sig": sig}

    def do(self, op, payload, address=None):
        return self.d.route(op, self.env(op, payload), address or self.address)


def premint_nft(*held, presets=5):
    return FakeNft([f"preset-{i}" for i in range(1, presets + 1)], "custody.id-test.testnet", held=list(held))


def inventory():
    nft = FakeNft([f"preset-{i}" for i in range(1, 6)], MIRROR)
    nft.state_extra = {}
    return nft


class Nep413(unittest.TestCase):
    def test_the_hash_is_the_tag_then_the_borsh_payload(self):
        nonce = bytes(range(32))
        want = hashlib.sha256(struct.pack("<I", 2 ** 31 + 413) + struct.pack("<I", 2) + b"hi" + nonce +
                              struct.pack("<I", 3) + b"app" + b"\x00").digest()
        self.assertEqual(identity.nep413_hash("hi", nonce, "app"), want)

    def test_a_signature_verifies_only_for_its_message_nonce_and_recipient(self):
        sk, pk = wallet_key()
        nonce = os.urandom(32)
        sig = base64.b64encode(sk.sign(identity.nep413_hash("m", nonce, "r"))).decode()
        self.assertTrue(identity.verify_nep413(pk, sig, "m", nonce, "r"))
        self.assertFalse(identity.verify_nep413(pk, sig, "m2", nonce, "r"))
        self.assertFalse(identity.verify_nep413(pk, sig, "m", os.urandom(32), "r"))
        self.assertFalse(identity.verify_nep413(pk, sig, "m", nonce, "other"))
        self.assertFalse(identity.verify_nep413(wallet_key()[1], sig, "m", nonce, "r"))


class SignIn(unittest.TestCase):
    def test_a_full_access_key_signs_in_once_per_code_naming_the_page_key_and_a_function_call_key_never(self):
        sk, pk = wallet_key()
        fc_sk, fc_pk = wallet_key()
        d, *_ = desk(premint_nft(("preset-1-00", "preset-1")), inventory(), {PLAYER: {pk}, PLAYER + "#fc": {fc_pk}})
        page = Page(d, sk, pk)
        self.assertIn(page.pub, page.challenge["message"])                  # the wallet signs the page's key
        self.assertEqual((page.sin["account_id"], page.sin["offer"]["kind"]), (PLAYER, "claim"))
        args = {"account_id": PLAYER, "public_key": pk, "nonce": page.challenge["nonce"],
                "signature": nep413_sign(sk, page.challenge, d.recipient)}
        with self.assertRaisesRegex(identity.IdentityError, "used or expired"):
            d.signin(dict(args))                                             # the code is one-use
        key = b64url(Ed25519PrivateKey.generate().public_key().public_bytes_raw())
        ch = d.challenge({"page_key": key})
        with self.assertRaisesRegex(identity.IdentityError, "not a full-access key"):
            d.signin({"account_id": PLAYER, "public_key": fc_pk, "nonce": ch["nonce"],
                      "signature": nep413_sign(fc_sk, ch, d.recipient)})
        ch = d.challenge({"page_key": key})
        with self.assertRaisesRegex(identity.IdentityError, "signature does not match"):
            d.signin({"account_id": PLAYER, "public_key": pk, "nonce": ch["nonce"],
                      "signature": nep413_sign(sk, ch, "https://elsewhere.example")})
        ch = d.challenge({"page_key": key})
        wrong = dict(ch, message=ch["message"].replace(key, page.pub))      # signed for another page's key
        with self.assertRaisesRegex(identity.IdentityError, "signature does not match"):
            d.signin({"account_id": PLAYER, "public_key": pk, "nonce": ch["nonce"],
                      "signature": nep413_sign(sk, wrong, d.recipient)})

    def test_the_sign_in_id_alone_is_no_bearer_every_step_is_signed_by_the_page_key_once(self):
        sk, pk = wallet_key()
        d, *_ = desk(premint_nft(), inventory(), {PLAYER: {pk}})
        page = Page(d, sk, pk)
        thief = Ed25519PrivateKey.generate()
        with self.assertRaisesRegex(identity.IdentityError, "not signed by the page that signed in"):
            d.route("permit", page.env("permit", {"preset": "looter-lob", "sheet": {"name": "Pebble"}}, key=thief))
        env = page.env("permit", {"preset": "looter-lob", "sheet": {"name": "Pebble"}})
        d.route("permit", env)
        with self.assertRaisesRegex(identity.IdentityError, "already used"):
            d.route("permit", env)                                           # a replay is refused
        for variant in (env["sig"] + "==", env["sig"][:-1] + chr(ord(env["sig"][-1]) ^ 1)):   # padding; a spare bit
            with self.assertRaises(identity.IdentityError):
                d.route("permit", dict(env, sig=variant))                     # a re-encoded signature is no new step
        old = page.env("permit", {"preset": "looter-lob", "sheet": {"name": "Pebble"}}, at=int(d.clock() * 1000) - 120_000)
        with self.assertRaisesRegex(identity.IdentityError, "too old"):
            d.route("permit", old)


class ClaimAndMint(unittest.TestCase):
    def test_a_free_claim_moves_a_held_premint_to_the_player_and_files_its_inventory_shadow(self):
        sk, pk = wallet_key()
        nft = FakeNft(["brawler-swing", "hunter-lunge"], "custody.id-test.testnet",
                      held=[("hunter-lunge-01", "hunter-lunge"), ("hunter-lunge-00", "hunter-lunge")])
        inv = inventory()
        state = tempfile.mkdtemp()
        d, idc, invc, _ = desk(nft, inv, {PLAYER: {pk}}, state_dir=state)
        out = Page(d, sk, pk).do("claim", {"preset": "hunter-lunge"})
        tok = out["token_id"]
        self.assertIn(tok, ("hunter-lunge-00", "hunter-lunge-01"))      # any held copy of the chosen option
        self.assertEqual(nft.tokens[tok]["owner"], PLAYER)
        self.assertEqual(idc.calls[0][:3], ("identity_minter", ID_NFT, "claim"))
        shadow = inv.tokens[tok]
        self.assertEqual((shadow["owner"], shadow["preset_id"], shadow["sale_ready"]), (MIRROR, "preset-2", False))
        self.assertEqual(shadow["digest"], identity.shadow_digest(ID_NFT, tok))
        self.assertTrue(out["claim_tx"] and out["shadow_tx"])
        self.assertEqual(d.registered(PLAYER, tok)["account_id"], PLAYER)
        self.assertIn(PLAYER, (Path(state) / "identity-claims.jsonl").read_text())   # recorded on disk

    def test_the_permit_signs_only_the_checked_name_and_the_digest_computed_on_the_host(self):
        sk, pk = wallet_key()
        d, _, _, permit_key = desk(premint_nft(), inventory(), {PLAYER: {pk}})
        page = Page(d, sk, pk)
        self.assertEqual(page.sin["offer"], {"kind": "paid", "held": 0, "cost_yocto": "10000000000000000000000",
                                             "contract_id": ID_NFT})
        sheet = {"name": "Pebble", "voice": "counts shells"}
        out = page.do("permit", {"preset": "looter-lob", "sheet": sheet, "name": "Anything Else",
                                 "persona_digest": "ff" * 32})
        p = out["args"]["permit"]
        self.assertEqual((p["caller"], p["contract_id"], p["network_id"], p["preset_id"], p["name"]),
                         (PLAYER, ID_NFT, "testnet", "preset-4", "Pebble"))     # the page's name and digest are ignored
        self.assertEqual(p["persona_digest"], fake_persona(sheet)[1])
        raw = b"".join(struct.pack(">I", len(p[f].encode())) + p[f].encode() for f in identity.PERMIT_FIELDS)
        permit_key.public_key().verify(base64.urlsafe_b64decode(out["args"]["signature"] + "=="), raw)
        self.assertEqual(out["token_id"], "paid-" + p["nonce"])
        with self.assertRaisesRegex(identity.IdentityError, "can't be minted: name or tag is blocked"):
            page.do("permit", {"preset": "looter-lob", "sheet": {"name": "Rug Pull Scam Fraud Jail"}})
        with self.assertRaisesRegex(identity.IdentityError, "can't be minted: send the trenchie's sheet"):
            page.do("permit", {"preset": "looter-lob", "persona_digest": "ab" * 32, "name": "Pebble"})

    def test_confirm_refuses_a_token_the_account_does_not_own_and_a_sale_ready_inventory_record(self):
        sk, pk = wallet_key()
        nft = premint_nft(("preset-1-00", "preset-1"))
        inv = FakeNft([f"preset-{i}" for i in range(1, 6)], MIRROR, held=[("preset-1-00", "preset-1")])   # sale-ready
        d, *_ = desk(nft, inv, {PLAYER: {pk}})
        page = Page(d, sk, pk)
        with self.assertRaisesRegex(identity.IdentityError, "owned by custody.id-test.testnet"):
            page.do("confirm", {"token_id": "preset-1-00"})
        with self.assertRaisesRegex(identity.IdentityError, "sale-ready on the testnet inventory"):
            page.do("claim", {"preset": "brawler-swing"})
        with self.assertRaisesRegex(identity.IdentityError, "confirm preset-1-00 first"):
            d.registered(PLAYER, "preset-1-00")
        nft.tokens["preset-1-00"]["owner"] = "buyer.testnet"           # sold after a confirm: registration re-reads
        d.confirmed[(PLAYER, "preset-1-00")] = {"account_id": PLAYER}
        with self.assertRaisesRegex(identity.IdentityError, "owned by buyer.testnet now"):
            d.registered(PLAYER, "preset-1-00")


class ConfirmAfterAWalletMint(unittest.TestCase):
    def test_confirm_waits_for_a_mint_that_is_not_final_yet_and_gives_up_after_its_window(self):
        sk, pk = wallet_key()
        nft = premint_nft()
        d, *_ = desk(nft, inventory(), {PLAYER: {pk}})
        page = Page(d, sk, pk)
        naps = []
        tx = "4" * 44

        def nap(s):   # the mint becomes final after the second read
            naps.append(s)
            if len(naps) == 2:
                nft.tokens["paid-h1"] = {"owner": PLAYER, "preset_id": "preset-4", "digest": "ab" * 32, "sale_ready": False}
        d.sleep = nap
        d.permitted["paid-h1"] = (PLAYER, d.clock() + 600)            # a mint this host permitted to this account
        out = page.do("confirm", {"token_id": "paid-h1", "tx": tx})
        self.assertEqual((out["token_id"], out["mint_tx"], out["shadow"], len(naps)), ("paid-h1", tx, "minted", 2))
        nft.tokens["paid-h2"] = dict(nft.tokens["paid-h1"])
        out = page.do("confirm", {"token_id": "paid-h2", "tx": "x\nidentity: forged line"})
        self.assertNotIn("mint_tx", out)                                     # a tx that is not a hash is dropped
        d.sleep = lambda s: None
        d.permitted["paid-never"] = (PLAYER, d.clock() + 600)
        with self.assertRaisesRegex(identity.IdentityError, r"owned by nobody .* \(read for 30 s\)"):
            page.do("confirm", {"token_id": "paid-never"})
        naps.clear()
        d.sleep = naps.append
        with self.assertRaisesRegex(identity.IdentityError, r"owned by nobody on the identity NFT, not by"):
            page.do("confirm", {"token_id": "paid-never"})                   # waited for once, then answered at once
        self.assertEqual(naps, [])
        for _ in range(identity.MAX_LIVE_PERMITS):
            page.do("permit", {"preset": "looter-lob", "sheet": {"name": "Pebble"}})
        with self.assertRaisesRegex(identity.IdentityError, "before asking for another"):
            page.do("permit", {"preset": "looter-lob", "sheet": {"name": "Pebble"}})

    def test_a_confirm_of_a_token_this_host_never_permitted_answers_at_once(self):
        sk, pk = wallet_key()
        d, *_ = desk(premint_nft(), inventory(), {PLAYER: {pk}})
        page = Page(d, sk, pk)
        naps = []
        d.sleep = naps.append
        with self.assertRaisesRegex(identity.IdentityError, r"owned by nobody on the identity NFT, not by"):
            page.do("confirm", {"token_id": "paid-bogus"})
        self.assertEqual(naps, [])                                           # no wait for a token nobody permitted


class FailClosed(unittest.TestCase):
    def test_a_failed_owner_read_refuses_the_claim_and_a_restart_keeps_the_claim_record(self):
        sk, pk = wallet_key()
        nft = premint_nft(("preset-2-00", "preset-2"), ("preset-2-01", "preset-2"))
        state = tempfile.mkdtemp()
        d, idc, *_ = desk(nft, inventory(), {PLAYER: {pk}}, state_dir=state)
        page = Page(d, sk, pk)
        idc.fail_views = ("nft_tokens_for_owner",)
        with self.assertRaisesRegex(identity.IdentityError, "could not read player-one.testnet's trenchies") as e:
            page.do("claim", {"preset": "hunter-lunge"})
        self.assertNotIn("SECRET", str(e.exception))
        self.assertEqual({t["owner"] for t in nft.tokens.values()}, {"custody.id-test.testnet"})
        idc.fail_views = ()
        got = page.do("claim", {"preset": "hunter-lunge"})["token_id"]
        left = ({"preset-2-00", "preset-2-01"} - {got}).pop()
        nft.tokens[got]["owner"] = "elsewhere.testnet"                    # it gave the token away
        d2, *_ = desk(nft, inventory(), {PLAYER: {pk}}, state_dir=state)   # a restart of the host
        with self.assertRaisesRegex(identity.IdentityError, "one per account"):
            Page(d2, sk, pk).do("claim", {"preset": "hunter-lunge"})
        self.assertEqual(nft.tokens[left]["owner"], "custody.id-test.testnet")

    def test_two_claims_at_once_give_one_token(self):
        sk, pk = wallet_key()
        nft = premint_nft(("preset-2-00", "preset-2"), ("preset-3-00", "preset-3"))
        d, idc, *_ = desk(nft, inventory(), {PLAYER: {pk}})
        idc.call_delay = 0.3
        page = Page(d, sk, pk)
        envs = [page.env("claim", {"preset": p}) for p in ("hunter-lunge", "survivor-beam")]
        out = []

        def go(env):
            try:
                out.append(d.route("claim", env)["token_id"])
            except identity.IdentityError as exc:
                out.append(str(exc))
        threads = [threading.Thread(target=go, args=(e,)) for e in envs]
        [t.start() for t in threads]
        [t.join() for t in threads]
        owned = [t for t, v in nft.tokens.items() if v["owner"] == PLAYER]
        self.assertEqual(len(owned), 1, out)
        self.assertEqual(sum("one per account" in o or "still running" in o for o in out), 1, out)


class Limits(unittest.TestCase):
    def test_each_address_and_ipv6_slash_64_is_limited_per_step(self):
        sk, pk = wallet_key()
        d, *_ = desk(premint_nft(), inventory(), {PLAYER: {pk}})
        key = b64url(Ed25519PrivateKey.generate().public_key().public_bytes_raw())
        n, _ = identity.LIMITS["challenge"]
        for i in range(n):   # one /64, a different address each time
            d.route("challenge", {"page_key": key}, address=f"2001:db8:1:2::{i + 1:x}")
        with self.assertRaisesRegex(identity.IdentityError, "too many challenge requests"):
            d.route("challenge", {"page_key": key}, address="2001:db8:1:2:ffff::9")
        d.route("challenge", {"page_key": key}, address="2001:db8:1:3::1")    # another /64 is not affected
        self.assertEqual(identity.address_key("::ffff:203.0.113.7"), "203.0.113.7")

    def test_an_address_holds_a_few_live_codes_and_a_full_desk_refuses_rather_than_evicts(self):
        sk, pk = wallet_key()
        d, *_ = desk(premint_nft(), inventory(), {PLAYER: {pk}})
        key = b64url(Ed25519PrivateKey.generate().public_key().public_bytes_raw())
        first = d.challenge({"page_key": key}, "198.51.100.1")["nonce"]
        for _ in range(identity.PER_ADDRESS_CHALLENGES):
            d.challenge({"page_key": key}, "203.0.113.7")
        self.assertIn(first, d.challenges)                                   # a flood from one address keeps others'
        self.assertEqual(sum(v["address"] == "203.0.113.7" for v in d.challenges.values()), identity.PER_ADDRESS_CHALLENGES)
        saved = identity.MAX_LIVE_CHALLENGES
        identity.MAX_LIVE_CHALLENGES = len(d.challenges)
        self.addCleanup(setattr, identity, "MAX_LIVE_CHALLENGES", saved)
        with self.assertRaisesRegex(identity.IdentityError, "busy"):
            d.challenge({"page_key": key}, "192.0.2.50")
        self.assertIn(first, d.challenges)


class ShadowBudget(unittest.TestCase):
    def test_the_hours_shadow_budget_and_the_inventory_cap_refuse_out_loud(self):
        sk, pk = wallet_key()
        nft = premint_nft()
        inv = inventory()
        d, *_ = desk(nft, inv, {PLAYER: {pk}})
        page = Page(d, sk, pk)
        for i in range(identity.SHADOW_PER_HOUR):
            nft.tokens[f"paid-{i}"] = {"owner": PLAYER, "preset_id": "preset-1", "digest": f"{i:064x}", "sale_ready": False}
            page.do("confirm", {"token_id": f"paid-{i}"})
        nft.tokens["paid-x"] = {"owner": PLAYER, "preset_id": "preset-1", "digest": "e" * 64, "sale_ready": False}
        with self.assertRaisesRegex(identity.IdentityError, "all the new trenchies it can this hour"):
            page.do("confirm", {"token_id": "paid-x"})


class MirrorInventory(unittest.TestCase):
    def test_an_inventory_with_a_mirror_needs_no_shadow_mint(self):
        sk, pk = wallet_key()
        nft = premint_nft()
        inv = inventory()
        base = inv.view

        def view(method, args):
            out = base(method, args)
            return dict(out, mirror=MIRROR) if method == "contract_state" else out
        inv.view = view
        d, idc, invc, _ = desk(nft, inv, {PLAYER: {pk}})
        nft.tokens["paid-m1"] = {"owner": PLAYER, "preset_id": "preset-1", "digest": "c" * 64, "sale_ready": False}
        out = Page(d, sk, pk).do("confirm", {"token_id": "paid-m1"})
        self.assertEqual((out["shadow"], out["shadow_tx"]), ("made by the next batch", None))
        self.assertEqual(invc.calls, [])                                      # no mint_trenchie sent
        self.assertNotIn("paid-m1", inv.tokens)


class InventoryRoom(unittest.TestCase):
    def test_health_watches_the_inventorys_free_balance_and_an_unfunded_row_goes_again(self):
        sk, pk = wallet_key()
        inv = inventory()
        base = inv.view
        inv.view = lambda method, args: dict(base(method, args), mirror=MIRROR) if method == "contract_state" else base(method, args)
        d, idc, invc, _ = desk(premint_nft(), inv, {PLAYER: {pk}})
        storage = 500_000

        class Rpc:
            free_records = 0

            def call(self, method, params):
                assert params["account_id"] == INV_NFT
                free = self.free_records * identity.RECORD_BYTES * 10 ** 19
                return {"amount": str(storage * 10 ** 19 + free), "locked": "0", "storage_usage": storage}
        invc.rpc = Rpc()
        for records, want in ((200, None), (49, "AMBER"), (9, "RED")):
            invc.rpc.free_records = records
            d.check_float()
            self.assertEqual(None if d.alarm is None else d.alarm.split(":")[0], want, (records, d.alarm))
        self.assertTrue(d.health()["inventory_records"].startswith("RED"))
        # the writer: a batch that applied with an unfunded token keeps that token's base and refiles its row
        from near.chain.writer import ChainWriter
        logs = []
        w = type("W", (), {})()
        w.state = {"carry": ["older"]}
        w.log = lambda kind, **f: logs.append((kind, f))
        b = {"batch_id": "b9", "pending_bases": {"paid-x": {"bag": []}, "known": {"bag": []}}}
        out = {"events": [{"event": "apply_rows", "data": [{"created": [], "unfunded": ["paid-x"]}]}]}
        ChainWriter._unfunded(w, b, out)
        self.assertEqual((sorted(b["pending_bases"]), w.state["carry"], b["unfunded"]), (["known"], ["older", "paid-x"], ["paid-x"]))
        self.assertEqual(logs[0][0], "RECORD_UNFUNDED")


class NetworkSwitch(unittest.TestCase):
    def test_one_setting_moves_the_identity_to_mainnet_and_the_writes_stay_on_testnet(self):
        t = settings()
        self.assertEqual((t.identity_network, t.identity_send_urls[0]), ("testnet", "https://rpc.testnet.near.org"))
        m = settings(ident="nft.trenchie-arena.near")
        self.assertEqual(m.identity_network, "mainnet")
        self.assertEqual(m.identity_send_urls, identity.MAINNET_RPC)
        self.assertEqual((m.chain.network, m.chain.nft, m.chain.rpc_urls[0]),
                         ("testnet", INV_NFT, "https://rpc.testnet.near.org"))
        with self.assertRaisesRegex(identity.chaincfg.ConfigError, "not a mainnet account"):
            settings(ident=ID_NFT, extra="TRENCHIE_IDENTITY_NETWORK=mainnet\n")
        with self.assertRaisesRegex(identity.chaincfg.ConfigError, "two contracts"):
            settings(ident=INV_NFT)

    def test_presets_map_by_the_contracts_own_list(self):
        self.assertEqual(identity.contract_preset("survivor-beam", ["brawler-swing", "survivor-beam"], NAMES), "survivor-beam")
        self.assertEqual(identity.contract_preset("survivor-beam", [f"preset-{i}" for i in range(1, 6)], NAMES), "preset-3")
        self.assertEqual(identity.option_of("preset-5", NAMES), "brawler-zap")
        with self.assertRaises(identity.IdentityError):
            identity.contract_preset("survivor-beam", ["preset-1"], NAMES)

    def test_the_keys_file_must_be_owner_only(self):
        tmp = Path(tempfile.mkdtemp()) / "keys.json"
        k = near_tx.Key.generate("operator.x.testnet")
        row = {"account_id": k.account_id, "public_key": k.public_key,
               "private_key": "ed25519:" + near_tx.b58encode(k._sk.private_bytes_raw() + k.public_bytes)}
        seed = base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")
        tmp.write_text(json.dumps({**{r: row for r in identity.ROLES}, "permit": {"seed_b64url": seed}}))
        os.chmod(tmp, 0o644)
        with self.assertRaisesRegex(identity.chaincfg.ConfigError, "readable by others"):
            identity.load_keys(tmp)
        os.chmod(tmp, 0o600)
        self.assertEqual(identity.load_keys(tmp)["operator"].account_id, "operator.x.testnet")


PREMINT_SHEET = ROOT / "near" / "web" / "snapin" / "premint" / "pike-pennywhistle.json"


class HostedRoom(unittest.TestCase):
    """hosted_live.install on a real DevRoom served by snap_local.serve: off-loop identity work, the host's own persona
    check, signed tickets, a reply for every failure."""

    def setUp(self):
        import snap_local
        from near.chain import hosted_live
        self.snap_local, self.hosted_live = snap_local, hosted_live
        saved = (snap_local.make_contexts, snap_local.player_token, snap_local.DevHouse.binding, snap_local.DevRoom,
                 snap_local.MODE_NOTE, snap_local.server.Arena, snap_local.DevRoom.health)
        self.addCleanup(lambda: (setattr(snap_local, "make_contexts", saved[0]), setattr(snap_local, "player_token", saved[1]),
                                 setattr(snap_local.DevHouse, "binding", saved[2]), setattr(snap_local, "DevRoom", saved[3]),
                                 setattr(snap_local, "MODE_NOTE", saved[4]), setattr(snap_local.server, "Arena", saved[5]),
                                 setattr(saved[3], "health", saved[6])))
        block = Path(tempfile.mkdtemp()) / "blocklist.json"
        block.write_text(json.dumps({"names": ["Realname Person"], "handles": [], "slurs": []}))
        old = os.environ.get("TRENCHIE_BLOCKLIST")
        os.environ["TRENCHIE_BLOCKLIST"] = str(block)
        self.addCleanup(lambda: os.environ.pop("TRENCHIE_BLOCKLIST") if old is None else os.environ.__setitem__("TRENCHIE_BLOCKLIST", old))
        self.sk, self.pk = wallet_key()
        self.nft = premint_nft(("preset-2-00", "preset-2"))
        self.d, self.idc, *_ = desk(self.nft, inventory(), {PLAYER: {self.pk}})
        self.d.check_persona = None                        # the room's own check is installed

        class NoChain:     # a writer stand-in: seeds without a chain; owner reads are the desk's
            def claim_seeds(self, arena): return [11, 12, 13, 14, 15]
            def take_seeds(self, arena): return []
            def sealed(self, *a, **k): pass
            def owner_ok(self, b): return True
            def life_ended(self, t): pass
            def health(self): return {}
        self.room_cls = hosted_live.install(self.d.s, NoChain(), self.d)
        self.port = free_port()
        self.room = self.room_cls(self.port, tempfile.mkdtemp())
        self.loop = asyncio.new_event_loop()
        ready = threading.Event()
        self.thread = threading.Thread(target=lambda: self.loop.run_until_complete(
            snap_local.serve(self.room, ready=lambda port: ready.set())), daemon=True)
        self.thread.start()
        self.assertTrue(ready.wait(20))

    def tearDown(self):
        self.room.stop = True
        self.thread.join(10)

    def post(self, path, body, timeout=40):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        conn.request("POST", path, json.dumps(body).encode(), {"Content-Type": "application/json", "Host": f"127.0.0.1:{self.port}"})
        r = conn.getresponse()
        data = json.loads(r.read() or b"{}")
        conn.close()
        return r.status, data

    def page(self):
        page = Page.__new__(Page)
        page.d, page.key, page.address = self.d, Ed25519PrivateKey.generate(), "127.0.0.1"
        page.pub = b64url(page.key.public_key().public_bytes_raw())
        _, ch = self.post("/dev/identity", {"op": "challenge", "page_key": page.pub})
        st, page.sin = self.post("/dev/identity", {"op": "signin", "account_id": PLAYER, "public_key": self.pk,
                                                   "nonce": ch["nonce"], "signature": nep413_sign(self.sk, ch, self.d.recipient)})
        self.assertEqual(st, 200, page.sin)
        page.sid = page.sin["signin"]
        return page

    def test_the_arena_keeps_ticking_while_a_slow_identity_call_runs(self):
        self.idc.delay = 3.0
        tick0 = self.room.round.arena.sim.state["tick"]
        t0 = time.monotonic()
        key = b64url(Ed25519PrivateKey.generate().public_key().public_bytes_raw())
        _, ch = self.post("/dev/identity", {"op": "challenge", "page_key": key})
        status, out = self.post("/dev/identity", {"op": "signin", "account_id": PLAYER, "public_key": self.pk, "nonce": ch["nonce"],
                                                  "signature": nep413_sign(self.sk, ch, self.d.recipient)})
        took = time.monotonic() - t0
        ticks = self.room.round.arena.sim.state["tick"] - tick0
        self.assertEqual(status, 200, out)
        self.assertGreaterEqual(took, 3.0)
        self.assertGreaterEqual(ticks, int(took * 20 * 0.8), f"{ticks} ticks in {took:.2f} s")   # 20 Hz, a 20% margin

    def test_a_challenge_answers_within_a_second_while_slow_steps_fill_the_pool(self):
        pages = [self.page() for _ in range(2)]
        self.idc.delay = 3.0                                                 # every identity read now takes 3 s
        results = []
        threads = [threading.Thread(target=lambda p=p: results.append(self.post("/dev/identity", p.env("confirm", {"token_id": "paid-x"}))))
                   for p in pages]
        [t.start() for t in threads]
        time.sleep(0.3)
        st, out = self.post("/dev/identity", pages[0].env("confirm", {"token_id": "paid-y"}))
        self.assertEqual(st, 400)                                            # a third step from one address waits its turn
        self.assertRegex(out["error"], "steps running|still running")
        t0 = time.monotonic()
        key = b64url(Ed25519PrivateKey.generate().public_key().public_bytes_raw())
        st, out = self.post("/dev/identity", {"op": "challenge", "page_key": key})
        self.assertEqual(st, 200, out)
        self.assertLess(time.monotonic() - t0, 1.0)
        [t.join() for t in threads]

    def page_for(self, account, sk, pk):
        page = Page.__new__(Page)
        page.d, page.key, page.address = self.d, Ed25519PrivateKey.generate(), "127.0.0.1"
        page.pub = b64url(page.key.public_key().public_bytes_raw())
        _, ch = self.post("/dev/identity", {"op": "challenge", "page_key": page.pub})
        st, page.sin = self.post("/dev/identity", {"op": "signin", "account_id": account, "public_key": pk,
                                                   "nonce": ch["nonce"], "signature": nep413_sign(sk, ch, self.d.recipient)})
        self.assertEqual(st, 200, page.sin)
        page.sid = page.sin["signin"]
        return page

    def test_an_open_agent_session_rejoins_after_a_registration_restarts_the_round(self):
        """End to end on a chain host: a wallet's page claims a trenchie and makes an agent-door code; `snap.py live`
        joins on that token; a second wallet's registration restarts the round; the live session signs its rejoin, the
        chain route passes it to the room (not the desk), and the same token is in the new round's engine within 5 s."""
        import subprocess
        from unittest.mock import patch
        sl = self.snap_local
        sheets = {o: json.loads((PREMINT_SHEET.parent / f).read_text()) for o, f in
                  (("hunter-lunge", "pike-pennywhistle.json"), ("survivor-beam", "lantern-lou.json"))}
        self.nft.tokens["preset-3-00"] = {"owner": "custody.id-test.testnet", "preset_id": "preset-3",
                                          "digest": sl.sheet_digest(sheets["survivor-beam"]), "sale_ready": True}
        self.nft.tokens["preset-2-00"]["digest"] = sl.sheet_digest(sheets["hunter-lunge"])
        page = self.page()
        st, out = self.post("/dev/identity", page.env("claim", {"preset": "hunter-lunge"}))
        self.assertEqual((st, out.get("token_id")), (200, "preset-2-00"), out)
        st, code = self.post("/snap/code", page.env("code", {"agent": "claude-code", "name": "Pike", "preset": "hunter-lunge",
                                                              "sheet": sheets["hunter-lunge"], "nft_token_id": "preset-2-00"}))
        self.assertEqual(st, 200, code)
        fifo = Path(tempfile.mkdtemp()) / "orders.fifo"
        live = subprocess.Popen([sys.executable, "-I", str(ROOT / "near" / "arena" / "snap.py"), "--url", f"http://127.0.0.1:{self.port}",
                                 "live", "--code", code["code"], "--preset", "hunter-lunge", "--accept-terms", "1",
                                 "--fifo", str(fifo), "--seconds", "90"],
                                cwd=fifo.parent, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        def end_live():
            if live.poll() is None:
                live.kill()
            live.communicate(timeout=20)
        self.addCleanup(end_live)
        events = []

        def until(kind, seconds=60):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                line = live.stdout.readline()
                if not line:
                    self.fail("live ended: " + live.stderr.read()[-2000:] + str(events[-3:]))
                events.append(json.loads(line))
                if events[-1]["kind"] in (kind, "refusal"):
                    return events[-1]
            self.fail(f"no {kind} within {seconds} s: {events[-3:]}")
        ready = until("session_ready")
        self.assertEqual(ready.get("fighter_id"), "preset-2-00", ready)
        self.assertEqual(until("life_start")["kind"], "life_start")
        # a second wallet registers its own trenchie; the host's restart path runs as it does for a fresh chain
        # registration (the guard that keeps a round with a joiner in it is set aside for this one registration)
        sk2, pk2 = wallet_key()
        self.idc.full_access["player-two.testnet"] = {pk2}
        page2 = self.page_for("player-two.testnet", sk2, pk2)
        st, out = self.post("/dev/identity", page2.env("claim", {"preset": "survivor-beam"}))
        self.assertEqual((st, out.get("token_id")), (200, "preset-3-00"), out)
        session = b64url(Ed25519PrivateKey.generate().public_key().public_bytes_raw())
        signed = {"nft_token_id": "preset-3-00", "session_public_key": session, "name": "Lou", "preset": "survivor-beam"}
        old_round = self.room.round
        old_round.ever_dev = False
        with patch.object(sl.Round, "dev_members", lambda round_: []):
            st, out = self.post("/dev/identity", {"name": "Lou", "preset": "survivor-beam", "public_key": session,
                                                  "nft_token_id": "preset-3-00", "sheet": sheets["survivor-beam"],
                                                  "ticket": page2.env("register", signed)})
        self.assertEqual(st, 200, out)
        restarted = time.monotonic()
        self.assertIsNot(self.room.round, old_round, "the registration restarted the round")
        rejoined = until("rejoined", 10)
        self.assertEqual((rejoined["kind"], rejoined.get("fighter_id")), ("rejoined", "preset-2-00"), rejoined)
        while "preset-2-00" not in self.room.round.arena.members:
            self.assertLess(time.monotonic() - restarted, 5, "the same token is back in the new round within 5 s")
            time.sleep(0.05)
        self.assertLess(time.monotonic() - restarted, 5)

    def test_a_rejoin_goes_to_the_room_not_the_desk_and_is_limited(self):
        seen = []
        room_route = type(self.room).__mro__[1].route

        def spy(room, method, target, body, ip, admin=""):
            if json.loads(body or b"{}").get("op") == "rejoin":
                seen.append((method, target))
                return 200, {"rejoined": True}
            return room_route(room, method, target, body, ip, admin)
        type(self.room).__mro__[1].route = spy
        self.addCleanup(setattr, type(self.room).__mro__[1], "route", room_route)
        desk_calls = []
        desk_route = self.d.route
        self.d.route = lambda op, args, address="": (desk_calls.append(op), desk_route(op, args, address))[1]
        key = b64url(Ed25519PrivateKey.generate().public_key().public_bytes_raw())
        st, out = self.post("/dev/identity", {"op": "rejoin", "public_key": key})
        self.assertEqual((st, out, seen, desk_calls), (200, {"rejoined": True}, [("POST", "/dev/identity")], []))
        for _ in range(identity.LIMITS["rejoin"][0] - 1):
            self.post("/dev/identity", {"op": "rejoin", "public_key": key})
        st, out = self.post("/dev/identity", {"op": "rejoin", "public_key": key})
        self.assertEqual(st, 400)
        self.assertIn("too many rejoin requests", out["error"])
        st, out = self.post("/dev/identity", {"op": "confirm", "signin": "x"})   # every other op is still the desk's
        self.assertEqual(desk_calls[-1:], ["confirm"])

    def test_a_guarded_name_and_an_unchecked_digest_get_no_permit_and_a_checked_sheet_does(self):
        page = self.page()
        sheet = json.loads(PREMINT_SHEET.read_text())
        bad = json.loads(json.dumps(sheet))
        bad["game"]["name"] = "Rug Pull Scam Fraud Jail"
        st, out = self.post("/dev/identity", page.env("permit", {"preset": "hunter-lunge", "sheet": bad}))
        self.assertEqual(st, 400)
        self.assertIn("can't be minted", out["error"])
        house = json.loads(json.dumps(sheet))
        house["game"]["name"] = self.room.guard_names[0]
        st, out = self.post("/dev/identity", page.env("permit", {"preset": "hunter-lunge", "sheet": house}))
        self.assertEqual(st, 400)
        st, out = self.post("/dev/identity", page.env("permit", {"preset": "hunter-lunge", "persona_digest": "ab" * 32, "name": "Pike"}))
        self.assertEqual(st, 400)
        self.assertIn("send the trenchie's sheet", out["error"])
        st, out = self.post("/dev/identity", page.env("permit", {"preset": "hunter-lunge", "sheet": sheet}))
        self.assertEqual(st, 200, out)
        self.assertEqual((out["args"]["permit"]["name"], out["args"]["permit"]["persona_digest"]),
                         (sheet["game"]["name"], self.snap_local.sheet_digest(sheet)))

    def test_an_rpc_failure_answers_503_with_no_url_and_registration_needs_a_ticket_and_the_tokens_persona(self):
        page = self.page()
        self.idc.fail_views = ("contract_state",)
        st, out = self.post("/dev/identity", page.env("permit", {"preset": "hunter-lunge",
                                                                 "sheet": json.loads(PREMINT_SHEET.read_text())}))
        self.assertIn(st, (400, 503))
        self.assertNotIn("SECRET", json.dumps(out))
        self.assertNotIn("http", json.dumps(out))
        self.idc.fail_views = ()
        st, out = self.post("/dev/identity", page.env("claim", {"preset": "hunter-lunge"}))
        self.assertEqual((st, out.get("token_id")), (200, "preset-2-00"), out)
        session = b64url(Ed25519PrivateKey.generate().public_key().public_bytes_raw())
        premint = json.loads(PREMINT_SHEET.read_text())
        self.nft.tokens["preset-2-00"]["digest"] = self.snap_local.sheet_digest(premint)   # the token's persona
        self.d.confirmed[(PLAYER, "preset-2-00")]["persona_digest"] = self.snap_local.sheet_digest(premint)
        body = {"name": "Pike", "preset": "hunter-lunge", "public_key": session, "nft_token_id": "preset-2-00", "sheet": premint}
        st, out = self.post("/dev/identity", dict(body, signin=page.sid))           # a sign-in id is no bearer
        self.assertEqual(st, 400)
        own = json.loads(json.dumps(premint))
        own["game"]["voice"] = "a different persona under the same token"
        signed = {"nft_token_id": "preset-2-00", "session_public_key": session, "name": "Pike", "preset": "hunter-lunge"}
        thief = b64url(Ed25519PrivateKey.generate().public_key().public_bytes_raw())
        st, out = self.post("/dev/identity", dict(body, public_key=thief, ticket=page.env("register", signed)))
        self.assertEqual(st, 400)                                            # a seen ticket can't seat another key
        self.assertIn("the ticket names another public key", out["error"])
        st, out = self.post("/dev/identity", dict(body, sheet=own, ticket=page.env("register", signed)))
        self.assertEqual(st, 400)
        self.assertIn("not preset-2-00's persona", out["error"])
        st, out = self.post("/dev/identity", dict(body, ticket=page.env("register", signed)))
        self.assertEqual(st, 200, out)
        self.assertEqual((out["label"], out["nft_token_id"], out["account_id"]), ("TESTNET", "preset-2-00", PLAYER))
        self.assertTrue(self.snap_local.player_token("preset-2-00"))
        self.assertIn("CHAIN MODE", self.room.health()["claims"])

    def test_a_rejoin_reply_on_a_chain_host_names_the_network_and_a_dev_one_stays_dev(self):
        import snap
        page = self.page()
        st, out = self.post("/dev/identity", page.env("claim", {"preset": "hunter-lunge"}))
        self.assertEqual(st, 200, out)
        premint = json.loads(PREMINT_SHEET.read_text())
        self.nft.tokens["preset-2-00"]["digest"] = self.snap_local.sheet_digest(premint)
        self.d.confirmed[(PLAYER, "preset-2-00")]["persona_digest"] = self.snap_local.sheet_digest(premint)
        sk = Ed25519PrivateKey.generate()
        session = b64url(sk.public_key().public_bytes_raw())
        signed = {"nft_token_id": "preset-2-00", "session_public_key": session, "name": "Pike", "preset": "hunter-lunge"}
        st, out = self.post("/dev/identity", {"name": "Pike", "preset": "hunter-lunge", "public_key": session, "nft_token_id": "preset-2-00",
                                              "sheet": premint, "ticket": page.env("register", signed)})
        self.assertEqual((st, out["label"]), (200, "TESTNET"), out)
        at = int(time.time() * 1000)
        rnd = self.room.round_index
        proof = {"op": "rejoin", "public_key": session, "round": rnd, "at": at,
                 "sig": b64url(sk.sign(snap.rejoin_message(rnd, session, at)))}
        st, out = self.post("/dev/identity", proof)
        self.assertEqual((st, out.get("label"), out.get("nft_token_id")), (200, "TESTNET", "preset-2-00"), out)
        # a DEV identity on a DEV host keeps "DEV" (the base room's reply, untouched by chain mode)
        dev = self.snap_local.DevRoom.__mro__[1](free_port(), tempfile.mkdtemp())
        dev_key = b64url(Ed25519PrivateKey.generate().public_key().public_bytes_raw())
        dev.create_identity("Devvy", "hunter", dev_key)
        self.assertEqual(dev.identity_reply(dev.by_key[dev_key])["label"], "DEV")

    def test_a_token_id_players_panel_log_and_receipts_are_kept_like_a_dev_players(self):
        """Board 1's panel log: a chain-host player is seated under its token id, not a dev- id."""
        page = self.page()
        st, out = self.post("/dev/identity", page.env("claim", {"preset": "hunter-lunge"}))
        self.assertEqual((st, out.get("token_id")), (200, "preset-2-00"), out)
        premint = json.loads(PREMINT_SHEET.read_text())
        self.nft.tokens["preset-2-00"]["digest"] = self.snap_local.sheet_digest(premint)
        self.d.confirmed[(PLAYER, "preset-2-00")]["persona_digest"] = self.snap_local.sheet_digest(premint)
        session = b64url(Ed25519PrivateKey.generate().public_key().public_bytes_raw())
        signed = {"nft_token_id": "preset-2-00", "session_public_key": session, "name": "Pike", "preset": "hunter-lunge"}
        st, out = self.post("/dev/identity", {"name": "Pike", "preset": "hunter-lunge", "public_key": session,
                                              "nft_token_id": "preset-2-00", "sheet": premint, "ticket": page.env("register", signed)})
        self.assertEqual(st, 200, out)
        self.assertTrue(self.snap_local.player_token("preset-2-00"))
        self.room.fighter_event("preset-2-00", "joined", "Snapped in. Life 1.")
        self.room.receipt_seen({"nft_token_id": "preset-2-00"}, {"kind": "behaviour", "sequence": "7"},
                               {"status": "applied", "summary": "New behaviour recorded: stance flee", "applies_in_ms": 100})
        log = self.room.fighter_logs.get("preset-2-00", [])
        self.assertEqual([row["kind"] for row in log], ["joined", "order"])
        self.assertEqual(log[1]["receipt"]["summary"], "New behaviour recorded: stance flee")
        self.room.fighter_event("avichad", "joined", "a house fighter keeps no panel log")
        self.assertNotIn("avichad", self.room.fighter_logs)


def free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


if __name__ == "__main__":
    unittest.main()
