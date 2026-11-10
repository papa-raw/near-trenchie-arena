"""Focused identity cases with synthetic adapter signatures and no chain access."""
from copy import deepcopy
from pathlib import Path
import base64
import hashlib
import hmac
import json
import secrets
import unittest

from room.identity import IdentityAuthority
from room.policy import BoundaryError, canonical_bytes, digest

_DEFS = json.loads(Path(__file__).with_name('protocol.schema.json').read_text())['$defs']


def example(name):
    return deepcopy(_DEFS[name]['examples'][0])


def encoded(raw):
    return base64.urlsafe_b64encode(raw).decode().rstrip('=')


class Bridge:
    def __init__(self, clock):
        self.clock = clock
        self.secret = secrets.token_bytes(32)
        self.evidence = example('IdentityEvidence')
        self.failure = None
        self.reads = 0

    def proof(self, request):
        field = 'proof' if request['domain'] == 'room.join.v1' else 'wallet_proof'
        request[field] = {'method_id': 'synthetic_v1', 'key_id': 'wallet_a',
                          'proof_bytes': encoded(hmac.digest(self.secret, canonical_bytes(request, exclude=(field,)), 'sha256'))}
        return request

    def resolve_identity(self, request):
        self.reads += 1
        if self.failure:
            raise OSError('unavailable')
        field = 'proof' if request['domain'] == 'room.join.v1' else 'wallet_proof'
        expected = encoded(hmac.digest(self.secret, canonical_bytes(request, exclude=(field,)), 'sha256'))
        if not hmac.compare_digest(expected, request[field]['proof_bytes']):
            return {'type': 'error', 'code': 'proof_required', 'request_id': None, 'retry_after_ms': None}
        value = deepcopy(self.evidence)
        value['owner']['checked_at'] = str(self.clock[0])
        return value


