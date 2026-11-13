"""Local DEV HTTP host: real room/rules reads, with a refused browser registration fixture."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT), str(ROOT / 'near/arena')]
import snap_local

# Sparse worktrees may read the installed, immutable room schema from their primary checkout.
if os.environ.get('SNAP_CASE_ROOM_ROOT'):
    original_contexts = snap_local.make_contexts
    def contexts(*args, **kwargs):
        with patch.object(snap_local, 'ROOT', Path(os.environ['SNAP_CASE_ROOM_ROOT'])):
            return original_contexts(*args, **kwargs)
    snap_local.make_contexts = contexts


class RefusedJoinHost(snap_local.DevRoom):
    async def run_clock(self, ticks=None):
        self.hold_until = float('inf')
        while not self.stop:
            await asyncio.sleep(0.01)

    def route(self, method, target, body, ip, admin=''):
        if method == 'POST' and urlsplit(target).path == '/dev/identity':
            print('bare-page-host: refused browser registration', flush=True)
            return 400, {'error': "that sheet is not the Trenchie's persona; play the persona it was minted with"}
        return super().route(method, target, body, ip, admin)


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT / 'near/web/snapin'))
    import serve as web

    async def main():
        with tempfile.TemporaryDirectory() as tmp:
            dev = RefusedJoinHost(18734, tmp)
            loop = asyncio.get_running_loop()
            base = web.make_handler('http://127.0.0.1:18734', [18734])
            class Handler(base):
                def forward(self, method, body):
                    async def route():
                        status, value = dev.route(method, self.path, body or b'', '127.0.0.1')
                        return status, value, dev.round.vnow()
                    status, value, now = asyncio.run_coroutine_threadsafe(route(), loop).result(30)
                    self.reply(status, json.dumps(value).encode(), extra={'X-Dev-Now': str(now), 'X-Dev-Paused': '1'})
            server = web.BoundedHTTPServer(('127.0.0.1', 18734), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            print('bare-page-host: 18734', flush=True)
            try:
                await dev.run_clock()
            finally:
                server.shutdown()
                server.server_close()
    asyncio.run(main())
