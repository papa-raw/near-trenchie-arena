#!/usr/bin/env python3
"""snap.py: drive a DEV trenchie in the local arena (snap_local.py) from a shell or a Claude Code session.

  python3 -I near/arena/snap.py terms
  python3 -I near/arena/snap.py join --name claude --preset hunter --accept-terms 1 [--level 1-4]
  python3 -I near/arena/snap.py state
  python3 -I near/arena/snap.py intent [--focus nearest|ID|none] [--avoid ID|none] [--loot nearest|ignore] [--sig auto|hold|use] [--leave]
  python3 -I near/arena/snap.py respawn --preset looter --level 2
  python3 -I near/arena/snap.py result [--wait 90]
  python3 -I near/arena/snap.py stop

DEV only: the identity is a local session key, not a wallet, an NFT or a mainnet account. `join` starts a
small background process (the keeper) that holds your grant, renews the room lease and files your standing
prediction for each new life; every other command talks to it. State lives in `.snap-dev.json` in the
current folder (override with --state). Stdlib plus the checkout's own room client; no network beyond
127.0.0.1.
"""
from __future__ import annotations

import argparse
import base64
import errno
import json
import math
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
STARTUP_DEPENDENCIES = frozenset(('cryptography', 'jsonschema', 'requests'))
sys.path[:0] = [str(ROOT)]
try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
    from near.arena.snap_client import SEAT_QUEUE_CODES, SnapClient, SnapRefusal  # noqa: E402
    from near.arena.battle_protocol import rejoin_message  # noqa: E402
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from dev_persona import read_sheet, read_look  # noqa: E402
    from presets import NAMES as BATTLE_NAMES  # noqa: E402
except ModuleNotFoundError as exc:
    if (exc.name or '').split('.')[0] not in STARTUP_DEPENDENCIES:
        raise
    raise SystemExit(f"Missing {exc.name}: run python3 -m pip install -r {shlex.quote(str(ROOT / 'near/requirements.txt'))}") from None

DEFAULT_URL = "http://127.0.0.1:8765"
STATE = ".snap-dev.json"
PRESET_CHOICES = tuple(name.lower().replace(" ", "-") for name in BATTLE_NAMES) + ("brawler", "hunter", "looter", "guardian", "survivor")
ORDER_FIELDS = ("focus", "avoid", "loot", "sig")
DEFAULT_ORDERS = dict(focus=None, avoid=None, loot="nearest", sig="auto")
SPEECH_INTERVAL_MS = 10000
REFUSAL_FIXES = {
    "prediction_closed": "Wait until state says ring, then send the intent again; use respawn to change the next life's pick.",
    "rate_limited": "Wait out the order interval the arena rules give (`terms`) before another order, or 10 sim seconds before another speech line; follow the host's retry tick.",
    "stale_slot": "Run stop, then join again for fresh room authority.",
    "proof_required": "Run stop, then join again with a fresh local session.",
    "context_mismatch": "The host started a new round. Run stop, then join again.",
    "version_mismatch": "Run `terms`, read the arena rules' current version, then join with --accept-terms VERSION.",
    "request_conflict": "Read state before sending a new command; do not change and replay an old request.",
    "room_full": "Keep watching and retry when a seat opens.",
    "bad_message": "Check the command flags with --help and use a fighter id from state.",
}


RESULT_SCAN = 8  # sealed segments a `result` reads back, newest first: the host keeps at most 8 projections


def segment_number(segment_id: str) -> int:
    return int(segment_id.split(":", 1)[1])


def first_life_line(first: dict | None) -> str:
    """The join's account of the first life's prediction, with the room's reason whenever it was not accepted."""
    first = first or {}
    life, state, digest12 = first.get("life_id"), first.get("state"), str(first.get("prediction_hash"))[:12]
    counted = (f"; predicts {first['level']}+ KOs" if first.get("level") else
               f"; {first['note']}" if first.get("note") else "")
    if state == "accepted":
        return f"life {life} prediction accepted hash {digest12}{counted}"
    if state == "queued":
        return (f"life {life} prediction queued hash {digest12} ({first['reason']}): the room holds this prediction for "
                f"{life} and starts that life when a seat opens; `state` shows bench until then{counted}")
    if state == "none":
        return f"life {life} {first.get('note') or NO_PREDICTION_NOTE}"
    if state is None:
        return f"life {life} unpredicted: its prediction deadline passed before the keeper could file it"
    return f"life {life} prediction {state} ({refusal_message(first.get('reason') or 'refused')})"


def refusal_message(code: str) -> str:
    return code + ". " + REFUSAL_FIXES.get(code, "Read state and the arena rules (`terms`), then retry with a current room session.")


