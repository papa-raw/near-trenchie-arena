#!/usr/bin/env -S python3 -I
"""make demo: re-simulate every segment in near/replay/MANIFEST and check it against testnet, read from archival RPC.

    python3 -I near/replay/demo.py                       # the committed MANIFEST
    python3 -I near/replay/demo.py --manifest <path>     # another MANIFEST (a tampered copy, say)

No key, no account, no contract state. For each recorded batch it reads the `arena.post_batch` transaction (the
settle) from archival RPC only (archival-rpc.testnet.near.org, then archival-rpc.testnet.fastnear.com; B96), and the
`arena.commit_seeds` transaction each segment's seed came from. Then, for each segment, from the log committed here:

  seed         the record's seed is the committed seed at the args' (commit_id, seed_index): sha256(the commit's
               secret, its block's random seed, the index), as that commit's event and return value publish it,
               and its hash is the args' seed_hash;
  start        the start state is anchored: a run's first segment starts from a fresh arena on its seed (tick 0,
               nothing in it), and every later one from the previous MANIFEST segment's replayed end state, with
               only the new seed and the still-pending inputs' dedup keys changed (as the arena opens a segment).
               An end state is passed on only when its replay ended on the archival hash, which pins it; a segment
               after one whose replay did not cannot be anchored, so it fails too, and says so;
  inputs       the hash of the signed input log equals the args' inputs_hash;
  predictions  the hash of the predictions log equals the args' predictions_log_hash;
  rules        the record runs under the args' rules_hash, and that table ships in near/arena/rules/;
  KOs          the KOs the log's completed lives score equal the args' kos;
  replay       a re-simulation from the record's start state and commands, under that rules table, ends on the
               args' final_state_hash. The record's own sealed hashes are never trusted: the replay is held to
               the archival hash alone.

Each segment prints PASS or FAIL with the first check that failed; then the measured rates, the age of the oldest
settle transaction (every daily check should include one older than 2 days), and, last, the count that passed.
Exit 0 only when every segment passes.
"""

import argparse
import base64
import copy
import datetime
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "near" / "arena")]

import replay as engine  # noqa: E402  (near/arena)
import sim  # noqa: E402  (near/arena)
from near.chain import batch as fmt, rpc as rpclib  # noqa: E402

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "MANIFEST"
DAY_NS = 86_400 * 10 ** 9
OLD_DAYS = 2


class Unread(Exception):
    """An archival read that gave no usable answer."""


class Archive:
    """Archival reads only: each endpoint in order, the first answer wins; never a regular node."""

    def __init__(self, urls, post=None):
        self.urls, self.post = list(urls), post
        self.used, self.reads, self.seconds = set(), 0, 0.0

    def _call(self, fn):
        last = None
        for url in self.urls:
            t0 = time.perf_counter()
            try:
                out = fn(rpclib.Rpc([url], post=self.post, rounds=2))
            except (rpclib.RpcError, rpclib.RpcUnreachable) as exc:
                last = f"{url.split('//')[-1]}: {str(exc)[:160]}"
                continue
            finally:
                self.reads += 1
                self.seconds += time.perf_counter() - t0
            self.used.add(url.split("//")[-1])
            return out
        raise Unread(last or "no archival endpoint")

    def tx(self, tx_hash, signer):
        return self._call(lambda r: r.tx(tx_hash, signer))

    def block_ns(self, block_hash):
        return int(self._call(lambda r: r.call("block", {"block_id": block_hash}))["header"]["timestamp_nanosec"])


def function_call(res):
    t = res["transaction"]
    fc = t["actions"][0]["FunctionCall"]
    return t, fc["method_name"], json.loads(base64.b64decode(fc["args"]))


def read_batch(archive, m, b):
    """The post_batch args by segment id, its block time, and the batch-level problems (empty when sound)."""
    res = archive.tx(b["tx"], b["signer"])
    t, method, args = function_call(res)
    out = rpclib.outcome(res)
    problems = []
    if method != "post_batch" or t["receiver_id"] != m["arena"] or t["signer_id"] != b["signer"]:
        problems.append(f"tx is {t['signer_id']} -> {t['receiver_id']}.{method}, not {b['signer']} -> {m['arena']}.post_batch")
    if args.get("batch_id") != b["batch_id"]:
        problems.append(f"tx carries batch {args.get('batch_id')}, MANIFEST says {b['batch_id']}")
    if not out["ok"]:
        problems.append(f"tx failed: {out['failure']}")
    logged = [e.get("fight_hash") for e in rpclib.events_named(out, "post_batch")]
    fh = fmt.fight_hash(args.get("segments", []))
    if not logged or logged[-1] != fh:
        problems.append(f"fight_hash of the args {fh} is not the one the tx logged ({logged[-1] if logged else None})")
    segs = {s["segment_id"]: s for s in args.get("segments", [])}
    return {"segments": segs, "fight_hash": fh, "block_ns": archive.block_ns(res["transaction_outcome"]["block_hash"]),
            "problems": problems}


