"""Versioned wire validation and bounded canonical message decoding.

Schema validation, errors and signing bytes share the policy implementation;
transport and service callers use the same decoder before dispatch.
"""
from __future__ import annotations

import json
from .policy import BoundaryError, canonical_bytes, digest, safe_error, validate

__all__ = ('BoundaryError', 'canonical_bytes', 'digest', 'safe_error', 'validate',
           'parse_message', 'decode')


def parse_message(raw, *, max_control_bytes=16_384, max_depth=16, max_array_items=256):
    if type(raw) is not bytes:
        raise BoundaryError("bad_message")
    if len(raw) > max_control_bytes:
        raise BoundaryError("rate_limited")
    try:
        text = raw.decode("utf-8", errors="strict")
        # Bound structural depth before constructing Python containers. JSON
        # brackets inside strings have no structural meaning.
        depth, quoted, escaped = 0, False, False
        for char in text:
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char in "[{":
                depth += 1
                if depth > max_depth:
                    raise BoundaryError("rate_limited")
            elif char in "]}":
                depth -= 1

        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise BoundaryError("bad_message")
                result[key] = value
            return result

        def invalid(_):
            raise BoundaryError("bad_message")

        value = json.loads(text, object_pairs_hook=pairs, parse_float=invalid, parse_constant=invalid)

        def bounded(item, level=0):
            if level > max_depth:
                raise BoundaryError("rate_limited")
            if isinstance(item, list):
                if len(item) > max_array_items:
                    raise BoundaryError("rate_limited")
                for entry in item:
                    bounded(entry, level + 1)
            elif isinstance(item, dict):
                for entry in item.values():
                    bounded(entry, level + 1)
        bounded(value)
        if not isinstance(value, dict) or canonical_bytes(value) != raw:
            raise BoundaryError("bad_message")
        return value
    except BoundaryError:
        raise
    except (UnicodeError, ValueError, TypeError, RecursionError, OverflowError):
        raise BoundaryError("bad_message") from None


def decode(schema_name, raw, **limits):
    """Return one closed typed message, or a bounded error without input text."""
    return validate(schema_name, parse_message(raw, **limits))
