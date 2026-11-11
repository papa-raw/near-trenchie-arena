"""Connects the house runtime to the arena server's bridge (the house wiring).

The runtime asks the model; this driver turns answers into bridge calls and the sim into small views.
Everything goes through the same GameBridge a player's room uses (reserve_life, lock_prediction, apply):
the house gets no side door. A pick locks the prediction (or an explicit no-prediction) before the life
activates; the arena activates it on its own schedule. Lines go to a public feed list. Standard library only.
"""

try:
    from . import predictions
except ImportError:
    import predictions

MOMENT_TICKS = 200                         # a moment is worth a line for 10 s
KEYED = {"ko_given": "ko_given", "ko_taken": "ko_taken", "loot": "loot"}


class ArenaDriver:
    def __init__(self, arena, bindings, log=None, feed=None, models=None, life_prefix="", feed_tick=None):
        self.arena, self.bindings = arena, dict(bindings)
        self.life_prefix = life_prefix              # makes a life id unique in a log that outlives one arena
        self.feed_tick = feed_tick                  # the feed's own clock when the feed outlives one arena
        self.behaviour_log = None                   # battle mode: called with (name, trigger, sent, ack) for every order
        self.log = log                              # a PredictionLog, or None for no log
        self.feed = feed if feed is not None else []
        self.models = models or {}
        self.sequence = {}
        self.chosen = {}                            # name -> loadout the model picked, read by pick_resolver
        self.moments = {}
        self.open_lives = {}                        # life_id -> name, for resolving the log at the life's end

    # --- reading the arena -------------------------------------------------------------
    def sync(self, control, tick, observation):
        a, state = self.arena, self.arena.sim.state
        self._events(state["events"])
        benched, active, views = [], [], {}
        for name in sorted(self.bindings):
            m = a.members.get(name)
            if m is None or m["released"]:
                continue
            f = state["fighters"].get(name)
            if f is not None and f["state"] == "alive":
                active.append(name)
                views[name] = self._view(name, f)
            elif m["awaiting_life"] and m["life_id"] not in a.locks and not m["spawn_pending"]:
                benched.append(name)
                views[name] = {"bag": sorted(f["bag"]) if f else sorted(m["profile"]["bag"]),
                               "last_life_kos": f["life_kos"] if f else 0}
        now = state["tick"]
        self.moments = {n: (m, t) for n, (m, t) in self.moments.items() if now - t <= MOMENT_TICKS}
        moments = {n: self.moments[n][0] if n in self.moments else "idle" for n in active}   # quiet ticks get the idle line
        return {"active": active, "benched": benched, "views": views, "moments": moments}

    def _view(self, name, f):
        sim_state = self.arena.sim.state["fighters"]
        near = sorted(((abs(g["x"] - f["x"]) + abs(g["y"] - f["y"]), g["id"], g) for g in sim_state.values()
                       if g["id"] != name and g["state"] == "alive"))[:3]
        return {"hp": f["hp"], "x": f["x"], "y": f["y"], "style": f["style"], "kos": f["life_kos"],
                "enemies": [{"id": g["id"], "hp": g["hp"], "dx": g["x"] - f["x"], "dy": g["y"] - f["y"],
                             "style": g["style"]} for _, _, g in near]}

    def _events(self, events):
        for e in events:
            if e["kind"] == "ko":
                if e["source"] in self.bindings:
                    self.moments[e["source"]] = (KEYED["ko_given"], self.arena.sim.state["tick"])
                if e["fighter"] in self.bindings:
                    self.moments[e["fighter"]] = (KEYED["ko_taken"], self.arena.sim.state["tick"])
                    self._resolve(e["life_id"], e["life_kos"])
            elif e["kind"] == "grab" and e["fighter"] in self.bindings:
                self.moments[e["fighter"]] = (KEYED["loot"], self.arena.sim.state["tick"])
            elif e["kind"] == "leave" and e["fighter"] in self.bindings:
                f = self.arena.sim.state["fighters"].get(e["fighter"])
                if f is not None:
                    self._resolve(f["life_id"], f["life_kos"])

    def _resolve(self, life_id, kos):
        name = self.open_lives.pop(life_id, None)
        if name is not None and self.log is not None:
            self.log.resolve(self.life_prefix + life_id, kos)

    def moment_used(self, name):
        self.moments.pop(name, None)

    # --- acting on the arena -----------------------------------------------------------
    def _next(self, name):
        self.sequence[name] = self.sequence.get(name, 0) + 1
        return str(self.sequence[name])

    def apply_intent(self, name, data):
        b, m = self.bindings[name], self.arena.members.get(name)
        if m is None:
            return None
        payload = {"fighter_id": name, "focus": data.get("focus"), "avoid": data.get("avoid"),
                   "loot": data.get("loot", "nearest"), "sig": data.get("sig", "auto"), "leave": False, "say": None}
        return self.arena.bridge.apply(b, {"kind": "intent", "payload": payload, "life_id": m["life_id"],
                                           "sequence": self._next(name)})

    def pick_resolver(self, binding, payload):
        """The arena's pick_resolver for house members: the kit the model chose, else the house kit."""
        name = binding["nft_token_id"]
        return self.chosen.pop(name, None) or {k: v for k, v in self.arena.sim.rules["house"][name]["kit"].items()}

    def apply_pick(self, name, value):
        b, m = self.bindings[name], self.arena.members.get(name)
        if m is None or m["life_id"] in self.arena.locks:
            return None
        life_id, spread, zero = m["life_id"], value["spread_pct"], value["zero_pct"]
        pick = None
        if value["prediction"]:
            if value.get("loadout"):
                kit = dict(self.arena.sim.rules["house"][name]["kit"])
                f = self.arena.sim.state["fighters"].get(name)
                bag = f["bag"] if f is not None else m["profile"]["bag"]
                try:                                # a loadout the sim would refuse is dropped, never sent
                    choice = {k: v for k, v in dict(value["loadout"]).items() if k in kit and v is not None}
                    self.arena.sim._check_kit({**kit, **choice}, bag, True)
                    self.chosen[name] = {**kit, **choice}
                except (TypeError, ValueError, KeyError, AttributeError):
                    self.chosen.pop(name, None)
            pick = {"payload": {"loadout": {"menu_row": None, "bag_serials": []},
                                "spread_bps": {k: v * 100 for k, v in zip(("one", "two", "three", "four_plus"), spread)},
                                "zero_bps": zero * 100, "moves": [], "lock": False, "stake": None}}
        lock = self.arena.bridge.lock_prediction(b, life_id, pick)
        if "code" in lock:
            return lock
        if self.log is not None:
            self.log.lock(self.life_prefix + life_id, self.arena.sim.rules_hash, name, b["account_id"], self.models.get(name, "house-model"),
                          spread if value["prediction"] else None, zero if value["prediction"] else None)
            self.open_lives[life_id] = name
        return lock

    # --- battle mode: a behaviour order, answered by the arena's ACK --------------------------
    def apply_behaviour(self, name, behaviour, trigger=None):
        """Send one behaviour (schema v1) through the same bridge a player's room uses; log the ACK whatever it says."""
        b, m = self.bindings[name], self.arena.members.get(name)
        if m is None:
            return None
        ack = self.arena.bridge.apply(b, {"kind": "behaviour", "payload": behaviour, "life_id": m["life_id"],
                                          "sequence": self._next(name)})
        if self.behaviour_log is not None:
            self.behaviour_log(name, trigger, behaviour, ack)
        return ack

    def may_banter(self, name):
        """False while the feed's one-line-per-10-s cap (in feed ticks) still holds this trenchie: no model call is spent on a
        line the feed would refuse."""
        last = getattr(self.feed, "last_tick", {}).get(name)
        if last is None:
            return True
        now = self.feed_tick() if self.feed_tick is not None else self.arena.sim.state["tick"]
        return now - last >= getattr(self.feed, "rate", 0)

    def apply_banter(self, name, value):
        tick = self.arena.sim.state["tick"]
        if hasattr(self.feed, "post"):              # the public feed: it runs the guard and the line rate itself
            return self.feed.post(name, value["text"], source="house", label=value["label"], emoji=value.get("emoji"),
                                  tick=self.feed_tick() if self.feed_tick is not None else tick)
        self.feed.append({"tick": tick, "who": name, "text": value["text"],
                          "label": value["label"], "blocked": value["blocked"]})
