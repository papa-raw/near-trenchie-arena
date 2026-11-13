"""Focused restart regression: real hosted HTTP process, fake external chains, real signatures.

Run: python3 -I near/chain/test_identity_persist.py
Only public fixture keys cross the subprocess boundary; private keys stay in parent memory.
"""
import asyncio
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.parse import urlsplit
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'near' / 'arena')]
from near.chain import identity
from near.chain.test_identity_desk import (PLAYER, ID_NFT, NAMES, Page, b64url, desk,
    free_port, inventory, nep413_sign, premint_nft, wallet_key, FakeChain, settings, INV_NFT)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

TOKEN = 'preset-2-00'
SHEET = ROOT / 'near/web/snapin/premint/pike-pennywhistle.json'


def host_worker(state, port, public_key, owner):
    import snap_local
    from near.chain import hosted_live
    sheet = json.loads(SHEET.read_text())
    nft = premint_nft((TOKEN, 'preset-2'))
    nft.tokens[TOKEN].update(owner=owner, digest=snap_local.sheet_digest(sheet))
    d, *_ = desk(nft, inventory(), {PLAYER: {public_key}}, state_dir=state)

    class LocalWriter:
        def claim_seeds(self, arena): return [11, 12, 13, 14, 15]
        def take_seeds(self, arena): return []
        def sealed(self, *args, **kwargs): pass
        def owner_ok(self, binding): return True
        def life_ended(self, token): pass
        def health(self): return {}

    with tempfile.TemporaryDirectory() as data:
        block = Path(data) / 'blocklist.json'
        block.write_text(json.dumps({'names': [], 'handles': [], 'slurs': []}))
        os.environ['TRENCHIE_BLOCKLIST'] = str(block)
        room_type = hosted_live.install(d.s, LocalWriter(), d)
        room = room_type(int(port), data)
        asyncio.run(snap_local.serve(room))


