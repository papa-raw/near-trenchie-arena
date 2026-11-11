"""The live house composed on a real Arena with a scripted model: all 14 sheets, the shared guarded feed,
the predictions log hashed at each seal, the public roster with no private field, the budget stop's keyed lines."""

import json
from concurrent.futures import Future
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "arena"))
import feed as feed_mod
import guard
import live
import predictions
import runtime
import sheets as sheets_mod
import sim
import test_server as ts

FAKE = {"names": ["Fakeo Realperson"], "handles": ["@fakehandle"], "slurs": ["fakeslur"]}   # fake names in a fake store


class Sync:
    def submit(self, fn, *a):
        f = Future()
        try:
            f.set_result(fn(*a))
        except Exception as exc:
            f.set_exception(exc)
        return f


class Scripted:
    """A stand-in for the model: valid intents and spreads, a fresh banter line per call, one blocked line."""
    model = runtime.MODEL

    def __init__(self):
        self.n = 0

    def chat(self, messages, thinking=False, max_tokens=200):
        self.n += 1
        assert messages[0]["role"] == "system" and "house trenchie in Trenchie Village" in messages[0]["content"]
        text = messages[-1]["content"]
        if "Pick for your next life" in text:
            body = json.dumps({"loadout": {"weapon": "not-an-item"}, "spread_pct": [40, 30, 20, 10], "zero_pct": 35})
        elif "Write the behaviour you want now" in text:          # battle mode: a behaviour (schema v1) and a line
            body = json.dumps({"behaviour": {"v": 1, "stance": "berserk"}, "say": "Plan %d: swing first, ask never." % self.n})
        elif "Trash-talk about it" in text:
            body = json.dumps({"say": "Tide line %d writes word%d word%db" % (self.n, self.n, self.n)})
        elif "JSON object" in text:
            body = json.dumps({"loot": "nearest", "sig": "auto", "focus": None, "avoid": None})
        elif self.n == 7:
            body = "Fakeo Realperson owes me a coin"            # must become an emote
        else:
            body = "Tide line %d writes word%d word%db word%dc" % (self.n, self.n, self.n, self.n)
        return {"text": body, "usage": {"prompt_tokens": 750, "completion_tokens": 42, "cached_tokens": 600}}


def compose(tmp, clock, guard_list=FAKE, mode="building", meter=None):
    comp = ts.Composition("test_sixteen_admitted_six_ring_and_fifo_bench")
    comp.tmp = tempfile.TemporaryDirectory()
    names = sheets_mod.load()
    feed = feed_mod.PublicFeed(guard.Guard(guard_list, sheets_mod.guard_names(names)))
    budget = runtime.Budget(meter or runtime.JsonMeter(Path(tmp) / "house/spend.json"), mode, clock=lambda: clock[0])
    house = live.LiveHouse(ts.context(), tmp, feed, account_id="house.test", client=Scripted(),
                           clock=lambda: clock[0], executor=Sync(), budget=budget)
    arena = comp.arena(house_runtime=house, pick_resolver=house.pick_resolver, prediction_log=house.log)
    house.attach(arena)
    return comp, arena, house, feed


def run(arena, clock, ticks):
    for _ in range(ticks):
        arena.advance(1)
        clock[0] = round(clock[0] + 0.05, 2)


