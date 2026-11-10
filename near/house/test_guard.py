"""F32/W17: the guard blocks by the written rules, and without its list it mutes and says so."""

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import guard

# Invented stand-ins only: the real list never enters this tree.
LIST = {"names": ["Fakey McFakeface", "Quill Zephyrwood"], "handles": ["@fakeyhandle"], "slurs": ["blorp"]}
SPOOFS = ["Satrenchi", "Laser Sailor", "Zephyrwood Warrior"]


class Rules(unittest.TestCase):
    def setUp(self):
        self.g = guard.Guard(LIST, SPOOFS)

    def blocked(self, line):
        return self.g.check(line)["blocked"]

    def test_names_handles_and_slurs_block_whole_matches_ignoring_case(self):
        self.assertTrue(self.blocked("hello FAKEY mcfakeface"))
        self.assertTrue(self.blocked("ping @FakeyHandle now"))
        self.assertTrue(self.blocked("you blorp"))
        self.assertFalse(self.blocked("a blorpish day"))          # whole match only
        self.assertFalse(self.blocked("Fakey is a first name on its own"))
        self.assertFalse(self.blocked("Zephyrwood alone is a surname"))

    def test_accusation_words_always_block_and_exit_does_not(self):
        for word in ("scam", "fraud", "jail", "scammer", "Fraudster", "jailed", "frauds", "scamming"):
            self.assertTrue(self.blocked("that is a %s" % word.upper()), word)
        self.assertFalse(self.blocked("time to exit the ring"))

    def test_rug_blocks_only_beside_a_trenchie_name_or_a_real_name(self):
        self.assertFalse(self.blocked("the Great Rug took everything"))
        self.assertFalse(self.blocked("I got rugged by a faceless whale"))
        self.assertTrue(self.blocked("Satrenchi rugged us"))
        self.assertTrue(self.blocked("Laser Sailor did a rug pull"))
        self.assertTrue(self.blocked("Quill Zephyrwood is a rugger"))
        self.assertTrue(self.blocked("Satrenchi pulled the Great Rug"))          # B22: never beside a trenchie's name
        self.assertTrue(self.blocked("Satrenchi mourns the Great Rug"))
        self.assertFalse(self.blocked("the Great Rug was a faceless whale"))

    def test_longest_match_wins_so_a_spoof_that_contains_a_listed_name_is_allowed(self):
        g = guard.Guard({"names": ["Zephyrwood Warrior"], "handles": [], "slurs": []}, SPOOFS)
        self.assertFalse(g.check("Zephyrwood Warrior swings")["blocked"])
        g2 = guard.Guard({"names": ["Satrenchi Fakesurname"], "handles": [], "slurs": []}, SPOOFS)
        self.assertTrue(g2.check("Satrenchi Fakesurname swings")["blocked"])

    def test_a_blocked_line_becomes_an_emote_and_is_logged_by_hash_not_content(self):
        out = self.g.check("so Fakey McFakeface said", who="satrenchi")
        self.assertTrue(out["blocked"] and out["text"] in guard.EMOTES)
        row = self.g.log[-1]
        self.assertEqual((row["who"], row["reason"]), ("satrenchi", "real-name"))
        self.assertNotIn("Fakey", json.dumps(row))


class MissingList(unittest.TestCase):
    def test_without_the_block_list_every_line_is_muted_and_the_notice_says_so(self):
        for var in (None, "/nonexistent/blocklist.json"):
            old = os.environ.pop(guard.ENV, None)
            try:
                if var:
                    os.environ[guard.ENV] = var
                g = guard.Guard.from_env(SPOOFS)
            finally:
                os.environ.pop(guard.ENV, None)
                if old is not None:
                    os.environ[guard.ENV] = old
            self.assertEqual(g.notice(), "guard list missing")
            out = g.check("a perfectly nice line")
            self.assertTrue(out["blocked"] and out["reason"] == "guard-list-missing")
            self.assertIn(out["text"], guard.EMOTES)

    def test_a_list_file_outside_the_tree_loads_and_clears_the_notice(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "list.json"
            path.write_text(json.dumps(LIST))
            g = guard.Guard.from_env(SPOOFS, str(path))
            self.assertIsNone(g.notice())
            self.assertFalse(g.check("a perfectly nice line")["blocked"])
            path.write_text("not json")
            self.assertTrue(guard.Guard.from_env(SPOOFS, str(path)).missing)


if __name__ == "__main__":
    unittest.main()
