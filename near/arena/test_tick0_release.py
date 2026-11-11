"""Immediate signed release must cancel activation without crashing the host."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[2])]
from test_result_lifecycle import pending_join
from replay import replay_segment, cancel_spawns, cancel_loadouts
from nightly import events_of
from server import Arena
from sim import Sim


class TickZeroRelease(unittest.TestCase):
    def test_release_before_initial_spawn_survives_and_replays(self) -> None:
        with pending_join() as (dev, keeper):
            arena = dev.round.arena
            self.assertEqual(arena.sim.state['tick'], 0)
            before = deepcopy(arena.sim.state['inputs'])
            self.assertEqual({row['kind'] for row in before if row['fighter_id'] == keeper.token},
                             {'join', 'loadout', 'spawn'})
            legacy = Sim.restore(arena.sim.export(), arena.sim.rules)
            cancel_spawns(legacy, keeper.token)
            self.assertTrue(any(row['kind'] == 'loadout' and row['fighter_id'] == keeper.token
                                for row in legacy.state['inputs']), 'old spawn-only cancellation stays unchanged')
            cancel_loadouts(legacy, keeper.token)
            self.assertEqual(legacy.state['inputs'], [row for row in before if row['fighter_id'] != keeper.token
                                                      or row['kind'] not in ('loadout', 'spawn')])
            receipt = keeper.client.control('leave', {'reason': 'leave'})
            self.assertEqual(receipt['state'], 'accepted')
            arena.advance(8)
            self.assertNotIn(keeper.token, arena.members)
            self.assertFalse(arena.failed)
            self.assertNotIn(keeper.token, arena.sim.state['fighters'])
            self.assertFalse(any(row['fighter_id'] == keeper.token for row in arena.sim.state['inputs']))
            arena._flush_ticks()
            restored = Arena(arena.context, arena.seeds, data_dir=arena.store.root,
                             rules=arena.sim.rules, recover=True)
            self.assertEqual(restored.sim.state_hash(), arena.sim.state_hash(), 'journal recovery must agree')
            arena.advance(1193)
            native = arena.store.segment('segment:0')
            self.assertEqual(replay_segment(native).state_hash(), native['sealed']['final_state_hash'])
            self.assertEqual(sum(row['kind'] == 'cancel_loadout' and row['value'] == keeper.token
                                 for row in native['commands']), 1)
            game = None
            for game, _ in events_of(native):
                pass
            self.assertIsNotNone(game)
            self.assertEqual(game.state_hash(), native['sealed']['final_state_hash'])


if __name__ == '__main__':
    unittest.main()
