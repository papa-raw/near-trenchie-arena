"""New cases for bound-cast metadata on the existing opt-in spectator channel."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent))
import codec
import dev_brawl
import server
import snap_local
import test_quirks as fixture
from test_spectator_styles import Writer, payload
from test_quirk_telegraphs import observe_cast
from spectator_styles import SpectatorStyles

ROWS = ['leg-laser-eyes', 'leg-hydra-halo', 'leg-tinker-coil', 'leg-harvest-quake', 'leg-ether-stack', 'leg-router-drone']

class CastMetadata(unittest.TestCase):
    def test_cast_start_is_one_shared_delta_before_the_tick(self) -> None:
        host = dev_brawl.Brawl(417)
        game, fighter = fixture.arena(ROWS[0]); host.game = game
        host.styles = SpectatorStyles(game, dev_brawl.frame)
        one, two, legacy = Writer(), Writer(), Writer()
        host.clients.update({one: False, two: False, legacy: False})
        host.styles.connect(one); host.styles.connect(two)
        one.frames.clear(); two.frames.clear()
        fixture.start(game, fighter)
        host.latest = server.encode_snapshot(game)
        host.latest_codec = codec.encode_tick(game, codec.tables_for(game))
        before_hash, before_bytes = game.state_hash(), host.latest
        host.publish()
        self.assertEqual(one.frames, two.frames)
        self.assertIs(one.frames[0], two.frames[0], 'same serialised bytes object')
        update = payload(one.frames[0]); self.assertEqual(len(update['casts']), 1)
        self.assertIsInstance(payload(one.frames[1]), list)
        self.assertEqual(len(legacy.frames), 1)
        one.frames.clear(); host.publish(); self.assertEqual(len(one.frames), 1)
        self.assertEqual(game.state_hash(), before_hash)
        self.assertEqual(server.encode_snapshot(game), before_bytes)

    def test_one_bound_cast_shared_once_by_both_hosts_and_resynced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for host in (dev_brawl.Brawl(417), snap_local.DevRoom(0, directory)):
                game, f = fixture.arena(ROWS[0]); fixture.start(game, f)
                if isinstance(host, dev_brawl.Brawl): host.game = game
                else: host.round.arena.sim = game
                host.latest = server.encode_snapshot(game)
                host.latest_codec = codec.encode_tick(game, codec.tables_for(game))
                host.styles.refresh(game)
                one, two, legacy = Writer(), Writer(), Writer()
                host.clients.update({one: False, two: False, legacy: False})
                host.styles.connect(one); host.styles.connect(two)
                self.assertEqual(one.frames, two.frames)
                before_hash, before_bytes = game.state_hash(), server.encode_snapshot(game)
                data = payload(one.frames[-1]); expected = observe_cast(game)
                self.assertEqual(len(data['casts']), 1)
                cast = next(iter(data['casts'].values()))
                self.assertEqual(cast['radiusMilli'], int(expected['radius_milli']))
                self.assertEqual(cast['arcMillidegrees'], int(expected['arc_millidegrees']))
                self.assertEqual(data['rules']['version'], game.rules['version'])
                original_item = f['equipped']['trinket']
                f['equipped']['trinket'] = 'leg-hydra-halo'
                f['sig_range_pct'] = 250
                for writer in (one, two, legacy): writer.frames.clear()
                host.publish()
                self.assertEqual(one.frames, two.frames)
                self.assertEqual(len(one.frames), 1, 'unchanged bound cast only sends the frozen tick')
                self.assertTrue(all(isinstance(payload(data), list) for data in legacy.frames))
                f['equipped']['trinket'] = original_item; f['sig_range_pct'] = 100
                self.assertEqual(game.state_hash(), before_hash); self.assertEqual(server.encode_snapshot(game), before_bytes)
                one.buffered = dev_brawl.MAX_BUFFER + 1
                f['cast'] = None; f['sig_at'] = 0; host.publish()
                fixture.start(game, f); host.publish()
                one.buffered = 0; one.frames.clear(); host.publish()
                metadata = [payload(d) for d in one.frames if isinstance(payload(d), dict)]
                self.assertEqual(len(metadata), 1); self.assertTrue(metadata[0]['full'])

if __name__ == '__main__': unittest.main()
