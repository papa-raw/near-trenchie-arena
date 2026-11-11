"""A persona's emoji set (Battle mode, Pat 2026-11-11): the glyphs its AI picks from when it speaks.

    game.emoji: 5-8 unique strings, each ONE emoji: 1-4 code points, each Extended_Pictographic or one
    of the modifiers U+FE0F (variation), U+200D (joiner), U+1F3FB-U+1F3FF (skin tone), U+20E3 (keycap);
    at most 16 UTF-8 bytes; no ASCII. A sheet without a valid set uses its temperament's default set from
    emoji_defaults.json, and says so (emoji_source "temperament").

Standard library only; the house feed, the checker and the creator's sheet builder share these rules.
"""

import json
from pathlib import Path

DEFAULTS_PATH = Path(__file__).resolve().parent / "emoji_defaults.json"
MIN_SET, MAX_SET, MAX_POINTS, MAX_BYTES = 5, 8, 4, 16
MODIFIERS = {0xFE0F, 0x200D, 0x20E3} | set(range(0x1F3FB, 0x1F400))
# Extended_Pictographic, condensed from Unicode 15.1 emoji-data.txt (inclusive ranges).
PICTOGRAPHIC = (
    (0x00A9, 0x00A9), (0x00AE, 0x00AE), (0x203C, 0x203C), (0x2049, 0x2049), (0x2122, 0x2122), (0x2139, 0x2139),
    (0x2194, 0x2199), (0x21A9, 0x21AA), (0x231A, 0x231B), (0x2328, 0x2328), (0x2388, 0x2388), (0x23CF, 0x23CF),
    (0x23E9, 0x23F3), (0x23F8, 0x23FA), (0x24C2, 0x24C2), (0x25AA, 0x25AB), (0x25B6, 0x25B6), (0x25C0, 0x25C0),
    (0x25FB, 0x25FE), (0x2600, 0x2605), (0x2607, 0x2612), (0x2614, 0x2685), (0x2690, 0x2705), (0x2708, 0x2712),
    (0x2714, 0x2714), (0x2716, 0x2716), (0x271D, 0x271D), (0x2721, 0x2721), (0x2728, 0x2728), (0x2733, 0x2734),
    (0x2744, 0x2744), (0x2747, 0x2747), (0x274C, 0x274C), (0x274E, 0x274E), (0x2753, 0x2755), (0x2757, 0x2757),
    (0x2763, 0x2767), (0x2795, 0x2797), (0x27A1, 0x27A1), (0x27B0, 0x27B0), (0x27BF, 0x27BF), (0x2934, 0x2935),
    (0x2B05, 0x2B07), (0x2B1B, 0x2B1C), (0x2B50, 0x2B50), (0x2B55, 0x2B55), (0x3030, 0x3030), (0x303D, 0x303D),
    (0x3297, 0x3297), (0x3299, 0x3299), (0x1F000, 0x1F0FF), (0x1F10D, 0x1F10F), (0x1F12F, 0x1F12F),
    (0x1F16C, 0x1F171), (0x1F17E, 0x1F17F), (0x1F18E, 0x1F18E), (0x1F191, 0x1F19A), (0x1F1AD, 0x1F1E5),
    (0x1F201, 0x1F20F), (0x1F21A, 0x1F21A), (0x1F22F, 0x1F22F), (0x1F232, 0x1F23A), (0x1F23C, 0x1F23F),
    (0x1F249, 0x1F3FA), (0x1F400, 0x1F53D), (0x1F546, 0x1F64F), (0x1F680, 0x1F6FF), (0x1F774, 0x1F77F),
    (0x1F7D5, 0x1F7FF), (0x1F80C, 0x1F80F), (0x1F848, 0x1F84F), (0x1F85A, 0x1F85F), (0x1F888, 0x1F88F),
    (0x1F8AE, 0x1F8FF), (0x1F90C, 0x1F93A), (0x1F93C, 0x1F945), (0x1F947, 0x1FAFF), (0x1FC00, 0x1FFFD),
)


# Text-default symbols: an emoji only with U+FE0F right after them (a review found ©, ™ passing as emoji).
TEXT_DEFAULT = {0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139, 0x24C2, 0x3030, 0x303D, 0x3297, 0x3299} | set(range(0x2194, 0x21AB))


def _pictographic(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in PICTOGRAPHIC)


def check_glyph(glyph) -> str | None:
    """None when `glyph` is one emoji by the rules above, else the reason."""
    if not isinstance(glyph, str) or not glyph:
        return "an emoji is a non-empty string"
    points = [ord(c) for c in glyph]
    if len(points) > MAX_POINTS or len(glyph.encode("utf-8")) > MAX_BYTES:
        return f"{glyph!r} is longer than one emoji ({MAX_POINTS} code points, {MAX_BYTES} bytes at most)"
    if any(cp < 0x80 for cp in points):
        return f"{glyph!r} holds ASCII; an emoji set holds emoji only"
    if not _pictographic(points[0]) or not all(_pictographic(cp) or cp in MODIFIERS for cp in points):
        return f"{glyph!r} is not an emoji"
    if points[0] in TEXT_DEFAULT and (len(points) < 2 or points[1] != 0xFE0F):
        return f"{glyph!r} is a text symbol; as an emoji it needs U+FE0F after it"
    for i, cp in enumerate(points):     # a joiner sits between two pictographs (a review found trailing ZWJ padding)
        if cp == 0x200D and (i == 0 or i == len(points) - 1 or not _pictographic(points[i + 1])
                             or not (_pictographic(points[i - 1]) or points[i - 1] == 0xFE0F
                                     or 0x1F3FB <= points[i - 1] <= 0x1F3FF)):
            return f"{glyph!r} has a joiner that joins nothing"
    return None


def _same(glyph: str) -> str:
    """The form two emoji are compared in: without U+FE0F (☀ and ☀️ are one emoji)."""
    return glyph.replace("\ufe0f", "")


def check_set(glyphs) -> str | None:
    """None when `glyphs` is a valid emoji set (5-8 unique emoji), else the reason."""
    if not isinstance(glyphs, list) or not MIN_SET <= len(glyphs) <= MAX_SET:
        return f"an emoji set holds {MIN_SET} to {MAX_SET} emoji"
    for g in glyphs:
        reason = check_glyph(g)
        if reason:
            return reason
    if len({_same(g) for g in glyphs}) != len(glyphs):
        return "an emoji set holds each emoji once"
    return None


def defaults() -> dict:
    return json.loads(DEFAULTS_PATH.read_text(encoding="utf-8"))["sets"]


def resolve(game: dict) -> tuple[list, str]:
    """(the set a speaker picks from, "sheet" | "temperament"): the sheet's own set when valid."""
    own = game.get("emoji")
    if own is not None and check_set(own) is None:
        return list(own), "sheet"
    sets = defaults()
    if game.get("temperament") not in sets:
        raise ValueError(f"unknown temperament {game.get('temperament')!r}: one of {', '.join(sorted(sets))}")
    return list(sets[game["temperament"]]), "temperament"


def pick(game: dict, chosen) -> dict:
    """The fields a public line carries for the emoji its AI chose: never free text, never silent."""
    glyphs, source = resolve(game)
    ok = chosen in glyphs
    return {"emoji": chosen if ok else glyphs[0], "emoji_source": source, "emoji_fallback": not ok}
