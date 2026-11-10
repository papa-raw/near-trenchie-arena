"""New focused comparison with the approved additive member drawings."""
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
sys.path[:0] = [str(ROOT), str(ROOT/'near/arena'), str(Path(__file__).resolve().parent)]
import test_member_repair as fixtures
from member_fixture import case_handler
from near.members.runtime import member_server


class MemberPresentation(unittest.TestCase):
    def test_applied_and_fault_return_match_additive_drawings(self) -> None:
        with tempfile.TemporaryDirectory(prefix='member-presentation-') as temporary:
            shots = Path(os.environ.get('MEMBER_SHOTS',temporary))
            shots.mkdir(parents=True,exist_ok=True)
            host = fixtures.RepairRoom()
            self.addCleanup(host.close)
            server = member_server(host.session,handler_class=case_handler(host))
            self.addCleanup(server.server_close)
            threading.Thread(target=server.serve_forever,daemon=True).start()
            self.addCleanup(server.shutdown)
            result = subprocess.run(['node',str(Path(__file__).with_name('member-presentation-case.cjs')),
                'http://127.0.0.1:'+str(server.server_port),str(shots)],cwd=ROOT,
                capture_output=True,text=True,timeout=120)
            print(result.stdout,end='')
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            report = json.loads((shots/'presentation-report.json').read_text())
            self.assertEqual(report['failures'],[])
            self.assertEqual(report['errors'],[])
            self.assertTrue(host.self_bound())


if __name__ == '__main__':
    unittest.main()
