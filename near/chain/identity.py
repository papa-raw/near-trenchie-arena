"""The hosted arena's identity desk: a wallet signs in, gets its trenchie on the identity NFT, and plays under it.

A Trenchie is an NFT on the identity contract (mainnet `trenchie_nft`, inited
identity-only; until its deploy, a testnet rehearsal of the same code). Fights, gear and records stay on testnet, filed
by the arena's chain writer on the testnet inventory under the identity token's id. Which network the identity lives on
is one setting (TRENCHIE_IDENTITY_NETWORK); nothing else here changes with it.

The steps, each one call on the host (POST /dev/identity with an "op" field; hosted_live.py routes them):
  challenge  a one-use NEP-413 nonce and the exact message and recipient the wallet signs (5 minutes)
  signin     the wallet's signMessage answer: the signature is checked against NEP-413's bytes, and the public key is
             read on the identity network as a FULL-ACCESS key of that account (a function-call key proves nothing).
             Answers a sign-in id, the account's trenchies on the identity NFT, and what a new one costs: a free claim
             of a held premint while any is left, else a paid mint the wallet signs itself
  claim      the host's identity minter key calls `claim(token, to=account, persona_hash)` for a held premint of the
             chosen battle option (the minter key can't attach a deposit and needs none)
  permit     a short-lived mint permit for `paid_mint`, signed by the host's permit key, bound to this account, the
             name, the persona digest, the preset and a fresh nonce; the wallet sends the call with the mint cost
  inspect    read an owned token's immutable persona for the guide; no inventory write
  confirm    the token's owner is read on the identity NFT (it must be the signed-in account), and the testnet
             inventory gets the token's shadow (minted to a mirror account, never traded) if it has none, so the
             writer's batches can file the token's gear and record
Registration (POST /dev/identity with no "op") then seats the fighter under {account, token}; the arena's writer reads
the owner again before every life (writer.owner_ok), so a sale moves the trenchie.

With a state dir, sign-ins, confirmations and short-lived replay markers survive a restart in an atomic,
owner-only identity-sessions.json. Each keeps its original expiry; confirmations last one session (two hours).

Keys never pass through here as text: they come from the keys file (TRENCHIE_CHAIN_KEYS, owner-only, outside the repo).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import stat
import struct
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

import ipaddress

from . import config as chaincfg, near_tx, rpc as rpclib

NEP413_TAG = 2 ** 31 + 413
CHALLENGE_TTL_S = 300
SIGNIN_TTL_S = 2 * 3600       # one play session; a new sign-in is one wallet message
ENVELOPE_SKEW_MS = 60_000      # a signed step is accepted within a minute of its own time, once
PERMIT_DOMAIN, PERMIT_SCHEMA = "game.mint-permit.v1", "1"
PERMIT_FIELDS = ("domain", "schema", "epoch", "network_id", "contract_id", "caller",
                 "name", "persona_digest", "preset_id", "nonce", "issued_at", "expires_at")
PERMIT_TTL_MS = 60_000          # the kit inits permit_ttl_ms at 60000; a permit never asks for longer
CLAIM_TGAS, SHADOW_TGAS, PAID_MINT_TGAS = 30, 30, 50
CONFIRM_WAIT_S, CONFIRM_EVERY_S = 30, 2   # a wallet answers once its mint is sent; a `final` read can trail it by seconds
ROLES = ("operator", "resolver", "identity_minter", "inventory_minter")
MAX_LIVE_CHALLENGES = 5000      # unanswered sign-in codes kept at once; when full, new ones are refused (never evicted)
MAX_LIVE_SIGNINS = 5000
PER_ADDRESS_CHALLENGES = 5      # live codes per client address; a 6th drops that address's oldest, nobody else's
PER_ACCOUNT_SIGNINS = 3         # live sign-ins per account; a 4th drops that account's oldest
SHADOW_PER_HOUR = 20            # inventory records the host mints in any hour (the shadow minter's float and cap)
SHADOW_LOW_CAP, SHADOW_LOW_YOCTO = 20, 10 ** 23   # /health turns amber under 20 mints left or 0.1 NEAR
RECORD_BYTES = 1000             # storage a new inventory record takes with its first bag (940 B measured on testnet)
RECORDS_AMBER, RECORDS_RED = 50, 10
MAX_INFLIGHT = 16
MAX_LIVE_PERMITS = 3            # paid-mint permits an account holds unsent at once
SIGNIN_RPC_PER_MINUTE = 60      # assumed ceiling, not a measured provider tolerance; shared across addresses
SIGNIN_PERMISSION_TTL_S = 60   # only sign-in permission is cached; life owner reads remain fresh
SIGNIN_BAD_KEY_COOL_OFF_S = 600
PER_ADDRESS_INFLIGHT = 2        # identity steps one client address may have running at once
# Per client address, per step: at most N calls in a sliding window of W seconds (the host's own limits; nginx adds its own).
LIMITS = {"challenge": (20, 60), "signin": (10, 60), "claim": (20, 3600), "permit": (10, 3600), "confirm": (30, 60), "inspect": (30, 60),
          "register": (20, 60), "code": (10, 60), "rejoin": (20, 60)}
TX_HASH = __import__("re").compile(r"[1-9A-HJ-NP-Za-km-z]{43,44}")
URL = __import__("re").compile(r"(?:https?|wss?)://\S+")
MAINNET_RPC = ["https://rpc.mainnet.near.org", "https://rpc.mainnet.fastnear.com"]


class IdentityError(ValueError):
    """A refusal the page shows as is: the reason is in the message, never a key or a path."""


# ------------------------------------------------------------------ settings and keys

def _owner_only_outside_repo(path, what) -> Path:
    p = chaincfg._outside_repo(Path(path), what)
    chaincfg._owner_only(p, what)
    return p


def load_keys(path) -> dict:
    """The keys file: {"operator"|"resolver"|"identity_minter"|"inventory_minter": {account_id, public_key,
    private_key}, "permit": {"seed_b64url": 32-byte ed25519 seed}}. Owner-only and outside the repo, or refused."""
    p = _owner_only_outside_repo(path, "keys file")
    data = json.loads(p.read_text())
    missing = [r for r in ROLES if r not in data] + ([] if "permit" in data else ["permit"])
    if missing:
        raise chaincfg.ConfigError(f"keys file {p} is missing {', '.join(missing)}")
    keys = {}
    for role in ROLES:
        k = data[role]
        keys[role] = near_tx.Key(k["account_id"], k["public_key"], k.get("private_key") or k["secret_key"])
    seed = _b64url_decode(data["permit"]["seed_b64url"], 32, "permit seed")
    keys["permit"] = Ed25519PrivateKey.from_private_bytes(seed)
    return keys


@dataclass
class HostedSettings:
    """The writer's ChainConfig plus the identity desk's own settings, from one env file of ids and URLs."""
    chain: chaincfg.ChainConfig
    identity_network: str
    mirror: str
    identity_send_urls: list = field(default_factory=list)

    @classmethod
    def from_env_file(cls, path) -> "HostedSettings":
        env = chaincfg.read_env(path)
        missing = [k for k in ("TRENCHIE_NETWORK", "TRENCHIE_ARENA_ID", "TRENCHIE_MARKET_ID", "TRENCHIE_NFT_ID",
                               "TRENCHIE_IDENTITY_NFT_ID", "TRENCHIE_INVENTORY_MIRROR") if not env.get(k)]
        if missing:
            raise chaincfg.ConfigError(f"settings file is missing {', '.join(missing)}")
        if env["TRENCHIE_NETWORK"] != "testnet":
            raise chaincfg.ConfigError("the arena writes on testnet only (fights, gear, records)")
        ident = env["TRENCHIE_IDENTITY_NFT_ID"]
        net = env.get("TRENCHIE_IDENTITY_NETWORK") or ("mainnet" if ident.endswith(".near") else "testnet")
        if net not in ("testnet", "mainnet"):
            raise chaincfg.ConfigError("TRENCHIE_IDENTITY_NETWORK must be testnet or mainnet")
        if not ident.endswith(".near" if net == "mainnet" else ".testnet"):
            raise chaincfg.ConfigError(f"TRENCHIE_IDENTITY_NFT_ID {ident} is not a {net} account")
        for k in ("TRENCHIE_ARENA_ID", "TRENCHIE_MARKET_ID", "TRENCHIE_NFT_ID", "TRENCHIE_INVENTORY_MIRROR"):
            if not env[k].endswith(".testnet"):
                raise chaincfg.ConfigError(f"{k} must be a .testnet account")
        for k, v in env.items():
            if "coharness" in v.lower():
                raise chaincfg.ConfigError(f"{k}: account ids and URLs carry the game's names only")
        if ident == env["TRENCHIE_NFT_ID"]:
            raise chaincfg.ConfigError("the identity NFT and the testnet inventory must be two contracts")
        split = lambda v: [u.strip() for u in v.split(",") if u.strip()]
        id_urls = split(env["TRENCHIE_IDENTITY_RPC"]) if env.get("TRENCHIE_IDENTITY_RPC") else \
            list(MAINNET_RPC if net == "mainnet" else rpclib.TESTNET_RPC)
        cfg = chaincfg.ChainConfig("testnet", env["TRENCHIE_ARENA_ID"], env["TRENCHIE_MARKET_ID"], env["TRENCHIE_NFT_ID"],
                                   "", "", identity_nft=ident, identity_rpc_urls=id_urls)
        if env.get("TRENCHIE_RPC"):
            cfg.rpc_urls = split(env["TRENCHIE_RPC"])
        if env.get("TRENCHIE_ARCHIVAL"):
            cfg.archival_urls = split(env["TRENCHIE_ARCHIVAL"])
        return cls(cfg, net, env["TRENCHIE_INVENTORY_MIRROR"], identity_send_urls=id_urls)

    def public(self) -> dict:
        return dict(self.chain.public(), identity_network=self.identity_network, inventory_mirror=self.mirror)


# ------------------------------------------------------------------ NEP-413

def _b64url_decode(value: str, length: int, what: str) -> bytes:
    """Canonical base64url only: no padding, no spare bits (one encoding per byte string, so a re-encoded value is
    refused rather than seen as new)."""
    if not isinstance(value, str) or len(value) > 128 or "=" in value:
        raise IdentityError(f"invalid {what}")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except ValueError:
        raise IdentityError(f"invalid {what}") from None
    if len(raw) != length or base64.urlsafe_b64encode(raw).decode().rstrip("=") != value:
        raise IdentityError(f"invalid {what}")
    return raw


def _b64_any(value: str) -> bytes:
    """A wallet's signature: standard or url-safe base64, padded or not."""
    if not isinstance(value, str) or len(value) > 200:
        raise IdentityError("invalid signature")
    v = value.replace("-", "+").replace("_", "/")
    try:
        return base64.b64decode(v + "=" * (-len(v) % 4), validate=True)
    except ValueError:
        raise IdentityError("invalid signature") from None


