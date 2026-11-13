"""A bounded public card summary counts the whole prediction history, including after restart."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1] / 'web/snapin')]
import snap_local
import serve


class PredictionSummary(unittest.TestCase):
    def test_card_totals_cover_the_full_history_without_request_time_scans(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'predictions.jsonl'
            rows = [dict(life=f'run/avichad:life:{i}', persona='avichad', lock_hash=str(i), actual=i % 5,
                         prediction=True, score=100_000, base_score=200_000, model='x' * 500)
                    for i in range(316)]
            rows += [dict(life=f'run/other:life:{i}', persona='other', lock_hash=str(i), actual=0,
                          prediction=False, score=None, base_score=None, model='x' * 500)
                     for i in range(900)]
            path.write_bytes(b''.join(json.dumps(row).encode() + b'\n' for row in rows))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            host = snap_local.DevRoom.__new__(snap_local.DevRoom)
            host.house_log = snap_local.house_predictions.PredictionLog(directory)
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('request read the whole log')), \
                    patch.object(Path, 'read_text', side_effect=AssertionError('request scanned the log')):
                status, summary = host.route('GET', '/house/predictions/summary?persona=avichad', b'', 'local')
                self.assertEqual(status, 200)
                self.assertEqual((summary['lives'], summary['scored']), (316, 316))
                self.assertEqual(summary['kos'], sum(i % 5 for i in range(316)))
                self.assertEqual((summary['score_sum'], summary['base_score_sum']), (31_600_000, 63_200_000))
                self.assertEqual(summary['log_hash'], digest)
                self.assertEqual(summary['scope'], 'all')
            host.house_log.lock('next/avichad:life:316', 'r' * 64, 'avichad', 'owner.testnet', 'model')
            host.house_log.resolve('next/avichad:life:316', 3)
            self.assertEqual(host.house_log.summary('avichad')['lives'], 317)
            again = snap_local.house_predictions.PredictionLog(directory)
            self.assertEqual(again.summary('avichad'), host.house_log.summary('avichad'))
            self.assertEqual(again.summary('avichad')['log_hash'], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(again.summary('newcomer')['lives'], 0)
            # The same-origin web proxy must preserve the marker that tells the card to ask for exact totals.
            headers = {'X-Log-Window': 'tail', 'X-Log-Max-Bytes': '262144', 'X-Log-Hash': 'window-hash'}
            reply = SimpleNamespace(status=200, read=lambda: b'{}', getheader=lambda k, default=None: headers.get(k, default))
            connection = SimpleNamespace(request=lambda *a, **k: None, close=lambda: None, getresponse=lambda: reply)
            handler_class = serve.make_handler('http://127.0.0.1:1', [0])
            handler = handler_class.__new__(handler_class)
            handler.headers, handler.path = {}, '/house/predictions.jsonl'
            forwarded = []
            handler.reply = lambda status, data, ctype, extra: forwarded.append(extra)
            with patch.object(serve.http.client, 'HTTPConnection', return_value=connection):
                handler.forward('GET', None)
            self.assertEqual(forwarded, [headers])


if __name__ == '__main__':
    unittest.main()
