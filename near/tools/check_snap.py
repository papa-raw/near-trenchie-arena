#!/usr/bin/env python3
"""check_snap.py: checks near/SNAP.md, its snap rules table and its citation rules.

  python3 -I near/tools/check_snap.py                                   public mode: only what is in this repo
  TRENCHIE_DENY_FILE=PATH python3 -I near/tools/check_snap.py --prd PATH --decisions PATH   private mode

Public mode (no arguments; runs from a clean clone):
  - SNAP.md has the BEGIN/END snap rules block, and its table has 4 columns, 5 rows and no empty cell
  - each per-path table has 4 columns, and every body cell cites a decisions row as dec:<line>
  - every dec: cite is well formed (dec:<line> or dec:<line>-<line>)
  - the model-key rule is stated outside the copied block: it stays in the browser (O10)
  - the old coin's name is gone from SNAP.md
Private mode (both paths given, plus the TRENCHIE_DENY_FILE env var; all three are private, not in this repo) adds:
  - every line of PRD §2.5.4's table is in SNAP.md's block verbatim, and nothing else is
  - every dec:<line> is a table row of the decisions log, and the id cited beside it (Q38, B13b, O6...) is on that
    row, by name or inside a batch range such as "B79-B83"
  - no line of SNAP.md matches a pattern in the deny file named by the TRENCHIE_DENY_FILE env var (the words and names that
    must never reach the public repo; the list itself stays private)
Exit 0 only when every check in the mode passes. A mode it could not run (one path given, a path missing, or the
private mode without TRENCHIE_DENY_FILE set) exits 2:
a check it could not run is never a pass.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def arg(flag, default):
    a = sys.argv[1:]
    return a[a.index(flag) + 1] if flag in a and a.index(flag) + 1 < len(a) else default


SNAP = arg("--snap", os.path.normpath(os.path.join(HERE, "..", "SNAP.md")))
PRD = arg("--prd", None)
DEC = arg("--decisions", None)


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def id_on_row(rid, row):
    """True when decision id `rid` (e.g. B82, Q57, B13b) is on this decisions row, by name or inside a range
    in the row's first cell such as "B79-B83" or "B101-B109"."""
    if re.search(rf"\b{re.escape(rid)}\b", row):
        return True
    m = re.fullmatch(r"([QBOD])(\d+)", rid)
    if not m:
        return False
    first = row.split("|")[1] if row.count("|") >= 2 else row
    for a, lo, b, hi in re.findall(r"\b([QBOD])(\d+)-([QBOD]?)(\d+)\b", first):
        if a == m.group(1) and (not b or b == a) and int(lo) <= int(m.group(2)) <= int(hi):
            return True
    return False


def prd_table(lines):
    """The table lines under '#### 2.5.4', up to the next heading."""
    start = next((i for i, l in enumerate(lines) if l.startswith("#### 2.5.4")), None)
    if start is None:
        return None
    out = []
    for l in lines[start + 1:]:
        if l.startswith("#"):
            break
        if l.startswith("|"):
            out.append(l)
    return out


EXPECTED_COLS, EXPECTED_ROWS = 4, 5          # the snap rules table: 4 columns, 5 rows (the snap rules criterion)
# Public-mode sweep: the old coin's name is public history, so it is written out plainly here.
SWEEPS = [("old coin name", r"\$TRENCH|trench_ft")]
DENY_ENV = "TRENCHIE_DENY_FILE"   # private mode: a file outside this repo, one extended regex per line ('#' comments; 'sha16:' lines are for check_sheets)


def snap_block(snap):
    m = re.search(r"<!-- BEGIN PRD §2\.5\.4.*?-->\n(.*?)\n<!-- END PRD §2\.5\.4 -->", snap, re.S)
    return m.group(1).splitlines() if m else None


