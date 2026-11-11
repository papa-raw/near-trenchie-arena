"""Battle-mode behaviour schema v1: validation, normalisation and the ACK receipt.

A fighter's AI sends a behaviour (drives, an attack gate, a target mode and up to 8 reflexes). The host calls
`ack()` once per order: it normalises the behaviour, lists every clip and refusal with its fix, and writes the
plain receipt line. The engine logs and runs only the normalised form, which is a fixed point of `normalise()`,
so a replay never re-runs a clip. The schema text is BEHAVIOUR.md beside this file.

No clock, I/O or randomness here: the same input always gives the same answer.
"""

from collections.abc import Mapping
import json
import re

VERSION = 1
DRIVE_WEIGHTS = ("loot", "keep_away", "chase", "protect", "hold")
DRIVE_KEYS = DRIVE_WEIGHTS + ("keep_away_radius", "protect_ally", "hold_at", "hold_radius")
GATE_KEYS = ("match", "never", "target_hp_below_pct", "target_busy", "distance_under", "rival", "wears_legendary")
GATE_FLAGS = ("target_busy", "rival", "wears_legendary")
TARGET_MODES = ("auto", "nearest", "weakest", "attacker")
CONDITIONS = ("self_hp_below_pct", "self_hp_above_pct", "enemy_within", "enemies_at_least", "hit_recently",
              "ally_hit_recently", "loot_within", "legendary_on_floor", "target_hp_below_pct", "no_target")
CONDITIONS += ("always", "hit_by")                                   # schema v1.1, additive
CONDITION_FLAGS = ("hit_recently", "ally_hit_recently", "legendary_on_floor", "no_target", "always")
WHO = ("any", "rival", "ally_attacker")
ACTIONS = ("stance", "drives", "gate", "target", "say", "repeat")
TOP_KEYS = ("v", "stance", "drives", "gate", "target", "reflexes", "clear")
ID_CHARS = re.compile(r"[A-Za-z0-9._:@-]+")             # a fighter id: house slugs, dev- names, token ids


def _id_ok(value, cap):
    return type(value) is str and 1 <= len(value) <= cap and ID_CHARS.fullmatch(value) is not None


def _id_rule(cap):
    return f"1 to {cap} characters of letters, digits and . _ : @ -"


class _Report:
    def __init__(self):
        self.clipped, self.refused, self.notes = [], [], []

    def refuse(self, path, code, fix):
        self.refused.append({"path": path, "code": code, "fix": fix})

    def clip(self, path, sent, value, fix):
        self.clipped.append({"path": path, "sent": sent, "set": value, "fix": fix})


def _limits(rules):
    return rules["behaviour"]


def _is_int(value):
    return type(value) is int


def _ranged(value, low, high, path, name, report, unit=""):
    """An integer in [low, high]; out of range is clipped, a wrong type refused."""
    if not _is_int(value):
        report.refuse(path, "not_integer", f"{name} must be a whole number from {low} to {high}{unit}")
        return None
    if value < low or value > high:
        bound = low if value < low else high
        sign = "<" if value < low else ">"
        word = "min" if value < low else "max"
        report.clip(path, value, bound, f"{name} {value} {sign} {word} {bound}{unit}: set to {bound}")
        return bound
    return value


def _flag(value, path, name, report):
    if type(value) is not bool:
        report.refuse(path, "not_boolean", f"{name} must be true or false")
        return None
    return value


def _ident(value, path, name, report, rules, fighter_id):
    cap = _limits(rules)["id_chars"]
    if not _id_ok(value, cap):
        report.refuse(path, "bad_id", f"{name} must be a fighter id: {_id_rule(cap)}")
        return None
    if value == fighter_id:
        report.refuse(path, "self", f"{name} cannot be the fighter itself ({fighter_id})")
        return None
    return value


