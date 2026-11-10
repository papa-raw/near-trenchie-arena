#!/usr/bin/env python3
"""check_deps.py: every package pinned in a requirements file is installed at exactly that version.

  python3 -I tools/check_deps.py [requirements.txt]      (default: near/requirements.txt, next to this folder)

Follows `-r other.txt` lines. Prints one line per package. Exits 1 on the first run with any package missing or at
another version, and says how to fix it: a test run on a machine without the pinned packages stops here, loudly,
instead of failing later with an import error."""
import os
import re
import sys
from importlib import metadata


def pins(path, seen=None):
    seen = seen if seen is not None else set()
    path = os.path.abspath(path)
    if path in seen:
        return []
    seen.add(path)
    out = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            m = re.match(r"-r\s+(\S+)$", line)
            if m:
                out += pins(os.path.join(os.path.dirname(path), m.group(1)), seen)
                continue
            m = re.match(r"([A-Za-z0-9_.-]+)==([A-Za-z0-9_.+-]+)$", line)
            if not m:
                raise SystemExit(f"check_deps: {path}: cannot read the line {line!r}; every line must be name==version")
            out.append((m.group(1), m.group(2)))
    return out


def main(argv):
    here = os.path.dirname(os.path.abspath(__file__))
    req = argv[0] if argv else os.path.join(here, "..", "requirements.txt")
    bad = 0
    for name, want in pins(req):
        try:
            have = metadata.version(name)
        except metadata.PackageNotFoundError:
            have = None
        ok = have == want
        print(f"{'ok     ' if ok else 'MISSING' if have is None else 'WRONG  '} {name}=={want}" + ("" if ok or have is None else f" (installed {have})"))
        bad += not ok
    if bad:
        print(f"check_deps: {bad} pinned package(s) missing or at another version. Install them with `make setup` "
              f"(python3 -m pip install -r near/requirements.txt), then run again. Nothing was installed for you.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
