"""bar_gate computes the locked fields from run records; missing or thin cells are NOT MEASURED."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import balance
import bar_gate
import sim


def lift_run(left, right, kos, ticks, seed=1, style="brawler"):
    return {"scenario": {"family": "legendary_lift", "left": left, "right": right, "style": style, "crowd": 6},
            "seed": seed, "shares": {"fighter": {"holder": {"kos": kos, "ticks": ticks}}}, "lives": []}


class Gate(unittest.TestCase):
    def test_p1_is_a_pooled_ratio_of_sums_with_a_rare_ko_floor(self):
        cells = bar_gate.p1([lift_run("leg-x", "legendary", 40, 1000, 1), lift_run("leg-x", "legendary", 20, 1000, 2),
                             lift_run("leg-x", "rare", 20, 1000, 1), lift_run("leg-x", "rare", 20, 1000, 2)])
        self.assertEqual(cells[0]["lift_milli"], 1500)
        self.assertEqual(cells[0]["status"], "within")
        cells = bar_gate.p1([lift_run("leg-x", "legendary", 61, 1000), lift_run("leg-x", "rare", 40, 1000)])
        self.assertEqual((cells[0]["lift_milli"], cells[0]["status"]), (1525, "exceeds"))
        thin = bar_gate.p1([lift_run("leg-x", "legendary", 61, 1000), lift_run("leg-x", "rare", 29, 1000)])
        self.assertEqual(thin[0]["status"], "not measured")

    def test_empty_report_is_not_measured_never_within(self):
        runs = []
        self.assertEqual(bar_gate.p7(runs)["status"], "NOT MEASURED")
        self.assertEqual(bar_gate.p6(runs)["status"], "not measured")
        self.assertTrue(all(c["status"] == "not measured" for c in bar_gate.p5(runs)))
        self.assertTrue(all(c["status"] == "not measured" for c in bar_gate.p3(runs)))

    def test_a_small_real_sweep_produces_every_field(self):
        rules = sim.DEFAULT_RULES
        matrix = [c for c in balance.scenarios(rules) if (c.family in ("crowd", "pick_pressure")
                  and c.crowd == 2 and c.style == "brawler") or c.family == "rares_newcomers"][:6]
        report = {"variances": {"20": {"seeds": [1], "variants": {"baseline": balance.report(
            rules, [1], 240, matrix=matrix, controls=["baseline"])["variants"]["baseline"]}}}}
        result = bar_gate.gate(report, 20)
        self.assertEqual(set(result["fields"]), {"P1", "P2", "P3", "P4", "P5", "P6", "P7"})
        self.assertIn("awaiting the critic", result["status"])
        self.assertTrue(all(f["status"] in ("NOT MEASURED", "not measured") for k, f in result["fields"].items()
                            if k in ("P1", "P2", "P5", "P7")))
        self.assertIn("P7", bar_gate.table(result))


class RunConditions(unittest.TestCase):
    def entry(self, **change):
        rules = sim.rules_dict(sim.DEFAULT_RULES)
        matrix = [{"family": "legendary_lift", "crowd": 6, "density": 2}, {"family": "minority", "crowd": 6, "density": 0}]
        base = {"seeds": list(range(1, 11)), "ticks_per_run": 1200, "density_ticks": 4800, "rules": rules, "matrix": matrix}
        base.update(change)
        return base

    def test_the_locked_run_conditions_pass_when_met_and_each_failure_is_listed(self):
        self.assertEqual(bar_gate.run_conditions(self.entry(), 20, "baseline", 20), [])
        for change, text in ((dict(seeds=[1, 2, 3]), "seeds"), (dict(ticks_per_run=600), "ticks per run"),
                              (dict(density_ticks=1200), "density ticks"),
                              (dict(matrix=[{"family": "legendary_lift", "crowd": 6, "density": 0},
                                            {"family": "minority", "crowd": 6, "density": 0}]), "ceil(crowd/3)"),
                              (dict(matrix=[{"family": "legendary_lift", "crowd": 6, "density": 2}]), "minority")):
            failed = bar_gate.run_conditions(self.entry(**change), 20, "baseline", 20)
            self.assertTrue(any(text in f for f in failed), (text, failed))
        self.assertTrue(bar_gate.run_conditions(self.entry(rules=dict(sim.rules_dict(sim.DEFAULT_RULES), hitVarPct=15)), 15, "baseline", 20))   # a swept variance is not the live table's own
        self.assertTrue(bar_gate.run_conditions(self.entry(), 20, "baseline"))          # base table unknown
        self.assertTrue(bar_gate.run_conditions(self.entry(), 20, "misses", 20))            # a knob variant is not the gate

    def test_a_three_seed_report_computes_as_not_measured_everywhere(self):
        rules = sim.DEFAULT_RULES
        matrix = [c for c in balance.scenarios(rules) if c.family == "crowd" and c.crowd == 2 and c.style == "brawler"][:3]
        rep = balance.report(rules, [1, 2, 3], 240, matrix=matrix, controls=["baseline"])
        result = bar_gate.gate({"variances": {"20": rep}}, 20)
        self.assertTrue(result["run_conditions_failed"])
        self.assertTrue(all(f["status"] == "NOT MEASURED" for f in result["fields"].values()))


class Amended(unittest.TestCase):
    def test_minority_scenarios_exist_for_stack_and_top72_at_crowds_6_10_16(self):
        cells = {(c.crowd, c.build) for c in balance.scenarios(sim.DEFAULT_RULES) if c.family == "minority"}
        self.assertEqual(cells, {(n, b) for n in (6, 10, 16) for b in ("stack", "top72")})
        case = balance.Scenario("minority", 6, "brawler", "stack")
        players = balance.roster(case, sim.DEFAULT_RULES, 1)
        rows = [p["loadout"]["trinket"] for p in players]
        self.assertEqual(sim.DEFAULT_RULES["items"][rows[0]]["tier"], "legendary")
        self.assertEqual(len({sim.digest(p["loadout"]) for p in players[1:]}) > 1, True)

    def test_a_run_reports_its_censored_final_lives(self):
        run = balance.run_match(balance.Scenario("crowd", 2, "brawler", "default"), sim.DEFAULT_RULES, 1, 240)
        self.assertTrue(run["censored_lives"])
        self.assertEqual(len(run["censored_lives"]), run["right_censored"])
        self.assertTrue(all({"fighter", "ticks", "worn_legendary", "loadout"} <= set(c) for c in run["censored_lives"]))

    def test_minority_cell_math_and_the_survival_ratio_counts_the_final_life(self):
        def run(p00_ticks, p00_kos, others_ticks, others_kos, p00_lives, other_lives):
            lives = [{"fighter": "p00"}] * p00_lives + [{"fighter": "p01"}] * other_lives
            return {"scenario": {"family": "minority", "crowd": 6, "build": "stack", "style": "brawler"}, "lives": lives,
                    "shares": {"fighter": {"p00": {"kos": p00_kos, "ticks": p00_ticks},
                                           "p01": {"kos": others_kos, "ticks": others_ticks}}}}
        cell = bar_gate.minority([run(1000, 30, 5000, 150, 25, 125)], 6, "stack")
        self.assertEqual(cell["index_milli"], 30 * 6000 * 1000 // (180 * 1000))        # 1000
        self.assertEqual(cell["survival_ratio_milli"], 1000 * 125 * 1000 // (25 * 5000))   # 1000
        self.assertEqual(cell["status"], "within")
        hot = bar_gate.minority([run(1000, 90, 5000, 90, 25, 125)], 6, "stack")
        self.assertEqual(hot["status"], "exceeds")
        self.assertEqual(bar_gate.minority([run(1000, 1, 5000, 10, 25, 125)], 6, "stack")["status"], "not measured")  # under the KO floor
        self.assertEqual(bar_gate.minority([], 6, "stack")["status"], "not measured")


if __name__ == "__main__":
    unittest.main()
