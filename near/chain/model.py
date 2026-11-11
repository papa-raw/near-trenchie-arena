"""A Python model of the three contract methods the writer and the resolver call.

It follows near/contracts/{arena,market,trenchie_nft}/src/lib.rs for exactly the paths the writer uses:
`arena.commit_seeds`, `arena.post_batch` (record, seed order, the `apply_rows` hop, `on_apply`),
`trenchie_nft.apply_rows` (skip unknown tokens, row cap, apply a batch id once) and `market.resolve`
(conservation). It backs two things only, and both say so in their output:
  * the dry-run, so the arena can run on seeds "as if" committed, every one labelled DRY-RUN;
  * the fake RPC the tests drive the real signing and retry code through.
It is never a stand-in for a chain result. Fault switches let a test fail a hop or lose a response.
"""

import json
import os
import re

from . import batch

KEEP_RECORDS = 300
MAX_SEEDS_PER_COMMIT = 1440
SEEDS_IN_EVENT = 120


class Panic(Exception):
    """A contract panic: the transaction lands and fails with this message."""


def event(standard, name, data):
    return "EVENT_JSON:" + json.dumps({"standard": standard, "version": "1.0.0", "event": name, "data": [data]},
                                      separators=(",", ":"))


class Contracts:
    def __init__(self, arena_id, market_id, nft_id, operator, resolver, *, row_count=256, max_rows=256, tokens=()):
        self.ids = {"arena": arena_id, "market": market_id, "nft": nft_id}
        self.operator, self.resolver = operator, resolver
        self.row_count, self.max_rows = row_count, max_rows
        self.height = 1000
        # arena
        self.commits, self.secrets, self.batches = {}, set(), {}
        self.seed_commit = self.seed_index = 0
        self.next_commit, self.used_ids, self.next_seq, self.pending = 0, set(), 1, None
        self.last_seq = 0
        # nft
        self.tokens = set(tokens)
        self.owners = {}           # token -> owner (default custody)
        self.bags = {}             # token -> its bag entries, as the last applied row filed them
        self.records = {}          # token -> its record {lives, kos, skill}, as the last applied row filed it
        self.applied = set()
        self.nft_paused = False
        # market
        self.open_batch, self.stakes, self.pot, self.market_batches = 0, {}, 0, {}
        self.stakers, self.closed, self.voided, self.now_ns = {}, None, {}, 10 ** 18
        self.base_rate = [4010, 3470, 1570, 640, 310]
        # faults
        self.fail_next_hops = 0

    # ------------------------------------------------------------------ dispatch
    def call(self, signer, receiver, method, args):
        """Run one FunctionCall. Returns (value, logs, receipt_failures). Raises Panic on a top-level panic."""
        self.height += 1
        role = {v: k for k, v in self.ids.items()}.get(receiver)
        fn = getattr(self, f"{role}_{method}", None) if role else None
        if fn is None:
            raise Panic(f"MethodNotFound {receiver}.{method}")
        logs, failures = [], []
        value = fn(signer, logs, failures, **args)
        return value, logs, failures

    def view(self, receiver, method, args):
        role = {v: k for k, v in self.ids.items()}.get(receiver)
        fn = getattr(self, f"view_{role}_{method}", None) if role else None
        if fn is None:
            raise Panic(f"MethodNotFound {receiver}.{method}")
        return fn(**args)

    # ------------------------------------------------------------------ arena
    def arena_commit_seeds(self, signer, logs, failures, secret, count):
        if signer != self.operator:
            raise Panic("only the arena operator may write")
        if not 1 <= count <= MAX_SEEDS_PER_COMMIT:
            raise Panic("count must be 1 to 1440")
        if not batch.HEX64.fullmatch(secret):
            raise Panic("secret must be 64 lowercase hex characters")
        if secret in self.secrets:
            raise Panic("secret already committed")
        self.secrets.add(secret)
        random = os.urandom(32)
        seeds = [batch.derive_seed(bytes.fromhex(secret), random, i).hex() for i in range(count)]
        cid = self.next_commit
        self.next_commit += 1
        commit = {"commit_id": str(cid), "block_height": str(self.height), "random_seed": random.hex(),
                  "secret": secret, "count": count}
        self.commits[cid] = commit
        data = dict(commit, seeds=seeds) if count <= SEEDS_IN_EVENT else dict(commit)
        logs.append(event("trenchie_arena", "commit_seeds", data))
        return seeds

    def _seed_hex(self, cid, index):
        c = self.commits[cid]
        return batch.derive_seed(bytes.fromhex(c["secret"]), bytes.fromhex(c["random_seed"]), index).hex()

    def arena_post_batch(self, signer, logs, failures, batch_id, segments, rows, manifest):
        if signer != self.operator:
            raise Panic("only the arena operator may write")
        if not batch.ID.fullmatch(batch_id):
            raise Panic("invalid batch id")
        if not segments:
            raise Panic("a batch has at least one segment")
        for s in segments:
            try:
                batch.check_segment(s)
            except ValueError as exc:
                raise Panic(str(exc))
        fh, rd = batch.fight_hash(segments), batch.rows_digest(rows)
        rec = self.batches.get(batch_id)
        if rec is not None:
            if (rec["fight_hash"], rec["rows_digest"], rec["manifest"]) != (fh, rd, manifest):
                raise Panic("batch id reused with different content")
            if rec["status"] == "Applied":
                logs.append(event("trenchie_arena", "post_batch", {"batch_id": batch_id, "already_applied": True}))
                return None
            if rec["status"] == "Abandoned":
                raise Panic("batch was abandoned: post its rows under a new id")
        else:
            if self.pending is not None:
                raise Panic(f"batch {self.pending} is pending: retry it until it applies, then post the next")
            if batch_id in self.used_ids:
                raise Panic("batch id was used before (its record was pruned): post under a new id")
            sc, si, used = self._bind_seeds(segments)
            self.seed_commit, self.seed_index = sc, si
            for c in used:                 # every seed used: the record goes; its event stays on archival
                del self.commits[c]
                logs.append(event("trenchie_arena", "commit_used", {"commit_id": str(c)}))
            self.used_ids.add(batch_id)
            self.pending = batch_id
            rec = {"seq": str(self.next_seq), "fight_hash": fh, "segments": len(segments), "kos": sum(s["kos"] for s in segments),
                   "rows": len(rows), "rows_digest": rd, "manifest": manifest, "status": "Pending", "hops": 0,
                   "posted_at": str(self.height)}
            self.next_seq += 1
            self.batches[batch_id] = rec
        rec["hops"] += 1
        logs.append(event("trenchie_arena", "post_batch", {
            "batch_id": batch_id, "fight_hash": fh, "segments": rec["segments"], "kos": rec["kos"],
            "rows": rec["rows"], "manifest": manifest, "hop": rec["hops"]}))
        try:
            self._apply_rows(batch_id, int(rec["seq"]), rows, logs)
            ok = True
        except Panic as exc:
            failures.append(f"apply_rows: {exc}")
            ok = False
        if ok and rec["status"] != "Applied":
            rec["status"] = "Applied"
            if self.pending == batch_id:
                self.pending = None
        logs.append(event("trenchie_arena", "apply_result", {"batch_id": batch_id, "status": "applied" if ok else "pending"}))
        return ok

    def _bind_seeds(self, segments):
        """Each segment takes the next committed seed, in order, as `post_batch` checks."""
        sc, si, used = self.seed_commit, self.seed_index, []
        for s in segments:
            if int(s["commit_id"]) != sc or s["seed_index"] != si:
                raise Panic("a segment must use the next committed seed, in order")
            if sc not in self.commits:
                raise Panic("the next committed seed is not committed yet")
            if s["seed_hash"] != batch.seed_hash(batch.seed_u64(self._seed_hex(sc, si))):
                raise Panic("seed_hash is not the committed seed's")
            if si + 1 == self.commits[sc]["count"]:
                used.append(sc)
                sc, si = sc + 1, 0
            else:
                si += 1
        return sc, si, used

    def _apply_rows(self, batch_id, seq, rows, logs):
        if self.fail_next_hops > 0:
            self.fail_next_hops -= 1
            raise Panic("Exceeded the prepaid gas.")
        if self.nft_paused:
            raise Panic("paused")
        if batch_id in self.applied:
            logs.append(event("trenchie_nft", "apply_rows", {"batch_id": batch_id, "already_applied": True}))
            return
        if seq <= self.last_seq:
            raise Panic("batch seq out of order")
        if len(rows) > self.max_rows:
            raise Panic("batch over the row cap")
        skipped = [r["token_id"] for r in rows if r["token_id"] not in self.tokens]
        for r in rows:
            try:
                batch.check_row(r, self.row_count)
            except ValueError as exc:
                raise Panic(str(exc))
        self.applied.add(batch_id)
        self.last_seq = seq
        for r in rows:
            if r["token_id"] in self.tokens:
                self.bags[r["token_id"]] = [dict(e) for e in r["bag"]]   # the row's bag replaces the token's
                self.records[r["token_id"]] = dict(r["record"])
        logs.append(event("trenchie_nft", "apply_rows", {"batch_id": batch_id, "rows": len(rows) - len(skipped),
                                                          "skipped": skipped}))

    def view_nft_trenchie(self, token_id):
        if token_id not in self.tokens:
            return None
        return {"token_id": token_id, "owner_id": self.owners.get(token_id, "custody.t.testnet"),
                "bag": [dict(e) for e in self.bags.get(token_id, [])],
                "record": dict(self.records.get(token_id, {"lives": 0, "kos": 0, "skill": 0}))}

    def view_nft_nft_token(self, token_id):
        """NEP-171 `nft_token`, as the identity NFT answers it: null for a token that was never minted or is burned."""
        if token_id not in self.tokens:
            return None
        return {"token_id": token_id, "owner_id": self.owners.get(token_id, "custody.t.testnet"), "metadata": {},
                "approved_account_ids": {}}

    def view_arena_get_batch(self, batch_id):
        return self.batches.get(batch_id)

    def abandon_pending(self, batch_id):
        """The owner's `abandon_pending` (Pat's key; a test helper here)."""
        if self.pending != batch_id:
            raise Panic("that batch is not the pending one")
        self.batches[batch_id]["status"] = "Abandoned"
        self.pending = None

    def view_arena_state(self):
        return {"operator": self.operator, "commits": str(self.next_commit),
                "next_seed": {"commit_id": str(self.seed_commit), "seed_index": self.seed_index},
                "next_seq": str(self.next_seq), "pending": self.pending}

    def view_arena_get_commit(self, commit_id):
        c = self.commits.get(int(commit_id))
        if c is None:
            raise Panic("no such commit, or its seeds are all used: read its commit_seeds event on archival")
        return c

    def view_arena_seed_record(self, commit_id, index):
        h = self._seed_hex(int(commit_id), index)
        v = batch.seed_u64(h)
        return {"seed": h, "seed_u64": str(v), "seed_hash": batch.seed_hash(v)}

    # ------------------------------------------------------------------ market
    def market_close_batch(self, signer, logs, failures):
        if signer != self.resolver:
            raise Panic("only the stake resolver may close a batch")
        if self.closed is not None:
            raise Panic("resolve the closed batch first")
        count = sum(1 for s in self.stakes.values() if s["batch"] == self.open_batch)
        self.closed = {"batch": str(self.open_batch), "stakes": count, "opened_at": str(self.now_ns)}
        self.open_batch += 1
        logs.append(event("trenchie_market", "close_batch", {"batch": self.closed["batch"], "stakes": count}))
        return self.closed

    def market_resolve(self, signer, logs, failures, batch, results, pot_delta, base_rate, log_hash):
        if signer != self.resolver:
            raise Panic("only the stake resolver may resolve")
        if self.closed is None:
            raise Panic("close the batch first")
        closed = int(self.closed["batch"])
        if int(batch) != closed:
            raise Panic("batch is not the closed stake batch")
        mine = {a: s for a, s in self.stakes.items() if s["batch"] == closed}
        if len(results) != self.closed["stakes"]:
            raise Panic("every stake of the batch needs exactly one result")
        if sum(base_rate) != 10_000:
            raise Panic("base_rate must sum to 10000 basis points")
        if not re.fullmatch(r"[0-9a-f]{64}", log_hash):
            raise Panic("log_hash must be 64 lowercase hex characters")
        net_sum = 0
        for r in results:
            s = mine.pop(r["account_id"], None)
            if s is None:
                raise Panic("result for an account with no open stake")
            if int(r["net"]) < -int(s["amount"]):
                raise Panic("a stake cannot lose more than itself")
            net_sum += int(r["net"])
        if net_sum + int(pot_delta) != 0:
            raise Panic("stakes and pot must sum to zero")
        if self.pot + int(pot_delta) < 0:
            raise Panic("the pot cannot go below zero")
        for r in results:
            del self.stakes[r["account_id"]]
        self.pot += int(pot_delta)
        self.base_rate = list(base_rate)
        rec = {"log_hash": log_hash, "results": len(results), "pot_after": str(self.pot), "base_rate": list(base_rate),
               "resolved_at": str(self.height)}
        self.market_batches[closed] = rec
        self.stakers.pop(closed, None)
        logs.append(event("trenchie_market", "resolve", {"batch": str(closed), "results": len(results),
                                                         "pot_delta": str(pot_delta), "pot_after": str(self.pot),
                                                         "log_hash": log_hash}))
        self.closed = None
        return rec

    def stake(self, account, amount, at=None):
        """Test helper: a lock or top-up as `market.stake` leaves it, with its own part time."""
        at = self.now_ns if at is None else at
        s = self.stakes.get(account)
        if s is not None and s["batch"] != self.open_batch:
            raise Panic("previous stake unresolved")
        if s is None:
            s = {"amount": "0", "batch": self.open_batch, "locked_at": str(at), "storage_fee": "0", "parts": []}
            self.stakers.setdefault(self.open_batch, []).append(account)
        s["amount"] = str(int(s["amount"]) + amount)
        s["parts"].append({"amount": str(amount), "at": str(at)})
        self.stakes[account] = s

    def void(self, batch):
        """Test helper: a timeout refund voids the whole batch."""
        for a in [a for a, s in self.stakes.items() if s["batch"] == batch]:
            del self.stakes[a]
        self.voided[batch] = 0
        if self.closed is not None and int(self.closed["batch"]) == batch:
            self.closed = None

    def view_market_state(self):
        open_count = sum(1 for s in self.stakes.values() if s["batch"] == self.open_batch)
        return {"resolver": self.resolver, "open_batch": str(self.open_batch), "open_count": open_count,
                "pot": str(self.pot), "base_rate": self.base_rate, "closed": self.closed}

    def view_market_batch_stakes(self, batch, from_index=None, limit=None):
        names = self.stakers.get(int(batch), [])[from_index or 0:(from_index or 0) + (limit or 100)]
        return [{"account_id": a, "stake": dict(self.stakes[a], batch=str(self.stakes[a]["batch"]))}
                for a in names if a in self.stakes]

    def view_market_batch_voided(self, batch):
        return self.voided.get(int(batch))

    def view_market_stake_of(self, account_id):
        s = self.stakes.get(account_id)
        return None if s is None else dict(s, batch=str(s["batch"]))

    def view_market_batch(self, batch):
        return self.market_batches.get(int(batch))
