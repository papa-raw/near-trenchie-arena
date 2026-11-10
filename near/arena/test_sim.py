"""Portable acceptance cases for the integer arena engine."""

import ast
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sim


class Determinism(unittest.TestCase):
    def log(self):
        rows = [sim.Input(0, "join", name, 0, {"angle": angle})
                for name, angle in (("c", 180), ("a", 0), ("b", 90))]
        for tick in range(40, 9900, 40):
            for name in ("c", "a", "b"):
                rows.append(sim.Input(tick, "intent", name, tick,
                                      {"direction": (tick * 7) % 360}))
        rows.append(sim.Input(9990, "leave", "b", 9990, {}))
        return rows

    def test_ten_thousand_ticks_and_checkpoint_resume(self):
        hashes = []
        for rows in (self.log(), list(reversed(self.log()))):
            game = sim.Sim(20261106)
            for row in rows:
                game.enqueue(row)
            game.run(5000)
            restored = sim.Sim.restore(game.export(), game.rules)
            game.run(5000)
            restored.run(5000)
            self.assertEqual(game.state_hash(), restored.state_hash())
            self.assertEqual(game.state["tick"], 10000)
            self.assertEqual(len(game.checkpoints), 100)
            hashes.append(game.state_hash())
        self.assertEqual(*hashes)
        print("10000 ticks twice:", *hashes, flush=True)

    def test_splitmix_vectors_and_literal_sine(self):
        rng = sim.SplitMix64(0, sim.DEFAULT_RULES)
        self.assertEqual([rng.draw() for _ in range(3)],
                         [0xe220a8397b1dcdaf, 0x6e789e6aa1b965f4, 0x06c45d188009454f])
        self.assertEqual([sim.sin_deg(a, sim.DEFAULT_RULES)
                          for a in (0, 30, 90, 180, 270, 360, -90)],
                         [0, 512, 1024, 0, -1024, 0, -1024])
        self.assertEqual(len(sim.DEFAULT_RULES["sine"]), 91)

    def test_integer_boundary_and_rules_identity(self):
        game = sim.Sim(1)
        with self.assertRaises(ValueError):
            sim.Sim(1.0)
        for payload in ({"direction": 0.5}, {"nested": [float("nan")]}):
            with self.assertRaises(ValueError):
                game.enqueue(sim.Input(0, "intent", "a", 0, payload))
        state = game.export()
        state["rng"] = 1.5
        with self.assertRaises(ValueError):
            sim.Sim.restore(state, game.rules)
        game.state["tick"] = 0.5
        with self.assertRaises(ValueError):
            game.step()
        rules = sim.rules_dict(sim.DEFAULT_RULES)
        rules["speed_per_tick"] += 1
        other = sim.Sim(1, rules)
        self.assertNotEqual(other.rules_hash, sim.Sim(1).rules_hash)
        with self.assertRaises(TypeError):
            other.rules["speed_per_tick"] = 3

    def test_phase_input_order_and_reordering_guard(self):
        game = sim.Sim(7)
        for name in ("z", "a", "m"):
            game.enqueue(sim.Input(0, "join", name, 0, {}))
        game.step()
        original = game.export()
        game.state["fighters"] = dict(reversed(list(game.state["fighters"].items())))
        clone = sim.Sim.restore(original, game.rules)
        game.run(300)
        clone.run(300)
        self.assertEqual(game.state_hash(), clone.state_hash())
        self.assertEqual(game.phase_order,
                         ("inputs", "policy", "movement", "attacks", "projectiles",
                          "damage", "grabs", "bench", "leaves"))
        self.assertEqual(sim.ordered_ids({"z": 0, "a": 1}), ["a", "z"])
        tree = ast.parse(Path(sim.__file__).read_text())
        self.assertFalse(any(isinstance(n, ast.Constant) and isinstance(n.value, float)
                             or isinstance(n, ast.Div) for n in ast.walk(tree)))

    def test_effective_input_tick_duplicate_and_cross_process_hash(self):
        game = sim.Sim(9)
        row = game.receive("join", "a", 0, {}, receive_tick=0)
        self.assertEqual(row.tick, 2)
        game.run(2)
        self.assertFalse(game.state["fighters"])
        game.step()
        self.assertIn("a", game.state["fighters"])
        self.assertFalse(game.enqueue(row))
        with self.assertRaises(ValueError):
            game.enqueue(sim.Input(2, "join", "a", 0, {"angle": 3}))
        with self.assertRaises(ValueError):
            game.enqueue(sim.Input(0, "leave", "a", 99, {}))
        code = ("from sim import *; s=Sim(9); "
                "[s.enqueue(Input(0,'join',n,0,{})) for n in {'a','b','c'}]; "
                "s.run(1200); print(s.state_hash())")
        values = []
        import os
        for salt in ("1", "937"):
            values.append(subprocess.check_output(
                [sys.executable, "-B", "-c", code], cwd=Path(sim.__file__).parent,
                env={**os.environ, "PYTHONHASHSEED": salt}, text=True).strip())
        self.assertEqual(*values)


