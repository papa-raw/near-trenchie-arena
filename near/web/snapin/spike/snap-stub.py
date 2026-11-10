#!/usr/bin/env -S python3 -I
"""STUB, NOT THE REAL SNAP ENDPOINT. W2 spike (task r3-snapin-screens).

No hosted snap endpoint exists yet (SNAP.md asserts no origin; room/service.py serves /room/* only), so
providers.js SnapProviders.snap.* is written against this contract and this loopback stub answers it:
  POST /snap/code            {agent, name}  -> {code, expires_at (ms), snap_url, stub:true}
  GET  /snap/code/<code>                    -> {joined, expired}        (404 when unknown or past expiry)
  POST /snap/_join           {code}         -> marks the code joined (stands in for the agent arriving)
  GET  /SNAP.md                             -> a one-line stand-in
Codes are one-time, expire after 300 s, and are low-entropy WORD-NNN: fine for a stub, not a design.
Binds 127.0.0.1 only. Usage: python3 -I snap-stub.py [port]   (default 8832). Ctrl-C or kill to stop.
"""
import json, secrets, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8832
WORDS = ["CORAL", "KELP", "BRINE", "DRIFT", "SHELL", "TIDE", "WRACK", "PEBBLE"]
CODES = {}  # code -> {"expires": ms, "joined": bool, "agent": str}


class H(BaseHTTPRequestHandler):
    def _send(self, status, obj, ctype="application/json"):
        body = (json.dumps(obj) if ctype == "application/json" else obj).encode()
        self.send_response(status)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(body)))
        o = self.headers.get("Origin", "")
        if o.startswith(("http://127.0.0.1:", "http://localhost:")):  # loopback pages only
            self.send_header("access-control-allow-origin", o)
            self.send_header("access-control-allow-headers", "content-type")
            self.send_header("access-control-allow-methods", "GET,POST,OPTIONS")
        self.send_header("x-snap-stub", "1")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("content-length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def do_OPTIONS(self):
        self._send(204, {})

    def do_GET(self):
        if self.path == "/SNAP.md":
            return self._send(200, "# SNAP.md (STUB stand-in for the spike)\n", "text/markdown")
        if self.path.startswith("/snap/code/"):
            c = CODES.get(self.path.rsplit("/", 1)[1])
            if not c or c["expires"] < time.time() * 1000:
                return self._send(404, {"error": "unknown or expired code", "expired": True})
            return self._send(200, {"joined": c["joined"], "expired": False})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        b = self._body()
        if self.path == "/snap/code":
            if b.get("agent") not in ("claude-code", "codex"):
                return self._send(400, {"error": "agent must be claude-code or codex"})
            code = f"{secrets.choice(WORDS)}-{secrets.randbelow(900) + 100}"
            CODES[code] = {"expires": int(time.time() * 1000) + 300_000, "joined": False, "agent": b["agent"]}
            return self._send(200, {"code": code, "expires_at": CODES[code]["expires"],
                                    "snap_url": f"http://127.0.0.1:{PORT}/SNAP.md", "stub": True})
        if self.path == "/snap/_join":
            c = CODES.get(b.get("code"))
            if not c:
                return self._send(404, {"error": "unknown code"})
            c["joined"] = True
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"snap-stub.py: STUB (not the real endpoint) on http://127.0.0.1:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
