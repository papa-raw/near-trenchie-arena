"""Game-owned first-segment projection; native archives and locks stay intact."""
from __future__ import annotations

import base64
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
import threading
from typing import Protocol

from room.ledger import (Ledger, Refusal, canonical, digest, prediction_log_hash,
                         replay_event_hash, sealed_hash, verify_sealed)
from room.results import ResultAuthority, ResultReader

if __package__:
    from .engine_evidence import replay_evidence
    from .replay import load_rules
else:
    from engine_evidence import replay_evidence
    from replay import load_rules


class Archive(Protocol):
    """Trusted game archive reader; missing unsealed segments raise FileNotFoundError."""

    def segment(self, segment_id: str) -> dict: ...


def _check_command(event: dict, command: dict) -> None:
    """The public gameplay row must describe the command actually replayed."""
    kind, payload = event["kind"], event["payload"]
    if kind == "life_start":
        valid = command["payload"]["life_id"] == event["life_id"]
    elif kind == "intent":
        valid = (payload["fighter_id"] == command["fighter_id"]
                 and all(payload[key] == value for key, value in command["payload"].items())
                 and payload["say"] is None)
    elif kind == "join":
        valid = (payload["fighter_id"] == command["fighter_id"]
                 and payload["nft_token_id"] == event["nft_token_id"]
                 and command["payload"]["life_id"] == event["life_id"]
                 and {row["slot"]: row["item_id"] for row in payload["equipped"]} == command["payload"]["loadout"])
    else:
        valid = payload == {"reason": "leave"}
    if not valid or event["fighter_id"] != event["nft_token_id"]:
        raise Refusal("bad_message")


def _input_key(row: dict) -> tuple[str, str, str, str]:
    return row["kind"], str(row["tick"]), row["fighter_id"], str(row["sequence"])


def _cancelled_spawns(native: dict) -> set[tuple[str, str, str, str]]:
    """Find pending spawns removed by the independently replayed journal.

    Commands at tick T execute during the advance from T to T+1. A retire
    or cancel_spawn before that advance removes the spawn without starting
    its announced life. This does not excuse a missing applied input.
    """
    tick = native["initial_state"]["tick"]
    pending, cancelled, seen = {}, set(), set()
    for command in native["commands"]:
        kind, value = command["kind"], command["value"]
        if kind == "input" and value["kind"] == "spawn":
            key = _input_key(value)
            if key in seen:
                raise Refusal("bad_message")
            seen.add(key)
            pending[key] = value
        elif kind == "advance":
            tick += value
            pending = {key: row for key, row in pending.items() if row["tick"] >= tick}
        elif kind in {"retire", "cancel_spawn"}:
            removed = {key for key, row in pending.items() if row["fighter_id"] == value}
            cancelled.update(removed)
            pending = {key: row for key, row in pending.items() if key not in removed}
    return cancelled


def _check_commands(native: dict, input_lives: list[dict]) -> set[int]:
    """Reject a rehashed public row that contradicts the archived engine input."""
    commands = [row["value"] for row in native["commands"] if row["kind"] == "input"
                and row["value"]["kind"] in {"join", "spawn", "intent", "leave"}]
    delay = load_rules(native["rules_hash"])["input_delay"]
    actual_lives = {(row["kind"], row["tick"], row["fighter_id"], row["sequence"]): row["life_id"]
                    for row in input_lives}
    if len(actual_lives) != len(input_lives):
        raise Refusal("bad_message")
    cancelled, omitted = _cancelled_spawns(native), set()
    for position, event in enumerate(native["sealed"]["input_events"]):
        if event["kind"] == "prediction_lock":
            continue  # Full unsigned forecast and lock are checked by prediction_log_hash.
        kind = "spawn" if event["kind"] == "life_start" else event["kind"]
        # A release is journalled at receipt, while its engine command is delayed.
        tick = int(event["tick"]) + (delay if kind == "leave" else 0)
        match = next((row for row in commands if row["kind"] == kind
                      and row["fighter_id"] == event["fighter_id"] and row["tick"] == tick), None)
        if match is None:
            raise Refusal("bad_message")
        _check_command(event, match)
        key = _input_key(match)
        if key in cancelled and key not in actual_lives:
            omitted.add(position)  # Payload/life already matched the cancelled spawn.
        elif actual_lives.pop(key, None) != event["life_id"]:
            raise Refusal("bad_message")
        commands.remove(match)
    if commands or actual_lives:
        raise Refusal("bad_message")
    return omitted


def _check_predictions(native: dict) -> None:
    """Keep the exact archive lock, including its original ref and journal index."""
    predictions = {row["life_id"]: row for row in native["predictions"]}
    seen = set()
    for event in native["sealed"]["input_events"]:
        if event["kind"] != "prediction_lock":
            continue
        archived = predictions.get(event["life_id"])
        if (archived is None or event["life_id"] in seen
                or archived["nft_token_id"] != event["nft_token_id"]
                or event["fighter_id"] != event["nft_token_id"]
                or archived["prediction_lock"] != event["payload"]["prediction_lock"]):
            raise Refusal("bad_message")
        seen.add(event["life_id"])
    if seen != set(predictions):
        raise Refusal("bad_message")


