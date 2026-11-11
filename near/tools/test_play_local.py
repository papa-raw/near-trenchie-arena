"""make play: one command starts the DEV arena and the web server, prints READY, and SIGTERM stops both.

    python3 -I near/tools/test_play_local.py
"""
import os
import signal
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "near" / "tools"))
import play_local  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class PlayLocal(unittest.TestCase):
    def args(self, live=False):
        return type("A", (), {"live": live, "house": "keyed", "budget": "building", "arena_port": 9999})()

    def test_by_default_no_key_is_used_even_when_the_shell_and_the_file_hold_one(self):
        folder = Path(self.id().replace(".", "_")); folder.mkdir(exist_ok=True)
        (folder / "nearai.env").write_text("NEARAI_API_KEY=sk-file-key\n")
        real = play_local.CONFIG
        play_local.CONFIG = folder
        try:
            argv, child, notes = play_local.plan(self.args(), {**os.environ, play_local.KEY_ENV: "sk-shell-key"})
        finally:
            play_local.CONFIG = real
            (folder / "nearai.env").unlink(); folder.rmdir()
        self.assertEqual(argv[argv.index("--house") + 1], "keyed")
        self.assertNotIn(play_local.KEY_ENV, child)                       # the shell's key never reaches the host
        self.assertEqual(len([n for n in notes if n.startswith("house:")]), 1)
        self.assertIn("keyless", notes[0]); self.assertIn("LIVE=1", notes[0])
        self.assertFalse(any("sk-" in n for n in notes) or any("sk-" in a for a in argv))

    def test_live_loads_the_key_file_and_prints_its_path_and_the_cap_never_the_key(self):
        folder = Path(self.id().replace(".", "_")); folder.mkdir(exist_ok=True)
        (folder / "nearai.env").write_text("export NEARAI_API_KEY=sk-file-key\n")
        os.chmod(folder / "nearai.env", 0o644)
        env = {k: v for k, v in os.environ.items() if k != play_local.KEY_ENV}
        real = play_local.CONFIG
        play_local.CONFIG = folder
        try:
            with self.assertRaisesRegex(SystemExit, "readable by others; fix it with: chmod 600"):
                play_local.plan(self.args(live=True), env)
        finally:
            play_local.CONFIG = real
        os.chmod(folder / "nearai.env", 0o600)
        real = play_local.CONFIG
        play_local.CONFIG = folder
        try:
            argv, child, notes = play_local.plan(self.args(live=True), env)
            with self.assertRaisesRegex(SystemExit, "--live needs NEARAI_API_KEY"):
                (folder / "nearai.env").unlink()
                play_local.plan(self.args(live=True), env)
        finally:
            play_local.CONFIG = real
            folder.rmdir()
        self.assertEqual(argv[argv.index("--house") + 1], "live")
        self.assertEqual(child[play_local.KEY_ENV], "sk-file-key")
        self.assertIn(str(folder / "nearai.env"), notes[0]); self.assertIn("$2", notes[0])
        self.assertFalse(any("sk-file-key" in n for n in notes) or any("sk-file-key" in a for a in argv))
        guard = [n for n in notes if "guard" in n]
        self.assertTrue(guard)

    def test_the_readiness_probe_reads_the_whole_answer(self):
        import http.server, threading
        errors = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"x" * 200_000
                self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        srv.handle_error = lambda request, addr: errors.append(addr)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            for _ in range(5):
                self.assertTrue(play_local.answers(srv.server_address[1], "/web/arena.html"))
            time.sleep(0.5)
        finally:
            srv.shutdown()
        self.assertEqual(errors, [])

    def test_make_play_takes_port_house_and_live(self):
        out = subprocess.run(["make", "-n", "play", "PORT=8282", "ARENA_PORT=8866", "HOUSE=dev", "LIVE=1"], cwd=ROOT,
                             capture_output=True, text=True).stdout
        for part in ("--live", "--web-port 8282", "--arena-port 8866", "--house dev", "exec "):
            self.assertIn(part, out)

    def test_only_live_1_goes_live(self):
        def dry(*extra):
            return subprocess.run(["make", "-n", "play", *extra], cwd=ROOT, capture_output=True, text=True).stdout
        for off in ("LIVE=0", "LIVE=no", "LIVE=false", "LIVE=", "LIVE=off"):
            self.assertNotIn("--live", dry(off), off)
        self.assertNotIn("--live", dry())
        self.assertIn("--live", dry("LIVE=1"))

    def test_it_starts_everything_and_sigterm_stops_everything(self):
        a, w = free_port(), free_port()
        env = {k: v for k, v in os.environ.items() if k != play_local.KEY_ENV}
        p = subprocess.Popen([sys.executable, "-B", str(ROOT / "near/tools/play_local.py"), "--arena-port", str(a),
                              "--web-port", str(w), "--house", "dev"], cwd=ROOT, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        out, ready = [], False
        end = time.monotonic() + 180
        while time.monotonic() < end:
            line = p.stdout.readline()
            if not line:
                break
            out.append(line)
            if "play: READY" in line:
                ready = True
                break
        self.assertTrue(ready, "".join(out)[-2000:])
        time.sleep(2.5)                                   # the old probe's reset traceback came ~1.5 s after READY
        p.send_signal(signal.SIGINT)                      # what Ctrl-C sends
        rest, _ = p.communicate(timeout=60)
        text = "".join(out) + rest
        self.assertNotIn("Traceback", text)
        self.assertLess(text.index("play: stopping (SIGINT)"), text.index("nothing left running"))
        self.assertEqual(p.returncode, 0, text[-2000:])
        self.assertIn(f"/web/arena.html", text)
        self.assertIn("nothing left running", text)
        self.assertTrue(play_local.port_free(a) and play_local.port_free(w), "a port is still held")


if __name__ == "__main__":
    unittest.main()
