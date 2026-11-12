"""The spectator social frame's lives and names (the arena HUD's prediction circles and the wall sign's names).

Run: python3 -B near/arena/test_public_lives.py
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1]), str(HERE)]
import predict  # noqa: E402
import snap_local  # noqa: E402

LEVEL_2 = {"one": 0, "two": 10000, "three": 0, "four_plus": 0}
SPREAD = {"one": 4000, "two": 3000, "three": 2000, "four_plus": 1000}


class PublicLives(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        with mock.patch.object(snap_local.secrets, "randbelow", return_value=7):
            self.dev = snap_local.DevRoom(8765, tmp.name)
        self.arena = self.dev.round.arena
        for _ in range(3):
            self.arena.advance()
        self.alive = sorted(n for n, f in self.arena.sim.state["fighters"].items() if f["state"] == "alive")
        self.assertGreaterEqual(len(self.alive), 2, "the house is seated")

    def lock(self, name, spread, zero=0):
        life = self.arena.sim.state["fighters"][name]["life_id"]
        self.arena.locks[life] = {"public": {"pick": {"payload": {"spread_bps": dict(spread), "zero_bps": zero}}}, "at_ms": None}
        return life

    def test_each_fighters_life_carries_its_predicted_level_kos_and_reward_points(self) -> None:
        """A counted level, its KOs this life and the seal row's own reward points; a pick that does not count, and a
        life with no pick, carry no level (no circles)."""
        a, b = self.alive[:2]
        life_a = self.lock(a, LEVEL_2)
        self.arena.sim.state["fighters"][a]["life_kos"] = 1
        self.lock(b, SPREAD)
        lives = self.dev.public_lives()
        rules = self.arena.sim.rules
        points = predict.outcome(rules, 2, 2, list(predict.LAB_BASE_BPS))["reward_points"]
        self.assertGreater(points, 0)
        self.assertEqual(lives[a], {"life": life_a, "level": 2, "kos": 1, "points": points})
        self.assertEqual((lives[b]["level"], lives[b]["points"]), (None, 0))
        for name in self.alive[2:]:
            self.assertIsNone(lives[name]["level"])
        # the KOs follow the sim every frame; the level is read once per life
        self.arena.sim.state["fighters"][a]["life_kos"] = 2
        self.assertEqual(self.dev.public_lives()[a]["kos"], 2)

    def test_the_social_frame_carries_lives_and_the_names_of_registered_trenchies(self) -> None:
        self.lock(self.alive[0], LEVEL_2)
        self.dev.identities["dev-pebble"] = {"name": "Pebble Skipper"}
        raw = self.dev.social_frame()
        value = json.loads(raw[raw.index(b"{"):])
        self.assertEqual(value["type"], "spectator_social")
        self.assertEqual(value["lives"][self.alive[0]]["level"], 2)
        self.assertEqual(value["names"], {"dev-pebble": "Pebble Skipper"})


if __name__ == "__main__":
    unittest.main()
