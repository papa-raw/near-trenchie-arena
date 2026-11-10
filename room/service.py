"""Bounded transport-independent admission and control orchestration.

One instance owns ingress for house, browser and native connections. An edge
adapter supplies the actual peer IP and TLS/host/Origin checks; it never accepts
those values from message fields. The host supplies the game clock and bridge.
Identity and output policy are shared with every caller. No client callback,
path, executable, provider credential or chain writer is accepted here.

Admission starts closed. The trusted ready callback may become true only after
recovery and operational gates have reconciled the current epoch and restored
ban sets. security_event must commit transitions to the external security
journal before acknowledging them. Neither callback is a wire control.
"""
from __future__ import annotations

from collections import deque
from copy import deepcopy
import hmac
import secrets
import threading
import time
from urllib.parse import parse_qsl, urlsplit

from .policy import (BoundaryError, GuestPolicy, canonical_bytes, digest,
                     public_projection, validate)
from .slots import SlotError
from .protocol import parse_message


DEFAULT_LIMITS = dict(
    type="limits", max_control_bytes=16_384, max_depth=16, max_array_items=256,
    intent_interval_ms="2000", heartbeat_ms="10000", reservation_ms="60000",
    disconnect_grace_ms="30000", unauthenticated_ms="10000", join_attempts_per_minute=5,
    control_connections_per_persona=1, pending_requests=16, pending_snapshot_frames=2,
    max_replays=2, unauthenticated_connections=32, unauthenticated_per_ip=2)

_CONTROLS = dict(observe="ObserveRequest", intent="IntentRequest", prediction="PredictionRequest",
                 renew="RenewRequest", leave="LeaveRequest")
_READS = {"/room": "seat", **{"/room/" + name: name for name in
          ("observe", "tick", "limits", "result", "replay", "ledger")}}
_OWNER_ROUTES = {"/room/owner/" + path: action for path, action in (
    ("snapshot", "snapshot"), ("limit", "save_limit"), ("terms/accept", "accept_terms"),
    ("members/remove", "remove_member"), ("members/block", "block_member"),
    ("members/lift-block", "lift_block"), ("proposals/accept", "accept_proposal"),
    ("proposals/decline", "decline_proposal"))}
_BINDING_KEYS = ("context", "grant_id", "session_key_id", "member_id", "nft_token_id",
                 "persona_digest", "slot_id", "generation")
_OWNER_RESPONSE_BYTES = 524_288
_OWNER_HISTORY_MAX = 4096
_OWNER_PERMANENT_ACCOUNT_MAX = 256
_OWNER_READ_ACCOUNT_MAX = 64
_OWNER_READ_WINDOW_MS = 15_000


def _error(code, retry=None):
    return dict(type="error", code=code, request_id=None, retry_after_ms=retry)


def _call(callback, *args):
    try:
        return _check(callback(*args))
    except ValueError as exc:
        code = getattr(exc, "code", None)
        if isinstance(code, str):
            validate("ErrorCode", code)
            raise BoundaryError(code) from None
        raise


def _check(value):
    if isinstance(value, dict) and value.get("type") == "error":
        raise BoundaryError(value.get("code", "bad_message"))
    return value


def _message_name(value, key, choices):
    discriminator = value.get(key)
    if not isinstance(discriminator, str):
        raise BoundaryError("bad_message")
    name = choices.get(discriminator)
    if name is None:
        raise BoundaryError("bad_message")
    return name


class RecordReads:
    """Compose the portable ledger and result reader without another endpoint."""

    def __init__(self, ledger, results):
        self.ledger, self.results = ledger, results

    def page(self, after_index=None):
        return _call(self.ledger.page, after_index)

    def replay(self, segment_id, after_index=None):
        return _call(self.ledger.replay_page, segment_id, after_index)

    def result(self, segment_id):
        return _call(self.results.result, segment_id)


