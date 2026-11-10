#!/usr/bin/env python3
"""check_kit.py — the kit (kit.json) and its 24 menu specs pass the item checks.

Checks: 4 slots x 8 bases, every base inside its slot box with at most 40 nodes and palette-only colours, the menu names
24 rows whose bases exist in their slot, and every spec in specs/ (the 24 menu rows and the 14 legendaries) passes check_items. Run: python3 -I near/items/check_kit.py
(set CHECK_ITEMS_DIR to use a check_items.py that lives elsewhere).
"""
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
CHECKER = Path(os.environ.get("CHECK_ITEMS_DIR", HERE)).resolve()
sys.path.insert(0, str(CHECKER)); sys.path.insert(0, str(CHECKER.parent))
import check_items  # noqa: E402
from arena import sim  # noqa: E402


def main():
    limits, kit, bad = check_items.load_limits(CHECKER / "limits.json"), json.loads((HERE / "kit.json").read_text()), []
    if sorted(kit["bases"]) != ["body", "head", "trinket", "weapon"]:
        bad.append("kit has the four slots")
    for slot, bases in kit["bases"].items():
        if len(bases) < 8:
            bad.append("%s has %d bases, fewer than 8" % (slot, len(bases)))
        box = limits["slot_boxes"][slot]
        for name, base in bases.items():
            errors = []
            count, points = check_items.walk(base["nodes"], limits, errors, "%s/%s" % (slot, name))
            if count > limits["max_nodes"]:
                errors.append("%d nodes" % count)
            if any(p[i] < box["min"][i] - limits["box_tolerance"] or p[i] > box["max"][i] + limits["box_tolerance"] for p in points for i in range(3)):
                errors.append("%s/%s leaves the %s box" % (slot, name, slot))
            bad.extend(errors)
    if len(kit["menu"]) != 24:
        bad.append("menu has %d rows, not 24" % len(kit["menu"]))
    for row in kit["menu"]:
        slot, _, base = row["kit"].partition("/")
        if base not in kit["bases"].get(slot, {}):
            bad.append("menu row %s names a missing base %s" % (row["row"], row["kit"]))
    results = check_items.check_dir(HERE / "specs", kit, sim.DEFAULT_RULES, limits)
    bad.extend("%s: %s" % (k, "; ".join(v)) for k, v in results.items() if v)
    menu_specs = [k for k in results if not k.startswith("leg-")]
    if len(menu_specs) != 24:
        bad.append("%d menu specs, not 24" % len(menu_specs))
    if len(results) - len(menu_specs) not in (0, 14):
        bad.append("%d legendary specs, not 0 or 14" % (len(results) - len(menu_specs)))
    for line in bad:
        print("FAIL", line)
    print("kit: %d bases, %d menu rows, %d specs checked, %d failures" % (sum(len(b) for b in kit["bases"].values()), len(kit["menu"]), len(results), len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
