#!/usr/bin/env python3
"""gate.py: the pre-push scans for this repo. Standard library only; run from a checkout of this repo.

  python3 -I near/tools/gate.py                       every scan, then the clean-clone run
  python3 -I near/tools/gate.py private names         only the named scans
  python3 -I near/tools/gate.py --no-clean-clone      the five scans without the clean-clone run
  python3 -I near/tools/gate.py --root DIR ...        scan the checkout at DIR instead of this one

The scans read the files git would commit: tracked files plus untracked files that .gitignore does not hide
(so a file copied in and not yet added is scanned, not skipped). Hits are printed as `<scan>: path:line:text`;
a hit in the private scan shows the kind of secret and its first four characters, never the whole value.
After the hits, one line per scan gives its count. A scan that could not run says so and the gate exits 2:
a check that could not run is never a pass.

  private  secrets and keys in any file, key-like or internal file names, missing .gitignore patterns
  names    the two banned label words in any text file or file name, and each full name in names.txt
  deny     each extended regex in deny.txt
  leak     the one extended regex in leak.txt
  room     room/ equals the committed room source byte for byte (room-src/, and room-source.json names its commit)
  clean-clone  a fresh `git clone` into an empty folder, no harness on PATH, `make test` there

The pattern files are kept outside this repo, so this file carries no word or name it is meant to catch. They live
in the folder named by TRENCHIE_GATE_DIR (default: $XDG_CONFIG_HOME/trenchie-gate, else ~/.config/trenchie-gate) as
names.txt, deny.txt, leak.txt and room-src/; TRENCHIE_NAMES_FILE, TRENCHIE_DENY_FILE, TRENCHIE_LEAK_FILE and
TRENCHIE_ROOM_SRC override one each.
"""
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time

# Secret shapes. A few literals are split with a one-character class so this file does not match its own scan.
SECRETS = [
    ("private key hex", r"0x[a-fA-F0-9]{64}\b"),
    ("model or cloud key", r"sk-an[t]-|sk-pro[j]-|sk-tinyfis[h]-|\bsk-[A-Za-z0-9]{32,}"),
    ("github token", r"\bgh[pousr]_[A-Za-z0-9]{20,}|github_pa[t]_"),
    ("slack token", r"xox[abpr]-[0-9A-Za-z-]{10,}"),
    ("aws key id", r"AKI[A]{1}[0-9A-Z]{16}"),
    ("pem private key", r"-----BEGIN [A-Z ]*PRIVATE KE[Y]"),
    ("jwt", r"eyJ[A-Za-z0-9_-]{20,}\.eyJ"),
    ("near secret key", r"(ed25519|secp256k1):[1-9A-HJ-NP-Za-km-z]{60,}"),
    ("literal mnemonic", r"mnemonic\w*[\"']?\s*[:=]\s*[\"'](?:[a-z]{3,8} ){11,}[a-z]{3,8}[\"']"),
    ("env assignment with a literal", r"(?:API_KEY|SECRET|TOKEN|PASSWORD)[A-Z_]*\s*=\s*[\"']?[A-Za-z0-9/+_-]{16,}"),
    ("machine path", r"/(?:Users|home)/[a-z][a-z0-9_-]*/"),
]
# This pinned SDK's public curve parameters resemble hex keys. No other secret shape is exempt.
PRIVATE_HEX_ALLOW = {
    "near/web/snapin/vendor/near-api-js/near-api-js-7.3.1.min.js":
        "c173fa84ea7ea5a2fe66cef819700b183368473e6a978bbac2088cbd74d3652b",
}
FAKE = re.compile(r"not-real|not-a-token|must-not|should-not|stubkey|fixture|example|placeholder|synthetic", re.I)
FAKE_ELIGIBLE = ("env assignment with a literal", "private key hex")
KEY_FILE = re.compile(r"\.(pem|key|p12)$|(^|/)id_(rsa|ed25519)|(^|/)\.env($|\.)|\.env$|credential|secret", re.I)
INTERNAL = re.compile(
    r"(^|/)(artifacts|proto|gate|rules-raw|\.claude|\.worktrees|node_modules|target|\.demo|\.state)/"
    r"|(^|/)(CLAUDE[^/]*\.md|\.mcp\.json|DEBUG-LOG\.md|CHECKPOINT\.md)$")
