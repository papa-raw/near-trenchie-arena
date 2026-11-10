"""New member page case: real copied room, synthetic identity and local browser."""
from __future__ import annotations

import importlib
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


class MemberBoards(unittest.TestCase):
    def test_approved_b_flows_use_real_room_and_keep_recorded_answers(self) -> None:
        runtime = importlib.import_module('near.members.runtime')
        fixture = importlib.import_module('member_fixture')
        with tempfile.TemporaryDirectory(prefix='members-page-') as temporary:
            captures = Path(os.environ.get('MEMBER_SHOTS', temporary))
            captures.mkdir(parents=True, exist_ok=True)
            host = fixture.MemberCases()
            self.addCleanup(host.close)
            server = runtime.member_server(host.session, handler_class=fixture.case_handler(host))
            self.addCleanup(server.server_close)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            self.addCleanup(server.shutdown)
            origin = 'http://127.0.0.1:' + str(server.server_port)
            result = subprocess.run(['node', str(Path(__file__).with_name('members-case.cjs')), origin, str(captures)],
                cwd=ROOT, capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout, end='')
            report = json.loads((captures / 'case-report.json').read_text())
            self.assertTrue(report['real_room'])
            self.assertGreaterEqual(len(report['states']), 17)
            self.assertTrue(report['reload_keeps_answer'])
            self.assertEqual(report['uncertain_write_count'], 1)
            self.assertTrue(report['all_requests_self_bound'])
            self.assertTrue(host.self_bound())


if __name__ == '__main__':
    unittest.main()
