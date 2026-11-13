"""r5-predict, the arena side: rules integer-16, one level per prediction, rewards by rarity, the record, leaderboards."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parents[1]), str(HERE)]
import predict  # noqa: E402
import replay  # noqa: E402
import server  # noqa: E402
import sim  # noqa: E402
import test_server  # noqa: E402  (its context, binding and room double)

RULES_DIR = HERE / "rules"
LAB = (4010, 3470, 1570, 640, 310)
ONE_LEVEL = {1: "one", 2: "two", 3: "three", 4: "four_plus"}


def spread(level=None, legacy=None):
    if legacy is not None:
        return dict(zip(predict.BINS, legacy))
    return {b: (10000 if b == ONE_LEVEL[level] else 0) for b in predict.BINS}


class Table(unittest.TestCase):
    def test_integer_16_is_15_plus_the_predict_block_and_old_tables_keep_their_hashes(self):
        fifteen = json.loads((RULES_DIR / "integer-15.json").read_bytes())
        sixteen = json.loads((RULES_DIR / "integer-16.json").read_bytes())
        self.assertEqual(sim.digest(sixteen), "852a82695da097598170e8dd4ab514a82010e68d483e544d434d9ea8e199d20e")
        self.assertEqual({k: sixteen.get(k) for k in set(sixteen) | set(fifteen) if sixteen.get(k) != fifteen.get(k)},
                         {"version": "integer-16",
                          "predict": {"levels": [1, 2, 3, 4], "margin_bps": 1000, "cap_bps": 200000,
                                      "amount_yocto": "10000000000000000000000", "window": 2000, "min_lives": 200}})
        for name, digest in (("integer-11.json", "73e9ca29a956"), ("integer-14.json", "3975d414b4c3"),
                             ("integer-15.json", "0bcbd83d92da")):
            table = json.loads((RULES_DIR / name).read_bytes())
            self.assertTrue(sim.digest(table).startswith(digest), name)
            self.assertIsNone(predict.block(table))
        self.assertEqual(sim.digest(replay.load_rules(sim.digest(sixteen))), sim.digest(sixteen))

    def test_a_bad_predict_block_is_refused(self):
        good = dict(sim.DEFAULT_RULES["predict"])
        for change in ({"levels": [0, 1, 2, 3]}, {"margin_bps": 10000}, {"cap_bps": 9999}, {"amount_yocto": 10 ** 22},
                       {"amount_yocto": "0"}, {"window": 0}, {"min_lives": 2001}, {"extra": 1}):
            with self.subTest(change=change):
                with self.assertRaises(ValueError):
                    sim._validate_predict({**good, **change})
        sim._validate_predict(good)


class Levels(unittest.TestCase):
    rules = sim.DEFAULT_RULES

    def test_one_bin_reads_as_its_level_and_anything_else_is_not_counted(self):
        for level in (1, 2, 3, 4):
            self.assertEqual(predict.read_level(self.rules, spread(level), 0), (level, None))
        for bad, zero in ((spread(legacy=(4000, 3000, 2000, 1000)), 0),        # snap.py and the guide's default
                          (spread(2), 1),                                      # a zero chance besides
                          (spread(legacy=(5000, 5000, 0, 0)), 0),
                          ({"one": 10000, "two": 0, "three": 0}, 0)):           # a bin missing
            with self.subTest(bad=bad, zero=zero):
                self.assertEqual(predict.read_level(self.rules, bad, zero), (None, predict.NOT_COUNTED))
        self.assertEqual(predict.read_level(self.rules, None, None), (None, None))
        fifteen = json.loads((RULES_DIR / "integer-15.json").read_bytes())
        self.assertEqual(predict.read_level(fifteen, spread(2), 0), (None, None))     # old tables: the old rule

    def test_multipliers_on_the_lab_table_match_the_spec(self):
        p = self.rules["predict"]
        self.assertEqual([predict.at_least_bps(LAB, l) for l in (1, 2, 3, 4)], [5990, 2520, 950, 310])
        self.assertEqual([predict.multiplier_bps(p, LAB, l) for l in (1, 2, 3, 4)], [15025, 35714, 94736, 200000])
        self.assertEqual(predict.multiplier_bps(p, (10000, 0, 0, 0, 0), 4), 200000)      # never reached: the cap
        right = predict.outcome(self.rules, 2, 3, LAB)
        self.assertEqual(right, {"result": "correct", "multiplier_bps": 35714, "reward_points": 357})
        self.assertEqual(predict.outcome(self.rules, 2, 2, LAB)["result"], "correct")    # 2 = 2 or more
        self.assertEqual(predict.outcome(self.rules, 3, 2, LAB),
                         {"result": "failure", "multiplier_bps": 94736, "reward_points": 0})
        self.assertEqual(predict.outcome(self.rules, None, 5, LAB)["result"], "none")
        cent = 10 ** 22
        self.assertEqual(predict.returned_yocto(cent, "correct", 35714), 35714 * 10 ** 18)
        self.assertEqual(predict.returned_yocto(cent, "failure", 35714), 0)


class Leaderboards(unittest.TestCase):
    def row(self, persona, kos, level=None, day="2026-11-12", house=False, life=None):
        rules = sim.DEFAULT_RULES
        ns = {"2026-11-12": 1794441600 * 10 ** 9, "2026-11-11": 1794355200 * 10 ** 9}[day]
        self.n = getattr(self, "n", 0) + 1
        return predict.seal_row(life_id=life or f"{persona}:life:{self.n}", persona=persona, house=house, rules=rules,
                                level=level, note=None, kos=kos, base_bps=LAB, sealed_ns=ns)

    def test_the_seal_row_carries_the_public_fields_only(self):
        r = self.row("vitrenchik", 3, level=2, house=True)
        self.assertEqual(set(r), {"kind", "run", "life", "persona", "name", "house", "rules", "level", "note", "kos",
                                  "result", "multiplier_bps", "reward_points", "base_rate_bps", "day", "at_ns"})
        self.assertEqual((r["rules"], r["level"], r["kos"], r["result"], r["multiplier_bps"], r["reward_points"],
                          r["day"]), (sim.DEFAULT_RULES["version"], 2, 3, "correct", 35714, 357, "2026-11-12"))

    def test_most_correct_ranks_by_count_then_name_and_most_kos_by_kos(self):
        rows = ([self.row("timid", 1, level=1) for _ in range(6)]       # six correct 1+: 6 x 150 = 900 points
                + [self.row("bold", 3, level=3)]                         # one correct 3+: 947 points
                + [self.row("bold", 0, level=4)]                         # a failure: no points
                + [self.row("twin-b", 2, level=2), self.row("twin-a", 2, level=2)]    # 357 each, one correct
                + [self.row("pair", 1, level=1), self.row("pair", 1, level=1), self.row("pair", 5, level=None)]
                + [self.row("yesterday", 9, level=4, day="2026-11-11")]
                + [self.row("quiet", 0, level=2)])
        b = predict.leaderboards(rows, "2026-11-12")
        self.assertEqual([(e["persona"], e["reward_points"], e["correct"]) for e in b["most_correct"]],
                         [("timid", 900, 6), ("pair", 300, 2), ("bold", 947, 1), ("twin-a", 357, 1), ("twin-b", 357, 1)])
        self.assertEqual([(e["persona"], e["kos"], e["lives"]) for e in b["most_kos"]],
                         [("pair", 7, 3), ("timid", 6, 6), ("bold", 3, 2), ("twin-a", 2, 1), ("twin-b", 2, 1)])
        self.assertNotIn("yesterday", json.dumps(b))
        self.assertNotIn("quiet", [e["persona"] for e in b["most_correct"]])
        # equal points (300 each): the larger count of correct predictions first
        one_big = dict(self.row("one-big", 2, level=2), reward_points=300)
        b = predict.leaderboards([one_big, self.row("two-small", 1, level=1), self.row("two-small", 1, level=1)],
                                 "2026-11-12")
        self.assertEqual([(e["persona"], e["correct"]) for e in b["most_correct"]], [("two-small", 2), ("one-big", 1)])

    def test_the_sign_boards_split_players_from_house_and_count_kos_over_the_last_hour(self):
        now = 1794441600 * 10 ** 9 + 7200 * 10 ** 9                   # 02:00 UTC on 2026-11-12

        def at(row, seconds_ago):
            return dict(row, at_ns=str(now - seconds_ago * 10 ** 9))
        rows = [at(self.row("p-old", 5, level=1), 3600),                  # exactly an hour ago: outside
                at(self.row("p-new", 2, level=2), 3599),
                at(self.row("p-new", 1, level=1), 60),
                at(self.row("h-one", 4, level=None, house=True), 30),
                at(self.row("h-two", 1, level=1, house=True), 10)]
        b = predict.leaderboards(rows, "2026-11-12", now_ns=now)["boards"]
        self.assertEqual(b["hour_from_ns"], str(now - 3600 * 10 ** 9))
        self.assertEqual([(e["persona"], e["kos"]) for e in b["most_kos_hour"]["players"]], [("p-new", 3)])
        self.assertEqual([(e["persona"], e["kos"]) for e in b["most_kos_hour"]["house"]], [("h-one", 4), ("h-two", 1)])
        self.assertEqual([(e["persona"], e["reward_points"], e["correct"]) for e in b["most_correct_day"]["players"]],
                         [("p-new", 507, 2), ("p-old", 150, 1)])               # the whole UTC day, not the hour
        self.assertEqual([e["persona"] for e in b["most_correct_day"]["house"]], ["h-two"])
        self.assertNotIn("most_kos_hour", predict.leaderboards(rows, "2026-11-12")["boards"])

    def test_the_record_keeps_one_row_of_each_kind_per_life_across_restarts(self):
        with tempfile.TemporaryDirectory() as d:
            rec = predict.Record(Path(d) / "record.jsonl")
            r = self.row("a", 2, level=2, life="a:life:1")
            self.assertTrue(rec.add(r))
            self.assertFalse(rec.add(dict(r, kos=9)))                        # a re-seal never rewrites a life
            self.assertTrue(rec.settled("local", "a:life:1", "a", 10 ** 22, 35714 * 10 ** 18, "TX"))
            self.assertFalse(rec.settled("local", "a:life:1", "a", 10 ** 22, 0, "TX2"))
            self.assertTrue(rec.add(dict(r, run="round-2")))                 # the same life id in another arena
            again = predict.Record(Path(d) / "record.jsonl")
            self.assertEqual([x["kind"] for x in again.rows], ["life", "settled", "life"])
            self.assertEqual(again.life("local", "a:life:1")["kos"], 2)
            self.assertEqual(again.rows[1], {"kind": "settled", "run": "local", "life": "a:life:1", "persona": "a",
                                             "amount_yocto": str(10 ** 22), "returned_yocto": str(35714 * 10 ** 18),
                                             "batch_tx": "TX"})


class ArenaRows(unittest.TestCase):
    """A real arena: three players lock a level, a legacy spread and no prediction; their lives end in the segment."""

    def test_each_completed_life_adds_its_seal_row_with_its_level_or_why_it_is_not_counted(self):
        with tempfile.TemporaryDirectory() as d:
            fx = test_server.Composition()
            fx.tmp = type("T", (), {"name": d})()
            arena = fx.arena(pick_resolver=lambda b, p: sim.rules_dict(sim.DEFAULT_RULES["default_loadout"]),
                             server_time_ms=lambda: 1794441600000)
            picks = {"lvl": (spread(2), 0), "old": (spread(legacy=(4000, 3000, 2000, 1000)), 0), "none": None,
                     "won": (spread(1), 0)}
            bindings = {}
            for name, pick in picks.items():
                b = bindings[name] = test_server.binding(name)
                life = arena.bridge.reserve_life(b)["life_id"]
                payload = None if pick is None else {"payload": {"loadout": {"menu_row": None, "bag_serials": []},
                                                                 "spread_bps": pick[0], "zero_bps": pick[1], "moves": [],
                                                                 "lock": False, "stake": None}}
                lock = arena.bridge.lock_prediction(b, life, payload)
                arena.bridge.activate(b, life, lock["lock_ref"])
            arena.advance(4)
            arena.sim.state["fighters"]["won"]["life_kos"] = 2           # two KOs this life (a test shortcut)
            for name in picks:                                             # each life ends by leaving
                self.assertEqual(arena.room.act(bindings[name], {"leave": True})["state"], "accepted")
            arena.advance(1200 - arena.sim.state["tick"] % 1200)
            rows = {r["persona"]: r for r in arena.record.rows}
            self.assertEqual(set(rows), set(picks))
            self.assertEqual((rows["lvl"]["level"], rows["lvl"]["result"], rows["lvl"]["multiplier_bps"]), (2, "failure", 35714))
            self.assertEqual((rows["won"]["level"], rows["won"]["kos"], rows["won"]["result"], rows["won"]["reward_points"]),
                             (1, 2, "correct", 150))
            self.assertEqual((rows["old"]["level"], rows["old"]["note"], rows["old"]["result"]),
                             (None, predict.NOT_COUNTED, "none"))
            self.assertEqual((rows["none"]["level"], rows["none"]["note"], rows["none"]["result"]), (None, None, "none"))
            self.assertEqual({r["base_rate_bps"] and tuple(r["base_rate_bps"]) for r in rows.values()} - {None}, {LAB})
            self.assertEqual(set(arena.sealed_rows), {r["life"] for r in rows.values()})
            self.assertEqual({r["run"] for r in rows.values()}, {arena.record_run})
            day = arena.record.leaderboards("2026-11-12")
            self.assertEqual([e["persona"] for e in day["most_correct"]], ["won"])



class HouseFlag(unittest.TestCase):
    """seal-house-flag (found on board 2): a house trenchie whose life ends and who swims home before the seal is
    no longer a member or a fighter at the seal; its row must still say house, and a player's must not."""

    def test_every_house_life_seals_house_true_even_after_it_swims_home(self):
        with tempfile.TemporaryDirectory() as d:
            fx = test_server.Composition()
            fx.tmp = type("T", (), {"name": d})()
            arena = fx.arena(server_time_ms=lambda: 1794441600000)
            house = sorted(sim.DEFAULT_RULES["house"])
            self.assertEqual(len(house), 14)
            waves = [house[i:i + 5] for i in range(0, 14, 5)]
            waves[0] = waves[0] + ["pip"]                               # one player, in the first wave
            for wave in waves:                                          # the ring holds 6 at a time
                people = [test_server.binding(n, house=n != "pip") for n in wave]
                for b in people:
                    life = arena.bridge.reserve_life(b)
                    lock = arena.bridge.lock_prediction(b, life["life_id"], None)
                    arena.bridge.activate(b, life["life_id"], lock["lock_ref"])
                arena.advance(4)
                for b in people:                                        # every life ends by leaving
                    self.assertEqual(arena.room.act(b, {"leave": True})["state"], "accepted")
                for _ in range(40):                                     # ...and they swim home and are retired
                    arena.advance(20)
                    if not any(b["nft_token_id"] in arena.members for b in people):
                        break
            arena.advance(1200 - arena.sim.state["tick"] % 1200)       # the seal comes after they are all gone
            rows = {r["persona"]: r for r in arena.record.rows}
            self.assertEqual(set(rows), set(house) | {"pip"})           # all 14 house lives and the player's
            self.assertFalse(set(rows) & (set(arena.members) | set(arena.sim.state["fighters"])))   # all gone first
            self.assertEqual({n: r["house"] for n, r in rows.items()}, {n: n != "pip" for n in rows})


