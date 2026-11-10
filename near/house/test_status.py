"""Private status for every admitted member, a separate public roster, no player spend in public output."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import status

CANARIES = ("CANARY-SPEND-424242", "CANARY-CAP-737373", "CANARY-REASONING-the-secret-plan")


def members():
    rows = [{"persona": "satrenchi", "model": "deepseek-ai/DeepSeek-V4.1-Flash-1017", "state": "alive", "life": 3,
             "spend_today_microusd": 1500, "calls_per_min": 12, "house": True},
            {"persona": "laser-sailor", "model": "deepseek-ai/DeepSeek-V4.1-Flash-1017", "state": "bench", "life": 1,
             "spend_today_microusd": 900, "calls_per_min": 4, "house": True},
            {"persona": "player-one", "model": "gpt-example", "state": "alive", "life": 2,
             "spend_today_microusd": 424242, "calls_per_min": 30, "house": False,
             "cap": 737373, "reasoning": CANARIES[2]}]
    rows[2]["spend_today_microusd"] = 424242
    return rows


class Fields(unittest.TestCase):
    def test_fields_and_period(self):
        with tempfile.TemporaryDirectory() as d:
            writer = status.StatusWriter(d)
            stamps = []
            for now in range(0, 13):                      # a clock ticking once a second for 12 s
                if writer.maybe_write(members(), now):
                    stamps.append(now)
            self.assertEqual(stamps, [0, 5, 10])
            self.assertTrue(all(b - a <= 5 for a, b in zip(stamps, stamps[1:])))
            private = json.loads((Path(d) / "status.json").read_text())
            self.assertEqual(len(private["members"]), 3)
            for row in private["members"]:
                for field in status.PRIVATE_FIELDS:
                    self.assertIn(field, row)
            public = json.loads((Path(d) / "roster.json").read_text())
            self.assertEqual(public["admitted"], len(private["members"]))
            states = {m["persona"]: m["state"] for m in public["members"]}
            self.assertEqual(states["player-one"], "in the ring")
            by = {m["persona"]: m for m in public["members"]}
            self.assertIn("spend_today_microusd", by["satrenchi"])
            self.assertNotIn("spend_today_microusd", by["player-one"])
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()), ["roster.json", "status.json"])

    def test_player_spend_cap_and_reasoning_canaries_never_reach_the_public_projection(self):
        text = json.dumps(status.public_roster(members()))
        for canary in ("424242", "737373", CANARIES[2], "cap", "reasoning"):
            self.assertNotIn(canary, text)
        with tempfile.TemporaryDirectory() as d:
            status.StatusWriter(d).maybe_write(members(), 0)
            published = (Path(d) / "roster.json").read_text()
            for canary in ("424242", "737373", CANARIES[2]):
                self.assertNotIn(canary, published)


if __name__ == "__main__":
    unittest.main()