def _events(native: dict, omitted: set[int]) -> list[dict]:
    """Project effective tick order and wire hash chain, preserving every lock.

    Native event indices count segment events; immutable lock indices address
    the engine journal. Wire prediction rows use that existing lock index.
    Other wire rows take the next free index. A collision refuses; no lock or
    archived event is repaired, renumbered in place or re-signed here.
    Announcements of proved cancelled spawns have no effective wire life_start;
    their native rows and every prediction lock remain in the archive.
    """
    projected, previous_hash, previous_index = [], "0" * 64, -1
    sources = [row for position, row in enumerate(native["sealed"]["input_events"]) if position not in omitted]
    for source in sorted(sources, key=lambda row: (int(row["tick"]), int(row["index"]))):
        event = deepcopy(source)
        if not 0 <= int(event["tick"]) < 1200:
            raise Refusal("recovery_pending")
        index = (int(event["payload"]["prediction_lock"]["ledger_index"])
                 if event["kind"] == "prediction_lock" else previous_index + 1)
        if index <= previous_index:
            raise Refusal("recovery_pending")
        event["index"] = str(index)
        event["record_hash"] = replay_event_hash(previous_hash, event)
        projected.append(event)
        previous_index, previous_hash = index, event["record_hash"]
    return projected


def _project(native: dict) -> tuple[dict, dict]:
    """Re-simulate real archive facts before deriving a separate wire seal."""
    # Carry-in needs its source-owned provenance contract; do not invent one.
    if native["initial_state"]["tick"] != 0 or native["sealed"]["segment_id"] != "segment:0":
        raise Refusal("recovery_pending")
    evidence = replay_evidence(native)
    omitted = _check_commands(native, evidence["input_lives"])
    _check_predictions(native)
    events = _events(native, omitted)
    locks = {row["payload"]["prediction_lock"]["lock_ref"] for row in events if row["kind"] == "prediction_lock"}
    if locks != set(evidence["predictions"]):
        raise Refusal("bad_message")
    predictions = {key: evidence["predictions"][key] for key in locks}
    lives = evidence["lives"]
    record = dict(segment_id=native["sealed"]["segment_id"],
        life_ids=[life["life_id"] for life in lives],
        nft_token_ids=sorted({life["nft_token_id"] for life in lives}),
        inputs_hash=digest(events), seed_hash=digest(native["sealed"]["seed"]),
        rules_hash=native["sealed"]["rules_hash"], final_state_hash=evidence["final_state_hash"],
        predictions_log_hash=prediction_log_hash(events, predictions), completed=True,
        tick_count="1200", lives=lives, seed=native["sealed"]["seed"], input_events=events)
    record["sealed_result_hash"] = sealed_hash(record)
    return record, dict(final_state_hash=evidence["final_state_hash"], lives=lives, predictions=predictions)


class EngineRecords:
    """Read port for RoomHost, backed by real archives and the portable ledger.

    Only segment:0 is supported until cross-segment life provenance is frozen.
    Each result is signed by ResultAuthority after its independent native
    engine replay and exact projection comparison. No settlement writer exists.
    The supplied signer and verifier use the same encoded 64-byte signature
    contract as RoomHost. Deployed implementations must pin Ed25519 adapters.
    """

    def __init__(self, archive: Archive, path: Path, control_context: dict, result_context: dict, *,
                 key_id: str, sign: Callable[[bytes], str],
                 verify: Callable[[str, bytes, str], bool], key_allowed: Callable[[str], bool]) -> None:
        common = ("version", "room_id", "deployment_id", "authority_epoch", "rules_hash")
        if any(result_context[key] != control_context[key] for key in common):
            raise Refusal("context_mismatch")
        self.archive = archive
        self.ledger = Ledger(path, control_context, authorize=lambda binding: False)
        self.authority = ResultAuthority(result_context, key_id,
            signer=lambda body: base64.urlsafe_b64decode(sign(body) + "=="),
            verifier=lambda key, body, raw: verify(key, body, base64.urlsafe_b64encode(raw).decode().rstrip("=")),
            key_allowed=key_allowed)
        self.reader = ResultReader(self.ledger, self.authority, self._replay)
        # Only segment:0 is supported, so one immutable source/projection entry
        # bounds memory. Source equality is full canonical material, not merely
        # a seal header. Successful facts are separate from live authorization.
        self._projection_cache: tuple[bytes, dict, dict] | None = None
        self._projection_lock = threading.Lock()

    def _native(self, segment_id: str) -> dict:
        try:
            return self.archive.segment(segment_id)
        except FileNotFoundError:
            raise Refusal("result_pending") from None

    def _projection(self, segment_id: str) -> tuple[dict, dict]:
        """Reuse only an agreed projection of unchanged full native source."""
        if segment_id != "segment:0":
            raise Refusal("recovery_pending")
        native = self._native(segment_id)
        source = canonical(native)
        if not self._projection_lock.acquire(blocking=False):
            raise Refusal("rate_limited")
        try:
            cached = self._projection_cache
            if cached is None or cached[0] != source:
                record, evidence = _project(native)
                # A real native replay has just produced this exact outcome.
                # Require portable agreement before making it reusable.
                verify_sealed(record, lambda readonly: deepcopy(evidence))
                cached = (source, deepcopy(record), deepcopy(evidence))
                self._projection_cache = cached
            return deepcopy(cached[1]), deepcopy(cached[2])
        finally:
            self._projection_lock.release()

    def _replay(self, record: dict) -> dict:
        expected, evidence = self._projection(record["segment_id"])
        if record != expected:
            raise Refusal("bad_message")
        return evidence

    def _seal(self, segment_id: str) -> None:
        record, _ = self._projection(segment_id)
        self.ledger.seal(record, self._replay)

    def result(self, segment_id: str) -> dict:
        """Return a replay-checked result through the actual room read route."""
        self._seal(segment_id)
        return self.reader.result(segment_id)

    def replay(self, segment_id: str, after_index: str | None = None) -> dict:
        self._seal(segment_id)
        return self.ledger.replay_page(segment_id, after_index)

    def page(self, after_index: str | None = None) -> dict:
        return self.ledger.page(after_index)
