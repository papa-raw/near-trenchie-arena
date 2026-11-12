"""One new desk case: browser actions, isolated SNAP agent, real room and replay."""
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
sys.path.insert(0, str(ROOT))


class ReviewerDesk(unittest.TestCase):
    def test_checked_replay_keeps_empty_omitted_and_present_forecasts_distinct(self) -> None:
        sys.path.insert(0, str(ROOT / 'near/arena'))
        from test_room_host import CopiedRoom
        from test_engine_evidence import drive
        from near.web.runtime import desk_server
        from near.web.evidence import read_evidence

        with tempfile.TemporaryDirectory(prefix='desk-forecast-presence-') as temporary:
            scratch = Path(temporary)
            shots = Path(os.environ.get('DESK_SHOTS', scratch / 'shots'))
            shots.mkdir(parents=True, exist_ok=True)
            origins, sources = [], {}
            for state in ('empty', 'omitted', 'present'):
                case = CopiedRoom()
                case.setUp()
                self.addCleanup(case.doCleanups)
                clients, sequences = [], []
                if state != 'empty':
                    grant = case.join('alice')
                    cid, ready = case.authenticate(grant)
                    if state == 'present':
                        case.predict(grant, cid, ready)
                    clients.append((grant, cid))
                    sequences.append(2 if state == 'present' else 1)
                drive(case, 1200, clients, sequences)
                archive = case.arena.store.segment('segment:0')
                folder = scratch / state
                folder.mkdir()
                (folder / 'segment.json').write_text(json.dumps(archive))
                facts = read_evidence(folder)
                self.assertEqual(facts['state'], 'checked', state)
                self.assertEqual(facts['recorded_hash'], facts['replayed_hash'], state)
                locked = [row for row in facts['predictions'] if row['spread_bps'] is not None]
                if state == 'empty':
                    self.assertEqual(facts['predictions'], [])
                elif state == 'omitted':
                    self.assertTrue(facts['predictions'])
                    self.assertFalse(locked)
                    self.assertTrue(all(row['prediction_lock']['state'] == 'none' for row in facts['predictions']))
                else:
                    self.assertTrue(locked)
                sources[state] = facts
                server = desk_server(folder)
                self.addCleanup(server.server_close)
                self.addCleanup(server.shutdown)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                origins.append(f'http://127.0.0.1:{server.server_port}')
            (shots / 'source-facts.json').write_text(json.dumps(sources, indent=2) + '\n')
            browser = subprocess.run(['node', str(Path(__file__).with_name('forecast-presence-case.cjs')),
                                      *origins, str(shots)], cwd=ROOT, capture_output=True,
                                     text=True, timeout=120)
            self.assertEqual(browser.returncode, 0, browser.stdout + browser.stderr)
            print(browser.stdout, end='')

    def test_four_actions_follow_real_local_agent_forecast_and_checked_replay(self) -> None:
        from near.web.runtime import desk_server
        from near.web.evidence import read_evidence

        with tempfile.TemporaryDirectory(prefix='reviewer-desk-') as temporary:
            scratch = Path(temporary)
            output = scratch / 'demo'
            result = subprocess.run(['make', '-C', str(ROOT / 'near'), 'rehearsal', f'DEMO_DIR={output}'],
                                    capture_output=True, text=True, timeout=240)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout, end='')
            facts = read_evidence(output)
            self.assertEqual(facts['state'], 'checked')
            self.assertEqual(facts['segment_id'], 'segment:0')
            self.assertEqual(facts['replayed_hash'], facts['recorded_hash'])
            self.assertTrue(any(row['life_id'] == 'alice:life:0' for row in facts['predictions']))
            alice = next(row for row in facts['predictions'] if row['life_id'] == 'alice:life:0')
            self.assertEqual(sum(alice['spread_bps'].values()), 10000)
            self.assertTrue(alice['prediction_lock']['locked_before_start'])
            self.assertIsNone(facts['chain_transaction'])
            self.assertNotIn('PRIVATE-CANARY', json.dumps(facts))
            self.assertNotIn('signature', json.dumps(facts))
            archive = json.loads((output / 'segment.json').read_text())
            corrupt = scratch / 'corrupt'
            corrupt.mkdir()
            archive['sealed']['final_state_hash'] = '0' * 64
            (corrupt / 'segment.json').write_text(json.dumps(archive))
            self.assertEqual(read_evidence(corrupt)['state'], 'unavailable')
            self.assertEqual(read_evidence(scratch / 'missing')['state'], 'pending')
            origins = []
            for directory in (None, output, corrupt):
                server = desk_server(directory)
                self.addCleanup(server.server_close)
                self.addCleanup(server.shutdown)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                origins.append(f'http://127.0.0.1:{server.server_port}')
            shots = Path(os.environ.get('DESK_SHOTS', scratch / 'shots'))
            shots.mkdir(parents=True, exist_ok=True)
            browser = subprocess.run(['node', str(Path(__file__).with_name('desk-case.cjs')),
                                      *origins, str(shots)], cwd=ROOT, capture_output=True,
                                     text=True, timeout=120)
            self.assertEqual(browser.returncode, 0, browser.stdout + browser.stderr)
            print(browser.stdout, end='')
            self.assertTrue(json.loads((shots / 'case-report.json').read_text())['four_actions'])


if __name__ == '__main__':
    unittest.main()