def speech_message(speech: dict | None) -> str:
    """Explain the speech outcome separately from whether the fighter order was accepted."""
    if speech is None:
        return ''
    if speech.get('refused') == 'rate_limited':
        return f"speech refused: wait {speech.get('retry_after_s', 10)} sim seconds, then send --say again."
    if speech.get('refused'):
        return "speech refused: " + str(speech['refused']) + ". Check state, then send a new --say line."
    if speech.get('muted'):
        return "speech muted: guard list missing; the feed shows " + str(speech.get('text', 'an emote')) + ". Ask the operator to load the guard list."
    if speech.get('blocked'):
        return "speech blocked: the feed shows " + str(speech.get('text', 'an emote')) + ". Change the line before sending --say again."
    return "speech posted: " + str(speech.get('text', ''))


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


def write_state(path: Path, state: dict) -> None:
    """Replace the state file in one step, so a reader sees the old file or the new one, never half of it."""
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)  # a private name per writer; mode 0600 (it holds the keeper's secret)
    with os.fdopen(fd, "w") as handle:
        handle.write(json.dumps(state))
    os.replace(name, path)


def read_state(path: Path) -> dict:
    """Read the state file; a reader that still races an older writer retries instead of failing."""
    for attempt in range(40):
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            if attempt == 39:
                raise
            time.sleep(0.05)


def call(url: str, method: str = "GET", body: bytes | dict | None = None, headers: dict | None = None, timeout: float = 60, seen: dict | None = None):
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    headers = dict(headers or {})
    if method == "POST":
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as reply:
            if seen is not None and reply.headers.get("X-Dev-Now"):
                seen.update(now=int(reply.headers["X-Dev-Now"]), at=time.monotonic(), paused=reply.headers.get("X-Dev-Paused") == "1")
            return json.loads(reply.read())
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read() or b"{}")
        except json.JSONDecodeError:
            raise SystemExit(f"snap: HTTP {exc.code} from the host or proxy. Check the local host and allowed route, then retry; no room action was confirmed.") from None
    except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
        reason = getattr(exc, 'reason', exc)
        denied = isinstance(reason, OSError) and reason.errno in {errno.EPERM, errno.EACCES}
        fix = ('The operating system or network policy denied this connection. Check this runtime\'s permissions and configured proxy route.'
               if denied else 'Check that the host is running at this address and that the network route is allowed.')
        raise SystemExit(f"snap: cannot reach {url}: {reason}. {fix}") from None


class Transport:
    """The room client's transport over the local HTTP shim; the control socket is three POST/GET routes."""

    def __init__(self, base: str, who: str) -> None:
        self.base, self.headers, self.seen = base.rstrip("/"), {}, {}
        call(self.base + "/dev/clock", seen=self.seen)

    def now(self) -> int:
        """Room time: the server's tick clock as of its last reply, run forward in real time unless it was paused."""
        s = self.seen
        return s["now"] if s["paused"] else s["now"] + int((time.monotonic() - s["at"]) * 1000)

    def request(self, method: str, target: str, body: bytes = b"") -> dict:
        return call(self.base + target, method, body or None, self.headers, seen=self.seen)

    def open_control(self, url: str) -> dict:
        return call(self.base + "/room/control/open", "POST", b"", self.headers, seen=self.seen)

    def frame(self, connection_id: str, body: bytes) -> dict:
        return call(f"{self.base}/room/control/frame?cid={connection_id}", "POST", body, self.headers, seen=self.seen)

    def drain_private(self, connection_id: str) -> list[dict]:
        return call(f"{self.base}/room/control/private?cid={connection_id}", "GET", None, self.headers, seen=self.seen)


def parse_spread(text: str) -> dict:
    try:
        parts = [int(x) for x in text.split(",")]
    except ValueError:
        raise SystemExit("snap: --spread needs four whole percents, for example 40,30,20,10") from None
    if len(parts) != 4 or sum(parts) != 100 or min(parts) < 0:
        raise SystemExit("snap: --spread is four whole percents that sum to 100: chance your life ends with 1, 2, 3, 4+ KOs given at least one")
    return dict(one=parts[0] * 100, two=parts[1] * 100, three=parts[2] * 100, four_plus=parts[3] * 100)


BINS = ("one", "two", "three", "four_plus")
NO_PREDICTION_NOTE = "no prediction for this life: add --level 1-4 to predict at least 1, 2, 3 or 4 KOs"
LEGACY_NOTE = ("prediction not counted under the level rules: a spread over several bins counts nothing; predict one level "
               "with --level 1-4 (1+, 2+, 3+ or 4+ KOs)")


