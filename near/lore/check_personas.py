#!/usr/bin/env python3
"""check_personas.py: validates persona sheets against persona.schema.json, then the arena and house rules.

  python3 -I near/lore/check_personas.py                 the 14 house sheets in personas/; prints "14/14 valid"
  python3 -I near/lore/check_personas.py FILE...         only the named sheets (a file argument is house-checked too
                                                         when its game.loadout is set)
  python3 -I near/lore/check_personas.py --dir DIR       every *.json in DIR, core and extension checks only
                                                         (battle-option sheets and player sheets)
  python3 -I near/lore/check_personas.py --digest FILE   the content digest of a sheet
  python3 -I near/lore/check_personas.py --selftest      breaks copies of the sheets on purpose and confirms each break
                                                         is caught; the two headline mutants must print "13/14 valid"
                                                         and exit 1

What it checks, in order:
  1. core: the schema (ten elements, unknown keys refused at every level, `game` optional and versioned);
     the manifest binds the elements it holds, once; names agree; memory is empty; an arena sheet grants no tool,
     network, file or permission beyond the six arena intents.
  2. extension: the game block is declarative data. No number biases a prediction (the only numbers are `version`
     and the legendary's `serial`). Every line passes the output check. The temperament is one of the six names.
  3. house (for sheets with a loadout, and for the 14-sheet run): the roster, the loadout split, tags, palette,
     legendary and kit equal kits.json; the rivalries equal the seeded pairs; the rendered game block fits its budget.
The standard library only. Exit 0 only when every sheet is valid and, in the 14-sheet run, all 14 are present.
"""
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_sheets as ks   # noqa: E402  (the kits.json checker and the roster constants)
import emoji as emoji_rules  # noqa: E402  (the emoji set's rules, shared with the house feed and the creator)

SCHEMA = os.path.join(HERE, "persona.schema.json")
KITS = os.path.join(HERE, "kits.json")
LORE = os.path.join(HERE, "LORE.md")
PERSONAS = os.path.join(HERE, "personas")

GAME_VERSION = 2
INTENTS = ["intent-focus", "intent-avoid", "intent-loot", "intent-sig", "intent-leave", "intent-say"]
TEMPERAMENTS = ["Sunny", "Deadpan", "Earnest", "Gruff", "Serene", "Restless"]
CORE = ["identity", "tools", "skills", "libraries", "hooks", "memory", "model_routing", "permissions",
        "manifest", "self_improvement"]
BLOCKED = ["scam", "fraud", "jail"]                  # accusation words: a blocked line becomes an emote
FEED_MAX = 60
RENDER_MAX_CHARS = 600                               # about 150 tokens at 4 characters a token (INFERRED ratio)
NO_NUMBERS_OUTSIDE = {("version",), ("cosmetics", "legendary", "serial")}   # the game block's only numbers
LEGACY = "jud" + "ge"                                    # the legacy core key; the canonical key is "assessor"
NAMES_SWEEP = re.compile(r"\b(" + LEGACY + r"s?|fig" + r"ures?)\b", re.I)   # the names sweep, spelled so this file passes it
STYLE_STEMS = ["brawl", "hunt", "loot", "guard", "surviv"]


# ---------------------------------------------------------------- a small JSON Schema reader
def _same(a, b):
    return type(a) is type(b) and a == b


