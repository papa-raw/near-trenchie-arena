"""Battle mode (rules table integer-13, BEHAVIOUR.md): one case per drive, gate condition, reflex condition and
reflex action, the ACK receipt, persistence, replay under old tables, Pat's example measured in a crowd, and the
per-tick cost at 16 fighters x 8 reflexes."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import battle_measure
import behaviour
import replay
import sim

R = sim.DEFAULT_RULES
TILE = R["tile"]
RULES_DIR = Path(__file__).parent / "rules"


def plan(raw, name="a"):
    out, clipped, refused, _ = behaviour.normalise(raw, R, name)
    assert not refused, refused
    return out


def arena(*bodies, seed=5):
    """Fighters a, b, c ... at the given (x, y) milli-tiles, alive, past spawn shields, nobody targeting."""
    game = sim.Sim(seed)
    for index in range(len(bodies)):
        game.enqueue(sim.Input(0, "join", chr(ord("a") + index), 0, {"angle": 0}))
    game._inputs()
    game.state["tick"] = 200
    for index, (x, y) in enumerate(bodies):
        f = game.state["fighters"][chr(ord("a") + index)]
        f.update(x=x, y=y, shield_until=0, attack_at=0, sig_at=99999, direction=0)
    return game


def give(game, name, raw):
    game._set_behaviour(game.state["fighters"][name], plan(raw, name))


def drop(game, x, y, row="c-beam"):
    return game.drop_item(row, x, y, None, True, origin="arena")


def moved(game, name="a"):
    game._policy()
    f = game.state["fighters"][name]
    return f["move_x"], f["move_y"]


class Drives(unittest.TestCase):
    def test_loot_walks_to_a_drop_and_stands_on_it(self):
        game = arena((0, 0), (0, 11000))
        drop(game, 3000, 0)
        give(game, "a", {"v": 1, "drives": {"loot": 10}})
        self.assertGreater(moved(game)[0], 0)
        game.state["fighters"]["a"]["x"] = 2900
        self.assertEqual(moved(game), (0, 0), "loot is the strongest drive: it stands on the drop")
        give(game, "a", {"v": 1, "drives": {"loot": 0}})
        game.state["fighters"]["a"]["x"] = 0
        self.assertEqual(moved(game), (0, 0))

    def test_keep_away_pushes_from_enemies_inside_the_radius_but_not_the_target(self):
        game = arena((0, 0), (2000, 0), (0, 11000))
        give(game, "a", {"v": 1, "drives": {"keep_away": 10, "keep_away_radius": 5}, "gate": {"rival": True}})
        self.assertLess(moved(game)[0], 0, "b is 2 tiles away: walk away from it")
        give(game, "a", {"v": 1, "drives": {"keep_away": 10, "keep_away_radius": 1}, "gate": {"rival": True}})
        self.assertEqual(moved(game), (0, 0), "outside a 1-tile radius b does not push")
        give(game, "a", {"v": 1, "drives": {"keep_away": 10, "keep_away_radius": 5}, "target": "b"})
        moved(game)
        self.assertEqual(game.state["fighters"]["a"]["target"], "b")
        self.assertEqual(moved(game), (0, 0), "the enemy being attacked does not push")

    def test_chase_walks_to_the_target_until_in_reach(self):
        game = arena((0, 0), (6000, 0))
        give(game, "a", {"v": 1, "drives": {"chase": 10}})
        self.assertGreater(moved(game)[0], 0)
        game.state["fighters"]["b"]["x"] = 1000
        self.assertEqual(moved(game), (0, 0), "in swing reach: stop")

    def test_protect_walks_to_the_ally_and_favours_whoever_hit_it(self):
        game = arena((0, 0), (0, 6000), (-2500, 0), (2500, 0))
        give(game, "a", {"v": 1, "drives": {"protect": 10, "protect_ally": "b"}})
        self.assertGreater(moved(game)[1], 0, "ally b is 6 tiles away: go to it")
        game.state["fighters"]["b"]["hits"]["d"] = game.state["tick"]
        game.state["fighters"]["a"]["target"] = None
        moved(game)
        self.assertEqual(game.state["fighters"]["a"]["target"], "d", "d hit the ally")

    def test_hold_returns_to_center_here_and_a_point(self):
        game = arena((5000, 0), (0, 11000))
        give(game, "a", {"v": 1, "drives": {"hold": 10, "hold_radius": 2}})
        self.assertLess(moved(game)[0], 0)
        give(game, "a", {"v": 1, "drives": {"hold": 10, "hold_at": "here", "hold_radius": 2}})
        self.assertEqual(game.state["fighters"]["a"]["battle_anchor"], [5000, 0])
        self.assertEqual(moved(game), (0, 0), "already here")
        game.state["fighters"]["a"]["x"] = 9000
        self.assertLess(moved(game)[0], 0, "the anchor stays where it was set")
        give(game, "a", {"v": 1, "drives": {"hold": 10, "hold_at": {"x_milli": 9000, "y_milli": 4000}}})
        self.assertGreater(moved(game)[1], 0)

    def test_no_drive_stands_its_ground(self):
        game = arena((0, 0), (6000, 0))
        give(game, "a", {"v": 1})
        self.assertEqual(moved(game), (0, 0))


class Gate(unittest.TestCase):
    def target_with(self, gate, setup=None, bodies=((0, 0), (2000, 0))):
        game = arena(*bodies)
        if setup:
            setup(game)
        give(game, "a", {"v": 1, "gate": gate})
        moved(game)
        return game.state["fighters"]["a"]["target"]

    def test_target_hp_below_pct(self):
        self.assertIsNone(self.target_with({"target_hp_below_pct": 40}))
        self.assertEqual(self.target_with({"target_hp_below_pct": 40},
                                          lambda g: g.state["fighters"]["b"].update(hp=30)), "b")

    def test_target_busy_fighting_someone_else_or_facing_away(self):
        def facing_me(game):
            game.state["fighters"]["b"].update(direction=180, target="a")
            game.state["fighters"]["c"].update(direction=180, target="a")
        self.assertIsNone(self.target_with({"target_busy": True}, facing_me, ((0, 0), (2000, 0), (6000, 0))))
        def fighting_c(game):
            game.state["fighters"]["b"].update(direction=180, target="c")
            game.state["fighters"]["c"].update(direction=180, target="a")
        self.assertEqual(self.target_with({"target_busy": True}, fighting_c, ((0, 0), (2000, 0), (6000, 0))), "b")
        def facing_away(game):
            game.state["fighters"]["b"].update(direction=0, target=None)
        self.assertEqual(self.target_with({"target_busy": True}, facing_away), "b")

    def test_distance_under(self):
        self.assertIsNone(self.target_with({"distance_under": 2}))
        self.assertEqual(self.target_with({"distance_under": 3}), "b")

    def test_rival(self):
        self.assertIsNone(self.target_with({"rival": True}))
        self.assertEqual(self.target_with({"rival": True},
                                          lambda g: g.state["fighters"]["a"].update(rivals=["b"])), "b")

    def test_wears_legendary(self):
        self.assertIsNone(self.target_with({"wears_legendary": True}))
        row = next(r for r in sorted(R["items"]) if R["items"][r]["tier"] == "legendary")
        self.assertEqual(self.target_with({"wears_legendary": True},
                                          lambda g: g.state["fighters"]["b"]["equipped"].update(trinket=row)), "b")

    def test_match_any_and_all(self):
        self.assertIsNone(self.target_with({"distance_under": 3, "target_hp_below_pct": 40}))
        self.assertEqual(self.target_with({"match": "any", "distance_under": 3, "target_hp_below_pct": 40}), "b")

    def test_gate_holds_weapons_and_offensive_signatures_but_not_shields(self):
        game = arena((0, 0), (1000, 0))
        give(game, "a", {"v": 1, "gate": {"target_hp_below_pct": 10}})
        moved(game)
        a = game.state["fighters"]["a"]
        self.assertIsNone(a["target"])
        game._attacks()
        self.assertEqual([d for d in game.state["damages"] if d["source"] == "a"], [],
                         "no weapon at an enemy the gate keeps out")
        for kind in ("beam_sweep", "chain_storm", "blink_strike"):
            self.assertFalse(game._should_signature(a, kind, None))
        a["hp"] = 10
        game.state["fighters"]["b"]["target"] = "a"
        trinket = lambda kind: next(r for r in sorted(R["items"]) if R["items"][r]["signature"] == kind)
        a["equipped"]["trinket"] = trinket("bubble")
        self.assertTrue(game._should_signature(a, "bubble", None), "a shield is never gated")
        a["equipped"]["trinket"] = trinket("shockwave")
        self.assertTrue(game._should_signature(a, "shockwave", None), "self-defence shockwave is not gated")
        a["hp"] = a["max_hp"]
        self.assertFalse(game._should_signature(a, "shockwave", None), "healthy, no gated target: no shockwave")


    def test_a_swing_spares_the_enemies_the_gate_keeps_out(self):
        game = arena((0, 0), (1000, 0), (1000, 300))
        game.state["fighters"]["b"]["hp"] = 20
        give(game, "a", {"v": 1, "gate": {"target_hp_below_pct": 40}})
        moved(game)
        self.assertEqual(game.state["fighters"]["a"]["target"], "b")
        game._attacks()
        self.assertEqual(sorted(d["target"] for d in game.state["damages"] if d["source"] == "a"), ["b"],
                         "c stands in the swing cone at full hp and is not hit")
        give(game, "a", {"v": 1})
        game.state["damages"], game.state["fighters"]["a"]["attack_at"] = [], 0
        moved(game)
        game._attacks()
        self.assertEqual(sorted(d["target"] for d in game.state["damages"] if d["source"] == "a"), ["b", "c"])


class Target(unittest.TestCase):
    def test_modes(self):
        game = arena((0, 0), (3000, 0), (0, 5000), (-7000, 0))
        game.state["fighters"]["c"]["hp"] = 20
        game.state["fighters"]["a"]["last_hit"] = "d"
        for mode, expected in (("nearest", "b"), ("weakest", "c"), ("attacker", "d"), ("d", "d")):
            with self.subTest(mode=mode):
                give(game, "a", {"v": 1, "target": mode})
                moved(game)
                self.assertEqual(game.state["fighters"]["a"]["target"], expected)


class Reflexes(unittest.TestCase):
    def reflex(self, cond, setup, then=None):
        game = arena((0, 0), (5000, 0), (0, -9000))
        give(game, "a", {"v": 1, "reflexes": [{"if": cond, "then": then or {"drives": {"chase": 10}}}]})
        moved(game)
        before = game.state["fighters"]["a"]["battle_reflexes"][0]["on"]
        setup(game)
        game.state["tick"] += R["behaviour"]["reflex_hold_ticks"]
        moved(game)
        return before, game.state["fighters"]["a"]["battle_reflexes"][0]["on"], game

    def test_each_condition_turns_on(self):
        F = lambda g, n: g.state["fighters"][n]
        legendary = next(r for r in sorted(R["items"]) if R["items"][r]["tier"] == "legendary")
        cases = {
            "self_hp_below_pct": (25, lambda g: F(g, "a").update(hp=20)),
            "self_hp_above_pct": (95, lambda g: F(g, "a").update(hp=F(g, "a")["max_hp"])),
            "enemy_within": (3, lambda g: F(g, "b").update(x=2000)),
            "enemies_at_least": ({"count": 2, "radius": 6}, lambda g: F(g, "c").update(y=-4000)),
            "hit_recently": (True, lambda g: F(g, "a")["hits"].update(b=g.state["tick"] + 20)),
            "ally_hit_recently": (True, lambda g: F(g, "c")["hits"].update(b=g.state["tick"] + 20)),
            "loot_within": (4, lambda g: drop(g, 2000, 2000)),
            "legendary_on_floor": (True, lambda g: drop(g, 6000, 6000, legendary)),
            "target_hp_below_pct": (30, lambda g: F(g, "b").update(hp=10)),
            "no_target": (True, lambda g: None),
        }
        for key, (value, setup) in cases.items():
            with self.subTest(condition=key):
                game = arena((0, 0), (5000, 0), (0, -9000))
                raw = {"v": 1, "drives": {"protect": 1, "protect_ally": "c"}, "target": "nearest",
                       "reflexes": [{"if": {key: value}, "then": {"drives": {"chase": 10}}}]}
                if key == "self_hp_above_pct":
                    game.state["fighters"]["a"]["hp"] = 50
                if key == "no_target":
                    raw["gate"] = {"distance_under": 1}
                give(game, "a", raw)
                moved(game)
                if key != "no_target":
                    self.assertFalse(game.state["fighters"]["a"]["battle_reflexes"][0]["on"], "off before")
                setup(game)
                game.state["tick"] += R["behaviour"]["reflex_hold_ticks"]
                moved(game)
                self.assertTrue(game.state["fighters"]["a"]["battle_reflexes"][0]["on"], "on after")

    def test_action_stance(self):
        _, on, game = self.reflex({"self_hp_below_pct": 25}, lambda g: g.state["fighters"]["a"].update(hp=20),
                                  {"stance": "flee"})
        self.assertTrue(on)
        drives, gate, mode, _ = game._effective(game.state["fighters"]["a"], [], [], {})
        self.assertEqual((drives["keep_away"], drives["keep_away_radius"], gate["distance_under"], mode), (10, 8, 2, "nearest"))

    def test_action_drives_gate_and_target(self):
        game = arena((0, 0), (5000, 0), (0, 3000))
        game.state["fighters"]["b"]["hp"] = 10
        give(game, "a", {"v": 1, "gate": {"distance_under": 1}, "target": "nearest",
                         "reflexes": [{"if": {"hit_recently": True},
                                       "then": {"drives": {"chase": 9}, "gate": {}, "target": "weakest"}}]})
        moved(game)
        self.assertIsNone(game.state["fighters"]["a"]["target"])
        game.state["fighters"]["a"]["hits"]["c"] = game.state["tick"]
        moved(game)
        a = game.state["fighters"]["a"]
        self.assertEqual(a["target"], "b", "gate opened and target weakest")
        self.assertEqual(game._effective(a, [], [], {})[0]["chase"], 9)

    def test_action_say_fires_once_on_turn_on_and_at_most_every_10_s(self):
        game = arena((0, 0), (5000, 0))
        give(game, "a", {"v": 1, "reflexes": [{"if": {"enemy_within": 3}, "then": {"say": "Back off."}}]})
        says = []
        for step, x in enumerate((2000, 2000, 6000, 2000, 6000, 2000)):
            game.state["fighters"]["b"]["x"] = x
            game.state["events"] = []
            game.state["tick"] += R["behaviour"]["reflex_hold_ticks"]
            moved(game)
            says += [e for e in game.state["events"] if e["kind"] == "say"]
        self.assertEqual([e["text"] for e in says], ["Back off."], "three turn-ons inside 10 s: one line")
        game.state["tick"] += R["behaviour"]["say_ticks"]
        game.state["fighters"]["b"]["x"] = 6000
        moved(game)
        game.state["tick"] += R["behaviour"]["reflex_hold_ticks"]
        game.state["fighters"]["b"]["x"] = 2000
        game.state["events"] = []
        moved(game)
        self.assertEqual([e["kind"] for e in game.state["events"] if e["kind"] in ("say", "reflex")], ["reflex", "say"])

    def test_reflex_one_wins_and_a_reflex_holds_for_one_second(self):
        game = arena((0, 0), (2000, 0))
        give(game, "a", {"v": 1, "reflexes": [{"if": {"enemy_within": 3}, "then": {"drives": {"chase": 1}}},
                                              {"if": {"enemy_within": 4}, "then": {"drives": {"chase": 7}}}]})
        moved(game)
        a = game.state["fighters"]["a"]
        self.assertEqual(game._effective(a, [], [], {})[0]["chase"], 1)
        game.state["fighters"]["b"]["x"] = 9000
        game.state["tick"] += 1
        moved(game)
        self.assertTrue(a["battle_reflexes"][0]["on"], "inside its 1 s hold it stays on")
        game.state["tick"] += R["behaviour"]["reflex_hold_ticks"]
        moved(game)
        self.assertFalse(a["battle_reflexes"][0]["on"])


class Engine(unittest.TestCase):
    def test_logged_input_persists_across_respawn_and_clear_returns_to_the_style(self):
        game = sim.Sim(3)
        for name, angle in (("a", 0), ("b", 180)):
            game.enqueue(sim.Input(0, "join", name, 0, {"angle": angle}))
        game.run(1)
        row = game.receive("behaviour", "a", 1, plan({"v": 1, "stance": "loot"}))
        self.assertEqual(row.tick, 3)
        self.assertIn({"kind": "behaviour", "fighter": "a"}, events(game, 3))
        a = game.state["fighters"]["a"]
        self.assertEqual(a["behaviour"]["stance"], "loot")
        a["hp"] = 0
        game._ko(a)
        game.state["tick"] = a["respawn_at"]
        game._bench()
        self.assertEqual(a["state"], "alive")
        self.assertEqual(a["behaviour"]["stance"], "loot", "persists across respawns")
        game.receive("behaviour", "a", 2, {"v": 1, "clear": True})
        game.run(3)
        self.assertIsNone(a["behaviour"])

    def test_one_order_clock_for_behaviours_and_intents(self):
        game = sim.Sim(3)
        game.enqueue(sim.Input(0, "join", "a", 0, {"angle": 0}))
        game.run(1)
        game.receive("intent", "a", 1, {"focus": None})
        game.run(1)
        game.receive("behaviour", "a", 2, plan({"v": 1, "stance": "berserk"}))
        self.assertIn({"kind": "intent_refused", "fighter": "a"}, events(game, 3))
        self.assertIsNone(game.state["fighters"]["a"]["behaviour"])
        game.run(R["intent_interval"])
        game.receive("behaviour", "a", 3, plan({"v": 1, "stance": "berserk"}))
        game.run(3)
        self.assertEqual(game.state["fighters"]["a"]["behaviour"]["stance"], "berserk")

    def test_engine_accepts_only_the_normalised_form(self):
        game = sim.Sim(3)
        game.enqueue(sim.Input(0, "join", "a", 0, {"angle": 0}))
        for raw in ({"v": 1, "stance": "loot"}, {"v": 1, "drives": {"chase": 40}}, {"v": 2}):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                game.enqueue(sim.Input(1, "behaviour", "a", 1, raw))

    def test_old_tables_refuse_the_kind_and_replay_unchanged(self):
        for name, expected in (("integer-11.json", "73e9ca29"), ("integer-12.json", "e1a357d2")):
            with self.subTest(table=name):
                rules = json.loads((RULES_DIR / name).read_bytes())
                self.assertTrue(sim.digest(rules).startswith(expected))
                self.assertNotIn("behaviour", rules)
                game = sim.Sim(3, rules)
                with self.assertRaises(ValueError):
                    game.enqueue(sim.Input(0, "behaviour", "a", 0, plan({"v": 1})))
                self.assertEqual(sim.digest(replay.load_rules(sim.digest(rules))), sim.digest(rules))
        thirteen = json.loads((RULES_DIR / "integer-13.json").read_bytes())
        self.assertEqual(sim.digest(thirteen), "d09b0050851898d9944eb1638fec7fe2ca94f544a5df231bb2df46ff33d72680")
        twelve = json.loads((RULES_DIR / "integer-12.json").read_bytes())
        self.assertEqual({k for k in set(thirteen) | set(twelve) if thirteen.get(k) != twelve.get(k)},
                         {"version", "intent_interval", "input_kinds", "behaviour"})
        fourteen = json.loads((RULES_DIR / "integer-14.json").read_bytes())
        self.assertEqual(sim.digest(fourteen), "3975d414b4c313622c351f9d132951a8d4d8a1f446cd63cfa9db1e0838af6a4b")
        self.assertEqual({k for k in set(fourteen) | set(thirteen) if fourteen.get(k) != thirteen.get(k)}, {"version", "behaviour"})
        self.assertEqual({k: v for k, v in fourteen["behaviour"].items() if thirteen["behaviour"].get(k) != v},
                         {"chase_seek": True})
        fifteen = json.loads((RULES_DIR / "integer-15.json").read_bytes())
        self.assertEqual(sim.digest(fifteen), "0bcbd83d92dab9bc89b2c7a461ca21e44f1b9c8062595315cc156dadf3174fbe")
        self.assertEqual({k: fifteen.get(k) for k in set(fifteen) | set(fourteen) if fifteen.get(k) != fourteen.get(k)},
                         {"version": "integer-15", "steer_band": 1000})
        # integer-16 adds predictions; integer-17 changes floor expiry. Their release cases pin both archived tables.

    def test_a_battle_segment_replays_to_the_same_hash_and_resumes(self):
        def segment():
            game = sim.Sim(20261111)
            houses = sorted(R["house"])[:6]
            for i, name in enumerate(houses):
                game.enqueue(sim.Input(0, "join", name, 0, {"house": True, "angle": i * 51}))
            for i, (name, raw) in enumerate(zip(houses, ({"v": 1, "stance": "loot"}, battle_measure.EXAMPLE,
                                                         {"v": 1, "stance": "hunt-weakest", "reflexes": [
                                                             {"if": {"self_hp_below_pct": 30}, "then": {"stance": "flee", "say": "Later."}}]}))):
                game.enqueue(sim.Input(1, "behaviour", name, 1, plan(raw, name)))
            game.run(600)
            resumed = sim.Sim.restore(game.export(), game.rules)
            game.run(600)
            resumed.run(600)
            self.assertEqual(game.state_hash(), resumed.state_hash())
            return game.state_hash()
        self.assertEqual(segment(), segment())


class Receipt(unittest.TestCase):
    def test_applied_clipped_refused_rate_and_notes(self):
        a = behaviour.ack(battle_measure.EXAMPLE, R, "a", 1, 18400, present=["a", "b"])
        self.assertEqual((a["status"], a["apply_tick"], a["applies_in_ms"]), ("applied", 18402, 100))
        self.assertEqual(a["summary"], "New behaviour recorded: loot 10 · keep_away 8 (radius 5) · chase 3 · "
                         "attack gate: hp below 40% and busy · target auto · no reflexes · "
                         "applies at tick 18,402 (in 0.1 s) · persists across respawns")
        self.assertEqual(a["rules_hash"], sim.digest(R))
        c = behaviour.ack({"v": 1, "drives": {"chase": 10, "keep_away": 4, "keep_away_radius": 40},
                           "reflexes": [{"if": {"self_hp_below_pct": 25}, "then": {"drives": {"keep_away": 10}}}] * 9},
                          R, "a", 2, 100)
        self.assertEqual(c["status"], "clipped")
        self.assertEqual([x["fix"] for x in c["clipped"]], ["keep_away_radius 40 > max 12 tiles: set to 12",
                                                            "9 reflexes > max 8: kept the first 8"])
        self.assertEqual(len(c["behaviour"]["reflexes"]), 8)
        self.assertIn("keep_away 4 (radius 12, clipped from 40)", c["summary"])
        self.assertIn("reflex 1: if hp < 25% then keep_away 10", c["summary"])
        r = behaviour.ack({"v": 1, "reflexes": [{"if": {"hp_low": 1}, "then": {"say": "x"}}]}, R, "a", 3, 100)
        self.assertEqual((r["status"], r["behaviour"], r["apply_tick"]), ("refused", None, None))
        self.assertTrue(r["summary"].startswith("Refused: reflexes[1].if: unknown condition 'hp_low'; use one of"))
        self.assertTrue(r["summary"].endswith("nothing changed; your last behaviour stays"))
        late = behaviour.ack({"v": 1}, R, "a", 4, 100, last_order_tick=95)
        self.assertEqual(late["refused"][0]["code"], "order_rate")
        self.assertIn("send it again at tick 103", late["refused"][0]["fix"])
        n = behaviour.ack({"v": 1, "drives": {"protect": 5, "protect_ally": "bee"}}, R, "a", 5, 100, present=["a"])
        self.assertEqual(n["notes"], ["protect_ally bee is not in the ring now; protect waits for it"])

    def test_every_refusal_names_its_fix(self):
        bad = [
            [], {"v": 2}, {"v": 1, "colour": 1}, {"v": 1, "stance": "dance"}, {"v": 1, "drives": {"loot": "lots"}},
            {"v": 1, "drives": {"protect": 5}}, {"v": 1, "stance": "follow-ally"}, {"v": 1, "target": "a"},
            {"v": 1, "drives": {"protect": 2, "protect_ally": "a"}}, {"v": 1, "gate": {"match": "most"}},
            {"v": 1, "gate": {"target_busy": "yes"}}, {"v": 1, "clear": True, "stance": "loot"},
            {"v": 1, "reflexes": [{"if": {}, "then": {"say": "x"}}]},
            {"v": 1, "reflexes": [{"if": {"enemy_within": 3, "hit_recently": True}, "then": {"say": "x"}}]},
            {"v": 1, "reflexes": [{"if": {"enemy_within": 3}, "then": {}}]},
            {"v": 1, "reflexes": [{"if": {"enemy_within": 3}, "then": {"jump": 1}}]},
            {"v": 1, "reflexes": [{"if": {"hit_recently": False}, "then": {"say": "x"}}]},
            {"v": 1, "reflexes": [{"if": {"enemy_within": 3}, "then": {"say": "two\nlines"}}]},
            {"v": 1, "reflexes": [{"if": {"enemy_within": 3}, "then": {"drives": {"protect": 3}}}]},
            {"v": 1, "drives": {"hold_at": "there"}}, {"v": 1, "target": "x" * 65},
            {"v": 1, "reflexes": [{"if": {"enemy_within": 3}, "then": {"say": "y" * 70}}] * 30},
        ]
        for raw in bad:
            with self.subTest(raw=str(raw)[:60]):
                out, _, refused, _ = behaviour.normalise(raw, R, "a")
                self.assertIsNone(out)
                self.assertTrue(refused and all(r["fix"] for r in refused))

    def test_clips_and_stances(self):
        out, clipped, refused, _ = behaviour.normalise(
            {"v": 1, "stance": "flee", "drives": {"loot": -3, "hold_radius": 9, "hold": 2,
                                                  "hold_at": {"x_milli": 20000, "y_milli": 0}},
             "gate": {"distance_under": 0, "target_hp_below_pct": 120},
             "reflexes": [{"if": {"enemy_within": 3}, "then": {"say": "z" * 90}}]}, R, "a")
        self.assertEqual(refused, [])
        self.assertEqual([c["path"] for c in clipped],
                         ["drives.loot", "drives.hold_radius", "drives.hold_at", "gate.target_hp_below_pct",
                          "gate.distance_under", "reflexes[1].then.say"])
        self.assertEqual(out["drives"]["hold_at"], {"x_milli": 12000, "y_milli": 0})
        self.assertEqual((out["drives"]["keep_away"], out["drives"]["loot"], out["target"]), (10, 0, "nearest"))
        self.assertEqual(len(out["reflexes"][0]["then"]["say"]), 80)
        for name in R["behaviour"]["stances"]:
            raw = {"v": 1, "stance": name, "drives": {"protect_ally": "b"}}
            with self.subTest(stance=name):
                stored = plan(raw)
                behaviour.check_stored(stored, R, "a")
                self.assertEqual(stored["stance"], name)


class SchemaOnePointOne(unittest.TestCase):
    """v1.1, additive (v1 payloads stay valid): gate never, conditions always / hit_by / enemy_within with who,
    and a repeating say."""

    CRITBEE = {"v": 1, "stance": "flee", "gate": {"never": True},
               "reflexes": [{"if": {"always": True}, "then": {"say": "AAAA RUN", "repeat": True}}]}

    def test_gate_never_attacks_no_one_even_in_self_defence_and_keeps_away_from_everyone(self):
        game = arena((0, 0), (900, 0))
        game.state["fighters"]["b"]["hp"] = 1
        give(game, "a", {"v": 1, "drives": {"keep_away": 10, "keep_away_radius": 5}, "gate": {"never": True}})
        a = game.state["fighters"]["a"]
        self.assertLess(moved(game)[0], 0, "no target, so the adjacent enemy pushes too")
        self.assertIsNone(a["target"])
        game._attacks()
        self.assertEqual([d for d in game.state["damages"] if d["source"] == "a"], [])
        a["hp"], a["equipped"]["trinket"] = 10, next(r for r in sorted(R["items"]) if R["items"][r]["signature"] == "shockwave")
        self.assertFalse(game._should_signature(a, "shockwave", None), "never: not even self-defence")
        game.queue_hit("a", "b", 12)
        self.assertEqual([d for d in game.state["damages"] if d["source"] == "a"], [], "a lingering hit lands on no one")
        out, _, _, notes = behaviour.normalise({"v": 1, "gate": {"never": True, "rival": True}}, R, "a")
        self.assertEqual(out["gate"], {"match": "all", "never": True})
        self.assertEqual(notes[0], "gate.never: the fighter attacks no one, so the other gate conditions are dropped")
        self.assertIn("attack gate: never attacks", behaviour.ack(self.CRITBEE, R, "a", 1, 100)["summary"])

    def test_conditions_always_hit_by_and_enemy_within_who(self):
        game = arena((0, 0), (2000, 0), (0, 2500), (9000, 0))
        a = game.state["fighters"]["a"]
        a["rivals"] = ["c"]
        tick = game.state["tick"]
        game.state["fighters"]["b"]["hits"]["d"] = tick
        give(game, "a", {"v": 1, "drives": {"protect": 1, "protect_ally": "b"}})
        holds = lambda cond: game._condition(a, plan({"v": 1, "drives": {"protect": 1, "protect_ally": "b"},
                                                      "reflexes": [{"if": cond, "then": {"say": "x"}}]})["reflexes"][0]["if"],
                                             sorted((sim.distance(a, game.state["fighters"][n]), n) for n in "bcd"), [], {})
        self.assertTrue(holds({"always": True}))
        self.assertTrue(holds({"enemy_within": {"radius": 3, "who": "rival"}}))
        self.assertFalse(holds({"enemy_within": {"radius": 2, "who": "rival"}}), "c is 2.5 tiles away")
        self.assertTrue(holds({"enemy_within": {"radius": 10, "who": "ally_attacker"}}), "d hit the ally")
        self.assertFalse(holds({"enemy_within": {"radius": 8, "who": "ally_attacker"}}))
        self.assertTrue(holds({"enemy_within": {"radius": 3, "who": "b"}}))
        self.assertFalse(holds({"hit_by": {"who": "any"}}))
        a["hits"]["c"] = tick
        self.assertTrue(holds({"hit_by": {"who": "rival"}}))
        self.assertTrue(holds({"hit_by": {"who": "c"}}))
        self.assertFalse(holds({"hit_by": {"who": "d"}}))
        stored = plan({"v": 1, "reflexes": [{"if": {"enemy_within": {"radius": 4, "who": "any"}}, "then": {"say": "x"}}]})
        self.assertEqual(stored["reflexes"][0]["if"], {"enemy_within": 4}, "who any is the v1 form")
        for raw in ({"enemy_within": {"radius": 4}}, {"hit_by": {"who": "ally_attacker"}}, {"hit_by": "rival"},
                    {"always": False}):
            with self.subTest(raw=raw):
                self.assertIsNone(behaviour.normalise({"v": 1, "reflexes": [{"if": raw, "then": {"say": "x"}}]}, R, "a")[0])
        self.assertIsNone(behaviour.normalise({"v": 1, "reflexes": [{"if": {"always": True}, "then": {"repeat": True}}]}, R, "a")[0])

    def test_critbee_runs_from_everyone_never_attacks_and_shouts_every_10_s_across_three_respawns(self):
        """Pat's case: 'run away from everyone, don't attack anyone, scream in caps every time you can'."""
        game = sim.Sim(11)
        houses = sorted(R["house"])[:5]
        for i, name in enumerate(houses):
            game.enqueue(sim.Input(0, "join", name, 0, {"house": True, "angle": i * 60}))
        game.enqueue(sim.Input(0, "join", "critbee", 0, {"angle": 300}))
        game.enqueue(sim.Input(1, "behaviour", "critbee", 1, plan(self.CRITBEE, "critbee")))
        bee = game.state["fighters"]
        says, damage, lives, alive_says = [], 0, set(), {}
        last = None
        while (last is None or game.state["tick"] < last + R["behaviour"]["say_ticks"] + 50) and game.state["tick"] < 20000:
            game.step()
            if last is None and len(lives) == 4:
                last = game.state["tick"]
            me = bee["critbee"]
            lives.add(me["life_id"])
            for e in game.state["events"]:
                if e["kind"] == "say" and e["fighter"] == "critbee":
                    says.append(game.state["tick"])
                    alive_says[me["life_id"]] = alive_says.get(me["life_id"], 0) + 1
                if e["kind"] == "hit" and e["source"] == "critbee":
                    damage += e["damage"]
        print("\ncritbee:", {"lives": len(lives), "says": len(says), "per_life": alive_says, "ticks": game.state["tick"]}, flush=True)
        self.assertGreaterEqual(len(lives), 4, "three respawns")
        self.assertEqual(damage, 0, "never attacks anyone")
        gaps = [b - a for a, b in zip(says, says[1:])]
        self.assertTrue(gaps and min(gaps) >= R["behaviour"]["say_ticks"], gaps)
        self.assertEqual(len(alive_says), len(lives), "it shouts in every life, so the behaviour persisted")
        self.assertEqual(bee["critbee"]["behaviour"]["gate"], {"match": "all", "never": True})


class Fuzz(unittest.TestCase):
    """Every field of two full behaviours, swapped for each wrong type: only ever a refusal (or a valid plan)."""

    FULL = [
        {"v": 1, "stance": "loot", "target": "weakest",
         "drives": {"loot": 5, "keep_away": 4, "keep_away_radius": 3, "chase": 2, "protect": 1, "protect_ally": "b",
                    "hold": 1, "hold_at": {"x_milli": 100, "y_milli": -200}, "hold_radius": 2},
         "gate": {"match": "any", "target_hp_below_pct": 40, "target_busy": True, "distance_under": 3, "rival": True,
                  "wears_legendary": True},
         "reflexes": [{"if": {"self_hp_below_pct": 20}, "then": {"stance": "flee", "say": "out", "repeat": True}},
                      {"if": {"self_hp_above_pct": 80}, "then": {"drives": {"chase": 9, "protect": 2}}},
                      {"if": {"enemy_within": 3}, "then": {"gate": {"never": True}}},
                      {"if": {"enemies_at_least": {"count": 3, "radius": 4}}, "then": {"target": "nearest"}},
                      {"if": {"hit_recently": True}, "then": {"target": "attacker", "gate": {}}},
                      {"if": {"ally_hit_recently": True}, "then": {"stance": "follow-ally"}},
                      {"if": {"loot_within": 2}, "then": {"drives": {"loot": 10, "hold_at": "here"}}},
                      {"if": {"legendary_on_floor": True}, "then": {"drives": {"hold_at": "center"}}}]},
        {"v": 1, "stance": "follow-ally", "drives": {"protect_ally": "b"}, "target": "c",
         "reflexes": [{"if": {"target_hp_below_pct": 30}, "then": {"say": "now"}},
                      {"if": {"no_target": True}, "then": {"stance": "hold"}},
                      {"if": {"always": True}, "then": {"drives": {"keep_away": 1, "keep_away_radius": 9}}},
                      {"if": {"hit_by": {"who": "rival"}}, "then": {"target": "c"}},
                      {"if": {"enemy_within": {"radius": 5, "who": "ally_attacker"}}, "then": {"gate": {"rival": True}}}]},
        {"v": 1, "clear": True},
    ]
    WRONG = ("10", True, None, 2.5, [], [1], {}, {"x": 1})

    def paths(self, value, path=()):
        yield path
        if isinstance(value, dict):
            for key in value:
                yield from self.paths(value[key], path + (key,))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                yield from self.paths(item, path + (index,))

    def swapped(self, base, path, wrong):
        root = json.loads(json.dumps(base))
        if not path:
            return wrong
        node = root
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = wrong
        return root

    def test_every_field_with_every_wrong_type_is_refused_never_raised(self):
        count = refused = 0
        game = sim.Sim(3)
        game.enqueue(sim.Input(0, "join", "a", 0, {"angle": 0}))
        for base in self.FULL:
            self.assertIsNotNone(behaviour.normalise(base, R, "a")[0], "the base behaviour is valid")
            for path in self.paths(base):
                for wrong in self.WRONG:
                    raw = self.swapped(base, path, wrong)
                    count += 1
                    with self.subTest(path=path, wrong=wrong):
                        out, _, refusals, _ = behaviour.normalise(raw, R, "a")
                        receipt = behaviour.ack(raw, R, "a", 1, 100, present=["a", "b"])
                        self.assertIsInstance(receipt["summary"], str)
                        if out is None:
                            refused += 1
                            self.assertTrue(refusals and all(r["fix"] for r in refusals), refusals)
                            self.assertEqual(receipt["status"], "refused")
                        try:
                            game.enqueue(sim.Input(1, "behaviour", "a", count, raw))
                        except ValueError:
                            pass
        print("\nfuzz:", count, "inputs,", refused, "refused", flush=True)
        self.assertGreater(refused, count // 2)

    def test_a_non_integer_protect_is_refused_with_its_fix(self):
        for raw in ({"v": 1, "drives": {"protect": "10"}}, {"v": 1, "drives": {"protect": True}},
                    {"v": 1, "stance": "follow-ally", "drives": {"protect": None}},
                    {"v": 1, "drives": {"protect_ally": "b"},
                     "reflexes": [{"if": {"always": True}, "then": {"drives": {"protect": "x"}}}]},
                    {"v": 1, "reflexes": [{"if": {"no_target": True}, "then": {"drives": {"protect": "x"}}}]}):
            with self.subTest(raw=raw):
                out, _, refused, _ = behaviour.normalise(raw, R, "a")
                self.assertIsNone(out)
                self.assertIn("protect must be a whole number from 0 to 10", [r["fix"] for r in refused])

    def test_ids_take_fighter_id_characters_only(self):
        for bad in ("b c", "b\u202e", "<b>", "b\"", "\u0431", "b\n"):
            for raw in ({"v": 1, "target": bad}, {"v": 1, "drives": {"protect": 1, "protect_ally": bad}},
                        {"v": 1, "reflexes": [{"if": {"hit_by": {"who": bad}}, "then": {"say": "x"}}]}):
                with self.subTest(bad=bad, raw=str(raw)[:40]):
                    out, _, refused, _ = behaviour.normalise(raw, R, "a")
                    self.assertIsNone(out)
                    self.assertTrue(any("letters, digits" in r["fix"] for r in refused), refused)
                    self.assertNotIn(bad, behaviour.ack(raw, R, "a", 1, 100)["summary"])
        for good in ("laser-sailor", "dev-critbee", "token.42", "a_b:1", "x@y"):
            self.assertIsNotNone(behaviour.normalise({"v": 1, "target": good}, R, "a")[0], good)


class GateAtAttackStart(unittest.TestCase):
    """Review finding (9619e78): the gate is checked again on the tick an attack starts, not only where it lands."""

    def test_an_enemy_that_turns_round_before_the_swing_is_not_swung_at(self):
        game = arena((0, 0), (1000, 0), (3000, 0))
        b = game.state["fighters"]["b"]
        b.update(hp=20, direction=0, target="a")                  # faces away from a: busy by facing
        give(game, "a", {"v": 1, "gate": {"target_hp_below_pct": 40, "target_busy": True}})
        moved(game)
        self.assertEqual(game.state["fighters"]["a"]["target"], "b", "b passed the gate at the policy phase")
        b["direction"] = 180                                       # b's own attack this tick turns it to face a
        game._attacks()
        self.assertEqual([d for d in game.state["damages"] if d["source"] == "a"], [])
        self.assertNotIn({"kind": "attack", "fighter": "a", "weapon": "swing"}, game.state["events"])
        b["direction"] = 0
        game.state["fighters"]["a"]["attack_at"] = 0
        game._attacks()
        self.assertEqual([d["target"] for d in game.state["damages"] if d["source"] == "a"], ["b"],
                         "facing away again: the swing starts")

    def test_pats_example_on_seeds_7_to_12_starts_every_attack_inside_the_gate(self):
        keys = ("attacks", "attacks_meeting_gate", "signature_starts", "signature_starts_meeting_gate",
                "signature_self_defence", "hits", "hits_meeting_gate")
        rows = [battle_measure.run(seed, 4000, 9, battle_measure.EXAMPLE) for seed in range(7, 13)]
        total = {k: sum(r[k] for r in rows) for k in keys}
        print("\nseeds 7-12:", total, flush=True)
        self.assertGreater(total["attacks"], 0)
        self.assertEqual(total["attacks_meeting_gate"], total["attacks"])
        # BEHAVIOUR.md "Attack gate": an offensive signature starts only at a target that passes, except a shockwave in
        # self-defence (own hp under its threshold, an enemy in trigger range), which a `never` gate also forbids. The
        # measure labels those starts self_defence; every other start must meet the gate, and every hit must.
        self.assertEqual(total["signature_starts_meeting_gate"] + total["signature_self_defence"], total["signature_starts"])
        self.assertEqual(total["hits_meeting_gate"], total["hits"])

    def test_a_segment_with_no_behaviour_replays_as_before_the_fix(self):
        """The fix runs only for fighters on a behaviour, so integer-13 segments without one keep their hash
        (computed with main 831b891's engine before the fix, under integer-13)."""
        game = sim.Sim(1, json.loads((RULES_DIR / "integer-13.json").read_bytes()))
        houses = sorted(R["house"])[:8]
        for i, name in enumerate(houses):
            game.enqueue(sim.Input(0, "join", name, 0, {"house": True, "angle": i * 45}))
        game.enqueue(sim.Input(0, "join", "p", 0, {"angle": 200}))
        for tick in range(40, 2400, 40):
            game.enqueue(sim.Input(tick, "intent", "p", tick, {"focus": houses[tick % 8]}))
        game.run(2400)
        self.assertEqual(game.state_hash(), "1d2fc46e31bf09b749a989681d3caaa18a4ab7ccb8380c8b2be9cf63c5584565")


class ChaseSeek(unittest.TestCase):
    """integer-14 (balance finding 4): chase walks to the nearest gated enemy anywhere when none is in view, so
    two berserkers alone fight. integer-13 keeps its own behaviour and replays as before."""

    def duel(self, rules, seed, raw, ticks):
        game = sim.Sim(seed, rules)
        for i, name in enumerate(("x", "y")):
            game.enqueue(sim.Input(0, "join", name, 0, {"angle": i * 180, "style": "brawler"}))
        for name in ("x", "y"):
            game.enqueue(sim.Input(1, "behaviour", name, 1, behaviour.normalise(raw, game.rules, name)[0]))
        for _ in range(ticks):
            game.step()
            if any(e["kind"] == "hit" for e in game.state["events"]):
                return game.state["tick"]
        return None

    def test_two_berserkers_alone_fight_within_10_s(self):
        for seed in (1, 2, 3):
            with self.subTest(seed=seed):
                first = self.duel(sim.DEFAULT_RULES, seed, {"v": 1, "stance": "berserk"}, 200)
                self.assertIsNotNone(first, "a hit inside 200 ticks (10 s)")

    def test_integer_13_berserkers_still_stand_still(self):
        thirteen = json.loads((RULES_DIR / "integer-13.json").read_bytes())
        self.assertIsNone(self.duel(thirteen, 1, {"v": 1, "stance": "berserk"}, 600))

    def test_seek_follows_the_gate(self):
        for raw in ({"v": 1, "drives": {"chase": 10}, "gate": {"never": True}},
                    {"v": 1, "drives": {"chase": 10}, "gate": {"target_hp_below_pct": 40}}):
            with self.subTest(raw=raw):
                self.assertIsNone(self.duel(sim.DEFAULT_RULES, 1, raw, 400), "no enemy passes, so no seek")
        game = arena((0, -11000), (0, 11000))
        give(game, "a", {"v": 1, "drives": {"chase": 10}})
        self.assertGreater(moved(game)[1], 0, "b is out of view (22 tiles) yet passes the gate: walk to it")
        self.assertIsNone(game.state["fighters"]["a"]["target"], "seeking is movement, not a target")


def jitter(rules, stances, ticks=2400, seed=20261112):
    """Visible back-and-forth per 1000 alive ticks, and the share of idle ticks, in a 5-fighter crowd.

    A visible reversal is a tick whose move points against the previous tick's (negative dot product) while
    both steps are at least half the fighter's speed: a body stepping back and forth on the spot."""
    game = sim.Sim(seed, rules)
    houses = sorted(rules["house"])[:len(stances)]
    for i, name in enumerate(houses):
        game.enqueue(sim.Input(0, "join", name, 0, {"house": True, "angle": i * 72}))
    for name, stance in zip(houses, stances):
        if stance is not None:
            out, _, refused, _ = behaviour.normalise({"v": 1, "stance": stance}, rules, name)
            assert not refused, refused
            game.enqueue(sim.Input(1, "behaviour", name, 1, out))
    previous, reversals, alive = {}, 0, 0
    for _ in range(ticks):
        game.step()
        for name, f in game.state["fighters"].items():
            if f["state"] != "alive":
                previous.pop(name, None)
                continue
            alive += 1
            move, half = (f["move_x"], f["move_y"]), f["speed"] // 2
            last = previous.get(name)
            big = lambda m: m[0] * m[0] + m[1] * m[1] >= half * half
            if last is not None and big(last) and big(move) and last[0] * move[0] + last[1] * move[1] < 0:
                reversals += 1
            previous[name] = move
    return reversals * 1000 // max(1, alive)


class Steering(unittest.TestCase):
    """Fighters seen "stuck in one place vibrating" in a click-through. Each drive switched on or off at its boundary
    (keep-away radius, weapon reach, hold radius) and the summed pull was always scaled to full speed, so a
    fighter on a boundary stepped a full stride across it and a full stride back. integer-15 (`steer_band`)
    makes every pull continuous at its boundary and scales the step by the net pull."""

    CROWDS = (("flee", "loot", "hold", "defend", "berserk"),
              ("hunt-weakest", "loot", "flee", "hold", "defend"),
              (None, None, None, None, None))           # no plan: the default policy (survivor/looter styles)

    def test_no_crowd_steps_back_and_forth_on_the_spot(self):
        for stances in self.CROWDS:
            with self.subTest(stances=stances):
                self.assertLessEqual(jitter(R, stances), 2, "visible reversals per 1000 alive ticks")

    def test_integer_14_still_steps_as_it_did(self):
        fourteen = sim.freeze(json.loads((RULES_DIR / "integer-14.json").read_bytes()))
        self.assertNotIn("steer_band", fourteen)
        self.assertGreater(jitter(fourteen, self.CROWDS[0]), 50, "the old table keeps its old movement, so its segments replay")


class PatsExample(unittest.TestCase):
    def test_loots_keeps_its_distance_and_only_hits_low_busy_targets(self):
        """Pat: "grab all the loot and run away from others, only attack when they're low on HP and not paying
        attention". Four seeded crowds of 10, 4000 ticks each, against the same fighter with no behaviour."""
        with_plan = [battle_measure.run(seed, 4000, 9, battle_measure.EXAMPLE) for seed in (1, 2, 3, 4)]
        without = [battle_measure.run(seed, 4000, 9, None) for seed in (1, 2, 3, 4)]
        total = lambda rows, key: sum(r[key] for r in rows)
        print("\nPat's example:", json.dumps({k: [total(with_plan, k), total(without, k)] for k in (
            "grabs", "mean_nearest_enemy_milli", "ticks_enemy_inside_radius_pct", "attacks", "attacks_meeting_gate",
            "hits", "hits_meeting_gate")}), flush=True)
        self.assertGreater(total(with_plan, "attacks"), 0, "it does attack")
        self.assertEqual(total(with_plan, "attacks_meeting_gate"), total(with_plan, "attacks"))
        self.assertEqual(total(with_plan, "hits_meeting_gate"), total(with_plan, "hits"))
        self.assertLess(total(without, "attacks_meeting_gate") * 2, total(without, "attacks"), "the baseline is not gated")
        self.assertGreater(total(with_plan, "grabs"), total(without, "grabs"))
        self.assertGreater(total(with_plan, "mean_nearest_enemy_milli"), total(without, "mean_nearest_enemy_milli"))
        self.assertLess(total(with_plan, "ticks_enemy_inside_radius_pct"), total(without, "ticks_enemy_inside_radius_pct"))


class Cost(unittest.TestCase):
    def test_sixteen_fighters_with_eight_reflexes_fit_the_tick(self):
        cost = battle_measure.tick_cost(16, 8, 200)
        print("\ntick cost ms:", cost, flush=True)
        self.assertLess(cost["behaviour"], 10, "a fifth of the 50 ms tick, with room for a slower host core")


def events(game, ticks):
    """Every engine event over the next `ticks` ticks."""
    out = []
    for _ in range(ticks):
        game.step()
        out += game.state["events"]
    return out


if __name__ == "__main__":
    unittest.main()
