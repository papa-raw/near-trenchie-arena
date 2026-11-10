"""Focused case for the recorded budget scene; use the lane's simulation wrapper."""
import importlib.util
import json
import os
from pathlib import Path

path = Path(os.environ["ARENA_TEST_ROOT"]) / "near/web/arena_budget.py" if "ARENA_TEST_ROOT" in os.environ else Path(__file__).with_name("arena_budget.py")
spec = importlib.util.spec_from_file_location("arena_budget", path)
budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(budget)
record = budget.recording(417)
assert len(record["frames"]) == 1301
assert len(record["loadouts"]) == 16
assert all(len(kit) == 4 for kit in record["loadouts"].values())
assert record["frames"][-1][1] - record["frames"][0][1] == 1300
kit = json.loads((budget.NEAR / "items/kit.json").read_text())
used = set()
def collect(nodes):
    for node in nodes:
        used.add(node["type"])
        collect(node.get("children", []))
for loadout in record["loadouts"].values():
    for row in loadout.values():
        if row.startswith("sig-"):
            continue
        item = json.loads((budget.NEAR / "items/specs" / (("c-" + row[2:] if row.startswith("r-") else row) + ".json")).read_text())
        collect(item.get("nodes", []))
        if "kit" in item:
            slot, name = item["kit"].split("/")
            collect(kit["bases"][slot][name]["nodes"])
assert used == {"sphere", "hemisphere", "cylinder", "cone", "box", "torus", "tube", "plate"}, used
print(json.dumps({"ok": True, "fighters": 16, "frames": len(record["frames"]), "seconds": 65, "actualPrimitives": sorted(used)}))
