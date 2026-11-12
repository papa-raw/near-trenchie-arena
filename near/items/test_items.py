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



class LimitsVersions(unittest.TestCase):
    """trenchie-item-limits/2 (Pat's item 57): a wider weapon box for newly made items; released items keep /1."""

    def tall(self):
        """The kit-built rare club with a 3.0-tall shaft from y 0.9 to 3.9: 2.5x today's largest weapon."""
        spec = fixture("kit-built-weapon.json")
        spec["nodes"] = [{"type": "cylinder", "r": 0.05, "h": 3.0, "color": "p12", "translate": [0, 2.4, 0]}]
        return spec

    def test_a_weapon_three_point_nine_tall_passes_under_2_and_fails_under_1(self):
        spec = self.tall()
        version, errors = check_items.check(spec, sim.DEFAULT_RULES, KIT)
        self.assertEqual(version, "trenchie-item-limits/1")
        self.assertIn("a node leaves the weapon box", errors)
        version, errors = check_items.check(dict(spec, limits="trenchie-item-limits/2"), sim.DEFAULT_RULES, KIT)
        self.assertEqual((version, errors), ("trenchie-item-limits/2", []))
        over = dict(spec, limits="trenchie-item-limits/2")
        over["nodes"] = [dict(spec["nodes"][0], translate=[0, 2.62, 0])]          # reaches y 4.12
        self.assertIn("a node leaves the weapon box", check_items.check(over, sim.DEFAULT_RULES, KIT)[1])
        wide = dict(spec, limits="trenchie-item-limits/2")
        wide["nodes"] = [{"type": "box", "w": 1.6, "h": 0.2, "d": 0.2, "color": "p12", "translate": [0, 1.0, 0]}]
        self.assertEqual(check_items.check(wide, sim.DEFAULT_RULES, KIT)[1], [])  # x +-0.8, inside +-0.85
        one, two = check_items.limits_named("trenchie-item-limits/1"), check_items.limits_named("trenchie-item-limits/2")
        self.assertEqual({k: two[k] for k in two if two[k] != one.get(k)},
                         {"spec": "trenchie-item-limits/2", "status": two["status"],
                          "slot_boxes": dict(one["slot_boxes"], weapon={"min": [-0.85, -0.2, -1.2], "max": [0.85, 4.0, 1.2]}),
                          "weapon_render_scale": 1})                               # budgets and other slots unchanged

    def test_every_released_item_and_kit_row_validates_under_1_with_its_bytes_unchanged(self):
        import hashlib
        files = sorted(list((HERE / "specs").glob("*.json")) + list((HERE / "fixtures").rglob("*.json"))
                       + [HERE / "kit.json", HERE / "limits.json"])
        h = hashlib.sha256()
        for path in files:
            h.update(str(path.relative_to(HERE)).encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
        self.assertEqual(h.hexdigest(), "57c95a0acae0bfaef17ce05238b93bb29fce126fe0df384d33bc354d2a60b8f8")
        kit = json.loads((HERE / "kit.json").read_text())
        for path in sorted((HERE / "specs").glob("*.json")):
            with self.subTest(item=path.name):
                self.assertEqual(check_items.check(json.loads(path.read_text()), sim.DEFAULT_RULES, kit),
                                 ("trenchie-item-limits/1", []))

    def test_the_checker_names_the_version_it_used(self):
        import contextlib, io, tempfile
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "old.json").write_text(json.dumps(fixture("kit-built-weapon.json")))
            (Path(d) / "new.json").write_text(json.dumps(dict(self.tall(), limits="trenchie-item-limits/2")))
            (Path(d) / "tall-old.json").write_text(json.dumps(self.tall()))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = check_items.main(["--specs", d, "--kit", str(HERE / "fixtures/kit/kit.json")])
        lines = out.getvalue().splitlines()
        self.assertEqual(code, 1)
        self.assertTrue(lines[0].startswith("FAIL tall-old.json (trenchie-item-limits/1) "), lines)
        self.assertIn("2/3 items valid", lines[1])
        self.assertTrue(lines[1].endswith("under trenchie-item-limits/1 x2, trenchie-item-limits/2 x1"), lines[1])

    def test_an_unknown_limits_version_is_refused(self):
        version, errors = check_items.check(dict(self.tall(), limits="trenchie-item-limits/9"), sim.DEFAULT_RULES, KIT)
        self.assertEqual(version, "trenchie-item-limits/9")
        self.assertTrue(errors and errors[0].startswith("unknown limits version"), errors)
        self.assertIn("item was made under trenchie-item-limits/2, checked here under trenchie-item-limits/1",
                      check(dict(self.tall(), limits="trenchie-item-limits/2")))

if __name__ == "__main__":
    unittest.main()
