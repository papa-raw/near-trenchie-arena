"""The locked balance bar (P1-P7b), computed from a sweep report. Prints values, never a verdict.

Run: python3 -B near/arena/bar_gate.py REPORT.json --variance 20 [--variant baseline] [--output gate.json]

Every threshold is the reviewer's locked number. A cell that is missing, censored-only or under its
minimum denominator is reported as NOT MEASURED, which the bar counts as a fail. A field reads
"within" when every gated cell is inside its limit and every required cell was measured. The builder
never marks the bar passed: the status line says it awaits the critic.
"""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
import balance
import replay

LIMITS = {"P1_lift_milli": 1500, "P1_min_rare_kos": 30, "P2_bps": 6000, "P2_min_resolved": 50,
          "P2_max_censored_pct": 25, "index_milli": 2000, "kos_floor": 20, "P4_min_lives": 20,
          "P4_survival_milli": 2000, "P5_min_lives": 100, "P6_min_lives": 100,
          "P7a_streak": 3, "P7b_milli": 500, "P7b_min_lives": 20}
CROWDS = (2, 6, 10, 16)
HUNT_CROWDS = (6, 10, 16)


def verdict(cells):
    """cells: list of dicts with 'status' in within|exceeds|not measured|ungated."""
    states = {c["status"] for c in cells}
    if not cells or "not measured" in states:
        return "NOT MEASURED"
    return "exceeds" if "exceeds" in states else "within"


def floor_split(rows, limit, label):
    """Gate a pooled share table: expected KOs = ticks share * total KOs must reach the floor."""
    total_ticks = sum(r["ticks"] for r in rows.values())
    total_kos = sum(r["kos"] for r in rows.values())
    cells = []
    for key in sorted(rows):
        r = rows[key]
        expected_x1000 = r["ticks"] * total_kos * 1000 // total_ticks if total_ticks else 0
        cell = {label: key, "ticks": r["ticks"], "kos": r["kos"], "expected_kos_milli": expected_x1000,
                "index_milli": r["index_milli"]}
        if expected_x1000 < LIMITS["kos_floor"] * 1000:
            cell["status"] = "ungated"
        else:
            cell["status"] = "exceeds" if r["index_milli"] > limit else "within"
        cells.append(cell)
    return cells


def p1(runs):
    arms = defaultdict(lambda: {"legendary": [0, 0], "rare": [0, 0]})
    for run in runs:
        c = run["scenario"]
        if c["family"] != "legendary_lift":
            continue
        holder = run["shares"]["fighter"].get("holder", {"kos": 0, "ticks": 0})
        cell = arms[(c["left"], c["style"])][c["right"]]
        cell[0] += holder["kos"]
        cell[1] += holder["ticks"]
    cells = []
    for (row, style), arm in sorted(arms.items()):
        (lk, lt), (rk, rt) = arm["legendary"], arm["rare"]
        cell = {"row": row, "style": style, "legendary_kos": lk, "legendary_ticks": lt,
                "rare_kos": rk, "rare_ticks": rt}
        if rk < LIMITS["P1_min_rare_kos"] or not lt or not rt:
            cell["status"] = "not measured"
        else:
            cell["lift_milli"] = lk * rt * 1000 // (lt * rk)
            cell["status"] = "exceeds" if cell["lift_milli"] > LIMITS["P1_lift_milli"] else "within"
        cells.append(cell)
    return cells


def p2(runs):
    rates = balance.set_pieces(runs)
    cells = []
    for crowd, key, name in (("2", "rare_win_bps", "rare beats 1 newcomer"),
                             ("3", "newcomer_win_bps", "rare loses to 2 newcomers")):
        row = rates.get(crowd)
        cell = {"set_piece": name, "crowd": crowd, "row": row}
        if (row is None or row["resolved_runs"] < LIMITS["P2_min_resolved"]
                or row["censored_runs"] * 100 > LIMITS["P2_max_censored_pct"] * row["runs"]
                or row["evidence_missing_runs"]):
            cell["status"] = "not measured"
        else:
            cell["status"] = "within" if row[key] >= LIMITS["P2_bps"] else "exceeds"
        cells.append(cell)
    return cells


