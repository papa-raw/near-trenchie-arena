"""One roster: a private status.json for the host, and a separate public projection.

Every admitted member (house trenchies and joined players) keeps the private fields persona, model,
state, life, spend_today and calls_per_min. The public projection lists the same admitted count with
the public state, and spend only for house members: a player's spend, cap and reasoning never leave
the host. status.json is rewritten at most 5 s apart, atomically, under the data directory.
Standard library only.
"""

import json
import os
from pathlib import Path
import tempfile

PERIOD_S = 5
PRIVATE_FIELDS = ("persona", "model", "state", "life", "spend_today_microusd", "calls_per_min")
PUBLIC_STATES = {"alive": "in the ring", "bench": "on the bench", "left": "swam home"}


def private_row(member):
    row = {k: member[k] for k in PRIVATE_FIELDS}
    row["house"] = bool(member["house"])
    return row


def public_roster(members):
    """The public rows: name, public state, and spend for the house only. Nothing else is copied."""
    rows = []
    for m in sorted(members, key=lambda m: m["persona"]):
        row = {"persona": m["persona"], "house": bool(m["house"]), "state": PUBLIC_STATES[m["state"]],
               "model": m["model"]}
        if "id" in m:                                   # the fighter id the arena view already shows, for its cards
            row["id"] = m["id"]
        if m["house"]:
            row["spend_today_microusd"] = m["spend_today_microusd"]
        rows.append(row)
    return {"admitted": len(rows), "members": rows}


class StatusWriter:
    def __init__(self, directory, period_s=PERIOD_S):
        self.dir, self.period, self.last, self.writes = Path(directory), period_s, None, 0

    def maybe_write(self, members, now):
        """Write status.json and roster.json when the period has passed; returns True when it wrote."""
        if self.last is not None and now - self.last < self.period:
            return False
        self._atomic("status.json", {"as_of": now, "members": [private_row(m) for m in members]})
        self._atomic("roster.json", {"as_of": now, **public_roster(members)})
        self.last, self.writes = now, self.writes + 1
        return True

    def _atomic(self, name, data):
        self.dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix="." + name + ".")
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, sort_keys=True)
        os.replace(tmp, self.dir / name)
