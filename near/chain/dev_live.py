#!/usr/bin/env -S python3 -I
"""The DEV arena (near/arena/snap_local.py) with the chain writer attached.

    python3 -I near/chain/dev_live.py                                  # dry-run: prints every call, sends nothing
    python3 -I near/chain/dev_live.py --chain testnet --env ~/.config/trenchie/chain-testnet.env --minutes 60

Dry-run is the default. It needs no env file and no key: each call the writer would send is printed in full
(signer, receiver, method, gas, deposit, the exact argument bytes) and simulated on the contract model, and
every line and tx id says DRY-RUN. `--chain testnet` signs with the key files the env file names (outside
the repo) and sends to NEAR testnet.

The arena runs on committed seeds only: the writer commits a batch of seeds first, reads them from that
transaction's return value, and the arena opens no segment before its seed is published. Each sealed
segment is bound to its seed; every `--batch-segments` seals (60 = one hour, the G0 cadence) close a batch
for `arena.post_batch`, and the stake resolver follows it with `market.resolve`. The writer's journal,
state and hashes.tsv live under `<data dir>/chain/`. snap_local is used as it is: the runner hands its
arenas the writer through `server.Arena(chain=...)`.
"""

import argparse
import asyncio
import functools
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "near" / "arena")]

import server  # noqa: E402  (near/arena)
import snap_local  # noqa: E402  (near/arena)
from near.chain import config as chaincfg, model, rpc as rpclib, sender as senders  # noqa: E402
from near.chain.writer import ChainWriter, G0_OPTIONS  # noqa: E402


def make_writer(mode, env, data_dir, **kw):
    if mode == "testnet":
        if not env:
            raise SystemExit("--chain testnet needs --env <file outside the repo> (or TRENCHIE_CHAIN_ENV)")
        cfg = chaincfg.ChainConfig.from_env_file(env)
        keys = cfg.keys()
        snd = senders.RpcSender(cfg.rpc(), keys)
        identity = cfg.identity_rpc()
        print("chain: TESTNET writes on " + json.dumps(cfg.public()) +
              f"; operator {keys['operator'].account_id} ({keys['operator'].public_key}), "
              f"resolver {keys['resolver'].account_id} ({keys['resolver'].public_key})", flush=True)
    else:
        cfg = chaincfg.ChainConfig.from_env_file(env) if env else chaincfg.dry_run_config()
        ids = {"operator": "operator.dry-run.testnet", "resolver": "resolver.dry-run.testnet"}
        m = model.Contracts(cfg.arena, cfg.market, cfg.nft, ids["operator"], ids["resolver"])
        (Path(data_dir) / "chain").mkdir(parents=True, exist_ok=True)
        snd = senders.DryRun(m, ids, calls_path=Path(data_dir) / "chain" / "dry-run-calls.jsonl")
        identity = model.Contracts(cfg.arena, cfg.market, cfg.identity_nft, ids["operator"], ids["resolver"])
        print("chain: DRY-RUN: nothing is sent; every call below is printed and simulated on the contract model",
              flush=True)
    return ChainWriter(snd, cfg, Path(data_dir) / "chain", identity=identity, **kw)


def attach(writer):
    """Make every arena snap_local builds take its seeds from, and report its seals to, this writer."""
    original = server.Arena

    class ChainArena(original):
        def __init__(self, *a, **k):
            k.setdefault("chain", writer)
            super().__init__(*a, **k)

    snap_local.server.Arena = ChainArena
    if not getattr(snap_local.DevRoom.health, "chain_passthrough", False):
        dev_health = snap_local.DevRoom.health

        def health(room):
            """/dev/health with the writer's `chain` field (owner-read holds, backlog), unless the host adds it."""
            out = dev_health(room)
            if "chain" not in out:
                chain = room.round.arena.health().get("chain")
                if chain is not None:
                    out["chain"] = chain
            return out
        health.chain_passthrough = True
        snap_local.DevRoom.health = health
    return original


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--chain", choices=("dry-run", "testnet"), default="dry-run")
    ap.add_argument("--env", default=chaincfg.env_file_default())
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--minutes", type=float, default=60.0, help="arena minutes to run (1200 ticks each)")
    ap.add_argument("--g0", choices=sorted(G0_OPTIONS), default="C",
                    help="the G0 batch option (Pat's pick; C, 3 parts an hour, is the default)")
    ap.add_argument("--batch-segments", type=int, default=None, help="override the option's period, in segments")
    ap.add_argument("--parts", type=int, default=None, help="override the option's parts a period")
    ap.add_argument("--max-rows", type=int, default=None, help="override the option's rows a part")
    ap.add_argument("--commit-size", type=int, default=60)
    ap.add_argument("--lookahead", type=int, default=15)
    ap.add_argument("--flush-partial", action="store_true", help="at the end, post the open segments as a short batch")
    a = ap.parse_args(argv)
    data_dir = a.data_dir or tempfile.mkdtemp(prefix="dev-live-")
    g0 = dict(G0_OPTIONS[a.g0])
    for k in ("batch_segments", "parts", "max_rows"):
        if getattr(a, k) is not None:
            g0[k] = getattr(a, k)
    print(f"dev_live: G0 option {a.g0} as run: {g0}", flush=True)
    writer = make_writer(a.chain, a.env, data_dir, commit_size=a.commit_size, lookahead=a.lookahead, **g0)
    writer.start()
    attach(writer)
    dev = snap_local.DevRoom(a.port, data_dir)
    writer.run_background(every=10.0)
    writer.run_owner_reader()
    # Arena time, not wall time: N minutes is N*1200 ticks, so 60 minutes seals exactly 60 segments (one G0
    # batch) however busy the machine is; +2 ticks let the last segment seal. Wall time is in the summary.
    ticks = int(a.minutes * 60 * snap_local.RULES["tick_hz"]) + 2
    print(f"dev_live: DEV arena on http://127.0.0.1:{a.port}, data {data_dir}, {a.minutes} min "
          f"({ticks} ticks), chain {a.chain}. Admin header X-Dev-Admin: {dev.admin}", flush=True)
    started = time.time()
    try:
        asyncio.run(snap_local.serve(dev, ticks=ticks))
    except KeyboardInterrupt:
        print("dev_live: stopped by Ctrl-C", flush=True)
    finally:
        if a.flush_partial:
            writer.flush_open()
        writer.close(flush=True)
        summary = dict(writer.summary(), wall_seconds=round(time.time() - started, 1), data_dir=data_dir,
                       resyncs=dev.resyncs, slowest_tick_ms=round(dev.slowest * 1000, 1))
        (Path(data_dir) / "chain" / "summary.json").write_text(json.dumps(summary, indent=1))
        print("dev_live: summary " + json.dumps(summary), flush=True)
    return 0 if not writer.failed else 1


if __name__ == "__main__":
    sys.exit(main())
