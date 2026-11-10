"""Composition cases use a local room double, never wallet or provider access."""

import asyncio
import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sim
import server


def context():
    return {"version": 1, "room_id": "arena", "deployment_id": "local",
            "authority_epoch": "1", "rules_hash": sim.digest(sim.DEFAULT_RULES),
            "audience": "local", "network_id": "mainnet",
            "contract_ids": {"nft": "nft.test", "arena": "arena.test"}}


def binding(name, generation=1, house=False):
    return {"context": context(), "grant_id": "grant:" + name + ":" + str(generation),
            "session_key_id": "key:" + name, "member_id": name,
            "nft_token_id": name, "persona_digest": "a" * 64,
            "account_id": "house.test" if house else name + ".test",
            "slot_id": name, "generation": str(generation)}


class RoomDouble:
    def __init__(self, bridge):
        self.bridge = bridge
        self.calls = []

    def maintain(self):
        pass

    def publish_snapshot(self):
        pass

    def life_boundary(self, grant_id):
        pass

    def act(self, b, payload, sequence=1, house=False):
        self.calls.append("house" if house else "guest")
        return self.bridge.apply(b, {"kind": "intent", "payload": {"fighter_id": b["nft_token_id"],
                                "focus": None, "avoid": None, "loot": "ignore", "sig": "hold",
                                "leave": False, "say": None, **payload},
                                "life_id": self.bridge.reserve_life(b)["life_id"], "sequence": str(sequence)})


