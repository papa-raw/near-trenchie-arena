"""A production host never seats a `dev-` identity; only a DEV host does. An ordinary id is admitted."""

from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
import server
import test_server as ts


def binding(name, **change):
    b = ts.binding(name)
    b.update(change)
    return b


class Production(unittest.TestCase):
    def arena(self, names=None, **kwargs):
        comp = ts.Composition()
        comp.setUp()
        self.addCleanup(comp.doCleanups)
        arena = comp.arena(**kwargs)
        if names is not None:
            inner = arena.profile_provider
            arena.profile_provider = lambda b: dict(inner(b), public_name=names.get(b["nft_token_id"], b["nft_token_id"]))
        return arena

    def test_dev_as_a_player_id_a_name_and_a_session_name_is_refused_and_an_ordinary_id_is_admitted(self):
        arena = self.arena({"visitor": "dev-visitor", "Plain": "Plain Jane"})
        for label, b in (("player id", binding("dev-x")),
                         ("member id", binding("ok1", member_id="dev-x")),
                         ("slot id", binding("ok2", slot_id="dev-x")),
                         ("session key", binding("ok3", session_key_id="DEV-session")),
                         ("grant id", binding("ok4", grant_id="Dev-grant")),
                         ("persona name", binding("visitor"))):
            with self.subTest(label):
                reply = arena.bridge.reserve_life(b)
                self.assertEqual(reply.get("code"), "banned", reply)
                self.assertNotIn(b["nft_token_id"], arena.members)
        self.assertEqual(len(arena.refusals), 6)
        self.assertEqual({r["reason"] for r in arena.refusals}, {"dev_prefix"})
        self.assertEqual(arena.health()["dev_prefix_refusals"], 6)
        self.assertNotIn("dev-x", str(list(arena.refusals)) + str(arena.health()))       # fields only, never values
        self.assertIn("life_id", arena.bridge.reserve_life(binding("Plain")))
        for ordinary in ("devon", "device-9", "dev", "adev-1", "avichad"):
            self.assertIn("life_id", arena.bridge.reserve_life(binding(ordinary)), ordinary)

    def test_case_unicode_dashes_width_and_hidden_characters_do_not_get_round_it(self):
        arena = self.arena()
        for sneaky in ("DEV-x", "Dev-x", "ＤＥＶ－ｘ", "dev‑x", "dev–x", "dev−x", "d​ev-x",
                       "‭dev-x", "  dev-x", "dev­x".replace("­", "-"), "d⁠e‍v-x"):
            with self.subTest(repr(sneaky)):
                self.assertTrue(server.dev_prefixed(sneaky))
                self.assertEqual(arena.bridge.reserve_life(binding("p", nft_token_id=sneaky)).get("code"), "banned")
        for ordinary in ("device", "devon-1", "dev x", "xdev-1", "de-v", ""):
            self.assertFalse(server.dev_prefixed(ordinary), ordinary)

    def test_a_dev_host_seats_dev_ids_by_flag_or_by_its_deployment_id(self):
        flagged = self.arena(dev_host=True)
        self.assertIn("life_id", flagged.bridge.reserve_life(binding("dev-x")))
        self.assertTrue(flagged.health()["dev_host"])
        by_deployment = ts.Composition()
        by_deployment.setUp()
        self.addCleanup(by_deployment.doCleanups)
        context = ts.context()
        context["deployment_id"] = "dev-local"
        self.assertTrue(server.Arena(context, [1, 2, 3], data_dir=by_deployment.tmp.name + "/d").dev_host)
        self.assertFalse(server.Arena(ts.context(), [1, 2, 3], data_dir=by_deployment.tmp.name + "/p").dev_host)
        explicit_off = server.Arena(context, [1, 2, 3], data_dir=by_deployment.tmp.name + "/o", dev_host=False)
        self.assertFalse(explicit_off.dev_host)


if __name__ == "__main__":
    unittest.main()
