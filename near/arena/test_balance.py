"""Focused sweep cases and exact arithmetic fixtures."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sim
import test_policy


class Baseline(unittest.TestCase):
    def test_baseline_weapon_and_signature_constants_match_the_tuned_model(self):
        r = sim.DEFAULT_RULES
        self.assertEqual((r["weapons"]["shot"]["damage"], r["weapons"]["beam"]["cooldown"]), (7, 34))
        self.assertEqual((r["signatures"]["shockwave"]["damage"], r["signatures"]["shockwave"]["cooldown"]), (12, 200))
        self.assertEqual(r["signatures"]["blink_strike"]["behind"], 900)
        self.assertEqual(r["signatures"]["beam_sweep"]["width"], 500)

    def test_counter_cycle_is_applied_before_variance_and_records_the_move(self):
        g, a, b = test_policy.Knobs().game()
        rules = sim.rules_dict(g.rules)
        rules["hitVarPct"] = 0
        g.rules = sim.freeze(rules)
        b["equipped"]["weapon"] = "c-shot"
        hp = b["hp"]
        g.queue_hit("a", "b", 10, move="lunge")
        g._damage()
        self.assertEqual(hp - b["hp"], 15)
        self.assertEqual(g.state["events"][-1]["move"], "lunge")
        b["equipped"]["weapon"] = "c-lunge"
        hp = b["hp"]
        g.queue_hit("a", "b", 10, move="shot")
        g._damage()
        self.assertEqual(hp - b["hp"], 6)
        self.assertEqual(g.rules["counter_pct"], 50)

    def test_threat_sidestep_and_recharging_shot_slow_are_in_the_baseline(self):
        g, a, b = test_policy.Knobs().game()
        a.update(move_x=a["speed"], move_y=0)
        a["equipped"]["weapon"] = "c-shot"
        g._movement()
        self.assertEqual(a["x"], a["speed"] // 2)
        a["x"] = 0
        g._object({"kind": "shot", "owner": "b", "x": -1000, "y": 0,
                   "vx": 350, "vy": 0, "resolve_at": 1})
        g._policy()
        self.assertGreater(a["move_y"], 0)
        self.assertEqual(g.rules["weapons"]["shot"]["speed"], 350)
        self.assertEqual(g.rules["shot_hit_radius"], 250)


class Sweep(unittest.TestCase):
    def test_first_life_requires_distinct_victims_of_that_rare_life(self):
        import balance
        def death(victim, source, life=0, source_life=0):
            return {"fighter": victim, "source": source, "life_id": f"{victim}:{life}",
                    "source_life_id": f"{source}:{source_life}", "kos": 2}
        def run(lives):
            return {"scenario": {"family": "rares_newcomers", "crowd": 3},
                    "lives": lives, "shares": {"fighter": {"p00": {"kos": 2}}}}
        repeated = [death("p01", "p00"), death("p01", "p00", 1), death("p02", "p01")]
        wrong_life = [death("p01", "p00", source_life=1), death("p02", "p00", source_life=1)]
        winner = [death("p01", "p00"), death("p02", "p00")]
        loser = [death("p01", "p00"), death("p00", "p02")]
        rows = [run(repeated), run(wrong_life), run(winner), run(loser)]
        result = balance.set_pieces(rows)["3"]
        self.assertEqual(result["rare_win_bps"], 5000)
        self.assertEqual(result["resolved_runs"], 2)
        self.assertEqual(result["censored_runs"], 2)
        old = run([{"fighter": "p01", "kos": 0}, {"fighter": "p02", "kos": 0}])
        self.assertEqual(balance.set_pieces([old])["3"]["evidence_missing_runs"], 1)
        self.assertIsNone(balance.set_pieces([old])["3"]["rare_win_bps"])

    def test_measure_keeps_victim_and_attacker_life_identity(self):
        import balance
        game = sim.Sim(1)
        for sequence, name in enumerate(("p00", "p01")):
            game.enqueue(sim.Input(0, "join", name, sequence, {"style": "brawler"}))
        game.step()
        measure = balance.Measure(game)
        before = measure.before()
        game.state["tick"] = 20
        measure._life({"fighter": "p01", "source": "p00", "life_id": "p01:0", "life_kos": 0}, before)
        row = measure.result()["lives"][0]
        self.assertEqual((row["source"], row["life_id"], row["source_life_id"]),
                         ("p00", "p01:0", "p00:0"))

    def test_set_pieces_count_a_surviving_winner_and_keep_censoring_explicit(self):
        import balance
        def run(lives, kos):
            return {"scenario": {"family": "rares_newcomers", "crowd": 2},
                    "lives": lives, "shares": {"fighter": {"p00": {"kos": kos}}}}
        rows = [run([{"fighter": "p01", "source": "p00", "life_id": "p01:0", "source_life_id": "p00:0", "kos": 0}], 1),
                run([{"fighter": "p00", "source": "p01", "life_id": "p00:0", "source_life_id": "p01:0", "kos": 0}], 0), run([], 0)]
        result = balance.set_pieces(rows)["2"]
        self.assertEqual(result["rare_win_bps"], 5000)
        self.assertEqual(result["resolved_runs"], 2)
        self.assertEqual(result["censored_runs"], 1)

    def test_stop_at_one_never_requests_leave_from_a_closed_life(self):
        import balance
        rules = sim.rules_dict(sim.DEFAULT_RULES)
        rules["knobs"]["beam_fire_slow"] = True
        result = balance.run_match(balance.Scenario("stop_at_one", 6, build="mean52"), rules, 1, 1200)
        self.assertTrue(result["final_state_hash"])

    def test_density_duration_extends_hunt_samples_without_repeating_other_inputs(self):
        import balance
        from unittest.mock import patch
        real = balance.measure_cached
        durations = []
        def measure(task):
            durations.append(task[3])
            return real(task)
        matrix = [balance.Scenario("crowd", 2), balance.Scenario("density", 6, density=4)]
        with patch.object(balance, "measure_cached", measure):
            result = balance.report(sim.DEFAULT_RULES, [1], 12, matrix,
                                    controls=["baseline"], density_ticks=48)
        self.assertEqual(durations, [12, 48])
        self.assertEqual(result["density_ticks"], 48)

    def test_declared_matrix_covers_styles_crowds_pairs_loot_and_density(self):
        import balance
        matrix = balance.scenarios(sim.DEFAULT_RULES)
        self.assertEqual(matrix[0].family, "stack")
        for crowd in (2, 6, 10, 16):
            self.assertEqual({s.style for s in matrix if s.family == "crowd" and s.crowd == crowd},
                             set(sim.DEFAULT_RULES["styles"]))
        for crowd in (6, 10, 16):
            for density in (4, 14):
                for on in (False, True):
                    self.assertTrue(any(s.family == "density" and s.crowd == crowd and
                                        s.density == density and s.bounty == on for s in matrix))
        dense = balance.Scenario("density", 6, density=14, build="mean52")
        rows = balance.roster(dense, sim.DEFAULT_RULES, 1)
        self.assertEqual(len(rows), 6)
        legends = {row for r in rows for row in r["bag"] if sim.DEFAULT_RULES["items"][row]["tier"] == "legendary"}
        self.assertEqual(len(legends), 14)

    def test_ratios_use_time_and_missing_denominators_stay_missing(self):
        import balance
        from collections import Counter
        rows = balance.shares(Counter(a=30, b=70), Counter(a=6, b=4))
        self.assertEqual(rows["a"]["index_milli"], 2000)
        self.assertEqual(rows["b"]["index_milli"], 571)
        self.assertIsNone(balance.shares(Counter(a=0), Counter())["a"]["index_milli"])

    def test_small_real_engine_report_is_repeatable_and_keeps_all_fields(self):
        import balance
        matrix = [balance.Scenario("crowd", 2), balance.Scenario("shared_owner", 2)]
        a = balance.report(sim.DEFAULT_RULES, [1], 12, matrix)
        b = balance.report(sim.DEFAULT_RULES, [1], 12, matrix)
        self.assertEqual(sim.digest(a), sim.digest(b))
        self.assertEqual(set(a["variants"]), {"baseline", *sim.DEFAULT_RULES["knobs"]})
        for variant in a["variants"].values():
            self.assertEqual(len(variant["fields"]), 7)
            self.assertIn("survival_pairs", variant["fields"]["hunted_loop"])
            self.assertEqual(variant["runs"][1]["owner_groups"], {"p00": "one-owner", "p01": "one-owner"})
            self.assertEqual(variant["status"], "awaiting independent review")


class Summary(unittest.TestCase):
    def test_compact_report_retains_each_duel_and_its_target_status(self):
        import balance
        import balance_summary
        fields = balance.bar_fields([])
        rows = {
            "weapon_duel/beam/shot/10": {"left_wins": 2, "right_wins": 1, "draws": 1,
                "left_rate_bps": 6666, "distinct_outcomes": 3, "runs": 4},
            "signature_duel/bubble/magnet/10": {"left_wins": 0, "right_wins": 0,
                "draws": 2, "left_rate_bps": None, "distinct_outcomes": 1, "runs": 2}}
        fields["move_parity"]["duels"] = rows
        result = balance_summary.summarize_variant(
            {"fields": fields, "runs": [], "observed_kos": 0}, sim.DEFAULT_RULES)
        duels = result["mirrored_duels"]
        self.assertFalse(duels["target_is_gate"])
        self.assertEqual(duels["target_bps"], [4000, 6000])
        for key, row in rows.items():
            self.assertEqual({k: duels["pairs"][key][k] for k in row}, row)
        self.assertEqual(duels["pairs"]["weapon_duel/beam/shot/10"]["decisive_runs"], 3)
        self.assertEqual(duels["pairs"]["weapon_duel/beam/shot/10"]["target_status"], "outside")
        self.assertEqual(duels["pairs"]["signature_duel/bubble/magnet/10"]["target_status"], "unmeasured")

    def test_style_comparison_uses_matched_crowds_and_excludes_duel_mix(self):
        import balance_summary as summary
        rows = [{"scenario": {"family": family}, "lives": [{"style": style, "kos": 1,
                 "ticks": 20, "items_kept": 2}]} for family, style in
                (("crowd", "guardian"), ("weapon_duel", "brawler"))]
        data = summary.matched_styles(rows, ["guardian", "brawler"])
        self.assertEqual(set(data["outcomes"]), {"guardian"})
        self.assertEqual(data["missing_styles"], ["brawler"])

    def test_leave_policy_revision_invalidates_only_its_two_declared_families(self):
        import balance
        import tempfile
        source = Path(balance.__file__).read_text()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "previous.py"
            # The old policy differed only in this explicitly family-scoped block.
            path.write_text(source.replace('f["state"] == "alive" and ', ''))
            _, families = balance._checkpoint_state(path)
            self.assertEqual(set(families), {"escape", "stop_at_one"})

    def test_counterfactual_abuse_score_keeps_zero_and_constant_calls_have_zero_skill(self):
        import balance_summary as summary
        point_one = [0, 10000, 0, 0, 0]
        self.assertEqual(summary.rps_numerator(point_one, 1), 0)
        self.assertEqual(summary.rps_numerator(point_one, 0), 100000000)
        rows = [{"fighter": "a", "actual": 1, "forecast_bps": point_one} for _ in range(20)]
        self.assertEqual(summary.counterfactual_readout(rows)["a"]["own_skill_milli"], 0)
        self.assertIsNone(summary.counterfactual_readout(rows[:3])["a"]["own_skill_milli"])

    def test_resume_rejects_a_changed_measurement_function(self):
        import balance
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "previous.py"
            source = Path(balance.__file__).read_text()
            path.write_text(source)
            self.assertEqual(len(balance.checkpoint_hash(path)), 64)
            path.write_text(source.replace('sequence = 0', 'sequence = 99'))
            with self.assertRaisesRegex(ValueError, "measurement code"):
                balance.checkpoint_hash(path)

    def test_real_zero_kos_stay_in_base_rates_and_unmeasured_ratios_do_not_pass(self):
        import balance_summary
        lives = [{"kos": n, "ticks": 20} for n in (0, 0, 1, 2, 3, 7)]
        rates = balance_summary.base_rates(lives)
        self.assertEqual(rates["bins"], [2, 1, 1, 1, 1])
        self.assertEqual(sum(rates["spread_bps"]), 10000)
        self.assertEqual(rates["mean_life_ticks_milli"], 20000)
        empty = balance_summary.base_rates([])
        self.assertIsNone(empty["spread_bps"])
        self.assertEqual(balance_summary.over_limit([None, 1400, 1600], 1500),
                         {"observed": 2, "missing": 1, "exceedances": 1, "worst": 1600})

    def test_tuned_hunt_is_a_distinct_table_and_baseline_remains_replayable(self):
        import replay
        baseline = sim.rules_dict(sim.DEFAULT_RULES)
        tuned = json.loads((Path(__file__).parent / "rules/integer-10.json").read_bytes())
        self.assertEqual(baseline["bounty_weight"], 150)
        self.assertEqual(tuned["bounty_weight"], 100)
        before = sim.Sim(8, baseline)
        after = sim.Sim(8, tuned)
        self.assertNotEqual(before.rules_hash, after.rules_hash)
        self.assertEqual(replay.load_rules(before.rules_hash), sim.freeze(baseline))
        self.assertEqual(replay.load_rules(after.rules_hash), sim.freeze(tuned))



if __name__ == "__main__":
    unittest.main()
