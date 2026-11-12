"""The sim's own fight events, with no renderer: the dev brawl from a seed, stepped headless.

Run:  python3 -I near/web/arena-fight-ticks.py --seed 7 --crowd 16 --to 2400

Prints one JSON object: {"rules_hash", "events": [[tick, kind, a, b, move_or_weapon], ...]} for every hit, KO and attack the
sim makes in ticks 1..to. arena-fight-ticks-case.cjs compares it with what the arena page drew from the same seed, live.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "near/arena"), str(ROOT)]
import dev_brawl  # noqa: E402


def events(seed: int, crowd: int, to: int) -> dict:
    game = dev_brawl.new_brawl(seed, crowd=crowd)
    out = []
    while game.state["tick"] < to:
        game.step()
        tick = game.state["tick"]
        for e in game.state["events"]:
            if e["kind"] == "hit":
                out.append([tick, "hit", e["source"], e["target"], e.get("move", "")])
            elif e["kind"] == "ko":
                out.append([tick, "ko", e["fighter"], e.get("source"), ""])
            elif e["kind"] == "attack":
                out.append([tick, "attack", e["fighter"], None, e["weapon"]])
    return {"rules_hash": game.rules_hash, "events": out}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--crowd", type=int, default=16)
    ap.add_argument("--to", type=int, required=True)
    args = ap.parse_args()
    print(json.dumps(events(args.seed, args.crowd, args.to), separators=(",", ":")))


if __name__ == "__main__":
    main()
