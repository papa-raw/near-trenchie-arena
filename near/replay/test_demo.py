"""make demo's checks, offline: a fake testnet settles real segments, pin.py pins them, demo.py reads them back.

The arena runs on seeds the writer committed on the fake chain, the writer posts the batch with the MANIFEST flag,
pin.py copies the sealed records into a MANIFEST in a temporary folder, and demo.py checks every segment against
the fake archival node. Each tamper case changes one thing and must fail only the segment it touched.
"""

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "near" / "arena")]

from near.chain import test_chain  # noqa: E402  (its Rig: the fake testnet behind the real sender and writer)
from near.replay import demo, pin  # noqa: E402
import replay as engine  # noqa: E402  (near/arena)

FAKE = "https://fake.invalid"
BLOCK_NS = 1_794_394_579 * 10 ** 9          # the fake block time of every tx
DAY_NS = 86_400 * 10 ** 9


class Archival:
    """The fake node's tx results as an archival node gives them: with the block hash, and the `block` method."""

    def __init__(self, rig):
        self.rig, self.down = rig, False

    def post(self, url, json=None, timeout=None):
        if self.down:
            raise test_chain.requests.exceptions.ConnectionError("fake: archival node down")
        if json["method"] == "block":
            return test_chain.fakerpc._Response({"jsonrpc": "2.0", "id": json["id"],
                                                 "result": {"header": {"timestamp_nanosec": str(BLOCK_NS)}}})
        r = self.rig.rpc.post(url, json=json, timeout=timeout)
        body = r.json()
        if "result" in body and "transaction_outcome" in body["result"]:
            body = copy.deepcopy(body)
            body["result"]["transaction_outcome"]["block_hash"] = "fakeblock"
        return test_chain.fakerpc._Response(body)


