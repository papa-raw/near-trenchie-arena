"""Compact measured outcomes, with explicit missing data and no certification."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent))


def over_limit(values: list, limit: int) -> dict:
    observed = [x for x in values if x is not None]
    return {"observed": len(observed), "missing": len(values) - len(observed),
            "exceedances": sum(x > limit for x in observed), "worst": max(observed, default=None)}


def base_rates(lives: list[dict]) -> dict:
    """The zero bin stays independent of the conditional four-bin stake spread."""
    bins = [0] * 5
    for life in lives:
        bins[min(4, life["kos"])] += 1
    spread = None
    if lives:
        spread = [n * 10000 // len(lives) for n in bins]
        # Distribute only rounding residue; never discard or condition away zero.
        for i in range(10000 - sum(spread)):
            spread[i % len(spread)] += 1
    return {"lives": len(lives), "bins": bins, "spread_bps": spread,
            "mean_life_ticks_milli": sum(l["ticks"] for l in lives) * 1000 // len(lives) if lives else None,
            "mean_kos_milli": sum(l["kos"] for l in lives) * 1000 // len(lives) if lives else None}


def rps_numerator(spread: list[int], actual: int) -> int:
    """Five-bin ranked score, represented over the exact denominator 400,000,000."""
    if len(spread) != 5 or sum(spread) != 10000 or any(type(x) is not int or x < 0 for x in spread):
        raise ValueError("five nonnegative bins must total 10000")
    if type(actual) is not int or actual < 0:
        raise ValueError("actual KOs must be nonnegative")
    cumulative, score = 0, 0
    for i in range(4):
        cumulative += spread[i]
        score += (cumulative - (10000 if min(actual, 4) <= i else 0)) ** 2
    return score


def counterfactual_readout(rows: list[dict]) -> dict:
    """Diagnostic attacker calls, never production, signed or model-generated calls."""
    result = {}
    for name in sorted({r["fighter"] for r in rows}):
        calls = [r for r in rows if r["fighter"] == name]
        spread = base_rates([{"kos": r["actual"], "ticks": 0} for r in calls])["spread_bps"]
        ai_score = sum(rps_numerator(r["forecast_bps"], r["actual"]) for r in calls)
        own_score = sum(rps_numerator(spread, r["actual"]) for r in calls)
        # The empirical own-base comparison is descriptive; real trailing logs remain separate.
        skill = None
        if len(calls) >= 10:
            skill = (own_score - ai_score) * 1000 // own_score if own_score else (0 if ai_score == 0 else None)
        result[name] = {"lives": len(calls), "own_skill_milli": skill,
                        "comparison": "empirical own base, counterfactual only"}
    return result


def abuse_diagnostics(runs: list[dict], base: list[int] | None) -> dict:
    rows = []
    for run in runs:
        family = run["scenario"]["family"]
        if family not in ("stop_at_one", "shared_owner"):
            continue
        completed = [{"fighter": l["fighter"], "actual": l["kos"]} for l in run["lives"]]
        if family == "stop_at_one" and run["escapes"]:
            dead_kos = sum(l["kos"] for l in run["lives"] if l["fighter"] == "p00")
            total_kos = run["shares"]["fighter"].get("p00", {}).get("kos", 0)
            completed.append({"fighter": "p00", "actual": total_kos - dead_kos})
        for life in completed:
            actual, forecast = life["actual"], [0, 10000, 0, 0, 0]
            multiplier = None if base is None else 0 if actual == 0 else (
                1000 + (rps_numerator(base, actual) - rps_numerator(forecast, actual)) * 1000 // 400000000)
            rows.append({**life, "case": run["case"], "seed": run["seed"], "family": family,
                         "owner_group": run["owner_groups"].get(life["fighter"]), "forecast_bps": forecast,
                         "counterfactual_return_milli": multiplier, "origin": "synthetic attacker policy"})
    return {"rows": rows, "readout": counterfactual_readout(rows),
            "status": "diagnostic only; production trailing prediction log and settlement not exercised"}


def move_limits(fields: dict) -> dict:
    result = {}
    for crowd, rows in fields["move_parity"]["crowds"].items():
        result[crowd] = {kind: over_limit([r["index_milli"] for r in rows[kind].values()], 2000)
                         for kind in ("weapon", "signature")}
    return result


def mirrored_duels(fields: dict) -> dict:
    """Keep every pair and its decisive denominator, including all-draw cells."""
    parity = fields["move_parity"]
    low, high = parity["duel_target_bps"]
    pairs = {}
    for key, row in parity["duels"].items():
        rate = row["left_rate_bps"]
        pairs[key] = {**row, "decisive_runs": row["left_wins"] + row["right_wins"],
                      "target_status": "unmeasured" if rate is None else
                          "within" if low <= rate <= high else "outside"}
    return {"pairs": pairs, "target_bps": [low, high],
            "target_is_gate": parity["duel_target_is_gate"]}


def build_rates(runs: list[dict]) -> dict:
    totals = {}
    for run in runs:
        for life in run["lives"]:
            row = totals.setdefault(str(life["points"]), {"lives": 0, "kos": 0, "ticks": 0})
            row["lives"] += 1
            row["kos"] += life["kos"]
            row["ticks"] += life["ticks"]
    for row in totals.values():
        row["kos_per_live_hour_milli"] = row["kos"] * 72000000 // row["ticks"] if row["ticks"] else None
    return totals


def population_survival(runs: list[dict], rules: dict) -> dict:
    """Report fixed starting-kit cohorts as well as the live time-in-hand index."""
    try:
        from . import balance, sim
    except ImportError:
        import balance
        import sim
    result = {}
    for crowd in (2, 6, 10, 16):
        exposure, population, total_ticks, total_people = Counter(), Counter(), 0, 0
        for run in runs:
            if run["scenario"]["family"] != "crowd" or run["scenario"]["crowd"] != crowd:
                continue
            players = balance.roster(balance.Scenario(**run["scenario"]), rules, run["seed"])
            for player in players:
                key = sim.digest(player["loadout"])[:16]
                population[key] += 1
                exposure[key] += run["survival_ticks"].get(player["name"], 0)
                total_people += 1
            total_ticks += sum(run["survival_ticks"].values())
        result[str(crowd)] = {key: {"starting_bodies": population[key], "alive_ticks": exposure[key],
                                    "index_milli": exposure[key] * total_people * 1000 // (total_ticks * population[key])
                                    if total_ticks else None} for key in sorted(population)}
    return result


def matched_styles(runs: list[dict], styles: list[str]) -> dict:
    """Use the same builds/crowds for each style; exclude the separate duel mix."""
    try:
        from . import balance
    except ImportError:
        import balance
    lives = [life for run in runs if run["scenario"]["family"] == "crowd" for life in run["lives"]]
    rows = {}
    for style in styles:
        sample = [l for l in lives if l["style"] == style]
        if sample:
            rows[style] = {"lives": len(sample), "ko_milli": sum(l["kos"] for l in sample) * 1000 // len(sample),
                           "survival_ticks_milli": sum(l["ticks"] for l in sample) * 1000 // len(sample),
                           "items_kept_milli": sum(l["items_kept"] for l in sample) * 1000 // len(sample)}
    return {"outcomes": rows, "strictly_dominated": balance.style_dominance(rows),
            "missing_styles": [style for style in sorted(styles) if style not in rows]}


def summarize_variant(variant: dict, rules: dict) -> dict:
    try:
        from .balance import set_pieces
    except ImportError:
        from balance import set_pieces
    fields, runs = variant["fields"], variant["runs"]
    life_rows = [life for run in runs for life in run["lives"]]
    hunted = fields["hunted_loop"]
    ratios = [row["survival_ratio_milli"] for row in hunted["survival_pairs"]]
    escape = [r for r in runs if r["scenario"]["family"] == "escape"]
    base = base_rates(life_rows)
    return {
        "observed_kos": variant["observed_kos"],
        "legendary_lift": over_limit([r["lift_milli"] for r in fields["legendary_lift"]["matched_rates"]], 1500),
        "rares_newcomers": {"rates": set_pieces(runs),
                             "definition": "First rare life defeats all distinct newcomers before dying; surviving winners count, unresolved runs remain censored."},
        "move_indices": move_limits(fields),
        "mirrored_duels": mirrored_duels(fields),
        "loadout_ko_indices": {n: over_limit([r["index_milli"] for r in rows.values()], 2000)
                               for n, rows in fields["loadout_parity"]["crowds"].items()},
        "starting_loadout_survival": population_survival(runs, rules),
        "build_rates": build_rates(runs), "styles": matched_styles(runs, sorted(rules["styles"])),
        "hunted_loop": {"max_consecutive": hunted["max_consecutive"], "limit": 3,
                        "observed_pairs": sum(x is not None for x in ratios),
                        "missing_pairs": sum(x is None for x in ratios),
                        "below_half_survival": sum(x is not None and x < 500 for x in ratios),
                        "worst_survival_milli": min((x for x in ratios if x is not None), default=None)},
        "base_rates": {**base, "population": "experimental scenario mixture"},
        "abuse_diagnostics": abuse_diagnostics(runs, base["spread_bps"]),
        "right_censored": sum(r["right_censored"] for r in runs),
        "escape_attempts": sum(r["escape_attempts"] for r in escape),
        "escapes": sum(r["escapes"] for r in escape), "status": "awaiting independent review"}


def summarize(report: dict) -> dict:
    return {"base_rules_hash": report["base_rules_hash"], "status": "awaiting independent review",
            "variances": {v: {name: summarize_variant(data, result["rules"])
                              for name, data in result["variants"].items()}
                          for v, result in report["variances"].items()},
            "limits": ["Single-seed cells are observations, not a statistical balance certification.",
                       "Survival cohorts use starting kits; actual worn-kit KO indices use time in hand.",
                       "Rares set pieces use first-life outcomes: surviving winners count and unresolved runs remain censored.",
                       "Prediction-log scoring, stake settlement and deployed-load evidence remain external."]}


def markdown(summary: dict) -> str:
    lines = ["Measured engine outcomes; independent balance review pending.", "",
             "Each row includes all seven fields in the JSON. Counts below are observed exceedances, not verdicts.", "",
             "| Variance | Control | KOs | Lift >1.5x | Rare beats 1 / loses to 2 (bps) | Moves >2x | Kit KO/survival >2x | Styles dominated | Hunt streak | Hunt <half | Missing lift/pairs |",
             "|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|"]
    for variance, variants in summary["variances"].items():
        for name, row in variants.items():
            moves = sum(x["exceedances"] for crowd in row["move_indices"].values() for x in crowd.values())
            kits = sum(x["exceedances"] for x in row["loadout_ko_indices"].values())
            survival = sum(x["index_milli"] is not None and x["index_milli"] > 2000
                           for crowd in row["starting_loadout_survival"].values() for x in crowd.values())
            hunt, lift = row["hunted_loop"], row["legendary_lift"]
            rates = row["rares_newcomers"]["rates"]
            one = rates.get("2", {}).get("rare_win_bps")
            two = rates.get("3", {}).get("newcomer_win_bps")
            dominated = len(row["styles"]["strictly_dominated"])
            rates_text = str(one) if one is not None else "missing"
            rates_text += "/" + (str(two) if two is not None else "missing")
            lines.append(f"| {variance} | {name} | {row['observed_kos']} | {lift['exceedances']} | {rates_text} | {moves} | {kits}/{survival} | {dominated} | {hunt['max_consecutive']} | {hunt['below_half_survival']} | {lift['missing']}/{hunt['missing_pairs']} |")
    lines.extend(["", "Read denominators, complete style/build/set-piece results, missing cells and limits in the JSON.",
                  "A 60% mirrored-duel rate is a target; every pair retains its distinct-outcome count.",
                  "The stronger-build signal is the rare-vs-default 1v1 rate; complete point-stratified rates are in JSON.",
                  "No control is enabled by this report."])
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--json", type=Path, required=True)
    parser.add_argument("--markdown", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = summarize(json.loads(args.report.read_bytes()))
        args.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        args.markdown.write_text(markdown(result))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, "summary refused: " + str(exc) + "\n")
