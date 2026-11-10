"""New public-client cases; synthetic authority is explicit in every fixture."""
from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
import sys
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parent)]
import test_room_host as fixture


class LocalTransport:
    def __init__(self, case: fixture.CopiedRoom):
        self.case = case
        self.requests = []
        self.frames = []
        self.corrupt = False
        self.drop = False
        self.wrong_context = False
        self.record_replies = {}

    def request(self, method: str, target: str, body: bytes = b"") -> dict:
        self.requests.append((method, target, body))
        reply = (copy.deepcopy(self.record_replies[target]) if target in self.record_replies else
                 self.case.arena.control.request(method, target, body, ip="cold-agent"))
        if self.wrong_context and "context" in reply:
            reply["context"]["deployment_id"] = "other"
        return reply

    def open_control(self, url: str) -> dict:
        return self.case.arena.control.open_control(ip="cold-agent")

    def frame(self, cid: str, body: bytes) -> dict:
        self.frames.append(body)
        response = self.case.arena.control.frame(cid, body)
        if self.drop:
            self.drop = False
            raise OSError("fixture lost reply")
        if self.corrupt:
            response["signature"] = "B" * 85 + "A"
        return response

    def drain_private(self, cid: str) -> list[dict]:
        return self.case.arena.control.drain_private(cid)


