"""Deterministic integer arena. No clock, I/O or model runs inside a tick."""

from dataclasses import dataclass
import hashlib
import json
from math import isqrt
from types import MappingProxyType
from collections.abc import Mapping
try:
    from .catalog import ITEMS, HOUSE
except ImportError:
    from catalog import ITEMS, HOUSE


_RULES = {
    "version": "integer-11",
    "dodge_weapon_warnings": True,
    "beam_slow_active": True,
    "rival_seek": True,
    "counter_pct": 50,
    "weapon_counters": {"lunge": "shot", "shot": "beam", "beam": "lob",
                        "lob": "swing", "swing": "zap", "zap": "lunge"},
    "signature_counters": {"chain_storm": "bubble", "bubble": "shockwave",
                           "shockwave": "blink_strike", "blink_strike": "beam_sweep",
                           "beam_sweep": "magnet", "magnet": "chain_storm"},
    "threat_sidestep": True,
    "threat_look_ticks": 12,
    "threat_margin": 200,
    "shot_hit_radius": 250,
    "shot_fire_slow": True,
    "nanoseconds_per_second": 1000000000,
    "probability_total": 10000,
    "milliseconds_per_second": 1000,
    "prediction_window_ticks": 40,
    "health_scale": 1000,
    "capacity": 16,
    "ring_min": 4,
    "ring_max": 6,
    "house_min": 2,
    "house_fill": 6,
    "snapshot_queue": 2,
    "snapshot_version": 1,
    "metrics_samples": 1200,
    "replay_workers": 2,
    "replay_cache": 8,
    "tick_hz": 20,
    "segment_ticks": 1200,
    "checkpoint_ticks": 100,
    "input_delay": 2,
    "tile": 1000,
    "radius": 12000,
    "base_hp": 100,
    "speed_per_tick": 150,
    "trig_scale": 1024,
    "quarter_turn": 90,
    "half_turn": 180,
    "full_turn": 360,
    "rng_mask": 18446744073709551615,
    "rng_increment": 11400714819323198485,
    "rng_mul_a": 13787848793156543929,
    "rng_mul_b": 10723151780598845931,
    "rng_shift_a": 30,
    "rng_shift_b": 27,
    "rng_shift_c": 31,
    "phases": ["inputs", "policy", "movement", "attacks", "projectiles",
               "damage", "grabs", "bench", "leaves"],
    "input_kinds": ["intent", "join", "leave", "disconnect", "loadout", "spawn"],
    "combat_enabled": True,
    "auto_respawn": True,
    "hitVarPct": 20,
    "percent": 100,
    "damage_divisor": 1000000,
    "soft_cap": 20,
    "stat_scale": 2,
    "damage_per_point": 3,
    "cooldown_per_point": 3,
    "hp_per_point": 5,
    "speed_per_point": 2,
    "range_per_point": 3,
    "sig_range_per_point": 2,
    "body_radius": 400,
    "separation_radius": 800,
    "edge_margin": 1000,
    "view_radius": 12000,
    "sticky_ticks": 30,
    "sticky_percent": 125,
    "focus_weight": 150,
    "avoid_weight": 200,
    "rivalry_weight": 300,
    "bounty_weight": 150,
    "recent_hit_ticks": 60,
    "credit_ticks": 100,
    "intent_interval": 40,
    "intent_stale_ticks": 300,
    "spawn_shield_ticks": 40,
    "spawn_points": 32,
    "respawn_ticks": 900,
    "disconnect_ticks": 600,
    "surf_ticks": 100,
    "surf_margin": 250,
    "grab_ticks": 6,
    "grab_radius": 500,
    "floor_ticks": 1200,
    "scatter_min": 3000,
    "scatter_max": 4000,
    "loot_interval": 200,
    "loot_rare_denominator": 6,
    "bag_capacity": 48,
    "tier_rank": {"common": 0, "rare": 1, "legendary": 2},
    "tier_value": {"common": 40, "rare": 80, "legendary": 160},
    "tier_damage_pct": {"common": 80, "rare": 100, "legendary": 120},
    "budgets": {"common": 10, "rare": 16, "legendary": 24},
    "stat_cap_pct": 40,
    "default_style": "brawler",
    "default_loadout": {"head": "st-cap", "body": "st-tee",
                        "weapon": "st-bonk", "trinket": "st-roll"},
    "styles": {"brawler": [5,2,4,1,0,0], "hunter": [2,6,1,1,0,25],
               "looter": [2,1,2,7,0,40], "guardian": [2,1,6,0,8,0],
               "survivor": [1,2,3,2,0,50]},
    "guardian_radius": 3000,
    "looter_distance": 4000,
    "survivor_reengage_ticks": 100,
    "survivor_reengage_hp_pct": 60,
    "weapons": {
        "swing": {"damage": 12, "cooldown": 16, "range": 1300, "half_arc": 60},
        "shot": {"damage": 7, "cooldown": 12, "range": 6000, "speed": 350},
        "beam": {"damage": 20, "cooldown": 34, "range": 6000, "windup": 6, "width": 400},
        "lob": {"damage": 16, "cooldown": 32, "range": 5000, "windup": 12, "radius": 1200},
        "zap": {"damage": 9, "cooldown": 20, "range": 3500, "jump_range": 2000, "targets": 3},
        "lunge": {"damage": 14, "cooldown": 24, "range": 2500}},
    "signatures": {
        "beam_sweep": {"damage": 20, "cooldown": 260, "range": 4500, "duration": 20,
                       "half_arc": 30, "width": 500},
        "chain_storm": {"damage": 30, "cooldown": 180, "range": 4000,
                        "base_targets": 2, "crowd_divisor": 4, "trigger": 3},
        "shockwave": {"damage": 12, "cooldown": 200, "range": 3000,
                      "trigger_range": 4000, "knockback": 2000, "trigger": 2, "hp_pct": 35},
        "blink_strike": {"damage": 18, "cooldown": 200, "range": 6000,
                         "vanish_ticks": 20, "recovery_ticks": 15, "hp_pct": 30, "behind": 900},
        "magnet": {"shield": 30, "cooldown": 240, "range": 4000, "pull": 2500,
                   "shield_ticks": 60, "hp_pct": 70},
        "bubble": {"shield": 30, "cooldown": 200, "range": 1000,
                   "shield_ticks": 60, "hp_pct": 50, "knockback": 1000},
        "dodge_roll": {"cooldown": 120, "range": 2000, "invulnerable_ticks": 6}},
    "item_quirks": {
        "leg-stack-sats": {"text": "Larger shield bursts, with longer waits between loot pulls.",
                           "overrides": {"shield": 33, "cooldown": 264}},
        "leg-liquidity-wave": {"text": "A bigger wipeout, a softer landing.",
                               "overrides": {"knockback": 2200, "damage": 11}},
        "leg-tinker-coil": {"text": "Tries a longer connection; each spark is a little weaker.",
                            "overrides": {"range": 4400, "damage": 27}},
        "leg-laser-eyes": {"text": "One conviction: farther ahead, less to either side.",
                           "overrides": {"range": 4950, "half_arc": 24}},
        "leg-ether-stack": {"text": "Bigger cycle ahead; healthier pullback.",
                            "overrides": {"range": 4400, "pull": 2250}},
        "leg-fast-finality": {"text": "Finalizes sooner, with a lighter stamp.",
                              "overrides": {"vanish_ticks": 16, "damage": 16}},
        "leg-lifeboat": {"text": "Conviction floats longer; the next boat takes longer.",
                         "overrides": {"shield_ticks": 66, "cooldown": 220}},
        "leg-hydra-halo": {"text": "More heads watch the sides; none sees quite as far.",
                           "overrides": {"half_arc": 36, "range": 4050}},
        "leg-loop-flywheel": {"text": "The next loop comes sooner and hits lighter.",
                              "overrides": {"cooldown": 180, "damage": 10}},
        "leg-priority-fee": {"text": "Pulls loot more often; each shield is smaller.",
                             "overrides": {"cooldown": 216, "shield": 27}},
        "leg-builder-census": {"text": "Counts one more head; gives each a smaller share.",
                               "overrides": {"base_targets": 3, "damage": 24, "cooldown": 198}},
        "leg-harvest-quake": {"text": "Reaps a wider row, with a lighter, slower stomp.",
                              "overrides": {"range": 3300, "damage": 11, "cooldown": 220}},
        "leg-poker-face": {"text": "A thinner bluff, a harder table flip.",
                           "overrides": {"shield": 27, "knockback": 1200}},
        "leg-router-drone": {"text": "Spots a finish earlier, but takes a shorter route.",
                             "overrides": {"hp_pct": 35, "range": 5400}}},
    "telegraph_ticks": 10,
    "knockback_ticks": 4,
    "knobs": {"misses": False, "looter_reengage": False, "beam_fire_slow": False,
              "melee_gap_closer": False},
    "miss_pct": 15,
    "fire_slow_pct": 50,
    "gap_closer_range": 2000,
    "gap_closer_cooldown": 100,
    "items": ITEMS,
    "house": HOUSE,
    "sine": [0,18,36,54,71,89,107,125,143,160,178,195,213,230,248,265,
             282,299,316,333,350,367,384,400,416,433,449,465,481,496,512,
             527,543,558,573,587,602,616,630,644,658,672,685,698,711,724,
             737,749,761,773,784,796,807,818,828,838,848,858,868,878,887,
             896,904,912,920,928,935,943,949,956,962,968,974,979,984,989,
             993,998,1002,1005,1008,1011,1014,1016,1018,1020,1022,1023,
             1023,1024,1024],
}


