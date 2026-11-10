"""Read-only result verification and destination-scoped idempotent settlement.

The host supplies signing/verification and the capped writer adapter. This module
has no private keys, transaction credentials, network client or mint capability.
"""
from __future__ import annotations

import base64
from collections import OrderedDict
import copy
import threading

from .ledger import OrderedStore, Refusal, canonical, digest, sealed_hash, validate, verify_sealed


def _unsigned(message):
    return {key: value for key, value in message.items() if key != 'signature'}


def _signature_bytes(value):
    validate('Signature', value)
    try:
        raw = base64.b64decode(value + '==', altchars=b'-_', validate=True)
    except ValueError:
        raise Refusal('proof_required') from None
    if len(raw) != 64 or base64.urlsafe_b64encode(raw).decode().rstrip('=') != value:
        raise Refusal('proof_required')
    return raw


class ResultAuthority:
    """Pinned Ed25519 adapters: sign(bytes)->64 bytes; verify(key_id,bytes,bytes)->bool.

    The trusted verifier pins Ed25519 keys and never accepts an algorithm supplied
    in a message. key_allowed is a live revocation/epoch check, not a saved list.
    Its failure denies authority before any batch-cache lookup.
    """

    def __init__(self, context, key_id, signer, verifier, key_allowed):
        validate('Context', context)
        validate('Id', key_id)
        contracts = context['contract_ids']
        destination = ('near:mainnet:' + contracts['arena'] + ':post_batch'
                       if context['network_id'] == 'mainnet' else
                       'near:testnet:' + contracts['market'] + ':resolve')
        if context['audience'] != destination:
            raise Refusal('context_mismatch')
        self.context = copy.deepcopy(context)
        self.key_id = key_id
        self.signer = signer
        self.verifier = verifier
        self.key_allowed = key_allowed

    def _allowed(self, key_id):
        try:
            allowed = self.key_allowed(key_id)
        except Exception:
            raise Refusal('proof_required') from None
        if allowed is not True:
            raise Refusal('proof_required')

    def _sign(self, schema, body):
        body = copy.deepcopy(body)
        body['key_id'] = self.key_id
        body['signature'] = 'A' * 86
        validate(schema, body)
        if body['context'] != self.context:
            raise Refusal('context_mismatch')
        self._allowed(self.key_id)
        try:
            signature = self.signer(canonical(_unsigned(body)))
        except Exception:
            raise Refusal('proof_required') from None
        if not isinstance(signature, bytes) or len(signature) != 64:
            raise Refusal('proof_required')
        body['signature'] = base64.urlsafe_b64encode(signature).decode().rstrip('=')
        self._verify(schema, body)
        return body

    def _verify(self, schema, message):
        validate(schema, message)
        if message['context'] != self.context:
            raise Refusal('context_mismatch')
        self._allowed(message['key_id'])
        try:
            valid = self.verifier(message['key_id'], canonical(_unsigned(message)),
                                  _signature_bytes(message['signature']))
        except Exception:
            raise Refusal('proof_required') from None
        if valid is not True:
            raise Refusal('proof_required')

    def sign_record(self, record, batch_id, replay):
        record = verify_sealed(record, replay)
        validate('Id', batch_id)
        if record['rules_hash'] != self.context['rules_hash']:
            raise Refusal('context_mismatch')
        body = {key: copy.deepcopy(value) for key, value in record.items()
                if key not in ('seed', 'input_events')}
        body.update(domain='room.result.v1', context=copy.deepcopy(self.context),
                    grant_id=None, session_key_id=None, batch_id=batch_id)
        return self._sign('Result', body)

    def verify_result(self, result):
        """Require the current context and allowlisted room signature before use."""
        result = copy.deepcopy(result)
        self._verify('Result', result)
        if (result['rules_hash'] != self.context['rules_hash'] or
                result['sealed_result_hash'] != sealed_hash(result)):
            raise Refusal('bad_message')
        return result

    def batch_id(self, segment_id):
        """One identity per room/deployment/segment across retries and key epochs."""
        validate('Id', segment_id)
        return 'batch_' + digest(dict(room_id=self.context['room_id'],
                                      deployment_id=self.context['deployment_id'], segment_id=segment_id))

    def acknowledgement(self, result, state, chain_receipt):
        self.verify_result(result)
        body = dict(domain='room.receipt.v1', context=copy.deepcopy(self.context),
                    grant_id=None, session_key_id=None, batch_id=result['batch_id'],
                    result_digest=digest(_unsigned(result)), state=state,
                    chain_receipt=copy.deepcopy(chain_receipt), message_domain='room.result.v1')
        return self._sign('BatchAcknowledgement', body)


