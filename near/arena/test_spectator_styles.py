"""Focused public-style metadata case. Tick snapshot bytes and sim hashes remain unchanged."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dev_brawl
import snap_local
import server
import codec
import sim


def payload(data: bytes) -> object:
    size = data[1] & 127
    offset = 2 if size < 126 else 4 if size == 126 else 10
    return json.loads(data[offset:])


class Writer:
    def __init__(self) -> None:
        self.frames = []
        self.transport = self
        self.buffered = 0

    def write(self, data: bytes) -> None:
        self.frames.append(data)

    def get_write_buffer_size(self) -> int:
        return self.buffered


class SpectatorStyles(unittest.TestCase):
    def test_two_hosts_publish_one_shared_update_without_touching_tick_bytes_or_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for host in (dev_brawl.Brawl(seed=417), snap_local.DevRoom(0, directory)):
                game = host.game if isinstance(host, dev_brawl.Brawl) else host.round.arena.sim
                game.enqueue(sim.Input(game.state["tick"], "join", "sprout-visitor", 0, {"style": "looter"}))
                game.step()
                host.latest = server.encode_snapshot(game)
                host.latest_codec = codec.encode_tick(game, codec.tables_for(game))
                host.styles.refresh(game)
                one, two, legacy = Writer(), Writer(), Writer()
                host.clients.update({one: False, two: False, legacy: False})
                host.styles.connect(one)
                host.styles.connect(two)
                self.assertEqual(one.frames, two.frames)
                first = payload(one.frames[-1])
                self.assertTrue(first['full'])
                self.assertEqual(first['version'], 1)
                self.assertEqual(first['styles'], {n: f['style'] for n, f in game.state['fighters'].items()})
                name = 'sprout-visitor'
                # Fixture a new public state, as observed after a join/life change; no new sim mutation path is added.
                game.state['fighters'][name]['style'] = 'guardian'
                before_hash, before_bytes = game.state_hash(), server.encode_snapshot(game)
                for writer in (one, two, legacy): writer.frames.clear()
                host.publish()
                self.assertEqual(one.frames, two.frames)
                updates = [data for data in one.frames if isinstance(payload(data), dict)]
                self.assertEqual(len(updates), 1)
                self.assertEqual(payload(updates[0])['styles'], {name: 'guardian'})
                self.assertFalse(payload(updates[0])['full'])
                self.assertTrue(all(isinstance(payload(data), list) for data in legacy.frames))
                one.frames.clear(); two.frames.clear()
                host.publish()
                self.assertEqual(len(one.frames), 1, 'unchanged styles send only the tick')
                self.assertEqual(game.state_hash(), before_hash)
                self.assertEqual(server.encode_snapshot(game), before_bytes)
                one.buffered = dev_brawl.MAX_BUFFER + 1
                game.state['fighters'][name]['style'] = 'looter'; host.publish()
                game.state['fighters'][name]['style'] = 'survivor'; host.publish()
                one.buffered = 0; one.frames.clear(); host.publish()
                resync = [payload(data) for data in one.frames if isinstance(payload(data), dict)]
                self.assertEqual(len(resync), 1)
                self.assertTrue(resync[0]['full'], 'missed metadata resyncs full state')
                self.assertEqual(resync[0]['styles'][name], 'survivor')


if __name__ == '__main__':
    unittest.main()
