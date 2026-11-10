"""The runtime on a real Arena: house members lock a prediction through the bridge, fight, and get their lines in the feed."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "arena"))
import driver
import guard
import predictions
import runtime
import server
import sim
import test_server as ts


class Scripted:
    def __init__(self):
        self.calls = []

    def chat(self, messages, thinking=False, max_tokens=200):
        self.calls.append(messages[-1]["content"][:40])
        usage = {"prompt_tokens": 750, "completion_tokens": 42, "cached_tokens": 600}
        text = messages[-1]["content"]
        if "Pick for your next life" in text:
            body = json.dumps({"loadout": {}, "spread_pct": [40, 30, 20, 10], "zero_pct": 35})
        elif "JSON object" in text:
            body = json.dumps({"loot": "nearest", "sig": "auto", "focus": None, "avoid": None})
        else:
            body = "The tide keeps its own books."
        return {"text": body, "usage": usage}


class Wired(unittest.TestCase):
    def test_house_members_lock_a_prediction_fight_and_log_it(self):
        names = sorted(sim.DEFAULT_RULES["house"])[:3]
        with tempfile.TemporaryDirectory() as d:
            holder = {}
            sheets = {n: {"prefix": "You are " + n, "keyed": {"ko_given": "Down.", "ko_taken": "Again.", "loot": "Mine.", "idle": "Tide."}} for n in names}
            clock = [20_000 * 86400]
            from concurrent.futures import Future

            class Sync:
                def submit(self, fn, *a):
                    f = Future()
                    try:
                        f.set_result(fn(*a))
                    except Exception as exc:
                        f.set_exception(exc)
                    return f

            def build(**kw):
                a = ts.Composition("test_sixteen_admitted_six_ring_and_fifo_bench")
                a.tmp = tempfile.TemporaryDirectory()
                return a

            comp = build()
            log = predictions.PredictionLog(d + "/log")
            holder["driver"] = None
            rt_box = {}

            def resolver(binding, payload):
                return holder["driver"].pick_resolver(binding, payload)

            class Poller:
                def poll(self, control, tick, roster, count, view):
                    rt_box["rt"].poll(control, tick, roster, count, view)

            arena = comp.arena(house_runtime=Poller(), pick_resolver=resolver)
            bindings = {n: ts.binding(n, house=True) for n in names}
            for b in bindings.values():
                self.assertIn("life_id", arena.bridge.reserve_life(b))
            drv = driver.ArenaDriver(arena, bindings, log=log)
            holder["driver"] = drv
            meter = runtime.JsonMeter(d + "/spend.json")
            rt_box["rt"] = runtime.Runtime(Scripted(), runtime.Budget(meter, "building"),
                                           guard.Guard({"names": [], "handles": [], "slurs": []}, names),
                                           sheets, drv, lambda: clock[0], executor=Sync())
            for _ in range(400):
                arena.advance(1)
                clock[0] += 0.05
                clock[0] = round(clock[0], 2)
            fighters = arena.sim.state["fighters"]
            self.assertTrue(all(n in fighters for n in names))
            self.assertTrue(any(f["state"] == "alive" for f in fighters.values()))
            rows = [e for e in log.locks.values()]
            self.assertEqual(len(rows), len(names))
            self.assertTrue(all(r["body"]["prediction"] for r in rows))
            self.assertGreater(meter.total(), 0)
            sent = [c["value"] for c in arena.commands if c["kind"] == "input" and c["value"]["kind"] == "intent"]
            self.assertTrue(sent, "the model's intents reached the sim as logged inputs")
            self.assertTrue(drv.feed, "banter reached the feed")
            self.assertEqual(rt_box["rt"].notes, [])
            comp.tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
