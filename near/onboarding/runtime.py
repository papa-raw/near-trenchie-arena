"""Fight-first owner-runtime controller; wallet connection is an explicit action."""
from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Protocol

from .arrival import ArrivalRefusal, ArrivalService
from .signing import account_id, canonical, encode, session_key


class ArrivalClient(Protocol):
    def join(self, **arguments: object) -> dict: ...


class FightFirstSession:
    """Own one visitor key/client; never accept another member's client.

    Compute is provided by the visitor's runtime. The controller asks for no
    wallet while holding, accepting terms, predicting, or fighting. It invokes
    the owner-provided wallet callback only from claim() or stake_wallet().
    The wallet adapter returns (proved account id, proof signer); its actual
    account-control verification remains the service's independently configured
    wallet_verify port. No model credential or wallet secret enters the room.
    """

    def __init__(self, service: ArrivalService, client: ArrivalClient, *, public_key: str,
                 sign_session: Callable[[bytes], bytes],
                 connect_wallet: Callable[[], tuple[str, Callable[[bytes], str]]]) -> None:
        account_id(public_key)
        self.service, self.client, self.public_key = service, client, public_key
        self._sign, self._connect_wallet = sign_session, connect_wallet
        self.hold: dict | None = None
        self._begin_binding: dict | None = None
        self._admitted = False

    def begin(self, preset_id: str, request_id: str, *, device_id: str, ip: str, compute: dict) -> dict:
        binding = dict(preset_id=preset_id, request_id=request_id, device_id=device_id, ip=ip, compute=deepcopy(compute))
        if self.hold is not None and (self._admitted or binding != self._begin_binding):
            raise ArrivalRefusal('request_conflict')
        if self.hold is None:
            challenge = self.service.challenge(self.public_key, preset_id, request_id, device_id=device_id, ip=ip)
            held = self.service.allocate(challenge, encode(self._sign(canonical(challenge))))
            if held['state'] == 'paid_mint_required':
                return held
            self.hold = held
            self._begin_binding = binding
        held = self.hold
        # The native join proof rechecks current custody. Reissuing allocation
        # challenges here would consume quotas and cannot reconcile a lost join.
        self.client.join(account_id=held['account_id'], nft_token_id=held['token_id'],
            persona_digest=held['persona_digest'], session_public_key=session_key(self.public_key),
            request_id=request_id, declared_compute=deepcopy(compute),
            prove_wallet=lambda body: dict(method_id='visitor_session_v1', key_id=held['reservation_id'],
                                          proof_bytes=encode(self._sign(body))))
        self._admitted = True
        return deepcopy(held)

    def claim(self) -> dict:
        if self.hold is None:
            raise ArrivalRefusal('proof_required')
        if self.service.next_step(self.hold['reservation_id']) == 'fight':
            raise ArrivalRefusal('fight_first')
        account, wallet_sign = self._connect_wallet()
        challenge = self.service.claim_challenge(self.hold['reservation_id'], account)
        body = canonical(challenge)
        return self.service.claim(challenge, visitor_signature=encode(self._sign(body)), wallet_proof=wallet_sign(body))

    def paid_wallet_permit(self, preset_id: str) -> dict:
        """Explicit wallet step after run-out; return a newly signed caller binding."""
        account, wallet_sign = self._connect_wallet()
        challenge = self.service.paid_wallet_challenge(self.public_key, preset_id, account)
        body = canonical(challenge)
        return self.service.paid_wallet_permit(challenge, visitor_signature=encode(self._sign(body)),
                                              wallet_proof=wallet_sign(body))

    def stake_wallet(self) -> str:
        """Return the connected account; deposits/spend stay in the stake flow."""
        account, _ = self._connect_wallet()
        return account