def public_checks(snap, fails):
    snap_lines = snap.splitlines()
    # 1. the copied snap rules table: shape only
    block = snap_block(snap)
    if block is None:
        fails.append("SNAP.md has no BEGIN/END PRD §2.5.4 block")
        block = []
    got_tbl = [l for l in block if l.startswith("|")]
    ncols = len(cells(got_tbl[0])) if got_tbl else 0
    rows_body = got_tbl[2:]
    empty = sum(1 for l in rows_body for c in cells(l) if not c)
    print(f"snap rules: {ncols}/{EXPECTED_COLS} columns, {len(rows_body)} rows, {empty} empty cells")
    if ncols != EXPECTED_COLS:
        fails.append(f"the snap rules table has {ncols} columns, need {EXPECTED_COLS}")
    if len(rows_body) != EXPECTED_ROWS:
        fails.append(f"the snap rules table has {len(rows_body)} rows, need {EXPECTED_ROWS}")
    if any(len(cells(l)) != ncols for l in rows_body):
        fails.append("a snap rules row has a different column count from the header")
    if empty:
        fails.append(f"{empty} empty cell(s) in the snap rules table")
    # 2. the per-path tables: 4 columns, every body cell cites dec:<line>
    tables, cur = [], []
    in_block = False
    for l in snap_lines:
        if l.startswith("<!-- BEGIN PRD"):
            in_block = True
        if l.startswith("<!-- END PRD"):
            in_block = False
            continue
        if in_block:
            continue
        if l.startswith("|"):
            cur.append(l)
        elif cur:
            tables.append(cur)
            cur = []
    if cur:
        tables.append(cur)
    path_tables = [t for t in tables if cells(t[0])[0] == "Who joins"]
    if len(path_tables) != 2:
        fails.append(f"{len(path_tables)} per-path tables (header 'Who joins'), need 2: agent and human")
    n_cells = n_cited = 0
    for t in path_tables:
        if len(cells(t[0])) != 4:
            fails.append(f"per-path table header has {len(cells(t[0]))} columns: {t[0][:60]}")
        for row in t[2:]:
            for i, c in enumerate(cells(row)):
                n_cells += 1
                if re.search(r"dec:\d+", c):
                    n_cited += 1
                else:
                    fails.append(f"per-path cell without a dec:<line> cite: {cells(row)[0][:40]}... column {i + 1}")
    print(f"per-path tables: {len(path_tables)} x 4 columns, {n_cited}/{n_cells} cells cite dec:<line>")
    # 3. cite format
    all_cites = [c for c in re.findall(r"dec:\S*", snap) if not c.startswith("dec:<")]   # "dec:<line>" documents the format
    bad_fmt = [c for c in all_cites if not re.match(r"dec:\d+(-\d+)?(?![0-9A-Za-z_-])", c)]
    for c in bad_fmt:
        fails.append(f"malformed cite: {c[:30]}")
    print(f"cite format: {len(all_cites) - len(bad_fmt)}/{len(all_cites)} dec: cites well formed")
    # 4. the model key stays in the browser, said in SNAP.md's own text (not only inside the copied block)
    own = re.sub(r"<!-- BEGIN PRD.*?<!-- END PRD §2\.5\.4 -->", "", snap, flags=re.S)
    if not (re.search(r"stays in (your|the) browser", own) and "O10" in own):
        fails.append("the model-key rule is missing outside the copied block: 'stays in the browser' with O10")
    else:
        print("model key: 'stays in the browser' stated with O10")
    # 5. forbidden-word sweeps over the whole file
    hits = 0
    for name, pat in SWEEPS:
        for n, l in enumerate(snap_lines, 1):
            if re.search(pat, l, re.I):
                hits += 1
                fails.append(f"forbidden ({name}) at SNAP.md:{n}")
    print(f"sweeps: {hits} forbidden-word hits ({', '.join(n for n, _ in SWEEPS)})")


