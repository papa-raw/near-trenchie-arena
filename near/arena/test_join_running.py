"""Joining an arena that is already running: a full ring, a later segment, a seat freed by a swim home."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
import types
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]
import snap  # noqa: E402
from test_snap_local import LocalSnap  # noqa: E402


def keeper(url: str, name: str, **extra) -> snap.Keeper:
    return snap.Keeper(types.SimpleNamespace(url=url, name=name, preset="hunter", spread="40,30,20,10", zero=10, **extra))


class JoinRunning(unittest.TestCase):
    setUp = LocalSnap.setUp
    shutdown = LocalSnap.shutdown

    def test_a_join_into_a_full_ring_reports_its_prediction_as_queued_with_the_reason(self) -> None:
        """The room locks the prediction, then queues the seat (room_full). Its receipt says refused; the
        keeper must say the prediction is held for that life and why the fighter waits, not "refused"."""
        bob = keeper(self.url, "bob")
        arena = self.dev.round.arena  # the identity's round: a fresh arena for the first DEV joiner
        arena._ring_load = lambda: arena.sim.rules["ring_max"]  # every ring seat taken
        first = bob.start("1")
        self.assertEqual(first["state"], "queued", first)
        self.assertEqual(first["reason"], "room_full", first)
        held = arena.locks[first["life_id"]]["lock"]
        self.assertEqual(first["prediction_hash"], held["prediction_hash"])
        line = snap.first_life_line(first)
        self.assertIn("queued", line)
        self.assertIn("room_full", line)
        self.assertIn(held["prediction_hash"][:12], line)
        self.assertNotIn("refused", line)
        del arena._ring_load  # a seat opens: the same life starts with the same lock
        deadline = time.monotonic() + 30
        while bob.summary()["you"]["state"] != "ring":
            self.assertLess(time.monotonic(), deadline, bob.errors)
            bob.tick()
            time.sleep(0.2)
        self.assertEqual(bob.life_id, first["life_id"])

    def test_a_join_during_another_players_swim_home_is_admitted_on_the_freed_slot(self) -> None:
        """The room frees a leaver's slot at once and hands it to the next joiner, while the leaver's fighter
        still swims home. The arena must not refuse that slot id as stale_slot."""
        lou = keeper(self.url, "lou")
        lou.start("1")
        deadline = time.monotonic() + 30
        while lou.summary()["you"]["state"] != "ring":
            self.assertLess(time.monotonic(), deadline, lou.errors)
            lou.tick()
            time.sleep(0.2)
        freed = lou.client._binding()["slot_id"]
        left = lou.client.control("leave", {"reason": "leave"}, life_id=lou.life_id)
        self.assertEqual(left["state"], "accepted", left)
        arena = self.dev.round.arena
        self.assertTrue(arena.members[lou.token]["released"])
        self.assertNotEqual(arena.sim.state["fighters"][lou.token]["state"], "left")  # still swimming home
        bob = keeper(self.url, "bob")
        first = bob.start("1")  # main: SystemExit("... stale_slot ...")
        self.assertEqual(bob.client._binding()["slot_id"], freed, "the case needs the freed slot id reused")
        self.assertIn(first["state"], ("accepted", "queued"), first)
        self.assertIn(lou.token, arena.members, "the leaver is still swimming when the joiner is admitted")

    def test_a_player_who_joins_in_a_later_segment_reads_a_signed_result_for_that_segment(self) -> None:
        """Lou keeps the round going, so Bob's life falls in segment:1, not segment:0. Bob's `result` must be the
        room-signed result of segment:1 with Bob's life and his public prediction row."""
        arena = self.dev.round.arena
        lou = keeper(self.url, "lou")
        lou.start("1")
        arena = self.dev.round.arena
        def run_to(tick: int, *keepers: snap.Keeper) -> None:
            while arena.sim.state["tick"] < tick:
                self.dev.step(min(100, tick - arena.sim.state["tick"]))
                for k in keepers:
                    k.tick()
        run_to(1250, lou)
        bob = keeper(self.url, "bob")
        first = bob.start("1")
        self.assertEqual(arena.sim.state["tick"] // 1200, 1, "Bob joins inside segment:1")
        for _ in range(60):  # a house trenchie yields a seat at its next life boundary
            if bob.summary()["you"]["state"] == "ring":
                break
            run_to(arena.sim.state["tick"] + 10, lou, bob)
        self.assertEqual(bob.summary()["you"]["state"], "ring", bob.errors)
        self.assertLess(arena.sim.state["tick"], 2200, "Bob's life must start well inside segment:1")
        run_to(arena.sim.state["tick"] + 20, lou, bob)
        left = bob.client.control("leave", {"reason": "leave"}, life_id=bob.life_id)
        self.assertEqual(left["state"], "accepted", left)
        run_to(2410, lou, bob)
        out = bob.result(0)  # main: SystemExit "segment:0 is sealed and your life did not end inside it"
        self.assertEqual(out["segment"], "segment:1", out)
        self.assertTrue(out["signed"] and out["completed"], out)
        self.assertEqual([l["life_id"] for l in out["lives"]], [first["life_id"]], out)
        if first["state"] == "accepted":
            self.assertEqual(out["public_prediction_row"], "matches your private receipt")

    test_a_player_who_joins_in_a_later_segment_reads_a_signed_result_for_that_segment.manual_clock = True


class Levels(unittest.TestCase):
    """A prediction counts as one level: all 10000 on one bin (1+, 2+, 3+ or 4+) and zero_bps 0. --level sends that;
    a spread over several bins still goes out, and the client says it is not counted under the level rules."""

    def test_level_flags_build_a_single_bin_prediction_and_a_legacy_spread_prints_the_fix(self):
        order = snap.standing_order(level=3, spread=None, zero=None)
        self.assertEqual(snap.prediction_payload("hunter", order["spread"], order["zero"])["spread_bps"],
                         {"one": 0, "two": 0, "three": 10000, "four_plus": 0})
        self.assertEqual(snap.prediction_payload("hunter", order["spread"], order["zero"])["zero_bps"], 0)
        none = snap.standing_order(level=None, spread=None, zero=None)
        self.assertEqual((none["level"], none["spread"], none["predict"]), (None, None, False),
                         "no flag files no prediction: a prediction is never invented")
        self.assertIn("--level 1-4", none["note"])
        none_line = snap.first_life_line(dict(life_id="dev-bob:life:0", state="none", level=None, note=none["note"]))
        self.assertIn("no prediction", none_line)
        self.assertIn("--level 1-4", none_line)
        legacy = snap.standing_order(level=None, spread="40,30,20,10", zero=10)
        self.assertIsNone(legacy["level"])
        self.assertIn("not counted", legacy["note"])
        self.assertIn("--level", legacy["note"])
        self.assertEqual(snap.standing_order(level=None, spread="0,100,0,0", zero=0)["level"], 2, "a one-bin spread is a level")
        with self.assertRaisesRegex(SystemExit, "--level or --spread"):
            snap.standing_order(level=2, spread="40,30,20,10", zero=None)
        line = snap.first_life_line(dict(life_id="dev-bob:life:0", state="accepted", prediction_hash="ab" * 32, level=3))
        self.assertIn("prediction accepted hash abababababab", line)
        self.assertIn("predicts 3+ KOs", line)
        legacy_line = snap.first_life_line(dict(life_id="dev-bob:life:0", state="accepted", prediction_hash="ab" * 32,
                                                level=None, note=legacy["note"]))
        self.assertIn("not counted", legacy_line)
        parsed = snap.build_parser().parse_args(["join", "--preset", "hunter", "--accept-terms", "1", "--level", "4"])
        self.assertEqual((parsed.level, parsed.spread, parsed.zero), (4, None, None))
        parsed = snap.build_parser().parse_args(["respawn", "--preset", "hunter", "--level", "2"])
        self.assertEqual(parsed.level, 2)


class LiveRejoin(unittest.TestCase):
    """A live agent session left open across a round restart (on a chain host every registration may start one) comes
    back by itself: the same trenchie in the new round's engine within 5 s, its last behaviour re-sent, one line said."""
    setUp = LocalSnap.setUp
    shutdown = LocalSnap.shutdown

    def test_an_open_live_session_rejoins_the_new_round_by_itself(self):
        import subprocess
        from unittest.mock import patch
        import snap_local
        fifo = Path(self.tmp.name) / "orders.fifo"
        live = subprocess.Popen([sys.executable, "-I", str(Path(snap.__file__)), "--url", self.url, "live", "--name", "Rejoiner",
                                 "--preset", "hunter", "--accept-terms", "1", "--fifo", str(fifo), "--seconds", "90"],
                                cwd=self.tmp.name, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def end_live() -> None:
            if live.poll() is None:
                live.kill()
            live.communicate(timeout=20)
        self.addCleanup(end_live)
        events = []
        def until(kind: str, seconds: float = 45) -> dict:
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                line = live.stdout.readline()
                if not line:
                    self.fail("live ended: " + live.stderr.read()[-2000:] + str(events[-3:]))
                events.append(json.loads(line))
                if events[-1]["kind"] in (kind, "refusal"):
                    return events[-1]
            self.fail(f"no {kind} within {seconds} s: {events[-3:]}")
        ready = until("session_ready")
        token = ready["fighter_id"]
        self.assertEqual(until("life_start")["kind"], "life_start")
        with open(fifo, "w") as orders:
            orders.write(json.dumps({"v": 1, "stance": "flee", "gate": {"never": True}}) + "\n")
        self.assertEqual(until("ack")["receipt"]["ack"]["status"], "applied")
        old_round = self.dev.round
        # The host's own restart path, as a chain registration takes it: a new identity's join restarts the round.
        # The guard that keeps a round with a DEV trenchie in it is set aside for this one join.
        old_round.ever_dev = False
        with patch.object(snap_local.Round, "dev_members", lambda round_: []):
            other = snap.call(self.url + "/dev/identity", "POST", {"name": "Newcomer", "preset": "hunter", "public_key": snap.encoded(
                snap.Ed25519PrivateKey.generate().public_key().public_bytes(snap.serialization.Encoding.Raw, snap.serialization.PublicFormat.Raw))})
        self.assertIn("nft_token_id", other, other)
        restarted = time.monotonic()
        self.assertIsNot(self.dev.round, old_round, "the round restarted")
        rejoined = until("rejoined", 10)
        self.assertEqual(rejoined["kind"], "rejoined", rejoined)
        self.assertEqual(rejoined["fighter_id"], token, "the same trenchie")
        while token not in self.dev.round.arena.members:
            self.assertLess(time.monotonic() - restarted, 5, "back in the new round's engine within 5 s")
            time.sleep(0.05)
        self.assertLess(time.monotonic() - restarted, 5)
        resent = until("ack", 20)
        self.assertEqual(resent["receipt"]["ack"]["status"], "applied", resent)
        self.assertEqual(resent.get("resent"), True)
        applies = time.monotonic() + 5                          # the ACK names an apply tick a few ticks ahead
        while (self.dev.round.arena.sim.state["fighters"][token].get("behaviour") or {}).get("drives", {}).get("keep_away") != 10:
            self.assertLess(time.monotonic(), applies, "the flee behaviour runs in the new round")
            time.sleep(0.05)


class RejoinProof(unittest.TestCase):
    """A rejoin changes the round only when it carries the session key's own signature over this round and a fresh time:
    a stranger who knows a public key can neither refresh the round's claim nor keep a fresh join from restarting it."""
    setUp = LocalSnap.setUp
    shutdown = LocalSnap.shutdown

    def test_a_strangers_rejoin_is_refused_changes_no_claim_and_blocks_no_fresh_join(self):
        key = snap.Ed25519PrivateKey.generate()
        public = snap.encoded(key.public_key().public_bytes(snap.serialization.Encoding.Raw, snap.serialization.PublicFormat.Raw))
        self.dev.create_identity("Owner", "hunter", public)          # the owner's identity, from an earlier round
        r = self.dev.round
        r.ever_dev, r.claimed_at = False, 0.0                       # a quiet round nobody holds
        now_ms = int(time.time() * 1000)
        def sig(round_, at):
            return snap.encoded(key.sign(snap.rejoin_message(round_, public, at)))
        for bad in ({"op": "rejoin", "public_key": public},                                            # no proof at all
                    {"op": "rejoin", "public_key": public, "round": self.dev.round_index, "at": now_ms,
                     "sig": snap.encoded(snap.Ed25519PrivateKey.generate().sign(snap.rejoin_message(self.dev.round_index, public, now_ms)))},
                    {"op": "rejoin", "public_key": public, "round": self.dev.round_index + 1, "at": now_ms,
                     "sig": sig(self.dev.round_index + 1, now_ms)},                                    # another round
                    {"op": "rejoin", "public_key": public, "round": self.dev.round_index, "at": now_ms - 120_000,
                     "sig": sig(self.dev.round_index, now_ms - 120_000)}):                              # a stale one
            status, reply = self.dev.route("POST", "/dev/identity", json.dumps(bad).encode(), "127.0.0.1")
            self.assertNotIn("nft_token_id", reply, bad)
            self.assertEqual((r.ever_dev, r.claimed_at), (False, 0.0), "a refused rejoin changes no claim")
        other = snap.encoded(snap.Ed25519PrivateKey.generate().public_key().public_bytes(snap.serialization.Encoding.Raw,
                                                                                        snap.serialization.PublicFormat.Raw))
        self.dev.create_identity("Fresh", "hunter", other)
        self.assertIsNot(self.dev.round, r, "a fresh join still starts a new round")
        ok = {"op": "rejoin", "public_key": public, "round": self.dev.round_index, "at": int(time.time() * 1000),
              "sig": sig(self.dev.round_index, int(time.time() * 1000))}
        status, reply = self.dev.route("POST", "/dev/identity", json.dumps(ok).encode(), "127.0.0.1")
        self.assertEqual(reply.get("nft_token_id"), "dev-owner", reply)
        self.assertTrue(self.dev.round.ever_dev, "the owner's own signed rejoin holds the round")

    def test_a_signed_rejoin_is_used_once(self):
        """An observer who saw a signed rejoin can't replay it inside its 30 s window."""
        key = snap.Ed25519PrivateKey.generate()
        public = snap.encoded(key.public_key().public_bytes(snap.serialization.Encoding.Raw, snap.serialization.PublicFormat.Raw))
        self.dev.create_identity("Owner", "hunter", public)
        at = int(time.time() * 1000)
        body = json.dumps({"op": "rejoin", "public_key": public, "round": self.dev.round_index, "at": at,
                           "sig": snap.encoded(key.sign(snap.rejoin_message(self.dev.round_index, public, at)))}).encode()
        self.assertEqual(self.dev.route("POST", "/dev/identity", body, "127.0.0.1")[1].get("nft_token_id"), "dev-owner")
        self.dev.round.ever_dev, self.dev.round.claimed_at = False, 0.0
        again = self.dev.route("POST", "/dev/identity", body, "127.0.0.1")[1]
        self.assertNotIn("nft_token_id", again, "the same proof a second time")
        self.assertIn("already used", str(again))
        self.assertEqual((self.dev.round.ever_dev, self.dev.round.claimed_at), (False, 0.0), "a replay changes no claim")

    def test_a_used_rejoin_is_refused_whatever_spelling_its_signature_has(self):
        """The decoder takes non-canonical base64url (the spare low bits of the last character), so one signature has
        several spellings. A used proof is the signed message itself, so every spelling of it is a replay."""
        key = snap.Ed25519PrivateKey.generate()
        public = snap.encoded(key.public_key().public_bytes(snap.serialization.Encoding.Raw, snap.serialization.PublicFormat.Raw))
        self.dev.create_identity("Owner", "hunter", public)
        at = int(time.time() * 1000)
        sig = snap.encoded(key.sign(snap.rejoin_message(self.dev.round_index, public, at)))
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
        last = alphabet.index(sig[-1])
        respelled = sig[:-1] + alphabet[(last & 0b110000) | (~last & 0b001111)]   # same top 2 bits, other spare bits
        self.assertNotEqual(respelled, sig)
        self.assertEqual(snap.decoded(respelled), snap.decoded(sig), "the respelling decodes to the same signature")
        body = lambda s_: json.dumps({"op": "rejoin", "public_key": public, "round": self.dev.round_index, "at": at, "sig": s_}).encode()
        self.assertEqual(self.dev.route("POST", "/dev/identity", body(sig), "127.0.0.1")[1].get("nft_token_id"), "dev-owner")
        self.dev.round.ever_dev, self.dev.round.claimed_at = False, 0.0
        again = self.dev.route("POST", "/dev/identity", body(respelled), "127.0.0.1")[1]
        self.assertNotIn("nft_token_id", again, "the same proof, respelled")
        self.assertEqual((self.dev.round.ever_dev, self.dev.round.claimed_at), (False, 0.0))


BRAIN_TO_PAYLOAD = r"""
// The browser path, with the page's own code: brain.js predicts the next life through a fake room, and room.js's
// predictionPayload (lifted from its source by name) turns that order into the pick the room locks.
const fs = require('fs'), path = require('path'), B = require(path.join(process.argv[1], 'brain.js'));
const src = fs.readFileSync(path.join(process.argv[1], 'room.js'), 'utf8');
const ORDER_DEFAULT = Function('return ' + /ORDER_DEFAULT = (\{[^;]*\})/.exec(src)[1])();
const body = /function predictionPayload\(o\) \{([\s\S]*?)\n  \}/.exec(src)[1];
const predictionPayload = Function('ORDER_DEFAULT', 'o', body).bind(null, ORDER_DEFAULT);
const NEAR = { door: 'NEAR AI Cloud', route: 'key', identity: 'NEAR AI Cloud' };
const m = new Map([[B.constants.SAVE, JSON.stringify({ door: NEAR, sheet: { game: { name: 'Pip' }, identity: { brief: 'A newcomer.' } } })],
                   [B.constants.CAP_STORE, '1'], [B.constants.KEY_STORE + 'NEAR AI Cloud', 'k']]);
const store = { get: (k) => (m.has(k) ? m.get(k) : null), set: (k, v) => m.set(k, String(v)), del: (k) => m.delete(k),
                json: (k, d) => { const v = m.get(k); return v ? JSON.parse(v) : d; } };
const orders = [], answer = process.argv[2];
const room = { on() { return () => {}; }, setOrder(o) { orders.push(o); return true; } };
const fetch = async () => ({ status: 200, text: async () => JSON.stringify({ choices: [{ message: { content: answer } }], usage: { prompt_tokens: 10, completion_tokens: 5 } }) });
const b = B.create({ room, store, fetch, setTimer: () => 1, clearTimer: () => {} });
b.predictNext(b.choices()).then(() => {
  const o = orders[0];
  console.log(JSON.stringify(o.prediction ? predictionPayload({ preset: 'hunter', spread: o.spread, zero: o.zero }) : null));
});
"""


class LevelsCounted(unittest.TestCase):
    shutdown = LocalSnap.shutdown
    """Under integer-16 each client's locked prediction is one the arena's own reader counts: predict.read_level, the
    call the seal row makes (server.py _seal_rows), gives (level, None); a spread over several bins gives NOT_COUNTED."""

    def read(self, pick_payload):
        sys.path[:0] = [str(HERE.parents[1])]
        import predict
        import sim
        self.assertEqual(sim.DEFAULT_RULES["version"], "integer-17")
        return predict.read_level(sim.DEFAULT_RULES, pick_payload["spread_bps"], pick_payload["zero_bps"]), predict.NOT_COUNTED

    def test_an_agent_door_level_life_locks_a_counted_prediction_and_a_legacy_spread_does_not(self):
        LocalSnap.setUp(self)
        for name, extra, want in (("lvl", dict(level=3), 3), ("old", dict(spread="40,30,20,10", zero=10), None)):
            k = snap.Keeper(types.SimpleNamespace(url=self.url, name=name, preset="hunter", **extra))
            first = k.start("1")
            pick = self.dev.round.arena.locks[first["life_id"]]["public"]["pick"]
            (level, note), not_counted = self.read(pick["payload"])
            self.assertEqual(level, want, pick["payload"])
            self.assertEqual(note, None if want else not_counted)
            if want is None:
                self.assertIn("not counted", snap.first_life_line(first))

    def test_an_agent_door_life_with_no_flag_locks_no_prediction(self):
        LocalSnap.setUp(self)
        k = snap.Keeper(types.SimpleNamespace(url=self.url, name="quiet", preset="hunter"))
        first = k.start("1")
        self.assertEqual(first["state"], "none", first)
        self.assertIn("no prediction", snap.first_life_line(first))
        deadline = time.monotonic() + 30
        while first["life_id"] not in self.dev.round.arena.locks:     # the room locks "none" at the prediction deadline
            self.assertLess(time.monotonic(), deadline, k.errors)
            k.tick()
            time.sleep(0.2)
        lock = self.dev.round.arena.locks[first["life_id"]]
        self.assertIsNone(lock["public"].get("pick"), "nothing was predicted for this life")
        self.assertEqual(lock["lock"]["state"], "none")
        sys.path[:0] = [str(HERE.parents[1])]
        import predict
        import sim
        # The seal row server.py writes for such a life (no pick, so read_level gives no level) earns nothing, whatever it scores.
        self.assertEqual(predict.read_level(sim.DEFAULT_RULES, None, None), (None, None))
        row = predict.seal_row(life_id=first["life_id"], persona=k.token, house=False, rules=sim.DEFAULT_RULES, level=None,
                               note=None, kos=4, base_bps=list(predict.LAB_BASE_BPS), sealed_ns=0)
        self.assertEqual(row["reward_points"], 0)

    def test_a_house_life_locks_a_counted_prediction(self):
        sys.path[:0] = [str(HERE.parent / "house")]
        import test_driver
        pick = test_driver.Levels.lock(self, [40, 30, 20, 10], 10)   # the model's spread, through driver.apply_pick
        self.assertEqual(self.read(pick["payload"])[0], (2, None))

    def test_a_browser_brain_life_locks_a_counted_prediction(self):
        import subprocess
        web = HERE.parent / "web" / "snapin"
        def payload(answer):
            out = subprocess.run(["node", "-e", BRAIN_TO_PAYLOAD, "--", str(web), answer], capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
            return json.loads(out.stdout)
        self.assertEqual(self.read(payload('{"level": 3}'))[0], (3, None))
        self.assertIsNone(payload('{"level": 0}'), "0 predicts nothing: no pick")


if __name__ == "__main__":
    unittest.main()
