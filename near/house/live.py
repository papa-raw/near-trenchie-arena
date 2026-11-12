"""The live house: the 14 house personas on the NEAR AI Cloud model, composed into an arena host.

LiveHouse has the shape the arena's house hook calls (`binding(name)`, `poll(control, tick, roster,
count, view)`), so a host swaps it in for its deterministic house with one switch. It seats house members
through the same bridge a player's room uses, but it does not lock their lives itself: the model's respawn
pick locks the prediction, and if no valid pick arrives before the deadline the arena locks an explicit
no-prediction. The sim never waits on the model.

What it composes, all under one data directory:
- runtime.Runtime on runtime.NearAI (DeepSeek V4.1 Flash, thinking off), under runtime.Budget's daily cap,
  80% cadence drop and $77 hard stop; the meter is `<data>/house/spend.json`.
- driver.ArenaDriver, posting banter to the shared feed.PublicFeed (the guard runs there) and logging
  each life to predictions.PredictionLog at `<data>/house/predictions.jsonl`.
- status.StatusWriter: the private `<data>/house/status.json` and the public `roster.json` projection.

The model key is read from the environment variable named by key_env, never from a file in the repo,
and is never written anywhere. Without it a LiveHouse refuses to start: the host's default house is the
deterministic one, which needs no key. Standard library only.
"""

import copy
import os
from pathlib import Path

try:
    from . import battle as battle_mod, driver as driver_mod, msggraph, predictions, runtime, sheets as sheets_mod, status
except ImportError:
    import battle as battle_mod
    import driver as driver_mod
    import msggraph
    import predictions
    import runtime
    import sheets as sheets_mod
    import status

KEY_ENV = "NEARAI_API_KEY"
# The public name of the house model: the room protocol's Label refuses "/", so the API id is not shown as is.
MODEL_LABEL = runtime.MODEL.split("/")[-1] + " on NEAR AI Cloud"


KEYED_LABEL = "no model key: keyed lines only"


class KeyMissing(RuntimeError):
    pass


class NoModel:
    """The keyed house's client: there is no model, so a call is a bug, never a quiet stand-in answer."""
    model = None

    def chat(self, messages, thinking=False, max_tokens=200):
        raise RuntimeError("the keyed house makes no model call")


class _NoMeter:
    def today_for(self, day, who):
        return 0


class NoKeyBudget:
    """A budget that is always stopped: the house fights on its tick policy and posts only labelled keyed lines."""
    meter = _NoMeter()

    def day(self, now=None):
        return 0

    def state(self, now=None):
        return {"mode": "no_key", "interval_s": None, "autopilot": True, "chip": "autopilot (no model key)",
                "spent_today_microusd": 0, "cap_microusd": 0, "total_microusd": 0}

    def allow(self, name, now):
        return False

    def charge(self, usage, now=None, who=None):
        raise RuntimeError("the keyed house makes no model call")


def members_of(arena, sheets, house_model, spend=lambda name: 0, cpm=lambda name: 0):
    """Every admitted member of an arena, private fields included (for status.json only; never served).

    House members carry their sheet's full name, the house model and their own metered spend; a player carries
    its own public name and model, and its spend is never read here (the host never holds it)."""
    rows = []
    for name, m in sorted(arena.members.items()):
        if m["released"]:
            continue
        f = arena.sim.state["fighters"].get(name)
        state = "alive" if f is not None and f["state"] == "alive" else "left" if f is not None and f["state"] == "left" else "bench"
        house = bool(m["profile"]["house"])
        rows.append({"id": name, "persona": sheets[name]["name"] if house and name in sheets else m["profile"]["public_name"],
                     "model": house_model if house else m["profile"]["model"], "state": state,
                     "life": m["life_number"], "house": house,
                     "spend_today_microusd": spend(name) if house else 0, "calls_per_min": cpm(name) if house else 0})
    return rows


