#!/usr/bin/env python3
"""test_sheet.py: tests for near/web/snapin/sheet.js, the character skinner's data layer.

  python3 -I near/web/snapin/test_sheet.py          (from the worktree root; needs `node` on PATH)

The authority for a player sheet is near/lore/check_personas.py (the writer's checker, schema persona.schema.json: ten core
elements plus the versioned `game` block). This test does not port its rules; it RUNS that checker on the sheets sheet.js builds:

  1. every temperament x battle option x door combination builds a sheet that `check_personas.py --dir` reports valid, exit 0;
  2. sheet.js's own validate() (the page's pre-check) agrees on each of them;
  3. the JS content digest equals `check_personas.py --digest` for the same file, and ignores the AI choice (model_routing);
  4. broken copies each FAIL in the real checker (exit 1) and in validate();
  5. the name and line guard (structure, house names, the configured block list, look-alike spellings);
  6. the S3 look vocabulary equals the approved board's (art/parts-s3.js, set c) and the five battle options equal arena/balance.PRESETS;
  7. the names sweep finds nothing in the snap-in's own files.

Prints PASS/FAIL per check and a count; exit 0 only when nothing fails. No network, no clock.
"""
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))           # the worktree root
SHEET_JS = os.environ.get("SNAP_SHEET_JS") or os.path.join(HERE, "sheet.js")
CHECKER = os.path.join(ROOT, "near", "lore", "check_personas.py")
PARTS_S3 = os.path.join(HERE, "art", "parts-s3.js")

RESULTS = []


def check(name, cond, why=""):
    RESULTS.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else ": " + str(why)))


NODE = shutil.which("node")
BOOT = r"""
const S = require(process.argv[1]);
let inp = '';
process.stdin.on('data', d => inp += d).on('end', async () => {
  const q = JSON.parse(inp); let out;
  if (q.op === 'dump') {
    out = {TEMPERAMENTS: S.TEMPERAMENTS, QUIRKS: S.QUIRKS, PRESETS: S.PRESETS, DOORS: S.DOORS, LOOK: S.LOOK, LOOK_SLOTS: S.LOOK_SLOTS,
           REACTION_KEYS: S.REACTION_KEYS, GAME_KEYS: S.GAME_KEYS, LIMITS: S.LIMITS, HOUSE_NAMES: S.HOUSE_NAMES, HOUSE_TAGS: S.HOUSE_TAGS, DEFAULT_LOOK: S.DEFAULT_LOOK};
  } else if (q.op === 'build') {
    out = q.states.map(s => S.build(s));
  } else if (q.op === 'validate') {
    out = q.items.map(it => { S.setBlocklist(it.blocklist || []); return S.validate(it.sheet, it.opts || {}); });
  } else if (q.op === 'digest') {
    out = []; for (const s of q.sheets) out.push(await S.digest(s));
  } else if (q.op === 'guard') {
    if (q.global) globalThis.SNAP_BLOCKLIST = q.global;
    if (q.setter) S.setBlocklist(q.setter);
    out = q.names.map(n => S.guard(n));
  } else if (q.op === 'guardLine') {
    out = q.lines.map(n => S.guardLine(n));
  } else if (q.op === 'presetSet') {
    out = q.lists.map(l => S.validatePresetSet(l));
  } else if (q.op === 'randomLook') {
    out = q.seeds.map(s => S.randomLook(s));
  } else if (q.op === 'misc') {
    out = {slug: q.names.map(n => S.slugify(n)), tag: q.names.map(n => S.deriveTag(n)),
           battle: S.battleOption(q.state), look: S.lookFile(q.state), render: q.sheets.map(s => S.renderGame(s).length)};
  } else if (q.op === 'drift') {
    const fs = require('fs'), vm = require('vm');
    const src = fs.readFileSync(q.parts, 'utf8');
    const a = src.indexOf('var PART = {'), bm = /var DEFAULT = \{[^\n]*\};/.exec(src), r = /function rng\(seed\)[^\n]*\n/.exec(src);
    if (a < 0 || !bm || !r) { out = {skip: 'the board file no longer has the expected PART/SETS/DEFAULT/rng lines'}; }
    else {
      const ctx = {}; vm.createContext(ctx);
      vm.runInContext(src.slice(a, bm.index + bm[0].length) + '; var SLOTS_ = ["shape","body","tone","eyes","brows","mouth","hair","hairCol","hat"]; ' + r[0] + '; this.__ = {PART: PART, SETS: SETS, DEFAULT: DEFAULT, rng: rng};', ctx);
      const B = ctx.__, diffs = [];
      S.LOOK_SLOTS.forEach(k => {
        const board = B.SETS.c[k], mine = S.LOOK[k];
        if (JSON.stringify(board) !== JSON.stringify(mine)) diffs.push('SETS.c.' + k + ' board=' + JSON.stringify(board) + ' sheet.js=' + JSON.stringify(mine));
        const known = Object.keys(B.PART[k].opts);
        mine.forEach(v => { if (known.indexOf(v) < 0) diffs.push(k + ':' + v + ' has no label on the board'); });
      });
      if (JSON.stringify(B.DEFAULT) !== JSON.stringify(S.DEFAULT_LOOK)) diffs.push('DEFAULT differs');
      [0, 1, 7, 42, 99, 12345, 4294967295].forEach(sd => {
        const r1 = B.rng(sd), lk = {}; S.LOOK_SLOTS.forEach(k => { lk[k] = B.SETS.c[k][Math.floor(r1() * B.SETS.c[k].length)]; });
        if (JSON.stringify(lk) !== JSON.stringify(S.randomLook(sd))) diffs.push('randomLook(' + sd + ') differs from the board generator');
      });
      out = {diffs: diffs};
    }
  }
  process.stdout.write(JSON.stringify(out));
});
"""


