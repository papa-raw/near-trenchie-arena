"""Read-only, verified projection of an explicitly configured local demo archive."""
from __future__ import annotations

import json
from pathlib import Path

from near.arena.portable_records import _project
from near.arena.replay import replay_segment

MAX_ARCHIVE_BYTES = 4 * 1024 * 1024


def read_evidence(directory: Path | None) -> dict:
    """Expose public forecast fields only after native replay and projection agree.

    This is a synthetic segment-zero rehearsal, with no chain or live claim.
    Each read checks current bytes; a changed or missing archive cannot retain
    a previous checked state. Decision complexity stays below ten per function.
    """
    pending = dict(state='pending', chain_transaction=None, predictions=[])
    if directory is None:
        return pending
    try:
        with (directory / 'segment.json').open('rb') as stream:
            raw = stream.read(MAX_ARCHIVE_BYTES + 1)
        if len(raw) > MAX_ARCHIVE_BYTES:
            raise ValueError('archive exceeds local demo bound')
        archive = json.loads(raw)
        record, evidence = _project(archive)
        game = replay_segment(archive)
        rows = [_public_prediction(row) for row in archive['predictions']]
        return dict(state='checked', source='synthetic-local', segment_id=record['segment_id'],
                    recorded_hash=archive['sealed']['final_state_hash'], replayed_hash=game.state_hash(),
                    native_seal=archive['sealed']['sealed_result_hash'],
                    portable_seal=record['sealed_result_hash'], rules_hash=record['rules_hash'],
                    tick_count=record['tick_count'], predictions=rows, lives=evidence['lives'],
                    chain_transaction=None)
    except FileNotFoundError:
        return pending
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        return dict(state='unavailable', chain_transaction=None, predictions=[],
                    message='Local archive could not be checked. Run (cd near && make rehearsal) again.')


def _public_prediction(row: dict) -> dict:
    """Remove session/grant/signature fields from the committed fixture forecast."""
    payload = None if row['pick'] is None else row['pick']['payload']
    return dict(life_id=row['life_id'], persona=row['nft_token_id'],
                prediction_lock=row['prediction_lock'],
                spread_bps=None if payload is None else payload['spread_bps'],
                zero_bps=None if payload is None else payload['zero_bps'])
