#!/usr/bin/env python3
"""gen_kits.py: writes kits.json, the 14 house trenchie kits plus the item pool.

Run: python3 -I near/lore/gen_kits.py        (writes near/lore/kits.json next to this file)
Check: python3 -I near/lore/check_sheets.py --kits

The design tables live here as data, and kits.json is generated, so stat budgets are computed
and never hand-typed. Everything below is INFERRED tuning unless a line cites a source. The balance
sweep recalibrates it.

Every constant below states its rule in plain words: the 14 approved names, the starting loadouts, the five fight
styles, the tier budgets, the six shared signatures and the named legendaries, the set tags, and the item record shape
the arena prototype reads.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "kits.json")

STATS = ["damage", "cooldown", "hp", "speed", "range"]          # frame.js STAT order
BUDGET = {"common": 10, "rare": 16, "legendary": 24}            # B16b
# One fixed split per tier, highest share first. Max share = 4/10, 6/16, 9/24, all <= 40% (§2.4).
SPLIT = {"common": [4, 3, 2, 1, 0], "rare": [6, 4, 3, 2, 1], "legendary": [9, 6, 4, 3, 2]}


def stats(tier, order):
    """order: the 5 stats, most-favoured first -> {stat: points} in frame.js key order."""
    assert sorted(order) == sorted(STATS), order
    pts = dict(zip(order, SPLIT[tier]))
    return {s: pts[s] for s in STATS}


def item(id_, name, slot, tier, *, weapon=None, signature=None, reskin_of=None, order, set_tag=None,
         origin="pool", house=None, starter=False, fixed=None):
    """One item, keys exactly frame.js RECORD.item, in that order."""
    return {
        "id": id_, "name": name, "slot": slot, "tier": tier,
        "weapon": weapon, "signature": signature, "reskinOf": reskin_of,
        "stats": fixed if fixed is not None else stats(tier, order),
        "setTag": set_tag, "origin": origin, "house": house, "starter": starter,
    }


# ---------------------------------------------------------------- stat leanings (INFERRED)
WEAPON_ORDER = {   # what each attack type wants first
    "swing": ["damage", "hp", "cooldown", "speed", "range"],     # brawler in the crowd
    "shot":  ["cooldown", "damage", "range", "speed", "hp"],     # kiter
    "beam":  ["range", "damage", "cooldown", "hp", "speed"],     # sniper
    "lob":   ["damage", "range", "cooldown", "hp", "speed"],     # zoner
    "zap":   ["cooldown", "damage", "range", "hp", "speed"],     # crowd punisher
    "lunge": ["speed", "damage", "cooldown", "hp", "range"],     # diver
}
WEAPON_TAG = {"swing": "maxi", "shot": "degen", "beam": "builder", "lob": "builder", "zap": "degen", "lunge": "speedrunner"}
TAG_ORDER = {      # §2.6 fantasy: tank / glass cannon / hit and run / zoner
    "maxi":        ["hp", "damage", "cooldown", "range", "speed"],
    "degen":       ["damage", "cooldown", "speed", "range", "hp"],
    "speedrunner": ["speed", "cooldown", "damage", "hp", "range"],
    "builder":     ["range", "cooldown", "damage", "hp", "speed"],
}
SIG_ORDER = {      # what each signature's fire rule rewards (§2.5)
    "beam_sweep":   ["range", "damage", "cooldown", "hp", "speed"],
    "chain_storm":  ["cooldown", "damage", "range", "hp", "speed"],
    "shockwave":    ["hp", "damage", "cooldown", "range", "speed"],
    "blink_strike": ["damage", "speed", "cooldown", "hp", "range"],
    "magnet":       ["speed", "hp", "cooldown", "range", "damage"],
    "bubble":       ["hp", "cooldown", "range", "damage", "speed"],
}


def body_order(tag):
    """Bodies lean like heads of the same tag with the 2nd and 3rd stats swapped, so the two differ."""
    o = list(TAG_ORDER[tag])
    o[1], o[2] = o[2], o[1]
    return o


# ---------------------------------------------------------------- starters (B11, the prototype's STARTER_ITEM; ids and stats kept from its stub)
STARTERS = [
    item("st-bonk", "Driftwood Bonk", "weapon", "common", weapon="swing", order=None, origin="starter", starter=True,
         fixed={"damage": 4, "cooldown": 3, "hp": 0, "speed": 0, "range": 3}),     # a named starter weapon
    item("st-roll", "Dodge Roll", "trinket", "common", signature="dodge_roll", order=None, origin="starter", starter=True,
         fixed={"damage": 0, "cooldown": 4, "hp": 3, "speed": 3, "range": 0}),     # §2.5 names it
    item("st-cap", "Sun Cap", "head", "common", order=None, origin="starter", starter=True,
         fixed={"damage": 3, "cooldown": 0, "hp": 4, "speed": 0, "range": 3}),
    item("st-tee", "Beach Tee", "body", "common", order=None, origin="starter", starter=True,
         fixed={"damage": 0, "cooldown": 3, "hp": 4, "speed": 3, "range": 0}),
]
STARTER_KIT = {"weapon": "st-bonk", "trinket": "st-roll", "head": "st-cap", "body": "st-tee"}

# ---------------------------------------------------------------- the pool: one common and one rare per weapon type, per tag x (head, body), per signature
WEAPON_NAMES = {   # (common, rare): island junk, original
    "swing": ("Oar Swipe", "Captain's Oar"),
    "shot":  ("Pebble Sling", "Pearl Sling"),
    "beam":  ("Trout", "Prism Lens"),
    "lob":   ("Coconut Mortar", "Golden Coconut Mortar"),
    "zap":   ("Jelly Zapper", "Moon Jelly Zapper"),
    "lunge": ("Narwhal Pike", "Swordfish Pike"),
}
HEAD_NAMES = {"maxi": ("Bucket Hat", "Lifeguard Helmet"), "degen": ("Party Cone", "Neon Visor"),
              "speedrunner": ("Sweatband", "Aero Goggles"), "builder": ("Hard Hat", "Surveyor Hat")}
BODY_NAMES = {"maxi": ("Life Vest", "Diving Suit"), "degen": ("Hawaiian Shirt", "Velvet Robe"),
              "speedrunner": ("Wetsuit", "Racing Jersey"), "builder": ("Overalls", "Tool Belt Vest")}
TRINKET_NAMES = {"beam_sweep": ("Pocket Laser", "Lighthouse Charm"), "chain_storm": ("Static Sock", "Storm Jar"),
                 "shockwave": ("Thump Shell", "Conch of Thunder"), "blink_strike": ("Smoke Bomb", "Ink Cloud Locket"),
                 "magnet": ("Fridge Magnet", "Horseshoe Magnet"), "bubble": ("Bubble Wand", "Pearl Bubble Ring")}


def hy(s):
    return s.replace("_", "-")


POOL = []
for t, prefix in (("common", "c"), ("rare", "r")):
    k = 0 if t == "common" else 1
    for w, names in WEAPON_NAMES.items():
        POOL.append(item(f"{prefix}-{w}", names[k], "weapon", t, weapon=w, order=WEAPON_ORDER[w], set_tag=WEAPON_TAG[w]))
    for tag in TAG_ORDER:
        POOL.append(item(f"{prefix}-head-{tag}", HEAD_NAMES[tag][k], "head", t, order=TAG_ORDER[tag], set_tag=tag))
        POOL.append(item(f"{prefix}-body-{tag}", BODY_NAMES[tag][k], "body", t, order=body_order(tag), set_tag=tag))
    for sig, names in TRINKET_NAMES.items():
        POOL.append(item(f"{prefix}-{hy(sig)}", names[k], "trinket", t, signature=sig, order=SIG_ORDER[sig]))

# ---------------------------------------------------------------- the 14 house trenchies, B21 order
# loadout (B8): in B21 order the first seven start with "commons" (the legendary + 3 commons), the last seven with
# "rares" (3 rares + the legendary). Pat 2026-11-03: no identity label, only the loadout.
# The first 6 legendaries keep their original pairings (signature and holder kept; two renamed
# 2026-11-03 by an orchestrator decision, now Lifeboat and
# Builder Census; the old names are not in this repo). Round 7 (Q16): Stack Sats
# is re-fitted to a bitcoin-coded trenchie, Satrenchi (the stack that never moves), replacing its earlier legendary;
# the ETH-themed trenchie gets an ETH-themed magnet, Ether Stack. Laser Eyes stays with Laser Sailor. (Before round 7, Stack Sats sat with the ETH-themed trenchie.)
# (§2.5 offers him or a second Laser Sailor kit, and Laser Sailor already holds Laser Eyes). The other 8 are new
# original names (INFERRED). §5 fixes three of them: Vitrenchik fires a Chain Storm, Kain Warrior a Shockwave,
# Mert Mumtrench a Magnet. Stretch kits map to the nearest shared signature (§2.5): drones -> blink_strike (both
# go for the lowest HP), crops -> shockwave (§5), peel field -> Liquidity Wave (already a shockwave).
# Guardian is left out on purpose: it scores "stay by ward" (§3.2), and the endless FFA has no ward until the
# bodyguard jobs ship (B92 stretch 1).
#   (name, id, loadout, style, weapon, head/body tag, (legendary id, name, reskinOf), paletteIds, look brief)
ROSTER = [
    ("Satrenchi", "satrenchi", "commons", "hunter", "lunge", "builder",
     ("leg-stack-sats", "Stack Sats", "magnet"), ["p06", "p04"],
     "a grey hood over a stack of gold coins nobody has ever seen move; it spirals open and sucks loot in"),
    ("Captain Banana Zone", "captain-banana-zone", "commons", "brawler", "swing", "maxi",
     ("leg-liquidity-wave", "Liquidity Wave", "shockwave"), ["p12", "p09"],
     "a banana-yellow surfboard slammed flat; a sky-blue wave ring rolls out from it"),
    ("Vitrenchik", "vitrenchik", "commons", "brawler", "lob", "builder",
     ("leg-tinker-coil", "Tinker Coil", "chain_storm"), ["p11", "p07"],
     "a hand-wound copper coil on a backpack; lilac sparks hop body to body"),
    ("Laser Sailor", "laser-sailor", "commons", "survivor", "beam", "maxi",
     ("leg-laser-eyes", "Laser Eyes", "beam_sweep"), ["p15", "p16"],   # not p13: that is the legendary tier gold (designer 2026-11-03)
     "the eyes glow red, and a red beam sweeps the cone"),
    ("Tommy Leeth", "tommy-leeth", "commons", "looter", "shot", "degen",
     ("leg-ether-stack", "Ether Stack", "magnet"), ["p10", "p04"],
     "a tower of lilac ether coins that whirls into a spiral and sucks loot in"),
    ("Trenchtoly", "trenchtoly", "commons", "hunter", "lunge", "speedrunner",
     ("leg-fast-finality", "Fast Finality", "blink_strike"), ["p08", "p11"],
     "a green speed streak that ends in a stamped 'FINAL' tick mark behind the target"),
    ("Kathie Moonwood", "kathie-moonwood", "commons", "survivor", "lob", "degen",
     ("leg-lifeboat", "Lifeboat", "bubble"), ["p14", "p05"],
     "a little wooden boat hull closes over her as a peach bubble"),
    ("Illia Trenchukhin", "illia-trenchukhin", "rares", "brawler", "zap", "builder",
     ("leg-hydra-halo", "Hydra Halo", "beam_sweep"), ["p03", "p09"],
     "a halo of eight tiny heads, each firing a thin sky-blue beam as the sweep passes"),
    ("Eddie Lazertrench", "eddie-lazertrench", "rares", "survivor", "swing", "speedrunner",
     ("leg-loop-flywheel", "Loop Flywheel", "shockwave"), ["p09", "p06"],
     "a flywheel on the back spins up and throws a grey ring outward"),
    ("Mert Mumtrench", "mert-mumtrench", "rares", "brawler", "shot", "speedrunner",
     ("leg-priority-fee", "Priority Fee", "magnet"), ["p07", "p15"],
     "a mint toll gate; floor items queue through it to him, fastest first"),
    ("Avichad", "avichad", "rares", "brawler", "zap", "builder",
     ("leg-builder-census", "Builder Census", "chain_storm"), ["p05", "p12"],
     "a clipboard that crackles; yellow tally marks jump from head to head"),
    ("Kain Warrior", "kain-warrior", "rares", "looter", "swing", "builder",
     ("leg-harvest-quake", "Harvest Quake", "shockwave"), ["p02", "p08"],
     "a pitchfork stamped into the dirt; a ring of sprouting crops bursts outward"),
    ("Hameme Pumpeshi", "hameme-pumpeshi", "rares", "hunter", "lunge", "degen",
     ("leg-poker-face", "Poker Face", "bubble"), ["p01", "p15"],
     "a fanned hand of cards closes into a shield; it pops like a table flip"),
    ("Stepan Gershunode", "stepan-gershunode", "rares", "hunter", "beam", "speedrunner",
     ("leg-router-drone", "Router Drone", "blink_strike"), ["p04", "p10"],
     "a small cream drone blinks out of his orbit and reappears behind the weakest brawler"),
]

# ---------------------------------------------------------------- Q59: 3-4 seeded rivalries and a couple of alliances (INFERRED pairings)
RIVALS = [
    ("laser-sailor", "vitrenchik",
     "one coin forever against a thousand experiments; the first beef on the island"),
    ("trenchtoly", "illia-trenchukhin",
     "whose chain is faster: the speedster against the builder of the home chain"),
    ("tommy-leeth", "hameme-pumpeshi",
     "the bull who always sees a bigger cycle ahead against the sceptic who wants proof first: who called the top"),
    ("captain-banana-zone", "kathie-moonwood",
     "two chart forecasters with rival curves; each brawl settles whose line was right this week"),
]
ALLIANCES = [
    ("mert-mumtrench", "trenchtoly", "same-chain crew: they back each other's speed claims on the timeline"),
    ("avichad", "stepan-gershunode", "both think agents will hire agents; they split the work and the loot"),
]


# Arena short tags (round 7: Q18 dec:259, "Names, round 7" dec:265, Laser Sailor dec:260, Trenchukhin dec:262,
# Tommy Leeth dec:273, and Pat's later word for Eddie). Full names stay on the persona card. Single words, except Pat's own
# Q18 example "Banana Zone". The last five are the lore lane's proposals, for Pat's veto.
TAGS = {
    "laser-sailor": "Sailor", "eddie-lazertrench": "Eddie", "hameme-pumpeshi": "Pumpeshi", "stepan-gershunode": "Gershunode",
    "kathie-moonwood": "Moonwood", "avichad": "Avichad", "tommy-leeth": "Leeth", "illia-trenchukhin": "Trenchukhin",
    "captain-banana-zone": "Banana Zone",
    "satrenchi": "Satrenchi", "vitrenchik": "Vitrenchik", "trenchtoly": "Trenchtoly", "mert-mumtrench": "Mumtrench",
    "kain-warrior": "Warrior",
}


# Signature pieces (the 14 looked alike in review): every trenchie wears one SIGNATURE piece of its own, drawn by
# the art lane. It replaces the pool head or body the kit used to share, and copies that piece's tier, stats and set tag,
# so B8 loadouts, budgets and balance stay as they were; only the look and the item id change. Slots are chosen so no
# shared pool item appears in more than two kits: in each three-kit group with the same rare tag (builder: Trenchukhin,
# Avichad, Kain Warrior; speedrunner: Eddie, Mumtrench, Gershunode) one signature sits on the head and two on the body.
# Names are the lore lane's first proposals from each trenchie's lore; the art lane may rename them (INFERRED, original).
SIGNATURE_PIECES = {   # trenchieId: (slot, name, look brief for the art lane)
    # Signature pieces: each piece is that trenchie's
    # caricature trait. Names are original knowing nods, never a real name.
    # The art lane's limits: 1-3 primitives, one strong outline, nothing over the eyes or mouth. Face traits (glasses,
    # brows, smiles) that are not the piece are drawn by the art lane on the face. Rows the sheet marks unverified lead with
    # a prop (Lazertrench, Gershunode, Banana Zone).
    # Pat: Vitrenchik, Tommy Leeth and Trenchukhin wear chain hats (our own drawn marks, no trademark strings);
    # Vitrenchik's piece moves from body to head, so his body is the pool Overalls again; his stats are unchanged.
    "satrenchi": ("head", "Genesis Hood", "a deep grey hood framing a shadowed face with two soft lamp-glow eyes (eyes stay visible)"),
    "captain-banana-zone": ("body", "Banana Bandolier", "a bandolier of bananas slung across an open linen beach shirt"),
    "vitrenchik": ("head", "Rainbow Unicorn Hat", "a soft hat with a rainbow-striped unicorn horn on top, over tousled light-brown hair (Pat)"),
    "laser-sailor": ("head", "Silver Swept Hair", "swept-back silver-grey hair; bitcoin-orange as the only accent"),
    "tommy-leeth": ("head", "Ether Peak Cap", "a lilac cap with a blue band and a two-tone diamond standing on top (Pat; as drawn on the approved art board)"),
    "trenchtoly": ("head", "Gradient Ballcap", "a black baseball cap with a purple-to-green gradient brim"),
    "kathie-moonwood": ("head", "Side-Part Bob & Specs", "a shoulder-length side-parted light-brown bob, with dark rectangular glasses framing the eyes"),
    "illia-trenchukhin": ("head", "Nightshard Beanie", "a mint beanie with a folded brim and a dark N mark (Pat; pastel, as drawn on the approved art board)"),
    "eddie-lazertrench": ("body", "Paradox Cube", "a plain wire cube floating by the shoulder (as drawn on the approved art board)"),
    "mert-mumtrench": ("head", "Night-Shift Headset", "a smooth bald dome under an always-on headset: a band over the crown, two ear cups, a mic with a speech bubble (mouth stays visible)"),
    "avichad": ("body", "Trail Shell Jacket", "a black technical shell jacket with a headset mic clipped to the collar"),
    "kain-warrior": ("head", "Spiked Fringe", "short hair spiked up at the front, greying at the sides"),
    "hameme-pumpeshi": ("head", "High-Roller Visor", "a green card-dealer visor on a smooth bald dome, brim above one raised sceptical brow"),
    "stepan-gershunode": ("body", "Node Rack Backpack", "a compact server-rack backpack with blinking node lights"),
}


def build():
    items = list(STARTERS) + list(POOL)
    rows = []
    for name, tid, loadout, style, weapon, tag, (lid, lname, sig), pal, look in ROSTER:
        tier = "rare" if loadout == "rares" else "common"     # B8: 3 rares or 3 commons beside the legendary
        p = "r" if tier == "rare" else "c"
        items.append(item(lid, lname, "trinket", "legendary", signature=sig, reskin_of=sig, order=SIG_ORDER[sig],
                          origin=f"house:{tid}", house=tid))
        kit = {"weapon": f"{p}-{weapon}", "trinket": lid, "head": f"{p}-head-{tag}", "body": f"{p}-body-{tag}"}
        sslot, sname, slook = SIGNATURE_PIECES[tid]
        base = next(it for it in POOL if it["id"] == kit[sslot])
        sid = f"sig-{tid}"
        items.append(item(sid, sname, sslot, tier, order=None, set_tag=base["setTag"], origin=f"house:{tid}", house=tid,
                          fixed=dict(base["stats"])))
        kit[sslot] = sid
        rows.append({
            "trenchieId": tid, "name": name, "tag": TAGS[tid], "loadout": loadout, "fightStyle": style,
            "kit": kit,
            "signaturePiece": {"id": sid, "name": sname, "slot": sslot, "look": slook, "replaces": base["id"]},
            "legendary": {"id": lid, "name": lname, "reskinOf": sig, "look": look, "serial": 1},   # Q20: remakes count up from #1
            "paletteIds": pal,
        })
    doc = {
        "spec": "trenchie-kits/1",
        "generatedBy": "near/lore/gen_kits.py (2026-11-03)",
        "status": "INFERRED tuning; the balance sweep recalibrates every number",
        "budgets": {**BUDGET, "maxShareOfBudget": 0.4},
        "signatures": list(SIG_ORDER),
        "starterKit": STARTER_KIT,
        "trenchies": rows,
        "items": items,
        "rivals": [{"a": a, "b": b, "reason": r} for a, b, r in RIVALS],
        "alliances": [{"a": a, "b": b, "reason": r} for a, b, r in ALLIANCES],
    }
    return doc


if __name__ == "__main__":
    doc = build()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=1, ensure_ascii=False)
        f.write("\n")
    print(f"wrote {OUT}: {len(doc['trenchies'])} trenchies, {len(doc['items'])} items")
