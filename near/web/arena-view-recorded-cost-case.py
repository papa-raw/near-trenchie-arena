"""Focused budget proxy: feed the page's complete recording through the same buffer and render builders."""
from pathlib import Path
import importlib.util
import json
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("arena_budget", Path(__file__).with_name("arena_budget.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with tempfile.TemporaryDirectory(prefix="arena-cost-") as directory:
    recording = Path(directory) / "record.json"
    recording.write_text(json.dumps(module.recording(417), separators=(",", ":")))
    subprocess.run(["node", "--no-warnings", "--experimental-loader", "./near/web/arena-view-remainder-loader.mjs", "near/web/arena-view-cost-case.mjs", "--record", str(recording), *sys.argv[1:]], cwd=ROOT, check=True)