def standing_order(level, spread, zero) -> dict:
    """The prediction each life files: one level (all 10000 on one bin, zero 0), or an explicit legacy spread.

    No flag at all files no prediction: a prediction is never invented, so nothing is sent and the room locks "none"
    at the deadline, and the join line says how to add one. A spread on one bin with zero 0 is that level; any other
    spread is sent as given and carries LEGACY_NOTE, because the arena's level rules do not count it."""
    if level is not None and (spread is not None or zero is not None):
        raise SystemExit("snap: give --level or --spread/--zero, not both")
    if level is None and spread is None and zero is None:
        return dict(level=None, spread=None, zero=None, note=NO_PREDICTION_NOTE, predict=False)
    if spread is None and zero is None:
        if level not in (1, 2, 3, 4):
            raise SystemExit("snap: --level is 1, 2, 3 or 4: at least that many KOs this life")
        return dict(level=level, spread={b: 10000 if i + 1 == level else 0 for i, b in enumerate(BINS)}, zero=0, note=None,
                    predict=True)
    zero = 10 if zero is None else zero
    if not 0 <= zero <= 100:
        raise SystemExit("snap: --zero must be a whole percent from 0 to 100")
    bins = parse_spread("40,30,20,10" if spread is None else spread)
    one = [i + 1 for i, b in enumerate(BINS) if bins[b] == 10000]
    if one and zero == 0:
        return dict(level=one[0], spread=bins, zero=0, note=None, predict=True)
    return dict(level=None, spread=bins, zero=zero, note=LEGACY_NOTE, predict=True)


def prediction_payload(preset: str, spread: dict, zero_pct: int) -> dict:
    return dict(loadout=dict(menu_row=preset, bag_serials=[]), spread_bps=spread, zero_bps=zero_pct * 100,
                stake=None, moves=[], lock=False)


