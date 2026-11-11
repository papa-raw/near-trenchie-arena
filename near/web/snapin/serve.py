#!/usr/bin/env python3
"""serve.py: the DEV web server for the live arena page and the snap-in guide, on one loopback origin.

  python3 -I near/web/snapin/serve.py [--port 8181] [--arena http://127.0.0.1:8765]

It does two things, and nothing else:
  * serves the files under near/ (the arena page is /web/arena.html, the guide /web/snapin/index.html);
  * passes the room's HTTP routes (/room/..., /dev/identity, /dev/clock, /dev/players, /dev/health, /dev/corner, /snap/code..., /house/* reads)
    through to the DEV arena host (near/arena/snap_local.py), so the guide joins a fighter from the same origin.
    The host keeps its own rules (loopback Host header, JSON-only POSTs); this server adds no CORS and forwards
    no admin header, so /dev/shutdown is never reachable through it.

Hosted, nginx plays this part: one origin for the pages and the room. Loopback only; never expose this port.
"""
from __future__ import annotations

import argparse
import http.client
import mimetypes
import posixpath
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

NEAR = Path(__file__).resolve().parents[2]  # near/
PASS_GET = ("/room", "/room/", "/dev/clock", "/dev/players", "/dev/health", "/dev/terms", "/dev/corner", "/snap/code/", "/house/")
PASS_POST = ("/room/", "/dev/identity", "/snap/code")
KEEP_HEADERS = ("content-type", "x-dev-now", "x-dev-paused")
TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".json": "application/json", ".woff2": "font/woff2",
         ".css": "text/css", ".html": "text/html; charset=utf-8", ".png": "image/png", ".svg": "image/svg+xml"}


def passes(method: str, path: str) -> bool:
    rules = PASS_GET if method == "GET" else PASS_POST
    return any(path == r or (r.endswith("/") and path.startswith(r)) for r in rules)


def static_file(path: str) -> Path | None:
    """A file under near/ for this URL path, or None. No dotfiles, no traversal, no directory listings."""
    clean = posixpath.normpath(unquote(path))
    parts = [p for p in clean.split("/") if p]
    if not parts or any(p.startswith(".") or p == ".." for p in parts):
        return None
    f = NEAR.joinpath(*parts)
    try:
        f.resolve().relative_to(NEAR)
    except ValueError:
        return None
    return f if f.is_file() else None


def make_handler(arena: str, port_box: list):
    a = urlsplit(arena)
    a_host, a_port = a.hostname or "127.0.0.1", a.port or 80

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "trenchie-dev"

        def log_message(self, fmt, *args):  # quiet: one line per error only
            pass

        def own_host(self) -> bool:
            return self.headers.get("Host", "") in (f"127.0.0.1:{port_box[0]}", f"localhost:{port_box[0]}")

        def reply(self, status: int, body: bytes, ctype: str = "application/json", extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def fail(self, status: int, message: str) -> None:
            import json
            self.reply(status, json.dumps({"error": message}).encode())

        def forward(self, method: str, body: bytes | None) -> None:
            conn = http.client.HTTPConnection(a_host, a_port, timeout=30)
            headers = {"Host": f"{a_host}:{a_port}", "Connection": "close"}
            if method == "POST":
                headers["Content-Type"] = self.headers.get("Content-Type", "")
            try:
                conn.request(method, self.path, body=body, headers=headers)
                r = conn.getresponse()
                data = r.read()
            except OSError:
                return self.fail(502, f"the DEV arena at {arena} is not answering: start it with "
                                      "`python3 -I near/arena/snap_local.py`, then try again")
            finally:
                conn.close()
            self.reply(r.status, data, r.getheader("Content-Type", "application/json"),
                       {k: r.getheader(k) for k in ("X-Dev-Now", "X-Dev-Paused") if r.getheader(k) is not None})

        def do_GET(self) -> None:
            if not self.own_host():
                return self.fail(403, "host not allowed")
            path = urlsplit(self.path).path
            if passes("GET", path):
                return self.forward("GET", None)
            if path == "/":
                return self.reply(302, b"", "text/plain", {"Location": "/web/arena.html"})
            f = static_file(path)
            if f is None:
                return self.reply(404, b"not found", "text/plain")
            self.reply(200, f.read_bytes(), TYPES.get(f.suffix) or mimetypes.guess_type(f.name)[0] or "application/octet-stream")

        do_HEAD = do_GET

        def do_POST(self) -> None:
            if not self.own_host():
                return self.fail(403, "host not allowed")
            path = urlsplit(self.path).path
            if not passes("POST", path):
                return self.fail(404, "not found")
            size = int(self.headers.get("Content-Length") or 0)
            if not 0 <= size <= 65536:
                return self.fail(413, "body too large")
            self.forward("POST", self.rfile.read(size) if size else b"")

    return Handler


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8181)
    ap.add_argument("--arena", default="http://127.0.0.1:8765", help="the DEV arena host (snap_local.py)")
    args = ap.parse_args(argv)
    port_box = [args.port]
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(args.arena, port_box))
    port_box[0] = httpd.server_address[1]
    ws = "ws://" + urlsplit(args.arena).netloc
    print(f"serve: http://127.0.0.1:{port_box[0]}/web/arena.html?ws={ws} (guide: /web/snapin/index.html); "
          f"room routes pass to {args.arena}. Loopback only.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
