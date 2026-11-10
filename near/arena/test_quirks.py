"""Focused legendary tradeoffs, cast binding and one sealed segment replay."""

import argparse
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import replay
import sim


RULES_PATH = Path(__file__).parent / "rules" / "integer-11.json"


def table() -> dict:
    return json.loads(RULES_PATH.read_bytes())


def arena(row: str, positions: tuple = ((2000, 0),)) -> tuple:
    """Neutral percentages isolate base effects; ordinary joins create each body."""
    game = sim.Sim(71, table())
    kit = {**game.rules["default_loadout"], "trinket": row}
    bag = {} if game.rules["items"][row]["default"] else {row: game.inventory_entry(row)}
    game.enqueue(sim.Input(0, "join", "a", 0, {"angle": 0, "loadout": kit, "bag": bag}))
    for index in range(len(positions)):
        game.enqueue(sim.Input(0, "join", chr(ord("b") + index), 0, {"angle": 0}))
    game._inputs()
    game.state["tick"] = 100
    for index, fighter in enumerate(game.state["fighters"].values()):
        x, y = (0, 0) if index == 0 else positions[index - 1]
        fighter.update(x=x, y=y, hp=100, max_hp=100, damage_pct=100, cooldown_pct=100,
                       sig_range_pct=100, attack_at=10**9, sig_at=10**9, shield_until=0)
    wearer = game.state["fighters"]["a"]
    wearer.update(sig_at=0, target="b")
    return game, wearer


def start(game: sim.Sim, wearer: dict, force: bool = True) -> dict | None:
    if force:
        wearer["intent"]["sig"] = "use"
    game._attacks()
    return wearer["cast"]


def resolve(game: sim.Sim, wearer: dict) -> None:
    game.state["tick"] = wearer["cast"]["resolve_at"]
    game._attacks()


