"""Count real ZIP builds across repeated/concurrent frontend and direct-host GETs; no sockets."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'near/arena')]
from near.arena import client_bundle as bundle
import client_bundle as legacy_bundle
import snap_local
from near.web.snapin import serve


class ClientBundleCache(unittest.TestCase):
    def test_repeated_and_concurrent_gets_build_once_with_identical_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            room = snap_local.DevRoom(18733, tmp)
            handler_cls = serve.make_handler('http://127.0.0.1:18733', [0])
            count, lock, real_zip = [0], threading.Lock(), bundle.ZipFile
            def counted_zip(*args, **kwargs):
                with lock:
                    count[0] += 1
                return real_zip(*args, **kwargs)
            def frontend(_):
                handler = handler_cls.__new__(handler_cls)
                handler.path, handler.own_host = '/snap-client.zip', lambda: True
                answers = []
                handler.reply = lambda *args: answers.append(args)
                handler_cls.do_GET(handler)
                status, data, kind, headers = answers[0]
                self.assertEqual((status, kind), (200, 'application/zip'))
                self.assertEqual(headers['Cache-Control'], 'no-store')
                return data
            class Wire:
                def __init__(self): self.data = bytearray()
                def get_extra_info(self, key): return ('127.0.0.1', 12345)
                def write(self, data): self.data.extend(data)
                async def drain(self): pass
                def close(self): pass
            async def direct():
                reader, writer = asyncio.StreamReader(), Wire()
                reader.feed_data(b'GET /snap-client.zip HTTP/1.1\r\nHost: 127.0.0.1:18733\r\n\r\n')
                reader.feed_eof()
                await room.handle(reader, writer)
                head, data = bytes(writer.data).split(b'\r\n\r\n', 1)
                self.assertIn(b'HTTP/1.1 200', head)
                self.assertIn(b'Content-Type: application/zip', head)
                return data
            # Reset only this case's process cache; concurrent cold requests must not duplicate compression.
            with patch.object(bundle, '_bundle', None, create=True), patch.object(bundle, 'ZipFile', counted_zip), \
                 patch.object(legacy_bundle, 'ZipFile', counted_zip):
                with ThreadPoolExecutor(max_workers=8) as pool:
                    replies = list(pool.map(frontend, range(20)))
                replies.extend(asyncio.run(direct()) for _ in range(20))
                self.assertTrue(replies[0].startswith(b'PK'))
                self.assertTrue(all(body == replies[0] for body in replies))
                self.assertEqual(count[0], 1, '40 GETs, including simultaneous first GETs, must compress once')


if __name__ == '__main__':
    unittest.main()