class IdentityCases(unittest.TestCase):
    def setUp(self):
        self.clock = [1900000000000]
        self.bridge = Bridge(self.clock)
        self.session_secret = secrets.token_bytes(32)
        self.session_key = example('SessionPublicKey')
        self.consumed = set()
        self.is_ready = True
        self.authority = IdentityAuthority(
            example('MainnetContext'), self.bridge, now_ms=lambda: self.clock[0],
            sign=lambda body: encoded(hashlib.sha512(body).digest()), key_id='room_key_a',
            verify_session=self.verify, proof_methods=('synthetic_v1',),
            ready=lambda: self.is_ready, consume_nonce=self.consume)

    def consume(self, nonce, expiry):
        if nonce in self.consumed:
            return False
        self.consumed.add(nonce)
        return True

    def verify(self, public_key, body, signature):
        return public_key == self.session_key and hmac.compare_digest(
            signature, encoded(hmac.digest(self.session_secret, body, 'sha512')))

    def signed(self, request):
        request['signature'] = encoded(hmac.digest(self.session_secret, canonical_bytes(request, exclude=('signature',)), 'sha512'))
        return request

    def join(self):
        self.clock[0] += 60000
        request = example('JoinRequest')
        request['challenge'] = self.authority.challenge(example('JoinChallengeRequest'))
        return self.bridge.proof(request)

    def grant(self):
        request = self.join()
        owner = self.authority.resolve(request)
        binding = example('SlotBinding')
        binding.update({k: owner[k] for k in ('account_id', 'nft_token_id', 'persona_digest', 'context')})
        return self.authority.issue_grant(binding, request['session_public_key'])

    def refused(self, operation, code=None):
        with self.assertRaises(BoundaryError) as caught:
            operation()
        if code:
            self.assertEqual(caught.exception.code, code)
        self.assertNotIn('proof_bytes', json.dumps(caught.exception.error()))

    def test_nft_proof_and_custody(self):
        for custody in (False, True):
            with self.subTest(custody=custody):
                self.bridge.evidence['owner']['ownership_kind'] = 'custody' if custody else 'owner'
                self.bridge.evidence['owner']['custody_reservation_id'] = 'hold_a' if custody else None
                request = self.join()
                owner = self.authority.resolve(request)
                self.assertEqual(owner['ownership_kind'], 'custody' if custody else 'owner')
                self.refused(lambda: self.authority.resolve(request), 'proof_required')
        for path, value in [(('owner', 'account_id'), 'other.near'),
                            (('owner', 'nft_token_id'), 'other_token'),
                            (('owner', 'persona_digest'), 'b' * 64),
                            (('play_status',), 'locked'), (('play_status',), 'sale_ready'),
                            (('play_status',), 'unknown')]:
            with self.subTest(path=path, value=value):
                self.bridge.evidence = example('IdentityEvidence')
                target = self.bridge.evidence
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = value
                self.refused(lambda: self.authority.resolve(self.join()))
        self.bridge.evidence = example('IdentityEvidence')
        self.bridge.failure = True
        self.refused(lambda: self.authority.resolve(self.join()), 'ownership_unavailable')

    def test_challenge_binding_and_expiry(self):
        for field, replacement in [('persona_digest', 'b' * 64), ('request_id', 'different'),
                                    ('session_public_key', {'algorithm': 'ed25519', 'public_key': encoded(secrets.token_bytes(32))})]:
            request = self.join()
            request[field] = replacement
            self.bridge.proof(request)
            self.refused(lambda: self.authority.resolve(request), 'proof_required')
        request = self.join()
        self.clock[0] = int(request['challenge']['expires_at'])
        self.refused(lambda: self.authority.resolve(request), 'proof_required')
        request = self.join()
        request['challenge']['nonce'] = 'fabricated'
        self.bridge.proof(request)
        self.refused(lambda: self.authority.resolve(request), 'proof_required')
        request = self.join()
        request['proof']['proof_bytes'] = 'AA'
        self.refused(lambda: self.authority.resolve(request), 'proof_required')
        request = self.join()
        request['proof']['method_id'] = 'unknown_method'
        self.refused(lambda: self.authority.resolve(request), 'proof_required')

    def test_signed_context(self):
        for field, replacement in [('room_id', 'elsewhere'), ('deployment_id', 'elsewhere'),
                                    ('authority_epoch', '2'), ('rules_hash', 'b' * 64),
                                    ('audience', 'https://elsewhere.example/room#control'),
                                    ('network_id', 'testnet'), ('contract_ids', {'nft': 'other.near', 'arena': 'arena.near'})]:
            request = self.join()
            request['context'][field] = replacement
            self.refused(lambda: self.authority.resolve(request))
        request = self.join()
        self.bridge.evidence['owner']['context']['contract_ids']['nft'] = 'other.near'
        self.refused(lambda: self.authority.resolve(request), 'context_mismatch')
        self.bridge.evidence = example('IdentityEvidence')
        request = self.join()
        request['domain'] = 'room.control.v1'
        self.refused(lambda: self.authority.resolve(request))

    def test_identity_transfer_and_session_grants(self):
        grant = self.grant()
        request = self.signed(example('IntentRequest'))
        self.assertEqual(self.authority.authenticate(request), grant['binding'])
        self.refused(lambda: self.authority.authenticate(request, token='wrong'), 'proof_required')
        for field in ('member_id', 'nft_token_id', 'slot_id', 'session_key_id'):
            changed = deepcopy(request)
            changed[field] = 'different'
            self.signed(changed)
            self.refused(lambda: self.authority.authenticate(changed))
        changed = deepcopy(request)
        changed['generation'] = '3'
        self.signed(changed)
        self.refused(lambda: self.authority.authenticate(changed), 'stale_slot')
        changed = deepcopy(request)
        changed['payload']['fighter_id'] = 'other_fighter'
        self.refused(lambda: self.authority.authenticate(changed), 'proof_required')
        self.bridge.evidence['owner']['account_id'] = 'buyer.near'
        self.refused(lambda: self.authority.authenticate(request), 'proof_required')
        self.bridge.evidence = example('IdentityEvidence')
        self.refused(lambda: self.authority.authenticate(request), 'proof_required')
        self.authority.revoke(grant['binding']['grant_id'])
        self.refused(lambda: self.authority.authenticate(request), 'proof_required')

    def test_outage_lock_expiry_and_epoch_close_authority(self):
        for mode in ('outage', 'lock', 'expiry', 'epoch', 'recovery'):
            with self.subTest(mode=mode):
                self.setUp()
                grant = self.grant()
                request = self.signed(example('IntentRequest'))
                if mode == 'outage':
                    self.bridge.failure = True
                elif mode == 'lock':
                    self.bridge.evidence['play_status'] = 'locked'
                elif mode == 'expiry':
                    self.clock[0] = int(grant['expires_at'])
                elif mode == 'epoch':
                    context = example('MainnetContext')
                    context['authority_epoch'] = '2'
                    self.authority.invalidate(context)
                else:
                    self.is_ready = False
                self.refused(lambda: self.authority.authenticate(request))
                self.bridge.failure = None
                self.bridge.evidence = example('IdentityEvidence')
                if mode in ('outage', 'lock'):
                    self.refused(lambda: self.authority.authenticate(request), 'proof_required')

    def test_durable_nonce_and_method_gates(self):
        request = self.join()
        self.authority.consume_nonce = lambda nonce, expiry: False
        self.refused(lambda: self.authority.resolve(request), 'recovery_pending')
        self.assertEqual(self.bridge.reads, 0)
        self.authority.proof_methods = frozenset()
        self.refused(lambda: self.authority.challenge(example('JoinChallengeRequest')), 'proof_required')

    def test_sale_proof_is_separate_from_play(self):
        request = example('SaleControlRequest')
        challenge_request = example('SaleChallengeRequest')
        request['challenge'] = self.authority.challenge(challenge_request)
        request['nonce'] = request['challenge']['nonce']
        request['expires_at'] = request['challenge']['expires_at']
        self.bridge.evidence['play_status'] = 'locked'
        owner = self.authority.resolve(self.bridge.proof(request))
        self.assertEqual(owner['ownership_kind'], 'owner')
        self.assertEqual(self.authority.grant_count, 0)
        self.refused(lambda: self.authority.resolve(request), 'proof_required')
        self.bridge.evidence['owner']['ownership_kind'] = 'custody'
        self.bridge.evidence['owner']['custody_reservation_id'] = 'hold_a'
        request['challenge'] = self.authority.challenge(challenge_request)
        request.update(nonce=request['challenge']['nonce'], expires_at=request['challenge']['expires_at'])
        self.refused(lambda: self.authority.resolve(self.bridge.proof(request)), 'proof_required')


    def test_private_grant_renewal_resume_and_rotation(self):
        grant = self.grant()
        grant_id = grant['binding']['grant_id']
        self.assertEqual(self.authority.grant(grant_id), grant)
        resume = {'prior_grant_id': grant_id, 'prior_generation': grant['binding']['generation'],
                  'resume_token': grant['token']}
        self.assertEqual(self.authority.authenticate_resume(resume), grant)
        changed = deepcopy(resume)
        changed['resume_token'] = 'x' * 43
        self.refused(lambda: self.authority.authenticate_resume(changed), 'proof_required')
        changed = deepcopy(resume)
        changed['prior_generation'] = '999'
        self.refused(lambda: self.authority.authenticate_resume(changed), 'stale_slot')
        self.clock[0] += 1000
        renewed = self.authority.renew(grant_id, str(self.clock[0] + 10000))
        self.assertEqual(renewed['expires_at'], str(self.clock[0] + 10000))
        self.refused(lambda: self.authority.renew(grant_id, str(self.clock[0] + 999999)), 'bad_message')
        grant['capabilities'].clear()
        self.assertTrue(self.authority.grant(grant_id)['capabilities'])
        # A new proof rotates the key/generation; stale capabilities remain revoked.
        request = self.join()
        owner = self.authority.resolve(request)
        binding = example('SlotBinding')
        binding.update(grant_id='grant_b', session_key_id='session_b', generation='3')
        replacement = self.authority.issue_grant(binding, request['session_public_key'], capabilities=('observe',))
        self.assertEqual(replacement['capabilities'], ['observe'])
        self.refused(lambda: self.authority.authenticate_resume(resume), 'proof_required')
        intent = example('IntentRequest')
        intent.update(grant_id='grant_b', session_key_id='session_b', generation='3')
        self.refused(lambda: self.authority.authenticate(self.signed(intent)), 'proof_required')

    def test_authenticated_join_retry_and_receipt_signing(self):
        request = self.join()
        owner = self.authority.resolve(request)
        self.assertEqual(self.authority.recheck(request), owner)
        changed = deepcopy(request)
        changed['declared_compute']['model'] = 'different'
        self.bridge.proof(changed)
        self.refused(lambda: self.authority.recheck(changed), 'proof_required')
        self.refused(lambda: self.authority.resolve(request), 'proof_required')
        receipt = example('Receipt')
        signed = self.authority.sign_message(receipt)
        self.assertEqual(signed['signature'], encoded(hashlib.sha512(canonical_bytes(signed, exclude=('signature',))).digest()))
        self.refused(lambda: self.authority.sign_message(example('Result')))
        self.clock[0] = int(request['challenge']['expires_at'])
        self.refused(lambda: self.authority.recheck(request), 'proof_required')

    def test_challenge_attempt_limit(self):
        for _ in range(5):
            self.authority.challenge(example('JoinChallengeRequest'))
        self.refused(lambda: self.authority.challenge(example('JoinChallengeRequest')), 'rate_limited')
        self.clock[0] += 60000
        self.authority.challenge(example('JoinChallengeRequest'))


    def test_expired_and_rotated_grants_cannot_reopen_join_retry(self):
        for mode in ('expiry', 'rotation'):
            with self.subTest(mode=mode):
                self.setUp()
                original = self.join()
                self.authority.resolve(original)
                grant = self.authority.issue_grant(example('SlotBinding'), original['session_public_key'])
                if mode == 'expiry':
                    self.clock[0] = int(grant['expires_at'])
                    self.refused(lambda: self.authority.authenticate(self.signed(example('IntentRequest'))))
                else:
                    fresh = example('JoinRequest')
                    fresh['challenge'] = self.authority.challenge(example('JoinChallengeRequest'))
                    self.authority.resolve(self.bridge.proof(fresh))
                    replacement = example('SlotBinding')
                    replacement.update(grant_id='grant_b', session_key_id='session_b', generation='3')
                    self.authority.issue_grant(replacement, fresh['session_public_key'])
                self.refused(lambda: self.authority.recheck(original), 'proof_required')


    def test_revocation_preserves_distinct_fresh_resume_proof(self):
        old = self.grant()
        fresh = example('JoinRequest')
        fresh['challenge'] = self.authority.challenge(example('JoinChallengeRequest'))
        self.authority.resolve(self.bridge.proof(fresh))
        self.authority.revoke(old['binding']['grant_id'])
        replacement = example('SlotBinding')
        replacement.update(grant_id='grant_b', session_key_id='session_b', generation='3')
        grant = self.authority.issue_grant(replacement, fresh['session_public_key'])
        self.assertEqual(grant['binding'], replacement)


if __name__ == '__main__':
    unittest.main()
