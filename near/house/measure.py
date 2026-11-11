"""Live measurements of the house model through the runtime's own call paths (W16 and F75).

    python3 -B near/house/measure.py w16 --out DIR [--sheets satrenchi,laser-sailor] [--lines 20]
    python3 -B near/house/measure.py f75 --out DIR [--lives 2]

Both need NEARAI_API_KEY in the environment and spend under runtime.py's building cap, metered in
DIR/spend.json. Every model answer is written to DIR as JSONL before it is counted, so the numbers can be
recomputed from the file alone.

w16: for each sheet, `lines` banter lines through Runtime._banter (the card's last 3 lines, one reroll on a
     Jaccard >= 0.5 repeat of the last 20, then the keyed line under the "repeat" label), cycling the four
     moments. It prints, per sheet, fresh repeats posted (an unlabelled line that repeats any of the previous
     20 posted lines, recomputed from the posted list), rerolls and keyed lines.
f75: for each of the 14 sheets, `lives` respawn picks through Runtime._pick (an invalid spread is asked for
     once more, then the life carries no prediction). It prints the valid-spread rate on the first ask and
     after the one retry.
"""

import argparse
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import guard as guard_mod  # noqa: E402
import live  # noqa: E402
import novelty  # noqa: E402
import quote  # noqa: E402
import runtime  # noqa: E402
import sheets as sheets_mod  # noqa: E402

MOMENTS = ("ko_given", "ko_taken", "loot", "idle")


def safe(text, guard):
    """What the evidence file keeps: the text when it passes the guard, else only its hash (a blocked line is never kept)."""
    import hashlib
    return text if guard.reason(text) is None else "<blocked line, sha256 %s>" % hashlib.sha256(text.encode()).hexdigest()[:16]


class Recording:
    """Wraps the client: every answer is appended to the evidence file before the caller sees it."""

    def __init__(self, client, path, guard):
        self.client, self.path, self.calls, self.guard = client, Path(path), [], guard
        self.model = client.model

    def chat(self, messages, thinking=False, max_tokens=200):
        t = time.time()
        answer = self.client.chat(messages, thinking=thinking, max_tokens=max_tokens)
        row = {"ask": messages[-1]["content"][-160:], "text": safe(answer["text"], self.guard), "usage": answer["usage"],
               "seconds": round(time.time() - t, 2)}
        with open(self.path, "a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        self.calls.append(row)
        return answer


def build(out, names, record_name):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    loaded = sheets_mod.load(names=names)
    g = guard_mod.Guard.from_env(sheets_mod.guard_names(sheets_mod.load()))
    client = Recording(runtime.NearAI(key_env=live.KEY_ENV), out / record_name, g)
    budget = runtime.Budget(runtime.JsonMeter(out / "spend.json"), "building", clock=time.time)
    rt = runtime.Runtime(client, budget, g, loaded, driver=None, clock=time.time)
    return rt, client, budget, g, loaded


def fresh_repeats(posted):
    texts = [p["text"] for p in posted]
    return sum(1 for k, p in enumerate(posted) if p["label"] is None
               and any(novelty.is_repeat_of(novelty.words(texts[k]), novelty.words(o)) for o in texts[max(0, k - novelty.WINDOW):k]))


def w16(args):
    names = args.sheets.split(",")
    rt, client, budget, g, loaded = build(args.out, names, "w16-calls.jsonl")
    if g.missing:
        raise SystemExit("measure: guard list missing (TRENCHIE_BLOCKLIST); every line would be muted, so W16 is not measurable")
    report = []
    for name in names:
        posted = []
        for i in range(args.lines):
            moment = MOMENTS[i % len(MOMENTS)]
            result = rt._banter(name, moment)               # the runtime's own banter path: card, reroll, keyed, guard
            v = rt.voices[name]
            posted.append({"text": v.posted[-1], "shown": result["text"], "label": result["label"],
                           "blocked": result["blocked"], "moment": moment})
        v = rt.voices[name]
        row = {"sheet": name, "lines": len(posted), "fresh_repeats_posted": fresh_repeats(posted),
               "rerolls": v.stats["rerolls"], "keyed_lines": v.stats["keyed"],
               "blocked": sum(p["blocked"] for p in posted), "posted": posted}
        for p in posted:                                    # the report keeps no blocked line
            p["text"] = safe(p["text"], g)
        report.append(row)
        print(f"w16 {name}: lines {row['lines']}, fresh repeats posted {row['fresh_repeats_posted']}, "
              f"rerolls {row['rerolls']}, keyed lines {row['keyed_lines']}, blocked {row['blocked']}", flush=True)
    spend(budget, client)
    Path(args.out, "w16-report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))


def f75(args):
    rt, client, budget, g, loaded = build(args.out, None, "f75-calls.jsonl")
    lives = []
    for name in sorted(loaded):
        for life in range(args.lives):
            before = len(client.calls)
            view = {"bag": [], "last_life_kos": life}
            try:
                result = rt._pick(name, view)
            except Exception as exc:                        # a host error (e.g. the 20 s client timeout) is not a spread
                lives.append({"sheet": name, "life": life, "asks": len(client.calls) - before, "error": type(exc).__name__,
                              "prediction": None, "spread_pct": None, "zero_pct": None})
                continue
            asks = len(client.calls) - before
            lives.append({"sheet": name, "life": life, "asks": asks, "prediction": result["prediction"],
                          "spread_pct": result["spread_pct"], "zero_pct": result["zero_pct"]})
    errors = [l for l in lives if l.get("error")]
    lives_all, lives = lives, [l for l in lives if not l.get("error")]   # rates are over picks that got an answer
    first = sum(1 for l in lives if l["prediction"] and l["asks"] == 1)
    after = sum(1 for l in lives if l["prediction"])
    distinct = len({(tuple(l["spread_pct"]), l["zero_pct"]) for l in lives if l["prediction"]})
    print(f"f75: {len(lives)} picks; valid on the first ask {first}/{len(lives)}; valid after the one retry "
          f"{after}/{len(lives)}; no prediction {len(lives) - after}; distinct (spread, zero) answers {distinct}; "
          f"host errors (not counted) {len(errors)}", flush=True)
    spend(budget, client)
    Path(args.out, "f75-report.json").write_text(json.dumps({"lives": lives_all, "host_errors": len(errors), "first_ask_valid": first,
                                                             "valid_after_retry": after, "picks": len(lives),
                                                             "distinct_answers": distinct}, indent=1))


def spend(budget, client):
    s = budget.state()
    secs = sorted(c["seconds"] for c in client.calls)
    p = lambda q: secs[min(len(secs) - 1, int(q * len(secs)))] if secs else None
    print(f"spend: {len(client.calls)} calls, {s['spent_today_microusd']} micro-USD on this meter today; "
          f"latency p50 {p(0.5)} s, p95 {p(0.95)} s", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("w16")
    a.add_argument("--out", required=True)
    a.add_argument("--sheets", default="satrenchi,laser-sailor")
    a.add_argument("--lines", type=int, default=20)
    b = sub.add_parser("f75")
    b.add_argument("--out", required=True)
    b.add_argument("--lives", type=int, default=2)
    args = ap.parse_args(argv)
    if not os.environ.get(live.KEY_ENV):
        raise SystemExit("measure: needs %s in the process environment" % live.KEY_ENV)
    {"w16": w16, "f75": f75}[args.cmd](args)


if __name__ == "__main__":
    main()
