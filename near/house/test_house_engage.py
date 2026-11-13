"""The house engages in a spread ring: real plans from the house model, lean mode, the real arena and engine.

The fixtures are the plans DeepSeek V4.1 Flash wrote for the five house fighters of a live 3-minute crowd run on the
building cap (lean), as the house sent them, plus Avichad's first plan from the 14-persona live check. Four base plans
gate their attacks on the target's hp ("below 35-60%") and a short distance, and the fifth only on its rival, so in a
ring where everyone spawns apart at full hp almost nobody passes anybody's gate, and a "no_target -> stance hold"
reflex stands a fighter still: three of the five never landed a hit in that run. Avichad's plan protects its ally
from a reflex without naming the ally in drives.protect_ally and puts the ally's id in `target` instead, and the
arena refuses it whole.

Checked: on the composition's 5-fighter ring (the five above), lean mode, every house fighter attacks someone within
ENGAGE_S of sim time after its plan applies; a reflex that protects is sent with the ally named and never targets
that ally; no order is refused for it; the house says what it changed.
"""

import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "arena"))
sys.path.insert(0, str(HERE.parents[1]))
import battle
import sim
import test_battle as tb

ENGAGE_S = 20                     # every fighter in the ring attacks within 20 s of sim time after its plan applies

# Sent by the house in the lean crowd run (building cap), the model's own words; only the say lines are its text.
LIVE_PLANS = {
    "avichad": {"v": 1, "stance": "hold", "target": "weakest",
                "drives": {"chase": 2, "hold": 6, "hold_at": "center", "hold_radius": 4, "keep_away": 2, "keep_away_radius": 4, "loot": 3, "protect": 0},
                "gate": {"distance_under": 3, "target_hp_below_pct": 60},
                "reflexes": [{"if": {"self_hp_below_pct": 30}, "then": {"say": "Census still says down, not out.", "stance": "defend"}},
                             {"if": {"enemy_within": {"radius": 3, "who": "any"}}, "then": {"say": "Counted you, now build some hp back.", "stance": "berserk", "target": "nearest"}},
                             {"if": {"no_target": True}, "then": {"say": "Ship something, then fight me.", "stance": "hold"}}]},
    "kathie-moonwood": {"v": 1, "stance": "hold", "target": "weakest",
                        "drives": {"chase": 0, "hold": 4, "hold_at": "here", "hold_radius": 3, "keep_away": 8, "keep_away_radius": 10, "loot": 3},
                        "gate": {"distance_under": 5, "match": "all", "target_hp_below_pct": 40},
                        "reflexes": [{"if": {"self_hp_below_pct": 45}, "then": {"drives": {"keep_away": 10, "keep_away_radius": 12}, "say": "A dip the curve already holds.", "stance": "flee"}},
                                     {"if": {"enemy_within": {"radius": 6, "who": "rival"}}, "then": {"drives": {"keep_away": 10}, "stance": "flee", "target": "captain-banana-zone"}},
                                     {"if": {"no_target": True}, "then": {"say": "Notebook open, five-year arc intact.", "stance": "hold"}}]},
    "captain-banana-zone": {"v": 1, "stance": "berserk", "target": "kathie-moonwood",
                            "drives": {"chase": 7, "keep_away": 0, "loot": 3}, "gate": {"rival": True},
                            "reflexes": [{"if": {"enemy_within": {"radius": 6, "who": "rival"}}, "then": {"say": "Moonwood, the tide's rising right at you.", "target": "kathie-moonwood"}},
                                         {"if": {"self_hp_below_pct": 30}, "then": {"drives": {"keep_away": 5, "keep_away_radius": 4}, "say": "Just a dip before the zone, zoom out.", "stance": "defend"}}]},
    "laser-sailor": {"v": 1, "stance": "hold", "target": "nearest",
                     "drives": {"chase": 3, "hold": 5, "hold_at": "here", "hold_radius": 3, "keep_away": 6, "keep_away_radius": 5, "loot": 1},
                     "gate": {"distance_under": 4, "match": "all", "target_hp_below_pct": 35},
                     "reflexes": [{"if": {"enemy_within": {"radius": 6, "who": "rival"}}, "then": {"stance": "defend", "target": "vitrenchik"}},
                                  {"if": {"hit_recently": True}, "then": {"stance": "flee", "target": "auto"}},
                                  {"if": {"legendary_on_floor": True}, "then": {"drives": {"loot": 8}, "say": "Bought more sand.", "stance": "loot"}}]},
    "tommy-leeth": {"v": 1, "stance": "loot", "target": "weakest",
                    "drives": {"chase": 2, "hold": 0, "keep_away": 4, "keep_away_radius": 3, "loot": 10},
                    "gate": {"distance_under": 4, "target_hp_below_pct": 40},
                    "reflexes": [{"if": {"loot_within": 6}, "then": {"say": "Floor item first, bigger cycle ahead folks", "stance": "loot"}},
                                 {"if": {"enemy_within": {"radius": 5, "who": "rival"}}, "then": {"stance": "hold", "target": "hameme-pumpeshi"}},
                                 {"if": {"self_hp_below_pct": 30}, "then": {"say": "Just a healthy pullback, stacking later", "stance": "flee"}}]},
}

