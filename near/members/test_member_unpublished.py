"""New authoritative unpublished-state case; never a substituted room snapshot."""
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
sys.path[:0] = [str(ROOT),str(ROOT/'near/arena'),str(Path(__file__).resolve().parent)]
from member_fixture import MemberCases, case_handler
from near.arena.snap_client import SnapRefusal
from near.members.runtime import member_server


class MemberUnpublished(unittest.TestCase):
    def test_signed_unpublished_state_stays_distinct_from_failure_and_publish_requires_review(self) -> None:
        host = MemberCases()
        self.addCleanup(host.close)
        host.reset(published=False)
        self.assertIsNone(host.session.read()['snapshot']['terms'])
        with self.assertRaisesRegex(SnapRefusal,'version_mismatch'):
            host.clover.accept_terms('7',request_id='unpublished-consent')
        with tempfile.TemporaryDirectory(prefix='member-unpublished-') as temporary:
            shots = Path(os.environ.get('MEMBER_SHOTS',temporary))
            shots.mkdir(parents=True,exist_ok=True)
            server = member_server(host.session,handler_class=case_handler(host))
            self.addCleanup(server.server_close)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            self.addCleanup(server.shutdown)
            result = subprocess.run(['node',str(Path(__file__).with_name('member-unpublished-case.cjs')),
                'http://127.0.0.1:'+str(server.server_port),str(shots)],cwd=ROOT,
                capture_output=True,text=True,timeout=120)
            print(result.stdout,end='')
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            report = json.loads((shots/'unpublished-report.json').read_text())
            self.assertEqual(report['errors'],[])
            self.assertTrue(report['source_published'])
            self.assertTrue(report['recorded_acceptance'])
            self.assertTrue(host.self_bound())


if __name__ == '__main__':
    unittest.main()
