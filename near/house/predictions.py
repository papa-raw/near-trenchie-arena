"""The predictions log (F79): one public JSON line per AI per life, sealed before the life, scored after.

A lock fixes the prediction (or an explicit no-prediction marker) before the life activates and cannot be
replaced. A resolve appends the public line. Only whitelisted fields are ever written, so no model key,
prompt or reasoning can reach the file. The log lives under the data directory; its hash goes in the
settle batch, and each call's hash goes in the fight log. Standard library only.
"""

import hashlib
import json
import os
from pathlib import Path

try:
    from . import quote
except ImportError:
    import quote

FIELDS = ("life", "rules_hash", "persona", "owner", "model", "spread_pct", "zero_pct", "actual", "score",
          "base_score", "stake_yocto", "returned_yocto", "batch_tx", "lock_hash", "prediction")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class PredictionLog:
    def __init__(self, directory, on_line=None):
        self.dir = Path(directory)
        self.on_line = on_line                                   # called once per public line, after it is written
        self.path = self.dir / "predictions.jsonl"
        self.locks = {}
        for row in self.rows():                                  # a restart keeps every sealed life closed
            self.locks[row["life"]] = {"resolved": True, "hash": row["lock_hash"]}

    def rows(self):
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line]

    def lock(self, life, rules_hash, persona, owner, model, spread_pct=None, zero_pct=None):
        """Seal the prediction before activation. Returns the lock hash (put it in the fight log)."""
        if life in self.locks:
            raise ValueError("life %r is already locked; a prediction is immutable" % life)
        if spread_pct is not None:
            reason = quote.check_spread(spread_pct, zero_pct)
            if reason:
                raise ValueError(reason)
        body = {"life": life, "rules_hash": rules_hash, "persona": persona, "owner": owner, "model": model,
                "spread_pct": spread_pct, "zero_pct": zero_pct, "prediction": spread_pct is not None}
        self.locks[life] = {"resolved": False, "hash": digest(body), "body": body}
        return self.locks[life]["hash"]

    def resolve(self, life, actual, stake_yocto=0, batch_tx=None, base_bps=quote.PUBLISHED_BASE_BPS):
        """Append the public line for a locked life. Without a prediction the score fields are null."""
        entry = self.locks.get(life)
        if entry is None:
            raise ValueError("no lock for life %r: a line is only written for a sealed life" % life)
        if entry["resolved"]:
            raise ValueError("life %r is already resolved" % life)
        row = dict(entry["body"], actual=actual, lock_hash=entry["hash"], stake_yocto=str(stake_yocto), batch_tx=batch_tx)
        if row["prediction"]:
            row.update(score=quote.score(row["spread_pct"], actual), base_score=quote.base_score(base_bps, actual),
                       returned_yocto=str(quote.payout(stake_yocto, row["spread_pct"], actual, base_bps)))
        else:
            row.update(score=None, base_score=None, returned_yocto=str(0) if stake_yocto == 0 else None)
        extra = set(row) - set(FIELDS)
        if extra:
            raise ValueError("fields outside the log: %s" % sorted(extra))
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a") as f:
            f.write(json.dumps({k: row[k] for k in FIELDS}, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        entry["resolved"] = True
        if self.on_line is not None:
            self.on_line({k: row[k] for k in FIELDS})
        return row

    def log_hash(self):
        """The hash that goes in the batch: the whole file as written."""
        return hashlib.sha256(self.path.read_bytes() if self.path.exists() else b"").hexdigest()

    def readout(self, min_lives=quote.MIN_LIVES):
        """Per-persona skill against its own trailing base rate, from the lives that carried a prediction."""
        scored = [dict(r, life=i) for i, r in enumerate(self.rows()) if r["prediction"]]
        return quote.calibration(scored, min_lives)
