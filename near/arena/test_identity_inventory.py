#!/usr/bin/env python3
"""A sale moves the gear (Pat, 2026-11-11): after a token is sold on the identity NFT, its new owner can reserve
the next life and carries the bag the arena saved for it; the chain writer's owner read decides at activation.

  python3 -B near/arena/test_identity_inventory.py
"""
import sys, tempfile, types, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "near" / "arena")]

import server  # noqa: E402
import snap_local  # noqa: E402
from near.chain import test_chain as tc  # noqa: E402  (the fake testnet + identity rig)


class SaleMovesTheGear(unittest.TestCase):
    def arena(self, nft, saved=True):
        self.rig = tc.Rig(tempfile.mkdtemp(prefix="id-inv-"), batch_segments=1, commit_size=5, lookahead=2)
        self.rig.writer.start()
        ctx, _ = snap_local.make_contexts(1, 1)
        ctx["contract_ids"]["nft"] = nft
        preset = snap_local.battle_preset("brawler-swing", snap_local.RULES)
        profile = lambda b: {"house": False, "public_name": "Pebble", "model": "dev", "style": preset["style"],
                             "loadout": dict(preset["loadout"]), "bag": {}}
        room = types.SimpleNamespace(life_boundary=lambda grant_id: None)
        a = server.Arena(ctx, [1], data_dir=Path(self.rig.tmp) / "engine", chain=self.rig.writer, profile_provider=profile,
                         admission_gate=lambda: True, life_guard=lambda b: True, room_factory=lambda bridge: room,
                         identity_resolver=lambda request: {}, receipt_signer=lambda body: "sig")
        if saved:
            a.inventories["satrenchi"] = {"owner": "seller.near", "bag": {"r-beam": {"serial": 7, "born_batch": 1, "kos": 2, "hands": 1, "flags": 0}}, "life_number": 2}
        return a

    def binding(self, a, account):
        return {"context": dict(a.context), "grant_id": "g:" + account, "session_key_id": "k:" + account, "member_id": "satrenchi",
                "nft_token_id": "satrenchi", "persona_digest": "a" * 64, "account_id": account, "slot_id": "satrenchi", "generation": "1"}

    def test_the_buyer_reserves_the_next_life_and_carries_the_saved_bag(self):
        a = self.arena(tc.IDENT)
        r = a.bridge.reserve_life(self.binding(a, "buyer.near"))
        self.assertIn("life_id", r, r)
        self.assertEqual(r["life_id"], "satrenchi:life:3", "the life count follows the token")
        self.assertEqual(a.members["satrenchi"]["profile"]["bag"], {"r-beam": {"serial": 7, "born_batch": 1, "kos": 2, "hands": 1, "flags": 0}}, "the gear moved with the sale")

    def test_the_owner_read_still_decides_who_plays(self):
        a = self.arena(tc.IDENT)
        self.rig.ident.owners["satrenchi"] = "buyer.near"
        b = self.binding(a, "seller.near")
        life = a.bridge.reserve_life(b)
        lock = a.bridge.lock_prediction(b, life["life_id"], None)
        self.rig.writer.read_owners()
        self.assertEqual(a.bridge.activate(b, life["life_id"], lock["lock_ref"])["code"], "ownership_unavailable",
                         "the seller reserves, but the identity NFT names the buyer: no life")

    def test_a_fresh_arena_loads_the_tokens_gear_from_the_inventory(self):
        a = self.arena(tc.IDENT, saved=False)
        items = sorted(a.sim.rules["items"])
        row = items.index("r-beam")
        self.rig.model.__dict__.setdefault("bags", {})["satrenchi"] = [{"row": row, "serial": 4242, "born_batch": 3, "kos": 1, "hands": 2, "flags": 0}]
        b = self.binding(a, "buyer.near")
        self.assertEqual(a.bridge.reserve_life(b)["code"], "ownership_unavailable", "its inventory read is not in yet: ask again")
        self.rig.writer.read_owners()
        r = a.bridge.reserve_life(b)
        self.assertIn("life_id", r, r)
        self.assertEqual(a.members["satrenchi"]["profile"]["bag"], {"r-beam": {"serial": 4242, "born_batch": 3, "kos": 1, "hands": 2, "flags": 0}},
                         "whoever owns the token now fights with the gear the chain holds under it")

    def test_inventory_rows_the_sim_cannot_carry_are_dropped_not_fatal(self):
        a = self.arena(tc.IDENT, saved=False)
        items = sorted(a.sim.rules["items"])
        starter = next(i for i, n in enumerate(items) if a.sim.rules["items"][n]["default"])
        self.rig.model.__dict__.setdefault("bags", {})["satrenchi"] = [
            {"row": starter, "serial": 1, "born_batch": 1, "kos": 0, "hands": 0, "flags": 0},
            {"row": items.index("r-beam"), "serial": 2, "born_batch": 1, "kos": 0, "hands": 0, "flags": 0},
            {"row": len(items) + 5, "serial": 3, "born_batch": 1, "kos": 0, "hands": 0, "flags": 0}]
        b = self.binding(a, "buyer.near")
        a.bridge.reserve_life(b); self.rig.writer.read_owners()
        self.assertIn("life_id", a.bridge.reserve_life(b))
        self.assertEqual(list(a.members["satrenchi"]["profile"]["bag"]), ["r-beam"], "the starter and out-of-table rows are dropped")
        prof = a.members["satrenchi"]["profile"]
        a.sim._check_kit(prof["loadout"], prof["bag"], False)            # the join's own check passes: no crash
        self.rig.writer.process()
        self.assertTrue(any("inventory_rows_kept" in line for line in self.rig.log), self.rig.log)

    def test_a_saved_bag_older_than_the_chain_reloads_before_the_next_life(self):
        a = self.arena(tc.IDENT)                                             # saved: r-beam serial 7 (from this arena's base)
        rows = sorted(a.sim.rules["items"])
        beam = {"row": rows.index("r-beam"), "serial": 7, "born_batch": 1, "kos": 2, "hands": 1, "flags": 0}
        leg = {"row": rows.index("leg-builder-census"), "serial": 5, "born_batch": 3, "kos": 0, "hands": 1, "flags": 0}
        # the base: chain and arena both held r-beam; since then another host filed a legendary under this token
        self.rig.writer.bag_bases["satrenchi"] = ([beam, leg], [beam])
        a.bridge.reserve_life(self.binding(a, "buyer.near"))
        self.assertEqual(sorted(a.members["satrenchi"]["profile"]["bag"]), ["leg-builder-census", "r-beam"],
                         "the next life starts from the chain's bag plus this arena's own moves, not the stale saved bag")

    def test_the_arenas_own_saved_bag_comes_before_the_chains(self):
        a = self.arena(tc.IDENT)
        self.rig.model.__dict__.setdefault("bags", {})["satrenchi"] = [{"row": 0, "serial": 1, "born_batch": 1, "kos": 0, "hands": 0, "flags": 0}]
        self.rig.writer.read_owners()
        a.bridge.reserve_life(self.binding(a, "buyer.near"))
        self.assertEqual(list(a.members["satrenchi"]["profile"]["bag"]), ["r-beam"], "unsettled gear in this arena is newer than the chain's")

    def test_an_arena_without_the_identity_read_keeps_the_old_rule(self):
        a = self.arena("dev-nft.local")
        self.assertEqual(a.bridge.reserve_life(self.binding(a, "buyer.near"))["code"], "ownership_unavailable")


if __name__ == "__main__":
    unittest.main()
