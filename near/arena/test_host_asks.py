"""The five guide preset ids and the public local respawn corner."""
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
import presets
import snap
import snap_local

IDS = ('brawler-swing', 'hunter-lunge', 'survivor-beam', 'looter-lob', 'brawler-zap')


class HostAsks(unittest.TestCase):
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

    def keeper(self, preset: str) -> snap.Keeper:
        return snap.Keeper(types.SimpleNamespace(url='http://127.0.0.1:8765', name='shoal', preset=preset, spread='40,30,20,10', zero=10))

    def test_five_guide_ids_reach_identity_and_signed_prediction_with_exact_live_kits(self) -> None:
        with patch.object(snap, 'call', side_effect=self.direct_call):
            for index, preset in enumerate(IDS):
                with self.subTest(preset=preset):
                    self.dev = snap_local.DevRoom(8765, str(Path(self.tmp.name) / preset))
                    keeper = self.keeper(preset)
                    self.assertEqual(keeper.ident['preset'], preset)
                    first = keeper.start('1')
                    self.assertEqual(first['state'], 'accepted')
                    expected = presets.preset_kit(self.dev.round.arena.sim.rules, index)
                    member = self.dev.round.arena.members[keeper.token]
                    self.assertEqual(member['profile']['loadout'], expected['loadout'])
                    self.assertEqual(member['profile']['style'], expected['style'])
                    for _ in range(3):
                        self.dev.round.arena.advance()
                    fighter = self.dev.round.arena.sim.state['fighters'][keeper.token]
                    self.assertEqual(fighter['equipped'], expected['loadout'])
                    self.assertEqual(fighter['style'], expected['style'])
            unknown = self.direct_call('http://127.0.0.1:8765/dev/identity', 'POST', dict(name='bad', preset='invented', public_key=''))
            self.assertTrue(all(p in unknown['error'] for p in IDS), unknown)
            raw = json.dumps(dict(kind='prediction', payload=dict(loadout=dict(menu_row='invented', bag_serials=[])))).encode()
            status, refused = self.dev.route('POST', '/room/control/frame?cid=unknown', raw, '127.0.0.1')
            self.assertEqual(status, 400)
            self.assertTrue(all(p in refused['error'] for p in IDS), refused)

    def test_corner_projects_real_timer_floor_and_last_life_and_names_untracked_fields(self) -> None:
        with patch.object(snap, 'call', side_effect=self.direct_call):
            keeper = self.keeper('hunter')
            keeper.start('1')
            arena = self.dev.round.arena
            status, waiting = self.dev.route('GET', '/dev/corner?fighter=' + keeper.token, b'', '127.0.0.1')
            self.assertTrue(any(row['kind'] == 'respawn_pick' for row in waiting['pending']))
            arena.advance(3)
            status, current = self.dev.route('GET', '/dev/corner?fighter=' + keeper.token, b'', '127.0.0.1')
            self.assertEqual(status, 200, current)
            self.assertEqual(current['state'], 'ring')
            self.assertIsNone(current['respawn_at_ms'])
            self.assertIsNone(current['last_life'])
            self.assertEqual(set(('fighter_id','state','respawn_at_ms','last_life','taken','floor','pending','untracked')) - set(current), set())
            self.assertIn('taken', current['untracked'])
            rare = next(row for row, item in arena.sim.rules['items'].items() if item['tier'] == 'rare')
            drop = arena.sim.drop_item(rare, 50, 60, keeper.token, False)
            arena.sim.drop_item(rare, 70, 80, 'another-shoal', False)
            status, current = self.dev.route('GET', '/dev/corner?fighter=' + keeper.token, b'', '127.0.0.1')
            self.assertEqual(len(current['floor']), 1)
            self.assertEqual(current['floor'][0]['item_id'], rare)
            self.assertEqual(current['floor'][0]['owner'], keeper.token)
            expected_timer = self.dev.round.base + arena.sim.state['drops'][drop]['expires_at'] * 50
            self.assertEqual(current['floor'][0]['returns_at_ms'], expected_timer)
            fighter = arena.sim.state['fighters'][keeper.token]
            source = next(name for name in arena.sim._live() if name != keeper.token)
            fighter['hp'], fighter['shield'], fighter['shield_until'], fighter['invulnerable_until'] = 1, 0, 0, 0
            arena.sim.queue_hit(source, keeper.token, 1000000)
            arena.advance()  # the production advance hook, not a test callback, captures this life
            self.assertEqual(arena.sim.state['fighters'][keeper.token]['state'], 'bench')
            status, down = self.dev.route('GET', '/dev/corner?fighter=' + keeper.token, b'', '127.0.0.1')
            self.assertEqual(down['state'], 'down')
            self.assertEqual(down['respawn_at_ms'], self.dev.round.base + fighter['respawn_at'] * 50)
            self.assertEqual(down['last_life']['life_id'], keeper.life_id)
            self.assertEqual(down['last_life']['ended'], 'ko')
            self.assertEqual(down['last_life']['ended_by'], source)
            self.assertEqual(down['last_life']['prediction']['zero_bps'], 1000)
            bad_status, bad = self.dev.route('GET', '/dev/corner?fighter=missing', b'', '127.0.0.1')
            self.assertEqual(bad_status, 400)
            self.assertIn('/dev/players', bad['error'])


if __name__ == '__main__':
    unittest.main()
