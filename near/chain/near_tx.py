"""NEAR transactions of FunctionCall actions: base58, borsh encoding, ed25519 signing, and decoding.

Only what the arena writer and the stake resolver send: one signer, one receiver, FunctionCall actions.
The decoder reads back exactly what the encoder writes, so the fake RPC and the archival reader can
check a signed transaction byte for byte. A private key is held in memory only; nothing here prints it.
"""

import base64
import hashlib
import json
import struct
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
TGAS = 10 ** 12
MAX_TGAS = 300
FUNCTION_CALL = 2


def b58encode(raw: bytes) -> str:
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = B58[r] + out
    return "1" * (len(raw) - len(raw.lstrip(b"\0"))) + out


def b58decode(text: str) -> bytes:
    n = 0
    for c in text:
        i = B58.find(c)
        if i < 0:
            raise ValueError("not base58")
        n = n * 58 + i
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * (len(text) - len(text.lstrip("1"))) + raw


def args_bytes(args) -> bytes:
    """The exact bytes a call carries: compact JSON, keys in the order given."""
    return json.dumps(args, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


@dataclass(frozen=True)
class Action:
    method: str
    args: object
    tgas: int
    deposit: int = 0

    def __post_init__(self):
        if not 0 < self.tgas <= MAX_TGAS:
            raise ValueError("gas is 1 to 300 Tgas")
        if type(self.deposit) is not int or self.deposit < 0:
            raise ValueError("deposit is yoctoNEAR, a whole number")


class Key:
    """One ed25519 access key. `repr` and `str` never show the private half."""

    def __init__(self, account_id: str, public_key: str, private_key: str):
        if not public_key.startswith("ed25519:") or not private_key.startswith("ed25519:"):
            raise ValueError("only ed25519 keys are supported")
        self.account_id = account_id
        self.public_key = public_key
        seed = b58decode(private_key.split(":", 1)[1])[:32]
        self._sk = Ed25519PrivateKey.from_private_bytes(seed)
        derived = self._sk.public_key().public_bytes_raw()
        if derived != b58decode(public_key.split(":", 1)[1]):
            raise ValueError("the key file's public key does not match its private key")

    @property
    def public_bytes(self) -> bytes:
        return b58decode(self.public_key.split(":", 1)[1])

    def sign(self, message: bytes) -> bytes:
        return self._sk.sign(message)

    def __repr__(self):
        return f"Key({self.account_id}, {self.public_key})"

    __str__ = __repr__

    @classmethod
    def generate(cls, account_id: str) -> "Key":
        """A throwaway key for tests and the fake RPC; never written anywhere."""
        sk = Ed25519PrivateKey.generate()
        seed = sk.private_bytes_raw()
        pub = sk.public_key().public_bytes_raw()
        return cls(account_id, "ed25519:" + b58encode(pub), "ed25519:" + b58encode(seed + pub))


def _s(text: str) -> bytes:
    raw = text.encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


def encode_tx(signer_id: str, public_key: bytes, nonce: int, receiver_id: str, block_hash: bytes,
              actions: list[Action]) -> bytes:
    body = b""
    for a in actions:
        raw = args_bytes(a.args)
        body += (bytes([FUNCTION_CALL]) + _s(a.method) + struct.pack("<I", len(raw)) + raw
                 + struct.pack("<Q", a.tgas * TGAS) + a.deposit.to_bytes(16, "little"))
    return (_s(signer_id) + b"\x00" + public_key + struct.pack("<Q", nonce) + _s(receiver_id) + block_hash
            + struct.pack("<I", len(actions)) + body)


def sign_tx(key: Key, nonce: int, receiver_id: str, block_hash: bytes, actions: list[Action]) -> tuple[str, bytes]:
    """Returns (the tx hash in base58, the signed transaction bytes)."""
    tx = encode_tx(key.account_id, key.public_bytes, nonce, receiver_id, block_hash, actions)
    digest = hashlib.sha256(tx).digest()
    return b58encode(digest), tx + b"\x00" + key.sign(digest)


class _Reader:
    def __init__(self, raw: bytes):
        self.raw, self.at = raw, 0

    def take(self, n: int) -> bytes:
        if self.at + n > len(self.raw):
            raise ValueError("truncated transaction")
        out = self.raw[self.at:self.at + n]
        self.at += n
        return out

    def u8(self):
        return self.take(1)[0]

    def u32(self):
        return struct.unpack("<I", self.take(4))[0]

    def u64(self):
        return struct.unpack("<Q", self.take(8))[0]

    def string(self):
        return self.take(self.u32()).decode("utf-8")


def decode_signed_tx(signed: bytes) -> dict:
    """Parse a signed FunctionCall transaction and check its signature. Raises on anything else."""
    r = _Reader(signed)
    signer = r.string()
    if r.u8() != 0:
        raise ValueError("only ed25519 signers")
    pk = r.take(32)
    nonce = r.u64()
    receiver = r.string()
    block_hash = r.take(32)
    actions = []
    for _ in range(r.u32()):
        if r.u8() != FUNCTION_CALL:
            raise ValueError("only FunctionCall actions")
        method = r.string()
        args = json.loads(r.take(r.u32()))
        gas = r.u64()
        deposit = int.from_bytes(r.take(16), "little")
        actions.append({"method": method, "args": args, "gas": gas, "deposit": deposit})
    tx_end = r.at
    if r.u8() != 0:
        raise ValueError("only ed25519 signatures")
    sig = r.take(64)
    if r.at != len(signed):
        raise ValueError("trailing bytes after the signature")
    digest = hashlib.sha256(signed[:tx_end]).digest()
    Ed25519PublicKey.from_public_bytes(pk).verify(sig, digest)
    return {"hash": b58encode(digest), "signer_id": signer, "public_key": "ed25519:" + b58encode(pk),
            "nonce": nonce, "receiver_id": receiver, "block_hash": b58encode(block_hash), "actions": actions}


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()