def p3(runs):
    cells = []
    for crowd in CROWDS:
        sample = [r for r in runs if r["scenario"]["family"] == "crowd" and r["scenario"]["crowd"] == crowd]
        for kind in ("weapon", "signature"):
            rows = balance.group_shares(sample, kind) if sample else {}
            group = floor_split(rows, LIMITS["index_milli"], kind)
            gated = [c for c in group if c["status"] != "ungated"]
            cells.append({"crowd": crowd, "kind": kind, "runs": len(sample), "groups": group,
                          "status": verdict(gated) if sample else "not measured"})
    return cells


def p3_target(runs):
    duels = balance.bar_fields(runs)["move_parity"]["duels"]
    return {key: {**row, "target": "unmeasured" if row["left_rate_bps"] is None else
                  "within" if 4000 <= row["left_rate_bps"] <= 6000 else "outside"}
            for key, row in sorted(duels.items())}


def minority(runs, crowd, build):
    """One stack or top72 wearer among random kits: KO index and survival ratio, pooled over styles and seeds."""
    sample = [r for r in runs if r["scenario"]["family"] == "minority" and r["scenario"]["crowd"] == crowd
              and r["scenario"]["build"] == build]
    cell = {"crowd": crowd, "build": build, "runs": len(sample)}
    if not sample:
        return dict(cell, status="not measured")
    mine = [r["shares"]["fighter"].get("p00", {"kos": 0, "ticks": 0}) for r in sample]
    everyone = [row for r in sample for row in r["shares"]["fighter"].values()]
    mk, mt = sum(x["kos"] for x in mine), sum(x["ticks"] for x in mine)
    tk, tt = sum(x["kos"] for x in everyone), sum(x["ticks"] for x in everyone)
    my_lives = sum(1 for r in sample for l in r["lives"] if l["fighter"] == "p00")
    all_lives = sum(len(r["lives"]) for r in sample)
    cell.update(minority_kos=mk, minority_ticks=mt, total_kos=tk, total_ticks=tt, minority_lives=my_lives)
    if not mt or not tk or my_lives < LIMITS["P4_min_lives"] or all_lives == my_lives:
        return dict(cell, status="not measured")
    expected_milli = mt * tk * 1000 // tt
    cell["expected_kos_milli"] = expected_milli
    cell["index_milli"] = mk * tt * 1000 // (tk * mt)
    others_ticks, others_lives = tt - mt, all_lives - my_lives
    cell["survival_ratio_milli"] = (mt * others_lives * 1000) // (my_lives * others_ticks) if others_ticks else None
    if expected_milli < LIMITS["kos_floor"] * 1000 or cell["survival_ratio_milli"] is None:
        return dict(cell, status="not measured")
    cell["status"] = ("exceeds" if cell["index_milli"] > LIMITS["index_milli"]
                      or cell["survival_ratio_milli"] > LIMITS["P4_survival_milli"] else "within")
    return cell


def p4(runs):
    cells = []
    for crowd in CROWDS:
        sample = [r for r in runs if r["scenario"]["family"] in ("crowd", "pick_pressure")
                  and r["scenario"]["crowd"] == crowd]
        ko_group = floor_split(balance.group_shares(sample, "loadout") if sample else {},
                               LIMITS["index_milli"], "loadout")
        # Survival per life = (alive ticks incl. each run's final censored life) / completed lives.
        alive = balance.group_shares(sample, "loadout") if sample else {}
        lives = defaultdict(int)
        for r in sample:
            for l in r["lives"]:
                if l.get("loadout"):
                    lives[l["loadout"]] += 1
        total_ticks = sum(a["ticks"] for k, a in alive.items() if lives.get(k))
        total_lives = sum(lives.values())
        survival = []
        for kit in sorted(lives):
            n, ticks = lives[kit], alive.get(kit, {"ticks": 0})["ticks"]
            ratio = ticks * total_lives * 1000 // (n * total_ticks) if total_ticks else None
            status = ("ungated" if n < LIMITS["P4_min_lives"] else
                      "exceeds" if ratio > LIMITS["P4_survival_milli"] else "within")
            survival.append({"loadout": kit, "completed_lives": n, "alive_ticks": ticks, "ratio_milli": ratio, "status": status})
        outliers = [minority(runs, crowd, b) for b in ("stack", "top72")] if crowd in HUNT_CROWDS else []
        gated = ([c for c in ko_group if c["status"] != "ungated"]
                 + [c for c in survival if c["status"] != "ungated"] + outliers)
        status = verdict(gated) if sample else "not measured"
        cells.append({"crowd": crowd, "ko_groups": ko_group, "survival": survival,
                      "cheapest_outliers": outliers, "status": status})
    return cells


