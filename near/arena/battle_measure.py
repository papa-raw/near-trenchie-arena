"""Measure a battle-mode behaviour in a seeded crowd against the same fighter with no behaviour.

    python3 -I near/arena/battle_measure.py [--seeds 5] [--ticks 6000] [--crowd 9] [--out report.json]

The measured fighter runs Pat's example ("grab all the loot and run away from others, only attack when they're
low on HP and not paying attention") and is compared with the same seed and crowd where it has no behaviour.
Every attack it starts and every hit it lands is checked against the gate at that moment. It also times one tick
with 16 fighters each carrying 8 reflexes. Output is JSON; nothing here reads a clock inside the sim.
"""

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import behaviour  # noqa: E402
import sim  # noqa: E402

ME = "pat"
EXAMPLE = {"v": 1, "drives": {"loot": 10, "keep_away": 8, "keep_away_radius": 5, "chase": 3},
           "gate": {"target_hp_below_pct": 40, "target_busy": True}}


class Watched(sim.Sim):
    """Records, for the measured fighter, whether each attack and hit met the gate when it happened."""

    def __init__(self, seed, rules=sim.DEFAULT_RULES):
        super().__init__(seed, rules)
        self.attacks, self.hits, self.casts, self.targets = [], [], [], {}
        self.gate = behaviour.normalise(EXAMPLE, self.rules, ME)[0]["gate"]

    def _policy(self):
        self.targets = {n: self.state["fighters"][n]["target"] for n in self._live()}
        super()._policy()

    def _gate_now(self, enemy, targets=None):
        """The example's gate, checked as the engine checks it: against the targets of this tick's policy start."""
        me = self.state["fighters"][ME]
        return self._passes(me, enemy, self.gate, sim.distance(me, enemy), self.targets if targets is None else targets)

    def _fire_weapon(self, f, target, w, reach):
        if f["id"] == ME:
            now = {n: self.state["fighters"][n]["target"] for n in self._live()}
            self.attacks.append(self._gate_now(target, now))         # judged on the tick the attack starts
        super()._fire_weapon(f, target, w, reach)

    def _should_signature(self, f, kind, target):
        """Offensive signature starts: gated at their target, or (a target-less shockwave) self-defence."""
        start = super()._should_signature(f, kind, target)
        if start and f["id"] == ME and kind in self.OFFENSIVE_SIGNATURES:
            now = {n: self.state["fighters"][n]["target"] for n in self._live()}
            self.casts.append("self_defence" if target is None else self._gate_now(target, now))
        return start

    def queue_hit(self, source, target, base, damage_pct=None, tier_pct=None, knockback=0, move=None):
        before = len(self.state["damages"])
        super().queue_hit(source, target, base, damage_pct, tier_pct, knockback, move)
        if source == ME and len(self.state["damages"]) > before:
            me = self.state["fighters"][ME]
            now = {n: self.state["fighters"][n]["target"] for n in self._live()}
            self.hits.append({"gate": self._gate_now(self.state["fighters"][target], now),
                              "at_target": target == me["target"]})


