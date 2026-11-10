"""Versioned spectator-only style metadata. No fields enter sim state or frozen tick snapshots.

A client opts in with styles=1. Full maps and deltas are serialized once per revision,
shared across spectators, and a backed-up connection receives a full resync on recovery.
"""
from __future__ import annotations
import json
from typing import Callable, Protocol
from sim import rules_dict

# Approved target marker for the single-target blink, distinct from target-selection reach.
BLINK_STRIKE_RADIUS_MILLI = 1200


class GameState(Protocol):
    state: dict
    rules: dict
    rules_hash: str


class StyleWriter(Protocol):
    def write(self, data: bytes) -> None: ...


class SpectatorStyles:
    def __init__(self, game: GameState, frame: Callable[[bytes], bytes]) -> None:
        self.frame = frame
        self.current: dict[str, str] = {}
        self.casts: dict[str, dict] = {}
        self.cast_delta: dict[str, dict | None] = {}
        self.rules: dict = {}
        self.rules_cache: dict[str, dict] = {}
        self.tick = 0
        self.revision = 0
        self.clients: dict[StyleWriter, int] = {}
        self.full = self.encode({}, True)
        self.delta = self.full
        self.refresh(game)

    def encode(self, styles: dict[str, str | None], full: bool) -> bytes:
        data = {"type": "spectator_styles", "version": 1, "revision": self.revision, "full": full, "styles": styles, "tick": self.tick,
                "casts": self.casts if full else self.cast_delta}
        if full:
            data["rules"] = self.rules
        return self.frame(json.dumps(data, sort_keys=True, separators=(",", ":")).encode())

    def refresh(self, game: GameState) -> None:
        current = {name: f["style"] for name, f in sorted(game.state["fighters"].items()) if f["state"] != "left"}
        if game.rules_hash not in self.rules_cache:
            self.rules_cache[game.rules_hash] = rules_dict({key: game.rules.get(key, {}) for key in ("version", "signatures", "item_quirks")})
        rules = self.rules_cache[game.rules_hash]
        casts = {}
        for name, fighter in sorted(game.state["fighters"].items()):
            cast = fighter.get("cast")
            if cast is None or fighter["state"] != "alive":
                continue
            values = cast.get("parameters", game.rules["signatures"][cast["kind"]])
            casts[f"{name}:{cast['resolve_at']}"] = {
                "who": name, "resolveAt": cast["resolve_at"], "startTick": cast["start_tick"],
                "item": cast["item_id"], "signature": cast["kind"],
                "shape": "cone" if cast["kind"] == "beam_sweep" else "circle",
                "radiusMilli": values["range"] * cast.get("sig_range_pct", fighter["sig_range_pct"]) // game.rules["percent"],
                "arcMillidegrees": values.get("half_arc", 0) * 2 * game.rules["tile"]}
            if cast["kind"] == "blink_strike":
                casts[f"{name}:{cast['resolve_at']}"]["strikeRadiusMilli"] = BLINK_STRIKE_RADIUS_MILLI
        if current == self.current and casts == self.casts and rules == self.rules:
            return
        rules_changed = rules != self.rules
        self.cast_delta = {key: casts.get(key) for key in sorted(set(casts) | set(self.casts)) if casts.get(key) != self.casts.get(key)}
        self.casts = casts
        self.rules = rules
        self.tick = game.state["tick"]
        changes = {name: current.get(name) for name in sorted(set(current) | set(self.current)) if current.get(name) != self.current.get(name)}
        self.current = current
        self.revision += 1
        self.full = self.encode(current, True)
        self.delta = self.full if rules_changed else self.encode(changes, False)

    def connect(self, writer: StyleWriter) -> None:
        writer.write(self.full)
        self.clients[writer] = self.revision

    def send(self, writer: StyleWriter) -> None:
        previous = self.clients.get(writer)
        if previous is None or previous == self.revision:
            return
        writer.write(self.delta if previous == self.revision - 1 else self.full)
        self.clients[writer] = self.revision

    def forget(self, writer: StyleWriter) -> None:
        self.clients.pop(writer, None)