def _borsh_string(s: str) -> bytes:
    raw = s.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def nep413_hash(message: str, nonce: bytes, recipient: str, callback_url: str | None = None) -> bytes:
    """sha256(borsh(u32 2^31+413) || borsh(Payload{message, nonce[32], recipient, callbackUrl}))."""
    if len(nonce) != 32:
        raise IdentityError("the nonce is 32 bytes")
    payload = _borsh_string(message) + nonce + _borsh_string(recipient) + \
        (b"\x00" if callback_url is None else b"\x01" + _borsh_string(callback_url))
    return hashlib.sha256(struct.pack("<I", NEP413_TAG) + payload).digest()


def verify_nep413(public_key: str, signature: str, message: str, nonce: bytes, recipient: str) -> bool:
    if not isinstance(public_key, str) or not public_key.startswith("ed25519:"):
        return False
    try:
        pub = near_tx.b58decode(public_key.split(":", 1)[1])
        sig = _b64_any(signature)
        Ed25519PublicKey.from_public_bytes(pub).verify(sig, nep413_hash(message, nonce, recipient))
        return True
    except (InvalidSignature, ValueError, IdentityError):
        return False


def permit_bytes(permit: dict) -> bytes:
    """The contract's MintPermit::signing_bytes: each field's UTF-8, u32 big-endian length first, frozen order."""
    if set(permit) != set(PERMIT_FIELDS) or not all(isinstance(permit[f], str) for f in PERMIT_FIELDS):
        raise IdentityError("invalid permit fields")
    return b"".join(struct.pack(">I", len(permit[f].encode())) + permit[f].encode() for f in PERMIT_FIELDS)


