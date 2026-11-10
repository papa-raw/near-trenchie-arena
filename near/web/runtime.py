"""Loopback read-only reviewer desk. No wallet, consent or game write routes."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from near.web.evidence import read_evidence

ASSETS = Path(__file__).resolve().parent
STATIC = {
    '/': (ASSETS / 'index.html', 'text/html; charset=utf-8'),
    '/index.html': (ASSETS / 'index.html', 'text/html; charset=utf-8'),
    '/desk.js': (ASSETS / 'desk.js', 'text/javascript; charset=utf-8'),
    '/desk.css': (ASSETS / 'desk.css', 'text/css; charset=utf-8'),
    '/SNAP.md': (ROOT / 'near/SNAP.md', 'text/plain; charset=utf-8'),
    '/README.md': (ASSETS / 'README.md', 'text/plain; charset=utf-8'),
    '/assets/arena.png': (ROOT / 'near/members/arena.png', 'image/png'),
}
for name in ('Fredoka-var.woff2', 'LilitaOne-400.woff2', 'SpaceMono-400.woff2'):
    STATIC['/assets/' + name] = (ROOT / 'near/members/fonts' / name, 'font/woff2')


class DeskHandler(BaseHTTPRequestHandler):
    directory: Path | None = None

    def log_message(self, format: str, *args: object) -> None:
        return  # The local reviewer server keeps no visitor/request logs.

    def reply(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return  # Navigating away can close an otherwise completed read.

    def json_reply(self, status: int, value: dict) -> None:
        self.reply(status, json.dumps(value).encode(), 'application/json; charset=utf-8')

    def do_GET(self) -> None:
        origin = f'http://127.0.0.1:{self.server.server_port}'
        if (self.headers.get('Host') != origin.removeprefix('http://')
                or self.headers.get('Origin') not in (None, origin)
                or self.headers.get('Sec-Fetch-Site') == 'cross-site'):
            self.json_reply(403, dict(error='same_origin_required'))
            return
        path = urlsplit(self.path).path
        if path == '/api/evidence':
            self.json_reply(200, read_evidence(self.directory))
            return
        asset = STATIC.get(path)
        if asset is None:
            self.json_reply(404, dict(error='not_found'))
            return
        try:
            body = asset[0].read_bytes()
        except OSError:
            self.json_reply(503, dict(error='asset_unavailable'))
            return
        self.reply(200, body, asset[1])

    def do_POST(self) -> None:
        self.json_reply(405, dict(error='read_only_desk'))


def desk_server(directory: Path | None = None, *, port: int = 0) -> ThreadingHTTPServer:
    """Bind only loopback and expose an explicit static allowlist/public facts."""
    class BoundHandler(DeskHandler):
        pass
    BoundHandler.directory = directory
    return ThreadingHTTPServer(('127.0.0.1', port), BoundHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo-dir', type=Path, default=ROOT / 'near/.demo')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    server = desk_server(args.demo_dir, port=args.port)
    print(f'Reviewer desk: http://127.0.0.1:{server.server_port}', flush=True)
    print('Synthetic local evidence only. Hosted arena and chain check pending.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