def js(op, **kw):
    r = subprocess.run([NODE, "-e", BOOT, SHEET_JS], input=json.dumps(dict(op=op, **kw)), capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"node {op} failed: {r.stderr.strip()[:400]}")
    return json.loads(r.stdout)


def run_checker(args):
    r = subprocess.run([sys.executable, "-I", CHECKER] + args, capture_output=True, text=True, cwd=ROOT, timeout=120)
    return r.returncode, r.stdout


def write_dir(sheets_by_name, d):
    for f in os.listdir(d):
        os.remove(os.path.join(d, f))
    for slug, sheet in sheets_by_name.items():
        with open(os.path.join(d, slug + ".json"), "w", encoding="utf-8") as fh:
            json.dump(sheet, fh, ensure_ascii=False, indent=2)


if not NODE:
    check("node is available", False, "node not found on PATH; sheet.js cannot be run")
    print("0 PASS, 1 FAIL")
    sys.exit(1)

D = js("dump")
TMP = tempfile.mkdtemp(prefix="snap-sheets-")


def letters(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(97 + r) + s
    return s


# ---------------------------------------------------------------- 1 and 2: the matrix through the real checker
states = []
for ti, t in enumerate(D["TEMPERAMENTS"]):
    for pi_, p in enumerate(D["PRESETS"]):
        for di, door in enumerate(D["DOORS"] + [""]):
            n = len(states)
            states.append({"name": "Tess " + letters(n).capitalize(), "temperament": t["id"], "preset": p["id"], "door": door, "look": {},
                           "quirks": [D["QUIRKS"][(ti + pi_) % 10]["id"]], "voice": "Swings first and talks later."})
looks = js("randomLook", seeds=list(range(len(states))))
for st, lk in zip(states, looks):
    st["look"] = lk
sheets = js("build", states=states)
by_slug = {s["identity"]["role"]: s for s in sheets}
check(f"matrix: {len(sheets)} built sheets have {len(sheets)} distinct file names", len(by_slug) == len(sheets), len(by_slug))
write_dir(by_slug, TMP)
code, out = run_checker(["--dir", TMP])
tail = out.strip().splitlines()[-1] if out.strip() else ""
check(f"matrix: check_personas.py --dir reports {len(sheets)}/{len(sheets)} valid (6 temperaments x 5 battle options x 5 doors), exit 0",
      code == 0 and tail == f"{len(sheets)}/{len(sheets)} valid", f"exit {code}: {out[-400:]}")
jres = js("validate", items=[{"sheet": s} for s in sheets])
check("matrix: sheet.js validate() passes the same sheets", all(r == [] for r in jres), [r for r in jres if r][:2])
check("every sheet names exactly one of the six temperaments and has no loadout",
      all(s["game"]["temperament"] in ("Sunny", "Deadpan", "Earnest", "Gruff", "Serene", "Restless") and "loadout" not in s["game"] for s in sheets))

# worst case for the game block's render budget (600 characters): longest name, three 60-char lines, two longest quirks
worst = [{"name": "Abcdefghijklmnopqrstuvwxyzabcde" + "fghijk"[i], "temperament": t["id"], "preset": "brawler-zap", "quirks": ["third-person", "counts-kos"],
          "lines": ["x" * 60, "y" * 60, "z" * 60], "voice": "v" * 500, "door": "Claude", "look": {}} for i, t in enumerate(D["TEMPERAMENTS"])]
wsheets = js("build", states=worst)
write_dir({s["identity"]["role"]: s for s in wsheets}, TMP)
code, out = run_checker(["--dir", TMP])
check("worst-case sheets (longest name, lines, tics, brief) pass the real checker", code == 0 and out.strip().endswith("6/6 valid"), out[-300:])
check("worst-case sheets pass validate() and render within 600 characters",
      all(r == [] for r in js("validate", items=[{"sheet": s} for s in wsheets])) and max(js("misc", names=[], state={}, sheets=wsheets)["render"]) <= 600)

# ---------------------------------------------------------------- 3: digest
sample = sheets[7]
write_dir({sample["identity"]["role"]: sample}, TMP)
code, out = run_checker(["--digest", os.path.join(TMP, sample["identity"]["role"] + ".json")])
jd = js("digest", sheets=[sample])[0]
check("digest: JS content digest equals check_personas.py --digest", code == 0 and out.strip() == jd, f"{out.strip()} vs {jd}")
other_door = js("build", states=[dict(states[7], door="OpenRouter" if states[7]["door"] != "OpenRouter" else "Claude")])[0]
check("digest: changing the AI door leaves the digest equal", js("digest", sheets=[other_door])[0] == jd)
changed = js("build", states=[dict(states[7], temperament="gruff" if states[7]["temperament"] != "gruff" else "sunny")])[0]
check("digest: changing the temperament changes it", js("digest", sheets=[changed])[0] != jd)
check("digest: the same choices give the same sheet", js("build", states=[states[7]])[0] == sample)

# ---------------------------------------------------------------- 4: broken copies fail in the real checker and in validate()
base = copy.deepcopy(by_slug[next(iter(by_slug))])


def drop_tool(s):
    s["tools"]["builtin"].append("market-bid")


MUTANTS = [  # (label, mutation, validate() should also fail)
    ("game.version 1 (the old block)", lambda s: s["game"].update(version=1), True),
    ("a loadout field in game", lambda s: s["game"].update(loadout="rares"), True),
    ("a number that could bias a prediction", lambda s: s["game"].update(boldness=1), True),
    ("an unknown key in game", lambda s: s["game"].update(look={"hat": "st-cap"}), True),
    ("an old temperament name (Degen)", lambda s: s["game"].update(temperament="Degen"), True),
    ("a temperament that is a fight-style word", lambda s: s["game"].update(temperament="Brawler"), True),
    ("a tool beyond the six arena intents", drop_tool, True),
    ("network access granted", lambda s: s["permissions"]["sandbox"].update(network=["example.com"]), True),
    ("a skill carried", lambda s: s.update(skills=["x"]), True),
    ("memory pool built", lambda s: s["memory"].update(episodic_traces={"status": "built"}), True),
    ("a missing core element (hooks)", lambda s: s.pop("hooks"), True),
    ("a voice line with an accusation word", lambda s: s["game"]["voice"].__setitem__(0, "What a scam."), True),
    ("rug beside no Great", lambda s: s["game"]["voice"].__setitem__(0, "Rug rug rug."), True),
    ("a voice line over 60 characters", lambda s: s["game"]["voice"].__setitem__(1, "x" * 61), True),
    ("a reaction over 60 characters", lambda s: s["game"]["reactions"].update(ko_by_rival="x" * 61), True),
    ("a fifth tic", lambda s: s["game"].update(tics=["a"] * 5), True),
    ("palette id outside p01-p16", lambda s: s["game"]["cosmetics"].update(palette=["p17", "p01"]), True),
    ("the names-sweep word in the brief", lambda s: s["identity"].update(brief="A " + "jud" + "ge of the tide."), True),
    ("fight_style outside the five", lambda s: s["game"].update(fight_style="ninja"), True),
    ("manifest names another role", lambda s: s["manifest"].update(name="someone-else"), True),
    ("manifest lists an element twice", lambda s: s["manifest"]["elements"].append("tools"), True),
    ("model_routing tier outside the list", lambda s: s["model_routing"].update(tier="gpt"), True),
]
bad_validate, bad_checker = [], []
for label, fn, js_too in MUTANTS:
    s = copy.deepcopy(base)
    fn(s)
    write_dir({s["identity"]["role"]: s}, TMP)
    code, out = run_checker(["--dir", TMP])
    if code != 1 or out.strip().splitlines()[-1] != "0/1 valid":
        bad_checker.append((label, code, out.strip()[-120:]))
    if js_too and js("validate", items=[{"sheet": s}])[0] == []:
        bad_validate.append(label)
check(f"mutants: all {len(MUTANTS)} broken copies are refused by check_personas.py (0/1 valid, exit 1)", not bad_checker, bad_checker)
check(f"mutants: all {len(MUTANTS)} broken copies are flagged by sheet.js validate()", not bad_validate, bad_validate)
s = copy.deepcopy(base)
write_dir({"not-the-role": s}, TMP)
code, out = run_checker(["--dir", TMP])
check("mutant: a file name that is not identity.role is refused by the checker (the download is named <role>.json)", code == 1, out[-200:])

# ---------------------------------------------------------------- 5: the guard
g = js("guard", names=["Pip Shoals", "", " Pip", "Pip  Shoals", "x" * 33, "Laser Sailor", "satrenchi", "best.com", "aaaaaa", "Rug Pull", "No scam", "Zed_1", "123", "Café Ünal", "Mo-Mo's Bay"])
ok = [x["ok"] for x in g]
check("guard: good names pass, structure and house-name rules refuse the rest", ok == [True, False, False, False, False, False, False, False, False, False, False, False, False, True, True], ok)
gl = js("guard", names=["Zorp Lord", "Z0rp", "zorp"], setter=["zorp"])
check("guard: a configured block list refuses a name, a look-alike spelling and a bare word", [x["ok"] for x in gl] == [False, False, False])
gg = js("guard", names=["Zorp Lord", "Pip"], global_=None, **{"global": ["zorp"]})
check("guard: window.SNAP_BLOCKLIST is honoured", [x["ok"] for x in gg] == [False, True])
gline = js("guardLine", lines=["Lovely tide today!", "What a scam.", "Avichad did the Great Rug.", "The Great Rug was wild.", "Rug rug", "Hello Laser Sailor", "I am 90% sure.", "bid p50", "see www.x.com"])
check("guardLine: the output-check rules (accusation words, rug rule, names, numbers that bias, addresses)",
      [x["ok"] for x in gline] == [True, False, False, True, False, False, False, False, False], [x["ok"] for x in gline])

# ---------------------------------------------------------------- beside-the-sheet data
st = states[0]
mi = js("misc", names=["Pip Shoals", "9 Lives", "Éloïse", "!!!"], state=st, sheets=[])
check("slug: ASCII, starts with a letter, never empty", mi["slug"] == ["pip-shoals", "t-9-lives", "eloise", "trenchie"], mi["slug"])
check("battle option travels beside the sheet and equals the chosen preset", mi["battle"]["id"] == st["preset"] and mi["battle"]["style"] == by_slug[next(iter(by_slug))]["game"]["fight_style"])
check("look file holds the nine S3 parts and the same role as the sheet", list(mi["look"]["look"].keys()) == D["LOOK_SLOTS"] and mi["look"]["role"] == sheets[0]["identity"]["role"])
check("palette in the sheet repeats the look's body and hair colours", sheets[0]["game"]["cosmetics"]["palette"] == [st["look"]["body"], st["look"]["hairCol"]])

# ---------------------------------------------------------------- 6: the board and the arena
dr = js("drift", parts=PARTS_S3)
if "skip" in dr:
    print("SKIP S3 board parity: " + dr["skip"])
else:
    check("the look vocabulary, default and random generator equal the approved S3 board (set c)", not dr["diffs"], dr["diffs"][:3])
r = subprocess.run([sys.executable, "-I", "-c", "import sys,json;sys.path.insert(0,'near/arena');sys.dont_write_bytecode=True;import balance;print(json.dumps(balance.PRESETS))"],
                   capture_output=True, text=True, cwd=ROOT)
arena = json.loads(r.stdout) if r.returncode == 0 else None
mine = [[p["style"], p["weapon"], p["signature"]] for p in D["PRESETS"]]
check("the five battle options equal arena/balance.PRESETS in order", arena == mine, (arena, mine, r.stderr[-200:]))
good = [{"id": p["id"], "name": p["name"], "style": p["style"], "weapon": p["weapon"], "signature": p["signature"]} for p in D["PRESETS"]]
ps = js("presetSet", lists=[good, good[:4], good + [good[0]], None])
check("preset set: exactly five distinct valid options", ps[0] == [] and ps[1] != [] and ps[2] != [] and ps[3] != [])

# ---------------------------------------------------------------- 7: names sweep over the snap-in's own files
sweep = re.compile(r"\b(" + "jud" + "ges?|fig" + "ures?)\b", re.I)
hits = []
for dp, dn, fn in os.walk(HERE):
    dn[:] = [d for d in dn if d not in ("vendor", "node_modules", "__pycache__", "shots")]
    for f in fn:
        if f.endswith((".js", ".cjs", ".css", ".html", ".py", ".md", ".json", ".txt", ".mjs", ".sh")):
            p = os.path.join(dp, f)
            try:
                for i, line in enumerate(open(p, encoding="utf-8", errors="ignore"), 1):
                    if sweep.search(line):
                        hits.append(f"{os.path.relpath(p, HERE)}:{i}")
            except OSError:
                pass
check("names sweep: no hit in the snap-in's own files", not hits, hits[:5])

shutil.rmtree(TMP, ignore_errors=True)
n_ok = sum(RESULTS)
print(f"{n_ok} PASS, {len(RESULTS) - n_ok} FAIL")
sys.exit(0 if n_ok == len(RESULTS) else 1)
