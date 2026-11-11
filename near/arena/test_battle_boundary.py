"""A stale order at rollover must not close the next segment's authority."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[2])]
from test_battle_protocol import joined_room
from near.arena.snap_client import SnapRefusal


class BattleBoundary(unittest.TestCase):
    def test_refusal_after_segment_rollover_keeps_current_orders_usable(self) -> None:
        with joined_room() as (dev, keeper):
            arena, service = dev.round.arena, dev.round.host.service
            while arena.sim.state['tick'] < 1200:
                arena.advance(min(20, 1200 - arena.sim.state['tick']))
                keeper.tick()
            self.assertEqual(arena.segment_id, 'segment:0')
            before = arena.store.index
            refusal = keeper.client.control('behaviour', {'v': 1, 'stance': 'flee'}, life_id='stale-life')['ack']
            self.assertEqual(refusal['status'], 'refused')
            self.assertEqual(arena.segment_id, 'segment:1')
            self.assertGreater(arena.store.index, before, 'the request legitimately opened the next segment')
            self.assertFalse(service._failed, 'rollover alone is not an uncertain request effect')
            keeper.tick()
            next_order = keeper.client.control('behaviour', {'v': 1, 'stance': 'flee'}, life_id=keeper.life_id)['ack']
            self.assertEqual(next_order['status'], 'applied')
            arena.advance(10)
            enqueue = arena._enqueue
            def apply_then_fail(*args: object, **options: object) -> None:
                enqueue(*args, **options)
                raise RuntimeError('request input written after rollover')
            with patch.object(arena, '_enqueue', side_effect=apply_then_fail):
                with self.assertRaisesRegex(SnapRefusal, '^recovery_pending$'):
                    keeper.client.control('behaviour', {'v': 1, 'stance': 'hold'}, life_id=keeper.life_id)
            self.assertTrue(service._failed, 'a real request write still closes authority on failure')
            count = arena.sequence
            with self.assertRaisesRegex(SnapRefusal, '^recovery_pending$'):
                keeper.client.control('behaviour', {'v': 1, 'stance': 'hold'}, life_id=keeper.life_id)
            self.assertEqual(arena.sequence, count, 'retry did not add another input')


if __name__ == '__main__':
    unittest.main()
