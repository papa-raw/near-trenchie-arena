"""New focused member repair case; no existing unittest method is invoked."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'near/arena'), str(Path(__file__).resolve().parent)]
from member_fixture import MemberCases, case_handler
from near.members.runtime import member_server


class RepairRoom(MemberCases):
    def control(self, request: dict) -> dict:
        if request['action'] != 'apply':
            return super().control(request)
        for token in ('clover', 'house'):
            self.clients[token].answer_change('interval-v8', '7', accept=True, request_id='repair-' + token)
        # This trusted callback certifies only source-owned terms, not engine rules.
        self.case.host.service.owner_apply_terms = lambda terms: True
        applied = self.case.host.service.apply_owner_boundary('segment:1')
        return dict(applied=applied, terms=self.case.host.service.export_owner_state()['terms'])


class MemberRepair(unittest.TestCase):
    def test_fault_exit_context_and_applied_terms_use_fresh_room_facts(self) -> None:
        with tempfile.TemporaryDirectory(prefix='member-repair-') as temporary:
            captures = Path(os.environ.get('MEMBER_SHOTS', temporary))
            captures.mkdir(parents=True, exist_ok=True)
            host = RepairRoom()
            self.addCleanup(host.close)
            server = member_server(host.session, handler_class=case_handler(host))
            self.addCleanup(server.server_close)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            self.addCleanup(server.shutdown)
            origin = 'http://127.0.0.1:' + str(server.server_port)
            result = subprocess.run(['node', str(Path(__file__).with_name('member-repair-case.cjs')), origin, str(captures)],
                cwd=ROOT, capture_output=True, text=True, timeout=120)
            print(result.stdout, end='')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads((captures / 'repair-report.json').read_text())
            self.assertEqual(report['failures'], [])
            self.assertEqual(report['source_terms']['input_interval_ms'], '1500')
            self.assertEqual(len(report['exits']), 4)
            self.assertTrue(host.self_bound())


if __name__ == '__main__':
    unittest.main()