class Keeper:
    """The background process: holds the grant, renews the lease, files each life's standing prediction."""

    def __init__(self, args, *, transport_factory=Transport) -> None:
        self.base = args.url
        self.lock = threading.RLock()
        self.key = Ed25519PrivateKey.generate()  # this session's key: only the public half ever leaves this process
        public = encoded(self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))
        identity = {"name": args.name, "preset": args.preset, "public_key": public}
        sheet = read_sheet(getattr(args, "sheet", None))
        if sheet is not None:
            identity["sheet"] = sheet
        look = read_look(getattr(args, "look", None))
        if look is not None:
            identity["look"] = look
        if getattr(args, "code", None):
            identity["code"] = args.code
        self.public_key, self.transport_factory, self.terms_version = public, transport_factory, None
        self.bind(call(self.base + "/dev/identity", "POST", identity))
        # A subscription door may set a weekly limit (a share of the plan's week); the live session stops sending
        # orders once its reported share reaches it. Read with the door code, the only thing that names it.
        self.plan_stop_pct = None
        if getattr(args, "code", None):
            row = call(self.base + "/snap/code/" + args.code)
            stop = row.get("plan_stop_pct") if isinstance(row, dict) else None
            self.plan_stop_pct = stop if type(stop) is int and 0 < stop <= 100 else None
        self.order = dict(preset=self.ident["preset"], **standing_order(getattr(args, "level", None), getattr(args, "spread", None),
                                                                     getattr(args, "zero", None)))
        self.life_id = None
        self.lives_seen = 0
        self.ko_seen = False
        self.last_renew = 0
        self.last_intent = 0
        self.last_say: int | None = None
        self.errors: list[str] = []
        self.result_cache = None
        self.orders = dict(DEFAULT_ORDERS)
        self.orders_life = None
        self.reapply_failures = 0
        self.joined_at = 0
        self.stopping = False
        self.interval_ms = 2000
        self.heartbeat_ms = 10000

    def bind(self, ident: dict) -> None:
        """Take an identity reply: this round's contexts, a fresh transport and a client signing with this session's key."""
        if "nft_token_id" not in ident:
            raise SystemExit("snap: " + str(ident.get("error", ident)))
        self.ident, self.token = ident, ident["nft_token_id"]
        room = ident["room_public_key"]
        self.transport = self.transport_factory(self.base, self.token)
        now = self.now = self.transport.now
        self.client = SnapClient(ident["context"], self.transport, now_ms=now,
            sign_session=lambda body: encoded(self.key.sign(body)),
            verify_room=lambda key, body, sig: key == ident["key_id"] and verify_ed25519(room, body, sig),
            trusted_key_ids=(ident["key_id"],), result_context=ident["result_context"])

    def rejoin(self, round_index: int) -> dict:
        """The host started round `round_index` under this session: sign in again as the same trenchie with the same key
        (the request carries this key's signature over that round and the time) and the terms version the owner
        accepted, and file the standing prediction for the new round's first life."""
        with self.lock:
            old = self.transport
            at = int(time.time() * 1000)
            proof = encoded(self.key.sign(rejoin_message(round_index, self.public_key, at)))
            self.bind(call(self.base + "/dev/identity", "POST", {"op": "rejoin", "public_key": self.public_key,
                                                                "round": int(round_index), "at": at, "sig": proof}))
            try:
                old.close()
            except (AttributeError, OSError, ValueError):
                pass
            self.life_id, self.joined_segment = None, 0
            return self.start(self.terms_version)

    def wallet(self, body: bytes) -> dict:
        return dict(method_id=self.ident["proof_method"], key_id="dev_local", proof_bytes=encoded(self.key.sign(b"dev-wallet|" + body)))

    def start(self, terms_version: str) -> dict:
        self.terms_version = terms_version
        deadline, attempt = time.monotonic() + 120, 0
        while True:
            attempt += 1
            try:
                grant = self.client.join(account_id=self.ident["account_id"], nft_token_id=self.token,
                    persona_digest=self.ident["persona_digest"], session_public_key=self.ident["session_public_key"],
                    request_id=f"dev-join-{self.public_key[:12]}-{self.now()}-{attempt}", declared_compute=dict(harness="external", model="claude-code", source="owner", effort="high"),
                    prove_wallet=self.wallet)
                if grant.get("state") == "accepted":
                    break
                reason = "room_full"
            except SnapRefusal as exc:
                reason = str(exc)
                if reason not in ("ownership_unavailable", "room_full", "rate_limited"):
                    raise
            if time.monotonic() >= deadline:
                raise SystemExit(f"snap: still waiting for {reason}; no fighter authority yet. Retry live with the same unjoined code.")
            if attempt == 1:
                print("snap: waiting for the arena's inventory/owner read or a free seat; keeping this session open", file=sys.stderr, flush=True)
            # One quick retry, then at most four attempts per minute, within the room's join allowance.
            time.sleep(min(2 if attempt == 1 else 15, max(0, deadline - time.monotonic())))
        terms = self.client.member_snapshot(request_id="dev-read-terms")["terms"]
        if terms is None or terms["version"] != terms_version:
            raise SystemExit(f"snap: the arena rules are now version {terms and terms['version']}; you accepted {terms_version}. Run `terms`.")
        self.client.accept_terms(terms["version"], request_id="dev-accept-terms")
        limits = self.client.manifest()["limits"]
        self.interval_ms, self.heartbeat_ms = int(limits["intent_interval_ms"]), int(limits["heartbeat_ms"])
        ready = self.client.authenticate(request_id="dev-control")
        self.joined_segment = segment_number(self.client.observe()["clock"]["segment_id"])
        self.last_renew = self.now()
        return self.file_prediction(ready["next_life"]) or {}

    def file_prediction(self, notice: dict) -> dict | None:
        life = notice["reservation"]["life_id"]
        self.life_id, self.lives_seen = life, self.lives_seen + 1
        if self.now() >= int(notice["reservation"]["prediction_deadline"]):
            self.errors.append(f"prediction deadline passed for {life}; this life is unpredicted")
            return None
        o = self.order
        if not o["predict"]:   # nothing is sent; the room locks "none" for this life at its deadline
            return dict(life_id=life, state="none", prediction_lock=None, standing_order=o["preset"], level=None,
                        prediction_hash=None, note=o["note"])
        from_preset = o["preset"]
        reply = self.client.control("prediction", prediction_payload(from_preset, o["spread"], o["zero"]), life_id=life)
        out = dict(life_id=life, state=reply["state"], prediction_lock=reply.get("prediction_lock"), standing_order=o["preset"],
                   level=o["level"])
        if o["note"]:
            out["note"] = o["note"]
        lock = reply.get("prediction_lock") or {}
        out["prediction_hash"] = lock.get("prediction_hash")
        if reply["state"] != "accepted":
            out["reason"] = reply.get("code") or "refused"
            if out["reason"] in SEAT_QUEUE_CODES:
                # The room locked this prediction, then queued the seat: same life, same lock, when a seat opens.
                out["state"] = "queued"
                out["prediction_hash"] = reply["request_digest"]
            else:
                self.errors.append(f"prediction for {life} refused: {refusal_message(out['reason'])}"[:200])
        return out

    def tick(self) -> None:
        """One keeper beat: renew the lease, then file the standing prediction for any new life."""
        with self.lock:
            try:
                if self.now() - self.last_renew >= self.heartbeat_ms - 2000:
                    self.client.control("renew", dict(lease_until=str(self.now() + 30_000)))
                    self.last_renew = self.now()
                for notice in self.client.life_notices():
                    if notice["reservation"]["life_id"] != self.life_id:
                        self.ko_seen = True
                        self.file_prediction(notice)
                self.reapply_orders()
            except (SnapRefusal, ValueError, KeyError, SystemExit) as exc:
                self.errors.append(f"{type(exc).__name__}: {exc}"[:200])
                del self.errors[:-5]

    def loop(self) -> None:
        while not self.stopping:
            self.tick()
            time.sleep(0.3)

    # --- commands ------------------------------------------------------------------------------------
    def summary(self) -> dict:
        with self.lock:
            snap = self.client.observe()
        clock = snap["clock"]
        tick, seg_ticks = int(clock["tick"]), int(clock["segment_ticks"])
        fighters = snap["fighters"]
        me = next((f for f in fighters if f["nft_token_id"] == self.token), None)
        def pos(f):
            return int(f["x_milli"]), int(f["y_milli"])
        rows = []
        for f in fighters:
            if f["state"] == "bench" and f is not me:
                continue
            row = dict(id=f["fighter_id"], house=f["house"], state=f["state"], hp=int(f["health_milli"]),
                       x=pos(f)[0], y=pos(f)[1], gear=[e["item_id"] for e in f["equipped"]])
            if me is not None and f is not me and me["state"] != "bench":
                row["distance_milli"] = round(math.dist(pos(f), pos(me)))
            rows.append(row)
        rows.sort(key=lambda r: r.get("distance_milli", 0))
        left = (seg_ticks - tick % seg_ticks) / 20
        return dict(you=dict(id=self.token, label="DEV", preset=self.ident["preset"], state=me["state"] if me else "unknown",
                        hp=int(me["health_milli"]) if me else None, life_id=self.life_id, lives_started=self.lives_seen),
                    segment=clock["segment_id"], tick=tick, segment_seconds_left=round(left, 1),
                    ring=rows, drops=snap["items"][:8], ko_seen=self.ko_seen,
                    standing_order=self.order, keeper_errors=self.errors[-3:])

    def merge_orders(self, body: dict) -> dict:
        """Orders stay until you change them: a field you leave out keeps its last value."""
        merged = dict(self.orders)
        merged.update({k: body[k] for k in ORDER_FIELDS if k in body})
        self.orders = merged
        return merged

    def send_orders(self, me: dict, snap: dict, orders: dict, leave: bool, say: str | None = None) -> dict:
        focus = orders["focus"]
        if focus == "nearest":
            others = [f for f in snap["fighters"] if f is not me and f["state"] == "ring"]
            at = (int(me["x_milli"]), int(me["y_milli"]))
            focus = min(others, key=lambda f: math.dist((int(f["x_milli"]), int(f["y_milli"])), at))["fighter_id"] if others else None
        reply = {}
        for _ in range(40):  # The advertised order spacing runs on sim time; retry while it says rate_limited.
            wait = (self.last_intent + self.interval_ms - self.now()) / 1000
            if wait > 0:
                time.sleep(min(wait, 2.5))
            try:
                reply = self.client.control("intent", dict(fighter_id=me["fighter_id"], focus=focus, avoid=orders["avoid"],
                    loot=orders["loot"], sig=orders["sig"], leave=leave, say=say), life_id=self.life_id)
            except SnapRefusal as exc:
                if str(exc) != "rate_limited":  # the host steps aside for the last ticks of a segment: same bytes, again shortly
                    raise
                time.sleep(0.3)
                continue
            if reply["state"] == "accepted" or reply.get("code") != "rate_limited":
                break
            time.sleep(0.5)
        self.last_intent = self.now()
        reply["resolved_focus"] = focus
        return reply

    def intent(self, body: dict) -> dict:
        with self.lock:
            snap = self.client.observe()
            me = next((f for f in snap["fighters"] if f["nft_token_id"] == self.token), None)
            if me is None:
                raise SystemExit("snap: you are not on the island")
            orders = self.merge_orders(body)
            say = body.get("say")
            speech_refusal = None
            last_say = getattr(self, "last_say", None)
            if say is not None and last_say is not None and self.now() - last_say < SPEECH_INTERVAL_MS:
                speech_refusal = dict(refused="rate_limited", retry_after_s=math.ceil((SPEECH_INTERVAL_MS - self.now() + last_say) / 1000))
                say = None
            reply = self.send_orders(me, snap, orders, bool(body.get("leave")), say)
            self.orders_life = self.life_id
            out = dict(state=reply["state"], applied_tick=reply.get("applied_tick"), focus=reply["resolved_focus"],
                       loot=orders["loot"], sig=orders["sig"], leave=bool(body.get("leave")))
            if speech_refusal is not None:
                out["speech"] = speech_refusal
            elif say is not None and reply["state"] == "accepted":
                posted = call(self.base + "/dev/speech?fighter_id=" + self.token)
                if posted.get("sequence") == reply.get("sequence"):
                    out["speech"] = posted["speech"]
                    if "refused" not in posted["speech"]:
                        self.last_say = self.now()
                else:
                    out["speech"] = {"refused": "not_posted"}
            if reply["state"] != "accepted":
                out.update(reason=refusal_message(reply.get("reason") or reply.get("code") or "refused"))
            return out

    def reapply_orders(self) -> None:
        """A new life starts with the room's default orders: put yours back once the fighter is in the ring."""
        if self.orders == DEFAULT_ORDERS or self.orders_life == self.life_id or self.life_id is None:
            return
        if getattr(self, "reapply_life", None) != self.life_id:
            self.reapply_life, self.reapply_failures = self.life_id, 0
        snap = self.client.observe()
        me = next((f for f in snap["fighters"] if f["nft_token_id"] == self.token), None)
        if me is not None and me["state"] == "ring":
            reply = self.send_orders(me, snap, self.orders, False)
            if reply.get("state") == "accepted":
                self.orders_life = self.life_id
            else:
                self.reapply_failures += 1
                self.errors.append(f"could not re-send your orders for {self.life_id}: {reply.get('state')} {reply.get('code')}"[:200])
                if self.reapply_failures >= 5:
                    self.orders_life = self.life_id  # stop retrying this life; `state` shows keeper_errors

    def respawn(self, body: dict) -> dict:
        with self.lock:
            self.order = dict(preset=body["preset"], **standing_order(body.get("level"), body.get("spread"), body.get("zero")))
        out = dict(standing_order=self.order["preset"], level=self.order["level"], applies="to your next life")
        if self.order["note"]:
            out["note"] = self.order["note"]
        return out

    def why(self, segment_id: str) -> str:
        try:
            info = call(self.base + "/dev/why?segment_id=" + segment_id)
        except SystemExit:
            return ""
        crossing = info.get("crossing_commands") or []
        text = f" The host says the check that refused it is {info.get('check')}" if info.get("refused") else ""
        if crossing:
            text += f"; {len(crossing)} input(s) were applied after the segment's last tick ({crossing[0]['kind']} for {crossing[0]['fighter']} at tick {crossing[0]['tick']})"
        return text + "." if text else ""

    def result(self, wait: float) -> dict:
        """The signed result of the newest sealed segment that holds one of your lives.

        A result lists the lives whose prediction lock, start and end all fall inside its segment, so a player
        who joins a running arena reads the segment its life was in. A life that crosses a segment boundary is
        in no result; this says so instead of waiting for one."""
        end = time.monotonic() + wait
        left_in = None  # the segment in which your fighter was first seen gone home
        while True:
            with self.lock:
                snap = self.client.observe()
                current = segment_number(snap["clock"]["segment_id"])
                first = getattr(self, "joined_segment", 0)
                for n in range(current - 1, max(first, current - RESULT_SCAN) - 1, -1):  # newest sealed first
                    segment = f"segment:{n}"
                    try:
                        result = self.client.result(segment)
                    except SnapRefusal as exc:
                        if str(exc) == "result_pending":  # sealed, none of your lives in it
                            continue
                        raise SystemExit(f"snap: the room refused the result for {segment} ({exc}).{self.why(segment)} "
                                         "Run `stop` and `join` again for a fresh round.") from None
                    own = [l for l in result["lives"] if l["nft_token_id"] == self.token]
                    known = next((l["life_id"] for l in own if l["life_id"] in self.client._predictions), None)
                    row = self.client.prediction_row(segment, known) if known else None
                    out = dict(dev=True, chain_result=False, signed=True, signer=result["key_id"], segment=segment,
                               completed=result["completed"], sealed_result_hash=result["sealed_result_hash"],
                               signature=result["signature"][:24] + "...",
                               lives=[dict(life_id=l["life_id"], ko_count=l["ko_count"], prediction_lock=l["prediction_lock"]["state"]) for l in own],
                               public_prediction_row="matches your private receipt" if row else "no prediction filed for this life")
                    self.result_cache = out
                    return out
                home = not any(f["nft_token_id"] == self.token for f in snap["fighters"])
                left_in = current if home and left_in is None else left_in
            if left_in is not None and current > left_in:
                raise SystemExit(f"snap: your fighter has swum home and every segment up to segment:{current - 1} is sealed; none of your "
                                 "lives was locked, started and ended inside one segment, so no signed result holds it. A life that "
                                 "crosses a segment boundary is in no DEV result. Join again, and send `intent --leave` while `state` "
                                 "shows several seconds left in the segment.")
            if time.monotonic() >= end:
                raise SystemExit(f"snap: no signed result yet (result_pending): your lives so far did not end inside a sealed segment "
                                 f"(the arena is in segment:{current}; each segment seals after 60 s, and a life that crosses a segment "
                                 "boundary is in no DEV result). Send `intent --leave` while `state` shows several seconds left, then "
                                 "`result` again once that segment has sealed.")
            time.sleep(1.5)


