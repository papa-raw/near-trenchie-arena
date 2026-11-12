"""The arena's chain writer: seed commits, the hourly batch and the stake resolver (C6, F84, F80).

The arena calls three methods (near/arena/server.py, `chain=`):
  claim_seeds(arena)            at construction: the committed, unused seeds, in commit order;
  sealed(arena, segment_id, r)  at each seal: binds the segment to its committed seed and queues it;
  take_seeds(arena)             at each segment open: seeds committed since the arena last asked.
Everything that talks to the chain runs in `process()` (one background thread in production), never in
the 20 Hz tick.

Seeds (B79, B103). A commit sends `arena.commit_seeds(secret, count)`; the seeds are read from that
transaction's own return value once it is final, and only then handed to the arena, so every segment
runs on a seed published before it opened, and nothing is drawn in the call that requests the seeds.
The pool starts at the contract's `next_seed` (seeds an earlier run committed but never used are taken
first), and a new commit is sent when fewer than `lookahead` seeds remain unused.

Batches (F84). Every `batch_segments` sealed segments (a period: 60 is an hour) close into `parts` batches
that post in order (G0_OPTIONS: Pat's pick A-D is a setting; C, 3 parts of 20 segments and <= 72 rows, is the
default): each part carries its segments with their committed seed refs and hashes, and a share of the rows,
one per persona touched in the period (its bag as it stands, its absolute record). The last part carries the
period's lives and resolves its one stake batch. `post_batch` is retried with the same batch id and the same bytes:
  * a landed tx whose hop failed (`apply_result: pending`) is resent, and the contract re-sends the hop only;
  * an unknown outcome (timeout, no answer) is read back first, from the tx and then from `get_batch`,
    so a batch is never posted twice under two ids;
  * a refusal or a panic is logged with the node's own words; after `attempts` tries the batch is HELD
    and retried at the next cycle. Nothing is dropped and nothing is reported applied that was not.
Batch ids carry a per-run prefix, so a restart never reuses an id with different content.

Stakes (F80). After a batch's record exists, the resolver key posts `market.resolve` for the market's
open stake batch, with the results `resolver.compute` gives from the batch's lives. It refuses to post
(and says why) when the market holds open stakes the server cannot attribute to an account it knows.
"""

import collections
import copy
import json
import os
import secrets
import threading
import time
from pathlib import Path

from . import batch as fmt, resolver, rpc as rpclib
from .model import Panic

POST_TGAS = 300
# G0 on b1a2f6d (2026-11-11): arena ~7 + 0.36 per segment; nft ~2.22 per bag-rewrite row (worst case),
# ~1.38 per pure add; on_apply ~1.7. A batch whose worst-case estimate passes SAFE_TGAS is held, never sent to
# run out of gas; the split rule is Pat's G0 pick.
SAFE_TGAS = 270
# The G0 options on the board for Pat (r4a-g0-and-price-2026-11-11.md); his pick is one of these settings.
G0_OPTIONS = {
    "A": {"batch_segments": 60, "parts": 1, "max_rows": 100},   # hourly, 1 tx; extra rows wait an hour
    "B": {"batch_segments": 60, "parts": 2, "max_rows": 107},   # hourly in 2 parts of 30 segments
    "C": {"batch_segments": 60, "parts": 3, "max_rows": 72},    # hourly in 3 parts of 20 segments (recommended)
    "D": {"batch_segments": 30, "parts": 1, "max_rows": 107},   # every 30 min, 1 tx
}


def estimate_tgas(segments: int, rows: int) -> float:
    return round(7 + 0.36 * segments + 2.22 * rows + 1.7 + 3, 1)
COMMIT_TGAS = 30
ACTUALS_WINDOW = 2000      # lives the trailing base rate is taken over (resolver.next_base_rate)
RESOLVES_KEPT = 4          # the last base rates, each with when it landed: a level is rewarded at the one before its lock
LOCK_SEEN_TTL_NS = 6 * 3600 * 10 ** 9
RESOLVE_TGAS = 30


class WriterError(RuntimeError):
    pass


REREAD_REFUSED_NS = 30 * 10**9   # a refused binding's token is read again once its last read is this old
ASK_GAP_NS = 5 * 10**9           # an activation asked again after this long without asking is a new activation


def merge_bag(chain: list, base_arena: list, arena: list) -> list:
    """The chain's bag with the arena's own moves applied: rows in base_arena but not in arena were lost (taken off),
    rows in arena that are new or changed since base_arena were gained (set); every other chain row stays."""
    out = {int(e["row"]): dict(e) for e in chain}
    was = {int(e["row"]): dict(e) for e in base_arena}
    has = {int(e["row"]): dict(e) for e in arena}
    for row in was:
        if row not in has:
            out.pop(row, None)
    for row, e in has.items():
        if was.get(row) != e:
            out[row] = e
    return [out[r] for r in sorted(out)]


