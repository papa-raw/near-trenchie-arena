"""F26: the ItemSpec checks. A known-good fixture per slot and a kit-built one pass; each rule has a refusal."""

import copy
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import check_items
from arena import sim

LIMITS = check_items.load_limits()
KIT = json.loads((HERE / "fixtures/kit/kit.json").read_text())


def fixture(name):
    return json.loads((HERE / "fixtures" / name).read_text())


def check(spec, kit=KIT):
    return check_items.check_item(spec, sim.DEFAULT_RULES, kit, LIMITS)


class Good(unittest.TestCase):
    def test_one_known_good_fixture_per_slot_and_a_kit_built_one_pass(self):
        for name in ("known-good-head.json", "known-good-body.json", "known-good-weapon.json",
                     "known-good-trinket.json", "kit-built-weapon.json", "free-drawn-legendary.json"):
            self.assertEqual(check(fixture(name)), [], name)

    def test_cli_prints_the_count(self):
        self.assertEqual(check_items.main([]), 0)


class Refusals(unittest.TestCase):
    def refuses(self, name, change, text, kit=KIT):
        spec = fixture(name)
        change(spec)
        errors = check(spec, kit)
        self.assertTrue(any(text in e for e in errors), (text, errors))

    def test_each_rule_has_a_refusal(self):
        weapon = "known-good-weapon.json"
        cases = [
            ("node type off the whitelist", weapon, lambda s: s["nodes"].append({"type": "mesh", "color": "p01"}) if "nodes" in s else s.update(nodes=[{"type": "mesh", "color": "p01"}]), "whitelist"),
            ("raw hex colour", weapon, lambda s: s.update(nodes=[{"type": "box", "w": 1, "h": 1, "d": 1, "color": "#ff0000"}]), "palette"),
            ("reserved danger hue", weapon, lambda s: s.update(nodes=[{"type": "box", "w": 1, "h": 1, "d": 1, "color": "danger"}]), "palette"),
            ("scale above 4", weapon, lambda s: s.update(nodes=[{"type": "box", "w": 0.1, "h": 0.1, "d": 0.1, "color": "p01", "scale": 5}]), "scale"),
            ("scale below 0.25", weapon, lambda s: s.update(nodes=[{"type": "box", "w": 1, "h": 1, "d": 1, "color": "p01", "scale": [0.1, 1, 1]}]), "scale"),
            ("size field out of range", weapon, lambda s: s.update(nodes=[{"type": "sphere", "r": 0, "color": "p01"}]), "size field"),
            ("outside the slot box", weapon, lambda s: s.update(nodes=[{"type": "box", "w": 1, "h": 1, "d": 1, "color": "p01", "translate": [3, 0, 0]}]), "leaves the weapon box"),
            ("rotation pushes a node out", weapon, lambda s: s.update(nodes=[{"type": "box", "w": 0.7, "h": 0.1, "d": 2.2, "color": "p01", "translate": [0, 0.7, 0], "rotate": [0, 90, 0]}]), "leaves the weapon box"),
            ("41 nodes", weapon, lambda s: s.update(nodes=[{"type": "box", "w": 0.1, "h": 0.1, "d": 0.1, "color": "p01"}] * 41, kit=None) or s.pop("kit"), "nodes after kit expansion"),
            ("unknown kit base", weapon, lambda s: s.update(kit="weapon/missing"), "kit"),
            ("kit base for the wrong slot", weapon, lambda s: s.update(kit="head/cap"), "kit"),
            ("over the tier budget", weapon, lambda s: s["stats"].update(damage=9), "disagree"),
            ("banned word in the name", weapon, lambda s: s.update(name=("Jud" + "ge Club")), "banned"),
            ("weapon without move", weapon, lambda s: s.pop("move"), "move"),
            ("trinket without sig", "known-good-trinket.json", lambda s: s.pop("sig"), "sig"),
            ("tag on a trinket", "known-good-trinket.json", lambda s: s.update(tag="x"), "tag"),
            ("row not in the rules table", weapon, lambda s: s.update(id="c-nope"), "rules table"),
            ("slot disagrees with the row", weapon, lambda s: s.update(slot="head"), "disagree"),
            ("wrong spec string", weapon, lambda s: s.update(spec="trenchie-item/2"), "trenchie-item/3"),
            ("over 4 KB", "free-drawn-legendary.json", lambda s: s.update(note="x" * 5000), "bytes"),
            ("common with its own nodes and no kit base", weapon, lambda s: s.update(nodes=[{"type": "box", "w": 0.2, "h": 0.2, "d": 0.2, "color": "p01"}]) or s.pop("kit"), "names a kit base"),
            ("too many decorations", "kit-built-weapon.json", lambda s: s.update(nodes=s["nodes"] * 7), "decorations"),
        ]
        for label, name, change, text in cases:
            with self.subTest(label):
                self.refuses(name, change, text)

    def test_stat_over_forty_percent_and_total_over_budget(self):
        spec = fixture("known-good-weapon.json")
        row = dict(sim.DEFAULT_RULES["items"]["c-beam"]["stats"])
        rules = sim.rules_dict(sim.DEFAULT_RULES)
        rules["items"]["c-beam"]["stats"] = {**row, "damage": 5, "cooldown": 0, "hp": 0, "speed": 0, "range": 5}
        spec["stats"] = rules["items"]["c-beam"]["stats"]
        errors = check_items.check_item(spec, rules, KIT, LIMITS)
        self.assertTrue(any("40%" in e for e in errors), errors)
        rules["items"]["c-beam"]["stats"] = {**row, "damage": 4, "cooldown": 4, "hp": 4}
        spec["stats"] = rules["items"]["c-beam"]["stats"]
        errors = check_items.check_item(spec, rules, KIT, LIMITS)
        self.assertTrue(any("budget" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