def serve_keeper(keeper: Keeper, state_path: Path, secret: str) -> None:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # keep the keeper quiet
            pass

        def do_POST(self):
            if self.headers.get("X-Keeper") != secret:
                self.send_response(403); self.end_headers(); return
            size = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(size) or b"{}")
            path = self.path
            try:
                if path == "/state":
                    out = keeper.summary()
                elif path == "/intent":
                    out = keeper.intent(body)
                elif path == "/respawn":
                    out = keeper.respawn(body)
                elif path == "/result":
                    out = keeper.result(float(body.get("wait", 0)))
                elif path == "/stop":
                    out = dict(stopped=True)
                    keeper.stopping = True
                else:
                    out = dict(error="unknown command")
            except SystemExit as exc:
                out = dict(error=str(exc))
            except SnapRefusal as exc:
                out = dict(error="refused: " + refusal_message(str(exc)))
            data = json.dumps(out).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    state = read_state(state_path)
    state.update(port=httpd.server_address[1], pid=os.getpid(), ready=True)
    write_state(state_path, state)
    threading.Thread(target=keeper.loop, daemon=True).start()
    httpd.timeout = 0.5
    while not keeper.stopping:
        httpd.handle_request()


def daemon_main(args) -> None:
    state_path = Path(args.state)
    try:
        keeper = Keeper(args)
        first = keeper.start(args.accept_terms)
    except BaseException as exc:  # report to the waiting `join`, never hang it
        state = read_state(state_path)
        state.update(error=str(exc) or type(exc).__name__)
        write_state(state_path, state)
        return
    state = read_state(state_path)
    state.update(first=first, identity=dict(id=keeper.token, label="DEV", preset=keeper.ident["preset"], account=keeper.ident["account_id"], name_notice=keeper.ident.get("name_notice")))
    write_state(state_path, state)
    serve_keeper(keeper, state_path, state["secret"])