def private_checks(snap, prd_lines, dec_lines, fails):
    # 6. PRD §2.5.4 verbatim, inside the marked block
    want = prd_table(prd_lines)
    if not want:
        fails.append("prd: no '#### 2.5.4' table found")
        return
    block = snap_block(snap) or []
    missing = [l for l in want if l not in block]
    got_tbl = [l for l in block if l.startswith("|")]
    extra = [l for l in got_tbl if l not in want]
    print(f"verbatim: {'matches' if not missing and not extra else 'DIFFERS FROM'} PRD §2.5.4 ({len(want) - 2} rows), "
          f"{len(missing)} missing, {len(extra)} extra")
    for l in missing:
        fails.append(f"PRD line not copied verbatim: {l[:90]}...")
    for l in extra:
        fails.append(f"line in the block that is not in the PRD: {l[:90]}...")
    # 7. every dec:<line> is a real decisions row, and the id cited beside it is on that row
    cited = sorted({int(x) for x in re.findall(r"dec:(\d+)", snap)})
    bad = [n for n in cited if not (1 <= n <= len(dec_lines) and dec_lines[n - 1].startswith("| "))]
    for n in bad:
        fails.append(f"dec:{n} is not a table row of the decisions log")
    print(f"citations: {len(cited) - len(bad)}/{len(cited)} distinct dec:<line> cites land on a decisions row")
    n_pairs, wrong, no_id = 0, [], 0
    for seg in re.split(r"[;()]", snap):                         # one citation group per ';' / '(' segment
        for m in re.finditer(r"dec:(\d+)(?:-(\d+))?", seg):
            lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
            ids = re.findall(r"\b([QBOD]\d+[a-z]?)\b", seg[:m.start()])
            if not ids:
                no_id += 1                                       # e.g. "v2.3 inferred calls, dec:198": named by title
                title = seg[:m.start()].strip(" ,\"*")
                rows = " ".join(dec_lines[n - 1] for n in range(lo, hi + 1) if 1 <= n <= len(dec_lines))
                key = re.sub(r"[^a-z0-9. ]", "", title.lower())[-20:].strip()
                if key and key not in rows.lower():
                    wrong.append(f"'{title[-40:]}' -> dec:{lo}")
                continue
            n_pairs += 1
            rows = [dec_lines[n - 1] for n in range(lo, hi + 1) if 1 <= n <= len(dec_lines)]
            if not any(id_on_row(i, r) for i in ids for r in rows):
                wrong.append(f"{'/'.join(ids)} -> dec:{lo}{'-' + str(hi) if hi != lo else ''}")
    for w in wrong:
        fails.append(f"citation points at a row that does not hold its id: {w}")
    wrong_ids = sum(1 for w in wrong if not w.startswith("'"))
    print(f"citation ids: {n_pairs - wrong_ids}/{n_pairs} id->row pairs hold; {no_id} cited by title, checked by title text")
    # 8. the private deny list: words and names that must never reach the public repo
    pats = [l.strip() for l in open(os.environ[DENY_ENV], encoding="utf-8") if l.strip() and not l.lstrip().startswith(("#", "sha16:"))]
    hits = 0
    for n, l in enumerate(snap.splitlines(), 1):
        for pat in pats:
            if re.search(pat, l, re.I):
                hits += 1
                fails.append(f"deny-list pattern #{pats.index(pat) + 1} matches SNAP.md:{n}")
    print(f"deny list: {len(pats)} patterns, {hits} hits")


def main():
    fails = []
    if bool(PRD) != bool(DEC):
        print("CANNOT RUN private mode: pass both --prd PATH and --decisions PATH, or neither for public mode")
        return 2
    if PRD and not os.environ.get(DENY_ENV):
        print(f"CANNOT RUN private mode: set ${DENY_ENV} to the private deny file (one regex per line, outside this repo)")
        return 2
    for p in [SNAP] + ([PRD, DEC, os.environ[DENY_ENV]] if PRD else []):
        if not os.path.exists(p):
            print(f"CANNOT RUN: {p} not found")
            return 2
    snap = open(SNAP, encoding="utf-8").read()
    print("mode: private (public checks + the PRD verbatim diff, the decisions-row checks and the deny list)" if PRD else
          "mode: public (repo-only checks; pass --prd and --decisions for the private checks)")
    public_checks(snap, fails)
    if PRD:
        private_checks(snap, open(PRD, encoding="utf-8").read().splitlines(),
                       open(DEC, encoding="utf-8").read().splitlines(), fails)
    for f in fails:
        print("FAIL " + f)
    print("SNAP.md: OK" if not fails else f"SNAP.md: {len(fails)} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
