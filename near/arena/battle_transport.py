"""One bounded WebSocket for live room controls, private notices and battle events."""
from collections import deque
import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import threading
import time
from urllib.parse import urlsplit, urlunsplit

MAX_FRAME = 65536
MAX_QUEUED = 256
GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'


def _masked(payload, opcode=1):
    mask = os.urandom(4)
    size = len(payload)
    if size > MAX_FRAME:
        raise ValueError('live frame too large: use at most 65536 bytes')
    if size < 126:
        head = bytes((0x80 | opcode, 0x80 | size))
    elif size < 65536:
        head = struct.pack('!BBH', 0x80 | opcode, 0xFE, size)
    else:
        head = struct.pack('!BBQ', 0x80 | opcode, 0xFF, size)
    return head + mask + bytes(value ^ mask[index % 4] for index, value in enumerate(payload))


class WebSocket:
    """Small non-fragmenting client; partial reads survive a receive timeout."""

    def __init__(self, connection, buffered=b''):
        self.connection = connection
        self.buffer = bytearray(buffered)
        self.closed = False

    @classmethod
    def connect(cls, url):
        parsed = urlsplit(url)
        if parsed.scheme not in ('ws', 'wss') or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError('live URL must be ws:// or wss:// with no credentials')
        port = parsed.port or (443 if parsed.scheme == 'wss' else 80)
        connection = socket.create_connection((parsed.hostname, port), timeout=5)
        try:
            if parsed.scheme == 'wss':
                connection = ssl.create_default_context().wrap_socket(connection, server_hostname=parsed.hostname)
            key = base64.b64encode(os.urandom(16)).decode()
            path = parsed.path or '/'
            if parsed.query:
                path += '?' + parsed.query
            request = (f'GET {path} HTTP/1.1\r\nHost: {parsed.netloc}\r\nUpgrade: websocket\r\n'
                       f'Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\n\r\n')
            connection.sendall(request.encode('ascii'))
            buffered = cls._handshake(connection, key)
            return cls(connection, buffered)
        except BaseException:
            connection.close()
            raise

    @staticmethod
    def _handshake(connection, key):
        data = bytearray()
        while b'\r\n\r\n' not in data:
            chunk = connection.recv(4096)
            if not chunk or len(data) + len(chunk) > 16384:
                raise ValueError('live upgrade failed: restart live against the arena URL')
            data.extend(chunk)
        header, buffered = bytes(data).split(b'\r\n\r\n', 1)
        lines = header.decode('latin-1').split('\r\n')
        fields = {k.lower().strip(): v.strip() for k, _, v in (line.partition(':') for line in lines[1:])}
        expected = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        if (lines[0].split(' ')[:2] != ['HTTP/1.1', '101'] or fields.get('sec-websocket-accept') != expected
                or fields.get('upgrade', '').lower() != 'websocket'
                or 'upgrade' not in [item.strip() for item in fields.get('connection', '').lower().split(',')]
                or 'sec-websocket-extensions' in fields):
            raise ValueError('live upgrade failed: use a host that supports /room/live')
        return buffered

    def send(self, value):
        self.connection.sendall(_masked(json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode()))

    def _next_frame(self):
        if len(self.buffer) < 2:
            return None
        first, second = self.buffer[:2]
        if first & 0x70 or not first & 0x80 or second & 0x80:
            raise ValueError('live frame flags refused: reconnect to the arena')
        size, offset = second & 127, 2
        extra = 2 if size == 126 else 8 if size == 127 else 0
        if len(self.buffer) < offset + extra:
            return None
        if extra:
            size = int.from_bytes(self.buffer[offset:offset + extra], 'big')
            offset += extra
        if size > MAX_FRAME or first & 15 >= 8 and size > 125:
            raise ValueError('live frame too large: reconnect to the arena')
        if len(self.buffer) < offset + size:
            return None
        payload = bytes(self.buffer[offset:offset + size])
        del self.buffer[:offset + size]
        return first & 15, payload

    def receive(self, timeout):
        deadline = time.monotonic() + max(0, timeout)
        while not self.closed:
            frame = self._next_frame()
            if frame is not None:
                opcode, payload = frame
                if opcode == 1:
                    value = json.loads(payload)
                    if not isinstance(value, dict):
                        raise ValueError('live messages must be JSON objects')
                    return value
                if opcode == 8:
                    self.close()
                    raise ValueError('live connection closed: restart live to rejoin')
                if opcode == 9:
                    self.connection.sendall(_masked(payload, 10))
                elif opcode != 10:
                    raise ValueError('unsupported live frame: reconnect to the arena')
                continue
            remaining = max(0, deadline - time.monotonic())
            self.connection.settimeout(remaining)
            try:
                chunk = self.connection.recv(8192)
            except (TimeoutError, BlockingIOError, ssl.SSLWantReadError, ssl.SSLWantWriteError):
                return None
            if not chunk:
                self.close()
                raise ValueError('live connection lost: restart live to rejoin')
            self.buffer.extend(chunk)
        raise ValueError('live connection is closed: restart live to rejoin')

    def close(self):
        if not self.closed:
            self.closed = True
            self.connection.close()


