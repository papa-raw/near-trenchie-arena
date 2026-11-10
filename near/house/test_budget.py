"""F31: the budget rules with a fake meter: 80% slows to 30 s, 100% stops with the autopilot chip, $77 is the hard stop."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import guard
import runtime

DAY = 86400
T0 = 20_000 * DAY                     # a UTC midnight


class FakeMeter:
    """Spend in micro-USD, set by the test; no file and no clock."""

    def __init__(self, today=0, total=0):
        self.days, self.tot, self.data = {}, total, {}
        self.days["d"] = today

    def today(self, day):
        return self.days["d"]

    def total(self):
        return self.tot

    def add(self, day, microusd, usage=None):
        self.days["d"] += microusd
        self.tot += microusd


class Thresholds(unittest.TestCase):
    def budget(self, today_usd=0.0, total_usd=0.0, mode="building"):
        return runtime.Budget(FakeMeter(int(today_usd * 1e6), int(total_usd * 1e6)), mode)

    def test_below_80_percent_each_active_trenchie_gets_one_call_every_5_s(self):
        b = self.budget(1.59)                                     # cap $2, 79.5%
        s = b.state(T0)
        self.assertEqual((s["mode"], s["interval_s"], s["autopilot"]), ("normal", 5, False))
        self.assertTrue(b.allow("a", T0))
        self.assertFalse(b.allow("a", T0 + 4))
        self.assertTrue(b.allow("a", T0 + 5))
        self.assertTrue(b.allow("b", T0 + 5))                      # a different trenchie has its own spacing

    def test_at_80_percent_the_interval_is_30_s_per_active_trenchie(self):
        b = self.budget(1.60)
        s = b.state(T0)
        self.assertEqual((s["mode"], s["interval_s"], s["autopilot"]), ("slow", 30, False))
        self.assertTrue(b.allow("a", T0))
        self.assertFalse(b.allow("a", T0 + 29))
        self.assertTrue(b.allow("a", T0 + 30))

    def test_at_100_percent_there_are_zero_calls_and_the_autopilot_chip(self):
        b = self.budget(2.00)
        s = b.state(T0)
        self.assertEqual((s["mode"], s["interval_s"], s["chip"]), ("capped", None, "autopilot"))
        self.assertFalse(any(b.allow(n, T0 + k) for n in "ab" for k in range(0, 120, 5)))

    def test_cumulative_77_dollars_is_a_hard_stop_whatever_the_day_has_left(self):
        b = self.budget(0.0, 77.0, mode="judging")
        s = b.state(T0)
        self.assertEqual((s["mode"], s["interval_s"], s["autopilot"]), ("hard_stop", None, True))
        self.assertIn("hard stop", s["chip"])
        self.assertFalse(b.allow("a", T0))
        self.assertEqual(self.budget(0.0, 76.999999, mode="judging").state(T0)["mode"], "normal")

    def test_phase_caps_are_2_8_and_3_dollars(self):
        self.assertEqual([runtime.DAY_CAPS_USD[m] for m in ("building", "judging", "after")], [2, 8, 3])
        self.assertEqual(self.budget(2.40, mode="judging").state(T0)["mode"], "normal")
        self.assertEqual(self.budget(3.00, mode="after").state(T0)["mode"], "capped")


class Meter(unittest.TestCase):
    def test_cost_uses_the_catalogue_prices_and_the_day_rolls_at_midnight_utc(self):
        usage = {"prompt_tokens": 750, "completion_tokens": 42, "cached_tokens": 400}
        self.assertEqual(runtime.cost_microusd(usage), (350 * 300 + 400 * 6 + 42 * 1200) // 1000)
        with tempfile.TemporaryDirectory() as d:
            meter = runtime.JsonMeter(Path(d) / "spend.json")
            b = runtime.Budget(meter, "building")
            b.charge(usage, T0 + 100)
            self.assertEqual(meter.today(20_000), runtime.cost_microusd(usage))
            self.assertEqual(b.state(T0 + DAY + 1)["spent_today_microusd"], 0)    # new UTC day, fresh cap
            self.assertEqual(runtime.JsonMeter(Path(d) / "spend.json").total(), runtime.cost_microusd(usage))
            self.assertEqual(sorted(p.name for p in Path(d).iterdir()), ["spend.json"])


class Transport(unittest.TestCase):
    def test_the_key_never_reaches_curls_argv_and_the_body_rides_stdin(self):
        from unittest import mock
        seen = {}

        def fake_run(argv, input=None, **kw):
            seen.update(argv=argv, input=input)
            class R:
                stdout = json.dumps({"choices": [{"message": {"content": "hi"}}],
                                     "usage": {"prompt_tokens": 10, "completion_tokens": 2,
                                               "prompt_tokens_details": {"cached_tokens": 4}}})
            return R()
        import os
        with mock.patch.dict(os.environ, {"NEAR_AI_KEY": "sk-SECRET-CANARY"}), \
                mock.patch.object(runtime.subprocess, "run", fake_run):
            out = runtime.NearAI().chat([{"role": "user", "content": "say \"hi\"\nplease"}], thinking=False)
        self.assertEqual((out["text"], out["usage"]["cached_tokens"]), ("hi", 4))
        self.assertNotIn("sk-SECRET-CANARY", " ".join(seen["argv"]))
        self.assertIn("sk-SECRET-CANARY", seen["input"])
        self.assertIn('enable_thinking', seen["input"])


class Calls(unittest.TestCase):
    """The runtime end to end on a fake model and a fake driver."""

    class Client:
        def __init__(self, answers):
            self.answers, self.calls = list(answers), []

        def chat(self, messages, thinking=False, max_tokens=200):
            self.calls.append({"thinking": thinking, "system": messages[0]["content"]})
            return {"text": self.answers.pop(0), "usage": {"prompt_tokens": 750, "completion_tokens": 42, "cached_tokens": 0}}

    class Driver:
        def __init__(self, benched=(), active=()):
            self.view = {"benched": list(benched), "active": list(active), "views": {}, "moments": {}}
            self.applied = []

        def sync(self, control, tick, observation):
            return self.view

        def apply_intent(self, name, value):
            self.applied.append(("intent", name, value))

        def apply_pick(self, name, value):
            self.applied.append(("pick", name, value))

        def apply_banter(self, name, value):
            self.applied.append(("banter", name, value))

    class Now:
        def __init__(self, t):
            self.t = t

        def __call__(self):
            return self.t

    class Sync:
        def submit(self, fn, *a):
            from concurrent.futures import Future
            f = Future()
            try:
                f.set_result(fn(*a))
            except Exception as exc:
                f.set_exception(exc)
            return f

    def runtime(self, client, driver, today_usd=0.0, now=T0):
        sheets = {"satrenchi": {"prefix": "You are Satrenchi.", "keyed": {"idle": "Quiet tide."}}}
        clock = self.Now(now)
        rt = runtime.Runtime(client, runtime.Budget(FakeMeter(int(today_usd * 1e6)), "building"),
                             guard.Guard({"names": [], "handles": [], "slurs": []}, ["Satrenchi"]),
                             sheets, driver, clock, executor=self.Sync())
        return rt, clock

    def test_a_valid_pick_carries_its_prediction_and_an_invalid_one_is_asked_again_once(self):
        good = json.dumps({"loadout": {"weapon": "c-beam"}, "spread_pct": [40, 30, 20, 10], "zero_pct": 35})
        bad = json.dumps({"loadout": {}, "spread_pct": [50, 50, 10, 0], "zero_pct": 35})
        rt, _ = self.runtime(self.Client([bad, good]), self.Driver(benched=["satrenchi"]))
        rt.poll(None, 1, (), 0, None)
        rt.poll(None, 2, (), 0, None)
        kind, name, value = rt.driver.applied[0]
        self.assertEqual((kind, value["prediction"], value["spread_pct"]), ("pick", True, [40, 30, 20, 10]))
        rt2, _ = self.runtime(self.Client([bad, bad]), self.Driver(benched=["satrenchi"]))
        rt2.poll(None, 1, (), 0, None)
        rt2.poll(None, 2, (), 0, None)
        value = rt2.driver.applied[0][2]
        self.assertEqual((value["prediction"], value["spread_pct"]), (False, None))
        self.assertTrue(any("no prediction" in n for n in rt2.notes))

    def test_every_call_sets_thinking_off_and_puts_the_sheet_first(self):
        rt, _ = self.runtime(self.Client(['{"loot": "nearest", "sig": "auto", "focus": null, "avoid": null}']),
                             self.Driver(active=["satrenchi"]))
        rt.poll(None, 1, (), 0, None)
        rt.poll(None, 2, (), 0, None)
        self.assertEqual(rt.client.calls[0], {"thinking": False, "system": "You are Satrenchi."})
        self.assertEqual(rt.driver.applied[0][0], "intent")

    def test_at_100_percent_no_call_is_made_and_the_chip_and_note_say_autopilot(self):
        client = self.Client([])
        rt, _ = self.runtime(client, self.Driver(active=["satrenchi"], benched=["satrenchi"]), today_usd=2.0)
        rt.poll(None, 1, (), 0, None)
        self.assertEqual(client.calls, [])
        self.assertEqual(rt.chip, "autopilot")
        self.assertTrue(any("autopilot" in n for n in rt.notes))

    def test_banter_shares_the_trenchies_cadence_and_a_reroll_cannot_outrun_the_cap(self):
        # at 80% every call kind is one per 30 s per trenchie: banter does not add calls on top of intents
        intent = '{"loot": "nearest", "sig": "auto", "focus": null, "avoid": null}'
        client = self.Client([intent, "A fresh line about the tide"] + [intent] * 40)
        driver = self.Driver(active=["satrenchi"])
        driver.view["moments"] = {"satrenchi": "idle"}
        rt, clock = self.runtime(client, driver, today_usd=1.60)
        for second in range(0, 60):
            clock.t = T0 + second
            rt.poll(None, second, (), 0, None)
        self.assertEqual(len(client.calls), 2)                  # t=0 and t=30, never more
        # the cap is reached while a banter call is rerolling: the second ask is refused, not made
        loud = self.Client(["One coin, one island.", "One coin, one island!"])
        rt2, clock2 = self.runtime(loud, self.Driver(active=["satrenchi"]), today_usd=1.99999)
        rt2.voices["satrenchi"].posted.append("One coin, one island.")
        rt2.voices["satrenchi"].keyed = {"idle": "Quiet tide."}
        with self.assertRaises(runtime.Autopilot):
            rt2._banter("satrenchi", "idle")
        self.assertEqual(len(loud.answers), 1)

    def test_a_failed_call_is_said_out_loud_not_swallowed(self):
        class Boom:
            def chat(self, *a, **k):
                raise RuntimeError("timeout")
        rt, _ = self.runtime(Boom(), self.Driver(active=["satrenchi"]))
        rt.poll(None, 1, (), 0, None)
        rt.poll(None, 2, (), 0, None)
        self.assertTrue(any("tick policy continues" in n for n in rt.notes))


if __name__ == "__main__":
    unittest.main()
