#!/usr/bin/env python3
"""check_sheets.py: validates the house trenchie kit table (kits.json). The persona sheets are checked by
check_personas.py, which reads kits.json through this file's check.

  python3 -I near/lore/check_sheets.py --kits      kits.json only (also the default)
  python3 -I near/lore/check_sheets.py --selftest  breaks copies of the kit table on purpose and confirms each break is caught
  python3 -I near/lore/check_sheets.py --old-names scans near/ (plus any --also DIR) for names retired in round 7;
                  private mode only: it needs the TRENCHIE_DENY_FILE env var (the retired-name list is private)
  --frame PATH    opt-in drift check: also compare the enums against a copy of the arena prototype's frame.js
                  (not in this repo). Without it the enums are checked against this file's constants only.

Exit 0 only when every check passes. Every failure prints one line: FAIL <where>: <what>.
The --kits path uses only the standard library.
"""
import copy
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KITS = os.path.join(HERE, "kits.json")
def _flag(flag):
    a = sys.argv[1:]
    return [a[i + 1] for i, x in enumerate(a) if x == flag and i + 1 < len(a)]


FRAME = (_flag("--frame") or [None])[0]   # optional: the prototype's frame.js lives outside this repo

# ---------------------------------------------------------------- the record (sources cited per constant)
B21 = ["Satrenchi", "Captain Banana Zone", "Vitrenchik", "Laser Sailor", "Tommy Leeth", "Trenchtoly",
       "Kathie Moonwood", "Illia Trenchukhin", "Eddie Lazertrench", "Mert Mumtrench", "Avichad", "Kain Warrior",
       "Hameme Pumpeshi", "Stepan Gershunode"]                                     # the 14 approved names (B21)
# B8 starting loadouts: in B21 order, the first seven house trenchies start with "commons" (the legendary + 3 commons)
# and the last seven with "rares" (3 rares + the legendary). The rares, by B21 name
# (Pat 2026-11-03: no identity label in the data, only the loadout):
RARES_LOADOUT = {"Illia Trenchukhin", "Eddie Lazertrench", "Mert Mumtrench", "Avichad", "Kain Warrior", "Hameme Pumpeshi",
                 "Stepan Gershunode"}
SIX_LEGENDARIES = {   # the six named legendaries, as amended: two renamed (2026-11-03) and Stack Sats re-fitted (Q16); one of the six left the house kits
    "Laser Eyes": ("beam_sweep", "Laser Sailor"),
    "Builder Census": ("chain_storm", "Avichad"),    # renamed 2026-11-03 (orchestrator decision)
    "Liquidity Wave": ("shockwave", "Captain Banana Zone"),
    "Stack Sats": ("magnet", "Satrenchi"),         # round 7 Q16: re-fitted to a bitcoin-coded trenchie
    "Lifeboat": ("bubble", "Kathie Moonwood"),            # renamed from its §2.5 name 2026-11-03 (same DECISION)
}
SIGNATURES = ["beam_sweep", "chain_storm", "shockwave", "blink_strike", "magnet", "bubble"]   # §2.5, frame.js
STARTER_SIGNATURE = "dodge_roll"
WEAPONS = ["swing", "shot", "beam", "lob", "zap", "lunge"]                 # §2.3
STYLES = ["brawler", "hunter", "looter", "guardian", "survivor"]           # §3.2 (B9), frame.js STYLE
SET_TAGS = ["maxi", "degen", "speedrunner", "builder"]                     # §2.6
STATS = ["damage", "cooldown", "hp", "speed", "range"]                     # §2.4 (B16b)
TIERS = ["common", "rare", "legendary"]
SLOTS = ["weapon", "trinket", "head", "body"]
BUDGET = {"common": 10, "rare": 16, "legendary": 24}                       # §2.4 / B16b
MAX_SHARE = 0.4                                                             # "one stat can take at most 40%"
ITEM_KEYS = ["id", "name", "slot", "tier", "weapon", "signature", "reskinOf", "stats", "setTag", "origin",
             "house", "starter"]                                            # frame.js RECORD.item