def keeper_call(state_path: Path, command: str, body: dict | None = None) -> dict:
    if not state_path.exists():
        raise SystemExit("snap: no session here. Run `join` first (state file " + str(state_path) + ").")
    state = read_state(state_path)
    if "port" not in state:
        raise SystemExit("snap: no live keeper here (" + str(state.get("error", "join did not finish")) + "). Run `join` again.")
    reply = call(f"http://127.0.0.1:{state['port']}/{command}", "POST", body or {}, {"X-Keeper": state["secret"]}, timeout=120)
    if "error" in reply:
        raise SystemExit("snap: " + reply["error"])
    return reply


def build_parser() -> argparse.ArgumentParser:
    level_help = "predict at least this many KOs this life: 1, 2, 3 or 4 (without it, no prediction is filed)"
    ap = argparse.ArgumentParser(prog="snap.py", description=__doc__.split("\n")[0])
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--state", default=STATE)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("terms")
    j = sub.add_parser("join")
    j.add_argument("--name", default="newcomer")
    j.add_argument("--sheet", help="a checked creator persona JSON file")
    j.add_argument("--look", help="optional exported player look JSON")
    j.add_argument("--code", help="refused: a door code starts `live --code` (battle mode)")
    j.add_argument("--preset", required=True, choices=PRESET_CHOICES)
    j.add_argument("--accept-terms", required=True, help="the arena rules version you have read with `terms`")
    j.add_argument("--level", type=int, choices=(1, 2, 3, 4), help=level_help)
    j.add_argument("--spread", help="legacy: four percents over 1, 2, 3, 4+ KOs (not counted under the level rules)")
    j.add_argument("--zero", type=int, help="legacy, with --spread: percent chance of a life with 0 KOs")
    live = sub.add_parser('live', help='one connection: line commands in, JSON-line battle events out')
    live.add_argument('--name', default='newcomer'); live.add_argument('--sheet'); live.add_argument('--look'); live.add_argument('--code')
    live.add_argument('--preset', required=True, choices=PRESET_CHOICES)
    live.add_argument('--accept-terms', required=True)
    live.add_argument('--level', type=int, choices=(1, 2, 3, 4), help=level_help)
    live.add_argument('--spread'); live.add_argument('--zero', type=int)
    live.add_argument('--fifo', help='read commands from this private named pipe instead of stdin')
    live.add_argument('--seconds', type=int, default=0, help='stop after this many seconds; zero keeps streaming until leave')
    sub.add_parser("state")
    i = sub.add_parser("intent")
    i.add_argument("--say", help="one public line, at most one per 10 sim seconds")
    i.add_argument("--focus"); i.add_argument("--avoid"); i.add_argument("--loot", choices=["nearest", "ignore"])
    i.add_argument("--sig", choices=["auto", "hold", "use"]); i.add_argument("--leave", action="store_true")
    r = sub.add_parser("respawn")
    r.add_argument("--preset", required=True, choices=PRESET_CHOICES)
    r.add_argument("--level", type=int, choices=(1, 2, 3, 4), help=level_help)
    r.add_argument("--spread"); r.add_argument("--zero", type=int)
    s = sub.add_parser("result")
    s.add_argument("--wait", type=float, default=90)
    sub.add_parser("stop")
    d = sub.add_parser("_keeper")
    d.add_argument("--sheet"); d.add_argument("--look"); d.add_argument("--code")
    d.add_argument("--name", required=True); d.add_argument("--preset", required=True)
    d.add_argument("--accept-terms", required=True); d.add_argument("--level", type=int)
    d.add_argument("--spread"); d.add_argument("--zero", type=int)
    return ap


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    state_path = Path(args.state)

    if args.cmd == 'live':
        from near.arena.battle_transport import LiveTransport
        from near.arena.snap_live import run_live
        standing_order(args.level, args.spread, args.zero)
        status = run_live(args, lambda options: Keeper(options, transport_factory=lambda base, who: LiveTransport(Transport(base, who))),
                          refusal_fix=refusal_message)
        raise SystemExit(status)
    elif args.cmd == "terms":
        terms = call(args.url + "/dev/terms")
        print(json.dumps(terms))
        print(f"arena rules, version {terms['version']}: segments are {int(terms['segment_ms']) // 1000} s, one order every {int(terms['input_interval_ms']) / 1000:g} s, "
              f"simulated at {terms['simulation_hz']} Hz. Joining as a DEV Trenchie: no wallet, no chain, no NFT. Accept with: join --accept-terms {terms['version']}")
    elif args.cmd == "join":
        if args.code:  # checked before the host is called, so the code stays unspent
            raise SystemExit("snap: a door code starts a live battle session on the creator's Trenchie: run "
                             f"`snap.py --url {args.url} live --code {args.code} --preset {args.preset} --accept-terms {args.accept_terms} "
                             '--fifo "$PWD/orders.fifo"` (SNAP.md, "Pair a local AI door"). The code was not used.')
        standing_order(args.level, args.spread, args.zero)
        read_sheet(args.sheet)
        read_look(args.look)
        secret = encoded(os.urandom(18))
        write_state(state_path, dict(secret=secret, url=args.url))
        proc = subprocess.Popen([sys.executable, "-I", str(Path(__file__).resolve()), "--url", args.url, "--state", str(state_path), "_keeper",
                                 "--name", args.name, "--preset", args.preset, "--accept-terms", args.accept_terms,
                                 ] + (["--level", str(args.level)] if args.level is not None else []) +
                                (["--spread", args.spread] if args.spread is not None else []) +
                                (["--zero", str(args.zero)] if args.zero is not None else []) +
                                (["--sheet", str(Path(args.sheet).resolve())] if args.sheet else []) +
                                (["--code", args.code] if args.code else []) +
                                (["--look", str(Path(args.look).resolve())] if args.look else []),
                                start_new_session=True, stdin=subprocess.DEVNULL,
                                stdout=open(state_path.with_suffix(".log"), "ab"), stderr=subprocess.STDOUT)
        for _ in range(600):
            time.sleep(0.2)
            state = read_state(state_path)
            if state.get("error"):
                raise SystemExit("snap: join failed: " + state["error"])
            if state.get("ready"):
                first = state["first"]
                print(json.dumps(dict(joined=True, **state["identity"], first_life=first)))
                print(f"joined as {state['identity']['id']} (DEV); {first_life_line(first)}; "
                      f"the keeper (pid {state['pid']}) holds your seat. Next: state, intent, result.")
                if state["identity"].get("name_notice"):
                    print(state["identity"]["name_notice"])
                return
            if proc.poll() is not None:
                raise SystemExit("snap: the keeper exited; see " + str(state_path.with_suffix(".log")))
        raise SystemExit("snap: join timed out")
    elif args.cmd == "_keeper":
        daemon_main(args)
    elif args.cmd == "state":
        out = keeper_call(state_path, "state")
        print(json.dumps(out))
        you = out["you"]
        print(f"{you['id']} (DEV {you['preset']}) is {you['state']} hp {you['hp']}; {out['segment']} has {out['segment_seconds_left']} s left; "
              f"{len(out['ring'])} on the island; ko_seen={out['ko_seen']}")
    elif args.cmd == "intent":
        body = {}
        for key in ("focus", "avoid"):  # "none" clears the order; leaving the flag out keeps it
            value = getattr(args, key)
            if value is not None:
                body[key] = None if value == "none" else value
        for key in ("loot", "sig"):
            if getattr(args, key) is not None:
                body[key] = getattr(args, key)
        body["leave"] = args.leave
        if args.say is not None:
            if not 1 <= len(args.say) <= 140:
                raise SystemExit("snap: --say needs 1 to 140 characters")
            body["say"] = args.say
        out = keeper_call(state_path, "intent", body)
        print(json.dumps(out))
        message = speech_message(out.get('speech'))
        speech_note = '; ' + message if message else ''
        print(f"intent {out['state']} (applies at tick {out['applied_tick']}); focus {out['focus']} loot {out['loot']} sig {out['sig']}; orders stay until you change them{speech_note}")
        if out.get('reason'):
            print(out['reason'])
    elif args.cmd == "respawn":
        standing_order(args.level, args.spread, args.zero)  # refuse a bad order here, before the keeper sees it
        out = keeper_call(state_path, "respawn", dict(preset=args.preset, level=args.level, spread=args.spread, zero=args.zero))
        print(json.dumps(out))
        print(f"your next life predicts {out['level']}+ KOs" if out.get("level") else out.get("note", ""))
    elif args.cmd == "result":
        out = keeper_call(state_path, "result", dict(wait=args.wait))
        print(json.dumps(out))
        life = out["lives"][0] if out["lives"] else {}
        print(f"DEV RESULT (local room key, not a chain result): {out['segment']} sealed, signature checked against this host's room key "
              f"{out['signer']}, hash {out['sealed_result_hash'][:12]}; life {life.get('life_id')} ended with {life.get('ko_count')} KO(s), "
              f"prediction {life.get('prediction_lock')}; {out['public_prediction_row']}")
    elif args.cmd == "stop":
        out = keeper_call(state_path, "stop")
        print(json.dumps(out))


if __name__ == "__main__":
    main()
