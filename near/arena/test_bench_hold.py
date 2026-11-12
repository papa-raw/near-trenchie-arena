"""Pat's Q5 bench hold and item 55's swaps: a KO'd trenchie stays on the bench until its player sends it back in,
the 45 s timer stops while it is held, and gear changes from the bag only on the bench. Board 1's panel reads it all
from /dev/corner (bench, events, hp)."""
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


class BenchHold(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dev = snap_local.DevRoom(8765, self.tmp.name)
        self.patch = patch.object(snap, 'call', side_effect=self.direct_call)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.keeper = snap.Keeper(types.SimpleNamespace(url='http://127.0.0.1:8765', name='shoal', preset='hunter',
                                                        spread='40,30,20,10', zero=10))
        self.keeper.start('1')
        self.arena = self.dev.round.arena
        self.arena.advance(3)
        self.me = self.keeper.token

    def direct_call(self, url: str, method: str = 'GET', body=None, headers=None, timeout=60, seen=None):
        target = urlsplit(url)
        raw = json.dumps(body).encode() if isinstance(body, dict) else body or b''
        status, value = self.dev.route(method, target.path + ('?' + target.query if target.query else ''), raw, '127.0.0.1')
        if seen is not None:
            seen.update(now=self.dev.round.vnow(), at=time.monotonic(), paused=True)
        return value

    def corner(self) -> dict:
        status, value = self.dev.route('GET', '/dev/corner?fighter=' + self.me, b'', '127.0.0.1')
        self.assertEqual(status, 200, value)
        return value

    def play(self, ticks: int) -> None:
        """Advance the sim with the keeper renewing its lease, as an open page does."""
        while ticks > 0:
            step = min(ticks, 50)
            self.arena.advance(step)
            self.keeper.tick()
            ticks -= step

    def fighter(self) -> dict:
        return self.arena.sim.state['fighters'][self.me]

    def knock_out(self) -> None:
        f = self.fighter()
        source = next(name for name in self.arena.sim._live() if name != self.me)
        f['hp'], f['shield'], f['shield_until'], f['invulnerable_until'] = 1, 0, 0, 0
        self.arena.sim.queue_hit(source, self.me, 1000000)
        self.arena.advance()
        self.assertEqual(self.fighter()['state'], 'bench')
        self.keeper.tick()  # files the next life's prediction, as the browser's keeper does at once

    def full_ring(self) -> None:
        """Isolate the timer: a ring short of fighters pulls a benched one in early by design (ring_min)."""
        real = self.arena._ring_load
        floor = self.arena.sim.rules['ring_min']
        patcher = patch.object(self.arena, '_ring_load', lambda: max(real(), floor))
        patcher.start()
        self.addCleanup(patcher.stop)

    def bench(self, payload: dict) -> dict:
        reply = self.keeper.client.control('bench', payload, life_id=self.keeper.life_id)
        self.assertEqual(reply['kind'], 'bench')
        return reply['ack']

    def test_a_held_trenchie_sits_out_past_45_s_and_send_back_in_resumes_the_stopped_timer(self) -> None:
        respawn = self.arena.sim.rules['respawn_ticks']
        self.full_ring()
        ack = self.bench({'hold': True})  # armed in the ring: applies at the next KO
        self.assertEqual(ack['type'], 'bench_ack')
        self.assertEqual(ack['status'], 'applied', ack)
        self.assertTrue(ack['bench']['hold'])
        self.assertFalse(ack['bench']['held'])
        self.knock_out()  # the KO tick itself sets respawn_at; the hold starts on the next tick
        self.play(100)
        before = self.corner()
        self.assertEqual(before['state'], 'down')
        self.assertTrue(before['bench']['held'])
        self.assertIsNone(before['bench']['respawn_in_ms'])
        frozen = (respawn - 1) * 1000 // self.arena.sim.rules['tick_hz']
        self.assertEqual(before['bench']['remaining_ms'], frozen)
        self.play(respawn + 200)  # well past 45 s
        self.assertEqual(self.fighter()['state'], 'bench', 'the hold keeps it out of the ring')
        self.assertEqual(self.corner()['bench']['remaining_ms'], frozen, 'the timer is stopped')
        released = self.bench({'hold': False})
        self.assertEqual(released['status'], 'applied', released)
        self.assertFalse(released['bench']['held'])
        self.assertEqual(released['bench']['respawn_in_ms'], frozen)
        self.play(respawn - 1 - 20)
        self.assertEqual(self.fighter()['state'], 'bench', 'the remainder still runs: no skipped timer')
        self.play(40)
        self.assertEqual(self.fighter()['state'], 'alive')
        kinds = [e['kind'] for e in self.corner()['events']]
        self.assertIn('kod', kinds)
        self.assertIn('held', kinds)
        self.assertIn('released', kinds)
        self.assertIn('respawn', kinds)

    def until_alive(self, limit: int) -> None:
        """Play until the next life starts (the ring may fill early when it is short of fighters), at most `limit`."""
        for _ in range(0, limit, 10):
            if self.fighter()['state'] == 'alive':
                return
            self.play(10)
        self.assertEqual(self.fighter()['state'], 'alive')

    def test_a_bag_item_swapped_on_the_bench_is_worn_next_life_and_a_swap_in_the_ring_is_refused(self) -> None:
        rules = self.arena.sim.rules
        rares = {slot: next(row for row, item in sorted(rules['items'].items()) if item['tier'] == 'rare' and item['slot'] == slot)
                 for slot in ('body', 'head')}
        for row in rares.values():
            self.fighter()['bag'][row] = self.arena.sim.inventory_entry(row)
        refused = self.bench({'equip': {'slot': 'body', 'item_id': rares['body']}})
        self.assertEqual(refused['status'], 'refused')
        self.assertIn('bench', refused['summary'])
        self.bench({'hold': True})
        self.knock_out()
        self.play(5)
        corner = self.corner()
        self.assertEqual(sorted(row['item_id'] for row in corner['bench']['bag']), sorted(rares.values()))
        worn = next(row['item_id'] for row in corner['bench']['equipped'] if row['slot'] == 'body')
        for slot, row in sorted(rares.items()):
            ack = self.bench({'equip': {'slot': slot, 'item_id': row}})
            self.assertEqual(ack['status'], 'applied', ack)
            self.assertIn(row, [r['item_id'] for r in ack['bench']['equipped']])
            self.assertIn('goes on', ack['summary'])
        self.play(3)
        self.assertEqual({slot: self.fighter()['kit'][slot] for slot in rares}, rares)
        self.assertNotIn(worn, [row['item_id'] for row in self.corner()['bench']['equipped']])
        self.assertEqual(self.corner()['bench']['bag'][0]['item_id'], worn) if not rules['items'][worn]['default'] else None
        self.bench({'hold': False})
        self.until_alive(rules['respawn_ticks'] + 40)
        self.assertEqual({slot: self.fighter()['equipped'][slot] for slot in rares}, rares)
        # The next KO drops one of the two; its next pick resets to the preset, and the swapped item still owned stays on.
        self.bench({'hold': True})
        self.knock_out()
        self.play(5)
        kept = [slot for slot, row in sorted(rares.items()) if row in self.fighter()['bag']]
        self.assertEqual(len(kept), 1, self.fighter()['bag'])
        self.assertEqual(self.fighter()['kit'][kept[0]], rares[kept[0]])
        lost = next(slot for slot in rares if slot not in kept)
        self.assertNotEqual(self.fighter()['kit'][lost], rares[lost])
        foreign = next(row for row, item in sorted(rules['items'].items())
                       if item['tier'] == 'rare' and item['slot'] == 'weapon' and row not in self.fighter()['bag'])
        miss = self.bench({'equip': {'slot': 'weapon', 'item_id': foreign}})
        self.assertEqual(miss['status'], 'refused')
        self.assertIn('not in your bag', miss['summary'])
        wrong = self.bench({'equip': {'slot': 'weapon', 'item_id': rares[kept[0]]}})
        self.assertIn('does not go in', wrong['summary'])

    def test_without_a_hold_a_players_pick_still_waits_out_the_45_s(self) -> None:
        respawn = self.arena.sim.rules['respawn_ticks']
        self.full_ring()
        self.knock_out()
        self.play(100)
        corner = self.corner()
        self.assertEqual(corner['state'], 'down', 'the pick locked at the KO; the life must not start before 45 s')
        self.assertEqual(corner['bench']['respawn_in_ms'], (respawn - 101) * 1000 // self.arena.sim.rules['tick_hz'])
        self.play(respawn - 101 + 20)
        self.assertEqual(self.fighter()['state'], 'alive')

    def test_the_corner_carries_hp_and_the_fighters_own_events(self) -> None:
        corner = self.corner()
        self.assertEqual(corner['hp'], self.fighter()['hp'])
        self.assertEqual(corner['max_hp'], self.fighter()['max_hp'])
        self.assertEqual(corner['events'][0]['kind'], 'joined')
        self.assertFalse(corner['bench']['hold'])
        self.assertEqual(len(corner['bench']['equipped']), 4)
        self.assertTrue(all(row['name'] for row in corner['bench']['equipped']))


if __name__ == '__main__':
    unittest.main()