class RoomService:
    """Single ingress owner; all methods take bytes, never pretrusted messages.

    records is an optional trusted read port exposing result(segment_id),
    replay(segment_id, after_index), and page(after_index). Missing adapters
    refuse with recovery_pending. Signing and current identity checks belong
    to IdentityAuthority. Game operations use only the frozen host bridge.
    Transport sockets are represented by server-generated connection ids.
    Call close_control when transport is lost; drain private frames separately
    from replaceable public snapshots. Transport writes must be asynchronous.
    """

    def __init__(self, slots, bridge, identity, *, now_ms=None, ready=None,
                 records=None, security_event=None, admission_open=None, limits=None,
                 denied_accounts=(), denied_tokens=(), house_tokens=(), sale_operations=None, policy=None,
                 owner_state=None, owner_budget=None, owner_apply_terms=None, owner_member_name=None):
        self.slots, self.bridge, self.identity = slots, bridge, identity
        self.now_ms = now_ms or (lambda: time.time_ns() // 1_000_000)
        self.ready = ready or (lambda: False)
        self.security_event = security_event
        self.admission_open = admission_open or (lambda: False)
        self.records = records
        self.context = deepcopy(identity.context)
        validate("MainnetContext", self.context)
        if slots.room_id != self.context["room_id"] or slots.capacity != 16:
            raise BoundaryError("context_mismatch")
        self.limits = deepcopy(DEFAULT_LIMITS if limits is None else limits)
        validate("Limits", self.limits)
        self.policy = policy or GuestPolicy(now_ms=self.now_ms,
            max_control_bytes=self.limits["max_control_bytes"], max_depth=self.limits["max_depth"],
            max_array_items=self.limits["max_array_items"])
        self.origin = self.context["audience"].split("/room#", 1)[0]
        self.control_url = "wss://" + self.origin.removeprefix("https://") + "/room/control"
        validate("ControlUrl", self.control_url)
        self._lock = threading.RLock()
        self._pending = threading.BoundedSemaphore(self.limits["pending_requests"])
        self._replays = threading.BoundedSemaphore(self.limits["max_replays"])
        self._attempts = {}
        self._sessions = {}
        self._joins = {}
        self._sales = deepcopy(sale_operations or {})
        self._connections = {}
        self._denied_accounts = set(denied_accounts)
        self._denied_tokens = set(denied_tokens)
        self.house_tokens = frozenset(house_tokens)
        for token in self.house_tokens:
            validate("TokenId", token)
        self._failed = False
        self.owner_budget = owner_budget
        self.owner_apply_terms = owner_apply_terms
        self.owner_member_name = owner_member_name
        self._owner_attempts = {}
        self._owner_state = deepcopy(owner_state) if owner_state is not None else dict(
            context=deepcopy(self.context), terms=dict(version="1", input_interval_ms=self.limits["intent_interval_ms"],
                segment_ms="60000", simulation_hz=20), accepted=[], members=[], proposal=None,
            moderation=[], requests=[], denied_accounts=[], denied_tokens=[], proposal_ids=[])
        # Missing fields belong to the original published/permanent contract.
        # Never infer action or discard an operation id during migration.
        for key, default in (("read_requests", []), ("write_requests", []),
                             ("read_clock_ms", "0"), ("terms_published", True)):
            self._owner_state.setdefault(key, default)
        validate("OwnerState", self._owner_state)
        self._owner_history_check()
        if self._owner_state["context"] != self.context:
            raise BoundaryError("context_mismatch")
        self._denied_accounts.update(self._owner_state["denied_accounts"])
        self._denied_tokens.update(self._owner_state["denied_tokens"])
        self._owner_interval(self._owner_state["terms"]["input_interval_ms"])

    def _now(self) -> int:
        try:
            now = self.now_ms()
            if type(now) is not int or not 0 <= now < 2 ** 64 - 60_000:
                raise BoundaryError("recovery_pending")
            # Validate this exact sample before any caller can prune history
            # or replace its high-water mark, including after authentication.
            if now < int(self._owner_state["read_clock_ms"]):
                raise BoundaryError("recovery_pending")
            return now
        except Exception:
            self._failed = True
            raise BoundaryError("recovery_pending") from None

    def _guard(self):
        if self._failed or self.security_event is None or self.ready() is not True:
            raise BoundaryError("recovery_pending")
        self._now()
        if self.identity.context != self.context:
            raise BoundaryError("context_mismatch")

    def _security(self, kind, binding):
        self._guard()
        try:
            if self.security_event(dict(kind=kind, context=deepcopy(self.context),
                                        binding=deepcopy(binding), at=str(self._now()))) is not True:
                raise BoundaryError("recovery_pending")
        except Exception:
            self._failed = True
            raise BoundaryError("recovery_pending") from None

    def _signed(self, name, value):
        signed = self.identity.sign_message(deepcopy(value))
        validate(name, signed)
        return signed

    def _context(self, value):
        if value.get("context", {}).get("version") != self.context["version"]:
            raise BoundaryError("version_mismatch")
        if value.get("context") != self.context:
            raise BoundaryError("context_mismatch")

    def _banned(self, account, token):
        if account in self._denied_accounts or token in self._denied_tokens:
            raise BoundaryError("banned")

    def _parse(self, raw):
        return parse_message(raw, max_control_bytes=self.limits["max_control_bytes"],
            max_depth=self.limits["max_depth"], max_array_items=self.limits["max_array_items"])

    def _attempt(self, ip, account=None):
        # IP and account are independent ceilings. Bound the key table as well
        # as each bucket, so rotating caller labels cannot exhaust memory.
        now = self._now()
        self._attempts = {key: values for key, values in self._attempts.items()
                          if values and values[-1] > now - 60_000}
        keys = [("ip", ip)] + ([] if account is None else [("account", account)])
        if len(self._attempts) + sum(key not in self._attempts for key in keys) > 4096:
            raise BoundaryError("rate_limited")
        for key in keys:
            values = self._attempts.setdefault(key, deque())
            while values and values[0] <= now - 60_000:
                values.popleft()
            if len(values) >= self.limits["join_attempts_per_minute"]:
                raise BoundaryError("rate_limited")
        for key in keys:
            self._attempts[key].append(now)

    def _ip(self, ip):
        if not isinstance(ip, str) or not 1 <= len(ip) <= 128 or any(ord(c) < 32 for c in ip):
            raise BoundaryError("bad_message")
        return ip

    def request(self, method, target, body=b"", *, ip):
        """HTTP adapter entry. GET routing parameters are never a request body."""
        if not self._pending.acquire(blocking=False):
            return _error("rate_limited", "1000")
        try:
            self._ip(ip)
            if not isinstance(target, str) or len(target) > 1024 or any(ord(c) < 32 for c in target):
                raise BoundaryError("bad_message")
            try:
                parsed = urlsplit(target)
            except ValueError:
                raise BoundaryError("bad_message") from None
            if parsed.scheme or parsed.netloc or parsed.fragment:
                raise BoundaryError("bad_message")
            if method == "GET":
                if body != b"" or parsed.path not in _READS:
                    raise BoundaryError("bad_message")
                return self._read(parsed)
            if method != "POST" or parsed.query or parsed.path not in {
                    "/room/challenge", "/room/join", "/room/sale-control", *_OWNER_ROUTES}:
                raise BoundaryError("bad_message")
            value = self._parse(body)
            with self._lock:
                if parsed.path in _OWNER_ROUTES:
                    self._owner_rate(("ip", ip))
                    return self._owner(value, _OWNER_ROUTES[parsed.path])
                account = value.get("account_id")
                if parsed.path == "/room/join":
                    account = value.get("challenge", {}).get("account_id") if isinstance(value.get("challenge"), dict) else None
                if not isinstance(account, str):
                    raise BoundaryError("bad_message")
                self._collect()
                # The parser and cheap shape/context checks precede all proof
                # work; both account and edge IP share this budget.
                self._attempt(ip, account)
                if parsed.path == "/room/challenge":
                    name = _message_name(value, "purpose", dict(
                        join="JoinChallengeRequest", sale_control="SaleChallengeRequest",
                        sale_control_lookup="LookupChallengeRequest"))
                    validate(name, value)
                    self._context(value)
                    if value["purpose"] == "join":
                        if self.admission_open() is not True:
                            raise BoundaryError("admission_closed")
                        self._banned(value["account_id"], value["nft_token_id"])
                    self._guard()
                    return _check(self.identity.challenge(value))
                if parsed.path == "/room/join":
                    validate("JoinRequest", value)
                    self._context(value)
                    return self._join(value)
                # This route is owner-only and grants no fighter capability.
                validate("SaleControlLookup" if value.get("purpose") == "sale_control_lookup" else "SaleControlRequest", value)
                self._context(value)
                self._guard()
                return self._sale(value)
        except (BoundaryError, SlotError) as exc:
            return _error(exc.code, "1000" if exc.code == "rate_limited" else None)
        except Exception:
            # A failed trusted dependency cannot leak its exception or produce
            # an optimistic acknowledgement. Explicit reset/recovery is needed.
            self._failed = True
            return _error("recovery_pending")
        finally:
            self._pending.release()

    def _read(self, parsed):
        verb = _READS[parsed.path]
        try:
            pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=4)
        except ValueError:
            raise BoundaryError("bad_message") from None
        if len({k for k, _ in pairs}) != len(pairs):
            raise BoundaryError("bad_message")
        query = dict(pairs)
        allowed = {"segment_id"} if verb == "result" else {"segment_id", "after_index"} if verb == "replay" else {"after_index"} if verb == "ledger" else set()
        if set(query) - allowed or (verb in {"result", "replay"} and "segment_id" not in query):
            raise BoundaryError("bad_message")
        value = dict(verb=verb, segment_id=query.get("segment_id"), after_index=query.get("after_index"))
        validate("ReadRequest", value)
        if verb == "seat":
            manifest = self.slots.manifest()
            manifest.update(type="manifest", context=deepcopy(self.context), protocol_version=1,
                            rules_hash=self.context["rules_hash"], limits=deepcopy(self.limits),
                            admission=("open" if self.admission_open() is True else "closed")
                                if self.ready() is True and not self._failed and self.security_event is not None else "recovery_pending",
                            proof_methods=sorted(self.identity.proof_methods), session_algorithm="ed25519",
                            control_authentication="first_frame_v1")
            validate("Manifest", manifest)
            return manifest
        if verb == "limits":
            return deepcopy(self.limits)
        if verb in {"observe", "tick"}:
            snapshot = self._snapshot(None)
            return snapshot if verb == "observe" else snapshot["clock"]
        if self.records is None:
            raise BoundaryError("recovery_pending")
        if verb == "ledger":
            result = _call(self.records.page, value["after_index"])
            validate("LedgerPage", result)
        else:
            if not self._replays.acquire(blocking=False):
                raise BoundaryError("rate_limited")
            try:
                if verb == "result":
                    result = _call(self.records.result, value["segment_id"])
                    validate("Result", result)
                else:
                    result = _call(self.records.replay, value["segment_id"], value["after_index"])
                    validate("ReplayPage", result)
            finally:
                self._replays.release()
        return deepcopy(result)

    def _sale(self, request):
        owner = _check(self.identity.resolve(request))
        validate("OwnerBinding", owner)
        key = (owner["account_id"], request["request_id"])
        prior = self._sales.get(key)
        auth_digest = digest(request, exclude=("wallet_proof",))
        if request["purpose"] == "sale_control_lookup":
            if prior is None:
                raise BoundaryError("not_found")
            if (prior["digest"] != request["original_digest"]
                    or prior["action"] != request["action"]
                    or prior["owner"]["nft_token_id"] != owner["nft_token_id"]):
                raise BoundaryError("request_conflict")
            if prior.get("ack") is None:
                raise BoundaryError("recovery_pending")
            ack = deepcopy(prior["ack"])
            ack.update(owner=deepcopy(owner), authentication_digest=auth_digest)
            return self._signed("SaleAcknowledgement", ack)
        if prior is not None:
            raise BoundaryError("request_conflict")
        if len(self._sales) >= 256:
            raise BoundaryError("rate_limited")
        operation = dict(owner=deepcopy(owner), action=request["action"],
                         request_id=request["request_id"], digest=auth_digest, ack=None)
        self._security("sale_control", operation)
        self._sales[key] = operation
        ack = _check(self.bridge.sale_control(owner, request["action"], request["request_id"]))
        validate("SaleAcknowledgement", ack)
        if (ack["context"] != self.context or ack["action"] != request["action"]
                or ack["request_id"] != request["request_id"]
                or any(ack["owner"][field] != owner[field] for field in
                       ("account_id", "nft_token_id", "persona_digest"))):
            raise BoundaryError("context_mismatch")
        ack.update(owner=deepcopy(owner), operation_digest=auth_digest,
                   authentication_digest=auth_digest)
        operation["ack"] = self._signed("SaleAcknowledgement", ack)
        return deepcopy(operation["ack"])

    def sale_acknowledged(self, acknowledgement):
        """Trusted host update after an operation reaches its batch boundary."""
        with self._lock:
            self._guard()
            validate("SaleAcknowledgement", acknowledgement)
            self._context(acknowledgement)
            key = (acknowledgement["owner"]["account_id"], acknowledgement["request_id"])
            operation = self._sales.get(key)
            if (operation is None or operation["digest"] != acknowledgement["operation_digest"]
                    or operation["action"] != acknowledgement["action"]
                    or operation["owner"]["nft_token_id"] != acknowledgement["owner"]["nft_token_id"]):
                raise BoundaryError("request_conflict")
            operation["ack"] = self._signed("SaleAcknowledgement", acknowledgement)

    def _join_key(self, request):
        challenge = request["challenge"]
        immutable = {key: request[key] for key in
                     ("context", "persona_digest", "session_public_key", "declared_compute", "resume")}
        immutable.update(account_id=challenge["account_id"], nft_token_id=challenge["nft_token_id"])
        return (challenge["account_id"], request["request_id"]), digest(immutable)

    def _join(self, request):
        self._guard()
        if self.admission_open() is not True:
            raise BoundaryError("admission_closed")
        proposal = self._owner_proposal()
        if proposal is not None and proposal["state"] == "pending":
            raise BoundaryError("admission_closed")
        challenge = request["challenge"]
        self._banned(challenge["account_id"], challenge["nft_token_id"])
        key, immutable = self._join_key(request)
        prior = self._joins.get(key)
        if prior is not None and prior["immutable"] != immutable:
            raise BoundaryError("request_conflict")
        complete_digest = digest(request)
        owner = _check(self.identity.recheck(request) if prior is not None and
                       complete_digest in prior["authenticated"] else self.identity.resolve(request))
        validate("OwnerBinding", owner)
        if any(owner[field] != challenge[field] for field in
               ("context", "account_id", "nft_token_id", "persona_digest")):
            raise BoundaryError("proof_required")
        self._banned(owner["account_id"], owner["nft_token_id"])
        if prior is not None and "accepted" in prior:
            session = self._sessions.get(prior["accepted"]["grant_id"])
            if session is None:
                raise BoundaryError("proof_required")
            self.slots.authorize(session["record"])
            if int(session["grant"]["expires_at"]) <= self._now():
                raise BoundaryError("proof_required")
            return deepcopy(prior["accepted"])
        if len(self._joins) >= 256 and key not in self._joins:
            raise BoundaryError("room_full")
        member_id = "member-" + digest(dict(account_id=owner["account_id"], nft_token_id=owner["nft_token_id"]))[:40]
        previous_session = None
        resume = request["resume"]
        if resume is not None:
            self.identity.authenticate_resume(resume)
            old = self._sessions.get(resume["prior_grant_id"])
            if (old is None or old["binding"]["account_id"] != owner["account_id"]
                    or old["binding"]["nft_token_id"] != owner["nft_token_id"]
                    or old["binding"]["persona_digest"] != owner["persona_digest"]
                    or old["binding"]["generation"] != resume["prior_generation"]
                    or not hmac.compare_digest(old["grant"]["token"], resume["resume_token"])):
                raise BoundaryError("proof_required")
            previous_session = old
            self._revoke(old)
            record = self.slots.resume(old["record"])
        else:
            record = self.slots.reserve(member_id, owner["persona_digest"])
        self._joins.setdefault(key, dict(immutable=immutable, expires=self._now() + 60_000, authenticated=set()))
        self._joins[key]["authenticated"].add(complete_digest)
        if record["state"] == "spectating":
            return self._signed("QueueStatus", dict(
                domain="room.receipt.v1", context=deepcopy(self.context), grant_id=None, session_key_id=None,
                status="spectating", account_id=owner["account_id"], nft_token_id=owner["nft_token_id"],
                queue_id="queue-" + member_id, position=str(record["queue_position"]),
                request_id=request["request_id"], request_digest=digest(request, exclude=("proof",)),
                message_domain=request["domain"], state="pending", applied_tick=None, boundary=None))
        # A live binding cannot be retrieved by changing the request id or key.
        # Fresh owner proof rotates authority, including after process restart.
        if record["state"] in {"joined", "disconnected"} and resume is None:
            for session in self._sessions.values():
                if session["binding"]["member_id"] == member_id and not session["revoked"]:
                    previous_session = session
                    self._revoke(session)
            record = self.slots.resume(record)
        record = self.slots.join(record, request["declared_compute"],
                                 house=owner["nft_token_id"] in self.house_tokens)
        binding = {key: deepcopy(owner[key]) for key in
                   ("context", "account_id", "nft_token_id", "persona_digest")}
        binding.update(member_id=record["member_id"], slot_id=record["slot_id"], generation=record["generation"],
                       grant_id="grant-" + secrets.token_hex(20), session_key_id="session-" + secrets.token_hex(20))
        validate("SlotBinding", binding)
        self._security("grant", binding)
        grant = _check(self.identity.issue_grant(binding, request["session_public_key"]))
        session = dict(binding=binding, record=record, grant=grant, revoked=False, connection=None,
                       receipts={}, sequence=-1, reserved=None, prediction_lock=None, fighter=None)
        self._sessions[binding["grant_id"]] = session
        self._owner_remember(binding)
        if previous_session is not None:
            session.update(reserved=deepcopy(previous_session["reserved"]),
                           prediction_lock=deepcopy(previous_session["prediction_lock"]),
                           fighter=deepcopy(previous_session["fighter"]))
            if session["reserved"] is not None:
                session["reserved"]["binding"] = deepcopy(binding)
            if session["fighter"] is not None:
                session["fighter"]["binding"] = deepcopy(binding)
        else:
            session["reserved"] = _check(self.bridge.reserve_life(binding))
        if session["reserved"] is not None:
            validate("ReservedLife", session["reserved"])
            if session["reserved"]["binding"] != binding:
                self._revoke(session)
                raise BoundaryError("stale_slot")
        accepted = self._signed("JoinAccepted", dict(
            **deepcopy(binding), domain="room.receipt.v1", expires_at=grant["expires_at"], token=grant["token"],
            control_url=self.control_url, session_public_key=deepcopy(request["session_public_key"]),
            capabilities=deepcopy(grant["capabilities"]), request_id=request["request_id"],
            request_digest=digest(request, exclude=("proof",)), message_domain=request["domain"],
            state="accepted", applied_tick=None, boundary=None))
        self._joins[key]["accepted"] = deepcopy(accepted)
        return accepted

    def _revoke(self, session):
        session["revoked"] = True
        self.identity.revoke(session["binding"]["grant_id"])
        connection_id = session["connection"]
        if connection_id is not None:
            self._connections.pop(connection_id, None)
        session["connection"] = None

    def _collect(self):
        now = self._now()
        for cid, connection in list(self._connections.items()):
            if connection["session"] is None and int(connection["challenge"]["expires_at"]) <= now:
                self._connections.pop(cid, None)
        for key, prior in list(self._joins.items()):
            if prior["expires"] <= now:
                self._joins.pop(key, None)
        for gid, session in list(self._sessions.items()):
            if int(session["grant"]["expires_at"]) <= now:
                self._sessions.pop(gid, None)
                if not session["revoked"]:
                    self._revoke(session)
                    self._security("expire", session["binding"])
                    _check(self.bridge.release(session["binding"]))

    def open_control(self, *, ip, origin=None):
        """Called only after a TLS upgrade to the fixed configured endpoint."""
        try:
            self._ip(ip)
            if origin is not None and origin != self.origin:
                raise BoundaryError("proof_required")
            with self._lock:
                self._guard()
                self._collect()
                pending = [c for c in self._connections.values() if c["session"] is None]
                if (len(pending) >= self.limits["unauthenticated_connections"]
                        or sum(c["ip"] == ip for c in pending) >= self.limits["unauthenticated_per_ip"]):
                    raise BoundaryError("rate_limited")
                cid = "connection-" + secrets.token_hex(20)
                challenge = self._signed("ControlChallenge", dict(
                    domain="room.receipt.v1", context=deepcopy(self.context), grant_id=None, session_key_id=None,
                    type="control_challenge", connection_id=cid, nonce="nonce-" + secrets.token_hex(20),
                    expires_at=str(self._now() + 10_000)))
                self._connections[cid] = dict(ip=ip, challenge=challenge, session=None,
                    snapshots=deque(maxlen=self.limits["pending_snapshot_frames"]), private=deque())
                return challenge
        except (BoundaryError, SlotError) as exc:
            return _error(exc.code)
        except Exception:
            self._failed = True
            return _error("recovery_pending")

    def _notice(self, session):
        reserved = session["reserved"]
        if reserved is None:
            return None
        if (int(reserved["prediction_deadline"]) <= self._now()
                and session["prediction_lock"] is None):
            self._activate_when_ready(session)
            if session["reserved"] is None:
                return None
        binding = session["binding"]
        return self._signed("LifeNotice", dict(
            **{key: deepcopy(binding[key]) for key in _BINDING_KEYS},
            domain="room.receipt.v1", type="life_notice", reservation=deepcopy(reserved),
            prediction_lock=deepcopy(session["prediction_lock"])))

    def _authenticate(self, cid, connection, request):
        validate("ControlAuthenticate", request)
        self._context(request)
        if (connection["challenge"] != request["challenge"]
                or int(connection["challenge"]["expires_at"]) <= self._now()):
            raise BoundaryError("proof_required")
        session = self._sessions.get(request["grant_id"])
        if session is None or session["revoked"]:
            raise BoundaryError("proof_required")
        binding = session["binding"]
        self._banned(binding["account_id"], binding["nft_token_id"])
        self.slots.authorize(session["record"])
        checked = _check(self.identity.authenticate(request, token=request["token"]))
        if checked != binding:
            raise BoundaryError("stale_slot")
        self._security("authenticate", dict(binding, nonce=connection["challenge"]["nonce"], connection_id=cid))
        old = session["connection"]
        if old is not None:
            self._connections.pop(old, None)
        session["connection"] = cid
        connection["session"] = request["grant_id"]
        return self._signed("ControlReady", dict(
            **{key: deepcopy(binding[key]) for key in _BINDING_KEYS},
            domain="room.receipt.v1", type="control_ready", connection_id=cid,
            request_id=request["request_id"], request_digest=digest(request, exclude=("signature",)),
            next_life=self._notice(session)))

    def frame(self, connection_id, body):
        if not self._pending.acquire(blocking=False):
            return _error("rate_limited", "1000")
        connection = None
        try:
            with self._lock:
                self._guard()
                connection = self._connections.get(connection_id)
                if connection is None:
                    raise BoundaryError("proof_required")
                if connection["session"] is None:
                    if int(connection["challenge"]["expires_at"]) <= self._now():
                        raise BoundaryError("proof_required")
                    try:
                        request = self._parse(body)
                        if request.get("kind") != "authenticate":
                            raise BoundaryError("proof_required")
                        return self._authenticate(connection_id, connection, request)
                    except Exception:
                        self._connections.pop(connection_id, None)
                        raise
                request = self._parse(body)
                name = _message_name(request, "kind", _CONTROLS)
                validate(name, request)
                self._context(request)
                session = self._sessions[connection["session"]]
                binding = session["binding"]
                self._banned(binding["account_id"], binding["nft_token_id"])
                if session["revoked"] or session["connection"] != connection_id:
                    raise BoundaryError("proof_required")
                self.slots.authorize(session["record"])
                checked = _check(self.identity.authenticate(request))
                if checked != binding:
                    raise BoundaryError("stale_slot")
                request_digest = digest(request, exclude=("signature",))
                sequence = int(request["sequence"])
                prior = session["receipts"].get(sequence)
                if prior is not None:
                    if prior[0] != request_digest:
                        raise BoundaryError("request_conflict")
                    return deepcopy(prior[1])
                if sequence <= session["sequence"]:
                    raise BoundaryError("request_conflict")
                session["sequence"] = sequence
                try:
                    result = self._control(session, request)
                except (BoundaryError, SlotError) as exc:
                    result = self._receipt(session, request, code=exc.code)
                session["receipts"][sequence] = (request_digest, deepcopy(result))
                # Evicted old sequences can never dispatch again: high water
                # remains even when only the bounded receipt tail is retained.
                while len(session["receipts"]) > 64:
                    session["receipts"].pop(min(session["receipts"]))
                return result
        except (BoundaryError, SlotError) as exc:
            return _error(exc.code, "1000" if exc.code == "rate_limited" else None)
        except Exception:
            self._failed = True
            return _error("recovery_pending")
        finally:
            self._pending.release()

    def _receipt(self, session, request, *, code=None, applied_tick=None,
                 boundary=None, prediction_lock=None):
        return self._signed("Receipt", dict(
            domain="room.receipt.v1", context=deepcopy(self.context),
            grant_id=session["binding"]["grant_id"], session_key_id=session["binding"]["session_key_id"],
            owner=None, request_id=None, sequence=request["sequence"], message_domain=request["domain"],
            request_digest=digest(request, exclude=("signature",)), state="refused" if code else "accepted",
            applied_tick=applied_tick, boundary=boundary, prediction_lock=prediction_lock, code=code))

    def _control(self, session, request):
        binding = session["binding"]
        fighter = session["fighter"]
        if request["kind"] in {"intent", "prediction"}:
            self._owner_control_consent(binding)
        self.policy.authorize(binding, request, capabilities=session["grant"]["capabilities"],
                              fighter_id=None if fighter is None else fighter["fighter_id"],
                              life_id=(session["reserved"]["life_id"] if request["kind"] == "prediction" and session["reserved"]
                                       else None if fighter is None else fighter["life_id"]))
        kind = request["kind"]
        if kind == "observe":
            snapshot = self._snapshot(binding)
            connection = self._connections[session["connection"]]
            connection["snapshots"].append(snapshot)
            return self._receipt(session, request)
        if kind == "intent":
            if fighter is None or request["life_id"] != fighter["life_id"]:
                raise BoundaryError("stale_slot")
            acknowledgement = _check(self.bridge.apply(binding, request))
            validate("Receipt", acknowledgement)
            expected = dict(domain="room.receipt.v1", context=self.context,
                            grant_id=binding["grant_id"], session_key_id=binding["session_key_id"],
                            owner=None, request_id=None, sequence=request["sequence"],
                            message_domain=request["domain"], request_digest=digest(request, exclude=("signature",)))
            if any(acknowledgement[key] != value for key, value in expected.items()):
                raise BoundaryError("context_mismatch")
            return self._signed("Receipt", acknowledgement)
        if kind == "prediction":
            reserved = session["reserved"]
            if (reserved is None or reserved["life_id"] != request["life_id"]
                    or session["prediction_lock"] is not None):
                raise BoundaryError("prediction_closed")
            if int(reserved["prediction_deadline"]) <= self._now():
                self._activate(session, None)
                raise BoundaryError("prediction_closed")
            lock = self._activate(session, request)
            return self._receipt(session, request, prediction_lock=lock,
                                 boundary=dict(kind="pre_spawn", life_id=request["life_id"], segment_id=None, not_before_ms=None))
        if kind == "renew":
            renewed = self.slots.renew(session["record"])
            self.identity.renew(binding["grant_id"], renewed["lease_until"])
            session["record"] = renewed
            session["grant"]["expires_at"] = renewed["lease_until"]
            return self._receipt(session, request)
        # Revoke locally before bridge work. A failed downstream removal may
        # remain pending, but it can never leave this connection authorised.
        self._revoke(session)
        self._security("release", binding)
        if request["payload"]["reason"] == "disconnect":
            self.slots.disconnect(session["record"])
        else:
            self.slots.release(session["record"])
        ack = _check(self.bridge.release(binding))
        validate("ReleaseAck", ack)
        return self._receipt(session, request, boundary=ack["boundary"])

    def _activate(self, session, pick):
        self._guard()
        self._owner_control_consent(session["binding"])
        reserved = session["reserved"]
        if reserved is None:
            raise BoundaryError("prediction_closed")
        binding, life_id = session["binding"], reserved["life_id"]
        lock = session["prediction_lock"]
        if lock is None:
            lock = _check(self.bridge.lock_prediction(binding, life_id, pick))
            validate("PredictionLock", lock)
            if (lock["life_id"] != life_id or lock["state"] != ("none" if pick is None else "prediction")
                    or lock["prediction_hash"] != (None if pick is None else digest(pick, exclude=("signature",)))):
                raise BoundaryError("prediction_closed")
            session["prediction_lock"] = deepcopy(lock)
        elif pick is not None or lock["life_id"] != life_id:
            raise BoundaryError("prediction_closed")
        # A committed fence survives a refused activation. Retry that same life
        # and lock, never replace its forecast with a no-answer lock at deadline.
        self.slots.authorize(session["record"])
        fighter = _check(self.bridge.activate(binding, life_id, lock["lock_ref"]))
        validate("FighterBinding", fighter)
        if fighter["binding"] != binding or fighter["life_id"] != life_id or fighter["lock_ref"] != lock["lock_ref"]:
            raise BoundaryError("stale_slot")
        session["fighter"] = deepcopy(fighter)
        session["reserved"] = None
        self.slots.start_life(session["record"])
        return lock

    def _activate_when_ready(self, session: dict) -> None:
        """Capacity, ownership and unaccepted terms leave the member queued."""
        try:
            self._activate(session, None)
        except BoundaryError as exc:
            if exc.code not in {"room_full", "ownership_unavailable", "version_mismatch"}:
                raise

    def _snapshot(self, binding):
        value = _check(self.bridge.observe(binding))
        projected = public_projection("PublicSnapshot", value)
        validate("PublicSnapshot", projected)
        if projected["context"] != self.context or projected["clock"]["context"] != self.context:
            raise BoundaryError("context_mismatch")
        return projected

    def maintain(self):
        """Host clock maintenance; client messages cannot call or advance it."""
        with self._lock:
            self._guard()
            try:
                self._collect()
                self.slots.expire()
                for session in list(self._sessions.values()):
                    reserved = session["reserved"]
                    if (not session["revoked"] and reserved is not None
                            and (session["prediction_lock"] is not None
                                 or int(reserved["prediction_deadline"]) <= self._now())):
                        self._maintain_member(session)
            except Exception:
                self._failed = True  # Uncertain maintenance requires host recovery.
                raise

    def _maintain_member(self, session):
        try:
            self.identity.authenticate_resume(dict(
                prior_grant_id=session["binding"]["grant_id"],
                prior_generation=session["binding"]["generation"],
                resume_token=session["grant"]["token"]))
        except BoundaryError as exc:
            # An evidence refusal in authenticate_resume revokes that grant.
            # Retire it locally; a later owner proof must establish fresh authority.
            if exc.code not in {"proof_required", "stale_slot", "banned", "ownership_unavailable"}:
                raise
            self._retire_member(session)
            return
        try:
            self._activate_when_ready(session)
        except (BoundaryError, SlotError) as exc:
            if exc.code not in {"proof_required", "stale_slot", "banned", "prediction_closed"}:
                raise
            self._retire_member(session)

    def _retire_member(self, session):
        """Revoke confirmed authority loss without touching a newer occupant."""
        binding = session["binding"]
        self._revoke(session)
        self._security("release", binding)
        try:
            self.slots.release(session["record"])
        except SlotError as exc:
            if exc.code != "stale_slot":
                raise
        try:
            acknowledgement = _check(self.bridge.release(binding))
        except BoundaryError as exc:
            if exc.code != "stale_slot":
                raise
            # The bridge no longer has this exact binding. Do not touch its
            # replacement; only discard the already revoked local session.
        else:
            validate("ReleaseAck", acknowledgement)
            if acknowledgement["binding"] != binding or acknowledgement["revoked"] is not True:
                self._failed = True
                raise BoundaryError("recovery_pending")
        session.update(reserved=None, prediction_lock=None, fighter=None)

    def life_boundary(self, grant_id):
        """Host-only notification after a life ends; reserve and deliver the next."""
        with self._lock:
            self._guard()
            session = self._sessions.get(grant_id)
            if session is None or session["revoked"]:
                raise BoundaryError("proof_required")
            if session["fighter"] is None:
                raise BoundaryError("prediction_closed")
            self.slots.life_boundary(session["record"])
            try:
                self.slots.authorize(session["record"])
            except SlotError:
                self._revoke(session)
                self._security("release", session["binding"])
                _check(self.bridge.release(session["binding"]))
                return None
            reserved = _check(self.bridge.reserve_life(session["binding"]))
            validate("ReservedLife", reserved)
            if (reserved["binding"] != session["binding"] or session["fighter"] is not None
                    and reserved["life_id"] == session["fighter"]["life_id"]):
                raise BoundaryError("stale_slot")
            session.update(reserved=deepcopy(reserved), fighter=None, prediction_lock=None)
            notice = self._notice(session)
            cid = session["connection"]
            if cid is not None and notice is not None:
                connection = self._connections[cid]
                if len(connection["private"]) >= self.limits["pending_requests"]:
                    self.close_control(cid)
                else:
                    connection["private"].append(deepcopy(notice))
            return notice

    def drain_private(self, connection_id):
        """Transport-owned private delivery; overflow requires reconnect/resync."""
        with self._lock:
            connection = self._connections.get(connection_id)
            if connection is None or connection["session"] is None:
                return []
            session = self._sessions[connection["session"]]
            self.slots.authorize(session["record"])
            self.identity.grant(session["binding"]["grant_id"])
            frames = list(connection["private"])
            connection["private"].clear()
            return frames

    def close_control(self, connection_id):
        """Transport loss suspends fresh input immediately, preserving grace."""
        with self._lock:
            connection = self._connections.pop(connection_id, None)
            if connection is None or connection["session"] is None:
                return
            session = self._sessions.get(connection["session"])
            if session is None or session["connection"] != connection_id:
                return
            session["connection"] = None
            try:
                session["record"] = self.slots.disconnect(session["record"])
            except SlotError:
                self._revoke(session)

    def publish_snapshot(self):
        """Replace old public frames without blocking the host clock on I/O."""
        with self._lock:
            snapshot = self._snapshot(None)
            for connection in self._connections.values():
                if connection["session"] is not None:
                    connection["snapshots"].append(deepcopy(snapshot))

    def drain_snapshots(self, connection_id):
        with self._lock:
            connection = self._connections.get(connection_id)
            if connection is None or connection["session"] is None:
                return []
            snapshots = list(connection["snapshots"])
            connection["snapshots"].clear()
            return snapshots


    def _owner_interval(self, value):
        if not 1000 <= int(value) <= 60000:
            raise BoundaryError("bad_message")
        self.limits["intent_interval_ms"] = value
        self.policy.intent_interval_ms = int(value)

    def export_owner_state(self):
        """Private host checkpoint, reconciled with the security journal on boot."""
        with self._lock:
            value = deepcopy(self._owner_state)
            value.update(denied_accounts=sorted(self._denied_accounts), denied_tokens=sorted(self._denied_tokens))
            validate("OwnerState", value)
            return value

    def _owner_persist(self, *, operation=None):
        # The host must durably checkpoint this complete private state through
        # the off-host high-water mark before returning True. It is no wire read.
        self._security("owner_state", dict(state=self.export_owner_state(), operation=operation))

    def _owner_remember(self, binding):
        members = self._owner_state["members"]
        prior = next((m for m in members if m["member_id"] == binding["member_id"]), None)
        if prior is not None:
            if any(prior[k] != binding[k] for k in ("account_id", "nft_token_id")):
                raise BoundaryError("stale_slot")
            return
        if len(members) >= 256:
            raise BoundaryError("room_full")
        name = binding["member_id"] if self.owner_member_name is None else self.owner_member_name(deepcopy(binding))
        member = dict(member_id=binding["member_id"], account_id=binding["account_id"],
                      nft_token_id=binding["nft_token_id"], name=name)
        validate("OwnerMemberRecord", member)
        members.append(member)
        self._owner_persist()

    def _owner_rate(self, ip):
        now = self._now()
        self._owner_attempts = {key: times for key, times in self._owner_attempts.items()
                                if times and times[-1] > now - 60_000}
        if ip not in self._owner_attempts and len(self._owner_attempts) >= 4096:
            raise BoundaryError("rate_limited")
        times = self._owner_attempts.setdefault(ip, deque())
        while times and times[0] <= now - 60_000:
            times.popleft()
        if len(times) >= 60:
            raise BoundaryError("rate_limited")
        times.append(now)

    def _owner_history_check(self) -> None:
        """Recovered banks share one account/id namespace, including legacy ids."""
        seen = set()
        for key, limit in (("requests", _OWNER_PERMANENT_ACCOUNT_MAX),
                           ("write_requests", _OWNER_PERMANENT_ACCOUNT_MAX),
                           ("read_requests", _OWNER_READ_ACCOUNT_MAX)):
            counts = {}
            for operation in self._owner_state[key]:
                account = operation["account_id"]
                identity = (account, operation["request_id"])
                counts[account] = counts.get(account, 0) + 1
                if identity in seen or counts[account] > limit:
                    raise BoundaryError("recovery_pending")
                seen.add(identity)

    def _owner_claim(self, binding: dict, request: dict) -> None:
        """Reserve durable replay evidence before dispatch, with signed read expiry."""
        now = self._now()
        reads = self._owner_state["read_requests"]
        prior_count = len(reads)
        reads[:] = [r for r in reads if int(r["expires_at"]) > now]
        if len(reads) != prior_count:
            # Writes/legacy reads can also commit pruning. Fence rollback at
            # that pruning clock, not just at the last expiring read.
            self._owner_state["read_clock_ms"] = str(now)
        operation = dict(account_id=binding["account_id"], request_id=request["request_id"])
        expiring = request["action"] == "snapshot" and "expires_at" in request["payload"]
        if expiring and not now < int(request["payload"]["expires_at"]) <= now + _OWNER_READ_WINDOW_MS:
            raise BoundaryError("proof_required")
        if any(all(row[k] == value for k, value in operation.items())
               for key in ("requests", "write_requests", "read_requests") for row in self._owner_state[key]):
            raise BoundaryError("request_conflict")
        key = "read_requests" if expiring else "requests" if request["action"] == "snapshot" else "write_requests"
        requests = self._owner_state[key]
        account_max = _OWNER_READ_ACCOUNT_MAX if expiring else _OWNER_PERMANENT_ACCOUNT_MAX
        if len(requests) >= _OWNER_HISTORY_MAX or sum(r["account_id"] == binding["account_id"] for r in requests) >= account_max:
            raise BoundaryError("rate_limited")
        if expiring:
            operation["expires_at"] = request["payload"]["expires_at"]
            self._owner_state["read_clock_ms"] = str(now)
        requests.append(operation)

    def _owner(self, request, route_action):
        validate("OwnerRequest", request)
        if request["action"] != route_action:
            raise BoundaryError("bad_message")
        self._context(request)
        self._guard()
        session = self._sessions.get(request["grant_id"])
        if session is None or session["revoked"]:
            raise BoundaryError("proof_required")
        binding = session["binding"]
        self._banned(binding["account_id"], binding["nft_token_id"])
        self.slots.authorize(session["record"])
        checked = _check(self.identity.authenticate(request))
        if checked != binding:
            raise BoundaryError("stale_slot")
        self._owner_rate(("account", binding["account_id"]))
        # Read capabilities from the current authenticated grant, never the
        # request, display model, URL or a cached client-side owner bit.
        grant = self.identity.grant(binding["grant_id"])
        action = request["action"]
        version = self._owner_state["terms"]["version"]
        if action == "snapshot":
            if request["terms_version"] != "0":
                raise BoundaryError("bad_message")
        elif request["terms_version"] != version:
            raise BoundaryError("version_mismatch")
        if action in {"accept_terms", "accept_proposal", "decline_proposal"}:
            self._owner_require_published()
        self._owner_claim(binding, request)
        state = "accepted"
        if action in {"remove_member", "block_member", "lift_block"}:
            state = self._owner_moderate(binding, request)
        elif action == "save_limit":
            if self.owner_budget is None:
                raise BoundaryError("recovery_pending")
            # Consume the id before an independently durable budget write.
            # A crash/unknown result can only be resolved by a fresh read.
            self._owner_persist(operation=request["request_id"])
            value = _call(self.owner_budget, deepcopy(binding), request["payload"]["person_cents"])
            validate("OwnerLimits", value)
            if (value["person_cents"] != request["payload"]["person_cents"]
                    or int(value["person_cents"]) < int(value["used_cents"]) + int(value["held_cents"])):
                self._failed = True
                raise BoundaryError("recovery_pending")
        elif action == "accept_terms":
            self._owner_accept(binding["member_id"], version)
            self._owner_persist(operation=request["request_id"])
        elif action in {"accept_proposal", "decline_proposal"}:
            state = self._owner_answer(binding, request)
        else:
            self._owner_persist(operation=request["request_id"])
        snapshot = self._owner_snapshot(session, grant)
        if action == "save_limit" and (snapshot["limits"] is None or
                snapshot["limits"]["person_cents"] != request["payload"]["person_cents"]):
            self._failed = True
            raise BoundaryError("recovery_pending")
        response = self._signed("OwnerResponse", dict(type="owner_response", domain="room.receipt.v1",
            context=deepcopy(self.context), grant_id=binding["grant_id"], session_key_id=binding["session_key_id"],
            request_id=request["request_id"], action=action, request_digest=digest(request, exclude=("signature",)),
            state=state, snapshot=snapshot))
        if len(canonical_bytes(response)) > _OWNER_RESPONSE_BYTES:
            raise BoundaryError("rate_limited")
        if action == "snapshot" and "expires_at" in request["payload"]:
            # Include trusted journal, budget and signer latency in the window.
            self._guard()
            if self._now() >= int(request["payload"]["expires_at"]):
                raise BoundaryError("proof_required")
        return response

    def _owner_accept(self, member_id: str, version: str) -> None:
        """Record only the authenticated member's exact effective version."""
        self._owner_require_published()
        validate("Id", member_id)
        validate("U64", version)
        if version != self._owner_state["terms"]["version"]:
            raise BoundaryError("version_mismatch")
        accepted = self._owner_state["accepted"]
        remaining = [value for value in accepted if value["member_id"] != member_id]
        if len(remaining) >= 256:
            raise BoundaryError("rate_limited")
        accepted[:] = remaining + [dict(member_id=member_id, version=version)]

    def _owner_proposal_sets(self, proposal: dict) -> None:
        """Reject inconsistent recovered consent rather than infer an answer."""
        required = set(proposal["required_members"])
        accepted, declined = set(proposal["accepted_members"]), set(proposal["declined_members"])
        if not required or not (accepted | declined).issubset(required) or accepted & declined:
            raise BoundaryError("recovery_pending")
        outcomes = {"pending": not declined, "declined": bool(declined),
                    "expired": not declined, "accepted": accepted == required and not declined}
        if not outcomes[proposal["state"]]:
            raise BoundaryError("recovery_pending")

    def _owner_proposal_version(self, proposal: dict) -> None:
        """The immutable proposal id binds both old and next effective terms."""
        terms = self._owner_state["terms"]
        if proposal["proposal_id"] not in self._owner_state["proposal_ids"]:
            raise BoundaryError("recovery_pending")
        if not 1000 <= int(proposal["proposed_ms"]) <= 60000 or proposal["current_ms"] == proposal["proposed_ms"]:
            raise BoundaryError("recovery_pending")
        if proposal["state"] == "accepted":
            matched = (proposal["effective_version"] == terms["version"]
                       and proposal["proposed_ms"] == terms["input_interval_ms"])
        else:
            matched = (int(proposal["effective_version"]) == int(terms["version"]) + 1
                       and proposal["current_ms"] == terms["input_interval_ms"])
        if not matched:
            raise BoundaryError("recovery_pending")

    def _owner_proposal(self) -> dict | None:
        if not self._owner_state["terms_published"]:
            return None
        proposal = self._owner_state["proposal"]
        if proposal is None:
            return None
        try:
            validate("OwnerProposal", proposal)
            self._owner_proposal_sets(proposal)
            self._owner_proposal_version(proposal)
        except (BoundaryError, KeyError, TypeError, ValueError):
            raise BoundaryError("recovery_pending") from None
        if proposal["state"] == "pending" and int(proposal["expires_at"]) <= self._now():
            proposal["state"] = "expired"
            self._owner_persist()
        return proposal

    def _owner_answer(self, binding: dict, request: dict) -> str:
        proposal = self._owner_proposal()
        if proposal is None or proposal["proposal_id"] != request["payload"]["proposal_id"]:
            raise BoundaryError("not_found")
        if proposal["state"] != "pending":
            raise BoundaryError("version_mismatch")
        member_id = binding["member_id"]
        if member_id not in proposal["required_members"]:
            raise BoundaryError("proof_required")
        if member_id in proposal["accepted_members"] or member_id in proposal["declined_members"]:
            raise BoundaryError("request_conflict")
        if request["action"] == "accept_proposal":
            proposal["accepted_members"].append(member_id)
            state = "pending"  # Unanimity still waits for the host's boundary.
        else:
            proposal["declined_members"].append(member_id)
            proposal["state"] = "declined"
            state = "accepted"
        self._owner_persist(operation=request["request_id"])
        return state

    def _owner_affected(self) -> set[str]:
        """Only currently authorised gameplay members can be newly affected."""
        affected = set()
        for session in self._sessions.values():
            if session["revoked"]:
                continue
            try:
                capabilities = self.identity.capabilities(session["binding"]["grant_id"])
            except BoundaryError as exc:
                if exc.code not in {"proof_required", "stale_slot", "banned"}:
                    raise
                continue
            if "intent" in capabilities:
                affected.add(session["binding"]["member_id"])
        return affected

    def propose_owner_change(self, *, proposal_id: str, proposed_ms: str,
                             boundary_segment_id: str, expires_at: str,
                             required_members: list[str]) -> dict:
        """Host-only creation; persist a never-reused id before any answer."""
        with self._lock:
            self._guard()
            self._owner_require_published()
            current = self._owner_proposal()
            if current is not None and current["state"] == "pending":
                raise BoundaryError("request_conflict")
            validate("Id", proposal_id)
            if proposal_id in self._owner_state["proposal_ids"]:
                raise BoundaryError("request_conflict")
            if len(self._owner_state["proposal_ids"]) >= 4096:
                raise BoundaryError("rate_limited")
            if type(required_members) is not list:
                raise BoundaryError("bad_message")
            terms = self._owner_state["terms"]
            proposal = dict(proposal_id=proposal_id, row="input_interval_ms", current_ms=terms["input_interval_ms"],
                proposed_ms=proposed_ms, effective_version=str(int(terms["version"]) + 1),
                boundary_segment_id=boundary_segment_id, required_members=deepcopy(required_members),
                accepted_members=[], declined_members=[], expires_at=expires_at, state="pending")
            validate("OwnerProposal", proposal)
            self._owner_check_proposed(proposal)
            self._owner_state["proposal_ids"].append(proposal_id)
            self._owner_state["proposal"] = proposal
            self._owner_persist()
            return deepcopy(proposal)

    def _owner_check_proposed(self, proposal: dict) -> None:
        # Limit unresolved consent to one day, using only the trusted host clock.
        now = self._now()
        if (not 1000 <= int(proposal["proposed_ms"]) <= 60000
                or proposal["proposed_ms"] == proposal["current_ms"]
                or not now < int(proposal["expires_at"]) <= now + 86_400_000
                or not proposal["required_members"]
                or set(proposal["required_members"]) != self._owner_affected()):
            raise BoundaryError("bad_message")

    def apply_owner_boundary(self, segment_id: str) -> bool:
        """Apply unanimous, unexpired terms only at the host's named fence."""
        with self._lock:
            self._guard()
            validate("Id", segment_id)
            proposal = self._owner_proposal()
            if proposal is None or proposal["state"] != "pending":
                return False
            if (segment_id != proposal["boundary_segment_id"]
                    or set(proposal["accepted_members"]) != set(proposal["required_members"])
                    or not self._owner_affected().issubset(proposal["required_members"])):
                return False
            if self.owner_apply_terms is None:
                raise BoundaryError("recovery_pending")
            terms = dict(self._owner_state["terms"], version=proposal["effective_version"],
                         input_interval_ms=proposal["proposed_ms"])
            # Persist the activation intent first. An unknown host result must
            # reconcile this same fence during recovery, never retry blindly.
            self._security("owner_terms_boundary", dict(segment_id=segment_id, terms=terms,
                                                        proposal=deepcopy(proposal)))
            self._owner_apply_proposal(proposal, terms)
            return True

    def _owner_apply_proposal(self, proposal: dict, terms: dict) -> None:
        try:
            if self.owner_apply_terms(deepcopy(terms)) is not True:
                raise BoundaryError("recovery_pending")
            self._owner_state["terms"] = terms
            self._owner_interval(terms["input_interval_ms"])
            for member_id in proposal["accepted_members"]:
                self._owner_accept(member_id, terms["version"])
            proposal["state"] = "accepted"
            self._owner_persist()
        except Exception:
            self._failed = True
            raise BoundaryError("recovery_pending") from None

    def _owner_control_consent(self, binding: dict) -> None:
        self._owner_require_published()
        version = self._owner_state["terms"]["version"]
        # Version one is the original admission contract. Every later version
        # requires an explicit acceptance or its member's proposal answer.
        if version != "1" and dict(member_id=binding["member_id"], version=version) not in self._owner_state["accepted"]:
            raise BoundaryError("version_mismatch")

    def _owner_require_published(self) -> None:
        if not self._owner_state["terms_published"]:
            raise BoundaryError("version_mismatch")

    def publish_owner_terms(self) -> dict:
        """Trusted host only: durably publish the configured draft exactly once.

        Advance beyond the version-one compatibility gate and discard all old
        acceptance. A failed journal commit closes authority without an ack.
        Later changes still use unanimous host-boundary proposals.
        """
        with self._lock:
            self._guard()
            if self._owner_state["terms_published"]:
                raise BoundaryError("request_conflict")
            terms = dict(self._owner_state["terms"], version=str(max(2, int(self._owner_state["terms"]["version"]) + 1)))
            validate("OwnerTerms", terms)
            self._owner_state.update(terms=terms, terms_published=True, accepted=[], proposal=None)
            self._owner_persist()
            return deepcopy(terms)

    def _owner_moderate(self, binding, request):
        action = request["action"]
        target_id = request["payload"]["target_member_id"]
        if target_id == binding["member_id"]:
            raise BoundaryError("proof_required")
        target = next((m for m in self._owner_state["members"] if m["member_id"] == target_id), None)
        if target is None:
            raise BoundaryError("not_found")
        affected = [s for s in self._sessions.values() if not s["revoked"] and
                    (s["binding"]["member_id"] == target_id if action == "remove_member" else
                     s["binding"]["account_id"] == target["account_id"] or s["binding"]["nft_token_id"] == target["nft_token_id"])]
        if action == "lift_block":
            affected = []
            if target["account_id"] not in self._denied_accounts and target["nft_token_id"] not in self._denied_tokens:
                raise BoundaryError("not_found")
            self._denied_accounts.discard(target["account_id"])
            self._denied_tokens.discard(target["nft_token_id"])
        else:
            if action == "remove_member" and not affected:
                raise BoundaryError("not_found")
            if action == "block_member":
                self._denied_accounts.add(target["account_id"])
                self._denied_tokens.add(target["nft_token_id"])
            # Local emergency denial precedes all I/O, even when the journal is
            # down. Old sockets, tokens and resume authority stay unusable.
            for session in affected:
                self._revoke(session)
        self._owner_persist(operation=dict(action=action, request_id=request["request_id"],
                                          target_member_id=target_id, reason=request["payload"]["reason"]))
        boundary = None
        pending = False
        for session in affected:
            try:
                self.slots.release(session["record"])
            except SlotError as exc:
                if exc.code != "stale_slot":
                    raise
            ack = _check(self.bridge.release(session["binding"]))
            validate("ReleaseAck", ack)
            if ack["binding"] != session["binding"] or ack["revoked"] is not True:
                self._failed = True
                raise BoundaryError("recovery_pending")
            boundary = ack["boundary"]
            pending = pending or boundary["kind"] != "released"
        outcome = dict(target_member_id=target_id, target_name=target["name"],
            outcome={"remove_member": "removed", "block_member": "blocked", "lift_block": "block_lifted"}[action],
            boundary=boundary)
        moderation = self._owner_state["moderation"]
        moderation[:] = [m for m in moderation if m["viewer_account_id"] != binding["account_id"]]
        moderation.append(dict(viewer_account_id=binding["account_id"], outcome=outcome))
        self._owner_persist()
        return "pending" if pending else "accepted"

    def _owner_snapshot(self, session, grant):
        binding = session["binding"]
        moderates = "room_moderate" in grant["capabilities"]
        budget = None if self.owner_budget is None else _call(self.owner_budget, deepcopy(binding))
        if budget is not None:
            validate("OwnerLimits", budget)
        proposal = self._owner_proposal()
        active = {s["binding"]["member_id"]: s for s in self._sessions.values() if not s["revoked"]}
        members = []
        records = sorted(self._owner_state["members"], key=lambda m: m["member_id"] not in active)
        for record in records:
            member_id = record["member_id"]
            current = active.get(member_id)
            blocked = record["account_id"] in self._denied_accounts or record["nft_token_id"] in self._denied_tokens
            if current is None and not blocked:
                continue
            member = dict(member_id=member_id, name=record["name"],
                is_house=record["nft_token_id"] in self.house_tokens,
                place="blocked" if blocked else "disconnected" if moderates and current["connection"] is None else
                    "ring" if current["fighter"] is not None else "bench",
                verified=current is not None)
            if moderates:
                member["connected"] = current is not None and current["connection"] is not None
            members.append(member)
        moderation = next((m["outcome"] for m in self._owner_state["moderation"]
                           if m["viewer_account_id"] == binding["account_id"]), None)
        terms = self._owner_state["terms"]
        snapshot = dict(room_id=self.context["room_id"], name=self.context["room_id"],
            viewer_member_id=binding["member_id"], is_room_owner=moderates,
            declared_model=session["record"]["model"], grant_status="verified", limits=budget,
            terms=(dict(terms, accepted=dict(member_id=binding["member_id"], version=terms["version"]) in self._owner_state["accepted"])
                   if self._owner_state["terms_published"] else None),
            members=members, proposal=deepcopy(proposal), moderation=deepcopy(moderation), waiting_count=None,
            admission_closed=self.admission_open() is not True or proposal is not None and proposal["state"] == "pending",
            max_message_bytes=self.limits["max_control_bytes"])
        validate("OwnerSnapshot", snapshot)
        return snapshot

    def deny(self, *, account_id=None, nft_token_id=None):
        """Trusted operator adapter only; no guest route can call this method.

        Local denial is immediate even if the external journal is unavailable.
        A failed commit closes future authority and never acknowledges durability.
        Persisted bans must be injected again before a recovered service opens.
        """
        with self._lock:
            if account_id is not None:
                validate("AccountId", account_id)
                self._denied_accounts.add(account_id)
            if nft_token_id is not None:
                validate("TokenId", nft_token_id)
                self._denied_tokens.add(nft_token_id)
            affected = []
            for session in list(self._sessions.values()):
                binding = session["binding"]
                if not session["revoked"] and (binding["account_id"] in self._denied_accounts or binding["nft_token_id"] in self._denied_tokens):
                    affected.append(session)
                    self._revoke(session)
                    try:
                        self.slots.release(session["record"])
                    except SlotError:
                        pass  # Already expired or released confers no authority.
            self._security("ban", dict(account_id=account_id, nft_token_id=nft_token_id))
            try:
                for session in affected:
                    binding = session["binding"]
                    _check(self.bridge.release(binding))
            except Exception:
                self._failed = True
                raise BoundaryError("recovery_pending") from None
