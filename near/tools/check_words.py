#!/usr/bin/env python3
"""check_words.py: the words players read, and the one order rate they are told.

  python3 -I near/tools/check_words.py              both checks over this checkout
  python3 -I near/tools/check_words.py --selftest   the checks' own cases (planted text in a temp folder)

1. Words. Player-facing text never says "bet", "stake", "pot", "payout" (a prediction "predicts"; it earns
   "rewards" or ends in "failure") or "terms" (the arena has "Arena rules"; nothing here is a legal agreement).
   Player-facing text is:
     - the prose of every Markdown file in the public set (README.md, AGENTS.md, near/**/*.md), with fenced code
       blocks and `code spans` left out: a command, flag or protocol field name in code is the protocol, not prose;
     - every string a page shows: string literals in the snap-in guide, the arena page and the reviewer desk
       (near/web/**/*.js|mjs|html, tests, QA cases, vendored code, the art and spike boards left out), text between
       HTML tags, and the title, alt, placeholder and aria-label attributes;
     - every string the agent client and the local host print or send back to an agent (snap.py, snap_local.py,
       play_local.py, battle_room.py, battle_events.py; docstrings and comments left out).
   A string literal with no space and no capital letter is an identifier, an action id or a path ('accept_terms',
   'terms-reload', '/dev/terms'), not shown text. Two places are left out on purpose: room/ (a byte copy of the
   room source, checked by gate.py's room scan) and near/members/ (the synthetic member-page rehearsal and its
   approved drawings; no game page links to it).
   The agreed protocol mentions are listed in AGREED (SNAP.md names the protocol once, for agents); each must be
   present exactly once, and each is printed.
2. The order rate. sim.DEFAULT_RULES fixes it (intent_interval ticks at tick_hz); the battle host advertises that
   value (battle_room.ORDER_INTERVAL_MS, read by the guide and by snap.py from /dev/terms), and every rate the
   Markdown prose states ("one order per 0.5 s", "one order every 0.5 s", "the 0.5 s order window") equals it.
   The verbatim PRD block in SNAP.md keeps the portable room's own reference and is left out (SNAP.md says so
   under the block).
Prints each hit as `words: path:line: text` or `rate: path:line: text`, then one count line per check.
Exit 0 only when both checks find nothing.
"""
import io
import os
import re
import subprocess
import sys
import tempfile
import tokenize

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))

BANNED = re.compile(r"\b(bets?|betting|stakes?|staked|staking|pots?|payouts?|terms)\b", re.I)
AGREED = [("near/SNAP.md", "the arena's rules (terms v1)")]
SKIP_DIRS = ("room/", "near/members/", "near/web/snapin/vendor/", "near/web/vendor/", "near/web/snapin/qa/",
             "near/web/snapin/spike/", "near/web/art/", "near/web/hud-art/")
AGENT_PY = ("near/arena/snap.py", "near/arena/snap_local.py", "near/tools/play_local.py",
            "near/arena/battle_room.py", "near/arena/battle_events.py")
# a CLI flag, or the snap.py command line an agent copies (`snap.py ... terms`), is the protocol
PROTOCOL = re.compile(r"--[a-z][a-z-]*|(?:snap\.py|\{snap\}|\$SNAP\b)[^\n'\"]*")
PRD_BLOCK = re.compile(r"<!-- BEGIN PRD .*?<!-- END PRD [^>]*-->", re.S)
N = r"(\d+(?:\.\d+)?) ?(?:sim )?s(?:econds?)?\b"
RATE = re.compile(r"\bone (?:order|intent) (?:per|every) " + N
                  + r"|\b(?:orders?|intents?)\b[^.\n]{0,60}?\bone (?:per|every) " + N
                  + r"|(\d+(?:\.\d+)?) s order window|order interval \((\d+(?:\.\d+)?) s|order sooner than " + N, re.I)


def public_files(root):
    out = subprocess.run(["git", "-C", root, "ls-files", "-z"], capture_output=True, check=True).stdout
    names = [n for n in out.decode().split("\0") if n]
    keep = ("README.md", "AGENTS.md")
    return [n for n in names if (n in keep or n.startswith("near/")) and not n.startswith(SKIP_DIRS)]


def is_test(name):
    base = os.path.basename(name)
    return base.startswith("test_") or "case" in base or "fixture" in base or "_check" in base


# ---- Markdown prose ---------------------------------------------------------------------------------------------
def md_prose(text):
    """(line number, prose) pairs: fenced blocks blanked, `code spans` removed."""
    rows, fenced = [], False
    for n, line in enumerate(text.split("\n"), 1):
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if not fenced:
            rows.append((n, re.sub(r"`[^`]*`", " ", line)))
    return rows