STARTER_ITEM = {"weapon": "st-bonk", "trinket": "st-roll", "head": "st-cap", "body": "st-tee"}   # frame.js
PALETTE = [f"p{i:02d}" for i in range(1, 17)]                              # palette ids p01-p16 only
ROW_KEYS = ["trenchieId", "name", "tag", "loadout", "fightStyle", "kit", "legendary"]   # the prototype contract (role -> loadout; + tag)
# Arena short tags (round 7). Pat set nine; the lore lane proposed five. One word each, except Pat's own Q18 example.
TAGS_DECIDED = {"Laser Sailor": "Sailor", "Eddie Lazertrench": "Eddie", "Hameme Pumpeshi": "Pumpeshi",
                "Stepan Gershunode": "Gershunode", "Kathie Moonwood": "Moonwood", "Avichad": "Avichad",
                "Tommy Leeth": "Leeth", "Illia Trenchukhin": "Trenchukhin", "Captain Banana Zone": "Banana Zone"}
TAG_MULTIWORD_OK = {"Banana Zone"}
MAX_SHARED_USES = 2   # no shared (pool) item is worn by more than two of the 14 at the start                                          # Q18, Pat's example


class Report:
    def __init__(self):
        self.fails = []

    def fail(self, where, what):
        self.fails.append(f"FAIL {where}: {what}")


def frame_enums(r):
    """With --frame PATH, parse the frozen enums out of the prototype's frame.js so kits.json cannot drift from it.
    Without it, the enums are checked against this file's constants above."""
    if not FRAME:
        return "enums checked against this file's constants"
    if not os.path.exists(FRAME):
        r.fail("frame.js", f"--frame {FRAME} not found")
        return "frame.js missing"
    src = open(FRAME, encoding="utf-8").read()

    def arr(pattern):
        m = re.search(pattern, src, re.S)
        return re.findall(r"'([^']+)'", m.group(1)) if m else None

    pairs = [("WEAPON", arr(r"const WEAPON = \[(.*?)\];"), WEAPONS),
             ("SIGNATURE", arr(r"const SIGNATURE = \[(.*?)\];"), SIGNATURES),
             ("STAT", arr(r"const STAT = \[(.*?)\];"), STATS),
             ("TIER", arr(r"const TIER = \[(.*?)\];"), TIERS),
             ("SLOT", arr(r"const SLOT = \[(.*?)\];"), SLOTS),
             ("STYLE", arr(r"const STYLE = \[(.*?)\];"), STYLES),
             ("SET_TAG", arr(r"const SET_TAG = \[(.*?)\];"), SET_TAGS),
             ("RECORD.item", arr(r"\n\s*item: \[(.*?)\]"), ITEM_KEYS)]
    for name, got, want in pairs:
        if got != want:
            r.fail("frame.js", f"{name} is {got}, this checker expects {want}")
    m = re.search(r"const STARTER_ITEM = \{(.*?)\};", src, re.S)
    got = dict(re.findall(r"(\w+): '([^']+)'", m.group(1))) if m else None
    if got != STARTER_ITEM:
        r.fail("frame.js", f"STARTER_ITEM is {got}, expected {STARTER_ITEM}")
    return "frame.js enums match"