def contract_preset(option: str, presets: list, names: tuple) -> str:
    """The identity contract's preset id for a guide battle option: the option's own slug when the contract was inited
    with the battle options (the mainnet kit), else preset-<n> by the options' order (the synthetic testnet rehearsal)."""
    if option in presets:
        return option
    slugs = [n.lower().replace(" ", "-") for n in names]
    if option in slugs and sorted(presets) == [f"preset-{i + 1}" for i in range(len(slugs))]:
        return f"preset-{slugs.index(option) + 1}"
    raise IdentityError(f"battle option {option!r} has no preset on the identity contract ({', '.join(presets)})")


def option_of(preset: str, names: tuple) -> str:
    """The battle option a contract preset stands for: its own slug, or preset-<n> by the options' order."""
    slugs = [n.lower().replace(" ", "-") for n in names]
    if preset in slugs:
        return preset
    if preset.startswith("preset-") and preset[7:].isdigit() and 1 <= int(preset[7:]) <= len(slugs):
        return slugs[int(preset[7:]) - 1]
    raise IdentityError(f"preset {preset!r} stands for no battle option")


def shadow_digest(identity_nft: str, token_id: str) -> str:
    """The inventory shadow's persona digest: derived from the identity token, so it never collides with a persona the
    inventory already holds (the inventory's digest set is its own; the persona lives on the identity NFT)."""
    return hashlib.sha256(f"inventory-shadow|{identity_nft}|{token_id}".encode()).hexdigest()


# ------------------------------------------------------------------ the desk

def address_key(ip: str) -> str:
    """The rate limits' client key: an IPv4 address, or an IPv6 address's /64 (a client owns a whole /64)."""
    try:
        a = ipaddress.ip_address(str(ip))
    except ValueError:
        return str(ip)[:64]
    if a.version == 6:
        if a.ipv4_mapped is not None:
            return str(a.ipv4_mapped)
        return str(ipaddress.ip_network(f"{a}/64", strict=False))
    return str(a)


def clean(text) -> str:
    """A refusal or log text with no URL in it (an RPC URL may carry a key in its query)."""
    return URL.sub("<rpc>", str(text)).replace("\n", " ")[:300]


def envelope_bytes(op: str, sid: str, at: str, payload: str) -> bytes:
    return f"trenchie-desk|{op}|{sid}|{at}|{hashlib.sha256(payload.encode('utf-8')).hexdigest()}".encode()


class SigninReads:
    """A separate read allowance: unauthenticated traffic cannot consume the owner checks' RPC budget."""

    def __init__(self, rpc: rpclib.Rpc, clock: Callable[[], float]) -> None:
        self.rpc, self.clock = rpc, clock
        self.calls: list[float] = []
        self.permissions: dict[tuple[str, str], tuple[float, dict]] = {}
        self.cool_off: dict[str, float] = {}
        self.key_reads: set[str] = set()
        self.lock = threading.Lock()

    def take(self) -> None:
        now = self.clock()
        with self.lock:
            self.calls = [at for at in self.calls if at > now - 60]
            if len(self.calls) >= SIGNIN_RPC_PER_MINUTE:
                raise rpclib.RpcUnreachable("sign-in read limit reached; wait a minute")
            self.calls.append(now)

    def _begin_key_read(self, account: str, public_key: str, address: str) -> dict | None:
        """One read in flight per address prevents a concurrent burst from outrunning its cool-off."""
        now = self.clock()
        with self.lock:
            self.permissions = {key: value for key, value in self.permissions.items() if value[0] > now}
            self.cool_off = {ip: until for ip, until in self.cool_off.items() if until > now}
            cached = self.permissions.get((account, public_key))
            if cached is not None:
                # A cached denial spends no RPC capacity; only an actual read allocates address state.
                return dict(cached[1])
            if address in self.cool_off:
                raise IdentityError('a sign-in key from this address was not full-access; wait ten minutes before another key read')
            if address in self.key_reads:
                raise IdentityError('a sign-in key read from this address is still running; wait for it')
            self.key_reads.add(address)
        return None

    def _remember_key(self, account: str, public_key: str, address: str, permission: object) -> None:
        now = self.clock()
        with self.lock:
            self.permissions[(account, public_key)] = (now + SIGNIN_PERMISSION_TTL_S, {'permission': permission})
            if permission != 'FullAccess':
                self.cool_off[address] = now + SIGNIN_BAD_KEY_COOL_OFF_S

    def access_key(self, account: str, public_key: str, *, address: str = '') -> dict:
        cached = self._begin_key_read(account, public_key, address)
        if cached is not None:
            return cached
        try:
            self.take()
            try:
                result = self.rpc.access_key(account, public_key)
            except rpclib.RpcError as exc:
                if exc.name not in ('UNKNOWN_ACCESS_KEY', 'UNKNOWN_ACCOUNT'):
                    raise
                result = {'permission': None}  # a definitive missing key, never a transport failure
            permission = result.get('permission') if isinstance(result, dict) else None
            self._remember_key(account, public_key, address, permission)
            return {'permission': permission}
        finally:
            with self.lock:
                self.key_reads.discard(address)

    def view(self, account: str, method: str, args: dict | None = None) -> object:
        self.take()
        return self.rpc.view(account, method, args)


