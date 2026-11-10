"""F83 arena loot and A13 seeded hit variance: rates, mix and replay to the settle hash."""

from collections import Counter
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import replay
import server
import sim


def sealed_segment(rules, ticks=1200, seed=11):
    """A recorded 60 s segment of three joined fighters, built the way test_replay does."""
    game = sim.Sim(seed, rules)
    game.loot_spawns = 0
    real = game.drop_item
    def watch(row, x, y, owner, house, entry=None, origin="ko"):
        game.loot_spawns += origin == "arena"
        return real(row, x, y, owner, house, entry=entry, origin=origin)
    game.drop_item = watch
    start = game.export()
    rows = [sim.Input(0, "join", n, 0, {"angle": a, "house": h})
            for n, a, h in (("a", 0, False), ("b", 120, False), ("c", 240, False))]
    for row in rows:
        game.enqueue(row)
    game.run(ticks)
    record = {"initial_state": start, "rules_hash": game.rules_hash,
              "commands": [{"kind": "input", "value": r.record()} for r in rows]
                          + [{"kind": "advance", "value": ticks}],
              "predictions": [], "sealed": {"tick_count": str(ticks),
                                            "final_state_hash": game.state_hash()}}
    record["sealed"]["sealed_result_hash"] = server.engine_commitment(record)
    return record, game


class Variance(unittest.TestCase):
    def test_segment_with_variance_on_replays_to_its_hash_and_differs_from_off(self):
        rules = sim.rules_dict(sim.DEFAULT_RULES)
        self.assertGreater(rules["hitVarPct"], 0)
        record, game = sealed_segment(rules)
        hits = Counter()
        for event in game.state["events"]:
            hits[event["kind"]] += 1
        self.assertEqual(replay.replay_segment(record, sim.freeze(rules)).state_hash(),
                         record["sealed"]["final_state_hash"])
        damages = {e["damage"] for e in self._events(rules) if e["kind"] == "hit"}
        self.assertGreater(len(damages), 3)
        off = sim.rules_dict(rules)
        off["hitVarPct"] = 0
        _, quiet = sealed_segment(off)
        self.assertNotEqual(quiet.state_hash(), game.state_hash())

    def _events(self, rules):
        game = sim.Sim(11, rules)
        for n, a in (("a", 0), ("b", 120), ("c", 240)):
            game.enqueue(sim.Input(0, "join", n, 0, {"angle": a}))
        seen = []
        for _ in range(1200):
            game.step()
            seen.extend(game.state["events"])
        return seen


class Loot(unittest.TestCase):
    def test_spawn_rate_and_tier_mix_hold_and_a_loot_segment_replays(self):
        rules = sim.rules_dict(sim.DEFAULT_RULES)
        rules["combat_enabled"] = False
        game = sim.Sim(5, rules)
        tiers = []
        real = game.drop_item
        def watch(row, x, y, owner, house, entry=None, origin="ko"):
            if origin == "arena":
                tiers.append(game.rules["items"][row]["tier"])
            return real(row, x, y, owner, house, entry=entry, origin=origin)
        game.drop_item = watch
        ticks = 200 * 600
        game.run(ticks)
        self.assertEqual(len(tiers), (ticks - 1) // 200)
        rare = Counter(tiers)["rare"]
        self.assertEqual(set(tiers), {"common", "rare"})
        # 599 draws at 1 in 6: mean 100, sigma 9.1; the band is three sigma either side.
        self.assertTrue(72 <= rare <= 128, rare)
        record, played = sealed_segment(sim.rules_dict(sim.DEFAULT_RULES))
        self.assertEqual(played.loot_spawns, 5)
        self.assertEqual(replay.replay_segment(record).state_hash(), record["sealed"]["final_state_hash"])


if __name__ == "__main__":
    unittest.main()
