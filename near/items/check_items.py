#!/usr/bin/env python3
"""ItemSpec checks (trenchie-item/3) as a build-time test on the rules table (F26).

No PASS, no runtime validator: a row that fails stops the build. Checks, in one rule set for
kit-built and free-drawn items: slot and tier, stats inside the tier budget with one stat at most
40%, move on weapons, sig on trinkets, tag on head/body/weapon, palette ids p01-p16 only (raw hex and
the reserved danger hue are refused), size fields in range, node types on the primitive whitelist,
scale 0.25-4 per axis, at most 40 nodes after kit expansion and 4 KB as authored, every node inside the
slot box after scale, rotate and translate, a kit id that names a base in the kit for that slot, a
name that passes the banned-word list, and the row agreeing with the rules table.

Run: python3 -I near/items/check_items.py [--specs DIR] [--kit FILE]
"""
import argparse
import json
import math
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from arena import sim  # noqa: E402

SIZE_FIELDS = {"sphere": ("r",), "hemisphere": ("r",), "cylinder": ("r", "h"), "cone": ("r", "h"),
               "box": ("w", "h", "d"), "torus": ("r", "tube"), "tube": ("width",), "plate": ("w", "h")}


def load_limits(path: str | Path = HERE / "limits.json") -> dict:
    limits = json.loads(Path(path).read_text())
    limits["banned_words"] = [
        "".join(word) if isinstance(word, list) else word
        for word in limits["banned_words"]
    ]
    return limits


def canonical_size(spec):
    return len(json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def matrix_apply(node, points):
    """scale, then rotate (degrees, X then Y then Z), then translate."""
    scale = node.get("scale", 1)
    sx, sy, sz = (scale, scale, scale) if isinstance(scale, (int, float)) else scale
    rx, ry, rz = (math.radians(a) for a in node.get("rotate", (0, 0, 0)))
    tx, ty, tz = node.get("translate", (0, 0, 0))
    out = []
    for x, y, z in points:
        x, y, z = x * sx, y * sy, z * sz
        y, z = y * math.cos(rx) - z * math.sin(rx), y * math.sin(rx) + z * math.cos(rx)
        x, z = x * math.cos(ry) + z * math.sin(ry), -x * math.sin(ry) + z * math.cos(ry)
        x, y = x * math.cos(rz) - y * math.sin(rz), x * math.sin(rz) + y * math.cos(rz)
        out.append((x + tx, y + ty, z + tz))
    return out


def local_points(node):
    """The eight corners of a primitive's own axis-aligned box (a group has none of its own)."""
    kind = node["type"]
    if kind == "sphere":
        r = node["r"]; lo, hi = (-r, -r, -r), (r, r, r)
    elif kind == "hemisphere":
        r = node["r"]; lo, hi = (-r, 0, -r), (r, r, r)
    elif kind in ("cylinder", "cone"):
        r, h = node["r"], node["h"]; lo, hi = (-r, -h / 2, -r), (r, h / 2, r)
    elif kind == "box":
        w, h, d = node["w"], node["h"], node["d"]; lo, hi = (-w / 2, -h / 2, -d / 2), (w / 2, h / 2, d / 2)
    elif kind == "torus":
        r, t = node["r"], node["tube"]; lo, hi = (-(r + t), -t, -(r + t)), (r + t, t, r + t)
    elif kind == "tube":
        pts, half = node["points"], node["width"] / 2
        lo = tuple(min(p[i] for p in pts) - half for i in range(3))
        hi = tuple(max(p[i] for p in pts) + half for i in range(3))
    elif kind == "plate":
        w, h = node["w"], node["h"]; lo, hi = (-w / 2, -h / 2, -0.025), (w / 2, h / 2, 0.025)
    else:
        return []
    return [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]


def walk(nodes, limits, errors, path, parent_chain=()):
    """Yield world-space corner points for every leaf; collect structural errors; count nodes."""
    count = 0
    points = []
    for index, node in enumerate(nodes):
        where = "%s[%d]" % (path, index)
        count += 1
        if not isinstance(node, dict) or node.get("type") not in limits["primitives"]:
            errors.append("%s: type %r is not on the primitive whitelist" % (where, node.get("type") if isinstance(node, dict) else node))
            continue
        kind = node["type"]
        color = node.get("color")
        if kind != "group" and (not isinstance(color, str) or color not in limits["palette"]):
            errors.append("%s: color %r is not a palette id p01-p16" % (where, color))
        elif kind == "group" and color is not None and color not in limits["palette"]:
            errors.append("%s: color %r is not a palette id p01-p16" % (where, color))
        scale = node.get("scale", 1)
        factors = [scale] * 3 if isinstance(scale, (int, float)) and not isinstance(scale, bool) else scale
        if (not isinstance(factors, (list, tuple)) or len(factors) != 3
                or any(isinstance(f, bool) or not isinstance(f, (int, float)) or not limits["scale"][0] <= f <= limits["scale"][1]
                       for f in factors)):
            errors.append("%s: scale %r must stay within %s per axis" % (where, scale, limits["scale"]))
            factors = [1, 1, 1]
        for key in ("translate", "rotate"):
            value = node.get(key, (0, 0, 0))
            if (not isinstance(value, (list, tuple)) or len(value) != 3
                    or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value)):
                errors.append("%s: %s must be three numbers" % (where, key))
        for field in SIZE_FIELDS.get(kind, ()):
            v = node.get(field)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= limits["size_max"]:
                errors.append("%s: size field %s=%r is out of range (0, %s]" % (where, field, v, limits["size_max"]))
        if kind == "tube":
            pts = node.get("points")
            lo, hi = limits["tube_points"]
            if (not isinstance(pts, list) or not lo <= len(pts) <= hi
                    or any(not isinstance(p, (list, tuple)) or len(p) != 3 for p in pts)):
                errors.append("%s: a tube needs %d-%d points of three numbers" % (where, lo, hi))
        if errors and any(e.startswith(where) for e in errors):
            continue
        if kind == "group":
            inner_count, inner = walk(node.get("children", []), limits, errors, where + ".children")
            count += inner_count
            points.extend(matrix_apply(node, inner))
        else:
            points.extend(matrix_apply(node, local_points(node)))
    return count, points