def run(seed, ticks, crowd, plan):
    game = Watched(seed)
    houses = sorted(game.rules["house"])[:crowd]
    for i, name in enumerate(houses):
        game.enqueue(sim.Input(0, "join", name, 0, {"house": True, "angle": i * 360 // (crowd + 1)}))
    game.enqueue(sim.Input(0, "join", ME, 0, {"angle": crowd * 360 // (crowd + 1)}))
    if plan is not None:
        game.enqueue(sim.Input(1, "behaviour", ME, 1, behaviour.normalise(plan, game.rules, ME)[0]))
    radius = EXAMPLE["drives"]["keep_away_radius"] * game.rules["tile"]
    alive = crowded = grabs = taken = 0
    nearest_sum = 0
    for _ in range(ticks):
        game.step()
        me = game.state["fighters"][ME]
        for event in game.state["events"]:
            if event["kind"] == "grab" and event["fighter"] == ME:
                grabs += 1
            if event["kind"] == "hit" and event["target"] == ME:
                taken += event["damage"]
        if me["state"] != "alive":
            continue
        others = [sim.distance(me, game.state["fighters"][n]) for n in game._live() if n != ME]
        if others:
            alive += 1
            nearest_sum += min(others)
            crowded += min(others) < radius
    hits = game.hits
    return {"seed": seed, "grabs": grabs, "kos": me["kos"], "deaths": me["deaths"], "damage_taken": taken,
            "ticks_alive_with_others": alive,
            "mean_nearest_enemy_milli": nearest_sum // max(1, alive),
            "ticks_enemy_inside_radius_pct": crowded * 100 // max(1, alive),
            "attacks": len(game.attacks), "attacks_meeting_gate": sum(game.attacks),
            "signature_starts": len(game.casts), "signature_starts_meeting_gate": game.casts.count(True),
            "signature_self_defence": game.casts.count("self_defence"),
            "hits": len(hits), "hits_meeting_gate": sum(h["gate"] for h in hits),
            "hits_on_chosen_target": sum(h["at_target"] for h in hits),
            "hits_on_chosen_target_meeting_gate": sum(h["gate"] for h in hits if h["at_target"])}


def tick_cost(fighters=16, reflexes=8, ticks=400):
    """Mean wall time of one tick with every fighter on a behaviour of `reflexes` reflexes, against none."""
    conditions = [{"self_hp_below_pct": 30}, {"enemy_within": 3}, {"enemies_at_least": {"count": 3, "radius": 5}},
                  {"hit_recently": True}, {"loot_within": 4}, {"legendary_on_floor": True},
                  {"target_hp_below_pct": 25}, {"no_target": True}]
    actions = [{"stance": "flee", "say": "Out."}, {"drives": {"keep_away": 9}}, {"gate": {}},
               {"target": "attacker"}, {"drives": {"loot": 10}}, {"stance": "loot"},
               {"target": "weakest"}, {"stance": "hunt-weakest"}]
    plan = {"v": 1, "stance": "loot", "gate": {"target_hp_below_pct": 40, "target_busy": True},
            "reflexes": [{"if": c, "then": a} for c, a in zip(conditions[:reflexes], actions[:reflexes])]}
    out = {}
    for label, with_plan in (("no_behaviour", False), ("behaviour", True)):
        game = sim.Sim(99)
        names = [f"f{i:02d}" for i in range(fighters)]
        for i, name in enumerate(names):
            game.enqueue(sim.Input(0, "join", name, 0, {"angle": i * 360 // fighters}))
            if with_plan:
                game.enqueue(sim.Input(1, "behaviour", name, 1, behaviour.normalise(plan, game.rules, name)[0]))
        game.run(200)
        start = time.perf_counter()
        game.run(ticks)
        out[label] = round((time.perf_counter() - start) * 1000 / ticks, 3)
    out["fighters"], out["reflexes"], out["ticks"] = fighters, reflexes, ticks
    out["tick_budget_ms_at_20hz"] = 50
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--ticks", type=int, default=6000)
    parser.add_argument("--crowd", type=int, default=9)
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    rows = []
    for seed in range(1, args.seeds + 1):
        rows.append({"behaviour": run(seed, args.ticks, args.crowd, EXAMPLE),
                     "no_behaviour": run(seed, args.ticks, args.crowd, None)})
    total = {side: {k: sum(r[side][k] for r in rows) for k in rows[0][side] if k != "seed"}
             for side in ("behaviour", "no_behaviour")}
    for side in total:
        total[side]["mean_nearest_enemy_milli"] //= len(rows)
        total[side]["ticks_enemy_inside_radius_pct"] //= len(rows)
    report = {"rules_hash": sim.digest(sim.DEFAULT_RULES), "example": EXAMPLE, "ticks": args.ticks,
              "crowd": args.crowd + 1, "seeds": [r["behaviour"]["seed"] for r in rows],
              "per_seed": rows, "total": total, "tick_cost": tick_cost()}
    text = json.dumps(report, indent=1, sort_keys=True)
    if args.out:
        Path(args.out).write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
