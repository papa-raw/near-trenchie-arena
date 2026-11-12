#!/usr/bin/env -S python3 -I
"""Append one settled batch, with its segment records, to near/replay/MANIFEST (B101: appended as they land).

    python3 -I near/replay/pin.py --state <writer data dir>/chain/state.json --batch <batch id> \
        [--commit <commit id>=<commit_seeds tx hash>] ...

Reads the writer's state (and batches.jsonl, where it moves settled batches), takes the batch's `post_batch` tx,
its signer and its segments, and copies each segment's sealed record, byte for byte, to
near/replay/segments/<segment id>.json. Every commit the batch's seeds come from must name its `commit_seeds` tx:
from the writer's state, or with --commit when the state does not hold it (a commit an earlier run sent). It needs no
network and no key; `make demo` then checks the batch against archival RPC. It refuses a batch that did not apply,
a batch already pinned, and a record whose sealed hashes differ from the batch's segment.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT)]

from near.chain import batch as fmt  # noqa: E402

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "MANIFEST"


def load_state(path):
    state = json.loads(Path(path).read_text())
    settled = Path(path).with_name("batches.jsonl")
    state["settled"] = [json.loads(l) for l in settled.read_text().splitlines() if l] if settled.exists() else []
    return state


def pin(state, batch_id, commits_given=None, manifest_path=MANIFEST, signer=None):
    manifest_path = Path(manifest_path)
    m = json.loads(manifest_path.read_text())
    if any(b["batch_id"] == batch_id for b in m["batches"]):
        raise SystemExit(f"pin: {batch_id} is already in {manifest_path.name}")
    b = next((b for b in state["settled"] + state["batches"] if b["batch_id"] == batch_id), None)
    if b is None:
        raise SystemExit(f"pin: no batch {batch_id} in the writer state")
    applied = [a for a in b.get("attempts", []) if a.get("status") == "applied"]
    if b.get("status") not in ("applied", "settled") or not applied:
        raise SystemExit(f"pin: {batch_id} has not applied (status {b.get('status')}); only a settled batch is pinned")
    if b.get("arena", m["arena"]) != m["arena"]:
        raise SystemExit(f"pin: {batch_id} was posted to {b.get('arena')}, the MANIFEST is for {m['arena']}")
    known = {int(c["commit_id"]): c.get("tx") for c in state.get("commits", [])}
    known.update({int(k): v for k, v in (commits_given or {}).items()})
    pinned = {int(c["commit_id"]) for c in m["commits"]}
    needed = sorted({int(s["commit_id"]) for s in b["segments"]} - pinned)
    missing = [c for c in needed if not known.get(c)]
    if missing:
        raise SystemExit(f"pin: the commit_seeds tx of commit(s) {missing} is unknown: give --commit <id>=<tx>")
    rows = []
    for seg, local in zip(b["segments"], b["local"]):
        raw = Path(local).read_bytes()
        sealed = json.loads(raw)["sealed"]
        if any(sealed[k] != seg[k] for k in fmt.SEGMENT_HASHES):
            raise SystemExit(f"pin: {local}'s sealed hashes differ from segment {seg['segment_id']} of the batch")
        name = f"segments/{seg['segment_id']}.json"
        (manifest_path.parent / "segments").mkdir(exist_ok=True)
        (manifest_path.parent / name).write_bytes(raw)
        rows.append({"segment_id": seg["segment_id"], "record": name})
    signer = signer or m["signer"]
    for c in needed:
        m["commits"].append({"commit_id": c, "tx": known[c], "signer": signer})
    m["batches"].append({"batch_id": batch_id, "tx": applied[-1]["tx"], "signer": signer, "segments": rows})
    manifest_path.write_text(json.dumps(m, indent=1) + "\n")
    return len(rows), needed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", required=True, help="the writer's chain/state.json")
    ap.add_argument("--batch", required=True)
    ap.add_argument("--commit", action="append", default=[], help="<commit id>=<commit_seeds tx hash>")
    ap.add_argument("--manifest", default=str(MANIFEST))
    a = ap.parse_args(argv)
    given = dict(c.split("=", 1) for c in a.commit)
    n, commits = pin(load_state(a.state), a.batch, given, a.manifest)
    print(f"pinned {a.batch}: {n} segment records, new commits {commits or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
