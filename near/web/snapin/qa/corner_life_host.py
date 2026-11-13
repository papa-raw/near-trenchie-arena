"""Real DEV HTTP host with a case-only clock/KO route; never imported by production."""
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


# Keep one real house opponent: there is a free seat and low-crowd respawns need no 45-second wait.
class OneHouse(snap_local.DevHouse):
    def poll(self, control, tick, roster, count, view):
        count = max(0, 1 - sum(m['profile']['house'] for m in self.arena.members.values()))
        return super().poll(control, tick, roster, count, view)


class CornerHost(snap_local.DevRoom):
    def make_house(self, context):
        return OneHouse(context)

    async def run_clock(self, ticks=None):
        self.hold_until = float('inf')
        while not self.stop:
            await asyncio.sleep(0.01)

    def route(self, method, target, body, ip, admin=''):
        if method == 'POST' and urlsplit(target).path == '/case/step':
            args = json.loads(body)
            arena = self.round.arena
            token = args.get('fighter')
            if args.get('ko'):
                f = arena.sim.state['fighters'][token]
                source = next(n for n in arena.sim._live() if n != token)
                f['hp'], f['shield'], f['shield_until'], f['invulnerable_until'] = 1, 0, 0, 0
                arena.sim.queue_hit(source, token, 1000000)
            for _ in range(args.get('ticks', 1)):
                fighter = arena.sim.state['fighters'].get(token)
                if fighter is not None and not args.get('ko'):
                    fighter['invulnerable_until'] = arena.sim.state['tick'] + 100000
                arena.advance()
            self.refresh_frames()
            self.publish()
            self.hold_until = float('inf')
            return 200, {'tick': arena.sim.state['tick'], 'corner': self.corner(token) if token else None}
        try:
            return super().route(method, target, body, ip, admin)
        finally:
            self.hold_until = float('inf')


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT / 'near/web/snapin'))
    import serve as web

    async def main():
        with tempfile.TemporaryDirectory() as tmp:
            dev = CornerHost(18734, tmp)
            loop = asyncio.get_running_loop()
            base = web.make_handler('http://127.0.0.1:18734', [18734])
            class Handler(base):
                def forward(self, method, body):
                    async def route():
                        status, value = dev.route(method, self.path, body or b'', '127.0.0.1')
                        return status, value, dev.round.vnow()
                    status, value, now = asyncio.run_coroutine_threadsafe(route(), loop).result(30)
                    try:
                        self.reply(status, json.dumps(value).encode(), extra={'X-Dev-Now': str(now), 'X-Dev-Paused': '1'})
                    except ConnectionError:
                        pass  # navigation can cancel an in-flight poll
                def do_POST(self):
                    if urlsplit(self.path).path == '/case/step':
                        return self.forward('POST', self.rfile.read(int(self.headers['Content-Length'])))
                    return super().do_POST()
            server = web.BoundedHTTPServer(('127.0.0.1', 18734), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            print('corner-life-host: 18734', flush=True)
            try:
                await dev.run_clock()
            finally:
                server.shutdown()
                server.server_close()
    asyncio.run(main())
