"""Owner delays must not consume the signed-result fixture's simulated segment."""
import time
import unittest

from test_snap_local import LocalSnap


class LocalSimClock(unittest.TestCase):
    setUp = LocalSnap.setUp
    shutdown = LocalSnap.shutdown
    keeper = LocalSnap.keeper

    def test_slow_owner_still_fights_leaves_and_reads_segment_zero(self) -> None:
        # The real HTTP host remains responsive while the owner is delayed.
        time.sleep(0.25)
        self.assertEqual(self.dev.round.arena.sim.state['tick'], 0)
        keeper = self.keeper()
        self.assertEqual(keeper.start('1')['state'], 'accepted')
        self.dev.step(12)
        keeper.tick()
        self.assertEqual(keeper.summary()['you']['state'], 'ring')
        self.assertEqual(keeper.intent({'focus': 'nearest', 'loot': 'nearest', 'sig': 'auto'})['state'], 'accepted')
        self.dev.step(10)
        self.assertEqual(keeper.intent({'leave': True})['state'], 'accepted')
        arena = self.dev.round.arena
        while arena.sim.state['tick'] < 1201:
            self.dev.step(min(20, 1201 - arena.sim.state['tick']))
            keeper.tick()
        result = keeper.result(0)
        self.assertTrue(result['signed'] and result['completed'])
        self.assertEqual(result['public_prediction_row'], 'matches your private receipt')

    test_slow_owner_still_fights_leaves_and_reads_segment_zero.manual_clock = True


if __name__ == '__main__':
    unittest.main()
