"""Focused crash and input-order cases for reviewed engine boundaries."""

import unittest
from unittest.mock import patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_server as fixtures
import test_policy
import sim
import server


class Returned(unittest.TestCase):
    def fixture(self):
        case = fixtures.Composition()
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def test_release_cancels_a_delayed_spawn_and_survives_recovery(self):
        fixture = self.fixture()
        arena = fixture.arena()
        fixture.start(arena, fixtures.binding("a"))
        self.assertTrue(any(r["kind"] == "spawn" for r in arena.sim.state["inputs"]))
        self.assertTrue(arena.bridge.release(fixtures.binding("a"))["revoked"])
        arena.advance(20)
        self.assertNotIn("a", arena.sim.state["fighters"])
        self.assertTrue(arena.can_admit())
        recovered = fixture.arena(recover=True)
        self.assertEqual(recovered.sim.state_hash(), arena.sim.state_hash())
        recovered.advance(2)

    def test_any_failed_tick_closes_admission_before_propagating(self):
        arena = self.fixture().arena()
        with patch.object(arena.sim, "step", side_effect=ValueError("tick interrupted")):
            with self.assertRaisesRegex(ValueError, "tick interrupted"):
                arena.advance()
        self.assertFalse(arena.can_admit())
        with self.assertRaisesRegex(RuntimeError, "paused"):
            arena.advance()

    def test_crashes_on_both_sides_of_seal_publication_recover_before_opening(self):
        for after_write in (False, True):
            with self.subTest(after_write=after_write):
                fixture = self.fixture()
                arena = fixture.arena()
                original = arena.store.put_segment
                def interrupted(name, record):
                    if after_write:
                        original(name, record)
                    raise OSError("simulated publication interruption")
                with patch.object(arena.store, "put_segment", interrupted):
                    with self.assertRaises(OSError):
                        arena.advance(1200)
                self.assertFalse(arena.can_admit())
                expected = arena.sim.state_hash()
                recovered = fixture.arena(recover=True)
                sealed = recovered.bridge.seal("segment:0")
                self.assertEqual(sealed["final_state_hash"], expected)
                record = recovered.store.segment("segment:0")
                self.assertEqual(server.replay_segment(record).state_hash(), expected)
                recovered.advance()
                self.assertEqual(recovered.segment_id, "segment:1")
                self.assertEqual(recovered.bridge.seal("segment:0"), sealed)

    def boundary_request(self, action: str) -> tuple[fixtures.Composition, server.Arena, Path, bytes]:
        fixture = self.fixture()
        arena = fixture.arena()
        actor = fixtures.binding("a")
        fixture.start(arena, actor)
        arena.advance(1199)
        if action in ("lock", "activate"):
            waiting = fixtures.binding("waiting")
            life = arena.bridge.reserve_life(waiting)["life_id"]
            if action == "activate":
                lock = arena.bridge.lock_prediction(waiting, life, None)["lock_ref"]
        arena.advance()
        path = arena.store._segment_path("segment:0")
        completed = path.read_bytes()
        if action == "reserve":
            reply = arena.bridge.reserve_life(fixtures.binding("new"))
            self.assertIn("life_id", reply)
        elif action == "rotate":
            reply = arena.bridge.reserve_life(fixtures.binding("a", 2))
            self.assertEqual(reply["binding"]["generation"], "2")
        elif action == "release":
            self.assertTrue(arena.bridge.release(actor)["revoked"])
        elif action == "intent":
            reply = arena.bridge.apply(actor, {
                "kind": "intent", "life_id": arena.members["a"]["life_id"], "sequence": "1",
                "payload": {"fighter_id": "a", "focus": None, "avoid": None,
                            "loot": "nearest", "sig": "hold", "leave": False}})
            self.assertEqual(reply["state"], "accepted")
        elif action == "lock":
            self.assertIn("lock_ref", arena.bridge.lock_prediction(waiting, life, None))
        elif action == "activate":
            self.assertEqual(arena.bridge.activate(waiting, life, lock)["start_tick"], "1202")
        else:
            self.fail("unknown boundary request")
        return fixture, arena, path, completed

    def test_boundary_requests_recover_before_the_next_tick(self) -> None:
        for action in ("reserve", "rotate", "release", "intent", "lock", "activate"):
            with self.subTest(action=action):
                fixture, arena, path, completed = self.boundary_request(action)
                recovered = fixture.arena(recover=True)
                self.assertEqual(arena.segment_id, "segment:1")
                self.assertEqual(recovered.segment_id, arena.segment_id)
                self.assertEqual(recovered.sim.state_hash(), arena.sim.state_hash())
                self.assertEqual(recovered.members, arena.members)
                self.assertEqual(recovered.commands, arena.commands)
                self.assertEqual(recovered.input_events, arena.input_events)
                self.assertEqual(recovered.locks, arena.locks)
                self.assertEqual(path.read_bytes(), completed)
                # Continue only the recovered writer against this journal.
                recovered.advance(1200)
                self.assertTrue(recovered.can_admit())
                self.assertEqual(path.read_bytes(), completed)
                record = recovered.store.segment("segment:1")
                self.assertEqual(server.replay_segment(record).state_hash(), recovered.sim.state_hash())

    def test_boundary_requests_advance_without_rewriting_the_completed_seal(self) -> None:
        for action in ("reserve", "rotate", "release", "intent", "lock", "activate"):
            with self.subTest(action=action):
                fixture, arena, path, completed = self.boundary_request(action)
                arena.advance(arena.sim.rules["tick_hz"])
                self.assertTrue(arena.can_admit())
                self.assertEqual(arena.segment_id, "segment:1")
                self.assertEqual(path.read_bytes(), completed)
                recovered = fixture.arena(recover=True)
                self.assertEqual(recovered.sim.state_hash(), arena.sim.state_hash())
                self.assertEqual(recovered.members, arena.members)
                self.assertEqual(path.read_bytes(), completed)

    def test_boundary_open_failure_preserves_the_seal_and_refuses_the_request(self) -> None:
        for after_write in (False, True):
            with self.subTest(after_write=after_write):
                fixture = self.fixture()
                arena = fixture.arena()
                arena.advance(1200)
                path = arena.store._segment_path("segment:0")
                completed = path.read_bytes()
                append = arena.store.append
                def interrupted(kind: str, value: object) -> int:
                    if kind == "open":
                        if after_write:
                            append(kind, value)
                        raise OSError("segment opening interrupted")
                    return append(kind, value)
                with patch.object(arena.store, "append", interrupted):
                    with self.assertRaisesRegex(OSError, "segment opening interrupted"):
                        arena.bridge.reserve_life(fixtures.binding("new"))
                self.assertFalse(arena.can_admit())
                self.assertNotIn("new", arena.members)
                recovered = fixture.arena(recover=True)
                self.assertEqual(path.read_bytes(), completed)
                self.assertNotIn("new", recovered.members)
                self.assertIn("life_id", recovered.bridge.reserve_life(fixtures.binding("new")))
                recovered.advance(1200)
                self.assertEqual(path.read_bytes(), completed)
                record = recovered.store.segment("segment:1")
                self.assertEqual(server.replay_segment(record).state_hash(), recovered.sim.state_hash())

    def test_dodge_roll_checks_weapon_warning_geometry_and_expiry(self):
        for kind in ("beam", "lob"):
            g, a, b = test_policy.Knobs().game()
            b["equipped"]["weapon"] = "c-" + kind
            a.update(x=1000, y=0)
            b.update(x=0, y=0)
            g._fire_weapon(b, a, g._weapon(b), 6000)
            self.assertTrue(g._should_signature(a, "dodge_roll", b))
            a["y"] = 4000
            self.assertFalse(g._should_signature(a, "dodge_roll", b))
            a["y"] = 0
            g.state["tick"] = 100
            self.assertFalse(g._should_signature(a, "dodge_roll", b))


if __name__ == "__main__":
    unittest.main()