def expand(spec, kit):
    """Kit base nodes first, then the item's own nodes (decorations, or the full tree when free-drawn)."""
    nodes = []
    if "kit" in spec:
        slot, _, base = spec["kit"].partition("/")
        nodes.extend(kit.get("bases", {}).get(slot, {}).get(base, {}).get("nodes", []))
    nodes.extend(spec.get("nodes", []))
    return nodes


def check_item(spec, rules, kit, limits):
    errors = []
    name = spec.get("id", "?")
    if spec.get("spec") != "trenchie-item/3":
        errors.append("spec must be trenchie-item/3")
    row = rules["items"].get(spec.get("id"))
    if row is None:
        errors.append("id %r is not a row of the rules table" % spec.get("id"))
        return errors
    slot, tier = spec.get("slot"), spec.get("tier")
    if slot not in limits["slot_boxes"]:
        errors.append("slot %r must be head|body|weapon|trinket" % slot)
        return errors
    if tier not in limits["budgets"]:
        errors.append("tier %r must be common|rare|legendary" % tier)
        return errors
    if (slot, tier) != (row["slot"], row["tier"]):
        errors.append("slot/tier %s/%s disagree with the rules row %s/%s" % (slot, tier, row["slot"], row["tier"]))
    stats = spec.get("stats", {})
    budget = limits["budgets"][tier]
    if dict(stats) != dict(row["stats"]):
        errors.append("stats disagree with the rules row")
    if any(type(v) is not int or v < 0 for v in stats.values()):
        errors.append("stats must be non-negative integers")
    elif sum(stats.values()) > budget:
        errors.append("stats total %d exceed the %s budget %d" % (sum(stats.values()), tier, budget))
    elif any(v * 100 > budget * limits["stat_cap_pct"] for v in stats.values()):
        errors.append("one stat exceeds %d%% of the %s budget" % (limits["stat_cap_pct"], tier))
    if slot == "weapon":
        if spec.get("move") not in rules["weapons"]:
            errors.append("a weapon needs move from the rules table's weapons")
        elif spec["move"] != row["weapon"]:
            errors.append("move disagrees with the rules row")
    elif "move" in spec:
        errors.append("move belongs to weapons only")
    if slot == "trinket":
        if spec.get("sig") not in rules["signatures"]:
            errors.append("a trinket needs sig from the rules table's signatures")
        elif spec["sig"] != row["signature"]:
            errors.append("sig disagrees with the rules row")
    elif "sig" in spec:
        errors.append("sig belongs to trinkets only")
    if "tag" in spec and (slot == "trinket" or not isinstance(spec["tag"], str)
                          or not re.fullmatch(r"[a-z0-9-]{1,24}", spec["tag"])):
        errors.append("tag is a short slug on head, body or weapon only")
    words = re.findall(r"[a-z0-9]+", str(spec.get("name", "")).lower())
    if not spec.get("name") or set(words) & set(limits["banned_words"]):
        errors.append("name is empty or uses a banned word")
    if "kit" in spec:
        kit_slot, _, base = spec["kit"].partition("/")
        if kit_slot != slot or base not in kit.get("bases", {}).get(slot, {}):
            errors.append("kit %r does not name a base in the kit for slot %s" % (spec["kit"], slot))
        if tier != "legendary" and len(spec.get("nodes", [])) > limits["kit_decorations"]:
            errors.append("a kit-built item carries at most %d decorations" % limits["kit_decorations"])
    elif tier != "legendary":
        errors.append("a common or rare item names a kit base (only legendaries are drawn freely)")
    if canonical_size(spec) > limits["max_bytes"]:
        errors.append("item is %d bytes, over %d" % (canonical_size(spec), limits["max_bytes"]))
    nodes = expand(spec, kit)
    count, points = walk(nodes, limits, errors, "nodes")
    if count > limits["max_nodes"]:
        errors.append("%d nodes after kit expansion, over %d" % (count, limits["max_nodes"]))
    if not nodes:
        errors.append("an item has at least one node")
    box, tol = limits["slot_boxes"][slot], limits["box_tolerance"]
    if points and any(p[i] < box["min"][i] - tol or p[i] > box["max"][i] + tol for p in points for i in range(3)):
        errors.append("a node leaves the %s box" % slot)
    return errors


def check_dir(specs_dir, kit, rules, limits):
    results = {}
    for path in sorted(Path(specs_dir).glob("*.json")):
        results[path.name] = check_item(json.loads(path.read_text()), rules, kit, limits)
    return results


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--specs", type=Path, default=HERE / "fixtures")
    parser.add_argument("--kit", type=Path, default=HERE / "fixtures" / "kit" / "kit.json")
    args = parser.parse_args(argv)
    limits, rules = load_limits(), sim.DEFAULT_RULES
    kit = json.loads(args.kit.read_text())
    results = check_dir(args.specs, kit, rules, limits)
    bad = {k: v for k, v in results.items() if v}
    for name, errors in sorted(bad.items()):
        print("FAIL", name, "; ".join(errors))
    print("%d/%d items valid (%s)" % (len(results) - len(bad), len(results), args.specs))
    final = HERE / "specs"
    print("rules-table specs: %s" % ("checked above" if args.specs == final else
          "none yet (the kit board V3 writes near/items/specs and kit.json)" if not final.exists() else
          "present, run with --specs near/items/specs --kit near/items/kit.json"))
    return 1 if bad or not results else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
