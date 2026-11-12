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


class Variants(unittest.TestCase):
    """Spacing, case, punctuation and invisible characters must not slip a listed name past the
    guard (it also signs persona permits). Every name here is the invented stand-in from LIST."""

    def setUp(self):
        self.g = guard.Guard(LIST, SPOOFS)

    def blocked(self, line):
        return self.g.check(line)["blocked"]

    def test_a_listed_name_is_blocked_in_every_spelling_variant(self):
        for line in ("FAKEY  MCFAKEFACE", "Fakey\tMcFakeface", "Fakey \n McFakeface",       # runs of whitespace
                     "Fakey-McFakeface", "Fakey_McFakeface", "Fakey.McFakeface",           # hyphen, underscore, dot
                     "Fakey\u2013McFakeface", "Fakey \u2014 McFakeface",                   # en and em dash
                     "Fakey\u200bMcFakeface", "Fa\u200bkey Mc\u200dFakeface", "\ufeffFakey McFakeface",  # zero-width
                     "FakeyMcFakeface", "fakeymcfakeface",                                  # run together
                     "\uff26\uff41\uff4b\uff45\uff59 McFakeface",                           # fullwidth (NFKC)
                     "Fakey\u00a0McFakeface",                                               # no-break space
                     "Fakey/McFakeface", "Fakey,McFakeface", "Fakey'McFakeface", "Fakey+McFakeface",   # any other
                     "Fakey*McFakeface", "Fakey:McFakeface", "Fakey|McFakeface", "Fakey~McFakeface",   # non-word mark
                     "Fakey\U0001f525McFakeface", "(Fakey) [McFakeface]",                           # emoji, brackets
                     "QUILL ZEPHYRWOOD", "quill-zephyrwood"):
            self.assertTrue(self.blocked("hello " + line + " there"), repr(line))
            self.assertEqual(self.g.reason(line), "real-name", repr(line))

    def test_handles_and_slurs_are_normalised_the_same_way(self):
        for line in ("ping @FAKEYHANDLE", "ping @fakey\u200bhandle", "you BLORP", "you b\u200blorp", "you \uff42lorp"):
            self.assertTrue(self.blocked(line), repr(line))

    def test_normalising_does_not_widen_the_rules(self):
        for line in ("Fakey is a first name on its own", "Zephyrwood alone is a surname", "a blorpish day",
                     "Fakey McFakefaced", "the Great Rug took everything", "time to exit the ring"):
            self.assertFalse(self.blocked(line), repr(line))
        for line in ("co-op, e.g. a fakey's day", "Fakey's McFakefaced cousin", "Fakey/someone else"):
            self.assertFalse(self.blocked(line), repr(line))
        g = guard.Guard({"names": ["Zephyrwood Warrior"], "handles": [], "slurs": []}, SPOOFS)
        for line in ("Zephyrwood Warrior swings", "zephyrwood-warrior swings", "Zephyrwood  Warrior swings"):
            self.assertFalse(g.check(line)["blocked"], repr(line))                 # the spoof is still the longest match

    def test_gaps_inside_one_word_are_read_as_the_word_for_terms_of_four_letters_or_more(self):
        # guard-confusables: was a stated limit in guard-norm.
        for line in ("you b-l-o-r-p", "you bl orp", "you b.l.o.r.p", "you b\u200bl\u200bo\u200br\u200bp"):
            self.assertTrue(self.blocked(line), repr(line))

    def test_the_posted_text_is_never_rewritten(self):
        self.assertEqual(self.g.check("Satrenchi  waves\u2014hi")["text"], "Satrenchi  waves\u2014hi")


