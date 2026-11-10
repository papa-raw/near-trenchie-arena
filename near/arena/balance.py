"""Deterministic measurements on the real engine. Reports never certify balance."""

import argparse
import ast
from collections import Counter, defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass, asdict
from itertools import combinations
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from . import sim, replay
except ImportError:
    import sim
    import replay


PRESETS = (("brawler", "swing", "shockwave"), ("hunter", "lunge", "blink_strike"),
           ("survivor", "beam", "bubble"), ("looter", "lob", "magnet"),
           ("brawler", "zap", "chain_storm"))
CROWDS = (2, 6, 10, 16)
VARIANCES = (10, 15, 20, 25, 30)


@dataclass(frozen=True)
class Scenario:
    family: str
    crowd: int = 6
    style: str = "brawler"
    build: str = "default"
    left: str = ""
    right: str = ""
    density: int = 0
    bounty: bool = True
    loot_seconds: int = 10
    mirror: bool = False

    @property
    def key(self) -> str:
        return sim.digest(asdict(self))[:16]


def scenarios(rules: Mapping) -> list[Scenario]:
    """The same declared matrix is measured for baseline and each single control."""
    result = [Scenario("stack", build="stack")]
    styles = sorted(rules["styles"])
    for crowd in CROWDS:
        for build in ("default", "random", "mean52", "top72", "saver", "presets"):
            result.extend(Scenario("crowd", crowd, style, build) for style in styles)
        result.extend(Scenario("pick_pressure", crowd, style, "top72") for style in styles)
    for family, kinds in (("weapon_duel", sorted(rules["weapons"])),
                          ("signature_duel", sorted(k for k in rules["signatures"] if k != "dodge_roll")),
                          ("preset_duel", [str(i) for i in range(len(PRESETS))])):
        for left, right in combinations(kinds, 2):
            for mirror in (False, True):
                result.append(Scenario(family, 2, left=left, right=right, mirror=mirror))
    for crowd in (2, 3):
        for style in styles:
            for mirror in (False, True):
                result.append(Scenario("rares_newcomers", crowd, style, "rares", mirror=mirror))
    for row in sorted(rules["items"]):
        if rules["items"][row]["tier"] == "legendary":
            for style in styles:
                for arm in ("legendary", "rare"):
                    result.append(Scenario("legendary_lift", 6, style, "rares", left=row, right=arm))
    for crowd in (6, 10, 16):
        for density in (0, 4, 14, (crowd + 2) // 3):
            for bounty in (False, True):
                result.append(Scenario("density", crowd, build="mean52", density=density, bounty=bounty))
    for seconds in (0, 20, 10, 5):
        for left, right in combinations(sorted(rules["weapons"]), 2):
            result.append(Scenario("loot_duel", 2, left=left, right=right, loot_seconds=seconds))
        result.append(Scenario("loot_crowd", 16, build="mean52", loot_seconds=seconds))
    result.extend(Scenario(f, 6, build="mean52") for f in ("escape", "stop_at_one", "shared_owner"))
    return list(dict.fromkeys(result))


def kit(rules: Mapping, rng: sim.SplitMix64, build: str, weapon: str | None = None,
        signature: str | None = None) -> dict:
    """Pick legal catalog rows: 52 points means exactly two rares and two defaults."""
    chosen = {}
    for index, slot in enumerate(("head", "body", "weapon", "trinket")):
        tier = "rare" if build in ("rares", "top72", "stack") or build == "mean52" and index < 2 else "common"
        if slot == "trinket" and build in ("top72", "stack"):
            tier = "legendary"
        if build == "random":
            tier = ("common", "rare")[rng.draw() % 2]
        rows = [row for row in sorted(rules["items"]) if rules["items"][row]["slot"] == slot
                and rules["items"][row]["tier"] == tier and
                (tier != "common" or rules["items"][row]["default"])]
        field, kind = ("weapon", weapon) if slot == "weapon" else ("signature", signature)
        if slot in ("weapon", "trinket") and kind is not None:
            rows = [row for row in rows if rules["items"][row][field] == kind]
        if not rows:
            raise ValueError("no legal row for requested build and move")
        chosen[slot] = (max(rows, key=lambda row: (rules["items"][row]["stats"]["damage"], row))
                        if build == "stack" else rows[rng.draw() % len(rows)])
    return chosen


def roster(case: Scenario, rules: Mapping, seed: int) -> list[dict]:
    rng = sim.SplitMix64(seed, rules)
    size = case.crowd
    names = ["p" + str(i).zfill(2) for i in range(size)]
    if case.family == "density":
        houses = sorted(rules["house"])
        offset = seed % len(houses)
        houses = houses[offset:] + houses[:offset]
        names = houses[:size - 2] + ["visitor-a", "visitor-b"]
    elif case.family == "legendary_lift":
        names[0], names[1] = rules["items"][case.left]["house"], "holder"
    result = []
    for i, name in enumerate(names):
        style, weapon, signature = case.style, None, None
        build = case.build
        if case.family in ("weapon_duel", "loot_duel"):
            weapon = case.left if i == 0 else case.right
        elif case.family == "signature_duel":
            weapon, signature = "swing", case.left if i == 0 else case.right
        elif case.family == "preset_duel" or build == "presets":
            p = int(case.left if i == 0 else case.right) if case.family == "preset_duel" else i % len(PRESETS)
            style, weapon, signature = PRESETS[p]
            build = "default"
        if case.family == "rares_newcomers" and i:
            build = "default"
        if case.family == "pick_pressure" and i == size - 1:
            build = "mean52"
        if case.family == "legendary_lift" and i == 1:
            signature = rules["items"][case.left]["signature"]
        loadout = kit(rules, rng, build, weapon, signature)
        if case.family == "legendary_lift" and i == 1 and case.right == "legendary":
            loadout["trinket"] = case.left
        if case.family == "legendary_lift" and i == 2:
            loadout["trinket"] = next(row for row in sorted(rules["items"])
                                       if rules["items"][row]["tier"] == "legendary" and row != case.left)
        if case.family == "density":
            style = rules["house"].get(name, {}).get("style", case.style)
        bag = {row: {"serial": 0, "born_batch": 0, "kos": 0, "hands": 0, "flags": 0}
               for row in loadout.values() if not rules["items"][row]["default"]}
        if build == "saver":
            for row in kit(rules, rng, "top72").values():
                if not rules["items"][row]["default"]:
                    bag[row] = {"serial": 0, "born_batch": 0, "kos": 0, "hands": 0, "flags": 0}
        result.append({"name": name, "style": style, "loadout": loadout, "bag": bag,
                       "house": (case.family == "density" and name in rules["house"] or
                                 case.family == "legendary_lift" and i == 0)})
    if case.family == "density":
        present = [rules["house"][name]["legendary"] for name in names if name in rules["house"]]
        legends = present + [row for row in sorted(rules["items"]) if rules["items"][row]["tier"] == "legendary" and row not in present]
        for i, row in enumerate(legends[:case.density]):
            holder = result[(i + 1) % len(result)] if i < len(result) else result[-1]
            holder["bag"][row] = {"serial": 0, "born_batch": 0, "kos": 0, "hands": 0, "flags": 0}
            if i < len(result):
                holder["loadout"]["trinket"] = row
    return result


def ratio(numerator: int, denominator: int, scale: int = 1000) -> int | None:
    return numerator * scale // denominator if denominator else None


def shares(exposure: Counter, outcomes: Counter) -> dict:
    total_time, total_outcomes = sum(exposure.values()), sum(outcomes.values())
    return {key: {"ticks": exposure[key], "kos": outcomes[key],
                  "index_milli": ratio(outcomes[key] * total_time, total_outcomes * exposure[key])}
            for key in sorted(exposure)}


class Measure:
    def __init__(self, game: sim.Sim):
        self.game = game
        self.exposure = {key: Counter() for key in ("weapon", "signature", "loadout", "style", "fighter")}
        self.kos = {key: Counter() for key in self.exposure}
        self.damage = Counter()
        self.starts = {}
        self.label_cache = {}
        self.lives = []
        self.streak, self.max_streak = Counter(), Counter()
        self.grabs, self.losses = 0, 0
        self.escapes, self.escape_attempts = 0, 0

    def labels(self, f: dict) -> dict:
        items = self.game.rules["items"]
        key = (f["id"], f["style"], tuple(sorted(f["equipped"].items())))
        if key not in self.label_cache:
            self.label_cache[key] = {"weapon": items[f["equipped"]["weapon"]]["weapon"],
                "signature": items[f["equipped"]["trinket"]]["signature"],
                "loadout": sim.digest(f["equipped"])[:16], "style": f["style"], "fighter": f["id"]}
        return self.label_cache[key]

    def before(self) -> dict:
        before = {}
        for name in self.game._live():
            f = self.game.state["fighters"][name]
            self.starts.setdefault(name, self.game.state["tick"])
            labels = self.labels(f)
            for kind, label in labels.items():
                self.exposure[kind][label] += 1
            before[name] = {"labels": labels, "equipped": dict(f["equipped"]), "kos": f["life_kos"], "life_id": f["life_id"],
                            "points": sum(sum(self.game.rules["items"][row]["stats"].values()) for row in f["equipped"].values())}
        return before

    def after(self, before: dict) -> None:
        for event in self.game.state["events"]:
            kind = event["kind"]
            if kind == "ko":
                self._life(event, before)
            elif kind == "hit":
                self.damage[event.get("move") or "other"] += event["damage"]
            elif kind == "grab":
                self.grabs += 1
            elif kind == "floor_loss":
                self.losses += 1
            elif kind == "leave":
                self.escapes += 1

    def _life(self, event: dict, before: dict) -> None:
        name, source = event["fighter"], event["source"]
        f = self.game.state["fighters"][name]
        for kind, label in before.get(source, {}).get("labels", {}).items():
            self.kos[kind][label] += 1
        equipped = before.get(name, {}).get("equipped", {})
        hunters = [self.game.rules["items"][row]["house"] for row in equipped.values()
                   if self.game.rules["items"][row]["tier"] == "legendary"]
        self.streak[name] = self.streak[name] + 1 if source in hunters else 0
        self.max_streak[name] = max(self.max_streak[name], self.streak[name])
        self.lives.append({"fighter": name, "source": source, "life_id": event["life_id"],
                           "source_life_id": before.get(source, {}).get("life_id"), "hunter": source in hunters,
                           "worn_legendary": bool(hunters), "kos": event["life_kos"],
                           "ticks": self.game.state["tick"] - self.starts.pop(name, 0),
                           "style": f["style"], "items_kept": len(f["bag"]),
                           "points": before.get(name, {}).get("points", 0)})

    def result(self) -> dict:
        return {"shares": {key: shares(self.exposure[key], self.kos[key]) for key in self.exposure},
                "survival_ticks": dict(self.exposure["fighter"]), "damage": dict(self.damage),
                "lives": self.lives, "max_hunted_streak": max(self.max_streak.values(), default=0),
                "grabs": self.grabs, "floor_losses": self.losses,
                "escape_attempts": self.escape_attempts, "escapes": self.escapes}


def choose_kit(game: sim.Sim, f: dict, saver: bool) -> dict:
    if saver or f["house"]:
        return dict(f["kit"])
    result = {}
    for slot in sorted(f["kit"]):
        choices = [row for row in sorted(game.rules["items"]) if game.rules["items"][row]["slot"] == slot
                   and (game.rules["items"][row]["default"] or row in f["bag"])]
        result[slot] = max(choices, key=lambda row: (sum(game.rules["items"][row]["stats"].values()), row))
    return result


def run_match(case: Scenario, rules: Mapping, seed: int, ticks: int) -> dict:
    """Drive managed lives with logged bench picks; no model or stake is invented."""
    mutable = sim.rules_dict(rules)
    mutable["bounty_weight"] = mutable["bounty_weight"] if case.bounty else 0
    mutable["loot_interval"] = case.loot_seconds * mutable["tick_hz"] if case.loot_seconds else ticks + 1
    game = sim.Sim(seed, mutable)
    players = roster(case, game.rules, seed)
    ring = min(case.crowd, game.rules["ring_max"])
    sequence = 0
    for i, player in enumerate(players):
        payload = {k: player[k] for k in ("style", "house", "loadout", "bag")}
        angle = (i * 360 // len(players) + seed % 360) % 360
        if len(players) == 2:
            angle = (seed % 360 + (60 if bool(i) != case.mirror else 0)) % 360
        payload.update(angle=angle, managed=True, waiting=i >= ring)
        game.enqueue(sim.Input(0, "join", player["name"], sequence, payload))
        sequence += 1
    waiting, queued = deque(), set()
    measure = Measure(game)
    for _ in range(ticks):
        fighters = game.state["fighters"]
        for name in sorted(fighters):
            f = fighters[name]
            if f["state"] == "bench" and name not in queued:
                waiting.append(name)
                queued.add(name)
        if waiting and len(game._live()) < ring:
            name = waiting[0]
            f = fighters[name]
            if game.state["tick"] >= f["respawn_at"] or len(game._live()) < min(ring, game.rules["ring_min"]):
                waiting.popleft()
                queued.remove(name)
                fixed = case.build in ("saver", "presets") or case.family in ("weapon_duel", "signature_duel", "preset_duel")
                chosen = choose_kit(game, f, fixed)
                game.enqueue(sim.Input(game.state["tick"], "loadout", name, sequence, chosen))
                game.enqueue(sim.Input(game.state["tick"], "spawn", name, sequence + 1,
                                       {"life_id": name + ":" + str(f["life_number"] + 1)}))
                sequence += 2
        before = measure.before()
        if game.state["tick"] == game.rules["intent_interval"] and case.family in ("shared_owner", "rares_newcomers"):
            for player in players[1:]:
                game.enqueue(sim.Input(game.state["tick"], "intent", player["name"], sequence,
                                       {"focus": players[0]["name"], "loot": "ignore"}))
                sequence += 1
        if case.family in ("escape", "stop_at_one"):
            name = players[0]["name"]
            f = fighters.get(name)
            if f is not None and f["state"] == "alive" and not f["leave"] and (case.family == "escape" or f["life_kos"] >= 1):
                game.enqueue(sim.Input(game.state["tick"], "leave", name, sequence, {}))
                sequence += 1
                measure.escape_attempts += 1
        game.step()
        measure.after(before)
    data = measure.result()
    data.update(seed=seed, rules_hash=game.rules_hash, final_state_hash=game.state_hash(),
                scenario=asdict(case), case=case.key, active_ring_limit=ring,
                admitted=len(players), right_censored=len(measure.starts),
                owner_groups={p["name"]: "one-owner" if case.family == "shared_owner" and i < 2 else p["name"]
                              for i, p in enumerate(players)})
    return data


def group_shares(runs: list[dict], label: str) -> dict:
    exposure, outcomes = Counter(), Counter()
    for run in runs:
        for key, row in run["shares"][label].items():
            exposure[key] += row["ticks"]
            outcomes[key] += row["kos"]
    return shares(exposure, outcomes)


def outcome_count(runs: list[dict]) -> int:
    return sum(sum(row["kos"] for row in run["shares"]["fighter"].values()) for run in runs)


def hunted_pairs(runs: list[dict]) -> list[dict]:
    pairs = defaultdict(dict)
    for run in runs:
        case = run["scenario"]
        if case["family"] == "density":
            pairs[(case["crowd"], case["density"], run["seed"])][case["bounty"]] = run
    rows = []
    for (crowd, density, seed), arms in sorted(pairs.items()):
        if not all(on in arms for on in (False, True)):
            continue
        names = sorted({life["fighter"] for run in arms.values() for life in run["lives"] if life["worn_legendary"]})
        for name in names:
            off, on = ([l["ticks"] for l in arms[arm]["lives"] if l["fighter"] == name and l["worn_legendary"]]
                       for arm in (False, True))
            rows.append({"crowd": crowd, "density": density, "seed": seed, "holder": name,
                         "on_lives": len(on), "off_lives": len(off),
                         "survival_ratio_milli": ratio(sum(on) * len(off), sum(off) * len(on))})
    return rows


def legendary_pairs(runs: list[dict]) -> list[dict]:
    pairs = defaultdict(dict)
    for run in runs:
        c = run["scenario"]
        if c["family"] == "legendary_lift":
            pairs[(c["left"], c["style"], run["seed"])][c["right"]] = run
    result = []
    for (item, style, seed), arms in sorted(pairs.items()):
        if "rare" in arms and "legendary" in arms:
            a, b = (arms[arm]["shares"]["fighter"].get("holder", {"kos": 0, "ticks": 0}) for arm in ("legendary", "rare"))
            result.append({"item": item, "style": style, "seed": seed,
                           "legendary_kos": a["kos"], "rare_kos": b["kos"],
                           "lift_milli": ratio(a["kos"] * b["ticks"], b["kos"] * a["ticks"])})
    return result


def set_pieces(runs: list[dict]) -> dict:
    groups = defaultdict(list)
    missing = Counter()
    for run in runs:
        if run["scenario"]["family"] == "rares_newcomers":
            n = run["scenario"]["crowd"]
            first_death = next((i for i, life in enumerate(run["lives"]) if life["fighter"] == "p00"), None)
            prior = run["lives"] if first_death is None else run["lives"][:first_death]
            if any(not all(k in life for k in ("source", "life_id", "source_life_id")) for life in run["lives"]):
                missing[n] += 1
                groups[n].append(None)
                continue
            newcomers = {"p" + str(i).zfill(2) for i in range(1, n)}
            victims = {life["fighter"] for life in prior if life["source"] == "p00"
                       and life["source_life_id"] == "p00:0" and life["fighter"] in newcomers}
            won = victims == newcomers
            groups[n].append(True if won else False if first_death is not None else None)
    result = {}
    for n, outcomes in sorted(groups.items()):
        resolved = [x for x in outcomes if x is not None]
        result[str(n)] = {"runs": len(outcomes), "resolved_runs": len(resolved),
                          "evidence_missing_runs": missing[n],
                          "censored_runs": len(outcomes) - len(resolved),
                          "rare_win_bps": ratio(sum(resolved), len(resolved), 10000),
                          "newcomer_win_bps": ratio(sum(not x for x in resolved), len(resolved), 10000)}
    return result


def style_dominance(rows: dict) -> list[dict]:
    keys = ("ko_milli", "survival_ticks_milli", "items_kept_milli")
    return [{"style": a, "dominated_by": b} for a in sorted(rows) for b in sorted(rows) if a != b
            and all(rows[a][k] is not None and rows[b][k] is not None and rows[a][k] < rows[b][k] for k in keys)]


def bar_fields(runs: list[dict]) -> dict:
    """Print every field with observations and denominators; missing evidence stays missing."""
    crowd_rows = {}
    for crowd in CROWDS:
        sample = [r for r in runs if r["scenario"]["crowd"] == crowd and r["scenario"]["family"] == "crowd"]
        crowd_rows[str(crowd)] = {k: group_shares(sample, k) for k in ("weapon", "signature", "loadout")}
    duels = defaultdict(list)
    for run in runs:
        if run["scenario"]["family"] in ("weapon_duel", "signature_duel", "preset_duel", "loot_duel"):
            case = run["scenario"]
            duels["/".join((case["family"], case["left"], case["right"], str(case["loot_seconds"])))].append(run)
    duel_rows = {}
    for key, sample in sorted(duels.items()):
        outcomes = [tuple(row["kos"] for _, row in sorted(r["shares"]["fighter"].items())) for r in sample]
        left = sum(a > b for a, b in outcomes)
        right = sum(b > a for a, b in outcomes)
        duel_rows[key] = {"left_wins": left, "right_wins": right, "draws": len(sample) - left - right,
                          "left_rate_bps": ratio(left, left + right, 10000),
                          "distinct_outcomes": len(set(outcomes)), "runs": len(sample)}
    lives = [life for run in runs for life in run["lives"]]
    style_rows = {}
    for style in sorted({life["style"] for life in lives}):
        sample = [life for life in lives if life["style"] == style]
        style_rows[style] = {"lives": len(sample), "ko_milli": ratio(sum(x["kos"] for x in sample), len(sample)),
                             "survival_ticks_milli": ratio(sum(x["ticks"] for x in sample), len(sample)),
                             "items_kept_milli": ratio(sum(x["items_kept"] for x in sample), len(sample))}
    density = [r for r in runs if r["scenario"]["family"] == "density"]
    fields = {
        "legendary_lift": {"matched_rates": legendary_pairs(runs), "density_pairs": [{"case": r["case"], "seed": r["seed"], "density": r["scenario"]["density"],
            "crowd": r["scenario"]["crowd"], "bounty": r["scenario"]["bounty"], "holders": r["shares"]["fighter"],
            "lives": r["lives"]} for r in density], "limit_milli": 1500},
        "rares_newcomers": {"rates": set_pieces(runs),
                             "definition": "First rare life: defeat all distinct newcomers before dying; surviving winners count, unresolved runs stay censored."},
        "move_parity": {"crowds": crowd_rows, "duels": duel_rows, "crowd_limit_milli": 2000,
                        "duel_target_bps": [4000, 6000], "duel_target_is_gate": False},
        "loadout_parity": {"crowds": {n: x["loadout"] for n, x in crowd_rows.items()}, "limit_milli": 2000,
                           "survival": [{"case": r["case"], "seed": r["seed"], "ticks": r["survival_ticks"]} for r in runs]},
        "build_strength": {"by_points": {str(points): {"lives": len(sample), "kos": sum(l["kos"] for l in sample)}
            for points in sorted({l["points"] for l in lives})
            for sample in [[l for l in lives if l["points"] == points]]}},
        "style_parity": {"outcomes": style_rows, "strictly_dominated": style_dominance(style_rows)},
        "hunted_loop": {"max_consecutive": max((r["max_hunted_streak"] for r in density), default=0),
                        "limit": 3, "survival_floor_milli": 500, "paired_runs": len(density),
                        "survival_pairs": hunted_pairs(runs)},
    }
    return fields


def measure_cached(args: tuple) -> dict:
    case, rules, seed, ticks, checkpoint, source_hash = args
    key = sim.digest([asdict(case), sim.digest(rules), seed, ticks, source_hash])
    path = None if checkpoint is None else Path(checkpoint) / (key + ".json")
    if path is not None and path.exists():
        cached = json.loads(path.read_bytes())
        if cached["checksum"] != sim.digest(cached["run"]):
            raise ValueError("corrupt measurement checkpoint; remove " + str(path))
        return cached["run"]
    run = run_match(case, rules, seed, ticks)
    if path is not None:
        temporary = path.with_suffix("." + str(os.getpid()) + ".tmp")
        temporary.write_bytes(sim.canonical({"checksum": sim.digest(run), "run": run}))
        temporary.replace(path)
    return run


def checkpoint_hash(previous_source: Path | None = None) -> str:
    """Reuse scheduling-only revisions after comparing every measurement dependency."""
    return _checkpoint_state(previous_source)[0]


def _checkpoint_state(previous_source: Path | None = None) -> tuple[str, tuple[str, ...]]:
    current = Path(__file__).read_bytes()
    previous = current if previous_source is None else previous_source.read_bytes()
    names = {"Scenario", "scenarios", "kit", "roster", "ratio", "shares", "Measure", "choose_kit",
             "run_match", "measure_cached", "PRESETS", "CROWDS", "VARIANCES"}
    leave_test = ast.dump(ast.parse("case.family in ('escape', 'stop_at_one')", mode="eval").body)
    class LeavePolicy(ast.NodeTransformer):
        def visit_If(self, node):
            if ast.dump(node.test) == leave_test:
                node.body = [ast.Pass()]
                return node
            return self.generic_visit(node)
    def definitions(source: bytes, normalize_leave: bool = False) -> dict:
        nodes = {}
        for node in ast.parse(source).body:
            if isinstance(node, ast.Assign):
                name = node.targets[0].id if isinstance(node.targets[0], ast.Name) else None
            else:
                name = getattr(node, "name", None)
            if name in names:
                if name == "run_match" and normalize_leave:
                    node = LeavePolicy().visit(node)
                nodes[name] = ast.dump(node)
        return nodes
    invalidated = ()
    if definitions(current) != definitions(previous):
        if definitions(current, True) != definitions(previous, True):
            raise ValueError("measurement code changed; use a fresh checkpoint directory")
        invalidated = ("escape", "stop_at_one")
    return hashlib.sha256(previous + Path(sim.__file__).read_bytes()).hexdigest(), invalidated


def report(rules: Mapping, seeds: list[int], ticks: int, matrix: list[Scenario] | None = None,
           progress: bool = False, checkpoint: Path | None = None, workers: int = 1,
           controls: list[str] | None = None, previous_source: Path | None = None,
           density_ticks: int | None = None) -> dict:
    matrix = scenarios(rules) if matrix is None else matrix
    variants = ["baseline"] + sorted(rules["knobs"]) if controls is None else controls
    if set(variants) - {"baseline", *rules["knobs"]}:
        raise ValueError("unknown optional control")
    if density_ticks is not None and density_ticks < ticks:
        raise ValueError("density duration must cover the ordinary sample")
    output = {}
    source_hash = hashlib.sha256(Path(__file__).read_bytes() + Path(sim.__file__).read_bytes()).hexdigest()
    measurement_hash, invalidated_families = _checkpoint_state(previous_source)
    if checkpoint is not None:
        checkpoint.mkdir(parents=True, exist_ok=True)
    for variant in variants:
        current = sim.rules_dict(rules)
        current["knobs"] = {key: key == variant for key in current["knobs"]}
        runs = []
        tasks = [(case, current, seed,
                  density_ticks if density_ticks is not None and case.family == "density" and case.density else ticks,
                  checkpoint, source_hash if case.family in invalidated_families else measurement_hash)
                 for case in matrix for seed in seeds]
        if workers > 1:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                for index, run in enumerate(pool.map(measure_cached, tasks)):
                    runs.append(run)
                    if progress and index % 20 == 0:
                        print(variant, index + 1, "/", len(tasks), flush=True)
        else:
            for index, task in enumerate(tasks):
                runs.append(measure_cached(task))
                if progress and index % 20 == 0:
                    print(variant, index + 1, "/", len(tasks), flush=True)
        output[variant] = {"rules_hash": sim.digest(current), "fields": bar_fields(runs), "runs": runs,
                           "observed_kos": outcome_count(runs), "status": "awaiting independent review"}
    return {"format": 1, "rules_hash": sim.digest(rules), "source_hash": source_hash,
            "measurement_hash": measurement_hash, "rules": sim.rules_dict(rules),
            "invalidated_families": list(invalidated_families),
            "ticks_per_run": ticks, "seeds": seeds, "scenario_count": len(matrix),
            "density_ticks": ticks if density_ticks is None else density_ticks,
            "matrix": [asdict(case) for case in matrix], "variants": output,
            "limits": ["Tick policy only; no model, chain, stake settlement or hosted-load evidence.",
                       "Right-censored lives are counted separately; rates show their denominators.",
                       "The proposed balance thresholds require independent locking and review.",
                       "Shared-owner and stop-at-one rows measure fight behavior; prediction-log scoring is an external dependency."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules-hash", default=sim.digest(sim.DEFAULT_RULES))
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--ticks", type=int, default=1200)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--workers", type=int, choices=(1, 2), default=1)
    parser.add_argument("--variances", type=int, nargs="+", default=list(VARIANCES))
    parser.add_argument("--comparison-variance", type=int, default=20)
    parser.add_argument("--resume-source", type=Path)
    parser.add_argument("--density-ticks", type=int, default=4800)
    args = parser.parse_args()
    if args.seeds < 1 or args.ticks < 1 or args.density_ticks < args.ticks:
        parser.error("positive seeds and ticks required")
    if args.comparison_variance not in VARIANCES:
        parser.error("comparison variance must be one of 10,15,20,25,30")
    rules = replay.load_rules(args.rules_hash)
    results = {}
    for variance in args.variances:
        if variance not in VARIANCES:
            parser.error("variance must be one of 10,15,20,25,30")
        current = sim.rules_dict(rules)
        current["hitVarPct"] = variance
        results[str(variance)] = report(current, list(range(1, args.seeds + 1)), args.ticks,
                                         progress=True, checkpoint=args.checkpoint, workers=args.workers,
                                         controls=None if variance == args.comparison_variance else ["baseline"],
                                         previous_source=args.resume_source, density_ticks=args.density_ticks)
    result = {"format": 1, "base_rules_hash": sim.digest(rules), "variances": results,
              "comparison_variance": args.comparison_variance}
    args.output.write_text(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    print("measured", len(results), "variance values; review pending")


if __name__ == "__main__":
    main()
