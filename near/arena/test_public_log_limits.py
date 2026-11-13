"""Public JSONL endpoints serve bounded, complete rows without hashing the history on the tick loop."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import snap_local


class PublicLogLimits(unittest.TestCase):
    def test_record_and_predictions_read_only_a_bounded_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'public.jsonl'
            row = json.dumps({'event': 'x' * 500}).encode() + b'\n'
            path.write_bytes(row * 5000)
            host = snap_local.DevRoom.__new__(snap_local.DevRoom)
            host.round = SimpleNamespace(arena=SimpleNamespace(record=SimpleNamespace(path=path)))
            host.house_log = SimpleNamespace(path=path, log_hash=lambda: self.fail('whole-file hash on request'))
            for route in ('/house/record.jsonl', '/house/predictions.jsonl'):
                with self.subTest(route=route):
                    status, (data, digest) = host.route('GET', route, b'', '127.0.0.1')
                    self.assertEqual(status, 200)
                    self.assertLessEqual(len(data), 256 * 1024)
                    self.assertGreater(len(data), 0)
                    self.assertEqual(data, row * (len(data) // len(row)))
                    if digest is not None:
                        self.assertEqual(digest, hashlib.sha256(data).hexdigest())
            # Whole-file convenience readers must never be used by these routes, even for a short log.
            path.write_bytes(row + b'{"partial":')
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('unbounded read')):
                self.assertEqual(host.house_predictions(), row)
            path.unlink()
            self.assertEqual(host.house_predictions(), b'')


if __name__ == '__main__':
    unittest.main()