# ---- JS / HTML shown strings --------------------------------------------------------------------------------------
def js_strings(src):
    """(line, literal) for every string literal; comments and regex literals skipped."""
    out, i, n, line, last, prev_last = [], 0, len(src), 1, "", ""
    while i < n:
        c = src[i]
        if not c.isspace() and not src.startswith(("//", "/*"), i):
            prev_last, last = last, c
        if c == "\n":
            line += 1; i += 1
        elif src.startswith("//", i):
            j = src.find("\n", i); i = n if j < 0 else j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2); j = n if j < 0 else j + 2
            line += src.count("\n", i, j); i = j
        elif c == "/" and (prev_last == "" or prev_last in "(,=:[!&|?{};+-*%<>~^"):
            j, cls = i + 1, False                     # a regex literal: skip to its closing slash
            while j < n and src[j] != "\n" and (cls or src[j] != "/"):
                if src[j] == "\\":
                    j += 1
                elif src[j] == "[":
                    cls = True
                elif src[j] == "]":
                    cls = False
                j += 1
            i = j + 1
        elif c in "'\"`":
            j, start = i + 1, line
            while j < n and src[j] != c:
                if src[j] == "\\":
                    j += 1
                if j < n and src[j] == "\n":
                    line += 1
                j += 1
            body = src[i + 1:j]
            out.append((start, re.sub(r"\$\{[^}]*\}", " ", body) if c == "`" else body)); i = j + 1; last = c
        else:
            i += 1
    return out


def shown(literal):
    """True when a literal is text a reader sees: it has a space or a capital letter (else an id or a path)."""
    return bool(re.search(r"\s|[A-Z]", literal))


def html_text(src):
    """(line, text) for text between tags and for the shown attributes; scripts and styles left to js_strings."""
    rows = []
    for n, line in enumerate(src.split("\n"), 1):
        for m in re.finditer(r'\b(?:title|alt|placeholder|aria-label)="([^"]*)"', line):
            rows.append((n, m.group(1)))
        rows.append((n, re.sub(r"<[^>]*>", " ", line)))
    return rows


def py_strings(src):
    """(line, literal) for string literals that are not docstrings or bare statements; an f-string is taken whole."""
    rows, prev, lines, fstart = [], tokenize.NEWLINE, src.split("\n"), None
    fs_start = getattr(tokenize, "FSTRING_START", None)
    fs_end = getattr(tokenize, "FSTRING_END", None)
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == fs_start and fstart is None:
            fstart = (tok.start, prev)
        elif tok.type == fs_end and fstart is not None and fstart[0] is not None:
            (r0, c0), was = fstart
            r1, c1 = tok.end
            text = "\n".join([lines[r0 - 1][c0:]] + lines[r0:r1 - 1] + [lines[r1 - 1][:c1]]) if r1 > r0 else lines[r0 - 1][c0:c1]
            if was not in BARE:
                rows.append((r0, re.sub(r"\{[^{}]*\}", " ", PROTOCOL.sub(" ", text))))     # the {expressions} are code
            fstart = None
        elif tok.type == tokenize.STRING and fstart is None and prev not in BARE:
            rows.append((tok.start[0], tok.string))
        if tok.type not in (tokenize.COMMENT, tokenize.NL) and fstart is None:
            prev = tok.type
    return [(n, PROTOCOL.sub(" ", re.sub(r"`[^`]*`", " ", t))) for n, t in rows]


BARE = (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.NL, tokenize.ENCODING)


def text_rows(root, name):
    path = os.path.join(root, name)
    try:
        src = open(path, encoding="utf-8").read()
    except (UnicodeDecodeError, IsADirectoryError, FileNotFoundError):
        return []
    if name.endswith(".md"):
        return md_prose(src)
    if name.startswith("near/web/") and not is_test(name):
        if name.endswith((".js", ".mjs")):
            return [(n, s) for n, s in js_strings(src) if shown(s)]
        if name.endswith(".html"):
            rows = html_text(re.sub(r"<(script|style)\b.*?</\1>", lambda m: "\n" * m.group(0).count("\n"), src, flags=re.S))
            for m in re.finditer(r"<script\b[^>]*>(.*?)</script>", src, re.S):
                base = src.count("\n", 0, m.start(1))
                rows += [(base + n, s) for n, s in js_strings(m.group(1)) if shown(s)]
            return rows
    if name in AGENT_PY:
        return [(n, s) for n, s in py_strings(src) if shown(s)]
    return []


def check_words(root, files=None):
    hits, agreed_seen = [], {}
    for name in files if files is not None else public_files(root):
        for n, text in text_rows(root, name):
            for path, phrase in AGREED:
                if name == path and phrase in text:
                    agreed_seen.setdefault((path, phrase), []).append(n)
                    text = text.replace(phrase, " ")
            for m in BANNED.finditer(text):
                hits.append(f"words: {name}:{n}: {m.group(0)!r} in {text.strip()[:160]}")
    agreed = []
    for path, phrase in AGREED:
        lines = agreed_seen.get((path, phrase), [])
        if files is None or path in files:
            if len(lines) != 1:
                hits.append(f"words: {path}: the agreed mention {phrase!r} appears {len(lines)} times, not once")
            agreed += [f"agreed: {path}:{n}: {phrase}" for n in lines]
    return hits, agreed