def read_commit(archive, m, c):
    """{index: 32-byte seed hex} of one commit_seeds tx, each seed re-derived from the event's secret and random seed."""
    res = archive.tx(c["tx"], c["signer"])
    t, method, args = function_call(res)
    out = rpclib.outcome(res)
    if method != "commit_seeds" or t["receiver_id"] != m["arena"] or not out["ok"]:
        raise Unread(f"commit {c['commit_id']}: tx {c['tx']} is not a landed {m['arena']}.commit_seeds")
    ev = rpclib.events_named(out, "commit_seeds")
    if not ev or int(ev[0]["commit_id"]) != int(c["commit_id"]):
        raise Unread(f"commit {c['commit_id']}: tx {c['tx']} logged commit {ev[0]['commit_id'] if ev else None}")
    secret, random_seed = bytes.fromhex(ev[0]["secret"]), bytes.fromhex(ev[0]["random_seed"])
    if ev[0]["secret"] != args["secret"]:
        raise Unread(f"commit {c['commit_id']}: the logged secret is not the one the tx sent")
    seeds = out["value"]
    derived = [fmt.derive_seed(secret, random_seed, i).hex() for i in range(len(seeds))]
    if derived != seeds:
        raise Unread(f"commit {c['commit_id']}: its return value is not sha256(secret, random seed, i)")
    return dict(enumerate(seeds))


def next_start(end, seed):
    """The state the arena opens a segment with, from the previous segment's end state and the new seed.
    Mirrors near/arena/server.py `Arena._open_next_segment`; test_demo's chained segment fails if the two drift."""
    start = copy.deepcopy(end)
    start["seed"] = start["rng"] = seed
    pending = {sim.canonical([row["kind"], row["fighter_id"], row["sequence"]]).decode("utf-8") for row in start["inputs"]}
    start["seen"] = {key: start["seen"][key] for key in sorted(pending)}
    return start


def check_start(record, prev):
    """Why the record's start state is not anchored, or None. `prev` is the previous MANIFEST segment's
    {"end": its replayed end state, or None when its replay missed, "label": its n/total}, or None for the first."""
    start = record["initial_state"]
    if start["tick"] == 0:
        fresh = sim.Sim(start["seed"], engine.load_rules(record["rules_hash"])).export()
        return None if start == fresh else "a tick-0 start state that is not a fresh arena on its seed"
    if prev is None or prev["end"] is None:
        why = (f"segment {prev['label']}'s replay did not end on its archival hash" if prev
               else "no earlier segment in the MANIFEST")
        return f"unanchored: it continues a run, and {why}"
    if prev["end"]["tick"] != start["tick"]:
        return f"starts at tick {start['tick']}, the previous MANIFEST segment ends at {prev['end']['tick']}"
    if next_start(prev["end"], start["seed"]) != start:
        return "not the previous segment's replayed end state"
    return None


def check_segment(record, arg, seeds, prev=None):
    """(the first check that failed as (name, detail), or None; the replayed end state, or None).

    The end state is returned whenever the re-simulation ended on the args' final_state_hash, even if another check
    failed: that hash pins it, so the next segment can still be anchored on it."""
    fails = []
    start = record["initial_state"]
    seed = start["seed"]
    committed = seeds.get(int(arg["commit_id"]), {}).get(int(arg["seed_index"]))
    if committed is None:
        fails.append(("seed", f"commit {arg['commit_id']} index {arg['seed_index']} is not in a MANIFEST commit"))
    elif fmt.seed_u64(committed) != seed:
        fails.append(("seed", f"log seed {seed} is not commit {arg['commit_id']}'s seed {arg['seed_index']} "
                              f"({fmt.seed_u64(committed)})"))
    elif sim.digest(str(seed)) != arg["seed_hash"]:
        fails.append(("seed", "seed hash differs from the args"))
    if record["rules_hash"] != arg["rules_hash"] or start["rules_hash"] != arg["rules_hash"]:
        return ("rules", f"the log runs under {record['rules_hash'][:12]}, the args say {arg['rules_hash'][:12]}"), None
    try:
        engine.load_rules(arg["rules_hash"])
    except ValueError:
        return ("rules", f"no shipped rules table has hash {arg['rules_hash']}"), None
    unanchored = check_start(record, prev)
    if unanchored:
        fails.append(("start", unanchored))
    # Hold the replay to the archival hash: the record's sealed final hash is replaced by the args' before replaying.
    held = copy.deepcopy(record)
    held["sealed"]["final_state_hash"] = arg["final_state_hash"]
    held["sealed"]["sealed_result_hash"] = engine.engine_commitment(held)
    end = None
    try:
        end = engine.replay_segment(held).export()
    except (ValueError, KeyError, TypeError) as exc:
        fails.append(("replay", "the re-simulated final state is not the args' final_state_hash"
                      if str(exc) == "replay state hash mismatch" else f"re-simulation refused: {exc}"))
    if sim.digest(record["sealed"]["input_events"]) != arg["inputs_hash"]:
        fails.append(("inputs", "the input log's hash differs from the args' inputs_hash"))
    if sim.digest(record["predictions"]) != arg["predictions_log_hash"]:
        fails.append(("predictions", "the predictions log's hash differs from the args"))
    if fmt.segment_kos(record["sealed"]) != int(arg["kos"]):
        fails.append(("KOs", f"the log's lives score {fmt.segment_kos(record['sealed'])} KOs, the args {arg['kos']}"))
    return (fails[0] if fails else None), end


