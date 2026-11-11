"""The chain writer against the fake RPC (real signing, sending and read-back) and in dry-run.

    python3 -I -m pytest near/chain/test_chain.py -q
"""

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "near" / "arena")]

import requests  # noqa: E402

import server  # noqa: E402
import snap_local  # noqa: E402
from near.chain import archival, batch as fmt, config as chaincfg, dev_live, fakerpc, model, near_tx, resolver  # noqa: E402
from near.chain import rpc as rpclib, sender as senders  # noqa: E402
from near.chain import writer as wmod  # noqa: E402
from near.chain.writer import ChainWriter  # noqa: E402

ARENA, MARKET, NFT = "arena.t.testnet", "market.t.testnet", "nft.t.testnet"
IDENT = "nft.trenchie-arena.near"          # the identity NFT (mainnet) the owner reads go to
IDENT_RPC = "https://identity.fake.invalid"
SEG = snap_local.RULES["segment_ticks"]


def cfg():
    return chaincfg.ChainConfig("testnet", ARENA, MARKET, NFT, "", "", identity_nft=IDENT,
                                identity_rpc_urls=[IDENT_RPC])


class Rig:
    """A fake testnet: the model behind the fake RPC, real keys, the real RpcSender."""

    def __init__(self, tmp, **kw):
        self.op, self.res = near_tx.Key.generate("op.t.testnet"), near_tx.Key.generate("res.t.testnet")
        self.model = model.Contracts(ARENA, MARKET, NFT, self.op.account_id, self.res.account_id,
                                     tokens={"satrenchi", "vitrenchik"})
        self.rpc = fakerpc.FakeRpc(self.model)
        self.rpc.add_key(self.op)
        self.rpc.add_key(self.res)
        snd = senders.RpcSender(rpclib.Rpc(["https://fake.invalid"], post=self.rpc.post, sleep=lambda s: None),
                                {"operator": self.op, "resolver": self.res})
        # the identity NFT on its own network: a second fake node, read-only, reached only through IDENT_RPC
        self.ident = model.Contracts("arena.unused.near", "market.unused.near", IDENT, "none.near", "none.near",
                                     tokens={"satrenchi", "vitrenchik"})
        self.ident_rpc = fakerpc.FakeRpc(self.ident)
        self.ident_calls, self.ident_down = [], False

        def ident_post(url, json=None, timeout=None):
            self.ident_calls.append((url, json["method"], json["params"]))
            if self.ident_down:
                raise requests.exceptions.ReadTimeout("fake: the identity node timed out")
            return self.ident_rpc.post(url, json=json, timeout=timeout)
        self.identity = cfg().identity_rpc(post=ident_post, sleep=lambda s: None, rounds=1)
        self.log = []
        kw.setdefault("parts", 1)
        self.writer = ChainWriter(snd, cfg(), Path(tmp) / "chain", sleep=lambda s: None, log=self.log.append,
                                  identity=self.identity, **kw)
        self.tmp = tmp

    def arena(self):
        """A bare arena on the writer's seeds (the house-filled DEV room is the dry-run smoke's job)."""
        self.writer.start()
        ctx, _ = snap_local.make_contexts(1, 1)
        self._arena = server.Arena(ctx, [1], data_dir=Path(self.tmp) / "engine", chain=self.writer)
        return self._arena

    def run_segments(self, n):
        for _ in range(n * SEG + 1):
            self._arena.advance()

    def batches(self, writer=None):
        """Every batch, settled ones (moved to batches.jsonl) first; fresh copies of the settled ones."""
        w = writer or self.writer
        return w.settled_batches() + w.state["batches"]

    def posts(self):
        return [t for t in self.rpc.sent if t["actions"][0]["method"] == "post_batch"]


