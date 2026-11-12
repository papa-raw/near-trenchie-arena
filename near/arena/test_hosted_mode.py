"""Hosted mode (make play behind nginx): the public name, the visitor's address, no admin route, persistent house state."""
from __future__ import annotations

import asyncio
import http.client
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "web" / "snapin")]
import snap_local  # noqa: E402
import serve as web_serve  # noqa: E402

ORIGIN = "https://neartrenchies.xyz"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(port: int, method: str, path: str, host: str, body: bytes | None = None, headers: dict | None = None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    conn.request(method, path, body, {"Host": host, **(headers or {})})
    reply = conn.getresponse()
    data = reply.read()
    conn.close()
    try:
        return reply.status, json.loads(data or b"{}")
    except json.JSONDecodeError:
        return reply.status, data


class HostedMode(unittest.TestCase):
    def test_public_name_visitor_address_no_admin_route_and_state_that_survives_a_restart(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        state = Path(tmp.name) / "state"
        for i in range(6):  # six earlier runs: the four newest are kept, and a non-run directory is never touched
            (state / "runs" / f"2026111{i}T000000Z").mkdir(parents=True)
        (state / "runs" / "keep-me").mkdir()
        run = snap_local.new_run_dir(state)
        kept = {p.name for p in (state / "runs").iterdir()}
        self.assertEqual(kept, {"20261112T000000Z", "20261113T000000Z", "20261114T000000Z", "20261115T000000Z",
                                run.name, "keep-me"})

        with self.assertRaises(ValueError):
            snap_local.DevRoom(free_port(), str(run), public_origin="https://neartrenchies.xyz/path")
        port = free_port()
        dev = snap_local.DevRoom(port, str(run), house="keyed", public_origin=ORIGIN, state_dir=str(state))
        ready = threading.Event()
        thread = threading.Thread(target=lambda: asyncio.run(snap_local.serve(dev, ready=lambda p: ready.set())), daemon=True)
        thread.start()
        self.assertTrue(ready.wait(60), "host did not start")

        def stop() -> None:
            dev.stop = True
            thread.join(15)
        self.addCleanup(stop)

        # The house's predictions log lives in the state dir, not in this start's run dir.
        self.assertEqual(dev.house_log.path.parent, state / "house")
        # The public name is the room's audience, and the Host check takes it alongside the loopback name.
        self.assertEqual(dev.round.context["audience"], ORIGIN + "/room#control")
        self.assertEqual(call(port, "GET", "/dev/health", "neartrenchies.xyz")[0], 200)
        self.assertEqual(call(port, "GET", "/dev/health", f"127.0.0.1:{port}")[0], 200)
        self.assertEqual(call(port, "GET", "/dev/health", "evil.example")[0], 403)
        # The admin route does not exist, even with the right token.
        status, body = call(port, "POST", "/dev/shutdown", "neartrenchies.xyz", b"{}",
                            {"Content-Type": "application/json", "X-Dev-Admin": dev.admin})
        self.assertEqual((status, body), (404, {"error": "not found"}))
        self.assertFalse(dev.stop)
        # An agent's code points at the public origin and the agent's own clone.
        code = dev.issue_code({"agent": "claude-code", "name": "tester"})
        self.assertEqual(code["snap_url"], ORIGIN + "/SNAP.md")
        # The door starts battle mode on the same trenchie: one live session with the code and an orders fifo, never join.
        self.assertEqual(code["command"], f"python3 -I near/arena/snap.py --url {ORIGIN} live --code {code['code']} --preset hunter"
                                          ' --accept-terms 1 --fifo "$PWD/orders.fifo"')
        self.assertNotIn(" join ", code["command"])
        # The visitor's address is nginx's X-Real-IP; a malformed one falls back to the peer.
        seen = []
        original = dev.route
        dev.route = lambda method, target, body, ip, admin="": (seen.append(ip), original(method, target, body, ip, admin))[1]
        call(port, "GET", "/dev/clock", "neartrenchies.xyz", headers={"X-Real-IP": "203.0.113.7"})
        call(port, "GET", "/dev/clock", "neartrenchies.xyz", headers={"X-Real-IP": "not an address"})
        self.assertEqual(seen, ["203.0.113.7", "127.0.0.1"])

        # The web server in front: the public name passes its Host check, and X-Real-IP reaches the arena host.
        web_port = free_port()
        httpd = web_serve.ThreadingHTTPServer(("127.0.0.1", web_port),
                                              web_serve.make_handler(f"http://127.0.0.1:{port}", [web_port], "neartrenchies.xyz"))
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        seen.clear()
        self.assertEqual(call(web_port, "GET", "/dev/clock", "neartrenchies.xyz", headers={"X-Real-IP": "198.51.100.9"})[0], 200)
        self.assertEqual(seen, ["198.51.100.9"])
        self.assertEqual(call(web_port, "GET", "/dev/clock", "evil.example")[0], 403)
        self.assertEqual(call(web_port, "POST", "/dev/shutdown", "neartrenchies.xyz", b"{}",
                              {"Content-Type": "application/json"})[0], 404)


    def test_the_live_house_spend_survives_a_restart_through_the_state_dir(self) -> None:
        """A live house's meter is <state>/house/spend.json: a second start in a fresh run dir reads the day's spend back."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        state = Path(tmp.name) / "state"

        def start() -> snap_local.DevRoom:
            # A scripted client stands in for the model: no key and no call; only the meter is under test.
            return snap_local.DevRoom(free_port(), str(snap_local.new_run_dir(state)), house="live",
                                      house_client=snap_local.house_live.NoModel(), budget_mode="building",
                                      public_origin=ORIGIN, state_dir=str(state))
        first = start()
        day = first.house_budget.day()
        first.house_budget.meter.add(day, 1_250_000)  # $1.25 of the building cap's $2
        self.assertEqual(first.house_budget.meter.path, state / "house" / "spend.json")
        second = start()  # the restart: a new run dir, the same state dir
        self.assertNotEqual(second.data_dir, first.data_dir)
        self.assertEqual(second.house_budget.meter.today(day), 1_250_000)
        self.assertEqual(second.house_budget.state()["spent_today_microusd"], 1_250_000)


if __name__ == "__main__":
    unittest.main()
