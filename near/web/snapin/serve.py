#!/usr/bin/env python3
"""serve.py: the DEV web server for the live arena page and the snap-in guide, on one loopback origin.

  python3 -I near/web/snapin/serve.py [--port 8181] [--arena http://127.0.0.1:8765]

It does two things, and nothing else:
  * serves the files under near/ (the arena page is /web/arena.html, the guide /web/snapin/index.html);
  * passes the room's HTTP routes (/room/..., /dev/identity, /dev/clock, /dev/players, /dev/health, /dev/corner, /snap/code..., /house/* reads)
    through to the DEV arena host (near/arena/snap_local.py), so the guide joins a fighter from the same origin.
    The host keeps its own rules (loopback Host header, JSON-only POSTs); this server adds no CORS and forwards
    no admin header, so /dev/shutdown is never reachable through it.

Loopback only; never expose this port directly. Hosted (`--public-origin https://<name>`, behind nginx in the
arena's container): the public name joins the Host check and nginx's X-Real-IP is passed on to the arena host, so
its per-address limits see each visitor. Still no admin header and no /dev/shutdown.
"""
from __future__ import annotations

import argparse
import http.client
import mimetypes
import posixpath
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

NEAR = Path(__file__).resolve().parents[2]  # near/
sys.path.insert(0, str(NEAR.parent))
from near.arena.client_bundle import build_client_bundle
PASS_GET = ("/room", "/room/", "/dev/clock", "/dev/players", "/dev/health", "/dev/terms", "/dev/corner", "/snap/code/", "/house/")
PASS_POST = ("/room/", "/dev/identity", "/snap/code")
KEEP_HEADERS = ("content-type", "x-dev-now", "x-dev-paused")
TYPES = {".js": "text/javascript", ".mjs": "text/javascript", ".json": "application/json", ".woff2": "font/woff2",
         ".css": "text/css", ".html": "text/html; charset=utf-8", ".png": "image/png", ".svg": "image/svg+xml"}
HTTP_WORKERS = 32  # leave room under the container's 256-PID cap for the arena, house and curl
CLIENT_TIMEOUT_S = 10


class BoundedHTTPServer(ThreadingHTTPServer):
    """Refuse excess clients before starting threads; idle sockets cannot retain a worker forever."""

    def __init__(self, server_address: tuple[str, int], handler: type[BaseHTTPRequestHandler],
                 bind_and_activate: bool = True, *, max_workers: int = HTTP_WORKERS) -> None:
        self.slots = threading.BoundedSemaphore(max_workers)
        super().__init__(server_address, handler, bind_and_activate)

    def process_request(self, request: socket.socket, client_address: tuple[str, int]) -> None:
        if not self.slots.acquire(blocking=False):
            try:
                request.settimeout(0.1)  # overload replies must not stall the accept loop
                request.sendall(b'HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\n'
                                b'Retry-After: 1\r\nConnection: close\r\n\r\n')
            except OSError:
                self.close_request(request)
            else:
                self.shutdown_request(request)
            return
        try:
            request.settimeout(CLIENT_TIMEOUT_S)
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request: socket.socket, client_address: tuple[str, int]) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


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


def make_handler(arena: str, port_box: list, public_host: str | None = None):
    a = urlsplit(arena)
    a_host, a_port = a.hostname or "127.0.0.1", a.port or 80

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "trenchie-dev"

        def log_message(self, fmt, *args):  # quiet: one line per error only
            pass

        def own_host(self) -> bool:
            return self.headers.get("Host", "") in (f"127.0.0.1:{port_box[0]}", f"localhost:{port_box[0]}",
                                                    *((public_host,) if public_host else ()))

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
            if public_host and self.headers.get("X-Real-IP"):
                headers["X-Real-IP"] = self.headers["X-Real-IP"]  # set by nginx; the arena host validates it
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
                       {k: r.getheader(k) for k in ("X-Dev-Now", "X-Dev-Paused", "X-Log-Hash", "X-Log-Window", "X-Log-Max-Bytes")
                        if r.getheader(k) is not None})

        def do_GET(self) -> None:
            if not self.own_host():
                return self.fail(403, "host not allowed")
            path = urlsplit(self.path).path
            if passes("GET", path):
                return self.forward("GET", None)
            if path == "/":
                return self.reply(302, b"", "text/plain", {"Location": "/web/arena.html"})
            if path == "/snap-client.zip":
                try:
                    data = build_client_bundle()
                except (OSError, ValueError):
                    return self.fail(503, "client download unavailable; try again shortly")
                return self.reply(200, data, "application/zip", {"Cache-Control": "no-store"})
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
    ap.add_argument("--bind", default="127.0.0.1", help="the listen address (hosted in a container: 0.0.0.0)")
    ap.add_argument("--public-origin", default=None, help="hosted behind nginx: https://<name>")
    args = ap.parse_args(argv)
    public_host = None
    if args.public_origin is not None:
        if not args.public_origin.startswith("https://") or "/" in args.public_origin[len("https://"):]:
            raise SystemExit("serve: --public-origin is https://<name>, with no path")
        public_host = args.public_origin[len("https://"):]
    port_box = [args.port]
    httpd = BoundedHTTPServer((args.bind, args.port), make_handler(args.arena, port_box, public_host))
    port_box[0] = httpd.server_address[1]
    ws = "ws://" + urlsplit(args.arena).netloc
    if public_host:
        print(f"serve: listening on {args.bind}:{port_box[0]}, hosted as {args.public_origin}/web/arena.html; "
              f"room routes pass to {args.arena}.", flush=True)
    else:
        print(f"serve: http://127.0.0.1:{port_box[0]}/web/arena.html?ws={ws} (guide: /web/snapin/index.html); "
              f"room routes pass to {args.arena}. Loopback only.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    sys.exit(main())
