"""Focused cases for house targeting and optional combat controls."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sim


class Bounty(unittest.TestCase):
    def game(self):
        game = sim.Sim(317, sim.DEFAULT_RULES)
        for name, payload in (("avichad", {"house": True, "angle": 0}),
                              ("holder", {"angle": 90}), ("other", {"angle": 180})):
            game.enqueue(sim.Input(0, "join", name, 0, payload))
        game.step()
        hunter, holder, other = (game.state["fighters"][n] for n in ("avichad", "holder", "other"))
        for f, x in ((hunter, 0), (holder, 6000), (other, -6000)):
            f.update(x=x, y=0, attack_at=99999, sig_at=99999, shield_until=0)
            f["intent"]["loot"] = "ignore"
        holder["bag"][hunter["legendary"]] = game.inventory_entry(hunter["legendary"])
        holder["equipped"]["trinket"] = hunter["legendary"]
        game._stats(holder)
        holder["hp"] = holder["max_hp"]
        return game, hunter, holder, other

    def test_only_the_worn_named_item_adds_one_hundred_fifty(self):
        game, hunter, holder, other = self.game()
        plain = game.target_score(hunter, other)
        self.assertEqual(game.target_score(hunter, holder), plain + 150)
        # Keeping it in the bag does not keep the hunt active.
        holder["equipped"]["trinket"] = "st-roll"
        self.assertEqual(game.target_score(hunter, holder), plain)
        other["equipped"]["trinket"] = hunter["legendary"]
        self.assertEqual(game.target_score(hunter, other), plain + 150)
        hunter["house"] = False
        self.assertEqual(game.target_score(hunter, other), plain)

    def test_chase_segment_replays_and_has_no_expiry(self):
        game, hunter, holder, other = self.game()
        game.state["tick"] = 12000
        game._policy()
        self.assertEqual(hunter["target"], "holder")
        self.assertGreater(hunter["move_x"], 0)
        start = game.export()
        final_hash = game.run(game.rules["segment_ticks"])
        replay = sim.Sim.restore(start, game.rules)
        self.assertEqual(replay.run(game.rules["segment_ticks"]), final_hash)
        print("chase segment:", final_hash, flush=True)


class Knobs(unittest.TestCase):
    def game(self, knob=None):
        rules = sim.rules_dict(sim.DEFAULT_RULES)
        rules["knobs"] = {k: k == knob for k in rules["knobs"]}
        game = sim.Sim(83, rules)
        for name, angle in (("a", 0), ("b", 180)):
            game.enqueue(sim.Input(0, "join", name, 0, {"angle": angle}))
        game.step()
        for name, x in (("a", 0), ("b", 3000)):
            game.state["fighters"][name].update(x=x, y=0, shield_until=0,
                attack_at=99999, sig_at=99999, target="b" if name == "a" else "a")
            game.state["fighters"][name]["intent"]["loot"] = "ignore"
        return game, game.state["fighters"]["a"], game.state["fighters"]["b"]

    def test_beam_slow_covers_windup_and_active_sweep(self):
        for phase in ("beam", "telegraph", "sweep", "idle"):
            with self.subTest(phase=phase):
                g, a, b = self.game("beam_fire_slow")
                a.update(move_x=a["speed"], move_y=0)
                if phase == "beam":
                    a["equipped"]["weapon"] = "c-beam"
                    g._fire_weapon(a, b, g._weapon(a), 6000)
                elif phase == "telegraph":
                    a["cast"] = {"kind": "beam_sweep", "resolve_at": 10}
                elif phase == "sweep":
                    g._object({"kind": "beam_sweep", "owner": "a", "until": 20})
                start = g.export()
                g._movement()
                moved = a["x"]
                expected = a["speed"] if phase == "idle" else a["speed"] // 2
                self.assertEqual(moved, expected)
                off = sim.rules_dict(g.rules)
                off["knobs"]["beam_fire_slow"] = False
                start["rules_hash"] = sim.digest(off)
                plain = sim.Sim.restore(start, off)
                plain._movement()
                self.assertEqual(plain.state["fighters"]["a"]["x"], a["speed"])

    def test_seeded_misses_cover_only_the_three_ranged_kinds(self):
        for kind in ("shot", "beam", "beam_sweep", "lob"):
            g, a, b = self.game("misses")
            rules = sim.rules_dict(g.rules)
            rules["miss_pct"] = 100
            g.rules = sim.freeze(rules)
            before = g.rng.state
            g._object_hit({"kind": kind, "owner": "a", "damage": 20,
                           "damage_pct": 100, "tier_pct": 100}, "b")
            self.assertEqual(bool(g.state["damages"]), kind == "lob")
            self.assertEqual(g.rng.state == before, kind == "lob")

    def test_looter_reengage_and_melee_dash_cooldown(self):
        for enabled in (False, True):
            g, a, b = self.game("looter_reengage" if enabled else None)
            b["x"] = 6000
            a.update(style="looter", hp=1, fleeing_since=0)
            g.state["tick"] = g.rules["survivor_reengage_ticks"]
            g._policy()
            self.assertEqual(a["move_x"] > 0, enabled)
            g, a, b = self.game("melee_gap_closer" if enabled else None)
            a["attack_at"] = 0
            g._attacks()
            self.assertEqual(a["x"] > 0, enabled)
            if enabled:
                self.assertEqual(a["gap_at"], g.state["tick"] + g.rules["gap_closer_cooldown"])
                a["x"] = 0
                g._attacks()
                self.assertEqual(a["x"], 0)
        self.assertFalse(any(sim.DEFAULT_RULES["knobs"].values()))


class Rivalry(unittest.TestCase):
    def test_rival_seek_crosses_the_whole_ring_but_normal_seek_does_not(self):
        hashes = []
        for seek in (False, True):
            rules = sim.rules_dict(sim.DEFAULT_RULES)
            rules["rival_seek"] = seek
            g = sim.Sim(87, rules)
            for name in ("captain-banana-zone", "kathie-moonwood", "stranger"):
                g.enqueue(sim.Input(0, "join", name, 0, {"house": name != "stranger"}))
            g.step()
            a, rival, stranger = (g.state["fighters"][n] for n in
                                 ("captain-banana-zone", "kathie-moonwood", "stranger"))
            for f, x, y in ((a, -11000, 0), (rival, 11000, 0), (stranger, 10000, 1000)):
                f.update(x=x, y=y, target=None, attack_at=99999, sig_at=99999)
                f["intent"]["loot"] = "ignore"
            self.assertEqual(g.target_score(a, stranger), -1)
            g._policy()
            self.assertEqual(a["target"], rival["id"] if seek else None)
            self.assertEqual(a["move_x"] > 0, seek)
            start = g.export()
            hashes.append(g.run(1200))
            self.assertEqual(sim.Sim.restore(start, rules).run(1200), hashes[-1])
        self.assertNotEqual(*hashes)
        self.assertTrue(sim.DEFAULT_RULES["rival_seek"])

    def test_rivalry_adds_three_hundred_without_overriding_other_terms(self):
        g, a, rival, other = Bounty().game()
        a["rivals"] = [rival["id"]]
        rival["equipped"]["trinket"] = "st-roll"
        plain = g.target_score(a, other)
        self.assertEqual(g.target_score(a, rival), plain + 300)
        a["rivals"] = []
        self.assertEqual(g.target_score(a, rival), plain)


if __name__ == "__main__":
    unittest.main()
