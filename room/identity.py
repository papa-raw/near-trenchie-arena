"""Wallet-neutral proof orchestration and session authority over a host bridge."""
from __future__ import annotations

from copy import deepcopy
import hmac
import secrets
from threading import RLock

from .policy import BoundaryError, CAPABILITIES, canonical_bytes, digest, validate


class IdentityAuthority:
    """Adapters own cryptography and chain reads; unknown authority always refuses.

    ``sign(bytes)`` returns the configured room's encoded signature.
    ``verify_session(public_key, bytes, signature)`` verifies only Ed25519.
    ``consume_nonce(nonce, expires_at)`` must durably consume once and return True.
    ``ready()`` includes the current recovery, ban and revocation fence. The host
    must also gate individual account/token bans before issuing or using grants.
    No wallet method is enabled unless the host explicitly supplies its tested id.
    """

    def __init__(self, context, bridge, *, now_ms, sign, verify_session, key_id,
                 proof_methods=(), ready=None, consume_nonce=None,
                 challenge_ttl_ms=60000, grant_ttl_ms=30000, room_owner_accounts=()):
        validate('MainnetContext', context)
        validate('Id', key_id)
        if not (1 <= challenge_ttl_ms <= 60000 and 1 <= grant_ttl_ms <= 60000):
            raise BoundaryError('bad_message')
        self._context = deepcopy(context)
        self.bridge = bridge
        self.now_ms = now_ms
        self.sign = sign
        self.verify_session = verify_session
        self.key_id = key_id
        for method in proof_methods:
            validate('Id', method)
        self.proof_methods = frozenset(proof_methods)
        self.ready = ready
        self.consume_nonce = consume_nonce
        self.challenge_ttl_ms = challenge_ttl_ms
        self.grant_ttl_ms = grant_ttl_ms
        self.room_owner_accounts = frozenset(room_owner_accounts)
        for account in self.room_owner_accounts:
            validate('AccountId', account)
        self._challenges = {}
        self._attempts = {}
        self._proved = {}
        self._verified = {}
        self._grants = {}
        self._lock = RLock()

    @property
    def context(self):
        return deepcopy(self._context)

    @property
    def grant_count(self):
        with self._lock:
            return len(self._grants)

    def _open(self):
        try:
            allowed = self.ready is not None and self.ready() is True
        except Exception:
            allowed = False
        if not allowed or self.consume_nonce is None:
            raise BoundaryError('recovery_pending')
        if not self.proof_methods:
            raise BoundaryError('proof_required')

    def _context_check(self, message):
        if type(message) is not dict or message.get('context') != self._context:
            raise BoundaryError('context_mismatch')

    def _signed(self, message, schema):
        try:
            message['signature'] = self.sign(canonical_bytes(message, exclude=('signature',)))
        except Exception:
            raise BoundaryError('proof_required') from None
        validate(schema, message)
        return message

    def challenge(self, request):
        self._open()
        self._context_check(request)
        purpose = request.get('purpose')
        schemas = {'join': ('JoinChallengeRequest', 'JoinChallenge'),
                   'sale_control': ('SaleChallengeRequest', 'SaleChallenge'),
                   'sale_control_lookup': ('LookupChallengeRequest', 'LookupChallenge')}
        if purpose not in schemas:
            raise BoundaryError('bad_message')
        incoming, outgoing = schemas[purpose]
        validate(incoming, request)
        now = self.now_ms()
        with self._lock:
            self._challenges = {key: value for key, value in self._challenges.items() if int(value['expires_at']) > now}
            self._proved = {key: value for key, value in self._proved.items() if value['until'] > now}
            self._verified = {key: value for key, value in self._verified.items() if value['until'] > now}
            self._attempts = {key: [t for t in attempts if now - t < 60000] for key, attempts in self._attempts.items()
                              if any(now - t < 60000 for t in attempts)}
            attempts = self._attempts.setdefault(request['account_id'], [])
            if len(attempts) >= 5 or len(self._challenges) >= 512:
                raise BoundaryError('rate_limited')
            attempts.append(now)
            challenge = deepcopy(request)
            challenge.update(challenge_id='challenge_' + secrets.token_hex(24), nonce='nonce_' + secrets.token_hex(32),
                             expires_at=str(now + self.challenge_ttl_ms), key_id=self.key_id)
            self._signed(challenge, outgoing)
            self._challenges[challenge['challenge_id']] = deepcopy(challenge)
            return challenge

    def _evidence(self, request, *, sale=False):
        try:
            evidence = self.bridge.resolve_identity(deepcopy(request))
        except Exception:
            raise BoundaryError('ownership_unavailable') from None
        if type(evidence) is dict and evidence.get('type') == 'error':
            code = evidence.get('code')
            raise BoundaryError(code if code in ('proof_required', 'banned', 'ownership_unavailable', 'recovery_pending')
                                else 'ownership_unavailable')
        try:
            validate('IdentityEvidence', evidence)
        except BoundaryError:
            raise BoundaryError('ownership_unavailable') from None
        owner = evidence['owner']
        self._context_check(owner)
        challenge = request['challenge']
        if any(owner[key] != challenge[key] for key in ('account_id', 'nft_token_id')):
            raise BoundaryError('proof_required')
        if not sale and owner['persona_digest'] != request['persona_digest']:
            raise BoundaryError('proof_required')
        age = self.now_ms() - int(owner['checked_at'])
        if age < 0 or age > 1000 or int(evidence['chain_height']) == 0:
            raise BoundaryError('ownership_unavailable')
        if sale:
            if owner['ownership_kind'] != 'owner' or evidence['sale_control_allowed'] is not True or evidence['play_status'] == 'unknown':
                raise BoundaryError('proof_required')
        elif evidence['play_status'] != 'eligible':
            raise BoundaryError('proof_required')
        return deepcopy(owner)

    def resolve(self, request):
        self._open()
        self._context_check(request)
        sale = request.get('domain') == 'room.sale-control.v1'
        schema = ('SaleControlLookup' if request.get('purpose') == 'sale_control_lookup' else 'SaleControlRequest') if sale else 'JoinRequest'
        validate(schema, request)
        request = deepcopy(request)
        challenge = request['challenge']
        self._context_check(challenge)
        proof = request['wallet_proof' if sale else 'proof']
        if proof['method_id'] not in self.proof_methods:
            raise BoundaryError('proof_required')
        fields = ('request_id', 'action', 'account_id', 'nft_token_id', 'purpose') if sale else ('request_id', 'persona_digest', 'session_public_key')
        if any(request[field] != challenge[field] for field in fields):
            raise BoundaryError('proof_required')
        if sale and any(request[field] != challenge[field] for field in ('nonce', 'expires_at')):
            raise BoundaryError('proof_required')
        if sale and request['purpose'] == 'sale_control_lookup' and request['original_digest'] != challenge['original_digest']:
            raise BoundaryError('proof_required')
        with self._lock:
            issued = self._challenges.pop(challenge['challenge_id'], None)
            if issued != challenge or int(challenge['expires_at']) <= self.now_ms():
                raise BoundaryError('proof_required')
            try:
                consumed = self.consume_nonce(challenge['nonce'], challenge['expires_at']) is True
            except Exception:
                consumed = False
            if not consumed:
                raise BoundaryError('recovery_pending')
            owner = self._evidence(request, sale=sale)
            if not sale:
                key = (owner['account_id'], owner['nft_token_id'], canonical_bytes(request['session_public_key']))
                receipt = {'owner': deepcopy(owner), 'request': request, 'until': int(challenge['expires_at'])}
                self._proved[key] = deepcopy(receipt)
                self._verified[digest(request)] = deepcopy(receipt)
            return owner

    def issue_grant(self, binding, session_public_key, *, capabilities=None):
        self._open()
        validate('SlotBinding', binding)
        validate('SessionPublicKey', session_public_key)
        self._context_check(binding)
        key = (binding['account_id'], binding['nft_token_id'], canonical_bytes(session_public_key))
        with self._lock:
            proof = self._proved.get(key)
            if proof is None or proof['until'] <= self.now_ms() or proof['owner']['persona_digest'] != binding['persona_digest']:
                raise BoundaryError('proof_required')
            if binding['grant_id'] in self._grants:
                raise BoundaryError('request_conflict')
            available = set(CAPABILITIES)
            if proof['owner']['ownership_kind'] == 'owner':
                available.add('owner_settings')
                if binding['account_id'] in self.room_owner_accounts:
                    available.add('room_moderate')
            requested = available if capabilities is None else available.intersection(capabilities)
            # One current key and generation per persona, including a reconnect.
            for grant_id, old in list(self._grants.items()):
                if old['binding']['nft_token_id'] == binding['nft_token_id']:
                    if int(binding['generation']) <= int(old['binding']['generation']):
                        raise BoundaryError('stale_slot')
                    self.revoke(grant_id)
            grant = {'binding': deepcopy(binding), 'session_public_key': deepcopy(session_public_key),
                     'capabilities': sorted(requested), 'expires_at': str(self.now_ms() + self.grant_ttl_ms),
                     'token': secrets.token_urlsafe(32)}
            self._grants[binding['grant_id']] = dict(deepcopy(grant), request=deepcopy(proof['request']), owner=deepcopy(proof['owner']))
            self._verified[digest(proof['request'])]['grant_id'] = binding['grant_id']
            self._proved.pop(key, None)
            return grant

    def authenticate(self, request, token=None):
        self._open()
        self._context_check(request)
        kinds = {'observe': 'ObserveRequest', 'intent': 'IntentRequest', 'prediction': 'PredictionRequest',
                 'renew': 'RenewRequest', 'leave': 'LeaveRequest', 'authenticate': 'ControlAuthenticate',
                 'owner_control': 'OwnerRequest'}
        if request.get('kind') not in kinds:
            raise BoundaryError('bad_message')
        validate(kinds[request['kind']], request)
        with self._lock:
            grant_id = request['grant_id']
            grant = self._grants.get(grant_id)
            if grant is None:
                raise BoundaryError('proof_required')
            if int(grant['expires_at']) <= self.now_ms():
                self.revoke(grant_id)
                raise BoundaryError('proof_required')
            binding = grant['binding']
            for field in ('grant_id', 'session_key_id', 'member_id', 'nft_token_id', 'persona_digest', 'slot_id', 'generation'):
                if request[field] != binding[field]:
                    raise BoundaryError('stale_slot')
            supplied_token = request['token'] if request['kind'] in ('authenticate', 'owner_control') else token
            if supplied_token is not None and (type(supplied_token) is not str or not hmac.compare_digest(supplied_token, grant['token'])):
                raise BoundaryError('proof_required')
            capability = request['kind']
            if capability == 'owner_control':
                # Self-consent belongs to admitted gameplay, including custody.
                # Reading one's state grants neither spending nor moderation.
                capability = {
                    'snapshot': 'observe',
                    'accept_terms': 'intent',
                    'accept_proposal': 'intent',
                    'decline_proposal': 'intent',
                    'save_limit': 'owner_settings',
                    'remove_member': 'room_moderate',
                    'block_member': 'room_moderate',
                    'lift_block': 'room_moderate',
                }[request['action']]
            if capability != 'authenticate' and capability not in grant['capabilities']:
                raise BoundaryError('proof_required')
            try:
                verified = self.verify_session(deepcopy(grant['session_public_key']),
                                               canonical_bytes(request, exclude=('signature',)), request['signature']) is True
            except Exception:
                verified = False
            if not verified:
                raise BoundaryError('proof_required')
            try:
                owner = self._evidence(grant['request'])
                if any(owner[key] != grant['owner'][key] for key in
                       ('account_id', 'nft_token_id', 'persona_digest', 'ownership_kind', 'custody_reservation_id')):
                    raise BoundaryError('proof_required')
            except BoundaryError:
                self.revoke(grant_id)
                raise
            return deepcopy(binding)

    def sign_message(self, message):
        """Sign only closed receipt-domain objects using the room receipt key."""
        self._open()
        self._context_check(message)
        candidate = deepcopy(message)
        candidate.update(key_id=self.key_id, signature='A' * 86)
        schemas = ('Receipt', 'JoinAccepted', 'QueueStatus', 'ControlChallenge',
                   'ControlReady', 'LifeNotice', 'SaleAcknowledgement', 'OwnerResponse')
        for schema in schemas:
            try:
                validate(schema, candidate)
            except BoundaryError:
                continue
            return self._signed(candidate, schema)
        raise BoundaryError('bad_message')

    def grant(self, grant_id):
        """Trusted in-process view; never put this object on a public route."""
        self._open()
        with self._lock:
            stored = self._grants.get(grant_id)
            if stored is None:
                raise BoundaryError('proof_required')
            if int(stored['expires_at']) <= self.now_ms():
                self.revoke(grant_id)
                raise BoundaryError('proof_required')
            return {key: deepcopy(stored[key]) for key in
                    ('binding', 'session_public_key', 'capabilities', 'expires_at', 'token')}

    def recheck(self, request):
        """Reauthenticate exact accepted join bytes, without a second nonce effect.

        Only the original bounded proof window is eligible. This is used before
        a service returns its existing queue/reservation receipt, never as a new
        wallet proof or a way to extend an expired challenge.
        """
        self._open()
        self._context_check(request)
        validate('JoinRequest', request)
        with self._lock:
            prior = self._verified.get(digest(request))
            if prior is None or prior['until'] <= self.now_ms():
                raise BoundaryError('proof_required')
            prior_grant = prior.get('grant_id')
            if prior_grant is not None:
                self.grant(prior_grant)
            try:
                owner = self._evidence(prior['request'])
                if any(owner[key] != prior['owner'][key] for key in
                       ('account_id', 'nft_token_id', 'persona_digest', 'ownership_kind', 'custody_reservation_id')):
                    raise BoundaryError('proof_required')
            except BoundaryError:
                self._verified.pop(digest(request), None)
                if prior_grant is not None:
                    self.revoke(prior_grant)
                raise
            key = (owner['account_id'], owner['nft_token_id'], canonical_bytes(request['session_public_key']))
            self._proved[key] = dict(deepcopy(prior), owner=deepcopy(owner))
            return owner

    def authenticate_resume(self, resume_binding):
        self._open()
        validate('ResumeBinding', resume_binding)
        with self._lock:
            grant_id = resume_binding['prior_grant_id']
            grant = self.grant(grant_id)
            if not hmac.compare_digest(resume_binding['resume_token'], grant['token']):
                raise BoundaryError('proof_required')
            if resume_binding['prior_generation'] != grant['binding']['generation']:
                raise BoundaryError('stale_slot')
            stored = self._grants[grant_id]
            try:
                owner = self._evidence(stored['request'])
                if any(owner[key] != stored['owner'][key] for key in
                       ('account_id', 'nft_token_id', 'persona_digest', 'ownership_kind', 'custody_reservation_id')):
                    raise BoundaryError('proof_required')
            except BoundaryError:
                self.revoke(grant_id)
                raise
            return grant

    def renew(self, grant_id, expires_at):
        """Server-only renewal, after slot/generation and security checks."""
        validate('U64', expires_at)
        with self._lock:
            grant = self.grant(grant_id)
            now = self.now_ms()
            if not now < int(expires_at) <= now + self.grant_ttl_ms:
                raise BoundaryError('bad_message')
            self.authenticate_resume({'prior_grant_id': grant_id,
                                      'prior_generation': grant['binding']['generation'],
                                      'resume_token': grant['token']})
            self._grants[grant_id]['expires_at'] = expires_at
            return self.grant(grant_id)

    def capabilities(self, grant_id):
        return tuple(self.grant(grant_id)['capabilities'])

    def revoke(self, grant_id):
        """Immediate local denial; the caller persists its security transition."""
        with self._lock:
            grant = self._grants.pop(grant_id, None)
            if grant is not None:
                self._verified.pop(digest(grant['request']), None)
                key = (grant['binding']['account_id'], grant['binding']['nft_token_id'],
                       canonical_bytes(grant['session_public_key']))
                proof = self._proved.get(key)
                if proof is not None and digest(proof['request']) == digest(grant['request']):
                    self._proved.pop(key, None)

    def invalidate(self, context):
        """Install a strictly newer trusted epoch after external reconciliation."""
        validate('MainnetContext', context)
        with self._lock:
            if int(context['authority_epoch']) <= int(self._context['authority_epoch']):
                raise BoundaryError('context_mismatch')
            self._context = deepcopy(context)
            self._challenges.clear()
            self._grants.clear()
            self._proved.clear()
            self._verified.clear()
            self._attempts.clear()