def p5(runs):
    cells = []
    for crowd in HUNT_CROWDS:
        lives = [l for r in runs if r["scenario"]["family"] == "crowd" and r["scenario"]["build"] == "random"
                 and r["scenario"]["crowd"] == crowd for l in r["lives"]]
        cell = {"crowd": crowd, "lives": len(lives)}
        points = sorted(l["points"] for l in lives)
        if points:
            median = points[len(points) // 2]
            high = [l for l in lives if l["points"] > median]
            low = [l for l in lives if l["points"] <= median]
            cell.update(median_points=median, high_lives=len(high), low_lives=len(low))
            if min(len(high), len(low)) < LIMITS["P5_min_lives"] or not sum(l["ticks"] for l in high) or not sum(l["ticks"] for l in low):
                cell["status"] = "not measured"
            else:
                hk, ht = sum(l["kos"] for l in high), sum(l["ticks"] for l in high)
                lk, lt = sum(l["kos"] for l in low), sum(l["ticks"] for l in low)
                cell.update(high_kos=hk, high_ticks=ht, low_kos=lk, low_ticks=lt)
                cell["status"] = "within" if hk * lt > lk * ht else "exceeds"
        else:
            cell["status"] = "not measured"
        cells.append(cell)
    return cells


def p6(runs):
    crowd = [r for r in runs if r["scenario"]["family"] == "crowd"]
    lives = [l for r in crowd for l in r["lives"]]
    alive = balance.group_shares(crowd, "style") if crowd else {}
    rows = {}
    for style in sorted({l["style"] for l in lives}):
        sample = [l for l in lives if l["style"] == style]
        rows[style] = {"lives": len(sample), "ko_milli": balance.ratio(sum(x["kos"] for x in sample), len(sample)),
                       "survival_ticks_milli": balance.ratio(alive.get(style, {"ticks": 0})["ticks"], len(sample)),
                       "items_kept_milli": balance.ratio(sum(x["items_kept"] for x in sample), len(sample))}
    short = [s for s, r in rows.items() if r["lives"] < LIMITS["P6_min_lives"]]
    dominated = balance.style_dominance(rows)
    return {"styles": rows, "strictly_dominated": dominated, "under_floor": short,
            "status": "not measured" if short or not rows else "exceeds" if dominated else "within"}


def p7(runs):
    density = [r for r in runs if r["scenario"]["family"] == "density" and r["scenario"]["density"]
               and r["scenario"]["crowd"] in HUNT_CROWDS]
    cells = []
    for crowd in HUNT_CROWDS:
        for count in sorted({r["scenario"]["density"] for r in density if r["scenario"]["crowd"] == crowd}):
            arms = {on: [r for r in density if r["scenario"]["crowd"] == crowd and r["scenario"]["density"] == count
                         and r["scenario"]["bounty"] is on] for on in (True, False)}
            cell = {"crowd": crowd, "density": count}
            if not arms[True] or not arms[False]:
                cell.update(status="not measured", a_status="not measured", b_status="not measured")
                cells.append(cell)
                continue
            streak = max(r["max_hunted_streak"] for r in arms[True])
            held = {on: [l for r in arms[on] for l in r["lives"] if l["worn_legendary"]] for on in arms}
            extra = {on: sum(c["ticks"] for r in arms[on] for c in r.get("censored_lives", []) if c["worn_legendary"])
                     for on in arms}
            cell.update(max_streak=streak, runs_on=len(arms[True]), runs_off=len(arms[False]),
                        lives_on=len(held[True]), lives_off=len(held[False]),
                        a_status="exceeds" if streak > LIMITS["P7a_streak"] else "within")
            if min(len(held[True]), len(held[False])) < LIMITS["P7b_min_lives"]:
                cell["b_status"] = "not measured"
            else:
                on_mean = (sum(l["ticks"] for l in held[True]) + extra[True]) * 1000 // len(held[True])
                off_mean = (sum(l["ticks"] for l in held[False]) + extra[False]) * 1000 // len(held[False])
                cell.update(on_mean_ticks_milli=on_mean, off_mean_ticks_milli=off_mean,
                            ratio_milli=on_mean * 1000 // off_mean if off_mean else None)
                cell["b_status"] = ("within" if off_mean and on_mean * 1000 >= LIMITS["P7b_milli"] * off_mean
                                    else "exceeds")
            cell["status"] = verdict([{"status": cell["a_status"]}, {"status": cell["b_status"]}])
            cells.append(cell)
    expected = {(c, d) for c in HUNT_CROWDS for d in (4, 14, -(-c // 3))}
    seen = {(c["crowd"], c["density"]) for c in cells}
    return {"cells": cells, "missing_cells": sorted(expected - seen),
            "status": verdict(cells + ([{"status": "not measured"}] if expected - seen else []))}


def run_conditions(entry, variance, variant, base_hit_var=None):
    """The locked run conditions. Each failure is listed; any failure makes every field NOT MEASURED."""
    failed = []
    seeds = entry.get("seeds", [])
    if len(set(seeds)) < 10 or not set(range(1, 11)) <= set(seeds):
        failed.append("seeds must include 1-10 (got %s)" % seeds)
    if entry.get("ticks_per_run", 0) < 1200:
        failed.append("ticks per run must be at least 1200")
    if entry.get("density_ticks", 0) < 4800:
        failed.append("density ticks must be at least 4800")
    if entry.get("rules", {}).get("hitVarPct") != variance:
        failed.append("hitVarPct %r is not the variance %r under test" % (entry.get("rules", {}).get("hitVarPct"), variance))
    if base_hit_var is None:
        failed.append("the base rules table is unknown: the live version's own hitVarPct cannot be checked")
    elif base_hit_var != variance:
        failed.append("variance %r is not the live table's own hitVarPct %r" % (variance, base_hit_var))
    if not entry.get("rules", {}).get("bounty_weight"):
        failed.append("the bounty weight must be on")
    if variant != "baseline":
        failed.append("the gate runs the baseline variant (all knobs off) until Pat names his set")
    lifts = [c for c in entry.get("matrix", []) if c["family"] == "legendary_lift"]
    if not lifts or any(c["density"] != -(-c["crowd"] // 3) for c in lifts):
        failed.append("legendary_lift needs ceil(crowd/3) other legendary wearers")
    if not any(c["family"] == "minority" for c in entry.get("matrix", [])):
        failed.append("the matrix has no minority scenarios (the amended P4 lock)")
    return failed


def gate(report, variance, variant="baseline"):
    entry = report["variances"][str(variance)]
    result = entry["variants"][variant]
    runs = result["runs"]
    try:
        base_hit_var = replay.load_rules(report["base_rules_hash"])["hitVarPct"]
    except (KeyError, ValueError):
        base_hit_var = None
    failed = run_conditions(entry, variance, variant, base_hit_var)
    fields = {"P1": {"cells": p1(runs)}, "P2": {"cells": p2(runs)}, "P3": {"cells": p3(runs)},
              "P4": {"cells": p4(runs)}, "P5": {"cells": p5(runs)}, "P6": p6(runs), "P7": p7(runs)}
    for name in ("P1", "P2", "P3", "P4", "P5"):
        fields[name]["status"] = verdict(fields[name]["cells"])
    if failed:
        for field in fields.values():
            field["measured_status"], field["status"] = field["status"], "NOT MEASURED"
    return {"rules_hash": result["rules_hash"], "variance": variance, "variant": variant,
            "seeds": entry["seeds"], "limits": LIMITS, "run_conditions_failed": failed, "fields": fields,
            "p3_target_not_a_gate": p3_target(runs),
            "status": "awaiting the critic: the builder does not mark the bar passed"}


def table(result):
    lines = ["| Field | Status | Detail |", "|---|---|---|"]
    for name, field in result["fields"].items():
        cells = field.get("cells", [])
        counts = defaultdict(int)
        for c in cells:
            counts[c["status"]] += 1
        if "strictly_dominated" in field:
            detail = "%d strictly dominated, under floor %s" % (len(field["strictly_dominated"]), field["under_floor"])
        else:
            detail = ", ".join("%d %s" % (n, s) for s, n in sorted(counts.items())) or "no cells"
            if field.get("missing_cells"):
                detail += "; missing cells %s" % field["missing_cells"]
        lines.append("| %s | %s | %s |" % (name, field["status"], detail))
    return "\n".join(lines)


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", type=Path)
    parser.add_argument("--variance", type=int, default=20)
    parser.add_argument("--variant", default="baseline")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = gate(json.loads(args.report.read_text()), args.variance, args.variant)
    if args.output:
        args.output.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(table(result))
    print(result["status"])


if __name__ == "__main__":
    main(sys.argv[1:])