# Avichad's first plan from the live check: the reflex that guards its ally names the ally as the attack target.
ALLY_PLAN = {"v": 1, "stance": "hunt-weakest", "target": "weakest",
             "drives": {"loot": 3, "keep_away": 0, "chase": 6, "protect": 0},
             "gate": {"target_hp_below_pct": 70, "distance_under": 6, "match": "all"},
             "reflexes": [{"if": {"self_hp_below_pct": 40}, "then": {"stance": "defend", "say": "Census stays calm; tally still counts me alive."}},
                          {"if": {"ally_hit_recently": True}, "then": {"stance": "follow-ally", "target": "stepan-gershunode", "say": "Stepan shipped; I bring the chain over."}},
                          {"if": {"target_hp_below_pct": 25}, "then": {"stance": "berserk", "say": "Counted three brawlers, now one signature."}}]}

USAGE = {"prompt_tokens": 750, "completion_tokens": 42, "cached_tokens": 600}


class Recorded(tb.Model):
    """Answers every plan ask (first plans and retries alike) with that persona's recorded plan."""

    def __init__(self, sheets, plans):
        super().__init__()
        self.sheets, self.plans = sheets, plans

    def chat(self, messages, thinking=False, max_tokens=200):
        text = messages[-1]["content"]
        if "Write the behaviour you want now" not in text:
            return super().chat(messages, thinking, max_tokens)
        self.asks.append(text)
        slug = next(s for s, sh in self.sheets.items() if sh["prefix"] == messages[0]["content"])
        return {"text": json.dumps({"behaviour": self.plans[slug], "say": None}), "usage": USAGE}


def lean_ring(d, plans, mode="building"):
    clock = [20_000 * 86400]
    comp, arena, house, feed, orders = tb.compose(d, clock, mode=mode)      # building: lean battle mode; judging: full
    house.client = house.runtime.client = Recorded(house.sheets, plans)
    return comp, arena, house, clock, orders


def run(arena, clock, seconds, on_event=lambda tick, e: None):
    for _ in range(seconds * 20):
        arena.advance(1)
        clock[0] = round(clock[0] + 0.05, 2)
        for e in arena.sim.state["events"]:
            on_event(arena.sim.state["tick"], e)


