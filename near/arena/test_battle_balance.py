"""The battle-mode balance sweep (battle_balance.py): covers all 8 behaviours at every crowd size, is deterministic,
and raises a flag with its numbers. A small run; the report itself is BATTLE-BALANCE.md."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import battle_balance
import sim


class Sweep(unittest.TestCase):
    def test_small_sweep_covers_every_behaviour_and_size_and_repeats_exactly(self):
        sizes, seeds = (2, 6), {2: 2, 6: 1}
        first = battle_balance.sweep(sizes=sizes, seeds=seeds, ticks=600)
        again = battle_balance.sweep(sizes=sizes, seeds=seeds, ticks=600)
        self.assertEqual(first, again, "same seeds, same report")
        names = set(battle_balance.behaviours(sim.DEFAULT_RULES))
        self.assertEqual(names, set(sim.DEFAULT_RULES["behaviour"]["stances"]) | {"pats-example"})
        self.assertEqual(len(names), 8)
        for part in ("mixed", "all"):
            self.assertEqual({(r["behaviour"], r["size"]) for r in first[part]}, {(n, s) for n in names for s in sizes})
        self.assertEqual({r["size"] for r in first["baseline"]}, set(sizes))
        self.assertEqual(first["rules_hash"], sim.digest(sim.DEFAULT_RULES))
        duel = next(r for r in first["mixed"] if r["size"] == 2)["duel"]
        self.assertEqual(duel["wins"] + duel["losses"] + duel["ties"], 2)
        six = next(r for r in first["mixed"] if r["size"] == 6)
        self.assertEqual(six["on_behaviour"], 3)
        self.assertIn("### Flags", battle_balance.markdown(first))

    def test_follow_ally_pairs_up_and_a_lone_one_names_an_absent_ally(self):
        raw = {"v": 1, "stance": "follow-ally"}
        names = ["f00", "f02", "f04"]
        self.assertEqual(battle_balance.plan_for(raw, "f00", names)["drives"]["protect_ally"], "f02")
        self.assertEqual(battle_balance.plan_for(raw, "f02", names)["drives"]["protect_ally"], "f00")
        self.assertEqual(battle_balance.plan_for(raw, "f04", names)["drives"]["protect_ally"], battle_balance.ABSENT)

    def test_each_table_is_swept_on_its_own_rules_and_old_runs_are_kept(self):
        import json
        import tempfile
        small = dict(sizes=(2,), seeds={2: 1}, ticks=1200)                 # one 60 s segment
        thirteen = battle_balance.sweep(rules=battle_balance.table("integer-13"), **small)
        fourteen = battle_balance.sweep(rules=battle_balance.table("integer-14"), **small)
        self.assertEqual((thirteen["rules_version"], fourteen["rules_version"]), ("integer-13", "integer-14"))
        stalled = lambda report: next(r for r in report["all"] if r["behaviour"] == "berserk")["stall_pct"]
        self.assertEqual(stalled(thirteen), 100, "integer-13: two berserkers never meet")
        self.assertEqual(stalled(fourteen), 0, "integer-14: chase seeks, so they fight")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.json"
            path.write_text(json.dumps(thirteen))
            self.assertEqual(list(battle_balance.load_runs(path)), ["integer-13"])
            path.write_text(json.dumps({"tables": {"integer-14": fourteen}}))
            self.assertEqual(list(battle_balance.load_runs(path)), ["integer-14"])

    def test_a_flag_carries_its_numbers(self):
        report = {"mixed": [{"behaviour": "x", "size": 2, "duel": {"wins": 9, "losses": 3, "ties": 0, "win_pct_of_decided": 75},
                             "ko_index_x100": None, "survival_index_x100": 100, "distinct_outcomes": 5},
                            {"behaviour": "x", "size": 6, "ko_index_x100": 230, "ko_share_pct": 115, "pop_share_pct": 50,
                             "survival_index_x100": 90, "distinct_outcomes": 4}],
                  "all": [{"behaviour": "x", "size": 6, "stall_pct": 75, "stalled_segments": 3, "segments": 4,
                           "distinct_outcomes": 2}],
                  "baseline": [{"size": 6, "stall_pct": 0}]}
        fields = {f["field"]: f["value"] for f in battle_balance.flags(report)}
        self.assertEqual(fields["1v1 win rate (P3 target, not a gate)"], "9-3-0 (W-L-T), 75% of decided: the behaviour wins more")
        report["mixed"][0]["duel"] = {"wins": 3, "losses": 8, "ties": 13, "win_pct_of_decided": 27}
        fields = {f["field"]: f["value"] for f in battle_balance.flags(report)}
        self.assertEqual(fields["1v1 win rate (P3 target, not a gate)"], "3-8-13 (W-L-T), 27% of decided: the default AI wins more")
        self.assertEqual(fields["KO share / ring share (P3/P4 bar)"], "2.30x (115% of KOs, 50% of ring)")
        self.assertEqual(fields["stall (whole ring on it)"], "3/4 segments with no KO (75%); default ring 0%")


if __name__ == "__main__":
    unittest.main()
