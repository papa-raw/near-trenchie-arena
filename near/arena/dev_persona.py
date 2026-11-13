"""Checked display-only persona data for local DEV admission. Sheets grant no access."""
from __future__ import annotations

import json
import re
from pathlib import Path
import sys

LORE = Path(__file__).resolve().parents[1] / 'lore'
sys.path.insert(0, str(LORE))
import check_personas as checker
from near.house.guard import Guard, load_blocklist

SCHEMA = json.loads((LORE / 'persona.schema.json').read_text())
KITS = json.loads((LORE / 'kits.json').read_text())


def check_sheet(sheet: dict) -> dict:
    """Return only checked public cosmetics; keep the private persona core off the feed."""
    if not isinstance(sheet, dict) or not isinstance(sheet.get('game'), dict):
        raise ValueError('sheet needs a game block; check it with near/lore/check_personas.py')
    try:
        slug = (sheet.get('identity') or {}).get('role', '')
        errors = checker.check_doc(sheet, slug, SCHEMA, KITS)
    except (KeyError, TypeError, AttributeError):
        raise ValueError('sheet is malformed; run near/lore/check_personas.py on it') from None
    if errors:
        raise ValueError('sheet refused: ' + errors[0][:160])
    game = sheet['game']
    return dict(name=game['name'], tag=game['tag'], temperament=game['temperament'],
                paletteIds=list(game['cosmetics']['palette']), fightStyle=game['fight_style'],
                **check_display_name(game['name'], game['tag']))


def check_display_name(name: str, tag: str, *, plain: bool = False) -> dict:
    """A missing private list is an explicit unchecked label, never a silent name approval."""
    for field, value in (("name", name), ("tag", tag)):
        if plain:  # legacy local DEV names are slugged; this never applies to a minted persona sheet
            if not isinstance(value, str) or not value.strip() or not value.isprintable() or len(value) > 64:
                raise ValueError('a plain DEV name needs 1 to 64 printable characters')
            continue
        schema = SCHEMA['properties']['game']['properties'][field]
        errors = []
        checker.validate(schema, value, SCHEMA, field, errors)
        if errors:
            raise ValueError('name or tag needs ASCII letters, digits, spaces, apostrophes or hyphens; name max 32, tag max 12')
    if not plain and (name != name.strip() or '  ' in name or not re.search('[A-Za-z]', name)
                      or re.search(r'(.)\1{4,}', name)):
        raise ValueError('name needs a letter, single spaces and no run of five repeated characters')
    blocklist = load_blocklist()
    name_guard = Guard(blocklist if blocklist is not None else dict(names=[], handles=[], slurs=[]), [])
    if name_guard.reason(name) or name_guard.reason(tag):
        raise ValueError('name or tag is blocked; choose an original spoof name')
    return dict(nameChecked=blocklist is not None,
                nameNotice=None if blocklist is not None else 'guard list missing · name unchecked')


def sheet_digest(sheet: dict) -> str:
    return checker.digest(sheet)


def read_sheet(path: str | None) -> dict | None:
    if path is None:
        return None
    try:
        sheet = json.loads(Path(path).read_text())
        check_sheet(sheet)
        return sheet
    except (OSError, ValueError) as exc:
        raise SystemExit(f'snap: cannot use sheet {path}: {exc}') from None


LOOK_OPTIONS = {
    "shape": ("gumdrop", "bean", "dumpling", "pear", "pebble", "acorn"),
    "body": tuple(f"p{i:02}" for i in range(1, 17)),
    "tone": ("light", "warm", "tan", "deep"),
    "eyes": ("dot", "sleepy", "sparkle", "happy", "wink", "keen"),
    "brows": ("none", "arch", "worried", "cross", "dash"),
    "mouth": ("smile", "o", "cat", "gap", "blep", "wave"),
    "hair": ("none", "sprout", "knot", "puffs", "cowlick", "fin", "buns"),
    "hairCol": ("p01", "p03", "p12", "p11", "p14", "p07", "p10", "p15"),
    "hat": ("st-cap", "hide", "c-head-maxi", "c-head-degen", "c-head-speedrunner", "c-head-builder"),
}


def check_look(value: dict | None) -> dict | None:
    """Allow only the approved player's cosmetic vocabulary, never item grants."""
    if value is None:
        return None
    look = value.get("look", value) if isinstance(value, dict) else value
    if not isinstance(look, dict) or any(k not in LOOK_OPTIONS or v not in LOOK_OPTIONS[k] for k, v in look.items()):
        raise ValueError("look has an unknown part; export a fresh look from the persona creator")
    return dict(look)


def read_look(path: str | None) -> dict | None:
    if path is None:
        return None
    try:
        return check_look(json.loads(Path(path).read_text()))
    except (OSError, ValueError) as exc:
        raise SystemExit(f"snap: cannot use look {path}: {exc}") from None