class IdentityDesk:
    """The identity steps. `id_rpc` reads the identity network; `id_sender` signs as the identity minter there;
    `inv_sender` signs as the inventory minter on testnet and reads the inventory (near/chain/sender.py's shape).
    `check_persona(sheet) -> (name, digest)` is the host's own persona and name check (hosted_live passes snap_local's
    check_sheet + name guard): a permit names only what it returned. Blocking: run every call off the arena's loop."""

    def __init__(self, settings: HostedSettings, id_rpc, id_sender, inv_sender, permit_key: Ed25519PrivateKey,
                 recipient: str, *, names: tuple, check_persona=None, state_dir=None, clock=time.time, log=None,
                 sleep=time.sleep, signin_rpc=None):
        self.s, self.id_rpc, self.id_sender, self.inv_sender = settings, id_rpc, id_sender, inv_sender
        self.permit_key, self.recipient, self.names = permit_key, recipient, names
        self.check_persona = check_persona
        self.clock, self.sleep = clock, sleep
        self.signin_rpc = SigninReads(signin_rpc or id_rpc, clock)
        self._log = log or (lambda line: print(line, flush=True))
        self.lock = threading.Lock()
        self.challenges = {}       # nonce b64url -> {"expires", "page_key", "address"}
        self.signins = {}          # signin id -> {"account_id", "page_key", "expires"}
        self.confirmed = {}        # (account, token) -> {"at", "expires", "shadow_tx", ...}
        self.journal = []          # every chain step: what, tx, network (the evidence rows)
        self.calls = {}            # (address, step) -> [times] within its window
        self.used = {}             # (signin, signature bytes) -> expires: each signed step is accepted once
        self.permitted = {}        # paid token id -> (account, expires): the only tokens a confirm waits for
        self.busy = set()          # accounts with a step running: one at a time
        self.replies = {}          # (signin, signature text) -> (expires, answer): a resent step gets its first answer
        self.reserving = set()     # accounts with a claim in flight
        self.shadows = []          # times of the host's inventory mints (SHADOW_PER_HOUR)
        self.alarm = None          # the shadow minter's low float or cap, for /health
        self.state_dir = Path(state_dir) if state_dir else None
        self.claims_path = self.state_dir / "identity-claims.jsonl" if self.state_dir else None
        self.sessions_path = self.state_dir / "identity-sessions.json" if self.state_dir else None
        self.claimed = set()       # accounts that took a free claim through this host: on disk, survives a restart
        if self.claims_path and self.claims_path.exists():
            for line in self.claims_path.read_text().splitlines():
                if line.strip():
                    self.claimed.add(json.loads(line)["account_id"])
        self._load_sessions()

    def _session_scope(self) -> dict:
        return {"network": self.s.identity_network, "identity_nft": self.nft,
                "inventory_nft": self.s.chain.nft}

    def _prune_sessions(self) -> None:
        now = self.clock()
        self.signins = {k: v for k, v in self.signins.items() if v["expires"] > now}
        self.confirmed = {k: v for k, v in self.confirmed.items() if v["expires"] > now}
        self.used = {k: v for k, v in self.used.items() if v > now}

    def _load_sessions(self) -> None:
        """Reload trusted, unexpired authorizations; an unusable cache requires fresh sign-ins."""
        if self.sessions_path is None:
            return
        try:
            if self.sessions_path.stat().st_mode & 0o077:
                raise ValueError("permissions")
            data = json.loads(self.sessions_path.read_text())
            if data["version"] != 1 or data["scope"] != self._session_scope():
                raise ValueError("scope")
            self.signins = data["signins"]
            self.confirmed = {(r["account_id"], r["token_id"]): r for r in data["confirmed"]}
            self.used = {(sid, bytes.fromhex(sig)): expires for sid, sig, expires in data["used"]}
            for rec in self.signins.values():
                _b64url_decode(rec["page_key"], 32, "page key")
                if not chaincfg_account_ok(rec["account_id"], self.s.identity_network):
                    raise ValueError("account")
            self._prune_sessions()
            self._save_sessions()
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            # Reject the entire cache, including anything assigned before a later record failed validation.
            # Retain its bytes for the operator; a successful new sign-in replaces it atomically, owner-only.
            self.signins, self.confirmed, self.used = {}, {}, {}
            self.log("session_state_skipped", file="identity-sessions.json", fresh_signin_required=True)

    def _save_sessions(self) -> None:
        """Under self.lock: durable owner-only replacement before acknowledging a signed step.

        Only public page keys and authorization records are stored, never wallet or page private keys.
        Replay markers retain their original short expiry across a process restart too.
        """
        if self.sessions_path is None:
            return
        self._prune_sessions()
        data = {"version": 1, "scope": self._session_scope(), "signins": self.signins,
                "confirmed": list(self.confirmed.values()),
                "used": [[sid, sig.hex(), expires] for (sid, sig), expires in self.used.items()]}
        tmp = None
        try:
            self.sessions_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", dir=self.sessions_path.parent, suffix=".tmp", delete=False) as out:
                tmp = Path(out.name)
                os.fchmod(out.fileno(), 0o600)
                json.dump(data, out)
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp, self.sessions_path)
            directory = os.open(self.sessions_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            raise IdentityError("could not save sign-in state; the arena operator must check its state storage, then retry") from None
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)

    @property
    def nft(self):
        return self.s.chain.identity_nft

    def log(self, kind, **fields):
        row = dict(at=round(self.clock(), 3), kind=kind, **{k: clean(v) if isinstance(v, str) else v for k, v in fields.items()})
        self.journal.append(row)
        self._log("identity: " + kind + " " + " ".join(f"{k}={row[k]}" for k in fields))

    def public(self) -> dict:
        """What the page needs to talk to the wallet and the contract: never a key."""
        return {"network": self.s.identity_network, "identity_nft": self.nft, "inventory_nft": self.s.chain.nft,
                "recipient": self.recipient}

    def health(self) -> dict:
        return {"identity_network": self.s.identity_network, "claims_recorded": len(self.claimed),
                "shadow_minter": self.alarm or "ok", "inventory_records": self.alarm or "ok"}

    # ---- limits
    def limit(self, address: str, step: str) -> None:
        """A sliding-window limit per client address (IPv6: its /64) and step; over it, refused before any work."""
        n, window = LIMITS[step]
        key = address_key(address)
        now = self.clock()
        with self.lock:
            if len(self.calls) > 20000:
                self.calls = {k: [t for t in v if t > now - LIMITS[k[1]][1]] for k, v in self.calls.items()}
                self.calls = {k: v for k, v in self.calls.items() if v}
            seen = [t for t in self.calls.get((key, step), []) if t > now - window]
            if len(seen) >= n:
                left = int(seen[0] + window - now) + 1
                wait = f"{left} seconds" if left < 60 else f"{(left + 59) // 60} minute{'s' if left > 60 else ''}"
                raise IdentityError(f"too many {step} requests from this address; try again in {wait}")
            seen.append(now)
            self.calls[(key, step)] = seen

    # ---- sign-in
    def challenge(self, args: dict, address: str = "") -> dict:
        """A one-use code for the wallet to sign, bound to the page's own key (b64url ed25519 public key)."""
        page_key = str(args.get("page_key", ""))
        _b64url_decode(page_key, 32, "page key")
        nonce = secrets.token_bytes(32)
        key = base64.urlsafe_b64encode(nonce).decode().rstrip("=")
        who = address_key(address)
        now = self.clock()
        with self.lock:
            self.challenges = {k: v for k, v in self.challenges.items() if v["expires"] > now}
            mine = [k for k, v in self.challenges.items() if v["address"] == who]
            while len(mine) >= PER_ADDRESS_CHALLENGES:
                self.challenges.pop(mine.pop(0))
            if len(self.challenges) >= MAX_LIVE_CHALLENGES:
                raise IdentityError("the arena is busy signing people in; try again in a minute")
            self.challenges[key] = {"expires": now + CHALLENGE_TTL_S, "page_key": page_key, "address": who}
        return dict(self.public(), nonce=key, message=self._message(key, page_key), expires_in_s=CHALLENGE_TTL_S)

    def _message(self, nonce_key: str, page_key: str) -> str:
        return (f"Sign in to Trenchie Arena ({self.s.identity_network}). This page's key: {page_key}. "
                f"One-use code {nonce_key[:12]}.")

    def signin(self, args: dict) -> dict:
        account, public_key = str(args.get("account_id", "")), str(args.get("public_key", ""))
        nonce_key = str(args.get("nonce", ""))
        nonce = _b64url_decode(nonce_key, 32, "nonce")
        with self.lock:
            live = self.challenges.pop(nonce_key, None)
        if live is None or live["expires"] <= self.clock():
            raise IdentityError("that sign-in code is used or expired: ask for a new one")
        if not chaincfg_account_ok(account, self.s.identity_network):
            raise IdentityError(f"{account!r} is not a {self.s.identity_network} account")
        if not verify_nep413(public_key, str(args.get("signature", "")), self._message(nonce_key, live["page_key"]),
                             nonce, self.recipient):
            raise IdentityError("the wallet's signature does not match this sign-in code")
        try:
            ak = self.signin_rpc.access_key(account, public_key, address=live['address'])
        except (rpclib.RpcError, rpclib.RpcUnreachable) as exc:
            raise IdentityError(f"could not read {account}'s keys on {self.s.identity_network}; try again "
                                f"({type(exc).__name__})") from None
        if not isinstance(ak, dict) or ak.get("permission") != "FullAccess":
            raise IdentityError(f"that key is not a full-access key of {account} on {self.s.identity_network}")
        sid = secrets.token_urlsafe(24)
        with self.lock:
            now = self.clock()
            self.signins = {k: v for k, v in self.signins.items() if v["expires"] > now}
            same = [k for k, v in self.signins.items() if v["account_id"] == account]
            while len(same) >= PER_ACCOUNT_SIGNINS:
                self.signins.pop(same.pop(0))
            if len(self.signins) >= MAX_LIVE_SIGNINS:
                raise IdentityError("the arena is busy signing people in; try again in a minute")
            self.signins[sid] = {"account_id": account, "page_key": live["page_key"], "expires": now + SIGNIN_TTL_S}
            self._save_sessions()
        self.log("signin", account=account, network=self.s.identity_network)
        return dict(self.public(), signin=sid, account_id=account, trenchies=self.owned(account, strict=False, rpc=self.signin_rpc),
                    offer=self.offer(rpc=self.signin_rpc))

    def opened(self, op: str, env: dict) -> tuple[str, dict]:
        """A signed step: {signin, at, payload (a JSON string), sig}, signed by the page key the wallet named. Answers
        (account, the payload's args). Each envelope is accepted once, within a minute of its own time."""
        sid, at, payload, sig = (str(env.get(k, "")) for k in ("signin", "at", "payload", "sig"))
        rec = self.signins.get(sid)
        now = self.clock()
        if rec is None or rec["expires"] <= now:
            raise IdentityError("sign in with your wallet first (the sign-in expired or is unknown)")
        if not at.isdigit() or abs(int(at) - int(now * 1000)) > ENVELOPE_SKEW_MS:
            raise IdentityError("this step is too old or from the future; send it again")
        try:
            raw_sig = _b64url_decode(sig, 64, "signature")
            Ed25519PublicKey.from_public_bytes(_b64url_decode(rec["page_key"], 32, "page key")).verify(
                raw_sig, envelope_bytes(op, sid, at, payload))
        except (InvalidSignature, IdentityError):
            raise IdentityError("this step is not signed by the page that signed in") from None
        with self.lock:
            self.used = {k: v for k, v in self.used.items() if v > now}
            if (sid, raw_sig) in self.used:
                raise IdentityError("this step was already used; send a new one")
            self.used[(sid, raw_sig)] = now + 2 * ENVELOPE_SKEW_MS / 1000
            self._save_sessions()
        try:
            args = json.loads(payload or "{}")
        except ValueError:
            raise IdentityError("the step's payload is not JSON") from None
        if not isinstance(args, dict):
            raise IdentityError("the step's payload must be an object")
        return rec["account_id"], args

    # ---- reads
    def owned(self, account: str, strict: bool = True, *, rpc=None) -> list:
        """The account's trenchies on the identity NFT. strict: an RPC failure refuses (claims fail closed)."""
        try:
            toks = (rpc or self.id_rpc).view(self.nft, "nft_tokens_for_owner", {"account_id": account, "limit": 20}) or []
        except (rpclib.RpcError, rpclib.RpcUnreachable) as exc:
            if strict:
                raise IdentityError(f"could not read {account}'s Trenchies; try again ({type(exc).__name__})") from None
            return []
        return [{"token_id": t["token_id"], "title": (t.get("metadata") or {}).get("title")} for t in toks]

    def state(self, *, rpc=None) -> dict:
        try:
            return (rpc or self.id_rpc).view(self.nft, "contract_state")
        except (rpclib.RpcError, rpclib.RpcUnreachable) as exc:
            raise IdentityError(f"could not read the identity contract; try again ({type(exc).__name__})") from None

    def view(self, method, args):
        try:
            return self.id_rpc.view(self.nft, method, args)
        except (rpclib.RpcError, rpclib.RpcUnreachable) as exc:
            raise IdentityError(f"could not read the identity contract; try again ({type(exc).__name__})") from None

    def offer(self, *, rpc=None) -> dict:
        st = self.state(rpc=rpc)
        held = int(((st.get("premint") or {}).get("held")) or 0)
        if held > 0:
            return {"kind": "claim", "held": held, "cost_yocto": "0"}
        return {"kind": "paid", "held": 0, "cost_yocto": str(st["mint_cost"]), "contract_id": self.nft}

    def owner(self, token: str) -> str | None:
        try:
            t = self.id_rpc.view(self.nft, "nft_token", {"token_id": token})
        except (rpclib.RpcError, rpclib.RpcUnreachable) as exc:
            raise IdentityError(f"could not read {token}'s owner; try again ({type(exc).__name__})") from None
        return (t or {}).get("owner_id")

    # ---- the free claim
    def claim(self, account: str, args: dict) -> dict:
        """A held premint of the chosen option, to this account. Claims are recorded on disk;
        the account is reserved before sending, so concurrent claims give one token."""
        with self.lock:
            if account in self.reserving:
                raise IdentityError("a claim for this account is still running; wait for it to finish")
            self.reserving.add(account)
        try:
            self.owned(account, strict=True)   # a failed ownership read still refuses; existing tokens do not limit claims
            st = self.state()
            preset = contract_preset(str(args.get("preset", "")), st["presets"], self.names)
            held = self.view("nft_tokens_for_owner", {"account_id": st["custodian"], "limit": 100}) or []
            mine = sorted(t["token_id"] for t in held if t["token_id"].startswith(preset + "-"))
            if not mine:
                raise IdentityError(f"no free {args.get('preset')} is left to claim; a paid mint is the way in")
            token = secrets.choice(mine)   # any held copy: two accounts claiming at once rarely want the same one
            persona = self.view("trenchie", {"token_id": token})
            out = self.id_sender.call("identity_minter", self.nft, "claim",
                                      {"token_id": token, "to": account, "persona_hash": persona["persona_digest"]}, CLAIM_TGAS)
            if out.get("landed") is None:   # outcome unknown: the account's claim stays recorded (fail closed for it)
                self._record_claim(account, token, out.get("tx"))
                self.log("claim_unknown", account=account, token=token, tx=out.get("tx"), failure=out.get("failure"))
                raise IdentityError("the claim's outcome is not known yet; sign in again in a minute to see your Trenchie")
            if not out.get("ok"):
                self.log("claim_failed", account=account, token=token, tx=out.get("tx"), failure=out.get("failure"))
                raise IdentityError(f"the claim was refused: {clean(out.get('failure') or 'no answer')}")
            self._record_claim(account, token, out["tx"])
            self.log("claim", account=account, token=token, tx=out["tx"], network=self.s.identity_network)
        finally:
            with self.lock:
                self.reserving.discard(account)
        conf = self.confirm(account, {"token_id": token})
        return dict(conf, claim_tx=out["tx"])

    def _record_claim(self, account, token, tx):
        with self.lock:
            self.claimed.add(account)
            if self.claims_path:
                self.claims_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.claims_path, "a") as f:
                    f.write(json.dumps({"account_id": account, "token_id": token, "tx": tx, "at": round(self.clock())}) + "\n")

    # ---- the paid mint
    def permit(self, account: str, args: dict) -> dict:
        """A paid_mint permit for the persona the host checked: the name is the checked sheet's, the digest is
        computed here from that sheet. Nothing named by the page alone is signed."""
        if self.check_persona is None:
            raise IdentityError("this host has no persona check, so it signs no permit")
        try:
            name, digest = self.check_persona(args.get("sheet"))
        except ValueError as exc:
            raise IdentityError(f"that Trenchie can't be minted: {clean(exc)}") from None
        st = self.state()
        preset = contract_preset(str(args.get("preset", "")), st["presets"], self.names)
        now_ms = int(self.clock() * 1000)
        permit = {"domain": PERMIT_DOMAIN, "schema": PERMIT_SCHEMA, "epoch": str(st["permit_epoch"]),
                  "network_id": self.s.identity_network, "contract_id": self.nft, "caller": account, "name": name,
                  "persona_digest": digest, "preset_id": preset, "nonce": "h" + secrets.token_hex(12),
                  "issued_at": str(now_ms - 5_000), "expires_at": str(now_ms + PERMIT_TTL_MS - 5_000)}
        sig = base64.urlsafe_b64encode(self.permit_key.sign(permit_bytes(permit))).decode().rstrip("=")
        with self.lock:
            self.permitted = {k: v for k, v in self.permitted.items() if v[1] > self.clock()}
            if sum(1 for v in self.permitted.values() if v[0] == account) >= MAX_LIVE_PERMITS:
                raise IdentityError("send the mints you were already given (or wait a minute) before asking for another")
            self.permitted["paid-" + permit["nonce"]] = (account, self.clock() + PERMIT_TTL_MS / 1000 + CONFIRM_WAIT_S)
        self.log("permit", account=account, nonce=permit["nonce"], preset=preset, digest=digest[:12])
        return {"contract_id": self.nft, "method": "paid_mint", "args": {"permit": permit, "signature": sig},
                "deposit_yocto": str(st["mint_cost"]), "tgas": PAID_MINT_TGAS, "token_id": "paid-" + permit["nonce"],
                "network": self.s.identity_network}

    # ---- confirm and the inventory record
    def inspect(self, account: str, args: dict) -> dict:
        """Read an owned token's immutable persona before the guide offers edits; no inventory write."""
        token = str(args.get("token_id", ""))[:64]
        owner = self.owner(token)
        if owner != account:
            raise IdentityError(f"{token} is owned by {owner or 'nobody'} on the identity NFT, not by {account}")
        persona = self.view("trenchie", {"token_id": token})
        return {"account_id": account, "token_id": token, "persona_digest": persona["persona_digest"],
                "preset_id": persona["preset_id"]}

    def confirm(self, account: str, args: dict) -> dict:
        token = str(args.get("token_id", ""))[:64]
        owner = self.owner(token)
        waited = 0
        with self.lock:   # a permitted mint is waited for once: a second confirm of it answers at once
            mine = self.permitted.pop(token, None)
        expect = mine is not None and mine[0] == account and mine[1] > self.clock()
        while owner is None and expect and waited < CONFIRM_WAIT_S:   # a mint this host permitted, not final yet
            self.sleep(CONFIRM_EVERY_S)
            waited += CONFIRM_EVERY_S
            owner = self.owner(token)
        if owner != account:
            raise IdentityError(f"{token} is owned by {owner or 'nobody'} on the identity NFT, not by {account}"
                                + (f" (read for {waited} s)" if waited else ""))
        persona = self.view("trenchie", {"token_id": token})
        shadow = self.ensure_shadow(token, persona["preset_id"])
        rec = {"account_id": account, "token_id": token, "owner_read": "identity NFT nft_token",
               "persona_digest": persona["persona_digest"], "preset_id": persona["preset_id"], **shadow}
        tx = str(args.get("tx") or "")
        if TX_HASH.fullmatch(tx):
            rec["mint_tx"] = tx
        with self.lock:
            now = self.clock()
            self.confirmed[(account, token)] = dict(rec, at=now, expires=now + SIGNIN_TTL_S)
            self._save_sessions()
        self.log("confirmed", account=account, token=token, network=self.s.identity_network,
                 shadow=shadow.get("shadow"), shadow_tx=shadow.get("shadow_tx"), mint_tx=rec.get("mint_tx"))
        return rec

    def ensure_shadow(self, token: str, identity_preset: str) -> dict:
        """The inventory's record for this token: present and not sale-ready (a sale-ready token's bag can't change,
        so the writer's batch would panic), or minted now to the mirror account, within the hour's budget."""
        inv = self.s.chain.nft
        try:
            have = self.inv_sender.view(inv, "trenchie", {"token_id": token})
        except (rpclib.RpcError, rpclib.RpcUnreachable) as exc:
            raise IdentityError(f"could not read the testnet inventory; try again ({type(exc).__name__})") from None
        if have:
            if have.get("sale_ready"):
                raise IdentityError(f"{token} is sale-ready on the testnet inventory, so its gear can't be filed; "
                                    "the arena refuses it rather than stall every batch")
            return {"shadow": "present", "shadow_tx": None}
        try:
            inv_state = self.inv_sender.view(inv, "contract_state")
        except (rpclib.RpcError, rpclib.RpcUnreachable) as exc:
            raise IdentityError(f"could not read the testnet inventory; try again ({type(exc).__name__})") from None
        if inv_state.get("mirror"):   # nft-apply-rows: the inventory makes the record itself, in the token's first batch
            return {"shadow": "made by the next batch", "shadow_tx": None}
        now = self.clock()
        with self.lock:
            self.shadows = [t for t in self.shadows if t > now - 3600]
            if len(self.shadows) >= SHADOW_PER_HOUR:
                raise IdentityError("the arena has filed all the new Trenchies it can this hour; try again later")
            self.shadows.append(now)
        st = inv_state
        left = int(st.get("mint_cap", 0)) - int(st.get("minted_by_minter", 0))
        if left <= 0:
            self.alarm = "RED: the testnet inventory's mint cap is used up; no new trenchie can be filed"
            raise IdentityError("the arena can't file new Trenchies right now (its inventory is full); the operators "
                                "have been told")
        if left < SHADOW_LOW_CAP:
            self.alarm = f"AMBER: {left} inventory records left"
        preset = identity_preset if identity_preset in st["presets"] else \
            contract_preset(option_of(identity_preset, self.names), st["presets"], self.names)
        out = self.inv_sender.call("inventory_minter", inv, "mint_trenchie",
                                   {"token_id": token, "owner_id": self.s.mirror, "preset_id": preset,
                                    "persona_digest": shadow_digest(self.nft, token)}, SHADOW_TGAS)
        if not (out.get("landed") and out.get("ok")):
            failure = out.get("failure") or "no answer"
            if "token id already minted" in failure:
                return {"shadow": "present", "shadow_tx": None}
            if "Exceeded the account balance" in failure or "allowance" in failure.lower() or "NotEnoughBalance" in failure:
                self.alarm = "RED: the inventory minter is out of gas money"
            self.log("shadow_failed", token=token, tx=out.get("tx"), failure=failure)
            raise IdentityError(f"the inventory record did not land ({clean(failure)[:120]}); the operators have been told")
        self.log("shadow", token=token, inventory=inv, tx=out["tx"])
        return {"shadow": "minted", "shadow_tx": out["tx"]}

    def check_float(self) -> None:
        """Called now and then (hosted_live), for /health: with a mirror, the inventory's free balance in records
        (amber under 50, red under 10); without, the shadow minter's float and the inventory's cap."""
        try:
            st = self.inv_sender.view(self.s.chain.nft, "contract_state")
        except Exception as exc:   # noqa: BLE001 (a read for /health; its failure is itself shown)
            self.alarm = f"AMBER: could not read the inventory ({type(exc).__name__})"
            return
        if st.get("mirror"):   # the inventory makes records itself, from its own balance: watch that balance
            try:
                acct = self.inv_sender.rpc.call("query", {"request_type": "view_account", "finality": "final",
                                                          "account_id": self.s.chain.nft}) or {}
            except Exception as exc:   # noqa: BLE001 (a read for /health; its failure is itself shown)
                self.alarm = f"AMBER: could not read the inventory's balance ({type(exc).__name__})"
                return
            free = int(acct.get("amount", 0)) + int(acct.get("locked", 0)) - int(acct.get("storage_usage", 0)) * 10 ** 19
            records = max(0, free) // (RECORD_BYTES * 10 ** 19)
            self.alarm = (f"RED: room for about {records} new trenchie records on the inventory; top it up" if records < RECORDS_RED
                          else f"AMBER: room for about {records} new trenchie records on the inventory" if records < RECORDS_AMBER
                          else None)
            return
        try:   # no mirror: the host mints each record, so watch the minter's float and the inventory's cap
            bal = int((self.inv_sender.rpc.call("query", {"request_type": "view_account", "finality": "final",
                                                           "account_id": self.inv_sender.account("inventory_minter")}) or {}).get("amount", 0))
        except Exception as exc:   # noqa: BLE001
            self.alarm = f"AMBER: could not read the inventory minter ({type(exc).__name__})"
            return
        left = int(st.get("mint_cap", 0)) - int(st.get("minted_by_minter", 0))
        if left <= 0 or bal < SHADOW_LOW_YOCTO // 10:
            self.alarm = f"RED: {left} inventory records left, minter balance {bal / 1e24:.3f} NEAR"
        elif left < SHADOW_LOW_CAP or bal < SHADOW_LOW_YOCTO:
            self.alarm = f"AMBER: {left} inventory records left, minter balance {bal / 1e24:.3f} NEAR"
        else:
            self.alarm = None

    def registered(self, account: str, token: str) -> dict:
        """For registration: a confirmed token of this account, and a fresh owner read now."""
        if (account, token) not in self.confirmed:
            raise IdentityError(f"confirm {token} first (claim or mint it, then confirm)")
        owner = self.owner(token)
        if owner != account:
            raise IdentityError(f"{token} is owned by {owner or 'nobody'} now, not by {account}")
        rec = self.confirmed[(account, token)]
        if rec.get("expires", 0) <= self.clock():
            raise IdentityError(f"confirm {token} first (the confirmation expired)")
        return rec

    def route(self, op: str, args: dict, address: str = "") -> dict:
        """One public step. Blocking (RPC): the host runs it off its event loop."""
        if op in LIMITS:
            self.limit(address, op)
        if op == "challenge":
            return self.challenge(args, address)
        if op == "signin":
            return self.signin(args)
        if op in ("claim", "permit", "confirm", "inspect"):
            key, now = (str(args.get("signin", "")), str(args.get("sig", ""))), self.clock()
            with self.lock:
                self.replies = {k: v for k, v in self.replies.items() if v[0] > now}
                done = self.replies.get(key)
            if done is not None:   # the page resent a step that already went through: answer as the first time
                return done[1]
            account, payload = self.opened(op, args)
            with self.lock:
                if account in self.busy:
                    raise IdentityError("a step for this account is still running; wait for it")
                self.busy.add(account)
            try:
                out = {"claim": self.claim, "permit": self.permit, "confirm": self.confirm, "inspect": self.inspect}[op](account, payload)
                with self.lock:
                    self.replies[key] = (now + 2 * ENVELOPE_SKEW_MS / 1000, out)
                return out
            finally:
                with self.lock:
                    self.busy.discard(account)
        raise IdentityError(f"unknown op {op!r}; one of challenge, signin, claim, permit, confirm, inspect")


