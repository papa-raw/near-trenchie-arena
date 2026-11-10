"""Portable slot admission cases. Run with python -m unittest room.test_room."""
from concurrent.futures import ProcessPoolExecutor
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import time
import unittest


def persona(name):
    return hashlib.sha256(name.encode()).hexdigest()


COMPUTE = dict(harness="external", model="declared", source="owner", effort="high")


class ProtocolBoundary(unittest.TestCase):
    def test_exported_parser_and_service_share_wire_rules(self):
        from room.protocol import BoundaryError, canonical_bytes, decode, parse_message
        from room.service import DEFAULT_LIMITS, RoomService
        schema = json.loads(Path(__file__).with_name('protocol.schema.json').read_text())
        clock = schema['$defs']['Clock']['examples'][0]
        raw = canonical_bytes(clock)
        self.assertEqual(decode('Clock', raw), clock)
        service = object.__new__(RoomService)
        service.limits = dict(DEFAULT_LIMITS)
        self.assertEqual(service._parse(raw), parse_message(raw))
        for invalid in (b'{"x":1,"x":2}', b'{ "x":1}', b'{"x":1.0}',
                        b'{"x":NaN}', b'[]', b'{"x":"\\ud800"}', b'\xff'):
            with self.subTest(raw=invalid):
                for parser in (parse_message, service._parse):
                    with self.assertRaises(BoundaryError) as caught:
                        parser(invalid)
                    self.assertEqual(caught.exception.code, 'bad_message')
        for raw, limits in ((b'{"x":"large"}', dict(max_control_bytes=2)),
                            (b'{"x":[[1]]}', dict(max_depth=2)),
                            (b'{"x":[1,2]}', dict(max_array_items=1))):
            with self.subTest(limits=limits):
                with self.assertRaises(BoundaryError) as caught:
                    parse_message(raw, **limits)
                self.assertEqual(caught.exception.code, 'rate_limited')
        with self.assertRaises(BoundaryError):
            decode('Clock', canonical_bytes(dict(clock, extra=True)))


def claim_last(directory, member):
    from room.slots import SlotStore
    def clock():
        # Model a slow durable-store read inside the critical section.
        time.sleep(0.03)
        return time.time_ns() // 1_000_000
    return SlotStore(directory, "demo", 1, clock=clock).reserve(member, persona(member))


