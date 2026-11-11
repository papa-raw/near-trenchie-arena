"""A failed engine closes room authority even before the request checkpoint."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[2])]
from test_battle_protocol import joined_room
from near.arena.snap_client import SnapRefusal


class BattlePrepare(unittest.TestCase):
    def test_failed_preparation_fences_room_without_applying_or_signing(self) -> None:
        for failure_type in (RuntimeError, ValueError):
            with self.subTest(error=failure_type.__name__), joined_room() as (dev, keeper):
                arena, service = dev.round.arena, dev.round.host.service
                sequence = arena.sequence
                def failed_prepare() -> None:
                    arena.failed = True
                    raise failure_type('engine preparation failed')
                with patch.object(arena, '_prepare_segment', side_effect=failed_prepare), \
                        patch.object(service, '_battle_apply', wraps=service._battle_apply) as apply, \
                        patch.object(service, '_battle_receipt', wraps=service._battle_receipt) as receipt:
                    with self.assertRaisesRegex(SnapRefusal, '^recovery_pending$'):
                        keeper.client.control('behaviour', {'v': 1, 'stance': 'flee'}, life_id=keeper.life_id)
                    self.assertTrue(arena.failed)
                    self.assertTrue(service._failed, 'the failed engine must also close room authority')
                    apply.assert_not_called()
                    receipt.assert_not_called()
                with self.assertRaisesRegex(SnapRefusal, '^recovery_pending$'):
                    keeper.client.control('behaviour', {'v': 1, 'stance': 'flee'}, life_id=keeper.life_id)
                self.assertEqual(arena.sequence, sequence, 'neither request added an engine input')


if __name__ == '__main__':
    unittest.main()
