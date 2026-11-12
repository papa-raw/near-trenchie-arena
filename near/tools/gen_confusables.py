#!/usr/bin/env python3
"""gen_confusables.py: builds near/house/confusables.json, the guard's look-alike fold, from Unicode's confusables.txt.

  curl -sSO https://www.unicode.org/Public/security/latest/confusables.txt
  python3 -I near/tools/gen_confusables.py confusables.txt

Keeps every mapping whose source is one non-ASCII code point and whose prototype is one ASCII letter or digit
(Cyrillic a -> a, Greek capital beta -> B, Cherokee letters, mathematical and small-capital forms, ...). Multi-character
prototypes ("rn" for m) and ASCII sources (the guard folds digit swaps itself) are left out. The output carries the
source URL, the file's version and date lines, and Unicode's notice, which the data's licence asks to travel with it.
Standard library only; deterministic (sorted keys).
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "house", "confusables.json"))
SOURCE = "https://www.unicode.org/Public/security/latest/confusables.txt"
NOTICE = ("Copyright (c) 1991-present Unicode, Inc. Unicode and the Unicode Logo are registered trademarks of Unicode, "
          "Inc. in the U.S. and other countries. This map is a subset of Unicode's confusables.txt (Unicode Security "
          "Mechanisms, UTS #39), used under Unicode's terms of use (https://www.unicode.org/terms_of_use.html) and the "
          "Unicode License v3 (https://www.unicode.org/license.txt).")


def build(text, sha256=""):
    header = {}
    table = {}
    for line in text.splitlines():
        m = re.match(r"#\s*(Version|Date):\s*(.+)$", line)
        if m and m.group(1) not in header:
            header[m.group(1).lower()] = m.group(2).strip()
        body = line.split("#", 1)[0].strip().lstrip("\ufeff")
        if not body:
            continue
        fields = [f.strip() for f in body.split(";")]
        if len(fields) < 2:
            continue
        src, dst = fields[0].split(), fields[1].split()
        if len(src) != 1 or len(dst) != 1:
            continue
        s, d = chr(int(src[0], 16)), chr(int(dst[0], 16))
        if ord(s) > 127 and d.isascii() and d.isalnum():
            table[s] = d
    if not table or "version" not in header:
        raise SystemExit("gen_confusables: no mappings or no Version line; is this confusables.txt?")
    return {"source": SOURCE, "version": header["version"], "date": header.get("date", ""), "sha256": sha256, "notice": NOTICE,
            "map": dict(sorted(table.items()))}


def main(argv):
    if len(argv) != 1:
        raise SystemExit(__doc__)
    raw = open(argv[0], "rb").read()
    data = build(raw.decode("utf-8-sig"), hashlib.sha256(raw).hexdigest())
    with open(OUT, "w", encoding="ascii") as f:
        json.dump(data, f, ensure_ascii=True, indent=0, sort_keys=False)
        f.write("\n")
    print(f"confusables.json: {len(data['map'])} mappings from confusables.txt version {data['version']}")


if __name__ == "__main__":
    main(sys.argv[1:])
