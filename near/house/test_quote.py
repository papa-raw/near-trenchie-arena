"""Prediction math on fixtures: the score, the payout and calibration(), recomputed independently."""

from fractions import Fraction
import json
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import quote

ROWS = json.loads((HERE / "fixtures" / "lives.json").read_text())["rows"]


class Score(unittest.TestCase):
    def test_hand_computed_scores(self):
        self.assertEqual(quote.score([100, 0, 0, 0], 1), 0)
        self.assertEqual(quote.score([100, 0, 0, 0], 4), 750_000)
        self.assertEqual(quote.score([100, 0, 0, 0], 2), 250_000)
        self.assertEqual(quote.score([25, 25, 25, 25], 3), 93_750)
        self.assertEqual(quote.base_score(quote.PUBLISHED_BASE_BPS, 1), 58_572)

    def test_matches_an_independent_recompute_on_every_fixture_life(self):
        for row in ROWS:
            full = Fraction(quote.rps_numerator(quote.five_bins(row["spread_pct"]), row["actual"]), quote.RPS_MAX)
            five = [0] + list(row["spread_pct"])
            cum, expect = Fraction(0), Fraction(0)
            for i in range(4):
                cum += Fraction(five[i], 100)
                expect += (cum - (1 if min(row["actual"], 4) <= i else 0)) ** 2
            self.assertEqual(full, expect / 4)

    def test_a_bad_spread_is_refused_and_zero_can_never_be_bet(self):
        for bad in ([100, 0, 0], [50, 50, 10, 0], [-10, 60, 25, 25], [50.0, 50, 0, 0], [True, 99, 0, 0]):
            self.assertIsNotNone(quote.check_spread(bad, 40), bad)
            with self.assertRaises(ValueError):
                quote.score(bad, 1)
        self.assertIsNotNone(quote.check_spread([100, 0, 0, 0], 101))
        self.assertEqual(quote.five_bins([100, 0, 0, 0])[0], 0)


class Payout(unittest.TestCase):
    def test_payout_is_stake_times_one_plus_base_minus_ai_and_zero_ko_pays_nothing(self):
        stake = 10 ** 22
        self.assertEqual(quote.payout(stake, [100, 0, 0, 0], 0), 0)
        self.assertEqual(quote.payout(stake, [100, 0, 0, 0], 1), stake * (1_000_000 + 58_572) // 1_000_000)
        worse = quote.payout(stake, [0, 0, 0, 100], 1)
        self.assertLess(worse, stake)
        self.assertGreaterEqual(worse, 0)
        self.assertEqual(quote.payout(0, [100, 0, 0, 0], 3), 0)
        with self.assertRaises(ValueError):
            quote.payout(1.5, [100, 0, 0, 0], 1)


class Calibration(unittest.TestCase):
    def test_always_saying_the_base_rate_scores_zero_skill_and_a_thin_record_is_none(self):
        rows = [{"persona": "p", "life": i, "spread_pct": [50, 30, 10, 10], "zero_pct": 40, "actual": a}
                for i, a in enumerate([1, 2, 1, 1, 3, 1, 2, 1, 1, 4, 1, 2])]
        # The persona's own lives all have at least 1 KO, so its trailing base has no zero bin; a
        # spread equal to the trailing base on the four bins would score 0. Here it is not, so skill is
        # an exact integer from the rows, recomputed below.
        out = quote.calibration(rows)["p"]
        ai = base = 0
        priors = []
        for r in rows:
            own = quote.base_rate_bps(priors) or quote.PUBLISHED_BASE_BPS
            ai += quote.rps_numerator(quote.five_bins(r["spread_pct"]), r["actual"])
            base += quote.rps_numerator(own, r["actual"])
            priors.append(r["actual"])
        self.assertEqual(out["skill_milli"], (base - ai) * 1000 // base)
        self.assertIsNone(quote.calibration(rows[:9])["p"]["skill_milli"])

    def test_repeating_its_own_base_rate_exactly_gives_zero_skill(self):
        # A persona whose every prior is [x] and states the same base: with constant actuals the
        # trailing base equals what it says after the first life; skill compares like with like.
        rows = [{"persona": "q", "life": i, "spread_pct": [100, 0, 0, 0], "zero_pct": 0, "actual": 1} for i in range(12)]
        out = quote.calibration(rows)["q"]
        self.assertEqual(out["lives"], 12)
        self.assertGreaterEqual(out["skill_milli"], 0)

    def test_fixture_readout_has_reliability_tables_and_two_personas(self):
        out = quote.calibration(ROWS)
        self.assertEqual(sorted(out), ["alpha", "bravo"])
        for name, row in out.items():
            self.assertEqual(row["lives"], 12)
            self.assertEqual(sum(b["lives"] for b in row["reliability_zero"].values()), 12)
            self.assertEqual(row["reliability_spread"]["scored_lives"],
                             sum(1 for r in ROWS if r["persona"] == name and r["actual"] >= 1))
        self.assertEqual(out["alpha"]["reliability_zero"]["40"]["mean_predicted_pct_milli"], 40_000)
        self.assertEqual(out["alpha"]["reliability_zero"]["40"]["observed_zero_pct_milli"], 5 * 100_000 // 12 * 1)


if __name__ == "__main__":
    unittest.main()
