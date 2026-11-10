"""Two new W3 repair cases; no old acceptance test methods are invoked."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'near/arena')]

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from near.onboarding import arrival, runtime, signing
from near.onboarding.test_arrival import Arrival


class ArrivalRecovery(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Arrival()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def real_client(self, drop_target: str) -> tuple[runtime.FightFirstSession, object, object]:
        from snap_client import SnapClient
        from test_room_host import CopiedRoom
        from test_cold_join import LocalTransport
        fixture = self.fixture
        contract_id = fixture.contract.contract_id

        class Room(CopiedRoom):
            def example(self, name: str) -> dict:
                value = super().example(name)
                if name == 'MainnetContext':
                    value['contract_ids']['nft'] = contract_id
                return value

        case = Room()
        case.setUp()
        self.addCleanup(case.doCleanups)
        fixture.service.bind_room(case.context, allow_synthetic_context=True)
        case.arena.identity_resolver = fixture.service.resolve_identity
        case.host.identity.proof_methods = frozenset(('visitor_session_v1',))
        case.host.identity.verify_session = signing.verify_session

        class DropOnce(LocalTransport):
            dropped = False

            def request(self, method: str, target: str, body: bytes = b'') -> dict:
                if target == drop_target and not self.dropped:
                    self.dropped = True
                    raise OSError('synthetic one-request admission interruption')
                return super().request(method, target, body)

        client = SnapClient(case.context, DropOnce(case), now_ms=lambda: fixture.now,
            sign_session=lambda body: signing.encode(fixture.key.sign(body)),
            verify_room=lambda key, body, signature: signature == case.sign(body),
            trusted_key_ids=('room_key_a',))

        def no_wallet() -> tuple:
            raise AssertionError('admission retry asked for a wallet')

        flow = runtime.FightFirstSession(fixture.service, client, public_key=fixture.public,
            sign_session=fixture.key.sign, connect_wallet=no_wallet)
        return flow, client, case

    def test_same_controller_retries_interrupted_admission_with_original_hold(self) -> None:
        fixture = self.fixture
        flow, client, room = self.real_client('/room')
        arguments = dict(preset_id='preset-1', request_id='retry-arrival', device_id='edge', ip='edge',
            compute=dict(harness='external', model='fixture', source='owner', effort='high'))
        with self.assertRaises(OSError):
            flow.begin(**arguments)
        original = deepcopy(flow.hold)
        self.assertEqual(fixture.service.counts()['held'], 1)
        self.assertFalse(client.can_answer)
        for change in (dict(request_id='other'), dict(preset_id='preset-2'),
                       dict(compute=dict(arguments['compute'], model='other'))):
            with self.assertRaisesRegex(arrival.ArrivalRefusal, 'request_conflict'):
                flow.begin(**dict(arguments, **change))
        fixture.now += 1_000
        room.now = fixture.now
        recovered = flow.begin(**arguments)
        self.assertEqual(recovered, original, 'retry must preserve token, reservation and original expiry')
        self.assertTrue(client.can_answer)
        self.assertEqual(room.host.identity.grant_count, 1)
        self.assertEqual(len(room.arena.members), 1)
        self.assertEqual(fixture.service.counts(), dict(total=50, held=1, claimed=0, available=49))
        self.assertEqual(fixture.contract.claims, [])
        snapshot = client.member_snapshot(request_id='read-recovered')
        client.accept_terms(snapshot['terms']['version'], request_id='accept-recovered')
        self.assertEqual(client.authenticate(request_id='authenticate-recovered')['type'], 'control_ready')
        with self.assertRaisesRegex(arrival.ArrivalRefusal, 'request_conflict'):
            flow.begin(**arguments)

    def test_paid_challenge_principal_and_class_caps_preserve_arrival_and_claim(self) -> None:
        fixture = self.fixture
        service = fixture.service
        accepted, refused = [], 0
        for index in range(arrival.MAX_PENDING_CHALLENGES):
            try:
                accepted.append(service.paid_wallet_challenge(fixture.public,
                    'preset-' + str(index % 5 + 1), 'recipient-' + str(index) + '.testnet'))
            except arrival.ArrivalRefusal as error:
                self.assertEqual(str(error), 'rate_limited')
                refused += 1
        self.assertLessEqual(len(accepted), 5, 'one unproved key occupied the shared challenge table')
        self.assertGreater(refused, 0)
        self.assertEqual(service.counts(), dict(total=50, held=0, claimed=0, available=50))
        # A fresh service instance must enforce the same persisted per-key bound.
        reopened = arrival.ArrivalService(service.path, contract=fixture.contract, now_ms=lambda: fixture.now,
            permit_sign=fixture.permit_key.sign, permit_epoch='1', wallet_verify=service.wallet_verify,
            name_allowed=lambda name: name == 'Pebble')
        with self.assertRaisesRegex(arrival.ArrivalRefusal, 'rate_limited'):
            reopened.paid_wallet_challenge(fixture.public, 'preset-1', 'alice.testnet')
        for index in range(arrival.MAX_PENDING_CHALLENGES):
            public = signing.public_key(Ed25519PrivateKey.generate())
            try:
                service.paid_wallet_challenge(public, 'preset-1', 'alice.testnet')
            except arrival.ArrivalRefusal as error:
                self.assertEqual(str(error), 'rate_limited')
        with service._db() as db:
            self.assertLessEqual(db.execute('SELECT COUNT(*) FROM challenges').fetchone()[0], 64,
                'unproved paid-wallet requests must leave admission and claim capacity')
        victim = Ed25519PrivateKey.generate()
        challenge = service.challenge(signing.public_key(victim), 'preset-1', 'victim', device_id='victim', ip='victim')
        held = service.allocate(challenge, signing.sign(victim, challenge))
        claim = service.claim_challenge(held['reservation_id'], 'alice.testnet')
        claimed = service.claim(claim, visitor_signature=signing.sign(victim, claim),
            wallet_proof=signing.sign(fixture.wallet, claim))
        self.assertEqual(claimed['state'], 'claimed')
        self.assertEqual(len(fixture.contract.claims), 1)
        fixture.now += arrival.CHALLENGE_MS
        renewed = reopened.paid_wallet_challenge(fixture.public, 'preset-1', 'alice.testnet')
        self.assertNotIn(renewed['nonce'], {row['nonce'] for row in accepted})


if __name__ == '__main__':
    unittest.main()