def _unknown(keys, allowed, path, report):
    extra = sorted(k for k in keys if k not in allowed)
    for key in extra:
        where = f"{path}.{key}" if path else str(key)
        report.refuse(where, "unknown_key", f"unknown key {key!r}; use one of {', '.join(allowed)}")
    return bool(extra)


def _ring_point(x, y, radius):
    """Pull a point onto the ring edge with the engine's own integer rounding."""
    from math import isqrt
    if x * x + y * y <= radius * radius:
        return x, y
    d = isqrt(x * x + y * y)
    x, y = x * radius // d, y * radius // d
    while x * x + y * y > radius * radius:
        x -= (x > 0) - (x < 0)
        y -= (y > 0) - (y < 0)
    return x, y


def _drives(raw, path, report, rules, fighter_id):
    """Validate a drives object, keeping only the keys sent."""
    lim = _limits(rules)
    out = {}
    if not isinstance(raw, Mapping):
        report.refuse(path, "not_object", "drives must be an object such as {\"loot\": 10}")
        return out
    if _unknown(raw, DRIVE_KEYS, path, report):
        return out
    for key in DRIVE_WEIGHTS:
        if key in raw:
            out[key] = _ranged(raw[key], 0, lim["drive_max"], f"{path}.{key}", key, report)
    if "keep_away_radius" in raw:
        out["keep_away_radius"] = _ranged(raw["keep_away_radius"], 1, lim["radius_max_tiles"],
                                          f"{path}.keep_away_radius", "keep_away_radius", report, " tiles")
    if "hold_radius" in raw:
        out["hold_radius"] = _ranged(raw["hold_radius"], 1, lim["hold_radius_max_tiles"],
                                     f"{path}.hold_radius", "hold_radius", report, " tiles")
    if "protect_ally" in raw:
        out["protect_ally"] = (None if raw["protect_ally"] is None else
                               _ident(raw["protect_ally"], f"{path}.protect_ally", "protect_ally", report, rules, fighter_id))
    if "hold_at" in raw:
        at = raw["hold_at"]
        if at in ("center", "here"):
            out["hold_at"] = at
        elif isinstance(at, Mapping) and set(at) == {"x_milli", "y_milli"} and all(_is_int(at[k]) for k in at):
            x, y = _ring_point(at["x_milli"], at["y_milli"], rules["radius"])
            if (x, y) != (at["x_milli"], at["y_milli"]):
                report.clip(f"{path}.hold_at", {"x_milli": at["x_milli"], "y_milli": at["y_milli"]},
                            {"x_milli": x, "y_milli": y},
                            f"hold_at is off the ring: moved onto its edge at ({x}, {y})")
            out["hold_at"] = {"x_milli": x, "y_milli": y}
        else:
            report.refuse(f"{path}.hold_at", "bad_hold_at",
                          "hold_at must be \"center\", \"here\" or {\"x_milli\": int, \"y_milli\": int}")
    return out


def _gate(raw, path, report, rules):
    """Normalised gate: the match word plus only the conditions that are on."""
    lim = _limits(rules)
    if not isinstance(raw, Mapping):
        report.refuse(path, "not_object", "gate must be an object; {} lets any target through")
        return None
    if _unknown(raw, GATE_KEYS, path, report):
        return None
    out = {"match": "all"}
    if "match" in raw:
        if raw["match"] not in ("all", "any"):
            report.refuse(f"{path}.match", "bad_match", "match must be \"all\" or \"any\"")
        else:
            out["match"] = raw["match"]
    if "target_hp_below_pct" in raw:
        out["target_hp_below_pct"] = _ranged(raw["target_hp_below_pct"], 1, 99, f"{path}.target_hp_below_pct",
                                             "target_hp_below_pct", report, "%")
    if "distance_under" in raw:
        out["distance_under"] = _ranged(raw["distance_under"], 1, lim["radius_max_tiles"], f"{path}.distance_under",
                                        "distance_under", report, " tiles")
    for key in GATE_FLAGS:
        if key in raw and _flag(raw[key], f"{path}.{key}", key, report):
            out[key] = True
    if "never" in raw and _flag(raw["never"], f"{path}.never", "never", report):
        if len(out) > 1 or out["match"] != "all":
            report.notes.append(f"{path}.never: the fighter attacks no one, so the other gate conditions are dropped")
        return {"match": "all", "never": True}
    return out


