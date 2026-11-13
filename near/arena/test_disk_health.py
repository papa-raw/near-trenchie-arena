"""Health exposes free space on the persistent arena volume and the specified warning thresholds."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import snap_local


class DiskHealth(unittest.TestCase):
    def test_missing_disk_projection_does_not_break_the_health_check(self):
        with tempfile.TemporaryDirectory() as directory:
            host = snap_local.DevRoom(0, directory)
            for projection in ({}, {'chain': {'owner_reads_waiting': 2}}):
                host.round.arena.health = lambda: projection
                for path in ('/health', '/dev/health'):
                    with self.subTest(projection=projection, path=path):
                        status, data = host.route('GET', path, b'', 'local')
                        self.assertEqual(status, 200)
                        self.assertIsNone(data.get('free_disk_bytes'))
                        self.assertEqual(data['status'], 'unknown')
                        if 'chain' in projection:
                            self.assertEqual(data['chain'], projection['chain'])

    def test_health_reports_disk_bytes_and_both_threshold_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            host = snap_local.DevRoom(0, directory)
            for free, expected in ((6_000_000_000, 'green'), (5_000_000_000, 'green'),
                                   (4_999_999_999, 'amber'), (2_000_000_000, 'amber'),
                                   (1_999_999_999, 'red')):
                with self.subTest(free=free), patch.object(snap_local.shutil, 'disk_usage',
                                                         return_value=SimpleNamespace(free=free)) as usage:
                    status, data = host.route('GET', '/health', b'', '127.0.0.1')
                    self.assertEqual(status, 200)
                    self.assertEqual(data.get('free_disk_bytes'), free)
                    self.assertEqual(data.get('status'), expected)
                    usage.assert_called_once_with(host.round.arena.store.root)
            with patch.object(snap_local.shutil, 'disk_usage', side_effect=OSError('unavailable')):
                self.assertEqual(host.health()['status'], 'unknown')
                self.assertIsNone(host.health()['free_disk_bytes'])


if __name__ == '__main__':
    unittest.main()