class LiveHouse(unittest.TestCase):
    def test_fourteen_sheets_fight_post_through_the_guard_and_log_hashed_lives(self):
        with tempfile.TemporaryDirectory() as d:
            clock = [20_000 * 86400]
            comp, arena, house, feed = compose(d, clock)
            self.assertEqual(sorted(house.sheets), sorted(sim.DEFAULT_RULES["house"]))
            run(arena, clock, 2600)                       # past two segment seals
            sent = [c["value"] for c in arena.commands if c["kind"] == "input" and c["value"]["kind"] == "intent"]
            self.assertTrue(sent, "the model's intents reached the sim as logged inputs")
            self.assertGreaterEqual(sum(m["profile"]["house"] for m in arena.members.values()), sim.DEFAULT_RULES["house_min"])
            self.assertTrue(house.log.locks, "the model's pick locked a prediction")
            self.assertTrue(all(e["body"]["prediction"] for e in house.log.locks.values()))
            # every house line went through the one feed: guarded, at most one per 30 s per trenchie
            rows = feed.since(0)
            self.assertTrue(rows)
            self.assertTrue(all(r["source"] == "house" for r in rows))
            self.assertFalse(any("Fakeo" in r["text"] for r in rows), "a blocked line never reaches the feed")
            self.assertEqual(feed.counts["blocked"], 1)
            self.assertEqual(feed.counts["refused"], 0, "no model call is spent on a line the feed's cap would refuse")
            for who in {r["who"] for r in rows}:
                ticks = [r["tick"] for r in rows if r["who"] == who]
                self.assertTrue(all(b - a >= feed_mod.RATE_TICKS for a, b in zip(ticks, ticks[1:])), (who, ticks))
            # the production path journals PredictionLog.log_hash() at each seal
            self.assertEqual(sorted(arena.prediction_log_hashes), ["segment:0", "segment:1"])
            journalled = [r["value"] for r in arena.store.records() if r["kind"] == "house_predictions"]
            self.assertEqual([j["segment_id"] for j in journalled], ["segment:0", "segment:1"])
            # the log is append-only, so each sealed hash is the hash of the file as it stood at that seal: a line prefix
            lines = house.log.path.read_bytes().splitlines(keepends=True)
            prefixes = {__import__("hashlib").sha256(b"".join(lines[:k])).hexdigest(): k for k in range(len(lines) + 1)}
            self.assertTrue(all(j["log_hash"] in prefixes for j in journalled), journalled)
            self.assertGreater(prefixes[journalled[-1]["log_hash"]], 0, "lives were resolved into the log before the seal")
            self.assertEqual(arena.prediction_log_hashes["segment:1"], journalled[-1]["log_hash"])
            # the private status and the public roster
            status_doc = json.loads((Path(d) / "house/status.json").read_text())
            self.assertTrue(status_doc["members"])
            public = house.public_roster()
            self.assertEqual(public["admitted"], sum(not m["released"] for m in arena.members.values()))
            self.assertEqual(public["house_model"], live.MODEL_LABEL)
            self.assertNotIn("/", live.MODEL_LABEL)          # the room protocol's Label refuses "/"
            self.assertGreater(public["house_spend_today_microusd"], 0)
            blob = json.dumps(public)
            for private in ("calls_per_min", "PRIVATE-CANARY", "prompt", "life\"", "cap\""):
                self.assertNotIn(private, blob)
            self.assertNotIn("NEARAI", blob + json.dumps(house.log.rows()))
            self.assertEqual(house.runtime.notes, [], house.runtime.notes)
            comp.tmp.cleanup()

    def test_player_ai_lives_go_in_the_same_public_log(self):
        """F79 for every AI: a player's signed spread and a player's explicit no-prediction are logged by the arena itself."""
        with tempfile.TemporaryDirectory() as d:
            clock = [20_000 * 86400]
            comp, arena, house, feed = compose(d, clock)
            house_pick = arena.pick_resolver
            arena.pick_resolver = lambda b, p: (house_pick(b, p) if b["account_id"] == "house.test"
                                                else dict(sim.DEFAULT_RULES["default_loadout"]))
            pick = {"payload": {"loadout": {"menu_row": None, "bag_serials": []}, "moves": [], "lock": False, "stake": None,
                                "spread_bps": {"one": 4000, "two": 3000, "three": 2000, "four_plus": 1000}, "zero_bps": 1000}}
            players = {"p1": pick, "p2": None}
            for name, chosen in players.items():
                b = ts.binding(name)
                life = arena.bridge.reserve_life(b)
                lock = arena.bridge.lock_prediction(b, life["life_id"], chosen)
                self.assertIn("lock_ref", lock, lock)
                arena.bridge.activate(b, life["life_id"], lock["lock_ref"])
            run(arena, clock, 200)
            for name in players:
                arena.bridge.release(ts.binding(name))
            run(arena, clock, 1100)                        # the leaves land and the segment seals
            rows = {r["persona"]: r for r in house.log.rows() if r["persona"] in players}
            self.assertEqual(sorted(rows), ["p1", "p2"])
            self.assertEqual((rows["p1"]["prediction"], rows["p1"]["spread_pct"], rows["p1"]["zero_pct"]), (True, [40, 30, 20, 10], 10))
            self.assertEqual((rows["p2"]["prediction"], rows["p2"]["spread_pct"], rows["p2"]["score"]), (False, None, None))
            self.assertEqual(rows["p1"]["owner"], "p1.test")
            self.assertTrue(all(set(r) == set(predictions.FIELDS) for r in house.log.rows()))
            self.assertNotIn("PRIVATE-CANARY", house.log.path.read_text())
            self.assertEqual(list(arena.prediction_log_refusals), [])
            self.assertIn("segment:0", arena.prediction_log_hashes)
            comp.tmp.cleanup()

    def test_budget_stop_shows_the_chip_and_posts_only_labelled_keyed_lines(self):
        with tempfile.TemporaryDirectory() as d:
            clock = [20_000 * 86400]
            meter = runtime.JsonMeter(Path(d) / "house/spend.json")
            meter.add(20_000, 2 * runtime.USD)            # the day's building cap already spent
            comp, arena, house, feed = compose(d, clock, meter=meter)
            run(arena, clock, 2600)
            self.assertEqual(house.public_roster()["chip"], "autopilot")
            self.assertEqual(house.client.n, 0, "no model call after the cap")
            self.assertTrue(all(r["label"] == "autopilot" for r in feed.since(0)))
            self.assertTrue(arena.sim._live(), "the house fights on its tick policy")
            comp.tmp.cleanup()

    def test_every_call_failing_shows_the_autopilot_chip(self):
        """No silent fallback: when every model call fails, the public chip says so, not only a note."""
        class Down(Scripted):
            def chat(self, messages, thinking=False, max_tokens=200):
                raise RuntimeError("NEAR AI Cloud unreachable")

        with tempfile.TemporaryDirectory() as d:
            clock = [20_000 * 86400]
            comp, arena, house, feed = compose(d, clock)
            house.client = house.runtime.client = Down()
            run(arena, clock, 600)
            public = house.public_roster()
            self.assertEqual(public["chip"], "autopilot (model calls failing)")
            self.assertTrue(any("call failed" in n for n in public["notes"]))
            self.assertTrue(arena.sim._live(), "the house fights on its tick policy")
            house.runtime.client = Scripted()                  # the model comes back: the chip clears
            run(arena, clock, 300)
            self.assertIsNone(house.public_roster()["chip"])
            comp.tmp.cleanup()

    def test_live_house_refuses_to_start_without_the_key(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(__import__("os").environ)
            __import__("os").environ.pop(live.KEY_ENV, None)
            try:
                with self.assertRaises(live.KeyMissing):
                    live.LiveHouse(ts.context(), d, None, account_id="house.test")
            finally:
                __import__("os").environ.update(env)


class DevHost(unittest.TestCase):
    """The snap_local hook: --house live composes on the real room service (whose snapshot schema refuses a "/" in a
    model label), the default stays deterministic with no key, and the /house routes carry no private field."""

    def test_live_switch_on_the_dev_host_and_its_public_routes(self):
        import os
        import snap_local
        with tempfile.TemporaryDirectory() as d:
            saved = os.environ.pop(live.KEY_ENV, None)
            try:
                plain = snap_local.DevRoom(0, d + "/dev")                # the default: no key, no model
                self.assertIsInstance(plain.round.house, snap_local.DevHouse)
                with self.assertRaises(live.KeyMissing):
                    snap_local.DevRoom(0, d + "/nokey", house="live")
            finally:
                if saved is not None:
                    os.environ[live.KEY_ENV] = saved
            host = snap_local.DevRoom(0, d + "/live", house="live", house_client=Scripted())
            self.assertIsInstance(host.round.house, live.LiveHouse)
            for _ in range(1300):                                     # past the first seal, on the real room service
                host.round.arena.advance()
            self.assertFalse(host.round.arena.failed)
            self.assertEqual(host.round_index, 1, "the arena never stopped and restarted")
            self.assertIn("segment:0", host.round.arena.prediction_log_hashes)
            status_code, roster = host.route("GET", "/house/roster", b"", "local")
            self.assertEqual(status_code, 200)
            self.assertEqual(roster["admitted"], len([m for m in host.round.arena.members.values() if not m["released"]]))
            self.assertEqual(roster["house_model"], live.MODEL_LABEL)
            _, fed = host.route("GET", "/house/feed?since=0", b"", "local")
            self.assertEqual(fed["guard"], "missing" if not os.environ.get("TRENCHIE_BLOCKLIST") else "loaded")
            _, (body, log_hash) = host.route("GET", "/house/predictions.jsonl", b"", "local")
            self.assertEqual(log_hash, host.house_log.log_hash())
            self.assertEqual(__import__("hashlib").sha256(body).hexdigest(), log_hash)
            for route in ("/house/roster", "/house/feed", "/dev/players", "/health"):
                blob = json.dumps(host.route("GET", route, b"", "local")[1])
                for private in ("calls_per_min", "spend.json", "status.json", "prefix", "Rules for every answer"):
                    self.assertNotIn(private, blob, (route, private))


class MeterCall(unittest.TestCase):
    """A meter whose add() takes no per-trenchie argument still meters every call (the B78 fakes)."""

    def test_three_argument_meter_and_the_unguarded_list_feed(self):
        class ThreeArg:
            def __init__(self):
                self.adds = []

            def today(self, day):
                return 0

            def total(self):
                return 0

            def add(self, day, microusd, usage=None):
                self.adds.append(microusd)

        meter = ThreeArg()
        runtime.Budget(meter, "building", clock=lambda: 0).charge({"prompt_tokens": 750, "completion_tokens": 42}, 0, who="satrenchi")
        self.assertEqual(meter.adds, [runtime.cost_microusd({"prompt_tokens": 750, "completion_tokens": 42})])
        # An unguarded runtime over a plain list feed would publish unchecked lines, so it is refused
        class ListDriver:
            feed = []
        with self.assertRaises(ValueError):
            runtime.Runtime(Scripted(), runtime.Budget(meter, "building"), None, {}, ListDriver(), lambda: 0, executor=Sync())


class RoundRestart(unittest.TestCase):
    """The DEV host's one feed outlives a round, whose tick restarts at 0. In the new round the house and a
    player both post, B55's 30 s still holds across the restart, and no line ever goes back in time."""

    def test_house_and_player_post_in_the_next_round_within_b55(self):
        from unittest import mock
        import snap_local
        clock = [20_000 * 86400.0]
        with tempfile.TemporaryDirectory() as d, mock.patch("time.time", lambda: clock[0]):
            # battle mode on (integer-13), in a full period so lines flow; the host's own clock guard is what is tested
            host = snap_local.DevRoom(0, d, house="live", house_client=Scripted(), budget_mode="judging")
            self.assertTrue(host.round.house.battle, "the DEV host runs the house in battle mode")

            def run(ticks):
                for _ in range(ticks):
                    host.round.arena.advance()
                    clock[0] = round(clock[0] + 0.05, 2)

            run(1300)
            first = host.feed.since(0)
            self.assertTrue(first, "round 1 posted house lines")
            host.maybe_restart("test: a new round")             # the host's own restart path, offset and all
            self.assertEqual(host.round_index, 2)
            run(1300)
            second = [r for r in host.feed.since(first[-1]["id"])]
            self.assertTrue(second, "round 2's house lines are accepted, not held back by round 1's clock")
            self.assertGreater(second[0]["tick"], first[-1]["tick"], "the feed clock never goes back")
            rows = first + second
            for who in {r["who"] for r in rows}:
                ticks = [r["tick"] for r in rows if r["who"] == who]
                self.assertTrue(all(b - a >= feed_mod.RATE_TICKS for a, b in zip(ticks, ticks[1:])), (who, ticks))
            now = host.round.house.feed_clock()
            said = host.feed.post("dev-tester", "Washed up and ready", source="player", tick=now)
            self.assertNotIn("refused", said)
            self.assertEqual(host.feed.post("dev-tester", "again", source="player", tick=now + feed_mod.RATE_TICKS - 1)["refused"], "rate_limited")
            self.assertNotIn("refused", host.feed.post("dev-tester", "again", source="player", tick=now + feed_mod.RATE_TICKS))
            self.assertFalse(host.round.arena.failed)


class MakeLive(unittest.TestCase):
    """W17: `make live` with no block list (and no key) mutes every line and prints "guard list missing"."""

    def test_no_list_no_key_mutes_and_says_so(self):
        import contextlib
        import io
        import os
        import live_run
        saved = {k: os.environ.pop(k, None) for k in (live.KEY_ENV, guard.ENV)}
        out = io.StringIO()
        try:
            with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(out):
                self.assertEqual(live_run.main(["--seconds", "40", "--data-dir", d]), 0)
        finally:
            os.environ.update({k: v for k, v in saved.items() if v is not None})
        text = out.getvalue()
        self.assertIn("make live: guard list missing", text)
        self.assertIn("no model key", text)
        self.assertIn("chip autopilot (no model key)", text)
        counts = json.loads(text.split("feed: guard missing, counts ")[1].splitlines()[0])
        self.assertGreater(counts["posted"], 0, "the keyed house posted lines, so the mute is shown, not vacuous")
        self.assertEqual(counts["muted"], counts["posted"])
        self.assertIn("arena failed: False", text)


class Feed(unittest.TestCase):
    def feed(self, lst=FAKE):
        return feed_mod.PublicFeed(guard.Guard(lst, ["Satrenchi"]))

    def test_missing_list_mutes_every_producer_and_says_so(self):
        f = self.feed(None)
        self.assertEqual(f.notice(), "guard list missing")
        for source in ("house", "player"):
            row = f.post("p-" + source, "hello there", source=source, tick=0)
            self.assertTrue(row["muted"])
            self.assertEqual(row["label"], "guard list missing")
            self.assertIn(row["text"], guard.EMOTES)

    def test_guard_rate_and_one_reply_hold_for_players_and_house(self):
        f = self.feed()
        blocked = f.post("dev-a", "@FakeHandle is a fakeslur", source="player", tick=0)
        self.assertTrue(blocked["blocked"])
        self.assertIn(blocked["text"], guard.EMOTES)
        self.assertEqual(f.post("dev-a", "again", source="player", tick=feed_mod.RATE_TICKS - 1)["refused"], "rate_limited")
        ok = f.post("dev-a", "the Great Rug was a rogue bot", source="player", tick=feed_mod.RATE_TICKS)
        self.assertEqual(ok["text"], "the Great Rug was a rogue bot")
        reply = f.post("Satrenchi", "Noted.", source="house", tick=feed_mod.RATE_TICKS, reply_to=ok["id"])
        self.assertEqual(reply["reply_to"], ok["id"])
        self.assertEqual(f.post("dev-b", "me too", source="player", tick=feed_mod.RATE_TICKS, reply_to=ok["id"])["refused"], "already_replied")
        self.assertEqual(f.post("dev-c", "and me", source="player", tick=feed_mod.RATE_TICKS, reply_to=reply["id"])["refused"], "reply_to_a_reply")
        self.assertNotIn("fakeslur", json.dumps(f.public()))


if __name__ == "__main__":
    unittest.main()
