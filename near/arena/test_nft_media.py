"""New NFT media case: real HTTP responses must match the contract's pinned bytes."""
import base64
import hashlib
import os
import requests
import importlib.util
import json
from pathlib import Path
import re
import sys
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('nft_media_serve', os.environ.get('NFT_SERVE_SOURCE', ROOT / 'near/web/snapin/serve.py'))
serve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(serve)


class NftMedia(unittest.TestCase):
    def test_http_png_and_reference_match_contract_hashes(self):
        port = [0]
        host = serve.BoundedHTTPServer(('127.0.0.1', 0), serve.make_handler('http://127.0.0.1:1', port))
        port[0] = host.server_address[1]
        thread = threading.Thread(target=host.serve_forever, daemon=True)
        thread.start()
        source = (ROOT / 'near/contracts/trenchie_nft/src/media.rs').read_text()
        rows = re.findall(r'Some\(\("([a-z-]+)", "[^"]+", "([A-Za-z0-9+/=]+)", include_str!\("([^\"]+)"\)\)\)', source)
        self.assertEqual(len(rows), 5)
        try:
            for slug, media_hash, ref_path in rows:
                conn = requests.Session()
                conn.trust_env = False
                if os.environ.get('HTTPS_PROXY'): conn.proxies = {'http': os.environ['HTTPS_PROXY']}
                origin = f'http://127.0.0.1:{port[0]}'
                response = conn.get(origin + f'/nft/v1/{slug}.png', timeout=5)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers.get('Content-Type'), 'image/png')
                self.assertEqual(response.headers.get('Cache-Control'), 'public, max-age=31536000, immutable')
                png = response.content
                self.assertTrue(png.startswith(b'\x89PNG\r\n\x1a\n'))
                self.assertEqual(base64.b64encode(hashlib.sha256(png).digest()).decode(), media_hash)
                response = conn.get(origin + f'/nft/{slug}-08.png', timeout=5)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, png)
                response = conn.get(origin + f'/nft/v1/{slug}.json', timeout=5)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers.get('Content-Type'), 'application/json')
                reference = response.content
                compiled = (ROOT / 'near/contracts/trenchie_nft/src' / ref_path).resolve().read_bytes()
                self.assertEqual(reference, compiled)
                attrs = {a['trait_type']: a['value'] for a in json.loads(reference)['attributes']}
                self.assertIn('Fighting style', attrs)
                self.assertTrue(all('Starter ' + slot in attrs for slot in ('head', 'body', 'weapon', 'trinket')))
                conn.close()
        finally:
            host.shutdown()
            host.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
