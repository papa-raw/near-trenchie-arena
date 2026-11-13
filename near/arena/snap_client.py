"""Portable room client. Transport, wallet proof and signing stay with the owner."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from copy import deepcopy
from typing import Protocol
from urllib.parse import urlencode, urlsplit

from room.ledger import sealed_hash
from room.policy import canonical_bytes, digest, validate
try:
    from .battle_protocol import check_request as check_battle_request, check_receipt as check_battle_receipt, KINDS as BATTLE_KINDS, REQUEST_DOMAIN
except ImportError:
    from battle_protocol import check_request as check_battle_request, check_receipt as check_battle_receipt, KINDS as BATTLE_KINDS, REQUEST_DOMAIN

_BINDING = ("context", "grant_id", "session_key_id", "member_id", "nft_token_id",
            "persona_digest", "slot_id", "generation")
# Joint member-read contract: the room takes a signed read that expires within 15 s of its own clock
# (room/service.py _OWNER_READ_WINDOW_MS). The client's clock can run ahead of the room's (it adds the real time
# since the last reply between 50 ms ticks), so the read asks for 1 s less: a client ahead by under 1 s still passes.
_MEMBER_READ_WINDOW_MS = 15_000
_MEMBER_READ_MARGIN_MS = 1_000
_MEMBER_READ_TTL_MS = _MEMBER_READ_WINDOW_MS - _MEMBER_READ_MARGIN_MS
_CONTROL = {"observe": "ObserveRequest", "intent": "IntentRequest", "prediction": "PredictionRequest",
            "renew": "RenewRequest", "leave": "LeaveRequest", "behaviour": "BattleRequest", "speech": "BattleRequest",
            "bench": "BattleRequest", "note": "BattleRequest"}


class SnapTransport(Protocol):
    """Owner-supplied bounded HTTPS/WSS transport; never log private frames."""

    def request(self, method: str, target: str, body: bytes = b"") -> dict: ...
    def open_control(self, url: str) -> dict: ...
    def frame(self, connection_id: str, body: bytes) -> dict: ...
    def drain_private(self, connection_id: str) -> list[dict]: ...


# Seat refusals that leave a prediction locked and the member queued for the same life (room/service.py
# _activate, then _activate_when_ready): the room keeps the lock and starts that life when a seat opens. The lock
# step itself never returns these codes; version_mismatch is left out because the consent check can raise it
# before any lock exists.
SEAT_QUEUE_CODES = frozenset(("room_full", "ownership_unavailable"))


class SnapRefusal(ValueError):
    """A bounded protocol failure; no proof, token or response is echoed."""


class SnapClient:
    """Pin configuration before joining; a manifest never selects trust roots.

    ``prove_wallet(unsigned_join_bytes)`` returns the demonstrated WalletProof.
    ``sign_session(bytes)`` returns the owner's Ed25519 encoded signature.
    ``verify_room(key_id, bytes, signature)`` pins the independently obtained
    room keys. No credential or algorithm is inferred from a server message.
    Result destination context must be pinned separately from control context.
    Transport exceptions propagate, retaining exact pending control and join
    bytes. Identical join retries replay the original proof/challenge until
    verified success or its bounded expiry; changed join bindings refuse.
    """

    def __init__(self, context: dict, transport: SnapTransport, *, now_ms: Callable[[], int],
                 sign_session: Callable[[bytes], str], verify_room: Callable[[str, bytes, str], bool],
                 trusted_key_ids: Iterable[str], result_context: dict | None = None) -> None:
        validate("MainnetContext", context)
        if result_context is not None:
            validate("Context", result_context)
            common = ("version", "room_id", "deployment_id", "authority_epoch", "rules_hash")
            if any(result_context[key] != context[key] for key in common):
                raise SnapRefusal("context_mismatch")
            contracts = result_context["contract_ids"]
            destination = ("near:mainnet:" + contracts["arena"] + ":post_batch"
                           if result_context["network_id"] == "mainnet" else
                           "near:testnet:" + contracts["market"] + ":resolve")
            if result_context["audience"] != destination:
                raise SnapRefusal("context_mismatch")
        self._context = deepcopy(context)
        self._result_context = deepcopy(result_context)
        self._transport = transport
        self._now_ms, self._sign, self._verify = now_ms, sign_session, verify_room
        self._keys = frozenset(trusted_key_ids)
        if not self._keys:
            raise SnapRefusal("proof_required")
        self._control_url = "wss://" + urlsplit(context["audience"]).netloc + "/room/control"
        validate("ControlUrl", self._control_url)
        self._grant: dict | None = None
        self._connection: str | None = None
        self._sequence = 1
        self._pending: tuple[dict, bytes] | None = None
        self._pending_join: tuple[dict, dict, bytes] | None = None
        self._predictions: dict[str, dict] = {}
        # A prediction the room locked while the seat itself is still waiting: the room's receipt says refused with
        # the queue reason, and its signed lock reaches this client only in the sealed result of that life.
        self._queued: dict[str, dict] = {}

    def _checked(self, name: str, value: dict, context: dict | None = None) -> dict:
        if isinstance(value, dict) and value.get("type") == "error":
            validate("Error", value)
            raise SnapRefusal(value["code"])
        (check_battle_receipt(value) if name == 'BattleReceipt' else validate(name, value))
        if value.get("context") != (self._context if context is None else context):
            raise SnapRefusal("context_mismatch")
        return deepcopy(value)

    def _verified(self, name: str, value: dict, context: dict | None = None) -> dict:
        value = self._checked(name, value, context)
        if value["key_id"] not in self._keys:
            raise SnapRefusal("proof_required")
        try:
            valid = self._verify(value["key_id"], canonical_bytes(value, exclude=("signature",)),
                                 value["signature"]) is True
        except Exception:
            valid = False
        if not valid:
            raise SnapRefusal("proof_required")
        return value

    def _unexpired(self, value: dict) -> None:
        if int(value["expires_at"]) <= self._now_ms():
            raise SnapRefusal("proof_required")

    def _binding(self) -> dict:
        if self._grant is None:
            raise SnapRefusal("proof_required")
        return {key: deepcopy(self._grant[key]) for key in _BINDING}

    def _signed(self, name: str, value: dict) -> dict:
        value["signature"] = self._sign(canonical_bytes(value, exclude=("signature",)))
        (check_battle_request(value) if name == 'BattleRequest' else validate(name, value))
        return value

    def manifest(self) -> dict:
        return self._checked("Manifest", self._transport.request("GET", "/room"))

    def join(self, *, account_id: str, nft_token_id: str, persona_digest: str,
             session_public_key: dict, request_id: str, declared_compute: dict,
             prove_wallet: Callable[[bytes], dict]) -> dict:
        if self._grant is not None:
            raise SnapRefusal("request_conflict")
        arguments = dict(account_id=account_id, nft_token_id=nft_token_id, persona_digest=persona_digest,
            session_public_key=deepcopy(session_public_key), request_id=request_id, declared_compute=deepcopy(declared_compute))
        if self._pending_join is None:
            request = self._prepare_join(arguments, prove_wallet)
            self._pending_join = (arguments, request, canonical_bytes(request))
        pending_arguments, request, raw = self._pending_join
        if arguments != pending_arguments:
            raise SnapRefusal("request_conflict")
        self._unexpired(request["challenge"])
        reply = self._transport.request("POST", "/room/join", raw)
        name = "QueueStatus" if isinstance(reply, dict) and reply.get("status") == "spectating" else "JoinAccepted"
        try:
            reply = self._verified(name, reply)
        except SnapRefusal:
            # A temporary admission refusal is a completed response, not a lost response. A later attempt
            # needs a fresh challenge; transport failures still retain the exact pending request above.
            if isinstance(reply, dict) and reply.get("type") == "error" and reply.get("code") in (
                    "ownership_unavailable", "room_full", "rate_limited"):
                self._pending_join = None
            raise
        expected = dict(account_id=account_id, nft_token_id=nft_token_id, request_id=request_id,
                        request_digest=digest(request, exclude=("proof",)), message_domain=request["domain"])
        if any(reply[key] != value for key, value in expected.items()):
            raise SnapRefusal("context_mismatch")
        if name == "JoinAccepted":
            self._accept_grant(reply, persona_digest, session_public_key)
        self._pending_join = None
        return reply

    def _prepare_join(self, arguments: dict, prove_wallet: Callable[[bytes], dict]) -> dict:
        account_id, nft_token_id = arguments["account_id"], arguments["nft_token_id"]
        persona_digest, session_public_key = arguments["persona_digest"], arguments["session_public_key"]
        request_id, declared_compute = arguments["request_id"], arguments["declared_compute"]
        manifest = self.manifest()
        if manifest["admission"] != "open":
            raise SnapRefusal("admission_closed")
        challenge_request = dict(domain="room.join.v1", context=deepcopy(self._context),
            grant_id=None, session_key_id=None, account_id=account_id, nft_token_id=nft_token_id,
            persona_digest=persona_digest, session_public_key=deepcopy(session_public_key),
            request_id=request_id, purpose="join")
        validate("JoinChallengeRequest", challenge_request)
        challenge = self._verified("JoinChallenge", self._transport.request("POST", "/room/challenge",
            canonical_bytes(challenge_request)))
        if any(challenge[key] != value for key, value in challenge_request.items()):
            raise SnapRefusal("context_mismatch")
        self._unexpired(challenge)
        request = dict(domain="room.join.v1", context=deepcopy(self._context), grant_id=None,
            session_key_id=None, challenge=challenge, persona_digest=persona_digest,
            session_public_key=deepcopy(session_public_key), request_id=request_id,
            declared_compute=deepcopy(declared_compute), resume=None)
        request["proof"] = prove_wallet(canonical_bytes(request))
        validate("JoinRequest", request)
        if request["proof"]["method_id"] not in manifest["proof_methods"]:
            raise SnapRefusal("proof_required")
        return request

    def _accept_grant(self, grant: dict, persona_digest: str, session_public_key: dict) -> None:
        if (grant["control_url"] != self._control_url or grant["persona_digest"] != persona_digest
                or grant["session_public_key"] != session_public_key):
            raise SnapRefusal("context_mismatch")
        self._unexpired(grant)
        self._grant = grant

    def member_snapshot(self, *, request_id: str) -> dict:
        """Read self-bound terms with signed expiry; this never records consent.

        A fresh request id and expiry use the source's bounded durable read
        window. No legacy empty-payload fallback silently consumes write IDs.
        """
        freshness = {"expires_at": str(self._now_ms() + _MEMBER_READ_TTL_MS)}
        snapshot = self._member("snapshot", "snapshot", "0", request_id, payload=freshness)
        self._unexpired(freshness)  # A delayed signed reply must still be current when received.
        return snapshot

    def accept_terms(self, terms_version: str, *, request_id: str) -> dict:
        """Explicitly accept the exact version read by this owner runtime.

        An uncertain response requires a fresh member_snapshot request, rather
        than retrying the consumed write id or assuming that consent succeeded.
        """
        return self._member("terms/accept", "accept_terms", terms_version, request_id)

    @property
    def can_answer(self) -> bool:
        """Display hint from the proved grant; every write is authorized again."""
        return self._grant is not None and "intent" in self._grant["capabilities"]

    def answer_change(self, proposal_id: str, terms_version: str, *, accept: bool, request_id: str) -> dict:
        """Answer only the named change for this member, at its read version."""
        if type(accept) is not bool:
            raise SnapRefusal("bad_message")
        choice = "accept" if accept else "decline"
        snapshot = self._member("proposals/" + choice, choice + "_proposal", terms_version,
                                request_id, payload={"proposal_id": proposal_id})
        proposal = snapshot["proposal"]
        answers = "accepted_members" if accept else "declined_members"
        if (proposal is None or proposal["proposal_id"] != proposal_id
                or self._binding()["member_id"] not in proposal[answers]):
            raise SnapRefusal("bad_message")
        return snapshot

    def _member(self, route: str, action: str, version: str, request_id: str, *, payload: dict | None = None) -> dict:
        request = self._signed("OwnerRequest", dict(**self._binding(),
            domain="room.owner.v1", token=self._grant["token"], kind="owner_control",
            action=action, request_id=request_id, terms_version=version, payload={} if payload is None else deepcopy(payload)))
        reply = self._verified("OwnerResponse", self._transport.request(
            "POST", "/room/owner/" + route, canonical_bytes(request)))
        expected = dict(grant_id=request["grant_id"], session_key_id=request["session_key_id"],
            request_id=request_id, action=action, request_digest=digest(request, exclude=("signature",)))
        if (any(reply[key] != value for key, value in expected.items())
                or reply["snapshot"]["viewer_member_id"] != request["member_id"]
                or reply["snapshot"]["room_id"] != self._context["room_id"]):
            raise SnapRefusal("context_mismatch")
        if action == "accept_terms" and (reply["state"] != "accepted"
                or reply["snapshot"]["terms"] is None
                or reply["snapshot"]["terms"]["version"] != version
                or reply["snapshot"]["terms"]["accepted"] is not True):
            raise SnapRefusal("version_mismatch")
        return reply["snapshot"]

    def authenticate(self, *, request_id: str) -> dict:
        binding = self._binding()
        # A successful renewal extends server authority, not the original join
        # receipt's immutable expiry. Fresh signed ready proves current authority.
        challenge = self._verified("ControlChallenge", self._transport.open_control(self._control_url))
        self._unexpired(challenge)
        request = self._signed("ControlAuthenticate", dict(**binding, domain="room.control.v1",
            kind="authenticate", request_id=request_id, token=self._grant["token"], challenge=challenge))
        ready = self._verified("ControlReady", self._transport.frame(challenge["connection_id"], canonical_bytes(request)))
        expected = dict(**binding, connection_id=challenge["connection_id"], request_id=request_id,
                        request_digest=digest(request, exclude=("signature",)))
        if any(ready[key] != value for key, value in expected.items()):
            raise SnapRefusal("context_mismatch")
        self._connection = challenge["connection_id"]
        if ready["next_life"] is not None:
            self._notice(ready["next_life"])
        return ready

    def _notice(self, notice: dict) -> dict:
        notice = self._verified("LifeNotice", notice)
        if (any(notice[key] != value for key, value in self._binding().items())
                or notice["reservation"]["binding"] != {**self._binding(), "account_id": self._grant["account_id"]}):
            raise SnapRefusal("stale_slot")
        return notice

    def life_notices(self) -> list[dict]:
        if self._connection is None:
            raise SnapRefusal("proof_required")
        return [self._notice(value) for value in self._transport.drain_private(self._connection)]

    def control(self, kind: str, payload: dict, *, life_id: str | None = None) -> dict:
        if self._connection is None or kind not in _CONTROL:
            raise SnapRefusal("proof_required")
        domain = REQUEST_DOMAIN if kind in BATTLE_KINDS else "room.prediction.v1" if kind == "prediction" else "room.control.v1"
        request = dict(**self._binding(), domain=domain,
                       sequence=str(self._sequence), life_id=life_id, kind=kind, payload=deepcopy(payload))
        if self._pending is None:
            request = self._signed(_CONTROL[kind], request)
            self._pending = (request, canonical_bytes(request))
        elif canonical_bytes(request) != canonical_bytes(self._pending[0], exclude=("signature",)):
            raise SnapRefusal("request_conflict")
        request, raw = self._pending
        reply = self._verified("BattleReceipt" if kind in BATTLE_KINDS else "Receipt", self._transport.frame(self._connection, raw))
        expected = dict(grant_id=request["grant_id"], session_key_id=request["session_key_id"],
            sequence=request["sequence"], request_digest=digest(request, exclude=("signature",)))
        if kind in BATTLE_KINDS:
            expected.update(self._binding(), kind=kind, life_id=life_id)
        else:
            expected['message_domain'] = request['domain']
        if any(reply[key] != value for key, value in expected.items()):
            raise SnapRefusal("context_mismatch")
        if kind == "prediction" and reply["state"] == "accepted":
            lock = reply["prediction_lock"]
            if lock is None or lock["life_id"] != life_id or lock["prediction_hash"] != expected["request_digest"]:
                raise SnapRefusal("prediction_closed")
            self._predictions[life_id] = {"receipt": deepcopy(reply), "request": deepcopy(request)}
        elif kind == "prediction" and reply["state"] == "refused" and reply.get("code") in SEAT_QUEUE_CODES:
            self._queued[life_id] = deepcopy(request)
        self._pending = None
        self._sequence += 1
        return reply

    def observe(self) -> dict:
        snapshot = self._checked("PublicSnapshot", self._transport.request("GET", "/room/observe"))
        if snapshot["clock"]["context"] != self._context or snapshot["snapshot_hash"] != digest(snapshot, exclude=("snapshot_hash",)):
            raise SnapRefusal("bad_message")
        return snapshot

    def result(self, segment_id: str) -> dict:
        if self._result_context is None:
            raise SnapRefusal("recovery_pending")
        validate("Id", segment_id)
        value = self._verified("Result", self._transport.request("GET", "/room/result?" + urlencode(dict(segment_id=segment_id))),
                               self._result_context)
        if value["segment_id"] != segment_id or value["sealed_result_hash"] != sealed_hash(value):
            raise SnapRefusal("bad_message")
        own = [life for life in value["lives"] if life["nft_token_id"] == self._binding()["nft_token_id"]]
        if not own:
            raise SnapRefusal("result_pending")
        for life in own:
            queued = self._queued.get(life["life_id"])
            if queued is not None and life["life_id"] not in self._predictions:
                lock = life["prediction_lock"]
                if lock["prediction_hash"] != digest(queued, exclude=("signature",)) or lock["life_id"] != life["life_id"]:
                    raise SnapRefusal("bad_message")
                # The room-signed result now carries the lock the queued receipt could not.
                self._predictions[life["life_id"]] = {"receipt": {"prediction_lock": deepcopy(lock)}, "request": queued}
                del self._queued[life["life_id"]]
            known = self._predictions.get(life["life_id"])
            if known is not None and life["prediction_lock"] != known["receipt"]["prediction_lock"]:
                raise SnapRefusal("bad_message")
        return value

    def prediction_row(self, segment_id: str, life_id: str, *, max_pages: int = 16) -> dict:
        """Bind the public row to a fresh signed result and full private receipt."""
        validate("Id", segment_id)
        validate("Id", life_id)
        if type(max_pages) is not int or not 1 <= max_pages <= 256:
            raise SnapRefusal("bad_message")
        anchor = self.result(segment_id)
        rows, cursor = [], None
        for _ in range(max_pages):
            query = dict(segment_id=segment_id)
            if cursor is not None:
                query["after_index"] = cursor
            page = self._checked("ReplayPage", self._transport.request("GET", "/room/replay?" + urlencode(query)))
            if page["segment_id"] != segment_id or page["rules_hash"] != self._context["rules_hash"]:
                raise SnapRefusal("context_mismatch")
            if page["inputs_hash"] != anchor["inputs_hash"]:
                raise SnapRefusal("bad_message")
            rows.extend(page["input_events"])
            next_index = page["next_index"]
            if next_index is None:
                return self._prediction_row(rows, anchor["inputs_hash"], life_id)
            if cursor is not None and int(next_index) <= int(cursor):
                raise SnapRefusal("bad_message")
            cursor = next_index
        raise SnapRefusal("rate_limited")

    def _prediction_row(self, rows: list[dict], commitment: str, life_id: str) -> dict:
        if digest(rows) != commitment:
            raise SnapRefusal("bad_message")
        known = self._predictions.get(life_id)
        if known is None:
            raise SnapRefusal("not_found")
        for row in rows:
            if row["kind"] != "prediction_lock" or row["life_id"] != life_id:
                continue
            if (row["nft_token_id"] != self._binding()["nft_token_id"]
                    or row["payload"]["prediction_lock"] != known["receipt"]["prediction_lock"]
                    or any(row["payload"][key] != known["request"]["payload"][key]
                           for key in ("loadout", "moves", "lock"))):
                raise SnapRefusal("bad_message")
            return deepcopy(row)
        raise SnapRefusal("not_found")