def integer_data(value):
    """Reject values with platform-dependent or non-JSON representations."""
    if value is None or type(value) in (str, int, bool):
        return
    if isinstance(value, Mapping):
        for key in sorted(value):
            if type(key) is not str:
                raise ValueError("state keys must be strings")
            integer_data(value[key])
        return
    if isinstance(value, (tuple, list)):
        for item in value:
            integer_data(item)
        return
    raise ValueError("only integer JSON data is supported")


def rules_dict(value):
    if isinstance(value, Mapping):
        return {k: rules_dict(value[k]) for k in sorted(value)}
    if isinstance(value, (tuple, list)):
        return [rules_dict(v) for v in value]
    return value


def canonical(value):
    integer_data(value)
    return json.dumps(rules_dict(value), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def freeze(value):
    integer_data(value)
    if isinstance(value, Mapping):
        return MappingProxyType({k: freeze(value[k]) for k in sorted(value)})
    if isinstance(value, (tuple, list)):
        return tuple(freeze(v) for v in value)
    return value


DEFAULT_RULES = freeze(_RULES)
del _RULES


def validate_rules(rules):
    integer_data(rules)
    for key in ("tick_hz", "segment_ticks", "checkpoint_ticks", "loot_interval", "percent", "stat_scale"):
        if type(rules[key]) is not int or rules[key] <= 0:
            raise ValueError("invalid positive rule")
    if type(rules["hitVarPct"]) is not int or not 0 <= rules["hitVarPct"] <= rules["percent"]:
        raise ValueError("invalid variance")
    for row in ordered_ids(rules["items"]):
        item = rules["items"][row]
        budget = rules["budgets"][item["tier"]]
        total = 0
        for stat in sorted(item["stats"]):
            points = item["stats"][stat]
            if type(points) is not int or points < 0 or points * rules["percent"] > budget * rules["stat_cap_pct"]:
                raise ValueError("item stat exceeds tier cap")
            total += points
        if total > budget:
            raise ValueError("item exceeds tier budget")
    for row, quirk in rules.get("item_quirks", {}).items():
        _validate_quirk(rules, row, quirk)


def _validate_quirk(rules: Mapping, row: str, quirk: Mapping) -> None:
    """Quirks can override only positive, existing signature parameters."""
    item = rules["items"].get(row)
    if item is None or item["tier"] != "legendary" or item["signature"] not in rules["signatures"]:
        raise ValueError("quirk requires a legendary signature item")
    if not isinstance(quirk, Mapping) or set(quirk) != {"text", "overrides"}:
        raise ValueError("quirk requires text and parameter overrides")
    if (type(quirk["text"]) is not str or not quirk["text"].strip()
            or not isinstance(quirk["overrides"], Mapping)):
        raise ValueError("quirk requires text and parameter overrides")
    base = rules["signatures"][item["signature"]]
    for key, value in quirk["overrides"].items():
        if key not in base or type(value) is not int or value <= 0:
            raise ValueError("quirk parameter must be an existing positive integer")


def unsigned(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(name + " must be an unsigned integer")
    return value


def ordered_ids(mapping):
    return sorted(mapping)


def distance(a, b):
    return isqrt((a["x"] - b["x"]) ** 2 + (a["y"] - b["y"]) ** 2)


def angle_to(x, y, rules):
    return max(range(rules["full_turn"]),
               key=lambda a: (x * sin_deg(a + rules["quarter_turn"], rules)
                              + y * sin_deg(a, rules), -a))


def sin_deg(angle, rules):
    if type(angle) is not int:
        raise ValueError("angle must be an integer")
    angle %= rules["full_turn"]
    sign = 1
    if angle >= rules["half_turn"]:
        angle -= rules["half_turn"]
        sign = -1
    if angle > rules["quarter_turn"]:
        angle = rules["half_turn"] - angle
    return sign * rules["sine"][angle]


def vector(angle, length, rules):
    return (length * sin_deg(angle + rules["quarter_turn"], rules) // rules["trig_scale"],
            length * sin_deg(angle, rules) // rules["trig_scale"])


def normalise(x, y, length):
    distance = isqrt(x * x + y * y)
    if not distance:
        return 0, 0
    return x * length // distance, y * length // distance


class SplitMix64:
    def __init__(self, seed, rules=DEFAULT_RULES):
        validate_rules(rules)
        self.rules = rules
        self.state = unsigned(seed, "seed")
        if seed > rules["rng_mask"]:
            raise ValueError("seed exceeds 64 bits")

    def draw(self):
        r = self.rules
        self.state = (self.state + r["rng_increment"]) & r["rng_mask"]
        z = self.state
        z = ((z ^ (z >> r["rng_shift_a"])) * r["rng_mul_a"]) & r["rng_mask"]
        z = ((z ^ (z >> r["rng_shift_b"])) * r["rng_mul_b"]) & r["rng_mask"]
        return z ^ (z >> r["rng_shift_c"])


@dataclass(frozen=True)
class Input:
    tick: int
    kind: str
    fighter_id: str
    sequence: int
    payload: Mapping

    def record(self):
        return {"tick": self.tick, "kind": self.kind, "fighter_id": self.fighter_id,
                "sequence": self.sequence, "payload": rules_dict(self.payload)}


class Sim:
    def __init__(self, seed, rules=DEFAULT_RULES):
        self.rules = freeze(rules)
        self.rules_hash = digest(self.rules)
        self.rng = SplitMix64(seed, self.rules)
        self.state = {"tick": 0, "seed": seed, "rng": seed, "rules_hash": self.rules_hash,
                      "fighters": {}, "inputs": [], "seen": {}, "objects": {},
                      "drops": {}, "damages": [], "serials": {}, "next_id": 0,
                      "events": []}
        self.checkpoints = []

    @property
    def phase_order(self):
        return self.rules["phases"]

    def export(self):
        self.state["rng"] = self.rng.state
        return json.loads(canonical(self.state))

    @classmethod
    def restore(cls, state, rules=DEFAULT_RULES):
        integer_data(state)
        game = cls(state["seed"], rules)
        if state["rules_hash"] != game.rules_hash:
            raise ValueError("rules hash mismatch")
        unsigned(state["tick"], "tick")
        game.rng = SplitMix64(state["rng"], game.rules)
        game.state = json.loads(canonical(state))
        return game

    def state_hash(self):
        return digest(self.export())

    def enqueue(self, row):
        record = row.record()
        integer_data(record)
        unsigned(row.tick, "tick")
        unsigned(row.sequence, "sequence")
        if row.kind not in self.rules["input_kinds"]:
            raise ValueError("unknown input kind")
        if type(row.fighter_id) is not str or not row.fighter_id:
            raise ValueError("fighter id is required")
        if not isinstance(row.payload, Mapping):
            raise ValueError("payload must be an object")
        identity = canonical([row.kind, row.fighter_id, row.sequence]).decode("utf-8")
        fingerprint = digest(record)
        prior = self.state["seen"].get(identity)
        if prior is not None:
            if prior != fingerprint:
                raise ValueError("changed duplicate input")
            return False
        if row.tick < self.state["tick"]:
            raise ValueError("input tick is in the past")
        self._validate_input(row)
        self.state["seen"][identity] = fingerprint
        self.state["inputs"].append(record)
        self.state["inputs"].sort(key=lambda r: (r["tick"], r["kind"],
                                                r["fighter_id"], r["sequence"]))
        return True

    def receive(self, kind, fighter_id, sequence, payload, receive_tick=None):
        if receive_tick is None:
            receive_tick = self.state["tick"]
        unsigned(receive_tick, "receive tick")
        if receive_tick != self.state["tick"]:
            raise ValueError("receive tick must be the engine clock")
        row = Input(receive_tick + self.rules["input_delay"], kind, fighter_id, sequence, payload)
        self.enqueue(row)
        return row

    def _validate_input(self, row):
        allowed = {"join": {"angle", "style", "house", "loadout", "bag", "managed", "life_id", "waiting"},
                   "intent": {"direction", "focus", "avoid", "loot", "sig", "leave", "ward"},
                   "leave": set(), "disconnect": set(), "loadout": set(self.rules["default_loadout"]),
                   "spawn": {"life_id"}}
        if set(row.payload) - allowed[row.kind]:
            raise ValueError("unknown payload field")
        for field in ("angle", "direction"):
            if field in row.payload and type(row.payload[field]) is not int:
                raise ValueError("direction must be an integer")
        p = row.payload
        if "style" in p and p["style"] not in self.rules["styles"]:
            raise ValueError("unknown style")
        for field in ("house", "managed", "leave", "waiting"):
            if field in p and type(p[field]) is not bool:
                raise ValueError("invalid boolean")
        if "loot" in p and p["loot"] not in ("nearest", "ignore"):
            raise ValueError("invalid loot order")
        if "sig" in p and p["sig"] not in ("auto", "hold", "use"):
            raise ValueError("invalid signature order")
        for field in ("focus", "avoid", "ward", "life_id"):
            if field in p and p[field] is not None and (type(p[field]) is not str or not p[field]):
                raise ValueError("invalid identifier")
        if row.kind == "join":
            self._check_kit(p.get("loadout", self.rules["default_loadout"]), p.get("bag", {}),
                            p.get("house", False))

    def _check_kit(self, loadout, bag, house=False):
        if not isinstance(bag, Mapping) or len(bag) > self.rules["bag_capacity"]:
            raise ValueError("invalid bag")
        for row in ordered_ids(bag):
            if row not in self.rules["items"] or self.rules["items"][row]["default"]:
                raise ValueError("invalid inventory row")
            entry = bag[row]
            if not isinstance(entry, Mapping) or set(entry) != {"serial", "born_batch", "kos", "hands", "flags"}:
                raise ValueError("invalid inventory entry")
            for key in sorted(entry):
                unsigned(entry[key], "inventory value")
        if not isinstance(loadout, Mapping) or set(loadout) != set(self.rules["default_loadout"]):
            raise ValueError("loadout must cover all slots")
        for slot in ordered_ids(loadout):
            row = self.rules["items"].get(loadout[slot])
            if row is None or row["slot"] != slot:
                raise ValueError("invalid slot item")
            if not house and not row["default"] and loadout[slot] not in bag:
                raise ValueError("item is not in bag")

    def run(self, ticks):
        unsigned(ticks, "ticks")
        for _ in range(ticks):
            self.step()
        return self.state_hash()

    def step(self):
        integer_data(self.state)
        unsigned(self.state["tick"], "tick")
        self.state["events"] = []
        for phase in self.phase_order:
            getattr(self, "_" + phase)()
        self.state["tick"] += 1
        self.state["rng"] = self.rng.state
        if self.state["tick"] % self.rules["checkpoint_ticks"] == 0:
            self.checkpoints.append((self.state["tick"], self.state_hash()))

    def _inputs(self):
        remaining = []
        rows = sorted(self.state["inputs"], key=lambda r: (r["tick"], r["kind"],
                                                          r["fighter_id"], r["sequence"]))
        for row in rows:
            if row["tick"] == self.state["tick"]:
                self._apply(row)
            else:
                remaining.append(row)
        self.state["inputs"] = remaining

    def _apply(self, row):
        name, kind, payload = row["fighter_id"], row["kind"], row["payload"]
        fighters = self.state["fighters"]
        if kind == "join":
            if name in fighters:
                raise ValueError("fighter already exists")
            angle = payload.get("angle")
            if angle is None:
                angle = self.rng.draw() % self.rules["full_turn"]
            x, y = vector(angle, self.rules["radius"], self.rules)
            fighters[name] = {"id": name, "x": x, "y": y, "hp": self.rules["base_hp"],
                              "direction": (angle + self.rules["half_turn"]) % self.rules["full_turn"],
                              "state": "alive", "leave": False}
            f = fighters[name]
            house_row = self.rules["house"].get(name, {}) if payload.get("house", False) else {}
            kit = payload.get("loadout", house_row.get("kit", self.rules["default_loadout"]))
            f.update(house=payload.get("house", False), style=payload.get("style", house_row.get("style", self.rules["default_style"])),
                     kit=rules_dict(kit), equipped=rules_dict(kit), bag=rules_dict(payload.get("bag", {})),
                     legendary=house_row.get("legendary"), rivals=rules_dict(house_row.get("rivals", [])),
                     intent={"focus": None, "avoid": None, "loot": "nearest", "sig": "auto", "ward": None},
                     last_intent=-self.rules["intent_interval"], target=None, target_since=0,
                     move_x=0, move_y=0, attack_at=0, sig_at=0, cast=None, shield=0, shield_ends=0,
                     shield_kind=None, shield_until=self.state["tick"] + self.rules["spawn_shield_ticks"],
                     invulnerable_until=0, cannot_attack_until=0, grab_id=None, grab_ticks=0,
                     surf_ticks=0, disconnected_until=None, respawn_at=None, hits={},
                     last_hit=None, last_damage_tick=-1, kos=0, assists=0, deaths=0, life_kos=0,
                     life_number=0, managed=payload.get("managed", False), gap_at=0, fleeing_since=None,
                     life_id=payload.get("life_id", name + ":0"), knock_x=0, knock_y=0, knock_ticks=0)
            if f["house"]:
                f["bag"] = {r: self.inventory_entry(r) for r in sorted(kit.values())
                            if not self.rules["items"][r]["default"]}
            for row in ordered_ids(f["bag"]):
                if self.rules["items"][row]["tier"] == "legendary":
                    self.state["serials"][row] = max(self.state["serials"].get(row, 0), f["bag"][row]["serial"])
            self._stats(f)
            f["hp"] = f["max_hp"]
            if payload.get("waiting"):
                f["state"] = "bench"
                f["respawn_at"] = self.state["tick"]
        elif name not in fighters:
            raise ValueError("unknown fighter")
        elif kind == "intent":
            f = fighters[name]
            if self.state["tick"] - f["last_intent"] < self.rules["intent_interval"]:
                self.state["events"].append({"kind": "intent_refused", "fighter": name})
                return
            f["last_intent"] = self.state["tick"]
            f["direction"] = payload.get("direction", f["direction"])
            for key in sorted(f["intent"]):
                if key in payload:
                    f["intent"][key] = payload[key]
            if payload.get("leave"):
                f["leave"] = True
        elif kind == "leave":
            fighters[name]["leave"] = True
            if fighters[name]["state"] == "bench":
                fighters[name]["state"] = "left"
        elif kind == "disconnect":
            fighters[name]["disconnected_until"] = self.state["tick"] + self.rules["disconnect_ticks"]
        elif kind == "loadout":
            f = fighters[name]
            if f["state"] != "bench":
                raise ValueError("loadout is closed during a life")
            chosen = {**f["kit"], **payload}
            self._check_kit(chosen, f["bag"], f["house"])
            f["kit"] = chosen
        elif kind == "spawn":
            f = fighters[name]
            if f["state"] != "bench":
                raise ValueError("fighter is not on bench")
            f["life_id"] = payload["life_id"]
            self._respawn(f)

    def _policy(self):
        if not self.rules["combat_enabled"]:
            return
        live = self._live()
        for name in live:
            f = self.state["fighters"][name]
            enemies = [self.state["fighters"][n] for n in live if n != name]
            f["move_x"], f["move_y"] = 0, 0
            if f["leave"]:
                f["move_x"], f["move_y"] = normalise(f["x"] or 1, f["y"], f["speed"])
                continue
            choices = [(self.target_score(f, e), "fighter", e["id"]) for e in enemies]
            if "rival_seek" in self.rules:
                choices = [c for c in choices if c[0] >= 0]
            if f["intent"]["loot"] != "ignore":
                for drop_id in ordered_ids(self.state["drops"]):
                    d = self.state["drops"][drop_id]
                    if not self._can_grab(f, d):
                        continue
                    dist = distance(f, d)
                    score = (self.rules["styles"][f["style"]][3]
                             * self.rules["tier_value"][self.rules["items"][d["row"]]["tier"]]
                             * max(0, self.rules["view_radius"] - dist) // self.rules["view_radius"])
                    choices.append((score, "drop", drop_id))
            if not choices:
                f["target"] = None
                continue
            best = max(choices, key=lambda c: (c[0], c[1], c[2]))
            current = next((c for c in choices if c[2] == f["target"]), None)
            if current is not None and (self.state["tick"] - f["target_since"] < self.rules["sticky_ticks"]
                                        or best[0] * self.rules["percent"] <= current[0] * self.rules["sticky_percent"]):
                best = current
            if best[2] != f["target"]:
                f["target_since"] = self.state["tick"]
            f["target"] = best[2]
            target = self.state["fighters"].get(best[2]) or self.state["drops"].get(best[2])
            dx, dy = target["x"] - f["x"], target["y"] - f["y"]
            dist = max(1, isqrt(dx * dx + dy * dy))
            preferred = self._weapon(f)["range"] * f["range_pct"] // self.rules["percent"]
            fleeing = f["hp"] * self.rules["percent"] < f["max_hp"] * self.rules["styles"][f["style"]][5]
            if f["style"] == "survivor" or (f["style"] == "looter" and self.rules["knobs"]["looter_reengage"]):
                if fleeing and f["fleeing_since"] is None:
                    f["fleeing_since"] = self.state["tick"]
                if f["fleeing_since"] is not None and self.state["tick"] - f["fleeing_since"] >= self.rules["survivor_reengage_ticks"]:
                    fleeing = False
            if fleeing and enemies:
                dx = f["x"] * len(enemies) - sum(e["x"] for e in enemies)
                dy = f["y"] * len(enemies) - sum(e["y"] for e in enemies)
            elif best[1] == "drop":
                preferred = 0
            elif f["style"] == "looter":
                preferred = self.rules["looter_distance"]
            elif f["style"] == "guardian" and f["intent"]["ward"] in live:
                ward = self.state["fighters"][f["intent"]["ward"]]
                if distance(f, ward) > self.rules["guardian_radius"]:
                    dx, dy = ward["x"] - f["x"], ward["y"] - f["y"]
                    preferred = 0
            if not fleeing and best[1] == "fighter" and dist < preferred:
                if f["style"] in ("survivor", "looter"):
                    dx, dy = -dx, -dy
                else:
                    dx, dy = 0, 0
            if best[1] == "drop" and dist <= self.rules["grab_radius"]:
                dx, dy = 0, 0
            f["move_x"], f["move_y"] = normalise(dx, dy, f["speed"])
            if self.rules.get("threat_sidestep", False):
                sx, sy = self._sidestep(f)
                if sx or sy:
                    f["move_x"], f["move_y"] = normalise(
                        sx * 2 + f["move_x"] // 2, sy * 2 + f["move_y"] // 2, f["speed"])

    def _sidestep(self, fighter: dict) -> tuple[int, int]:
        """Steer away from the soonest incoming shot, beam or lob threat."""
        choices = []
        for key in ordered_ids(self.state["objects"]):
            obj = self.state["objects"][key]
            if obj["owner"] == fighter["id"]:
                continue
            threat = self._threat(fighter, obj)
            if threat is not None:
                choices.append((*threat, key))
        if not choices:
            return 0, 0
        _, dx, dy, _ = min(choices, key=lambda t: (t[0], t[3]))
        return normalise(dx, dy, fighter["speed"])

    def _threat(self, f: dict, obj: dict) -> tuple[int, int, int] | None:
        r, tick = self.rules, self.state["tick"]
        if obj["kind"] == "lob":
            remaining = obj["resolve_at"] - tick
            dx, dy = f["x"] - obj["target_x"], f["y"] - obj["target_y"]
            if 0 <= remaining <= r["threat_look_ticks"] and isqrt(dx * dx + dy * dy) <= obj["radius"] + r["body_radius"]:
                return remaining, dx or 1, dy
            return None
        if obj["kind"] not in ("shot", "beam"):
            return None
        vx, vy = (obj["vx"], obj["vy"]) if obj["kind"] == "shot" else vector(obj["angle"], r["trig_scale"], r)
        length = max(1, isqrt(vx * vx + vy * vy))
        dx, dy = f["x"] - obj["x"], f["y"] - obj["y"]
        along, cross = dx * vx + dy * vy, vx * dy - vy * dx
        remaining = along // (length * length) if obj["kind"] == "shot" else obj["resolve_at"] - tick
        width = r["shot_hit_radius"] + r["threat_margin"] if obj["kind"] == "shot" else obj["width"]
        if along < 0 or not 0 <= remaining <= r["threat_look_ticks"] or abs(cross) > (width + r["body_radius"]) * length:
            return None
        side = 1 if cross >= 0 else -1
        return remaining, -vy * side, vx * side

    def _live(self):
        return [n for n in ordered_ids(self.state["fighters"])
                if self.state["fighters"][n]["state"] == "alive"]

    def _stats(self, f):
        r = self.rules
        points = {k: 0 for k in ("damage", "cooldown", "hp", "speed", "range")}
        for slot in ordered_ids(f["equipped"]):
            item = r["items"][f["equipped"][slot]]
            for stat in sorted(points):
                points[stat] += item["stats"][stat]
        effective = {k: min(points[k], r["soft_cap"]) * r["stat_scale"]
                     + max(0, points[k] - r["soft_cap"]) for k in sorted(points)}
        f["damage_pct"] = r["percent"] + effective["damage"] * r["damage_per_point"] // r["stat_scale"]
        f["cooldown_pct"] = r["percent"] + effective["cooldown"] * r["cooldown_per_point"] // r["stat_scale"]
        f["range_pct"] = r["percent"] + effective["range"] * r["range_per_point"] // r["stat_scale"]
        f["sig_range_pct"] = r["percent"] + effective["range"] * r["sig_range_per_point"] // r["stat_scale"]
        f["max_hp"] = r["base_hp"] + effective["hp"] * r["hp_per_point"] // r["stat_scale"]
        f["speed"] = r["speed_per_tick"] * (r["percent"] + effective["speed"] * r["speed_per_point"] // r["stat_scale"]) // r["percent"]

    def target_score(self, f, enemy):
        r = self.rules
        weights = r["styles"][f["style"]]
        dist = distance(f, enemy)
        rival = f["house"] and enemy["id"] in f["rivals"]
        if "rival_seek" in r and dist > r["view_radius"] and not (r["rival_seek"] and rival):
            return -1
        score = weights[0] * max(0, r["view_radius"] - dist) * r["percent"] // r["view_radius"]
        score += weights[1] * (enemy["max_hp"] - enemy["hp"]) * r["percent"] // enemy["max_hp"]
        prior = f["hits"].get(enemy["id"])
        if prior is not None and self.state["tick"] - prior <= r["recent_hit_ticks"]:
            score += weights[2] * r["percent"]
        ward = self.state["fighters"].get(f["intent"]["ward"])
        if ward is not None and enemy["id"] in ward["hits"]:
            if self.state["tick"] - ward["hits"][enemy["id"]] <= r["recent_hit_ticks"]:
                score += weights[4] * r["percent"]
        if rival:
            score += r["rivalry_weight"]
        if f["house"] and f["legendary"] is not None and f["legendary"] in enemy["equipped"].values():
            score += r["bounty_weight"]
        if f["intent"]["focus"] == enemy["id"]:
            score += r["focus_weight"]
        if f["intent"]["avoid"] == enemy["id"]:
            score -= r["avoid_weight"]
        return score

    def _clamp(self, fighter):
        radius = self.rules["radius"]
        if fighter["x"] ** 2 + fighter["y"] ** 2 > radius ** 2:
            fighter["x"], fighter["y"] = normalise(fighter["x"], fighter["y"], radius)
            while fighter["x"] ** 2 + fighter["y"] ** 2 > radius ** 2:
                fighter["x"] -= (fighter["x"] > 0) - (fighter["x"] < 0)
                fighter["y"] -= (fighter["y"] > 0) - (fighter["y"] < 0)

    def _movement(self):
        live = self._live()
        positions = {n: {"x": self.state["fighters"][n]["x"], "y": self.state["fighters"][n]["y"]} for n in live}
        for name in live:
            fighter = self.state["fighters"][name]
            if fighter["state"] != "alive":
                continue
            if self.rules["combat_enabled"]:
                dx, dy = fighter["move_x"], fighter["move_y"]
                for other in live:
                    if other == name:
                        continue
                    dist = distance(positions[name], positions[other])
                    if dist < self.rules["separation_radius"]:
                        push = self.rules["separation_radius"] - dist
                        px, py = normalise(positions[name]["x"] - positions[other]["x"] or (1 if name < other else -1),
                                           positions[name]["y"] - positions[other]["y"], push)
                        dx += px
                        dy += py
                radius = isqrt(fighter["x"] ** 2 + fighter["y"] ** 2)
                if not fighter["leave"] and radius > self.rules["radius"] - self.rules["edge_margin"]:
                    px, py = normalise(-fighter["x"], -fighter["y"], fighter["speed"])
                    dx += px
                    dy += py
                if dx or dy:
                    dx, dy = normalise(dx, dy, min(fighter["speed"], isqrt(dx * dx + dy * dy)))
                shot_slow = (self.rules.get("shot_fire_slow", False) and
                             self._weapon_kind(fighter) == "shot" and self.state["tick"] < fighter["attack_at"])
                if shot_slow or self.rules["knobs"]["beam_fire_slow"] and self._beam_active(fighter):
                    dx = dx * self.rules["fire_slow_pct"] // self.rules["percent"]
                    dy = dy * self.rules["fire_slow_pct"] // self.rules["percent"]
            else:
                dx, dy = vector(fighter["direction"], self.rules["speed_per_tick"], self.rules)
            if fighter["knock_ticks"]:
                dx += fighter["knock_x"]
                dy += fighter["knock_y"]
                fighter["knock_ticks"] -= 1
            fighter["x"] += dx
            fighter["y"] += dy
            self._clamp(fighter)

    def _beam_active(self, fighter: dict) -> bool:
        """A sweep telegraph, beam windup or live sweep occupies its owner."""
        if fighter["cast"] is not None and fighter["cast"]["kind"] == "beam_sweep":
            return True
        if not self.rules.get("beam_slow_active", False):
            return False
        tick = self.state["tick"]
        if self.rules.get("shot_fire_slow", False) and self._weapon_kind(fighter) == "beam" and tick < fighter["attack_at"]:
            return True
        return any(obj["owner"] == fighter["id"] and
                   (obj["kind"] == "beam" and tick <= obj["resolve_at"] or
                    obj["kind"] == "beam_sweep" and tick <= obj["until"])
                   for obj in self.state["objects"].values())

    def _attacks(self):
        if not self.rules["combat_enabled"]:
            return
        tick = self.state["tick"]
        for name in self._live():
            f = self.state["fighters"][name]
            self._expire_shield(f)
            if f["cast"] is not None and tick >= f["cast"]["resolve_at"]:
                cast = f["cast"]
                f["cast"] = None
                self._signature(f, cast)
            if tick < f["cannot_attack_until"]:
                continue
            target = self.state["fighters"].get(f["target"])
            if target is not None and target["state"] == "alive":
                weapon = self._weapon(f)
                reach = weapon["range"] * f["range_pct"] // self.rules["percent"]
                if self.rules["knobs"]["melee_gap_closer"] and self._weapon_kind(f) in ("swing", "lunge"):
                    if tick >= f["gap_at"] and reach < distance(f, target) <= reach + self.rules["gap_closer_range"]:
                        dx, dy = normalise(target["x"] - f["x"], target["y"] - f["y"], self.rules["gap_closer_range"])
                        f["x"] += dx
                        f["y"] += dy
                        self._clamp(f)
                        f["gap_at"] = tick + self.rules["gap_closer_cooldown"]
                if tick >= f["attack_at"] and distance(f, target) <= reach and f["cast"] is None:
                    f["shield_until"] = tick
                    f["attack_at"] = tick + max(1, weapon["cooldown"] * self.rules["percent"] // f["cooldown_pct"])
                    self._fire_weapon(f, target, weapon, reach)
            if f["cast"] is None and tick >= f["sig_at"]:
                item_id = f["equipped"]["trinket"]
                kind = self.rules["items"][item_id]["signature"]
                s = self._signature_rules(item_id)
                if self._should_signature(f, kind, target):
                    delay = self.rules["telegraph_ticks"]
                    if kind == "blink_strike":
                        delay += s["vanish_ticks"]
                        f["invulnerable_until"] = tick + delay
                        f["cannot_attack_until"] = tick + delay + s["recovery_ticks"]
                    f["cast"] = {"kind": kind, "resolve_at": tick + delay,
                                 "start_tick": tick, "item_id": f["equipped"]["trinket"],
                                 "target": target["id"] if target is not None else None,
                                 "x": target["x"] if target is not None else f["x"],
                                 "y": target["y"] if target is not None else f["y"]}
                    if "item_quirks" in self.rules:
                        f["cast"].update(parameters=rules_dict(s), damage_pct=f["damage_pct"],
                                         sig_range_pct=f["sig_range_pct"],
                                         tier_pct=self.rules["tier_damage_pct"][self.rules["items"][item_id]["tier"]])
                    if "snapshot_version" not in self.rules:
                        f["cast"].pop("start_tick")
                        f["cast"].pop("item_id")
                    f["sig_at"] = tick + max(1, s["cooldown"] * self.rules["percent"] // f["cooldown_pct"])
                    self.state["events"].append({"kind": "telegraph", "fighter": name, "signature": kind,
                                                 "resolve_at": tick + delay})

    def _weapon_kind(self, f):
        return self.rules["items"][f["equipped"]["weapon"]]["weapon"]

    def _weapon(self, f):
        return self.rules["weapons"][self._weapon_kind(f)]

    def _object(self, data):
        if "snapshot_version" not in self.rules:
            data.pop("item_id", None)
            data.pop("start_tick", None)
        number = self.state["next_id"]
        self.state["next_id"] += 1
        key = "object:" + str(number)
        self.state["objects"][key] = data
        return key

    def _fire_weapon(self, f, target, w, reach):
        kind = self._weapon_kind(f)
        dx, dy = target["x"] - f["x"], target["y"] - f["y"]
        f["direction"] = angle_to(dx, dy, self.rules)
        data = {"kind": kind, "owner": f["id"], "x": f["x"], "y": f["y"],
                "item_id": f["equipped"]["weapon"], "start_tick": self.state["tick"],
                "target_x": target["x"], "target_y": target["y"], "damage": w["damage"],
                "damage_pct": f["damage_pct"], "tier_pct": self.rules["percent"],
                "range": reach, "angle": f["direction"], "resolve_at": self.state["tick"]}
        if kind == "swing":
            for name in self._live():
                e = self.state["fighters"][name]
                if name != f["id"] and self._in_cone(f, e, f["direction"], reach, w["half_arc"]):
                    self.queue_hit(f["id"], name, w["damage"], f["damage_pct"], move=kind)
        elif kind == "zap":
            self._chain(f, target, w["targets"], w["jump_range"], w["damage"], self.rules["percent"])
        elif kind == "lunge":
            mx, my = normalise(dx, dy, min(reach, max(0, distance(f, target) - self.rules["body_radius"])))
            f["x"] += mx
            f["y"] += my
            self._clamp(f)
            self.queue_hit(f["id"], target["id"], w["damage"], f["damage_pct"], move=kind)
        else:
            if kind == "shot":
                data["vx"], data["vy"] = normalise(dx, dy, w["speed"])
                data["travelled"] = 0
            else:
                data["resolve_at"] += w["windup"]
                data["radius"] = w.get("radius", 0)
                data["width"] = w.get("width", 0)
            self._object(data)
        self.state["events"].append({"kind": "attack", "fighter": f["id"], "weapon": kind})

    def _in_cone(self, origin, e, angle, reach, half_arc):
        if distance(origin, e) > reach:
            return False
        vx, vy = vector(angle, self.rules["trig_scale"], self.rules)
        dx, dy = e["x"] - origin["x"], e["y"] - origin["y"]
        return dx * vx + dy * vy >= distance(origin, e) * sin_deg(half_arc + self.rules["quarter_turn"], self.rules)

    def _chain(self, f: dict, first: dict | None, count: int, jump_range: int,
               damage: int, tier_pct: int, move: str = "zap", damage_pct: int | None = None) -> None:
        if damage_pct is None:
            damage_pct = f["damage_pct"]
        visited = {f["id"]}
        current = first
        for _ in range(count):
            if current is None or current["id"] in visited or current["state"] != "alive":
                break
            visited.add(current["id"])
            self.queue_hit(f["id"], current["id"], damage, damage_pct, tier_pct, move=move)
            choices = [self.state["fighters"][n] for n in self._live() if n not in visited
                       and distance(current, self.state["fighters"][n]) <= jump_range]
            current = min(choices, key=lambda e: (distance(current, e), e["id"])) if choices else None

    def _signature_rules(self, item_id: str) -> Mapping:
        """Resolve item-local signature parameters without changing the shared table."""
        kind = self.rules["items"][item_id]["signature"]
        base = self.rules["signatures"][kind]
        override = self.rules.get("item_quirks", {}).get(item_id, {}).get("overrides", {})
        return {**base, **override}

    def _should_signature(self, f, kind, target):
        r, intent = self.rules, f["intent"]
        if intent["sig"] == "hold" and (target is None or target["id"] != intent["focus"]):
            return False
        if intent["sig"] == "use":
            return True
        s = self._signature_rules(f["equipped"]["trinket"])
        enemies = [self.state["fighters"][n] for n in self._live() if n != f["id"]]
        near = [e for e in enemies if distance(f, e) <= s["range"]]
        if kind == "beam_sweep":
            return len(near) >= 2 or target is not None and target["id"] == intent["focus"] and target in near
        if kind == "chain_storm":
            return len(near) >= min(s["trigger"], len(enemies)) and bool(near)
        if kind == "shockwave":
            near = [e for e in enemies if distance(f, e) <= s["trigger_range"]]
            return len(near) >= s["trigger"] or bool(near) and f["hp"] * r["percent"] < f["max_hp"] * s["hp_pct"]
        if kind == "blink_strike":
            return target is not None and target in near and target["hp"] * r["percent"] <= target["max_hp"] * s["hp_pct"]
        if kind == "magnet":
            return (f["hp"] * r["percent"] < f["max_hp"] * s["hp_pct"]
                    or any(self._can_grab(f, self.state["drops"][d]) and distance(f, self.state["drops"][d]) <= s["range"]
                           for d in ordered_ids(self.state["drops"])))
        if kind == "bubble":
            return f["hp"] * r["percent"] < f["max_hp"] * s["hp_pct"] and any(e["target"] == f["id"] for e in enemies)
        if r.get("dodge_weapon_warnings", False) and self._weapon_warning(f):
            return True
        casts = ((enemy, enemy["cast"]) for enemy in enemies if enemy["cast"] is not None)
        return any(distance(f, enemy) <= cast.get("parameters", r["signatures"][cast["kind"]])["range"]
                   for enemy, cast in casts)

    def _weapon_warning(self, fighter: dict) -> bool:
        """Dodge only while an enemy's unexpired weapon warning covers this body."""
        for key in ordered_ids(self.state["objects"]):
            obj = self.state["objects"][key]
            if obj["owner"] == fighter["id"] or self.state["tick"] >= obj["resolve_at"]:
                continue
            if obj["kind"] == "lob":
                if distance(fighter, {"x": obj["target_x"], "y": obj["target_y"]}) <= obj["radius"] + self.rules["body_radius"]:
                    return True
            elif obj["kind"] == "beam":
                vx, vy = vector(obj["angle"], self.rules["trig_scale"], self.rules)
                if self._on_line(obj, fighter, vx, vy, obj["range"], obj["width"] + self.rules["body_radius"]):
                    return True
        return False

    def _signature(self, f, cast):
        kind, r = cast["kind"], self.rules
        s = cast.get("parameters", r["signatures"][kind])
        tier_pct = cast.get("tier_pct", r["tier_damage_pct"][r["items"][f["equipped"]["trinket"]]["tier"]])
        damage_pct = cast.get("damage_pct", f["damage_pct"])
        target = self.state["fighters"].get(cast["target"])
        reach = s["range"] * cast.get("sig_range_pct", f["sig_range_pct"]) // r["percent"]
        f["shield_until"] = self.state["tick"]
        if kind == "beam_sweep":
            angle = angle_to(cast["x"] - f["x"], cast["y"] - f["y"], r)
            obj = {"kind": kind, "owner": f["id"], "x": f["x"], "y": f["y"],
                   "item_id": cast.get("item_id", f["equipped"]["trinket"]), "start_tick": self.state["tick"],
                   "angle": angle - s["half_arc"], "start": self.state["tick"],
                   "resolve_at": self.state["tick"], "until": self.state["tick"] + s["duration"],
                   "range": reach, "width": s["width"], "damage": s["damage"],
                   "damage_pct": damage_pct, "tier_pct": tier_pct, "hit": []}
            if "parameters" in cast:
                obj.update(half_arc=s["half_arc"], duration=s["duration"])
            self._object(obj)
        elif kind == "chain_storm":
            if target is not None and target["state"] == "alive" and distance(f, target) <= reach:
                count = s["base_targets"] + len(self._live()) // s["crowd_divisor"]
                self._chain(f, target, count, reach, s["damage"], tier_pct, move=kind, damage_pct=damage_pct)
        elif kind == "shockwave":
            for name in self._live():
                e = self.state["fighters"][name]
                if name != f["id"] and distance(f, e) <= reach:
                    self.queue_hit(f["id"], name, s["damage"], damage_pct, tier_pct, s["knockback"], move=kind)
        elif kind == "blink_strike":
            if target is not None and target["state"] == "alive" and distance(f, target) <= reach:
                dx, dy = vector(target["direction"], -s["behind"], r)
                f["x"], f["y"] = target["x"] + dx, target["y"] + dy
                self._clamp(f)
                self.queue_hit(f["id"], target["id"], s["damage"], damage_pct, tier_pct, move=kind)
        elif kind in ("magnet", "bubble"):
            f["shield"], f["shield_kind"] = s["shield"], kind
            f["shield_ends"] = self.state["tick"] + s["shield_ticks"]
            if "parameters" in cast:
                f["shield_parameters"] = rules_dict(s)
            if kind == "magnet":
                for drop_id in ordered_ids(self.state["drops"]):
                    d = self.state["drops"][drop_id]
                    if self._can_grab(f, d) and distance(f, d) <= reach:
                        d["x"], d["y"] = f["x"], f["y"]
                enemies = [self.state["fighters"][n] for n in self._live()
                           if n != f["id"] and distance(f, self.state["fighters"][n]) <= reach]
                if enemies:
                    e = min(enemies, key=lambda e: (distance(f, e), e["id"]))
                    dx, dy = normalise(f["x"] - e["x"], f["y"] - e["y"], min(s["pull"], distance(f, e)))
                    e["x"] += dx
                    e["y"] += dy
                    self._clamp(e)
        else:
            dx, dy = vector(f["direction"], reach, r)
            f["x"] += dx
            f["y"] += dy
            self._clamp(f)
            f["invulnerable_until"] = self.state["tick"] + s["invulnerable_ticks"]
        self.state["events"].append({"kind": "signature", "fighter": f["id"], "signature": kind})

    def _projectiles(self):
        tick = self.state["tick"]
        for key in ordered_ids(self.state["objects"]):
            obj = self.state["objects"][key]
            if tick < obj["resolve_at"]:
                continue
            kind = obj["kind"]
            origin = {"x": obj["x"], "y": obj["y"]}
            remove = True
            if kind == "shot":
                obj["x"] += obj["vx"]
                obj["y"] += obj["vy"]
                obj["travelled"] += isqrt(obj["vx"] ** 2 + obj["vy"] ** 2)
                candidates = [n for n in self._live() if n != obj["owner"] and
                              self._on_line(origin, self.state["fighters"][n], obj["vx"], obj["vy"],
                                            isqrt(obj["vx"] ** 2 + obj["vy"] ** 2), self.rules.get("shot_hit_radius", self.rules["body_radius"]))]
                candidates.sort(key=lambda n: (distance(origin, self.state["fighters"][n]), n))
                if candidates:
                    self._object_hit(obj, candidates[0])
                else:
                    remove = obj["travelled"] >= obj["range"]
            elif kind == "lob":
                landing = {"x": obj["target_x"], "y": obj["target_y"]}
                for name in self._live():
                    if name != obj["owner"] and distance(landing, self.state["fighters"][name]) <= obj["radius"]:
                        self._object_hit(obj, name)
            else:
                angle = obj["angle"]
                if kind == "beam_sweep":
                    s = self.rules["signatures"][kind]
                    angle += (tick - obj["start"]) * (obj.get("half_arc", s["half_arc"]) * 2) // obj.get("duration", s["duration"])
                    remove = tick >= obj["until"]
                vx, vy = vector(angle, self.rules["trig_scale"], self.rules)
                for name in self._live():
                    if name != obj["owner"] and name not in obj.get("hit", []):
                        if self._on_line(origin, self.state["fighters"][name], vx, vy, obj["range"], obj["width"]):
                            self._object_hit(obj, name)
                            if kind == "beam_sweep":
                                obj["hit"].append(name)
            if remove:
                del self.state["objects"][key]

    def _on_line(self, origin, target, vx, vy, reach, width):
        dx, dy = target["x"] - origin["x"], target["y"] - origin["y"]
        length = max(1, isqrt(vx * vx + vy * vy))
        projection = dx * vx + dy * vy
        return 0 <= projection <= reach * length and abs(dx * vy - dy * vx) <= width * length

    def _object_hit(self, obj, name):
        if self.rules["knobs"]["misses"] and obj["kind"] in ("shot", "beam", "beam_sweep"):
            if self.rng.draw() % self.rules["percent"] < self.rules["miss_pct"]:
                return
        self.queue_hit(obj["owner"], name, obj["damage"], obj["damage_pct"], obj["tier_pct"], move=obj["kind"])

    def damage_amount(self, base, damage_pct, tier_pct, taken_pct, counter_pct=None):
        d = base * damage_pct * tier_pct * taken_pct // self.rules["damage_divisor"]
        if counter_pct is not None:
            d = d * counter_pct // self.rules["percent"]
        v = self.rules["hitVarPct"]
        if v:
            d = d * (self.rules["percent"] - v + self.rng.draw() % (2 * v + 1)) // self.rules["percent"]
        return max(1, d)

    def queue_hit(self, source, target, base, damage_pct=None, tier_pct=None, knockback=0, move=None):
        p = self.rules["percent"]
        self.state["damages"].append({"source": source, "target": target, "base": base,
                                     "damage_pct": p if damage_pct is None else damage_pct,
                                     "tier_pct": p if tier_pct is None else tier_pct, "knockback": knockback})
        if "counter_pct" in self.rules:
            self.state["damages"][-1]["move"] = move

    def counter_multiplier(self, move: str | None, target: dict) -> int:
        """Each move family has one stronger and one weaker matchup."""
        r, p = self.rules, self.rules["percent"]
        table = r["weapon_counters"] if move in r["weapon_counters"] else r["signature_counters"]
        theirs = (self._weapon_kind(target) if table is r["weapon_counters"] else
                  r["items"][target["equipped"]["trinket"]]["signature"])
        if table.get(move) == theirs:
            return p + r["counter_pct"]
        if table.get(theirs) == move and move is not None:
            return p * p // (p + r["counter_pct"])
        return p

    def _damage(self):
        tick = self.state["tick"]
        for hit in sorted(self.state["damages"], key=lambda h: (h["target"], h["source"], h["base"], h["tier_pct"], h["knockback"])):
            f = self.state["fighters"].get(hit["target"])
            if f is None or f["state"] != "alive" or tick < max(f["shield_until"], f["invulnerable_until"]):
                continue
            counter = self.counter_multiplier(hit.get("move"), f) if "counter_pct" in self.rules else None
            amount = self.damage_amount(hit["base"], hit["damage_pct"], hit["tier_pct"], self.rules["percent"], counter)
            self._expire_shield(f)
            absorbed = min(f["shield"], amount)
            f["shield"] -= absorbed
            f["hp"] = max(0, f["hp"] - amount + absorbed)
            if f["shield"] == 0 and f["shield_kind"] == "bubble":
                self._pop_bubble(f)
            if f["shield"] == 0:
                f.pop("shield_parameters", None)
            f["hits"][hit["source"]] = tick
            f["last_hit"] = hit["source"]
            f["last_damage_tick"] = tick
            f["grab_ticks"], f["surf_ticks"] = 0, 0
            if hit["knockback"]:
                source = self.state["fighters"].get(hit["source"])
                if source is not None:
                    f["knock_x"], f["knock_y"] = normalise(f["x"] - source["x"], f["y"] - source["y"],
                                                          hit["knockback"] // self.rules["knockback_ticks"])
                    f["knock_ticks"] = self.rules["knockback_ticks"]
            self.state["events"].append({"kind": "hit", "source": hit["source"], "target": f["id"], "damage": amount})
            if "counter_pct" in self.rules:
                self.state["events"][-1]["move"] = hit.get("move")
            if f["hp"] == 0:
                self._ko(f)
                if "counter_pct" in self.rules:
                    self.state["events"][-1]["move"] = hit.get("move")
        self.state["damages"] = []

    def _expire_shield(self, f):
        if f["shield"] and self.state["tick"] >= f["shield_ends"]:
            f["shield"] = 0
            if f["shield_kind"] == "bubble":
                self._pop_bubble(f)
            f.pop("shield_parameters", None)
            f["shield_kind"] = None

    def _pop_bubble(self, f):
        f["shield_kind"] = None
        s = f.pop("shield_parameters", self.rules["signatures"]["bubble"])
        radius = s["range"]
        for name in self._live():
            e = self.state["fighters"][name]
            if name != f["id"] and distance(f, e) <= radius:
                e["knock_x"], e["knock_y"] = normalise(e["x"] - f["x"], e["y"] - f["y"],
                                                       s["knockback"] // self.rules["knockback_ticks"])
                e["knock_ticks"] = self.rules["knockback_ticks"]

    def inventory_entry(self, row):
        return {"serial": 0, "born_batch": 0, "kos": 0, "hands": 0, "flags": 0}

    def drop_item(self, row, x, y, owner, house, entry=None, origin="ko"):
        key = "drop:" + str(self.state["next_id"])
        self.state["next_id"] += 1
        self.state["drops"][key] = {"row": row, "x": x, "y": y, "owner": owner,
                                    "house": house, "origin": origin, "entry": entry or self.inventory_entry(row),
                                    "created_at": self.state["tick"],
                                    "expires_at": self.state["tick"] + self.rules["floor_ticks"]}
        self._clamp(self.state["drops"][key])
        return key

    def _ko(self, f):
        tick = self.state["tick"]
        killer = f["last_hit"]
        if killer in self.state["fighters"] and tick - f["hits"][killer] <= self.rules["credit_ticks"]:
            attacker = self.state["fighters"][killer]
            attacker["kos"] += 1
            attacker["life_kos"] += 1
            for row in sorted(attacker["equipped"].values()):
                if row in attacker["bag"]:
                    attacker["bag"][row]["kos"] += 1
        for name in ordered_ids(f["hits"]):
            if name != killer and name in self.state["fighters"] and tick - f["hits"][name] <= self.rules["credit_ticks"]:
                self.state["fighters"][name]["assists"] += 1
        droppable = [row for row in sorted(f["equipped"].values()) if not self.rules["items"][row]["default"]]
        if droppable:
            row = droppable[self.rng.draw() % len(droppable)]
            angle = self.rng.draw() % self.rules["full_turn"]
            length = self.rules["scatter_min"] + self.rng.draw() % (self.rules["scatter_max"] - self.rules["scatter_min"] + 1)
            dx, dy = vector(angle, length, self.rules)
            entry = f["bag"].pop(row, self.inventory_entry(row))
            self.drop_item(row, f["x"] + dx, f["y"] + dy, f["id"], f["house"], entry)
        f["deaths"] += 1
        f["state"] = "left" if f["leave"] else "bench"
        f["respawn_at"] = tick + self.rules["respawn_ticks"]
        f["cast"] = None
        self.state["events"].append({"kind": "ko", "fighter": f["id"], "source": killer,
                                     "life_id": f["life_id"], "life_kos": f["life_kos"]})

    def _grabs(self):
        tick = self.state["tick"]
        for key in ordered_ids(self.state["drops"]):
            if tick >= self.state["drops"][key]["expires_at"]:
                self.state["events"].append({"kind": "floor_loss", "drop": key})
                del self.state["drops"][key]
        if tick and tick % self.rules["loot_interval"] == 0:
            tier = "rare" if self.rng.draw() % self.rules["loot_rare_denominator"] == 0 else "common"
            rows = [row for row in ordered_ids(self.rules["items"])
                    if self.rules["items"][row]["tier"] == tier and
                    (not self.rules["items"][row]["default"] if tier == "rare" else row.startswith("c-"))]
            row = rows[self.rng.draw() % len(rows)]
            angle = self.rng.draw() % self.rules["full_turn"]
            length = isqrt(self.rng.draw() % (self.rules["radius"] ** 2))
            x, y = vector(angle, length, self.rules)
            self.drop_item(row, x, y, None, True, origin="arena")
        for name in self._live():
            f = self.state["fighters"][name]
            if f["last_damage_tick"] == tick or f["intent"]["loot"] == "ignore":
                continue
            eligible = [key for key in ordered_ids(self.state["drops"])
                        if self._can_grab(f, self.state["drops"][key])
                        and distance(f, self.state["drops"][key]) <= self.rules["grab_radius"]]
            if not eligible:
                f["grab_id"], f["grab_ticks"] = None, 0
                continue
            key = min(eligible, key=lambda k: (distance(f, self.state["drops"][k]), k))
            if f["grab_id"] != key:
                f["grab_id"], f["grab_ticks"] = key, 0
            f["grab_ticks"] += 1
            if f["grab_ticks"] >= self.rules["grab_ticks"]:
                d = self.state["drops"].pop(key)
                row = d["row"]
                item = self.rules["items"][row]
                duplicate = row in f["bag"]
                if not duplicate and not item["default"]:
                    entry = d["entry"]
                    if item["tier"] == "legendary" and not entry["serial"]:
                        self.state["serials"][row] = self.state["serials"].get(row, 0) + 1
                        entry["serial"] = self.state["serials"][row]
                    entry["hands"] += d["owner"] != f["id"]
                    f["bag"][row] = entry
                if not duplicate:
                    slot = item["slot"]
                    current = self.rules["items"][f["equipped"][slot]]
                    if self.rules["tier_rank"][item["tier"]] > self.rules["tier_rank"][current["tier"]]:
                        f["equipped"][slot] = row
                        old_max = f["max_hp"]
                        self._stats(f)
                        f["hp"] = min(f["max_hp"], f["hp"] + max(0, f["max_hp"] - old_max))
                self.state["events"].append({"kind": "grab", "fighter": name, "row": row,
                                             "destroyed": duplicate, "pending": True})
                f["grab_id"], f["grab_ticks"] = None, 0

    def _can_grab(self, f, drop):
        return not (f["house"] and not drop["house"]) and (drop["row"] in f["bag"]
                or self.rules["items"][drop["row"]]["default"] or len(f["bag"]) < self.rules["bag_capacity"])

    def _bench(self):
        if not self.rules["auto_respawn"]:
            return
        for name in ordered_ids(self.state["fighters"]):
            f = self.state["fighters"][name]
            if f["state"] == "bench" and not f["managed"] and self.state["tick"] >= f["respawn_at"]:
                self._respawn(f)

    def _respawn(self, f):
        r = self.rules
        f.pop("shield_parameters", None)
        if f["house"]:
            f["bag"] = {row: self.inventory_entry(row) for row in sorted(f["kit"].values())
                        if not r["items"][row]["default"]}
        for slot in ordered_ids(f["equipped"]):
            row = f["kit"][slot]
            f["equipped"][slot] = row if r["items"][row]["default"] or row in f["bag"] else r["default_loadout"][slot]
        live = [self.state["fighters"][n] for n in self._live() if n != f["id"]]
        points = [vector(index * r["full_turn"] // r["spawn_points"], r["radius"], r)
                  for index in range(r["spawn_points"])]
        best = max(enumerate(points), key=lambda p: (min((distance({"x":p[1][0], "y":p[1][1]}, e)
                                                        for e in live), default=r["radius"]), -p[0]))[1]
        f["x"], f["y"] = best
        self._clamp(f)
        self._stats(f)
        f.update(state="alive", hp=f["max_hp"], shield_until=self.state["tick"] + r["spawn_shield_ticks"],
                 shield=0, shield_kind=None, cast=None, attack_at=self.state["tick"], sig_at=self.state["tick"],
                 target=None, life_kos=0, hits={}, last_hit=None, grab_id=None, grab_ticks=0, surf_ticks=0,
                 knock_ticks=0, fleeing_since=None)
        f["life_number"] += 1
        if not f["managed"]:
            f["life_id"] = f["id"] + ":" + str(f["life_number"])
        self.state["events"].append({"kind": "respawn", "fighter": f["id"], "life_id": f["life_id"]})

    def _leaves(self):
        for name in ordered_ids(self.state["fighters"]):
            f = self.state["fighters"][name]
            if f["disconnected_until"] is not None and self.state["tick"] >= f["disconnected_until"]:
                f["leave"] = True
            if f["leave"] and f["state"] == "bench":
                f["state"] = "left"
            if f["leave"] and f["state"] == "alive":
                radius = isqrt(f["x"] ** 2 + f["y"] ** 2)
                if radius >= self.rules["radius"] - self.rules["surf_margin"] and f["last_damage_tick"] != self.state["tick"]:
                    f["surf_ticks"] += 1
                    if f["surf_ticks"] >= self.rules["surf_ticks"]:
                        f["state"] = "left"
                        f["cast"] = None
                        self.state["events"].append({"kind": "leave", "fighter": name})
                else:
                    f["surf_ticks"] = 0
