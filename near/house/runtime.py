"""House runtime v1: 14 house trenchies on one NEAR AI Cloud model, under the daily cap and the hard stop.

One model serves all 14, because each trenchie is a prompt. A per-tick policy fights; the model sends
at most one intent per ~5 s per active trenchie, plus banter, the respawn pick and the prediction.
The sim never waits on a model: calls run on worker threads and their answers are applied on later polls.

Budget: a daily cap per phase; at 80% of the day's cap each active trenchie slows to one
call per 30 s; at 100% calls stop until 00:00 UTC and the "autopilot" chip shows; at a cumulative $77 a
hard stop holds until Pat releases the reserve. Every fallback says so: nothing is silent.
Calls with no confirmed usage consume a conservative uncached prompt/output allowance. An unreadable
or unwritable spend meter stops calls until its history is recovered and the runtime restarted.
Every write path is under the data directory (/srv/arena/data in the container). Standard library only.
"""

import json
import os
import re
import sys
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

try:
    from . import battle as battle_mod, guard as guard_mod, novelty, quote, pursuit
except ImportError:
    import battle as battle_mod
    import guard as guard_mod
    import novelty
    import quote
    import pursuit

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
BANTER_INTERVAL_S = 10                # at most one line per 10 s per trenchie (battle mode; it was 30 s before)
FAILING_AFTER = 3                     # this many failed calls in a row, with no success between, shows the failing chip
MEASURED_CACHED_SHARE_PCT = 55
NOTES_KEPT = 50                       # the roster shows the last 5; older notes are dropped
CHAT_MESSAGE_TOKEN_ALLOWANCE = 32     # framing overhead per message when usage is unknown


def cost_microusd(usage):
    """From metered token counts: uncached input, cache reads and output, rounded down."""
    cached = usage.get("cached_tokens", 0)
    fresh = usage["prompt_tokens"] - cached
    nano = fresh * PRICE_NANOUSD["in"] + cached * PRICE_NANOUSD["cache"] + usage["completion_tokens"] * PRICE_NANOUSD["out"]
    return nano // 1000


class JsonMeter:
    """The spend counter, one small file under the data directory, replaced atomically."""
    per_name = True                                     # it also keeps each trenchie's spend for the roster

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.fault = None
        self.data = {"days": {}, "total": 0, "calls": 0, "cached_tokens": 0, "prompt_tokens": 0}
        try:
            data = json.loads(self.path.read_bytes())
            if self.valid(data):
                self.data = data
            else:
                self.fault = "invalid history"
        except FileNotFoundError:
            if self.path.is_symlink():
                self.fault = "unreadable history"
            else:
                try:
                    self._save()  # learn that a new meter cannot be written before a model call
                except OSError:
                    self.fault = "unwritable history"
        except (OSError, ValueError):
            self.fault = "unreadable history"

    @staticmethod
    def valid(data: object) -> bool:
        """Reject corrupt counters as well as invalid JSON; a valid-looking reset must not fail open."""
        if not isinstance(data, dict) or not isinstance(data.get('days'), dict):
            return False
        counters = [data.get(k) for k in ('total', 'calls', 'cached_tokens', 'prompt_tokens')]
        counters += list(data['days'].values())
        names = data.get('names', {})
        if not isinstance(names, dict) or any(not isinstance(day, dict) for day in names.values()):
            return False
        counters += [value for day in names.values() for value in day.values()]
        return (all(type(n) is int and n >= 0 for n in counters)
                and data['total'] >= sum(data['days'].values())
                and data['cached_tokens'] <= data['prompt_tokens'])

    def today(self, day):
        return self.data["days"].get(str(day), 0)

    def total(self):
        return self.data["total"]

    def today_for(self, day, who):
        return self.data.get("names", {}).get(str(day), {}).get(who, 0)

    def add(self, day, microusd, usage=None, who=None):
        with self.lock:
            if self.fault:
                raise OSError("spend meter unavailable; recover its history before restarting")
            self.data["days"][str(day)] = self.today(day) + microusd
            if who is not None:                         # the per-trenchie meter the roster shows for house members
                names = self.data.setdefault("names", {}).setdefault(str(day), {})
                names[who] = names.get(who, 0) + microusd
            self.data["total"] += microusd
            self.data["calls"] += 1
            if usage:
                self.data["cached_tokens"] += usage.get("cached_tokens", 0)
                self.data["prompt_tokens"] += usage["prompt_tokens"]
            self._save()

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".spend.")
            try:
                with os.fdopen(fd, "w") as f:
                    json.dump(self.data, f, sort_keys=True)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, self.path)
            finally:
                Path(tmp).unlink(missing_ok=True)
        except OSError:
            self.fault = "unwritable history"
            raise


