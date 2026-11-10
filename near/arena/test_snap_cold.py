"""One cold SNAP program, isolated owner state, real room and engine records."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parent)]
import test_room_host as fixture


class ColdHost:
    """Trusted fixture clock and byte transport, never an agent-accessible bridge."""

    def __init__(self, case: fixture.CopiedRoom, records: object) -> None:
        self.case = case
        self.case.host.service.records = records
        self.rival = case.join("bob")
        self.rival_cid, ready = case.authenticate(self.rival)
        case.predict(self.rival, self.rival_cid, ready)
        self.rival_sequence = 2

    def advance_second(self) -> None:
        for _ in range(20):  # Host-owned 20Hz clock, advancing50ms per tick.
            tick = self.case.arena.sim.state["tick"]
            if tick and tick % 200 == 0:  # Rival heartbeats every10seconds.
                renew = self.case.control(self.rival, "RenewRequest", None, self.rival_sequence)
                renew["payload"]["lease_until"] = str(self.case.now + 30_000)
                receipt = self.case.arena.control.frame(self.rival_cid,
                    self.case.policy.canonical_bytes(self.case.signed(renew)))
                if receipt.get("state") != "accepted":
                    raise AssertionError("synthetic rival heartbeat refused")
                self.rival_sequence += 1
            self.case.now += 50
            self.case.arena.advance()

    def dispatch(self, request: dict) -> dict | list:
        operation = request["operation"]
        control = self.case.arena.control
        if operation == "request":
            if request["target"] == "/room/observe":
                self.advance_second()
            return control.request(request["method"], request["target"], request["body"].encode(), ip="cold-alice")
        if operation == "open_control":
            if request["url"] != "wss://arena.example/room/control":
                raise AssertionError("cold agent tried an unpinned control origin")
            return control.open_control(ip="cold-alice")
        if operation == "frame":
            return control.frame(request["cid"], request["body"].encode())
        if operation == "drain_private":
            return control.drain_private(request["cid"])
        raise AssertionError("agent attempted an undocumented host operation")


class SnapCold(unittest.TestCase):
    def test_snap_only_temp_agent_accepts_predicts_fights_ko_and_signed_result(self) -> None:
        snap = (ROOT / "near/SNAP.md").read_text()
        match = re.search(r"<!-- BEGIN COLD AGENT -->\s*```python\n(.*?)\n```\s*<!-- END COLD AGENT -->", snap, re.S)
        self.assertIsNotNone(match, "SNAP lacks an executable cold path; its old fixture stops before a signed result")
        with tempfile.TemporaryDirectory(prefix="snap-cold-") as directory:
            owner, public = self.prepare_owner(Path(directory), snap, match.group(1))
            case = fixture.CopiedRoom()
            case.setUp()
            self.addCleanup(case.doCleanups)
            from portable_records import EngineRecords
            from room.ledger import Refusal
            result_context = copy.deepcopy(case.context)
            result_context["audience"] = "near:mainnet:" + result_context["contract_ids"]["arena"] + ":post_batch"
            records = EngineRecords(case.arena.store, Path(case.tmp.name) / "wire.sqlite",
                case.context, result_context, key_id="room_key_a", sign=case.sign,
                verify=lambda key, body, signature: signature == case.sign(body),
                key_allowed=lambda key: key == "room_key_a")
            with self.assertRaisesRegex(Refusal, "result_pending"):
                records.result("segment:0")
            host = ColdHost(case, records)
            boot = dict(public_checkout=str(public), context=case.context, result_context=result_context,
                session_public_key=case.example("SessionPublicKey"), now_ms=case.now,
                account_id="alice.near", nft_token_id="alice", persona_digest=hashlib.sha256(b"alice").hexdigest())
            summary, trace = self.run_agent(owner, boot, host)
            self.check_summary(summary, trace, case)
            self.check_record_boundaries(records, case)
            self.assertNotIn("grant", boot)
            self.assertNotIn("test_room_host", (owner / "agent.py").read_text())
            print(json.dumps({key: summary[key] for key in (
                "terms_accepted", "combat_seen", "ko_seen", "signed_result", "life_id")}, sort_keys=True))

    @staticmethod
    def prepare_owner(scratch: Path, snap: str, program: str) -> tuple[Path, Path]:
        # Only documented client dependencies, never private game state.
        public = scratch / "public"
        (public / "near/arena").mkdir(parents=True)
        shutil.copytree(ROOT / "room", public / "room", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy2(ROOT / "near/arena/snap_client.py", public / "near/arena/snap_client.py")
        owner = scratch / "owner"
        owner.mkdir()
        (owner / "SNAP.md").write_text(snap)
        (owner / "agent.py").write_text(program + "\n")
        return owner, public

    def run_agent(self, owner: Path, boot: dict, host: ColdHost) -> tuple[dict, list[dict]]:
        child = subprocess.Popen([sys.executable, "-I", "-B", "agent.py"], cwd=owner,
            env={"PATH": os.environ["PATH"], "HOME": str(owner)}, text=True,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(self.stop, child)
        child.stdin.write(json.dumps(boot) + "\n")
        child.stdin.flush()
        trace = []
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            for _ in range(500):  # Bounded reads and operations; no indefinitely waiting child.
                self.assertTrue(selector.select(timeout=20), "cold agent stopped responding")
                line = child.stdout.readline()
                if not line:
                    self.fail("cold agent exited: " + child.stderr.read()[-4000:])
                request = json.loads(line)
                if request["operation"] == "finished":
                    self.assertEqual(child.wait(timeout=10), 0, child.stderr.read())
                    return request, trace
                trace.append(copy.deepcopy(request))
                response = host.dispatch(request)
                child.stdin.write(json.dumps(dict(value=response, now_ms=host.case.now)) + "\n")
                child.stdin.flush()
        self.fail("cold agent exceeded its bounded operation budget")

    def check_summary(self, summary: dict, trace: list[dict], case: fixture.CopiedRoom) -> None:
        for key in ("terms_accepted", "combat_seen", "ko_seen", "signed_result"):
            self.assertTrue(summary[key], key)
        self.assertEqual(summary["prediction_lock"], summary["public_lock"])
        own = [life for life in case.arena.store.segment("segment:0")["sealed"]["lives"]
               if life["nft_token_id"] == "alice"]
        self.assertTrue(own)
        self.assertEqual(summary["life_id"], own[0]["life_id"])
        frames = [json.loads(row["body"]) for row in trace if row["operation"] == "frame"]
        self.assertTrue(any(row.get("kind") == "intent" for row in frames))
        self.assertTrue(any(row.get("kind") == "renew" for row in frames))
        self.assertFalse(case.arena.failed)
        self.assertFalse(case.host.service._failed)
        state = case.host.service.export_owner_state()
        self.assertTrue(any(value["version"] == "1" for value in state["accepted"]))

    def check_record_boundaries(self, records: object, case: fixture.CopiedRoom) -> None:
        from portable_records import _project
        from room.ledger import Refusal, digest
        import replay
        archive = case.arena.store.segment("segment:0")
        before = copy.deepcopy(archive)
        wire, _ = _project(archive)
        self.assertEqual(archive, before, "projection must not edit native archives")
        self.assertNotEqual(wire["sealed_result_hash"], archive["sealed"]["sealed_result_hash"])
        with self.assertRaisesRegex(Refusal, "recovery_pending"):
            records.result("segment:1")
        changed = copy.deepcopy(wire)
        changed["lives"][0]["ko_count"] = "999"
        with self.assertRaisesRegex(Refusal, "bad_message"):
            records._replay(changed)
        forged = copy.deepcopy(archive)
        event = next(row for row in forged["sealed"]["input_events"] if row["kind"] == "intent")
        event["payload"]["focus"] = "forged-target"
        forged["sealed"]["inputs_hash"] = digest(forged["sealed"]["input_events"])
        forged["sealed"]["sealed_result_hash"] = replay.engine_commitment(forged)
        with self.assertRaisesRegex(Refusal, "bad_message"):
            _project(forged)
        forged = copy.deepcopy(archive)
        event = next(row for row in forged["sealed"]["input_events"] if row["kind"] == "prediction_lock")
        event["fighter_id"] = "another-fighter"
        forged["sealed"]["inputs_hash"] = digest(forged["sealed"]["input_events"])
        forged["sealed"]["sealed_result_hash"] = replay.engine_commitment(forged)
        with self.assertRaisesRegex(Refusal, "bad_message"):
            _project(forged)
        self.assertEqual(case.arena.store.segment("segment:0"), before)

    @staticmethod
    def stop(child: subprocess.Popen) -> None:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=10)
        for stream in (child.stdin, child.stdout, child.stderr):
            stream.close()


if __name__ == "__main__":
    unittest.main()