class ColdJoin(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("snap_client")
        self.case = fixture.CopiedRoom()
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.transport = LocalTransport(self.case)
        self.client = self.module.SnapClient(self.case.context, self.transport,
            now_ms=lambda: self.case.now, sign_session=self.sign_session,
            verify_room=lambda key, body, signature: signature == self.case.sign(body),
            trusted_key_ids=("room_key_a",))

    def sign_session(self, body: bytes) -> str:
        import hmac
        return fixture.encoded(hmac.digest(b"synthetic-session", body, "sha512"))

    def wallet(self, body: bytes) -> dict:
        import hmac
        return {"method_id": "synthetic_v1", "key_id": "wallet_a",
                "proof_bytes": fixture.encoded(hmac.digest(b"synthetic-wallet", body, "sha512"))}

    def join(self) -> dict:
        return self.client.join(account_id="alice.near", nft_token_id="alice",
            persona_digest=fixture.hashlib.sha256(b"alice").hexdigest(),
            session_public_key=self.case.example("SessionPublicKey"), request_id="cold-alice",
            declared_compute={"harness": "external", "model": "fixture", "source": "owner", "effort": "high"},
            prove_wallet=self.wallet)

    def payload(self) -> dict:
        return {"loadout": {"menu_row": "default", "bag_serials": []},
            "spread_bps": {"one": 2500, "two": 2500, "three": 2500, "four_plus": 2500},
            "zero_bps": 1000, "stake": None, "moves": [], "lock": False}

    def test_client_joins_predicts_and_retries_exact_bytes_after_lost_reply(self):
        grant = self.join()
        ready = self.client.authenticate(request_id="cold-socket")
        life = ready["next_life"]["reservation"]["life_id"]
        prediction = self.client.control("prediction", self.payload(), life_id=life)
        self.assertEqual(prediction["prediction_lock"]["state"], "prediction")
        self.case.arena.advance(4)
        payload = {"fighter_id": "alice", "focus": None, "avoid": None,
                   "loot": "ignore", "sig": "hold", "leave": False, "say": None}
        self.transport.drop = True
        with self.assertRaises(OSError):
            self.client.control("intent", payload, life_id=life)
        inputs = copy.deepcopy(self.case.arena.sim.state["inputs"])
        accepted = self.client.control("intent", payload, life_id=life)
        self.assertEqual(accepted["state"], "accepted")
        self.assertEqual(self.transport.frames[-2], self.transport.frames[-1])
        self.assertEqual(self.case.arena.sim.state["inputs"], inputs)
        self.assertEqual(accepted["sequence"], "2")
        self.assertNotIn(grant["token"], repr(self.transport.requests))
        self.assertEqual(self.client.observe()["clock"]["tick"], "4")

    def test_client_rejects_bad_signature_and_untrusted_context_before_progress(self):
        self.join()
        ready = self.client.authenticate(request_id="cold-socket")
        life = ready["next_life"]["reservation"]["life_id"]
        self.transport.corrupt = True
        with self.assertRaisesRegex(self.module.SnapRefusal, "proof_required"):
            self.client.control("prediction", self.payload(), life_id=life)
        self.transport.corrupt = False
        with self.assertRaisesRegex(self.module.SnapRefusal, "request_conflict"):
            self.client.control("prediction", dict(self.payload(), zero_bps=5000), life_id=life)
        accepted = self.client.control("prediction", self.payload(), life_id=life)
        self.assertEqual(accepted["sequence"], "1")
        self.transport.wrong_context = True
        with self.assertRaisesRegex(self.module.SnapRefusal, "context_mismatch"):
            self.client.observe()

    def test_client_never_accepts_unconfigured_or_unsigned_result(self):
        self.join()
        with self.assertRaisesRegex(self.module.SnapRefusal, "recovery_pending"):
            self.client.result("segment:0")
        self.assertFalse(any("/result" in target for _, target, _ in self.transport.requests))
        self.assertEqual(self.client.manifest()["control_authentication"], "first_frame_v1")

    def test_fresh_raw_loop_process_joins_predicts_and_fights_from_public_checkout(self):
        grant = self.case.join("bob")
        cid, ready = self.case.authenticate(grant)
        self.case.predict(grant, cid, ready)
        child = subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "--synthetic-agent"],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def stop() -> None:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=10)
            for stream in (child.stdin, child.stdout, child.stderr):
                stream.close()
        self.addCleanup(stop)
        child.stdin.write(json.dumps({"context": self.case.context, "now_ms": self.case.now,
                                      "session_public_key": self.case.example("SessionPublicKey")}) + "\n")
        child.stdin.flush()
        operations = []
        summary = None
        for _ in range(200):
            line = child.stdout.readline()
            self.assertTrue(line, "raw-loop process must produce a protocol operation")
            command = json.loads(line)
            operation = command.pop("operation")
            operations.append(operation)
            if operation == "finished":
                summary = command
                break
            # This fixture drives the host clock. There is no guest advance verb.
            self.case.arena.advance(10)
            if operation == "request":
                reply = self.transport.request(command["method"], command["target"], command["body"].encode())
            elif operation == "open_control":
                reply = self.transport.open_control(command["url"])
            elif operation == "frame":
                reply = self.transport.frame(command["cid"], command["body"].encode())
            elif operation == "drain_private":
                reply = self.transport.drain_private(command["cid"])
            else:
                self.fail("unexpected raw-loop transport operation")
            child.stdin.write(json.dumps(reply) + "\n")
            child.stdin.flush()
        self.assertIsNotNone(summary)
        self.assertEqual(child.wait(timeout=10), 0, child.stderr.read())
        self.assertEqual(summary, {"joined": True, "prediction": "accepted", "intent": "accepted",
                                   "combat_seen": True, "record_acceptance": "blocked"})
        self.assertGreater(len(operations), 6)
        self.assertNotIn("token", json.dumps(summary))

    def test_client_verifies_signed_result_and_public_lock_fixture(self):
        # These are synthetic record responses, not a completed game result.
        from room.ledger import sealed_hash
        context = copy.deepcopy(self.case.context)
        context["audience"] = "near:mainnet:" + context["contract_ids"]["arena"] + ":post_batch"
        self.client = self.module.SnapClient(self.case.context, self.transport,
            now_ms=lambda: self.case.now, sign_session=self.sign_session,
            verify_room=lambda key, body, signature: signature == self.case.sign(body),
            trusted_key_ids=("room_key_a",), result_context=context)
        self.join()
        ready = self.client.authenticate(request_id="cold-socket")
        life = ready["next_life"]["reservation"]["life_id"]
        receipt = self.client.control("prediction", self.payload(), life_id=life)
        page = self.case.example("ReplayPage")
        page.update(context=copy.deepcopy(self.case.context), segment_id="segment:0", seed="1",
            rules_hash=self.case.context["rules_hash"], input_events=copy.deepcopy(self.case.arena.input_events), next_index=None)
        page["inputs_hash"] = self.case.policy.digest(page["input_events"])
        result = self.case.example("Result")
        result.update(context=context, key_id="room_key_a", segment_id="segment:0", life_ids=[life],
            nft_token_ids=["alice"], inputs_hash=page["inputs_hash"], rules_hash=self.case.context["rules_hash"],
            lives=[dict(life_id=life, nft_token_id="alice", prediction_lock=receipt["prediction_lock"],
                        ko_count="0", inventory_hash="0" * 64, completed=True)])
        result["sealed_result_hash"] = sealed_hash(result)
        result["signature"] = self.case.sign(self.case.policy.canonical_bytes(result, exclude=("signature",)))
        self.transport.record_replies.update({"/room/result?segment_id=segment%3A0": result,
                                             "/room/replay?segment_id=segment%3A0": page})
        self.assertEqual(self.client.result("segment:0"), result)
        row = self.client.prediction_row("segment:0", life)
        self.assertEqual(row["payload"]["prediction_lock"], receipt["prediction_lock"])
        page["input_events"][0]["record_hash"] = "0" * 64
        with self.assertRaisesRegex(self.module.SnapRefusal, "bad_message"):
            self.client.prediction_row("segment:0", life)
        result["context"]["deployment_id"] = "other"
        result["signature"] = self.case.sign(self.case.policy.canonical_bytes(result, exclude=("signature",)))
        with self.assertRaisesRegex(self.module.SnapRefusal, "context_mismatch"):
            self.client.result("segment:0")

    def test_renewed_grant_reauthenticates_after_original_expiry(self):
        grant = self.join()
        self.client.authenticate(request_id="cold-socket")
        self.case.now += 20_000
        renewed = self.client.control("renew", {"lease_until": str(self.case.now + 30_000)})
        self.assertEqual(renewed["state"], "accepted")
        self.case.now += 11_000
        self.assertLess(int(grant["expires_at"]), self.case.now)
        self.assertGreater(int(self.case.host.identity.grant(grant["grant_id"])["expires_at"]), self.case.now)
        ready = self.client.authenticate(request_id="reconnected-socket")
        self.assertEqual(ready["type"], "control_ready")

    def test_public_record_matches_signed_result_and_complete_prediction_receipt(self):
        from room.ledger import sealed_hash, replay_event_hash
        context = copy.deepcopy(self.case.context)
        context["audience"] = "near:mainnet:" + context["contract_ids"]["arena"] + ":post_batch"
        self.client = self.module.SnapClient(self.case.context, self.transport,
            now_ms=lambda: self.case.now, sign_session=self.sign_session,
            verify_room=lambda key, body, signature: signature == self.case.sign(body),
            trusted_key_ids=("room_key_a",), result_context=context)
        self.join()
        ready = self.client.authenticate(request_id="record-regression")
        life = ready["next_life"]["reservation"]["life_id"]
        receipt = self.client.control("prediction", self.payload(), life_id=life)
        page = self.case.example("ReplayPage")
        page.update(context=copy.deepcopy(self.case.context), segment_id="segment:0", seed="1",
            rules_hash=self.case.context["rules_hash"], input_events=copy.deepcopy(self.case.arena.input_events), next_index=None)
        page["inputs_hash"] = self.case.policy.digest(page["input_events"])
        result = self.case.example("Result")
        result.update(context=context, key_id="room_key_a", segment_id="segment:0", life_ids=[life],
            nft_token_ids=["alice"], inputs_hash=page["inputs_hash"], rules_hash=self.case.context["rules_hash"],
            lives=[dict(life_id=life, nft_token_id="alice", prediction_lock=copy.deepcopy(receipt["prediction_lock"]),
                        ko_count="0", inventory_hash="0" * 64, completed=True)])

        def sign_result(value: dict) -> None:
            value["sealed_result_hash"] = sealed_hash(value)
            value["signature"] = self.case.sign(self.case.policy.canonical_bytes(value, exclude=("signature",)))

        def install(public: dict, signed: dict) -> None:
            self.transport.record_replies = {"/room/result?segment_id=segment%3A0": signed,
                                             "/room/replay?segment_id=segment%3A0": public}

        sign_result(result)
        install(copy.deepcopy(page), copy.deepcopy(result))
        self.assertEqual(self.client.result("segment:0"), result)
        baseline = self.client.prediction_row("segment:0", life)
        self.assertEqual(baseline["payload"]["prediction_lock"], receipt["prediction_lock"])
        for attack in ("unsigned_rehash", "signed_result_lock", "anchored_page_lock", "anchored_page_loadout"):
            public, signed = copy.deepcopy(page), copy.deepcopy(result)
            row = next(row for row in public["input_events"] if row["kind"] == "prediction_lock")
            if attack == "signed_result_lock":
                signed["lives"][0]["prediction_lock"].update(lock_ref="changed-lock", ledger_index="999")
                sign_result(signed)
            else:
                if attack in ("unsigned_rehash", "anchored_page_lock"):
                    row["payload"]["prediction_lock"].update(lock_ref="changed-lock", ledger_index="999")
                if attack in ("unsigned_rehash", "anchored_page_loadout"):
                    row["payload"]["loadout"]["menu_row"] = "changed-menu"
                previous = "0" * 64
                for event in public["input_events"]:
                    event["record_hash"] = replay_event_hash(previous, event)
                    previous = event["record_hash"]
                public["inputs_hash"] = self.case.policy.digest(public["input_events"])
                if attack != "unsigned_rehash":
                    signed["inputs_hash"] = public["inputs_hash"]
                    sign_result(signed)
            install(public, signed)
            with self.subTest(attack=attack):
                with self.assertRaisesRegex(self.module.SnapRefusal, "bad_message"):
                    if attack == "signed_result_lock":
                        self.client.result("segment:0")
                    else:
                        self.client.prediction_row("segment:0", life)
        install(copy.deepcopy(page), copy.deepcopy(result))
        receipt["prediction_lock"]["lock_ref"] = "caller-mutated-copy"
        self.assertEqual(self.client.prediction_row("segment:0", life), baseline)


