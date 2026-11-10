#!/usr/bin/env python3
"""snap.py: drive a DEV trenchie in the local arena (snap_local.py) from a shell or a Claude Code session.

  python3 -I near/arena/snap.py terms
  python3 -I near/arena/snap.py join --name claude --preset hunter --accept-terms 1 [--spread 40,30,20,10] [--zero 10]
  python3 -I near/arena/snap.py state
  python3 -I near/arena/snap.py intent [--focus nearest|ID|none] [--avoid ID|none] [--loot nearest|ignore] [--sig auto|hold|use] [--leave]
  python3 -I near/arena/snap.py respawn --preset looter --spread 25,25,25,25 --zero 10
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
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT)]
try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
except ImportError:
    raise SystemExit("snap: needs the `cryptography` package: python3 -m pip install -r near/onboarding/requirements.txt")
from near.arena.snap_client import SnapClient, SnapRefusal  # noqa: E402

DEFAULT_URL = "http://127.0.0.1:8765"
STATE = ".snap-dev.json"
ORDER_FIELDS = ("focus", "avoid", "loot", "sig")
DEFAULT_ORDERS = dict(focus=None, avoid=None, loot="nearest", sig="auto")


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
        return json.loads(exc.read() or b"{}")
    except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
        raise SystemExit(f"snap: cannot reach {url}: {getattr(exc, 'reason', exc)}. Is snap_local.py running?")


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
    parts = [int(x) for x in text.split(",")]
    if len(parts) != 4 or sum(parts) != 100 or min(parts) < 0:
        raise SystemExit("snap: --spread is four whole percents that sum to 100: chance your life ends with 1, 2, 3, 4+ KOs given at least one")
    return dict(one=parts[0] * 100, two=parts[1] * 100, three=parts[2] * 100, four_plus=parts[3] * 100)


def prediction_payload(preset: str, spread: dict, zero_pct: int) -> dict:
    return dict(loadout=dict(menu_row=preset, bag_serials=[]), spread_bps=spread, zero_bps=zero_pct * 100,
                stake=None, moves=[], lock=False)


class Keeper:
    """The background process: holds the grant, renews the lease, files each life's standing prediction."""

    def __init__(self, args) -> None:
        self.base = args.url
        self.lock = threading.RLock()
        self.key = Ed25519PrivateKey.generate()  # this session's key: only the public half ever leaves this process
        public = encoded(self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))
        ident = call(self.base + "/dev/identity", "POST", {"name": args.name, "preset": args.preset, "public_key": public})
        if "nft_token_id" not in ident:
            raise SystemExit("snap: " + str(ident.get("error", ident)))
        self.ident, self.token = ident, ident["nft_token_id"]
        room = ident["room_public_key"]
        self.transport = Transport(self.base, self.token)
        now = self.now = self.transport.now
        self.client = SnapClient(ident["context"], self.transport, now_ms=now,
            sign_session=lambda body: encoded(self.key.sign(body)),
            verify_room=lambda key, body, sig: key == ident["key_id"] and verify_ed25519(room, body, sig),
            trusted_key_ids=(ident["key_id"],), result_context=ident["result_context"])
        self.order = dict(preset=args.preset, spread=parse_spread(args.spread), zero=args.zero)
        self.life_id = None
        self.lives_seen = 0
        self.ko_seen = False
        self.last_renew = 0
        self.last_intent = 0
        self.errors: list[str] = []
        self.result_cache = None
        self.orders = dict(DEFAULT_ORDERS)
        self.orders_life = None
        self.reapply_failures = 0
        self.joined_at = 0
        self.stopping = False
        self.interval_ms = 2000
        self.heartbeat_ms = 10000

    def wallet(self, body: bytes) -> dict:
        return dict(method_id=self.ident["proof_method"], key_id="dev_local", proof_bytes=encoded(self.key.sign(b"dev-wallet|" + body)))

    def start(self, terms_version: str) -> dict:
        grant = self.client.join(account_id=self.ident["account_id"], nft_token_id=self.token,
            persona_digest=self.ident["persona_digest"], session_public_key=self.ident["session_public_key"],
            request_id="dev-join-" + str(self.now()), declared_compute=dict(harness="external", model="claude-code", source="owner", effort="high"),
            prove_wallet=self.wallet)
        if grant.get("state") != "accepted":
            raise SystemExit("snap: the room queued this join (no fighter authority yet): " + json.dumps(grant)[:200])
        terms = self.client.member_snapshot(request_id="dev-read-terms")["terms"]
        if terms is None or terms["version"] != terms_version:
            raise SystemExit(f"snap: the room's current terms are version {terms and terms['version']}; you accepted {terms_version}. Run `terms`.")
        self.client.accept_terms(terms["version"], request_id="dev-accept-terms")
        limits = self.client.manifest()["limits"]
        self.interval_ms, self.heartbeat_ms = int(limits["intent_interval_ms"]), int(limits["heartbeat_ms"])
        ready = self.client.authenticate(request_id="dev-control")
        self.last_renew = self.now()
        return self.file_prediction(ready["next_life"]) or {}

    def file_prediction(self, notice: dict) -> dict | None:
        life = notice["reservation"]["life_id"]
        self.life_id, self.lives_seen = life, self.lives_seen + 1
        if self.now() >= int(notice["reservation"]["prediction_deadline"]):
            self.errors.append(f"prediction deadline passed for {life}; this life is unpredicted")
            return None
        o = self.order
        from_preset = o["preset"]
        reply = self.client.control("prediction", prediction_payload(from_preset, o["spread"], o["zero"]), life_id=life)
        return dict(life_id=life, state=reply["state"], prediction_lock=reply.get("prediction_lock"), standing_order=o["preset"])

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

    def send_orders(self, me: dict, snap: dict, orders: dict, leave: bool) -> dict:
        focus = orders["focus"]
        if focus == "nearest":
            others = [f for f in snap["fighters"] if f is not me and f["state"] == "ring"]
            at = (int(me["x_milli"]), int(me["y_milli"]))
            focus = min(others, key=lambda f: math.dist((int(f["x_milli"]), int(f["y_milli"])), at))["fighter_id"] if others else None
        reply = {}
        for _ in range(40):  # the room's 2 s order spacing runs on sim time; retry while it says rate_limited
            wait = (self.last_intent + self.interval_ms - self.now()) / 1000
            if wait > 0:
                time.sleep(min(wait, 2.5))
            try:
                reply = self.client.control("intent", dict(fighter_id=me["fighter_id"], focus=focus, avoid=orders["avoid"],
                    loot=orders["loot"], sig=orders["sig"], leave=leave, say=None), life_id=self.life_id)
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
            reply = self.send_orders(me, snap, orders, bool(body.get("leave")))
            self.orders_life = self.life_id
        out = dict(state=reply["state"], applied_tick=reply.get("applied_tick"), focus=reply["resolved_focus"],
                   loot=orders["loot"], sig=orders["sig"], leave=bool(body.get("leave")))
        if reply["state"] != "accepted":
            out.update(reason=reply.get("reason") or reply.get("code"))
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
            self.order = dict(preset=body["preset"], spread=parse_spread(body["spread"]), zero=int(body["zero"]))
        return dict(standing_order=self.order["preset"], applies="to your next life")

    def why(self) -> str:
        try:
            info = call(self.base + "/dev/why?segment_id=segment:0")
        except SystemExit:
            return ""
        crossing = info.get("crossing_commands") or []
        text = f" The host says the check that refused it is {info.get('check')}" if info.get("refused") else ""
        if crossing:
            text += f"; {len(crossing)} input(s) were applied after the segment's last tick ({crossing[0]['kind']} for {crossing[0]['fighter']} at tick {crossing[0]['tick']})"
        return text + "." if text else ""

    def result(self, wait: float) -> dict:
        end = time.monotonic() + wait
        while True:
            with self.lock:
                try:
                    result = self.client.result("segment:0")
                    own = [l for l in result["lives"] if l["nft_token_id"] == self.token]
                    known = next((l["life_id"] for l in own if l["life_id"] in self.client._predictions), None)
                    row = self.client.prediction_row("segment:0", known) if known else None
                    out = dict(dev=True, chain_result=False, signed=True, signer=result["key_id"], segment="segment:0",
                               completed=result["completed"], sealed_result_hash=result["sealed_result_hash"],
                               signature=result["signature"][:24] + "...",
                               lives=[dict(life_id=l["life_id"], ko_count=l["ko_count"], prediction_lock=l["prediction_lock"]["state"]) for l in own],
                               public_prediction_row="matches your private receipt" if row else "no prediction filed for this life")
                    self.result_cache = out
                    return out
                except SnapRefusal as exc:
                    reason = str(exc)
                sealed = self.client.observe()["clock"]["segment_id"] != "segment:0"
            if reason != "result_pending":  # any other refusal will not clear by waiting
                raise SystemExit(f"snap: the room refused the result for segment:0 ({reason}).{self.why()} Run `stop` and `join` again for a fresh round.")
            if sealed:
                raise SystemExit("snap: segment:0 is sealed and your life did not end inside it, so there is no signed result for you. "
                                 "Orders in the last 0.1 s of a segment, or a life that ends later, land in segment:1. Run `stop` and `join` again, "
                                 "and send `intent --leave` while `state` shows several seconds left.")
            if time.monotonic() >= end:
                raise SystemExit("snap: no signed result yet (result_pending). Your life has not ended inside segment:0: send `intent --leave` before the round's 60 s run out.")
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
                out = dict(error="refused: " + str(exc))
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
    state.update(first=first, identity=dict(id=keeper.token, label="DEV", preset=keeper.ident["preset"], account=keeper.ident["account_id"]))
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


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="snap.py", description=__doc__.split("\n")[0])
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--state", default=STATE)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("terms")
    j = sub.add_parser("join")
    j.add_argument("--name", required=True)
    j.add_argument("--preset", required=True, choices=["brawler", "hunter", "looter", "guardian", "survivor"])
    j.add_argument("--accept-terms", required=True, help="the terms version you have read with `terms`")
    j.add_argument("--spread", default="40,30,20,10")
    j.add_argument("--zero", type=int, default=10, help="percent chance of a life with 0 KOs")
    sub.add_parser("state")
    i = sub.add_parser("intent")
    i.add_argument("--focus"); i.add_argument("--avoid"); i.add_argument("--loot", choices=["nearest", "ignore"])
    i.add_argument("--sig", choices=["auto", "hold", "use"]); i.add_argument("--leave", action="store_true")
    r = sub.add_parser("respawn")
    r.add_argument("--preset", required=True, choices=["brawler", "hunter", "looter", "guardian", "survivor"])
    r.add_argument("--spread", required=True); r.add_argument("--zero", type=int, required=True)
    s = sub.add_parser("result")
    s.add_argument("--wait", type=float, default=90)
    sub.add_parser("stop")
    d = sub.add_parser("_keeper")
    d.add_argument("--name", required=True); d.add_argument("--preset", required=True)
    d.add_argument("--accept-terms", required=True); d.add_argument("--spread", default="40,30,20,10"); d.add_argument("--zero", type=int, default=10)
    args = ap.parse_args(argv)
    state_path = Path(args.state)

    if args.cmd == "terms":
        terms = call(args.url + "/dev/terms")
        print(json.dumps(terms))
        print(f"terms version {terms['version']}: segments are {int(terms['segment_ms']) // 1000} s, one intent every {int(terms['input_interval_ms']) / 1000:g} s, "
              f"simulated at {terms['simulation_hz']} Hz. Joining as a DEV trenchie: no wallet, no chain, no NFT. Accept with: join --accept-terms {terms['version']}")
    elif args.cmd == "join":
        parse_spread(args.spread)
        secret = encoded(os.urandom(18))
        write_state(state_path, dict(secret=secret, url=args.url))
        proc = subprocess.Popen([sys.executable, "-I", str(Path(__file__).resolve()), "--url", args.url, "--state", str(state_path), "_keeper",
                                 "--name", args.name, "--preset", args.preset, "--accept-terms", args.accept_terms,
                                 "--spread", args.spread, "--zero", str(args.zero)],
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
                lock = (first or {}).get("prediction_lock") or {}
                print(f"joined as {state['identity']['id']} (DEV); life {first.get('life_id')} prediction {first.get('state')} "
                      f"hash {str(lock.get('prediction_hash'))[:12]}; the keeper (pid {state['pid']}) holds your seat. Next: state, intent, result.")
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
        out = keeper_call(state_path, "intent", body)
        print(json.dumps(out))
        print(f"intent {out['state']} (applies at tick {out['applied_tick']}); focus {out['focus']} loot {out['loot']} sig {out['sig']}; orders stay until you change them")
    elif args.cmd == "respawn":
        out = keeper_call(state_path, "respawn", dict(preset=args.preset, spread=args.spread, zero=args.zero))
        print(json.dumps(out))
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