class MakeDemo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="demo-test-")
        original = test_chain.snap_local.server.Arena
        try:
            rig = test_chain.Rig(cls.tmp, batch_segments=2, commit_size=5, lookahead=2, manifest=True)
            rig.arena()
            rig.run_segments(2)
            rig.writer.process()
        finally:
            test_chain.snap_local.server.Arena = original
        [b] = rig.batches()
        assert b["status"] == "applied", rig.log
        cls.rig, cls.batch = rig, b
        cls.base = Path(cls.tmp) / "replay"
        cls.base.mkdir()
        (cls.base / "MANIFEST").write_text(json.dumps({
            "network": "testnet", "arena": test_chain.ARENA, "signer": rig.op.account_id,
            "archival": [FAKE], "commits": [], "batches": [], "jobs": []}))
        state = dict(rig.writer.state, settled=rig.writer.settled_batches())
        cls.pinned = pin.pin(state, b["batch_id"], manifest_path=cls.base / "MANIFEST")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def copy(self):
        d = Path(tempfile.mkdtemp(prefix="demo-case-", dir=self.tmp))
        shutil.copytree(self.base, d, dirs_exist_ok=True)
        return d

    def record(self, d, i):
        m = json.loads((d / "MANIFEST").read_text())
        p = d / m["batches"][0]["segments"][i]["record"]
        return p, json.loads(p.read_text())

    def demo(self, d, archival=None, now_ns=BLOCK_NS + DAY_NS):
        lines = []
        code = demo.run(d / "MANIFEST", urls=[FAKE], post=(archival or Archival(self.rig)).post, now_ns=now_ns,
                        out=lines.append)
        return code, lines

    def verdicts(self, lines):
        return [l.split()[0] for l in lines if l.startswith(("PASS ", "FAIL ")) and l.split()[1][0].isdigit()]

    def test_pin_flags_the_batch_and_names_its_commit(self):
        self.assertEqual(self.pinned, (2, [0]))
        m = json.loads((self.base / "MANIFEST").read_text())
        self.assertEqual(m["commits"], [{"commit_id": 0, "tx": self.rig.writer.state["commits"][0]["tx"],
                                         "signer": self.rig.op.account_id}])
        self.assertIs(self.rig.model.batches[self.batch["batch_id"]]["manifest"], True)
        with self.assertRaises(SystemExit):     # a batch is pinned once
            pin.pin(dict(self.rig.writer.state, settled=self.rig.writer.settled_batches()), self.batch["batch_id"],
                    manifest_path=self.base / "MANIFEST")

    def test_every_pinned_segment_passes_against_the_archival_args(self):
        code, lines = self.demo(self.copy())
        self.assertEqual((code, self.verdicts(lines)), (0, ["PASS", "PASS"]), "\n".join(lines))
        self.assertIn("2/2 PASS", lines)
        self.assertTrue(any(l.startswith("measured: 2 segments re-simulated") for l in lines), lines)
        self.assertIn("1.0 days old; one older than 2 days: not yet", lines[-2])
        self.assertEqual(lines[-1], "2/2 PASS")

    def test_a_changed_command_log_fails_that_segment_only(self):
        d = self.copy()
        p, rec = self.record(d, 1)
        self.assertEqual(rec["commands"][-1], {"kind": "advance", "value": 1})
        rec["commands"][-1:] = []                   # the log now stops one tick short
        p.write_text(json.dumps(rec))
        code, lines = self.demo(d)
        self.assertEqual((code, self.verdicts(lines)), (1, ["PASS", "FAIL"]), "\n".join(lines))
        self.assertIn("replay:", [l for l in lines if l.startswith("FAIL")][0])
        self.assertEqual(lines[-1], "1/2 PASS, 1 FAIL")

    def test_a_record_resealed_to_match_its_own_change_still_fails_against_the_chain(self):
        d = self.copy()
        p, rec = self.record(d, 0)
        rec["initial_state"]["rng"] ^= 1
        forged = engine.sim.Sim.restore(rec["initial_state"], engine.load_rules(rec["rules_hash"]))
        self.assertEqual({c["kind"] for c in rec["commands"]}, {"advance"})   # the bare arena's log: ticks only
        for c in rec["commands"]:
            for _ in range(c["value"]):
                forged.step()
        rec["sealed"]["final_state_hash"] = forged.state_hash()      # the record now agrees with itself
        rec["sealed"]["sealed_result_hash"] = engine.engine_commitment(rec)
        engine.replay_segment(rec)                                     # ...so a self-check would pass it
        p.write_text(json.dumps(rec))
        code, lines = self.demo(d)
        # its replay misses the archival hash, so the next segment has no anchored start either, and says so
        self.assertEqual((code, self.verdicts(lines)), (1, ["FAIL", "FAIL"]), "\n".join(lines))
        self.assertIn("start: a tick-0 start state that is not a fresh arena on its seed", lines[2])
        self.assertIn("start: unanchored: it continues a run, and segment 1/2's replay did not end on its archival hash",
                      lines[3])

    def test_a_start_state_change_the_replay_washes_out_is_still_caught(self):
        """A value the segment overwrites (say the HP of a fighter that is KO'd and respawns) can leave the final hash
        unchanged; the start must still be the previous segment's replayed end state."""
        d = self.copy()
        _, first = self.record(d, 0)
        _, second = self.record(d, 1)
        prev = {"end": engine.replay_segment(first).export(), "label": "1/2"}
        self.assertIsNone(demo.check_start(second, prev))
        second["initial_state"]["next_id"] += 1
        self.assertEqual(demo.check_start(second, prev), "not the previous segment's replayed end state")
        first_fresh = copy.deepcopy(first)
        first_fresh["initial_state"]["next_id"] += 1
        self.assertEqual(demo.check_start(first_fresh, None), "a tick-0 start state that is not a fresh arena on its seed")
        self.assertIn("no earlier segment in the MANIFEST", demo.check_start(second, None))

    def test_a_changed_input_log_fails_on_its_hash(self):
        d = self.copy()
        p, rec = self.record(d, 0)
        rec["sealed"]["input_events"].append({"kind": "join", "fighter_id": "zz-extra"})
        p.write_text(json.dumps(rec))
        code, lines = self.demo(d)
        self.assertEqual(self.verdicts(lines), ["FAIL", "PASS"], "\n".join(lines))
        self.assertIn("inputs: the input log's hash differs", lines[2])

    def test_a_seed_that_is_not_the_committed_one_fails(self):
        d = self.copy()
        p, rec = self.record(d, 1)
        rec["initial_state"]["seed"] += 1
        p.write_text(json.dumps(rec))
        code, lines = self.demo(d)
        self.assertEqual(self.verdicts(lines), ["PASS", "FAIL"], "\n".join(lines))
        self.assertIn("seed: log seed", lines[3])

    def test_a_segment_the_tx_does_not_carry_fails(self):
        d = self.copy()
        m = json.loads((d / "MANIFEST").read_text())
        m["batches"][0]["segments"][1]["segment_id"] = "not-in-the-tx"
        (d / "MANIFEST").write_text(json.dumps(m))
        code, lines = self.demo(d)
        self.assertEqual(self.verdicts(lines), ["PASS", "FAIL"], "\n".join(lines))
        self.assertIn("batch: the tx's args carry no such segment", lines[3])

    def test_no_archival_answer_fails_every_segment_and_says_why(self):
        archival = Archival(self.rig)
        archival.down = True
        code, lines = self.demo(self.copy(), archival)
        self.assertEqual((code, self.verdicts(lines)), (1, ["FAIL", "FAIL"]), "\n".join(lines))
        self.assertIn("archival read failed", lines[2])
        self.assertFalse(any(l.startswith("archival age") for l in lines))

    def test_a_pinned_job_tx_is_never_passed_unchecked(self):
        d = self.copy()
        m = json.loads((d / "MANIFEST").read_text())
        m["jobs"] = [{"tx": "somejob", "signer": "buyer.t.testnet"}]
        (d / "MANIFEST").write_text(json.dumps(m))
        code, lines = self.demo(d)
        self.assertEqual((code, self.verdicts(lines)), (1, ["PASS", "PASS"]), "\n".join(lines))
        self.assertIn("FAIL jobs: 1 job transactions are pinned, and this demo has no job check yet", lines)
        self.assertEqual(lines[-1], "2/2 PASS; 1 job transactions not checked: FAIL")

    def test_the_age_line_says_yes_once_a_tx_is_over_two_days_old(self):
        code, lines = self.demo(self.copy(), now_ns=BLOCK_NS + 3 * DAY_NS)
        self.assertEqual(code, 0)
        self.assertTrue(lines[-2].endswith("3.0 days old; one older than 2 days: yes"), lines[-2])


if __name__ == "__main__":
    unittest.main()
