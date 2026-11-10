"""The banter guard (B23, B86, B87): every public feed line passes this check; a blocked line becomes an emote.

The block list of real names, handles and slurs never ships in the repo. It is a JSON file outside
the tree, named by the TRENCHIE_BLOCKLIST environment variable:
    {"names": ["First Last", ...], "handles": ["@someone", ...], "slurs": [...]}
Without it (a clean-clone `make live`) every line is muted to an emote and the output prints
"guard list missing"; nothing falls back to letting lines through.

Rules:
- Blocked: a listed real name or handle as a whole match, ignoring case; the words scam, fraud and jail;
  "rug", "rugger", "rugged" and "rug pull" only when a trenchie name or a real name is in the same
  line; listed slurs. The longest match wins: a trenchie name that overlaps a listed entry and is
  at least as long is allowed.
- Not blocked: "the Great Rug" and myth theories while no trenchie or real name is in the line;
  a first name or surname on its own; "exit".
Standard library only.
"""

import hashlib
import json
import os
from pathlib import Path
import re

MISSING_NOTICE = "guard list missing"
ENV = "TRENCHIE_BLOCKLIST"
EMOTES = ("(._.)", "(>_<)", "(^_^)", "(o_o)", "(-_-)", "\\(^o^)/")
ALWAYS = ("scam", "fraud", "jail")          # stems: scammer, fraudster, jailed and frauds all match
RUG = re.compile(r"\b(?:rug pull|rugger|rugged|rug)\b", re.I)
GREAT_RUG = re.compile(r"\bthe great rug\b", re.I)


def _whole(term):
    return re.compile(r"(?<![\w@])" + re.escape(term.strip()) + r"(?![\w])", re.I)


def load_blocklist(path=None):
    """The list as a dict, or None when it is missing or unreadable (never an empty fallback)."""
    path = path or os.environ.get(ENV)
    if not path:
        return None
    try:
        data = json.loads(Path(path).read_bytes())
        return {k: [t for t in data.get(k, []) if isinstance(t, str) and t.strip()] for k in ("names", "handles", "slurs")}
    except (OSError, ValueError, AttributeError):
        return None


class Guard:
    def __init__(self, blocklist, trenchie_names):
        self.blocklist = blocklist
        self.missing = blocklist is None
        self.trenchie = [_whole(n) for n in trenchie_names]
        self.real = [] if blocklist is None else [(t, _whole(t)) for k in ("names", "handles") for t in blocklist[k]]
        self.slurs = [] if blocklist is None else [_whole(t) for t in blocklist["slurs"]]
        self.log = []

    @classmethod
    def from_env(cls, trenchie_names, path=None):
        return cls(load_blocklist(path), trenchie_names)

    def notice(self):
        """The line `make live` prints at start when banter is muted; None when the list is loaded."""
        return MISSING_NOTICE if self.missing else None

    def _spans(self, patterns, line):
        return [m.span() for p in patterns for m in p.finditer(line)]

    def reason(self, line):
        """None when the line may post, else a short code."""
        if self.missing:
            return "guard-list-missing"
        low = line
        trenchie_spans = self._spans(self.trenchie, low)
        real_spans = [s for t, p in self.real for s in (m.span() for m in p.finditer(low))]
        real_alive = [s for s in real_spans if not any(t[0] <= s[0] and s[1] <= t[1] and t[1] - t[0] >= s[1] - s[0]
                                                         for t in trenchie_spans)]
        if real_alive:
            return "real-name"
        if any(re.search(r"\b" + w + r"\w*", low, re.I) for w in ALWAYS):
            return "accusation-word"
        if any(p.search(low) for p in self.slurs):
            return "slur"
        if (RUG.search(low) or GREAT_RUG.search(low)) and (trenchie_spans or real_spans):
            return "rug-near-a-name"           # the Great Rug is blamed on myths only (B22): never beside a name
        return None

    def check(self, line, who="?"):
        """Returns {"text", "blocked", "reason"}; a blocked line is logged by hash, never by content."""
        reason = self.reason(line)
        if reason is None:
            return {"text": line, "blocked": False, "reason": None}
        digest = hashlib.sha256(line.encode()).hexdigest()
        self.log.append({"who": who, "reason": reason, "line_sha256": digest[:16]})
        return {"text": EMOTES[int(digest[:8], 16) % len(EMOTES)], "blocked": True, "reason": reason}
