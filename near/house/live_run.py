"""make live: the local DEV host with the house for a fixed time, then a summary of what really ran.

    python3 -B near/house/live_run.py [--seconds 30] [--port 0] [--data-dir DIR] [--budget building]

With NEARAI_API_KEY in the environment the 14 house personas run on the NEAR AI Cloud model under the
daily budget cap; without it the house fights on its tick policy and posts only its sheets' keyed lines,
labelled "autopilot" under the "autopilot (no model key)" chip, and the output says so, with no model call.
Without TRENCHIE_BLOCKLIST (the block list kept outside the repo) every feed line, house and player alike,
is muted to an emote and the output prints "guard list missing". Nothing falls back quietly.

What this target does not do yet, said in the output: the labelled testnet copy of the contracts.
Standard library plus the arena's own dependencies.
"""

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "near/arena"), str(ROOT / "near/house")]
import live  # noqa: E402
import runtime  # noqa: E402
import snap_local  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seconds", type=int, default=30)
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--budget", choices=["auto"] + sorted(runtime.DAY_CAPS_USD), default="auto")
    args = ap.parse_args(argv)
    kind = "live" if os.environ.get(live.KEY_ENV) else "keyed"
    data_dir = args.data_dir or tempfile.mkdtemp(prefix="make-live-")
    dev = snap_local.DevRoom(args.port, data_dir, house=kind, budget_mode=args.budget)
    say = lambda line: print("make live: " + line, flush=True)
    if kind == "keyed":
        say(f"no model key ({live.KEY_ENV} is not set): the house fights on its tick policy and posts only its labelled "
            "keyed lines (chip: autopilot (no model key)); no model call is made")
    else:
        b = dev.house_budget
        say(f"house on {live.MODEL_LABEL}, {b.mode} cap ${runtime.DAY_CAPS_USD[b.mode]}/day ({b.source})")
    if dev.feed.notice():
        say(f"{dev.feed.notice()}: TRENCHIE_BLOCKLIST is not set, so every feed line is muted to an emote")
    say("not part of this target yet: the labelled testnet copy of the contracts")

    def ready(port):
        say(f"DEV host on http://127.0.0.1:{port} for {args.seconds} s (spectator ws://127.0.0.1:{port}; "
            "GET /house/feed, /house/roster, /house/predictions.jsonl)")

    asyncio.run(snap_local.serve(dev, ready=ready, ticks=args.seconds * 20))
    _, roster = dev.route("GET", "/house/roster", b"", "local")
    fed = dev.feed.public()
    _, (log_bytes, log_hash) = dev.route("GET", "/house/predictions.jsonl", b"", "local")
    say(f"ran {dev.round.arena.sim.state['tick']} ticks; round {dev.round_index}; arena failed: {dev.round.arena.failed}")
    say(f"roster: {roster['admitted']} admitted, house model {roster['house_model']}, chip {roster['chip']}, "
        f"house spend today {roster['house_spend_today_microusd']} micro-USD")
    say(f"feed: guard {fed['guard']}, counts {json.dumps(fed['counts'], sort_keys=True)}")
    for row in fed["lines"][-3:]:
        say(f"  {row['who']}: {row['text']}" + (f"  [{row['label']}]" if row["label"] else ""))
    say(f"predictions: {len(log_bytes.splitlines())} lines, log hash {log_hash}")
    for note in roster.get("notes", []):
        say("note: " + note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
