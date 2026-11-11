"""Valid optional speech fields and request errors cannot fence the room."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[2])]
from test_battle_protocol import joined_room
from test_snap_cold import SnapCold


class BattleResilience(unittest.TestCase):
    def test_text_only_speech_posts_and_following_frames_work(self) -> None:
        with joined_room() as (dev, keeper):
            client = keeper.client
            posted = client.control('speech', {'text': 'WAVES AHEAD'}, life_id=keeper.life_id)['ack']
            self.assertEqual(posted['status'], 'posted')
            self.assertNotIn('choose one', posted['summary'])
            capped = client.control('speech', {'text': 'MORE WAVES'}, life_id=keeper.life_id)['ack']
            self.assertEqual(capped['status'], 'refused')
            self.assertEqual(capped['speech']['refused'], 'rate_limited')
            plan = client.control('behaviour', {'v': 1, 'stance': 'flee'}, life_id=keeper.life_id)['ack']
            self.assertEqual(plan['status'], 'applied')
            self.assertFalse(dev.round.host.service._failed)

    def test_application_data_error_is_a_signed_refusal_then_next_request_works(self) -> None:
        with joined_room() as (dev, keeper):
            service = dev.round.host.service
            with patch.object(service, '_battle_apply', side_effect=ValueError('invalid request data')):
                receipt = keeper.client.control('behaviour', {'v': 1, 'stance': 'flee'}, life_id=keeper.life_id)
            self.assertEqual(receipt['ack']['status'], 'refused')
            self.assertFalse(service._failed)
            self.assertEqual(keeper.client.control('behaviour', {'v': 1, 'stance': 'flee'},
                                                  life_id=keeper.life_id)['ack']['status'], 'applied')

    def test_request_exception_does_not_latch_a_room_failure(self) -> None:
        with joined_room() as (dev, keeper):
            service = dev.round.host.service
            from near.arena.snap_client import SnapRefusal
            with patch.object(service, '_battle_session', side_effect=RuntimeError('request handler unavailable')):
                with self.assertRaises(SnapRefusal):
                    keeper.client.control('behaviour', {'v': 1, 'stance': 'flee'}, life_id=keeper.life_id)
            self.assertFalse(service._failed)
            # The same pending signed frame is safe to retry after a request
            # error before sequence reservation; it was never applied.
            self.assertEqual(keeper.client.control('behaviour', {'v': 1, 'stance': 'flee'},
                                                  life_id=keeper.life_id)['ack']['status'], 'applied')

    def test_security_journal_failure_still_fences_authority(self) -> None:
        from near.arena.snap_client import SnapRefusal
        with joined_room() as (dev, keeper):
            service = dev.round.host.service
            with patch.object(service, 'security_event', return_value=False):
                with self.assertRaises(SnapRefusal):
                    keeper.client.control('behaviour', {'v': 1, 'stance': 'flee'}, life_id=keeper.life_id)
            self.assertTrue(service._failed, 'a lost security journal still closes authority')
            with self.assertRaises(SnapRefusal):
                keeper.client.control('behaviour', {'v': 1, 'stance': 'flee'}, life_id=keeper.life_id)


class ColdClientPackage(unittest.TestCase):
    def test_isolated_public_copy_imports_client_and_battle_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            owner, public = SnapCold.prepare_owner(Path(directory), '', '')
            code = ('import sys; sys.path.insert(0, sys.argv[1]); '
                    'from near.arena.snap_client import SnapClient; '
                    'from near.arena.battle_protocol import check_request; '
                    'assert callable(SnapClient) and callable(check_request)')
            result = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(public)],
                                    cwd=owner, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
