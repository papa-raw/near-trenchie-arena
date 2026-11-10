"""Testnet-only in-process contract adapter. No RPC, signer or transaction code."""
from __future__ import annotations

from copy import deepcopy
from threading import RLock

from .signing import permit_bytes, persona_digest, verify
from .contract import PRESETS, PERMIT_TTL_MS, MINT_COST

class MockContract:
    """Confirmed-state mock for held claims and direct wallet-paid permit mint.

    Fixed 5×10 genesis inventory models already minted tokens. `set_sale_ready`
    models a confirmed settlement receipt; it never predicts a batch outcome.
    """

    synthetic = True

    def __init__(self, *, network_id: str, contract_id: str, custodian: str,
                 minter: str, permit_public_key: str) -> None:
        if network_id != 'testnet' or not all(value.endswith('.testnet') for value in (contract_id, custodian, minter)):
            raise ValueError('mock requires testnet accounts')
        self.network_id, self.contract_id = network_id, contract_id
        self.custodian, self.minter = custodian, minter
        self.permit_public_key = permit_public_key
        self.epoch = '1'
        self.available = True
        self.claims: list[dict] = []
        self._lock = RLock()
        self._used: set[str] = set()
        self._tokens = {f'{preset}-{copy:02}': dict(token_id=f'{preset}-{copy:02}', preset_id=preset,
            owner_id=custodian, persona_digest=persona_digest(persona), sale_ready=True, chain_height='1')
            for preset, persona in PRESETS.items() for copy in range(10)}

    def inventory(self) -> list[dict]:
        with self._lock:
            return [deepcopy(value) for value in self._tokens.values() if not value.get('paid')]

    def token(self, token_id: str) -> dict:
        with self._lock:
            if not self.available:
                raise OSError('contract read unavailable')
            return deepcopy(self._tokens[token_id])

    def set_sale_ready(self, token_id: str, value: bool) -> None:
        with self._lock:
            self._tokens[token_id]['sale_ready'] = value

    def claim(self, token_id: str, recipient: str, digest: str, *, caller: str) -> dict:
        from .arrival import ArrivalRefusal
        with self._lock:
            token = self.token(token_id)
            if caller != self.minter or digest != token['persona_digest']:
                raise ArrivalRefusal('proof_required')
            if token['owner_id'] == recipient:
                return token
            if token['owner_id'] != self.custodian or token['sale_ready'] is not True:
                raise ArrivalRefusal('claim_pending')
            self._tokens[token_id]['owner_id'] = recipient
            self.claims.append(dict(token_id=token_id, recipient=recipient, persona_digest=digest))
            return self.token(token_id)

    def paid_mint(self, permit: dict, *, caller: str, signer: str, persona: dict,
                  attached_deposit: str, now_ms: int) -> dict:
        """One atomic direct call verifies name/persona/caller/context/time/nonce."""
        from .arrival import ArrivalRefusal
        with self._lock:
            try:
                payload = permit['payload']
                body = permit_bytes(payload)
                unsigned = int(payload['issued_at']), int(payload['expires_at'])
                valid = (set(permit) == {'payload', 'signature'}
                    and self._permit_context(payload)
                    and self._permit_persona(payload, persona)
                    and caller == signer == payload['caller']
                    and unsigned[0] <= now_ms < unsigned[1]
                    and 0 < unsigned[1] - unsigned[0] <= PERMIT_TTL_MS
                    and payload['nonce'] not in self._used
                    and type(attached_deposit) is str and attached_deposit.isdecimal()
                    and int(attached_deposit) == int(MINT_COST)
                    and verify(self.permit_public_key, body, permit['signature']))
            except (KeyError, ValueError, TypeError):
                valid = False
            if not valid:
                raise ArrivalRefusal('invalid_mint_permit')
            token_id = 'paid-' + payload['nonce']
            token = dict(token_id=token_id, preset_id=payload['preset_id'], owner_id=caller,
                persona_digest=payload['persona_digest'], sale_ready=True, chain_height='1', paid=True)
            self._used.add(payload['nonce'])
            self._tokens[token_id] = token
            return deepcopy(token)

    def _permit_context(self, payload: dict) -> bool:
        return (payload['domain'] == 'game.mint-permit.v1' and payload['schema'] == '1'
            and payload['epoch'] == self.epoch and payload['network_id'] == self.network_id
            and payload['contract_id'] == self.contract_id)

    @staticmethod
    def _permit_persona(payload: dict, persona: dict) -> bool:
        return (payload['name'] == persona['name'] and payload['preset_id'] == persona['preset_id']
            and payload['persona_digest'] == persona_digest(persona))
