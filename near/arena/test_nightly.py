"""F9: nightly columns from sealed logs: shares add up, the report is deterministic, stack builds come first."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nightly
import sim
import test_loot_variance as tlv


def crowded_segment():
    rules = sim.rules_dict(sim.DEFAULT_RULES)
    game = sim.Sim(41, rules)
    start = game.export()
    rows = []
    for i in range(6):
        row = sim.Input(0, "join", "p0%d" % i, 0, {"angle": i * 60})
        game.enqueue(row)
        rows.append(row)
    game.run(1200)
    import server
    record = {"initial_state": start, "rules_hash": game.rules_hash,
              "commands": [{"kind": "input", "value": r.record()} for r in rows] + [{"kind": "advance", "value": 1200}],
              "predictions": [], "sealed": {"tick_count": "1200", "final_state_hash": game.state_hash()}}
    record["sealed"]["sealed_result_hash"] = server.engine_commitment(record)
    return record


class Nightly(unittest.TestCase):
    def test_columns_add_up_are_deterministic_and_stack_builds_sort_first(self):
        record = crowded_segment()
        out = nightly.report([record])
        self.assertEqual(out, nightly.report([record]))
        self.assertGreater(out["hits"], 0)
        columns = out["weapon_columns"]
        self.assertTrue(abs(sum(c["damage_share_milli"] for c in columns.values()) - 1000) <= len(columns))
        self.assertEqual(sum(c["kos"] for c in columns.values()), sum(p["kos"] for p in out["build_style_pairs"].values()))
        win = out["win_after_first_ko"]
        self.assertLessEqual(win["reached_second"], win["lives_with_first_ko"])
        keys = list(out["build_style_pairs"])
        self.assertEqual(keys, sorted(keys, key=lambda k: ("/stack" not in k, k)))
        self.assertTrue(all(p["lives"] > 0 for p in out["build_style_pairs"].values()))


if __name__ == "__main__":
    unittest.main()
