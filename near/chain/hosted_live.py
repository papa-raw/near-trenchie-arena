#!/usr/bin/env -S python3 -I
"""The hosted arena with the chain on: wallet sign-in, a trenchie on the identity NFT, results and gear on testnet.

    python3 -I near/chain/hosted_live.py --chain testnet [every snap_local.py argument: --port, --bind,
                                         --public-origin, --state-dir, --house, --budget, --data-dir]

Settings come from TRENCHIE_CHAIN_ENV (ids and URLs only, KEY=VALUE; near/chain/identity.py HostedSettings) and the
keys from TRENCHIE_CHAIN_KEYS (owner-only JSON outside the repo: operator, resolver, identity_minter, inventory_minter,
permit). Both files must exist; nothing here falls back to DEV. Without --chain this script refuses: plain DEV is
near/arena/snap_local.py, unchanged.

What it adds to snap_local's DEV arena (snap_local itself is used as it is, as near/chain/dev_live.py does):
  * the chain writer (near/chain/writer.py): seeds committed on the testnet arena before any segment opens, the
    hourly batches of results and gear filed on the testnet inventory under each token id, the stake resolver;
  * every binding names the identity NFT, so every life of a player waits for an owner read on that NFT (the writer's
    owner_ok) and a sale moves the trenchie; the host's house account and fixed roster are admitted without one
    (TRENCHIE_HOUSE_ON_IDENTITY=on makes the house wait for its own identity tokens too, as the rehearsals did);
  * POST /dev/identity with "op" runs the identity desk (challenge, signin, claim, permit, confirm); without "op" it
    registers a fighter only for a signed-in account and a token it owns, re-read at that moment;
  * /dev/health says CHAIN MODE with the networks and contracts, never DEV's "no wallet, chain or NFT".
"""

import argparse
import asyncio
import concurrent.futures
import contextlib
import io
import json
import os
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "near" / "arena")]

import snap_local  # noqa: E402  (near/arena)
from near.chain import dev_live, identity, rpc as rpclib, sender as senders  # noqa: E402
from near.chain.writer import ChainWriter, G0_OPTIONS  # noqa: E402
import presets as battle_options  # noqa: E402  (near/arena)


def chain_parts(env_path, keys_path, data_dir, *, g0="C", overrides=None, log=None):
    """The writer and the desk from the two files. Raises ConfigError on anything missing or unsafe."""
    settings = identity.HostedSettings.from_env_file(env_path)
    keys = identity.load_keys(keys_path)
    cfg = settings.chain
    snd = senders.RpcSender(cfg.rpc(), {"operator": keys["operator"], "resolver": keys["resolver"]})
    id_read = rpclib.Rpc(settings.identity_send_urls, read_urls=settings.identity_send_urls)
    opts = dict(G0_OPTIONS[g0], **(overrides or {}))
    writer = ChainWriter(snd, cfg, Path(data_dir) / "chain", identity=id_read, **opts)
    desk = identity.build(settings, keys, recipient="", names=battle_options.NAMES, log=log,
                          state_dir=Path(data_dir) / "chain")
    return settings, keys, writer, desk


