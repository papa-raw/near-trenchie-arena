"""Local snap-in host (DEV): the room, the engine and the spectator socket in one process.

Run:  python3 -B near/arena/snap_local.py [--port 8765]

One loopback port serves three things from the same running arena:
  * the spectator WebSocket the first-look page draws (identical frames to dev_brawl.py),
  * the room's HTTP routes (`/room`, `/room/challenge`, `/room/join`, `/room/observe`, ...), plus a
    local shim for the control socket (`/room/control/open|frame|private`) so a plain HTTP client can
    drive it, and
  * `/dev/*`: DEV identity issue, terms, players, clock.

DEV means what it says. There is no wallet, no chain and no NFT. A joiner generates its own Ed25519 session
key and registers only the public half; the room signs with its own Ed25519 key and a joiner receives only the
room's public key, so a joiner can neither forge a room signature nor read another joiner's key. The copied room
protocol defines only a mainnet context, so its `network_id` field must read "mainnet"; the contract ids are
`dev-nft.local` and `dev-arena.local`, which exist on no chain, and the deployment id is `dev-local-r<round>`.
Every DEV trenchie is `dev-<name>` in the feed, in `/dev/players` and on its card. Loopback only: the host
refuses any Host header but its own, takes POSTs only as application/json, and allows cross-origin reads of
`/dev/players` and `/dev/health` from the first-look page's origin alone. Never expose this port.

One round: a join with no DEV trenchie present starts a fresh arena, so the joiner's life falls inside
segment:0 (the only segment the result reader supports); the round's results stay readable until the next
round starts. The 14 house trenchies fill the ring (six at most) and yield seats at their life boundaries.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import copy
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time
import traceback
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(HERE)]
import codec  # noqa: E402
import dev_brawl  # noqa: E402
from spectator_styles import SpectatorStyles  # noqa: E402
import server  # noqa: E402
import sim  # noqa: E402
from portable_records import EngineRecords  # noqa: E402
from cryptography.exceptions import InvalidSignature  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey  # noqa: E402
from room.policy import canonical_bytes  # noqa: E402
from room.slots import SlotStore  # noqa: E402
from room_host import RoomHost  # noqa: E402

RULES = sim.DEFAULT_RULES
PROOF_METHOD = "dev_local_v1"
HOUSE_ACCOUNT = "house.dev.local"
SEED_BATCH = 600
UNREAD_GRACE_S = 180
# The five battle presets: one per fight style, built only from free menu items.
PRESETS = {
    "brawler": dict(style="brawler", loadout=dict(weapon="c-swing", trinket="c-shockwave", body="c-body-builder", head="c-head-builder")),
    "hunter": dict(style="hunter", loadout=dict(weapon="c-shot", trinket="c-blink-strike", body="c-body-speedrunner", head="c-head-speedrunner")),
    "looter": dict(style="looter", loadout=dict(weapon="c-lunge", trinket="c-magnet", body="c-body-degen", head="c-head-degen")),
    "guardian": dict(style="guardian", loadout=dict(weapon="c-lob", trinket="c-bubble", body="c-body-maxi", head="c-head-maxi")),
    "survivor": dict(style="survivor", loadout=dict(weapon="c-zap", trinket="c-chain-storm", body="c-body-speedrunner", head="c-head-maxi")),
}


def encoded(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decoded(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def verify_ed25519(public_key: str, body: bytes, signature: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(decoded(public_key)).verify(decoded(signature), body)
        return True
    except (InvalidSignature, ValueError):
        return False


def now_ms() -> int:
    return time.time_ns() // 1_000_000


ORIGIN = "http://127.0.0.1:8181"  # the first-look page; the only origin allowed to read /dev/players and /dev/health


def make_contexts(port: int, index: int) -> tuple[dict, dict]:
    schema = json.loads((ROOT / "room/protocol.schema.json").read_bytes())
    control = copy.deepcopy(schema["$defs"]["MainnetContext"]["examples"][0])
    control.update(rules_hash=sim.digest(RULES), deployment_id=f"dev-local-r{index}",
                   audience=f"https://127.0.0.1:{port}/room#control",
                   contract_ids=dict(nft="dev-nft.local", arena="dev-arena.local"))
    result = copy.deepcopy(control)
    result["audience"] = "near:mainnet:" + control["contract_ids"]["arena"] + ":post_batch"
    return control, result


class DevHouse:
    """Keeps the house roster seated through the same bridge calls the engine tests use."""

    def __init__(self, context: dict) -> None:
        self.context = context
        self.arena: server.Arena | None = None
        self.cursor = 0

    def binding(self, name: str) -> dict:
        return {"context": copy.deepcopy(self.context), "grant_id": "grant:" + name, "session_key_id": "key:" + name,
                "member_id": name, "nft_token_id": name, "persona_digest": "a" * 64,
                "account_id": HOUSE_ACCOUNT, "slot_id": name, "generation": "1"}

    def poll(self, control, tick, roster, count, view) -> None:
        bridge = self.arena.bridge
        if not any(n.startswith("dev-") for n in self.arena.members):  # keep one ring seat free for a DEV joiner
            count = min(count, 5 - sum(m["profile"]["house"] for m in self.arena.members.values()))
        for step in range(len(roster)):
            if count <= 0:
                return
            name = roster[(self.cursor + step) % len(roster)]
            if name in self.arena.members:
                continue
            b = self.binding(name)
            life = bridge.reserve_life(b)
            if "life_id" not in life:
                continue
            lock = bridge.lock_prediction(b, life["life_id"], None)
            bridge.activate(b, life["life_id"], lock["lock_ref"])
            count -= 1
            self.cursor = (self.cursor + step + 1) % len(roster)


class Round:
    """One arena, one room and one result reader, built together."""

    def __init__(self, dev: "DevRoom", index: int) -> None:
        self.index = index
        self.dev = dev
        self.context, self.result_context = make_contexts(dev.port, index)
        self.tmp = Path(dev.data_dir) / f"round-{index}"
        self.tmp.mkdir(parents=True)
        self.security: list[dict] = []
        self.consumed: set[str] = set()
        self.base = now_ms()
        self.arena = None
        slots = SlotStore(self.tmp / "slots", self.context["room_id"], 16, clock=self.vnow)
        self.host = RoomHost(slots, self.context, now_ms=self.vnow, sign=dev.room_sign,
            verify_session=dev.verify_session, key_id="room_key_a", proof_methods=(PROOF_METHOD,),
            consume_nonce=self.consume, ready=lambda: True, admission_open=lambda: True,
            security_event=self.commit_security)
        house = DevHouse(self.context)
        base = secrets.randbelow(1 << 40) * 1000
        self.arena = server.Arena(self.context, [base + i for i in range(SEED_BATCH)], data_dir=self.tmp / "engine",
            room_factory=self.host, profile_provider=dev.profile, identity_resolver=dev.resolve,
            receipt_signer=self.host.sign_receipt, admission_gate=self.host.admission_ready,
            life_guard=self.life_guard, server_time_ms=self.vnow, pick_resolver=dev.pick,
            house_runtime=house, dev_host=True)  # this host seats `dev-` ids by design; a production host refuses them
        house.arena = self.arena
        boundary = self.host.service.life_boundary
        house_grants = {house.binding(n)["grant_id"] for n in RULES["house"]}
        self.deferred_notices: list[str] = []

        def life_boundary(grant_id: str) -> None:
            # House trenchies are seated through the bridge, not the room, so they hold no grant to notify. A notice
            # that reserves a life enqueues an input two ticks ahead: after the step to the segment's last 2 ticks that
            # lands in the next segment, so it waits until the segment turns over.
            if grant_id in house_grants:
                return None
            if self.in_boundary():
                self.deferred_notices.append(grant_id)
                return None
            return boundary(grant_id)

        self.host.service.life_boundary = life_boundary
        # DEV boundary guard. An input enqueued in the last input_delay ticks of a segment is journalled in this
        # segment but applied in the next, and the result reader refuses a segment that holds one. The room-facing
        # routes below refuse such calls for a moment; the engine's own scheduling and life notices step aside for
        # the same ticks.
        schedule = self.arena._schedule

        def guarded_schedule() -> None:
            if self.in_boundary():
                return None
            while self.deferred_notices:
                boundary(self.deferred_notices.pop(0))
            return schedule()

        self.arena._schedule = guarded_schedule
        self.records = EngineRecords(self.arena.store, self.tmp / "wire.sqlite", self.context, self.result_context,
            key_id="room_key_a", sign=dev.room_sign, verify=lambda key, body, sig: key == "room_key_a" and verify_ed25519(dev.room_public, body, sig),
            key_allowed=lambda key: key == "room_key_a")
        self.host.service.records = self.records
        self.ever_dev = False
        self.claimed_at = 0.0
        self.result_served = False

    def in_boundary(self) -> bool:
        return self.arena.sim.state["tick"] % RULES["segment_ticks"] >= RULES["segment_ticks"] - RULES["input_delay"]

    def vnow(self) -> int:
        """Room time is sim time (50 ms a tick from the round's start): a stalled or paused sim stalls every deadline."""
        return self.base + (0 if self.arena is None else self.arena.sim.state["tick"] * 50)

    def consume(self, nonce: str, expires_at: str) -> bool:
        if nonce in self.consumed or int(expires_at) <= self.vnow():
            return False
        self.consumed.add(nonce)
        return True

    def commit_security(self, event: dict) -> bool:
        self.security.append(copy.deepcopy(event))
        return True

    def life_guard(self, binding: dict) -> bool:
        return True if binding["account_id"] == HOUSE_ACCOUNT else self.host.life_guard(binding)

    def dev_members(self) -> list[str]:
        return [n for n in self.arena.members if n.startswith("dev-")]


class DevRoom:
    def __init__(self, port: int, data_dir: str) -> None:
        self.port = port
        self.data_dir = data_dir
        self.room_key = Ed25519PrivateKey.generate()
        self.room_public = encoded(self.room_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))
        self.admin = encoded(os.urandom(18))  # printed once at start; /dev/shutdown needs it
        self.hold_tokens: dict[str, float] = {}
        self.identities: dict[str, dict] = {}
        self.by_key: dict[str, dict] = {}
        self.round_index = 0
        self.round = self._new_round()
        self.clients: dict = {}  # writer -> True when it asked for the compact frames (?codec=1)
        self.tables = None
        self.styles = SpectatorStyles(self.round.arena.sim, dev_brawl.frame)
        self.client_tables: dict = {}  # writer -> table_id of the last tables frame it was sent
        self.latest_codec = None
        self.refresh_frames()
        self.dropped = 0
        self.slowest = 0.0
        self.stop = False
        self.hold_until = 0.0
        self.resyncs = 0

    # --- DEV adapters -------------------------------------------------------------------------------
    def room_sign(self, body: bytes) -> str:
        return encoded(self.room_key.sign(body))

    def verify_session(self, public_key: dict, body: bytes, signature: str) -> bool:
        rec = self.by_key.get(public_key.get("public_key"))
        return rec is not None and verify_ed25519(rec["session_public_key"]["public_key"], body, signature)

    def resolve(self, request: dict) -> dict:
        challenge = request["challenge"]
        rec = self.identities.get(challenge["nft_token_id"])
        proof = request["proof"]
        if (rec is None or proof.get("method_id") != PROOF_METHOD or rec["account_id"] != challenge["account_id"]
                or not verify_ed25519(rec["session_public_key"]["public_key"], b"dev-wallet|" + canonical_bytes(request, exclude=("proof",)), proof["proof_bytes"])):
            return server.error("proof_required")
        return {"owner": {"context": copy.deepcopy(self.round.context), "account_id": rec["account_id"],
                "nft_token_id": rec["nft_token_id"], "persona_digest": request["persona_digest"],
                "ownership_kind": "owner", "custody_reservation_id": None, "checked_at": str(self.round.vnow())},
                "play_status": "eligible", "chain_height": "1", "sale_control_allowed": True}

    def profile(self, binding: dict) -> dict:
        name = binding["nft_token_id"]
        if binding["account_id"] == HOUSE_ACCOUNT:
            row = RULES["house"][name]
            return {"house": True, "public_name": name, "model": "house", "style": row["style"],
                    "loadout": sim.rules_dict(row["kit"]), "bag": {}}
        rec = self.identities[name]
        preset = PRESETS[rec["preset"]]
        return {"house": False, "public_name": "DEV " + rec["name"], "model": "dev", "style": preset["style"],
                "loadout": dict(preset["loadout"]), "bag": {}}

    def pick(self, binding: dict, payload: dict) -> dict:
        row = payload["loadout"]["menu_row"]
        if row not in PRESETS:
            raise ValueError("unknown preset")
        return dict(PRESETS[row]["loadout"])

    def create_identity(self, name: str, preset: str, public_key: str) -> dict:
        slug = "".join(c for c in name.lower() if c.isalnum())[:16]
        if not slug or preset not in PRESETS:
            raise ValueError("name needs letters or digits; preset must be one of " + ", ".join(PRESETS))
        try:
            if len(decoded(public_key)) != 32 or len(public_key) != 43:
                raise ValueError
            Ed25519PublicKey.from_public_bytes(decoded(public_key))
        except ValueError:
            raise ValueError("public_key must be a 32-byte Ed25519 public key, base64url without padding") from None
        token = "dev-" + slug
        if token in self.round.arena.members:
            raise ValueError(f"{token} is seated right now; pick another name or `stop` that session first")
        self.maybe_restart("a DEV identity with no DEV trenchie present")
        self.round.ever_dev = True  # this round now belongs to the DEV joiner: it is not restarted under them
        self.round.claimed_at = time.monotonic()
        old = self.identities.get(token)
        if old is not None:
            self.by_key.pop(old["session_public_key"]["public_key"], None)
        rec = {"name": slug, "preset": preset, "nft_token_id": token, "account_id": f"dev-{slug}.local",
               "persona_digest": hashlib.sha256(f"dev|{slug}|{preset}".encode()).hexdigest(),
               "session_public_key": {"algorithm": "ed25519", "public_key": public_key}}
        self.identities[token] = rec
        self.by_key[public_key] = rec
        print(f"snap_local: DEV identity registered: {token} ({preset}); no wallet, chain or NFT is involved", flush=True)
        return {"label": "DEV", "name": slug, "preset": preset, "nft_token_id": token, "account_id": rec["account_id"],
                "persona_digest": rec["persona_digest"], "session_public_key": rec["session_public_key"],
                "room_public_key": self.room_public, "proof_method": PROOF_METHOD, "key_id": "room_key_a",
                "context": self.round.context, "result_context": self.round.result_context, "presets": sorted(PRESETS)}

    # --- rounds -------------------------------------------------------------------------------------
    def _new_round(self) -> Round:
        self.round_index += 1
        return Round(self, self.round_index)

    def maybe_restart(self, why: str) -> None:
        """A join with no DEV trenchie present starts segment:0 now, unless a result is still pending."""
        r = self.round
        if r.dev_members() or (r.ever_dev and r.arena.segment_index == 0 and not r.arena.failed):
            return
        wait = UNREAD_GRACE_S - (time.monotonic() - r.claimed_at)
        if r.ever_dev and not r.result_served and not r.arena.failed and wait > 0:
            raise ValueError(f"round {self.round_index} still holds a result its player has not read; "
                             f"retry in {int(wait) + 1} s, or read it first with `snap.py result`")
        self.round = self._new_round()
        self.refresh_frames()
        print(f"snap_local: round {self.round_index} started ({why})", flush=True)

    @staticmethod
    def guarded(path: str, body: bytes) -> bool:
        """Calls that become engine inputs: a join, or a control frame that is an order or a prediction."""
        if path == "/room/join":
            return True
        try:
            return json.loads(body).get("kind") in ("intent", "prediction")
        except (ValueError, AttributeError):
            return False

    def start_hold(self) -> None:
        """Freeze the sim for one join handshake (up to 10 s). Callers are unauthenticated, so repeats and other
        callers never extend it, and a new freeze waits 5 s after the last one ended."""
        now = time.monotonic()
        if now >= self.hold_until + 5:
            self.hold_until = now + 10

    def why(self, segment_id: str) -> dict:
        """Say which check of the sealed-record projection refuses a segment, and which commands cross its end."""
        from portable_records import _project
        from room.ledger import Refusal
        try:
            record = self.round.arena.store.segment(segment_id)
        except (FileNotFoundError, KeyError, ValueError):
            return {"segment_id": segment_id, "sealed": False}
        end = RULES["segment_ticks"] * (int(segment_id.split(":")[1]) + 1)
        crossing = [{"kind": row["value"]["kind"], "fighter": row["value"]["fighter_id"], "tick": row["value"]["tick"]}
                    for row in record["commands"] if row["kind"] == "input" and row["value"]["tick"] >= end]
        try:
            _project(record)
            return {"segment_id": segment_id, "sealed": True, "refused": False, "crossing_commands": crossing}
        except Refusal as exc:
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            return {"segment_id": segment_id, "sealed": True, "refused": True, "code": str(exc),
                    "check": f"{frame.name} (portable_records.py:{frame.lineno})", "crossing_commands": crossing}

    def players(self) -> list[dict]:
        a = self.round.arena
        out = []
        for name in a.members:
            if name.startswith("dev-"):
                rec = self.identities.get(name, {})
                f = a.sim.state["fighters"].get(name)
                out.append({"label": "DEV", "fighter_id": name, "name": rec.get("name"), "preset": rec.get("preset"),
                            "state": f["state"] if f else "bench", "life_id": a.members[name]["life_id"]})
        return out

    def health(self) -> dict:
        a = self.round.arena
        return {"dev": True, "round": self.round_index, "tick": a.sim.state["tick"], "segment": a.segment_id,
                "spectators": len(self.clients), "dev_players": len(self.round.dev_members()), "failed": a.failed,
                "dropped_sends": self.dropped, "clock_resyncs": self.resyncs, "slowest_step_ms": round(self.slowest * 1000, 2),
                "rules_hash": a.sim.rules_hash, "claims": "DEV: no wallet, chain or NFT; contract ids are dev-*.local; the protocol's network field reads mainnet because its schema defines no other context"}

    def refresh_frames(self) -> None:
        """The plain snapshot every tick; the compact tick frame (and its tables, when the roster changed) only if wanted."""
        arena = self.round.arena
        self.latest = arena.snapshot_bytes
        if any(self.clients.values()) or self.tables is None:
            self.tables = codec.tables_for(arena.sim)
            self.latest_codec = codec.encode_tick(arena.sim, self.tables)
        else:
            self.latest_codec = None

    # --- HTTP ----------------------------------------------------------------------------------------
    def route(self, method: str, target: str, body: bytes, ip: str, admin: str = "") -> tuple[int, object]:
        url = urlsplit(target)
        path, query = url.path, {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if path == "/dev/identity" and method == "POST":
                args = json.loads(body or b"{}")
                return 200, self.create_identity(str(args.get("name", "")), str(args.get("preset", "")), str(args.get("public_key", "")))
            if path == "/dev/shutdown" and method == "POST":
                if not hmac.compare_digest(admin, self.admin):
                    return 403, {"error": "needs the admin token printed at start"}
                self.stop = True
                return 200, {"stopping": True}
            if path == "/dev/why":
                return 200, self.why(query.get("segment_id", "segment:0"))
            if path == "/dev/players":
                return 200, self.players()
            if path == "/dev/terms":
                return 200, self.round.host.service.export_owner_state()["terms"]
            if path == "/dev/clock":
                return 200, {"now_ms": self.round.vnow(), "tick": self.round.arena.sim.state["tick"], "segment": self.round.arena.segment_id}
            if path in ("/", "/health", "/dev/health"):
                return 200, self.health()
            if path in ("/room/challenge", "/room/join"):
                self.start_hold()
            if (path == "/room/join" or path == "/room/control/frame") and method == "POST" and self.round.in_boundary() and self.guarded(path, body):
                return 200, {"type": "error", "code": "rate_limited", "request_id": None, "retry_after_ms": "200"}
            if path == "/room/control/open":
                return 200, self.round.arena.control.open_control(ip=ip)
            if path == "/room/control/frame":
                reply = self.round.arena.control.frame(query["cid"], body)
                if isinstance(reply, dict) and reply.get("state") == "accepted" and reply.get("prediction_lock"):
                    self.hold_until = 0.0
                return 200, reply
            if path == "/room/control/private":
                return 200, self.round.arena.control.drain_private(query["cid"])
            if path == "/room" or path.startswith("/room/"):
                reply = self.round.arena.control.request(method, target, body, ip=ip)
                if path == "/room/result" and isinstance(reply, dict) and reply.get("type") != "error":
                    self.round.result_served = True
                return 200, reply
            return 404, {"error": "not found"}
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            return 400, {"error": str(exc)[:200]}

    async def handle(self, reader, writer) -> None:
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            writer.close()
            return
        lines = head.decode("latin-1").split("\r\n")
        method, target, _ = (lines[0].split(" ") + ["", ""])[:3]
        headers = {k.strip().lower(): v.strip() for k, _, v in (l.partition(":") for l in lines[1:] if ":" in l)}
        key = headers.get("sec-websocket-key")
        if headers.get("upgrade", "").lower() == "websocket" and key:
            await self.spectate(reader, writer, key, "codec=1" in target, parse_qs(urlsplit(target).query).get("styles") == ["1"])
            return
        allowed_hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        path = urlsplit(target).path
        try:
            if headers.get("host", "") not in allowed_hosts:  # DNS rebinding: only our own name and port
                status, value = 403, {"error": "host not allowed"}
            elif method not in ("GET", "POST"):
                status, value = 405, {"error": "GET or POST only"}
            elif method == "POST" and headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
                status, value = 415, {"error": "POST bodies must be application/json"}  # a web page cannot send that cross-origin unpreflighted
            else:
                size = int(headers.get("content-length", "0"))
                if not 0 <= size <= 65536:
                    raise ValueError("body too large")
                body = await asyncio.wait_for(reader.readexactly(size), 5) if size else b""
                peer = (writer.get_extra_info("peername") or ("local",))[0]
                ip = peer
                status, value = self.route(method, target, body, ip, headers.get("x-dev-admin", ""))
        except (ValueError, asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
            status, value = 400, {"error": str(exc)[:200]}
        data = json.dumps(value, separators=(",", ":")).encode()
        paused = int(time.monotonic() < self.hold_until)
        cors = ""
        if method == "GET" and path in ("/dev/players", "/dev/health") and headers.get("origin") == ORIGIN:
            cors = f"Access-Control-Allow-Origin: {ORIGIN}\r\nVary: Origin\r\n"
        writer.write(f"HTTP/1.1 {status} OK\r\nContent-Type: application/json\r\n{cors}"
                     f"X-Dev-Now: {self.round.vnow()}\r\nX-Dev-Paused: {paused}\r\n"
                     f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n".encode() + data)
        try:
            await writer.drain()
        except ConnectionError:
            pass
        writer.close()

    async def spectate(self, reader, writer, key: str, compact: bool = False, styles: bool = False) -> None:
        accept = base64.b64encode(hashlib.sha1(key.encode() + dev_brawl.GUID).digest())
        writer.write(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                     b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n")
        if styles:
            self.styles.connect(writer)
        if compact:
            self.tables = codec.tables_for(self.round.arena.sim)
            self.client_tables[writer] = self.tables["table_id"]
            writer.write(dev_brawl.frame(codec.encode_tables(self.tables)))
            writer.write(dev_brawl.frame(codec.encode_tick(self.round.arena.sim, self.tables)))
        else:
            writer.write(dev_brawl.frame(self.latest))
        self.clients[writer] = compact
        try:
            while True:
                opcode, data = await dev_brawl.read_frame(reader)
                if opcode == 0x8:
                    writer.write(dev_brawl.frame(b"", 0x8))
                    break
                if opcode == 0x9:
                    writer.write(dev_brawl.frame(data, 0xA))
        except (asyncio.IncompleteReadError, ConnectionError, ValueError):
            pass
        finally:
            self.clients.pop(writer, None)
            self.styles.forget(writer)
            self.client_tables.pop(writer, None)
            writer.close()

    def publish(self) -> None:
        self.styles.refresh(self.round.arena.sim)
        plain = dev_brawl.frame(self.latest)
        small = dev_brawl.frame(self.latest_codec) if self.latest_codec is not None else None
        tables = None
        for writer, compact in tuple(self.clients.items()):
            if writer.transport.get_write_buffer_size() > dev_brawl.MAX_BUFFER:
                self.dropped += 1
                continue
            self.styles.send(writer)
            if compact and small is not None:
                if self.client_tables.get(writer) != self.tables["table_id"]:  # new roster, or a send this client missed
                    tables = tables or dev_brawl.frame(codec.encode_tables(self.tables))
                    writer.write(tables)
                    self.client_tables[writer] = self.tables["table_id"]
                writer.write(small)
            elif not compact:
                writer.write(plain)

    async def run_clock(self, ticks: int | None = None) -> None:
        period = 1 / RULES["tick_hz"]
        deadline = time.monotonic()
        count = 0
        while (ticks is None or count < ticks) and not self.stop:
            started = time.monotonic()
            if started < self.hold_until:
                await asyncio.sleep(0.02)
                deadline = time.monotonic()
                continue
            arena = self.round.arena
            try:
                arena.advance()
            except Exception as exc:  # a failed arena (e.g. seeds exhausted) is replaced, never hidden
                print(f"snap_local: arena stopped: {exc!r}", flush=True)
                traceback.print_exc()
                self.round.ever_dev = False
                for name in self.round.dev_members():
                    self.round.arena.members.pop(name, None)
                self.maybe_restart("the previous arena stopped")
                continue
            self.refresh_frames()
            self.slowest = max(self.slowest, time.monotonic() - started)
            self.publish()
            count += 1
            deadline += period
            if time.monotonic() - deadline > 2 * period:
                # Behind by more than two ticks (a slow handler, a busy machine): never run ticks back to back to
                # catch up. Room time is sim time, so the sim simply runs slower for a while.
                self.resyncs += 1
                deadline = time.monotonic()
            await asyncio.sleep(max(0, deadline - time.monotonic()))


async def serve(dev: DevRoom, ready=None, ticks: int | None = None) -> None:
    listener = await asyncio.start_server(dev.handle, "127.0.0.1", dev.port)
    dev.port = listener.sockets[0].getsockname()[1]
    if ready is not None:
        ready(dev.port)
    async with listener:
        await dev.run_clock(ticks)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--data-dir", default=None)
    args = ap.parse_args()
    data_dir = args.data_dir or tempfile.mkdtemp(prefix="snap-local-")
    dev = DevRoom(args.port, data_dir)
    print(f"snap_local: DEV arena on http://127.0.0.1:{args.port} (spectator ws://127.0.0.1:{args.port}); "
          f"data {data_dir}. No wallet, chain or NFT. Stop it with Ctrl-C, or POST /dev/shutdown with header X-Dev-Admin: {dev.admin}", flush=True)
    try:
        asyncio.run(serve(dev))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