class Served(unittest.TestCase):
    """The local and hosted arena host serves the record and the two leaderboards to the page."""

    def test_the_host_serves_the_record_and_todays_leaderboards(self):
        import snap_local  # noqa: E402  (near/arena)
        with tempfile.TemporaryDirectory() as d:
            dev = snap_local.DevRoom(0, d)
            arena = dev.round.arena
            day = predict.utc_day(arena.server_time_ms() * 1_000_000)
            ns = arena.server_time_ms() * 1_000_000
            for life, persona, kos, level in (("x:life:1", "x", 3, 2), ("y:life:1", "y", 1, 1), ("y:life:2", "y", 0, 3)):
                arena.record.add(predict.seal_row(life_id=life, persona=persona, house=False, rules=sim.DEFAULT_RULES,
                                                  level=level, note=None, kos=kos, base_bps=LAB, sealed_ns=ns))
            status, boards = dev.route("GET", "/house/leaderboards.json", b"", "127.0.0.1")
            self.assertEqual(status, 200)
            self.assertEqual(boards["day"], day)
            self.assertEqual([e["persona"] for e in boards["boards"]["most_kos_hour"]["players"]], ["x", "y"])
            self.assertEqual(boards["boards"]["most_kos_hour"]["house"], [])
            self.assertEqual([(e["persona"], e["kos"]) for e in boards["most_kos"]], [("x", 3), ("y", 1)])
            self.assertEqual([(e["persona"], e["reward_points"], e["correct"]) for e in boards["most_correct"]],
                             [("x", 357, 1), ("y", 150, 1)])
            status, (body, log_hash) = dev.route("GET", "/house/record.jsonl", b"", "127.0.0.1")
            self.assertEqual((status, log_hash), (200, None))
            self.assertEqual([json.loads(l)["life"] for l in body.decode().splitlines()], ["x:life:1", "y:life:1", "y:life:2"])
            self.assertEqual(dev.route("GET", "/house/leaderboards.json?day=2026-11-11", b"", "127.0.0.1")[1]["most_kos"], [])
            self.assertEqual(dev.route("GET", "/house/leaderboards.json?day=yesterday", b"", "127.0.0.1")[0], 400)