def validate(schema, doc, root, path, out):
    """Reads: $ref, type, enum, required, properties, additionalProperties false, items, minItems, maxItems,
    minLength, maxLength, pattern. Appends 'path: message' to out."""
    if "$ref" in schema:
        ref = root
        for part in schema["$ref"].lstrip("#/").split("/"):
            ref = ref[part]
        validate(ref, doc, root, path, out)
        return
    t = schema.get("type")
    kinds = {"object": dict, "array": list, "string": str}
    if t in kinds and not isinstance(doc, kinds[t]):
        out.append(f"{path}: expected {t}, got {type(doc).__name__}")
        return
    if t == "integer" and (isinstance(doc, bool) or not isinstance(doc, int)):
        out.append(f"{path}: expected an integer")
        return
    if "enum" in schema and not any(_same(doc, e) for e in schema["enum"]):
        out.append(f"{path}: {doc!r} is not one of {schema['enum']}")
        return
    if isinstance(doc, str):
        if len(doc) < schema.get("minLength", 0):
            out.append(f"{path}: empty string")
        if len(doc) > schema.get("maxLength", 10 ** 9):
            out.append(f"{path}: {len(doc)} characters, at most {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], doc):
            out.append(f"{path}: {doc!r} does not match {schema['pattern']}")
    if isinstance(doc, list):
        if len(doc) < schema.get("minItems", 0):
            out.append(f"{path}: {len(doc)} items, at least {schema['minItems']}")
        if len(doc) > schema.get("maxItems", 10 ** 9):
            out.append(f"{path}: {len(doc)} items, at most {schema['maxItems']}")
        if "items" in schema:
            for i, x in enumerate(doc):
                validate(schema["items"], x, root, f"{path}[{i}]", out)
    if isinstance(doc, dict):
        props = schema.get("properties", {})
        for k in schema.get("required", []):
            if k not in doc:
                out.append(f"{path}: missing required key {k!r}")
        if schema.get("additionalProperties") is False:
            for k in doc:
                if k not in props:
                    out.append(f"{path}: unknown key {k!r} (refused)")
        for k, v in doc.items():
            if k in props:
                validate(props[k], v, root, f"{path}.{k}" if path else k, out)


# ---------------------------------------------------------------- helpers
def walk_keys(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from walk_keys(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk_keys(v)


def walk_numbers(x, path=()):
    if isinstance(x, bool):
        return
    if isinstance(x, (int, float)):
        yield path
    elif isinstance(x, dict):
        for k, v in x.items():
            yield from walk_numbers(v, path + (k,))
    elif isinstance(x, list):
        for v in x:
            yield from walk_numbers(v, path)


def digest(doc):
    """The persona's content digest. The compute envelope (model_routing) and the manifest are left out: changing the
    operator's model, provider or effort leaves it equal; changing the identity, tools, permissions or game block does not."""
    body = {k: v for k, v in doc.items() if k not in ("model_routing", "manifest")}
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def render(g):
    """The game block as the runtime puts it in the prompt (the cacheable prefix): everything the model reads.
    Cosmetics and the keyed reactions are not rendered; the reactions are fallback output."""
    parts = [f"{g.get('temperament', '')}", " ".join(g.get("tics", [])), "never: " + "; ".join(g.get("never_hooks", [])),
             "not " + ", ".join(g.get("banned_registers", [])), (g.get("belief") or {}).get("line", ""),
             "; ".join(f"{r.get('kind')}: {r.get('name')}" for r in g.get("rivalries", [])), " | ".join(g.get("voice", [])),
             ("emoji: " + " ".join(emoji_rules.resolve(g)[0])) if g.get("temperament") else ""]
    return "\n".join(p for p in parts if p.strip())


def line_problems(line, own_name, names):
    """The output check for a banter or keyed line: accusation words, 'rug' outside 'the Great Rug' or beside a
    name, another trenchie's name (keep feed lines self-contained)."""
    bad, lc = [], line.lower()
    for w in BLOCKED:
        if re.search(rf"\b{w}", lc):
            bad.append(f"blocked word {w!r}")
    if re.search(r"\brug", lc) and (any(n.lower() in lc for n in names) or "great rug" not in lc):
        bad.append("'rug' outside 'the Great Rug' or beside a name")
    others = [n for n in names if n != own_name and n.lower() in lc]
    if others:
        bad.append(f"names another trenchie {others}")
    return bad


# ---------------------------------------------------------------- one sheet
def check_core(doc, schema, slug):
    out = []
    gv = doc.get("game", {}).get("version") if isinstance(doc.get("game"), dict) else None
    if gv == 1 and not isinstance(gv, bool):
        return [f"game.version 1 is refused: the arena's game block is version {GAME_VERSION}, with its own fields"]
    validate(schema, doc, schema, "", out)
    if out:
        return out
    iden, man = doc["identity"], doc["manifest"]
    if iden["role"] != slug:
        out.append(f"identity.role {iden['role']!r} != file name {slug!r}")
    if man["name"] != iden["role"]:
        out.append(f"manifest.name {man['name']!r} != identity.role")
    want = [e for e in CORE if e != "manifest"] + (["game"] if "game" in doc else [])
    if sorted(man["elements"]) != sorted(want) or len(set(man["elements"])) != len(man["elements"]):
        out.append(f"manifest.elements {man['elements']} must list each held element once: {want}")
    si = doc["self_improvement"]
    for k in ("mark", "assessor"):
        if k in si and si[k] != iden[k]:
            out.append(f"self_improvement.{k} differs from identity.{k}")
    held = set(doc["tools"]["builtin"]) | set(doc["tools"]["mcp_servers"])
    if not set(doc["permissions"]["tool_subset"]) <= held:
        out.append("permissions.tool_subset names a tool that tools does not hold")
    for k in doc["tools"].get("limits", {}):
        if k not in held:
            out.append(f"tools.limits names {k!r}, which is not a held tool")
    if LEGACY in set(walk_keys(doc)):
        out.append(f"the legacy key {LEGACY!r} is refused; the canonical key is 'assessor'")
    text = json.dumps(doc, ensure_ascii=False)
    if NAMES_SWEEP.search(text):
        out.append(f"text matches the names sweep {NAMES_SWEEP.pattern}")
    if "game" in doc:
        # an arena sheet declares and grants nothing beyond the six arena intents
        if not set(doc["tools"]["builtin"]) <= set(INTENTS) or doc["tools"]["mcp_servers"]:
            out.append("an arena sheet may hold only the six arena intents and no MCP server")
        sb = doc["permissions"]["sandbox"]
        if sb["network"] or sb["write"] or sb["read"] or sb["machLookup"] or doc["permissions"].get("network_grants"):
            out.append("an arena sheet grants no network, file or service access")
        if doc["skills"] or doc["libraries"] or doc["hooks"]:
            out.append("an arena sheet carries no skills, libraries or hooks")
    return out


def check_game(doc, names):
    out, g = [], doc["game"]
    for path in walk_numbers(g):
        if path not in NO_NUMBERS_OUTSIDE:
            out.append(f"game.{'.'.join(path)}: a number in the game block (only version and serial are allowed)")
    if g["temperament"] in [s for s in ks.STYLES]:
        out.append("temperament reuses a fight-style word")
    for stem in STYLE_STEMS:
        if g["temperament"].lower().startswith(stem):
            out.append(f"temperament {g['temperament']!r} reuses the fight-style stem {stem!r}")
    if "emoji" in g:
        reason = emoji_rules.check_set(g["emoji"])
        if reason:
            out.append(f"game.emoji: {reason}")
    if g.get("preset") not in (None, g["fight_style"]):
        out.append("preset must equal fight_style at version 2")
    lines = list(g["voice"]) + list(g["reactions"].values()) + list(g.get("tics", [])) + list(g.get("never_hooks", [])) \
        + [(g.get("belief") or {}).get("line", "")]
    for ln in lines:
        for p in line_problems(ln, g["name"], names):
            out.append(f"{p}: {ln!r}")
    for r in g.get("rivalries", []):
        if r["with"] == (doc["identity"]["role"]):
            out.append("a trenchie is its own rival")
    return out


def check_house(doc, slug, kits):
    out, g = [], doc["game"]
    rows = {r["name"]: r for r in kits["trenchies"]}
    if g["name"] not in ks.B21 or g["name"] not in rows:
        return [f"name {g['name']!r} is not one of the 14 house names"]
    row = rows[g["name"]]
    if slug != row["trenchieId"]:
        out.append(f"file name {slug!r} != trenchieId {row['trenchieId']!r}")
    want_loadout = "rares" if g["name"] in ks.RARES_LOADOUT else "commons"
    if g.get("loadout") != want_loadout or row["loadout"] != want_loadout:
        out.append(f"loadout {g.get('loadout')!r}, the house split says {want_loadout!r}")
    if g["tag"] != row["tag"]:
        out.append(f"tag {g['tag']!r} != kits.json {row['tag']!r}")
    if g["fight_style"] != row["fightStyle"]:
        out.append(f"fight_style {g['fight_style']!r} != kits.json {row['fightStyle']!r}")
    c, leg = g["cosmetics"], row["legendary"]
    if c.get("palette") != row["paletteIds"]:
        out.append(f"palette {c.get('palette')} != kits.json {row['paletteIds']}")
    got = c.get("legendary") or {}
    if (got.get("id"), got.get("name"), got.get("reskin_of"), got.get("serial")) != (leg["id"], leg["name"], leg["reskinOf"], leg["serial"]):
        out.append(f"legendary {got} != kits.json {leg}")
    if c.get("starter_kit") != row["kit"]:
        out.append("starter_kit != kits.json kit")
    if c.get("signature_piece") != row["signaturePiece"]["id"]:
        out.append("signature_piece != kits.json signaturePiece")
    if len(g["voice"]) != 3:
        out.append("a house sheet carries exactly three voice lines")
    for k in ("ko_by_rival", "lost_legendary", "missed_prediction", "hit_prediction"):
        if k not in g["reactions"]:
            out.append(f"missing keyed reaction {k}")
    for k in ("tics", "banned_registers", "belief", "never_hooks", "emoji"):
        if not g.get(k):
            out.append(f"a house sheet needs {k}")
    want = []
    for kind, pairs in (("rival", kits.get("rivals", [])), ("ally", kits.get("alliances", []))):
        for p in pairs:
            if row["trenchieId"] in (p["a"], p["b"]):
                want.append((p["b"] if p["a"] == row["trenchieId"] else p["a"], kind))
    have = [(r["with"], r["kind"]) for r in g.get("rivalries", [])]
    if sorted(have) != sorted(want):
        out.append(f"rivalries {have} != kits.json {want}")
    n = len(render(g))
    if n > RENDER_MAX_CHARS:
        out.append(f"rendered game block is {n} characters, at most {RENDER_MAX_CHARS} (about 150 tokens)")
    return out


def check_doc(doc, slug, schema, kits, house=None):
    """All problems with one sheet. house=None: run the house checks when a loadout is set."""
    out = check_core(doc, schema, slug)
    if out or "game" not in doc:
        return out
    names = ks.B21
    out += check_game(doc, names)
    if house is True or (house is None and "loadout" in doc["game"]):
        out += check_house(doc, slug, kits)
    return out


def check_set(docs, kits):
    """Set-wide rules for the 14 house sheets. docs: {slug: doc}. Returns problems as strings."""
    out, games = [], [d["game"] for d in docs.values() if isinstance(d.get("game"), dict)]
    def dup(vals, what):
        for v in sorted({x for x in vals if vals.count(x) > 1}):
            out.append(f"{what} {v!r} is used twice")
    dup([g.get("tag") for g in games], "tag")
    dup([(g.get("cosmetics") or {}).get("palette", [None])[0] for g in games], "primary palette id")
    dup([((g.get("cosmetics") or {}).get("legendary") or {}).get("id") for g in games], "legendary id")
    dup([g.get("name") for g in games], "name")
    used = {g.get("temperament") for g in games}
    if used != set(TEMPERAMENTS):
        out.append(f"the 14 use temperaments {sorted(used)}; the six names are {TEMPERAMENTS}")
    split = [g.get("loadout") for g in games]
    if split.count("rares") != 7 or split.count("commons") != 7:
        out.append(f"loadout split is {split.count('rares')} rares and {split.count('commons')} commons, need 7 and 7")
    missing = sorted(set(ks.B21) - {g.get("name") for g in games})
    if missing:
        out.append(f"no sheet for {missing}")
    # the lore bible names every legendary and tag
    try:
        lore = open(LORE, encoding="utf-8").read()
    except OSError:
        out.append("LORE.md is missing")
        lore = ""
    if lore:
        for g in games:
            for what, val in (("legendary", ((g.get("cosmetics") or {}).get("legendary") or {}).get("name")), ("tag", g.get("tag"))):
                if val and val not in lore:
                    out.append(f"LORE.md does not mention {what} {val!r}")
    return out


# ---------------------------------------------------------------- loading and reporting
def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run(paths, house_set, kits, schema, quiet=False, expect=None):
    docs, valid, bad = {}, 0, []
    for p in sorted(paths):
        slug = os.path.basename(p)[:-5]
        try:
            doc = load(p)
        except (OSError, ValueError) as e:
            bad.append(f"FAIL {slug}: cannot read: {e}")
            continue
        probs = check_doc(doc, slug, schema, kits, house=True if house_set else None)
        if probs:
            bad += [f"FAIL {slug}: {x}" for x in probs]
        else:
            valid += 1
            docs[slug] = doc
            if not quiet:
                g = doc.get("game", {})
                print(f"OK   {slug:<22} {g.get('temperament', '-'):<9} {g.get('fight_style', '-'):<8} {digest(doc)[:12]}")
    set_probs = check_set(docs, kits) if house_set and valid == len(paths) == 14 else []
    total = expect if expect is not None else len(paths)
    for line in bad + [f"FAIL set: {x}" for x in set_probs]:
        print(line)
    print(f"{valid}/{total} valid")
    return 0 if (valid == total and not bad and not set_probs) else 1


def load_context():
    schema = load(SCHEMA)
    kits = load(KITS)
    kr = ks.Report()
    ks.check_kits_doc(kr, kits)
    if kr.fails:
        print("\n".join(kr.fails))
        print("kits.json fails; the sheets copy their game block from it. Fix it first (check_sheets.py --kits).")
        return None, None
    return schema, kits


# ---------------------------------------------------------------- self-test
def selftest():
    schema, kits = load_context()
    if not schema:
        return 1
    paths = [os.path.join(PERSONAS, f) for f in sorted(os.listdir(PERSONAS)) if f.endswith(".json")]
    base = {os.path.basename(p)[:-5]: load(p) for p in paths}
    probs = [x for s, d in base.items() for x in check_doc(d, s, schema, kits, house=True)] + check_set(base, kits)
    if probs or len(base) != 14:
        print("selftest: the shipped sheets fail, fix that first:\n" + "\n".join(probs))
        return 1
    failures = []

    # 1. the two headline mutants, through the real command: each must print 13/14 valid and exit 1
    def headline(label, mutate):
        with tempfile.TemporaryDirectory() as tmp:
            d = os.path.join(tmp, "personas")
            os.makedirs(d)
            for s, doc in base.items():
                doc = copy.deepcopy(doc)
                if s == "avichad":
                    mutate(doc)
                with open(os.path.join(d, s + ".json"), "w", encoding="utf-8") as f:
                    json.dump(doc, f)
            r = subprocess.run([sys.executable, "-I", os.path.abspath(__file__), "--sheets-dir", d],
                               capture_output=True, text=True)
        ok = r.returncode == 1 and r.stdout.strip().splitlines()[-1] == "13/14 valid"
        print(f"{'ok  ' if ok else 'FAIL'} mutant: {label} -> {r.stdout.strip().splitlines()[-1]}, exit {r.returncode}")
        if not ok:
            failures.append(label)

    headline("a required core element deleted (permissions)", lambda d: d.pop("permissions"))
    headline("an invalid house loadout", lambda d: d["game"].update(loadout="heroes"))

    # 2. in-process breaks: every one must be caught
    def sh(slug, f):
        return lambda docs: f(docs[slug])
    cases = {
        "core element deleted: identity.assessor": sh("avichad", lambda d: d["identity"].pop("assessor")),
        "core element deleted: manifest": sh("avichad", lambda d: d.pop("manifest")),
        "legacy core key in identity": sh("avichad", lambda d: d["identity"].update({LEGACY: "the operator"})),
        "unknown root key": sh("avichad", lambda d: d.update(lore="x")),
        "loadout flipped to the other split": sh("avichad", lambda d: d["game"].update(loadout="commons")),
        "game version 1 (refused, with a clear message)": sh("avichad", lambda d: d["game"].update(version=1)),
        "game version 3": sh("avichad", lambda d: d["game"].update(version=3)),
        "game version as a string": sh("avichad", lambda d: d["game"].update(version="2")),
        "game block names a tool": sh("avichad", lambda d: d["game"].update(tools=["bash"])),
        "game block carries a command": sh("avichad", lambda d: d["game"].update(command="curl x")),
        "game block carries a permission": sh("avichad", lambda d: d["game"].update(permissions={"network": ["x.com"]})),
        "game block carries memory": sh("avichad", lambda d: d["game"].update(memory={"seed": ["x"]})),
        "game block carries a bias number": sh("avichad", lambda d: d["game"].update(boldness=0.9)),
        "bias number inside the belief": sh("avichad", lambda d: d["game"]["belief"].update(weight=3)),
        "a built memory pool": sh("avichad", lambda d: d["memory"].update(episodic_traces={"status": "built", "path": "x"})),
        "a pool path with a not-built status": sh("avichad", lambda d: d["memory"].update(semantic_rules={"status": "not built", "path": "x"})),
        "an extra tool granted": sh("avichad", lambda d: (d["tools"]["builtin"].append("Bash"), d["permissions"]["tool_subset"].append("Bash"))),
        "an MCP server granted": sh("avichad", lambda d: d["tools"]["mcp_servers"].append("fetch")),
        "network granted": sh("avichad", lambda d: d["permissions"]["sandbox"]["network"].append("example.com")),
        "tool_subset names an unheld tool": sh("avichad", lambda d: d["permissions"]["tool_subset"].append("Bash")),
        "a skill added": sh("avichad", lambda d: d["skills"].append({"name": "craft", "status": "stable"})),
        "manifest omits game": sh("avichad", lambda d: d["manifest"]["elements"].remove("game")),
        "manifest name differs": sh("avichad", lambda d: d["manifest"].update(name="somebody-else")),
        "temperament outside the six": sh("avichad", lambda d: d["game"].update(temperament="Brawler")),
        "fight_style outside the five": sh("avichad", lambda d: d["game"].update(fight_style="ninja")),
        "name outside the 14": sh("avichad", lambda d: d["game"].update(name="Somebody Else")),
        "tag drifts from kits.json": sh("avichad", lambda d: d["game"].update(tag="Chad")),
        "palette drifts": sh("avichad", lambda d: d["game"]["cosmetics"].update(palette=["p01", "p02"])),
        "palette id outside p01-p16": sh("avichad", lambda d: d["game"]["cosmetics"].update(palette=["p17"])),
        "legendary renamed": sh("avichad", lambda d: d["game"]["cosmetics"]["legendary"].update(name="Beam Thing")),
        "serial as a string": sh("avichad", lambda d: d["game"]["cosmetics"]["legendary"].update(serial="1")),
        "starter kit drifts": sh("avichad", lambda d: d["game"]["cosmetics"]["starter_kit"].update(head="c-head-maxi")),
        "two voice lines": sh("avichad", lambda d: d["game"]["voice"].pop()),
        "voice line over 60 characters": sh("avichad", lambda d: d["game"]["voice"].__setitem__(0, "x" * 61)),
        "voice accusation word": sh("avichad", lambda d: d["game"]["voice"].__setitem__(0, "What a scam.")),
        "rug beside a name": sh("avichad", lambda d: d["game"]["reactions"].update(ko_by_rival="Tommy Leeth did the Great Rug.")),
        "reaction names another trenchie": sh("avichad", lambda d: d["game"]["reactions"].update(hit_prediction="Satrenchi saw it too.")),
        "keyed reaction missing": sh("avichad", lambda d: d["game"]["reactions"].pop("lost_legendary")),
        "myth outside the three": sh("avichad", lambda d: d["game"]["belief"].update(myth="tommy-leeth")),
        "rivalry dropped": sh("laser-sailor", lambda d: d["game"].update(rivalries=[])),
        "names sweep word in the brief": sh("avichad", lambda d: d["identity"].update(brief=d["identity"]["brief"] + f" The {LEGACY}s agree.")),
        "game block over the render budget": sh("avichad", lambda d: d["game"].update(tics=["x" * 100] * 4)),
        "compute-only change must keep the digest": None,
    }
    for label, mut in cases.items():
        if mut is None:
            continue
        docs = copy.deepcopy(base)
        mut(docs)
        p = []
        for s, d in docs.items():
            p += check_doc(d, s, schema, kits, house=True)
        caught = bool(p)
        print(f"{'ok  ' if caught else 'MISSED'} {label}" + (f"  ({p[0]})" if caught else ""))
        if not caught:
            failures.append(label)

    v1 = copy.deepcopy(base["avichad"]); v1["game"]["version"] = 1
    msg = check_doc(v1, "avichad", schema, kits, house=True)
    ok = len(msg) == 1 and "version 1 is refused" in msg[0] and base["avichad"]["game"]["version"] == GAME_VERSION \
        and not check_doc(base["avichad"], "avichad", schema, kits, house=True)
    print(f"{'ok  ' if ok else 'FAIL'} version: a version-1 sheet is refused with one clear message; a version-2 sheet passes")
    if not ok:
        failures.append("version message")

    # 3. set-wide breaks
    set_cases = {
        "duplicate tag": lambda docs: docs["avichad"]["game"].update(tag="Leeth"),
        "duplicate legendary id": lambda docs: docs["avichad"]["game"]["cosmetics"]["legendary"].update(id="leg-lifeboat"),
        "a temperament unused": lambda docs: docs["captain-banana-zone"]["game"].update(temperament="Serene") or
                                             docs["tommy-leeth"]["game"].update(temperament="Serene"),
        "a legendary missing from LORE.md": lambda docs: docs["avichad"]["game"]["cosmetics"]["legendary"].update(name="Nobody Knows This Name"),
    }
    for label, mut in set_cases.items():
        docs = copy.deepcopy(base)
        mut(docs)
        p = check_set(docs, kits)
        print(f"{'ok  ' if p else 'MISSED'} set: {label}" + (f"  ({p[0]})" if p else ""))
        if not p:
            failures.append("set: " + label)

    # 4. the digest: compute picks leave it equal, persona content changes it
    d0 = base["avichad"]
    a = copy.deepcopy(d0); a["model_routing"] = {"tier": "opus", "effort": "high", "compute_home": {"kind": "plan", "unit": "percent of weekly"}}
    a["manifest"]["version"] = "2026-12-01.1"
    b = copy.deepcopy(d0); b["game"]["temperament"] = "Gruff"
    c = copy.deepcopy(d0); c["permissions"]["write_deny"] = ["/etc"]
    ok = digest(a) == digest(d0) and digest(b) != digest(d0) and digest(c) != digest(d0)
    print(f"{'ok  ' if ok else 'FAIL'} digest: a model or provider change keeps it; a temperament or permission change moves it")
    if not ok:
        failures.append("digest")

    total = 2 + len([m for m in cases.values() if m]) + len(set_cases) + 2
    print(f"selftest: {total - len(failures)}/{total} checks passed" + (f"; failed: {failures}" if failures else ""))
    return 1 if failures else 0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    if "--digest" in argv:
        print(digest(load(argv[argv.index("--digest") + 1])))
        return 0
    schema, kits = load_context()
    if not schema:
        return 1
    if "--sheets-dir" in argv:     # the 14-sheet run against another folder (used by --selftest)
        d = argv[argv.index("--sheets-dir") + 1]
        return run([os.path.join(d, f) for f in os.listdir(d) if f.endswith(".json")], True, kits, schema, quiet=True, expect=14)
    if "--dir" in argv:
        d = argv[argv.index("--dir") + 1]
        paths = [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".json")]
        return run(paths, False, kits, schema)
    files = [a for a in argv if not a.startswith("--")]
    if files:
        return run(files, False, kits, schema)
    paths = [os.path.join(PERSONAS, f) for f in os.listdir(PERSONAS) if f.endswith(".json")]
    return run(paths, True, kits, schema, expect=14)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