def check_item(r, it):
    where = f"item {it.get('id')}"
    if list(it.keys()) != ITEM_KEYS:
        r.fail(where, f"keys {list(it.keys())} != frame.js RECORD.item {ITEM_KEYS}")
        return
    if it["slot"] not in SLOTS:
        r.fail(where, f"slot {it['slot']!r}")
    if it["tier"] not in TIERS:
        r.fail(where, f"tier {it['tier']!r}")
        return
    st = it["stats"]
    if not isinstance(st, dict) or list(st.keys()) != STATS or not all(isinstance(v, int) and v >= 0 for v in st.values()):
        r.fail(where, f"stats must be the 5 stats in order as ints >= 0, got {st}")
        return
    budget = BUDGET[it["tier"]]
    if sum(st.values()) != budget:
        r.fail(where, f"stat points {sum(st.values())} != {it['tier']} budget {budget}")
    if max(st.values()) > MAX_SHARE * budget:
        r.fail(where, f"one stat holds {max(st.values())} of {budget} (> 40%)")
    # slot-specific fields
    if it["slot"] == "weapon":
        if it["weapon"] not in WEAPONS or it["signature"] is not None:
            r.fail(where, f"weapon needs weapon in {WEAPONS} and no signature")
    elif it["slot"] == "trinket":
        sig_ok = it["signature"] in SIGNATURES or (it["starter"] and it["signature"] == STARTER_SIGNATURE)
        if not sig_ok or it["weapon"] is not None:
            r.fail(where, f"trinket needs a signature in {SIGNATURES} (or dodge_roll on the starter) and no weapon")
        if it["setTag"] is not None:
            r.fail(where, "trinkets carry no set tag (§2.6)")
    else:
        if it["weapon"] is not None or it["signature"] is not None:
            r.fail(where, "head/body carry no weapon or signature")
    if not it["starter"] and it["slot"] != "trinket" and it["setTag"] not in SET_TAGS:
        r.fail(where, f"head/body/weapon needs a set tag in {SET_TAGS}")
    if it["starter"] and it["setTag"] is not None:
        r.fail(where, "starter items carry no set tag")
    # tier-specific fields
    if it["tier"] == "legendary":
        if it["slot"] != "trinket" or it["reskinOf"] not in SIGNATURES or it["signature"] != it["reskinOf"]:
            r.fail(where, "a legendary is a trinket whose reskinOf is one of the 6 shared signatures and equals its signature")
        if not (isinstance(it["house"], str) and it["origin"] == f"house:{it['house']}"):
            r.fail(where, f"legendary origin must be house:<trenchieId>, got {it['origin']!r} / house {it['house']!r}")
    else:
        signature_piece = (isinstance(it["house"], str) and it["origin"] == f"house:{it['house']}"
                           and it["slot"] in ("head", "body") and not it["starter"] and it["id"].startswith("sig-"))
        if it["reskinOf"] is not None or (it["house"] is not None and not signature_piece):
            r.fail(where, "only legendaries and house signature pieces (sig-<trenchieId>, head/body) carry house")
        if signature_piece:
            pass
        elif it["origin"] != ("starter" if it["starter"] else "pool"):
            r.fail(where, f"origin {it['origin']!r}")


