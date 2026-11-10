"""Real copied-room assembly with synthetic proof/signature adapters only."""
from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import server
import sim


def encoded(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def assert_admission_audit(case: CopiedRoom, grant: dict, connection_id: str) -> None:
    """Grant and authentication bracket the required private member checkpoint."""
    case.assertEqual([event["kind"] for event in case.security], ["grant", "owner_state", "authenticate"])
    binding = {key: grant[key] for key in ("context", "grant_id", "session_key_id", "member_id",
               "account_id", "nft_token_id", "persona_digest", "slot_id", "generation")}
    case.assertEqual(case.security[0]["binding"], binding)
    authenticated = case.security[2]["binding"]
    case.assertEqual({key: authenticated[key] for key in binding}, binding)
    case.assertEqual(set(authenticated), set(binding) | {"nonce", "connection_id"})
    case.assertEqual(authenticated["connection_id"], connection_id)
    case.assertEqual(authenticated["nonce"], case.host.service._connections[connection_id]["challenge"]["nonce"])
    checkpoint = case.security[1]["binding"]["state"]
    case.policy.validate("OwnerState", checkpoint)
    case.assertEqual(checkpoint["context"], case.context)
    case.assertEqual(checkpoint["terms"], case.host.service.export_owner_state()["terms"])
    case.assertEqual(checkpoint["members"], [dict(member_id=grant["member_id"],
        account_id=grant["account_id"], nft_token_id=grant["nft_token_id"], name=grant["member_id"])])


class CopiedRoom(unittest.TestCase):
    def setUp(self):
        self.host_module = importlib.import_module("room_host")
        self.policy = importlib.import_module("room.policy")
        self.service_module = importlib.import_module("room.service")
        self.schema = json.loads((ROOT / "room/protocol.schema.json").read_bytes())
        self.context = self.example("MainnetContext")
        self.context["rules_hash"] = sim.digest(sim.DEFAULT_RULES)
        self.now = 1_900_000_000_000
        self.ready = True
        self.admit = True
        self.available = True
        self.owners = {}
        self.consumed = set()
        self.security = []
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        slots = importlib.import_module("room.slots").SlotStore(
            Path(self.tmp.name) / "slots", self.context["room_id"], 16, clock=lambda: self.now)
        self.host = self.host_module.RoomHost(slots, self.context, now_ms=lambda: self.now,
            sign=self.sign, verify_session=self.verify_session, key_id="room_key_a",
            proof_methods=("synthetic_v1",), consume_nonce=self.consume,
            ready=lambda: self.ready, admission_open=lambda: self.admit,
            security_event=self.commit_security)
        self.arena = server.Arena(self.context, [1, 2, 3, 4, 5], data_dir=Path(self.tmp.name) / "engine",
            room_factory=self.host, profile_provider=self.profile, identity_resolver=self.resolve,
            receipt_signer=self.host.sign_receipt, admission_gate=self.host.admission_ready,
            life_guard=self.host.life_guard, server_time_ms=lambda: self.now,
            pick_resolver=lambda binding, payload: sim.rules_dict(sim.DEFAULT_RULES["default_loadout"]))

    def example(self, name: str) -> dict:
        return copy.deepcopy(self.schema["$defs"][name]["examples"][0])

    def sign(self, body: bytes) -> str:
        return encoded(hmac.digest(b"synthetic-room", body, "sha512"))

    def signed(self, value: dict) -> dict:
        value["signature"] = encoded(hmac.digest(b"synthetic-session",
            self.policy.canonical_bytes(value, exclude=("signature",)), "sha512"))
        return value

    def verify_session(self, public_key: dict, body: bytes, signature: str) -> bool:
        return public_key == self.example("SessionPublicKey") and hmac.compare_digest(signature,
            encoded(hmac.digest(b"synthetic-session", body, "sha512")))

    def consume(self, nonce: str, expires_at: str) -> bool:
        if nonce in self.consumed or int(expires_at) <= self.now:
            return False
        self.consumed.add(nonce)
        return True

    def commit_security(self, event: dict) -> bool:
        # A fixture recorder, not the deployed external security journal.
        self.security.append(copy.deepcopy(event))
        return True

    def resolve(self, request: dict) -> dict:
        if not self.available:
            return server.error("ownership_unavailable")
        challenge = request["challenge"]
        expected = encoded(hmac.digest(b"synthetic-wallet",
            self.policy.canonical_bytes(request, exclude=("proof",)), "sha512"))
        if not hmac.compare_digest(expected, request["proof"]["proof_bytes"]):
            return server.error("proof_required")
        account = self.owners.get(challenge["nft_token_id"], challenge["account_id"])
        return {"owner": {"context": copy.deepcopy(self.context), "account_id": account,
            "nft_token_id": challenge["nft_token_id"], "persona_digest": request["persona_digest"],
            "ownership_kind": "owner", "custody_reservation_id": None, "checked_at": str(self.now)},
            "play_status": "eligible", "chain_height": "1", "sale_control_allowed": True}

    def profile(self, binding: dict) -> dict:
        return {"house": False, "public_name": binding["nft_token_id"], "model": "fixture",
                "style": "brawler", "loadout": sim.rules_dict(sim.DEFAULT_RULES["default_loadout"]),
                "bag": {}, "prompt": "PRIVATE-CANARY", "player_spend": "PRIVATE-CANARY"}

    def join(self, token: str = "alice") -> dict:
        challenge_request = self.example("JoinChallengeRequest")
        challenge_request.update(context=copy.deepcopy(self.context), account_id=token + ".near",
            nft_token_id=token, persona_digest=hashlib.sha256(token.encode()).hexdigest(), request_id="join-" + token)
        challenge = self.arena.control.request("POST", "/room/challenge",
            self.policy.canonical_bytes(challenge_request), ip=token)
        if challenge.get("type") == "error":
            return challenge
        request = self.example("JoinRequest")
        request.update(context=copy.deepcopy(self.context), challenge=challenge,
            persona_digest=challenge_request["persona_digest"], request_id=challenge_request["request_id"],
            declared_compute={"harness": "external", "model": "fixture", "source": "owner", "effort": "high"})
        request["proof"] = {"method_id": "synthetic_v1", "key_id": "wallet_a", "proof_bytes": "AA"}
        request["proof"]["proof_bytes"] = encoded(hmac.digest(b"synthetic-wallet",
            self.policy.canonical_bytes(request, exclude=("proof",)), "sha512"))
        return self.arena.control.request("POST", "/room/join", self.policy.canonical_bytes(request), ip=token)

    def authenticate(self, grant: dict) -> tuple[str, dict]:
        challenge = self.arena.control.open_control(ip=grant["nft_token_id"])
        self.assertEqual(challenge.get("type"), "control_challenge", challenge)
        request = {key: copy.deepcopy(grant[key]) for key in
            ("context", "grant_id", "session_key_id", "member_id", "nft_token_id", "persona_digest", "slot_id", "generation")}
        request.update(domain="room.control.v1", kind="authenticate", request_id="socket-" + grant["nft_token_id"],
            challenge=challenge, token=grant["token"])
        ready = self.arena.control.frame(challenge["connection_id"], self.policy.canonical_bytes(self.signed(request)))
        self.assertEqual(ready.get("type"), "control_ready", ready)
        return challenge["connection_id"], ready

    def control(self, grant: dict, name: str, life: str | None, sequence: int) -> dict:
        request = self.example(name)
        request.update({key: copy.deepcopy(grant[key]) for key in
            ("context", "grant_id", "session_key_id", "member_id", "nft_token_id", "persona_digest", "slot_id", "generation")})
        request.update(life_id=life, sequence=str(sequence))
        return request

    def predict(self, grant: dict, cid: str, ready: dict, sequence: int = 1) -> dict:
        life = ready["next_life"]["reservation"]["life_id"]
        pick = self.control(grant, "PredictionRequest", life, sequence)
        pick["payload"].update(loadout={"menu_row": "default", "bag_serials": []},
            spread_bps={"one": 2500, "two": 2500, "three": 2500, "four_plus": 2500},
            zero_bps=1000, stake=None, moves=[], lock=False)
        receipt = self.arena.control.frame(cid, self.policy.canonical_bytes(self.signed(pick)))
        self.assertEqual(receipt.get("state"), "accepted", receipt)
        self.assertEqual(receipt["prediction_lock"]["state"], "prediction")
        return pick

    def test_real_copy_joins_predicts_and_applies_authenticated_intent(self):
        self.assertIsInstance(self.arena.room, self.service_module.RoomService)
        self.assertIs(self.arena.room.bridge, self.arena.bridge)
        self.assertIs(self.arena.room.identity.bridge, self.arena.bridge)
        grant = self.join()
        self.assertEqual(grant.get("state"), "accepted", grant)
        cid, ready = self.authenticate(grant)
        pick = self.predict(grant, cid, ready)
        self.arena.advance(4)
        self.assertIn("alice", self.arena.sim._live())
        intent = self.control(grant, "IntentRequest", pick["life_id"], 2)
        intent["payload"].update(fighter_id="alice", focus=None, avoid=None, loot="ignore", sig="hold", leave=False, say=None)
        receipt = self.arena.control.frame(cid, self.policy.canonical_bytes(self.signed(intent)))
        self.assertEqual(receipt.get("state"), "accepted", receipt)
        self.assertEqual(receipt["applied_tick"], "6")
        self.assertEqual(receipt["request_digest"], server.control_digest(intent))
        self.assertEqual(receipt["signature"], self.sign(self.policy.canonical_bytes(receipt, exclude=("signature",))))
        self.arena.advance(2)
        snapshot = self.arena.control.request("GET", "/room/observe", ip="watcher")
        self.assertEqual(snapshot["clock"]["tick"], "6")
        self.assertNotIn(grant["token"], json.dumps(snapshot))
        self.assertNotIn("PRIVATE-CANARY", json.dumps(snapshot))
        self.assertFalse(hasattr(self.arena.control, "bridge"))
        self.assertFalse(hasattr(self.arena.control, "maintain"))
        assert_admission_audit(self, grant, cid)

    def test_real_validator_refuses_forgery_and_current_ownership_loss(self):
        grant = self.join()
        cid, ready = self.authenticate(grant)
        pick = self.predict(grant, cid, ready)
        self.arena.advance(4)
        message = self.control(grant, "IntentRequest", pick["life_id"], 2)
        message["payload"].update(fighter_id="alice", focus=None, avoid=None, loot="ignore", sig="hold", leave=False, say=None)
        self.signed(message)
        message["signature"] = "B" * 85 + "A"
        before = copy.deepcopy(self.arena.sim.state["inputs"])
        refused = self.arena.control.frame(cid, self.policy.canonical_bytes(message))
        self.assertEqual(refused["code"], "proof_required")
        self.assertEqual(self.arena.sim.state["inputs"], before)
        cid, _ = self.authenticate(grant)
        self.available = False
        self.assertEqual(self.arena.control.frame(cid, self.policy.canonical_bytes(self.signed(message)))["code"], "ownership_unavailable")
        self.assertFalse(self.host.life_guard(self.arena.members["alice"]["binding"]))
        self.assertEqual(self.arena.sim.state["inputs"], before)

    def test_closed_host_and_incompatible_slot_context_refuse(self):
        self.admit = False
        self.assertEqual(self.join()["code"], "admission_closed")
        self.assertFalse(self.arena.can_admit())
        self.admit = True
        self.ready = False
        self.assertFalse(self.host.admission_ready())
        self.assertFalse(self.host.life_guard({}))
        with self.assertRaises(self.policy.BoundaryError):
            self.host.sign_receipt(self.example("Receipt"))
        slots = importlib.import_module("room.slots").SlotStore(
            Path(self.tmp.name) / "other", "wrong-room", 16, clock=lambda: self.now)
        with self.assertRaisesRegex(self.policy.BoundaryError, "context_mismatch"):
            self.host_module.RoomHost(slots, self.context, now_ms=lambda: self.now,
                sign=self.sign, verify_session=self.verify_session, key_id="room_key_a",
                proof_methods=("synthetic_v1",), consume_nonce=self.consume,
                ready=lambda: True, security_event=self.commit_security)

    def test_real_room_cannot_advance_clock_and_engine_seals_1200_ticks(self):
        for method, target, body in (("POST", "/room/tick", b"{}"),
                                     ("GET", "/room/tick?advance=1200", b"")):
            self.assertEqual(self.arena.control.request(method, target, body, ip="watcher")["code"], "bad_message")
        self.assertEqual(self.arena.sim.state["tick"], 0)
        self.arena.advance(1200)
        self.assertEqual(self.arena.bridge.seal("segment:0")["tick_count"], "1200")
        clock = self.arena.control.request("GET", "/room/tick", ip="watcher")
        self.assertEqual(clock["tick"], "1200")
        self.assertFalse(self.arena.failed)

    def test_real_combat_delivers_next_life_notice_after_ko(self):
        clients = {}
        for token in ("alice", "bob"):
            grant = self.join(token)
            cid, ready = self.authenticate(grant)
            pick = self.predict(grant, cid, ready)
            clients[token] = (grant, cid, pick["life_id"])
        for _ in range(1200):
            self.arena.advance()
            if self.arena.completed_lives:
                break
        self.assertTrue(self.arena.completed_lives, "the real engine must complete a combat life")
        completed = self.arena.completed_lives[0]
        token = completed["nft_token_id"]
        grant, cid, first_life = clients[token]
        self.assertEqual(completed["life_id"], first_life)
        notices = self.arena.control.drain_private(cid)
        self.assertEqual(len(notices), 1, notices)
        notice = notices[0]
        self.assertEqual(notice["type"], "life_notice")
        self.assertNotEqual(notice["reservation"]["life_id"], first_life)
        self.assertEqual(notice["reservation"]["binding"]["grant_id"], grant["grant_id"])
        self.assertEqual(notice["signature"], self.sign(self.policy.canonical_bytes(notice, exclude=("signature",))))
        self.predict(grant, cid, {"next_life": notice}, sequence=2)
        self.assertFalse(self.arena.failed)


if __name__ == "__main__":
    unittest.main()
