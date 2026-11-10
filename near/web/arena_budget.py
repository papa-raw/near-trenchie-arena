"""Serve a repeatable recorded arena budget scene. Standard library only; no hosted service.

Run from the repo root: python3 -B near/web/arena_budget.py
Records 60 seconds plus warm-up, then opens Chrome. Ctrl-C stops the local server.
"""
from __future__ import annotations
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

NEAR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NEAR / "arena"))
import dev_brawl
import server
import sim
from spectator_styles import SpectatorStyles


def recording(seed: int) -> dict:
    """Record the real sim; retain complete starting kits for the render-only stress projection."""
    game = dev_brawl.new_brawl(seed)
    rules = game.rules
    for i, name in enumerate(("sand-sprout", "tidal-turnip")):
        game.enqueue(sim.Input(0, "join", name, 0, {"angle": i * 180, "loadout": {"head": "st-cap", "body": "st-tee", "weapon": "c-lob" if i else "c-zap", "trinket": "st-roll"}}))
    frames = []
    details = SpectatorStyles(game, lambda data: data)
    metadata = [json.loads(details.full)]
    for _ in range(1301):
        game.step()
        previous = details.revision
        details.refresh(game)
        if details.revision != previous:
            metadata.append(json.loads(details.delta))
        frames.append(json.loads(server.encode_snapshot(game)))
    first = frames[0]
    loadouts = {first[2][f[0]]: dict(zip(("body", "head", "trinket", "weapon"), (first[3][r] for r in f[8]))) for f in first[4]}
    kit = json.loads((NEAR / "items/kit.json").read_text())
    types = {"group"}
    def collect(nodes: list[dict]) -> None:
        for node in nodes:
            types.add(node["type"])
            collect(node.get("children", []))
    for loadout in loadouts.values():
        for row in loadout.values():
            if row.startswith("sig-"):
                continue
            source = "c-" + row[2:] if row.startswith("r-") else row
            item = json.loads((NEAR / "items/specs" / (source + ".json")).read_text())
            collect(item.get("nodes", []))
            if "kit" in item:
                slot, name = item["kit"].split("/")
                collect(kit["bases"][slot][name]["nodes"])
    return {"seed": seed, "tickMs": 50, "rulesHash": game.rules_hash, "frames": frames, "metadata": metadata, "loadouts": loadouts, "styles": {n: f["style"] for n, f in game.state["fighters"].items()},
            "projection": "render-only: 16 live full kits, fixed positions, 150 effects; sim rules unchanged", "primitiveTypes": sorted(types)}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, data: bytes, **kwargs):
        self.data = data
        super().__init__(*args, directory=str(NEAR), **kwargs)

    def do_GET(self) -> None:
        if urlsplit(self.path).path == "/budget-stream.json":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(self.data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(self.data)
        else:
            super().do_GET()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--seed", type=int, default=417)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    print("Recording arena…", flush=True)
    data = json.dumps(recording(args.seed), separators=(",", ":")).encode()
    with ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, data=data)) as host:
        url = f"http://127.0.0.1:{host.server_port}/web/arena.html?replay=/budget-stream.json&budget=60&dprforce=2&diag"
        print("Open: " + url, flush=True)
        if not args.no_open:
            subprocess.run(["open", "-a", "Google Chrome", url], check=True)
        try:
            host.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