class Composition(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def arena(self, **kwargs):
        def profile(b):
            house = b["account_id"] == "house.test"
            row = sim.DEFAULT_RULES["house"].get(b["nft_token_id"])
            return {"house": house, "public_name": b["nft_token_id"], "model": "local",
                    "style": row["style"] if house else "brawler",
                    "loadout": sim.rules_dict(row["kit"] if house else sim.DEFAULT_RULES["default_loadout"]),
                    "bag": {}, "player_spend": "PRIVATE-CANARY", "prompt": "PRIVATE-CANARY"}
        return server.Arena(context(), [101,202,303,404,505], data_dir=self.tmp.name,
                            room_factory=RoomDouble, profile_provider=profile,
                            identity_resolver=lambda p: {"play_status": "eligible"},
                            receipt_signer=lambda r: {**r, "key_id": "local", "signature": "local"},
                            admission_gate=lambda: True, life_guard=lambda b: True, **kwargs)

    def start(self, arena, b):
        life = arena.bridge.reserve_life(b)
        lock = arena.bridge.lock_prediction(b, life["life_id"], None)
        return arena.bridge.activate(b, life["life_id"], lock["lock_ref"])

    def test_room_is_bound_before_ingress_and_missing_dependencies_close_admission(self):
        arena = self.arena()
        self.assertIs(arena.room.bridge, arena.bridge)
        self.start(arena, binding("a"))
        arena.advance(4)
        receipt = arena.room.act(binding("a"), {"focus": "b"})
        self.assertEqual(receipt["state"], "accepted")
        self.assertEqual(receipt["applied_tick"], "6")
        closed = server.Arena(context(), [1,2,3,4,5], data_dir=self.tmp.name + "/closed")
        self.assertEqual(closed.bridge.reserve_life(binding("a"))["code"], "admission_closed")

    def test_sixteen_admitted_six_ring_and_fifo_bench(self):
        arena = self.arena()
        for i in range(16):
            name = "p" + str(i).zfill(2)
            b = binding(name)
            life = arena.bridge.reserve_life(b)
            self.assertIn("life_id", life)
            lock = arena.bridge.lock_prediction(b, life["life_id"], None)
            arena.bridge.activate(b, life["life_id"], lock["lock_ref"])
        self.assertEqual(arena.bridge.reserve_life(binding("overflow"))["code"], "room_full")
        arena.advance(8)
        self.assertEqual(len(arena.members), 16)
        self.assertEqual(len(arena.sim._live()), 6)
        self.assertEqual(sum(f["state"] == "bench" for f in arena.sim.state["fighters"].values()), 10)
        self.assertEqual(len(arena.bridge.observe(None)["fighters"]), 16)
        arena.sim.state["fighters"]["p00"]["state"] = "left"
        arena.advance(4)
        self.assertIn("p06", arena.sim._live())

    def test_house_roster_yields_at_life_boundary_and_keeps_two(self):
        arena = self.arena()
        names = sorted(sim.DEFAULT_RULES["house"])
        self.assertEqual(len(names), 14)
        for name in names[:6]:
            self.start(arena, binding(name, house=True))
        arena.advance(4)
        for i in range(4):
            self.start(arena, binding("p" + str(i)))
        arena.advance(3)
        self.assertEqual(sum(f["house"] for f in arena.sim.state["fighters"].values()
                             if f["state"] == "alive"), 6)
        for name in names[:4]:
            arena.sim.state["fighters"][name]["state"] = "bench"
            arena.sim.state["fighters"][name]["respawn_at"] = 0
        arena.advance(4)
        active_house = [m for m in arena.members.values() if m["profile"]["house"]]
        self.assertEqual(len(active_house), 2)
        self.assertEqual(len(arena.sim._live()), 6)

    def test_pre_life_lock_is_durable_immutable_and_survives_rotation(self):
        arena = self.arena()
        b = binding("a")
        life = arena.bridge.reserve_life(b)["life_id"]
        self.assertEqual(arena.bridge.activate(b, life, "wrong")["code"], "prediction_closed")
        locked = arena.bridge.lock_prediction(b, life, None)
        self.assertEqual(arena.bridge.lock_prediction(b, life, {"payload": {}})["code"], "request_conflict")
        newer = binding("a", 2)
        self.assertEqual(arena.bridge.reserve_life(newer)["life_id"], life)
        self.assertEqual(arena.bridge.lock_prediction(newer, life, None)["lock_ref"], locked["lock_ref"])
        self.assertEqual(arena.bridge.activate(b, life, locked["lock_ref"])["code"], "stale_slot")
        restored = self.arena(recover=True)
        self.assertEqual(restored.bridge.reserve_life(binding("a", 3))["life_id"], life)
        self.assertEqual(restored.bridge.lock_prediction(binding("a", 3), life, None)["lock_ref"], locked["lock_ref"])

    def test_segments_replay_across_seed_cut_and_carry_delayed_input(self):
        arena = self.arena()
        self.start(arena, binding("a"))
        arena.advance(1199)
        arena.room.act(binding("a"), {"loot": "nearest"})
        arena.advance(1)
        sealed = arena.bridge.seal("segment:0")
        self.assertTrue(sealed["completed"])
        self.assertEqual(sealed["tick_count"], "1200")
        self.assertEqual(sealed["seed"], "101")
        arena.advance(1200)
        other = arena.bridge.seal("segment:1")
        self.assertEqual(other["seed"], "202")
        for name in ("segment:0", "segment:1"):
            record = arena.store.segment(name)
            replayed = server.replay_segment(record, arena.sim.rules)
            self.assertEqual(replayed.state_hash(), record["sealed"]["final_state_hash"])
        self.assertEqual(arena.bridge.seal("segment:2")["code"], "result_pending")
        self.assertEqual(sealed, arena.bridge.seal("segment:0"))

    def test_snapshot_fanout_is_shared_bounded_and_public(self):
        arena = self.arena()
        self.start(arena, binding("a"))
        arena.advance(4)
        one, two = arena.subscribe(), arena.subscribe()
        self.assertIs(one.get_nowait(), two.get_nowait())
        before = arena.serialisations
        arena.advance(1)
        self.assertEqual(arena.serialisations, before + 1)
        self.assertIs(one.get_nowait(), two.get_nowait())
        arena.advance(20)
        self.assertLessEqual(one.qsize(), 2)
        self.assertGreater(arena.dropped_sends, 0)
        public = arena.snapshot_bytes + sim.canonical(arena.bridge.observe(None))
        self.assertNotIn(b"PRIVATE-CANARY", public)
        self.assertNotIn(b"PRIVATE-CANARY", arena.store.journal.read_bytes())
        self.assertEqual(arena.bridge.observe(None)["fighters"][0]["house_spend_microusd"], None)

    def test_absolute_deadlines_do_not_wait_for_house_model(self):
        from concurrent.futures import Future
        class PendingHouse:
            def __init__(self):
                self.model_result = Future()
                self.polls = 0
            def poll(self, room, tick, roster, count, view):
                self.polls += 1
        runtime = PendingHouse()
        arena = self.arena(house_runtime=runtime)
        clock = [0]
        waits = []
        def now():
            return clock[0]
        async def wait(seconds):
            waits.append(seconds)
            clock[0] += round(seconds * 1000000000)
            clock[0] += 3000000
        asyncio.run(arena.run(max_ticks=20, now_ns=now, sleep=wait))
        self.assertEqual(arena.sim.state["tick"], 20)
        self.assertEqual(arena.deadlines[0], 50000000)
        self.assertEqual(arena.deadlines[-1], 1000000000)
        self.assertEqual(arena.dropped_ticks, 0)
        self.assertEqual(len(waits), 20)
        self.assertEqual(runtime.polls, 20)
        self.assertFalse(runtime.model_result.done())

    def test_transport_loopback_and_same_room_for_house_and_guest(self):
        arena = self.arena()
        house = sorted(sim.DEFAULT_RULES["house"])[0]
        self.start(arena, binding(house, house=True))
        self.start(arena, binding("a"))
        arena.advance(4)
        arena.room.act(binding(house, house=True), {}, house=True)
        arena.room.act(binding("a"), {})
        self.assertEqual(arena.room.calls, ["house", "guest"])
        seen = {}
        async def transport(**kwargs):
            seen.update(kwargs)
        asyncio.run(arena.serve(transport, port=9000))
        self.assertEqual(seen["host"], "127.0.0.1")
        self.assertIsNone(seen["compression"])
        self.assertIs(seen["room"], arena.control)

    def test_ko_reserves_the_next_prediction_window_and_joins_queue_tail(self):
        arena = self.arena()
        for name in ("a", "b", "c", "d", "e", "f", "g"):
            self.start(arena, binding(name))
        arena.advance(4)
        old = arena.members["a"]["life_id"]
        arena.sim.state["fighters"]["a"]["shield_until"] = 0
        arena.sim.queue_hit("b", "a", 9999)
        arena.advance(1)
        reserved = arena.bridge.reserve_life(binding("a"))
        self.assertNotEqual(reserved["life_id"], old)
        self.assertTrue(arena.members["a"]["awaiting_life"])
        self.assertEqual(arena.bridge.lock_prediction(binding("a"), reserved["life_id"], None)["state"], "none")
        self.assertGreater(arena.members["a"]["queue_order"], arena.members["g"]["queue_order"])
        arena.advance(4)
        self.assertIn("g", arena.sim._live())

    def test_locked_loadout_is_the_logged_spawn_kit(self):
        chosen = sim.rules_dict(sim.DEFAULT_RULES["default_loadout"])
        chosen["weapon"] = "c-zap"
        arena = self.arena(pick_resolver=lambda b, p: chosen)
        b = binding("a")
        life = arena.bridge.reserve_life(b)["life_id"]
        pick = {"payload": {"loadout": {"menu_row": "c-zap", "bag_serials": []},
                            "spread_bps": {"one": 10000, "two": 0, "three": 0, "four_plus": 0},
                            "zero_bps": 0, "moves": [], "lock": False, "stake": None}}
        lock = arena.bridge.lock_prediction(b, life, pick)
        arena.bridge.activate(b, life, lock["lock_ref"])
        arena.advance(4)
        self.assertEqual(arena.sim.state["fighters"]["a"]["equipped"]["weapon"], "c-zap")
        self.assertTrue(any(c["kind"] == "input" and c["value"]["kind"] == "loadout"
                            for c in arena.commands))

    def test_leave_keeps_authoritative_bag_and_never_reuses_a_life_id(self):
        arena = self.arena()
        b = binding("a")
        self.start(arena, b)
        arena.advance(4)
        old = arena.members["a"]["life_id"]
        f = arena.sim.state["fighters"]["a"]
        f["bag"]["r-swing"] = arena.sim.inventory_entry("r-swing")
        f["state"] = "left"
        arena.advance(1)
        reserved = arena.bridge.reserve_life(binding("a", 2))
        self.assertNotEqual(reserved["life_id"], old)
        self.assertIn("r-swing", arena.members["a"]["profile"]["bag"])

    def test_journal_recovery_and_sealed_replay_share_the_live_frames(self):
        arena = self.arena()
        self.start(arena, binding("a"))
        arena.advance(1200)
        restored = self.arena(recover=True)
        self.assertEqual(restored.sim.state_hash(), arena.sim.state_hash())
        frames = asyncio.run(restored.replay("segment:0"))
        self.assertEqual(len(frames), 1200)
        self.assertEqual(frames[-1], arena.snapshot_bytes)
        self.assertIs(asyncio.run(restored.replay("segment:0")), frames)

    def test_public_tactical_fields_and_independent_zero_probability(self):
        arena = self.arena(pick_resolver=lambda b, p: sim.rules_dict(sim.DEFAULT_RULES["default_loadout"]))
        b = binding("a")
        life = arena.bridge.reserve_life(b)["life_id"]
        pick = {"payload": {"loadout": {"menu_row": "c-swing", "bag_serials": []},
                            "spread_bps": {"one": 10000, "two": 0, "three": 0, "four_plus": 0},
                            "zero_bps": 4000, "moves": [], "lock": False, "stake": None}}
        with self.subTest(field="zero_probability"):
            lock = arena.bridge.lock_prediction(b, life, pick)
            self.assertEqual(lock.get("state"), "prediction")
        with self.subTest(field="tactical_projection"):
            view = arena.bridge.observe(None)
            self.assertEqual(view["projection_version"], 1)
            self.assertEqual(set(view) - {"snapshot_hash"},
                             {"type", "context", "clock", "fighters", "items", "projection_version",
                              "projectiles", "telegraphs", "actions"})
            self.assertEqual(len(view["fighters"][0]["equipped"]), 4)

    def test_published_seed_extension_is_durable_before_rotation(self):
        arena = server.Arena(context(), [11], data_dir=self.tmp.name)
        arena.advance(1200)
        arena.add_published_seeds([22,33])
        arena.advance(20)
        self.assertEqual(arena.sim.state["seed"], 22)
        restored = server.Arena(context(), [11], data_dir=self.tmp.name, recover=True)
        self.assertEqual(restored.seeds, (11,22,33))
        self.assertEqual(restored.sim.state_hash(), arena.sim.state_hash())

    def test_seal_commits_checkpoint_and_effective_commands(self):
        arena = self.arena()
        arena.advance(1200)
        record = arena.store.segment("segment:0")
        record["commands"].append({"kind": "retire", "value": "absent"})
        with self.assertRaises(ValueError):
            server.replay_segment(record, arena.sim.rules)

    def test_prediction_deadline_is_absolute_and_retries_do_not_extend_it(self):
        arena = self.arena()
        first = arena.bridge.reserve_life(binding("a"))
        self.assertGreater(int(first["prediction_deadline"]), 1000000000000)
        arena.advance(10)
        again = arena.bridge.reserve_life(binding("a"))
        self.assertEqual(first["prediction_deadline"], again["prediction_deadline"])

    def test_segment_boundary_bounds_engine_deduplication_history(self):
        arena = self.arena()
        self.start(arena, binding("a"))
        arena.advance(1200)
        self.assertTrue(arena.sim.state["seen"])
        arena.advance(1)
        self.assertFalse(arena.sim.state["seen"])


if __name__ == "__main__":
    unittest.main()
