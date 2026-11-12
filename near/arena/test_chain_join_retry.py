#!/usr/bin/env python3
"""first-join-restart (builder-g's observation, bd:19099): on a chain host the first join could get a signed seat that the
arena never held, and only "Snap in again" seated it.

Cause: on a chain host a token's first life waits for the chain's inventory read, so the arena answers
reserve_life with ownership_unavailable and the guide asks again (room.js, every 2 s). The room takes the slot
before it asks the arena, so the refused join leaves the slot joined; the retry then resumes that session, copies
its empty reservation and signs an accepted grant without asking the arena again. The player sees "In the arena"
while the arena has no member, no life and no row (r2 in builder-g's run). The DEV round restart was not involved.

This case drives the real HTTP room on a snap_local host with the fake-testnet chain writer (near/chain/test_chain):
join, refused with ownership_unavailable; the read lands; join again with a fresh request id. The second join must
seat the fighter in the arena on that try.

  python3 -B near/arena/test_chain_join_retry.py
"""
import asyncio
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "near" / "arena")]

import snap  # noqa: E402
import snap_local  # noqa: E402
from near.chain import test_chain as tc  # noqa: E402  (the fake testnet + identity rig)
from test_snap_local import free_port  # noqa: E402


class ChainJoinRetry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.rig = tc.Rig(str(Path(self.tmp.name) / "chain"), batch_segments=1, commit_size=5, lookahead=2)
        self.rig.writer.start()
        writer = self.rig.writer
        original_arena, original_contexts = snap_local.server.Arena, snap_local.make_contexts

        class ChainArena(original_arena):           # what near/chain/dev_live.py does for a chain host
            def __init__(self, *a, **k):
                k.setdefault("chain", writer)
                super().__init__(*a, **k)

        def contexts(*a, **k):                      # what hosted_live does: player bindings name the identity NFT
            control, result = original_contexts(*a, **k)
            for c in (control, result):
                c["contract_ids"] = dict(c["contract_ids"], nft=tc.IDENT)
            return control, result

        snap_local.server.Arena, snap_local.make_contexts = ChainArena, contexts
        self.addCleanup(setattr, snap_local, "make_contexts", original_contexts)
        self.addCleanup(setattr, snap_local.server, "Arena", original_arena)
        self.port = free_port()
        self.dev = snap_local.DevRoom(self.port, str(Path(self.tmp.name) / "host"))
        ready = threading.Event()
        thread = threading.Thread(target=lambda: asyncio.run(snap_local.serve(self.dev, ready=lambda p: ready.set())), daemon=True)
        thread.start()
        self.assertTrue(ready.wait(60), "host did not start")
        self.addCleanup(lambda: (setattr(self.dev, "stop", True), thread.join(15)))
        self.url = f"http://127.0.0.1:{self.port}"

    def join(self, keeper, n):
        return keeper.client.join(account_id=keeper.ident["account_id"], nft_token_id=keeper.token,
                                  persona_digest=keeper.ident["persona_digest"], session_public_key=keeper.ident["session_public_key"],
                                  request_id=f"retry-join-{n}", declared_compute=dict(harness="external", model="case", source="owner", effort="high"),
                                  prove_wallet=keeper.wallet)

    def test_a_join_asked_again_after_ownership_unavailable_is_seated_in_the_arena(self):
        keeper = snap.Keeper(types.SimpleNamespace(url=self.url, name="pebble", preset="hunter", spread="40,30,20,10", zero=10))
        token = keeper.token
        with self.assertRaises(Exception) as first:
            self.join(keeper, 1)                     # the chain has not read this token's inventory yet
        self.assertEqual((type(first.exception).__name__, str(first.exception)), ("SnapRefusal", "ownership_unavailable"))
        self.assertNotIn(token, self.dev.round.arena.members)
        self.rig.writer.read_owners()                # the read lands (the guide waits 2 s and asks again)
        keeper.client._pending_join = None           # as room.js does: a fresh challenge and request id on each try
        grant = self.join(keeper, 2)
        self.assertEqual(grant.get("state"), "accepted", grant)
        self.assertIn(token, self.dev.round.arena.members,
                      "an accepted join must be a seat the arena holds: the retry was granted without a reserved life")
        self.assertEqual(self.dev.round.arena.members[token]["life_id"], token + ":life:0")


    def test_a_retry_before_the_read_lands_is_refused_again_never_a_seat_without_a_life(self):
        keeper = snap.Keeper(types.SimpleNamespace(url=self.url, name="pebble", preset="hunter", spread="40,30,20,10", zero=10))
        for n in (1, 2):                             # the guide's 2 s retries while the inventory read is still out
            keeper.client._pending_join = None
            with self.assertRaises(Exception) as refused:
                self.join(keeper, n)
            self.assertEqual(str(refused.exception), "ownership_unavailable", f"try {n}")
            self.assertNotIn(keeper.token, self.dev.round.arena.members)
        # (a third try inside the minute would meet the room's 5 join attempts per minute; the first case seats it)


if __name__ == "__main__":
    unittest.main()
