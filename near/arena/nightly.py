"""Nightly report columns (F9) computed from real sealed segment logs.

Re-simulates each sealed record under its own rules and reads its events. Columns: damage share against KO
share per weapon kind and signature; win rate after the first KO (lives with a first KO that reach a second);
(build band, style) pairs; and the stack-one-stat build (a kit with 20 or more points in one stat) first.
Integers only (milli-units). Run: python3 -B near/arena/nightly.py DIR_OF_SEGMENT_JSON
"""

from collections import Counter, defaultdict
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

STACK_POINTS = 20
BANDS = ((0, 40, "<=40"), (41, 60, "41-60"), (61, 10 ** 6, "61+"))


def events_of(record):
    """Yield (game, events) after every tick of a sealed record, following replay's command rules."""
    rules = replay.load_rules(record["rules_hash"])
    game = sim.Sim.restore(record["initial_state"], rules)
    for command in record["commands"]:
        kind, value = command["kind"], command["value"]
        if kind == "input":
            game.enqueue(sim.Input(**value))
        elif kind == "cancel_spawn":
            replay.cancel_spawns(game, value)
        elif kind == "retire":
            game.state["fighters"].pop(value, None)
            game.state["inputs"] = [r for r in game.state["inputs"] if r["fighter_id"] != value]
        elif kind == "advance":
            for _ in range(value):
                game.step()
                yield game, game.state["events"]


def band(points):
    return next(label for lo, hi, label in BANDS if lo <= points <= hi)


def kit_points(game, equipped):
    items = game.rules["items"]
    stats = Counter()
    for row in equipped.values():
        for k, v in items[row]["stats"].items():
            stats[k] += v
    return sum(stats.values()), max(stats.values(), default=0)


def report(records):
    damage, kos, hits = Counter(), Counter(), 0
    lives = {}                                   # life_id -> {"kos", "style", "points", "stack"}
    first_ko = Counter()
    for record in records:
        for game, events in events_of(record):
            for f in game.state["fighters"].values():          # every life, first lives included
                if f["state"] == "alive" and f["life_id"] not in lives:
                    points, top = kit_points(game, f["equipped"])
                    lives[f["life_id"]] = {"kos": 0, "style": f["style"], "points": points, "stack": top >= STACK_POINTS}
            for e in events:
                if e["kind"] == "hit":
                    src = game.state["fighters"].get(e["source"])
                    if src is not None:
                        label = game.rules["items"][src["equipped"]["weapon"]]["weapon"]
                        damage[label] += e["damage"]
                        hits += 1
                elif e["kind"] == "ko":
                    src = game.state["fighters"].get(e["source"])
                    if src is not None:
                        label = game.rules["items"][src["equipped"]["weapon"]]["weapon"]
                        kos[label] += 1
                        mine = lives.get(src["life_id"])
                        if mine is not None:
                            mine["kos"] += 1
    total_damage, total_kos = sum(damage.values()), sum(kos.values())
    columns = {w: {"damage_share_milli": damage[w] * 1000 // total_damage if total_damage else None,
                   "ko_share_milli": kos[w] * 1000 // total_kos if total_kos else None,
                   "damage": damage[w], "kos": kos[w]} for w in sorted(set(damage) | set(kos))}
    with_first = [l for l in lives.values() if l["kos"] >= 1]
    pairs = defaultdict(lambda: {"lives": 0, "kos": 0})
    for l in lives.values():
        row = pairs["%s/%s%s" % (band(l["points"]), l["style"], "/stack" if l["stack"] else "")]
        row["lives"] += 1
        row["kos"] += l["kos"]
    ordered = dict(sorted(pairs.items(), key=lambda kv: ("/stack" not in kv[0], kv[0])))     # stack builds first
    for row in ordered.values():
        row["kos_per_life_milli"] = row["kos"] * 1000 // row["lives"]
    return {"segments": len(records), "hits": hits, "weapon_columns": columns,
            "win_after_first_ko": {"lives_with_first_ko": len(with_first),
                                   "reached_second": sum(l["kos"] >= 2 for l in with_first),
                                   "rate_milli": sum(l["kos"] >= 2 for l in with_first) * 1000 // len(with_first) if with_first else None},
            "build_style_pairs": ordered}


if __name__ == "__main__":
    files = sorted(Path(sys.argv[1]).glob("segment-*.json"))
    print(json.dumps(report([json.loads(p.read_bytes()) for p in files]), indent=1, sort_keys=True))