def _target(raw, path, report, rules, fighter_id):
    if raw in TARGET_MODES:
        return raw
    if type(raw) is str and raw:
        return _ident(raw, path, "target", report, rules, fighter_id)
    if type(raw) is str:
        report.refuse(path, "bad_target", f"target must be one of {', '.join(TARGET_MODES)} or a fighter id")
        return None
    report.refuse(path, "bad_target", f"target must be one of {', '.join(TARGET_MODES)} or a fighter id")
    return None


def _stance(name, path, report, rules):
    stances = _limits(rules)["stances"]
    if type(name) is not str or name not in stances:
        report.refuse(path, "unknown_stance", f"unknown stance {name!r}; use one of {', '.join(sorted(stances))}")
        return None
    return stances[name]


def _condition(raw, path, report, rules):
    lim = _limits(rules)
    if not isinstance(raw, Mapping) or len(raw) != 1:
        report.refuse(path, "one_condition", f"if must hold exactly one condition, one of {', '.join(CONDITIONS)}")
        return None
    (key, value), = raw.items()
    if key not in CONDITIONS:
        report.refuse(path, "unknown_condition", f"unknown condition {key!r}; use one of {', '.join(CONDITIONS)}")
        return None
    where = f"{path}.{key}"
    if key in CONDITION_FLAGS:
        if value is not True:
            report.refuse(where, "flag_true", f"{key} takes true")
            return None
        return {key: True}
    if key in ("self_hp_below_pct", "self_hp_above_pct", "target_hp_below_pct"):
        out = _ranged(value, 1, 99, where, key, report, "%")
    elif key == "loot_within" or key == "enemy_within" and not isinstance(value, Mapping):
        out = _ranged(value, 1, lim["radius_max_tiles"], where, key, report, " tiles")
    elif key == "enemy_within":
        return _enemy_within(value, where, report, rules)
    elif key == "hit_by":
        if not isinstance(value, Mapping) or set(value) != {"who"}:
            report.refuse(where, "bad_hit_by", "hit_by takes {\"who\": \"any\" | \"rival\" | <fighter id>}")
            return None
        who = _who(value["who"], where + ".who", report, rules, ("any", "rival"))
        out = None if who is None else {"who": who}
    else:
        if not isinstance(value, Mapping) or set(value) != {"count", "radius"}:
            report.refuse(where, "bad_crowd", "enemies_at_least takes {\"count\": 2-15, \"radius\": 1-12}")
            return None
        count = _ranged(value["count"], 2, rules["capacity"] - 1, where + ".count", "count", report)
        radius = _ranged(value["radius"], 1, lim["radius_max_tiles"], where + ".radius", "radius", report, " tiles")
        out = None if count is None or radius is None else {"count": count, "radius": radius}
    return None if out is None else {key: out}


def _who(value, path, report, rules, words):
    """A who filter: one of `words`, or a fighter id."""
    cap = _limits(rules)["id_chars"]
    if type(value) is str and (value in words or _id_ok(value, cap) and value not in WHO):
        return value
    report.refuse(path, "bad_who", f"who must be one of {', '.join(words)} or a fighter id: {_id_rule(cap)}")
    return None