class ChainWriterCases(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="chain-test-")
        self.original = snap_local.server.Arena

    def tearDown(self):
        snap_local.server.Arena = self.original

    def test_arena_runs_on_committed_seeds_and_posts_the_batch(self):
        rig = Rig(self.tmp, batch_segments=2, commit_size=5, lookahead=2)
        arena = rig.arena()
        commit = rig.rpc.sent[0]
        self.assertEqual(commit["actions"][0]["method"], "commit_seeds")
        committed = [fmt.seed_u64(rig.model._seed_hex(0, i)) for i in range(5)]
        self.assertEqual(list(arena.seeds[:5]), committed)          # the given seed [1] was replaced
        rig.run_segments(2)
        rig.writer.process()
        [b] = rig.batches()
        self.assertEqual(b["status"], "applied", rig.log)
        rec = rig.model.batches[b["batch_id"]]
        self.assertEqual((rec["status"], rec["hops"], rec["segments"]), ("Applied", 1, 2))
        self.assertEqual([(s["commit_id"], s["seed_index"]) for s in b["segments"]], [("0", 0), ("0", 1)])
        # the read path: the archival reader recomputes fight_hash from the tx args and matches the log
        report, ok = archival.check(archival.read_batch(rig.posts()[0]["hash"], rig.op.account_id,
                                                        urls=["https://fake.invalid"], post=rig.rpc.post),
                                    state=dict(rig.writer.state, settled=rig.writer.settled_batches()), replay=1)
        self.assertTrue(ok, json.dumps(report["checks"], indent=1))
        self.assertEqual(b["resolve"]["status"], "resolved")
        self.assertEqual(rig.model.open_batch, 1)

    def test_failed_hop_is_retried_with_the_same_id(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        rig.arena()
        rig.model.fail_next_hops = 1
        rig.run_segments(1)
        rig.writer.process()
        [b] = rig.batches()
        self.assertEqual([a["status"] for a in b["attempts"]], ["pending_hop", "applied"])
        posts = rig.posts()
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0]["actions"][0]["args"], posts[1]["actions"][0]["args"])   # same id, same bytes
        self.assertEqual(rig.model.batches[b["batch_id"]]["hops"], 2)

    def test_lost_response_is_read_back_not_posted_twice(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        rig.arena()
        rig.rpc.drop_responses = 1          # the next send executes, but the caller sees a timeout
        rig.run_segments(1)
        rig.writer.process()
        [b] = rig.batches()
        self.assertEqual(b["status"], "applied")
        self.assertEqual(len(rig.posts()), 1)

    def test_a_pending_batch_holds_every_later_batch(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2, attempts=2)
        rig.arena()
        rig.model.fail_next_hops = 10
        rig.run_segments(2)
        rig.writer.process()
        b0, b1 = rig.batches()
        self.assertEqual(b0["status"], "pending_hop")
        self.assertEqual(b1["status"], "queued")
        self.assertEqual({t["actions"][0]["args"]["batch_id"] for t in rig.posts()}, {b0["batch_id"]})
        self.assertTrue(any("HELD" in line for line in rig.log), rig.log)
        rig.model.fail_next_hops = 0
        rig.writer.process()
        self.assertEqual([b["status"] for b in rig.batches()], ["applied", "applied"])

    def test_a_pending_batch_survives_a_restart_and_keeps_its_id(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2, attempts=1)
        rig.arena()
        rig.model.fail_next_hops = 10
        rig.run_segments(1)
        rig.writer.process()
        [b0] = rig.batches()
        self.assertEqual(b0["status"], "pending_hop")
        again = ChainWriter(rig.writer.sender, cfg(), Path(self.tmp) / "chain", sleep=lambda s: None,
                            log=rig.log.append, batch_segments=1, commit_size=5, lookahead=2,
                            identity=rig.identity)   # state from disk
        rig.model.fail_next_hops = 0
        again.process()
        self.assertEqual([b["status"] for b in rig.batches(again)], ["applied"])
        self.assertEqual({t["actions"][0]["args"]["batch_id"] for t in rig.posts()}, {b0["batch_id"]})

    def test_every_closed_stake_gets_a_result_and_a_void_is_reported(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        rig.arena()
        rig.model.stake("stranger.testnet", resolver.PER_LIFE)       # never played: its stake comes back whole
        rig.run_segments(1)
        rig.writer.process()
        b0 = rig.batches()[0]
        self.assertEqual((b0["status"], b0["resolve"]["status"]), ("applied", "resolved"))
        self.assertEqual(b0["resolve"]["plan"]["results"], [{"account_id": "stranger.testnet", "net": "0"}])
        methods = [t["actions"][0]["method"] for t in rig.rpc.sent]
        self.assertLess(methods.index("close_batch"), methods.index("resolve"))
        # the next stake batch times out before its result: the resolver reports the void, then moves on
        rig.model.stake("late.testnet", resolver.PER_LIFE)
        real = rig.model.market_resolve
        rig.model.market_resolve = lambda *a, **k: (_ for _ in ()).throw(model.Panic("fake: resolver down"))
        rig.run_segments(1)
        rig.writer.process()
        b1 = rig.batches()[1]
        self.assertEqual(b1["resolve"]["status"], "retry")
        rig.model.void(b1["resolve"]["market_batch"])
        rig.model.market_resolve = real
        rig.writer.process()
        self.assertEqual(rig.batches()[1]["resolve"]["status"], "voided")
        self.assertTrue(any("RESOLVE_VOIDED" in line for line in rig.log), rig.log)

    def test_an_abandoned_batch_carries_its_rows_into_the_next(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2, attempts=2)
        rig.arena()
        rig.model.fail_next_hops = 10
        rig.run_segments(1)
        rig.writer.process()
        b0 = rig.batches()[0]
        self.assertEqual(b0["status"], "pending_hop")
        b0["rows"] = [{"token_id": "satrenchi", "bag": [], "record": {"lives": 0, "kos": 0, "skill": 0}, "sale_ready": None}]
        rig.model.batches[b0["batch_id"]]["rows_digest"] = b0["rows_digest"] = fmt.rows_digest(b0["rows"])
        rig.model.abandon_pending(b0["batch_id"])                  # Pat's key gives up on it
        rig.model.fail_next_hops = 0
        rig.run_segments(1)
        rig.writer.process()
        b1 = rig.batches()[1]
        self.assertEqual((b0["status"], b1["status"]), ("abandoned", "applied"), rig.log)
        self.assertIn("satrenchi", [r["token_id"] for r in b1["rows"]])

    def test_a_rate_limited_node_is_retried_next_cycle_not_fatal(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        rig.arena()
        rig.run_segments(1)
        transport = rig.writer.sender.rpc
        real = transport.post
        transport.post = lambda url, json=None, timeout=None: fakerpc._Response({}, status=429)
        rig.writer.process()                                   # every endpoint answers 429
        self.assertIsNone(rig.writer.failed)
        self.assertTrue(any("rpc_retry" in line for line in rig.log), rig.log)
        transport.post = real
        rig.writer.process()
        self.assertEqual([b["status"] for b in rig.batches()], ["applied"])

    # ------------------------------------------------------------------ RPC fallthrough (rate limits)
    def two_nodes(self, rig, first):
        """The rig's chain behind two endpoints: `first(method, json)` may answer for node A (else it passes through)."""
        posts, sleeps = [], []

        def post(url, json=None, timeout=None):
            posts.append((url, json["method"], json["params"]))
            if url == "https://a.invalid":
                got = first(json["method"], json)
                if got is not None:
                    return got
            return rig.rpc.post(url, json=json, timeout=timeout)
        r = rpclib.Rpc(["https://a.invalid", "https://b.invalid"], post=post, sleep=sleeps.append)
        return r, posts, sleeps

    def test_fastnear_is_in_the_default_send_and_read_lists(self):
        self.assertEqual(rpclib.TESTNET_RPC, ["https://rpc.testnet.near.org", "https://rpc.testnet.fastnear.com"])
        r = chaincfg.ChainConfig("testnet", ARENA, MARKET, NFT, "", "").rpc()
        self.assertIn("https://rpc.testnet.fastnear.com", r.urls)          # sends fall through to it
        self.assertIn("https://rpc.testnet.fastnear.com", r.read_urls)
        self.assertIn("https://rpc.testnet.fastnear.com", chaincfg.identity_rpc_default("id.r.testnet"))

    def test_a_rate_limit_error_body_backs_off_and_falls_through(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        limited = lambda method, json: fakerpc._Response(
            {"jsonrpc": "2.0", "id": json["id"], "error": {"code": -429, "message": "deprecated", "data": "use another RPC"}})
        r, posts, sleeps = self.two_nodes(rig, limited)
        self.assertIsNotNone(r.view(ARENA, "state"))                      # answered by node B
        self.assertEqual([u for u, m, _ in posts], ["https://a.invalid", "https://a.invalid", "https://b.invalid"])
        self.assertEqual(len(sleeps), 2)                                   # backed off before each retry and the move
        self.assertTrue(rpclib.rate_limited({"name": "HANDLER_ERROR", "cause": {"name": "TOO_MANY_REQUESTS"}}))
        self.assertTrue(rpclib.rate_limited({"code": -32000, "message": "Rate limit exceeded"}))
        self.assertFalse(rpclib.rate_limited({"name": "HANDLER_ERROR", "cause": {"name": "UNKNOWN_TRANSACTION"}}))
        panic = {"name": "HANDLER_ERROR", "message": "Server error", "cause": {"name": "INVALID_TRANSACTION"},
                 "data": {"ActionError": "Smart contract panicked: rate limit reached for this key"}}
        self.assertFalse(rpclib.rate_limited(panic))                       # text in data is the contract's, not the node's
        with self.assertRaises(rpclib.RpcError):                          # a real error still raises at once
            rpclib.Rpc(["https://b.invalid"], post=rig.rpc.post, sleep=lambda s: None).tx("nohash", "op.t.testnet")

    def test_a_rate_limited_send_rebroadcasts_the_same_signed_tx(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        limited = lambda method, json: fakerpc._Response(
            {"jsonrpc": "2.0", "id": json["id"], "error": {"code": -429, "message": "deprecated"}}) if method == "send_tx" else None
        r, posts, _ = self.two_nodes(rig, limited)
        rig.writer.sender.rpc = r
        rig.arena()
        rig.run_segments(1)
        rig.writer.process()
        sends = [(u, p["signed_tx_base64"]) for u, m, p in posts if m == "send_tx"]
        by_tx = {}
        for u, b64 in sends:
            by_tx.setdefault(b64, []).append(u)
        for b64, urls in by_tx.items():
            self.assertEqual(urls, ["https://a.invalid", "https://a.invalid", "https://b.invalid"])   # the same bytes
        hashes = [t["hash"] for t in rig.rpc.sent]
        self.assertEqual(len(hashes), len(set(hashes)))                   # each signed tx executed once
        self.assertEqual(len(hashes), len(by_tx))
        self.assertEqual([b["status"] for b in rig.batches()], ["applied"])

    def test_a_send_that_timed_out_is_never_sent_again_and_settles_by_hash(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        r, posts, _ = self.two_nodes(rig, lambda method, json: None)
        rig.writer.sender.rpc = r
        rig.arena()
        rig.run_segments(1)
        rig.rpc.drop_responses = 1                     # node A executes the next send, and the reply is lost
        rig.writer.process()
        sends = [(u, p["signed_tx_base64"]) for u, m, p in posts if m == "send_tx"]
        lost = sends[0][1]
        self.assertEqual([u for u, b in sends if b == lost], ["https://a.invalid"])   # never to node B, never re-signed
        self.assertTrue(any(m == "EXPERIMENTAL_tx_status" for _, m, _ in posts))       # settled by hash
        hashes = [t["hash"] for t in rig.rpc.sent]
        self.assertEqual(len(hashes), len(set(hashes)))
        self.assertEqual([b["status"] for b in rig.batches()], ["applied"])
        self.assertEqual(len([t for t in rig.rpc.sent if t["actions"][0]["method"] == "post_batch"]), 1)

    def test_a_batch_over_the_gas_a_tx_carries_is_held_not_sent(self):
        from near.chain import writer as wmod
        self.assertLess(wmod.estimate_tgas(60, 107), wmod.SAFE_TGAS + 30)
        self.assertGreater(wmod.estimate_tgas(60, 150), 300 - 40)         # the measured 60 seg + 150 rewrites ran out
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        rig.arena()
        rig.writer.state["tallies"]["satrenchi"] = {"lives": 1, "kos": 0, "skill_sum": 0, "skill_n": 0}
        rig.writer.state["carry"] = ["satrenchi"]
        rig.run_segments(1)
        safe = wmod.SAFE_TGAS
        wmod.SAFE_TGAS = wmod.estimate_tgas(1, 1) - 1        # this one batch is just over the line
        try:
            rig.writer.process()
        finally:
            wmod.SAFE_TGAS = safe
        [b] = rig.batches()
        self.assertEqual(b["status"], "held")
        self.assertIn("Pat's G0 pick", b["held"])
        self.assertEqual(rig.posts(), [])

    def test_option_c_posts_a_period_in_three_ordered_parts(self):
        rig = Rig(self.tmp, batch_segments=3, parts=3, max_rows=1, commit_size=5, lookahead=2)
        rig.arena()
        for token in ("satrenchi", "vitrenchik", "zz-extra"):
            rig.writer.state["tallies"][token] = {"lives": 1, "kos": 0, "skill_sum": 0, "skill_n": 0}
        rig.writer.state["carry"] = ["satrenchi", "vitrenchik", "zz-extra"]
        rig.run_segments(3)
        rig.writer.process()
        parts = rig.batches()
        self.assertEqual([(b["part"], len(b["segments"]), len(b["rows"]), b["status"]) for b in parts],
                         [(1, 1, 1, "applied"), (2, 1, 1, "applied"), (3, 1, 1, "applied")])
        self.assertEqual([t["actions"][0]["args"]["batch_id"] for t in rig.posts()], [b["batch_id"] for b in parts])
        self.assertEqual([rig.model.batches[b["batch_id"]]["seq"] for b in parts], ["1", "2", "3"])
        self.assertEqual([(b["resolve"] or {}).get("status") for b in parts], ["part", "part", "resolved"])
        self.assertEqual(sum(1 for t in rig.rpc.sent if t["actions"][0]["method"] == "resolve"), 1)

    def test_option_a_carries_the_rows_over_the_cap_to_the_next_hour(self):
        rig = Rig(self.tmp, batch_segments=1, parts=1, max_rows=1, commit_size=5, lookahead=2)
        rig.arena()
        for token in ("satrenchi", "vitrenchik"):
            rig.writer.state["tallies"][token] = {"lives": 1, "kos": 0, "skill_sum": 0, "skill_n": 0}
        rig.writer.state["carry"] = ["satrenchi", "vitrenchik"]
        rig.run_segments(2)
        rig.writer.process()
        b0, b1 = rig.batches()
        self.assertEqual(([r["token_id"] for r in b0["rows"]], [r["token_id"] for r in b1["rows"]]),
                         (["satrenchi"], ["vitrenchik"]))
        self.assertEqual((b0["status"], b1["status"]), ("applied", "applied"))

    def test_a_token_sold_mid_play_fights_no_new_life_under_its_old_owner(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        arena = rig.arena()
        w = rig.writer
        b = {"nft_token_id": "satrenchi", "account_id": "seller.near"}
        rig.ident.owners["satrenchi"] = "seller.near"
        self.assertTrue(arena.life_guard is not None)
        self.assertFalse(w.owner_ok(b))                                  # first life: held for its first read
        w.read_owners()
        self.assertTrue(w.owner_ok(b))                                   # the identity NFT names the binding: admitted
        w.life_ended("satrenchi")                                        # KO; meanwhile it sold on mainnet
        rig.ident.owners["satrenchi"] = "buyer.near"
        self.assertFalse(w.owner_ok(b))                                  # no read since the life ended: refused, queued
        w.read_owners()
        self.assertFalse(w.owner_ok(b))                                  # the read shows the buyer: refused
        w.process()
        self.assertTrue(any("OWNER_CHANGED" in line for line in rig.log), rig.log)
        self.assertTrue(w.owner_ok({"nft_token_id": "satrenchi", "account_id": "buyer.near"}))

    def test_the_arena_asks_the_writer_before_each_life(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        ctx, _ = snap_local.make_contexts(1, 1)
        rig.writer.start()
        asked = []
        rig.writer.owner_ok = lambda binding: asked.append(binding) or False
        a = server.Arena(ctx, [1], data_dir=Path(self.tmp) / "engine2", chain=rig.writer, life_guard=lambda b: True)
        self.assertFalse(a.life_guard({"nft_token_id": "x", "account_id": "y.testnet"}))
        self.assertEqual(asked, [{"nft_token_id": "x", "account_id": "y.testnet"}])

    def test_the_read_path_says_so_when_no_batch_is_pinned(self):
        pinned = archival.SETTLED
        archival.SETTLED = Path(self.tmp) / "missing-settled.json"
        err = io.StringIO()
        real, sys.stderr = sys.stderr, err
        try:
            self.assertEqual(archival.main([]), 2)
        finally:
            sys.stderr, archival.SETTLED = real, pinned
        self.assertIn("no pinned batches", err.getvalue())
        self.assertTrue(pinned.exists(), "near/chain/settled.json pins the batches make verify-batches reads")

    def test_one_segment_is_one_batch_row_even_if_sealed_twice(self):
        rig = Rig(self.tmp, batch_segments=5, commit_size=5, lookahead=2)
        arena = rig.arena()
        rig.run_segments(1)                                  # the arena sealed segment 0 twice (end of tick + boundary)
        rig.writer.process()
        self.assertEqual(len(rig.writer.state["open"]), 1)
        record = json.loads((arena.store.segments / "segment-0.json").read_bytes())
        changed = json.loads(json.dumps(record))
        changed["sealed"]["sealed_result_hash"] = "0" * 64   # a second seal of the same index with other content
        arena.segment_index, real = 0, arena.segment_index
        rig.writer.sealed(arena, "segment:0", changed)
        arena.segment_index = real
        rig.writer.process()
        self.assertEqual(len(rig.writer.state["open"]), 1)  # never a second row for one segment
        self.assertIn("next unbound seed", rig.writer.failed)  # it stops, loudly

    def test_state_stays_bounded_over_many_periods(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=4, lookahead=2)
        rig.arena()
        path = Path(self.tmp) / "chain" / "state.json"
        sizes = []
        for _ in range(9):
            rig.run_segments(1)
            rig.writer.process()
            sizes.append(path.stat().st_size)
        self.assertEqual(len(rig.writer.settled_batches()), 9)              # every settled batch kept, append-only
        self.assertEqual(rig.writer.state["batches"], [])                  # none of them in state.json
        self.assertLessEqual(len(rig.writer.state["pool"]), 4 + 2)         # used seeds trimmed
        self.assertLess(max(sizes[3:]) - min(sizes[3:]), 400, sizes)       # flat, not growing per period
        rig.writer.state["actuals"] = list(range(5000))
        rig.writer._compact()
        self.assertEqual(len(rig.writer.state["actuals"]), wmod.ACTUALS_WINDOW)

    def test_a_chain_arena_refuses_to_recover_a_journal_clearly(self):
        rig = Rig(self.tmp, batch_segments=3, commit_size=10, lookahead=2)
        rig.arena()
        rig.run_segments(1)
        ctx, _ = snap_local.make_contexts(1, 1)
        with self.assertRaisesRegex(ValueError, "does not recover a journal: start a fresh arena"):
            server.Arena(ctx, [1], data_dir=Path(self.tmp) / "engine", chain=rig.writer, recover=True)
        fresh = server.Arena(ctx, [1], data_dir=Path(self.tmp) / "engine-2", chain=rig.writer)   # the boot path
        self.assertEqual(fresh.seeds[0], rig.writer._pool_at(rig.writer.bound)[2])

    def test_dev_tokens_respawn_without_reads_and_holds_show_in_health(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        rig.arena()
        w = rig.writer
        dev = {"nft_token_id": "satrenchi", "account_id": "house.dev.local",
               "context": {"contract_ids": {"nft": "dev-nft.local"}}}
        mine = {"nft_token_id": "vitrenchik", "account_id": "p.testnet", "context": {"contract_ids": {"nft": NFT}}}
        w.life_ended("satrenchi")
        w.life_ended("vitrenchik")
        w.reads.clear()
        self.assertTrue(w.owner_ok(dev))           # an RPC outage holds no DEV or house id: nothing onchain to read
        self.assertFalse(w.owner_ok(mine))
        h = w.health()
        self.assertEqual((h["lives_held_for_owner_read"], h["owner_reads_waiting"]), (1, 1))
        self.assertIsNotNone(h["oldest_hold_s"])
        self.assertIn("chain", rig._arena.health())

    def test_an_owner_read_counts_from_when_it_was_sent(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        rig.arena()
        w = rig.writer
        b = {"nft_token_id": "satrenchi", "account_id": "custody.t.testnet"}
        w.reads.append("satrenchi")
        real = w.identity.view

        ended = []

        def slow_view(receiver, method, args=None):
            if method == "nft_token" and not ended:
                ended.append(1)
                w.life_ended("satrenchi")          # the life ends while the first read is in flight
                w.reads.clear()                    # (its own re-read is what the next line must not need)
            return real(receiver, method, args)
        w.identity.view = slow_view
        w.read_owners()
        w.identity.view = real
        self.assertFalse(w.owner_ok(b))            # a read sent before the end does not admit the next life

    def test_the_stake_batch_closes_before_the_period_posts(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        rig.arena()
        rig.run_segments(1)
        rig.writer.process()
        methods = [t["actions"][0]["method"] for t in rig.rpc.sent]
        self.assertLess(methods.index("close_batch"), methods.index("post_batch"))
        self.assertEqual(rig.batches()[0]["status"], "applied")

    def test_an_older_layout_batch_fails_with_a_reason(self):
        read = {"tx": "T", "rpc": "https://archival.example", "signer": "op.t.testnet", "receiver": ARENA,
                "method": "post_batch", "outcome": {"events": [], "logs": []},
                "args": {"batch_id": "old", "rows": [], "segments": [
                    {"segment_id": "s0", "seed_hash": "0" * 64, "inputs_hash": "0" * 64, "rules_hash": "0" * 64,
                     "final_state_hash": "0" * 64, "predictions_log_hash": "0" * 64, "kos": 1}]}}
        report, ok = archival.check(read)
        self.assertFalse(ok)
        self.assertIn("older segment layout", " ".join(c["detail"] for c in report["checks"]))

    def test_the_live_hosts_dev_health_carries_the_chain_field(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        rig.writer.start()
        dev_live.attach(rig.writer)
        h = snap_local.DevRoom(0, str(Path(self.tmp) / "dev")).health()
        for key in ("lives_held_for_owner_read", "owner_reads_waiting", "oldest_hold_s"):
            self.assertIn(key, h["chain"])

    def test_dry_run_prints_every_call_and_sends_nothing(self):
        out = io.StringIO()
        ids = {"operator": "op.dry-run.testnet", "resolver": "res.dry-run.testnet"}
        m = model.Contracts(ARENA, MARKET, NFT, ids["operator"], ids["resolver"])
        w = ChainWriter(senders.DryRun(m, ids, out=out), cfg(), Path(self.tmp) / "chain", sleep=lambda s: None,
                        log=lambda line: None, commit_size=5, lookahead=2,
                        identity=model.Contracts(ARENA, MARKET, IDENT, ids["operator"], ids["resolver"]))
        real_post = requests.post
        requests.post = lambda *a, **k: (_ for _ in ()).throw(AssertionError("dry-run touched the network"))
        try:
            w.start()
        finally:
            requests.post = real_post
        line = out.getvalue().strip().splitlines()[0]
        self.assertTrue(line.startswith("DRY-RUN would send (not onchain): "))
        call = json.loads(line.split(": ", 1)[1])
        self.assertEqual((call["method"], call["receiver"], call["args"]["count"]), ("commit_seeds", ARENA, 5))
        self.assertTrue(call["dry_run"].startswith("DRY-RUN-"))
        self.assertFalse((Path(self.tmp) / "chain" / "hashes.tsv").exists())

    def test_resolver_conserves_and_never_covers_an_earlier_life(self):
        spread = (0, 1000, 4000, 3000, 2000)
        cent = resolver.PER_LIFE
        lives = [{"account": "a.testnet", "life_id": "a:1", "kos": 2, "bins": spread, "locked_after_ns": 200},
                 {"account": "b.testnet", "life_id": "b:1", "kos": 0, "bins": spread, "locked_after_ns": 200},
                 {"account": "c.testnet", "life_id": "c:1", "kos": 3, "bins": spread, "locked_after_ns": 50},
                 # d staked 0.01, played d:1 (covered), then d:2 (no stake left), then topped up after d:2's
                 # result was public: the top-up must not reach d:2.
                 {"account": "d.testnet", "life_id": "d:1", "kos": 0, "bins": spread, "locked_after_ns": 200},
                 {"account": "d.testnet", "life_id": "d:2", "kos": 4, "bins": spread, "locked_after_ns": 300}]
        stakes = {"a.testnet": cent, "b.testnet": cent, "c.testnet": cent, "d.testnet": 2 * cent}
        sk = resolver.SKEW_NS
        parts = {a: [{"amount": str(cent), "at": str(100)}] for a in ("a.testnet", "b.testnet")}
        parts["c.testnet"] = [{"amount": str(cent), "at": str(100 + sk)}]          # landed after c:1 began
        parts["d.testnet"] = [{"amount": str(cent), "at": str(100)},                # the first lock
                              {"amount": str(cent), "at": str(350 + sk)}]           # the top-up, after d:2 began
        for life in lives:
            life["locked_after_ns"] += sk
        plan = resolver.compute(stakes, lives, 0, resolver.quote.PUBLISHED_BASE_BPS, parts=parts)
        net = {r["account_id"]: int(r["net"]) for r in plan["results"]}
        self.assertEqual(net["b.testnet"], -cent)                  # a 0-KO life loses its draw
        self.assertEqual(net["c.testnet"], 0)                      # its only life began before the stake locked
        self.assertEqual(net["d.testnet"], -cent)                  # d:1 lost; the top-up never reached d:2
        self.assertGreater(net["a.testnet"], 0)                    # the pot is recycled to the 1+ KO life
        self.assertEqual(sum(net.values()) + int(plan["pot_delta"]), 0)
        draws = {d["life_id"]: int(d["draw"]) for d in plan["detail"] if "life_id" in d}
        self.assertTrue(all(v <= cent for v in draws.values()))    # no life draws more than the per-life stake

    # ------------------------------------------------------------------ owners on the identity NFT (mainnet)
    def test_owner_reads_go_to_the_identity_nft_nft_token_at_final(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        rig.arena()
        w = rig.writer
        rig.ident.owners["vitrenchik"] = "p.near"
        b = {"nft_token_id": "vitrenchik", "account_id": "p.near", "context": {"contract_ids": {"nft": IDENT}}}
        self.assertFalse(w.owner_ok(b))
        sent_before = len(rig.rpc.sent)
        w.read_owners()
        self.assertTrue(w.owner_ok(b))
        [(url, method, params)] = rig.ident_calls
        self.assertEqual((url, method), (IDENT_RPC, "query"))
        self.assertEqual({k: params[k] for k in ("request_type", "finality", "account_id", "method_name")},
                         {"request_type": "call_function", "finality": "final", "account_id": IDENT,
                          "method_name": "nft_token"})
        self.assertEqual(json.loads(__import__("base64").b64decode(params["args_base64"])), {"token_id": "vitrenchik"})
        self.assertEqual(len(rig.rpc.sent), sent_before)                 # a read signs and sends nothing

    def test_a_missing_or_burned_identity_token_is_refused_and_logged(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        rig.arena()
        w = rig.writer
        b = {"nft_token_id": "never-minted", "account_id": "p.near", "context": {"contract_ids": {"nft": IDENT}}}
        w.owner_ok(b)
        w.read_owners()
        self.assertFalse(w.owner_ok(b))                                  # nft_token answered null
        rig.ident.tokens.discard("satrenchi")                            # burned
        s = {"nft_token_id": "satrenchi", "account_id": "custody.t.testnet"}
        w.owner_ok(s)
        w.read_owners()
        self.assertFalse(w.owner_ok(s))
        w.process()
        missing = [line for line in rig.log if "OWNER_MISSING" in line]
        self.assertEqual(len(missing), 2, rig.log)

    def test_an_identity_rpc_error_or_timeout_holds_the_life(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        rig.arena()
        w = rig.writer
        rig.ident.owners["satrenchi"] = "p.near"
        b = {"nft_token_id": "satrenchi", "account_id": "p.near"}
        rig.ident_down = True
        self.assertFalse(w.owner_ok(b))                                  # a first life too: no read, no life
        w.read_owners()
        self.assertFalse(w.owner_ok(b))
        w.process()
        self.assertTrue(any("owner_read_retry" in line and "ReadTimeout" in line for line in rig.log), rig.log)
        h = w.health()
        self.assertEqual((h["lives_held_for_owner_read"], h["owner_reads_waiting"]), (1, 1))
        rig.ident_down = False
        w.read_owners()
        self.assertTrue(w.owner_ok(b))                                   # the node is back: the read admits it

    def test_the_testnet_inventory_owner_is_never_consulted(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        rig.arena()
        w = rig.writer
        rig.model.owners["satrenchi"] = "p.near"                         # the testnet shadow says the binding owns it
        rig.ident.owners["satrenchi"] = "other.near"                     # the identity NFT says otherwise
        testnet_views = []
        real = rig.model.view
        rig.model.view = lambda receiver, method, args: testnet_views.append((receiver, method)) or real(receiver, method, args)
        b = {"nft_token_id": "satrenchi", "account_id": "p.near", "context": {"contract_ids": {"nft": NFT}}}
        w.owner_ok(b)
        w.read_owners()
        self.assertFalse(w.owner_ok(b))                                  # a binding naming the inventory NFT is read on the identity NFT
        rig.ident_down = True
        w.life_ended("satrenchi")
        w.owner_ok(b)
        w.read_owners()
        self.assertFalse(w.owner_ok(b))                                  # the identity node down: still no testnet read
        self.assertEqual([v for v in testnet_views if v[1] in ("trenchie", "nft_token")], [])
        with self.assertRaisesRegex(ValueError, "never read from the testnet inventory"):
            ChainWriter(w.sender, chaincfg.ChainConfig("testnet", ARENA, MARKET, NFT, "", ""), Path(self.tmp) / "c2")

    def test_a_refusal_is_read_again_once_its_read_is_old(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        rig.arena()
        w = rig.writer
        rig.ident.owners["satrenchi"] = "seller.near"
        b = {"nft_token_id": "satrenchi", "account_id": "buyer.near"}
        w.owner_ok(b)
        w.read_owners()
        self.assertFalse(w.owner_ok(b))                                  # read before the sale: refused
        self.assertEqual(list(w.reads), [])                              # a fresh read is not re-queued at once
        rig.ident.owners["satrenchi"] = "buyer.near"                     # the sale lands on mainnet
        w.owners["satrenchi"]["read_ns"] -= wmod.REREAD_REFUSED_NS + 1   # 30 s later
        self.assertFalse(w.owner_ok(b))
        self.assertEqual(list(w.reads), ["satrenchi"])
        w.read_owners()
        self.assertTrue(w.owner_ok(b))

    def test_a_sale_after_the_post_ko_read_is_caught_at_the_next_activation(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        rig.arena()
        w = rig.writer
        rig.ident.owners["satrenchi"] = "seller.near"
        seller = {"nft_token_id": "satrenchi", "account_id": "seller.near"}
        buyer = {"nft_token_id": "satrenchi", "account_id": "buyer.near"}
        w.owner_ok(seller); w.read_owners()
        self.assertTrue(w.owner_ok(seller))                              # life 1
        w.life_ended("satrenchi"); w.read_owners()                       # the KO queues a read: it shows the seller
        rig.ident.owners["satrenchi"] = "buyer.near"                     # the sale lands after that read
        getattr(w, "asking", {}).clear()                                 # (the next activation comes later)
        self.assertFalse(w.owner_ok(seller))                             # the post-KO read is older than this ask
        w.read_owners()
        self.assertFalse(w.owner_ok(seller))                             # the fresh read shows the buyer
        w.reads.append("satrenchi"); w.read_owners()                    # a re-read (the 30 s rule) shows the same buyer
        self.assertFalse(w.owner_ok(seller))                             # refused again, not logged again
        w.process()
        self.assertEqual(sum("OWNER_CHANGED" in line for line in rig.log), 1, rig.log)
        self.assertTrue(w.owner_ok(buyer))                               # that same fresh read admits the buyer
        w.life_ended("satrenchi"); w.read_owners(); getattr(w, "asking", {}).clear()
        self.assertFalse(w.owner_ok(buyer))                              # and each later life waits one read again
        w.read_owners()
        self.assertTrue(w.owner_ok(buyer))

    # ------------------------------------------------------------------ records continue from the chain
    def filed(self, rig, token):
        rows = [r for b in rig.batches() for r in b["rows"] if r["token_id"] == token]
        return rows[-1]["record"] if rows else None

    def test_a_fresh_writer_continues_a_tokens_record_from_the_chain(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)    # an empty state.json: a fresh host
        rig.model.__dict__.setdefault("records", {})["satrenchi"] = {"lives": 7, "kos": 3, "skill": 140}
        rig.arena()
        rig.writer.state["tallies"]["satrenchi"] = {"lives": 2, "kos": 1, "skill_sum": 0, "skill_n": 0}   # this run's
        rig.writer.state["carry"] = ["satrenchi"]
        rig.run_segments(1); rig.writer.process()
        self.assertEqual(self.filed(rig, "satrenchi"), {"lives": 9, "kos": 4, "skill": 140},
                         "the filed record continues from the chain's 7/3/140, never from zero")
        self.assertEqual(rig.batches()[0]["status"], "applied")
        rig.writer.state["tallies"]["satrenchi"]["lives"] += 1              # one more life next period
        rig.writer.state["carry"] = ["satrenchi"]
        rig.run_segments(1); rig.writer.process()
        self.assertEqual(self.filed(rig, "satrenchi")["lives"], 10, "seeded once: the chain record is not added twice")

    def test_a_failed_chain_read_holds_only_that_token(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        rig.arena()
        for t in ("satrenchi", "vitrenchik"):
            rig.writer.state["tallies"][t] = {"lives": 2, "kos": 1, "skill_sum": 0, "skill_n": 0}
        rig.writer.state["carry"] = ["satrenchi", "vitrenchik"]
        real = rig.model.view
        def down(receiver, method, args):
            if method == "trenchie" and args.get("token_id") == "satrenchi":
                raise model.Panic("fake: the inventory view failed")
            return real(receiver, method, args)
        rig.model.view = down
        rig.run_segments(1); rig.writer.process()
        rows = [r["token_id"] for b in rig.batches() for r in b["rows"]]
        self.assertEqual(rows, ["vitrenchik"], "the token whose read failed is not filed; the other one is")
        self.assertIsNone(rig.writer.failed)
        self.assertTrue(any("RECORD_SEED_FAILED" in line and "satrenchi" in line for line in rig.log), rig.log)
        rig.model.view = real
        rig.run_segments(1); rig.writer.process()
        self.assertEqual(self.filed(rig, "satrenchi")["lives"], 2, "it files once its read works, from its tallies")

    def entry(self, row, serial):
        return {"row": row, "serial": serial, "born_batch": 1, "kos": 0, "hands": 1, "flags": 0}

    def test_a_fresh_state_keeps_every_chain_row_and_continues_the_record(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        items = snap_local.RULES["items"]
        rows = sorted(items)                                                 # today's registry (the guard case pins it)
        starter = next(i for i, n in enumerate(rows) if items[n]["default"])
        beam, leg = rows.index("r-beam"), rows.index("leg-builder-census")
        m = rig.model.__dict__
        m.setdefault("bags", {})["satrenchi"] = [self.entry(starter, 4242), self.entry(beam, 7)]
        m.setdefault("records", {})["satrenchi"] = {"lives": 7, "kos": 3, "skill": 140}
        m["bags"]["vitrenchik"] = [self.entry(beam, 9)]                       # a token no arena here loads
        rig.arena()
        w = rig.writer
        self.assertIsNone(w.inventory_bag("satrenchi", items)); w.read_owners()
        self.assertEqual(list(w.inventory_bag("satrenchi", items)), ["r-beam"], "the starter row cannot be carried")
        w.process()                                                       # the load is noted: the starter row is kept
        # the fighter's life: it kept r-beam and grabbed a legendary; vitrenchik's arena bag holds only that legendary
        w.state["bags"]["satrenchi"] = fmt.bag_entries({"r-beam": {"serial": 7, "born_batch": 1, "kos": 0, "hands": 1, "flags": 0},
                                                        "leg-builder-census": {"serial": 11, "born_batch": 2, "kos": 1, "hands": 1, "flags": 0}},
                                                       {n: rows.index(n) for n in items})
        w.state["bags"]["vitrenchik"] = [self.entry(leg, 12)]
        for t in ("satrenchi", "vitrenchik"):
            w.state["tallies"][t] = {"lives": 2, "kos": 1, "skill_sum": 0, "skill_n": 0}
        w.state["carry"] = ["satrenchi", "vitrenchik"]
        rig.run_segments(1); w.process()
        self.assertEqual(sorted((e["row"], e["serial"]) for e in rig.model.bags["satrenchi"]),
                         sorted([(starter, 4242), (beam, 7), (leg, 11)]), "nothing the arena did not move is lost")
        self.assertEqual(sorted((e["row"], e["serial"]) for e in rig.model.bags["vitrenchik"]),
                         [(beam, 9)], "a token never loaded here: its moves are unknown, so the chain's bag stands")
        self.assertTrue(any("bag_rows_not_filed" in line and "vitrenchik" in line for line in rig.log), rig.log)
        self.assertEqual(rig.model.records["satrenchi"], {"lives": 9, "kos": 4, "skill": 140}, "and its record continues")

    def test_a_fighter_that_left_before_the_seal_files_its_saved_bag(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        arena = rig.arena()
        bag = {"r-beam": {"serial": 7, "born_batch": 1, "kos": 0, "hands": 1, "flags": 0}}
        arena.inventories["satrenchi"] = {"owner": "p.near", "bag": bag, "life_number": 1}
        real = arena.store.put_segment

        def with_life(name, rec):         # the sealed record names satrenchi, as if it fought and left before the seal
            rec["sealed"]["nft_token_ids"] = sorted(set(rec["sealed"]["nft_token_ids"]) | {"satrenchi"})
            return real(name, rec)
        arena.store.put_segment = with_life
        rig.run_segments(1)
        rig.writer.process()
        self.assertEqual(rig.writer.state["bags"].get("satrenchi"),
                         fmt.bag_entries(bag, {n: i for i, n in enumerate(sorted(snap_local.RULES["items"]))}),
                         "the bag the arena saved at the leave is filed, not an empty one")

    def test_a_rules_change_neither_repoints_nor_loses_stored_gear(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        rows = sorted(snap_local.RULES["items"])                             # today's registry (the guard case pins it)
        beam = rows.index("r-beam")
        items = dict(snap_local.RULES["items"])
        retired = "c-beam"                                                   # an item the new table drops
        items.pop(retired)
        items["aa-new-hat"] = dict(snap_local.RULES["items"]["r-beam"])      # sorts first: a sorted table shifts every row
        rig.writer.item_rows = rows + ["aa-new-hat"]                         # the registry only appends
        rig.model.__dict__.setdefault("bags", {})["satrenchi"] = [self.entry(beam, 7), self.entry(rows.index(retired), 5)]
        w = rig.writer
        w.inventory_bag("satrenchi", items); w.read_owners()
        self.assertEqual(w.inventory_bag("satrenchi", items), {"r-beam": {"serial": 7, "born_batch": 1, "kos": 0, "hands": 1, "flags": 0}},
                         "row %d still names r-beam under the new table" % beam)
        w.process()
        base = w.state["bases"]["satrenchi"]
        self.assertIn(rows.index(retired), [e["row"] for e in base["bag"]], "the retired item stays in the chain base")
        self.assertNotIn(rows.index(retired), [e["row"] for e in base["arena"]], "and the arena never carried it, so it is never moved")
        with self.assertRaisesRegex(ValueError, "append them"):
            fmt.row_index(items, rows)                                       # a table the registry lacks stops the writer

    def loaded(self, rig, chain):
        """Tokens whose first life here loaded their chain bag (the bag base)."""
        rig.model.__dict__.setdefault("bags", {}).update(chain)
        items, w = snap_local.RULES["items"], rig.writer
        for t in chain:
            w.inventory_bag(t, items)
        w.read_owners()
        for t in chain:
            w.inventory_bag(t, items)
        w.process()

    def test_an_item_lost_in_a_fight_stays_with_its_new_holder(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        items = snap_local.RULES["items"]
        rows = sorted(items)                                                 # today's registry
        starter = next(i for i, n in enumerate(rows) if items[n]["default"])
        beam = rows.index("r-beam")
        rig.arena()
        self.loaded(rig, {"satrenchi": [self.entry(beam, 7), self.entry(starter, 4242)], "vitrenchik": []})
        w = rig.writer
        w.state["bags"]["satrenchi"] = []                                   # it lost r-beam in a fight...
        w.state["bags"]["vitrenchik"] = [self.entry(beam, 7)]               # ...and vitrenchik grabbed it
        for t in ("satrenchi", "vitrenchik"):
            w.state["tallies"][t] = {"lives": 1, "kos": 0, "skill_sum": 0, "skill_n": 0}
        w.state["carry"] = ["satrenchi", "vitrenchik"]
        rig.run_segments(1); w.process()
        self.assertEqual([(e["row"], e["serial"]) for e in rig.model.bags["satrenchi"]], [(starter, 4242)],
                         "r-beam is not filed back to the token that lost it; the starter row it never moved stays")
        self.assertEqual([(e["row"], e["serial"]) for e in rig.model.bags["vitrenchik"]], [(beam, 7)], "one copy, with its new holder")

    def test_a_chain_row_another_host_filed_is_kept(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        rows = sorted(snap_local.RULES["items"])
        beam, leg = rows.index("r-beam"), rows.index("leg-builder-census")
        rig.arena()
        self.loaded(rig, {"satrenchi": [self.entry(beam, 7)]})               # this arena's base: r-beam
        w = rig.writer
        w.state["bags"]["satrenchi"] = [self.entry(beam, 7)]                # this arena moved nothing
        rig.model.bags["satrenchi"] = [self.entry(beam, 7), self.entry(leg, 5)]   # another host filed a legendary since
        w.state["tallies"]["satrenchi"] = {"lives": 1, "kos": 0, "skill_sum": 0, "skill_n": 0}
        w.state["carry"] = ["satrenchi"]
        rig.run_segments(1); w.process()
        self.assertEqual(sorted((e["row"], e["serial"]) for e in rig.model.bags["satrenchi"]), sorted([(beam, 7), (leg, 5)]),
                         "a chain row this arena never held is kept: the arena files only its own moves")
        self.assertTrue(any("chain_bag_moved" in line for line in rig.log), rig.log)
        # the next life from this arena's saved bag (r-beam only) starts from the chain's bag plus its own moves
        newer = w.saved_bag_update("satrenchi", {"r-beam": {"serial": 7, "born_batch": 1, "kos": 0, "hands": 1, "flags": 0}},
                                   snap_local.RULES["items"])
        self.assertEqual(sorted(newer), ["leg-builder-census", "r-beam"], "the saved bag older than the chain reloads first")
        self.assertIsNone(w.saved_bag_update("satrenchi", newer, snap_local.RULES["items"]), "a current saved bag is left alone")

    def test_a_row_carried_over_the_cap_keeps_the_arenas_moves(self):
        rig = Rig(self.tmp, batch_segments=1, parts=1, max_rows=1, commit_size=5, lookahead=2)
        rig.arena()
        self.loaded(rig, {"satrenchi": [self.entry(5, 1)], "vitrenchik": [self.entry(5, 1)]})   # both loaded row 5
        w = rig.writer
        for t in ("satrenchi", "vitrenchik"):
            w.state["tallies"][t] = {"lives": 1, "kos": 0, "skill_sum": 0, "skill_n": 0}
            w.state["bags"][t] = [self.entry(5, 1), self.entry(7, 2)]       # then the arena gained row 7
        w.state["carry"] = ["satrenchi", "vitrenchik"]
        rig.run_segments(2); w.process()                                    # one row a period: vitrenchik is carried
        filed = {r["token_id"]: [(e["row"], e["serial"]) for e in r["bag"]] for b in rig.batches() for r in b["rows"]}
        self.assertEqual(filed, {"satrenchi": [(5, 1), (7, 2)], "vitrenchik": [(5, 1), (7, 2)]},
                         "a carried row still carries the arena's gain: a base moves only when its batch applies")
        self.assertEqual(sorted((e["row"], e["serial"]) for e in rig.model.bags["vitrenchik"]), [(5, 1), (7, 2)])

    def test_an_abandoned_row_keeps_the_arenas_moves_and_refiles_them(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2, attempts=2)
        rig.arena()
        self.loaded(rig, {"satrenchi": [self.entry(5, 1)]})                # the chain and the arena hold row 5
        w = rig.writer
        w.state["tallies"]["satrenchi"] = {"lives": 1, "kos": 0, "skill_sum": 0, "skill_n": 0}
        w.state["bags"]["satrenchi"] = [self.entry(5, 1), self.entry(7, 2)]   # the arena gained row 7
        w.state["carry"] = ["satrenchi"]
        rig.model.fail_next_hops = 10
        rig.run_segments(1); w.process()
        b0 = rig.batches()[0]
        self.assertEqual(b0["status"], "pending_hop")
        self.assertEqual([(e["row"], e["serial"]) for e in w.state["bases"]["satrenchi"]["bag"]], [(5, 1)],
                         "a batch that has not applied leaves the base where it was")
        rig.model.abandon_pending(b0["batch_id"])                          # the owner gives the batch up
        rig.model.fail_next_hops = 0
        rig.run_segments(1); w.process()
        b1 = rig.batches()[1]
        self.assertEqual((b0["status"], b1["status"]), ("abandoned", "applied"), rig.log)
        row = next(r for r in b1["rows"] if r["token_id"] == "satrenchi")
        self.assertEqual([(e["row"], e["serial"]) for e in row["bag"]], [(5, 1), (7, 2)], "the rebuild refiles the arena's move")
        self.assertEqual(sorted((e["row"], e["serial"]) for e in rig.model.bags["satrenchi"]), [(5, 1), (7, 2)])
        self.assertEqual([(e["row"], e["serial"]) for e in w.state["bases"]["satrenchi"]["bag"]], [(5, 1), (7, 2)],
                         "and the base moves once that batch has applied")

    def test_the_writer_refuses_to_start_on_a_registry_rules_mismatch(self):
        rows = fmt.item_rows()
        bad = Path(self.tmp) / "rows.json"
        swapped = list(rows); swapped[3], swapped[4] = swapped[4], swapped[3]
        bad.write_text(json.dumps({"rows": swapped}))
        real = fmt.ITEM_ROWS
        fmt.ITEM_ROWS = bad
        try:
            with self.assertRaisesRegex(wmod.WriterError, "does not match the released rules tables"):
                Rig(self.tmp + "/w", batch_segments=1, commit_size=5, lookahead=2)
        finally:
            fmt.ITEM_ROWS = real

    def test_the_registry_guard_takes_appends_anywhere_and_refuses_reorders(self):
        rows, tables = fmt.item_rows(), fmt.released_tables()
        self.assertEqual(len(tables), len(list((ROOT / "near/arena/rules").glob("integer-*.json"))))
        self.assertEqual(fmt.check_registry(rows, tables), [], "every released table, in release order")
        nxt = dict(tables[-1][1], **{"c-beam-aaa": tables[-1][1]["c-beam"]})   # a new item that sorts mid-table
        self.assertEqual(fmt.check_registry(rows + ["c-beam-aaa"], tables + [("integer-99.json", nxt)]), [],
                         "a mid-table item appended at the end passes")
        self.assertNotEqual(fmt.check_registry(rows, tables + [("integer-99.json", nxt)]), [], "a table item the registry lacks fails")
        swapped = list(rows); swapped[3], swapped[4] = swapped[4], swapped[3]
        self.assertNotEqual(fmt.check_registry(swapped, tables), [], "a reorder fails")
        self.assertNotEqual(fmt.check_registry(rows[:5] + ["c-beam-aaa"] + rows[5:], tables), [], "an insert before the end fails")
        self.assertNotEqual(fmt.check_registry(rows[1:], tables), [], "a removal fails")
        self.assertNotEqual(fmt.check_registry(rows + [rows[0]], tables), [], "a reused row fails")

    def test_only_other_contracts_skip_the_owner_read(self):
        rig = Rig(self.tmp, batch_segments=1, commit_size=5, lookahead=2)
        rig.arena()
        w = rig.writer
        dev = {"nft_token_id": "dev-x", "account_id": "house.dev.local", "context": {"contract_ids": {"nft": "dev-nft.local"}}}
        self.assertTrue(w.owner_ok(dev))                                 # the DEV room's ids: nothing onchain to read
        for nft in (IDENT, NFT, None):
            ctx = {} if nft is None else {"context": {"contract_ids": {"nft": nft}}}
            self.assertFalse(w.owner_ok(dict({"nft_token_id": "satrenchi", "account_id": "p.near"}, **ctx)), nft)
        self.assertEqual(list(w.reads), ["satrenchi"])
        self.assertEqual(rig.ident_calls, [])

    def test_the_env_names_the_identity_nft_and_its_own_read_list(self):
        env = Path(self.tmp) / "c.env"
        base = ("TRENCHIE_NETWORK=testnet\nTRENCHIE_ARENA_ID=arena.r.testnet\nTRENCHIE_MARKET_ID=market.r.testnet\n"
                "TRENCHIE_NFT_ID=nft.r.testnet\nTRENCHIE_OPERATOR_KEY_FILE=/x\nTRENCHIE_RESOLVER_KEY_FILE=/y\n")
        env.write_text(base)
        os.chmod(env, 0o600)
        with self.assertRaisesRegex(chaincfg.ConfigError, "TRENCHIE_IDENTITY_NFT_ID"):
            chaincfg.ChainConfig.from_env_file(env)
        env.write_text(base + "TRENCHIE_IDENTITY_NFT_ID=nft.r.testnet\n")
        with self.assertRaisesRegex(chaincfg.ConfigError, "never from the inventory"):
            chaincfg.ChainConfig.from_env_file(env)
        env.write_text(base + "TRENCHIE_IDENTITY_NFT_ID=nft.trenchie-arena.near\n")
        c = chaincfg.ChainConfig.from_env_file(env)
        self.assertEqual((c.identity_nft, c.identity_rpc_urls), ("nft.trenchie-arena.near", ["https://rpc.mainnet.near.org"]))
        self.assertEqual((c.identity_rpc().urls, c.identity_rpc().read_urls), (c.identity_rpc_urls, c.identity_rpc_urls))
        env.write_text(base + "TRENCHIE_IDENTITY_NFT_ID=id.r.testnet\nTRENCHIE_IDENTITY_RPC=https://a.example, https://b.example\n")
        c = chaincfg.ChainConfig.from_env_file(env)
        self.assertEqual(c.identity_rpc_urls, ["https://a.example", "https://b.example"])
        self.assertEqual(chaincfg.identity_rpc_default("id.r.testnet"), rpclib.TESTNET_RPC)

    def test_env_and_key_files_stay_outside_the_repo_and_private(self):
        inside = ROOT / "near" / "chain" / "_test.env"
        with self.assertRaises(chaincfg.ConfigError):
            chaincfg.read_env(inside)
        env = Path(self.tmp) / "c.env"
        env.write_text("TRENCHIE_OPERATOR_KEY_FILE=/x\n")
        os.chmod(env, 0o644)
        with self.assertRaises(chaincfg.ConfigError):
            chaincfg.read_env(env)
        os.chmod(env, 0o600)
        env.write_text("TRENCHIE_OPERATOR_KEY=ed25519:" + "1" * 80 + "\n")
        with self.assertRaises(chaincfg.ConfigError):
            chaincfg.read_env(env)


if __name__ == "__main__":
    unittest.main()
