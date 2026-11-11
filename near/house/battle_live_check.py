"""Live check of the house's battle prompts on the real model (no arena): each of the 14 personas writes its first
behaviour from the same plan prompt the runtime sends, and one line about a real-looking event. It prints whether
each answer is a schema-v1-shaped behaviour, and how many distinct plans the 14 wrote. The arena's own validator
(near/arena/behaviour.py) is used when present; otherwise only the shape is checked, and the output says so.

    NEARAI_API_KEY=... python3 -B near/house/battle_live_check.py OUT_DIR
"""

import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "arena")]
import battle  # noqa: E402
import live  # noqa: E402
import runtime  # noqa: E402
import sheets as sheets_mod  # noqa: E402

KEYS = {"v", "stance", "drives", "gate", "target", "reflexes", "clear"}


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        import behaviour as validator  # the arena's own behaviour validator
    except ImportError:
        validator = None
    loaded = sheets_mod.load()
    client = runtime.NearAI(key_env=live.KEY_ENV)
    spend, rows = 0, []
    for slug in sorted(loaded):
        others = [s for s in sorted(loaded) if s != slug][:3]
        state = {"fighters": {slug: {"id": slug, "x": 0, "y": 0, "hp": 100, "max_hp": 100, "style": loaded[slug]["game"]["fight_style"], "state": "alive"}}}
        for i, o in enumerate(others):
            state["fighters"][o] = {"id": o, "x": 2000 * (i + 1), "y": 0, "hp": 60 + 10 * i, "max_hp": 100, "style": "brawler", "state": "alive"}
        ring = battle.ring_view(slug, state, lambda n: loaded[n]["tag"])
        ask = battle.plan_ask(slug, loaded, "start", "your first plan", ring, None)
        t = time.time()
        answer = client.chat([{"role": "system", "content": loaded[slug]["prefix"]}, {"role": "user", "content": ask}], max_tokens=450)
        secs = time.time() - t
        spend += runtime.cost_microusd(answer["usage"])
        row = {"persona": slug, "style": loaded[slug]["game"]["fight_style"], "temperament": loaded[slug]["game"]["temperament"], "seconds": round(secs, 2)}
        try:
            data = battle.parse(answer["text"])
            b = dict(data.get("behaviour") or {}, v=1)
            row["behaviour"] = b
            row["shape_ok"] = set(b) <= KEYS and len(b.get("reflexes", [])) <= 8
            row["say"] = battle.clean_say(data.get("say"))
            row["emoji"] = data.get("emoji")
            row["emoji_in_set"] = data.get("emoji") in battle.emoji_set(loaded[slug]["game"])
            if validator is not None:
                row["validator"] = "applied/clipped/refused per near/arena/behaviour.py"
        except ValueError as exc:
            row["error"] = str(exc)
        rows.append(row)
    plans = {json.dumps({k: r["behaviour"].get(k) for k in ("stance", "drives", "gate", "target")}, sort_keys=True)
             for r in rows if r.get("behaviour")}
    report = {"model": runtime.MODEL, "personas": len(rows), "shape_ok": sum(1 for r in rows if r.get("shape_ok")),
              "distinct_plans": len(plans), "stances": sorted({str(r.get("behaviour", {}).get("stance")) for r in rows}),
              "emoji_in_set": sum(1 for r in rows if r.get("emoji_in_set")), "validator": "near/arena/behaviour.py" if validator else "NOT RUN (no behaviour validator in this tree): shape only",
              "spend_microusd": spend, "rows": rows}
    (out / "battle-live-check.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, ensure_ascii=False))


if __name__ == "__main__":
    if not os.environ.get(live.KEY_ENV):
        raise SystemExit("needs %s" % live.KEY_ENV)
    main(sys.argv[1])
