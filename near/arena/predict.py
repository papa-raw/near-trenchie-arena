"""Predictions from rules integer-16 on: one level, "L or more KOs", rewarded by how rarely the house reaches it.

A prediction travels as the room's spread (room.prediction.v1) with all of `probability_total` on one bin: `one` is
1+, `two` 2+, `three` 3+, `four_plus` 4+, and `zero_bps` 0. Any other spread under a table with a `predict` block is
not counted, and says why (NOT_COUNTED). A table without the block (integer-15 and older) keeps the old spread rule;
nothing here applies to it.

A correct prediction (KOs >= level) is rewarded at the multiplier m(L) = (1 - margin) / P(>=L), capped, where P(>=L)
comes from the five-bin base rate (`market` stores it at each resolve, from house lives only). With 0.01 testnet NEAR
drawn for the life, a correct one returns amount * m(L); a failure leaves its amount in the reward fund. With no
NEAR, a correct one is counted on the leaderboard; the multiplier only sets the NEAR reward.

The public record: one seal row per completed life (`seal_row`), and a settlement row (`settle_row`) for a life NEAR
was drawn for, once its batch resolves. The two leaderboards are computed from the seal rows alone, per UTC day.
Integers only; standard library only.
"""

import datetime
import json
import sys
import threading
from pathlib import Path

try:
    from near.house.quote import PUBLISHED_BASE_BPS as LAB_BASE_BPS   # the lab table, until the house has 200 lives
except ModuleNotFoundError:          # imported with only near/arena (or near/house) on sys.path, as several tests do
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from near.house.quote import PUBLISHED_BASE_BPS as LAB_BASE_BPS

BINS = ("one", "two", "three", "four_plus")
NOT_COUNTED = "prediction not counted: one level, all 10000 on one bin (1+, 2+, 3+ or 4+)"
BPS = 10_000
TOP = 5


def block(rules):
    """The table's predict block, or None for a table from before integer-16."""
    return rules.get("predict")


def read_level(rules, spread_bps, zero_bps):
    """(level 1..4 or None, a note or None) for a locked pick under `rules`.

    No pick, or a table without a predict block: (None, None). A pick that is not one level: (None, NOT_COUNTED).
    """
    if block(rules) is None or spread_bps is None:
        return None, None
    total = rules["probability_total"]
    values = [spread_bps.get(b) for b in BINS]
    if (zero_bps != 0 or set(spread_bps) != set(BINS) or any(type(v) is not int for v in values)
            or sorted(values) != [0, 0, 0, total]):
        return None, NOT_COUNTED
    return values.index(total) + 1, None


def at_least_bps(base_bps, level):
    """P(KOs >= level) in bps, from the five bins over 0, 1, 2, 3, 4+."""
    if len(base_bps) != 5 or not 1 <= level <= 4:
        raise ValueError("a base rate has five bins and a level is 1 to 4")
    return sum(int(b) for b in base_bps[level:])