def check_kits_doc(r, doc):
    """Every field of the kits criterion. Returns per-trenchie summary lines."""
    lines = []
    items = doc.get("items", [])
    ids = [it.get("id") for it in items]
    for d in sorted({i for i in ids if ids.count(i) > 1}):
        r.fail("items", f"duplicate item id {d}")
    by_id = {it.get("id"): it for it in items}
    for it in items:
        check_item(r, it)
    if doc.get("starterKit") != STARTER_ITEM:
        r.fail("starterKit", f"{doc.get('starterKit')} != frame.js STARTER_ITEM {STARTER_ITEM}")
    for slot, sid in STARTER_ITEM.items():
        it = by_id.get(sid)
        if not it or not it["starter"] or it["slot"] != slot or it["tier"] != "common":
            r.fail("starterKit", f"{sid} must be a common starter {slot} item")
    # every pool slot/tier the drops and throws draw from exists
    for tier in ("common", "rare"):
        pool = [it for it in items if it.get("origin") == "pool" and it.get("tier") == tier]
        for w in WEAPONS:
            if not any(it["weapon"] == w for it in pool):
                r.fail("pool", f"no {tier} {w} weapon")
        for s in SIGNATURES:
            if not any(it["signature"] == s for it in pool):
                r.fail("pool", f"no {tier} {s} trinket")
        for slot in ("head", "body"):
            for tag in SET_TAGS:
                if not any(it["slot"] == slot and it["setTag"] == tag for it in pool):
                    r.fail("pool", f"no {tier} {tag} {slot}")

    rows = doc.get("trenchies", [])
    names = [row.get("name") for row in rows]
    if len(rows) != 14:
        r.fail("trenchies", f"{len(rows)} rows, need 14")
    if sorted(names) != sorted(B21):
        r.fail("trenchies", f"names {sorted(set(names) ^ set(B21))} differ from B21")
    tids = [row.get("trenchieId") for row in rows]
    for d in sorted({t for t in tids if tids.count(t) > 1}):
        r.fail("trenchies", f"duplicate trenchieId {d}")
    leg_ids, leg_names, arena_tags = [], [], []
    for row in rows:
        name = row.get("name")
        where = f"trenchie {name}"
        missing = [k for k in ROW_KEYS if k not in row]
        if missing:
            r.fail(where, f"missing keys {missing}")
            continue
        tid = row["trenchieId"]
        tag = row["tag"]
        arena_tags.append(tag)
        if not isinstance(tag, str) or not tag.strip() or (len(tag.split()) != 1 and tag not in TAG_MULTIWORD_OK):
            r.fail(where, f"tag {tag!r} must be one word (Q18; only {sorted(TAG_MULTIWORD_OK)} may be two)")
        if name in TAGS_DECIDED and tag != TAGS_DECIDED[name]:
            r.fail(where, f"tag {tag!r}, Pat set {TAGS_DECIDED[name]!r} (round 7)")
        sr = row["legendary"].get("serial") if isinstance(row.get("legendary"), dict) else None
        if not (isinstance(sr, int) and not isinstance(sr, bool) and sr >= 1):
            r.fail(where, f"legendary serial {sr!r} must be an int >= 1 (Q20: remakes count up from #1)")
        if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", tid or ""):
            r.fail(where, f"trenchieId {tid!r} is not a lower-case slug")
        want_loadout = "rares" if name in RARES_LOADOUT else "commons"
        if row["loadout"] != want_loadout:
            r.fail(where, f"loadout {row['loadout']!r}, the B8 split says {want_loadout}")
        if "role" in row:
            r.fail(where, "the row still carries a role field (loadout only)")
        if row["fightStyle"] not in STYLES:
            r.fail(where, f"fightStyle {row['fightStyle']!r} not in the five fight styles {STYLES}")
        kit = row["kit"]
        if not isinstance(kit, dict) or list(kit.keys()) != SLOTS:
            r.fail(where, f"kit must hold exactly {SLOTS}, got {kit}")
            continue
        worn = {}
        for slot, iid in kit.items():
            it = by_id.get(iid)
            if not it:
                r.fail(where, f"kit {slot} {iid!r} is not in items")
                continue
            if it["slot"] != slot:
                r.fail(where, f"kit {slot} holds {iid}, a {it['slot']} item")
            if it["starter"]:
                r.fail(where, f"kit {slot} holds a starter item {iid}")
            worn[slot] = it
        if len(worn) != 4:
            continue
        # B8: "rares" = 3 rares + the legendary; "commons" = the legendary + 3 commons
        others = [worn[s]["tier"] for s in ("weapon", "head", "body")]
        want_tier = "rare" if want_loadout == "rares" else "common"
        if worn["trinket"]["tier"] != "legendary" or others != [want_tier] * 3:
            r.fail(where, f"B8: a {want_loadout} loadout wears a legendary trinket + 3 {want_tier}s, got trinket "
                          f"{worn['trinket']['tier']} and {others}")
        leg = row["legendary"]
        if not isinstance(leg, dict) or not {"id", "name", "reskinOf"} <= set(leg):
            r.fail(where, f"legendary must carry id, name, reskinOf: {leg}")
            continue
        leg_ids.append(leg["id"])
        leg_names.append(leg["name"])
        if leg["id"] != kit["trinket"]:
            r.fail(where, f"legendary {leg['id']} is not the kit trinket {kit['trinket']}")
        if leg["reskinOf"] not in SIGNATURES:
            r.fail(where, f"legendary reskinOf {leg['reskinOf']!r} is not one of the 6 shared signatures")
        li = by_id.get(leg["id"])
        if li and (li["name"] != leg["name"] or li["reskinOf"] != leg["reskinOf"] or li["house"] != tid):
            r.fail(where, f"legendary row {leg} disagrees with item {li['name']}/{li['reskinOf']}/{li['house']}")
        if leg["name"] in SIX_LEGENDARIES:
            sig, holder = SIX_LEGENDARIES[leg["name"]]
            if holder != name or sig != leg["reskinOf"]:
                r.fail(where, f"{leg['name']} belongs to {holder} as {sig}")
        pal = row.get("paletteIds")
        if pal is not None and (not isinstance(pal, list) or not pal or any(p not in PALETTE for p in pal)):
            r.fail(where, f"paletteIds {pal} must be ids from p01-p16")
        tags = [worn[s]["setTag"] for s in ("weapon", "head", "body")]
        top = max(set(tags), key=tags.count)
        lines.append(f"{name:<20} {row['loadout']:<7} {row['fightStyle']:<8} {worn['weapon']['weapon'] or '-':<5} "
                     f"{leg['name']} -> {leg['reskinOf']}  set {top} x{tags.count(top)}  "
                     f"points {sum(sum(w['stats'].values()) for w in worn.values())}")
    # Signature pieces (the 14 looked alike in review): every trenchie has its own signature piece, and no shared item is in more than two kits
    uses = {}
    for row in rows:
        for iid in (row.get("kit") or {}).values():
            uses[iid] = uses.get(iid, 0) + 1
    for iid, n in sorted(uses.items()):
        if n > MAX_SHARED_USES:
            r.fail("kits", f"{iid} ({by_id.get(iid, {}).get('name', '?')}) is worn by {n} trenchies; at most {MAX_SHARED_USES}")
    sig_ids = []
    for row in rows:
        sp, where = row.get("signaturePiece"), f"trenchie {row.get('name')}"
        if not (isinstance(sp, dict) and {"id", "name", "slot", "look", "replaces"} <= set(sp)):
            r.fail(where, f"signaturePiece must carry id, name, slot, look, replaces; got {sp}")
            continue
        sig_ids.append(sp["id"])
        it, base = by_id.get(sp["id"]), by_id.get(sp["replaces"])
        if not it or row["kit"].get(sp["slot"]) != sp["id"]:
            r.fail(where, f"signature piece {sp['id']} must be in the kit's {sp['slot']} slot")
            continue
        if it["origin"] != f"house:{row['trenchieId']}" or it["name"] != sp["name"] or it["slot"] != sp["slot"]:
            r.fail(where, f"signature piece {sp['id']} item disagrees with the row (origin/name/slot)")
        if base and (it["tier"], it["stats"], it["setTag"]) != (base["tier"], base["stats"], base["setTag"]):
            r.fail(where, f"signature piece {sp['id']} must copy the tier, stats and set tag of {sp['replaces']} (balance-neutral)")
    if len(set(sig_ids)) != len(rows) or len(sig_ids) != len(rows):
        r.fail("kits", f"{len(set(sig_ids))} distinct signature pieces for {len(rows)} trenchies; need one each")
    for d in sorted({t for t in arena_tags if arena_tags.count(t) > 1}):
        r.fail("tags", f"tag {d!r} is used twice")
    for d in sorted({i for i in leg_ids if leg_ids.count(i) > 1}):
        r.fail("legendaries", f"legendary id {d} is used twice")
    for d in sorted({n for n in leg_names if leg_names.count(n) > 1}):
        r.fail("legendaries", f"legendary name {d} is used twice")
    for six, (_, holder) in SIX_LEGENDARIES.items():
        if six not in leg_names:
            r.fail("legendaries", f"{six} ({holder}) is missing: the canon legendaries keep their holders")
    house_legs = [it["id"] for it in items if it.get("tier") == "legendary"]
    if sorted(house_legs) != sorted(leg_ids):
        r.fail("legendaries", f"legendary items {sorted(set(house_legs) ^ set(leg_ids))} are not exactly the 14 kit legendaries")

    # Q59: 3-4 seeded rivalries, each between two of the 14, with a reason
    tidset = set(tids)
    rivals = doc.get("rivals", [])
    if not 3 <= len(rivals) <= 4:
        r.fail("rivals", f"{len(rivals)} pairs, Q59 asks for 3-4")
    seen = set()
    for i, p in enumerate(rivals + doc.get("alliances", [])):
        kind = "rival" if i < len(rivals) else "alliance"
        a, b = p.get("a"), p.get("b")
        if a not in tidset or b not in tidset or a == b:
            r.fail(kind, f"pair {a}/{b} must be two different trenchies of the 14")
        if not (p.get("reason") or "").strip():
            r.fail(kind, f"pair {a}/{b} has no reason")
        key = frozenset((a, b))
        if key in seen:
            r.fail(kind, f"pair {a}/{b} is listed twice (rival and alliance at once?)")
        seen.add(key)
    return lines