GITIGNORE_NEEDS = [".env", ".env.*", "*.env", "*.pem", "*.key", "node_modules/", "__pycache__/"]
ROOM_FILES = ["__init__.py", "service.py", "protocol.py", "protocol.schema.json", "slots.py", "identity.py",
              "policy.py", "ledger.py", "results.py", "bridge.py", "ROOM.md", "requirements.txt",
              "test_room.py", "test_identity.py", "test_policy.py", "test_recovery.py", "mutants.py"]
PATTERN_FILES = {"names": ("TRENCHIE_NAMES_FILE", "names.txt"), "deny": ("TRENCHIE_DENY_FILE", "deny.txt"),
                 "leak": ("TRENCHIE_LEAK_FILE", "leak.txt")}
ROOM_SRC = ("TRENCHIE_ROOM_SRC", "room-src")
MIN_NAMES = 14
SCANS = ["private", "names", "deny", "leak", "room"]
LABELS = {"private": "private sweep", "names": "names sweep", "deny": "client deny scan", "leak": "leak check",
          "room": "room copy", "clean-clone": "clean clone"}
MAX_SHOWN = 200
# Release references in the build log and exact dependency-version lines are public data.
LEAK_ALLOW = {
    ("BUILD-LOG.md", re.compile(r"\b0\.2\.19\b")),
    ("near/contracts/Cargo.lock", re.compile(r'^version = "[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?"$')),
}
HELP = ("The pattern files are kept outside this repository. Point TRENCHIE_GATE_DIR at the folder that holds "
        "names.txt, deny.txt, leak.txt and room-src/ (default {default}).")


class NotRun(Exception):
    pass


def gate_dir():
    env = os.environ.get("TRENCHIE_GATE_DIR")
    if env:
        return env
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "trenchie-gate")


def resolve(kind):
    var, name = PATTERN_FILES[kind] if kind in PATTERN_FILES else ROOM_SRC
    return os.environ.get(var) or os.path.join(gate_dir(), name), var