def multiplier_bps(p, base_bps, level):
    """m(L) in bps: (10000 - margin) * 10000 / P(>=L), never above the cap (a level never reached is at the cap)."""
    reach = at_least_bps(base_bps, level)
    if reach <= 0:
        return p["cap_bps"]
    return min(p["cap_bps"], (BPS - p["margin_bps"]) * BPS // reach)


def outcome(rules, level, kos, base_bps):
    """{result, multiplier_bps, reward_points} for one completed life. result is correct, failure or none."""
    p = block(rules)
    if p is None or level is None:
        return {"result": "none", "multiplier_bps": None, "reward_points": 0}
    m = multiplier_bps(p, base_bps, level)
    correct = int(kos) >= level
    return {"result": "correct" if correct else "failure", "multiplier_bps": m,
            "reward_points": m // 100 if correct else 0}


def returned_yocto(amount_yocto, result, multiplier):
    """What a life's amount brings back: amount * m(L) if correct, nothing on a failure (it stays in the fund)."""
    if type(amount_yocto) is not int or amount_yocto < 0:
        raise ValueError("an amount is whole yoctoNEAR, at least 0")
    return amount_yocto * multiplier // BPS if result == "correct" else 0


def utc_day(ns):
    return datetime.datetime.fromtimestamp(int(ns) // 10 ** 9, datetime.timezone.utc).strftime("%Y-%m-%d")


def seal_row(*, life_id, persona, house, rules, level, note, kos, base_bps, sealed_ns, run="local", name=None):
    """The record row a completed life adds at its seal. Public; no account, key or model text.

    `run` names the arena the life ran in (life ids restart with each arena, so a host's one record keys rows by
    run and life); `name` is the trenchie's public display name (guard-checked at join), the token id if none."""
    o = outcome(rules, level, kos, base_bps)
    return {"kind": "life", "run": run, "life": life_id, "persona": persona, "name": name or persona,
            "house": bool(house), "rules": rules["version"],
            "level": level, "note": note, "kos": int(kos), "result": o["result"],
            "multiplier_bps": o["multiplier_bps"], "reward_points": o["reward_points"],
            "base_rate_bps": list(base_bps) if level is not None else None,
            "day": utc_day(sealed_ns), "at_ns": str(sealed_ns)}


def settle_row(*, life_id, persona, amount_yocto, returned, batch_tx, run="local"):
    """The row a life adds when NEAR was drawn for it and its batch resolved."""
    return {"kind": "settled", "run": run, "life": life_id, "persona": persona, "amount_yocto": str(amount_yocto),
            "returned_yocto": str(returned), "batch_tx": batch_tx}


def _most_kos(rows, top):
    kos, lives, house, shown = {}, {}, {}, {}
    for r in rows:
        name = r["persona"]
        house[name], shown[name] = r["house"], r.get("name") or name
        kos[name] = kos.get(name, 0) + int(r["kos"])
        lives[name] = lives.get(name, 0) + 1
    order = sorted(kos, key=lambda n: (-kos[n], -lives[n], n))[:top]
    return [{"persona": n, "name": shown[n], "house": house[n], "kos": kos[n], "lives": lives[n]} for n in order]


def _most_correct(rows, top):
    points, correct, house, shown = {}, {}, {}, {}
    for r in rows:
        if r["result"] != "correct":
            continue
        name = r["persona"]
        house[name], shown[name] = r["house"], r.get("name") or name
        points[name] = points.get(name, 0) + int(r["reward_points"])
        correct[name] = correct.get(name, 0) + 1
    order = sorted(correct, key=lambda n: (-correct[n], n))[:top]
    return [{"persona": n, "name": shown[n], "house": house[n], "reward_points": points[n], "correct": correct[n]}
            for n in order]


def _sides(rows, rank, top):
    return {"players": rank([r for r in rows if not r["house"]], top), "house": rank([r for r in rows if r["house"]], top)}


HOUR_NS = 3600 * 10 ** 9


def leaderboards(rows, day, top=TOP, now_ns=None):
    """{day, most_kos, most_correct, boards} from the seal rows.

    most_kos: KOs per persona on that UTC day (lives beside them). most_correct ("Most correct predictions"):
    the count of correct predictions per persona that day; only personas with a correct one.
    Ties use the persona's name. Both mix house and players. Numeric reward fields remain in the public record.

    boards, the arena sign's two boards (slot 1, bd:19214), each split into players and house, top 5 each:
    most_kos_hour, KOs in the hour before `now_ns` (seal time, the hour it ends in); and most_correct_day, as
    most_correct for `day`. Without `now_ns`, most_kos_hour is left out.
    """
    lives = [r for r in rows if r.get("kind") == "life"]
    today = [r for r in lives if r.get("day") == day]
    boards = {"most_correct_day": _sides(today, _most_correct, top)}
    if now_ns is not None:
        hour = [r for r in lives if now_ns - HOUR_NS < int(r["at_ns"]) <= now_ns]
        boards["most_kos_hour"] = _sides(hour, _most_kos, top)
        boards["hour_from_ns"] = str(now_ns - HOUR_NS)
    return {"day": day, "most_kos": _most_kos(today, top), "most_correct": _most_correct(today, top), "boards": boards}

class Record:
    """The public record file: append-only JSON lines, one seal row and at most one settlement row per life.

    One record per host: every round's arena, and every start of the host, appends to the same file, so the UTC-day
    and hour boards read the whole day. A row is keyed by (kind, run, life); writing one that exists is a no-op (an
    arena seals a segment again at the next tick's boundary, and a resolve is read back before it is repeated)."""

    def __init__(self, path):
        """`path` None keeps the rows in memory only (an arena with no host to give it the host's file)."""
        self.path = Path(path) if path is not None else None
        self.rows = ([json.loads(l) for l in self.path.read_text().splitlines() if l]
                     if self.path is not None and self.path.exists() else [])
        self.seen = {(r["kind"], r.get("run", "local"), r["life"]) for r in self.rows}
        self.lock = threading.Lock()       # the arena thread adds seal rows, the chain writer's thread settlement rows

    def add(self, row):
        key = (row["kind"], row.get("run", "local"), row["life"])
        with self.lock:
            if key in self.seen:
                return False
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a") as f:
                    f.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
            self.rows.append(row)
            self.seen.add(key)
            return True

    def settled(self, run, life_id, persona, amount_yocto, returned, batch_tx):
        return self.add(settle_row(life_id=life_id, persona=persona, amount_yocto=amount_yocto, returned=returned,
                                   batch_tx=batch_tx, run=run))

    def life(self, run, life_id):
        return next((r for r in self.rows if r["kind"] == "life" and r.get("run", "local") == run
                     and r["life"] == life_id), None)

    def leaderboards(self, day, now_ns=None):
        return leaderboards(self.rows, day, now_ns=now_ns)
