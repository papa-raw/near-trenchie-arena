"""F77: five presets, a closed set, each a legal kit on the live table; Shot has none."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import balance
import presets
import sim


class Presets(unittest.TestCase):
    def test_five_legal_kits_in_a_closed_set_without_shot(self):
        rules = sim.DEFAULT_RULES
        found = presets.all_presets(rules)
        self.assertEqual([p["name"] for p in found], list(presets.NAMES))
        self.assertEqual(len(found), 5)
        self.assertNotIn("shot", [p["weapon_kind"] for p in found])
        game = sim.Sim(1, rules)
        for p in found:
            game._check_kit(p["loadout"], {})                       # legal: default-menu rows only
            self.assertEqual(rules["items"][p["loadout"]["weapon"]]["weapon"], p["weapon_kind"])
            self.assertEqual(rules["items"][p["loadout"]["trinket"]]["signature"], p["signature"])
            self.assertIn(p["style"], rules["styles"])
        self.assertEqual([(p["style"], p["weapon_kind"], p["signature"]) for p in found], list(balance.PRESETS))

    def test_the_sweep_runs_the_same_five(self):
        matrix = balance.scenarios(sim.DEFAULT_RULES)
        indexes = {c.left for c in matrix if c.family == "preset_duel"} | {c.right for c in matrix if c.family == "preset_duel"}
        self.assertEqual(indexes, {str(i) for i in range(5)})
        self.assertTrue(any(c.family == "crowd" and c.build == "presets" for c in matrix))


if __name__ == "__main__":
    unittest.main()