def root_of(path):
    out = subprocess.run(["git", "-C", path, "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if out.returncode != 0:
        raise NotRun(f"{path} is not a git checkout")
    return out.stdout.strip()


def candidate_files(root):
    """Tracked files plus untracked files .gitignore does not hide, as (all, untracked_count)."""
    def ls(*args):
        out = subprocess.run(["git", "-C", root, "ls-files", "-z", *args], capture_output=True, check=True).stdout
        return [p.decode("utf-8", "surrogateescape") for p in out.split(b"\0") if p]
    tracked = ls("--cached")
    others = ls("--others", "--exclude-standard")
    return sorted(set(tracked) | set(others)), len(others)


def text_lines(root, path):
    """(lineno, text) for a text file; nothing for a binary file or a path that is not a regular file (grep -I)."""
    full = os.path.join(root, path)
    if not os.path.isfile(full) or os.path.islink(full):
        return []
    with open(full, "rb") as f:
        data = f.read()
    if b"\0" in data[:8192]:
        return []
    return list(enumerate(data.decode("utf-8", "replace").splitlines(), 1))


def hit(scan, path, n, text):
    return f"{scan}: {path}:{n}:{text.strip()[:160]}"


def scan_regex(scan, root, files, rx, allow=()):
    out = []
    for p in files:
        for n, t in text_lines(root, p):
            if rx.search(t):
                if any(p == ap and arx.search(t) for ap, arx in allow):
                    continue
                out.append(hit(scan, p, n, t))
    return out


def pattern_lines(kind):
    path, var = resolve(kind)
    if not os.path.isfile(path) or not os.access(path, os.R_OK):
        raise NotRun(f"{kind.upper()} FILE MISSING: {path} ({var}). " + HELP.format(default=gate_dir()))
    with open(path, encoding="utf-8") as f:
        lines = [l.rstrip("\n") for l in f if l.strip() and not l.lstrip().startswith("#")]
    if not lines:
        raise NotRun(f"{kind.upper()} FILE EMPTY: {path}; a scan with nothing to look for is not a pass")
    return lines


def check_private(root, files):
    out = []
    curve_paths = set()
    for path in files:
        if path in PRIVATE_HEX_ALLOW:
            with open(os.path.join(root, path), "rb") as source:
                if hashlib.sha256(source.read()).hexdigest() == PRIVATE_HEX_ALLOW[path]:
                    curve_paths.add(path)
    for p in files:
        if KEY_FILE.search(p):
            out.append(hit("private", p, 0, "key-like file name"))
        if INTERNAL.search(p):
            out.append(hit("private", p, 0, "internal path in a public tree"))
    for label, rx in SECRETS:
        crx = re.compile(rx)
        for p in files:
            if label == "private key hex" and p in curve_paths:
                continue
            for n, t in text_lines(root, p):
                m = crx.search(t)
                if not m:
                    continue
                if label in FAKE_ELIGIBLE and FAKE.search(t):
                    continue
                out.append(hit("private", p, n, f"[{label}] {m.group(0)[:4]}..."))
    gi = os.path.join(root, ".gitignore")
    have = set()
    if os.path.isfile(gi):
        with open(gi, encoding="utf-8") as f:
            have = {l.strip() for l in f}
    for need in GITIGNORE_NEEDS:
        if need not in have:
            out.append(hit("private", ".gitignore", 0, f"missing pattern {need}"))
    return out


def name_alternation(names):
    return "|".join(re.escape(n.strip()) for n in sorted(names, key=len, reverse=True))


def check_names(root, files):
    word = re.compile(r"(?<![A-Za-z0-9_])(?:jud[g]es?|figur[e]s?)(?![A-Za-z0-9_])", re.I)
    out = scan_regex("names", root, files, word)
    out += [hit("names", p, 0, "file name") for p in files if word.search(p)]
    names = pattern_lines("names")
    if len(names) < MIN_NAMES:
        raise NotRun(f"NAMES FILE SHORT: {len(names)} names, expected at least {MIN_NAMES}; the list is not whole")
    rx = re.compile(r"(?<![A-Za-z])(?:" + name_alternation(names) + r")(?![A-Za-z])", re.I)
    out += scan_regex("names", root, files, rx)
    out += [hit("names", p, 0, "file name") for p in files if rx.search(p)]
    return out


def check_deny(root, files):
    pats = pattern_lines("deny")
    return scan_regex("deny", root, files, re.compile("|".join(f"(?:{p})" for p in pats), re.I))


def check_leak(root, files):
    pats = pattern_lines("leak")
    if len(pats) != 1:
        raise NotRun(f"LEAK FILE must hold exactly one regex line, found {len(pats)}")
    return scan_regex("leak", root, files, re.compile(pats[0], re.I), LEAK_ALLOW)


def check_room(root, files):
    src, var = resolve("room")
    if not os.path.isdir(src):
        raise NotRun(f"ROOM SOURCE MISSING: {src} ({var}). " + HELP.format(default=gate_dir()))
    out = []
    # The directory holds the committed source's files; src.commit names the commit they came from.
    marker = src.rstrip("/") + ".commit"
    want = None
    meta = os.path.join(root, "room-source.json")
    if os.path.isfile(meta):
        with open(meta, encoding="utf-8") as f:
            want = json.load(f).get("commit")
    if not os.path.isfile(marker):
        raise NotRun(f"ROOM SOURCE UNDATED: {marker} is missing; it must name the commit room-src/ was extracted from")
    with open(marker, encoding="utf-8") as f:
        have_commit = f.read().strip()
    if want != have_commit:
        out.append(hit("room", "room-source.json", 0, "names a commit other than the one the source folder holds"))
    here = {p[len("room/"):] for p in files if p.startswith("room/")}
    for f in sorted(set(ROOM_FILES) | here):
        a, b = os.path.join(src, f), os.path.join(root, "room", f)
        if f not in ROOM_FILES:
            out.append(hit("room", f"room/{f}", 0, "file not in the room allowlist"))
        elif not os.path.isfile(a):
            out.append(hit("room", f"room/{f}", 0, "missing from the committed room source"))
        elif f not in here or not os.path.isfile(b):
            out.append(hit("room", f"room/{f}", 0, "missing from the copy"))
        else:
            with open(a, "rb") as fa, open(b, "rb") as fb:
                if fa.read() != fb.read():
                    out.append(hit("room", f"room/{f}", 0, "bytes differ from the committed room source"))
    return out


CHECKS = {"private": check_private, "names": check_names, "deny": check_deny, "leak": check_leak, "room": check_room}


def clean_clone(root, targets=("test", "demo", "live")):
    """Clone the committed tree to an empty folder and run make there, with no PYTHONPATH and a PATH holding no
    checkout of the harness (browser cases still need node, Playwright and its browser installed, as `make setup` does). Returns (hit lines, notices). Targets that print NOT BUILT and exit 2 are notices."""
    lines, notices = [], []
    bad = [e for e in os.environ.get("PATH", "").split(os.pathsep) + os.environ.get("PYTHONPATH", "").split(os.pathsep)
           if re.search(r"coharness", e, re.I)]
    if bad:
        return [hit("clean-clone", "PATH", 0, "an entry names a harness checkout: " + ", ".join(bad))], notices
    dirty = subprocess.run(["git", "-C", root, "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
    if dirty:
        n = len(dirty.splitlines())
        return [hit("clean-clone", ".", 0, f"{n} uncommitted path(s); the clone is the committed tree, so commit first")], notices
    with tempfile.TemporaryDirectory(prefix="clean-clone-") as tmp:
        dest = os.path.join(tmp, "clone")
        r = subprocess.run(["git", "clone", "-q", root, dest], capture_output=True, text=True)
        if r.returncode != 0:
            return [hit("clean-clone", ".", 0, "git clone failed: " + r.stderr.strip()[:120])], notices
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")}
        # HOME stays: browser cases find their installed browser under it. Only the harness-bearing variables go.
        env.update({"PYTHONDONTWRITEBYTECODE": "1"})
        for t in targets:
            t0 = time.time()
            r = subprocess.run(["make", "-C", dest, t], env=env, capture_output=True, text=True)
            took = f"{time.time() - t0:.0f}s"
            tail = (r.stdout + r.stderr).strip().splitlines()[-1:] or [""]
            if r.returncode == 0:
                notices.append(f"clean-clone: make {t} passed from a fresh clone in {took}; last line: {tail[0][:120]}")
            elif r.returncode == 2 and "NOT BUILT" in (r.stdout + r.stderr):
                notices.append(f"clean-clone: make {t} is NOT BUILT yet (the stub says so); it is not a pass")
            else:
                last = "\n".join((r.stdout + r.stderr).strip().splitlines()[-12:])
                lines.append(hit("clean-clone", "make " + t, 0, f"exit {r.returncode} after {took}"))
                lines.extend("    " + l for l in last.splitlines())
    return lines, notices


def run(root, wanted, with_clone):
    files, untracked = candidate_files(root)
    head = subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or "no commit"
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"gate {stamp}  root={os.path.basename(root)}  HEAD={head}  files={len(files)} ({untracked} untracked)")
    code, rows, notices = 0, [], []
    for w in wanted:
        try:
            hits = CHECKS[w](root, files)
        except NotRun as e:
            rows.append(f"{LABELS[w]:<17}: NOT RUN, {e}")
            code = 2
            continue
        for h in hits[:MAX_SHOWN]:
            print(h)
        if len(hits) > MAX_SHOWN:
            print(f"{w}: ... {len(hits) - MAX_SHOWN} more")
        rows.append(f"{LABELS[w]:<17}: {len(hits)} lines")
        if hits and code == 0:
            code = 1
    if with_clone:
        hits, notes = clean_clone(root)
        for h in hits:
            print(h)
        notices += notes
        rows.append(f"{LABELS['clean-clone']:<17}: {len([h for h in hits if not h.startswith('    ')])} lines")
        if hits and code == 0:
            code = 1
    print("-" * 60)
    for r in rows:
        print(r)
    for n in notices:
        print(n)
    print(f"gate: {stamp} exit {code} ({len(files)} files; 0 = every requested scan ran and printed 0 lines)")
    return code


def main(argv):
    root_arg, with_clone = None, True
    if "--root" in argv:
        i = argv.index("--root")
        root_arg = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if "--no-clean-clone" in argv:
        with_clone = False
        argv = [a for a in argv if a != "--no-clean-clone"]
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        root = root_of(root_arg or os.path.join(here, "..", ".."))
    except NotRun as e:
        print(f"gate: {e}", file=sys.stderr)
        return 2
    wanted = [a for a in argv if a != "clean-clone"]
    only_clone = bool(argv) and not wanted
    if argv and "clean-clone" not in argv:
        with_clone = False
    bad = [w for w in wanted if w not in CHECKS]
    if bad:
        print(f"gate: unknown scan {bad[0]}; choose from {', '.join(SCANS)} or clean-clone", file=sys.stderr)
        return 2
    return run(root, [] if only_clone else (wanted or SCANS), with_clone)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
