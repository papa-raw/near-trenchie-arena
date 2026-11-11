#!/usr/bin/env -S python3 -I
"""Read a settled batch back from archival RPC: the `arena.post_batch` transaction's own arguments.

    python3 -I near/chain/archival.py                         # every batch pinned in near/chain/settled.json
    python3 -I near/chain/archival.py <tx hash> <signer account> [--state <writer state.json>] [--replay N]

It never reads contract state and never a non-archival node (B96): it asks archival-rpc.testnet.near.org,
then archival-rpc.testnet.fastnear.com, for the transaction, decodes the FunctionCall arguments, recomputes
`fight_hash` and `rows_digest` the way `arena.post_batch` does (borsh over the arguments), and checks them
against the `post_batch` event the same transaction logged. With `--state`, each segment is matched to the
writer's local sealed record: its seed, inputs, rules, final-state and predictions-log hashes must equal the
archival arguments; `--replay N` re-simulates the first N of those records and checks each final-state hash
against the archival arguments. Exit 0 only when every check holds.
"""

import argparse
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "near" / "arena")]

from near.chain import batch as fmt, rpc as rpclib  # noqa: E402

SETTLED = Path(__file__).resolve().parent / "settled.json"   # batches written on testnet, pinned for the read path


def read_batch(tx_hash, signer, urls=None, post=None):
    """{tx, rpc, receiver, method, args, events...} for one post_batch tx, from archival RPC only."""
    last = None
    for url in urls or rpclib.TESTNET_ARCHIVAL:
        try:
            res = rpclib.Rpc([url], post=post).tx(tx_hash, signer)
            break
        except (rpclib.RpcError, rpclib.RpcUnreachable) as exc:
            last = f"{url}: {exc}"
    else:
        raise SystemExit(f"archival read failed: {last}")
    t = res["transaction"]
    fc = t["actions"][0]["FunctionCall"]
    out = rpclib.outcome(res)
    return {"tx": tx_hash, "rpc": url, "signer": t["signer_id"], "receiver": t["receiver_id"],
            "method": fc["method_name"], "args": json.loads(base64.b64decode(fc["args"])), "outcome": out}


def check(read, state=None, replay=0):
    """Every check on one archival read; returns (report, ok)."""
    args, out = read["args"], read["outcome"]
    checks = []

    def need(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    need("method is post_batch", read["method"] == "post_batch", read["method"])
    segs, rows = args.get("segments", []), args.get("rows", [])
    old_layout = [s.get("segment_id") for s in segs if "commit_id" not in s or "seed_index" not in s]
    need("segments carry their committed seed (commit_id, seed_index)", not old_layout,
         f"older segment layout, before the seed binding: {old_layout[:3]}" if old_layout else "")
    if old_layout:
        report = {"tx": read["tx"], "rpc": read["rpc"].split("//")[1], "signer": read["signer"],
                  "receiver": read["receiver"], "batch_id": args.get("batch_id"), "segments": len(segs),
                  "rows": len(rows), "kos": sum(s.get("kos", 0) for s in segs), "fight_hash": None,
                  "rows_digest": None, "first_segment": segs[0] if segs else None, "checks": checks, "ok": False}
        return report, False
    fh, rd = fmt.fight_hash(segs), fmt.rows_digest(rows)
    ev = rpclib.events_named(out, "post_batch")
    logged = [e.get("fight_hash") for e in ev if "fight_hash" in e]
    need("fight_hash recomputed from the args equals the logged one", logged and logged[-1] == fh,
         f"args {fh} logged {logged[-1] if logged else None}")
    applied = [e["status"] for e in rpclib.events_named(out, "apply_result")]
    need("apply_rows applied", applied and applied[-1] == "applied", f"apply_result {applied}")
    for s in segs:
        try:
            fmt.check_segment(s)
            fine = True
        except ValueError as exc:
            fine = str(exc)
        need(f"segment {s['segment_id']} well formed", fine is True, "" if fine is True else fine)
    if state is not None:
        b = next((b for b in state["batches"] + state.get("settled", []) if b["batch_id"] == args["batch_id"]), None)
        need("batch is in the writer state", b is not None, args["batch_id"])
        if b is not None:
            need("writer's fight_hash equals the archival one", b["fight_hash"] == fh)
            for i, (s, local) in enumerate(zip(segs, b["local"])):
                rec = json.loads(Path(local).read_text())
                sealed = rec["sealed"]
                same = all(sealed[k] == s[k] for k in fmt.SEGMENT_HASHES)
                need(f"{s['segment_id']}: local sealed hashes equal the archival args", same, local)
                if i < replay:
                    import server  # noqa: E402  (near/arena)
                    game = server.replay_segment(rec)
                    need(f"{s['segment_id']}: replay final state equals the archival args",
                         game.state_hash() == s["final_state_hash"], game.state_hash())
    ok = all(c["ok"] for c in checks)
    report = {"tx": read["tx"], "rpc": read["rpc"].split("//")[1], "signer": read["signer"], "receiver": read["receiver"],
              "batch_id": args.get("batch_id"), "segments": len(segs), "rows": len(rows),
              "kos": sum(s["kos"] for s in segs), "fight_hash": fh, "rows_digest": rd,
              "first_segment": segs[0] if segs else None, "checks": checks, "ok": ok}
    return report, ok


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("tx", nargs="?")
    ap.add_argument("signer", nargs="?")
    ap.add_argument("--state", help="the writer's state.json, to match each segment to its local sealed record")
    ap.add_argument("--replay", type=int, default=0, help="re-simulate the first N local records")
    a = ap.parse_args(argv)
    if a.tx is None:
        if not SETTLED.exists():
            print(f"archival: no pinned batches: {SETTLED} is missing. Give a tx hash and its signer, "
                  f"or pin settled batches there.", file=sys.stderr)
            return 2
        pinned = json.loads(SETTLED.read_text())
        bad = 0
        for item in pinned["batches"]:
            report, ok = check(read_batch(item["tx"], item["signer"]))
            same = report["fight_hash"] == item["fight_hash"]
            bad += not (ok and same)
            print(f"{'PASS' if ok and same else 'FAIL'} {item['batch_id']} tx {item['tx']} via {report['rpc']}: "
                  f"{report['segments']} segments, {report['rows']} rows, {report['kos']} KOs, fight_hash {report['fight_hash']}"
                  + ("" if same else f" (pinned {item['fight_hash']})")
                  + "".join(f"\n  FAIL {c['check']}: {c['detail']}" for c in report["checks"] if not c["ok"]))
        print(f"{len(pinned['batches']) - bad}/{len(pinned['batches'])} settled batches read back from archival RPC")
        return 1 if bad else 0
    if a.signer is None:
        ap.error("a tx hash needs its signer account")
    read = read_batch(a.tx, a.signer)
    state = None
    if a.state:
        state = json.loads(Path(a.state).read_text())
        settled = Path(a.state).with_name("batches.jsonl")      # batches the writer moved out once settled
        state["settled"] = [json.loads(l) for l in settled.read_text().splitlines() if l] if settled.exists() else []
    report, ok = check(read, state, a.replay)
    print(json.dumps(report, indent=1))
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
