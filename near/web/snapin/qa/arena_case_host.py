"""One-process local DEV arena + static files for browser cases, including the real spectator WebSocket."""
import asyncio
import mimetypes
import os
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT), str(ROOT / 'near/arena'), str(ROOT / 'near/web/snapin')]
import snap_local
import serve as web

if os.environ.get('SNAP_CASE_ROOM_ROOT'):
    original_contexts = snap_local.make_contexts
    def contexts(*args, **kwargs):
        with patch.object(snap_local, 'ROOT', Path(os.environ['SNAP_CASE_ROOM_ROOT'])):
            return original_contexts(*args, **kwargs)
    snap_local.make_contexts = contexts


class PrefixedReader:
    def __init__(self, reader, head):
        self.reader, self.head = reader, head

    async def readuntil(self, separator):
        if self.head is not None:
            head, self.head = self.head, None
            return head
        return await self.reader.readuntil(separator)

    def __getattr__(self, name):
        return getattr(self.reader, name)


class ArenaCaseHost(snap_local.DevRoom):
    async def handle(self, reader, writer):
        try:
            head = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 5)
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            writer.close()
            return
        first, *headers = head.decode('latin-1').split('\r\n')
        method, target, *_ = first.split(' ')
        path = urlsplit(target).path
        file = web.static_file(path) if method == 'GET' else None
        if file is None:
            return await super().handle(PrefixedReader(reader, head), writer)
        hosts = [line.partition(':')[2].strip() for line in headers if line.lower().startswith('host:')]
        if len(hosts) != 1 or hosts[0] not in self.own_hosts():
            writer.close()
            return
        body = file.read_bytes()
        kind = web.TYPES.get(file.suffix) or mimetypes.guess_type(str(file))[0] or 'application/octet-stream'
        writer.write(f'HTTP/1.1 200 OK\r\nContent-Type: {kind}\r\nContent-Length: {len(body)}\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n'.encode() + body)
        try:
            await writer.drain()
        except ConnectionError:
            pass
        writer.close()


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if not port:
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            port = probe.getsockname()[1]
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(snap_local.serve(ArenaCaseHost(port, tmp), ready=lambda p: print('arena-case: http://127.0.0.1:' + str(p) + '/', flush=True)))
