"""Replay acceptance cases use sealed local fixtures and no external service."""

import asyncio
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sim
import server


def segment(rules, ticks=20):
    game = sim.Sim(713, rules)
    start = game.export()
    row = sim.Input(0, "join", "a", 0, {"angle": 10})
    game.enqueue(row)
    game.run(ticks)
    record = {"initial_state": start, "rules_hash": game.rules_hash,
              "commands": [{"kind": "input", "value": row.record()}, {"kind": "advance", "value": ticks}],
              "predictions": [], "sealed": {"tick_count": str(ticks),
              "final_state_hash": game.state_hash()}}
    record["sealed"]["sealed_result_hash"] = server.engine_commitment(record)
    return record


class Replay(unittest.IsolatedAsyncioTestCase):
    async def test_server_opens_a_playable_isolated_channel_and_reports_free_disk(self):
        import replay
        with tempfile.TemporaryDirectory() as directory:
            arena = server.Arena({"rules_hash": sim.digest(sim.DEFAULT_RULES)}, [1, 2], data_dir=directory)
            rules = json.loads((Path(__file__).parent / "rules/integer-3.json").read_bytes())
            arena.store.put_segment("segment:0", segment(rules))
            channel = await arena.open_replay("segment:0")
            self.assertIsInstance(channel, replay.Playback)
            left, right = channel.subscribe(), channel.subscribe()
            self.assertIs(left.get_nowait(), right.get_nowait())
            live = arena.subscribe()
            live_frame = live.get_nowait()
            async def no_delay(delay):
                pass
            await channel.play(no_delay)
            self.assertEqual(json.loads(left._queue[-1])[1], 20)
            self.assertIs(arena.snapshot_bytes, live_frame)
            self.assertTrue(live.empty())
            self.assertGreater(arena.health()["free_disk_bytes"], 0)
            self.assertEqual(sorted(p.name for p in Path(directory).rglob("*")),
                             ["engine.jsonl", "segment-0.json", "segments"])

    async def test_archive_lookup_checks_the_complete_seal_and_final_hash(self):
        import replay
        rules = json.loads((Path(__file__).parent / "rules/integer-3.json").read_bytes())
        record = segment(rules)
        self.assertEqual(replay.replay_segment(record).state_hash(), record["sealed"]["final_state_hash"])
        tampered = copy.deepcopy(record)
        tampered["predictions"].append({"forged": True})
        with self.assertRaisesRegex(ValueError, "sealed"):
            replay.replay_segment(tampered)
        tampered = copy.deepcopy(record)
        tampered["sealed"]["final_state_hash"] = "0" * 64
        tampered["sealed"]["sealed_result_hash"] = server.engine_commitment(tampered)
        with self.assertRaisesRegex(ValueError, "state hash"):
            replay.replay_segment(tampered)
        with self.assertRaisesRegex(ValueError, "unknown rules"):
            replay.load_rules("0" * 64)

    async def test_streams_shared_bytes_with_bounded_queues_and_no_frame_files(self):
        import replay
        record = segment(sim.DEFAULT_RULES)
        before = sim.canonical(record)
        service = replay.Replays(lambda name: record, server.encode_snapshot)
        channel = replay.Fanout(2)
        left, right = channel.subscribe(), channel.subscribe()
        first = []
        async def tick(delay):
            self.assertEqual(delay, 1 / 20)
            self.assertIs(left._queue[-1], right._queue[-1])
            first.append(left._queue[-1])
        await service.stream("segment:0", channel, tick)
        self.assertEqual(len(first), 20)
        self.assertEqual(left.qsize(), 2)
        self.assertEqual(channel.dropped, 36)
        late = channel.subscribe()
        self.assertIs(late.get_nowait(), right._queue[-1])
        self.assertEqual(sim.canonical(record), before)

    async def test_two_workers_eight_cache_entries_and_single_flight(self):
        import replay
        record = segment(sim.DEFAULT_RULES, 1)
        service = replay.Replays(lambda name: record, server.encode_snapshot)
        real = replay.replay_segment
        counts = {"active": 0, "peak": 0, "calls": 0}
        import threading
        lock = threading.Lock()
        import time
        def observe(*args, **kwargs):
            with lock:
                counts["active"] += 1
                counts["calls"] += 1
                counts["peak"] = max(counts["peak"], counts["active"])
            try:
                time.sleep(0.005)
                return real(*args, **kwargs)
            finally:
                with lock:
                    counts["active"] -= 1
        from unittest.mock import patch
        with patch.object(replay, "replay_segment", observe):
            same = await asyncio.gather(*(service.frames("segment:0") for _ in range(5)))
            self.assertTrue(all(x is same[0] for x in same))
            self.assertEqual(counts["calls"], 1)
            for batch in (range(1, 7), range(7, 12)):
                await asyncio.gather(*(service.frames("segment:" + str(n)) for n in batch))
        self.assertEqual(counts["peak"], 2)
        self.assertEqual(len(service.cache), 8)
        self.assertFalse(service.pending)


if __name__ == "__main__":
    unittest.main()
