"""Game-owned assembly of the installed room, with all authority injected."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from copy import deepcopy
from typing import Protocol

from room.bridge import GameBridge, MainnetContext, Receipt, SlotBinding
from room.identity import IdentityAuthority
from room.policy import BoundaryError, GuestPolicy, validate
from room.service import RoomService
from room.slots import SlotStore


class PublicRecords(Protocol):
    """Read-only game adapter; absent records retain the room's refusal."""

    def page(self, after_index: str | None = None) -> dict: ...
    def replay(self, segment_id: str, after_index: str | None = None) -> dict: ...
    def result(self, segment_id: str) -> dict: ...


class RoomHost:
    """Bind one room authority to the actual engine bridge during Arena setup.

    Supply this object as ``room_factory``, and its ``sign_receipt``,
    ``admission_ready`` and ``life_guard`` methods as Arena's corresponding
    adapters. Wallet/chain evidence remains the game's identity resolver.
    Signers, session verification, durable nonce consumption, the external
    security journal and recovery/admission gates are host responsibilities.
    No default proof method, signing key, readiness or open admission exists.
    A transport receives only Arena.control, never this host object.
    """

    def __init__(self, slots: SlotStore, context: MainnetContext, *,
                 now_ms: Callable[[], int], sign: Callable[[bytes], str],
                 verify_session: Callable[[dict, bytes, str], bool], key_id: str,
                 consume_nonce: Callable[[str, str], bool],
                 security_event: Callable[[dict], bool], proof_methods: Iterable[str] = (),
                 ready: Callable[[], bool] | None = None,
                 admission_open: Callable[[], bool] | None = None,
                 records: PublicRecords | None = None, house_tokens: Iterable[str] = (),
                 policy: GuestPolicy | None = None, owner_state: dict | None = None,
                 owner_member_name: Callable[[dict], str] | None = None) -> None:
        validate("MainnetContext", context)
        if slots.room_id != context["room_id"] or slots.capacity != 16:
            raise BoundaryError("context_mismatch")
        self.slots = slots
        self._context = deepcopy(context)
        self.now_ms = now_ms
        self._sign = sign
        self._verify_session = verify_session
        self.key_id = key_id
        self._consume_nonce = consume_nonce
        self._security_event = security_event
        self._proof_methods = tuple(proof_methods)
        self._ready = ready
        self._admission_open = admission_open
        self._records = records
        self._house_tokens = tuple(house_tokens)
        self._policy = policy
        self._owner_state = deepcopy(owner_state)
        self._owner_member_name = owner_member_name
        self.identity: IdentityAuthority | None = None
        self.service: RoomService | None = None

    def is_ready(self) -> bool:
        """An unavailable recovery/journal/nonce/proof dependency closes authority."""
        if (self._ready is None or self._security_event is None
                or self._consume_nonce is None or not self._proof_methods):
            return False
        try:
            return self._ready() is True
        except Exception:
            return False

    def admission_ready(self) -> bool:
        """Use the same explicit admission decision in the game and the room."""
        if self.service is None or not self.is_ready() or self._admission_open is None:
            return False
        try:
            return self._admission_open() is True
        except Exception:
            return False

    def __call__(self, bridge: GameBridge) -> RoomService:
        if self.service is not None:
            raise ValueError("room host is already bound to an engine")
        identity = IdentityAuthority(self._context, bridge, now_ms=self.now_ms,
            sign=self._sign, verify_session=self._verify_session, key_id=self.key_id,
            proof_methods=self._proof_methods, ready=self.is_ready, consume_nonce=self._consume_nonce)
        service = RoomService(self.slots, bridge, identity, now_ms=self.now_ms,
            ready=self.is_ready, admission_open=self.admission_ready,
            security_event=self._security_event, records=self._records,
            house_tokens=self._house_tokens, policy=self._policy,
            owner_state=self._owner_state, owner_member_name=self._owner_member_name)
        self.identity, self.service = identity, service
        return service

    def sign_receipt(self, receipt: Receipt) -> Receipt:
        """Delegate to the installed authority's closed receipt-domain signer."""
        if self.identity is None or not self.is_ready():
            raise BoundaryError("recovery_pending")
        return self.identity.sign_message(receipt)

    def life_guard(self, binding: SlotBinding) -> bool:
        """Recheck current grant, generation and fresh owner/lock evidence."""
        if self.identity is None or not self.is_ready():
            return False
        try:
            grant = self.identity.grant(binding["grant_id"])
            checked = self.identity.authenticate_resume({
                "prior_grant_id": binding["grant_id"],
                "prior_generation": binding["generation"], "resume_token": grant["token"]})
            return checked["binding"] == binding
        except (BoundaryError, KeyError):
            return False
