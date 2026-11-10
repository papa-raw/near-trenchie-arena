"""Host conformance with a typed room fake; no wallet, chain or model calls."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import typing
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import server
import sim
from test_server import binding, context


def contract_module():
    directory = Path(os.environ.get("ROOM_CONTRACT_DIR", Path(__file__).resolve().parents[2] / "room"))
    path = directory / "bridge.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_arena_contract", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def check_type(value, expected):
    """Check the actual frozen structural types, including closed required keys."""
    origin, args = typing.get_origin(expected), typing.get_args(expected)
    if origin in (typing.Union, types.UnionType):
        for alternative in args:
            try:
                check_type(value, alternative)
                return
            except AssertionError:
                continue
        raise AssertionError(f"value does not match {expected}")
    if origin is typing.Literal:
        assert any(type(value) is type(a) and value == a for a in args), expected
    elif typing.is_typeddict(expected):
        hints = typing.get_type_hints(expected)
        assert type(value) is dict and set(value) == set(hints), expected.__name__
        for key, kind in hints.items():
            check_type(value[key], kind)
    elif origin is list:
        assert type(value) is list, expected
        for item in value:
            check_type(item, args[0])
    else:
        assert type(value) is expected, expected


class CheckedBridge:
    """Every fake dispatch uses signatures and types read from the frozen module."""
    def __init__(self, bridge, contract):
        self.bridge, self.contract = bridge, contract
        self.calls = []

    def __getattr__(self, name):
        method = getattr(self.contract.GameBridge if self.contract else self.bridge, name)
        signature = inspect.signature(method)
        hints = typing.get_type_hints(method) if self.contract else None
        def call(*args, **kwargs):
            bound = signature.bind(self.bridge, *args, **kwargs) if self.contract else signature.bind(*args, **kwargs)
            for key, value in bound.arguments.items():
                if hints and key != "self":
                    check_type(value, hints[key])
            if name == "apply":
                assert bound.arguments["sequenced_input"]["kind"] == "intent"
            result = getattr(self.bridge, name)(*args, **kwargs)
            if hints:
                check_type(result, hints["return"])
            self.calls.append(name)
            return result
        return call


class RoomFake:
    """Fixture authority and one frame validator shared by all client sources.

    This fake exercises dispatch only. It supplies no wallet/signature security.
    """
    def __init__(self, bridge, contract):
        self.bridge = CheckedBridge(bridge, contract)
        self.bindings, self.lives = {}, {}
        self.frames, self.boundaries, self.maintenance = [], [], 0

    def request(self, method, target, body=b"", *, ip):
        if method == "GET" and target in ("/room/observe", "/room/tick") and body == b"":
            view = self.bridge.observe(None)
            return view["clock"] if target.endswith("tick") else view
        return server.error("bad_message")

    def open_control(self, *, ip, origin=None):
        return {"connection_id": ip}

    def frame(self, connection_id, body):
        self.frames.append(connection_id)
        if type(body) is not bytes:
            return server.error("bad_message")
        message = json.loads(body)
        if message.get("kind") != "intent":
            return server.error("bad_message")
        b = self.bindings.get(connection_id)
        if b is None:
            return server.error("proof_required")
        if self.bridge.contract:
            check_type(message, self.bridge.contract.IntentRequest)
        for key in ("context", "grant_id", "session_key_id", "member_id", "nft_token_id",
                    "persona_digest", "slot_id", "generation"):
            if message[key] != b[key]:
                return server.error("stale_slot")
        return self.bridge.apply(b, message)

    def close_control(self, connection_id):
        self.bindings.pop(connection_id, None)

    def drain_private(self, connection_id):
        return []

    def drain_snapshots(self, connection_id):
        return []

    def maintain(self):
        self.maintenance += 1

    def publish_snapshot(self):
        pass

    def life_boundary(self, grant_id):
        self.boundaries.append(grant_id)

    def admit_fixture(self, b):
        life = self.bridge.reserve_life(b)
        lock = self.bridge.lock_prediction(b, life["life_id"], None)
        fighter = self.bridge.activate(b, life["life_id"], lock["lock_ref"])
        self.bindings[b["member_id"]] = b
        self.lives[b["member_id"]] = life["life_id"]
        return fighter


def intent(b, life, sequence="1", say=None):
    return {**{k: copy.deepcopy(b[k]) for k in ("context", "grant_id", "session_key_id",
        "member_id", "nft_token_id", "persona_digest", "slot_id", "generation")},
        "domain": "room.control.v1", "sequence": sequence, "life_id": life, "kind": "intent",
        "payload": {"fighter_id": b["nft_token_id"], "focus": None, "avoid": None,
                    "loot": "ignore", "sig": "hold", "leave": False, "say": say},
        "signature": "A" * 86}


class FrozenBridge(unittest.TestCase):
    def setUp(self):
        self.contract = contract_module()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def arena(self, **kwargs):
        def profile(b):
            house = b["nft_token_id"] in sim.DEFAULT_RULES["house"]
            row = sim.DEFAULT_RULES["house"].get(b["nft_token_id"])
            return {"house": house, "public_name": b["nft_token_id"], "model": "local",
                    "style": row["style"] if house else "brawler", "bag": {},
                    "loadout": sim.rules_dict(row["kit"] if house else sim.DEFAULT_RULES["default_loadout"])}
        return server.Arena(context(), [1, 2, 3, 4, 5], data_dir=self.directory.name,
            room_factory=kwargs.pop("room_factory", lambda bridge: RoomFake(bridge, self.contract)), profile_provider=profile,
            identity_resolver=lambda p: {"owner": self.owner(), "play_status": "eligible",
                "chain_height": "1", "sale_control_allowed": True},
            receipt_signer=lambda r: {**r, "key_id": "local", "signature": "A" * 86},
            admission_gate=lambda: True, life_guard=lambda b: True, server_time_ms=lambda: 1000,
            **kwargs)

    def owner(self):
        return {"context": context(), "account_id": "a.test", "nft_token_id": "a",
                "persona_digest": "a" * 64, "ownership_kind": "owner",
                "custody_reservation_id": None, "checked_at": "1000"}

    def test_copied_service_constructor_receives_the_host_bridge(self):
        slots, identity, ready = object(), object(), lambda: True
        seen, contract = [], self.contract
        class ServiceFake(RoomFake):
            def __init__(self, slots, bridge, identity, *, ready):
                seen.append((slots, bridge, identity, ready))
                super().__init__(bridge, contract)
        package, module = types.ModuleType("room"), types.ModuleType("room.service")
        module.RoomService = ServiceFake
        with patch.dict(sys.modules, {"room": package, "room.service": module}):
            factory = server.room_service_factory(slots, identity, ready=ready)
            arena = self.arena(room_factory=factory)
            self.assertEqual(seen, [(slots, arena.bridge, identity, ready)])
            self.assertEqual(arena.control.request("GET", "/room/tick", ip="spectator")["tick"], "0")
            # A service with a different constructor cannot be silently adapted.
            module.RoomService = lambda slots, identity: None
            with self.assertRaises(TypeError):
                server.room_service_factory(slots, identity)(arena.bridge)

    def test_callbacks_match_frozen_types_and_receipts_bind_unsigned_bytes(self):
        arena = self.arena()
        room, b = arena.room, binding("a")
        # Proof fixture comes from the closed wire example, with this deployment context.
        schema = None
        if self.contract:
            schema_path = Path(self.contract.__file__).with_name("protocol.schema.json")
            schema = json.loads(schema_path.read_bytes())
        proof = copy.deepcopy(schema["$defs"]["JoinRequest"]["examples"][0]) if schema else {"context": context()}
        proof["context"] = context()
        room.bridge.resolve_identity(proof)
        room.admit_fixture(b)
        arena.advance(4)
        message = intent(b, room.lives["a"], say="line\n雪\\n")
        receipt = room.frame("a", json.dumps(message).encode())
        # Use the frozen literal signing vector to establish the canonical digest.
        if schema:
            vector = next(v for v in schema["x-signing-examples"] if v["name"] == "IntentRequest")
            expected = hashlib.sha256(vector["canonical_utf8"].encode()).hexdigest()
            self.assertEqual(server.control_digest(vector["message"]), expected)
        text = '{"payload":{"say":"line\\u000a雪\\\\n"}}'
        self.assertEqual(server.control_digest({"payload": {"say": "line\n雪\\n"}, "signature": "unused"}),
                         hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(receipt["request_digest"], server.control_digest(message))
        other_signature = {**message, "signature": "B" * 86}
        self.assertEqual(room.bridge.apply(b, other_signature), receipt)
        wrong = copy.deepcopy(message)
        wrong["kind"] = "prediction"
        with self.assertRaises(AssertionError):
            room.bridge.apply(b, wrong)
        with self.assertRaises(TypeError):
            room.bridge.activate(b, room.lives["a"])
        room.bridge.sale_control(self.owner(), "lock", "sale-request")
        self.assertEqual(set(room.bridge.calls), {"resolve_identity", "reserve_life", "lock_prediction",
            "activate", "observe", "apply", "sale_control"} - {"observe"})
        room.bridge.release(b)
        arena.advance(1196)
        sealed = room.bridge.seal("segment:0")
        self.assertEqual(sealed["tick_count"], "1200")
        self.assertEqual(room.bridge.seal("segment:1")["code"], "result_pending")
        room.bridge.observe(None)
        self.assertEqual(set(room.bridge.calls), {"resolve_identity", "reserve_life", "lock_prediction",
            "activate", "observe", "apply", "release", "sale_control", "seal"})

    def test_all_sources_share_one_ingress_and_cannot_tick(self):
        arena = self.arena()
        house = sorted(sim.DEFAULT_RULES["house"])[0]
        for name in ("browser", "harness", house):
            arena.room.admit_fixture(binding(name, house=name == house))
        arena.advance(4)
        for name in ("browser", "harness", house):
            self.assertEqual(arena.control.frame(name, json.dumps(intent(
                arena.room.bindings[name], arena.room.lives[name])).encode())["state"], "accepted")
            self.assertEqual(arena.control.frame(name, b'{"kind":"tick"}')["code"], "bad_message")
        self.assertEqual(arena.sim.state["tick"], 4)
        self.assertEqual(len(arena.room.frames), 6)
        self.assertFalse(hasattr(arena.control, "bridge"))
        self.assertFalse(hasattr(arena.control, "maintain"))
        self.assertEqual(arena.control.request("GET", "/room/tick", ip="spectator")["tick"], "4")

    def test_fixed_clock_and_grant_scoped_life_notifications(self):
        rules = sim.rules_dict(sim.DEFAULT_RULES)
        rules["segment_ticks"] = 1199
        ctx = {**context(), "rules_hash": sim.digest(rules)}
        with self.assertRaisesRegex(ValueError, "20 Hz.*1200"):
            server.Arena(ctx, [1], rules=rules, data_dir=self.directory.name + "/wrong")
        arena = self.arena()
        b = binding("a")
        arena.room.admit_fixture(b)
        arena.advance(4)
        before = arena.room.maintenance
        arena.sim.state["events"] = [{"kind": "ko", "fighter": "a", "source": None}]
        self.assertEqual(arena._collect_events(), [b["grant_id"]])
        self.assertEqual(arena.room.boundaries, [])
        arena.advance()
        self.assertEqual(arena.room.maintenance, before + 1)

    def test_boundary_kos_are_sealed_before_reserving_callbacks(self):
        # Ordinary logged joins and engine phases produce two deaths on tick1200.
        rules = sim.rules_dict(sim.DEFAULT_RULES)
        rules.update(hitVarPct=0, base_hp=1, spawn_shield_ticks=0, view_radius=100000)
        rules["weapons"]["swing"].update(damage=10000, range=100000, half_arc=180)
        ctx = {**context(), "rules_hash": sim.digest(rules)}
        observations, reservations = [], []

        class ReservingRoom(RoomFake):
            def life_boundary(room, grant_id):
                super().life_boundary(grant_id)
                # Capture the durable result BEFORE reserve_life can seal/open.
                observations.append(room.bridge.seal("segment:0"))
                b = next(b for b in room.bindings.values() if b["grant_id"] == grant_id)
                reservations.append(room.bridge.reserve_life(b))

        def make(recover=False):
            return server.Arena(ctx, [1, 2, 3], rules=rules, data_dir=self.directory.name,
                room_factory=lambda bridge: ReservingRoom(bridge, self.contract),
                profile_provider=lambda b: {"house": False, "public_name": b["nft_token_id"],
                    "model": "fixture", "style": "brawler", "bag": {},
                    "loadout": rules["default_loadout"]},
                identity_resolver=lambda p: {"play_status": "eligible"},
                receipt_signer=lambda r: {**r, "key_id": "local", "signature": "A" * 86},
                admission_gate=lambda: True, life_guard=lambda b: True,
                server_time_ms=lambda: 1000, recover=recover)

        arena = make()
        arena.advance(1197)
        for name in ("a", "b"):
            arena.room.admit_fixture({**binding(name), "context": copy.deepcopy(ctx)})
        arena.advance(3)
        expected_lives = ["a:life:0", "b:life:0"]
        self.assertEqual([e["fighter"] for e in arena.sim.state["events"] if e["kind"] == "ko"], ["a", "b"])
        self.assertEqual(arena.room.boundaries, [binding(name)["grant_id"] for name in ("a", "b")])
        self.assertEqual([row.get("life_ids") for row in observations], [expected_lives, expected_lives])
        sealed = arena.bridge.seal("segment:0")
        self.assertEqual(sealed["life_ids"], expected_lives)
        self.assertEqual([r["life_id"] for r in reservations], ["a:life:1", "b:life:1"])
        self.assertEqual(arena.segment_id, "segment:1")
        self.assertEqual(arena.completed_lives, [])
        self.assertEqual(server.replay_segment(arena.store.segment("segment:0"), rules).state_hash(),
                         sealed["final_state_hash"])
        restored = make(recover=True)
        self.assertEqual(restored.bridge.seal("segment:0"), sealed)
        self.assertEqual(restored.segment_id, "segment:1")
        self.assertEqual(restored.completed_lives, [])


if __name__ == "__main__":
    unittest.main()
