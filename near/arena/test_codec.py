"""W14: one round-trip on a recorded tick: decode(encode) equals server.encode_snapshot, and it is smaller."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import codec
import dev_brawl
import server
import sim


def busy_game():
    game = dev_brawl.new_brawl(7)
    seen = set()
    for _ in range(3000):
        game.step()
        s = game.state
        seen |= {"drop" for d in s["drops"]} | {"object" for o in s["objects"]} | {"cast" for f in s["fighters"].values() if f["cast"]}
        if {"drop", "object", "cast"} <= seen and s["events"] and s["objects"] and s["drops"] \
                and any(f["cast"] for f in s["fighters"].values()):
            return game
    raise AssertionError("no tick with a drop, an object, a cast and an event in 3000 ticks")


class RoundTrip(unittest.TestCase):
    def test_decode_of_encode_equals_the_canonical_snapshot_on_a_busy_recorded_tick(self):
        game = busy_game()
        tables = codec.tables_for(game)
        frame = codec.encode_tick(game, tables)
        self.assertEqual(codec.decode_tick(frame, tables), json.loads(server.encode_snapshot(game)))
        full = len(server.encode_snapshot(game))
        print("bytes per tick: canonical %d, compact %d (tables frame %d, sent once)"
              % (full, len(frame), len(codec.encode_tables(tables))))
        self.assertLess(len(frame), full)

    def test_every_tick_of_a_run_round_trips_and_arrays_are_integers_only(self):
        game = dev_brawl.new_brawl(3)
        game.step()
        tables = codec.tables_for(game)
        for _ in range(400):
            game.step()
            frame = codec.encode_tick(game, tables)
            head = json.loads(frame)
            for part in head[:7]:
                self.assertTrue(all(type(x) is int for x in (part if isinstance(part, list) else [part])))
            self.assertEqual(codec.decode_tick(frame, tables), json.loads(server.encode_snapshot(game)))

    def test_stale_or_changed_tables_are_refused(self):
        game = dev_brawl.new_brawl(3)
        game.step()
        tables = codec.tables_for(game)
        frame = codec.encode_tick(game, tables)
        other = dict(tables, table_id=tables["table_id"] + 1)
        with self.assertRaises(ValueError):
            codec.decode_tick(frame, other)
        game.state["fighters"].pop(sorted(game.state["fighters"])[0])
        with self.assertRaises(ValueError):
            codec.encode_tick(game, tables)


if __name__ == "__main__":
    unittest.main()
