"""Spectator replies stay bounded even when a visitor sends pings without reading."""
import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import snap_local


class SpectatorLimits(unittest.IsolatedAsyncioTestCase):
    async def test_control_frames_and_inbound_floods_are_bounded_before_they_cost_a_tick(self):
        reader = asyncio.StreamReader()
        reader.feed_data(b'\x89\xfe\x10\x00' + b'\0' * 4 + b'p' * 4096)
        with self.subTest(kind='oversized-control'), self.assertRaises(ValueError):
            await snap_local.dev_brawl.read_frame(reader)
        sent = []
        async def drain():
            return None
        class Writer:
            pass
        writer = Writer()
        writer.write, writer.drain, writer.close = sent.append, drain, lambda: None
        writer.transport = SimpleNamespace(get_write_buffer_size=lambda: 0, abort=lambda: None)
        host = SimpleNamespace(latest=b'{}', clients={}, social_clients={}, client_tables={},
                               styles=SimpleNamespace(forget=lambda w: None))
        remaining = [(9, b'p')] * 64 + [(8, b'')]
        async def read_frame(reader):
            return remaining.pop(0)
        with patch.object(snap_local.dev_brawl, 'read_frame', read_frame):
            await snap_local.DevRoom.spectate(host, None, writer, 'test')
        with self.subTest(kind='frame-rate'):
            self.assertGreater(len(remaining), 40, 'a reading ping flood must be disconnected too')

    async def test_ping_replies_obey_backpressure_and_release_stalled_peers(self):
        class Writer:
            def __init__(self, stalled=False):
                self.transport = self
                self.buffer = self.peak = self.drains = 0
                self.closed = self.aborted = False
                self.stalled = stalled

            def write(self, data):
                self.buffer += len(data)
                self.peak = max(self.peak, self.buffer)

            def get_write_buffer_size(self):
                return self.buffer

            async def drain(self):
                self.drains += 1
                if self.stalled and self.drains > 1:
                    await asyncio.Event().wait()
                self.buffer = 0

            def abort(self):
                self.aborted = True
                self.buffer = 0

            def close(self):
                self.closed = True

        for scenario in ('reading', 'stalled', 'full'):
            stalled = scenario == 'stalled'
            with self.subTest(scenario=scenario):
                writer = Writer(stalled)
                host = SimpleNamespace(latest=b'{}', clients={}, social_clients={}, client_tables={},
                                       styles=SimpleNamespace(forget=lambda w: None))
                frames = [(9, b'p' * 4096)] * 1024 + [(8, b'')]
                async def read_frame(reader):
                    if scenario == 'full':
                        writer.buffer = snap_local.dev_brawl.MAX_BUFFER
                    return frames.pop(0)
                with patch.object(snap_local.dev_brawl, 'read_frame', read_frame), \
                        patch.object(snap_local, 'SPECTATOR_DRAIN_S', 0.01, create=True):
                    await snap_local.DevRoom.spectate(host, None, writer, 'test')
                self.assertLessEqual(writer.peak, snap_local.dev_brawl.MAX_BUFFER + 4100)
                if scenario != 'full':
                    self.assertGreater(writer.drains, 1, 'pong writes must drain')
                self.assertTrue(writer.closed)
                self.assertEqual(host.clients, {})
                if scenario != 'reading':
                    self.assertTrue(writer.aborted, 'a timed-out peer must release its output buffer')


if __name__ == '__main__':
    unittest.main()