def load_kits(r):
    try:
        with open(KITS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        r.fail("kits.json", f"cannot load: {e}")
        return None


def run_kits():
    r = Report()
    note = frame_enums(r)
    doc = load_kits(r)
    lines = check_kits_doc(r, doc) if doc else []
    for ln in lines:
        print("OK  " + ln)
    for f in r.fails:
        print(f)
    n_items = len(doc.get("items", [])) if doc else 0
    if r.fails:
        print(f"kits.json: {len(r.fails)} failure(s)")
        return 1
    print(f"kits.json: {len(lines)} OK, {n_items} items, {len(doc['rivals'])} rival pairs, "
          f"{len(doc.get('alliances', []))} alliances ({note})")
    return 0


# ---------------------------------------------------------------- self-test: every break must be caught
def selftest():
    r0 = Report()
    base = load_kits(r0)
    if not base:
        print("\n".join(r0.fails))
        return 1
    clean = Report()
    check_kits_doc(clean, base)
    if clean.fails:
        print("selftest: the shipped kits.json fails, fix that first")
        return 1

    def row(d, name):
        return next(x for x in d["trenchies"] if x["name"] == name)

    def item(d, iid):
        return next(x for x in d["items"] if x["id"] == iid)

    cases = {
        "13 rows": lambda d: d["trenchies"].pop(),
        "non-B21 name": lambda d: row(d, "Hameme Pumpeshi").update(name="Somebody Else"),
        "rares loadout marked commons": lambda d: row(d, "Eddie Lazertrench").update(loadout="commons"),
        "commons loadout marked rares": lambda d: row(d, "Vitrenchik").update(loadout="rares"),
        "style outside §3.2": lambda d: row(d, "Satrenchi").update(fightStyle="ninja"),
        "reskin outside the 6": lambda d: (row(d, "Hameme Pumpeshi")["legendary"].update(reskinOf="drones"),
                                           item(d, "leg-poker-face").update(reskinOf="drones", signature="drones")),
        "duplicate legendary id": lambda d: (row(d, "Hameme Pumpeshi")["kit"].update(trinket="leg-lifeboat"),
                                             row(d, "Hameme Pumpeshi")["legendary"].update(id="leg-lifeboat")),
        "Laser Eyes re-paired": lambda d: (row(d, "Laser Sailor")["legendary"].update(name="Beam Thing"),
                                           item(d, "leg-laser-eyes").update(name="Beam Thing")),
        "rares loadout with a common": lambda d: row(d, "Avichad")["kit"].update(head="c-head-builder"),
        "commons loadout with a rare": lambda d: row(d, "Kathie Moonwood")["kit"].update(body="r-body-degen"),
        "common over budget": lambda d: item(d, "c-swing")["stats"].update(range=5),
        "stat over 40%": lambda d: item(d, "r-zap")["stats"].update(cooldown=7, damage=3),
        "legendary under budget": lambda d: item(d, "leg-stack-sats")["stats"].update(hp=0),
        "rival outside the 14": lambda d: d["rivals"][0].update(b="smol_degen"),
        "rival with itself": lambda d: d["rivals"][0].update(b=d["rivals"][0]["a"]),
        "2 rival pairs": lambda d: d["rivals"].__delitem__(slice(2, None)),
        "rival without reason": lambda d: d["rivals"][1].update(reason=" "),
        "item key drift": lambda d: item(d, "c-lob").update(tag="builder"),
        "kit item missing": lambda d: row(d, "Trenchtoly")["kit"].update(weapon="c-crossbow"),
        "trinket in weapon slot": lambda d: row(d, "Trenchtoly")["kit"].update(weapon="c-magnet"),
        "duplicate tag": lambda d: row(d, "Trenchtoly").update(tag="Leeth"),
        "two-word tag": lambda d: row(d, "Kain Warrior").update(tag="Kain W"),
        "Pat's tag changed": lambda d: row(d, "Laser Sailor").update(tag="Laser"),
        "serial 0": lambda d: row(d, "Satrenchi")["legendary"].update(serial=0),
        "a pool item worn 3 times": lambda d: row(d, "Mert Mumtrench")["kit"].update(weapon="r-zap"),
        "signature piece shared": lambda d: row(d, "Avichad").update(signaturePiece=dict(row(d, "Kain Warrior")["signaturePiece"])),
        "signature piece re-statted": lambda d: item(d, "sig-satrenchi")["stats"].update(hp=item(d, "sig-satrenchi")["stats"]["hp"] + 1, range=item(d, "sig-satrenchi")["stats"]["range"] - 1),
    }
    missed = []
    for label, mutate in cases.items():
        d = copy.deepcopy(base)
        mutate(d)
        r = Report()
        check_kits_doc(r, d)
        print(f"{'caught' if r.fails else 'MISSED'}  {label}" + (f"  ({r.fails[0]})" if r.fails else ""))
        if not r.fails:
            missed.append(label)

    print(f"selftest: {len(cases) - len(missed)}/{len(cases)} kits breaks caught")
    return 1 if missed else 0


# ---------------------------------------------------------------- retired names: private mode only
# The retired round-7 names are private, so this repo holds neither the names nor their hashes. --old-names reads
# the hashes from the private deny file named by the TRENCHIE_DENY_FILE env var: lines "sha16:<hex>", each
# sha256(lowercase)[:16] of a retired word or word pair. Files are split into lowercase words on non-alphanumerics;
# every word and adjacent word pair is hashed and compared, so "Name", "name-slug" and "Name Slug" all match.
DENY_ENV = "TRENCHIE_DENY_FILE"


def load_retired():
    path = os.environ.get(DENY_ENV)
    if not path or not os.path.exists(path):
        return None
    return {l.strip()[6:] for l in open(path, encoding="utf-8") if l.strip().startswith("sha16:")}


EXTRA_ROOTS = [os.path.normpath(p) for p in _flag("--also")]   # optional extra trees to scan, outside this repo
# Skipped in an extra root: *-built-* directories (frozen provenance copies) and the Zdog draft files below (frozen legacy).
FROZEN_LEGACY = {"look/look.js", "look/look.next.js", "look/sketch.html", "look/drafts.html", "look/neg-ellipsis.html"}
FROZEN_LEGACY_DIRS = ("look/_v1/",)
SCAN_EXT = (".js", ".cjs", ".py", ".json", ".yaml", ".md", ".html", ".css")


def retired_hits(text, retired):
    import hashlib
    words = re.findall(r"[a-z0-9]+", text.lower())
    grams = set(words) | {a + " " + b for a, b in zip(words, words[1:])}
    return sum(1 for g in grams if hashlib.sha256(g.encode()).hexdigest()[:16] in retired)


def run_old_names():
    retired = load_retired()
    if not retired:
        print(f"CANNOT RUN --old-names: set {DENY_ENV} to the private deny file with its sha16: lines "
              "(the retired names are private and not in this repo)")
        return 2
    roots = [os.path.normpath(os.path.join(HERE, ".."))] + [p for p in EXTRA_ROOTS if os.path.isdir(p)]
    hits, scanned = [], 0
    for root in roots:
        for d, dirs, files in os.walk(root):
            dirs[:] = [x for x in dirs if x not in ("vendor", "node_modules", ".git") and "-built-" not in x]
            for fn in files:
                path = os.path.join(d, fn)
                rel = os.path.relpath(path, root)
                if not fn.endswith(SCAN_EXT):
                    continue
                if root in EXTRA_ROOTS and (rel in FROZEN_LEGACY or rel.startswith(FROZEN_LEGACY_DIRS)):
                    continue
                scanned += 1
                try:
                    n = retired_hits(open(path, encoding="utf-8", errors="replace").read(), retired)
                except OSError as e:
                    print(f"FAIL cannot read {path}: {e}")
                    return 1
                if n:
                    hits.append((path, n))
    for path, n in hits:
        print(f"FAIL retired name(s) in {path} ({n} distinct)")
    print(f"old-names: {scanned} files scanned under {', '.join(roots)}; {len(hits)} with retired names "
          f"(excluded: *-built-* dirs, vendor/, {len(FROZEN_LEGACY)} frozen Zdog files + look/_v1/)")
    return 1 if hits else 0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    if "--kits" in argv:
        return run_kits()
    if "--old-names" in argv:
        return run_old_names()
    return run_kits()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
