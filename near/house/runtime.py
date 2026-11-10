"""House runtime v1 (F31): 14 house trenchies on one NEAR AI Cloud model, under the daily cap and the hard stop.

One model serves all 14, because each trenchie is a prompt. A per-tick policy fights; the model sends
at most one intent per ~5 s per active trenchie, plus banter, the respawn pick and the prediction.
The sim never waits on a model: calls run on worker threads and their answers are applied on later polls.

Budget (B78, prd 4.6): a daily cap per phase; at 80% of the day's cap each active trenchie slows to one
call per 30 s; at 100% calls stop until 00:00 UTC and the "autopilot" chip shows; at a cumulative $77 a
hard stop holds until Pat releases the reserve. Every fallback says so (gate 6): nothing is silent.
Every write path is under the data directory (/srv/arena/data in the container). Standard library only.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor

try:
    from . import guard as guard_mod, novelty, quote
except ImportError:
    import guard as guard_mod
    import novelty
    import quote

# Catalogue prices for deepseek-ai/DeepSeek-V4.1-Flash-1017, in nano-USD per token ($0.30 / $1.20 / $0.006 per 1M).
PRICE_NANOUSD = {"in": 300, "out": 1200, "cache": 6}
MODEL = "deepseek-ai/DeepSeek-V4.1-Flash-1017"
ENDPOINT = "https://cloud-api.near.ai/v1/chat/completions"
USD = 1_000_000                       # micro-USD per dollar
DAY_CAPS_USD = {"building": 2, "soak": 8, "judging": 8, "after": 3}
HARD_STOP_USD = 77
SLOW_AT_PCT = 80
BASE_INTERVAL_S = 5
SLOW_INTERVAL_S = 30
BANTER_INTERVAL_S = 30                # at most one line per 30 s per trenchie (B55)
MEASURED_CACHED_SHARE_PCT = 55


def cost_microusd(usage):
    """From metered token counts: uncached input, cache reads and output, rounded down."""
    cached = usage.get("cached_tokens", 0)
    fresh = usage["prompt_tokens"] - cached
    nano = fresh * PRICE_NANOUSD["in"] + cached * PRICE_NANOUSD["cache"] + usage["completion_tokens"] * PRICE_NANOUSD["out"]
    return nano // 1000


class JsonMeter:
    """The spend counter, one small file under the data directory, replaced atomically."""

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        try:
            self.data = json.loads(self.path.read_bytes())
        except (OSError, ValueError):
            self.data = {"days": {}, "total": 0, "calls": 0, "cached_tokens": 0, "prompt_tokens": 0}

    def today(self, day):
        return self.data["days"].get(str(day), 0)

    def total(self):
        return self.data["total"]

    def add(self, day, microusd, usage=None):
        with self.lock:
            self.data["days"][str(day)] = self.today(day) + microusd
            self.data["total"] += microusd
            self.data["calls"] += 1
            if usage:
                self.data["cached_tokens"] += usage.get("cached_tokens", 0)
                self.data["prompt_tokens"] += usage["prompt_tokens"]
            self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".spend.")
        with os.fdopen(fd, "w") as f:
            json.dump(self.data, f, sort_keys=True)
        os.replace(tmp, self.path)


class Budget:
    def __init__(self, meter, mode="building", clock=None):
        if mode not in DAY_CAPS_USD:
            raise ValueError("mode is one of %s" % sorted(DAY_CAPS_USD))
        self.meter, self.mode, self.clock = meter, mode, clock
        self.last_call = {}

    def day(self, now=None):
        return int((self.clock() if now is None else now) // 86400)

    @property
    def cap_microusd(self):
        return DAY_CAPS_USD[self.mode] * USD

    def state(self, now=None):
        day, spent, total = self.day(now), self.meter.today(self.day(now)), self.meter.total()
        base = {"spent_today_microusd": spent, "cap_microusd": self.cap_microusd, "total_microusd": total}
        if total >= HARD_STOP_USD * USD:
            return {**base, "mode": "hard_stop", "interval_s": None, "autopilot": True, "chip": "autopilot (hard stop)"}
        if spent >= self.cap_microusd:
            return {**base, "mode": "capped", "interval_s": None, "autopilot": True, "chip": "autopilot"}
        if spent * 100 >= SLOW_AT_PCT * self.cap_microusd:
            return {**base, "mode": "slow", "interval_s": SLOW_INTERVAL_S, "autopilot": False, "chip": None}
        return {**base, "mode": "normal", "interval_s": BASE_INTERVAL_S, "autopilot": False, "chip": None}

    def allow(self, name, now):
        """True when this trenchie may make a call now; spaces calls per active trenchie."""
        gap = self.state(now)["interval_s"]
        if gap is None:
            return False
        if now - self.last_call.get(name, -10 ** 9) < gap:
            return False
        self.last_call[name] = now
        return True

    def charge(self, usage, now=None):
        self.meter.add(self.day(now), cost_microusd(usage), usage)

    def daily_report(self, now):
        """The judging-day check: cached share against the measured 55%, and when the 80% mark falls."""
        m = self.meter.data if hasattr(self.meter, "data") else {}
        shared = m.get("cached_tokens", 0) * 100 // m["prompt_tokens"] if m.get("prompt_tokens") else None
        spent, into_day = self.meter.today(self.day(now)), now % 86400
        mark = None
        if spent and into_day:
            mark = (SLOW_AT_PCT * self.cap_microusd // 100) * into_day // spent // 3600   # UTC hour, projected
        return {"cached_share_pct": shared, "measured_cached_share_pct": MEASURED_CACHED_SHARE_PCT,
                "projected_80pct_utc_hour": mark, **self.state(now)}


class NearAI:
    """The OpenAI-compatible NEAR AI Cloud client. Thinking is set explicitly on every call."""

    def __init__(self, key_env="NEAR_AI_KEY", model=MODEL, endpoint=ENDPOINT):
        self.key_env, self.model, self.endpoint = key_env, model, endpoint

    def chat(self, messages, thinking=False, max_tokens=200):
        key = os.environ.get(self.key_env)
        if not key:
            raise RuntimeError("model key missing: set %s from the env file outside the repo" % self.key_env)
        body = json.dumps({"model": self.model, "messages": messages, "max_tokens": max_tokens,
                           "chat_template_kwargs": {"enable_thinking": bool(thinking)}}, ensure_ascii=False)
        # The key and the body go to curl on stdin as a config file, never on argv, where `ps` could read them.
        config = "\n".join(["url = " + json.dumps(self.endpoint),
                            "header = " + json.dumps("Authorization: Bearer " + key),
                            "header = \"Content-Type: application/json\"",
                            "max-time = " + ("240" if thinking else "20"), "silent", "show-error",
                            "data = " + json.dumps(body, ensure_ascii=False)])
        out = subprocess.run(["curl", "--config", "-"], input=config, capture_output=True, text=True, check=True).stdout
        data = json.loads(out)
        usage = data["usage"]
        return {"text": data["choices"][0]["message"]["content"],
                "usage": {"prompt_tokens": usage["prompt_tokens"], "completion_tokens": usage["completion_tokens"],
                          "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)}}


class Autopilot(RuntimeError):
    """The daily cap or the hard stop was reached; the tick policy carries on."""


INTENT_KEYS = {"focus": (str, type(None)), "avoid": (str, type(None)), "loot": str, "sig": str}


def parse_json(text):
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the answer")
    return json.loads(text[start:end + 1])


class Runtime:
    """poll() is called from the server's schedule step; model answers apply on later polls."""

    def __init__(self, client, budget, guard, sheets, driver, clock, executor=None, log=None):
        self.client, self.budget, self.guard, self.sheets = client, budget, guard, sheets
        self.driver, self.clock = driver, clock
        self.executor = executor or ThreadPoolExecutor(max_workers=3)
        self.pending = []
        self.voices = {n: novelty.Voice(n, s["keyed"]) for n, s in sheets.items()}
        self.last_banter = {}
        self.notes = []            # no silent fallback: every fallback is recorded here and shown
        self.log = log if log is not None else []

    def note(self, text):
        if text not in self.notes[-3:]:
            self.notes.append(text)

    @property
    def chip(self):
        return self.budget.state(self.clock())["chip"]

    def _ask(self, name, task, instruction, thinking=False, max_tokens=120):
        if self.budget.state(self.clock())["autopilot"]:      # a reroll or a second ask never outruns the cap
            raise Autopilot("budget stop reached mid-call")
        sheet = self.sheets[name]
        card = "\n".join(["Recent lines: " + " | ".join(self.voices[name].card_lines()), task])
        messages = [{"role": "system", "content": sheet["prefix"]}, {"role": "user", "content": card + "\n" + instruction}]
        answer = self.client.chat(messages, thinking=thinking, max_tokens=max_tokens)
        self.budget.charge(answer["usage"], self.clock())
        return answer["text"]

    def poll(self, control, tick, names, want_new, observation):
        now = self.clock()
        self._harvest()
        view = self.driver.sync(control, tick, observation)
        if self.budget.state(now)["autopilot"]:
            self.note("budget stop: the house fights on its tick policy (autopilot)")
            return
        for name in view.get("benched", []):
            if name in self.sheets and self.budget.allow(name, now):
                self.pending.append((name, "pick", self.executor.submit(self._pick, name, view["views"].get(name, {}))))
        for name in view.get("active", []):
            if name not in self.sheets or not self.budget.allow(name, now):
                continue                      # one gate for every call kind: banter shares the trenchie's cadence
            moment = view.get("moments", {}).get(name)
            if moment and now - self.last_banter.get(name, -10 ** 9) >= BANTER_INTERVAL_S:
                self.last_banter[name] = now
                getattr(self.driver, "moment_used", lambda n: None)(name)
                self.pending.append((name, "banter", self.executor.submit(self._banter, name, moment)))
            else:
                self.pending.append((name, "intent", self.executor.submit(self._intent, name, view["views"].get(name, {}))))

    def _harvest(self):
        waiting = []
        for name, kind, future in self.pending:
            if not future.done():
                waiting.append((name, kind, future))
                continue
            try:
                result = future.result()
            except Exception as exc:                       # a failed call is an autopilot tick, said out loud
                self.note("%s: %s call failed (%s): tick policy continues" % (name, kind, type(exc).__name__))
                continue
            if result is not None:
                getattr(self.driver, "apply_" + kind)(name, result)
        self.pending = waiting

    def _intent(self, name, view):
        text = self._ask(name, "State: " + json.dumps(view, sort_keys=True),
                         'Answer one JSON object: {"focus": id|null, "avoid": id|null, "loot": "nearest"|"ignore", "sig": "auto"|"hold"|"use"}.')
        data = parse_json(text)
        if set(data) - set(INTENT_KEYS) or data.get("loot", "nearest") not in ("nearest", "ignore") \
                or data.get("sig", "auto") not in ("auto", "hold", "use"):
            raise ValueError("intent refused")
        return data

    def _banter(self, name, moment):
        voice = self.voices[name]

        def generate():
            return self._ask(name, "Moment: " + moment, "Say one short line in your own voice.", max_tokens=60).strip()

        posted = voice.post(generate, moment if moment in voice.keyed else sorted(voice.keyed)[0],
                            on_reroll=lambda: None)
        checked = self.guard.check(posted["text"], who=name)
        if checked["blocked"]:
            self.note("%s: a line was blocked (%s) and shown as an emote" % (name, checked["reason"]))
        return {"text": checked["text"], "label": posted["label"], "blocked": checked["blocked"]}

    def _pick(self, name, view):
        """The respawn pick: inventory choice, a spread over 1, 2, 3, 4+ KOs and the chance of 0 KOs."""
        ask = ('Pick for your next life. Answer one JSON object: {"loadout": {slot: row}, '
               '"spread_pct": [p1, p2, p3, p4+] (whole percents summing to 100), "zero_pct": 0-100}.')
        for attempt in (0, 1):                              # an invalid spread is asked for once more
            data = parse_json(self._ask(name, "State: " + json.dumps(view, sort_keys=True), ask, max_tokens=160))
            if quote.check_spread(data.get("spread_pct"), data.get("zero_pct")) is None:
                return {"loadout": data.get("loadout"), "spread_pct": data["spread_pct"], "zero_pct": data["zero_pct"],
                        "prediction": True}
            ask = "That spread was invalid (%s). " % quote.check_spread(data.get("spread_pct"), data.get("zero_pct")) + ask
        self.note("%s: no valid spread after a second ask; this life carries no prediction" % name)
        return {"loadout": data.get("loadout"), "spread_pct": None, "zero_pct": None, "prediction": False}
