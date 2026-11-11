"""The DEV health alias forwards the production arena's public chain hold status."""
from __future__ import annotations
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import snap_local


class ChainHoldHealth(unittest.TestCase):
    def test_public_dev_health_copies_chain_holds_and_omits_absent_writer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dev = snap_local.DevRoom(8765, directory)
            chain = dict(lives_held_for_owner_read=3, owner_reads_waiting=2, oldest_hold_s=42.7)
            dev.round.arena.health = lambda: dict(chain=chain)
            for path in ('/health', '/dev/health'):
                status, value = dev.route('GET', path, b'', '127.0.0.1')
                self.assertEqual(status, 200)
                self.assertEqual(value.get('chain'), chain)
                self.assertIsNot(value['chain'], chain)
            dev.round.arena.health = lambda: {}
            self.assertNotIn('chain', dev.health())


if __name__ == '__main__': unittest.main()