class Combat(unittest.TestCase):
    def game(self, seed=23, **changes):
        rules = sim.rules_dict(sim.DEFAULT_RULES)
        rules.update(changes)
        game = sim.Sim(seed, rules)
        for index, name in enumerate(("a", "b", "c")):
            game.enqueue(sim.Input(0, "join", name, 0,
                                   {"style": "brawler", "angle": index * 90}))
        game.step()
        for index, name in enumerate(("a", "b", "c")):
            f = game.state["fighters"][name]
            f.update(x=index * 500, y=0, shield_until=0, attack_at=0,
                     sig_at=99999, target="b" if name == "a" else "a")
        return game

    def test_every_weapon_and_signature_has_a_real_effect(self):
        for weapon in ("swing", "shot", "beam", "lunge", "zap", "lob"):
            with self.subTest(weapon=weapon):
                game = self.game(hitVarPct=0)
                a, b = (game.state["fighters"][n] for n in ("a", "b"))
                a["equipped"]["weapon"] = "c-" + weapon
                before = b["hp"]
                game._attacks()
                for _ in range(20):
                    game._projectiles()
                    game._damage()
                    game.state["tick"] += 1
                self.assertLess(b["hp"], before)
        for signature in ("beam_sweep", "chain_storm", "shockwave", "blink_strike",
                          "magnet", "bubble", "dodge_roll"):
            with self.subTest(signature=signature):
                game = self.game(hitVarPct=0)
                a = game.state["fighters"]["a"]
                a["equipped"]["trinket"] = ("st-roll" if signature == "dodge_roll"
                                               else "c-" + signature.replace("_", "-"))
                a["intent"]["sig"] = "use"
                a["sig_at"] = 0
                game._attacks()
                self.assertIsNotNone(a["cast"])
                self.assertGreaterEqual(a["cast"]["resolve_at"] - game.state["tick"], 10)
                for _ in range(35):
                    game.state["tick"] += 1
                    game._attacks()
                    game._projectiles()
                    game._damage()
                self.assertTrue(any(e["kind"] == "signature" and e["signature"] == signature
                                    for e in game.state["events"]))

    def test_variance_rounding_draw_count_and_segment_replay(self):
        game = self.game(hitVarPct=20)
        before = game.rng.state
        independent = sim.SplitMix64(before, game.rules)
        multiplier = 80 + independent.draw() % 41
        self.assertEqual(game.damage_amount(17, 121, 120, 90),
                         max(1, (17 * 121 * 120 * 90 // 1000000) * multiplier // 100))
        self.assertEqual(game.rng.state, independent.state)
        zero = self.game(hitVarPct=0)
        before = zero.rng.state
        self.assertEqual(zero.damage_amount(17, 121, 120, 90),
                         max(1, 17 * 121 * 120 * 90 // 1000000))
        self.assertEqual(before, zero.rng.state)
        start = game.export()
        clone = sim.Sim.restore(start, game.rules)
        game.run(1200)
        clone.run(1200)
        self.assertEqual(game.state_hash(), clone.state_hash())
        print("variance segment:", game.state_hash(), flush=True)

    def test_ko_drops_only_one_worn_item_and_scatter_is_clamped(self):
        for edge in (False, True):
            game = self.game(hitVarPct=0)
            f = game.state["fighters"]["b"]
            f["bag"] = {"r-swing": game.inventory_entry("r-swing"),
                        "r-shot": game.inventory_entry("r-shot")}
            f["equipped"]["weapon"] = "r-swing"
            f.update(x=11000 if edge else 0, y=0, hp=1)
            game.queue_hit("a", "b", 999)
            game._damage()
            self.assertEqual(f["state"], "bench")
            self.assertEqual(game.state["fighters"]["a"]["life_kos"], 1)
            self.assertEqual(len(game.state["drops"]), 1)
            drop = next(iter(game.state["drops"].values()))
            self.assertEqual(drop["row"], "r-swing")
            self.assertIn("r-shot", f["bag"])
            self.assertNotIn("r-swing", f["bag"])
            self.assertLessEqual(drop["x"] ** 2 + drop["y"] ** 2, game.rules["radius"] ** 2)
            if not edge:
                distance = (drop["x"] ** 2 + drop["y"] ** 2)
                self.assertGreaterEqual(distance, 2990 ** 2)
                self.assertLessEqual(distance, 4010 ** 2)
        game = self.game()
        game.queue_hit("a", "b", 999)
        game._damage()
        self.assertFalse(game.state["drops"])

    def test_grab_is_six_undamaged_ticks_house_refusal_and_duplicate_sink(self):
        game = self.game(hitVarPct=0)
        a = game.state["fighters"]["a"]
        game.state["fighters"]["b"]["x"] = 10000
        game.state["fighters"]["c"]["x"] = -10000
        drop_id = game.drop_item("r-swing", a["x"], a["y"], "b", False)
        a["house"] = True
        for _ in range(6):
            game._grabs()
        self.assertIn(drop_id, game.state["drops"])
        a["house"] = False
        for _ in range(5):
            game._grabs()
        self.assertNotIn("r-swing", a["bag"])
        game.queue_hit("b", "a", 1)
        game._damage()
        self.assertEqual(a["grab_ticks"], 0)
        game.state["tick"] += 1
        for _ in range(6):
            game._grabs()
        self.assertNotIn(drop_id, game.state["drops"])
        self.assertIn("r-swing", a["bag"])
        self.assertEqual(a["equipped"]["weapon"], "r-swing")
        before = game.export()["fighters"]["a"]["bag"]
        duplicate = game.drop_item("r-swing", a["x"], a["y"], "b", False)
        for _ in range(6):
            game._grabs()
        self.assertNotIn(duplicate, game.state["drops"])
        self.assertEqual(a["bag"], before)

    def test_floor_loss_and_legendary_serials(self):
        game = self.game()
        a = game.state["fighters"]["a"]
        first = game.drop_item("leg-laser-eyes", a["x"], a["y"], "b", True)
        for _ in range(6):
            game._grabs()
        serial1 = a["bag"]["leg-laser-eyes"]["serial"]
        del a["bag"]["leg-laser-eyes"]
        a["equipped"]["trinket"] = "st-roll"
        game.drop_item("leg-laser-eyes", a["x"], a["y"], "b", True)
        for _ in range(6):
            game._grabs()
        self.assertGreater(a["bag"]["leg-laser-eyes"]["serial"], serial1)
        drop = game.drop_item("r-beam", 11000, 0, "a", False)
        expires = game.state["drops"][drop]["expires_at"]
        self.assertEqual(expires - game.state["tick"], 1200)
        game.state["tick"] = expires
        game._grabs()
        self.assertNotIn(drop, game.state["drops"])
        self.assertNotIn("r-beam", a["bag"])

    def test_respawn_restores_house_kit_and_shield_and_inventory_fence(self):
        game = self.game()
        b = game.state["fighters"]["b"]
        b["house"] = True
        b["kit"]["weapon"] = "r-swing"
        b["equipped"]["weapon"] = "r-swing"
        b["bag"]["r-swing"] = game.inventory_entry("r-swing")
        game.queue_hit("a", "b", 999)
        game._damage()
        self.assertEqual(b["respawn_at"] - game.state["tick"], 900)
        game.state["tick"] = b["respawn_at"] - 1
        game._bench()
        self.assertEqual(b["state"], "bench")
        game.state["tick"] += 1
        game._bench()
        self.assertEqual(b["state"], "alive")
        self.assertEqual(b["equipped"]["weapon"], "r-swing")
        self.assertEqual(b["shield_until"] - game.state["tick"], 40)
        hp = b["hp"]
        game.queue_hit("a", "b", 10)
        game._damage()
        self.assertEqual(b["hp"], hp)
        game.enqueue(sim.Input(game.state["tick"], "loadout", "a", 100,
                               {"weapon": "c-zap"}))
        with self.assertRaises(ValueError):
            game._inputs()

    def test_leave_requires_surf_and_disconnect_grace(self):
        game = self.game()
        a = game.state["fighters"]["a"]
        a.update(leave=True, x=0, y=0)
        game._leaves()
        self.assertEqual(a["surf_ticks"], 0)
        a["x"] = game.rules["radius"]
        for _ in range(99):
            game._leaves()
        self.assertEqual(a["state"], "alive")
        game.queue_hit("b", "a", 1)
        game._damage()
        self.assertEqual(a["surf_ticks"], 0)
        game.state["tick"] += 1
        for _ in range(100):
            game._leaves()
        self.assertEqual(a["state"], "left")
        b = game.state["fighters"]["b"]
        game.enqueue(sim.Input(game.state["tick"], "disconnect", "b", 100, {}))
        game._inputs()
        self.assertEqual(b["disconnected_until"] - game.state["tick"], 600)
        self.assertFalse(b["leave"])
        game.state["tick"] += 600
        game._leaves()
        self.assertTrue(b["leave"])

    def test_styles_rival_seek_bounty_and_seeded_loot(self):
        game = self.game()
        self.assertEqual(set(game.rules["styles"]),
                         {"brawler", "hunter", "looter", "guardian", "survivor"})
        a, b = (game.state["fighters"][n] for n in ("a", "b"))
        a.update(house=True, rivals=["b"], legendary="leg-laser-eyes")
        b.update(x=11000, y=0)
        score = game.target_score(a, b)
        a["rivals"] = []
        self.assertEqual(score - game.target_score(a, b), 300)
        b["equipped"]["trinket"] = "leg-laser-eyes"
        score = game.target_score(a, b)
        b["equipped"]["trinket"] = "st-roll"
        self.assertEqual(score - game.target_score(a, b), 150)
        a["rivals"] = ["b"]
        game._policy()
        self.assertEqual(a["target"], "b")
        rules = sim.rules_dict(game.rules)
        rules["combat_enabled"] = False
        game = sim.Sim(77, rules)
        game.run(1201)
        loot = [d for d in game.state["drops"].values() if d["origin"] == "arena"]
        self.assertEqual(len(loot), 6)
        self.assertEqual([d["created_at"] for d in loot], [200,400,600,800,1000,1200])

    def test_catalog_caps_and_existing_serial_high_watermark(self):
        sim.validate_rules(sim.DEFAULT_RULES)
        invalid = sim.rules_dict(sim.DEFAULT_RULES)
        invalid["items"]["r-swing"]["stats"]["damage"] = 100
        with self.assertRaises(ValueError):
            sim.Sim(1, invalid)
        game = sim.Sim(12)
        entry = game.inventory_entry("leg-laser-eyes")
        entry["serial"] = 407
        game.enqueue(sim.Input(0, "join", "a", 0, {"bag": {"leg-laser-eyes": entry}}))
        game.step()
        a = game.state["fighters"]["a"]
        del a["bag"]["leg-laser-eyes"]
        game.drop_item("leg-laser-eyes", a["x"], a["y"], None, True)
        for _ in range(6):
            game._grabs()
        self.assertGreater(a["bag"]["leg-laser-eyes"]["serial"], 407)

    def test_signature_effects_use_current_values_and_shield_ends_on_attack(self):
        for kind in ("magnet", "bubble", "dodge_roll", "blink_strike"):
            game = self.game(hitVarPct=0)
            a, b = (game.state["fighters"][n] for n in ("a", "b"))
            a["equipped"]["trinket"] = "st-roll" if kind == "dodge_roll" else "c-" + kind.replace("_", "-")
            b["x"] = 3000
            game.state["fighters"]["c"]["x"] = -11000
            cast = {"kind": kind, "target": "b", "x": 3000, "y": 0}
            before = (a["x"], a["y"], b["x"], b["hp"])
            game._signature(a, cast)
            if kind in ("magnet", "bubble"):
                self.assertEqual(a["shield"], 30)
            if kind == "magnet":
                self.assertEqual(b["x"], 500)
            if kind == "dodge_roll":
                self.assertNotEqual((a["x"], a["y"]), before[:2])
                self.assertEqual(a["invulnerable_until"] - game.state["tick"], 6)
            if kind == "blink_strike":
                game._damage()
                self.assertLess(b["hp"], before[3])
        game = self.game(hitVarPct=0)
        a = game.state["fighters"]["a"]
        a["shield_until"] = 999
        game._attacks()
        self.assertEqual(a["shield_until"], game.state["tick"])


class Compatibility(unittest.TestCase):
    def test_archived_integer_rules_keep_their_combat_hash(self):
        import json
        rules = json.loads((Path(__file__).parent / "rules" / "integer-2.json").read_text())
        game = sim.Sim(23, rules)
        for index, name in enumerate(("a", "b", "c")):
            game.enqueue(sim.Input(0, "join", name, 0,
                                   {"style": "brawler", "angle": index * 90}))
        game.step()
        for index, name in enumerate(("a", "b", "c")):
            game.state["fighters"][name].update(x=index * 500, y=0, shield_until=0,
                                                attack_at=0, sig_at=99999,
                                                target="b" if name == "a" else "a")
        probe = sim.Sim.restore(game.export(), rules)
        probe.state["fighters"]["a"]["intent"]["sig"] = "use"
        probe.state["fighters"]["a"]["sig_at"] = 0
        probe._attacks()
        self.assertNotIn("item_id", probe.state["fighters"]["a"]["cast"])
        game.damage_amount(17, 121, 120, 90)
        game.run(1200)
        self.assertEqual(game.state_hash(), "51e549748bee0baa9150ef18938db06ab5c63e5324c6e045b111f2ae65cea85c")


if __name__ == "__main__":
    unittest.main()
