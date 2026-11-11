"""The live DEV crowd check for battle mode: the DEV host with the house on the real model, headless, for a
number of sim minutes, then a report of what the house actually did.

    NEARAI_API_KEY=... TRENCHIE_BLOCKLIST=... python3 -B near/house/battle_crowd.py OUT_DIR [--minutes 5] [--budget building]

It needs the arena's behaviour input (rules table integer-13 or later); without it the report says so and the
house is not in battle mode. It reports, from the host's own records (never from the model's account of itself):
- plans: every behaviour order and its ACK (house/behaviours.jsonl): per persona, how many applied, clipped or
  refused, the distinct plans, and the triggers that caused rewrites;
- reflexes: the engine's `reflex` events per persona (turned on / off), and which fired while a rival was within reach;
- lines: every house feed row, with its emoji and whether the line names something the event log shows happened;
- spend: the meter against the day's cap, the chip at the end.
The model key is read from the environment only and never written. Standard library only.
"""

import argparse
import collections
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(HERE.parent / "arena"), str(HERE)]
import live  # noqa: E402
import runtime  # noqa: E402
import snap_local  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("out")
    ap.add_argument("--minutes", type=float, default=5)
    ap.add_argument("--budget", choices=["auto"] + sorted(runtime.DAY_CAPS_USD), default="auto")
    args = ap.parse_args(argv)
    if not os.environ.get(live.KEY_ENV):
        raise SystemExit("battle_crowd: needs %s in the process environment" % live.KEY_ENV)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    data = out / "host"
    host = snap_local.DevRoom(0, str(data), house="live", budget_mode=args.budget)
    house = host.round.house
    battle_on = house.battle
    reflexes, said, events_seen = collections.Counter(), [], collections.Counter()
    t0, ticks = time.time(), int(args.minutes * 60 * 20)
    for _ in range(ticks):                       # real time per tick, so the model calls land as they would live
        host.round.arena.advance()
        for e in host.round.arena.sim.state["events"]:
            events_seen[e["kind"]] += 1
            if e["kind"] == "reflex" and e.get("on"):
                reflexes[(e["fighter"], e.get("index"))] += 1
        time.sleep(max(0.0, t0 + (_ + 1) / 20 - time.time()))
    plans = [json.loads(l) for l in (data / "house" / "behaviours.jsonl").read_text().splitlines()] if (data / "house" / "behaviours.jsonl").exists() else []
    by = collections.defaultdict(list)
    for p in plans:
        by[p["persona"]].append(p)
    distinct = {name: len({json.dumps(p.get("applied"), sort_keys=True) for p in rows if p.get("applied")}) for name, rows in by.items()}
    lines = [r for r in host.feed.since(0) if r["source"] == "house"]
    roster = house.public_roster()
    report = {
        "battle_mode": battle_on,
        "engine_has_behaviour_input": "behaviour" in snap_local.RULES.get("input_kinds", ()),
        "sim_minutes": args.minutes, "wall_seconds": round(time.time() - t0, 1),
        "plans": {"orders": len(plans), "status": collections.Counter(p.get("status") for p in plans),
                  "triggers": collections.Counter(p.get("trigger") for p in plans), "distinct_applied_per_persona": distinct,
                  "personas_with_a_plan": len(by),
                  "first_applied": {n: rows[0].get("applied") for n, rows in by.items() if rows and rows[0].get("applied")}},
        "reflexes_on": {"%s#%s" % k: v for k, v in sorted(reflexes.items())},
        "events": dict(events_seen),
        "lines": {"count": len(lines), "with_emoji": sum(1 for r in lines if r.get("emoji")),
                  "emoji_fallback": sum(1 for r in lines if r.get("emoji_fallback")),
                  "sample": [{"who": r["who"], "text": r["text"], "emoji": r.get("emoji"), "label": r.get("label")} for r in lines[:12]]},
        "spend": {"today_microusd": roster["house_spend_today_microusd"], "cap_microusd": roster["house_cap_today_microusd"],
                  "chip": roster["chip"], "notes": roster.get("notes")},
    }
    (out / "battle-crowd.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, default=dict))
    print(json.dumps({k: v for k, v in report.items() if k != "lines"}, ensure_ascii=False, default=dict)[:2000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
