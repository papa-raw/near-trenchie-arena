"""Pat's items 47-49 for the plan doors: an agent session's orders, its in-character replies and the host's receipts
reach the owner's browser panel, with the plan's weekly use when the session reports it ("not reported" otherwise).
The guide page reads it with the door code it holds; the public corner never shows an order or a reply."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import snap
import snap_local


class OwnerLog(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dev = snap_local.DevRoom(8765, self.tmp.name)
        self.patch = patch.object(snap, 'call', side_effect=self.direct_call)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def direct_call(self, url: str, method: str = 'GET', body=None, headers=None, timeout=60, seen=None):
        target = urlsplit(url)
        raw = json.dumps(body).encode() if isinstance(body, dict) else body or b''
        status, value = self.dev.route(method, target.path + ('?' + target.query if target.query else ''), raw, '127.0.0.1')
        if seen is not None:
            seen.update(now=self.dev.round.vnow(), at=time.monotonic(), paused=True)
        return value

    def get(self, path: str) -> tuple[int, dict]:
        return self.dev.route('GET', path, b'', '127.0.0.1')

    def test_an_agent_sessions_order_reply_and_receipt_reach_the_owner_by_its_code_and_never_the_corner(self) -> None:
        status, issued = self.dev.route('POST', '/snap/code', json.dumps(dict(agent='claude-code', name='Barnacle Bertie',
                                         preset='hunter', plan_stop_pct=10)).encode(), '127.0.0.1')
        self.assertEqual(status, 200, issued)
        code = issued['code']
        status, pending = self.get(f'/snap/code/{code}/log')
        self.assertEqual((status, pending['joined']), (200, False))
        keeper = snap.Keeper(types.SimpleNamespace(url='http://127.0.0.1:8765', name='ignored', preset='hunter',
                                                   spread='40,30,20,10', zero=10, code=code))
        keeper.start('1')
        self.dev.round.arena.advance(3)
        status, joined = self.get(f'/snap/code/{code}/log')
        self.assertEqual(status, 200, joined)
        self.assertTrue(joined['joined'])
        self.assertEqual((joined['fighter_id'], joined['agent'], joined['state']), (keeper.token, 'claude-code', 'ring'))
        self.assertEqual(joined['plan'], dict(stop_pct=10, week_used_pct=None, reported_at_ms=None, stopped=False))  # "not reported"
        self.assertEqual(joined['hp'], self.dev.round.arena.sim.state['fighters'][keeper.token]['hp'])
        self.assertEqual(joined['log'][0]['kind'], 'joined')

        receipt = keeper.client.control('behaviour', {'v': 1, 'stance': 'flee'}, life_id=keeper.life_id)
        seq = receipt['sequence']
        note = keeper.client.control('note', dict(seq=seq, order='run away from everyone',
                                     reply="Tide's out, so am I. Catch me if you can.",
                                     why='you asked me to avoid every fight.', plan=dict(week_used_pct=4)),
                                     life_id=keeper.life_id)
        self.assertEqual(note['ack']['type'], 'note_ack')
        self.assertEqual(note['ack']['status'], 'kept')
        status, log = self.get(f'/snap/code/{code}/log')
        order = [row for row in log['log'] if row['kind'] == 'order']
        self.assertEqual(len(order), 1, log['log'])
        self.assertEqual(order[0]['seq'], seq)
        self.assertEqual(order[0]['order'], 'run away from everyone')
        self.assertEqual(order[0]['reply'], "Tide's out, so am I. Catch me if you can.")
        self.assertEqual(order[0]['why'], 'you asked me to avoid every fight.')
        self.assertEqual(order[0]['receipt']['status'], receipt['ack']['status'])
        self.assertEqual(order[0]['receipt']['summary'], receipt['ack']['summary'])
        self.assertEqual(order[0]['receipt']['applies_in_ms'], receipt['ack']['applies_in_ms'])
        self.assertEqual(log['plan']['week_used_pct'], 4)
        self.assertEqual(log['plan']['stop_pct'], 10)

        status, corner = self.get('/dev/corner?fighter=' + keeper.token)
        self.assertEqual(status, 200, corner)
        self.assertNotIn('order', [row['kind'] for row in corner['events']])
        self.assertNotIn('run away', json.dumps(corner))
        self.assertEqual(self.get('/snap/code/not-a-code/log')[0], 404)

    def test_a_note_is_refused_when_it_carries_nothing_or_too_much(self) -> None:
        keeper = snap.Keeper(types.SimpleNamespace(url='http://127.0.0.1:8765', name='shoal', preset='hunter',
                                                   spread='40,30,20,10', zero=10))
        keeper.start('1')
        self.dev.round.arena.advance(3)
        for payload in ({}, {'seq': '1'}, {'order': 'x' * 301}, {'plan': {'week_used_pct': 101}}, {'reply': 'hi', 'extra': 1}):
            with self.subTest(payload=payload), self.assertRaises(Exception):
                keeper.client.control('note', payload, life_id=keeper.life_id)
            keeper.client._pending = None  # the client keeps a refused request for retry; this case sends a new one


if __name__ == '__main__':
    unittest.main()
