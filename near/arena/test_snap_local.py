"""The local DEV snap-in: one host process, one keeper, a signed result. Starts one sim: run it through the slot cap."""
from __future__ import annotations

import asyncio
import contextlib
import http.client
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.request
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]
import codec  # noqa: E402
import snap  # noqa: E402
import snap_local  # noqa: E402


def new_public_key() -> str:
    key = snap.Ed25519PrivateKey.generate()
    return snap.encoded(key.public_key().public_bytes(snap.serialization.Encoding.Raw, snap.serialization.PublicFormat.Raw))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class SimClockRoom(snap_local.DevRoom):
    """Real HTTP room whose simulation advances only when its case requests it."""

    async def run_clock(self, ticks: int | None = None) -> None:
        if ticks is not None:
            raise ValueError('the manual fixture uses step(), not an automatic tick limit')
        self._fixture_loop = asyncio.get_running_loop()
        self.hold_until = float('inf')
        while not self.stop:
            await asyncio.sleep(0.01)

    def route(self, method: str, target: str, body: bytes, ip: str, admin: str = '') -> tuple[int, object]:
        try:
            return super().route(method, target, body, ip, admin)
        finally:
            # Predictions normally release the DEV join hold. This fixture's
            # clock stays paused, so owner clocks must stay on sim time too.
            self.hold_until = float('inf')

    def step(self, ticks: int) -> None:
        async def advance() -> None:
            for _ in range(ticks):
                self.round.arena.advance()
                self.refresh_frames()
                self.publish()
                await asyncio.sleep(0)
        asyncio.run_coroutine_threadsafe(advance(), self._fixture_loop).result(timeout=60)


class StateFile(unittest.TestCase):
    """Finding 1: the first join printed a JSONDecodeError while the keeper was writing the state file."""

    def test_reader_never_sees_half_a_file_and_waits_out_a_half_written_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".snap-dev.json"
            snap.write_state(path, {"n": 0})
            stop = threading.Event()
            big = {"pad": "x" * 200_000}
            writer = threading.Thread(target=lambda: [snap.write_state(path, {**big, "n": i}) for i in range(200)] and stop.set())
            writer.start()
            seen = [snap.read_state(path)["n"] for _ in range(300)]  # raises on any torn read
            writer.join()
            self.assertTrue(seen)
            path.write_text('{"half"')  # a writer that truncated and has not finished
            threading.Timer(0.2, lambda: snap.write_state(path, {"done": True})).start()
            self.assertEqual(snap.read_state(path), {"done": True})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600, "L4: the state file holds the keeper secret")


class ResultWording(unittest.TestCase):
    """M1 as ruled: the room copy's inherited mainnet strings stay, so the CLI must not call a local result a chain result."""

    def test_result_line_and_json_say_dev_and_not_chain(self) -> None:
        sample = {"dev": True, "chain_result": False, "signed": True, "signer": "room_key_a", "segment": "segment:0", "completed": True,
                  "sealed_result_hash": "ab" * 32, "signature": "x...", "public_prediction_row": "matches your private receipt",
                  "lives": [{"life_id": "dev-t:life:0", "ko_count": "1", "prediction_lock": "prediction"}]}
        real = snap.keeper_call
        snap.keeper_call = lambda *a, **k: sample
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                snap.main(["--state", "unused.json", "result"])
        finally:
            snap.keeper_call = real
        lines = out.getvalue().splitlines()
        self.assertTrue(lines[1].startswith("DEV RESULT (local room key, not a chain result): "), lines[1])
        self.assertIn("signature checked against this host's room key", lines[1])
        self.assertNotIn("SIGNED RESULT OK", out.getvalue())
        self.assertEqual((json.loads(lines[0])["dev"], json.loads(lines[0])["chain_result"]), (True, False))
        self.assertNotIn("SIGNED RESULT OK", (HERE / "../SNAP.md").read_text())
        self.assertIn("DEV RESULT (local room key, not a chain result)", (HERE / "../SNAP.md").read_text())


class StubClient:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.fighters = [{"fighter_id": "dev-t", "nft_token_id": "dev-t", "state": "ring", "x_milli": "0", "y_milli": "0"},
                         {"fighter_id": "near", "nft_token_id": "near", "state": "ring", "x_milli": "100", "y_milli": "0"},
                         {"fighter_id": "far", "nft_token_id": "far", "state": "ring", "x_milli": "9000", "y_milli": "0"}]

    def observe(self) -> dict:
        return {"fighters": self.fighters}

    def control(self, kind: str, payload: dict, *, life_id: str | None = None) -> dict:
        self.sent.append(dict(payload, life_id=life_id))
        return {"state": "accepted", "applied_tick": "9"}


