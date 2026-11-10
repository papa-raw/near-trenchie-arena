"""New replay witness cases over real archived engine/room integration data."""
from __future__ import annotations

import copy
import importlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parent)]
import replay
import test_room_host as fixture


def drive(case: fixture.CopiedRoom, ticks: int, clients: list, sequences: list[int]) -> None:
    """Advance trusted host time at20Hz; owners send ordinary10s heartbeats."""
    for _ in range(ticks):
        tick = case.arena.sim.state["tick"]
        if tick and tick % 200 == 0:
            for index, (grant, cid) in enumerate(clients):
                renew = case.control(grant, "RenewRequest", None, sequences[index])
                renew["payload"]["lease_until"] = str(case.now + 30_000)
                response = case.arena.control.frame(cid, case.policy.canonical_bytes(case.signed(renew)))
                if response.get("state") != "accepted":
                    raise AssertionError("fixture heartbeat refused: " + response.get("code", "unknown"))
                sequences[index] += 1
        case.now += 50
        case.arena.advance()


class EngineEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = importlib.import_module("engine_evidence")
        case = fixture.CopiedRoom()
        case.setUp()
        cls.addClassCleanup(case.doCleanups)
        clients = []
        for token in ("alice", "bob"):
            grant = case.join(token)
            cid, ready = case.authenticate(grant)
            case.predict(grant, cid, ready)
            clients.append((grant, cid))
        drive(case, 1200, clients, [2, 2])
        cls.archive = case.arena.store.segment("segment:0")

    def test_replay_derives_completed_lives_and_unsigned_forecasts(self) -> None:
        before = copy.deepcopy(self.archive)
        evidence = self.module.replay_evidence(self.archive)
        self.assertEqual(evidence["final_state_hash"], self.archive["sealed"]["final_state_hash"])
        self.assertTrue(evidence["lives"])
        self.assertEqual(evidence["lives"], self.archive["sealed"]["lives"])
        self.assertEqual(evidence["engine_commitment"], self.archive["sealed"]["sealed_result_hash"])
        self.assertTrue(any(value is not None for value in evidence["predictions"].values()))
        self.assertTrue(all(value is None or "signature" not in value for value in evidence["predictions"].values()))
        self.assertEqual(self.archive, before)

    def test_rehashed_forged_life_count_refuses(self) -> None:
        forged = copy.deepcopy(self.archive)
        forged["sealed"]["lives"][0]["ko_count"] = str(int(forged["sealed"]["lives"][0]["ko_count"]) + 1)
        forged["sealed"]["sealed_result_hash"] = replay.engine_commitment(forged)
        with self.assertRaisesRegex(ValueError, "completed life"):
            self.module.replay_evidence(forged)

    def test_rehashed_changed_forecast_refuses(self) -> None:
        forged = copy.deepcopy(self.archive)
        row = next(row for row in forged["predictions"] if row["pick"] is not None)
        row["pick"]["payload"]["zero_bps"] += 1
        forged["sealed"]["sealed_result_hash"] = replay.engine_commitment(forged)
        with self.assertRaisesRegex(ValueError, "prediction"):
            self.module.replay_evidence(forged)

    def test_cross_segment_life_evidence_uses_real_initial_state(self) -> None:
        case = fixture.CopiedRoom()
        case.setUp()
        self.addCleanup(case.doCleanups)
        grant = case.join()
        cid, ready = case.authenticate(grant)
        prediction = case.predict(grant, cid, ready)
        sequences = [2]
        drive(case, 1200, [(grant, cid)], sequences)
        first = case.arena.store.segment("segment:0")
        self.assertEqual(first["sealed"]["lives"], [])
        leave = case.control(grant, "IntentRequest", prediction["life_id"], sequences[0])
        leave["payload"].update(fighter_id="alice", focus=None, avoid=None, loot="ignore", sig="hold", leave=True, say=None)
        receipt = case.arena.control.frame(cid, case.policy.canonical_bytes(case.signed(leave)))
        self.assertEqual(receipt["state"], "accepted", receipt)
        sequences[0] += 1
        drive(case, 1200, [(grant, cid)], sequences)
        second = case.arena.store.segment("segment:1")
        evidence = self.module.replay_evidence(second)
        self.assertEqual(len(evidence["lives"]), 1)
        self.assertEqual(evidence["lives"][0]["life_id"], prediction["life_id"])
        self.assertEqual(evidence["lives"], second["sealed"]["lives"])
        self.assertNotIn("life_start", [row["kind"] for row in second["sealed"]["input_events"]])

    def test_rehashed_duplicate_metadata_must_match_replay_and_archive_material(self) -> None:
        original = copy.deepcopy(self.archive)
        valid = self.module.replay_evidence(self.archive)
        self.assertTrue(valid["lives"])
        contradictions = {
            "life_ids": ["contradictory-life"],
            "predictions_log_hash": "0" * 64,
            "rules_hash": "0" * 64,
            "inputs_hash": "0" * 64,
            "seed_hash": "0" * 64,
            "seed": str(int(self.archive["sealed"]["seed"]) + 1),
            "nft_token_ids": ["contradictory-token"],
            "segment_id": "segment:999",
        }
        for field, value in contradictions.items():
            forged = copy.deepcopy(self.archive)
            forged["sealed"][field] = value
            forged["sealed"]["sealed_result_hash"] = replay.engine_commitment(forged)
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "metadata"):
                    self.module.replay_evidence(forged)
        self.assertEqual(self.archive, original)
        self.assertEqual(self.module.replay_evidence(self.archive), valid)
        pending = fixture.CopiedRoom()
        pending.setUp()
        self.addCleanup(pending.doCleanups)
        drive(pending, 1199, [], [])
        self.assertEqual(pending.join("late")["state"], "accepted")
        drive(pending, 1, [], [])
        archive = pending.arena.store.segment("segment:0")
        self.assertEqual(archive["sealed"]["nft_token_ids"], ["late"])
        self.assertNotIn("late", pending.arena.sim.state["fighters"])
        self.assertEqual(self.module.replay_evidence(archive)["lives"], [])


if __name__ == "__main__":
    unittest.main()