class HouseEngages(unittest.TestCase):
    def test_a_lean_ring_of_five_with_the_models_cautious_plans_engages_within_twenty_seconds(self):
        with tempfile.TemporaryDirectory() as d:
            comp, arena, house, clock, orders = lean_ring(d, LIVE_PLANS)
            planned, first_attack = {}, {}

            def watch(tick, e):
                if e["kind"] == "behaviour":
                    planned.setdefault(e["fighter"], tick)
                if e["kind"] == "attack" and e["fighter"] in planned:
                    first_attack.setdefault(e["fighter"], tick - planned[e["fighter"]])
            run(arena, clock, 10 + ENGAGE_S, watch)          # the plans apply in the first seconds (the first asks)
            ring = sorted(n for n, f in arena.sim.state["fighters"].items() if house.sheets.get(n) and f["state"] != "bench")
            self.assertEqual(ring, sorted(LIVE_PLANS), "the composition seats the five fighters of the live run")
            self.assertEqual(house.runtime.battle.style, "lean")
            self.assertEqual(sorted({n for n, _ in orders}), ring, "every fighter sent its own plan")
            self.assertTrue(all(planned[n] <= 10 * 20 for n in ring), planned)
            late = [n for n in ring if first_attack.get(n, 10 ** 9) > ENGAGE_S * 20]
            self.assertEqual(late, [], "every house fighter attacks within %d s of its plan (ticks after the plan: %s)"
                             % (ENGAGE_S, first_attack))
            for name, payload in orders:                      # what made the ring stall is not what the house sends
                self.assertEqual(payload.get("gate"), {}, (name, payload))
                self.assertNotIn(payload.get("target"), ("attacker",) + tuple(house.sheets), (name, payload))
            logged = [json.loads(l) for l in (Path(d) / "house/behaviours.jsonl").read_text().splitlines()]
            self.assertTrue(all(r["status"] in ("applied", "clipped") for r in logged), logged)
            self.assertTrue(all(r["house_fixed"] for r in logged), "each change the house made is logged")
            self.assertTrue(any("gate" in fix for r in logged for fix in r["house_fixed"]))
            self.assertEqual([n.split(" ", 2)[1].rstrip(":") for n in house.public_roster()["engage_notes"]], ring,
                             "each change is said on the roster, one line per fighter")
            comp.tmp.cleanup()

    def test_a_failing_call_note_is_not_pushed_off_the_roster_by_engage_notes_in_full_mode(self):
        with tempfile.TemporaryDirectory() as d:
            comp, arena, house, clock, orders = lean_ring(d, LIVE_PLANS, mode="judging")
            failed = "kathie-moonwood: plan call failed (ModelCallError: curl exit 28): tick policy continues"
            house.runtime.note(failed)
            run(arena, clock, 60)                             # full mode: every seated fighter plans, rewrites on hits
            self.assertEqual(house.runtime.battle.style, "full")
            roster = house.public_roster()
            self.assertTrue(any(n.endswith(failed) for n in roster["notes"]),
                            "the failing call is still among the roster's last notes: %s" % roster["notes"])
            self.assertGreaterEqual(len(roster["engage_notes"]), 5, roster["engage_notes"])
            self.assertTrue(all("so it engages" in n for n in roster["engage_notes"]))
            self.assertFalse([n for n in roster["notes"] if "engages" in n], "engage notes have their own list")
            comp.tmp.cleanup()

    def test_a_reflex_that_protects_names_the_ally_and_is_never_refused(self):
        with tempfile.TemporaryDirectory() as d:
            comp, arena, house, clock, orders = lean_ring(d, dict(LIVE_PLANS, avichad=ALLY_PLAN))
            run(arena, clock, 10)
            sent = [p for n, p in orders if n == "avichad"]
            self.assertEqual(len(sent), 1, "one order, accepted the first time: no retry was needed")
            ally = battle.relations(house.sheets["avichad"]["game"])[1][0]
            self.assertEqual(sent[0]["drives"]["protect"], 0, "the house fights rather than following an ally")
            self.assertFalse(any(r["then"].get("target") == ally for r in sent[0]["reflexes"]), "the ally is never the attack target")
            logged = [json.loads(l) for l in (Path(d) / "house/behaviours.jsonl").read_text().splitlines()]
            self.assertEqual([r["status"] for r in logged if r["persona"] == "avichad"], ["clipped"] if logged[0]["clipped"] else ["applied"])
            self.assertFalse([r for r in logged if r["status"] == "refused"], "no order is refused")
            comp.tmp.cleanup()

    def test_without_an_ally_a_protect_reflex_is_dropped_never_sent(self):
        game = {"rivalries": [{"with": "kathie-moonwood", "kind": "rival"}]}
        plan = {"v": 1, "stance": "berserk",
                "reflexes": [{"if": {"hit_recently": True}, "then": {"stance": "follow-ally", "say": "Cover me."}},
                             {"if": {"self_hp_below_pct": 20}, "then": {"drives": {"protect": 6}}}]}
        fixed, notes = battle.engage(plan, game, sim.DEFAULT_RULES)
        self.assertEqual(fixed["reflexes"][0]["then"]["say"], "Cover me.")
        self.assertTrue(all(r["then"].get("drives", {}).get("protect", 0) == 0 for r in fixed["reflexes"]))
        self.assertTrue(all(r["then"].get("stance") != "follow-ally" for r in fixed["reflexes"]))
        self.assertTrue(notes)

    def test_the_plan_prompt_says_how_to_engage_and_how_to_name_an_ally(self):
        loaded = tb.sheets_mod.load()
        ask = battle.plan_ask("avichad", loaded, "start", "your first plan", {"me": {}, "near": []}, None, minor=1)
        self.assertIn('"gate": {}', ask)
        self.assertIn("chase", ask)
        self.assertIn("Never flee", ask)
        self.assertIn("never your ally", ask)


if __name__ == "__main__":
    unittest.main()