def _enemy_within(value, where, report, rules):
    """v1's whole-number radius, or v1.1's {"radius", "who"}; who "any" is stored as the v1 number."""
    if set(value) != {"radius", "who"}:
        report.refuse(where, "bad_enemy_within",
                      "enemy_within takes tiles, or {\"radius\": 1-12, \"who\": \"any\" | \"rival\" | \"ally_attacker\" | <id>}")
        return None
    radius = _ranged(value["radius"], 1, _limits(rules)["radius_max_tiles"], where + ".radius", "radius", report, " tiles")
    who = _who(value["who"], where + ".who", report, rules, WHO)
    if radius is None or who is None:
        return None
    return {"enemy_within": radius if who == "any" else {"radius": radius, "who": who}}


def _expand(stance_name, preset, drives, gate, target):
    """A stance fills values in; the keys sent beside it win, key by key."""
    out = {}
    if stance_name is not None:
        out["stance"] = stance_name
    out["drives"] = {**preset["drives"], **drives} if preset else dict(drives)
    if gate is not None:
        out["gate"] = gate
    elif preset:
        out["gate"] = dict(preset["gate"])
    if target is not None:
        out["target"] = target
    elif preset:
        out["target"] = preset["target"]
    return out


def _then(raw, path, report, rules, fighter_id):
    lim = _limits(rules)
    if not isinstance(raw, Mapping) or not raw:
        report.refuse(path, "no_action", f"then must hold at least one action, from {', '.join(ACTIONS)}")
        return None
    if _unknown(raw, ACTIONS, path, report):
        return None
    preset = _stance(raw["stance"], path + ".stance", report, rules) if "stance" in raw else None
    drives = _drives(raw["drives"], path + ".drives", report, rules, fighter_id) if "drives" in raw else {}
    gate = _gate(raw["gate"], path + ".gate", report, rules) if "gate" in raw else None
    target = _target(raw["target"], path + ".target", report, rules, fighter_id) if "target" in raw else None
    out = _expand(raw.get("stance") if preset else None, preset, drives, gate, target)
    if not out["drives"]:
        del out["drives"]
    if "say" in raw:
        text = raw["say"]
        cap = lim["say_chars"]
        if type(text) is not str or not text.strip() or not text.isprintable():
            report.refuse(path + ".say", "bad_say", f"say must be one printable line of 1 to {cap} characters")
        else:
            text = text.strip()
            if len(text) > cap:
                report.clip(path + ".say", len(text), cap, f"say is {len(text)} characters > max {cap}: cut to {cap}")
                text = text[:cap].rstrip()
            out["say"] = text
    if "repeat" in raw:
        if "say" not in raw:
            report.refuse(path + ".repeat", "repeat_needs_say", "repeat goes with a say line: add \"say\": \"...\"")
        elif _flag(raw["repeat"], path + ".repeat", "repeat", report):
            out["repeat"] = True
    return out


def _defaults(rules):
    return dict(_limits(rules)["default_drives"])


