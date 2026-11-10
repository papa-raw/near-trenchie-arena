"""New arrival cases only: synthetic Ed25519 keys and a testnet contract mock."""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import importlib
from pathlib import Path
import sys
import tempfile
import unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'near/arena')]


class Arrival(unittest.TestCase):
    def setUp(self) -> None:
        self.api = importlib.import_module('near.onboarding.arrival')
        self.crypto = importlib.import_module('near.onboarding.signing')
        self.mock = importlib.import_module('near.onboarding.mock_contract')
        self.key = Ed25519PrivateKey.generate()
        self.wallet = Ed25519PrivateKey.generate()
        self.permit_key = Ed25519PrivateKey.generate()
        self.public = self.crypto.public_key(self.key)
        self.now = 1_900_000_000_000
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.contract = self.mock.MockContract(network_id='testnet', contract_id='personas.testnet',
            custodian='custodian.testnet', minter='snap.testnet',
            permit_public_key=self.crypto.public_key(self.permit_key))
        self.service = self.api.ArrivalService(Path(self.tmp.name) / 'custody.sqlite',
            contract=self.contract, now_ms=lambda: self.now,
            permit_sign=self.permit_key.sign, permit_epoch='1',
            wallet_verify=lambda account, body, proof: account == 'alice.testnet'
                and self.crypto.verify(self.crypto.public_key(self.wallet), body, proof),
            name_allowed=lambda name: name == 'Pebble')

    def hold(self, key: Ed25519PrivateKey | None = None, request_id: str = 'arrival',
             preset: str = 'preset-1', edge: str = 'edge-a') -> dict:
        key = self.key if key is None else key
        public = self.crypto.public_key(key)
        challenge = self.service.challenge(public, preset, request_id, device_id=edge, ip=edge)
        return self.service.allocate(challenge, self.crypto.sign(key, challenge))

    def claim_challenge(self, hold: dict, recipient: str = 'alice.testnet') -> dict:
        return self.service.claim_challenge(hold['reservation_id'], recipient)

    def claim(self, hold: dict, challenge: dict | None = None) -> dict:
        challenge = self.claim_challenge(hold) if challenge is None else challenge
        return self.service.claim(challenge, visitor_signature=self.crypto.sign(self.key, challenge),
            wallet_proof=self.crypto.sign(self.wallet, challenge))

    def test_walletless_fight_then_proved_claim_and_login_order(self) -> None:
        held = self.hold()
        self.assertEqual(held['state'], 'held')
        self.assertEqual(self.hold(), held, 'identical retry preserves token and expiry')
        self.assertEqual(self.contract.claims, [])
        fixture = importlib.import_module('test_room_host')
        contract_id = self.contract.contract_id
        class ArrivalRoom(fixture.CopiedRoom):
            def example(self, name: str) -> dict:
                value = super().example(name)
                if name == 'MainnetContext':
                    value['contract_ids']['nft'] = contract_id
                return value
        case = ArrivalRoom()
        case.setUp()
        self.addCleanup(case.doCleanups)
        with self.assertRaisesRegex(self.api.ArrivalRefusal, 'context_mismatch'):
            self.service.bind_room(case.context)
        self.service.bind_room(case.context, allow_synthetic_context=True)
        case.arena.identity_resolver = lambda request: (self.service.resolve_identity(request)
            if request['challenge']['nft_token_id'] == held['token_id'] else case.resolve(request))
        case.host._proof_methods = ('visitor_session_v1',)
        case.host.identity.proof_methods = frozenset(case.host._proof_methods)
        case.host._verify_session = self.crypto.verify_session
        case.host.identity.verify_session = self.crypto.verify_session
        client_module = importlib.import_module('snap_client')
        transport_module = importlib.import_module('test_cold_join')
        transport = transport_module.LocalTransport(case)
        client = client_module.SnapClient(case.context, transport, now_ms=lambda: self.now,
            sign_session=lambda body: self.crypto.encode(self.key.sign(body)),
            verify_room=lambda key, body, sig: sig == case.sign(body), trusted_key_ids=('room_key_a',))
        runtime = importlib.import_module('near.onboarding.runtime')
        wallet_calls = []
        def connect_wallet() -> tuple[str, Callable[[bytes], str]]:
            wallet_calls.append('connect')
            return 'alice.testnet', lambda body: self.crypto.encode(self.wallet.sign(body))
        flow = runtime.FightFirstSession(self.service, client, public_key=self.public,
            sign_session=self.key.sign, connect_wallet=connect_wallet)
        self.assertEqual(flow.begin('preset-1', 'arrival', device_id='edge-a', ip='edge-a',
            compute=dict(harness='external', model='fixture', source='owner', effort='high')), held)
        self.assertEqual(wallet_calls, [])
        with self.assertRaises(self.api.ArrivalRefusal):
            flow.claim()
        self.assertEqual(wallet_calls, [], 'claim is not offered before the first fight')
        self.assertTrue(client.can_answer)
        self.assertNotIn('owner_settings', client._grant['capabilities'])
        snapshot = client.member_snapshot(request_id='read')
        client.accept_terms(snapshot['terms']['version'], request_id='accept')
        ready = client.authenticate(request_id='socket')
        self.assertEqual(ready['type'], 'control_ready')
        life = ready['next_life']['reservation']['life_id']
        pick = dict(loadout=dict(menu_row='default', bag_serials=[]),
            spread_bps=dict(one=2500, two=2500, three=2500, four_plus=2500),
            zero_bps=1000, stake=None, moves=[], lock=False)
        self.assertEqual(client.control('prediction', pick, life_id=life)['state'], 'accepted')
        case.host.identity.proof_methods |= {'synthetic_v1'}
        case.host.identity.verify_session = lambda public, body, signature: (
            self.crypto.verify_session(public, body, signature) if public == self.crypto.session_key(self.public)
            else case.verify_session(public, body, signature))
        rival = case.join('bob')
        rival_cid, rival_ready = case.authenticate(rival)
        case.predict(rival, rival_cid, rival_ready)
        case.arena.advance(4)
        self.assertIn(held['token_id'], case.arena.sim._live())
        self.assertTrue(case.host.life_guard(case.arena.members[held['token_id']]['binding']))
        self.assertEqual(self.service.next_step(held['reservation_id']), 'fight')
        for _ in range(1196):
            case.arena.advance()
            if any(row['nft_token_id'] == held['token_id'] for row in case.arena.completed_lives):
                break
        self.assertTrue(any(row['nft_token_id'] == held['token_id'] for row in case.arena.completed_lives),
            'the held visitor must complete a real combat life before claim is offered')
        completed = next(row for row in case.arena.completed_lives if row['nft_token_id'] == held['token_id'])
        self.service.fight_seen(held['reservation_id'], completed)
        self.assertEqual(wallet_calls, [], 'a complete first fight must require no wallet callback')
        self.assertEqual(self.service.next_step(held['reservation_id']), 'offer_claim')
        self.contract.set_sale_ready(held['token_id'], False)
        self.assertEqual(flow.claim()['state'], 'claim_pending')
        self.assertEqual(self.contract.claims, [])
        self.contract.set_sale_ready(held['token_id'], True)
        claimed = flow.claim()
        self.assertEqual(claimed['state'], 'claimed')
        self.assertEqual(self.contract.token(held['token_id'])['owner_id'], 'alice.testnet')
        self.assertEqual(len(self.contract.claims), 1)
        self.assertEqual(self.claim(held), claimed, 'proved retry does not transfer again')
        self.assertFalse(case.host.life_guard(case.arena.members[held['token_id']]['binding']))
        before_stake = len(wallet_calls)
        self.assertEqual(flow.stake_wallet(), 'alice.testnet')
        self.assertEqual(len(wallet_calls), before_stake + 1)

    def test_fiftieth_race_fifty_first_permit_is_bound_and_one_use(self) -> None:
        rows = []
        for index in range(49):
            key = Ed25519PrivateKey.generate()
            rows.append(self.hold(key, 'request-' + str(index), 'preset-' + str(index // 10 + 1), 'edge-' + str(index)))
        keys = [Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()]
        def last(index: int) -> dict:
            return self.hold(keys[index], 'last-' + str(index), 'preset-5', 'last-' + str(index))
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(last, range(2)))
        self.assertEqual(sorted(row['state'] for row in results), ['held', 'paid_mint_required'])
        self.assertEqual(self.service.counts(), dict(total=50, held=50, claimed=0, available=0))
        overflow = next(row for row in results if row['state'] == 'paid_mint_required')
        self.assertEqual(overflow['label'], 'All claimed')
        self.assertEqual(overflow['count'], 50)
        # A signed permit names the visitor implicit account. Wallet rebinding
        # requires independently proved account control and never handles funds.
        overflow_key = keys[results.index(overflow)]
        permit = overflow['permit']
        for field, value in [('name', 'Other'), ('network_id', 'mainnet'), ('contract_id', 'other.testnet'),
                             ('caller', 'thief.testnet'), ('epoch', '0'), ('expires_at', str(self.now + 999999))]:
            changed = deepcopy(permit)
            changed['payload'][field] = value
            with self.assertRaises(self.api.ArrivalRefusal):
                self.contract.paid_mint(changed, caller=permit['payload']['caller'], signer=permit['payload']['caller'],
                    persona=overflow['persona'], attached_deposit='100', now_ms=self.now)
        caller = self.crypto.account_id(self.crypto.public_key(overflow_key))
        with self.assertRaises(self.api.ArrivalRefusal):
            self.contract.paid_mint(permit, caller='thief.testnet', signer=caller,
                persona=overflow['persona'], attached_deposit='100', now_ms=self.now)
        token = self.contract.paid_mint(permit, caller=caller, signer=caller,
            persona=overflow['persona'], attached_deposit='100', now_ms=self.now)
        self.assertEqual(token['owner_id'], caller)
        with self.assertRaises(self.api.ArrivalRefusal):
            self.contract.paid_mint(permit, caller=caller, signer=caller,
                persona=overflow['persona'], attached_deposit='100', now_ms=self.now)
        self.assertEqual(self.service.counts()['total'], 50)
        self.assertEqual(self.contract.claims, [])
        challenge = self.service.paid_wallet_challenge(self.crypto.public_key(overflow_key), 'preset-5', 'alice.testnet')
        rebound = self.service.paid_wallet_permit(challenge,
            visitor_signature=self.crypto.sign(overflow_key, challenge), wallet_proof=self.crypto.sign(self.wallet, challenge))
        self.assertEqual(rebound['permit']['payload']['caller'], 'alice.testnet')
        self.assertNotEqual(rebound['permit']['payload']['nonce'], permit['payload']['nonce'])
        owned = self.contract.paid_mint(rebound['permit'], caller='alice.testnet', signer='alice.testnet',
            persona=rebound['persona'], attached_deposit='100', now_ms=self.now)
        self.assertEqual(owned['owner_id'], 'alice.testnet')

    def test_expiry_returns_safe_token_and_stale_session_cannot_reclaim(self) -> None:
        held = self.hold()
        self.now += self.api.HOLD_MS - 1
        self.assertEqual(self.service.counts()['held'], 1)
        self.now += 1
        self.assertEqual(self.service.counts(), dict(total=50, held=0, claimed=0, available=50))
        with self.assertRaises(self.api.ArrivalRefusal):
            self.claim_challenge(held)
        replacement = self.hold(Ed25519PrivateKey.generate(), 'replacement', edge='new-edge')
        self.assertEqual(replacement['token_id'], held['token_id'])
        self.assertNotEqual(replacement['reservation_id'], held['reservation_id'])
        with self.assertRaises(self.api.ArrivalRefusal):
            self.service.allocate(dict(token_id=held['token_id']), 'forged')
        self.contract.set_sale_ready(replacement['token_id'], False)
        self.now += self.api.HOLD_MS
        self.assertEqual(self.service.counts()['available'], 49, 'active expired token stays quarantined')
        self.contract.set_sale_ready(replacement['token_id'], True)
        self.assertEqual(self.service.counts()['available'], 50)

    def test_claim_requires_both_proofs_exact_target_and_durable_hold(self) -> None:
        held = self.hold()
        challenge = self.claim_challenge(held)
        with self.assertRaises(self.api.ArrivalRefusal):
            self.service.claim(challenge, visitor_signature='forged', wallet_proof=self.crypto.sign(self.wallet, challenge))
        challenge = self.claim_challenge(held)
        with self.assertRaises(self.api.ArrivalRefusal):
            self.service.claim(challenge, visitor_signature=self.crypto.sign(self.key, challenge), wallet_proof='forged')
        challenge = self.claim_challenge(held)
        swapped = dict(challenge, recipient='thief.testnet')
        with self.assertRaises(self.api.ArrivalRefusal):
            self.service.claim(swapped, visitor_signature=self.crypto.sign(self.key, swapped), wallet_proof=self.crypto.sign(self.wallet, challenge))
        self.assertEqual(self.contract.claims, [])
        restarted = self.api.ArrivalService(self.service.path, contract=self.contract, now_ms=lambda: self.now,
            permit_sign=self.permit_key.sign, permit_epoch='1', wallet_verify=self.service.wallet_verify,
            name_allowed=lambda name: name == 'Pebble')
        self.assertEqual(restarted.counts()['held'], 1)
        retry = restarted.challenge(self.public, 'preset-1', 'arrival', device_id='edge-a', ip='edge-a')
        self.assertEqual(restarted.allocate(retry, self.crypto.sign(self.key, retry)), held)
        self.contract.available = False
        unavailable = restarted.challenge(self.public, 'preset-1', 'arrival', device_id='edge-a', ip='edge-a')
        with self.assertRaisesRegex(self.api.ArrivalRefusal, 'ownership_unavailable'):
            restarted.allocate(unavailable, self.crypto.sign(self.key, unavailable))
        self.contract.available = True
        with self.assertRaisesRegex(self.api.ArrivalRefusal, 'rate_limited'):
            self.hold(Ed25519PrivateKey.generate(), 'script-second', edge='edge-a')

        original_claim = self.contract.claim
        def lost_receipt(token_id: str, recipient: str, digest: str, *, caller: str) -> dict:
            original_claim(token_id, recipient, digest, caller=caller)
            raise OSError('synthetic confirmed transfer lost its receipt')
        self.contract.claim = lost_receipt
        self.assertEqual(self.claim(held)['state'], 'claim_pending')
        self.assertEqual(len(self.contract.claims), 1)
        self.now += self.api.HOLD_MS
        self.assertEqual(restarted.counts()['available'], 49, 'unknown claim outcome cannot reallocate')
        recovered_challenge = restarted.claim_challenge(held['reservation_id'], 'alice.testnet')
        recovered = restarted.claim(recovered_challenge,
            visitor_signature=self.crypto.sign(self.key, recovered_challenge),
            wallet_proof=self.crypto.sign(self.wallet, recovered_challenge))
        self.assertEqual(recovered['state'], 'claimed')
        self.assertEqual(len(self.contract.claims), 1, 'confirmation recovery never transfers twice')


if __name__ == '__main__':
    unittest.main()
