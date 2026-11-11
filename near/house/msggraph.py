"""The message-graph log: one JSON line per public message, who sent it to where and how long it was.

    {"t": <seconds, 3 decimals>, "sender": <trenchie id>, "receiver": "feed" | "predictions", "len": <characters>}

A feed line is logged by PublicFeed's on_post hook (house banter and player say lines alike, after the
guard); a prediction line by PredictionLog's on_line hook, once per public JSONL line. Only these four fields
are written: never the text, the prompt or a key. The file lives under the data directory
(`<data>/house/msggraph.jsonl`) and is appended with one write per line. Standard library only.
"""

import json
import os
from pathlib import Path
import threading

FIELDS = ("t", "sender", "receiver", "len")


class MsgGraph:
    def __init__(self, path, clock):
        self.path, self.clock = Path(path), clock
        self.lock = threading.Lock()

    def _write(self, sender, receiver, length):
        row = {"t": round(self.clock(), 3), "sender": str(sender), "receiver": receiver, "len": int(length)}
        line = json.dumps({k: row[k] for k in FIELDS}, sort_keys=True) + "\n"
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())

    def feed_line(self, row):
        """PublicFeed.on_post: the line as posted (an emote when blocked or muted)."""
        self._write(row["who"], "feed", len(row["text"]))

    def prediction_line(self, row):
        """PredictionLog.on_line: the public line's length as written to the JSONL file."""
        self._write(row["persona"], "predictions", len(json.dumps(row, sort_keys=True)))

    def rows(self):
        if not self.path.exists():
            return []
        return [json.loads(l) for l in self.path.read_text().splitlines() if l]


def attach(graph, feed=None, log=None):
    """Hook a graph to a feed and a predictions log. A hook that is not a graph's stays and runs first; a hook from an
    earlier graph (a host that builds a new house each round) is replaced, so no message is ever logged twice."""
    for obj, attr, fn in ((feed, "on_post", graph.feed_line), (log, "on_line", graph.prediction_line)):
        if obj is None:
            continue
        prior = getattr(obj, attr)
        if prior is not None:
            prior = prior._outer if hasattr(prior, "_outer") else prior   # unwrap an earlier graph's hook to the outside one
            if isinstance(getattr(prior, "__self__", None), MsgGraph):
                prior = None

        def hook(row, prior=prior, fn=fn):
            if prior is not None:
                prior(row)
            fn(row)
        hook._outer = prior
        setattr(obj, attr, hook)
    return graph
