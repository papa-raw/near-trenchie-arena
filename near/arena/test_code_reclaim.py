"""An unseated code recovers with any key at its original address; another address is refused."""
import asyncio
import inspect
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'near/arena')]
import snap
import test_codex_ownership as boot


class CodeReclaim(unittest.TestCase):
    def test_other_address_is_refused_and_a_fresh_key_at_the_original_address_recovers(self):
        fixture = boot.CodexOwnership()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        bad = {'code': fixture.code, 'name': 'ignored', 'preset': 'hunter', 'public_key': 'invalid'}
        status, _ = fixture.route('POST', '/dev/identity', bad)
        self.assertEqual(status, 400)
        self.assertIsNone(fixture.room.codes[fixture.code]['claimed_by'], 'invalid registration cannot bind a code')
        first = fixture.keeper()
        other_key = snap.encoded(snap.Ed25519PrivateKey.generate().public_key().public_bytes(
            snap.serialization.Encoding.Raw, snap.serialization.PublicFormat.Raw))
        args = dict(bad, public_key=other_key)
        out = fixture.room.route('POST', '/dev/identity', json.dumps(args).encode(), '127.0.0.2')
        status, refused = asyncio.run(out) if inspect.isawaitable(out) else out
        self.assertEqual(status, 400, 'a caller at another address cannot replace the first client')
        self.assertIn('client', refused['error'])
        self.assertEqual(fixture.room.identities[first.token]['session_public_key']['public_key'], first.public_key)
        recovered = fixture.keeper()
        self.assertNotEqual(recovered.public_key, first.public_key, 'a fresh process uses a new key')
        self.assertEqual(recovered.token, first.token)
        self.assertNotIn(first.public_key, fixture.room.by_key, 'the previous client loses signing authority')
        args['public_key'] = recovered.public_key
        status, same = fixture.route('POST', '/dev/identity', args)
        self.assertEqual(status, 200, same)
        self.assertEqual(same['session_public_key']['public_key'], recovered.public_key)
        fixture.chain.inventory_ready = True
        recovered.start('1')
        self.assertTrue(fixture.room.codes[fixture.code]['joined'])
        status, used = fixture.route('POST', '/dev/identity', args)
        self.assertEqual(status, 400)
        self.assertIn('code already used', used['error'])


if __name__ == '__main__':
    unittest.main()
