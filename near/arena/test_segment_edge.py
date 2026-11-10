"""An input must never be journalled in a segment it does not apply in.

On a segment's last two ticks the room's bookkeeping happens at once and the engine effect (the enqueue and
its public row) is held and runs on the next segment's first tick. Only an intent, whose receipt names the
applied tick, is answered rate_limited and re-sent.
"""

from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))                  # the repo root, for `room`
import portable_records
import replay
import sim
import test_server as ts


def crossing(record):
    end = record["initial_state"]["tick"] + int(record["sealed"]["tick_count"])
    return [c["value"] for c in record["commands"] if c["kind"] == "input" and c["value"]["tick"] >= end]


def to_edge(arena, lead):
    """Advance to `lead` ticks before the segment's end (2 = relative tick 1198, 1 = 1199)."""
    arena.advance(1200 - lead - (arena.sim.state["tick"] - arena.segment_start))
    assert arena.at_edge() == (lead <= 2)


class Edge(unittest.TestCase):
    def setUp(self):
        self.comp = ts.Composition()
        self.comp.setUp()
        self.addCleanup(self.comp.doCleanups)
        self.arena = self.comp.arena()
        self.arena.add_published_seeds([9001, 9002, 9003, 9004])

    def kinds(self, record):
        return sorted((c["value"]["kind"], c["value"]["fighter_id"], c["value"]["tick"])
                      for c in record["commands"] if c["kind"] == "input")

    def test_a_join_on_either_edge_tick_is_accepted_held_and_runs_in_the_next_segment(self):
        arena = self.arena
        self.comp.start(arena, ts.binding("a"))
        for lead, name in ((2, "late2"), (1, "late1")):
            to_edge(arena, lead)
            reply = arena.bridge.reserve_life(ts.binding(name))
            self.assertIn("life_id", reply)                          # accepted, never an error
            self.assertIn(name, arena.members)
            self.assertNotIn(name, [v["fighter_id"] for v in
                                    (c["value"] for c in arena.commands if c["kind"] == "input")])
            arena.advance(lead + 3 if lead == 1 else 1)
        arena.advance(8)
        self.assertEqual(arena.segment_index, 1)
        zero = arena.store.segment("segment:0")
        self.assertEqual(crossing(zero), [])
        portable_records._project(zero)                              # refused (bad_message) before the hold
        first = [c for c in arena.commands if c["kind"] == "input" and c["value"]["kind"] == "join"]
        self.assertEqual(sorted(c["value"]["fighter_id"] for c in first), ["late1", "late2"])
        self.assertTrue(all(c["value"]["tick"] == 1202 for c in first))
        self.assertIn("late2", arena.sim.state["fighters"])
        self.assertEqual([e["kind"] for e in arena.input_events if e["fighter_id"] == "late2"], ["join"])

    def test_activation_and_loadout_on_the_edge_are_held_and_announce_the_real_start_tick(self):
        arena = self.arena
        to_edge(arena, 3)
        h = ts.binding("h1")
        life = arena.bridge.reserve_life(h)["life_id"]
        arena.advance(1)                                              # relative 1198: the edge
        self.assertTrue(arena.at_edge())
        pick = {"payload": {"loadout": {"menu_row": None, "bag_serials": []},
                            "spread_bps": {"one": 10000, "two": 0, "three": 0, "four_plus": 0},
                            "zero_bps": 0, "moves": [], "lock": False, "stake": None}}
        arena.pick_resolver = lambda b, p: sim.rules_dict(sim.DEFAULT_RULES["default_loadout"])
        lock = arena.bridge.lock_prediction(h, life, pick)
        self.assertEqual(lock["state"], "prediction")
        active = arena.bridge.activate(h, life, lock["lock_ref"])
        self.assertEqual(active["start_tick"], "1202")               # the first tick it can apply at
        arena.advance(8)
        spawn = [c["value"] for c in arena.commands if c["kind"] == "input" and c["value"]["kind"] == "spawn"]
        self.assertEqual([c["tick"] for c in spawn], [1202])
        self.assertEqual(arena.sim.state["fighters"]["h1"]["state"], "alive")
        self.assertEqual(crossing(arena.store.segment("segment:0")), [])

    def test_release_on_the_edge_revokes_at_once_and_leaves_in_the_next_segment(self):
        arena = self.arena
        a = ts.binding("a")
        self.comp.start(arena, a)
        to_edge(arena, 2)
        ack = arena.bridge.release(a)
        self.assertTrue(ack["revoked"])
        self.assertTrue(arena.members["a"]["released"])               # the room is told yes immediately
        self.assertEqual(crossing({"initial_state": arena.initial_state, "sealed": {"tick_count": "1200"},
                                   "commands": arena.commands}), [])
        arena.advance(6)
        record = arena.store.segment("segment:0")
        self.assertEqual(crossing(record), [])
        portable_records._project(record)
        leaves = [c["value"] for c in arena.commands if c["kind"] == "input" and c["value"]["kind"] == "leave"]
        self.assertEqual([c["tick"] for c in leaves], [1202])
        self.assertTrue(any(c["kind"] == "cancel_spawn" for c in arena.commands))
        self.assertEqual(sum(e["kind"] == "leave" for e in arena.input_events), 1)

    def test_release_on_either_edge_tick_always_succeeds_and_the_room_keeps_admitting(self):
        for lead in (2, 1):
            comp = ts.Composition()
            comp.setUp()
            self.addCleanup(comp.doCleanups)
            arena = comp.arena()
            arena.add_published_seeds([9001, 9002])
            a, b = ts.binding("a"), ts.binding("b")
            comp.start(arena, a)
            comp.start(arena, b)
            to_edge(arena, lead)
            self.assertTrue(arena.at_edge())
            for who in (a, b):                                         # twice: a repeat release is still fine
                ack = arena.bridge.release(who)
                self.assertNotIn("code", ack)
                self.assertTrue(ack["revoked"])
            self.assertFalse(arena.failed)
            self.assertTrue(arena.can_admit())
            self.assertIn("life_id", arena.bridge.reserve_life(ts.binding("newcomer")))   # still admitting, on the edge
            arena.advance(lead + 6)
            self.assertEqual(crossing(arena.store.segment("segment:0")), [])
            portable_records._project(arena.store.segment("segment:0"))
            self.assertTrue(all(n not in arena.sim.state["fighters"] or arena.sim.state["fighters"][n]["leave"]
                                for n in ("a", "b")))                  # the leave order is in the sim, swimming out
            leaves = sorted(c["value"]["fighter_id"] for c in arena.commands
                            if c["kind"] == "input" and c["value"]["kind"] == "leave")
            self.assertEqual(leaves, ["a", "b"])

    def test_an_intent_on_the_edge_is_held_with_rate_limited_and_the_resend_is_accepted(self):
        arena = self.arena
        a = ts.binding("a")
        self.comp.start(arena, a)
        to_edge(arena, 2)
        intent = {"kind": "intent", "life_id": arena.members["a"]["life_id"], "sequence": "1",
                  "payload": {"fighter_id": "a", "focus": None, "avoid": None, "loot": "ignore", "sig": "hold",
                              "leave": False, "say": None}}
        held = arena.bridge.apply(a, intent)
        self.assertEqual((held["code"], held["retry_after_ms"]), ("rate_limited", "100"))
        arena.advance(3)
        self.assertEqual(arena.bridge.apply(a, intent)["state"], "accepted")
        self.assertEqual(crossing(arena.store.segment("segment:0")), [])

    def test_a_held_effect_survives_a_crash_before_the_boundary_and_runs_once(self):
        arena = self.arena
        self.comp.start(arena, ts.binding("a"))
        to_edge(arena, 2)
        arena.bridge.reserve_life(ts.binding("late"))
        recovered = self.comp.arena(recover=True)
        self.assertEqual([e["op"] for e in recovered.deferred], ["join"])
        recovered.advance(6)
        joins = [c["value"] for c in recovered.commands if c["kind"] == "input" and c["value"]["kind"] == "join"]
        self.assertEqual([(c["fighter_id"], c["tick"]) for c in joins], [("late", 1202)])
        self.assertEqual(recovered.deferred, [])

    def test_three_segments_with_attempts_on_every_edge_tick_stay_readable_and_replay_to_their_hash(self):
        arena = self.arena
        self.comp.start(arena, ts.binding("a"))
        names = iter("pqrstuvwxy")
        for _ in range(3):
            for lead in (2, 1):
                to_edge(arena, lead)
                arena.bridge.reserve_life(ts.binding(next(names)))
            arena.advance(2)
        arena.advance(4)
        for i in range(3):
            record = arena.store.segment("segment:%d" % i)
            self.assertEqual(crossing(record), [], i)
            self.assertEqual(replay.replay_segment(record).state_hash(), record["sealed"]["final_state_hash"])
        portable_records._project(arena.store.segment("segment:0"))
        self.assertEqual(len(arena.members), 7)


if __name__ == "__main__":
    unittest.main()
