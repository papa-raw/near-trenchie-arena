"""The message-graph log: a 10-minute headless run on recorded intents writes msggraph.jsonl with exactly one {t, sender, receiver,
len} line per feed line and per prediction line; both are counted from the same run and they are equal."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import msggraph
import test_live

TEN_MINUTES = 10 * 60 * 20          # sim ticks at 20 Hz


class MessageGraph(unittest.TestCase):
    def test_ten_minute_run_logs_one_line_per_feed_and_prediction_line(self):
        with tempfile.TemporaryDirectory() as d:
            clock = [20_000 * 86400]
            comp, arena, house, feed = test_live.compose(d, clock)   # the scripted model: recorded intents, no endpoint
            arena.add_published_seeds([606, 707, 808, 909, 1010])     # 10 segments of 60 s
            test_live.run(arena, clock, TEN_MINUTES)
            graph = [json.loads(l) for l in (Path(d) / "house/msggraph.jsonl").read_text().splitlines()]
            self.assertTrue(all(set(row) == set(msggraph.FIELDS) for row in graph), "only the four fields")
            feed_lines, prediction_lines = feed.counts["posted"], len(house.log.rows())
            self.assertGreater(feed_lines, 0)
            self.assertGreater(prediction_lines, 0)
            self.assertEqual(sum(r["receiver"] == "feed" for r in graph), feed_lines)
            self.assertEqual(sum(r["receiver"] == "predictions" for r in graph), prediction_lines)
            self.assertEqual(len(graph), feed_lines + prediction_lines)
            fed = feed.since(0)
            self.assertEqual([(r["sender"], r["len"]) for r in graph if r["receiver"] == "feed"][-len(fed):],
                             [(r["who"], len(r["text"])) for r in fed])
            self.assertEqual(sorted(r["sender"] for r in graph if r["receiver"] == "predictions"),
                             sorted(r["persona"] for r in house.log.rows()))
            self.assertTrue(all(a["t"] <= b["t"] for a, b in zip(graph, graph[1:])))
            # a second house on the same feed and log (a host's next round) replaces the hook: never a line twice
            again = msggraph.attach(msggraph.MsgGraph(Path(d) / "house/msggraph.jsonl", lambda: clock[0]), feed, house.log)
            feed.post("dev-x", "hello", source="player", tick=10 ** 9)
            self.assertEqual(len(again.rows()), len(graph) + 1)
            comp.tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
