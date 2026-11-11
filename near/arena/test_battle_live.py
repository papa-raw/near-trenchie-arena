"""New battle live-mode transport cases; independent engine review is separate."""
import json
import asyncio
import io
import os
import struct
import tempfile
import types
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import urlsplit

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[2])]


class ScriptedSocket:
    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []
        self.closed = False

    def send(self, value):
        self.sent.append(value)

    def receive(self, timeout):
        return self.replies.pop(0) if self.replies else None

    def close(self):
        self.closed = True


class LegacyTransport:
    base = 'http://127.0.0.1:8765'

    def __init__(self):
        self.calls = []
        self.seen = {}

    def request(self, method, target, body=b''):
        self.calls.append((method, target, body))
        return {'manifest': True}

    def now(self):
        return self.seen.get('now', 0)


class BattleLive(unittest.TestCase):
    def test_fifo_is_private_and_startup_failures_exit_unsuccessfully(self):
        from snap_live import _input, run_live, CommandError
        with tempfile.TemporaryDirectory() as directory:
            regular = Path(directory)/'ordinary.txt'; regular.write_text('private data')
            output = io.StringIO()
            args = types.SimpleNamespace(seconds=0,fifo=str(regular))
            status = run_live(args,lambda args:self.fail('a regular file must never be read as orders'),refusal_fix=str,output=output)
            self.assertEqual(status,1)
            self.assertEqual(json.loads(output.getvalue())['kind'],'refusal')
            fifo = Path(directory)/'orders.fifo'
            descriptor, owned = _input(str(fifo))
            self.assertTrue(owned); os.close(descriptor)
            self.assertEqual(fifo.stat().st_mode & 0o777,0o600)
            os.chmod(fifo,0o666)
            with self.assertRaises(CommandError): _input(str(fifo))

    def test_line_commands_are_bounded_and_do_not_treat_speech_as_orders(self):
        from snap_live import parse_command, InputLines, CommandError
        self.assertEqual(parse_command('flee'), ('behaviour', {'v':1,'stance':'flee'}))
        self.assertEqual(parse_command('{"v":1,"drives":{"loot":10}}'), ('behaviour', {'v':1,'drives':{'loot':10}}))
        self.assertEqual(parse_command('say "STAY BACK!" 😱'), ('speech', {'text':'STAY BACK!','emoji':'😱'}))
        self.assertEqual(parse_command('leave'), ('leave', {'reason':'leave'}))
        self.assertIsNone(parse_command('   '))
        for bad in ('say TOO MANY WORDS', '{"v":1,"v":2}', '{"v":1,"drives":{"loot":1.5}}', 'go north', 'x'*16385):
            with self.subTest(line=bad[:30]), self.assertRaises(CommandError): parse_command(bad)
        stream = InputLines()
        line = 'say "STAY BACK!" 😱\n'.encode()
        self.assertEqual(stream.feed(line[:-2]), [])
        self.assertEqual(stream.feed(line[-2:]), ['say "STAY BACK!" 😱'])
        self.assertEqual(stream.feed(b'x'*17000), [])
        result = stream.feed(b'\nflee\n')
        self.assertIsInstance(result[0], CommandError)
        self.assertEqual(result[1], 'flee')
        self.assertEqual(stream.feed(b'leave'), [])
        self.assertEqual(stream.eof(), ['leave'])

    def test_websocket_route_is_live_and_refuses_foreign_hosts_and_origins(self):
        import snap_local
        class Reader:
            def __init__(self, host, origin):
                self.head = (f'GET /room/live HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n'
                             'Connection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n'
                             + (f'Origin: {origin}\r\n' if origin else '') + '\r\n').encode()
            async def readuntil(self, separator):
                return self.head
        class Writer:
            def __init__(self):
                self.parts = []
                self.closed = False
            def get_extra_info(self, field):
                return ('127.0.0.1', 1234)
            def write(self, data):
                self.parts.append(data)
            async def drain(self):
                pass
            def close(self):
                self.closed = True
        with tempfile.TemporaryDirectory() as directory:
            dev = snap_local.DevRoom(8765, directory)
            for host, origin, accepted in (('127.0.0.1:8765', None, True), ('other.invalid', None, False),
                                           ('127.0.0.1:8765', 'https://other.invalid', False)):
                with patch.object(snap_local, 'serve_live', new_callable=AsyncMock) as live:
                    writer = Writer()
                    asyncio.run(dev.handle(Reader(host, origin), writer))
                    self.assertEqual(live.await_count, int(accepted))
                    if not accepted:
                        self.assertTrue(writer.closed)
                        self.assertIn(b'403', b''.join(writer.parts))

    def test_live_peer_uses_the_real_signed_room_and_publishes_without_a_poll_request(self):
        import snap
        import snap_local
        from battle_live_host import LivePeer
        from battle_transport import LiveTransport
        with tempfile.TemporaryDirectory() as directory:
            dev = snap_local.DevRoom(8765, directory)
            def call(url, method='GET', body=None, headers=None, timeout=60, seen=None):
                parsed = urlsplit(url)
                target = parsed.path + ('?' + parsed.query if parsed.query else '')
                raw = json.dumps(body).encode() if isinstance(body, dict) else body or b''
                status, value = dev.route(method, target, raw, '127.0.0.1')
                self.assertEqual(status, 200, value)
                if seen is not None:
                    seen.update(now=dev.round.vnow(), at=0, paused=True)
                return value
            peers = []
            class PeerSocket:
                def __init__(self, url):
                    self.queue = []
                    self.peer = LivePeer(dev, self.queue.append, ip='127.0.0.1')
                    peers.append(self.peer)
                def send(self, value):
                    self.peer.receive(value)
                def receive(self, timeout):
                    return self.queue.pop(0) if self.queue else None
                def close(self):
                    self.peer.close()
            factory = lambda base, who: LiveTransport(snap.Transport(base, who), connector=PeerSocket)
            args = types.SimpleNamespace(url='http://127.0.0.1:8765', name='critbee', preset='survivor', spread='40,30,20,10', zero=10)
            with patch.object(snap, 'call', side_effect=call):
                keeper = snap.Keeper(args, transport_factory=factory)
                first = keeper.start('1')
                self.assertEqual(first['state'], 'accepted')
                self.assertEqual(len(peers), 1)
                # These are actual signed room prediction and renewal receipts.
                self.assertEqual(keeper.client.control('renew', {'lease_until': str(keeper.now() + 30000)})['state'], 'accepted')
                events = []
                for _ in range(12):
                    dev.round.arena.advance()
                    peers[0].publish()
                    events.extend(keeper.transport.poll(0))
                self.assertTrue(any(event['kind'] == 'life_start' for event in events), events)
                self.assertTrue(all(event['emitted_at_ms'] >= 0 for event in events))
                self.assertEqual(len(peers), 1)
                before = len(peers[0].dev.round.host.service._connections)
                keeper.transport.close()
                self.assertEqual(len(dev.round.host.service._connections), before - 1)

    def test_websocket_masking_limits_and_partial_reads(self):
        from battle_transport import WebSocket, _masked
        # A largest legal frame must use the 64-bit length form and stay masked.
        payload = b'x' * 65536
        wire = _masked(payload)
        self.assertEqual(wire[:2], b'\x81\xff')
        self.assertEqual(struct.unpack('!Q', wire[2:10])[0], len(payload))
        self.assertEqual(bytes(v ^ wire[10 + i % 4] for i, v in enumerate(wire[14:])), payload)
        with self.assertRaises(ValueError):
            _masked(payload + b'x')

        class ByteSocket:
            def __init__(self):
                self.parts = [b'\x81', TimeoutError(), b'\x0b{"ok":true}']
                self.closed = False
            def settimeout(self, timeout):
                pass
            def recv(self, size):
                part = self.parts.pop(0)
                if isinstance(part, Exception):
                    raise part
                return part
            def close(self):
                self.closed = True

        raw = ByteSocket()
        websocket = WebSocket(raw)
        self.assertIsNone(websocket.receive(1))
        self.assertEqual(websocket.receive(1), {'ok': True})
        for prefix in (b'\x01\x00', b'\x81\x80', b'\x81\x7f' + (65537).to_bytes(8, 'big')):
            websocket.buffer = bytearray(prefix)
            with self.assertRaises(ValueError):
                websocket.receive(0)

    def test_one_connection_multiplexes_replies_private_notices_and_events(self):
        from battle_transport import LiveTransport
        raw = ScriptedSocket([
            {'type': 'live_ready', 'challenge': {'connection_id': 'c1'}, 'clock': {'now_ms': 1000, 'paused': False}},
            {'event': {'kind': 'hit', 'tick': 21, 'damage': 7}},
            {'private': {'type': 'life_notice', 'reservation': {'life_id': 'life:2'}}},
            {'id': 'live-1', 'reply': {'type': 'control_ready'}},
            {'id': 'live-2', 'reply': {'fighters': ['bee']}, 'clock': {'now_ms': 1050, 'paused': False}},
            {'event': {'kind': 'low_hp', 'tick': 22}},
            {'event': {'kind': 'loot_near', 'tick': 22}},
        ])
        legacy = LegacyTransport()
        connects = []
        def connect(url):
            connects.append(url)
            return raw
        live = LiveTransport(legacy, connector=connect)
        self.assertEqual(live.request('GET', '/room'), {'manifest': True})
        self.assertEqual(live.open_control('wss://127.0.0.1:8765/room/control'), {'connection_id': 'c1'})
        self.assertEqual(live.frame('c1', b'{"kind":"authenticate"}'), {'type': 'control_ready'})
        self.assertEqual(live.request('GET', '/room/observe'), {'fighters': ['bee']})
        self.assertEqual(live.drain_private('c1')[0]['reservation']['life_id'], 'life:2')
        self.assertEqual([e['kind'] for e in live.poll(0)], ['hit', 'low_hp', 'loot_near'])
        self.assertEqual(connects, ['ws://127.0.0.1:8765/room/live'])
        self.assertEqual(len(legacy.calls), 1)
        self.assertEqual([m['op'] for m in raw.sent], ['frame', 'request'])
        self.assertEqual(legacy.seen['now'], 1050)
        with self.assertRaises(ValueError):
            live.frame('wrong-connection', b'{}')
        live.close()
        self.assertTrue(raw.closed)

    def test_reply_mismatch_and_stream_overflow_fail_closed_without_reconnect(self):
        from battle_transport import LiveTransport
        for incoming in ([{'id': 'other', 'reply': {}}], [{'event': {'kind': 'hit'}}] * 257):
            raw = ScriptedSocket([{'type': 'live_ready', 'challenge': {'connection_id': 'c1'}}] + incoming)
            connects = []
            def connect(url):
                connects.append(url)
                return raw
            live = LiveTransport(LegacyTransport(), connector=connect)
            live.open_control('wss://127.0.0.1:8765/room/control')
            with self.assertRaises(ValueError):
                live.frame('c1', b'{}')
            self.assertEqual(len(connects), 1)
            self.assertTrue(raw.closed)


if __name__ == '__main__':
    unittest.main()
