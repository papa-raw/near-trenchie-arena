"""W16: a fed repeat is rerolled once, then replaced by the labelled keyed line; a 20-line run per sheet."""

import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import novelty

SHEETS = json.loads((HERE / "fixtures" / "sheets.json").read_text())["sheets"]


def feed(lines):
    it = iter(lines)
    return lambda: next(it)


class Check(unittest.TestCase):
    def test_jaccard_boundary_is_one_half_inclusive(self):
        a, b = novelty.words("one two three four"), novelty.words("one two five six")
        self.assertFalse(novelty.is_repeat_of(a, b))          # 2 / 6
        self.assertTrue(novelty.is_repeat_of(novelty.words("one two three"), novelty.words("one two four")))  # 2 / 4
        self.assertTrue(novelty.is_repeat_of(novelty.words("a b"), novelty.words("a b c d")))  # 2 / 4
        self.assertFalse(novelty.is_repeat_of(frozenset(), frozenset()))

    def test_a_fed_repeat_is_rerolled_once_then_replaced_by_the_labelled_keyed_line(self):
        voice = novelty.Voice("Harbour", SHEETS[0]["keyed"])
        spent = []
        first = voice.post(feed(["One coin, one island."]), "idle")
        self.assertEqual((first["source"], first["label"], first["rerolled"]), ("model", None, 0))
        second = voice.post(feed(["One coin, one island!", "Fresh water is cold today."]), "idle", lambda: spent.append(1))
        self.assertEqual((second["source"], second["rerolled"], second["text"]), ("reroll", 1, "Fresh water is cold today."))
        third = voice.post(feed(["One coin one island.", "Fresh water is cold."]), "ko_given", lambda: spent.append(1))
        self.assertEqual((third["source"], third["label"], third["text"]), ("keyed", "repeat", "Down you go."))
        self.assertEqual(len(spent), 2)                          # each reroll is metered, the keyed line is free
        self.assertEqual(voice.stats["keyed"], 1)

    def test_card_carries_the_last_three_and_a_line_gets_one_reply(self):
        voice = novelty.Voice("Harbour", SHEETS[0]["keyed"])
        for i, line in enumerate(["alpha one", "bravo two", "charlie three", "delta four"]):
            voice.post(feed([line]), "idle")
        self.assertEqual(voice.card_lines(), ["bravo two", "charlie three", "delta four"])
        self.assertTrue(voice.may_reply("line-1"))
        self.assertFalse(voice.may_reply("line-1"))

    def test_window_is_the_last_twenty_posted_lines(self):
        voice = novelty.Voice("Harbour", SHEETS[0]["keyed"])
        voice.post(feed(["unique opening salvo"]), "idle")
        for i in range(20):
            voice.post(feed(["filler %s line %s" % ("abcdefghijklmnopqrst"[i] * 3, i)]), "idle")
        self.assertFalse(voice.repeats("unique opening salvo"))   # pushed out of the 20-line window

    def test_twenty_lines_per_sheet_post_no_repeat(self):
        for sheet in SHEETS:
            pool, index = sheet["pool"], [0]

            def generate():
                line = pool[index[0] % len(pool)]
                index[0] += 1
                return line

            out = novelty.run_lines(sheet, generate)
            print("%s: 20 lines, repeats posted %d, rerolls %d, keyed lines %d"
                  % (sheet["name"], out["repeats_posted"], out["rerolls"], out["keyed_lines"]))
            self.assertEqual(out["repeats_posted"], 0)
            self.assertGreater(out["rerolls"], 0)
            self.assertEqual(sum(p["label"] == "repeat" for p in out["posted"]), out["keyed_lines"])
            self.assertTrue(all(p["label"] in (None, "repeat") for p in out["posted"]))

    def test_repeats_posted_is_measured_from_the_posted_list_so_a_broken_checker_shows(self):
        from unittest import mock
        sheet = SHEETS[0]
        with mock.patch.object(novelty.Voice, "repeats", lambda self, line: False):    # a checker that never fires
            out = novelty.run_lines(sheet, lambda: "One coin, one island.")
        self.assertGreater(out["repeats_posted"], 0)


if __name__ == "__main__":
    unittest.main()
