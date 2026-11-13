"""One startup recovery regression: invalid cached sessions require a new wallet sign-in, not operator repair.

Run: python3 -B near/chain/test_session_recovery.py
Fixture wallet/page private keys remain in memory. No external chain is contacted.
"""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'near/arena')]
from near.chain import identity
from near.chain.test_identity_desk import (PLAYER, ID_NFT, INV_NFT, NAMES, Page, FakeChain,
    inventory, premint_nft, settings, wallet_key)
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


class SessionRecovery(unittest.TestCase):
    def test_untrusted_cache_never_restores_partial_authority_and_allows_fresh_signin(self):
        for damage in ('json', 'permissions', 'scope', 'partial', 'unreadable'):
            with self.subTest(damage=damage), tempfile.TemporaryDirectory() as tmp:
                sk, pk = wallet_key()
                idc = FakeChain({ID_NFT: premint_nft()}, {PLAYER: {pk}})
                invc = FakeChain({INV_NFT: inventory()})
                logs = []
                def make():
                    return identity.IdentityDesk(settings(), idc, idc, invc, Ed25519PrivateKey.generate(),
                        'https://arena.example', names=NAMES, state_dir=tmp, log=logs.append)
                first = make()
                old = Page(first, sk, pk)
                data = Path(tmp) / 'identity-sessions.json'
                valid = json.loads(data.read_text())
                if damage == 'json':
                    data.write_text('{')
                elif damage == 'permissions':
                    data.chmod(0o640)
                elif damage in ('scope', 'partial'):
                    broken = copy.deepcopy(valid)
                    if damage == 'scope':
                        broken['scope']['identity_nft'] = 'another.testnet'
                    else:
                        broken['confirmed'] = [{'account_id': PLAYER, 'token_id': 'retired'}]
                    data.write_text(json.dumps(broken))
                before = data.read_bytes()
                read = Path.read_text
                def blocked(path, *args, **kwargs):
                    if path == data:
                        raise PermissionError('fixture unreadable cache')
                    return read(path, *args, **kwargs)
                with patch.object(Path, 'read_text', blocked if damage == 'unreadable' else read):
                    loaded = make()  # baseline raises ConfigError instead of starting without authorizations
                self.assertEqual((loaded.signins, loaded.confirmed, loaded.used), ({}, {}, {}))
                self.assertEqual(data.read_bytes(), before, 'damaged bytes are retained for the operator')
                self.assertTrue(any('session_state_skipped' in s and 'fresh_signin_required=True' in s for s in logs), logs)
                self.assertNotIn(old.sid, '\n'.join(logs), 'log no authorization id')
                with self.assertRaises(identity.IdentityError):
                    loaded.opened('confirm', old.env('confirm', {'token_id': 'retired'}))
                fresh = Page(loaded, sk, pk)
                self.assertIn(fresh.sid, loaded.signins)
                self.assertNotIn(old.sid, loaded.signins)
                self.assertEqual(data.stat().st_mode & 0o777, 0o600)
                again = make()
                self.assertIn(fresh.sid, again.signins)
                print('session recovery:', damage, 'fresh sign-in persisted; stale authorization refused')


if __name__ == '__main__':
    unittest.main()
