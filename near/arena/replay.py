"""Verified re-simulation, memory-only frame caching and shared snapshot delivery."""

import asyncio
from collections import OrderedDict
from collections.abc import Callable, Mapping
from functools import lru_cache
import json
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from . import sim
except ImportError:
    import sim


def engine_commitment(record: dict) -> str:
    """Bind boundary state, effective commands, predictions and sealed metadata."""
    sealed = {k: record["sealed"][k] for k in sorted(record["sealed"]) if k != "sealed_result_hash"}
    return sim.digest({"initial_state": record["initial_state"], "commands": record["commands"],
                       "predictions": record["predictions"], "sealed": sealed})


@lru_cache(maxsize=32)
def load_rules(rules_hash: str) -> Mapping:
    """Resolve an exact digest from immutable shipped tables, never a fallback."""
    for path in sorted((Path(__file__).parent / "rules").glob("*.json")):
        rules = json.loads(path.read_bytes())
        if sim.digest(rules) == rules_hash:
            sim.validate_rules(rules)
            return sim.freeze(rules)
    raise ValueError("unknown rules hash; install its archived table")


def cancel_spawns(game: sim.Sim, name: str) -> None:
    """A released authority cancels only its still-pending activation commands."""
    game.state["inputs"] = [row for row in game.state["inputs"]
                            if row["kind"] != "spawn" or row["fighter_id"] != name]


def replay_segment(record: dict, rules: Mapping | None = None,
                   frame_sink: Callable | None = None, encoder: Callable | None = None,
                   input_sink: Callable[[sim.Sim, dict], None] | None = None) -> sim.Sim:
    """Re-run a bounded sealed segment and refuse a changed seal or final state."""
    if engine_commitment(record) != record["sealed"]["sealed_result_hash"]:
        raise ValueError("sealed record hash mismatch")
    rules = load_rules(record["rules_hash"]) if rules is None else rules
    if record["rules_hash"] != sim.digest(rules):
        raise ValueError("rules hash mismatch")
    count = int(record["sealed"]["tick_count"])
    if not 0 < count <= rules["segment_ticks"]:
        raise ValueError("invalid replay tick count")
    if input_sink is None:
        game = sim.Sim.restore(record["initial_state"], rules)
    else:
        class ObservedSim(sim.Sim):
            def _apply(self, row: dict) -> None:
                # Trusted observer sees the actual recipient before this input,
                # including ordering relative to same-tick spawn/leave inputs.
                input_sink(self, row)
                super()._apply(row)
        game = ObservedSim.restore(record["initial_state"], rules)
    end_tick = game.state["tick"] + count
    for command in record["commands"]:
        kind, value = command["kind"], command["value"]
        if kind == "input":
            game.enqueue(sim.Input(**value))
        elif kind == "cancel_spawn":
            cancel_spawns(game, value)
        elif kind == "retire":
            game.state["fighters"].pop(value, None)
            game.state["inputs"] = [r for r in game.state["inputs"] if r["fighter_id"] != value]
        elif kind == "advance":
            sim.unsigned(value, "advance count")
            if value == 0 or game.state["tick"] + value > end_tick:
                raise ValueError("invalid replay advance")
            for _ in range(value):
                game.step()
                if frame_sink is not None:
                    if encoder is None:
                        raise ValueError("replay frames require a snapshot encoder")
                    frame_sink(encoder(game))
        else:
            raise ValueError("unknown replay command")
    if game.state["tick"] != end_tick or game.state_hash() != record["sealed"]["final_state_hash"]:
        raise ValueError("replay state hash mismatch")
    return game


class Fanout:
    """One immutable snapshot reference per subscriber, with bounded send queues."""

    def __init__(self, queue_size: int, initial: bytes | None = None):
        if queue_size < 1:
            raise ValueError("snapshot queue must be positive")
        self.queue_size = queue_size
        self.latest = initial
        self.subscribers: set[asyncio.Queue] = set()
        self.dropped = 0

    def subscribe(self) -> asyncio.Queue:
        queue = asyncio.Queue(maxsize=self.queue_size)
        if self.latest is not None:
            queue.put_nowait(self.latest)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.subscribers.discard(queue)

    def publish(self, frame: bytes) -> None:
        self.latest = frame
        for queue in tuple(self.subscribers):
            if queue.full():
                queue.get_nowait()
                self.dropped += 1
            queue.put_nowait(frame)


class Playback(Fanout):
    """An isolated playback channel; transport owns the play task's lifetime."""

    def __init__(self, service: "Replays", name: str, queue_size: int, initial: bytes):
        super().__init__(queue_size, initial)
        self.service, self.name = service, name

    async def play(self, sleep: Callable = asyncio.sleep) -> None:
        await self.service.stream(self.name, self, sleep)


class Replays:
    """At most two CPU workers and eight completed segments; no frame writes."""

    def __init__(self, reader: Callable, encoder: Callable, workers: int = 2, cache_size: int = 8):
        if not 1 <= workers <= 2 or not 1 <= cache_size <= 8:
            raise ValueError("replay limits exceed two workers or eight cached segments")
        self.reader, self.encoder = reader, encoder
        self.slots = asyncio.Semaphore(workers)
        self.cache: OrderedDict[str, tuple[bytes, ...]] = OrderedDict()
        self.pending: dict[str, asyncio.Task] = {}
        self.cache_size = cache_size

    async def _compute(self, name: str) -> tuple[bytes, ...]:
        try:
            async with self.slots:
                record = await asyncio.to_thread(self.reader, name)
                frames = []
                await asyncio.to_thread(replay_segment, record, None, frames.append, self.encoder)
                result = tuple(frames)
                self.cache[name] = result
                while len(self.cache) > self.cache_size:
                    self.cache.popitem(last=False)
                return result
        finally:
            self.pending.pop(name, None)

    async def frames(self, name: str) -> tuple[bytes, ...]:
        if name in self.cache:
            self.cache.move_to_end(name)
            return self.cache[name]
        if name not in self.pending:
            # Bound waiters as well as CPU jobs; callers can retry after playback.
            if len(self.pending) >= self.cache_size:
                raise RuntimeError("replay queue full; retry after an active replay")
            self.pending[name] = asyncio.create_task(self._compute(name))
        return await asyncio.shield(self.pending[name])

    async def stream(self, name: str, channel: Fanout, sleep: Callable = asyncio.sleep) -> None:
        frames = await self.frames(name)
        record = self.reader(name)
        rules = load_rules(record["rules_hash"])
        for frame in frames:
            channel.publish(frame)
            await sleep(1 / rules["tick_hz"])


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Re-simulate a sealed segment with its archived rules")
    parser.add_argument("record", type=Path)
    args = parser.parse_args()
    try:
        print(replay_segment(json.loads(args.record.read_bytes())).state_hash())
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, "replay refused: " + str(exc) + "\n")
