"""Slow HTTP clients cannot allocate unbounded request threads (no network needed)."""
from pathlib import Path
import sys
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import serve


class ServerLimits(unittest.TestCase):
    def test_slow_connections_are_capped_and_slots_are_reusable(self):
        class Request:
            def __init__(self):
                self.output = b''
                self.started = threading.Event()
                self.finished = threading.Event()
            def settimeout(self, timeout):
                self.timeout = timeout
            def sendall(self, data):
                self.output += data
            def shutdown(self, how):
                return None
            def close(self):
                return None
        release = threading.Event()
        cls = getattr(serve, 'BoundedHTTPServer', serve.ThreadingHTTPServer)
        requests = []
        def handler(request, address, owner):
            request.started.set()
            try:
                release.wait(2)
                request.sendall(b'served')
            finally:
                request.finished.set()
        options = dict(bind_and_activate=False)
        if hasattr(serve, 'BoundedHTTPServer'):
            options['max_workers'] = 2
        server = cls(('127.0.0.1', 0), handler, **options)
        try:
            for _ in range(2):
                request = Request()
                requests.append(request)
                server.process_request(request, ('127.0.0.1', 1))
                self.assertTrue(request.started.wait(1))
            extra = Request()
            server.process_request(extra, ('127.0.0.1', 1))
            self.assertIn(b'503 Service Unavailable', extra.output)
            self.assertFalse(extra.started.is_set(), 'a full server must not start another worker')
            release.set()
            for request in requests:
                self.assertTrue(request.finished.wait(1))
            deadline = time.monotonic() + 1
            while time.monotonic() < deadline:
                fresh = Request()
                server.process_request(fresh, ('127.0.0.1', 1))
                if fresh.started.wait(0.01):
                    break
            self.assertTrue(fresh.finished.wait(1))
            self.assertEqual(fresh.output, b'served')
        finally:
            release.set()
            for request in requests:
                request.finished.wait(1)
            server.server_close()


if __name__ == '__main__':
    unittest.main()