class Lookalikes(unittest.TestCase):
    """guard-confusables (two lookalike gaps after guard-norm, fixed before any mainnet identity, since a
    mainnet NFT title is permanent). Invented names only; every non-ASCII character is written as an escape."""

    def setUp(self):
        self.g = guard.Guard(dict(LIST, slurs=["blorp", "zzslur", "qx"]), SPOOFS)

    def blocked(self, line):
        return self.g.check(line)["blocked"]

    def test_letters_from_other_scripts_fold_to_the_latin_letter_they_imitate(self):
        for line in ("F\u0430k\u0435y McF\u0430k\u0435f\u0430c\u0435",    # Cyrillic a, e
                     "Fakey McFakef\u0430\u0441e",                          # Cyrillic a, c
                     "\u0392lorp", "bl\u03bfrp", "b\u217corp",           # Greek capital beta, omicron; roman numeral l
                     "Quill Z\u0435phyrw\u043e\u043ed",                    # Cyrillic e, o, o
                     "ping @f\u0430keyh\u0430ndle",
                     "\u13f4lorp",                                          # Cherokee letter that imitates B
                     "Fak\u00e9y McFak\u00ebfac\u00e9", "Fa\u0301key McFakeface", "bl\u00f6rp",   # accents, precomposed or combining
                     "Q\u00fcill Z\u00e9phyrwood"):
            self.assertTrue(self.blocked(line), repr(line))

    def test_digit_swaps_are_read_as_the_letters_they_imitate(self):
        for line in ("F4key McF4kef4ce", "Fak3y McFak3fac3", "Quill Zephyrw00d", "Qu1ll Zephyrwood", "Qui11 Zephyrwood",
                     "bl0rp", "BL0RP", "ping @f4keyh4ndle", "zz5lur", "zz 5 1ur", "F4k3y_McF4k3f4c3"):
            self.assertTrue(self.blocked(line), repr(line))

    def test_a_single_word_term_split_anywhere_is_still_the_term(self):
        for line in ("zz slur", "z.z.slur", "z z s l u r", "zzs-lur", "ping @fakey_handle", "ping @fakey handle"):
            self.assertTrue(self.blocked(line), repr(line))

    def test_folding_does_not_widen_the_rules(self):
        for line in ("Fakey is a first name on its own", "Zephyrwood alone is a surname", "a blorpish day",
                     "Fakey McFakefaced", "the Great Rug took everything", "time to exit the ring",
                     "it's cam's turn", "slab lorry plus", "fizz slurp", "the qxz key",       # no over-match across words
                     "q x marks", "a q and an x",                                              # a term under 4 letters keeps word gaps only
                     "4 or 5 KOs", "loot at 0300", "I'll be 1st"):
            self.assertFalse(self.blocked(line), repr(line))
        self.assertTrue(self.blocked("qx"))
        g = guard.Guard({"names": ["Zephyrwood Warrior"], "handles": [], "slurs": []}, SPOOFS)
        for line in ("Zephyrw00d Warrior swings", "Z\u0435phyrwood Warrior swings", "Zephyr wood Warrior swings"):
            self.assertFalse(g.check(line)["blocked"], repr(line))                  # the spoof is still the longest match

    def test_accusation_words_read_other_scripts_but_keep_their_spelling(self):
        self.assertEqual(self.g.reason("that is a \u0455\u0441\u0430m"), "accusation-word")   # Cyrillic s, c, a
        self.assertEqual(self.g.reason("they went to jail"), "accusation-word")                # i and l are not merged here
        self.assertEqual(self.g.reason("they went to ja\u00efl"), "accusation-word")          # an accent does not hide it
        g = guard.Guard({"names": ["Jos\u00e9 Fakename"], "handles": [], "slurs": []}, [])
        for line in ("Jos\u00e9 Fakename", "Jose Fakename", "JOSE\u0301 FAKENAME"):            # a listed accented name still matches
            self.assertEqual(g.reason(line), "real-name", repr(line))

    def test_the_fold_table_is_unicodes_and_carries_its_notice(self):
        table = guard.CONFUSABLES
        self.assertTrue(table["source"].startswith("https://www.unicode.org/Public/security/"), table["source"])
        self.assertIn("Unicode", table["notice"])
        self.assertTrue(all(len(k) == 1 and ord(k) > 127 and v.isascii() and v.isalnum() for k, v in table["map"].items()))
        self.assertGreater(len(table["map"]), 500)

    def test_the_posted_text_is_never_rewritten(self):
        self.assertEqual(self.g.check("F4key waves \u0430t you")["text"], "F4key waves \u0430t you")


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
