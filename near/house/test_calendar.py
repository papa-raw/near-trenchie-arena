"""The house's cap period follows the hackathon calendar by itself: building, then the soak, then judging,
then after-judging, each with its own day cap and battle style; --budget is an override that the roster names."""

import datetime
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import battle
import runtime


def at(text):
    return datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


class Meter:
    def today(self, day):
        return 0

    def total(self):
        return 0

    def add(self, day, microusd, usage=None):
        pass


CASES = [  # (UTC instant, period, day cap in USD, battle style)
    ("2026-11-11T12:00:00Z", "building", 2, "lean"),
    ("2026-11-14T23:58:59Z", "building", 2, "lean"),
    ("2026-11-14T23:59:00Z", "soak", 8, "full"),                       # the rules' deadline (HACKATHON.md:20)
    ("2026-11-14T23:59:59Z", "soak", 8, "full"),
    ("2026-11-15T23:59:59Z", "soak", 8, "full"),
    ("2026-11-16T00:00:00Z", "judging", 8, "full"),
    ("2026-11-18T23:59:59Z", "judging", 8, "full"),
    ("2026-11-19T00:00:00Z", "after", 3, "lean"),
    ("2026-11-25T12:00:00Z", "after", 3, "lean"),
]


class Calendar(unittest.TestCase):
    def test_every_boundary_by_the_utc_clock(self):
        for instant, period, cap, style in CASES:
            with self.subTest(instant=instant):
                clock = [at(instant)]
                b = runtime.Budget(Meter(), clock=lambda: clock[0])         # the default is the calendar
                self.assertEqual(b.mode, period)
                self.assertEqual(b.source, "calendar")
                self.assertEqual(b.cap_microusd, cap * runtime.USD)
                self.assertEqual(battle.style_for(b.mode), style)

    def test_one_budget_crosses_the_boundaries_as_time_passes(self):
        clock = [at("2026-11-14T23:58:59Z")]
        b = runtime.Budget(Meter(), clock=lambda: clock[0])
        seen = []
        for instant in ("2026-11-14T23:58:59Z", "2026-11-14T23:59:00Z", "2026-11-16T00:00:00Z", "2026-11-19T00:00:00Z"):
            clock[0] = at(instant)
            seen.append((b.mode, b.state()["cap_microusd"] // runtime.USD))
        self.assertEqual(seen, [("building", 2), ("soak", 8), ("judging", 8), ("after", 3)])

    def test_the_override_holds_and_says_so(self):
        clock = [at("2026-11-17T12:00:00Z")]                              # judging by the calendar
        b = runtime.Budget(Meter(), "building", clock=lambda: clock[0])
        self.assertEqual((b.mode, b.source, b.cap_microusd), ("building", "override", 2 * runtime.USD))
        with self.assertRaises(ValueError):
            runtime.Budget(Meter(), "weekend", clock=lambda: clock[0])


if __name__ == "__main__":
    unittest.main()
