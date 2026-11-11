"""Game-owned live socket adapter. Room authentication remains the room's work."""
import asyncio
import base64
import hashlib
import json
import struct
import time
from urllib.parse import urlsplit
from room.policy import canonical_bytes

try:
    from .battle_events import BattleEvents
    from .battle_transport import MAX_FRAME
except ImportError:
    from battle_events import BattleEvents
    from battle_transport import MAX_FRAME

READ_PATHS = frozenset(('/room/observe', '/room', '/dev/clock', '/dev/speech', '/dev/terms', '/dev/health'))
MAX_BUFFER = 1 << 20


class LivePeer:
    def __init__(self, dev, send, *, ip):
        self.dev, self.send = dev, send
        self.round = dev.round
        self.control = self.round.arena.control
        self.events = BattleEvents()
        self.who = None
        self.closed = False
        self.last_clock = -20
        self.last_reflex_speech = None
        challenge = self.control.open_control(ip=ip)
        if challenge.get('type') == 'error':
            raise ValueError('live control unavailable: ' + str(challenge.get('code')))
        self.connection_id = challenge['connection_id']
        self._send(dict(type='live_ready', challenge=challenge))

    def _send(self, value):
        if not self.closed:
            clock = dict(now_ms=self.round.vnow(), paused=time.monotonic() < self.dev.hold_until)
            self.send(dict(value, clock=clock))

    def receive(self, message):
        if self.closed or self.round is not self.dev.round:
            self.close()
            raise ValueError('arena restarted: restart live to rejoin')
        if not isinstance(message, dict) or not isinstance(message.get('id'), str) or len(message['id']) > 64:
            raise ValueError('live request needs a short id')
        op = message.get('op')
        if op == 'frame' and set(message) == {'id', 'op', 'body'} and isinstance(message['body'], dict):
            body = canonical_bytes(message['body'])
            _, reply = self.dev.route('POST', '/room/control/frame?cid=' + self.connection_id, body, '127.0.0.1')
            if reply.get('type') == 'control_ready':
                self.who = reply['nft_token_id']
                self.dev.mark_paired(self.who)
            if reply.get('state') == 'accepted' and reply.get('prediction_lock'):
                self.dev.hold_until = 0.0
        elif op == 'request' and self._public_read(message):
            _, reply = self.dev.route('GET', message['target'], b'', '127.0.0.1')
        else:
            reply = dict(type='error', code='bad_message', fix='Use frame, or GET one of the live public read routes.')
        self._send(dict(id=message['id'], reply=reply))
        self._private()

    @staticmethod
    def _public_read(message):
        return (set(message) == {'id', 'op', 'method', 'target', 'body'} and message.get('method') == 'GET'
                and message.get('body') == '' and isinstance(message.get('target'), str)
                and len(message['target']) <= 1024 and urlsplit(message['target']).path in READ_PATHS
                and not urlsplit(message['target']).netloc)

    def _private(self):
        for notice in self.control.drain_private(self.connection_id):
            self._send(dict(private=notice))

    def publish(self):
        if self.closed:
            return
        if self.round is not self.dev.round:
            self.close()
            return
        self._private()
        if self.who is None:
            return
        fighter = self.round.arena.sim.state['fighters'].get(self.who, {})
        ally = (fighter.get('behaviour') or {}).get('drives', {}).get('protect_ally')
        for event in self.events.read(self.round.arena, self.who, allies=[ally] if ally else [],
                                      feed=self.dev.feed, feed_tick=self.dev.feed_tick()):
            self._send(dict(event=event))
        speech = self.dev.reflex_speech_results.get(self.who)
        if speech is not None and (speech['tick'], speech['index']) != self.last_reflex_speech:
            try:
                from .battle_room import speech_ack
            except ImportError:
                from battle_room import speech_ack
            self.last_reflex_speech = speech['tick'], speech['index']
            self._send(dict(event=dict(kind='speech', tick=speech['tick'], reflex=speech['index'],
                       emitted_at_ms=time.time_ns() // 1000000, ack=speech_ack(speech['speech'], speech['tick']))))
        tick = self.round.arena.sim.state['tick']
        if tick - self.last_clock >= 20:
            self.last_clock = tick
            self._send(dict(event=dict(kind='clock', tick=tick, emitted_at_ms=time.time_ns() // 1000000)))

    def close(self):
        if not self.closed:
            self.closed = True
            self.control.close_control(self.connection_id)


async def read_client_frame(reader):
    first, second = await reader.readexactly(2)
    if not first & 0x80 or first & 0x70 or not second & 0x80:
        raise ValueError('live client frames must be final and masked')
    size = second & 127
    if size in (126, 127):
        size = int.from_bytes(await reader.readexactly(2 if size == 126 else 8), 'big')
    if size > MAX_FRAME or first & 15 >= 8 and size > 125:
        raise ValueError('live frame too large')
    mask = await reader.readexactly(4)
    data = await reader.readexactly(size)
    return first & 15, bytes(value ^ mask[index % 4] for index, value in enumerate(data))


def server_frame(payload, opcode=1):
    size = len(payload)
    if size < 126:
        head = bytes((0x80 | opcode, size))
    elif size < 65536:
        head = struct.pack('!BBH', 0x80 | opcode, 126, size)
    else:
        head = struct.pack('!BBQ', 0x80 | opcode, 127, size)
    return head + payload


async def serve_live(dev, reader, writer, key, *, ip):
    accept = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
    writer.write(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                 b'Sec-WebSocket-Accept: ' + accept + b'\r\n\r\n')
    def send(value):
        if writer.transport.get_write_buffer_size() > MAX_BUFFER:
            raise ValueError('live reader fell behind: restart live and keep reading events')
        writer.write(server_frame(json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode()))
    peer = None
    try:
        peer = LivePeer(dev, send, ip=ip)
        dev.live_clients[writer] = peer
        await writer.drain()
        while not peer.closed:
            opcode, payload = await asyncio.wait_for(read_client_frame(reader), 30)
            if opcode == 8:
                writer.write(server_frame(b'', 8))
                break
            if opcode == 9:
                writer.write(server_frame(payload, 10))
            elif opcode == 1:
                peer.receive(json.loads(payload))
            elif opcode != 10:
                raise ValueError('live accepts JSON text, ping or close frames')
            await writer.drain()
    except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError, ValueError, KeyError):
        pass
    finally:
        dev.live_clients.pop(writer, None)
        if peer is not None:
            peer.close()
        writer.close()