class SlotRaceAndExpiry(unittest.TestCase):
    def test_transaction_holds_stable_lock(self):
        # A separately opened descriptor cannot acquire this same inode while
        # a transaction calls its clock. This checks exclusion without relying
        # on process scheduling or a probabilistic race window.
        import fcntl
        lock_path = Path(self.tmp.name) / '.slots.lock'
        checked = []
        def clock():
            with lock_path.open('a+') as contender:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
            checked.append(lock_path.stat().st_ino)
            return self.now
        self.store.clock = clock
        reservation = self.store.reserve('alice', persona('alice'))
        self.assertEqual(reservation['state'], 'reserved')
        joined = self.store.join(reservation, COMPUTE)
        self.store.authorize(joined)
        self.store.release(joined)
        self.store.local_fill('1', 'local', persona('local'), COMPUTE, {})
        self.store.local_release('1')
        self.assertGreaterEqual(len(checked), 3)
        self.assertEqual(set(checked), {lock_path.stat().st_ino})
        with lock_path.open('a+') as contender:
            fcntl.flock(contender, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(contender, fcntl.LOCK_UN)

    def setUp(self):
        self.module = importlib.import_module("room.slots")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1_000_000
        self.store = self.module.SlotStore(self.tmp.name, "demo", 1,
                                          clock=lambda: self.now, house_floor=0)

    def fill(self, member="alice", store=None, **kwargs):
        store = store or self.store
        reservation = store.reserve(member, persona(member))
        return store.join(reservation, COMPUTE, **kwargs)

    def test_concurrent_final_slot_and_persona(self):
        # Separate processes and separate store instances contend on one file.
        with ProcessPoolExecutor(max_workers=4) as workers:
            replies = list(workers.map(claim_last, [self.tmp.name] * 8,
                                      ["member-" + str(i) for i in range(8)]))
        self.assertEqual(sum(r["state"] == "reserved" for r in replies), 1)
        self.assertEqual(sum(r["state"] == "spectating" for r in replies), 7)
        manifest = self.module.SlotStore(self.tmp.name, "demo", 1).manifest()
        self.assertEqual(manifest["occupied"], 1)
        other = self.module.SlotStore(Path(self.tmp.name) / "other", "other", 2)
        other.reserve("first", persona("shared"))
        with self.assertRaises(self.module.SlotError):
            other.reserve("second", persona("shared"))

    def test_expired_reservation_and_lease_free_capacity(self):
        offer = self.store.manifest()["offers"][0]
        self.assertEqual(set(offer), {"slot_id", "capability", "expires_at"})
        self.assertEqual(offer["capability"], "fighter")
        old = self.store.reserve("alice", persona("alice"), offer=offer)
        self.assertEqual(self.store.reserve("alice", persona("alice")), old)
        waiting = self.store.reserve("bob", persona("bob"))
        self.assertEqual(waiting["state"], "spectating")
        self.now += 60_001
        self.store.expire()
        current = self.store.reserve("bob", persona("bob"))
        self.assertEqual(current["state"], "reserved")
        with self.assertRaises(self.module.SlotError):
            self.store.join(old, COMPUTE)
        with self.assertRaises(self.module.SlotError):
            self.store.reserve("eve", persona("eve"), offer=offer)
        joined = self.store.join(current, COMPUTE)
        self.now += 30_001
        self.store.expire()
        self.assertEqual(self.store.manifest()["occupied"], 0)
        with self.assertRaises(self.module.SlotError):
            self.store.renew(joined)

    def test_capacity_is_shared_durable_authority(self):
        first = self.fill()
        path = Path(self.tmp.name) / ".slots-state.json"
        before = path.read_bytes()
        for capacity in (2, 16):
            other = self.module.SlotStore(self.tmp.name, "demo", capacity,
                                          clock=lambda: self.now)
            for operation in (
                    other.manifest,
                    lambda: other.local_fill("2", "local", persona("local"), COMPUTE, {}),
                    lambda: other.reserve("bob", persona("bob"))):
                with self.subTest(capacity=capacity, operation=operation):
                    with self.assertRaisesRegex(self.module.SlotError, "context_mismatch"):
                        operation()
                    self.assertEqual(path.read_bytes(), before)
        reopened = self.module.SlotStore(self.tmp.name, "demo", 1, clock=lambda: self.now)
        self.assertEqual(reopened.authorize(first), first)
        self.assertEqual(reopened.manifest()["occupied"], 1)
        self.assertEqual(json.loads(path.read_text())["capacity"], 1)
        # Legacy state has no trustworthy common capacity; fail closed.
        legacy = json.loads(path.read_text())
        legacy.pop("capacity")
        path.write_text(json.dumps(legacy))
        with self.assertRaisesRegex(self.module.SlotError, "context_mismatch"):
            reopened.manifest()

    def test_consumed_offer_retry_preserves_request_context(self):
        offer = self.store.manifest()["offers"][0]
        record = self.store.reserve("alice", persona("alice"), offer=offer)
        self.assertEqual(self.store.reserve("alice", persona("alice"), offer=dict(offer)), record)
        reopened = self.module.SlotStore(self.tmp.name, "demo", 1, clock=lambda: self.now)
        self.assertEqual(reopened.reserve("alice", persona("alice"), offer=offer), record)
        self.assertEqual(reopened.reserve("alice", persona("alice")), record)
        changed = dict(offer, expires_at=str(int(offer["expires_at"]) + 1))
        for member, digest, kwargs in (
                ("alice", persona("other"), dict(offer=offer)),
                ("alice", persona("alice"), dict(offer=changed)),
                ("alice", persona("alice"), dict(slot_id="1", offer=offer)),
                ("bob", persona("bob"), dict(offer=offer))):
            with self.subTest(member=member, kwargs=kwargs):
                with self.assertRaises(self.module.SlotError):
                    reopened.reserve(member, digest, **kwargs)
        self.assertEqual(reopened.manifest()["occupied"], 1)
        self.store.release(record)
        next_offer = self.store.manifest()["offers"][0]
        replacement = self.store.reserve("bob", persona("bob"), offer=next_offer)
        with self.assertRaises(self.module.SlotError):
            self.store.reserve("alice", persona("alice"), offer=offer)
        self.assertEqual(self.store.manifest()["occupied"], 1)
        self.assertNotEqual(replacement["grant"], record["grant"])

    def test_old_generation_cannot_act_renew_or_release(self):
        old = self.fill()
        self.assertEqual(self.store.join(old, COMPUTE), old)
        self.store.release(old)
        replacement = self.fill("bob")
        self.assertGreater(int(replacement["generation"]), int(old["generation"]))
        for operation in (self.store.authorize, self.store.renew, self.store.release,
                          self.store.disconnect, self.store.resume):
            with self.subTest(operation=operation.__name__):
                with self.assertRaises(self.module.SlotError):
                    operation(old)
                with self.assertRaises(self.module.SlotError):
                    operation(dict(replacement, generation=old["generation"]))
        self.assertEqual(self.store.authorize(replacement), replacement)

    def test_reconnect_rotates_authority_without_second_body(self):
        old = self.fill()
        self.now += 1_000
        disconnected = self.store.disconnect(old)
        self.assertEqual(disconnected["state"], "disconnected")
        with self.assertRaises(self.module.SlotError):
            self.store.authorize(old)
        resumed = self.store.resume(old)
        self.assertEqual(resumed["slot_id"], old["slot_id"])
        self.assertEqual(resumed["member_id"], old["member_id"])
        self.assertNotEqual(resumed["grant"], old["grant"])
        self.assertGreater(int(resumed["generation"]), int(old["generation"]))
        with self.assertRaises(self.module.SlotError):
            self.store.authorize(old)
        self.assertEqual(self.store.reserve("alice", persona("alice")), resumed)
        self.assertEqual(self.store.manifest()["occupied"], 1)
        self.store.disconnect(resumed)
        self.now += 30_001
        with self.assertRaises(self.module.SlotError):
            self.store.resume(resumed)

    def test_server_clock_renew_and_closed_compute(self):
        joined = self.fill()
        self.now += 10_000
        renewed = self.store.renew(joined)
        self.assertEqual(int(renewed["lease_until"]), self.now + 30_000)
        self.assertEqual(renewed["generation"], joined["generation"])
        self.store.release(renewed)
        reservation = self.store.reserve("bob", persona("bob"))
        for field in ("command", "environment", "path", "token"):
            with self.subTest(field=field):
                with self.assertRaises(self.module.SlotError):
                    self.store.join(reservation, dict(COMPUTE, **{field: "private"}))

    def test_failed_local_replacement_keeps_authority(self):
        local = self.store.local_fill("1", "local", persona("local"), COMPUTE, {})
        for compute in (dict(COMPUTE, command="ignored"), dict(COMPUTE, effort=None)):
            with self.assertRaises(self.module.SlotError):
                self.store.local_fill("1", "local", persona("local"), compute, {})
            self.assertEqual(self.store.authorize(local), local)
        with self.assertRaises(self.module.SlotError):
            self.store.local_fill("1", "second", persona("second"), COMPUTE, {}, replace=False)
        self.assertEqual(self.store.authorize(local), local)
        self.store.local_release("1")
        replacement = self.store.local_fill("1", "local", persona("local"), COMPUTE, {})
        self.assertGreater(int(replacement["generation"]), int(local["generation"]))
        with self.assertRaises(self.module.SlotError):
            self.store.release(local)
        self.store.disconnect(replacement)
        self.now += 30_001
        self.assertEqual(self.store.manifest()["occupied"], 0)
        with self.assertRaises(self.module.SlotError):
            self.store.resume(replacement)

    def test_expired_house_loses_control_without_midlife_replacement(self):
        house = self.fill("house", house=True)
        self.store.start_life(house)
        self.store.reserve("guest", persona("guest"))
        self.now += 30_001
        self.assertEqual(self.store.reserve("guest", persona("guest"))["state"], "spectating")
        with self.assertRaises(self.module.SlotError):
            self.store.authorize(house)
        self.store.life_boundary(house)
        self.assertEqual(self.store.reserve("guest", persona("guest"))["state"], "reserved")

    def test_house_release_waits_for_life_boundary(self):
        house = self.fill("house", house=True)
        self.store.start_life(house)
        self.store.reserve("guest", persona("guest"))
        self.store.release(house)
        self.assertEqual(self.store.reserve("guest", persona("guest"))["state"], "spectating")
        with self.assertRaises(self.module.SlotError):
            self.store.authorize(house)
        self.store.life_boundary(house)
        self.assertEqual(self.store.reserve("guest", persona("guest"))["state"], "reserved")

    def test_fifo_spectators_and_house_yield_between_lives(self):
        house = self.fill("house", house=True)
        self.store.start_life(house)
        first = self.store.reserve("first", persona("first"))
        self.store.reserve("second", persona("second"))
        self.assertEqual(first["state"], "spectating")
        self.assertTrue(self.store.spectate()["read_only"])
        self.assertEqual(self.store.authorize(house)["member_id"], "house")
        self.assertEqual(self.store.manifest()["occupied"], 1)
        self.store.life_boundary(house)
        admitted = self.store.reserve("first", persona("first"))
        self.assertEqual(admitted["state"], "reserved")
        self.assertEqual(self.store.reserve("late", persona("late"))["state"], "spectating")
        self.store.release(admitted)
        self.assertEqual(self.store.reserve("second", persona("second"))["state"], "reserved")
        with self.assertRaises(self.module.SlotError):
            self.store.authorize(house)

    def test_capacity_sixteen_and_house_floor(self):
        arena = self.module.SlotStore(Path(self.tmp.name) / "arena", "arena", 16,
                                     clock=lambda: self.now)
        members = [self.fill("p" + str(i), store=arena, house=(i < 2))
                   for i in range(16)]
        self.assertEqual(arena.reserve("overflow", persona("overflow"))["state"], "spectating")
        arena.start_life(members[0])
        arena.life_boundary(members[0])
        self.assertEqual(arena.authorize(members[0])["member_id"], "p0")
        self.assertEqual(arena.manifest()["occupied"], 16)
        arena.set_eligible("overflow", False)
        arena.reserve("eligible", persona("eligible"))
        arena.release(members[-1])
        self.assertEqual(arena.reserve("eligible", persona("eligible"))["state"], "reserved")


class _ServiceHost:
    """In-process host fixture, with no transport, signing key or chain access."""

    def __init__(self, cases):
        self.cases = cases
        self.calls = []
        self.owners = {}
        self.status = {}
        self.reservations = {}
        self.locks = {}
        self.bindings = {}
        self.tick = 40

    def resolve_identity(self, request):
        from copy import deepcopy
        self.calls.append("resolve_identity")
        challenge = request.get("challenge", request)
        account, token = challenge["account_id"], challenge["nft_token_id"]
        proof = request.get("proof", request.get("wallet_proof"))
        if proof is not None and proof["proof_bytes"] != "AA":
            return self.cases.error("proof_required")
        if self.status.get(token) == "unknown":
            return self.cases.error("ownership_unavailable")
        owner = dict(context=deepcopy(self.cases.context), account_id=self.owners.get(token, account),
                     nft_token_id=token, persona_digest=challenge.get("persona_digest", persona(token)),
                     ownership_kind="owner", custody_reservation_id=None, checked_at=str(self.cases.now))
        return dict(owner=owner, play_status=self.status.get(token, "eligible"),
                    chain_height="10", sale_control_allowed=True)

    def reserve_life(self, binding):
        from copy import deepcopy
        self.calls.append("reserve_life")
        token = binding["nft_token_id"]
        life = self.reservations.setdefault(token, dict(binding=deepcopy(binding),
                  life_id="life-" + token, prediction_deadline=str(self.cases.now + 30_000)))
        life["binding"] = deepcopy(binding)
        return deepcopy(life)

    def lock_prediction(self, binding, life_id, pick):
        self.calls.append("lock_prediction")
        if life_id in self.locks:
            return self.cases.error("prediction_closed")
        from room.policy import digest
        lock = dict(life_id=life_id, lock_ref="lock-" + life_id,
                    state="none" if pick is None else "prediction",
                    prediction_hash=None if pick is None else digest(pick, exclude=("signature",)),
                    ledger_index="1", locked_before_start=True)
        self.locks[life_id] = lock
        return dict(lock)

    def activate(self, binding, life_id, lock_ref):
        self.calls.append("activate")
        if self.locks.get(life_id, {}).get("lock_ref") != lock_ref:
            return self.cases.error("prediction_closed")
        result = dict(binding=binding, life_id=life_id, lock_ref=lock_ref,
                      fighter_id="fighter-" + binding["nft_token_id"], start_tick=str(self.tick))
        self.bindings[binding["nft_token_id"]] = result
        return result

    def observe(self, binding):
        snapshot = self.cases.example("PublicSnapshot")
        snapshot.update(context=self.cases.context, fighters=[], items=[], projectiles=[], telegraphs=[], actions=[])
        snapshot["clock"].update(context=self.cases.context, tick=str(self.tick))
        return snapshot

    def apply(self, binding, request):
        self.calls.append("apply")
        receipt = self.cases.example("Receipt")
        receipt.update(context=self.cases.context, grant_id=binding["grant_id"],
                       session_key_id=binding["session_key_id"], owner=None,
                       sequence=request["sequence"], message_domain=request["domain"],
                       request_digest=self.cases.policy.digest(request, exclude=("signature",)),
                       prediction_lock=None, boundary=None, applied_tick=str(self.tick))
        return receipt

    def release(self, binding):
        self.calls.append("release")
        return dict(binding=binding, last_sequence="1", revoked=True,
                    boundary=dict(kind="released", life_id=None, segment_id=None, not_before_ms=None))

    def sale_control(self, owner, action, request_id):
        self.calls.append("sale_control")
        ack = self.cases.example("SaleAcknowledgement")
        ack.update(context=self.cases.context, owner=owner, action=action, request_id=request_id)
        return ack

    def seal(self, segment_id):
        self.calls.append("seal")
        return self.cases.error("result_pending")


class RoomServiceCases(unittest.TestCase):
    """Admission order, hostile-member, traffic and eight-verb cases."""

    def setUp(self):
        self.module = importlib.import_module("room.service")
        self.policy = importlib.import_module("room.policy")
        self.schema = json.loads((Path(__file__).parent / "protocol.schema.json").read_text())
        self.context = self.example("MainnetContext")
        self.now = 1_900_000_000_000
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = importlib.import_module("room.slots").SlotStore(
            self.tmp.name, self.context["room_id"], 16, clock=lambda: self.now, house_floor=0)
        self.host = _ServiceHost(self)
        self.durable = []
        identity = importlib.import_module("room.identity")
        self.identity = identity.IdentityAuthority(
            self.context, self.host, now_ms=lambda: self.now,
            sign=lambda *args: "A" * 86,
            verify_session=lambda *args: args[-1] != "B" * 85 + "A",
            key_id="room_key_a", proof_methods=["wallet_digest_v1"],
            ready=lambda: True,
            consume_nonce=lambda *args: self.durable.append(args) or True)
        self.service = self.module.RoomService(
            self.store, self.host, self.identity, now_ms=lambda: self.now,
            ready=lambda: True, admission_open=lambda: True, records=self,
            security_event=lambda event: self.durable.append(event) or True)
        self.known = {}

    def example(self, name):
        from copy import deepcopy
        return deepcopy(self.schema["$defs"][name]["examples"][0])

    def error(self, code):
        return dict(type="error", code=code, request_id=None, retry_after_ms=None)

    def result(self, segment_id):
        return self.error("result_pending")

    def replay(self, segment_id, after_index=None):
        page = self.example("ReplayPage")
        page.update(context=self.context, segment_id=segment_id, input_events=[], next_index=None)
        return page

    def page(self, after_index=None):
        page = self.example("LedgerPage")
        page.update(context=self.context, events=[], next_index=None)
        return page

    def wire(self, message):
        return self.policy.canonical_bytes(message)

    def challenge(self, name, *, ip=None, request_id=None):
        request = self.example("JoinChallengeRequest")
        request.update(context=self.context, account_id=name + ".near", nft_token_id=name,
                       persona_digest=persona(name), request_id=request_id or "request-" + name)
        return self.service.request("POST", "/room/challenge", self.wire(request), ip=ip or name)

    def join_request(self, name, *, challenge=None, ip=None, request_id=None):
        request = self.example("JoinRequest")
        request.update(context=self.context, challenge=challenge or self.challenge(name, ip=ip, request_id=request_id),
                       persona_digest=persona(name), request_id=request_id or "request-" + name)
        return request

    def join(self, name, **kwargs):
        request = self.join_request(name, **kwargs)
        response = self.service.request("POST", "/room/join", self.wire(request), ip=kwargs.get("ip") or name)
        self.known[name] = (request, response)
        return response

    def control(self, grant, kind, sequence="1", **changes):
        from copy import deepcopy
        names = dict(intent="IntentRequest", prediction="PredictionRequest", observe="ObserveRequest",
                     renew="RenewRequest", leave="LeaveRequest")
        request = self.example(names[kind])
        for key in ("context", "grant_id", "session_key_id", "member_id", "nft_token_id",
                    "persona_digest", "slot_id", "generation"):
            request[key] = deepcopy(grant[key])
        request["sequence"] = sequence
        if kind in ("intent", "prediction"):
            request["life_id"] = "life-" + grant["nft_token_id"]
        if kind == "intent":
            request["payload"].update(fighter_id="fighter-" + grant["nft_token_id"], say=None)
        request.update(changes)
        return request

    def connect(self, grant, ip="socket"):
        challenge = self.service.open_control(ip=ip, origin="https://arena.example")
        request = self.example("ControlAuthenticate")
        for key in ("context", "grant_id", "session_key_id", "member_id", "nft_token_id",
                    "persona_digest", "slot_id", "generation", "token"):
            request[key] = grant[key]
        request.update(challenge=challenge, request_id="auth-" + challenge["connection_id"])
        response = self.service.frame(challenge["connection_id"], self.wire(request))
        self.assertEqual(response.get("type"), "control_ready", response)
        return challenge["connection_id"]

    def assert_code(self, response, code):
        self.assertEqual(response.get("code"), code, response)
        self.assertNotIn("token", response)

    def test_admission_retry_fifo_spectators_and_expiry(self):
        grants = [self.join("member" + str(i)) for i in range(16)]
        self.assertTrue(all(g.get("state") == "accepted" for g in grants), grants)
        first = self.join("first")
        second = self.join("second")
        self.assertEqual((first["status"], first["position"], second["position"]), ("spectating", "1", "2"))
        self.assertNotIn("token", first)
        connection = self.connect(grants[-1])
        leave = self.control(grants[-1], "leave")
        self.assertEqual(self.service.frame(connection, self.wire(leave))["state"], "accepted")
        request = self.known["first"][0]
        admitted = self.service.request("POST", "/room/join", self.wire(request), ip="first")
        self.assertEqual(admitted["state"], "accepted")
        self.assertEqual(self.store.manifest()["occupied"], 16)
        retry = self.service.request("POST", "/room/join", self.wire(request), ip="first")
        self.assertEqual(retry, admitted)
        self.now += 60_001
        self.store.expire()
        self.assertLess(self.store.manifest()["occupied"], 16)

    def test_challenge_binding_expiry_and_proof_refusal(self):
        from copy import deepcopy
        request = self.join_request("alice")
        bad = deepcopy(request)
        bad["proof"]["proof_bytes"] = "AQ"
        self.assert_code(self.service.request("POST", "/room/join", self.wire(bad), ip="bad"), "proof_required")
        other = self.join_request("bob")
        other["challenge"]["persona_digest"] = persona("other")
        self.assert_code(self.service.request("POST", "/room/join", self.wire(other), ip="other"), "proof_required")
        expired = self.join_request("carol")
        self.now += 60_001
        self.assert_code(self.service.request("POST", "/room/join", self.wire(expired), ip="carol"), "proof_required")
        self.assertEqual(self.store.manifest()["occupied"], 0)

    def test_join_changed_retry_and_resume_rotate_generation(self):
        from copy import deepcopy
        grant = self.join("alice")
        original = self.known["alice"][0]
        changed = deepcopy(original)
        changed["declared_compute"]["model"] = "other-model"
        self.assert_code(self.service.request("POST", "/room/join", self.wire(changed), ip="retry"), "request_conflict")
        connection = self.connect(grant)
        self.service.close_control(connection)
        fresh = self.join_request("alice", ip="resume", request_id="resume-alice")
        fresh["resume"] = dict(prior_grant_id=grant["grant_id"], prior_generation=grant["generation"], resume_token=grant["token"])
        resumed = self.service.request("POST", "/room/join", self.wire(fresh), ip="resume")
        self.assertEqual(resumed["slot_id"], grant["slot_id"])
        self.assertNotEqual(resumed["generation"], grant["generation"])
        self.assertNotEqual(resumed["token"], grant["token"])
        self.assertEqual(self.store.manifest()["occupied"], 1)
        self.assert_code(self.service.frame(connection, self.wire(self.control(grant, "renew"))), "proof_required")

    def test_hostile_member_closed_fields_signatures_and_own_subject(self):
        from copy import deepcopy
        grant = self.join("alice")
        connection = self.connect(grant)
        prediction = self.control(grant, "prediction")
        self.assertEqual(self.service.frame(connection, self.wire(prediction))["state"], "accepted")
        intent = self.control(grant, "intent", "2")
        for field, value in (("command", "../../host"), ("clock", "1200"), ("winner", True)):
            bad = dict(intent, **{field: value})
            self.assert_code(self.service.frame(connection, self.wire(bad)), "bad_message")
        bad = deepcopy(intent)
        bad["payload"]["fighter_id"] = "fighter-bob"
        self.assert_code(self.service.frame(connection, self.wire(bad)), "stale_slot")
        bad = dict(intent, signature="B" * 85 + "A")
        self.assert_code(self.service.frame(connection, self.wire(bad)), "proof_required")
        self.assertNotIn("apply", self.host.calls)
        intent["sequence"] = "3"
        self.assertEqual(self.service.frame(connection, self.wire(intent))["state"], "accepted")
        self.assertEqual(self.host.calls.count("apply"), 1)

    def test_current_authority_checked_before_cached_receipt(self):
        grant = self.join("alice")
        connection = self.connect(grant)
        request = self.control(grant, "renew")
        first = self.service.frame(connection, self.wire(request))
        self.assertEqual(first["state"], "accepted")
        self.assertEqual(self.service.frame(connection, self.wire(request)), first)
        self.host.owners["alice"] = "buyer.near"
        self.assert_code(self.service.frame(connection, self.wire(request)), "proof_required")
        self.assertEqual(self.host.calls.count("apply"), 0)

    def test_server_time_renew_and_immediate_leave(self):
        grant = self.join("alice")
        connection = self.connect(grant)
        self.now += 10_000
        renewal = self.control(grant, "renew", payload={"lease_until": "18446744073709551615"})
        self.assertEqual(self.service.frame(connection, self.wire(renewal))["state"], "accepted")
        record = self.store.reserve(grant["member_id"], grant["persona_digest"])
        self.assertEqual(record["lease_until"], str(self.now + 30_000))
        self.assertEqual(self.service.frame(connection, self.wire(self.control(grant, "leave", "2")))["state"], "accepted")
        self.assertEqual(self.store.manifest()["occupied"], 0)
        self.assertEqual(self.host.calls.count("release"), 1)
        self.assert_code(self.service.frame(connection, self.wire(renewal)), "proof_required")

    def test_eight_verbs_and_read_query_allowlist(self):
        for path, expected in (("/room", "manifest"), ("/room/observe", "snapshot"),
                               ("/room/tick", "clock"), ("/room/limits", "limits"),
                               ("/room/replay?segment_id=segment_a", "replay"), ("/room/ledger", "ledger")):
            self.assertEqual(self.service.request("GET", path, ip="reader")["type"], expected)
        self.assert_code(self.service.request("GET", "/room/result?segment_id=segment_a", ip="reader"), "result_pending")
        for path in ("/room/tick?advance=1200", "/room/tick?segment_id=segment_a", "/room/result",
                     "/room/ledger?segment_id=segment_a", "/room/replay?segment_id=a&segment_id=b",
                     "/room/replay?segment_id=segment_a&after_index=01", "/room/../../secret"):
            self.assert_code(self.service.request("GET", path, ip="reader"), "bad_message")
        self.assert_code(self.service.request("GET", "/room", b"{}", ip="reader"), "bad_message")
        self.assert_code(self.service.request("POST", "/room/tick", b"{}", ip="reader"), "bad_message")
        self.assertEqual(self.host.tick, 40)

    def test_traffic_size_depth_array_duplicate_and_canonical_guards(self):
        messages = (b" " * 16_385, b"[" * 40 + b"0" + b"]" * 40,
                    b"[" + b",".join([b"0"] * 257) + b"]", b'{"a":1,"a":2}',
                    b'{"value":NaN}', b'{"value":1.0}', b'{ "a": 1 }', b'"\\ud800"')
        for raw in messages:
            with self.subTest(raw=raw[:40]):
                response = self.service.request("POST", "/room/challenge", raw, ip="oversize")
                self.assertIn(response.get("code"), ("bad_message", "rate_limited"))
        self.assertEqual(self.host.calls, [])
        self.assertEqual(self.service.request("GET", "/room/limits", ip="legal")["type"], "limits")

    def test_traffic_per_account_and_ip_before_chain_work(self):
        for i in range(5):
            self.challenge("attacker" + str(i), ip="shared")
        self.assert_code(self.challenge("sixth", ip="shared"), "rate_limited")
        for i in range(5):
            self.challenge("same", ip="source" + str(i), request_id="attempt" + str(i))
        self.assert_code(self.challenge("same", ip="new", request_id="attempt6"), "rate_limited")
        self.assertEqual(self.host.calls, [])
        legal = self.join("legal")
        self.assertEqual(legal["state"], "accepted")
        self.assertEqual(self.host.calls.count("resolve_identity"), 1)

    def test_control_first_frame_timeout_caps_and_replacement(self):
        grant = self.join("alice")
        first = self.service.open_control(ip="unauth", origin="https://arena.example")
        self.assert_code(self.service.frame(first["connection_id"], self.wire(self.control(grant, "renew"))), "proof_required")
        second = self.service.open_control(ip="timeout", origin="https://arena.example")
        self.now += 10_001
        self.assert_code(self.service.frame(second["connection_id"], b"{}"), "proof_required")
        for _ in range(2):
            self.assertEqual(self.service.open_control(ip="limited", origin=None)["type"], "control_challenge")
        self.assert_code(self.service.open_control(ip="limited", origin=None), "rate_limited")
        self.assert_code(self.service.open_control(ip="bad", origin="null"), "proof_required")
        old = self.connect(grant, ip="old")
        current = self.connect(grant, ip="new")
        self.assert_code(self.service.frame(old, self.wire(self.control(grant, "renew"))), "proof_required")
        self.assertEqual(self.service.frame(current, self.wire(self.control(grant, "renew")))["state"], "accepted")

    def test_intent_rate_and_slow_reader_bounds(self):
        grant = self.join("alice")
        connection = self.connect(grant)
        self.service.frame(connection, self.wire(self.control(grant, "prediction")))
        first = self.service.frame(connection, self.wire(self.control(grant, "intent", "2")))
        self.assertEqual(first["state"], "accepted")
        self.assert_code(self.service.frame(connection, self.wire(self.control(grant, "intent", "3"))), "rate_limited")
        self.now += 2_000
        self.assertEqual(self.service.frame(connection, self.wire(self.control(grant, "intent", "4")))["state"], "accepted")
        for _ in range(50):
            self.service.publish_snapshot()
        self.assertLessEqual(len(self.service.drain_snapshots(connection)), 2)
        self.assertEqual(self.host.calls.count("apply"), 2)
        self.assertEqual(self.host.tick, 40)

    def test_ban_reconnect_and_guest_moderation_refusal(self):
        grant = self.join("alice")
        connection = self.connect(grant)
        bad = dict(self.control(grant, "renew"), kind="ban")
        self.assert_code(self.service.frame(connection, self.wire(bad)), "bad_message")
        self.service.deny(account_id="alice.near", nft_token_id="alice")
        self.assert_code(self.service.frame(connection, self.wire(self.control(grant, "renew"))), "proof_required")
        self.assert_code(self.challenge("alice", ip="banned", request_id="after-ban"), "banned")
        request = self.known["alice"][0]
        self.assert_code(self.service.request("POST", "/room/join", self.wire(request), ip="banned"), "banned")
        self.assertEqual(self.store.manifest()["occupied"], 0)
        self.assertEqual(self.service.request("GET", "/room/observe", ip="viewer")["type"], "snapshot")

    def test_concurrent_final_service_seat_admits_one(self):
        from concurrent.futures import ThreadPoolExecutor
        for index in range(15):
            self.assertEqual(self.join("filled" + str(index))["state"], "accepted")
        requests = [self.join_request(name) for name in ("first", "second")]
        with ThreadPoolExecutor(max_workers=2) as workers:
            replies = list(workers.map(lambda pair: self.service.request(
                "POST", "/room/join", self.wire(pair[1]), ip=pair[0]), zip(("first", "second"), requests)))
        self.assertEqual(sum(reply.get("state") == "accepted" for reply in replies), 1)
        self.assertEqual(sum(reply.get("status") == "spectating" for reply in replies), 1)
        self.assertEqual(self.store.manifest()["occupied"], 16)
        self.assertEqual(self.host.calls.count("reserve_life"), 16)

    def test_closed_admission_and_security_failure_keep_authority_closed(self):
        self.service.admission_open = lambda: False
        self.assert_code(self.challenge("closed"), "admission_closed")
        self.assertEqual(self.service.request("GET", "/room", ip="viewer")["admission"], "closed")
        self.service.admission_open = lambda: True
        self.service.ready = lambda: False
        self.assert_code(self.challenge("recovering"), "recovery_pending")
        self.service.ready = lambda: True
        self.service.security_event = lambda event: False
        self.assert_code(self.join("journal"), "recovery_pending")
        self.assertNotIn("reserve_life", self.host.calls)
        self.assert_code(self.service.open_control(ip="none"), "recovery_pending")
        self.assertEqual(self.service.request("GET", "/room/observe", ip="viewer")["type"], "snapshot")

    def test_resume_keeps_live_body_and_closed_prediction(self):
        grant = self.join("alice")
        connection = self.connect(grant)
        self.assertEqual(self.service.frame(connection, self.wire(self.control(grant, "prediction")))["state"], "accepted")
        self.service.close_control(connection)
        request = self.join_request("alice", ip="fresh", request_id="fresh-alice")
        request["resume"] = dict(prior_grant_id=grant["grant_id"], prior_generation=grant["generation"], resume_token=grant["token"])
        resumed = self.service.request("POST", "/room/join", self.wire(request), ip="fresh")
        self.assertEqual(resumed["state"], "accepted", resumed)
        connection = self.connect(resumed, ip="resumed")
        response = self.service.frame(connection, self.wire(self.control(resumed, "prediction", "2")))
        self.assertEqual(response["state"], "refused")
        self.assertIn(response["code"], ("stale_slot", "prediction_closed"))
        self.assertEqual(self.host.calls.count("activate"), 1)
        self.assertEqual(self.host.calls.count("reserve_life"), 1)
        self.assertEqual(self.store.manifest()["occupied"], 1)

    def test_prediction_deadline_and_private_life_notice_backlog(self):
        grant = self.join("alice")
        connection = self.connect(grant)
        self.now += 20_000
        self.assertEqual(self.service.frame(connection, self.wire(self.control(grant, "renew")))["state"], "accepted")
        self.now += 10_000
        self.service.maintain()
        self.assertEqual(self.host.locks["life-alice"]["state"], "none")
        self.assertEqual(self.host.calls.count("activate"), 1)
        for index in range(17):
            self.host.reservations["alice"] = dict(binding=self.host.bindings["alice"]["binding"],
                life_id="next-" + str(index), prediction_deadline=str(self.now + 30_000))
            self.service.life_boundary(grant["grant_id"])
            if index < 16:
                prediction = self.control(grant, "prediction", str(index + 2), life_id="next-" + str(index))
                self.assertEqual(self.service.frame(connection, self.wire(prediction))["state"], "accepted")
        self.assertEqual(self.service.drain_private(connection), [])
        # The pending life is retained for an authenticated reconnect even when
        # the transport's bounded notice queue had to be closed for resync.
        record = self.store.reserve(grant["member_id"], grant["persona_digest"])
        self.assertEqual(record["state"], "disconnected")

    def test_seventh_prediction_refusal_keeps_clock_and_immutable_lock(self):
        from copy import deepcopy
        activate = self.host.activate
        reserve = self.host.reserve_life

        def reserve_two_seconds(binding):
            value = reserve(binding)
            value["prediction_deadline"] = str(self.now + 2_000)
            self.host.reservations[binding["nft_token_id"]] = deepcopy(value)
            return value

        def six_body_activation(binding, life_id, lock_ref):
            if len(self.host.bindings) >= 6 and binding["nft_token_id"] not in self.host.bindings:
                return self.error("room_full")
            return activate(binding, life_id, lock_ref)

        self.host.reserve_life = reserve_two_seconds
        self.host.activate = six_body_activation
        grants, connections, replies = [], [], []
        for index in range(7):
            grant = self.join("p" + str(index))
            self.assertEqual(grant.get("state"), "accepted", grant)
            connection = self.connect(grant, ip="p" + str(index))
            reply = self.service.frame(connection, self.wire(self.control(grant, "prediction")))
            self.assertEqual(reply["state"], "accepted" if index < 6 else "refused", reply)
            grants.append(grant); connections.append(connection); replies.append(reply)
        self.assertEqual(replies[-1]["code"], "room_full")
        queued = self.service._sessions[grants[-1]["grant_id"]]
        lock, reservation = deepcopy(queued["prediction_lock"]), deepcopy(queued["reserved"])
        self.assertEqual(lock["state"], "prediction")
        tick = self.host.tick
        self.now += 2_001  # Prediction deadline, inside every 30-second slot lease.
        for _ in range(3):
            self.service.maintain()
            self.host.tick += 1  # This fixture host advances only after maintenance returns.
            self.assertFalse(self.service._failed)
            self.assertEqual(len(self.host.bindings), 6)
            self.assertIsNone(queued["fighter"])
            self.assertEqual(queued["prediction_lock"], lock)
            self.assertEqual(queued["reserved"], reservation)
        self.assertEqual(self.service.request("GET", "/room/tick", ip="watcher")["tick"], str(tick + 3))
        self.assertEqual(self.host.calls.count("lock_prediction"), 7)
        self.assertEqual(self.service.frame(connections[-1], self.wire(self.control(grants[-1], "prediction"))), replies[-1])
        self.assertEqual(self.service.frame(connections[-1], self.wire(self.control(grants[-1], "prediction", "2")))["code"], "prediction_closed")
        # Capacity becoming available starts exactly the originally locked life.
        self.host.bindings.pop("p0")
        self.service.maintain()
        self.assertEqual(queued["fighter"]["lock_ref"], lock["lock_ref"])
        self.assertEqual(queued["fighter"]["life_id"], reservation["life_id"])
        self.assertIsNone(queued["reserved"])
        self.assertEqual(self.host.calls.count("lock_prediction"), 7)

    def test_activation_refusals_are_member_local_but_uncertainty_fences(self):
        from copy import deepcopy
        for code in ("room_full", "ownership_unavailable", "stale_slot", "prediction_closed", "recovery_pending"):
            with self.subTest(code=code):
                fixture = RoomServiceCases()
                fixture.setUp()
                self.addCleanup(fixture.doCleanups)
                grant = fixture.join("waiting")
                session = fixture.service._sessions[grant["grant_id"]]
                session["reserved"]["prediction_deadline"] = str(fixture.now + 2_000)
                activate = fixture.host.activate
                fixture.host.activate = lambda *args: fixture.error(code)
                if code == "stale_slot":
                    fixture.host.release = lambda *args: fixture.error("stale_slot")
                fixture.now += 2_001
                if code == "recovery_pending":
                    with self.assertRaisesRegex(fixture.policy.BoundaryError, code):
                        fixture.service.maintain()
                    self.assertTrue(fixture.service._failed)
                    continue
                fixture.service.maintain()
                self.assertFalse(fixture.service._failed)
                if code in {"stale_slot", "prediction_closed"}:
                    self.assertTrue(session["revoked"])
                    self.assertIsNone(session["reserved"])
                    self.assertEqual(fixture.store.manifest()["occupied"], 0)
                    continue
                lock = deepcopy(session["prediction_lock"])
                self.assertEqual(lock["state"], "none")
                fixture.service.maintain()
                self.assertFalse(fixture.service._failed)
                self.assertEqual(session["prediction_lock"], lock)
                self.assertEqual(fixture.host.calls.count("lock_prediction"), 1)
                # A reconnect receives the queued no-answer fence rather than relocking.
                fixture.connect(grant)
                fixture.host.activate = activate
                fixture.service.maintain()
                self.assertIsNone(session["reserved"])
                self.assertEqual(session["fighter"]["lock_ref"], lock["lock_ref"])

        # Authentication after the deadline can itself be the first no-answer attempt.
        fixture = RoomServiceCases()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        grant = fixture.join("late")
        session = fixture.service._sessions[grant["grant_id"]]
        session["reserved"]["prediction_deadline"] = str(fixture.now)
        fixture.host.activate = lambda *args: fixture.error("room_full")
        fixture.connect(grant)
        self.assertFalse(fixture.service._failed)
        self.assertIsNone(session["fighter"])
        self.assertEqual(session["prediction_lock"]["state"], "none")


    def test_unavailable_owner_refresh_preserves_other_member_deadlines(self):
        grants = [self.join(name) for name in ("uncertain", "other")]
        sessions = [self.service._sessions[grant["grant_id"]] for grant in grants]
        for session in sessions:
            session["reserved"]["prediction_deadline"] = str(self.now + 2_000)
        self.host.status["uncertain"] = "unknown"
        self.now += 2_001
        self.service.maintain()
        self.assertFalse(self.service._failed)
        self.assertEqual(set(self.host.bindings), {"other"})
        self.assertIsNone(sessions[0]["prediction_lock"])
        self.assertIsNone(sessions[0]["reserved"])
        self.assertTrue(sessions[0]["revoked"])
        self.assertIsNone(sessions[1]["reserved"])
        with self.assertRaisesRegex(self.policy.BoundaryError, "proof_required"):
            self.identity.grant(grants[0]["grant_id"])
        self.host.status.pop("uncertain")
        self.service.maintain()
        self.assertFalse(self.service._failed)
        self.assertEqual(set(self.host.bindings), {"other"})
        self.assertEqual(self.host.calls.count("lock_prediction"), 1)
        self.assertEqual(self.store.manifest()["occupied"], 1)

    def test_house_yields_only_after_its_life_boundary(self):
        self.service.house_tokens = {"house0", "house1", "house2"}
        grants = [self.join("house" + str(index)) for index in range(3)]
        for index in range(13):
            self.assertEqual(self.join("player" + str(index))["state"], "accepted")
        connection = self.connect(grants[0])
        self.assertEqual(self.service.frame(connection, self.wire(self.control(grants[0], "prediction")))["state"], "accepted")
        queued = self.join("waiting")
        self.assertEqual(queued["status"], "spectating")
        self.assertEqual(self.store.manifest()["occupied"], 16)
        self.assertEqual(self.host.calls.count("release"), 0)
        self.service.life_boundary(grants[0]["grant_id"])
        request = self.known["waiting"][0]
        admitted = self.service.request("POST", "/room/join", self.wire(request), ip="waiting")
        self.assertEqual(admitted["state"], "accepted", admitted)
        self.assertEqual(self.store.manifest()["occupied"], 16)
        self.assertEqual(self.host.calls.count("release"), 1)

    def test_expired_rotated_session_never_releases_replacement(self):
        grant = self.join("alice")
        connection = self.connect(grant)
        self.service.close_control(connection)
        self.now += 10_000
        request = self.join_request("alice", ip="fresh", request_id="fresh-alice")
        request["resume"] = dict(prior_grant_id=grant["grant_id"], prior_generation=grant["generation"], resume_token=grant["token"])
        resumed = self.service.request("POST", "/room/join", self.wire(request), ip="fresh")
        self.assertEqual(resumed["state"], "accepted", resumed)
        self.now += 20_001
        self.service.maintain()
        self.assertEqual(self.host.calls.count("release"), 0)
        self.assertEqual(self.store.manifest()["occupied"], 1)
        self.assertEqual(self.host.bindings["alice"]["binding"]["generation"], resumed["generation"])

    def test_malformed_challenge_purposes_preserve_room_authority(self):
        grant = self.join("member")
        connection = self.connect(grant)
        for index, purpose in enumerate(([], {}, ["join"], None, True, 7, "unknown")):
            with self.subTest(purpose=purpose):
                bad = dict(account_id="attacker" + str(index) + ".near", purpose=purpose)
                self.assert_code(self.service.request("POST", "/room/challenge", self.wire(bad),
                                                      ip="attacker" + str(index)), "bad_message")
                self.assertEqual(self.service.request("GET", "/room", ip="viewer")["admission"], "open")
                renewed = self.service.frame(connection, self.wire(self.control(grant, "renew", str(index + 1))))
                self.assertEqual(renewed.get("state"), "accepted", renewed)

    def test_malformed_control_kinds_preserve_room_authority(self):
        grant = self.join("member")
        connection = self.connect(grant)
        for index, kind in enumerate(([], {}, ["renew"], None, True, 7, "unknown")):
            with self.subTest(kind=kind):
                self.assert_code(self.service.frame(connection, self.wire(dict(kind=kind))), "bad_message")
                self.assertEqual(self.service.request("GET", "/room", ip="viewer")["admission"], "open")
                renewed = self.service.frame(connection, self.wire(self.control(grant, "renew", str(index + 1))))
                self.assertEqual(renewed.get("state"), "accepted", renewed)

    def test_intent_receipt_preserves_bridge_outcome_and_retry(self):
        from copy import deepcopy
        grant = self.join("alice")
        connection = self.connect(grant)
        self.assertEqual(self.service.frame(connection, self.wire(self.control(grant, "prediction")))["state"], "accepted")
        apply = self.host.apply
        for sequence, state, code in ((2, "refused", "stale_slot"), (3, "pending", None), (4, "accepted", None)):
            with self.subTest(state=state):
                self.now += 2_000
                request = self.control(grant, "intent", str(sequence))
                expected = apply(grant, request)
                expected.update(state=state, code=code, applied_tick="40" if state == "accepted" else None,
                                boundary=dict(kind="applied", life_id="life-alice", segment_id=None, not_before_ms=None))
                # The bridge and service may use different signing keys.
                expected["key_id"] = "bridge-key"
                self.host.apply = lambda binding, message: deepcopy(expected)
                response = self.service.frame(connection, self.wire(request))
                for field in ("state", "code", "applied_tick", "boundary", "prediction_lock", "request_digest"):
                    self.assertEqual(response.get(field), expected[field], (field, response))
                self.assertEqual(response["key_id"], "room_key_a")
                self.host.apply = lambda *args: self.fail("cached retry dispatched twice")
                self.assertEqual(self.service.frame(connection, self.wire(request)), response)

    def test_intent_receipt_rejects_wrong_bridge_bindings(self):
        from copy import deepcopy
        grant = self.join("alice")
        connection = self.connect(grant)
        self.assertEqual(self.service.frame(connection, self.wire(self.control(grant, "prediction")))["state"], "accepted")
        apply = self.host.apply
        changes = dict(grant_id="other-grant", session_key_id="other-key",
                       owner=self.example("OwnerBinding"), request_id="other-request", sequence="99",
                       message_domain="room.prediction.v1", request_digest="f" * 64,
                       context=dict(self.context, authority_epoch="2"))
        for sequence, (field, value) in enumerate(changes.items(), 2):
            with self.subTest(field=field):
                self.now += 2_000
                request = self.control(grant, "intent", str(sequence))
                acknowledgement = apply(grant, request)
                acknowledgement[field] = value
                self.host.apply = lambda *args: deepcopy(acknowledgement)
                response = self.service.frame(connection, self.wire(request))
                self.assertEqual(response.get("state"), "refused", response)
                self.assertEqual(response.get("code"), "context_mismatch", response)
                self.assertIsNone(response["applied_tick"])

    def test_member_authority_loss_does_not_block_other_deadlines(self):
        alice, bob = self.join("alice"), self.join("bob")
        connections = [self.connect(grant, ip=grant["nft_token_id"]) for grant in (alice, bob)]
        self.now += 20_000
        for grant, connection in zip((alice, bob), connections):
            self.assertEqual(self.service.frame(connection, self.wire(self.control(grant, "renew")))["state"], "accepted")
        self.host.owners["alice"] = "buyer.near"
        self.now += 10_001
        self.service.maintain()
        self.assertNotIn("life-alice", self.host.locks)
        self.assertEqual(self.host.locks["life-bob"]["state"], "none")
        self.assertEqual(set(self.host.bindings), {"bob"})
        self.assertEqual(self.host.calls.count("release"), 1)
        self.assertEqual(self.store.manifest()["occupied"], 1)
        self.assert_code(self.service.frame(connections[0], self.wire(self.control(alice, "renew", "2"))), "proof_required")
        self.assertTrue(any(isinstance(event, dict) and event["kind"] == "release"
                            and event["binding"]["grant_id"] == alice["grant_id"] for event in self.durable))
        self.service.maintain()
        self.assertEqual(self.host.calls.count("release"), 1)
        self.assertEqual(self.host.calls.count("activate"), 1)
        self.assertEqual(self.service.request("GET", "/room", ip="viewer")["admission"], "open")

    def test_deadline_recovery_uncertainty_keeps_room_fenced(self):
        alice, bob = self.join("alice"), self.join("bob")
        connections = [self.connect(grant, ip=grant["nft_token_id"]) for grant in (alice, bob)]
        self.now += 20_000
        for grant, connection in zip((alice, bob), connections):
            self.assertEqual(self.service.frame(connection, self.wire(self.control(grant, "renew")))["state"], "accepted")
        self.now += 10_001
        self.identity.ready = lambda: False
        with self.assertRaisesRegex(self.policy.BoundaryError, "recovery_pending"):
            self.service.maintain()
        self.identity.ready = lambda: True
        self.assertEqual(self.host.calls.count("activate"), 0)
        self.assertEqual(self.service.request("GET", "/room", ip="viewer")["admission"], "recovery_pending")
        self.assert_code(self.service.frame(connections[1], self.wire(self.control(bob, "renew", "2"))), "recovery_pending")

    def test_offline_sale_lookup_authenticates_without_second_effect(self):
        request = self.example("SaleChallengeRequest")
        request.update(context=self.context, account_id="alice.near", nft_token_id="alice", request_id="sale-alice")
        challenge = self.service.request("POST", "/room/challenge", self.wire(request), ip="sale")
        sale = self.example("SaleControlRequest")
        sale.update(context=self.context, account_id="alice.near", nft_token_id="alice", request_id="sale-alice",
                    challenge=challenge, nonce=challenge["nonce"], expires_at=challenge["expires_at"])
        accepted = self.service.request("POST", "/room/sale-control", self.wire(sale), ip="sale")
        self.assertEqual(accepted["state"], "pending", accepted)
        self.assertEqual(self.store.manifest()["occupied"], 0)
        lookup_challenge = self.example("LookupChallengeRequest")
        lookup_challenge.update(context=self.context, account_id="alice.near", nft_token_id="alice",
            request_id="sale-alice", original_digest=accepted["operation_digest"])
        challenge = self.service.request("POST", "/room/challenge", self.wire(lookup_challenge), ip="lookup")
        lookup = self.example("SaleControlLookup")
        lookup.update(context=self.context, account_id="alice.near", nft_token_id="alice", request_id="sale-alice",
            original_digest=accepted["operation_digest"], challenge=challenge,
            nonce=challenge["nonce"], expires_at=challenge["expires_at"])
        status = self.service.request("POST", "/room/sale-control", self.wire(lookup), ip="lookup")
        self.assertEqual(status["state"], "pending", status)
        self.assertEqual(status["operation_digest"], accepted["operation_digest"])
        self.assertNotEqual(status["authentication_digest"], accepted["authentication_digest"])
        self.assertEqual(self.host.calls.count("sale_control"), 1)
        self.now += 60_001
        self.host.owners["alice"] = "buyer.near"
        challenge = self.service.request("POST", "/room/challenge", self.wire(lookup_challenge), ip="former")
        lookup.update(challenge=challenge, nonce=challenge["nonce"], expires_at=challenge["expires_at"])
        self.assert_code(self.service.request("POST", "/room/sale-control", self.wire(lookup), ip="former"), "proof_required")
        self.assertEqual(self.host.calls.count("sale_control"), 1)


class NamedSlotProof(unittest.TestCase):
    """Internal authority-handle check; fighter ownership needs the bound engine."""

    def test_slot_authority(self):
        from room.slots import SlotStore, SlotError
        with tempfile.TemporaryDirectory() as directory:
            store = SlotStore(directory, "demo", 2, clock=lambda: 1000000)
            alice = store.join(store.reserve("alice", persona("alice")), COMPUTE)
            bob = store.join(store.reserve("bob", persona("bob")), COMPUTE)
            self.assertEqual(store.authorize(alice), alice)
            self.assertEqual(store.authorize(bob), bob)
            for field in ("member_id", "persona_digest", "grant", "generation"):
                forged = dict(alice)
                forged[field] = bob[field] if field != "generation" else "999"
                with self.subTest(field=field):
                    with self.assertRaises(SlotError):
                        store.authorize(forged)
                    self.assertEqual(store.authorize(bob), bob)
            store.release(alice)
            replacement = store.join(store.reserve("replacement", persona("replacement")), COMPUTE)
            self.assertEqual(replacement["slot_id"], alice["slot_id"])
            with self.assertRaises(SlotError):
                store.authorize(alice)
            self.assertEqual(store.authorize(replacement), replacement)


class NamedServiceProof(unittest.TestCase):
    """Named ingress proofs using a synthetic host, without live game claims."""

    # Reuse fixture construction only; unittest must not rediscover the original
    # service cases through inheritance when running these named methods.
    example = RoomServiceCases.example
    error = RoomServiceCases.error
    result = RoomServiceCases.result
    replay = RoomServiceCases.replay
    page = RoomServiceCases.page
    wire = RoomServiceCases.wire
    challenge = RoomServiceCases.challenge
    join_request = RoomServiceCases.join_request
    join = RoomServiceCases.join
    control = RoomServiceCases.control
    connect = RoomServiceCases.connect
    assert_code = RoomServiceCases.assert_code

    def setUp(self):
        RoomServiceCases.setUp(self)

    def admitted(self, name):
        grant = self.join(name)
        self.assertEqual(grant.get("state"), "accepted", grant)
        connection = self.connect(grant, ip="socket-" + name)
        reply = self.service.frame(connection, self.wire(self.control(grant, "prediction")))
        self.assertEqual(reply.get("state"), "accepted", reply)
        return grant, connection

    def test_ownership(self):
        from copy import deepcopy
        alice, connection = self.admitted("alice")
        bob, other = self.admitted("bob")
        for grant, cid in ((alice, connection), (bob, other)):
            self.assertEqual(self.service.frame(cid, self.wire(self.control(grant, "intent", "2")))["state"], "accepted")
        protected = deepcopy(self.host.bindings["bob"])
        self.now += 2000
        forged = self.control(alice, "intent", "3")
        forged["payload"]["fighter_id"] = "fighter-bob"
        self.assert_code(self.service.frame(connection, self.wire(forged)), "stale_slot")
        self.assertEqual(self.host.calls.count("apply"), 2)
        self.assertEqual(self.host.bindings["bob"], protected)

    def test_target(self):
        alice, connection = self.admitted("alice")
        self.admitted("bob")
        legal = self.control(alice, "intent", "2")
        legal["payload"]["focus"] = "fighter-bob"
        self.assertEqual(self.service.frame(connection, self.wire(legal))["state"], "accepted")
        self.now += 2000
        illegal = self.control(alice, "intent", "3")
        illegal["payload"].update(fighter_id="fighter-bob", leave=True)
        self.assert_code(self.service.frame(connection, self.wire(illegal)), "stale_slot")
        self.assertEqual(self.host.calls.count("apply"), 1)

    def test_clock(self):
        alice, connection = self.admitted("alice")
        clock = self.service.request("GET", "/room/tick", ip="reader")
        self.assertEqual((clock["tick_hz"], clock["segment_seconds"], clock["segment_ticks"]), (20, 60, "1200"))
        for sequence in range(2, 10):
            request = self.control(alice, "intent", str(sequence))
            request["tick"] = str(sequence * 1200)
            self.assert_code(self.service.frame(connection, self.wire(request)), "bad_message")
        self.assertEqual(self.host.calls.count("apply"), 0)
        self.assertEqual(self.service.request("GET", "/room/tick", ip="reader"), clock)
        self.assert_code(self.service.request("GET", "/room/tick?advance=1200", ip="reader"), "bad_message")
        self.assertEqual(self.host.tick, 40)

    def test_action_cap(self):
        alice, connection = self.admitted("alice")
        def attempt(sequence):
            request = self.control(alice, "intent", str(sequence))
            request["payload"]["say"] = None
            return self.service.frame(connection, self.wire(request))
        self.assertEqual(attempt(2)["state"], "accepted")
        self.assert_code(attempt(3), "rate_limited")
        self.now += 1999
        self.assert_code(attempt(4), "rate_limited")
        self.now += 1
        self.assertEqual(attempt(5)["state"], "accepted")
        self.assertEqual(self.host.calls.count("apply"), 2)
        self.assertEqual(self.host.tick, 40)

    def test_seat_check(self):
        from copy import deepcopy
        alice, connection = self.admitted("alice")
        self.assertEqual(self.host.bindings["alice"]["binding"]["member_id"], alice["member_id"])
        bad = self.join("bob")
        other = self.connect(bad, ip="bob")
        activate = self.host.activate
        def mismatch(binding, life_id, lock_ref):
            response = deepcopy(activate(binding, life_id, lock_ref))
            response["binding"]["member_id"] = alice["member_id"]
            return response
        self.host.activate = mismatch
        response = self.service.frame(other, self.wire(self.control(bad, "prediction")))
        self.assert_code(response, "stale_slot")
        self.assertIsNone(self.service._sessions[bad["grant_id"]]["fighter"])
        # The other member keeps the original acknowledged body.
        self.assertEqual(self.service.frame(connection, self.wire(self.control(alice, "intent", "2")))["state"], "accepted")

    def test_reach(self):
        self.assertEqual(self.service.request("GET", "/room/limits", ip="reader")["type"], "limits")
        for path in ("/etc/passwd", "/room/../../secret", "/room/members/other", "/engine/control",
                     "/var/run/podman.sock", "https://elsewhere.example/room/limits", "//elsewhere.example/room/limits"):
            self.assert_code(self.service.request("GET", path, ip="reader"), "bad_message")
        self.assertEqual(self.host.calls, [])
        self.assertEqual(self.service.request("GET", "/room/limits", ip="reader")["type"], "limits")

    def test_byte_limit(self):
        raw = self.wire(dict(private="x" * 16384))
        with self.assertRaises(self.policy.BoundaryError) as caught:
            self.service._parse(raw)
        self.assertEqual(caught.exception.code, "rate_limited")
        self.assertEqual(self.service._parse(b'{"ok":true}'), {"ok": True})
        self.assertEqual(self.join("legal")["state"], "accepted")

    def test_canary_outputs(self):
        from copy import deepcopy
        alice, connection = self.admitted("alice")
        bob, other = self.admitted("bob")
        for grant, cid in ((alice, connection), (bob, other)):
            self.assertEqual(self.service.frame(cid, self.wire(self.control(grant, "intent", "2")))["state"], "accepted")
        canary = "PRIVATE_" + persona("per-owner-canary")
        self.service._sessions[alice["grant_id"]]["private_canary"] = canary
        observe = self.host.observe
        def contaminated(binding):
            snapshot = deepcopy(observe(binding))
            snapshot["private"] = dict(prompt=canary, token=canary, player_spend=canary)
            return snapshot
        self.host.observe = contaminated
        public = [self.service.request("GET", path, ip="spectator") for path in
                  ("/room", "/room/observe", "/room/tick", "/room/ledger", "/room/replay?segment_id=segment_a")]
        for cid, grant in ((connection, alice), (other, bob)):
            response = self.service.frame(cid, self.wire(self.control(grant, "observe", "3")))
            self.assertEqual(response["state"], "accepted")
            public += self.service.drain_snapshots(cid)
        public.append(self.service.request("GET", "/room/unknown?private=" + canary, ip="reader"))
        self.assertNotIn(canary, json.dumps(public))
        self.assertEqual(public[1], self.service.request("GET", "/room/observe", ip="other-viewer"))


class ResultReadSecurityCases(unittest.TestCase):
    """Anonymous result reads share bounded replay work and reuse verified seals."""

    def setUp(self):
        import threading
        from room.test_recovery import RecoveryCases
        self.service_fixture = RoomServiceCases()
        self.addCleanup(self.service_fixture.doCleanups)
        self.service_fixture.setUp()
        self.service = self.service_fixture.service
        self.fixture = RecoveryCases()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        f = self.fixture
        self.authority = f.authority()
        # The disposable openssl fixture uses files shared by sign and verify.
        signing_lock = threading.Lock()
        sign, verify = self.authority.signer, self.authority.verifier
        def signed(data):
            with signing_lock:
                return sign(data)
        def verified(*args):
            with signing_lock:
                return verify(*args)
        self.authority.signer, self.authority.verifier = signed, verified
        self.replays = {}
        for number in range(3):
            record, replay = f.record(number)
            f.ledger.seal(record, replay)
            self.replays[record['seed']] = replay
        self.calls = []
        self.replay = lambda record: self.replays[record['seed']](record)
        def counted(record):
            self.calls.append(record['segment_id'])
            return self.replay(record)
        self.reader = f.r.ResultReader(f.ledger, self.authority, counted)
        self.service.records = self.service_fixture.module.RecordReads(f.ledger, self.reader)

    def get(self, segment='segment_0'):
        return self.service.request('GET', '/room/result?segment_id=' + segment, ip='anonymous')

    def test_anonymous_results_share_replay_limit(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        entered = [threading.Event() for _ in range(2)]
        release = threading.Event()
        original = self.replay
        def blocked(record):
            if int(record['seed']) < len(entered):
                entered[int(record['seed'])].set()
                if not release.wait(10):
                    raise RuntimeError('result replay did not release')
            return original(record)
        self.replay = blocked
        with ThreadPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(self.get, 'segment_' + str(i)) for i in range(2)]
            try:
                self.assertTrue(all(event.wait(5) for event in entered))
                self.assertEqual(self.service.limits['max_replays'], 2)
                for _ in range(6):
                    self.assertEqual(self.get('segment_2').get('code'), 'rate_limited')
                page = self.service.request('GET', '/room/replay?segment_id=segment_0', ip='anonymous')
                self.assertEqual(page.get('code'), 'rate_limited')
                public = self.service.request('GET', '/room/observe', ip='anonymous')
                self.assertEqual(public.get('type'), 'snapshot')
            finally:
                release.set()
            for future in futures:
                self.fixture.l.validate('Result', future.result(timeout=5))
        self.assertEqual(len(self.calls), 2)
        self.replay = original
        self.fixture.l.validate('Result', self.get('segment_2'))

    def test_verified_result_cache_keeps_live_authority_and_seal_binding(self):
        from copy import deepcopy
        f = self.fixture
        first = self.get()
        f.l.validate('Result', first)
        first['lives'].clear()
        second = self.get()
        f.l.validate('Result', second)
        self.assertTrue(second['lives'])
        self.assertEqual(self.calls, ['segment_0'])
        # Cached verification never bypasses current key authorization.
        self.authority.key_allowed = lambda key: False
        self.assertEqual(self.get().get('code'), 'proof_required')
        self.authority.key_allowed = lambda key: key == 'key_a'
        f.l.validate('Result', self.get())
        self.assertEqual(self.calls, ['segment_0'])
        # A restored record under the same id needs a new replay for its seal.
        changed, _ = f.record(2)
        changed['segment_id'] = 'segment_0'
        changed['sealed_result_hash'] = f.l.sealed_hash(changed)
        original_sealed = f.ledger.sealed
        f.ledger.sealed = lambda segment: deepcopy(changed) if segment == 'segment_0' else original_sealed(segment)
        self.assertEqual(self.get()['sealed_result_hash'], changed['sealed_result_hash'])
        self.assertEqual(self.calls, ['segment_0', 'segment_0'])
        # Even with an unchanged claimed seal, damaged source bytes must refuse.
        changed['input_events'][0]['tick'] = '1'
        self.assertEqual(self.get().get('code'), 'bad_message')
        f.ledger.sealed = original_sealed
        # A failed replay is never cached and never leaves a permit occupied.
        original_replay = self.replay
        self.replay = lambda record: dict(final_state_hash='f' * 64, lives=[], predictions={})
        self.assertEqual(self.get('segment_1').get('code'), 'bad_message')
        self.replay = original_replay
        f.l.validate('Result', self.get('segment_1'))


class NamedLedgerProof(unittest.TestCase):
    """Local sealed-record and backup checks, without a live referee or chain."""

    def setUp(self):
        from room.test_recovery import RecoveryCases
        self.fixture = RecoveryCases("test_prediction_lock")
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def test_result_at_boundary(self):
        from copy import deepcopy
        f = self.fixture
        record, replay = f.record()
        self.assertEqual(f.l.verify_sealed(record, replay), record)
        for field, value in (("completed", False), ("tick_count", "1199")):
            cut = deepcopy(record)
            cut[field] = value
            # Recompute the digest so only the completeness rule catches it.
            cut["sealed_result_hash"] = f.l.sealed_hash(cut)
            with self.assertRaises(f.l.Refusal):
                f.l.verify_sealed(cut, replay)

    def test_referee_digest(self):
        from copy import deepcopy
        f = self.fixture
        record, replay = f.record()
        self.assertEqual(f.l.verify_sealed(record, replay), record)
        damaged = deepcopy(record)
        original = damaged["sealed_result_hash"]
        damaged["sealed_result_hash"] = ("1" if original[0] != "1" else "2") + original[1:]
        with self.assertRaises(f.l.Refusal):
            f.l.verify_sealed(damaged, replay)
        def disagree(record):
            outcome = replay(record)
            outcome["final_state_hash"] = "f" * 64
            return outcome
        with self.assertRaises(f.l.Refusal):
            f.l.verify_sealed(record, disagree)

    def test_restart_and_restore(self):
        import shutil
        import sqlite3
        f = self.fixture
        record, replay = f.record()
        f.ledger.seal(record, replay)
        backup = f.root / "backup.db"
        shutil.copyfile(f.root / "ledger.db", backup)
        restored = f.l.Ledger(backup, f.context, f.authorize)
        self.assertEqual(restored.sealed(record["segment_id"]), record)
        # A corrupted but parseable backup must fail through the hash-chain
        # check, rather than an unrelated SQLite syntax/I/O exception.
        with sqlite3.connect(backup) as connection:
            connection.execute("DROP TRIGGER immutable_update")
            connection.execute("UPDATE records SET record_hash=? WHERE position=(SELECT MAX(position) FROM records)", ("f" * 64,))
        with self.assertRaises(f.l.Refusal) as caught:
            f.l.Ledger(backup, f.context, f.authorize)
        self.assertEqual(caught.exception.code, "recovery_pending")

class MemberConsentRoutes(unittest.TestCase):
    """New member-only route cases; no inherited suite or live adapters."""

    example = RoomServiceCases.example
    error = RoomServiceCases.error
    result = RoomServiceCases.result
    replay = RoomServiceCases.replay
    page = RoomServiceCases.page
    wire = RoomServiceCases.wire
    challenge = RoomServiceCases.challenge
    join_request = RoomServiceCases.join_request
    join = RoomServiceCases.join
    control = RoomServiceCases.control
    connect = RoomServiceCases.connect
    assert_code = RoomServiceCases.assert_code

    paths = dict(accept_terms="/room/owner/terms/accept",
                 accept_proposal="/room/owner/proposals/accept",
                 decline_proposal="/room/owner/proposals/decline")

    def setUp(self):
        RoomServiceCases.setUp(self)
        self.alice, self.bob = self.join("alice"), self.join("bob")
        self.assertEqual(self.alice.get("state"), "accepted", self.alice)
        self.assertEqual(self.bob.get("state"), "accepted", self.bob)
        # Main baseline has no owner state/routes. Seed the same trusted host
        # inputs here so each red result exercises the missing HTTP route.
        if not hasattr(self.service, "_owner_state"):
            self.service._owner_state = dict(context=self.context,
                terms=dict(version="1", input_interval_ms="2000", segment_ms="60000", simulation_hz=20),
                accepted=[], members=[], proposal=None, moderation=[], requests=[],
                denied_accounts=[], denied_tokens=[], proposal_ids=[])
        self.applied = []
        self.service.owner_apply_terms = lambda terms: self.applied.append(terms) or True
        self.counter = 0

    def request_for(self, action, grant=None, **changes):
        from copy import deepcopy
        grant = self.alice if grant is None else grant
        request = {key: deepcopy(grant[key]) for key in
                   ("context", "grant_id", "session_key_id", "member_id", "nft_token_id",
                    "persona_digest", "slot_id", "generation", "token")}
        self.counter += 1
        request.update(domain="room.owner.v1", kind="owner_control", action=action,
                       request_id="member-write-" + str(self.counter), terms_version="1",
                       payload={} if action == "accept_terms" else {"proposal_id": "change-a"},
                       signature="A" * 86)
        request.update(changes)
        return request

    def post(self, request, path=None):
        return self.service.request("POST", path or self.paths[request["action"]],
                                    self.wire(request), ip="member-write")

    def proposal(self, **changes):
        value = dict(proposal_id="change-a", row="input_interval_ms", current_ms="2000",
                     proposed_ms="3000", effective_version="2", boundary_segment_id="segment-next",
                     required_members=[self.alice["member_id"], self.bob["member_id"]],
                     accepted_members=[], declined_members=[], expires_at=str(self.now + 1000),
                     state="pending")
        value.update(changes)
        self.service._owner_state.setdefault("proposal_ids", []).append(value["proposal_id"])
        self.service._owner_state["proposal"] = value
        return value

    def accepted(self, request, state="accepted"):
        response = self.post(request)
        self.assertEqual(response.get("type"), "owner_response", response)
        self.assertEqual(response["state"], state)
        self.assertEqual(response["request_id"], request["request_id"])
        self.assertEqual(response["request_digest"], self.policy.digest(request, exclude=("signature",)))
        self.assertEqual(response["snapshot"]["viewer_member_id"], request["member_id"])
        self.assertNotIn("token", response)
        return response

    def test_accept_terms_exact_version_and_member_only(self):
        response = self.accepted(self.request_for("accept_terms"))
        self.assertTrue(response["snapshot"]["terms"]["accepted"])
        self.assertEqual(self.service._owner_state["accepted"],
                         [dict(member_id=self.alice["member_id"], version="1")])
        self.assertTrue(any(isinstance(e, dict) and e.get("kind") == "owner_state" for e in self.durable))

    def test_accept_change_waits_for_each_member_and_exact_host_boundary(self):
        proposal = self.proposal()
        self.accepted(self.request_for("accept_proposal"), "pending")
        self.assertEqual(proposal["accepted_members"], [self.alice["member_id"]])
        self.assertFalse(self.service.apply_owner_boundary("segment-next"))
        self.accepted(self.request_for("accept_proposal", self.bob), "pending")
        self.assertFalse(self.service.apply_owner_boundary("segment-old"))
        self.assertEqual(self.service._owner_state["terms"]["version"], "1")
        self.assertEqual(self.applied, [])
        self.assertTrue(self.service.apply_owner_boundary("segment-next"))
        self.assertEqual(self.applied, [dict(version="2", input_interval_ms="3000", segment_ms="60000", simulation_hz=20)])
        self.assertEqual(proposal["state"], "accepted")
        self.assertEqual({r["member_id"] for r in self.service._owner_state["accepted"] if r["version"] == "2"},
                         set(proposal["required_members"]))
        self.assertNotIn("seal", self.host.calls)
        self.assertFalse(self.service.apply_owner_boundary("segment-next"))

    def test_decline_records_own_answer_and_prevents_application(self):
        proposal = self.proposal()
        response = self.accepted(self.request_for("decline_proposal", self.bob))
        self.assertEqual(response["snapshot"]["proposal"]["declined_members"], [self.bob["member_id"]])
        self.assertEqual(proposal["state"], "declined")
        self.assertFalse(self.service.apply_owner_boundary("segment-next"))
        self.assertEqual(self.applied, [])
        self.assertEqual(self.service._owner_state["terms"]["version"], "1")

    def test_all_routes_refuse_non_member_before_replay(self):
        self.proposal()
        for action in self.paths:
            with self.subTest(action=action):
                self.assert_code(self.post(self.request_for(action, grant_id="unknown-grant")), "proof_required")
        self.assertEqual(self.service._owner_state["requests"], [])

    def test_all_routes_refuse_stale_terms_version(self):
        self.proposal()
        for action in self.paths:
            with self.subTest(action=action):
                self.assert_code(self.post(self.request_for(action, terms_version="0")), "version_mismatch")
        self.assertEqual(self.service._owner_state["accepted"], [])

    def test_proposal_routes_refuse_stale_proposal_identity(self):
        self.proposal()
        for action in ("accept_proposal", "decline_proposal"):
            with self.subTest(action=action):
                self.assert_code(self.post(self.request_for(action, payload={"proposal_id": "change-old"})), "not_found")
        self.assertEqual(self.service._owner_state["proposal"]["accepted_members"], [])
        self.assertEqual(self.service._owner_state["proposal"]["declined_members"], [])

    def test_accept_terms_refuses_replayed_and_repurposed_id(self):
        request = self.request_for("accept_terms")
        self.accepted(request)
        self.assert_code(self.post(request), "request_conflict")
        self.proposal()
        changed = dict(request, action="accept_proposal", payload={"proposal_id": "change-a"})
        self.assert_code(self.post(changed), "request_conflict")

    def test_accept_change_refuses_replayed_id_and_second_answer(self):
        self.proposal()
        request = self.request_for("accept_proposal")
        self.accepted(request, "pending")
        self.assert_code(self.post(request), "request_conflict")
        self.assert_code(self.post(self.request_for("accept_proposal")), "request_conflict")
        self.assertEqual(self.service._owner_state["proposal"]["accepted_members"], [self.alice["member_id"]])

    def test_decline_refuses_replayed_id(self):
        self.proposal()
        request = self.request_for("decline_proposal")
        self.accepted(request)
        self.assert_code(self.post(request), "request_conflict")
        self.assertEqual(self.service._owner_state["proposal"]["declined_members"], [self.alice["member_id"]])

    def test_proposal_routes_refuse_answer_at_expiry(self):
        proposal = self.proposal(expires_at=str(self.now))
        for action in ("accept_proposal", "decline_proposal"):
            with self.subTest(action=action):
                self.assert_code(self.post(self.request_for(action)), "version_mismatch")
        self.assertEqual(proposal["state"], "expired")
        self.assertEqual(proposal["accepted_members"], [])
        self.assertEqual(proposal["declined_members"], [])
        self.assertFalse(self.service.apply_owner_boundary("segment-next"))

    def test_each_route_authenticates_expired_grant_before_replay(self):
        self.proposal()
        for action in self.paths:
            with self.subTest(action=action):
                self.assert_code(self.post(self.request_for(action, signature="B" * 85 + "A")), "proof_required")
                self.assert_code(self.post(self.request_for(action, token="C" * 43)), "proof_required")
        # Keep the slot live independently so this tests the grant-expiry fence,
        # rather than the slot-expiry check which deliberately runs first.
        self.now += 1000
        session = self.service._sessions[self.alice["grant_id"]]
        session["record"] = self.store.renew(session["record"])
        self.now += 29001
        self.assertLessEqual(int(self.alice["expires_at"]), self.now)
        self.assertGreater(int(session["record"]["lease_until"]), self.now)
        for action in self.paths:
            with self.subTest(expired=action):
                self.assert_code(self.post(self.request_for(action)), "proof_required")

    def test_each_route_refuses_other_member_binding_and_client_authority(self):
        self.proposal()
        for action in self.paths:
            with self.subTest(action=action):
                self.assert_code(self.post(self.request_for(action, member_id=self.bob["member_id"])), "stale_slot")
                self.assert_code(self.post(self.request_for(action, account_id="bob.near")), "bad_message")
                self.assert_code(self.post(self.request_for(action, effective_boundary="segment-next")), "bad_message")
        self.assertEqual(self.service._owner_state["accepted"], [])

    def test_proposal_routes_refuse_unaffected_member(self):
        self.proposal(required_members=[self.bob["member_id"]])
        for action in ("accept_proposal", "decline_proposal"):
            with self.subTest(action=action):
                self.assert_code(self.post(self.request_for(action)), "proof_required")

    def test_route_action_mismatch_refuses_before_dispatch(self):
        self.proposal()
        for action in self.paths:
            request = self.request_for(action)
            other = self.paths["accept_proposal" if action == "accept_terms" else "accept_terms"]
            with self.subTest(action=action):
                self.assert_code(self.post(request, other), "bad_message")
        self.assertEqual(self.service._owner_state["accepted"], [])

    def test_member_persistence_failure_never_acknowledges(self):
        self.service.security_event = lambda event: False
        response = self.post(self.request_for("accept_terms"))
        self.assert_code(response, "recovery_pending")
        self.assertTrue(self.service._failed)
        self.assert_code(self.post(self.request_for("accept_terms")), "recovery_pending")

    def test_expired_unanimous_proposal_never_applies(self):
        self.proposal()
        self.accepted(self.request_for("accept_proposal"), "pending")
        self.accepted(self.request_for("accept_proposal", self.bob), "pending")
        self.now += 1000
        self.assertFalse(self.service.apply_owner_boundary("segment-next"))
        self.assertEqual(self.applied, [])
        self.assertEqual(self.service._owner_state["terms"]["version"], "1")

    def test_proposal_ids_cannot_be_reused_after_supersession(self):
        options = dict(proposed_ms="3000", boundary_segment_id="segment-next",
                       expires_at=str(self.now + 1000),
                       required_members=[self.alice["member_id"], self.bob["member_id"]])
        self.service.propose_owner_change(proposal_id="change-a", **options)
        self.accepted(self.request_for("decline_proposal"))
        self.service.propose_owner_change(proposal_id="change-b", **options)
        self.accepted(self.request_for("decline_proposal", payload={"proposal_id": "change-b"}))
        with self.assertRaises(self.policy.BoundaryError) as caught:
            self.service.propose_owner_change(proposal_id="change-a", **dict(options, proposed_ms="4000"))
        self.assertEqual(caught.exception.code, "request_conflict")
        self.assertEqual(self.service._owner_state["proposal"]["proposal_id"], "change-b")

    def test_member_answers_and_replay_ids_survive_recovery_with_fresh_grant(self):
        request = self.request_for("accept_terms")
        self.accepted(request)
        checkpoint = self.service.export_owner_state()
        self.service = self.module.RoomService(self.store, self.host, self.identity,
            now_ms=lambda: self.now, ready=lambda: True, admission_open=lambda: True,
            records=self, owner_state=checkpoint,
            security_event=lambda event: self.durable.append(event) or True)
        fresh = self.join("alice", request_id="rejoin-alice")
        self.assertEqual(fresh.get("state"), "accepted", fresh)
        self.assertNotEqual(fresh["grant_id"], self.alice["grant_id"])
        retry = self.request_for("accept_terms", fresh, request_id=request["request_id"])
        self.assert_code(self.post(retry), "request_conflict")
        self.assertIn(dict(member_id=fresh["member_id"], version="1"), self.service._owner_state["accepted"])

    def test_corrupt_recovered_proposal_cannot_collect_an_answer(self):
        self.proposal(accepted_members=["outside-member"])
        self.assert_code(self.post(self.request_for("accept_proposal")), "recovery_pending")
        self.assertEqual(self.applied, [])

    def test_unaccepted_new_terms_fence_background_activation_and_input(self):
        self.service._owner_state["terms"].update(version="2", input_interval_ms="3000")
        binding = self.service._sessions[self.alice["grant_id"]]["binding"]
        with self.assertRaises(self.policy.BoundaryError) as caught:
            self.service._owner_control_consent(binding)
        self.assertEqual(caught.exception.code, "version_mismatch")
        session = self.service._sessions[self.alice["grant_id"]]
        with self.assertRaises(self.policy.BoundaryError) as caught:
            self.service._activate(session, None)
        self.assertEqual(caught.exception.code, "version_mismatch")
        self.assertNotIn("activate", self.host.calls)
        self.service._activate_when_ready(session)
        self.assertIsNotNone(session["reserved"])
        self.assertFalse(self.service._failed)
        connection = self.connect(self.alice)
        prediction = self.control(self.alice, "prediction")
        self.assert_code(self.service.frame(connection, self.wire(prediction)), "version_mismatch")
        self.accepted(self.request_for("accept_terms", terms_version="2"))
        self.service._owner_control_consent(binding)

    def test_boundary_application_failure_fences_writes_without_success(self):
        self.proposal()
        self.accepted(self.request_for("accept_proposal"), "pending")
        self.accepted(self.request_for("accept_proposal", self.bob), "pending")
        self.service.owner_apply_terms = lambda terms: False
        with self.assertRaises(self.policy.BoundaryError) as caught:
            self.service.apply_owner_boundary("segment-next")
        self.assertEqual(caught.exception.code, "recovery_pending")
        self.assertTrue(self.service._failed)
        self.assertEqual(self.service._owner_state["terms"]["version"], "1")
        self.assert_code(self.post(self.request_for("accept_terms")), "recovery_pending")


if __name__ == "__main__":
    unittest.main()


class RoomOwnerRouteCases(unittest.TestCase):
    """New authenticated inspector routes; all state and crypto ports are local."""

    setUp_base = RoomServiceCases.setUp
    example = RoomServiceCases.example
    error = RoomServiceCases.error
    result = RoomServiceCases.result
    replay = RoomServiceCases.replay
    page = RoomServiceCases.page
    wire = RoomServiceCases.wire
    challenge = RoomServiceCases.challenge
    join_request = RoomServiceCases.join_request
    join = RoomServiceCases.join
    control = RoomServiceCases.control
    connect = RoomServiceCases.connect
    assert_code = RoomServiceCases.assert_code

    paths = dict(snapshot="snapshot", save_limit="limit", accept_terms="terms/accept",
                 remove_member="members/remove", block_member="members/block",
                 lift_block="members/lift-block", accept_proposal="proposals/accept",
                 decline_proposal="proposals/decline")

    def setUp(self):
        self.setUp_base()
        # These are trusted host inputs, never supplied through a request.
        self.identity.room_owner_accounts = frozenset(("alice.near",))
        self.budgets = {}
        self.service.owner_budget = self.budget
        self.service.owner_apply_terms = lambda terms: True
        self.alice = self.join("alice")
        self.bob = self.join("bob")
        self.guest = self.join("guest")
        # A narrowed grant is an authenticated guest, not an owner-settings grant.
        guest_id = self.guest["grant_id"]
        self.identity._grants[guest_id]["capabilities"] = ["observe", "renew", "leave"]
        self.service._sessions[guest_id]["grant"]["capabilities"] = ["observe", "renew", "leave"]
        self.serial = 0

    def budget(self, binding, person_cents=None):
        account = binding["account_id"]
        value = self.budgets.setdefault(account, dict(person_cents="10000", swarm_cents="8000",
            persona_cents="6000", used_cents="100", held_cents="200"))
        if person_cents is not None:
            if int(person_cents) < int(value["used_cents"]) + int(value["held_cents"]):
                return self.error("bad_message")
            value["person_cents"] = person_cents
        return dict(value)

    def owner_request(self, grant, action, payload=None, **changes):
        from copy import deepcopy
        self.serial += 1
        request = {key: deepcopy(grant[key]) for key in
                   ("context", "grant_id", "session_key_id", "member_id", "nft_token_id",
                    "persona_digest", "slot_id", "generation", "token")}
        request.update(domain="room.owner.v1", kind="owner_control", action=action,
                       request_id="owner-" + str(self.serial), terms_version="0" if action == "snapshot" else "1",
                       payload={} if payload is None else payload, signature="A" * 86)
        request.update(changes)
        return request

    def post_owner(self, request, action=None):
        action = action or request["action"]
        return self.service.request("POST", "/room/owner/" + self.paths[action], self.wire(request), ip="owner-ip")

    def snapshot(self, grant=None):
        reply = self.post_owner(self.owner_request(grant or self.alice, "snapshot"))
        self.assertEqual(reply.get("type"), "owner_response", reply)
        self.policy.validate("OwnerResponse", reply)
        return reply["snapshot"]

    def test_snapshot_connection_status_is_moderator_private(self):
        self.connect(self.alice)
        bob_connection = self.connect(self.bob)
        member = self.join('carol')
        owner = {row['member_id']: row for row in self.snapshot(self.alice)['members']}
        self.assertTrue(owner[self.alice['member_id']]['connected'])
        self.assertTrue(owner[self.bob['member_id']]['connected'])
        before = {viewer['member_id']: self.snapshot(viewer)['members'] for viewer in (member, self.guest)}
        self.service.close_control(bob_connection)
        for viewer in (member, self.guest):
            with self.subTest(viewer=viewer['member_id']):
                for row in before[viewer['member_id']]:
                    self.assertNotIn('connected', row)
                    self.assertNotEqual(row['place'], 'disconnected')
                self.assertEqual(self.snapshot(viewer)['members'], before[viewer['member_id']])
        owner = {row['member_id']: row for row in self.snapshot(self.alice)['members']}
        self.assertTrue(owner[self.alice['member_id']]['connected'])
        self.assertFalse(owner[self.bob['member_id']]['connected'])
        self.assertEqual(owner[self.bob['member_id']]['place'], 'disconnected')

    def refusals(self, action, payload, *, moderation=False):
        # A second account cannot masquerade as the first even with a valid key.
        forged = self.owner_request(self.bob, action, payload, member_id=self.alice["member_id"])
        self.assert_code(self.post_owner(forged), "stale_slot")
        if moderation:
            self.assert_code(self.post_owner(self.owner_request(self.bob, action, payload)), "proof_required")
        self.assert_code(self.post_owner(self.owner_request(self.guest, action, payload)), "proof_required")
        self.assert_code(self.post_owner(self.owner_request(self.alice, action, payload, terms_version="999")), "version_mismatch")
        self.assert_code(self.post_owner(self.owner_request(self.alice, action, payload, signature="B" * 85 + "A")), "proof_required")
        self.assert_code(self.post_owner(self.owner_request(self.alice, action, payload, token="C" * 43)), "proof_required")

    def replay_refused(self, request):
        self.assert_code(self.post_owner(request), "request_conflict")
        change = {"person_cents": "7000"} if request["action"] == "save_limit" else {"reason": "Changed content"}
        altered = dict(request, payload=dict(request["payload"], **change))
        self.assert_code(self.post_owner(altered), "request_conflict")


    def test_owner_full_live_roster_retains_every_blocked_lift_target(self):
        for grant in (self.bob, self.guest):
            reply = self.post_owner(self.owner_request(self.alice, "block_member",
                dict(target_member_id=grant["member_id"], reason="Recorded moderation")))
            self.assertEqual(reply.get("state"), "accepted", reply)
        for i in range(15):
            reply = self.join("replacement-" + str(i))
            self.assertEqual(reply.get("state"), "accepted", reply)
        snapshot = self.snapshot()
        blocked = [row for row in snapshot["members"] if row["place"] == "blocked"]
        self.assertEqual({row["member_id"] for row in blocked}, {self.bob["member_id"], self.guest["member_id"]})
        self.assertEqual(sum(row["place"] != "blocked" for row in snapshot["members"]), 16)
        # A refreshed client selects the older target entirely from this reply,
        # even though the last moderation outcome names a different member.
        target = next(row for row in blocked if row["member_id"] != snapshot["moderation"]["target_member_id"])
        reply = self.post_owner(self.owner_request(self.alice, "lift_block",
            dict(target_member_id=target["member_id"], reason="Appeal reviewed")))
        self.assertEqual(reply.get("state"), "accepted", reply)
        self.assertEqual(reply["snapshot"]["moderation"]["target_name"], target["name"])


    def test_owner_retained_roster_has_separate_bounded_response_size(self):
        for i in range(253):
            account = "retained-" + str(i) + ".near"
            self.service._owner_state["members"].append(dict(member_id="retained-" + str(i),
                account_id=account, nft_token_id="retained-token-" + str(i), name="x" * 128))
            self.service._denied_accounts.add(account)
        request = self.owner_request(self.alice, "snapshot")
        reply = self.post_owner(request)
        self.assertEqual(reply.get("type"), "owner_response", reply)
        self.assertEqual(len(reply["snapshot"]["members"]), 256)
        encoded = self.wire(reply)
        self.assertGreater(len(encoded), 16_384)
        self.assertLessEqual(len(encoded), 524_288)
        self.assertEqual(self.service.limits["max_control_bytes"], 16_384)
        oversized = self.wire(dict(request, request_id="different")) + b" " * 16_384
        self.assert_code(self.service.request("POST", "/room/owner/snapshot", oversized, ip="large"), "rate_limited")


    def test_owner_save_limit(self):
        payload = dict(person_cents="5000")
        self.refusals("save_limit", payload)
        request = self.owner_request(self.alice, "save_limit", payload)
        reply = self.post_owner(request)
        self.assertEqual(reply.get("state"), "accepted", reply)
        self.assertEqual(reply["snapshot"]["limits"]["person_cents"], "5000")
        self.assertEqual(self.budget(dict(account_id="bob.near"))["person_cents"], "10000")
        self.replay_refused(request)
        self.assert_code(self.post_owner(self.owner_request(self.alice, "save_limit", dict(person_cents="299"))), "bad_message")
        self.service.owner_budget = None
        self.assert_code(self.post_owner(self.owner_request(self.alice, "save_limit", payload)), "recovery_pending")


    def test_owner_remove_member(self):
        payload = dict(target_member_id=self.bob["member_id"], reason="Owner request")
        self.refusals("remove_member", payload, moderation=True)
        cid = self.connect(self.bob)
        request = self.owner_request(self.alice, "remove_member", payload)
        reply = self.post_owner(request)
        self.assertEqual(reply.get("state"), "accepted", reply)
        self.assertNotIn(cid, self.service._connections)
        self.assertEqual(reply["snapshot"]["moderation"]["target_member_id"], self.bob["member_id"])
        self.assertTrue(reply["snapshot"]["moderation"]["target_name"])
        self.assertNotIn(self.bob["member_id"], [m["member_id"] for m in reply["snapshot"]["members"]])
        self.assert_code(self.post_owner(self.owner_request(self.bob, "snapshot")), "proof_required")
        self.replay_refused(request)
        self.now += 1000
        fresh = self.join("bob", request_id="fresh-bob")
        self.assertEqual(fresh.get("state"), "accepted", fresh)
        self.assertNotEqual(fresh["grant_id"], self.bob["grant_id"])
        self.assert_code(self.service.frame(cid, self.wire(self.control(self.bob, "renew"))), "proof_required")

    def test_owner_block_member(self):
        payload = dict(target_member_id=self.bob["member_id"], reason="Abuse report")
        self.refusals("block_member", payload, moderation=True)
        cid = self.connect(self.bob)
        request = self.owner_request(self.alice, "block_member", payload)
        reply = self.post_owner(request)
        self.assertEqual(reply.get("state"), "accepted", reply)
        self.assertNotIn(cid, self.service._connections)
        self.assertIn("bob.near", self.service._denied_accounts)
        self.assertIn("bob", self.service._denied_tokens)
        self.assert_code(self.challenge("bob", request_id="blocked-rejoin"), "banned")
        self.replay_refused(request)
        restored = self.module.RoomService(self.store, self.host, self.identity,
            now_ms=lambda: self.now, ready=lambda: True, admission_open=lambda: True,
            security_event=lambda event: True, owner_state=self.service.export_owner_state())
        req = self.example("JoinChallengeRequest")
        req.update(context=self.context, account_id="bob.near", nft_token_id="bob", persona_digest=persona("bob"))
        self.assert_code(restored.request("POST", "/room/challenge", self.wire(req), ip="new-ip"), "banned")

    def test_owner_lift_block(self):
        payload = dict(target_member_id=self.bob["member_id"], reason="Reviewed appeal")
        self.refusals("lift_block", payload, moderation=True)
        self.service.deny(account_id="bob.near", nft_token_id="bob")
        request = self.owner_request(self.alice, "lift_block", payload)
        reply = self.post_owner(request)
        self.assertEqual(reply.get("state"), "accepted", reply)
        self.assertNotIn("bob.near", self.service._denied_accounts)
        self.assertNotIn("bob", self.service._denied_tokens)
        self.assert_code(self.post_owner(self.owner_request(self.bob, "snapshot")), "proof_required")
        self.replay_refused(request)
        fresh = self.join("bob", request_id="after-lift")
        self.assertEqual(fresh.get("state"), "accepted", fresh)



    def test_owner_snapshot_wall_and_closed_shapes(self):
        alice = self.snapshot()
        self.assertTrue(alice["is_room_owner"])
        bob = self.snapshot(self.bob)
        self.assertFalse(bob["is_room_owner"])
        self.assertEqual(bob["viewer_member_id"], self.bob["member_id"])
        for field in ("owner", "clock", "account_id", "callback"):
            with self.subTest(field=field):
                self.assert_code(self.post_owner(self.owner_request(self.alice, "accept_terms", **{field: "untrusted"})), "bad_message")
        mismatched = self.owner_request(self.alice, "accept_terms")
        self.assert_code(self.post_owner(mismatched, "remove_member"), "bad_message")
        self.assert_code(self.post_owner(self.owner_request(self.alice, "snapshot", terms_version="1")), "bad_message")
        guest = self.snapshot(self.guest)
        self.assertEqual(guest["viewer_member_id"], self.guest["member_id"])
        self.assertFalse(guest["is_room_owner"])
        forged_guest_read = self.owner_request(self.guest, "snapshot", member_id=self.alice["member_id"])
        self.assert_code(self.post_owner(forged_guest_read), "stale_slot")
        raw = self.wire(self.service.request("GET", "/room", ip="public"))
        for secret in (b"person_cents", b"held_cents", b"owner_response", self.alice["token"].encode()):
            self.assertNotIn(secret, raw)
        self.assertNotIn("token", self.wire(alice).decode())

    def test_owner_journal_failure_revokes_without_ack(self):
        cid = self.connect(self.bob)
        self.service.security_event = lambda event: False
        request = self.owner_request(self.alice, "block_member", dict(target_member_id=self.bob["member_id"], reason="Emergency"))
        self.assert_code(self.post_owner(request), "recovery_pending")
        self.assertNotIn(cid, self.service._connections)
        self.assertTrue(self.service._failed)
        self.assert_code(self.service.frame(cid, self.wire(self.control(self.bob, "renew"))), "recovery_pending")


    def test_owner_replay_survives_fresh_join(self):
        request = self.owner_request(self.alice, "save_limit", dict(person_cents="5000"), request_id="durable-id")
        self.assertEqual(self.post_owner(request).get("state"), "accepted")
        fresh = self.join("alice", request_id="alice-reconnect")
        retry = self.owner_request(fresh, "save_limit", dict(person_cents="5000"), request_id="durable-id")
        self.assert_code(self.post_owner(retry), "request_conflict")
        state = self.service.export_owner_state()
        self.assertIn("durable-id", self.wire(state).decode())
        self.service = self.module.RoomService(self.store, self.host, self.identity,
            now_ms=lambda: self.now, ready=lambda: True, admission_open=lambda: True,
            security_event=lambda event: True, owner_state=state, owner_budget=self.budget)
        restored_grant = self.join("alice", request_id="alice-restored")
        retry = self.owner_request(restored_grant, "save_limit", dict(person_cents="5000"), request_id="durable-id")
        self.assert_code(self.post_owner(retry), "request_conflict")

    def test_owner_account_rate_and_retained_history_are_bounded(self):
        for i in range(60):
            request = self.owner_request(self.alice, "snapshot")
            reply = self.service.request("POST", "/room/owner/snapshot", self.wire(request), ip="rotating-" + str(i))
            self.assertEqual(reply.get("state"), "accepted", reply)
        request = self.owner_request(self.alice, "snapshot")
        self.assert_code(self.service.request("POST", "/room/owner/snapshot", self.wire(request), ip="fresh-ip"), "rate_limited")
        # Another authenticated account retains its own budget.
        self.assertEqual(self.snapshot(self.bob)["viewer_member_id"], self.bob["member_id"])
        self.service._owner_state["requests"] = [dict(account_id="bob.near", request_id="retained-" + str(i))
                                                   for i in range(256)]
        self.assert_code(self.post_owner(self.owner_request(self.bob, "snapshot")), "rate_limited")
        self.assertFalse(self.service._failed)

    def test_owner_budget_adapter_cannot_ack_below_committed_holds(self):
        def broken_budget(binding, person_cents=None):
            value = self.budget(binding)
            if person_cents is not None:
                value["person_cents"] = person_cents
            return value
        self.service.owner_budget = broken_budget
        request = self.owner_request(self.alice, "save_limit", dict(person_cents="299"))
        self.assert_code(self.post_owner(request), "recovery_pending")
        self.assertTrue(self.service._failed)

    def test_owner_interval_keeps_other_members_rate_history(self):
        self.service._owner_interval("60000")
        def apply(grant):
            request = self.control(grant, "intent")
            return self.service.policy.authorize(self.service._sessions[grant["grant_id"]]["binding"], request,
                capabilities=("intent",), fighter_id=request["payload"]["fighter_id"], life_id=request["life_id"])
        apply(self.alice)
        self.now += 40_000
        apply(self.bob)
        with self.assertRaises(self.policy.BoundaryError) as caught:
            apply(self.alice)
        self.assertEqual(caught.exception.code, "rate_limited")


class MemberCustodyConsentCases(unittest.TestCase):
    """Returned consent case: real custody issuance, without owner privileges."""

    example = MemberConsentRoutes.example
    error = MemberConsentRoutes.error
    result = MemberConsentRoutes.result
    replay = MemberConsentRoutes.replay
    page = MemberConsentRoutes.page
    wire = MemberConsentRoutes.wire
    challenge = MemberConsentRoutes.challenge
    join_request = MemberConsentRoutes.join_request
    join = MemberConsentRoutes.join
    control = MemberConsentRoutes.control
    connect = MemberConsentRoutes.connect
    assert_code = MemberConsentRoutes.assert_code
    request_for = MemberConsentRoutes.request_for
    post = MemberConsentRoutes.post
    accepted = MemberConsentRoutes.accepted
    paths = MemberConsentRoutes.paths

    def setUp(self):
        MemberConsentRoutes.setUp(self)
        original = self.host.resolve_identity
        def custody_evidence(request):
            evidence = original(request)
            if evidence.get("owner", {}).get("nft_token_id") == "custody":
                evidence["owner"].update(ownership_kind="custody", custody_reservation_id="hold-custody")
            return evidence
        self.host.resolve_identity = custody_evidence
        self.custody = self.join("custody")
        self.assertEqual(self.custody.get("state"), "accepted", self.custody)
        self.assertIn("intent", self.custody["capabilities"])
        self.assertNotIn("owner_settings", self.custody["capabilities"])
        self.assertNotIn("room_moderate", self.custody["capabilities"])

    def host_proposal(self):
        required = sorted(self.service._owner_affected())
        self.assertIn(self.custody["member_id"], required)
        return self.service.propose_owner_change(proposal_id="change-a", proposed_ms="3000",
            boundary_segment_id="segment-next", expires_at=str(self.now + 1000), required_members=required)

    def own_snapshot(self, grant):
        request = self.request_for("snapshot", grant, terms_version="0", payload={})
        response = self.post(request, "/room/owner/snapshot")
        self.assertEqual(response.get("state"), "accepted", response)
        self.assertEqual(response["request_digest"], self.policy.digest(request, exclude=("signature",)))
        self.assertEqual(response["snapshot"]["viewer_member_id"], grant["member_id"])
        self.assertFalse(response["snapshot"]["is_room_owner"])
        return response["snapshot"]

    def test_custody_accepts_own_terms_and_recovers_reply_by_snapshot(self):
        request = self.request_for("accept_terms", self.custody)
        self.accepted(request)
        self.assert_code(self.post(request), "request_conflict")
        # A fresh read resolves a lost reply without replaying the write.
        snapshot = self.own_snapshot(self.custody)
        self.assertTrue(snapshot["terms"]["accepted"])
        self.assertEqual(snapshot["terms"]["version"], "1")
        self.assertIn(dict(member_id=self.custody["member_id"], version="1"), self.service._owner_state["accepted"])
        self.assertNotIn(dict(member_id=self.alice["member_id"], version="1"), self.service._owner_state["accepted"])

    def test_custody_can_supply_required_acceptance_before_host_boundary(self):
        proposal = self.host_proposal()
        for grant in (self.alice, self.bob):
            self.accepted(self.request_for("accept_proposal", grant), "pending")
        self.assertFalse(self.service.apply_owner_boundary("segment-next"))
        request = self.request_for("accept_proposal", self.custody)
        self.accepted(request, "pending")
        self.assert_code(self.post(request), "request_conflict")
        snapshot = self.own_snapshot(self.custody)
        self.assertEqual(set(snapshot["proposal"]["accepted_members"]), set(proposal["required_members"]))
        self.assertTrue(self.service.apply_owner_boundary("segment-next"))
        self.assertEqual(self.service._owner_state["terms"]["version"], "2")
        self.assertTrue(self.own_snapshot(self.custody)["terms"]["accepted"])
        self.assertFalse(self.service._failed)

    def test_custody_can_decline_without_changing_effective_terms(self):
        proposal = self.host_proposal()
        self.accepted(self.request_for("accept_proposal", self.alice), "pending")
        self.accepted(self.request_for("decline_proposal", self.custody))
        snapshot = self.own_snapshot(self.custody)
        self.assertEqual(snapshot["proposal"]["state"], "declined")
        self.assertEqual(snapshot["proposal"]["declined_members"], [self.custody["member_id"]])
        self.assertFalse(self.service.apply_owner_boundary("segment-next"))
        self.assertEqual(self.service._owner_state["terms"]["version"], "1")
        self.assertEqual(self.applied, [])
        self.assertFalse(self.service._failed)

    def test_custody_consent_does_not_grant_spend_moderation_or_another_actor(self):
        actions = dict(save_limit=("limit", dict(person_cents="5000")),
            remove_member=("members/remove", dict(target_member_id=self.alice["member_id"], reason="No authority")),
            block_member=("members/block", dict(target_member_id=self.alice["member_id"], reason="No authority")),
            lift_block=("members/lift-block", dict(target_member_id=self.alice["member_id"], reason="No authority")))
        for action, (path, payload) in actions.items():
            with self.subTest(action=action):
                request = self.request_for(action, self.custody, payload=payload)
                self.assert_code(self.post(request, "/room/owner/" + path), "proof_required")
        self.host_proposal()
        for action in self.paths:
            with self.subTest(action=action):
                self.assert_code(self.post(self.request_for(action, self.custody, member_id=self.alice["member_id"])), "stale_slot")
                self.assert_code(self.post(self.request_for(action, self.custody, signature="B" * 85 + "A")), "proof_required")
                self.assert_code(self.post(self.request_for(action, self.custody, token="C" * 43)), "proof_required")
                self.assert_code(self.post(self.request_for(action, self.custody, terms_version="0")), "version_mismatch")
        self.assertNotIn("owner_settings", self.identity.capabilities(self.custody["grant_id"]))
        self.assertNotIn("room_moderate", self.identity.capabilities(self.custody["grant_id"]))
        self.own_snapshot(self.custody)

    def test_observe_only_grant_can_read_own_state_but_cannot_consent(self):
        issue = self.identity.issue_grant
        self.identity.issue_grant = lambda binding, key: issue(binding, key, capabilities=("observe", "renew", "leave"))
        observer = self.join("observer")
        self.assertEqual(observer.get("state"), "accepted", observer)
        self.assertNotIn("intent", observer["capabilities"])
        self.assertNotIn("owner_settings", observer["capabilities"])
        self.host_proposal()
        for action in self.paths:
            with self.subTest(action=action):
                self.assert_code(self.post(self.request_for(action, observer)), "proof_required")
        self.assertNotIn(observer["member_id"], self.service._owner_state["proposal"]["required_members"])
        self.own_snapshot(observer)


class MemberSourceCases(unittest.TestCase):
    """M1/M4 source regressions; no old case, suite or mutation replay."""

    def setUp(self):
        self.f = RoomOwnerRouteCases()
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()

    def read(self, grant=None, **changes):
        f = self.f
        return f.owner_request(grant or f.alice, "snapshot",
            dict(expires_at=str(f.now + 15_000)), **changes)

    def accepted(self, request):
        f = self.f
        response = f.post_owner(request)
        self.assertEqual(response.get("type"), "owner_response", response)
        f.policy.validate("OwnerResponse", response)
        self.assertEqual(response["request_digest"], f.policy.digest(request, exclude=("signature",)))
        return response["snapshot"]

    def recover(self, state):
        f = self.f
        f.service = f.module.RoomService(f.store, f.host, f.identity,
            now_ms=lambda: f.now, ready=lambda: True, admission_open=lambda: True,
            security_event=lambda event: f.durable.append(event) or True,
            owner_state=state, owner_budget=f.budget, owner_apply_terms=lambda terms: True)
        return f.service

    def unpublished(self):
        f = self.f
        state = f.service.export_owner_state()
        state["terms_published"] = False
        state["accepted"] = [dict(member_id=f.alice["member_id"], version="1")]
        self.recover(state)
        f.alice = f.join("alice", request_id="unpublished-join")
        self.assertEqual(f.alice.get("state"), "accepted", f.alice)

    def test_expiring_reads_survive_legacy_budget_with_real_renewals(self):
        f = self.f
        connection = f.connect(f.alice)
        for number in range(270):
            with self.subTest(read=number + 1):
                self.accepted(self.read())
                renewal = f.control(f.alice, "renew", str(number + 1))
                self.assertEqual(f.service.frame(connection, f.wire(renewal)).get("state"), "accepted")
            f.now += 10_000
        state = f.service.export_owner_state()
        self.assertLessEqual(len(state["read_requests"]), 2)
        self.assertEqual(state["requests"], [])
        self.assertEqual(state["read_clock_ms"], str(f.now - 10_000))

    def test_expiring_read_replay_recovers_and_expires_without_reviving(self):
        f = self.f
        request = self.read(request_id="durable-read")
        self.accepted(request)
        f.assert_code(f.post_owner(request), "request_conflict")
        state = f.service.export_owner_state()
        self.assertTrue(any(isinstance(e, dict) and e.get("kind") == "owner_state" and
            e["binding"]["state"]["read_requests"] == state["read_requests"] for e in f.durable))
        self.recover(state)
        grant = f.join("alice", request_id="read-recovery")
        retry = self.read(grant, request_id="durable-read")
        f.assert_code(f.post_owner(retry), "request_conflict")
        f.now += 15_000
        self.accepted(self.read(grant))
        f.assert_code(f.post_owner(retry), "proof_required")
        self.assertNotIn("durable-read", [r["request_id"] for r in f.service.export_owner_state()["read_requests"]])
        self.accepted(self.read(grant, request_id="durable-read"))

    def test_expiry_closed_shape_and_window_refuse(self):
        f = self.f
        for offset in (0, -1, 15_001):
            with self.subTest(offset=offset):
                request = f.owner_request(f.alice, "snapshot", dict(expires_at=str(f.now + offset)))
                f.assert_code(f.post_owner(request), "proof_required")
        for payload in (dict(expires_at=str(f.now + 15_000), clock="1"), dict(expires_at=f.now),
                        dict(expires_at="01"), dict(expires_at=None)):
            with self.subTest(payload=payload):
                f.assert_code(f.post_owner(f.owner_request(f.alice, "snapshot", payload)), "bad_message")
        self.accepted(self.read())

    def test_read_pruning_keeps_write_ids_and_shared_account_namespace(self):
        f = self.f
        write = f.owner_request(f.alice, "save_limit", dict(person_cents="5000"), request_id="permanent-write")
        self.accepted(write)
        f.assert_code(f.post_owner(self.read(request_id="permanent-write")), "request_conflict")
        self.accepted(self.read(request_id="live-read"))
        collision = f.owner_request(f.alice, "save_limit", dict(person_cents="5000"), request_id="live-read")
        f.assert_code(f.post_owner(collision), "request_conflict")
        f.now += 15_000
        self.accepted(self.read())
        state = f.service.export_owner_state()
        self.assertIn(dict(account_id="alice.near", request_id="permanent-write"), state["write_requests"])
        self.assertEqual(state["requests"], [])
        self.recover(state)
        grant = f.join("alice", request_id="write-recovery")
        f.assert_code(f.post_owner(f.owner_request(grant, "save_limit", dict(person_cents="5000"),
                                                  request_id="permanent-write")), "request_conflict")

    def test_full_legacy_checkpoint_migrates_without_losing_any_id(self):
        f = self.f
        state = f.service.export_owner_state()
        for key in ("read_requests", "write_requests", "read_clock_ms", "terms_published"):
            state.pop(key, None)
        # Baseline: 256 permanent legacy operations/account; action is unknown.
        state["requests"] = [dict(account_id="alice.near", request_id="old-" + str(n)) for n in range(256)]
        legacy = list(state["requests"])
        self.recover(state)
        grant = f.join("alice", request_id="legacy-recovery")
        f.assert_code(f.post_owner(f.owner_request(grant, "snapshot")), "rate_limited")
        self.assertIsNotNone(self.accepted(self.read(grant))["terms"])
        self.accepted(f.owner_request(grant, "save_limit", dict(person_cents="5000")))
        for action, payload in (("snapshot", {}), ("snapshot", dict(expires_at=str(f.now + 15_000))),
                                ("save_limit", dict(person_cents="5000"))):
            f.assert_code(f.post_owner(f.owner_request(grant, action, payload, request_id="old-0")), "request_conflict")
        migrated = f.service.export_owner_state()
        self.assertEqual(migrated["requests"], legacy)
        self.assertTrue(migrated["terms_published"])
        self.assertEqual(len(migrated["write_requests"]), 1)

    def test_recovered_read_clock_rollback_closes_authority_after_pruning(self):
        f = self.f
        old = self.read(request_id="pruned-read")
        self.accepted(old)
        f.now += 16_000
        self.accepted(self.read())
        state = f.service.export_owner_state()
        self.assertEqual(len(state["read_requests"]), 1)
        self.recover(state)
        f.now -= 16_000
        f.assert_code(f.post_owner(old), "recovery_pending")
        f.assert_code(f.post_owner(self.read()), "recovery_pending")

    def test_replay_banks_have_separate_bounded_capacity(self):
        f = self.f
        # Restore valid private windows at the account caps; live rate limits
        # prohibit producing 64 reads inside 15s through one healthy authority.
        state = f.service.export_owner_state()
        state.update(read_clock_ms=str(f.now), read_requests=[dict(account_id="alice.near",
            request_id="r-" + str(n), expires_at=str(f.now + 15_000)) for n in range(64)],
            write_requests=[dict(account_id="bob.near", request_id="w-" + str(n)) for n in range(256)])
        self.recover(state)
        alice = f.join("alice", request_id="read-cap-join")
        bob = f.join("bob", request_id="write-cap-join")
        f.assert_code(f.post_owner(self.read(alice)), "rate_limited")
        f.assert_code(f.post_owner(f.owner_request(bob, "save_limit", dict(person_cents="5000"))), "rate_limited")
        self.accepted(f.owner_request(alice, "save_limit", dict(person_cents="5000")))
        self.accepted(self.read(bob))
        f.now += 15_000
        self.accepted(self.read(alice))
        self.assertEqual(len(f.service.export_owner_state()["read_requests"]), 1)

    def test_unpublished_is_signed_null_with_consent_and_gameplay_closed(self):
        f = self.f
        self.unpublished()
        snapshot = self.accepted(self.read())
        self.assertIsNone(snapshot["terms"])
        self.assertIsNone(snapshot["proposal"])
        self.assertEqual(snapshot["viewer_member_id"], f.alice["member_id"])
        for action, payload in (("accept_terms", {}), ("accept_proposal", dict(proposal_id="absent")),
                                ("decline_proposal", dict(proposal_id="absent"))):
            f.assert_code(f.post_owner(f.owner_request(f.alice, action, payload)), "version_mismatch")
        with self.assertRaises(f.policy.BoundaryError) as caught:
            f.service.propose_owner_change(proposal_id="unpublished-change", proposed_ms="3000",
                boundary_segment_id="next", expires_at=str(f.now + 60_000),
                required_members=sorted(f.service._owner_affected()))
        self.assertEqual(caught.exception.code, "version_mismatch")
        connection = f.connect(f.alice)
        for sequence, kind in enumerate(("prediction", "intent"), 1):
            response = f.service.frame(connection, f.wire(f.control(f.alice, kind, str(sequence))))
            self.assertEqual(response.get("code"), "version_mismatch", response)
        self.assertNotIn("activate", f.host.calls)
        self.assertEqual(f.service.request("GET", "/room/observe", ip="watcher")["type"], "snapshot")
        for path in ("/room/owner/terms/publish", "/room/publish"):
            f.assert_code(f.service.request("POST", path, b"{}", ip="browser"), "bad_message")
        self.recover(f.service.export_owner_state())
        self.assertFalse(f.service.export_owner_state()["terms_published"])

    def test_host_publication_advances_version_requires_fresh_consent_and_recovers(self):
        f = self.f
        self.unpublished()
        published = f.service.publish_owner_terms()
        self.assertEqual(published["version"], "2")
        snapshot = self.accepted(self.read())
        self.assertEqual(snapshot["terms"]["version"], "2")
        self.assertFalse(snapshot["terms"]["accepted"])
        connection = f.connect(f.alice)
        response = f.service.frame(connection, f.wire(f.control(f.alice, "prediction")))
        self.assertEqual(response.get("code"), "version_mismatch", response)
        self.accepted(f.owner_request(f.alice, "accept_terms", terms_version="2"))
        response = f.service.frame(connection, f.wire(f.control(f.alice, "prediction", "2")))
        self.assertEqual(response.get("state"), "accepted", response)
        with self.assertRaises(f.policy.BoundaryError) as caught:
            f.service.publish_owner_terms()
        self.assertEqual(caught.exception.code, "request_conflict")
        state = f.service.export_owner_state()
        self.assertTrue(state["terms_published"])
        self.assertTrue(any(isinstance(e, dict) and e.get("kind") == "owner_state" and
            e["binding"]["state"]["terms"]["version"] == "2" for e in f.durable))
        self.recover(state)
        grant = f.join("alice", request_id="published-recovery")
        restored = self.accepted(self.read(grant))
        self.assertEqual(restored["terms"]["version"], "2")
        # A fresh membership is not allowed to inherit the prior member's consent.
        self.assertEqual(restored["terms"]["accepted"], grant["member_id"] == f.alice["member_id"])

    def test_read_journal_failure_closes_authority_without_ack(self):
        f = self.f
        f.service.security_event = lambda event: False
        f.assert_code(f.post_owner(self.read()), "recovery_pending")
        self.assertTrue(f.service._failed)
        f.assert_code(f.post_owner(self.read()), "recovery_pending")

    def test_publication_journal_failure_closes_authority_without_ack(self):
        f = self.f
        self.unpublished()
        f.service.security_event = lambda event: False
        with self.assertRaises(f.policy.BoundaryError) as caught:
            f.service.publish_owner_terms()
        self.assertEqual(caught.exception.code, "recovery_pending")
        self.assertTrue(f.service._failed)
        f.assert_code(f.post_owner(self.read()), "recovery_pending")


    def test_expiry_is_bound_by_game_hmac_adapter_and_receipt(self):
        # Same canonical-byte HMAC ports as game near/arena/test_room_host.py;
        # these synthetic adapters exercise actual source identity authentication.
        import base64
        from copy import deepcopy
        import hmac
        f = self.f
        def encoded(raw: bytes) -> str:
            return base64.urlsafe_b64encode(raw).decode().rstrip("=")
        def sign(body: bytes) -> str:
            return encoded(hmac.digest(b"synthetic-session", body, "sha512"))
        f.identity.verify_session = lambda key, body, signature: (key == f.example("SessionPublicKey") and
            hmac.compare_digest(signature, sign(body)))
        f.identity.sign = lambda body: encoded(hmac.digest(b"synthetic-room", body, "sha512"))
        request = self.read()
        request["signature"] = sign(f.policy.canonical_bytes(request, exclude=("signature",)))
        changed = deepcopy(request)
        changed["payload"]["expires_at"] = str(f.now + 14_000)
        f.assert_code(f.post_owner(changed), "proof_required")
        response = f.post_owner(request)
        self.assertEqual(response.get("type"), "owner_response", response)
        self.assertEqual(response["request_digest"], f.policy.digest(request, exclude=("signature",)))
        expected = encoded(hmac.digest(b"synthetic-room",
            f.policy.canonical_bytes(response, exclude=("signature",)), "sha512"))
        self.assertTrue(hmac.compare_digest(response["signature"], expected))
        f.now += 15_000
        f.assert_code(f.post_owner(request), "proof_required")
        f.assert_code(f.post_owner(changed), "proof_required")

    def test_global_read_and_write_limits_and_expired_cleanup(self):
        f = self.f
        # Inject shape-valid full private banks to hit global predicates without
        # 4096 authenticated writes; each unrelated account remains at its cap.
        state = f.service._owner_state
        state["read_requests"] = [dict(account_id="reader" + str(n // 64) + ".near",
            request_id="read-" + str(n), expires_at=str(f.now + 15_000)) for n in range(4096)]
        state["read_clock_ms"] = str(f.now)
        f.assert_code(f.post_owner(self.read()), "rate_limited")
        f.now += 15_000
        self.accepted(self.read())
        self.assertEqual(len(state["read_requests"]), 1)
        state["write_requests"] = [dict(account_id="writer" + str(n // 256) + ".near",
            request_id="write-" + str(n)) for n in range(4096)]
        f.assert_code(f.post_owner(f.owner_request(f.alice, "save_limit", dict(person_cents="5000"))), "rate_limited")
        self.assertEqual(len(state["write_requests"]), 4096)

    def test_expiring_reads_keep_existing_authentication_rate(self):
        f = self.f
        for number in range(60):
            request = self.read()
            response = f.service.request("POST", "/room/owner/snapshot", f.wire(request), ip="ip-" + str(number))
            self.assertEqual(response.get("type"), "owner_response", response)
        f.assert_code(f.service.request("POST", "/room/owner/snapshot", f.wire(self.read()), ip="ip-new"), "rate_limited")
        self.accepted(self.read(f.bob))
        f.now += 60_000
        fresh = f.join("alice", request_id="after-auth-minute")
        self.accepted(self.read(fresh))

    def test_invalid_clock_and_ambiguous_recovered_replay_banks_refuse(self):
        from copy import deepcopy
        f = self.f
        self.accepted(self.read())
        state = f.service.export_owner_state()
        self.recover(state)
        f.service.now_ms = lambda: "untrusted-clock"
        f.assert_code(f.post_owner(self.read()), "recovery_pending")
        self.assertTrue(f.service._failed)
        for bank in ("requests", "write_requests"):
            malformed = deepcopy(state)
            malformed[bank] = [{key: state["read_requests"][0][key] for key in ("account_id", "request_id")}]
            with self.subTest(bank=bank), self.assertRaises(f.policy.BoundaryError) as caught:
                self.recover(malformed)
            self.assertEqual(caught.exception.code, "recovery_pending")


    def test_write_pruning_also_fences_clock_rollback(self):
        f = self.f
        self.accepted(self.read(request_id="old-live-read"))
        f.now += 16_000
        self.accepted(f.owner_request(f.alice, "save_limit", dict(person_cents="5000")))
        state = f.service.export_owner_state()
        self.assertEqual(state["read_requests"], [])
        self.assertEqual(state["read_clock_ms"], str(f.now))
        self.recover(state)
        f.now -= 16_000
        f.assert_code(f.post_owner(self.read(request_id="old-live-read")), "recovery_pending")

    def test_slow_trusted_read_cannot_ack_after_signed_expiry(self):
        f = self.f
        def delayed_budget(binding, person_cents=None):
            f.now += 15_000
            return f.budget(binding, person_cents)
        f.service.owner_budget = delayed_budget
        f.assert_code(f.post_owner(self.read()), "proof_required")
        self.assertEqual(f.service.export_owner_state()["requests"], [])

    def test_draft_zero_cannot_publish_into_legacy_consent_exception(self):
        f = self.f
        state = f.service.export_owner_state()
        state.update(terms_published=False)
        state["terms"]["version"] = "0"
        self.recover(state)
        self.assertEqual(f.service.publish_owner_terms()["version"], "2")
        grant = f.join("alice", request_id="draft-zero")
        connection = f.connect(grant)
        response = f.service.frame(connection, f.wire(f.control(grant, "prediction")))
        self.assertEqual(response.get("code"), "version_mismatch", response)


    def test_source_checkpoint_structural_types_match_optional_migration(self):
        import typing
        from room import bridge
        defs = self.f.schema["$defs"]
        for name in ("OwnerState", "OwnerReadOperation", "OwnerMember"):
            with self.subTest(name=name):
                structural = getattr(bridge, name)
                hints = typing.get_type_hints(structural)
                self.assertEqual(set(hints), set(defs[name]["properties"]))
                self.assertEqual(set(structural.__required_keys__), set(defs[name]["required"]))
        self.assertIn(type(None), typing.get_args(typing.get_type_hints(bridge.OwnerSnapshot)["terms"]))


    def test_slow_receipt_signer_cannot_ack_after_signed_expiry(self):
        f = self.f
        def delayed_sign(body: bytes) -> str:
            f.now += 15_000
            return "A" * 86
        f.identity.sign = delayed_sign
        f.assert_code(f.post_owner(self.read()), "proof_required")


    def test_inflight_clock_rollback_cannot_revive_pruned_read_or_lower_checkpoint(self):
        """Clock changes after current native authentication must fence replay."""
        import base64
        from copy import deepcopy
        import hmac
        f = self.f
        def encoded(raw: bytes) -> str:
            return base64.urlsafe_b64encode(raw).decode().rstrip("=")
        def session_sign(body: bytes) -> str:
            return encoded(hmac.digest(b"synthetic-session", body, "sha512"))
        def room_sign(body: bytes) -> str:
            return encoded(hmac.digest(b"synthetic-room", body, "sha512"))
        f.identity.verify_session = lambda key, body, signature: (key == f.example("SessionPublicKey") and
            hmac.compare_digest(signature, session_sign(body)))
        f.identity.sign = room_sign
        def signed(request: dict) -> dict:
            request["signature"] = session_sign(f.policy.canonical_bytes(request, exclude=("signature",)))
            return request
        old = signed(self.read(request_id="inflight-pruned-read"))
        self.accepted(old)
        f.now += 16_000
        self.accepted(signed(self.read(request_id="inflight-pruning-read")))
        checkpoint = f.service.export_owner_state()
        self.assertNotIn(old["request_id"], [row["request_id"] for row in checkpoint["read_requests"]])
        f.assert_code(f.post_owner(old), "proof_required")
        # Baseline8ed149dd markT+16000; old signature expiresT+15000.
        high = f.now
        authenticate = f.identity.authenticate
        def authenticate_then_rollback(*args, **kwargs):
            binding = authenticate(*args, **kwargs)
            f.now = high - 16_000
            return binding
        f.identity.authenticate = authenticate_then_rollback
        durable = deepcopy(f.durable)
        response = f.post_owner(old)
        after = f.service.export_owner_state()
        with self.subTest(boundary="native-authenticate"):
            self.assertEqual(response.get("code"), "recovery_pending", response)
        with self.subTest(boundary="checkpoint"):
            self.assertEqual(after, checkpoint)
        with self.subTest(boundary="journal"):
            self.assertEqual(f.durable, durable)
        with self.subTest(boundary="authority"):
            self.assertTrue(f.service._failed)
        # Recover the exact high-water checkpoint, then exercise the sample at
        # the claim boundary itself, after entry/rate/auth checks have passed.
        f.now = high
        self.recover(checkpoint)
        f.identity.authenticate = authenticate
        grant = f.join("alice", request_id="inflight-recovered-join")
        fresh = signed(self.read(grant, request_id="inflight-claim-read"))
        checkpoint = f.service.export_owner_state()
        durable = deepcopy(f.durable)
        claim = f.service._owner_claim
        def claim_after_rollback(binding: dict, request: dict) -> None:
            f.now = high - 16_000
            claim(binding, request)
        f.service._owner_claim = claim_after_rollback
        response = f.post_owner(fresh)
        with self.subTest(boundary="claim-sample"):
            self.assertEqual(response.get("code"), "recovery_pending", response)
        with self.subTest(boundary="claim-checkpoint"):
            self.assertEqual(f.service.export_owner_state(), checkpoint)
        with self.subTest(boundary="claim-journal"):
            self.assertEqual(f.durable, durable)
        with self.subTest(boundary="claim-authority"):
            self.assertTrue(f.service._failed)