def _size(value):
    return len(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _reflexes(rows, report, rules, fighter_id):
    """At most `max_reflexes` well-formed reflexes; extras are clipped, malformed ones refused."""
    if not isinstance(rows, (list, tuple)):
        report.refuse("reflexes", "not_list", "reflexes must be a list of {\"if\": {...}, \"then\": {...}}")
        return []
    cap = _limits(rules)["max_reflexes"]
    if len(rows) > cap:
        report.clip("reflexes", len(rows), cap, f"{len(rows)} reflexes > max {cap}: kept the first {cap}")
        rows = rows[:cap]
    out = []
    for index, row in enumerate(rows):
        path = f"reflexes[{index + 1}]"
        if not isinstance(row, Mapping) or set(row) != {"if", "then"}:
            report.refuse(path, "bad_reflex", "a reflex is {\"if\": {<one condition>}, \"then\": {<actions>}}")
            continue
        cond = _condition(row["if"], path + ".if", report, rules)
        then = _then(row["then"], path + ".then", report, rules, fighter_id)
        if cond is not None and then is not None:
            out.append({"if": cond, "then": then})
    return out


def _check_allies(body, stance, report):
    """protect (in the drives, a follow-ally stance or a reflex) needs a named ally."""
    d = body["drives"]
    if (d["protect"] > 0 or stance == "follow-ally") and d.get("protect_ally") is None:
        report.refuse("drives.protect_ally", "needs_ally", "protect needs an ally: add \"protect_ally\": \"<fighter id>\"")
    for index, row in enumerate(body["reflexes"]):
        lay = row["then"].get("drives", {})
        if lay.get("protect", 0) > 0 and lay.get("protect_ally", d.get("protect_ally")) is None:
            report.refuse(f"reflexes[{index + 1}].then.drives.protect_ally", "needs_ally",
                          "this reflex protects but no ally is named: add drives.protect_ally to the behaviour")


def _add_notes(body, present, report):
    """Applied as sent, but worth saying: an absent ally or target, or every drive at 0."""
    d = body["drives"]
    if present is not None:
        names = set(present)
        if d.get("protect_ally") is not None and d["protect_ally"] not in names:
            report.notes.append(f"protect_ally {d['protect_ally']} is not in the ring now; protect waits for it")
        if body["target"] not in TARGET_MODES and body["target"] not in names:
            report.notes.append(f"target {body['target']} is not in the ring now; the target waits for it")
    if not any(d[k] for k in DRIVE_WEIGHTS):
        report.notes.append("every drive is 0: the fighter stands its ground and fights what the gate lets into reach")


def _envelope(raw, report, lim):
    """The checks before any field: an object of plain JSON within the size limit."""
    if not isinstance(raw, Mapping):
        report.refuse("", "not_object", "send a JSON object such as {\"v\": 1, \"stance\": \"loot\"}")
        return False
    try:
        size = _size(raw)
    except (TypeError, ValueError):
        report.refuse("", "not_json", "send plain JSON: objects, lists, strings, whole numbers, true/false")
        return False
    if size > lim["max_bytes"]:
        report.refuse("", "too_large", f"the behaviour is {size} bytes > max {lim['max_bytes']}: shorten it")
        return False
    return True


def normalise(raw, rules, fighter_id, present=None):
    """Return (behaviour or None, clipped, refused, notes).

    `present` is an optional collection of the fighter ids in the ring now; it only adds notes. A behaviour with
    any refusal is None: nothing changes and the previous behaviour keeps running.
    """
    report = _Report()
    if not _envelope(raw, report, _limits(rules)):
        return None, report.clipped, report.refused, report.notes
    _unknown(raw, TOP_KEYS, "", report)
    if raw.get("v") != VERSION or type(raw.get("v")) is not int:
        report.refuse("v", "version", "set \"v\": 1")
    if "clear" in raw:
        if raw["clear"] is not True or set(raw) != {"v", "clear"}:
            report.refuse("clear", "clear_alone", "send exactly {\"v\": 1, \"clear\": true} to drop the behaviour")
        out = None if report.refused else {"v": VERSION, "clear": True}
        return out, report.clipped, report.refused, report.notes
    preset = _stance(raw["stance"], "stance", report, rules) if "stance" in raw else None
    drives = _drives(raw["drives"], "drives", report, rules, fighter_id) if "drives" in raw else {}
    gate = _gate(raw["gate"], "gate", report, rules) if "gate" in raw else None
    target = _target(raw["target"], "target", report, rules, fighter_id) if "target" in raw else None
    body = _expand(raw.get("stance") if preset else None, preset, drives, gate, target)
    body["drives"] = {**_defaults(rules), **body["drives"]}
    body.setdefault("gate", {"match": "all"})
    body.setdefault("target", "auto")
    body["reflexes"] = _reflexes(raw["reflexes"], report, rules, fighter_id) if "reflexes" in raw else []
    if report.refused:                                   # a refused field may be None: check allies on clean values only
        return None, report.clipped, report.refused, report.notes
    _check_allies(body, raw.get("stance"), report)
    if report.refused:
        return None, report.clipped, report.refused, report.notes
    _add_notes(body, present, report)
    return {"v": VERSION, **body}, report.clipped, report.refused, report.notes


def check_stored(value, rules, fighter_id):
    """The engine's guard: accept only a normalised behaviour (a fixed point with no clip or refusal)."""
    out, clipped, refused, _ = normalise(value, rules, fighter_id)
    if refused or clipped or out != _plain(value):
        raise ValueError("behaviour is not in normalised form; send it through behaviour.normalise first")


def _plain(value):
    if isinstance(value, Mapping):
        return {k: _plain(value[k]) for k in value}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


# ---- the plain receipt line -------------------------------------------------------------------------------

_COND_TEXT = {
    "self_hp_below_pct": "hp < {}%", "self_hp_above_pct": "hp > {}%", "enemy_within": "an enemy within {} tiles",
    "hit_recently": "hit in the last 3 s", "ally_hit_recently": "ally hit in the last 3 s",
    "loot_within": "loot within {} tiles", "legendary_on_floor": "a legendary on the floor",
    "target_hp_below_pct": "target hp < {}%", "no_target": "no target passes the gate", "always": "always",
}


def _gate_text(gate):
    if gate.get("never"):
        return "never attacks"
    parts = []
    if "target_hp_below_pct" in gate:
        parts.append(f"hp below {gate['target_hp_below_pct']}%")
    if gate.get("target_busy"):
        parts.append("busy")
    if "distance_under" in gate:
        parts.append(f"within {gate['distance_under']} tiles")
    if gate.get("rival"):
        parts.append("rival")
    if gate.get("wears_legendary"):
        parts.append("wears a legendary")
    if not parts:
        return "any target"
    return (" and " if gate.get("match", "all") == "all" else " or ").join(parts)


def _at_text(at):
    return at if isinstance(at, str) else f"({at['x_milli']}, {at['y_milli']})"


def _drives_text(d, clipped_from, prefix=""):
    parts = []
    for key in DRIVE_WEIGHTS:
        if key not in d or not d[key]:
            continue
        text = f"{key} {d[key]}"
        if f"{prefix}{key}" in clipped_from:
            text += f" (clipped from {clipped_from[prefix + key]})"
        extra = []
        if key == "keep_away" and "keep_away_radius" in d:
            r = f"radius {d['keep_away_radius']}"
            if f"{prefix}keep_away_radius" in clipped_from:
                r += f", clipped from {clipped_from[prefix + 'keep_away_radius']}"
            extra.append(r)
        if key == "protect" and d.get("protect_ally"):
            extra.append(f"ally {d['protect_ally']}")
        if key == "hold":
            if "hold_at" in d:
                extra.append(_at_text(d["hold_at"]))
            if "hold_radius" in d:
                extra.append(f"radius {d['hold_radius']}")
        if extra:
            text += " (" + ", ".join(extra) + ")"
        parts.append(text)
    return parts


def _then_text(then):
    parts = []
    if "stance" in then:
        parts.append(f"stance {then['stance']}")
        say = [f"say “{then['say']}”" + (" every 10 s" if then.get("repeat") else "")] if "say" in then else []
        return " + ".join(parts + say)
    if "drives" in then:
        parts += _drives_text(then["drives"], {}) or [", ".join(f"{k} {v}" for k, v in sorted(then["drives"].items()))]
    if "gate" in then:
        parts.append(f"gate {_gate_text(then['gate'])}")
    if "target" in then:
        parts.append(f"target {then['target']}")
    if "say" in then:
        parts.append(f"say “{then['say']}”" + (" every 10 s" if then.get("repeat") else ""))
    return " + ".join(parts)


def _cond_text(cond):
    (key, value), = cond.items()
    if key == "enemies_at_least":
        return f"{value['count']}+ enemies within {value['radius']} tiles"
    if key == "enemy_within" and isinstance(value, Mapping):
        who = {"rival": "a rival", "ally_attacker": "the ally's attacker"}.get(value["who"], value["who"])
        return f"{who} within {value['radius']} tiles"
    if key == "hit_by":
        who = {"any": "anyone", "rival": "a rival"}.get(value["who"], value["who"])
        return f"hit by {who} in the last 3 s"
    return _COND_TEXT[key].format(value)


def _when(apply_tick, receive_tick, rules):
    ms = (apply_tick - receive_tick) * rules["milliseconds_per_second"] // rules["tick_hz"]
    return f"applies at tick {apply_tick:,} (in {ms // 1000}.{ms % 1000 // 100} s)", ms


def summary(behaviour, clipped, refused, notes, apply_tick, receive_tick, rules):
    if refused:
        first = refused[0]
        more = f" (+{len(refused) - 1} more)" if len(refused) > 1 else ""
        where = f"{first['path']}: " if first["path"] else ""
        return f"Refused: {where}{first['fix']}{more} · nothing changed; your last behaviour stays"
    when, _ = _when(apply_tick, receive_tick, rules)
    if behaviour.get("clear"):
        return f"Behaviour cleared: back to the style's own AI · {when}"
    clipped_from = {c["path"].split("drives.", 1)[-1]: c["sent"] for c in clipped if c["path"].startswith("drives.")}
    parts = []
    if behaviour.get("stance"):
        parts.append(f"stance {behaviour['stance']}")
    parts += _drives_text(behaviour["drives"], clipped_from) or ["no drives (stands its ground)"]
    parts.append(f"attack gate: {_gate_text(behaviour['gate'])}")
    parts.append(f"target {behaviour['target']}")
    if behaviour["reflexes"]:
        for i, row in enumerate(behaviour["reflexes"], 1):
            parts.append(f"reflex {i}: if {_cond_text(row['if'])} then {_then_text(row['then'])}")
    else:
        parts.append("no reflexes")
    others = [c["fix"] for c in clipped if not c["path"].startswith("drives.")]
    if others:
        parts.append("clipped: " + "; ".join(others))
    parts += notes
    parts.append(when)
    parts.append("persists across respawns")
    return "New behaviour recorded: " + " · ".join(parts)


def ack(raw, rules, fighter_id, seq, receive_tick, last_order_tick=None, present=None, rules_hash=None):
    """The host's ACK frame for one behaviour order (the host adds its signature).

    `last_order_tick` is the apply tick of this fighter's last accepted order (behaviour or intent); the engine
    refuses an order within `intent_interval` ticks of it, so the receipt says so first.
    """
    if rules_hash is None:
        try:
            from . import sim
        except ImportError:
            import sim
        rules_hash = sim.digest(rules)
    apply_tick = receive_tick + rules["input_delay"]
    behaviour, clipped, refused, notes = normalise(raw, rules, fighter_id, present)
    if last_order_tick is not None and apply_tick - last_order_tick < rules["intent_interval"]:
        ready = last_order_tick + rules["intent_interval"] - rules["input_delay"]
        ms = rules["intent_interval"] * rules["milliseconds_per_second"] // rules["tick_hz"]
        refused = [{"path": "", "code": "order_rate",
                    "fix": f"one order per {ms // 1000}.{ms % 1000 // 100} s: send it again at tick {ready:,} or later"}] + refused
        behaviour = None
    status = "refused" if refused else ("clipped" if clipped else "applied")
    applied = status != "refused"
    _, ms = _when(apply_tick, receive_tick, rules)
    return {"type": "behaviour_ack", "v": VERSION, "fighter": fighter_id, "seq": seq, "status": status,
            "receive_tick": receive_tick, "apply_tick": apply_tick if applied else None,
            "applies_in_ms": ms if applied else None, "behaviour": behaviour,
            "clipped": clipped, "refused": refused, "notes": notes,
            "summary": summary(behaviour, clipped, refused, notes, apply_tick, receive_tick, rules),
            "rules_hash": rules_hash}