def public_roster_of(arena, sheets, house_model, chip=None, budget_state=None, spend=lambda name: 0):
    """The public projection served to the arena page: status.public_roster plus the house's chip and day meter."""
    out = status.public_roster(members_of(arena, sheets, house_model, spend))
    out.update(house_model=house_model, chip=chip, budget_mode=budget_state["mode"] if budget_state else None,
               house_spend_today_microusd=budget_state["spent_today_microusd"] if budget_state else 0,
               house_cap_today_microusd=budget_state["cap_microusd"] if budget_state else 0)
    return out


class LiveHouse:
    def __init__(self, context, data_dir, feed, *, account_id, mode="auto", key_env=KEY_ENV, client=None,
                 clock=None, executor=None, log=None, sheets=None, life_prefix=None, budget=None, feed_tick=None,
                 model_label=None, battle=False):
        if client is None:
            if not os.environ.get(key_env):
                raise KeyMissing("--house live needs the model key in %s (load the env file outside the repo into the "
                                 "process environment); the default house needs no key" % key_env)
            client = runtime.NearAI(key_env=key_env)
        import time
        self.context, self.account_id = context, account_id
        self.clock = clock or time.time
        self.dir = Path(data_dir) / "house"
        self.feed = feed
        self.sheets = sheets if sheets is not None else sheets_mod.load()
        self.model = model_label or MODEL_LABEL
        self.battle = battle                    # battle mode: behaviours, rewrites on triggers, event lines
        self.host_feed_tick = feed_tick         # a host whose feed outlives one arena may pass its own increasing tick
        self.feed_base = 0
        self.budget = budget or runtime.Budget(runtime.JsonMeter(self.dir / "spend.json"), mode, clock=self.clock)
        self.log = log if log is not None else predictions.PredictionLog(self.dir)
        self.status = status.StatusWriter(self.dir)
        # the message graph: one {t, sender, receiver, len} line per public feed line and per prediction line
        self.graph = msggraph.attach(msggraph.MsgGraph(self.dir / "msggraph.jsonl", self.clock), feed, self.log)
        self.client = client
        self.executor = executor
        self.life_prefix = life_prefix          # None: each attached arena's own run name (attach), as its players' lives
        self.arena = None
        self.driver = None
        self.runtime = None
        self.cursor = 0
        self.extra_members = lambda: []             # the host adds its players' public rows here

    # --- the host's hook ---------------------------------------------------------------
    def binding(self, name):
        return {"context": copy.deepcopy(self.context), "grant_id": "grant:" + name, "session_key_id": "key:" + name,
                "member_id": name, "nft_token_id": name, "persona_digest": "a" * 64,
                "account_id": self.account_id, "slot_id": name, "generation": "1"}

    def attach(self, arena):
        """Bind to a new arena (a host may start a new round): a fresh driver and runtime, the same meter, log and feed."""
        self.arena = arena
        # The feed outlives an arena, whose tick restarts at 0. Without a host clock, this arena's feed clock starts
        # just after the feed's latest line, so it never goes back and the line rate holds across a restart.
        high = getattr(self.feed, "high_tick", -1)
        self.feed_base = high + 1 if high >= 0 and arena.sim.state["tick"] <= high else 0
        bindings = {n: self.binding(n) for n in self.sheets}
        self.driver = driver_mod.ArenaDriver(arena, bindings, log=self.log, feed=self.feed,
                                             models={n: self.model for n in self.sheets}, life_prefix=self.prefix_for(arena),
                                             feed_tick=self.feed_clock)
        self.driver.behaviour_log = self._log_behaviour
        if self.feed is not None and getattr(self.feed, "game_of", None) is None:
            self.feed.game_of = lambda who: self.sheets[who]["game"] if who in self.sheets else None
        self.runtime = runtime.Runtime(self.client, self.budget, None, self.sheets, self.driver, self.clock,
                                       executor=self.executor, battle=self.battle)
        return self

    def prefix_for(self, arena):
        """The house's lives go in the log under the same key the arena gives its players' lives (server._log_key): the
        arena's run name, which differs in every round and every host start, so a restart on the same state dir never
        meets a key the log already holds. Rows written before keep their keys."""
        if self.life_prefix is not None:
            return self.life_prefix
        run = getattr(arena, "record_run", None)
        return (run if run is not None else self.context.get("deployment_id", "")) + "/"

    def _log_behaviour(self, name, trigger, sent, ack):
        """Every behaviour order and the arena's answer, one JSON line each, under the data directory (no prompt, no key)."""
        import json
        ack = ack or {}
        row = {"t": round(self.clock(), 3), "persona": name, "trigger": trigger, "status": ack.get("status") or ack.get("code"),
               "summary": ack.get("summary"), "applied": ack.get("behaviour"), "sent": sent,
               "clipped": ack.get("clipped"), "refused": ack.get("refused")}
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / "behaviours.jsonl", "a") as f:
            f.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")

    def seat_order(self, roster):
        """Battle mode seats each seeded rival pair one after the other, so a rival is in the ring when its rival is and the
        plans' rival reflexes can fire (alphabetical seating left every rival pair apart). Everyone still rotates."""
        out, placed = [], set()
        for name in roster:
            if name in placed:
                continue
            out.append(name)
            placed.add(name)
            for other in battle_mod.relations(self.sheets[name]["game"])[0] if name in self.sheets else ():
                if other in roster and other not in placed:
                    out.append(other)
                    placed.add(other)
        return tuple(out)

    def feed_clock(self):
        """The tick every line this house posts carries: the host's clock when it has one, else this arena's tick
        after the feed's own last line. A host's other producers (player say lines) should post on the same clock."""
        if self.host_feed_tick is not None:
            return self.host_feed_tick()
        return self.feed_base + self.arena.sim.state["tick"]

    def pick_resolver(self, binding, payload):
        return self.driver.pick_resolver(binding, payload)

    def poll(self, control, tick, roster, count, view):
        bridge = self.arena.bridge
        if not any(n.startswith("dev-") for n in self.arena.members):   # keep one ring seat free for a DEV joiner
            seats = self.arena.sim.rules["ring_max"] - 1
            count = min(count, seats - sum(m["profile"]["house"] for m in self.arena.members.values()))
        roster = self.seat_order(roster) if self.battle else roster
        for step in range(len(roster)):
            if count <= 0:
                break
            name = roster[(self.cursor + step) % len(roster)]
            if name in self.arena.members or name not in self.sheets:
                continue
            if "life_id" in bridge.reserve_life(self.binding(name)):
                count -= 1
                self.cursor = (self.cursor + step + 1) % len(roster)
        for name, m in sorted(self.arena.members.items()):     # no valid pick by the deadline: an explicit no-prediction
            if (name in self.sheets and m["awaiting_life"] and not m["spawn_pending"] and not m["released"]
                    and m["life_id"] not in self.arena.locks and tick >= m["deadline_tick"]):
                bridge.lock_prediction(m["binding"], m["life_id"], None)
        self.runtime.poll(control, tick, roster, count, view)
        self.status.maybe_write(self.members(), self.clock())

    # --- what the host serves -----------------------------------------------------------
    @property
    def chip(self):
        return self.runtime.chip if self.runtime else None

    def _spend(self, name):
        return self.budget.meter.today_for(self.budget.day(), name)

    def members(self):
        """Every admitted member, private fields included (status.json only; never served)."""
        return members_of(self.arena, self.sheets, self.model, self._spend,
                          lambda n: self.runtime.calls_per_min(n) if self.runtime else 0)

    def public_roster(self):
        state = self.budget.state()
        chip = self.runtime.chip if self.runtime else state["chip"]   # the budget's chip, or the failing-calls chip
        out = public_roster_of(self.arena, self.sheets, self.model, chip, state, self._spend)
        out["battle_style"] = battle_mod.style_for(self.budget.mode) if self.battle and hasattr(self.budget, "mode") else None
        out["cap_period"] = getattr(self.budget, "mode", None)                  # building | soak | judging | after
        out["period_source"] = getattr(self.budget, "source", None)             # "calendar", or "override" (--budget)
        out["notes"] = self.notes()                  # every fallback said out loud, each with its UTC time: slug, call kind, the error and its message
        return out

    def notes(self):
        return list(self.runtime.notes[-5:]) if self.runtime else []