def install(settings, writer, desk, *, house_on_identity=False):
    """Install chain contexts, player ownership checks, house admission and the hosted room class."""
    cfg = settings.chain
    dev_live.attach(writer)
    make = snap_local.make_contexts

    def contexts(*a, **k):   # every player binding names the identity NFT: every life waits for its owner read
        control, result = make(*a, **k)
        for c in (control, result):
            c["contract_ids"] = dict(c["contract_ids"], nft=cfg.identity_nft)
        return control, result
    snap_local.make_contexts = contexts

    player_set = set()
    dev_player = snap_local.player_token
    snap_local.player_token = lambda name: dev_player(name) or name in player_set

    if not house_on_identity:
        chain_owner_ok = writer.owner_ok

        def owner_ok(binding: dict) -> bool:
            # Both house runtimes use the arena's context: reserve_life requires an exact match.
            # Only the host's account AND fixed house roster bypass identity ownership; players still read mainnet.
            if (binding.get("account_id") == snap_local.HOUSE_ACCOUNT
                    and binding.get("nft_token_id") in snap_local.RULES["house"]):
                return True
            return chain_owner_ok(binding)
        writer.owner_ok = owner_ok

    base = snap_local.DevRoom
    note = (f"CHAIN MODE: trenchies on {cfg.identity_nft} ({settings.identity_network}); results and gear filed on "
            f"{cfg.nft} (testnet) by {cfg.arena}.")
    snap_local.MODE_NOTE = note

    class HostedRoom(base):
        chain_players = player_set

        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.desk = desk
            desk.recipient = self.public_origin or f"http://127.0.0.1:{self.port}"
            if desk.check_persona is None:
                desk.check_persona = self.check_persona
            self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="identity")
            self.inflight = 0
            self.per_address = {}
            self.browser_rejoins = set()

        def check_persona(self, sheet):
            """The host's own check of the persona a permit names (CLAUDE.md names rule): the sheet passes the
            persona checker and the name guard with the block list loaded (never unchecked), and the name is no house
            trenchie's. Answers (the checked name, the digest computed here)."""
            if not isinstance(sheet, dict):
                raise ValueError("send the Trenchie's sheet; the host checks it and computes its digest")
            persona = snap_local.check_sheet(sheet)
            if not persona.get("nameChecked"):
                raise ValueError("the host's name list is missing, so it signs no mint (guard list missing)")
            if persona["name"].strip().lower() in {n.lower() for n in self.guard_names}:
                raise ValueError("that name belongs to a house Trenchie; choose an original one")
            return persona["name"], snap_local.sheet_digest(sheet)

        async def off_loop(self, fn, *a, address=None):
            """Blocking identity work (RPC, FINAL sends) on the pool, never on the arena's loop; at most 16 in flight
            and 2 per client address (IPv6: its /64), so one visitor can't hold the pool."""
            who = identity.address_key(address) if address is not None else None
            if self.inflight >= identity.MAX_INFLIGHT:
                raise identity.IdentityError("the arena is busy with sign-ins; try again in a moment")
            if who is not None and self.per_address.get(who, 0) >= identity.PER_ADDRESS_INFLIGHT:
                raise identity.IdentityError("you have steps running; wait for them")
            self.inflight += 1
            if who is not None:
                self.per_address[who] = self.per_address.get(who, 0) + 1
            try:
                return await asyncio.get_running_loop().run_in_executor(self.pool, fn, *a)
            finally:
                self.inflight -= 1
                if who is not None:
                    self.per_address[who] -= 1
                    if not self.per_address[who]:
                        del self.per_address[who]

        def route(self, method, target, body, ip, admin=""):
            path = urlsplit(target).path
            if method == "POST" and path in ("/dev/identity", "/snap/code"):
                return self.chain_route(path, body, ip)     # awaited by snap_local.handle
            reply = super().route(method, target, body, ip, admin)
            if method == "POST" and path == "/room/control/frame":
                _, value = reply
                if isinstance(value, dict) and value.get("type") == "control_ready" and value.get("nft_token_id") in self.browser_rejoins:
                    self.browser_rejoins.discard(value["nft_token_id"])
                    # Its original choices are already known: the authenticated browser needs no ten-second typing hold.
                    self.hold_until = 0.0
            return reply

        async def chain_route(self, path, body, ip):
            try:
                args = json.loads(body or b"{}")
                if not isinstance(args, dict):
                    raise identity.IdentityError("send a JSON object")
                if path == "/snap/code":
                    return 200, await self.chain_code(args, ip)
                if args.get("op") == "challenge":    # no RPC: answered on the loop, never queued behind slow steps
                    return 200, self.desk.route("challenge", args, ip)
                if args.get("op") == "rejoin":
                    # a live session back after a round restart (snap_local's rejoin_identity): it answers with the
                    # identity its session key already holds, registers nothing and restarts no round; the reply is
                    # public room material, seating still needs that key's signatures, and every life still waits for
                    # the owner read. Not the desk's: no wallet step. Limited per address like a registration.
                    self.desk.limit(ip, "rejoin")
                    return super().route("POST", path, body, ip)
                if "op" in args:
                    return 200, await self.off_loop(self.desk.route, str(args["op"]), args, ip, address=ip)
                return 200, await self.register_chain(args, ip)
            except (identity.IdentityError, ValueError) as exc:
                return 400, {"error": identity.clean(exc)}
            except Exception as exc:   # noqa: BLE001  an RPC failure or a bug: a short reply, the type only in the log
                print(f"hosted_live: identity step failed ({type(exc).__name__}); the page was told to retry", flush=True)
                return 503, {"error": "the chain did not answer; try again in a moment"}

        def _confirmed(self, account, token, sheet):
            """Thread: the confirmed token with a fresh owner read, and the sheet bound to the token's persona."""
            mine = self.desk.registered(account, token)
            if not isinstance(sheet, dict):
                raise identity.IdentityError("send the Trenchie's sheet with its token")
            if snap_local.sheet_digest(sheet) != mine["persona_digest"]:
                raise identity.IdentityError(f"that sheet is not {token}'s persona; play the persona the Trenchie was "
                                             "minted with")
            return mine

        async def register_chain(self, args, ip):
            """The browser's join: a ticket signed by the signed-in page key names the token; the agent door's join
            carries a code that holds a confirmed identity instead."""
            code = args.get("code")
            if code is not None:
                self.desk.limit(ip, "register")
                row = self.code_status(code, claim=True, address=ip)
                chain = row.get("chain")
                if chain is None:
                    raise identity.IdentityError("that code was not made by a signed-in wallet")
                mine = await self.off_loop(self._confirmed, chain["account_id"], chain["token_id"], row.get("sheet"), address=ip)
            else:
                ticket = args.get("ticket")
                if not isinstance(ticket, dict):
                    raise identity.IdentityError("sign in with your wallet first: a chain arena seats only owned Trenchies")
                self.desk.limit(ip, "register")
                if str(args.get("nft_token_id", "")) in self.round.arena.members:   # before the ticket is spent: a retry
                    raise identity.IdentityError(f"{args.get('nft_token_id')} is seated right now; `stop` that session first")
                account, payload = self.desk.opened("register", ticket)
                token = str(payload.get("nft_token_id", ""))
                for field in ("nft_token_id", "public_key", "name", "preset"):   # the ticket signs what is seated
                    signed = payload.get("session_public_key" if field == "public_key" else field)
                    if str(signed) != str(args.get(field, "")):
                        raise identity.IdentityError(f"the ticket names another {field.replace('_', ' ')}")
                mine = await self.off_loop(self._confirmed, account, token, args.get("sheet"), address=ip)
            reply = self.seat_chain(args, mine, code, address=ip)
            if code is None and payload.get("rejoin") is True:
                self.browser_rejoins.add(mine["token_id"])
            return reply

        def seat_chain(self, args, mine, code, *, address=None):
            token = mine["token_id"]
            if token in self.round.arena.members:
                raise identity.IdentityError(f"{token} is seated right now; `stop` that session first")
            quiet = io.StringIO()
            with contextlib.redirect_stdout(quiet):   # DEV's "no wallet, chain or NFT" line is not true here
                reply = self.create_identity(str(args.get("name", "")), str(args.get("preset", "")),
                                             str(args.get("public_key", "")), sheet=args.get("sheet"),
                                             code=code, look=args.get("look"), address=address)
            rec = self.identities.pop(reply["nft_token_id"])
            old = self.identities.get(token)
            if old is not None and old is not rec and self.by_key.get(old["session_public_key"]["public_key"]) is old:
                self.by_key.pop(old["session_public_key"]["public_key"], None)
            rec.update(nft_token_id=token, account_id=mine["account_id"], persona_digest=mine["persona_digest"],
                       chain=dict(mine))
            self.identities[token] = rec
            if code is not None:
                self.codes[code]["claimed_by"] = token
            player_set.add(token)
            print(f"hosted_live: fighter registered: {token} owned by {mine['account_id']} on {cfg.identity_nft} "
                  f"({settings.identity_network}); its lives wait for the owner read; results file on {cfg.nft}",
                  flush=True)
            return dict(reply, label=settings.identity_network.upper(), nft_token_id=token,
                        account_id=mine["account_id"], persona_digest=mine["persona_digest"],
                        chain={k: mine.get(k) for k in ("persona_digest", "preset_id", "shadow", "shadow_tx")})

        async def chain_code(self, args, ip):
            """The agent door's code in chain mode: made only by a signed-in page for a token it confirmed."""
            self.desk.limit(ip, "code")
            account, payload = self.desk.opened("code", args)
            token = str(payload.get("nft_token_id", ""))
            mine = await self.off_loop(self._confirmed, account, token, payload.get("sheet"), address=ip)
            out = self.issue_code({k: v for k, v in payload.items() if k != "nft_token_id"})
            self.codes[out["code"]]["chain"] = {"account_id": account, "token_id": token}
            return dict(out, dev=False, nft_token_id=token, account_id=mine["account_id"])

        def identity_reply(self, rec):
            """A chain token's identity reply names its network (as the registration's does), the rejoin's included;
            any other identity keeps the room's own label."""
            out = super().identity_reply(rec)
            if rec.get("nft_token_id") in player_set:
                out["label"] = settings.identity_network.upper()
            return out

        def players(self):
            out = super().players()
            for p in out:
                if p["fighter_id"] in player_set:
                    p["label"] = settings.identity_network.upper()
            return out

        def health(self):
            out = super().health()
            out["claims"] = note + " Every player life waits for an owner read on the identity NFT."
            out["chain_mode"] = dict(settings.public(), players=len(player_set), **self.desk.health())
            out["room_public_key"] = self.room_public  # identifies this host process; a restart makes a fresh key
            return out

    snap_local.DevRoom = HostedRoom
    return HostedRoom


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], add_help=True)
    ap.add_argument("--chain", choices=("testnet",), required=True,
                    help="testnet: the arena writes on testnet; the identity NFT's network is the settings file's")
    ap.add_argument("--chain-env", default=os.environ.get("TRENCHIE_CHAIN_ENV"))
    ap.add_argument("--chain-keys", default=os.environ.get("TRENCHIE_CHAIN_KEYS"))
    ap.add_argument("--g0", choices=sorted(G0_OPTIONS), default="C", help="the G0 batch option (Pat's pick; C by default)")
    ap.add_argument("--batch-segments", type=int, default=None, help="rehearsals only: a shorter period, in segments")
    ap.add_argument("--parts", type=int, default=None, help="rehearsals only: parts a period")
    mine, rest = ap.parse_known_args(argv)
    if not mine.chain_env or not mine.chain_keys:
        raise SystemExit("hosted_live: set TRENCHIE_CHAIN_ENV (settings) and TRENCHIE_CHAIN_KEYS (keys), or pass "
                         "--chain-env and --chain-keys; there is no DEV fallback in chain mode")
    # The writer's state must outlive a restart: under --state-dir when given (hosted), else beside --data-dir.
    probe = argparse.ArgumentParser(add_help=False)
    probe.add_argument("--state-dir")
    probe.add_argument("--data-dir")
    where, _ = probe.parse_known_args(rest)
    chain_home = where.state_dir or where.data_dir
    if not chain_home:
        raise SystemExit("hosted_live: pass --state-dir (hosted) or --data-dir: the chain writer's state must persist")
    try:
        settings, keys, writer, desk = chain_parts(mine.chain_env, mine.chain_keys, chain_home, g0=mine.g0,
                                                   overrides={k: v for k, v in (("batch_segments", mine.batch_segments), ("parts", mine.parts)) if v})
    except (identity.chaincfg.ConfigError, OSError, KeyError, ValueError) as exc:
        raise SystemExit(f"hosted_live: {exc}")
    print("hosted_live: " + json.dumps(settings.public()) + "; keys: " +
          ", ".join(f"{r} {keys[r].account_id} ({keys[r].public_key})" for r in identity.ROLES) +
          "; permit key loaded", flush=True)
    writer.start()
    install(settings, writer, desk, house_on_identity=os.environ.get("TRENCHIE_HOUSE_ON_IDENTITY") == "on")
    writer.run_background(every=10.0)
    writer.run_owner_reader(every=1.0)

    def floats():   # the shadow minter's float and the inventory's cap, for /health (amber, red), every 5 min
        while True:
            desk.check_float()
            if desk.alarm:
                print(f"hosted_live: shadow minter {desk.alarm}", flush=True)
            time.sleep(300)
    threading.Thread(target=floats, name="identity-float", daemon=True).start()
    sys.argv = [str(ROOT / "near" / "arena" / "snap_local.py")] + rest
    try:
        snap_local.main()
    finally:
        writer.close(flush=True)
        print("hosted_live: writer closed; summary " + json.dumps(writer.summary()), flush=True)


if __name__ == "__main__":
    main()