class LiveTransport:
    """Reuse the existing HTTP bootstrap, then send every operation on one socket."""

    def __init__(self, legacy, *, connector=WebSocket.connect):
        self.legacy = legacy
        self.connector = connector
        self.socket = None
        self.connection_id = None
        self.serial = 0
        self.events = deque()
        self.private = deque()
        self.lock = threading.RLock()

    def now(self):
        return self.legacy.now()

    def _receive(self, timeout):
        value = self.socket.receive(timeout)
        if value is not None and 'clock' in value:
            clock = value['clock']
            self.legacy.seen.update(now=int(clock['now_ms']), paused=bool(clock['paused']), at=time.monotonic())
        return value

    def open_control(self, url):
        if self.socket is not None:
            raise ValueError('live already has a control connection')
        parsed, base = urlsplit(url), urlsplit(self.legacy.base)
        if parsed.netloc != base.netloc:
            raise ValueError('live control host differs from the pinned arena')
        live_url = urlunsplit(('wss' if base.scheme == 'https' else 'ws', base.netloc, '/room/live', '', ''))
        self.socket = self.connector(live_url)
        try:
            ready = self._receive(5)
            if ready is None or ready.get('type') != 'live_ready':
                raise ValueError('live challenge missing: restart live to rejoin')
            challenge = ready['challenge']
            self.connection_id = challenge['connection_id']
            return challenge
        except BaseException:
            self.close()
            raise

    def _queue(self, value):
        for key, queue in (('event', self.events), ('private', self.private)):
            if key in value:
                if len(queue) >= MAX_QUEUED:
                    raise ValueError('live stream overflow: restart live and keep reading events')
                queue.append(value[key])
                return
        raise ValueError('unexpected live message: reconnect to the arena')

    def _exchange(self, op, **fields):
        with self.lock:
            self.serial += 1
            request_id = 'live-' + str(self.serial)
            deadline = time.monotonic() + 5
            try:
                self.socket.send(dict(id=request_id, op=op, **fields))
                while True:
                    value = self._receive(max(0, deadline - time.monotonic()))
                    if value is None:
                        raise ValueError('live reply timed out: restart live; do not assume the order applied')
                    if 'id' in value:
                        if value['id'] != request_id:
                            raise ValueError('live reply id mismatch: reconnect to the arena')
                        return value['reply']
                    self._queue(value)
            except BaseException:
                self.close()
                raise

    def request(self, method, target, body=b''):
        if self.socket is None:
            return self.legacy.request(method, target, body)
        return self._exchange('request', method=method, target=target, body=body.decode() if body else '')

    def frame(self, connection_id, body):
        if connection_id != self.connection_id or self.socket is None:
            raise ValueError('live connection binding differs: restart live to rejoin')
        return self._exchange('frame', body=json.loads(body))

    def drain_private(self, connection_id):
        if connection_id != self.connection_id:
            raise ValueError('live connection binding differs: restart live to rejoin')
        with self.lock:
            values = list(self.private)
            self.private.clear()
            return values

    def poll(self, timeout=0.05):
        with self.lock:
            try:
                value = self._receive(timeout)
                while value is not None:
                    self._queue(value)
                    value = self._receive(0)
                values = list(self.events)
                self.events.clear()
                return values
            except BaseException:
                self.close()
                raise

    def close(self):
        if self.socket is not None:
            self.socket.close()
