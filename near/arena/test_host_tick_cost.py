"""The DEV/hosted arena host's per-tick cost: work its clock does every tick that nothing reads.

Run: python3 -B near/arena/test_host_tick_cost.py
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
import server  # noqa: E402
import snap_local  # noqa: E402
from room.policy import validate  # noqa: E402
import room.slots as room_slots  # noqa: E402
from room_host import HostSlotStore  # noqa: E402

TICKS = 120


def dev_room(directory: str, *, room_snapshots: bool | None = None) -> snap_local.DevRoom:
    """A DEV host (the deterministic house) with fixed seeds; room_snapshots overrides the host's choice."""
    with mock.patch.object(snap_local.secrets, "randbelow", return_value=7), \
         mock.patch.object(snap_local, "now_ms", return_value=1_900_000_000_000):
        if room_snapshots is None:
            return snap_local.DevRoom(8765, directory)
        made = server.Arena

        class Forced(made):
            def __init__(self, *a, **k):
                k["room_snapshots"] = room_snapshots
                super().__init__(*a, **k)

        with mock.patch.object(snap_local.server, "Arena", Forced):
            return snap_local.DevRoom(8765, directory)


class RoomSnapshotPush(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_room(self, name: str, **kw) -> tuple[snap_local.DevRoom, list]:
        dev = dev_room(str(Path(self.tmp.name) / name), **kw)
        service = dev.round.host.service
        pushes = []
        publish = service.publish_snapshot
        service.publish_snapshot = lambda: (pushes.append(dev.round.arena.sim.state["tick"]), publish())[1]
        for _ in range(TICKS):
            dev.round.arena.advance()
            dev.refresh_frames()
        return dev, pushes

    def test_the_host_pushes_no_room_snapshot_per_tick_and_observe_and_the_engine_are_unchanged(self) -> None:
        """The host's transport never drains pushed room snapshots, so its clock builds none (before: one full
        projection, canonical encoding and two schema validations every tick). An explicit observe still answers a
        validated snapshot of the current tick, and the engine (its journal, inputs, state and spectator bytes) is
        byte-for-byte the same as with the push on: nothing downstream of the engine read the pushed snapshots."""
        dev, pushes = self.run_room("off")
        self.assertEqual(pushes, [], f"{len(pushes)} room snapshots pushed in {TICKS} ticks")
        status, snapshot = dev.route("GET", "/room/observe", b"", "127.0.0.1")
        self.assertEqual(status, 200)
        validate("PublicSnapshot", snapshot)
        self.assertEqual(snapshot["clock"]["tick"], str(TICKS))
        self.assertTrue(snapshot["fighters"], "the house is seated in the observed snapshot")

        on, on_pushes = self.run_room("on", room_snapshots=True)
        self.assertEqual(len(on_pushes), TICKS)  # the control: forced on, it pushes every tick
        a, b = dev.round.arena, on.round.arena
        self.assertEqual(a.sim.state_hash(), b.sim.state_hash())
        self.assertEqual(server.sim.digest(a.commands), server.sim.digest(b.commands))
        self.assertEqual(server.sim.digest(a.input_events), server.sim.digest(b.input_events))
        self.assertEqual(a.snapshot_bytes, b.snapshot_bytes)
        self.assertEqual(dev.latest, on.latest)
        _, observed_on = on.route("GET", "/room/observe", b"", "127.0.0.1")
        self.assertEqual(snapshot, observed_on)


def unrandom(state: dict) -> dict:
    """The slot state without its random grant tokens (each store draws its own)."""
    for slot in state["slots"].values():
        slot["record"].pop("grant", None)
    return state


class SlotStateWrites(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.writes: list[str] = []
        atomic = room_slots._atomic

        def counted(path, value):
            self.writes.append(Path(path).name)
            return atomic(path, value)

        patch = mock.patch.object(room_slots, "_atomic", counted)
        patch.start()
        self.addCleanup(patch.stop)

    def test_an_idle_host_writes_the_slot_state_about_once_a_second_not_every_tick(self) -> None:
        """The clock calls the room's maintain (and so the slot store's expire) every tick; with nobody seated
        nothing can lapse. Before: a full rewrite of .slots-state.json with two fsyncs on every tick (120 here)."""
        dev = dev_room(self.tmp.name)
        self.writes.clear()
        for _ in range(TICKS):  # 120 ticks = 6 s of room time (the slot store's clock is the sim's)
            dev.round.arena.advance()
        state_writes = self.writes.count(".slots-state.json")
        self.assertLessEqual(state_writes, 1 + TICKS * 50 // 1000, f"{state_writes} state writes in {TICKS} ticks")

    def test_a_lapsed_lease_expires_on_the_same_call_as_the_plain_store(self) -> None:
        """Two reservations with different leases, stepped 50 ms at a time past both: after every expire() the
        host's store holds exactly the state the plain store holds, so each lapse lands on the same call."""
        now = [1_900_000_000_000]
        clock = lambda: now[0]  # noqa: E731
        stores = [cls(Path(self.tmp.name) / name, "room-1", 16, clock=clock, reservation_ms=2_000)
                  for cls, name in ((room_slots.SlotStore, "plain"), (HostSlotStore, "host"))]
        digest = "a" * 64
        for store in stores:
            store.reserve("m1", digest.replace("a", "1"))
        now[0] += 700
        for store in stores:
            store.reserve("m2", digest.replace("a", "2"))
        self.writes.clear()
        lapsed_at = {}
        for step in range(70):  # 3.5 s: both leases (2.0 s and 2.7 s) lapse inside the window
            now[0] += 50
            for store in stores:
                store.expire()
            plain, host = (unrandom(json.loads((Path(self.tmp.name) / n / ".slots-state.json").read_text()))
                           for n in ("plain", "host"))
            self.assertEqual(plain, host, f"step {step}")
            for slot_id, slot in host["slots"].items():
                if slot["record"]["state"] == "released":
                    lapsed_at.setdefault(slot_id, step)
        self.assertEqual(len(lapsed_at), 2, lapsed_at)
        host_writes = self.writes.count(".slots-state.json") - 70  # the plain store wrote once per step
        self.assertLessEqual(host_writes, 6, f"{host_writes} host state writes in 70 steps")


if __name__ == "__main__":
    unittest.main()
