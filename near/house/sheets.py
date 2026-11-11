"""The 14 house persona sheets, read from near/lore/personas, in the shape the house runtime needs.

Each sheet becomes {"name", "tag", "prefix", "keyed"}:
- prefix: the system message the model reads first on every call (the cacheable prefix): who it is, its
  short brief, the rendered game block (the same render lore/check_personas.py measures against its
  150-token budget) and the output rules every public line must keep.
- keyed: one line per moment the driver names (ko_given, ko_taken, loot, idle), taken from the sheet's
  own reactions and voice lines. A keyed line is the labelled fallback when a banter line still repeats
  after its reroll; it is never shown as a fresh line.
Standard library only.
"""

import importlib.util
import json
from pathlib import Path

LORE = Path(__file__).resolve().parents[1] / "lore"
PERSONAS = LORE / "personas"
MOMENTS = ("idle", "ko_given", "ko_taken", "loot")
RULES = ("Rules for every answer: answer only in the format asked. A banter line is one short sentence, at most 14 words, "
         "in your own voice: no quotes, hashtags, emoji or stage directions, and never the same joke twice. Never name a real "
         "person, handle or firm. Never blame another trenchie for the Great Rug; only off-island myths take the blame. "
         "Never use the words scam, fraud or jail.")


def _render():
    spec = importlib.util.spec_from_file_location("check_personas_render", LORE / "check_personas.py")
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.path.insert(0, str(LORE))          # check_personas imports its sibling check_sheets
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(LORE))
    return module.render


def keyed_lines(game):
    """The sheet's own lines for each driver moment; every moment gets one."""
    r, v = game["reactions"], game["voice"]
    return {"ko_given": r["hit_prediction"], "ko_taken": r["ko_by_rival"], "loot": v[1 % len(v)], "idle": v[0]}


def prefix(doc, render):
    g = doc["game"]
    return "\n".join([
        "You are %s (arena tag \"%s\"), a house trenchie in Trenchie Village, an island where AI trenchies washed up "
        "after the Great Rug brawl in one free-for-all arena for gear." % (g["name"], g["tag"]),
        doc["identity"]["brief"],
        "Your character: " + render(g).replace("\n", " / "),
        RULES])


def load(directory=PERSONAS, names=None):
    """{slug: sheet} for every persona file (or only the named slugs); the slug is the arena's house id."""
    render = _render()
    out = {}
    for path in sorted(Path(directory).glob("*.json")):
        doc = json.loads(path.read_bytes())
        g = doc["game"]
        if names is not None and path.stem not in names:
            continue
        out[path.stem] = {"name": g["name"], "tag": g["tag"], "slug": path.stem, "prefix": prefix(doc, render),
                          "keyed": keyed_lines(g), "game": g}       # the raw game block: style, rivals, allies, emoji (battle.py)
    return out


def guard_names(loaded):
    """The spoof names and tags the guard allows as whole matches (the longest match wins over a real name)."""
    return sorted({n for s in loaded.values() for n in (s["name"], s["tag"])})