class Persistence(unittest.TestCase):
    def test_same_wallet_session_and_confirmation_register_after_host_process_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / 'state'
            port = int(os.environ.get('IDENTITY_PERSIST_TEST_PORT', '0')) or free_port()
            sk, pk = wallet_key()
            processes = []
            log = open(Path(tmp) / 'host.log', 'w+')
            self.addCleanup(log.close)

            def stop():
                for proc in processes:
                    if proc.poll() is None:
                        proc.terminate()
                        proc.wait(timeout=10)
            self.addCleanup(stop)

            def connection(timeout):
                proxy = os.environ.get('IDENTITY_PERSIST_TEST_PROXY')
                if proxy:
                    target = urlsplit(proxy)
                    c = http.client.HTTPConnection(target.hostname, target.port, timeout=timeout)
                    c.set_tunnel('127.0.0.1', port)
                    return c
                return http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)

            def post(body):
                c = connection(10)
                try:
                    c.request('POST', '/dev/identity', json.dumps(body), {'Content-Type': 'application/json'})
                    r = c.getresponse()
                    return r.status, json.loads(r.read())
                finally:
                    c.close()

            def start(owner=PLAYER):
                p = subprocess.Popen([sys.executable, '-I', str(Path(__file__).resolve()), '--host',
                    str(state), str(port), pk, owner], cwd=ROOT, stdout=log, stderr=log)
                processes.append(p)
                deadline = time.monotonic() + 20
                last = 'no request'
                while time.monotonic() < deadline:
                    if p.poll() is not None:
                        self.fail('fixture host exited; inspect local host log')
                    try:
                        c = connection(1)
                        c.request('GET', '/dev/health')
                        r = c.getresponse()
                        last = (r.status, r.read())
                        c.close()
                        if r.status == 200:
                            return p
                    except OSError as exc:
                        last = str(exc)
                    time.sleep(.05)
                log.flush()
                self.fail('fixture host did not start: ' + str(last) + ' ' + Path(log.name).read_text()[-2500:])

            first = start()
            page = Page.__new__(Page)
            page.d = SimpleNamespace(clock=time.time)
            page.key = Ed25519PrivateKey.generate()
            page.pub = b64url(page.key.public_key().public_bytes_raw())
            st, ch = post({'op': 'challenge', 'page_key': page.pub})
            self.assertEqual(st, 200)
            st, signed_in = post({'op': 'signin', 'account_id': PLAYER, 'public_key': pk,
                'nonce': ch['nonce'], 'signature': nep413_sign(sk, ch, ch['recipient'])})
            self.assertEqual(st, 200, signed_in)
            page.sid = signed_in['signin']
            consumed = page.env('confirm', {'token_id': TOKEN})
            st, confirmed = post(consumed)
            self.assertEqual(st, 200, confirmed)
            first.terminate()
            first.wait(timeout=10)
            start()
            # No challenge or wallet signature after restart: only the same page key signs its next ticket.
            session_pub = b64url(Ed25519PrivateKey.generate().public_key().public_bytes_raw())
            signed = {'nft_token_id': TOKEN, 'session_public_key': session_pub,
                      'name': 'Pike', 'preset': 'hunter-lunge'}
            body = {'nft_token_id': TOKEN, 'public_key': session_pub, 'name': 'Pike',
                    'preset': 'hunter-lunge', 'sheet': json.loads(SHEET.read_text())}
            st, joined = post(dict(body, ticket=page.env('register', signed)))
            self.assertEqual(st, 200, joined)
            self.assertEqual(joined['nft_token_id'], TOKEN)
            st, replay = post(consumed)
            self.assertEqual(st, 400, replay)
            self.assertIn('already used', replay['error'])
            stop()
            start('buyer.testnet')
            st, sold = post(dict(body, ticket=page.env('register', signed)))
            self.assertEqual(st, 400, sold)
            self.assertIn('owned by buyer.testnet now', sold['error'])
            self.assertEqual((state / 'identity-sessions.json').stat().st_mode & 0o777, 0o600)
            log.flush()
            text = Path(log.name).read_text()
            self.assertNotIn(page.sid, text)
            self.assertNotIn(consumed['sig'], text)

    def test_expiry_is_not_renewed_on_load_and_replay_and_write_failures_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = [1000.0]
            nft, inv = premint_nft((TOKEN, 'preset-2')), inventory()
            nft.tokens[TOKEN]['owner'] = PLAYER
            sk, pk = wallet_key()
            idc = FakeChain({ID_NFT: nft}, {PLAYER: {pk}})
            invc = FakeChain({INV_NFT: inv})
            def make():
                return identity.IdentityDesk(settings(), idc, idc, invc, Ed25519PrivateKey.generate(),
                    'https://arena.example', names=NAMES, state_dir=tmp, clock=lambda: now[0], log=lambda s: None)
            d = make()
            page = Page(d, sk, pk)
            now[0] += 10
            env = page.env('confirm', {'token_id': TOKEN}, at=str(int(now[0] * 1000)))
            d.route('confirm', env)
            signin_expiry = d.signins[page.sid]['expires']
            confirmed_expiry = d.confirmed[(PLAYER, TOKEN)]['expires']
            data = Path(tmp) / 'identity-sessions.json'
            before = data.read_bytes()
            with patch.object(identity.os, 'replace', side_effect=OSError('fixture disk failure')):
                with self.assertRaisesRegex(identity.IdentityError, 'could not save'):
                    Page(d, sk, pk)
            self.assertEqual(data.read_bytes(), before)
            self.assertEqual(list(Path(tmp).glob('*.tmp')), [])
            now[0] += 5
            loaded = make()
            self.assertEqual(loaded.signins[page.sid]['expires'], signin_expiry)
            self.assertEqual(loaded.confirmed[(PLAYER, TOKEN)]['expires'], confirmed_expiry)
            with self.assertRaisesRegex(identity.IdentityError, 'already used'):
                loaded.opened('confirm', env)
            self.assertGreater(confirmed_expiry, signin_expiry)
            now[0] = signin_expiry
            partially_expired = make()
            self.assertEqual(partially_expired.signins, {})
            self.assertIn((PLAYER, TOKEN), partially_expired.confirmed)
            now[0] = confirmed_expiry
            expired = make()
            self.assertEqual(expired.signins, {})
            self.assertEqual(expired.confirmed, {})
            self.assertEqual(expired.used, {})
            stored = json.loads(data.read_text())
            self.assertEqual(stored['signins'], {})
            self.assertEqual(stored['confirmed'], [])
            data.write_text('{')
            with self.assertRaisesRegex(identity.chaincfg.ConfigError, 'identity session state'):
                make()


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--host':
        host_worker(*sys.argv[2:])
    else:
        unittest.main()
