"""New focused public target-return projection, baseline 5627fd0 has zero timer fields."""
from pathlib import Path
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[2])]
from test_battle_protocol import joined_room


class TargetReturn(unittest.TestCase):
    def test_house_and_player_return_timers_follow_bench_hold(self):
        with joined_room() as (dev, keeper):
            arena = dev.round.arena
            house = next(name for name in arena.members if name != keeper.token)
            for name in (house, keeper.token):
                member = arena.members[name]
                fighter = arena.sim.state['fighters'][name]
                member.update(ever_started=True, spawn_pending=False, bench_hold=False, held_ticks=0)
                fighter.update(state='bench', respawn_at=arena.sim.state['tick'] + 250)
                row = next(row for row in dev.target_roster() if row['id'] == name)
                self.assertEqual(row['state'], 'bench')
                self.assertEqual(row['respawn_in_ms'], 12500)
                self.assertFalse(row['held'])
                self.assertTrue(row['name'] and row['tag'])
                member.update(bench_hold=True, held_since=arena.sim.state['tick'])
                row = next(row for row in dev.target_roster() if row['id'] == name)
                self.assertTrue(row['held'])
                self.assertIsNone(row['respawn_in_ms'])
                fighter['state'] = 'alive'
                row = next(row for row in dev.target_roster() if row['id'] == name)
                self.assertEqual(row['state'], 'ring')
                self.assertFalse(row['held'])
                self.assertIsNone(row['respawn_in_ms'])


if __name__ == '__main__':
    unittest.main()