class StickyOrders(unittest.TestCase):
    """Finding 2: `--loot ignore` was undone by the next order, and by every new life."""

    def keeper(self) -> snap.Keeper:
        k = snap.Keeper.__new__(snap.Keeper)
        k.lock, k.client, k.token, k.life_id = threading.RLock(), StubClient(), "dev-t", "life:0"
        k.orders, k.orders_life, k.last_intent, k.interval_ms, k.now = dict(snap.DEFAULT_ORDERS), None, 0, 0, lambda: 0
        return k

    def test_loot_ignore_survives_the_next_order_and_the_next_life(self) -> None:
        k = self.keeper()
        k.intent({"loot": "ignore", "leave": False})
        k.intent({"focus": "nearest", "leave": False})  # leaves --loot out: it must stay ignore
        self.assertEqual([(m["loot"], m["focus"]) for m in k.client.sent], [("ignore", None), ("ignore", "near")])
        k.life_id = "life:1"  # a KO: the room starts the new life on default orders
        k.reapply_orders()
        self.assertEqual((k.client.sent[-1]["loot"], k.client.sent[-1]["focus"], k.client.sent[-1]["life_id"]), ("ignore", "near", "life:1"))
        count = len(k.client.sent)
        k.reapply_orders()  # once per life
        self.assertEqual(len(k.client.sent), count)
        k.intent({"focus": None, "leave": False})  # `--focus none` clears focus only
        self.assertEqual((k.client.sent[-1]["loot"], k.client.sent[-1]["focus"]), ("ignore", None))


