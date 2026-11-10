"""Public fight logs (F88): each sealed segment as a read-only static file a buyer can replay.

publish() copies sealed segment records byte for byte from the data volume into a public directory and
writes index.json (segment id, file, rules_hash, final_state_hash, sealed_result_hash, size). nginx serves
that directory read-only with its own rate limit (host side, owned by the host lane, for example
`limit_req_zone $binary_remote_addr zone=logs:1m rate=2r/s;` on the /logs/ location). A buyer runs
`python3 near/arena/replay.py segment-N.json`, which prints the final-state hash to compare with the chain's
batch hash; verify() does the same here. Standard library only; nothing is written outside out_dir.
"""

import json
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from . import replay, sim
except ImportError:
    import replay
    import sim

FORBIDDEN = ("api_key", "secret", "prompt", "reasoning", "player_spend", "private_key", "seed_phrase")


def publish(data_dir, out_dir):
    """Copy every sealed segment verbatim and index them. Returns the index."""
    source, out = Path(data_dir) / "segments", Path(out_dir)
    (out / "segments").mkdir(parents=True, exist_ok=True)
    entries = []
    for path in sorted(source.glob("segment-*.json"), key=lambda p: int(p.stem.split("-")[1])):
        raw = path.read_bytes()
        record = json.loads(raw)
        text = raw.decode().lower()
        if any(word in text for word in FORBIDDEN):
            raise ValueError("%s carries a field that must stay private; not published" % path.name)
        target = out / "segments" / path.name
        if not target.exists() or target.read_bytes() != raw:
            target.write_bytes(raw)
        sealed = record["sealed"]
        entries.append({"segment_id": sealed["segment_id"], "file": "segments/" + path.name,
                        "rules_hash": record["rules_hash"], "final_state_hash": sealed["final_state_hash"],
                        "sealed_result_hash": sealed["sealed_result_hash"], "bytes": len(raw)})
    index = {"format": 1, "segments": entries, "index_hash": sim.digest(entries)}
    (out / "index.json").write_text(json.dumps(index, indent=1, sort_keys=True) + "\n")
    return index


def verify(path, expected_final_hash=None):
    """Re-simulate a published file under its own rules table; returns the final-state hash."""
    record = json.loads(Path(path).read_bytes())
    state_hash = replay.replay_segment(record).state_hash()
    if expected_final_hash is not None and state_hash != expected_final_hash:
        raise ValueError("replay hash %s does not match the chain's %s" % (state_hash, expected_final_hash))
    return state_hash


if __name__ == "__main__":
    index = publish(sys.argv[1], sys.argv[2])
    print("published %d segments, index_hash %s" % (len(index["segments"]), index["index_hash"]))
