"""Game contract port and fixed synthetic presets for the local acceptance path."""
from __future__ import annotations

from typing import Protocol

PRESETS = {f'preset-{index}': dict(name='Pebble', preset_id=f'preset-{index}', cosmetics={})
           for index in range(1, 6)}
PERMIT_TTL_MS = 60_000
MINT_COST = '100'  # Synthetic yoctoNEAR fixture cost, never a deployed price.


class Contract(Protocol):
    network_id: str
    contract_id: str
    custodian: str
    minter: str

    def inventory(self) -> list[dict]: ...
    def token(self, token_id: str) -> dict: ...
    def claim(self, token_id: str, recipient: str, digest: str, *, caller: str) -> dict: ...