class OneRecordPerHost(unittest.TestCase):
    """The record and the boards survive a round restart and a host start (one file per state dir)."""

    def lives(self, dev, days_ago, *names):
        """End one life per name in the host's current round, sealed `days_ago` days back, through its real arena's
        seal rows (every arena's life ids restart at :0)."""
        arena = dev.round.arena
        clock = arena.server_time_ms
        arena.server_time_ms = lambda: clock() - days_ago * 86_400_000
        try:
            arena._seal_rows([{"nft_token_id": n, "life_id": f"{n}:life:0", "ko_count": "2"} for n in names])
        finally:
            arena.server_time_ms = clock

    def test_a_round_restart_and_a_host_start_keep_yesterdays_and_todays_rows(self):
        import snap_local  # noqa: E402  (near/arena)
        with tempfile.TemporaryDirectory() as state:
            first = snap_local.DevRoom(0, str(Path(state) / "run-1"), state_dir=state)
            self.lives(first, 1, "old")                                   # yesterday, round 1
            self.lives(first, 0, "early")                                 # today, round 1
            run_one = first.round.arena.record_run
            first.round = first._new_round()                              # a round restart: a new arena, life ids from :0
            self.assertIs(first.round.arena.record, first.record)
            self.lives(first, 0, "early", "mid")                          # "early:life:0" again, in round 2
            second = snap_local.DevRoom(0, str(Path(state) / "run-2"), state_dir=state)   # a host start
            self.lives(second, 0, "late")
            rows = [r for r in second.record.rows if r["kind"] == "life"]
            today_day = predict.utc_day(second.round.arena.server_time_ms() * 1_000_000)
            yday = predict.utc_day((second.round.arena.server_time_ms() - 86_400_000) * 1_000_000)
            self.assertEqual(sorted((r["persona"], r["day"]) for r in rows),
                             sorted([("old", yday), ("early", today_day), ("early", today_day), ("mid", today_day),
                                     ("late", today_day)]))
            self.assertEqual(len({r["run"] for r in rows}), 3)
            self.assertIn(run_one, {r["run"] for r in rows})
            today = second.route("GET", "/house/leaderboards.json", b"", "127.0.0.1")[1]
            self.assertEqual({e["persona"]: e["kos"] for e in today["most_kos"]}, {"early": 4, "mid": 2, "late": 2})
            self.assertEqual({e["persona"] for e in today["boards"]["most_kos_hour"]["players"]}, {"early", "mid", "late"})
            yesterday = second.route("GET", f"/house/leaderboards.json?day={yday}", b"", "127.0.0.1")[1]
            self.assertEqual([e["persona"] for e in yesterday["most_kos"]], ["old"])
            body = second.route("GET", "/house/record.jsonl", b"", "127.0.0.1")[1][0]
            self.assertEqual(len(body.decode().splitlines()), 5)


if __name__ == "__main__":
    unittest.main()
