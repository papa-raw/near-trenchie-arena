"""F88: a fetched public log replays to its batch hash; private fields never reach the public directory."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import public_logs
import sim
import test_server as ts


class PublicLogs(unittest.TestCase):
    def test_a_published_segment_replays_to_the_hash_in_the_index(self):
        comp = ts.Composition("test_sixteen_admitted_six_ring_and_fifo_bench")
        comp.tmp = tempfile.TemporaryDirectory()
        arena = comp.arena()
        for name in ("a", "b", "c"):
            comp.start(arena, ts.binding(name))
        arena.advance(sim.DEFAULT_RULES["segment_ticks"] + 4)
        with tempfile.TemporaryDirectory() as out:
            index = public_logs.publish(comp.tmp.name, out)
            self.assertEqual(len(index["segments"]), 1)
            row = index["segments"][0]
            fetched = Path(out) / row["file"]
            self.assertEqual(public_logs.verify(fetched, row["final_state_hash"]), row["final_state_hash"])
            with self.assertRaises(ValueError):
                public_logs.verify(fetched, "0" * 64)
            for path in Path(out).rglob("*"):
                if path.is_file():
                    self.assertNotIn(b"PRIVATE-CANARY", path.read_bytes())
            self.assertEqual(json.loads((Path(out) / "index.json").read_text())["index_hash"], index["index_hash"])
            again = public_logs.publish(comp.tmp.name, out)           # republishing is idempotent
            self.assertEqual(again, index)
        comp.tmp.cleanup()

    def test_a_record_with_a_private_field_is_not_published(self):
        with tempfile.TemporaryDirectory() as data, tempfile.TemporaryDirectory() as out:
            (Path(data) / "segments").mkdir()
            (Path(data) / "segments" / "segment-0.json").write_text(json.dumps(
                {"rules_hash": "r", "sealed": {"segment_id": "segment:0", "final_state_hash": "f",
                                                "sealed_result_hash": "s"}, "note": {"api_key": "x"}}))
            with self.assertRaises(ValueError):
                public_logs.publish(data, out)


if __name__ == "__main__":
    unittest.main()