class ChainWriter:
    def __init__(self, sender, cfg, data_dir, *, batch_segments=60, parts=3, commit_size=60, lookahead=15, attempts=4,
                 max_rows=72, sleep=time.sleep, log=None, clock=time.time, identity=None, manifest=False):
        self.sender, self.cfg = sender, cfg
        if identity is None or not cfg.identity_nft:
            raise ValueError("a chain writer needs the identity NFT and its reader (identity=, cfg.identity_nft): "
                             "owners are never read from the testnet inventory")
        self.identity = identity           # read-only: .view(account, method, args) on the identity NFT's network
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.batch_segments, self.commit_size, self.lookahead = batch_segments, commit_size, lookahead
        self.attempts, self.max_rows, self.parts = attempts, max_rows, parts
        # MANIFEST (B96): batches posted with the flag keep their slim record forever; `make demo` re-simulates them.
        self.manifest = bool(manifest)
        self.record = None                 # the arena's public record (arena/predict.py), set at its first seal
        self.predict_block = None          # the serving rules table's predict block (integer-16 on), or None
        self.sleep, self.clock = sleep, clock
        self._log = log or (lambda line: print(line, flush=True))
        self.lock = threading.RLock()      # the worker: one chain step at a time
        self.pool_lock = threading.Lock()  # the arena thread's only lock: the seed pool and the bound cursor
        self.inbox = collections.deque()   # seals snapshotted on the arena thread, applied by the worker
        self.last_seal_ns = time.time_ns()  # a lock first seen at a seal happened after the previous seal
        # Owner re-reads: a token sold mid-play must not fight another life under its old owner.
        self.owners = {}                   # token -> {"owner": account or None (no such identity token), "read_ns": int}
        self.ended = {}                    # token -> ns its last life ended (KO or leave)
        self.reads = collections.deque()   # tokens waiting for an owner read
        self.read_wake = threading.Event()
        self.arenas = {}          # id(arena) -> {"base": pool index of its segment 0, "given": seeds handed over}
        self.current = None
        self.failed = None
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.thread = None
        self.state_path = self.dir / "state.json"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else self._fresh()
        self.state.setdefault("pool_base", 0)
        # Tokens whose chain record is already in their tallies. A state written before this field existed counts every
        # token it tallied as seeded, so a resumed writer never adds the chain record twice.
        self.state.setdefault("seeded", sorted(self.state["tallies"]))
        # token -> its bag base: {"bag": the chain's bag as last read or filed, "arena": the arena's bag (entries) at that
        # moment, "at": where it came from}. A filing sends the chain's bag now plus the arena's own moves since the base.
        self.state.setdefault("bases", {})
        self._saved = None
        self.bound = self.state["cursor"]
        self.held = {}                     # token -> ns its activation was first held for an owner read
        self.asking = {}                   # token -> [ns this activation was first asked, ns last asked]
        self.chain_bags = {}               # token -> {"bag": inventory entries ([] if the token has none), "read_ns"}
        self.item_rows = fmt.item_rows()   # inventory rows name these items, whatever the rules table (append only)
        problems = fmt.check_registry(self.item_rows, fmt.released_tables())
        if problems:
            raise WriterError("the inventory row registry does not match the released rules tables: " + "; ".join(problems))
        self.rules_items = None            # the serving arena's rules items (set at its first segment)
        self.bag_reads = collections.deque()  # tokens whose inventory bag a first life here is waiting for
        self.bag_bases = {t: (b["bag"], b["arena"]) for t, b in self.state["bases"].items()}   # arena-thread copy

    # ------------------------------------------------------------------ records
    def _fresh(self):
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(self.clock()))
        return {"version": 1, "mode": self.sender.label, "arena": self.cfg.arena, "market": self.cfg.market,
                "prefix": f"t{stamp}{secrets.token_hex(2)}", "pool": [], "pool_base": 0, "cursor": 0, "synced": False,
                "pending_commit": None, "commits": [], "open": [], "next_batch": 0, "batches": [],
                "tallies": {}, "accounts": {}, "bags": {}, "actuals": [], "resolves": [], "lock_seen": {}, "carry": [],
                "seeded": [], "bases": {}}

    def _save(self):
        """Write state.json only when it changed; it holds unsettled work only, so it stays small."""
        text = json.dumps(self.state, sort_keys=True)
        if text == self._saved:
            return
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(text)
        os.replace(tmp, self.state_path)
        self._saved = text

    # The seed pool is kept from the first unbound seed on; positions stay absolute (pool_base + index).
    def _pool_len(self):
        return self.state["pool_base"] + len(self.state["pool"])

    def _pool_at(self, pos):
        return self.state["pool"][pos - self.state["pool_base"]]

    def _pool_from(self, pos):
        return self.state["pool"][pos - self.state["pool_base"]:]

    def _compact(self):
        """Move settled periods to batches.jsonl (append-only) and trim what no unsettled step reads."""
        done = []
        while self.state["batches"]:
            period = self.state["batches"][0]["period"] if "period" in self.state["batches"][0] else None
            group = [b for b in self.state["batches"] if b.get("period") == period] if period is not None \
                else [self.state["batches"][0]]
            if not all(b["status"] in ("applied", "abandoned")
                       and (b["resolve"] or {}).get("status") in ("resolved", "voided", "part") for b in group):
                break
            done += group
            self.state["batches"] = self.state["batches"][len(group):]
        if done:
            with open(self.dir / "batches.jsonl", "a") as f:
                for b in done:
                    f.write(json.dumps(b, sort_keys=True) + "\n")
        with self.pool_lock:
            cut = min(self.state["cursor"], self.bound) - self.state["pool_base"]
            if cut > 0:
                del self.state["pool"][:cut]
                self.state["pool_base"] += cut
        live = {p[0] for p in self.state["pool"]}            # commits with seeds still unused (the journal keeps all)
        self.state["commits"] = [c for c in self.state["commits"] if c["commit_id"] in live]
        del self.state["actuals"][:-ACTUALS_WINDOW]
        del self.state["resolves"][:-RESOLVES_KEPT]
        stale = time.time_ns() - LOCK_SEEN_TTL_NS
        self.state["lock_seen"] = {k: v for k, v in self.state["lock_seen"].items() if v is None or v > stale}

    def settled_batches(self):
        """Every batch moved out of state.json, in order (for summaries and the archival reader)."""
        path = self.dir / "batches.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines() if line] if path.exists() else []

    def log(self, kind, **fields):
        row = dict(at=round(self.clock(), 3), kind=kind, mode=self.sender.label, **fields)
        with open(self.dir / "journal.jsonl", "a") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
        text = " ".join(f"{k}={v}" for k, v in fields.items() if k not in ("args",))
        self._log(f"chain[{self.sender.label}]: {kind} {text}")

    def _hash_row(self, step, role, out):
        if out.get("tx") and out.get("landed") and self.sender.label != "dry-run":
            with open(self.dir / "hashes.tsv", "a") as f:
                f.write(f"R4-B {step}\t{self.sender.account(role)}\t{out['tx']}\n")

    # ------------------------------------------------------------------ seeds
    def start(self) -> None:
        """Sync the seed pool with the contract and make sure enough seeds are committed. Blocks."""
        with self.lock:
            self._sync()
            self._recover_commit()
            if self._unused() < self.lookahead + 1:
                self._commit()
            if self._unused() < 1:
                raise WriterError("no committed seed is available; the arena cannot open a segment")

    def _sync(self):
        if self.state["synced"]:
            return
        st = self.sender.view(self.cfg.arena, "state")
        nxt = st["next_seed"]
        cid, index, commits = int(nxt["commit_id"]), int(nxt["seed_index"]), int(st["commits"])
        for c in range(cid, commits):
            commit = self.sender.view(self.cfg.arena, "get_commit", {"commit_id": str(c)})
            first = index if c == cid else 0
            for i in range(first, int(commit["count"])):
                seed = fmt.derive_seed(bytes.fromhex(commit["secret"]), bytes.fromhex(commit["random_seed"]), i).hex()
                self.state["pool"].append([c, i, fmt.seed_u64(seed)])
            self.state["commits"].append({"commit_id": c, "count": int(commit["count"]), "tx": None,
                                          "from": "earlier commit, unused seeds taken first"})
        self.state["synced"] = True
        self.log("sync", next_seed=f"{cid}/{index}", commits=commits, unused_taken=len(self.state["pool"]))
        self._save()

    def _unused(self):
        return self._pool_len() - max(self.state["cursor"], self.bound)

    def _recover_commit(self):
        """A commit whose outcome was never seen: adopt it if it landed, else resend the same secret."""
        p = self.state["pending_commit"]
        if p is None:
            return
        st = self.sender.view(self.cfg.arena, "state")
        for c in range(int(st["commits"]) - 1, -1, -1):
            try:
                commit = self.sender.view(self.cfg.arena, "get_commit", {"commit_id": str(c)})
            except (rpclib.RpcError, Panic):   # a fully used commit is pruned (its event stays on archival)
                break
            if commit["secret"] == p["secret"]:
                self._adopt_commit(c, commit, p.get("tx"), "recovered")
                return
            if c < int(st["commits"]) - 8:
                break
        self._commit(secret=p["secret"], count=p["count"])

    def _adopt_commit(self, cid, commit, tx, how):
        if any(c["commit_id"] == cid for c in self.state["commits"]):
            self.state["pending_commit"] = None
            return
        add = [[cid, i, fmt.seed_u64(fmt.derive_seed(bytes.fromhex(commit["secret"]),
                                                       bytes.fromhex(commit["random_seed"]), i).hex())]
               for i in range(int(commit["count"]))]
        with self.pool_lock:
            self.state["pool"].extend(add)
        self.state["commits"].append({"commit_id": cid, "count": int(commit["count"]), "tx": tx,
                                      "block_height": commit["block_height"], "random_seed": commit["random_seed"]})
        self.state["pending_commit"] = None
        self.log("commit_adopted", commit_id=cid, how=how, tx=tx)
        self._save()

    def _commit(self, secret=None, count=None):
        secret = secret or secrets.token_hex(32)
        count = count or self.commit_size
        self.state["pending_commit"] = {"secret": secret, "count": count, "tx": None}
        self._save()
        for attempt in range(1, self.attempts + 1):
            out = self.sender.call("operator", self.cfg.arena, "commit_seeds", {"secret": secret, "count": count},
                                   COMMIT_TGAS)
            self.state["pending_commit"]["tx"] = out.get("tx")
            self._save()
            if out.get("landed") is None and out.get("tx"):
                out = self.sender.tx_status(out["tx"], "operator") or out
            if out.get("landed") and out.get("ok"):
                ev = [d for e in out["events"] if e.get("event") == "commit_seeds" for d in e["data"]]
                if not ev:
                    raise WriterError(f"commit {out['tx']} landed with no commit_seeds event")
                cid = int(ev[0]["commit_id"])
                seeds = out["value"]
                if len(seeds) != count:
                    raise WriterError("commit returned the wrong number of seeds")
                check = self.sender.view(self.cfg.arena, "seed_record", {"commit_id": str(cid), "index": 0})
                if check["seed"] != seeds[0]:
                    raise WriterError(f"commit {cid}: the returned seed differs from the contract's own")
                with self.pool_lock:
                    self.state["pool"].extend([cid, i, fmt.seed_u64(h)] for i, h in enumerate(seeds))
                self.state["commits"].append({"commit_id": cid, "count": count, "tx": out["tx"],
                                              "block_height": ev[0]["block_height"], "random_seed": ev[0]["random_seed"]})
                self.state["pending_commit"] = None
                self._save()
                self._hash_row(f"commit_seeds {count} (commit {cid})", "operator", out)
                self.log("commit", commit_id=cid, count=count, tx=out["tx"], block_height=ev[0]["block_height"],
                         tgas=out.get("tgas"), published="seeds read from this tx's return value")
                return cid
            if out.get("landed") and "secret already committed" in (out.get("failure") or ""):
                self._recover_commit()
                return None
            self.log("commit_retry", attempt=attempt, landed=out.get("landed"), tx=out.get("tx"),
                     failure=out.get("failure"))
            self.sleep(min(30, 3 * attempt))
        raise WriterError("commit_seeds failed after every attempt (see journal); the arena keeps its current seeds")

    def claim_seeds(self, arena) -> list[int]:
        """Seeds for a new arena: every committed seed not yet bound to a sealed segment. Arena thread."""
        with self.pool_lock:
            if self.failed:
                raise WriterError(f"chain writer stopped: {self.failed}")
            base = self.bound
            seeds = [p[2] for p in self._pool_from(base)]
            if not seeds:
                raise WriterError("no committed seed is available")
            self.arenas[id(arena)] = {"base": base, "given": len(seeds)}
            self.current = id(arena)
            first = self._pool_at(base)
        self.inbox.append({"kind": "claim", "deployment": arena.context.get("deployment_id"),
                           "first_seed": f"{first[0]}/{first[1]}", "seeds": len(seeds)})
        return seeds

    def take_seeds(self, arena) -> list[int]:
        """Seeds committed since this arena last asked. Arena thread, at each segment open."""
        with self.pool_lock:
            a = self.arenas.get(id(arena))
            if a is None or id(arena) != self.current:
                return []
            if not a.get("rows_checked"):    # its first segment: an item the row registry lacks stops the arena here
                fmt.row_index(arena.sim.rules["items"], self.item_rows)
                self.rules_items = arena.sim.rules["items"]
                a["rows_checked"] = True
            new = [p[2] for p in self._pool_from(a["base"] + a["given"])]
            a["given"] += len(new)
            return new

    # ------------------------------------------------------------------ owners
    def life_ended(self, token: str) -> None:
        """Arena thread, at a KO or a leave: the token's owner is read again before its next life."""
        self.ended[token] = time.time_ns()
        self.reads.append(token)
        self.read_wake.set()

    def owner_ok(self, binding: dict) -> bool:
        """Arena thread, at each activation: never blocks; answers from the last owner read.

        The owner is the identity NFT's (mainnet, Pat 2026-11-11), read by the binding's token id. A life is
        admitted only on a read sent after this activation was first asked (and after the token's last life ended):
        a read taken earlier, even one after the last KO, misses a sale that landed since (the live identity
        rehearsal found it), so each life waits one read. The read must name the binding's account. Until it lands the activation is refused and the room
        keeps the member queued (it retries), so an RPC error or timeout holds the life (fail closed). Another owner
        is refused and logged OWNER_CHANGED; no such token (never minted, or burned) is refused and logged
        OWNER_MISSING. This re-reads every token, a superset of the request_exit and 48 h exit cases.

        A binding whose context names another NFT contract (the DEV room's ids) has nothing onchain to read and is
        admitted. One naming the testnet inventory NFT is read from the identity NFT like any other: the inventory's
        shadow tokens sit with a mirror account, so its owner is never consulted.
        """
        token, account = binding["nft_token_id"], binding["account_id"]
        nft = ((binding.get("context") or {}).get("contract_ids") or {}).get("nft")
        if nft is not None and nft not in (self.cfg.identity_nft, self.cfg.nft):
            return True            # not a trenchie of this deployment (DEV ids): nothing onchain to read
        ended = self.ended.get(token)
        o = self.owners.get(token)
        now = time.time_ns()
        ask = self.asking.get(token)
        if ask is None or now - ask[1] > ASK_GAP_NS:
            ask = self.asking[token] = [now, now]      # a new activation: it needs a read sent from now on
        ask[1] = now
        if o is None or o["read_ns"] < ask[0] or (ended is not None and o["read_ns"] <= ended):
            if token not in self.reads:
                self.reads.append(token)
            self.held.setdefault(token, time.time_ns())
            self.read_wake.set()
            return False
        self.held.pop(token, None)
        if o["owner"] == account:
            self.asking.pop(token, None)
            return True
        if time.time_ns() - o["read_ns"] > REREAD_REFUSED_NS and token not in self.reads:
            self.reads.append(token)       # a refusal never sticks on an old read: the token may have come back
            self.read_wake.set()
        if o.get("refused") != account:
            o["refused"] = account
            self.inbox.append({"kind": "owner_changed" if o["owner"] is not None else "owner_missing",
                               "token": token, "owner": o["owner"], "binding": account})
        return False

    def read_owners(self) -> None:
        """Worker: read each queued token's owner from the identity NFT's `nft_token` (NEP-171), finality final.

        An error or timeout leaves the token queued and its life held; nothing here ever reads the testnet NFT."""
        while self.reads:
            token = self.reads.popleft()
            sent = time.time_ns()                 # stamped at send: a sale after this is caught by the next read
            try:
                p = self.identity.view(self.cfg.identity_nft, "nft_token", {"token_id": token})
                owner = None if p is None else p["owner_id"]
                if owner is not None and not isinstance(owner, str):
                    raise ValueError(f"owner_id is not an account: {owner!r}")
            except (rpclib.RpcError, rpclib.RpcUnreachable, Panic, KeyError, TypeError, ValueError) as exc:
                self.reads.append(token)          # retried on the next pass; the guard keeps refusing meanwhile
                self.inbox.append({"kind": "owner_read_retry", "token": token,
                                   "error": f"{type(exc).__name__}: {exc}"[:200]})
                return
            old = self.owners.get(token)
            self.owners[token] = {"owner": owner, "read_ns": sent}
            if old and old.get("refused") and old["owner"] == owner:
                self.owners[token]["refused"] = old["refused"]   # the same owner again: the refusal is already logged
        while self.bag_reads:      # a token's gear on the inventory, read once, when its first life here needs it
            token = self.bag_reads.popleft()
            sent = time.time_ns()
            try:
                inv = self.sender.view(self.cfg.nft, "trenchie", {"token_id": token})
            except (rpclib.RpcError, rpclib.RpcUnreachable, Panic) as exc:
                self.bag_reads.append(token)
                self.inbox.append({"kind": "owner_read_retry", "token": token, "error": f"inventory: {type(exc).__name__}: {exc}"[:200]})
                return
            self.chain_bags[token] = {"bag": list((inv or {}).get("bag") or []), "read_ns": sent}

    def inventory_bag(self, token: str, items) -> dict | None:
        """Arena thread: the token's gear on the inventory as a sim bag ({row id: entry}), or None until it is read
        (the read is queued). Rows index the rules table's items in sorted order, as the batch rows file them."""
        rec = self.chain_bags.get(token)
        if rec is None:
            if token not in self.bag_reads:
                self.bag_reads.append(token)
            self.read_wake.set()
            return None
        bag, kept = {}, []
        for e in rec["bag"]:
            i = int(e["row"])
            name = self.item_rows[i] if 0 <= i < len(self.item_rows) else None
            if name is None or name not in items or items[name].get("default"):
                kept.append(dict(e))         # a row this table cannot carry (unknown, retired, a starter): kept as is
                continue
            bag[name] = {k: int(e[k]) for k in ("serial", "born_batch", "kos", "hands", "flags")}
        if not rec.get("reported"):
            rec["reported"] = True
            carried = [dict(e) for e in rec["bag"] if dict(e) not in kept]
            self.inbox.append({"kind": "inventory_loaded", "token": token, "bag": [dict(e) for e in rec["bag"]],
                               "arena": carried, "kept": kept})
            self.bag_bases[token] = ([dict(e) for e in rec["bag"]], carried)
        return bag

    def saved_bag_update(self, token: str, saved: dict, items) -> dict | None:
        """Arena thread, at a life reserved from the arena's saved bag: the bag to use instead when the chain holds
        moves the arena has not seen (another host filed this token since this arena's base), as the chain's latest
        bag plus this arena's own moves since its base; None when the saved bag is current."""
        base = self.bag_bases.get(token)
        if base is None:
            return None
        now = fmt.bag_entries(saved, fmt.row_index(saved, self.item_rows))
        merged = merge_bag(base[0], base[1], now)
        sim = {}
        for e in merged:
            name = self.item_rows[int(e["row"])] if 0 <= int(e["row"]) < len(self.item_rows) else None
            if name is not None and name in items and not items[name].get("default"):
                sim[name] = {k: int(e[k]) for k in ("serial", "born_batch", "kos", "hands", "flags")}
        if sim == saved:
            return None
        self.inbox.append({"kind": "saved_bag_reloaded", "token": token, "from": sorted(saved), "to": sorted(sim)})
        return sim

    def run_owner_reader(self, every=2.0) -> None:
        def loop():
            while not self.stop.is_set():
                self.read_owners()
                self.read_wake.wait(every)
                self.read_wake.clear()
        threading.Thread(target=loop, name="chain-owners", daemon=True).start()

    # ------------------------------------------------------------------ seals
    def sealed(self, arena, segment_id: str, record: dict) -> None:
        """Arena thread: bind the segment to its seed position and snapshot what the batch needs.

        Touches no chain and no writer record, holds only the small pool lock, and never raises into the
        arena's tick: a fault stops the writer and says so; the arena keeps running.
        """
        try:
            with self.pool_lock:
                a = self.arenas.get(id(arena))
                if a is None or id(arena) != self.current:
                    self.inbox.append({"kind": "ignored", "segment": segment_id})
                    return
                pos = a["base"] + arena.segment_index
                if a.get("sealed") == (arena.segment_index, record["sealed"]["sealed_result_hash"]):
                    return            # the arena seals a segment again at the next tick's boundary; same record
                if pos != self.bound:
                    raise WriterError(f"segment {segment_id} sits at seed {pos}, the next unbound seed is {self.bound}")
                self.bound = pos + 1
                a["sealed"] = (arena.segment_index, record["sealed"]["sealed_result_hash"])
            s = record["sealed"]
            row_index = fmt.row_index(arena.sim.rules["items"], self.item_rows)
            bags, accounts = {}, {}
            for token in s["nft_token_ids"]:
                m = arena.members.get(token)
                if m is not None:
                    accounts[token] = m["binding"]["account_id"]
                f = arena.sim.state["fighters"].get(token)
                bag = f["bag"] if f is not None else (m["profile"].get("bag") if m is not None else None)
                if bag is None and token in arena.inventories:   # it left before the seal: the bag the arena saved
                    bag = arena.inventories[token]["bag"]
                if bag is not None:
                    bags[token] = fmt.bag_entries(bag, row_index)
            self.record = getattr(arena, "record", None)      # the arena's public record; settlement rows go there
            self.predict_block = arena.sim.rules.get("predict")
            rows = copy.deepcopy(getattr(arena, "sealed_rows", {}))
            picks, locks = {}, {}
            for p in record["predictions"]:
                locks[p["life_id"]] = self.last_seal_ns
                pick = p.get("pick")
                picks[p["life_id"]] = copy.deepcopy(pick["payload"]["spread_bps"]) if pick else None
            self.inbox.append({
                "kind": "seal", "pos": pos, "segment_id": segment_id, "segment_index": arena.segment_index,
                "deployment": arena.context.get("deployment_id", "arena"),
                "sealed": {k: copy.deepcopy(s[k]) for k in ("seed", "seed_hash", "inputs_hash", "rules_hash",
                                                            "final_state_hash", "predictions_log_hash", "lives",
                                                            "nft_token_ids")},
                "picks": picks, "bags": bags, "accounts": accounts, "rows": rows,
                "levels": arena.sim.rules.get("predict") is not None,
                "house_log": getattr(arena, "prediction_log_hashes", {}).get(segment_id),
                "local": str(arena.store.segments / (segment_id.replace(":", "-") + ".json")),
                "locks": locks, "sealed_ns": time.time_ns()})
            self.last_seal_ns = time.time_ns()
        except Exception as exc:
            self.failed = f"{type(exc).__name__}: {exc}"
            self.inbox.append({"kind": "failed", "segment": segment_id, "error": self.failed})
        finally:
            self.wake.set()

    def _drain(self):
        while self.inbox:
            e = self.inbox.popleft()
            if e["kind"] == "claim":
                self.log("claim", deployment=e["deployment"], first_seed=e["first_seed"], seeds=e["seeds"])
            elif e["kind"] == "ignored":
                self.log("seal_ignored", segment=e["segment"], why="not the arena this writer serves")
            elif e["kind"] == "failed":
                self.log("FAILED", during="seal", segment=e["segment"], error=e["error"])
            elif e["kind"] == "owner_changed":
                self.log("OWNER_CHANGED", token=e["token"], owner_now=e["owner"], binding=e["binding"],
                         why="the identity NFT names another owner (sold, or never this account): no life under this binding")
            elif e["kind"] == "owner_missing":
                self.log("OWNER_MISSING", token=e["token"], binding=e["binding"],
                         why="the identity NFT has no such token (never minted, or burned): no new life")
            elif e["kind"] == "inventory_loaded":
                self.state["bases"][e["token"]] = {"bag": e["bag"], "arena": e["arena"], "at": "load"}
                if e["kept"]:
                    self.log("inventory_rows_kept", token=e["token"], rows=[k["row"] for k in e["kept"]],
                             why="rows this rules table cannot put in a bag stay on the chain untouched; never re-pointed or dropped")
            elif e["kind"] == "saved_bag_reloaded":
                self.log("saved_bag_reloaded", token=e["token"], saved=e["from"], now=e["to"],
                         why="the chain moved since this arena's base: the next life starts from the chain plus this arena's own moves")
            elif e["kind"] == "owner_read_retry":
                self.log("owner_read_retry", token=e["token"], error=e["error"])
            else:
                self._apply_seal(e)
                self._save()

    def _apply_seal(self, e):
        pos = e["pos"]
        if pos != self.state["cursor"]:
            raise WriterError(f"seal at seed {pos}, record cursor {self.state['cursor']}")
        cid, index, value = self._pool_at(pos)
        s = e["sealed"]
        if s["seed"] != str(value) or s["seed_hash"] != fmt.seed_hash(value):
            raise WriterError(f"segment {e['segment_id']} did not run on committed seed {cid}/{index}")
        seg = {"segment_id": f"{self.state['prefix']}.{e['deployment']}.{e['segment_index']}"[:64],
               "commit_id": str(cid), "seed_index": index, "seed_hash": s["seed_hash"], "inputs_hash": s["inputs_hash"],
               "rules_hash": s["rules_hash"], "final_state_hash": s["final_state_hash"],
               "predictions_log_hash": s["predictions_log_hash"], "kos": fmt.segment_kos(s)}
        fmt.check_segment(seg)
        self.state["cursor"] = pos + 1
        base_bps = self.state["resolves"][-1]["base_rate"] if self.state["resolves"] else list(resolver.quote.PUBLISHED_BASE_BPS)
        self.state["accounts"].update(e["accounts"])
        done = {life["life_id"] for life in s["lives"]}
        for life_id, at in e["locks"].items():      # the earliest seal that saw each still-running life's lock
            if life_id not in done:
                self.state["lock_seen"].setdefault(life_id, at)
        self.state["bags"].update(e["bags"])
        lives = []
        rows = e.get("rows", {})
        for life in s["lives"]:
            token, kos = life["nft_token_id"], int(life["ko_count"])
            t = self.state["tallies"].setdefault(token, {"lives": 0, "kos": 0, "skill_sum": 0, "skill_n": 0})
            t["lives"] += 1
            t["kos"] += kos
            row = rows.get(life["life_id"])
            # Rarity comes from house lives only, so no player can cheapen a level with throwaway lives (r5-predict).
            if row is not None and row["house"]:
                self.state["actuals"].append(kos)        # trimmed to ACTUALS_WINDOW in _compact
            spread = e["picks"].get(life["life_id"])
            if e.get("levels"):                          # integer-16 on: one level per life, scored in the seal row
                level = row["level"] if row is not None else None
                first = self.state["lock_seen"].pop(life["life_id"], None) or e["locks"].get(life["life_id"])
                lives.append({"account": self.state["accounts"].get(token), "token": token, "life_id": life["life_id"],
                              "kos": kos, "bins": None, "level": level,
                              "multiplier_bps": row["multiplier_bps"] if level is not None else None,
                              "result": row["result"] if row is not None else "none", "locked_after_ns": first,
                              "run": row.get("run", "local") if row is not None else "local"})
                continue
            bins = resolver.bins_from_spread(spread) if spread else None
            if bins is not None:
                ai = resolver.quote.rps_numerator(bins, kos) * resolver.MICRO // resolver.RPS_MAX
                base = resolver.quote.rps_numerator(tuple(base_bps), kos) * resolver.MICRO // resolver.RPS_MAX
                t["skill_sum"] += base - ai
                t["skill_n"] += 1
            first = self.state["lock_seen"].pop(life["life_id"], None) or e["locks"].get(life["life_id"])
            lives.append({"account": self.state["accounts"].get(token), "token": token, "life_id": life["life_id"],
                          "kos": kos, "bins": list(bins) if bins else None, "locked_after_ns": first})
        self.state["open"].append({"segment": seg, "tokens": sorted(s["nft_token_ids"]), "lives": lives,
                                   "house_log": e["house_log"], "local": e["local"]})
        self.log("seal", segment=seg["segment_id"], seed=f"{cid}/{index}", kos=seg["kos"], lives=len(lives),
                 open=len(self.state["open"]), unused_seeds=self._unused())
        if len(self.state["open"]) >= self.batch_segments:
            self._close_batch()

    def _seed_records(self, tokens) -> set:
        """Before a token is filed by this writer for the first time, add the record the chain already holds for it
        (the inventory's `trenchie` view) to its tallies: a record is absolute, so filing from 0 would erase the token's
        past (a fresh state, a new host). All reads first, then all adds. If a read fails, nothing is added, the period
        is not filed and the log says so; it is tried again on the next cycle (never filed from zero). The chain keeps
        the skill average, not how many lives it averages, so the seed weighs it by the record's lives."""
        seeded = set(self.state["seeded"])
        records, chain, failed = {}, {}, set()
        for token in sorted(tokens):    # every token's chain bag now (a filing applies moves to it); records once
            try:
                view = self.sender.view(self.cfg.nft, "trenchie", {"token_id": token})
            except (rpclib.RpcError, rpclib.RpcUnreachable, Panic) as exc:
                self.log("RECORD_SEED_FAILED", token=token, error=f"{type(exc).__name__}: {exc}"[:200],
                         why="this token's chain record and bag could not be read: its row waits for the next period "
                             "(never from zero, never over the chain's bag); the other tokens file")
                failed.add(token)
                continue
            chain[token] = [dict(e) for e in (view or {}).get("bag") or []]
            if token not in seeded:
                records[token] = (view or {}).get("record")
        self.chain_now = chain
        for token, rec in records.items():
            if rec:
                lives, kos, skill = int(rec["lives"]), int(rec["kos"]), int(rec["skill"])
                t = self.state["tallies"].setdefault(token, {"lives": 0, "kos": 0, "skill_sum": 0, "skill_n": 0})
                t["lives"] += lives
                t["kos"] += kos
                t["skill_sum"] += skill * 1000 * lives
                t["skill_n"] += lives
                self.log("record_seeded", token=token, chain_lives=lives, chain_kos=kos, chain_skill=skill)
        self.state["seeded"] = sorted(seeded | set(records))
        return failed

    def _close_batch(self):
        """Close one period (`batch_segments` seals) into `parts` batches that post in order (G0 option)."""
        opened = self.state["open"]
        tokens = {t for o in opened for t in o["tokens"]} | set(self.state["carry"])
        failed = self._seed_records(tokens)
        self.state["open"] = []
        self.state["carry"] = []
        rows = self._rows(tokens - failed)
        parts = max(1, min(self.parts, len(opened)))       # every part carries at least one segment
        capacity = parts * self.max_rows
        if len(rows) > capacity:                           # option A's rule: the rest waits for the next period
            self.state["carry"] = [r["token_id"] for r in rows[capacity:]]
            rows = rows[:capacity]
            self.log("rows_carried", rows=len(self.state["carry"]),
                     why=f"over this period's {parts} x {self.max_rows} rows; they go in the next period")
        n = self.state["next_batch"]
        self.state["next_batch"] = n + 1
        seg_cut = [len(opened) * i // parts for i in range(parts + 1)]
        row_cut = [len(rows) * i // parts for i in range(parts + 1)]
        ids = [f"{self.state['prefix']}-{n}" if parts == 1 else f"{self.state['prefix']}-{n}.{i + 1}" for i in range(parts)]
        self.state["carry"] = sorted(set(self.state["carry"]) | failed)   # unread tokens file in the next period
        house_log = next((o["house_log"] for o in reversed(opened) if o["house_log"]), None)
        for i in range(parts):
            self._add_part(opened, rows, n, i, parts, ids, seg_cut, row_cut, house_log)

    def _add_part(self, opened, rows, n, i, parts, ids, seg_cut, row_cut, house_log):
        mine = opened[seg_cut[i]:seg_cut[i + 1]]
        last = i == parts - 1
        b = {"batch_id": ids[i], "period": n, "part": i + 1, "parts": parts,
             "segments": [o["segment"] for o in mine], "rows": rows[row_cut[i]:row_cut[i + 1]], "manifest": self.manifest,
             "lives": [l for o in opened for l in o["lives"]] if last else [],
             "period_segments": [o["segment"] for o in opened] if last else None,
             "house_log": house_log if last else None, "local": [o["local"] for o in mine],
             "status": "queued", "attempts": [],
             # each row's new bag base, committed only once this batch has applied (a carried, abandoned, held or
             # unapplied row keeps the arena's moves pending for the next filing)
             "pending_bases": {r["token_id"]: self.pending_bases[r["token_id"]] for r in rows[row_cut[i]:row_cut[i + 1]]},
             # one stake batch a period: the last part resolves it
             "resolve": None if last else {"status": "part", "with": ids[-1]}}
        est = estimate_tgas(len(b["segments"]), len(b["rows"]))
        b["estimate_tgas"] = est
        if len(b["rows"]) > self.max_rows or est > SAFE_TGAS:
            b["status"] = "held"
            b["held"] = (f"{len(b['rows'])} rows, {len(b['segments'])} segments, worst-case {est} Tgas: over the "
                         f"{self.max_rows}-row / {SAFE_TGAS} Tgas cap; the split is Pat's G0 pick")
        b["fight_hash"], b["rows_digest"] = fmt.fight_hash(b["segments"]), fmt.rows_digest(b["rows"])
        self.state["batches"].append(b)
        self.log("batch_closed", batch=b["batch_id"], part=f"{i + 1}/{parts}", segments=len(b["segments"]),
                 rows=len(b["rows"]), estimate_tgas=est, fight_hash=b["fight_hash"], status=b["status"],
                 **({"held": b["held"]} if "held" in b else {}))

    # ------------------------------------------------------------------ chain work
    def process(self) -> None:
        """Do every chain step that is due: a seed top-up, then batches in order, then their resolves."""
        with self.lock:
            if self.failed:
                return
            try:
                self._drain()
                if self.failed:
                    return
                if len(self.state["open"]) >= self.batch_segments:
                    self._close_batch()      # a period whose record seed failed last time is tried again
                if self._unused() < self.lookahead and self.state["pending_commit"] is None:
                    self._commit()
                elif self.state["pending_commit"] is not None:
                    self._recover_commit()
                # Resolves, in order. The first unsettled period's stake batch is closed at once, at the period's
                # end (a stake placed after it joins the next period), and resolved once the period's
                # record exists; a blocked resolve is re-read and retried each cycle, later ones wait.
                for b in self.state["batches"]:
                    if (b["resolve"] or {}).get("status") in ("resolved", "voided", "part"):
                        continue
                    self._resolve(b, ready=b["status"] in ("applied", "pending_hop", "abandoned"))
                    break
                # Posts, strictly in order, stopping at the first batch not applied: rows are absolute and the
                # contracts don't order batches, so a later batch applied before an older pending one would be
                # rolled back when the older one's hop is retried.
                for b in self.state["batches"]:
                    if b["status"] not in ("applied", "abandoned"):
                        if b["status"] != "held":
                            self._post(b)
                        if b["status"] not in ("applied", "abandoned"):
                            break
                # The second pass resolves the period whose record the posts just wrote, in the same cycle.
                for b in self.state["batches"]:
                    if (b["resolve"] or {}).get("status") in ("resolved", "voided", "part"):
                        continue
                    self._resolve(b, ready=b["status"] in ("applied", "pending_hop", "abandoned"))
                    break
            except WriterError as exc:
                self.failed = str(exc)
                self.log("FAILED", error=self.failed)
            except (rpclib.RpcUnreachable, rpclib.RpcError) as exc:
                # A node that rate-limits (429) or errors on a read: nothing was decided on it. Every step reads
                # back before it repeats, so the next cycle picks up where this one stopped.
                self.log("rpc_retry", error=str(exc)[:300], next="the next cycle")
            finally:
                self._compact()
                self._save()

    def _carry(self, b):
        """The owner abandoned this batch: its seeds stay used; its personas' rows go again in the next batch."""
        self.state["carry"] = sorted(set(self.state["carry"]) | {r["token_id"] for r in b["rows"]})
        nxt = next((x for x in self.state["batches"] if x["status"] == "queued"), None)
        if nxt is not None:
            self._rebuild_rows(nxt)
        self.log("ABANDONED", batch=b["batch_id"], carried=len(self.state["carry"]),
                 into=nxt["batch_id"] if nxt else "the next batch to close")

    def _rows(self, tokens):
        self.pending_bases = {}
        rows = []
        for token in sorted(tokens):
            t = self.state["tallies"].get(token, {"lives": 0, "kos": 0, "skill_n": 0, "skill_sum": 0})
            skill = t["skill_sum"] // t["skill_n"] // 1000 if t["skill_n"] else 0
            bag = self._bag_to_file(token)
            rows.append({"token_id": token, "bag": bag,
                         "record": {"lives": t["lives"], "kos": t["kos"], "skill": skill}, "sale_ready": None})
        for r in rows:
            fmt.check_row(r)
        return rows

    def _bag_to_file(self, token):
        """The chain's bag now plus this arena's own moves since the token's base, and the new base. A row the arena
        did not move stays as the chain has it (another host's row, a starter, a retired item); a row the arena lost is
        taken off; a row it gained or changed is set. With no base (no arena here loaded this token), the arena's
        moves are unknown: the chain's bag is filed as it is and every arena row not filed is logged by name."""
        base = self.state["bases"].get(token)
        now = self.state["bags"].get(token)
        chain = getattr(self, "chain_now", {}).get(token, base["bag"] if base else [])
        if base is None:
            filed = sorted(chain, key=lambda e: int(e["row"]))
            declined = [e for e in now or [] if e not in chain]
            if declined:
                self.log("bag_rows_not_filed", token=token, rows=[(e["row"], e["serial"]) for e in declined],
                         why="no arena here loaded this token from the chain, so its moves are unknown; the chain's bag stands")
        else:
            if chain != base["bag"]:
                self.log("chain_bag_moved", token=token, why="another filing changed this token since the base: "
                         "this arena's own moves are applied to the chain's bag now")
            filed = merge_bag(chain, base["arena"], now if now is not None else base["arena"])
        if len(filed) > fmt.MAX_BAG:
            self.log("bag_over_cap", token=token, rows=len(filed), why="over 48 entries: the last rows wait")
            filed = filed[:fmt.MAX_BAG]
        arena = now if now is not None else (base["arena"] if base else [])
        self.pending_bases[token] = {"bag": filed, "arena": arena, "at": "filed"}   # the base once this row applies
        return filed

    def _unfunded(self, b, out):
        """The inventory could not afford the record of a token it met for the first time (trenchie_nft apply_rows'
        `unfunded`): that row did not apply, so its bag base stays and its row goes again in the next batch."""
        unfunded = sorted({t for e in out.get("events") or [] if e.get("event") == "apply_rows"
                           for d in e.get("data") or [] for t in d.get("unfunded") or []})
        if not unfunded:
            return
        for t in unfunded:
            (b.get("pending_bases") or {}).pop(t, None)
        b["unfunded"] = unfunded
        self.state["carry"] = sorted(set(self.state["carry"]) | set(unfunded))
        self.log("RECORD_UNFUNDED", batch=b["batch_id"], tokens=unfunded,
                 why="the inventory's balance could not make these tokens' records; their rows go again in the next "
                     "batch (top up the inventory contract)")

    def _commit_bases(self, b):
        """The batch applied: its rows are the chain's bags now, so they become the tokens' bases."""
        for token, base in (b.pop("pending_bases", None) or {}).items():
            self.state["bases"][token] = base
            self.bag_bases[token] = (base["bag"], base["arena"])

    def _rebuild_rows(self, b):
        b["rows"] = self._rows({r["token_id"] for r in b["rows"]} | set(self.state["carry"]))
        b["pending_bases"] = {r["token_id"]: self.pending_bases[r["token_id"]] for r in b["rows"]}
        b["rows_digest"] = fmt.rows_digest(b["rows"])
        self.state["carry"] = []

    def _record_status(self, b):
        rec = self.sender.view(self.cfg.arena, "get_batch", {"batch_id": b["batch_id"]})
        if rec is None:
            return None
        if rec["fight_hash"] != b["fight_hash"] or rec["rows_digest"] != b["rows_digest"]:
            raise WriterError(f"batch {b['batch_id']} onchain holds other content; stopping")
        return {"Applied": "applied", "Abandoned": "abandoned"}.get(rec["status"], "pending_hop")

    def _post(self, b):
        args = {"batch_id": b["batch_id"], "segments": b["segments"], "rows": b["rows"], "manifest": b["manifest"]}
        for attempt in range(1, self.attempts + 1):
            out = self.sender.call("operator", self.cfg.arena, "post_batch", args, POST_TGAS)
            if out.get("landed") is None and out.get("tx"):
                seen = self.sender.tx_status(out["tx"], "operator")
                if seen is not None:
                    out = seen
            status, why = self._classify(b, out)
            b["attempts"].append({"tx": out.get("tx"), "landed": out.get("landed"), "status": status, "why": why,
                                  "tgas": out.get("tgas"), "receipt_failures": out.get("receipt_failures", [])})
            if out.get("landed"):
                self._hash_row(f"post_batch {b['batch_id']} ({len(b['segments'])} seg, {len(b['rows'])} rows) {status}",
                               "operator", out)
            b["status"] = status
            if status == "applied":
                self._unfunded(b, out)
                self._commit_bases(b)
            self.log("post_batch", batch=b["batch_id"], attempt=attempt, tx=out.get("tx"), status=status, why=why,
                     tgas=out.get("tgas"))
            self._save()
            if status in ("applied", "conflict", "abandoned"):
                if status == "conflict":
                    raise WriterError(f"batch {b['batch_id']}: {why}")
                if status == "abandoned":
                    self._carry(b)
                return
            self.sleep(min(60, 5 * attempt))
        if b["status"] in ("queued", "unknown"):
            b["status"] = "held_retry"
        self.log("HELD", batch=b["batch_id"], status=b["status"],
                 why=f"not applied after {self.attempts} attempts; retried at the next cycle with the same id")

    def _classify(self, b, out):
        if out.get("landed") is None:
            st = self._record_status(b)
            return (st or "unknown"), "no outcome seen; read back from get_batch" + ("" if st else ": no record, resend")
        if out.get("landed") is False:
            st = self._record_status(b)          # a refusal (a stale nonce, say) can follow a send that landed
            return (st or "unknown"), f"refused before inclusion: {out.get('failure')}" + (f"; record {st}" if st else "")
        if not out.get("ok"):
            f = out.get("failure") or ""
            if "batch id reused with different content" in f:
                return "conflict", f
            if "batch was abandoned" in f:
                return "abandoned", f
            st = self._record_status(b)
            return (st or "held_retry"), f"tx failed: {f}"
        results = [d for e in out["events"] if e.get("event") == "apply_result" for d in e["data"]]
        if any(d.get("already_applied") for e in out["events"] if e.get("event") == "post_batch" for d in e["data"]):
            return "applied", "already applied (same id, same content)"
        if results and results[-1]["status"] == "applied":
            return "applied", "hop applied"
        return "pending_hop", "hop failed: " + "; ".join(out.get("receipt_failures") or ["no apply_result"])

    def _resolve(self, b, ready=True):
        """close_batch (at once), then, when the period's record exists, batch_stakes and resolve.

        Every step is read back before it is repeated."""
        log_hash = fmt.batch_log_hash(b.get("period_segments") or b["segments"], b.get("house_log"))
        r = b["resolve"] = b["resolve"] or {"status": "closing"}
        st = self.sender.view(self.cfg.market, "state")
        if r.get("market_batch") is None:
            st = self._close_stake_batch(b, st)
            if st.get("closed") is None:
                r["status"] = "retry"
                return
            r.update(market_batch=int(st["closed"]["batch"]), stakes=int(st["closed"]["stakes"]), status="closed")
            self._save()
        if not ready:
            return
        if self._settled(b, st, log_hash):
            return
        stakes = self._closed_stakes(r["market_batch"])
        if len(stakes) != r["stakes"]:
            r["status"] = "retry"
            self.log("resolve_retry", batch=b["batch_id"], market_batch=r["market_batch"],
                     why=f"batch_stakes lists {len(stakes)} of the {r['stakes']} closed stakes; re-read next cycle")
            return
        self._send_resolve(b, stakes, int(st["pot"]), log_hash)

    def _close_stake_batch(self, b, st):
        """Close the market's open stake batch unless one is already closed; returns the state after."""
        if st.get("closed") is not None:
            return st
        out = self.sender.call("resolver", self.cfg.market, "close_batch", {}, RESOLVE_TGAS)
        if out.get("landed") is None and out.get("tx"):
            out = self.sender.tx_status(out["tx"], "resolver") or out
        self.log("close_batch", batch=b["batch_id"], tx=out.get("tx"), landed=out.get("landed"), ok=out.get("ok"),
                 failure=out.get("failure"))
        if out.get("landed") and out.get("ok"):
            self._hash_row(f"close_batch stake batch {out['value']['batch']} for {b['batch_id']}", "resolver", out)
        return self.sender.view(self.cfg.market, "state")

    def _settled(self, b, st, log_hash):
        """True when the closed stake batch is already resolved (read back) or was voided by a timeout."""
        r, mb = b["resolve"], b["resolve"]["market_batch"]
        done = self.sender.view(self.cfg.market, "batch", {"batch": str(mb)})
        if done is not None:
            ours = done["log_hash"] == log_hash
            r["status"] = "resolved" if ours else "conflict"
            self.log("resolve", batch=b["batch_id"], market_batch=mb, status=r["status"] + " (read back)")
            if not ours:
                raise WriterError(f"stake batch {mb} was resolved with another log hash")
            return True
        closed = st.get("closed")
        if (self.sender.view(self.cfg.market, "batch_voided", {"batch": str(mb)}) is not None
                or closed is None or int(closed["batch"]) != mb):
            r["status"] = "voided"
            self.log("RESOLVE_VOIDED", batch=b["batch_id"], market_batch=mb,
                     why="the stake batch timed out and was voided: every stake in it refunded, none resolved")
            return True
        return False

    def _closed_stakes(self, mb):
        stakes, start = [], 0
        while True:
            got = self.sender.view(self.cfg.market, "batch_stakes", {"batch": str(mb), "from_index": start, "limit": 100})
            stakes += got
            if len(got) < 100:
                return stakes
            start += 100

    def _send_resolve(self, b, stakes, pot, log_hash):
        r, mb = b["resolve"], b["resolve"]["market_batch"]
        amounts = {s["account_id"]: int(s["stake"]["amount"]) for s in stakes}
        parts = {s["account_id"]: s["stake"]["parts"] for s in stakes}
        base_rate = self.state["resolves"][-1]["base_rate"] if self.state["resolves"] else list(resolver.quote.PUBLISHED_BASE_BPS)
        plan = resolver.compute(amounts, b["lives"], pot, base_rate, parts=parts)
        p = self.predict_block
        nxt = resolver.next_base_rate(self.state["actuals"], min_lives=p["min_lives"] if p else 1)
        args = {"batch": str(mb), "results": plan["results"], "pot_delta": plan["pot_delta"], "base_rate": nxt,
                "log_hash": log_hash}
        r.update(plan=plan, args=args)
        out = self.sender.call("resolver", self.cfg.market, "resolve", args, RESOLVE_TGAS)
        if out.get("landed") is None and out.get("tx"):
            out = self.sender.tx_status(out["tx"], "resolver") or out
        if out.get("landed") and out.get("ok"):
            r.update(status="resolved", tx=out["tx"])
            self.state["resolves"].append({"batch_id": b["batch_id"], "market_batch": mb, "base_rate": nxt,
                                           "previous": base_rate, "at_ms": int(self.clock() * 1000)})
            self._settlement_rows(plan, b["lives"], out["tx"])
            self._hash_row(f"resolve stake batch {mb} for {b['batch_id']} ({len(plan['results'])} stakes)", "resolver", out)
            self.log("resolve", batch=b["batch_id"], market_batch=mb, stakes=len(plan["results"]),
                     pot_delta=plan["pot_delta"], tx=out["tx"], tgas=out.get("tgas"))
            return
        r["status"] = "retry"            # read back (resolved, voided or still closed) at the next cycle
        self.log("resolve_retry", batch=b["batch_id"], market_batch=mb, landed=out.get("landed"), tx=out.get("tx"),
                 failure=out.get("failure"))

    def base_rate_at(self, at_ms) -> list:
        """The base rate published by the last resolve that landed before `at_ms` (a lock's time): a level is rewarded
        at the rarity the player saw when it locked. Before the first resolve kept, the base rate it replaced."""
        kept = self.state["resolves"]
        for r in reversed(kept):
            if r.get("at_ms", 0) <= at_ms:
                return list(r["base_rate"])
        return list(kept[0].get("previous") or resolver.quote.PUBLISHED_BASE_BPS) if kept else list(resolver.quote.PUBLISHED_BASE_BPS)

    def _settlement_rows(self, plan, lives, tx):
        """A settlement row in the public record for each life NEAR was drawn for (arena/predict.py)."""
        record = self.record
        if record is None:
            return
        by_life = {l["life_id"]: l for l in lives}
        for d in plan["detail"]:
            if "life_id" in d and int(d.get("draw", "0")) > 0:
                life = by_life.get(d["life_id"], {})
                record.settled(life.get("run", "local"), d["life_id"], life.get("token"), int(d["draw"]), int(d["paid"]), tx)

    def flush_open(self) -> None:
        """Close the open segments as a short batch (a run's last minutes); logged as such."""
        with self.lock:
            self._drain()
            if self.state["open"]:
                self.log("flush_open", segments=len(self.state["open"]), why="run ended before a full batch")
                self._close_batch()
                self._save()

    # ------------------------------------------------------------------ thread
    def run_background(self, every=15.0):
        def loop():
            while not self.stop.is_set():
                self.process()
                self.wake.wait(every)
                self.wake.clear()
        self.thread = threading.Thread(target=loop, name="chain-writer", daemon=True)
        self.thread.start()

    def close(self, flush=True):
        if flush:
            self.process()
        self.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=600)

    def health(self) -> dict:
        """For the arena's /health: chain writes and owner reads, so a stall is visible, never silent."""
        now = time.time_ns()
        oldest = min(self.held.values(), default=None)
        return {"mode": self.sender.label, "failed": self.failed, "unused_seeds": self._unused(),
                "identity_nft": self.cfg.identity_nft,
                "unsettled_batches": len(self.state["batches"]), "open_segments": len(self.state["open"]),
                "owner_reads_waiting": len(self.reads), "lives_held_for_owner_read": len(self.held),
                "oldest_hold_s": None if oldest is None else round((now - oldest) / 1e9, 1)}

    def summary(self) -> dict:
        with self.lock:
            return {"mode": self.sender.label, "prefix": self.state["prefix"], "commits": copy.deepcopy(self.state["commits"]),
                    "batches": [{k: b.get(k) for k in ("batch_id", "status", "fight_hash")} |
                                {"txs": [a["tx"] for a in b["attempts"]],
                                 "resolve": (b["resolve"] or {}).get("status"),
                                 "resolve_tx": (b["resolve"] or {}).get("tx")}
                                for b in self.settled_batches() + self.state["batches"]],
                    "open_segments": len(self.state["open"]), "unused_seeds": self._unused(), "failed": self.failed}