class Quirks(unittest.TestCase):
    """Each selected tradeoff must fail on the archived baseline."""

    def test_stack_sats(self) -> None:
        game, f = arena("leg-stack-sats")
        start(game, f)
        self.assertEqual(f["sig_at"], 364)
        resolve(game, f)
        self.assertEqual(f["shield"], 33)

    def test_liquidity_wave(self) -> None:
        game, f = arena("leg-liquidity-wave")
        start(game, f)
        resolve(game, f)
        self.assertEqual([(h["base"], h["knockback"]) for h in game.state["damages"]], [(11, 2200)])

    def test_tinker_coil(self) -> None:
        game, f = arena("leg-tinker-coil", ((4200, 0), (8500, 0)))
        start(game, f)
        resolve(game, f)
        self.assertEqual([(h["target"], h["base"]) for h in game.state["damages"]], [("b", 27), ("c", 27)])

    def test_laser_eyes(self) -> None:
        game, f = arena("leg-laser-eyes", ((4900, 0),))
        start(game, f)
        resolve(game, f)
        obj = next(iter(game.state["objects"].values()))
        self.assertEqual((obj["range"], obj["angle"]), (4950, -24))
        # Halfway through the sweep is its original aim line. Using the shared
        # 60-degree arc here would miss this body at the longer range.
        game.state["tick"] += 10
        game._projectiles()
        self.assertEqual([h["target"] for h in game.state["damages"]], ["b"])

    def test_ether_stack(self) -> None:
        game, f = arena("leg-ether-stack", ((3000, 0),))
        drop = game.drop_item("r-shot", 4200, 0, None, True)
        start(game, f)
        resolve(game, f)
        self.assertEqual((game.state["drops"][drop]["x"], game.state["drops"][drop]["y"]), (0, 0))
        self.assertEqual(game.state["fighters"]["b"]["x"], 750)

    def test_fast_finality(self) -> None:
        game, f = arena("leg-fast-finality")
        cast = start(game, f)
        self.assertEqual((cast["resolve_at"], f["invulnerable_until"], f["cannot_attack_until"]), (126, 126, 141))
        resolve(game, f)
        self.assertEqual([h["base"] for h in game.state["damages"]], [16])

    def test_lifeboat(self) -> None:
        game, f = arena("leg-lifeboat")
        start(game, f)
        self.assertEqual(f["sig_at"], 320)
        resolve(game, f)
        self.assertEqual(f["shield_ends"], 176)
        game.state["tick"] = 175
        game._expire_shield(f)
        self.assertEqual(f["shield"], 30)
        game.state["tick"] = 176
        game._expire_shield(f)
        self.assertEqual(f["shield"], 0)

    def test_hydra_halo(self) -> None:
        game, f = arena("leg-hydra-halo")
        start(game, f)
        resolve(game, f)
        obj = next(iter(game.state["objects"].values()))
        self.assertEqual((obj["range"], obj["angle"]), (4050, -36))

    def test_loop_flywheel(self) -> None:
        game, f = arena("leg-loop-flywheel")
        start(game, f)
        self.assertEqual(f["sig_at"], 280)
        resolve(game, f)
        self.assertEqual([(h["base"], h["knockback"]) for h in game.state["damages"]], [(10, 2000)])

    def test_priority_fee(self) -> None:
        game, f = arena("leg-priority-fee")
        start(game, f)
        self.assertEqual(f["sig_at"], 316)
        resolve(game, f)
        self.assertEqual(f["shield"], 27)

    def test_builder_census(self) -> None:
        game, f = arena("leg-builder-census", tuple((1000 + i * 100, 0) for i in range(5)))
        start(game, f)
        self.assertEqual(f["sig_at"], 298)
        resolve(game, f)
        self.assertEqual([(h["target"], h["base"]) for h in game.state["damages"]],
                         [("b", 24), ("c", 24), ("d", 24), ("e", 24)])

    def test_harvest_quake(self) -> None:
        game, f = arena("leg-harvest-quake", ((3200, 0),))
        start(game, f)
        self.assertEqual(f["sig_at"], 320)
        resolve(game, f)
        self.assertEqual([h["base"] for h in game.state["damages"]], [11])

    def test_poker_face(self) -> None:
        game, f = arena("leg-poker-face", ((750, 0),))
        start(game, f)
        resolve(game, f)
        self.assertEqual(f["shield"], 27)
        game.state["tick"] = f["shield_ends"]
        game._expire_shield(f)
        self.assertEqual(game.state["fighters"]["b"]["knock_x"], 300)

    def test_router_drone(self) -> None:
        game, f = arena("leg-router-drone", ((5000, 0),))
        game.state["fighters"]["b"]["hp"] = 33
        self.assertIsNotNone(start(game, f, force=False))
        resolve(game, f)
        self.assertEqual([h["base"] for h in game.state["damages"]], [18])
        far, other = arena("leg-router-drone", ((5500, 0),))
        far.state["fighters"]["b"]["hp"] = 29
        self.assertIsNone(start(far, other, force=False))


