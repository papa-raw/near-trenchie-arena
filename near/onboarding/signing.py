"""Explicit Ed25519 helpers and the game-owned permit's frozen byte encoding."""
from __future__ import annotations

import base64
import hashlib
import json
import struct

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

PERMIT_FIELDS = ('domain', 'schema', 'epoch', 'network_id', 'contract_id', 'caller',
                 'name', 'persona_digest', 'preset_id', 'nonce', 'issued_at', 'expires_at')


def canonical(value: dict) -> bytes:
    """Canonical JSON for game requests; floats are outside this API."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


def decode(value: str, length: int) -> bytes:
    if type(value) is not str or len(value) > 128:
        raise ValueError('invalid signature encoding')
    raw = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True)
    if len(raw) != length or encode(raw) != value:
        raise ValueError('invalid signature encoding')
    return raw


def public_key(key: Ed25519PrivateKey) -> str:
    return encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


def session_key(public: str) -> dict:
    decode(public, 32)
    return dict(algorithm='ed25519', public_key=public)


def account_id(public: str) -> str:
    """Implicit-address session principal; does not assert an account exists."""
    return decode(public, 32).hex()


def sign(key: Ed25519PrivateKey, value: dict) -> str:
    return encode(key.sign(canonical(value)))


def verify(public: str, body: bytes, signature: str) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(decode(public, 32)).verify(decode(signature, 64), body)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def verify_session(public: dict, body: bytes, signature: str) -> bool:
    return (public.get('algorithm') == 'ed25519'
            and set(public) == {'algorithm', 'public_key'}
            and verify(public['public_key'], body, signature))


def persona_digest(persona: dict) -> str:
    return hashlib.sha256(canonical(persona)).hexdigest()


def permit_bytes(payload: dict) -> bytes:
    """v1: fixed field order, each UTF-8 string prefixed by u32 big endian length.

    Reject extra/missing fields and nonstrings. Both issuer and contract mock
    reconstruct these bytes; no JSON serializer participates in this signature.
    """
    if set(payload) != set(PERMIT_FIELDS):
        raise ValueError('invalid permit fields')
    parts = []
    for field in PERMIT_FIELDS:
        value = payload[field]
        if type(value) is not str or len(value.encode()) > 1024:
            raise ValueError('invalid permit value')
        raw = value.encode('utf-8')
        parts.extend((struct.pack('>I', len(raw)), raw))
    return b''.join(parts)
