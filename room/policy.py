"""Closed guest permissions, bounded messages and explicit data projections."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from threading import RLock
from typing import Callable

from jsonschema import Draft202012Validator

_SCHEMA = json.loads(Path(__file__).with_name('protocol.schema.json').read_text(encoding='utf-8'))
CAPABILITIES = frozenset(('observe', 'intent', 'prediction', 'renew', 'leave'))
_PUBLIC = frozenset(('Manifest', 'PublicSnapshot', 'Clock', 'Limits', 'LedgerPage', 'ReplayPage', 'Result'))
_CONTROL = {kind.lower().removesuffix('request'): kind for kind in
            ('ObserveRequest', 'IntentRequest', 'PredictionRequest', 'RenewRequest', 'LeaveRequest')}


def safe_error(code: str) -> dict:
    """Never include client text, credentials or internal exceptions in errors."""
    allowed = _SCHEMA['$defs']['ErrorCode']['enum']
    return {'type': 'error', 'code': code if code in allowed else 'bad_message',
            'request_id': None, 'retry_after_ms': None}


class BoundaryError(ValueError):
    def __init__(self, code: str):
        self.code = safe_error(code)['code']
        super().__init__(self.code)

    def error(self) -> dict:
        return safe_error(self.code)


def _canonical(value):
    if value is None or type(value) in (bool, int):
        return json.dumps(value, separators=(',', ':'))
    if isinstance(value, str):
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            raise BoundaryError('bad_message')
        return '"' + ''.join('\\u%04x' % ord(char) if ord(char) < 32 else
                             '\\' + char if char in ('"', '\\') else char for char in value) + '"'
    if type(value) is list:
        return '[' + ','.join(_canonical(item) for item in value) + ']'
    if type(value) is dict and all(type(key) is str and key.isascii() for key in value):
        return '{' + ','.join(_canonical(key) + ':' + _canonical(value[key]) for key in sorted(value)) + '}'
    raise BoundaryError('bad_message')


def canonical_bytes(value, *, exclude=()) -> bytes:
    """Canonical unsigned bytes; only explicitly named top-level fields are omitted."""
    if exclude:
        if type(value) is not dict:
            raise BoundaryError('bad_message')
        value = {key: item for key, item in value.items() if key not in exclude}
    try:
        return _canonical(value).encode('utf-8')
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise BoundaryError('bad_message') from None


def digest(value, *, exclude=()) -> str:
    return sha256(canonical_bytes(value, exclude=exclude)).hexdigest()


def validate(name: str, value):
    if name not in _SCHEMA['$defs']:
        raise BoundaryError('bad_message')
    try:
        canonical_bytes(value)
        validator = Draft202012Validator({'$ref': '#/$defs/' + name, '$defs': _SCHEMA['$defs']})
        if not validator.is_valid(value):
            raise BoundaryError('bad_message')
    except (ValueError, TypeError, RecursionError):
        raise BoundaryError('bad_message') from None
    return value


def _project(schema, value):
    """Copy only declared fields, recursively, before validation or persistence."""
    if '$ref' in schema:
        return _project(_SCHEMA['$defs'][schema['$ref'].rsplit('/', 1)[1]], value)
    alternatives = schema.get('oneOf', schema.get('anyOf'))
    if alternatives:
        for alternative in alternatives:
            try:
                result = _project(alternative, value)
                if Draft202012Validator(dict(alternative, **{'$defs': _SCHEMA['$defs']})).is_valid(result):
                    return result
            except BoundaryError:
                pass
        raise BoundaryError('bad_message')
    if schema.get('type') == 'object':
        if type(value) is not dict:
            raise BoundaryError('bad_message')
        result = {key: _project(child, value[key]) for key, child in schema['properties'].items() if key in value}
        if schema is _SCHEMA['$defs']['PublicFighter'] and result.get('house') is False:
            result['house_spend_microusd'] = None
        return result
    if schema.get('type') == 'array':
        if type(value) is not list or len(value) > schema.get('maxItems', 256):
            raise BoundaryError('bad_message')
        return [_project(schema['items'], item) for item in value]
    if type(value) in (dict, list):
        raise BoundaryError('bad_message')
    return deepcopy(value)


def public_projection(schema_name: str, value) -> dict:
    if schema_name not in _PUBLIC:
        raise BoundaryError('bad_message')
    result = _project(_SCHEMA['$defs'][schema_name], value)
    if schema_name == 'PublicSnapshot':
        # The public digest covers the projection, never a private runtime object.
        result['snapshot_hash'] = digest(result, exclude=('snapshot_hash',))
    return validate(schema_name, result)


def member_view(viewer_member_id, owner_member_id, record: dict) -> dict:
    """Private connection view. Spectators and other members receive no fields."""
    if viewer_member_id is None or viewer_member_id != owner_member_id:
        return {}
    validate('Id', viewer_member_id)
    if type(record) is not dict:
        raise BoundaryError('bad_message')
    state = record.get('connection_status', 'disconnected')
    if state not in ('connected', 'disconnected', 'released'):
        raise BoundaryError('bad_message')
    receipts = record.get('receipts', [])
    if type(receipts) is not list or len(receipts) > 64:
        raise BoundaryError('bad_message')
    grant = record.get('grant')
    if grant is not None:
        grant = validate('JoinAccepted', _project(_SCHEMA['$defs']['JoinAccepted'], grant))
        if grant['member_id'] != owner_member_id:
            raise BoundaryError('proof_required')
    projected_receipts = [validate('Receipt', _project(_SCHEMA['$defs']['Receipt'], item)) for item in receipts]
    if any(item['grant_id'] is None or grant is None or
           (item['grant_id'], item['session_key_id'], item['context']) !=
           (grant['grant_id'], grant['session_key_id'], grant['context']) for item in projected_receipts):
        raise BoundaryError('proof_required')
    spend = record.get('player_spend_microusd')
    if spend is not None:
        validate('U64', spend)
    return {'connection_status': state, 'receipts': projected_receipts,
            'grant': grant, 'player_spend_microusd': spend}


class GuestPolicy:
    def __init__(self, *, now_ms: Callable[[], int], max_control_bytes=16384, max_depth=16, max_array_items=64):
        if not (1 <= max_control_bytes <= 16384 and 1 <= max_depth <= 32 and 1 <= max_array_items <= 256):
            raise BoundaryError('bad_message')
        self.now_ms = now_ms
        self.max_control_bytes = max_control_bytes
        self.max_depth = max_depth
        self.max_array_items = max_array_items
        self._last_intent = {}
        self._last_banter = {}
        self.intent_interval_ms = 2000
        self._lock = RLock()

    def _bounded(self, value, depth=0):
        if depth > self.max_depth:
            raise BoundaryError('bad_message')
        if type(value) is dict:
            if len(value) > 64:
                raise BoundaryError('bad_message')
            for child in value.values():
                self._bounded(child, depth + 1)
        elif type(value) is list:
            if len(value) > self.max_array_items:
                raise BoundaryError('bad_message')
            for child in value:
                self._bounded(child, depth + 1)

    def authorize(self, binding, request, *, capabilities, fighter_id=None, life_id=None):
        if binding is None:
            raise BoundaryError('proof_required')
        validate('SlotBinding', binding)
        self._bounded(request)
        if len(canonical_bytes(request)) > self.max_control_bytes:
            raise BoundaryError('bad_message')
        kind = request.get('kind') if type(request) is dict else None
        if kind not in _CONTROL:
            raise BoundaryError('bad_message')
        validate(_CONTROL[kind], request)
        if kind not in CAPABILITIES.intersection(capabilities):
            raise BoundaryError('proof_required')
        if request['context'] != binding['context']:
            raise BoundaryError('context_mismatch')
        for field in ('grant_id', 'session_key_id', 'member_id', 'nft_token_id', 'persona_digest', 'slot_id', 'generation'):
            if request[field] != binding[field]:
                raise BoundaryError('stale_slot')
        if kind in ('intent', 'prediction'):
            if life_id is None or request['life_id'] != life_id:
                raise BoundaryError('stale_slot')
        if kind == 'intent':
            if fighter_id is None or request['payload']['fighter_id'] != fighter_id:
                raise BoundaryError('stale_slot')
            identity = (binding['context']['deployment_id'], binding['nft_token_id'])
            now = self.now_ms()
            with self._lock:
                last = self._last_intent.get(identity)
                banter = self._last_banter.get(identity)
                if last is not None and now - last < self.intent_interval_ms:
                    raise BoundaryError('rate_limited')
                if request['payload']['say'] is not None and banter is not None and now - banter < 30000:
                    raise BoundaryError('rate_limited')
                for history, window in ((self._last_intent, self.intent_interval_ms), (self._last_banter, 30000)):
                    for key, timestamp in list(history.items()):
                        if now - timestamp >= window:
                            del history[key]
                self._last_intent[identity] = now
                if request['payload']['say'] is not None:
                    self._last_banter[identity] = now
        return deepcopy(binding)