def utc(ns):
    return datetime.datetime.fromtimestamp(ns / 1e9, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(manifest_path=MANIFEST, urls=None, post=None, now_ns=None, out=print):
    t_start = time.perf_counter()
    manifest_path = Path(manifest_path)
    m = json.loads(manifest_path.read_text())
    archive = Archive(urls or m["archival"], post)
    total = sum(len(b["segments"]) for b in m["batches"])
    name = "near/replay/MANIFEST" if manifest_path.resolve() == MANIFEST else str(manifest_path)
    out(f"make demo: {total} recorded segments in {name}, each re-simulated and checked against its "
        f"{m['network']} arena.post_batch transaction, read from archival RPC")
    seeds, commit_problem = {}, {}
    for c in m["commits"]:
        try:
            seeds[int(c["commit_id"])] = read_commit(archive, m, c)
        except (Unread, KeyError, ValueError) as exc:
            commit_problem[int(c["commit_id"])] = str(exc)
    n, passed, checked, ticks, sim_s, pass_s, block_times = 0, 0, 0, 0, 0.0, 0.0, []
    prev = None      # the previous MANIFEST segment: {"end": its replayed end state, or None if it failed, "label"}
    for b in m["batches"]:
        try:
            got = read_batch(archive, m, b)
            problem = "; ".join(got["problems"])
            block_times.append(got["block_ns"])
        except (Unread, KeyError, ValueError) as exc:
            got, problem = None, f"archival read failed: {exc}"
        rules = sorted({s["rules_hash"] for s in got["segments"].values()}) if got else []
        out(f"batch {b['batch_id']}: tx {b['tx']}, {len(b['segments'])} segments"
            + (f", settled {utc(got['block_ns'])}, rules {', '.join(r[:12] for r in rules)}" if got else ""))
        for s in b["segments"]:
            n += 1
            label = f"{n:>2}/{total} {s['segment_id']}"
            why, end = (("batch", problem) if problem else None), None
            arg = got["segments"].get(s["segment_id"]) if got else None
            if why is None and arg is None:
                why = ("batch", "the tx's args carry no such segment")
            if why is None and int(arg["commit_id"]) in commit_problem:
                why = ("seed", commit_problem[int(arg["commit_id"])])
            if why is None:
                try:
                    record = json.loads((manifest_path.parent / s["record"]).read_text())
                except (OSError, ValueError) as exc:
                    why = ("log", f"cannot read {s['record']}: {exc}")
            if why is None:
                t0 = time.perf_counter()
                try:
                    why, end = check_segment(record, arg, seeds, prev)
                except (KeyError, TypeError, ValueError) as exc:
                    why = ("log", f"malformed record: {type(exc).__name__}: {exc}")
                took = time.perf_counter() - t0
                checked, sim_s = checked + 1, sim_s + took
                if why is None:
                    ticks, pass_s = ticks + int(record["sealed"]["tick_count"]), pass_s + took
            prev = {"end": end, "label": f"{n}/{total}"}
            if why is None:
                passed += 1
                out(f"PASS {label}  seed {arg['commit_id']}:{arg['seed_index']}  {arg['kos']} KOs  "
                    f"final {arg['final_state_hash'][:16]}")
            else:
                out(f"FAIL {label}  {why[0]}: {why[1]}")
    jobs = len(m.get("jobs", []))
    if jobs:      # never pass what was not checked: job txs need their own check before they are pinned
        out(f"FAIL jobs: {jobs} job transactions are pinned, and this demo has no job check yet")
    else:
        out("jobs: none recorded (the market has no job methods in this build)")
    wall = time.perf_counter() - t_start
    rate = f" ({ticks / pass_s:,.0f} ticks/s, {pass_s / passed:.2f} s a passing segment)" if pass_s and passed else ""
    out(f"measured: {checked} segments re-simulated and checked in {sim_s:.1f} s{rate}; "
        f"{archive.reads} archival reads in {archive.seconds:.1f} s via {', '.join(sorted(archive.used)) or 'none'}; "
        f"total {wall:.1f} s")
    if block_times:
        now_ns = now_ns if now_ns is not None else time.time_ns()
        oldest = min(block_times)
        age = (now_ns - oldest) / DAY_NS
        met = age > OLD_DAYS
        out(f"archival age: the oldest settle tx is from {utc(oldest)}, {age:.1f} days old; one older than "
            f"{OLD_DAYS} days: " + ("yes" if met else f"not yet (from {utc(oldest + OLD_DAYS * DAY_NS)})"))
    out(f"{passed}/{total} PASS" + ("" if passed == total else f", {total - passed} FAIL")
        + (f"; {jobs} job transactions not checked: FAIL" if jobs else ""))
    return 0 if passed == total and not jobs else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--manifest", default=str(MANIFEST), help="the MANIFEST to check (default: the committed one)")
    a = ap.parse_args(argv)
    return run(a.manifest)


if __name__ == "__main__":
    sys.exit(main())