def synthetic_agent() -> None:
    """Test-only raw loop in a fresh process, with openly synthetic signatures."""
    import hashlib
    import hmac
    from snap_client import SnapClient
    boot = json.loads(sys.stdin.readline())
    class Pipes:
        def exchange(self, operation: str, **fields: object) -> dict:
            print(json.dumps(dict(operation=operation, **fields)), flush=True)
            return json.loads(sys.stdin.readline())

        def request(self, method: str, target: str, body: bytes = b"") -> dict:
            return self.exchange("request", method=method, target=target, body=body.decode())

        def open_control(self, url: str) -> dict:
            return self.exchange("open_control", url=url)

        def frame(self, cid: str, body: bytes) -> dict:
            return self.exchange("frame", cid=cid, body=body.decode())

        def drain_private(self, cid: str) -> list[dict]:
            return self.exchange("drain_private", cid=cid)

    def sign(body: bytes) -> str:
        return fixture.encoded(hmac.digest(b"synthetic-session", body, "sha512"))

    def wallet(body: bytes) -> dict:
        return {"method_id": "synthetic_v1", "key_id": "wallet_a",
                "proof_bytes": fixture.encoded(hmac.digest(b"synthetic-wallet", body, "sha512"))}

    client = SnapClient(boot["context"], Pipes(), now_ms=lambda: boot["now_ms"],
        sign_session=sign, trusted_key_ids=("room_key_a",),
        verify_room=lambda key, body, signature: signature == fixture.encoded(hmac.digest(b"synthetic-room", body, "sha512")))
    grant = client.join(account_id="alice.near", nft_token_id="alice",
        persona_digest=hashlib.sha256(b"alice").hexdigest(), session_public_key=boot["session_public_key"],
        request_id="raw-alice", declared_compute={"harness": "external", "model": "raw-loop", "source": "owner", "effort": "high"},
        prove_wallet=wallet)
    ready = client.authenticate(request_id="raw-socket")
    life = ready["next_life"]["reservation"]["life_id"]
    prediction = client.control("prediction", {"loadout": {"menu_row": "default", "bag_serials": []},
        "spread_bps": {"one": 2500, "two": 2500, "three": 2500, "four_plus": 2500},
        "zero_bps": 1000, "stake": None, "moves": [], "lock": False}, life_id=life)
    intent = client.control("intent", {"fighter_id": "alice", "focus": "bob", "avoid": None,
        "loot": "ignore", "sig": "hold", "leave": False, "say": None}, life_id=life)
    combat = False
    previous_health = {}
    for _ in range(60):
        snapshot = client.observe()
        health = {row["fighter_id"]: int(row["health_milli"]) for row in snapshot["fighters"]}
        damaged = any(value < previous_health.get(token, value) for token, value in health.items())
        if damaged or any(row["kind"] in ("attack", "damage", "ko") for row in snapshot["actions"]):
            combat = True
            break
        previous_health = health
    print(json.dumps(dict(operation="finished", joined=grant["state"] == "accepted",
        prediction=prediction["state"], intent=intent["state"], combat_seen=combat,
        record_acceptance="blocked")), flush=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["--synthetic-agent"]:
        synthetic_agent()
    else:
        unittest.main()
