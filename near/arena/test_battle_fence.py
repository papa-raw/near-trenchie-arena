"""Unreceipted mutations must close authority before another frame enters."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[2])]
from test_battle_protocol import joined_room
from near.arena.snap_client import SnapRefusal


class BattleFence(unittest.TestCase):
    def test_post_journal_exception_fences_and_retry_does_not_enqueue_twice(self) -> None:
        for error in (RuntimeError, TypeError):
            with self.subTest(error=error.__name__), joined_room() as (dev, keeper):
                arena, service = dev.round.arena, dev.round.host.service
                enqueue = arena._enqueue
                def journal_then_fail(*args: object, **options: object) -> None:
                    enqueue(*args, **options)
                    raise error('input is journaled but acknowledgement is unavailable')
                with patch.object(arena, '_enqueue', side_effect=journal_then_fail):
                    with self.assertRaises(SnapRefusal):
                        keeper.client.control('behaviour', {'v': 1, 'stance': 'flee'}, life_id=keeper.life_id)
                self.assertTrue(service._failed, 'an unreceipted journaled input closes authority')
                with self.assertRaises(SnapRefusal):
                    keeper.client.control('behaviour', {'v': 1, 'stance': 'flee'}, life_id=keeper.life_id)
                from room.policy import canonical_bytes
                request = dict(keeper.client._pending[0])
                request['sequence'] = str(int(request['sequence']) + 1)
                request = keeper.client._signed('BattleRequest', request)
                denied = keeper.transport.frame(keeper.client._connection, canonical_bytes(request))
                self.assertEqual(denied['code'], 'recovery_pending', 'a fresh sequence cannot bypass the fence')
                inputs = [row for row in arena.commands if row['kind'] == 'input'
                          and row['value']['kind'] == 'behaviour' and row['value']['fighter_id'] == keeper.token]
                self.assertEqual(len(inputs), 1, 'the exact signed retry cannot apply a second input')
                self.assertTrue(any(row['kind'] == 'input' and row['value']['kind'] == 'behaviour'
                                    for row in arena.store.records()))

    def test_receipt_exception_after_apply_also_fences(self) -> None:
        with joined_room() as (dev, keeper):
            service, arena = dev.round.host.service, dev.round.arena
            from room.policy import BoundaryError
            with patch.object(service, '_battle_receipt', side_effect=BoundaryError('bad_message')):
                with self.assertRaises(SnapRefusal):
                    keeper.client.control('behaviour', {'v': 1, 'stance': 'flee'}, life_id=keeper.life_id)
            self.assertTrue(service._failed)
            with self.assertRaises(SnapRefusal):
                keeper.client.control('behaviour', {'v': 1, 'stance': 'flee'}, life_id=keeper.life_id)
            self.assertEqual(sum(row['kind'] == 'input' and row['value']['kind'] == 'behaviour'
                                 for row in arena.commands), 1)

    def test_speech_callback_that_posts_then_raises_closes_authority(self) -> None:
        with joined_room() as (dev, keeper):
            service = dev.round.host.service
            post = service.battle_speech
            def post_then_fail(*args: object, **options: object) -> None:
                post(*args, **options)
                raise RuntimeError('speech posted but acknowledgement is unavailable')
            with patch.object(service, 'battle_speech', side_effect=post_then_fail):
                with self.assertRaises(SnapRefusal):
                    keeper.client.control('speech', {'text': 'ONE WAVE'}, life_id=keeper.life_id)
            self.assertTrue(service._failed)
            with self.assertRaises(SnapRefusal):
                keeper.client.control('speech', {'text': 'ONE WAVE'}, life_id=keeper.life_id)
            self.assertEqual(len([row for row in dev.feed.rows if row['who'] == keeper.token]), 1)

    def test_pre_mutation_error_and_successful_receipt_keep_authority_open(self) -> None:
        with joined_room() as (dev, keeper):
            service = dev.round.host.service
            with patch.object(service, '_battle_apply', side_effect=ValueError('invalid data before mutation')):
                reply = keeper.client.control('behaviour', {'v': 1, 'stance': 'flee'}, life_id=keeper.life_id)
            self.assertEqual(reply['ack']['status'], 'refused')
            self.assertFalse(service._failed)
            with patch.object(service, '_battle_session', side_effect=RuntimeError('before mutation')):
                with self.assertRaises(SnapRefusal):
                    keeper.client.control('behaviour', {'v': 1, 'stance': 'flee'}, life_id=keeper.life_id)
            self.assertFalse(service._failed)
            reply = keeper.client.control('behaviour', {'v': 1, 'stance': 'flee'}, life_id=keeper.life_id)
            self.assertEqual(reply['ack']['status'], 'applied')
            self.assertFalse(service._failed, 'a completed signed receipt clears the pending effect')


if __name__ == '__main__':
    unittest.main()