class BatchWriter:
    """Durable pending work around a host-owned, atomically idempotent writer.

    bridge.lookup(context, batch_id) returns None for unknown status, {state:
    'missing'} for known absence, or {state: 'pending'|'confirmed'|'failed',
    digest: sealed_result_hash, chain_receipt: object|null}. bridge.submit(result)
    atomically reserves/checks that same batch id/digest at its destination and
    retries an unfinished child hop. It must apply rows/counters at most once.
    Merely sending an ordinary non-idempotent transaction cannot implement this
    interface. No transaction is constructed here. Writer credentials belong to
    that separate adapter, never to ResultAuthority.
    """

    def __init__(self, path, authority, bridge):
        self.authority = authority
        self.bridge = bridge
        identity = {key: value for key, value in authority.context.items() if key != 'authority_epoch'}
        self.store = OrderedStore(path, identity)

    @staticmethod
    def _binding(result):
        return dict(batch_id=result['batch_id'], segment_id=result['segment_id'],
                    digest=result['sealed_result_hash'])

    def submit(self, result):
        result = self.authority.verify_result(result)
        self._expected_id(result)
        binding = self._binding(result)
        with self.store.transaction() as (connection, rows):
            if any(row['kind'] == 'batch' and
                   (row['data']['batch_id'] == binding['batch_id'] or
                    row['data']['segment_id'] == binding['segment_id']) for row in rows):
                raise Refusal('request_conflict')
            # Commit the original identity before calling a possibly failing host.
            self.store.add(connection, rows, 'batch', binding)
        return self._drive(result)

    def retry(self, result):
        """Fresh current-epoch authorization, same original batch and sealed digest."""
        result = self.authority.verify_result(result)
        self._expected_id(result)
        binding = self._binding(result)
        with self.store.transaction() as (_, rows):
            existing = next((row['data'] for row in rows if row['kind'] == 'batch' and
                             row['data']['batch_id'] == binding['batch_id']), None)
            if existing != binding:
                raise Refusal('request_conflict')
        return self._drive(result)

    def _expected_id(self, result):
        # An older local backup cannot allow a new alias for a previously posted segment.
        if result['batch_id'] != self.authority.batch_id(result['segment_id']):
            raise Refusal('request_conflict')

    def _drive(self, result):
        with self.store.transaction() as (connection, rows):
            self.authority.verify_result(result)
            batch_id = result['batch_id']
            prior = next((row['data'] for row in reversed(rows) if row['kind'] == 'ack' and
                          row['data']['batch_id'] == batch_id), None)
            try:
                status = self.bridge.lookup(copy.deepcopy(self.authority.context), batch_id)
            except Exception:
                raise Refusal('recovery_pending') from None
            status = self._status(status, result)
            if prior is not None and prior['state'] == 'confirmed' and status['state'] != 'confirmed':
                raise Refusal('recovery_pending')
            if status['state'] in ('missing', 'pending'):
                try:
                    status = self._status(self.bridge.submit(copy.deepcopy(result)), result)
                except Refusal:
                    raise
                except Exception:
                    raise Refusal('recovery_pending') from None
            if status['state'] == 'missing':
                raise Refusal('recovery_pending')
            if (prior is not None and prior['state'] == status['state'] and
                    prior['result_digest'] == digest(_unsigned(result)) and
                    prior['context'] == self.authority.context and
                    prior['chain_receipt'] == status['chain_receipt']):
                return copy.deepcopy(prior)
            acknowledgement = self.authority.acknowledgement(result, status['state'], status['chain_receipt'])
            self.store.add(connection, rows, 'ack', acknowledgement)
            return acknowledgement

    @staticmethod
    def _status(status, result):
        if not isinstance(status, dict):
            raise Refusal('recovery_pending')
        state = status.get('state')
        if state == 'missing' and set(status) == {'state'}:
            return status
        if (state not in ('pending', 'confirmed', 'failed') or
                set(status) != {'state', 'digest', 'chain_receipt'}):
            raise Refusal('recovery_pending')
        if status['digest'] != result['sealed_result_hash']:
            raise Refusal('request_conflict')
        if state == 'confirmed':
            validate('ChainReceipt', status['chain_receipt'])
        elif status['chain_receipt'] is not None:
            raise Refusal('recovery_pending')
        return copy.deepcopy(status)


class ResultReader:
    """Read port for the service; the replay implementation remains host-owned."""

    def __init__(self, ledger, authority, replay):
        self.ledger = ledger
        self.authority = authority
        self.replay = replay
        self._verified = OrderedDict()
        self._verifying = set()
        self._lock = threading.Lock()

    def result(self, segment_id):
        record = self.ledger.sealed(segment_id)
        validate('SealedRecord', record)
        if record['segment_id'] != segment_id:
            raise Refusal('bad_message')
        key = (segment_id, record['sealed_result_hash'])
        source_hash = digest(record)
        with self._lock:
            cached = self._verified.get(key)
            if cached is not None and cached[0] == source_hash:
                self._verified.move_to_end(key)
                outcome = copy.deepcopy(cached[1])
            else:
                cached = None
                if key in self._verifying:
                    raise Refusal('rate_limited')
                self._verifying.add(key)
        if cached is not None:
            # Recheck the seal and sign under current context/key authority;
            # only the already-agreed engine outcome is reused.
            return self.authority.sign_record(record, self.authority.batch_id(segment_id),
                                              lambda readonly: outcome)
        try:
            def replay(readonly):
                nonlocal outcome
                outcome = copy.deepcopy(self.replay(readonly))
                return outcome
            result = self.authority.sign_record(record, self.authority.batch_id(segment_id), replay)
            with self._lock:
                # Cache only successful agreement, bounded independently of
                # segment history. Full source hashing rejects damaged restores.
                self._verified[key] = (source_hash, outcome)
                self._verified.move_to_end(key)
                while len(self._verified) > 128:
                    self._verified.popitem(last=False)
            return result
        finally:
            with self._lock:
                self._verifying.discard(key)
