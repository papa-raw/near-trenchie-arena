"""The five battle options (F77) as a closed set, resolved to legal kits on the live rules table.

Brawler Swing, Hunter Lunge, Survivor Beam, Looter Lob and Brawler Zap, each with a fixed signature.
Shot gets no preset. The sweep measures exactly these (style, weapon, signature) triples (balance.PRESETS); a persona sheet that names a
preset must match one of these rows.
"""

import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from . import balance, sim
except ImportError:
    import balance
    import sim

NAMES = ("Brawler Swing", "Hunter Lunge", "Survivor Beam", "Looter Lob", "Brawler Zap")


def preset_kit(rules, index):
    """The common (default-menu) kit for one preset: highest-stat head and body, the named weapon and signature."""
    style, weapon, signature = balance.PRESETS[index]
    items = rules["items"]

    def best(slot, field=None, kind=None):
        rows = [r for r in sorted(items) if items[r]["slot"] == slot and items[r]["tier"] == "common"
                and items[r]["default"] and (field is None or items[r][field] == kind)]
        return max(rows, key=lambda r: (sum(items[r]["stats"].values()), r))

    return {"style": style, "name": NAMES[index], "weapon_kind": weapon, "signature": signature,
            "loadout": {"head": best("head"), "body": best("body"),
                        "weapon": best("weapon", "weapon", weapon), "trinket": best("trinket", "signature", signature)}}


def all_presets(rules):
    return [preset_kit(rules, i) for i in range(len(balance.PRESETS))]