class LocalSnap(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.port = free_port()
        manual = getattr(getattr(self, self._testMethodName), 'manual_clock', False)
        if manual:
            seeds = patch.object(snap_local.secrets, 'randbelow', return_value=1)
            seeds.start()
            self.addCleanup(seeds.stop)
        self.dev = (SimClockRoom if manual else snap_local.DevRoom)(self.port, self.tmp.name)
        self.ready = threading.Event()
        self.thread = threading.Thread(target=lambda: asyncio.run(snap_local.serve(self.dev, ready=lambda p: self.ready.set())), daemon=True)
        self.thread.start()
        self.assertTrue(self.ready.wait(60), "host did not start")
        self.addCleanup(self.shutdown)
        self.url = f"http://127.0.0.1:{self.port}"

    def shutdown(self) -> None:
        self.dev.stop = True
        self.thread.join(15)

    def keeper(self, preset: str = "hunter") -> snap.Keeper:
        return snap.Keeper(types.SimpleNamespace(url=self.url, name="tester", preset=preset, spread="40,30,20,10", zero=10))

    def test_dev_identity_is_labelled_and_refuses_unknown_presets(self) -> None:
        bad = snap.call(self.url + "/dev/identity", "POST", {"name": "x", "preset": "wizard", "public_key": new_public_key()})
        self.assertIn("error", bad)
        ok = snap.call(self.url + "/dev/identity", "POST", {"name": "Tester!", "preset": "guardian", "public_key": new_public_key()})
        self.assertEqual((ok["label"], ok["nft_token_id"], ok["preset"]), ("DEV", "dev-tester", "guardian"))
        self.assertEqual(sorted(ok["presets"]), sorted(["brawler", "guardian", "hunter", "looter", "survivor"] + list(snap_local.GUIDE_PRESET_IDS)))

    def test_join_needs_the_terms_version_the_owner_read(self) -> None:
        with self.assertRaises(SystemExit) as caught:
            self.keeper().start("999")
        self.assertIn("arena rules are now version 1", str(caught.exception))

    def test_the_order_rate_the_host_advertises_is_the_rules_tables(self) -> None:
        """Item 23: one order rate. The rules table fixes it; /dev/terms and /room carry it; snap.py prints it as is."""
        import battle_room
        import sim
        rules = sim.DEFAULT_RULES
        want = rules["intent_interval"] * rules["milliseconds_per_second"] // rules["tick_hz"]
        self.assertEqual((want, battle_room.ORDER_INTERVAL_MS), (500, 500))
        self.assertEqual(snap.call(self.url + "/dev/terms")["input_interval_ms"], str(want))
        self.assertEqual(snap.call(self.url + "/room")["limits"]["intent_interval_ms"], str(want))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            snap.main(["--url", self.url, "terms"])
        self.assertIn("arena rules, version 1: segments are 60 s, one order every 0.5 s,", out.getvalue())

    def raw(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None) -> tuple[int, dict, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        conn.request(method, path, body, headers or {})
        reply = conn.getresponse()
        data = json.loads(reply.read() or b"{}")
        out = (reply.status, {k.lower(): v for k, v in reply.getheaders()}, data)
        conn.close()
        return out

    def test_m3_host_refuses_foreign_hosts_non_json_posts_and_scopes_cors(self) -> None:
        self.assertEqual(self.raw("GET", "/dev/clock")[0], 200)
        self.assertEqual(self.raw("GET", "/dev/clock", headers={"Host": "evil.example:" + str(self.port)})[0], 403)  # DNS rebinding
        self.assertEqual(self.raw("POST", "/dev/identity", b"{}", {"Content-Type": "text/plain"})[0], 415)  # a no-preflight page POST
        self.assertEqual(self.raw("POST", "/dev/shutdown", b"{}", {"Content-Type": "application/json"})[0], 403)
        self.assertEqual(self.raw("POST", "/dev/shutdown", b"{}", {"Content-Type": "application/json", "X-Dev-Admin": "wrong"})[0], 403)
        page = snap_local.ORIGIN
        self.assertEqual(self.raw("GET", "/dev/players", headers={"Origin": page})[1].get("access-control-allow-origin"), page)
        self.assertNotIn("access-control-allow-origin", self.raw("GET", "/dev/players", headers={"Origin": "http://evil.example"})[1])
        for path in ("/dev/terms", "/dev/clock", "/room"):
            self.assertNotIn("access-control-allow-origin", self.raw("GET", path, headers={"Origin": page})[1], path)
        status, headers, _ = self.raw("POST", "/dev/identity", json.dumps({"name": "a", "preset": "hunter", "public_key": "x"}).encode(),
                                      {"Content-Type": "application/json", "Origin": page})
        self.assertNotIn("access-control-allow-origin", headers)

    def test_m2_a_joiner_gets_public_material_only_and_cannot_sign_as_the_room(self) -> None:
        key = snap.Ed25519PrivateKey.generate()
        public = snap.encoded(key.public_key().public_bytes(snap.serialization.Encoding.Raw, snap.serialization.PublicFormat.Raw))
        ident = snap.call(self.url + "/dev/identity", "POST", {"name": "forger", "preset": "hunter", "public_key": public})
        self.assertFalse([k for k in ident if "secret" in k or "private" in k], sorted(ident))
        self.assertTrue(snap.verify_ed25519(ident["room_public_key"], b"room says so", self.dev.room_sign(b"room says so")))
        forged = snap.encoded(key.sign(b"room says so"))  # the joiner's own key is all it holds
        self.assertFalse(snap.verify_ed25519(ident["room_public_key"], b"room says so", forged))

    def test_m1_l2_contexts_name_a_dev_deployment_that_changes_every_round(self) -> None:
        first = self.dev.round
        self.assertRegex(first.context["deployment_id"], r"^dev-local-r\d+$")
        self.assertTrue(all(v.endswith(".local") for v in first.context["contract_ids"].values()), first.context)
        self.assertIn("dev-arena.local", first.result_context["audience"])
        self.assertIn("no wallet, chain or NFT", self.dev.health()["claims"])
        first.ever_dev = False  # nobody seated and nothing claimed: the next identity opens a fresh round
        snap.call(self.url + "/dev/identity", "POST", {"name": "r2", "preset": "looter", "public_key": new_public_key()})
        self.assertNotEqual(self.dev.round.context["deployment_id"], first.context["deployment_id"])

    def frames(self, path: str, count: int) -> list[bytes]:
        """Read `count` WebSocket text frames from the spectator socket (the server never masks)."""
        with socket.create_connection(("127.0.0.1", self.port), timeout=20) as conn:
            conn.sendall((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                          "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
            buf = b""
            while b"\r\n\r\n" not in buf:
                buf += conn.recv(65536)
            buf = buf.split(b"\r\n\r\n", 1)[1]
            out = []
            while len(out) < count:
                while len(buf) < 2:
                    buf += conn.recv(65536)
                size, head = buf[1] & 0x7F, 2
                if size == 126:
                    while len(buf) < 4:
                        buf += conn.recv(65536)
                    size, head = int.from_bytes(buf[2:4], "big"), 4
                while len(buf) < head + size:
                    buf += conn.recv(1 << 20)
                out.append(buf[head:head + size])
                buf = buf[head + size:]
            return out

    def test_spectator_socket_serves_plain_and_compact_frames_like_dev_brawl(self) -> None:
        plain = json.loads(self.frames("/", 1)[0])
        self.assertEqual(plain[0], 1)  # server.encode_snapshot: [version, tick, names, ...]
        compact = [json.loads(f) for f in self.frames("/?codec=1", 2)]
        self.assertEqual(compact[0][0], "T")  # the tables frame comes first, then a tick frame that points at its table id
        self.assertEqual(compact[1][2], compact[0][1])

    def test_a_compact_client_that_missed_a_tables_frame_gets_it_before_the_next_tick(self) -> None:
        class Transport:
            size = 0

            def get_write_buffer_size(self) -> int:
                return self.size

        class Writer:
            def __init__(self) -> None:
                self.transport, self.sent = Transport(), []

            def write(self, data: bytes) -> None:
                self.sent.append(json.loads(data[2:]) if data[1] < 126 else json.loads(data[4:]))

        writer = Writer()
        self.dev.clients[writer] = True
        self.dev.client_tables[writer] = -1  # a roster the client has not seen yet
        self.dev.refresh_frames()
        writer.transport.size = 1 << 30  # backpressure: this tick is skipped for the client
        self.dev.publish()
        self.assertEqual(writer.sent, [])
        writer.transport.size = 0
        self.dev.publish()  # the roster did not change again, but the client still needs its tables first
        self.assertEqual([frame[0] for frame in writer.sent][:1], ["T"])
        self.assertEqual(len(writer.sent), 2)

    def test_l1_repeated_join_requests_do_not_extend_the_freeze(self) -> None:
        self.dev.start_hold()
        first = self.dev.hold_until
        time.sleep(0.05)
        self.dev.start_hold()  # any caller, same or different: the freeze is not extended
        self.assertEqual(self.dev.hold_until, first)
        self.dev.hold_until = time.monotonic() - 1  # just ended: a new one waits out the 5 s cooldown
        self.dev.start_hold()
        self.assertLess(self.dev.hold_until, time.monotonic())

    def test_a_leave_on_the_last_ticks_of_a_segment_waits_for_the_next_one_and_the_result_says_why_fast(self) -> None:
        keeper = self.keeper()
        keeper.start("1")
        self.dev.hold_until = time.monotonic() + 600  # freeze the clock; this test steps the arena itself
        time.sleep(0.2)
        arena, ticks = self.dev.round.arena, 0
        while arena.sim.state["tick"] < 1198:
            arena.advance()
            if arena.sim.state["tick"] % 100 == 0:
                keeper.tick()
                self.dev.hold_until = time.monotonic() + 600  # a filed prediction lifts the join freeze: freeze again
        self.dev.hold_until = time.monotonic() + 600
        time.sleep(0.3)
        self.assertEqual(arena.sim.state["tick"], 1198)
        sent = {}
        def send() -> None:
            try:
                sent.update(keeper.intent({"leave": True}))
            except BaseException as exc:  # SystemExit from the keeper is an answer, not a crash
                sent["raised"] = f"{type(exc).__name__}: {exc}"
        sender = threading.Thread(target=send, daemon=True)
        sender.start()
        time.sleep(1.5)
        self.assertTrue(sender.is_alive(), f"the leave must wait: applied at tick 1200 it would cross the segment's end; got {sent}, tick {arena.sim.state['tick']}")
        self.assertEqual(arena.sim.state["tick"], 1198)
        self.assertEqual([c for c in arena.commands if c["kind"] == "input" and c["value"]["tick"] >= 1200], [])
        self.dev.hold_until = 0
        sender.join(60)
        self.assertNotIn("raised", sent, sent)  # the order got an answer (applied or refused for a game reason), never a hang
        while arena.sim.state["tick"] < 1260:
            time.sleep(0.1)
        record = arena.store.segment("segment:0")
        crossing = [c for c in record["commands"] if c["kind"] == "input" and c["value"]["tick"] >= 1200]
        self.assertEqual(crossing, [], "no input may be applied after segment:0's last tick")
        self.assertFalse(self.dev.why("segment:0")["refused"], self.dev.why("segment:0"))
        started = time.monotonic()
        try:  # either the record reads (a life of ours ended earlier in segment:0) or the refusal is clear and quick
            answer = keeper.result(20)
            self.assertTrue(answer["signed"] and answer["dev"], answer)
        except SystemExit as exc:
            self.assertNotIn("bad_message", str(exc))
            self.assertIn("did not end inside it", str(exc))
        self.assertLess(time.monotonic() - started, 30)  # the agreed bound; a loaded machine took 21.5 s

    def test_l3_a_seated_name_cannot_be_taken_over(self) -> None:
        self.dev.hold_until = time.monotonic() + 30  # freeze the sim while a stand-in member is seated
        self.dev.round.arena.members["dev-seat"] = {}
        try:
            with self.assertRaises(ValueError):
                self.dev.create_identity("seat", "hunter", new_public_key())
        finally:
            del self.dev.round.arena.members["dev-seat"]

    def test_join_predicts_fights_leaves_and_reads_a_signed_result(self) -> None:
        keeper = self.keeper()
        first = keeper.start("1")
        self.assertEqual(first["state"], "accepted", first)
        self.assertEqual(first["prediction_lock"]["state"], "prediction")
        players = snap.call(self.url + "/dev/players")
        self.assertEqual([(p["label"], p["fighter_id"]) for p in players], [("DEV", "dev-tester")])
        keeper.tick()
        self.dev.step(12)
        keeper.tick()
        self.assertEqual(keeper.summary()["you"]["state"], "ring")
        pushed = keeper.intent({"focus": "nearest", "loot": "nearest", "sig": "auto"})
        self.assertEqual(pushed["state"], "accepted", pushed)
        self.dev.step(10)  # the advertised 0.5 sim-second order spacing
        ended = keeper.intent({"leave": True})
        self.assertEqual(ended["state"], "accepted", ended)
        arena = self.dev.round.arena
        while arena.sim.state['tick'] < 1201:
            self.dev.step(min(20, 1201 - arena.sim.state['tick']))
            keeper.tick()
        result = keeper.result(0)
        self.assertTrue(result["signed"] and result["completed"], result)
        self.assertEqual((result["dev"], result["chain_result"]), (True, False))
        self.assertEqual(result["lives"][0]["prediction_lock"], "prediction")
        self.assertEqual(result["public_prediction_row"], "matches your private receipt")

    test_join_predicts_fights_leaves_and_reads_a_signed_result.manual_clock = True


class DevHostFlag(unittest.TestCase):
    """The DEV host says `dev_host=True` itself; a production server refuses the same `dev-` id."""

    def test_a_dev_join_is_seated_by_the_dev_host_and_the_same_id_is_refused_by_a_production_server(self) -> None:
        import test_dev_prefix as production  # its binding helper; the production server and its refusal live in server.py
        import test_server
        make = snap_local.make_contexts
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)

        def non_dev_deployment(port: int, index: int) -> tuple[dict, dict]:
            control, result = make(port, index)
            control["deployment_id"] = result["deployment_id"] = "local"  # no `dev-` prefix: only the flag can seat a DEV id
            return control, result

        snap_local.make_contexts = non_dev_deployment
        self.addCleanup(setattr, snap_local, "make_contexts", make)
        dev = snap_local.DevRoom(free_port(), tmp.name)
        arena = dev.round.arena
        self.assertFalse(arena.context["deployment_id"].startswith("dev-"), arena.context["deployment_id"])
        identity = dev.create_identity("tester", "hunter", new_public_key())
        self.assertTrue(arena.health()["dev_host"])
        seated = arena.bridge.reserve_life(production.binding(identity["nft_token_id"], context=arena.context))
        self.assertIn("life_id", seated, seated)
        comp = test_server.Composition()
        comp.setUp()
        self.addCleanup(comp.doCleanups)
        arena2 = comp.arena()  # the production composition: a plain deployment id, no dev_host flag
        self.assertFalse(arena2.dev_host)
        refused = arena2.bridge.reserve_life(production.binding("dev-tester"))  # the same id the DEV host just seated
        self.assertEqual(refused.get("code"), "banned", refused)


class Clock(unittest.TestCase):
    """Finding 3: a stall must not be followed by a burst of ticks that runs faster than 20 Hz."""

    def test_a_stalled_loop_resyncs_instead_of_bursting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dev = snap_local.DevRoom(free_port(), directory)
            stamps: list[float] = []
            real = dev.round.arena.advance
            dev.round.arena.advance = lambda *a, **k: (stamps.append(time.monotonic()), real(*a, **k))[1]

            async def go() -> None:
                asyncio.get_running_loop().call_later(1.0, lambda: time.sleep(0.9))  # block the loop for 18 ticks' worth
                await dev.run_clock(80)

            asyncio.run(go())
            self.assertEqual(len(stamps), 80)
            fastest = min(stamps[i + 10] - stamps[i] for i in range(len(stamps) - 10))
            self.assertGreater(fastest, 0.35, f"10 ticks in {fastest:.3f}s is faster than 20 Hz (0.5 s)")
            self.assertGreaterEqual(dev.resyncs, 1)


if __name__ == "__main__":
    unittest.main()