# ---- the order rate ----------------------------------------------------------------------------------------------
def rules_rate_ms(root):
    sys.path.insert(0, root)
    sys.path.insert(0, os.path.join(root, "near", "arena"))
    from near.arena import sim
    r = sim.DEFAULT_RULES
    return r["intent_interval"] * r["milliseconds_per_second"] // r["tick_hz"]


def host_rate_ms(root):
    from near.arena import battle_room
    return battle_room.ORDER_INTERVAL_MS


def check_rate(root, rate_ms, host_ms=None, files=None):
    hits = []
    if host_ms is not None and host_ms != rate_ms:
        hits.append(f"rate: near/arena/battle_room.py: the battle host advertises {host_ms} ms; the rules say {rate_ms} ms")
    for name in files if files is not None else public_files(root):
        if not name.endswith(".md"):
            continue
        src = open(os.path.join(root, name), encoding="utf-8").read()
        src = PRD_BLOCK.sub(lambda m: "\n" * m.group(0).count("\n"), src)
        for n, text in md_prose(src):
            for m in RATE.finditer(text):
                said = float(next(g for g in m.groups() if g))
                if round(said * 1000) != rate_ms:
                    hits.append(f"rate: {name}:{n}: says {m.group(0)!r}; the rules say {rate_ms / 1000:g} s")
    return hits


def main(root):
    hits, agreed = check_words(root)
    rate = rules_rate_ms(root)
    rhits = check_rate(root, rate, host_rate_ms(root))
    for line in hits + rhits + agreed:
        print(line)
    print(f"words: {len(hits)} hit(s); {len(agreed)} agreed protocol mention(s)")
    print(f"rate: {len(rhits)} hit(s); the order rate is {rate / 1000:g} s ({rate} ms) from the rules table")
    return 1 if hits or rhits else 0


def selftest():
    fails = []
    with tempfile.TemporaryDirectory() as d:
        def put(name, text):
            os.makedirs(os.path.dirname(os.path.join(d, name)) or d, exist_ok=True)
            open(os.path.join(d, name), "w", encoding="utf-8").write(text)
        put("README.md", "Pick a stake.\n`--accept-terms 1` is a flag.\n```\nsnap.py terms\n```\nWin the pot.\n")
        put("near/SNAP.md", "Read the arena's rules (terms v1) once.\nOrders: one order per 2 s.\n"
                            "<!-- BEGIN PRD x -->\none order per 2 s\n<!-- END PRD x -->\n")
        put("near/web/snapin/app.js", "x('accept_terms', '/dev/terms', 'terms-reload'); // terms in a comment\n"
                                      "say('Review terms');\nvar ok = 'Arena rules';\n")
        put("near/web/snapin/index.html", '<div title="Place a bet">Money</div><script>t("Your payout")</script>\n')
        put("near/arena/snap.py", '"""terms in a docstring"""\nprint("the room\'s terms changed")\nx = "terms"\n')
        files = ["README.md", "near/SNAP.md", "near/web/snapin/app.js", "near/web/snapin/index.html", "near/arena/snap.py"]
        hits, agreed = check_words(d, files)
        want = {("README.md", 1), ("README.md", 6), ("near/web/snapin/app.js", 2), ("near/web/snapin/index.html", 1),
                ("near/arena/snap.py", 2)}
        got = {(h.split(":")[1].strip(), int(h.split(":")[2])) for h in hits if h.count(":") >= 3}
        if got != want:
            fails.append(f"words hits {sorted(got)} != {sorted(want)}")
        if len([h for h in hits if "index.html" in h]) != 2:
            fails.append("the title attribute and the inline script string are both checked")
        if agreed != ["agreed: near/SNAP.md:1: the arena's rules (terms v1)"]:
            fails.append(f"agreed {agreed}")
        put("near/SNAP.md", "no protocol name here\n")
        hits, _ = check_words(d, ["near/SNAP.md"])
        if not any("appears 0 times" in h for h in hits):
            fails.append("a missing agreed mention is a hit")
        rhits = check_rate(d, 500, 500, ["README.md", "near/SNAP.md"])
        if rhits:
            fails.append(f"rate: no claims expected, got {rhits}")
        put("near/SNAP.md", "Orders: one order per 2 s.\n<!-- BEGIN PRD x -->\none order per 2 s\n<!-- END PRD x -->\n"
                            "one order every 0.5 s; the 0.5 s order window\nOrders run at most one every 1 s.\n"
                            "| Orders (behaviours and intents share one clock) | one per 2 s per fighter |\n")
        rhits = check_rate(d, 500, 1000, ["near/SNAP.md"])
        if (len(rhits) != 4 or "battle host advertises 1000" not in rhits[0]
                or [h.split(":")[2] for h in rhits[1:]] != ["1", "6", "7"]):
            fails.append(f"rate hits {rhits}")
    for f in fails:
        print("selftest FAIL:", f)
    print("check_words selftest:", "OK" if not fails else f"{len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv[1:] else main(ROOT))
