"""The public feed's battle-mode rules: one line per 10 s per fighter, an emoji that travels with the line,
and the speaker's own set found through game_of (the emoji rules in near/lore/emoji.py)."""

from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import feed as feed_mod
import guard

SET = ["🦀", "🔥", "💥", "😤", "🏃"]
GAMES = {"crab": {"temperament": "Restless", "emoji": SET}, "pond": {"temperament": "Serene"}}


def feed(posted=None):
    return feed_mod.PublicFeed(guard.Guard({"names": [], "handles": [], "slurs": []}, ["Crab"]),
                               on_post=(posted.append if posted is not None else None), game_of=GAMES.get)


class TenSeconds(unittest.TestCase):
    def test_one_line_per_10_s_per_fighter(self):
        self.assertEqual(feed_mod.RATE_TICKS, 200)
        f = feed()
        self.assertNotIn("refused", f.post("crab", "one", source="house", tick=1000))
        self.assertEqual(f.post("crab", "two", source="house", tick=1199), {"refused": "rate_limited", "retry_after_s": 1})
        self.assertNotIn("refused", f.post("pond", "mine", source="player", tick=1199), "the limit is per fighter")
        self.assertNotIn("refused", f.post("crab", "two", source="house", tick=1200), "10 s later the next line posts")

    def test_the_limit_holds_across_a_round_because_the_feed_outlives_it(self):
        f = feed()
        f.post("crab", "end of round one", source="house", tick=5000)
        # a new round's clock continues after the feed's last line (LiveHouse.feed_clock, the host's feed_tick)
        self.assertGreater(f.high_tick, 0)
        self.assertEqual(f.post("crab", "too soon", source="house", tick=f.high_tick + 1)["refused"], "rate_limited")
        self.assertNotIn("refused", f.post("crab", "now", source="house", tick=f.high_tick + feed_mod.RATE_TICKS))


class Emoji(unittest.TestCase):
    def test_the_chosen_emoji_travels_with_the_line(self):
        posted = []
        f = feed(posted)
        row = f.post("crab", "Pinch first", source="house", tick=0, emoji="🔥")
        self.assertEqual((row["emoji"], row["emoji_source"], row["emoji_fallback"]), ("🔥", "sheet", False))
        self.assertEqual(posted[0]["emoji"], "🔥", "the on_post hook sees it")
        self.assertEqual(f.since(0)[0]["emoji"], "🔥", "the public rows carry it")

    def test_a_missing_or_foreign_emoji_is_the_sets_first_flagged_never_silent(self):
        f = feed()
        for i, chosen in enumerate((None, "🐸", "x", "🔥🔥🔥🔥🔥")):
            row = f.post("crab", "line %d" % i, source="house", tick=i * 200, emoji=chosen)
            self.assertEqual((row["emoji"], row["emoji_fallback"]), ("🦀", True), chosen)

    def test_game_of_supplies_the_set_and_a_sheet_without_one_uses_its_temperament(self):
        f = feed()
        row = f.post("pond", "Breathe first", source="player", tick=0, emoji=None)
        self.assertEqual(row["emoji_source"], "temperament")
        self.assertTrue(row["emoji"])
        plain = feed_mod.PublicFeed(guard.Guard({"names": [], "handles": [], "slurs": []}, []))
        self.assertNotIn("emoji", plain.post("crab", "no game_of", source="house", tick=0), "no game block, no emoji fields")


if __name__ == "__main__":
    unittest.main()