class Bindings(unittest.TestCase):
    def test_grabbed_copy_keeps_its_quirk_for_a_player(self) -> None:
        game, f = arena("st-roll")
        drop = game.drop_item("leg-stack-sats", 0, 0, "satrenchi", True)
        for _ in range(6):
            game._grabs()
        self.assertNotIn(drop, game.state["drops"])
        self.assertFalse(f["house"])
        self.assertEqual(f["equipped"]["trinket"], "leg-stack-sats")
        self.assertEqual(f["bag"]["leg-stack-sats"]["serial"], 1)
        f.update(cooldown_pct=100, sig_range_pct=100)
        start(game, f)
        resolve(game, f)
        self.assertEqual(f["shield"], 33)
        self.assertEqual(f["sig_at"], 364)

    def test_cast_then_grab_binds_common_damage_tier_stats_and_sweep(self) -> None:
        game, f = arena("c-beam-sweep", ((2000, 0),))
        start(game, f)
        game.drop_item("leg-hydra-halo", 0, 0, "illia-trenchukhin", True)
        for _ in range(6):
            game._grabs()
        self.assertEqual(f["equipped"]["trinket"], "leg-hydra-halo")
        restored = sim.Sim.restore(game.export(), game.rules)
        resolve(restored, restored.state["fighters"]["a"])
        obj = next(iter(restored.state["objects"].values()))
        self.assertEqual((obj["item_id"], obj["range"], obj["angle"], obj["damage_pct"], obj["tier_pct"]),
                         ("c-beam-sweep", 4500, -30, 100, 80))

    def test_shield_pop_is_bound_through_item_change_and_restore(self) -> None:
        game, f = arena("leg-poker-face", ((750, 0),))
        start(game, f)
        resolve(game, f)
        f["equipped"]["trinket"] = "leg-lifeboat"
        restored = sim.Sim.restore(game.export(), game.rules)
        shield = restored.state["fighters"]["a"]
        restored.state["tick"] = shield["shield_ends"]
        restored._expire_shield(shield)
        self.assertEqual(restored.state["fighters"]["b"]["knock_x"], 300)
        self.assertNotIn("shield_parameters", shield)

    def test_shared_signatures_retain_their_base_effects(self) -> None:
        for row, shield, cooldown in (("c-magnet", 30, 240), ("c-bubble", 30, 200)):
            with self.subTest(row=row):
                game, f = arena(row)
                start(game, f)
                self.assertEqual(f["sig_at"], 100 + cooldown)
                resolve(game, f)
                self.assertEqual(f["shield"], shield)
                self.assertEqual(f["shield_ends"], 170)
        for row, damage, count in (("c-shockwave", 12, 1), ("c-chain-storm", 30, 1),
                                   ("c-blink-strike", 18, 1)):
            with self.subTest(row=row):
                game, f = arena(row)
                start(game, f)
                resolve(game, f)
                self.assertEqual([h["base"] for h in game.state["damages"]], [damage] * count)
        game, f = arena("c-beam-sweep")
        start(game, f)
        resolve(game, f)
        obj = next(iter(game.state["objects"].values()))
        self.assertEqual((obj["range"], obj["angle"], obj["damage"]), (4500, -30, 20))

    def test_quirk_text_and_overrides_cover_only_the_fourteen_legendaries(self) -> None:
        rules = table()
        expected = {v["legendary"] for v in rules["house"].values()}
        self.assertEqual(set(rules["item_quirks"]), expected)
        for row, quirk in rules["item_quirks"].items():
            with self.subTest(row=row):
                self.assertTrue(quirk["text"].strip())
                self.assertEqual(sum(rules["items"][row]["stats"].values()), 24)
                self.assertLessEqual(max(rules["items"][row]["stats"].values()), 9)
        self.assertEqual(sim.rules_dict(sim.DEFAULT_RULES), rules)


class QuirkReplay(unittest.TestCase):
    def test_seeded_segment_replays_twice_with_bound_casts(self) -> None:
        game = sim.Sim(20261110, table())
        houses = sorted(game.rules["house"])
        rows = [sim.Input(0, "join", name, 0, {"house": True, "angle": i * 360 // len(houses)})
                for i, name in enumerate(houses)]
        rows += [sim.Input(20, "intent", name, 1, {"sig": "use"}) for name in houses]
        for row in rows:
            game.enqueue(row)
        # Seal a real boundary with active casts; the loader must preserve their
        # parameters as well as generator and input state through restore.
        game.run(25)
        self.assertTrue(any(f["cast"] is not None for f in game.state["fighters"].values()))
        initial = game.export()
        game.run(1200)
        record = {"initial_state": initial, "rules_hash": game.rules_hash,
                  "commands": [{"kind": "advance", "value": 1200}], "predictions": [],
                  "sealed": {"tick_count": "1200", "final_state_hash": game.state_hash()}}
        record["sealed"]["sealed_result_hash"] = replay.engine_commitment(record)
        for _ in range(2):
            self.assertEqual(replay.replay_segment(record).state_hash(), game.state_hash())
        print("quirks rules:", game.rules_hash, "segment twice:", game.state_hash(), flush=True)


class QuirkData(unittest.TestCase):
    def test_malformed_quirk_parameters_refuse_before_simulation(self) -> None:
        invalid = ([], {"text": "", "overrides": {}}, {"text": "x", "overrides": []},
                   {"text": "x", "overrides": {"unknown_parameter": 1}},
                   {"text": "x", "overrides": {"cooldown": 0}})
        for quirk in invalid:
            with self.subTest(quirk=quirk):
                rules = table()
                rules["item_quirks"]["leg-stack-sats"] = quirk
                with self.assertRaises(ValueError):
                    sim.validate_rules(rules)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--rules", type=Path)
    options, rest = parser.parse_known_args()
    if options.rules is not None:
        RULES_PATH = options.rules
    unittest.main(argv=[sys.argv[0], *rest])
