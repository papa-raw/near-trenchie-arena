"""The respawn corner files each life's pick under that life (/dev/corner last_life, snap_local capture_corner).

A keeper files 40/30/20/10 for its first life; after the KO its standing order changes to Brawler Zap with
25/25/25/25 and 20% for zero, which the keeper files for the next life. The corner's last life must carry the pick
filed for that life at every point: the first life's while the fighter is down, still after the next life starts,
and the next life's only once that life ends."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import snap
import snap_local

FIRST = {'one': 4000, 'two': 3000, 'three': 2000, 'four_plus': 1000}
NEXT = {'one': 2500, 'two': 2500, 'three': 2500, 'four_plus': 2500}


class CornerPick(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dev = snap_local.DevRoom(8765, self.tmp.name)

    def direct_call(self, url: str, method: str = 'GET', body=None, headers=None, timeout=60, seen=None):
        target = urlsplit(url)
        raw = json.dumps(body).encode() if isinstance(body, dict) else body or b''
        status, value = self.dev.route(method, target.path + ('?' + target.query if target.query else ''), raw, '127.0.0.1')
        if seen is not None:
            seen.update(now=self.dev.round.vnow(), at=time.monotonic(), paused=True)
        return value

    def corner(self, token: str) -> dict:
        status, value = self.dev.route('GET', '/dev/corner?fighter=' + token, b'', '127.0.0.1')
        self.assertEqual(status, 200, value)
        return value

    def knock_out(self, arena, token: str) -> None:
        fighter = arena.sim.state['fighters'][token]
        source = next(name for name in arena.sim._live() if name != token)
        fighter['hp'], fighter['shield'], fighter['shield_until'], fighter['invulnerable_until'] = 1, 0, 0, 0
        arena.sim.queue_hit(source, token, 1000000)
        arena.advance()

    def test_each_life_keeps_its_own_pick(self) -> None:
        with patch.object(snap, 'call', side_effect=self.direct_call):
            keeper = snap.Keeper(types.SimpleNamespace(url='http://127.0.0.1:8765', name='shoal', preset='hunter-lunge',
                                                       spread='40,30,20,10', zero=10))
            first = keeper.start('1')
            arena = self.dev.round.arena
            arena.advance(3)
            self.assertIsNone(self.corner(keeper.token)['last_life'])
            self.knock_out(arena, keeper.token)
            down = self.corner(keeper.token)
            self.assertEqual(down['last_life']['life_id'], first['life_id'])
            self.assertEqual(down['last_life']['prediction']['spread_bps'], FIRST)
            # the next life's pick differs in battle option, spread and zero
            keeper.order = dict(preset='brawler-zap', **snap.standing_order(None, '25,25,25,25', 20))
            for _ in range(600):
                keeper.tick()
                arena.advance()
                if arena.sim.state['fighters'][keeper.token]['state'] == 'alive':
                    break
            next_life = arena.members[keeper.token]['life_id']
            self.assertNotEqual(next_life, first['life_id'])
            self.assertEqual(arena.sim.state['fighters'][keeper.token]['state'], 'alive', 'the next life started')
            filed = arena.locks[next_life]['public']['pick']['payload']
            self.assertEqual((filed['spread_bps'], filed['zero_bps'], filed['loadout']['menu_row']), (NEXT, 2000, 'brawler-zap'))
            ring = self.corner(keeper.token)
            self.assertEqual(ring['last_life']['life_id'], first['life_id'], 'the next life running: the last life is still the first')
            self.assertEqual(ring['last_life']['prediction']['spread_bps'], FIRST, 'the first life keeps the first pick')
            self.knock_out(arena, keeper.token)
            ended = self.corner(keeper.token)
            self.assertEqual(ended['last_life']['life_id'], next_life)
            self.assertEqual(ended['last_life']['prediction'], dict(spread_bps=NEXT, zero_bps=2000), 'the next life carries its own pick')


if __name__ == '__main__':
    unittest.main()
