"""r5-predict, the chain side: level lives settle by their multiplier, failures stay in the reward fund, old batches
resolve byte for byte as before, and rarity comes from house lives only."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "near" / "arena")]

from near.chain import resolver, test_chain  # noqa: E402  (test_chain's Rig: the fake testnet, real sender and writer)
import predict  # noqa: E402  (near/arena)

C = 10 ** 22                       # 0.01 NEAR
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "resolve-legacy-golden.json"


def level_life(account, life_id, level, kos, multiplier, result=None, at=100):
    return {"account": account, "life_id": life_id, "kos": kos, "bins": None, "level": level,
            "multiplier_bps": multiplier, "locked_after_ns": at * 10 ** 9,
            "result": result or ("none" if level is None else ("correct" if kos >= level else "failure"))}


def funded(*accounts, amount=C):
    return {a: amount for a in accounts}, {a: [{"amount": str(amount), "at": "1000"}] for a in accounts}


class Resolve(unittest.TestCase):
    def test_an_old_rules_batch_resolves_to_the_bytes_it_did_before(self):
        f = json.loads(GOLDEN.read_text())
        out = resolver.compute({k: int(v) for k, v in f["open_stakes"].items()}, f["lives"], int(f["pot_before"]),
                               tuple(f["base_bps"]), parts=f["parts"])
        self.assertEqual(json.dumps(out, sort_keys=True), json.dumps(f["golden"], sort_keys=True))

    def test_a_correct_level_pays_its_multiplier_and_a_failure_stays_in_the_fund(self):
        stakes, parts = funded("right", "wrong", "legacy")
        stakes["two"], parts["two"] = 2 * C, [{"amount": str(2 * C), "at": "1000"}]
        lives = [level_life("right", "r:1", 2, 3, 35714),                 # 2+ with 3 KOs: correct
                 level_life("wrong", "w:1", 3, 2, 94736),                 # 3+ with 2 KOs: failure
                 level_life("legacy", "l:1", None, 4, None),              # a legacy spread: not counted, never drawn
                 level_life("two", "t:1", 1, 1, 15025), level_life("two", "t:2", 4, 0, 200000, at=200)]
        seed = 50 * C                                                     # the reward fund's 0.5 testnet NEAR
        out = resolver.compute(stakes, lives, seed, (4010, 3470, 1570, 640, 310), parts=parts)
        net = {r["account_id"]: int(r["net"]) for r in out["results"]}
        self.assertEqual(net, {"right": 35714 * C // 10_000 - C, "wrong": -C, "legacy": 0,
                               "two": 15025 * C // 10_000 - 2 * C})
        self.assertEqual(int(out["pot_delta"]), -sum(net.values()))       # no recycle: the fund keeps the rest
        self.assertEqual(int(out["pot_after"]), seed - sum(net.values()))
        draws = {d["life_id"]: d for d in out["detail"] if "life_id" in d}
        self.assertNotIn("l:1", draws)                                    # nothing drawn for the not-counted life
        self.assertEqual(draws["r:1"]["paid"], str(35714 * C // 10_000))
        resolver.check(stakes, out, seed)

    def test_a_legacy_spread_with_point_zero_one_open_nets_zero(self):
        stakes, parts = funded("legacy")
        out = resolver.compute(stakes, [level_life("legacy", "l:1", None, 3, None)], 0, (4010, 3470, 1570, 640, 310),
                               parts=parts)
        self.assertEqual(out["results"], [{"account_id": "legacy", "net": "0"}])
        self.assertEqual(out["pot_delta"], "0")

    def test_a_batch_with_any_level_life_has_no_recycle_step(self):
        stakes, parts = funded("old", "new")
        spread_life = {"account": "old", "life_id": "o:1", "kos": 0, "bins": [0, 4000, 3000, 2000, 1000],
                       "locked_after_ns": 100 * 10 ** 9}
        winner = {"account": "new", "life_id": "n:1", "kos": 1, "bins": [0, 10000, 0, 0, 0], "locked_after_ns": 100 * 10 ** 9}
        legacy_only = resolver.compute(stakes, [spread_life, winner], 0, (4010, 3470, 1570, 640, 310), parts=parts)
        mixed = resolver.compute(stakes, [spread_life, level_life("new", "n:1", 1, 1, 15025)], 0,
                                 (4010, 3470, 1570, 640, 310), parts=parts)
        net = {r["account_id"]: int(r["net"]) for r in mixed["results"]}
        self.assertEqual(net, {"old": -C, "new": 15025 * C // 10_000 - C})
        self.assertEqual(int(mixed["pot_after"]), C - (15025 * C // 10_000 - C))     # the rest stays in the fund
        recycled = {r["account_id"]: int(r["net"]) for r in legacy_only["results"]}
        self.assertEqual(sum(recycled.values()) + int(legacy_only["pot_delta"]), 0)
        self.assertEqual(int(legacy_only["pot_after"]), 0)                # the old rule recycles the whole fund

    def test_the_base_rate_waits_for_two_hundred_lives(self):
        self.assertEqual(resolver.next_base_rate([3] * 199, min_lives=200), list(resolver.quote.PUBLISHED_BASE_BPS))
        self.assertNotEqual(resolver.next_base_rate([3] * 200, min_lives=200), list(resolver.quote.PUBLISHED_BASE_BPS))
        self.assertEqual(resolver.next_base_rate([3]), resolver.next_base_rate([3], min_lives=1))   # old default kept


class Writer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="predict-chain-")
        self.original = test_chain.snap_local.server.Arena

    def tearDown(self):
        test_chain.snap_local.server.Arena = self.original

    def sealed_with(self, house_kos, player_kos):
        """A real segment from the fake chain, its seal event given these completed lives before the writer applies it."""
        rig = test_chain.Rig(self.tmp + f"/{len(house_kos)}-{len(player_kos)}", batch_segments=50, commit_size=5,
                             lookahead=2)
        rig.arena()
        rig.run_segments(1)
        [e] = [x for x in rig.writer.inbox if x["kind"] == "seal"]
        lives, rows = [], {}
        for n, (house, kos) in enumerate([(True, k) for k in house_kos] + [(False, k) for k in player_kos]):
            life_id, token = f"life:{n}", ("vitrenchik" if house else f"farm{n}")
            lives.append({"life_id": life_id, "nft_token_id": token, "ko_count": str(kos)})
            rows[life_id] = {"house": house, "level": None, "result": "none", "multiplier_bps": None}
        e["sealed"]["lives"], e["rows"] = lives, rows
        rig.writer.process()
        return rig.writer

    def test_three_hundred_cheap_player_lives_each_way_leave_rarity_unchanged(self):
        house = [0, 1, 1, 2, 0, 3, 1, 0, 2, 4] * 25                      # 250 house lives
        clean = self.sealed_with(house, [])
        farmed = self.sealed_with(house, [0] * 300 + [4] * 300)
        self.assertEqual(clean.state["actuals"], house)
        self.assertEqual(farmed.state["actuals"], house)                  # player lives never enter it
        p = test_chain.snap_local.sim.DEFAULT_RULES["predict"]
        bins = resolver.next_base_rate(farmed.state["actuals"], min_lives=p["min_lives"])
        self.assertEqual(bins, resolver.next_base_rate(house, min_lives=200))
        self.assertEqual([predict.multiplier_bps(p, bins, l) for l in (1, 2, 3, 4)],
                         [predict.multiplier_bps(p, resolver.next_base_rate(house, min_lives=200), l) for l in (1, 2, 3, 4)])

    def test_a_level_is_rewarded_at_the_base_rate_published_before_its_lock(self):
        w = self.sealed_with([], [])
        self.assertEqual(w.base_rate_at(5000), list(resolver.quote.PUBLISHED_BASE_BPS))   # no resolve yet: the lab
        w.state["resolves"] = [{"base_rate": [2000, 2000, 2000, 2000, 2000], "previous": [1, 2, 3, 4, 9990], "at_ms": 1000},
                               {"base_rate": [5000, 2000, 1500, 1000, 500], "previous": [2000] * 5, "at_ms": 3000}]
        self.assertEqual(w.base_rate_at(999), [1, 2, 3, 4, 9990])         # before every kept resolve
        self.assertEqual(w.base_rate_at(2999), [2000] * 5)
        self.assertEqual(w.base_rate_at(3000), [5000, 2000, 1500, 1000, 500])

    def test_a_resolve_adds_a_settlement_row_only_for_lives_near_was_drawn_for(self):
        w = self.sealed_with([], [])
        with tempfile.TemporaryDirectory() as d:
            w.record = predict.Record(Path(d) / "record.jsonl")
            stakes, parts = funded("right", "legacy")
            lives = [dict(level_life("right", "r:1", 2, 3, 35714), token="right-token"),
                     dict(level_life("legacy", "l:1", None, 3, None), token="legacy-token")]
            plan = resolver.compute(stakes, lives, 50 * C, (4010, 3470, 1570, 640, 310), parts=parts)
            w._settlement_rows(plan, lives, "TXHASH")
            self.assertEqual(w.record.rows, [{"kind": "settled", "run": "local", "life": "r:1", "persona": "right-token",
                                              "amount_yocto": str(C), "returned_yocto": str(35714 * C // 10_000),
                                              "batch_tx": "TXHASH"}])


if __name__ == "__main__":
    unittest.main()