def chaincfg_account_ok(account: str, network: str) -> bool:
    """A named account on that network, or a 64-hex implicit account (a wallet's own)."""
    if not isinstance(account, str) or not 2 <= len(account) <= 64:
        return False
    if len(account) == 64 and all(c in "0123456789abcdef" for c in account):
        return True
    ok = all(c.islower() or c.isdigit() or c in "-_." for c in account)
    return ok and account.endswith("." + ("near" if network == "mainnet" else "testnet"))


def build(settings: HostedSettings, keys: dict, recipient: str, names: tuple, **kw) -> IdentityDesk:
    """The live desk: identity reads and the identity minter on the identity network; the inventory on testnet. Its
    RPC waits are short (15 s, 2 rounds): a page is waiting, and the host runs these off its loop."""
    from . import sender as senders
    id_rpc = rpclib.Rpc(settings.identity_send_urls, read_urls=settings.identity_send_urls, timeout=15, rounds=2)
    # Sign-ins have no fallback or retry amplification: each allowance unit is one wire request. The
    # authenticated owner/claim/permit paths retain their independent read client and fresh checks.
    signin_rpc = rpclib.Rpc(settings.identity_send_urls[:1], timeout=5, rounds=1, attempts=1)
    id_sender = senders.RpcSender(id_rpc, {"identity_minter": keys["identity_minter"]})
    inv_rpc = rpclib.Rpc(settings.chain.rpc_urls, read_urls=settings.chain.rpc_urls, timeout=15, rounds=2)
    inv_sender = senders.RpcSender(inv_rpc, {"inventory_minter": keys["inventory_minter"]})
    return IdentityDesk(settings, id_rpc, id_sender, inv_sender, keys["permit"], recipient, names=names,
                        signin_rpc=signin_rpc, **kw)
