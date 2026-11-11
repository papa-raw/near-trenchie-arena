"""Fence responses describe recovery, and refusals cannot conceal journal writes."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[2])]
from test_battle_protocol import joined_room
from near.arena.snap_client import SnapRefusal
from room.policy import BoundaryError


class BattleFenceLows(unittest.TestCase):
    def test_fencing_frame_returns_recovery_instead_of_a_data_error(self) -> None:
        with joined_room() as (dev, keeper):
            service = dev.round.host.service
            with patch.object(service, '_battle_receipt', side_effect=BoundaryError('bad_message')):
                with self.assertRaisesRegex(SnapRefusal, '^recovery_pending$'):
                    keeper.client.control('behaviour', {'v': 1, 'stance': 'flee'}, life_id=keeper.life_id)
            self.assertTrue(service._failed)

    def test_refused_ack_after_journaling_fences_without_signing_a_false_refusal(self) -> None:
        with joined_room() as (dev, keeper):
            service, arena = dev.round.host.service, dev.round.arena
            refused = keeper.client.control('behaviour', {'v': 1, 'stance': 'invalid'},
                                            life_id=keeper.life_id)
            self.assertEqual(refused['ack']['status'], 'refused')
            self.assertFalse(service._failed, 'an ordinary refusal without a write remains safe')
            apply = service._battle_apply
            def apply_then_refuse(binding: dict, request: dict) -> dict:
                ack = apply(binding, request)
                self.assertEqual(ack['status'], 'applied')
                return service._refused_ack(binding, request, 'bad_message')
            with patch.object(service, '_battle_apply', side_effect=apply_then_refuse), \
                    patch.object(service, '_battle_receipt', wraps=service._battle_receipt) as receipt:
                with self.assertRaisesRegex(SnapRefusal, '^recovery_pending$'):
                    keeper.client.control('behaviour', {'v': 1, 'stance': 'flee'}, life_id=keeper.life_id)
                receipt.assert_not_called()
            self.assertTrue(service._failed)
            with self.assertRaisesRegex(SnapRefusal, '^recovery_pending$'):
                keeper.client.control('behaviour', {'v': 1, 'stance': 'flee'}, life_id=keeper.life_id)
            self.assertEqual(sum(row['kind'] == 'input' and row['value']['kind'] == 'behaviour'
                                 for row in arena.commands), 1)


if __name__ == '__main__':
    unittest.main()
