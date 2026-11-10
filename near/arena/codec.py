"""The compact int-array snapshot codec (W14, Python half). The JS decode lives in web/.

Two frame kinds, both JSON text and both made once per tick and sent as identical bytes to every spectator:

  tables  ["T", table_id, names, rows, signatures, kinds]      sent on connect and whenever table_id changes
  tick    [version, tick, table_id, F, D, O, C, E]             every tick

F, D, O and C are flat arrays of integers (stride below); E is the tick's event list, usually empty.
Names, item rows, signatures and object kinds are indexes into the tables frame.

  F stride 13  name, x, y, hp, direction, status(0 alive,1 bench,2 left), target(-1 none), sig_cooldown,
               row_body, row_head, row_trinket, row_weapon, shield
  D stride 5   id, row, x, y, expires_at          (id is the number in "drop:<id>")
  O stride 14  id, kind, x, y, resolve_at, target_x, target_y, vx, vy, range, angle, until, radius, width
  C stride 5   name, signature, resolve_at, x, y

decode() rebuilds exactly the structure of server.encode_snapshot, so one test pins the two together.
Standard library only; integers only.
"""

import json

try:
    from . import sim
except ImportError:
    import sim

STATUS = {"alive": 0, "bench": 1, "left": 2}
F_STRIDE, D_STRIDE, O_STRIDE, C_STRIDE = 13, 5, 14, 5
SLOTS = ("body", "head", "trinket", "weapon")          # sorted order of the equipped slots


def tables_for(game):
    rules, state = game.rules, game.state
    names = sim.ordered_ids(state["fighters"])
    rows = sim.ordered_ids(rules["items"])
    sigs = sorted(rules["signatures"])
    kinds = sorted(set(rules["weapons"]) | set(rules["signatures"]))
    table_id = int(sim.digest([names, rows, sigs, kinds])[:8], 16)
    return {"table_id": table_id, "names": names, "rows": rows, "signatures": sigs, "kinds": kinds}


def encode_tables(tables):
    return json.dumps(["T", tables["table_id"], tables["names"], tables["rows"], tables["signatures"], tables["kinds"]],
                      separators=(",", ":")).encode()


def _num(key, prefix):
    head, _, tail = key.partition(":")
    if head != prefix or not tail.isdigit():
        raise ValueError("unexpected key %r" % key)
    return int(tail)


def encode_tick(game, tables):
    """The per-tick frame as bytes; raises when the roster changed and the tables are stale."""
    state, rules = game.state, game.rules
    if tables["names"] != sim.ordered_ids(state["fighters"]):
        raise ValueError("stale tables: send a tables frame first")
    ni = {n: i for i, n in enumerate(tables["names"])}
    ri = {r: i for i, r in enumerate(tables["rows"])}
    si = {s: i for i, s in enumerate(tables["signatures"])}
    ki = {k: i for i, k in enumerate(tables["kinds"])}
    F, D, O, C = [], [], [], []
    for name in tables["names"]:
        f = state["fighters"][name]
        F += [ni[name], f["x"], f["y"], f["hp"], f["direction"], STATUS[f["state"]], ni.get(f["target"], -1),
              max(0, f["sig_at"] - state["tick"])]
        F += [ri[f["equipped"][slot]] for slot in SLOTS]
        F.append(f["shield"])
        if f["cast"] is not None:
            c = f["cast"]
            C += [ni[name], si[c["kind"]], c["resolve_at"], c["x"], c["y"]]
    for key in sim.ordered_ids(state["drops"]):
        d = state["drops"][key]
        D += [_num(key, "drop"), ri[d["row"]], d["x"], d["y"], d["expires_at"]]
    for key in sim.ordered_ids(state["objects"]):
        o = state["objects"][key]
        O += [_num(key, "object"), ki[o["kind"]], o["x"], o["y"], o["resolve_at"], o.get("target_x", o["x"]),
              o.get("target_y", o["y"]), o.get("vx", 0), o.get("vy", 0), o["range"], o["angle"],
              o.get("until", o["resolve_at"]), o.get("radius", 0), o.get("width", 0)]
    return json.dumps([rules.get("snapshot_version", 1), state["tick"], tables["table_id"], F, D, O, C, state["events"]],
                      separators=(",", ":"), sort_keys=True).encode()


def decode_tick(data, tables):
    """Rebuild the encode_snapshot structure; a frame for other tables is refused."""
    version, tick, table_id, F, D, O, C, events = json.loads(data)
    if table_id != tables["table_id"]:
        raise ValueError("table_id changed: wait for the tables frame")
    names, rows, sigs, kinds = tables["names"], tables["rows"], tables["signatures"], tables["kinds"]
    if len(F) % F_STRIDE or len(D) % D_STRIDE or len(O) % O_STRIDE or len(C) % C_STRIDE:
        raise ValueError("array length is not a whole number of records")
    fighters = [[F[i], F[i + 1], F[i + 2], F[i + 3], F[i + 4], F[i + 5], F[i + 6], F[i + 7], F[i + 8:i + 12], F[i + 12]]
                for i in range(0, len(F), F_STRIDE)]
    drops = [["drop:%d" % D[i], D[i + 1], D[i + 2], D[i + 3], D[i + 4]] for i in range(0, len(D), D_STRIDE)]
    objects = [["object:%d" % O[i], kinds[O[i + 1]]] + O[i + 2:i + O_STRIDE] for i in range(0, len(O), O_STRIDE)]
    casts = [C[i:i + C_STRIDE] for i in range(0, len(C), C_STRIDE)]
    return [version, tick, names, rows, fighters, drops, objects, casts, events]
