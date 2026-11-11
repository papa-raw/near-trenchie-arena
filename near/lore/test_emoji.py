"""The persona emoji set's rules (near/lore/emoji.py) and the temperament defaults.

    python3 -I near/lore/test_emoji.py
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from near.lore import emoji  # noqa: E402


class EmojiSet(unittest.TestCase):
    def test_every_temperament_default_is_a_valid_set(self):
        schema = json.loads((ROOT / "near/lore/persona.schema.json").read_text())
        temperaments = schema["properties"]["game"]["properties"]["temperament"]["enum"]
        sets = emoji.defaults()
        self.assertEqual(sorted(sets), sorted(temperaments))
        for name, glyphs in sets.items():
            self.assertIsNone(emoji.check_set(glyphs), name)

    def test_the_rules_refuse_text_and_long_runs(self):
        for bad in ["a", "😀a", "😀😀😀😀😀", "", "☺" * 5, 7]:
            self.assertIsNotNone(emoji.check_glyph(bad), repr(bad))
        for good in ["😵‍💫", "☀️", "👍🏽", "🫠"]:
            self.assertIsNone(emoji.check_glyph(good), good)
        self.assertIsNotNone(emoji.check_set(["😀"] * 5))            # repeats
        self.assertIsNotNone(emoji.check_set(["😀", "😃", "😄"]))     # too few

    def test_critic_b_lows(self):
        self.assertIsNotNone(emoji.check_set(["☀", "☀️", "🌈", "🎉", "😎"]))      # one emoji, two forms
        for bad in ["😀\u200d", "\u200d😀", "😀\u200d\u200d😀", "©", "™", "©😀"]:
            self.assertIsNotNone(emoji.check_glyph(bad), repr(bad))
        for good in ["©️", "™️", "😵‍💫", "👍🏽", "🧑‍💻", "🏳️‍🌈"]:
            self.assertIsNone(emoji.check_glyph(good), good)
        with self.assertRaisesRegex(ValueError, "unknown temperament 'Grumpy'"):
            emoji.resolve({"temperament": "Grumpy"})

    def test_a_pick_outside_the_set_is_labelled_not_silent(self):
        game = {"temperament": "Gruff"}
        self.assertEqual(emoji.pick(game, "🔥"), {"emoji": "🔥", "emoji_source": "temperament", "emoji_fallback": False})
        self.assertEqual(emoji.pick(game, "hello")["emoji_fallback"], True)
        own = {"temperament": "Gruff", "emoji": ["🍌", "🐒", "🌴", "🥥", "😜"]}
        self.assertEqual(emoji.pick(own, "🐒")["emoji_source"], "sheet")


class RejectedSetFallsBack(unittest.TestCase):
    def test_a_set_the_checker_rejects_resolves_to_the_temperament_default(self):
        for bad in (["🍌"] * 5, ["🍌", "🐒"], ["🍌", "a", "🌴", "🥥", "😜"], "🍌🐒🌴🥥😜", None):
            game = {"temperament": "Earnest", "emoji": bad}
            glyphs, source = emoji.resolve(game)
            self.assertEqual((glyphs, source), (emoji.defaults()["Earnest"], "temperament"), repr(bad))
            line = emoji.pick(game, "🍌")
            self.assertEqual(line, {"emoji": emoji.defaults()["Earnest"][0], "emoji_source": "temperament",
                                    "emoji_fallback": True}, repr(bad))


class SheetsCarryTheirSet(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / "near/lore"))
        import check_personas
        self.cp = check_personas
        self.schema = json.loads((ROOT / "near/lore/persona.schema.json").read_text())
        self.kits = json.loads((ROOT / "near/lore/kits.json").read_text())

    def sheet(self, slug):
        return json.loads((ROOT / f"near/lore/personas/{slug}.json").read_text(encoding="utf-8"))

    def test_all_fourteen_house_sheets_carry_a_valid_set(self):
        for path in sorted((ROOT / "near/lore/personas").glob("*.json")):
            g = json.loads(path.read_text(encoding="utf-8"))["game"]
            self.assertIsNone(emoji.check_set(g.get("emoji")), path.name)
            self.assertIn("emoji: " + " ".join(g["emoji"]), self.cp.render(g))     # the AI reads the set it picks from
            self.assertLessEqual(len(self.cp.render(g)), self.cp.RENDER_MAX_CHARS)

    def test_a_house_sheet_without_a_set_is_refused(self):
        doc = self.sheet("satrenchi")
        del doc["game"]["emoji"]
        self.assertIn("a house sheet needs emoji", self.cp.check_doc(doc, "satrenchi", self.schema, self.kits))
        doc["game"]["emoji"] = ["🗿", "🗿", "🌊", "🐚", "🤫"]
        self.assertTrue(any("game.emoji" in p for p in self.cp.check_doc(doc, "satrenchi", self.schema, self.kits)))

    def test_a_creator_sheet_without_a_set_renders_its_temperament_set(self):
        g = {"temperament": "Sunny", "voice": ["gm"]}
        self.assertIn("emoji: " + " ".join(emoji.defaults()["Sunny"]), self.cp.render(g))


if __name__ == "__main__":
    unittest.main()
