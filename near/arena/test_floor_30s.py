"""New 30-second floor table, exact expiry tick, and an unchanged shipped old-rules replay.

Run only this authored case: python3 -B near/arena/test_floor_30s.py Floor30s.test_new_table_expires_at_600_and_old_segment_replays
"""
import hashlib
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import replay
import sim

OLD_HASH = '852a82695da097598170e8dd4ab514a82010e68d483e544d434d9ea8e199d20e'
NEW_HASH = sim.digest(sim.DEFAULT_RULES)


class Floor30s(unittest.TestCase):
    def test_new_table_expires_at_600_and_old_segment_replays(self):
        self.assertEqual(sim.DEFAULT_RULES['floor_ticks'], 600, 'default ungrabbed drops last 30 seconds at 20 Hz')
        old_path = HERE / 'rules/integer-16.json'
        old_bytes = old_path.read_bytes()
        old = json.loads(old_bytes)
        new_path = HERE / 'rules' / (sim.DEFAULT_RULES['version'] + '.json')
        new = json.loads(new_path.read_bytes())
        self.assertEqual(sim.digest(old), OLD_HASH)
        self.assertEqual(sim.digest(new), NEW_HASH)
        self.assertEqual(sim.digest(sim.DEFAULT_RULES), NEW_HASH)
        self.assertEqual(new['floor_ticks'], 600)
        self.assertEqual(old['floor_ticks'], 1200)
        self.assertNotEqual(new['version'], old['version'])
        self.assertEqual(set(new), set(old))
        self.assertEqual(sim.digest(replay.load_rules(NEW_HASH)), NEW_HASH)
        self.assertEqual(sim.digest(replay.load_rules(OLD_HASH)), OLD_HASH)

        # The expiry phase processes tick 600 itself; step() advances the public clock after processing a tick.
        # Check both player and house origin, plus a legendary: every ungrabbed drop uses the table's lifetime.
        for row, house in [('r-lob', False), ('r-lob', True), ('leg-lifeboat', True)]:
            with self.subTest(item=row, house=house):
                game = sim.Sim(731, new)
                key = game.drop_item(row, 0, 0, None, house)
                self.assertEqual(game.state['drops'][key]['expires_at'], 600)
                game.state['tick'] = 599
                game._grabs()
                self.assertIn(key, game.state['drops'], 'not one tick early')
                game.state['tick'] = 600
                game._grabs()
                self.assertNotIn(key, game.state['drops'], 'gone while processing tick 600')
                self.assertIn({'kind': 'floor_loss', 'drop': key}, game.state['events'])
        archived = sim.Sim(731, old)
        key = archived.drop_item('r-lob', 0, 0, None, False)
        archived.state['tick'] = 600
        archived._grabs()
        self.assertIn(key, archived.state['drops'], 'old table keeps its 60-second lifetime')
        archived.state['tick'] = 1200
        archived._grabs()
        self.assertNotIn(key, archived.state['drops'])

        # Replay a real pinned segment, not a newly generated fixture. Exact-hash lookup selects its archived table.
        replay_root = HERE.parent / 'replay'
        manifest_bytes = (replay_root / 'MANIFEST').read_bytes()
        manifest = json.loads(manifest_bytes)
        path = replay_root / manifest['batches'][0]['segments'][0]['record']
        segment_bytes = path.read_bytes()
        segment = json.loads(segment_bytes)
        result = replay.replay_segment(segment)
        self.assertEqual(result.rules_hash, segment['rules_hash'])
        self.assertNotEqual(result.rules_hash, NEW_HASH)
        self.assertEqual(result.state_hash(), segment['sealed']['final_state_hash'])
        self.assertEqual(replay.engine_commitment(segment), segment['sealed']['sealed_result_hash'])
        self.assertEqual(old_path.read_bytes(), old_bytes)
        self.assertEqual(path.read_bytes(), segment_bytes)
        self.assertEqual((replay_root / 'MANIFEST').read_bytes(), manifest_bytes)
        print(json.dumps({'new_rules': NEW_HASH, 'floor_ticks': 600, 'seconds': 30,
                          'archived_segment': path.name, 'old_rules': result.rules_hash,
                          'old_final_state': result.state_hash(),
                          'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest()}, sort_keys=True))


if __name__ == '__main__':
    unittest.main()