# The cap period by the UTC clock, from the hackathon's own rule dates only (rules-raw/HACKATHON.md:20-22: submission
# deadline 2026-11-14T23:59:00Z, judging from 2026-11-16T00:00:00Z, results by 2026-11-18T23:59:00Z). The soak starts at
# the deadline itself; judging runs through 2026-11-18T23:59:59Z.
PERIOD_STARTS = (                     # (UTC epoch seconds, the period that starts then); "building" before the first
    (1794700740, "soak"),             # 2026-11-14T23:59:00Z, the submission deadline (the rules' own instant)
    (1794787200, "judging"),          # 2026-11-16T00:00:00Z
    (1795046400, "after"),            # 2026-11-19T00:00:00Z (judging runs to 2026-11-18T23:59:59Z)
)


def period_at(now):
    period = "building"
    for start, name in PERIOD_STARTS:
        if now >= start:
            period = name
    return period


class Budget:
    """mode "auto" (the default) follows the calendar; any period name is an explicit override, and says so."""

    def __init__(self, meter, mode="auto", clock=None):
        if mode != "auto" and mode not in DAY_CAPS_USD:
            raise ValueError("mode is auto or one of %s" % sorted(DAY_CAPS_USD))
        import time as _time
        self.meter, self.clock = meter, clock or _time.time
        self.override = None if mode == "auto" else mode
        self.last_call = {}

    @property
    def mode(self):
        """The active cap period: the override when one was given, else the period the UTC clock is in."""
        return self.override or period_at(self.clock())

    @property
    def source(self):
        return "override" if self.override else "calendar"

    def day(self, now=None):
        return int((self.clock() if now is None else now) // 86400)

    @property
    def cap_microusd(self):
        return DAY_CAPS_USD[self.mode] * USD

    def state(self, now=None):
        day, spent, total = self.day(now), self.meter.today(self.day(now)), self.meter.total()
        base = {"spent_today_microusd": spent, "cap_microusd": self.cap_microusd, "total_microusd": total}
        if getattr(self.meter, 'fault', None):
            return {**base, "mode": "meter_error", "interval_s": None, "autopilot": True,
                    "chip": "autopilot (spend meter unavailable)"}
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

    def charge(self, usage, now=None, who=None):
        if who is not None and getattr(self.meter, "per_name", False):
            self.meter.add(self.day(now), cost_microusd(usage), usage, who)
        else:                                           # a meter with no per-trenchie split keeps its 3-argument add
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
        # No --fail: an HTTP error's own body says why, and the status comes back on the last line (write-out).
        config = "\n".join(["url = " + json.dumps(self.endpoint),
                            "header = " + json.dumps("Authorization: Bearer " + key),
                            "header = \"Content-Type: application/json\"",
                            "max-time = " + ("240" if thinking else "20"), "silent", "show-error",
                            "write-out = \"\\n%{http_code}\"",
                            "data = " + json.dumps(body, ensure_ascii=False)])
        proc = subprocess.run(["curl", "--config", "-"], input=config, capture_output=True, text=True)
        return self.answer(proc.returncode, proc.stdout, proc.stderr, key)

    @staticmethod
    def answer(returncode, stdout, stderr, key=""):
        """curl's result as the answer, or a ModelCallError that says what failed: curl's exit code and its own
        message, or the HTTP status and the error body's message. The key never appears in it."""
        if returncode != 0:
            raise ModelCallError("curl exit %d" % returncode, _said(stderr, key) or "no message")
        text, _, code = stdout.rpartition("\n")
        status = int(code) if code.strip().isdigit() else 0
        try:
            data = json.loads(text)
        except ValueError:
            data = None
        if status != 200:
            raise ModelCallError("HTTP %d" % status, _said(_error_message(data) or text, key) or "empty body")
        try:
            usage = data["usage"]
            return {"text": data["choices"][0]["message"]["content"],
                    "usage": {"prompt_tokens": usage["prompt_tokens"], "completion_tokens": usage["completion_tokens"],
                              "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)}}
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelCallError("HTTP 200 without an answer (%s missing)" % exc,
                                 _said(_error_message(data) or text, key) or "empty body") from None


class ModelCallError(RuntimeError):
    """A model call that brought back no answer. `public` is what the public roster note shows: curl's exit code or the
    HTTP status only. The full text adds curl's own message or the error body's message (a billing message could name an
    account or a balance), and goes to stderr only. Neither carries the key."""

    def __init__(self, public, detail=""):
        super().__init__("%s: %s" % (public, detail) if detail else public)
        self.public = public


MESSAGE_CHARS = 160
KEY_ENVS = ("NEARAI_API_KEY", "NEAR_AI_KEY")   # the hosted env name and the client's default; both redacted


def _error_message(data):
    """The message an OpenAI-compatible error body carries: {"error": {"message"}}, {"error": "..."}, {"detail": ...}."""
    if not isinstance(data, dict):
        return None
    err = data.get("error")
    if isinstance(err, dict) and err.get("message"):
        return str(err["message"])
    if isinstance(err, str):
        return err
    if data.get("detail"):
        return data["detail"] if isinstance(data["detail"], str) else json.dumps(data["detail"])[:MESSAGE_CHARS]
    if data.get("message"):
        return str(data["message"])
    return None


def _said(text, key):
    """One short line for a public note: whitespace collapsed, the key (and any bearer token) removed, an IPv4 address
    (curl names the host's proxy hop, 10.0.2.2:18443) shown as [addr], cut to 160 chars."""
    line = " ".join(str(text or "").split())
    if key:
        line = line.replace(key, "[key]")
    line = re.sub(r"(?i)bearer\s+\S+", "Bearer [key]", line)
    line = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b", "[addr]", line)
    return line[:MESSAGE_CHARS] + ("…" if len(line) > MESSAGE_CHARS else "")


def described_publicly(exc):
    """What a public note says of a failed call: a ModelCallError's status or exit only; any other exception as described."""
    if isinstance(exc, ModelCallError):
        return "ModelCallError: " + exc.public
    return described(exc)


def described(exc):
    """An exception as a note says it: its class, and its own message when it has one (a ModelCallError carries curl's
    exit or the HTTP status and the error body's message; no exception here carries the key)."""
    text = str(exc)
    for env in KEY_ENVS:
        text = _said(text, os.environ.get(env, ""))
    return "%s: %s" % (type(exc).__name__, text) if text else type(exc).__name__


class Autopilot(RuntimeError):
    """The daily cap or the hard stop was reached; the tick policy carries on."""


INTENT_KEYS = {"focus": (str, type(None)), "avoid": (str, type(None)), "loot": str, "sig": str}


def parse_json(text):
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object in the answer")
    return json.loads(text[start:end + 1])


def now_ok(runtime, name):
    """A plan's line may post only inside the 10 s speech limit (the feed refuses it otherwise; ask first)."""
    return getattr(runtime.driver, "may_banter", lambda n: True)(name)


class Runtime:
    """poll() is called from the server's schedule step; model answers apply on later polls."""

    def __init__(self, client, budget, guard, sheets, driver, clock, executor=None, log=None, battle=False):
        self.client, self.budget, self.guard, self.sheets = client, budget, guard, sheets
        self.driver, self.clock = driver, clock
        if guard is None and not hasattr(getattr(driver, "feed", None), "post"):
            raise ValueError("an unguarded runtime needs a driver whose feed guards every line (feed.PublicFeed)")
        self.executor = executor or ThreadPoolExecutor(max_workers=3)
        self.pending = []
        self.voices = {n: novelty.Voice(n, s["keyed"]) for n, s in sheets.items()}
        self.last_banter = {}
        self.notes = []            # no silent fallback: every fallback is recorded here and shown, stamped with its UTC time
        self.note_texts = []       # the same notes without their stamps, for the repeat check
        self.note_lock = threading.Lock()   # note() runs on executor threads too (_pick, _banter): both lists change together
        self.engage_notes = {}     # name -> its latest "plan changed so it engages" line, stamped; apart from notes, so a
                                   # rewrite every few seconds (full mode) never pushes a failing call off the roster
        self.log = log if log is not None else []
        self.call_times = {}       # name -> recent call times, for calls_per_min on the private status
        self.failing = 0           # failed calls in a row (a success resets it; a budget stop is not a failure)
        self.battle = battle_mod.Memory() if battle else None   # battle mode: behaviours instead of single intents
        self.pursuits = pursuit.Pursuits() if battle else None
        self.stats = {"calls": 0, "banter": 0, "intent": 0, "pick": 0, "failed": 0, "autopilot_lines": 0, "plan": 0, "line": 0}

    def note(self, text):
        """A note reads "<UTC time> <text>", so a stale note never reads as a live failure. A text already among the
        last 3 is not added again: its stamp moves to now, so the time shown is always its latest. The last 50 are kept."""
        stamped = time.strftime("%Y-%m-%dT%H:%M:%SZ ", time.gmtime(self.clock())) + text
        with self.note_lock:
            recent = self.note_texts[-3:]
            if text in recent:
                self.notes[len(self.notes) - len(recent) + recent.index(text)] = stamped
                return
            self.notes.append(stamped)
            self.note_texts.append(text)
            del self.notes[:-NOTES_KEPT], self.note_texts[:-NOTES_KEPT]

    @property
    def chip(self):
        """The budget's chip; else, when the model's calls keep failing, the autopilot chip says so."""
        chip = self.budget.state(self.clock())["chip"]
        if chip is None and self.failing >= FAILING_AFTER:
            return "autopilot (model calls failing)"
        return chip

    def _ask(self, name, task, instruction, thinking=False, max_tokens=120):
        if self.budget.state(self.clock())["autopilot"]:      # a reroll or a second ask never outruns the cap
            raise Autopilot("budget stop reached mid-call")
        sheet = self.sheets[name]
        card = "\n".join(["Recent lines: " + " | ".join(self.voices[name].card_lines()), task])
        messages = [{"role": "system", "content": sheet["prefix"]}, {"role": "user", "content": card + "\n" + instruction}]
        try:
            answer = self.client.chat(messages, thinking=thinking, max_tokens=max_tokens)
        except Exception:
            # A timeout may still be billed. UTF-8 bytes bound prompt tokens conservatively; the output
            # allowance is the requested maximum. Include 32 tokens per message for chat framing.
            usage = {"prompt_tokens": sum(len(m['content'].encode('utf-8')) + CHAT_MESSAGE_TOKEN_ALLOWANCE for m in messages),
                     "completion_tokens": max_tokens, "cached_tokens": 0}
            self.budget.charge(usage, self.clock(), who=name)
            raise
        now = self.clock()
        self.budget.charge(answer["usage"], now, who=name)
        times = self.call_times.setdefault(name, [])
        times.append(now)
        self.call_times[name] = [t for t in times if now - t < 60]
        self.stats["calls"] += 1
        return answer["text"]

    def calls_per_min(self, name):
        now = self.clock()
        return sum(1 for t in self.call_times.get(name, ()) if now - t < 60)

    def poll(self, control, tick, names, want_new, observation):
        now = self.clock()
        self._harvest()
        view = self.driver.sync(control, tick, observation)
        if self.budget.state(now)["autopilot"]:
            self.note("%s: the house fights on its tick policy" % self.budget.state(now)["chip"])
            for name in view.get("active", []):            # keyed lines only, labelled: no model call
                moment = view.get("moments", {}).get(name)
                if name in self.sheets and moment and moment != "idle" \
                        and now - self.last_banter.get(name, -10 ** 9) >= BANTER_INTERVAL_S \
                        and getattr(self.driver, "may_banter", lambda n: True)(name):
                    self.last_banter[name] = now
                    getattr(self.driver, "moment_used", lambda n: None)(name)
                    keyed = self.sheets[name]["keyed"]
                    self.driver.apply_banter(name, {"text": keyed.get(moment, keyed[sorted(keyed)[0]]),
                                                    "label": "autopilot", "blocked": False})
                    self.stats["autopilot_lines"] += 1
            return
        for name in view.get("benched", []):
            if name in self.sheets and self.budget.allow(name, now):
                self.pending.append((name, "pick", self.executor.submit(self._pick, name, view["views"].get(name, {}))))
        if self.battle is not None:
            return self._battle_poll(view, now)
        for name in view.get("active", []):
            if name not in self.sheets or not self.budget.allow(name, now):
                continue                      # one gate for every call kind: banter shares the trenchie's cadence
            moment = view.get("moments", {}).get(name)
            if moment and now - self.last_banter.get(name, -10 ** 9) >= BANTER_INTERVAL_S \
                    and getattr(self.driver, "may_banter", lambda n: True)(name):
                self.last_banter[name] = now
                getattr(self.driver, "moment_used", lambda n: None)(name)
                self.pending.append((name, "banter", self.executor.submit(self._banter, name, moment)))
            else:
                self.pending.append((name, "intent", self.executor.submit(self._intent, name, view["views"].get(name, {}))))

    # --- battle mode -------------------------------------------------------------------------
    def _battle_poll(self, view, now):
        """Triggers become plan rewrites, real events become lines; everything else runs free in the engine."""
        arena = self.driver.arena
        mine = [n for n in view.get("active", []) if n in self.sheets]
        tag = lambda n: self.sheets[n]["tag"] if n in self.sheets else (arena.members[n]["profile"]["public_name"]
                                                                         if n in arena.members else n)
        self.battle.style = battle_mod.style_for(self.budget.mode)   # lean while building and after, full on judging days
        battle_mod.watch(self.battle, mine, self.sheets, arena.sim.state, arena.sim.state["events"], arena.sim.rules, now, tag)
        line_gap = battle_mod.STYLES[self.battle.style]["line_s"]
        busy = {n for n, _, _ in self.pending}
        self.pursuits.prune(mine, arena.sim.state['tick'])
        for name in mine:
            if name in busy:
                continue                                   # one call in flight per trenchie
            if self._retarget(name):
                continue                                   # one logged order; let it reach the engine before any model rewrite
            wants_plan = name not in self.battle.planned or bool(self.battle.pending.get(name))
            wants_line = (self.battle.unspoken.get(name, 0) > 0 and now - self.last_banter.get(name, -10 ** 9) >= max(BANTER_INTERVAL_S, line_gap)
                          and getattr(self.driver, "may_banter", lambda n: True)(name))
            if not (wants_plan or wants_line) or not self.budget.allow(name, now):
                continue                                   # the behaviour runs on its own: no call, no spend
            if wants_plan:
                trigger, detail = self.battle.take(name, now)
                ring = battle_mod.ring_view(name, arena.sim.state, tag)
                self.pending.append((name, "plan", self.executor.submit(self._plan, name, trigger, detail, ring)))
            else:
                self.last_banter[name] = now
                self.battle.unspoken[name] = 0
                self.pending.append((name, "line", self.executor.submit(self._line, name)))

    def _retarget(self, name):
        """Release only stale house pursuits through the existing bridge and receipt/log path."""
        game = self.driver.arena.sim
        f = game.state['fighters'].get(name)
        if f is None or game.state['tick'] - f['last_intent'] < game.rules['intent_interval']:
            return False
        result = self.pursuits.observe(name, game.state, game.rules,
                                       lambda a, b: game.target_score(a, b) >= 0 and game._may_strike(a, b))
        if result is None:
            return False
        plan, reason = result
        try:
            self._apply_battle(name, 'plan', {'behaviour': plan, 'trigger': 'stale_pursuit', 'fixed': [reason]})
        except Exception as exc:
            self.note('%s: retarget order failed (%s); last accepted plan continues' % (name, type(exc).__name__))
            self.stats['failed'] += 1
        return True

    def _plan(self, name, trigger, detail, ring):
        task = battle_mod.plan_ask(name, self.sheets, trigger, detail, ring, self.battle.behaviour.get(name),
                                   minor=battle_mod.schema_minor(self.driver.arena.sim.rules))
        data = battle_mod.parse(self._ask(name, task, "", max_tokens=450))
        behaviour = data.get("behaviour")
        if not isinstance(behaviour, dict):
            raise ValueError("the answer had no behaviour object")
        behaviour, fixed = battle_mod.engage(dict(behaviour, v=1), self.sheets[name]["game"], self.driver.arena.sim.rules)
        return {"behaviour": behaviour, "trigger": trigger, "say": battle_mod.clean_say(data.get("say")),
                "emoji": data.get("emoji"), "fixed": fixed}

    def _line(self, name):
        task = battle_mod.line_ask(name, self.sheets, self.battle)
        holder = {}

        def generate():
            data = battle_mod.parse(self._ask(name, task, "", max_tokens=60))
            holder["emoji"] = data.get("emoji")
            return battle_mod.clean_say(data.get("say")) or ""

        moments = sorted(self.voices[name].keyed)
        posted = self.voices[name].post(generate, moments[0])
        return {"text": posted["text"], "label": posted["label"], "blocked": False, "emoji": holder.get("emoji")}

    def _harvest(self):
        waiting = []
        for name, kind, future in self.pending:
            if not future.done():
                waiting.append((name, kind, future))
                continue
            try:
                result = future.result()
            except Exception as exc:                       # a failed call is an autopilot tick, said out loud
                self.note("%s: %s call failed (%s): tick policy continues" % (name, kind, described_publicly(exc)))
                print("house: %s %s call failed: %s" % (name, kind, described(exc)), file=sys.stderr, flush=True)  # the container log: the full message
                self.stats["failed"] += 1
                if not isinstance(exc, Autopilot):
                    self.failing += 1
                continue
            self.failing = 0
            self.stats[kind] += 1
            if result is not None and kind in ("plan", "line"):
                try:
                    self._apply_battle(name, kind, result)
                except Exception as exc:
                    self.note("%s: the arena refused the %s (%s): the last behaviour keeps running" % (name, kind, type(exc).__name__))
                    self.stats["failed"] += 1
            elif result is not None:
                try:
                    getattr(self.driver, "apply_" + kind)(name, result)
                except Exception as exc:                   # the arena refused the answer: said out loud, never fatal
                    self.note("%s: the arena refused the %s (%s): tick policy continues" % (name, kind, type(exc).__name__))
                    self.stats["failed"] += 1
        self.pending = waiting

    def _apply_battle(self, name, kind, result):
        if kind == "line":
            if result["text"]:
                self.driver.apply_banter(name, result)
            return
        if result.get("emoji") and hasattr(self.driver.feed, "set_voice_emoji"):
            self.driver.feed.set_voice_emoji(name, result["emoji"])      # the plan's reflex says speak with this emoji
        if result.get("fixed"):                          # the house's own engage check changed the plan: said out loud,
            n = len(result["fixed"])                     # each change in full in the behaviour log (house_fixed)
            self.engage_notes[name] = time.strftime("%Y-%m-%dT%H:%M:%SZ ", time.gmtime(self.clock())) + \
                "%s: plan changed in %d place%s so it engages" % (name, n, "" if n == 1 else "s")
        ack = self.driver.apply_behaviour(name, result["behaviour"], result["trigger"], fixed=result.get("fixed") or [])
        status = (ack or {}).get("status")
        if status in ("applied", "clipped"):
            self.battle.planned.add(name)
            self.battle.behaviour[name] = ack.get("behaviour")
        else:                                             # refused, or a host that has no behaviour input yet: said
            self.battle.planned.add(name)
            fixes = "; ".join(r.get("fix", "") for r in (ack or {}).get("refused") or [] if isinstance(r, dict))
            if status == "refused" and result["trigger"] != "refused" and fixes:   # one retry with the arena's own fix
                self.battle.fire(name, "refused", "the arena refused your last behaviour: " + fixes, self.clock())
            self.note("%s: behaviour not applied (%s)" % (name, (ack or {}).get("summary") or (ack or {}).get("code") or "no answer"))
        if result.get("say") and now_ok(self, name):
            self.last_banter[name] = self.clock()
            self.driver.apply_banter(name, {"text": result["say"], "label": None, "blocked": False, "emoji": result.get("emoji")})

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
        if self.guard is None:                              # the public feed runs the guard when it posts the line
            return {"text": posted["text"], "label": posted["label"], "blocked": False}
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
