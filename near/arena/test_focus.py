"""A focus order lands (rules table integer-12): a fighter told to focus an enemy in view targets it within 2 s of
sim time (40 ticks) after the order applies at receive_tick + 2, whatever it was targeting before.

integer-11 kept focus at +150, a preference that the 125% sticky rule let a closer, hurt, recently hit enemy outvote
for the whole life. integer-12 sets focus_weight so that a focused enemy at the edge of view (base score 0) beats
125% of the largest score any other target can reach, for every style. integer-11 stays on disk and replays by hash.
"""

import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import replay  # noqa: E402
import sim  # noqa: E402

RULES = HERE / "rules"
WINDOW = 40                      # 2 s at 20 Hz
INPUT_DELAY = 2                  # an intent applies at receive_tick + 2


def table(name):
    return json.loads((RULES / name).read_bytes())


def scene(rules, style="brawler"):
    """a holds b as its target (close, hurt, just hit); c stands near the edge of a's view, unhurt."""
    game = sim.Sim(4242, rules)
    for name in ("a", "b", "c"):
        game.enqueue(sim.Input(0, "join", name, 0, {"angle": 0, **({"style": style} if name == "a" else {})}))
    game._inputs()
    game.state["tick"] = 100
    for name, (x, y) in (("a", (0, 0)), ("b", (1500, 0)), ("c", (0, 9000))):
        game.state["fighters"][name].update(x=x, y=y, hp=100, max_hp=100, attack_at=10 ** 9, sig_at=10 ** 9,
                                            shield_until=0, speed=0)
    a, b = game.state["fighters"]["a"], game.state["fighters"]["b"]
    b["hp"] = 30
    a.update(target="b", target_since=0, last_intent=-10 ** 6)
    a["hits"]["b"] = game.state["tick"]
    return game, a


def focus_lands(rules, style="brawler"):
    game, a = scene(rules, style)
    game.step()                                        # a settles on b
    held = a["target"]
    receive = game.state["tick"]
    game.enqueue(sim.Input(receive + INPUT_DELAY, "intent", "a", 1,
                           {"focus": "c", "avoid": None, "loot": "nearest", "sig": "auto", "leave": False}))
    for _ in range(INPUT_DELAY + WINDOW):
        for f in game.state["fighters"].values():      # keep the scene still: nobody walks out of view
            f["speed"] = 0
        game.step()
        if a["target"] == "c":
            return held, game.state["tick"] - (receive + INPUT_DELAY)
    return held, None


class FocusLands(unittest.TestCase):
    def test_focus_switches_within_2_s_on_integer_12_and_not_on_integer_11(self):
        held, after = focus_lands(table("integer-12.json"))
        self.assertEqual(held, "b")
        self.assertIsNotNone(after, "integer-12: the focus order never took the target")
        self.assertLessEqual(after, WINDOW)
        held, after = focus_lands(table("integer-11.json"))
        self.assertEqual(held, "b")
        self.assertIsNone(after, "integer-11 is the failing baseline: +150 never outvotes the held target")

    def test_every_style_switches_and_the_weight_beats_the_sticky_bound(self):
        rules = table("integer-12.json")
        for style in sorted(rules["styles"]):
            _, after = focus_lands(rules, style)
            self.assertIsNotNone(after, style)
            self.assertLessEqual(after, WINDOW, style)
        # the guarantee, from the table alone: a focused enemy with base score 0 beats sticky_percent of the best other
        best_other = 0
        for w in rules["styles"].values():
            fighter = (w[0] + w[1] + w[2] + w[4]) * rules["percent"] + rules["rivalry_weight"] + rules["bounty_weight"]
            drop = w[3] * max(rules["tier_value"].values())
            best_other = max(best_other, fighter, drop)
        self.assertGreater(rules["focus_weight"] * rules["percent"], best_other * rules["sticky_percent"])
        self.assertLess(rules["sticky_ticks"], WINDOW, "a fresh switch's lock ends inside the window")

    def test_the_host_runs_integer_12s_focus_and_old_segments_replay_under_their_own_table(self):
        new, old = table("integer-12.json"), table("integer-11.json")
        self.assertEqual(sim.digest(new), "e1a357d20e2beeac7c1e1a9ac640640de3a134a7fba77c6a17a511230d086aaf")
        self.assertEqual(sim.DEFAULT_RULES["focus_weight"], new["focus_weight"], "integer-13 keeps integer-12's focus")
        self.assertEqual(sim.digest(old), "73e9ca29a956f7344f02443660838626e5229b7ef4cce4cc72f7bad47673348f")
        self.assertEqual({k for k in set(new) | set(old) if new.get(k) != old.get(k)}, {"version", "focus_weight"})
        for name in ("integer-11.json", "integer-12.json"):
            self.assertEqual(sim.digest(replay.load_rules(sim.digest(table(name)))), sim.digest(table(name)))


if __name__ == "__main__":
    unittest.main()
