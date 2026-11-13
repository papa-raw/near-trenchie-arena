"""Sign-in traffic has a shared RPC budget independent of client addresses."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(Path(__file__).resolve().parent)]
from near.chain import identity, rpc
import test_identity_desk as fixtures


class SigninLimits(unittest.TestCase):
    def test_six_failed_addresses_cannot_keep_real_wallets_out_and_permissions_expire(self):
        real_key, real_public = fixtures.wallet_key()
        desk, chain, _, _ = fixtures.desk(fixtures.premint_nft(), fixtures.inventory(),
                                         {fixtures.PLAYER: (real_public,)})
        now = [1000.0]
        desk.clock = lambda: now[0]
        desk.signin_rpc.clock = desk.clock
        original = chain.access_key
        reads = []
        def counted(account, public):
            reads.append((account, public))
            return original(account, public)
        chain.access_key = counted
        for cycle in range(2):
            for address in range(6):
                ip = f'198.51.100.{address + 1}'
                for attempt in range(10):
                    key, public = fixtures.wallet_key()  # rotating keys must not bypass the address cool-off
                    challenge = desk.route('challenge', {'page_key': fixtures.b64url(key.public_key().public_bytes_raw())}, ip)
                    with self.assertRaises(identity.IdentityError):
                        desk.route('signin', dict(account_id='visitor.testnet', public_key=public,
                                   nonce=challenge['nonce'], signature=fixtures.nep413_sign(key, challenge, desk.recipient)), ip)
            page = fixtures.Page(desk, real_key, real_public, address='203.0.113.10')
            self.assertEqual(page.sin['account_id'], fixtures.PLAYER)
            if cycle == 0:
                account, public = reads[0]
                occupied = len(desk.signin_rpc.cool_off)
                for index in range(20):
                    desk.signin_rpc.access_key(account, public, address=f'192.0.2.{index + 1}')
                self.assertEqual(len(desk.signin_rpc.cool_off), occupied,
                                 'cached denials must not allocate cooldown state without a metered RPC read')
            now[0] += 61
        self.assertLessEqual(sum(account == 'visitor.testnet' for account, _ in reads), 6)
        page = fixtures.Page(desk, real_key, real_public, address='203.0.113.11')
        before = len(reads)
        fixtures.Page(desk, real_key, real_public, address='203.0.113.12')
        self.assertEqual(len(reads), before, 'a cached permission must not spend another key read')
        chain.full_access.clear()
        now[0] += 61
        with self.assertRaises(identity.IdentityError):
            fixtures.Page(desk, real_key, real_public, address='203.0.113.13')
        self.assertEqual(len(reads), before + 1, 'an expired permission must be re-read and revocation refused')

    def test_self_signed_attempts_cannot_multiply_rpc_work_across_addresses(self):
        key, public = fixtures.wallet_key()
        desk, chain, _, _ = fixtures.desk(fixtures.premint_nft(), fixtures.inventory(), {})
        now = [1000.0]
        desk.clock = lambda: now[0]
        if hasattr(desk, 'signin_rpc'):
            desk.signin_rpc.clock = desk.clock
        calls = []
        def unknown(account, public_key):
            calls.append((account, public_key))
            raise identity.rpclib.RpcError({'name': 'UNKNOWN_ACCESS_KEY'})
        chain.access_key = unknown
        def attempt(index):
            challenge = desk.challenge({'page_key': fixtures.b64url(key.public_key().public_bytes_raw())},
                                       f'198.51.100.{index % 250 + 1}')
            args = dict(account_id=fixtures.PLAYER, public_key=public, nonce=challenge['nonce'],
                        signature=fixtures.nep413_sign(key, challenge, desk.recipient))
            with self.assertRaises(identity.IdentityError):
                desk.signin(args)
        for i in range(70):
            attempt(i)
        self.assertLessEqual(len(calls), 60, 'changing addresses must not create more RPC capacity')
        self.assertIsNone(desk.owner('missing'), 'sign-in pressure must not spend the fresh owner-read allowance')
        before = len(calls)
        now[0] += 61
        attempt(71)
        self.assertEqual(len(calls), before + 1)
        chain.access_key = fixtures.FakeChain.access_key.__get__(chain)
        chain.full_access[fixtures.PLAYER] = (public,)
        now[0] += 61  # a previously absent permission is allowed to remain cached for sixty seconds
        page = fixtures.Page(desk, key, public, address='203.0.113.4')
        self.assertEqual(page.sin['account_id'], fixtures.PLAYER)
        self.assertEqual(len(desk.signin_rpc.calls), 3)
        # The dedicated sign-in client makes one wire request per budget unit, including throttled responses.
        posts = []
        def throttled(url, **kwargs):
            posts.append(url)
            return SimpleNamespace(status_code=429)
        client = rpc.Rpc(['https://rpc.example'], post=throttled, rounds=1, attempts=1, sleep=lambda _: None)
        with self.assertRaises(rpc.RpcUnreachable):
            client.access_key(fixtures.PLAYER, public)
        self.assertEqual(len(posts), 1)


if __name__ == '__main__':
    unittest.main()
