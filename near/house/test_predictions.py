"""F79: sealed locks, one line per life, a readout that matches an independent recompute, no secrets in the file."""

from fractions import Fraction
import math
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import predictions
import quote

SPREAD = [[50, 30, 10, 10], [10, 60, 20, 10], [20, 20, 30, 30]]


def run(log, persona, actuals, start=0):
    for i, actual in enumerate(actuals):
        life = "%s:%d" % (persona, start + i)
        spread = SPREAD[i % 3]
        log.lock(life, "r" * 64, persona, "owner.testnet", "model-x", spread, 20 + 10 * (i % 3))
        log.resolve(life, actual, stake_yocto=10 ** 22 if i % 2 else 0, batch_tx="tx%d" % i)


class Log(unittest.TestCase):
    def test_a_written_run_reads_back_and_the_readout_matches_an_independent_recompute(self):
        with tempfile.TemporaryDirectory() as d:
            log = predictions.PredictionLog(d)
            actuals = [0, 1, 2, 1, 0, 3, 1, 1, 2, 0, 4, 1]
            run(log, "alpha", actuals)
            rows = log.rows()
            self.assertEqual(len(rows), 12)
            self.assertEqual(set(rows[0]), set(predictions.FIELDS))
            out = log.readout()["alpha"]
            # Independent recompute: cumulative-form ranked score in Fractions against the persona's own
            # trailing base rate (the whole-bps rounding the log publishes), skill = floor(1000 * (base - ai) / base).
            def rps(forecast, actual):
                cum, total = Fraction(0), Fraction(0)
                for j in range(4):
                    cum += forecast[j]
                    total += (cum - (1 if min(actual, 4) <= j else 0)) ** 2
                return total
            ai = base = Fraction(0)
            for i, actual in enumerate(actuals):
                bps = quote.base_rate_bps(actuals[:i]) or quote.PUBLISHED_BASE_BPS
                ai += rps([Fraction(x, 100) for x in [0] + SPREAD[i % 3]], actual)
                base += rps([Fraction(b, 10000) for b in bps], actual)
            self.assertEqual(out["skill_milli"], math.floor((base - ai) * 1000 / base))

    def test_locks_are_immutable_and_a_line_needs_its_lock(self):
        with tempfile.TemporaryDirectory() as d:
            log = predictions.PredictionLog(d)
            first = log.lock("a:0", "r" * 64, "a", "o", "m", [40, 30, 20, 10], 30)
            self.assertEqual(first, log.locks["a:0"]["hash"])
            with self.assertRaises(ValueError):
                log.lock("a:0", "r" * 64, "a", "o", "m", [100, 0, 0, 0], 30)
            with self.assertRaises(ValueError):
                log.resolve("never-locked", 1)
            log.resolve("a:0", 2)
            with self.assertRaises(ValueError):
                log.resolve("a:0", 2)
            reopened = predictions.PredictionLog(d)
            with self.assertRaises(ValueError):
                reopened.lock("a:0", "r" * 64, "a", "o", "m", [40, 30, 20, 10], 30)

    def test_no_prediction_is_an_explicit_marker_with_null_scores_and_an_invalid_spread_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            log = predictions.PredictionLog(d)
            log.lock("b:0", "r" * 64, "b", "o", "m")
            row = log.resolve("b:0", 3)
            self.assertEqual((row["prediction"], row["score"], row["base_score"]), (False, None, None))
            with self.assertRaises(ValueError):
                log.lock("b:1", "r" * 64, "b", "o", "m", [50, 50, 50, 0], 10)
            self.assertEqual(log.readout()["b"]["lives"] if "b" in log.readout() else 0, 0)

    def test_the_file_carries_only_whitelisted_fields_and_no_key(self):
        with tempfile.TemporaryDirectory() as d:
            log = predictions.PredictionLog(d)
            run(log, "c", [1, 2])
            text = (Path(d) / "predictions.jsonl").read_text()
            for secret in ("sk-", "Bearer", "api_key", "prompt", "reasoning"):
                self.assertNotIn(secret, text)
            self.assertEqual(len(log.log_hash()), 64)
            before = log.log_hash()
            run(log, "c", [3], start=2)
            self.assertNotEqual(before, log.log_hash())
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()), ["predictions.jsonl"])


if __name__ == "__main__":
    unittest.main()
