"""Focused persistence, result and recovery contracts; no network or chain writes."""
from __future__ import annotations

import copy
import importlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest


def example(name):
    schema = json.loads(Path(__file__).with_name('protocol.schema.json').read_text())
    return copy.deepcopy(schema['$defs'][name]['examples'][0])


class EphemeralSigner:
    """An external Ed25519 provider, with disposable generated keys only."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.private = self.directory / 'private.pem'
        self.public = self.directory / 'public.pem'
        self.run('genpkey', '-algorithm', 'ED25519', '-out', str(self.private))
        self.run('pkey', '-in', str(self.private), '-pubout', '-out', str(self.public))

    def run(self, *args):
        return subprocess.run(['openssl', *args], capture_output=True, check=True).stdout

    def sign(self, data):
        source = self.directory / 'message'
        source.write_bytes(data)
        return self.run('pkeyutl', '-sign', '-rawin', '-inkey', str(self.private), '-in', str(source))

    def verify(self, key_id, data, signature):
        if key_id != 'key_a':
            return False
        source = self.directory / 'message'
        signature_file = self.directory / 'signature'
        source.write_bytes(data)
        signature_file.write_bytes(signature)
        result = subprocess.run(['openssl', 'pkeyutl', '-verify', '-rawin', '-pubin',
                                 '-inkey', str(self.public), '-in', str(source),
                                 '-sigfile', str(signature_file)], capture_output=True)
        return result.returncode == 0


class RecoveryCases(unittest.TestCase):
    def setUp(self):
        self.assertTrue(Path(__file__).with_name('ledger.py').exists(), 'ordered record is absent')
        self.assertTrue(Path(__file__).with_name('results.py').exists(), 'result authority is absent')
        package = __package__ or 'room'
        self.l = importlib.import_module(package + '.ledger')
        self.r = importlib.import_module(package + '.results')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.context = example('MainnetContext')
        self.binding = example('SlotBinding')
        self.binding['context'] = copy.deepcopy(self.context)
        self.allowed = True
        self.authorize = lambda binding: self.allowed
        self.ledger = self.l.Ledger(self.root / 'ledger.db', self.context, self.authorize)

    def refuse(self, code, call):
        with self.assertRaises(self.l.Refusal) as caught:
            call()
        self.assertEqual(caught.exception.code, code)

    def pick(self):
        request = example('PredictionRequest')
        request.update({k: copy.deepcopy(v) for k, v in self.binding.items()
                        if k in request})
        return request

    def authority(self, context=None):
        signer_dir = self.root / 'keys'
        signer_dir.mkdir(exist_ok=True)
        signer = EphemeralSigner(signer_dir)
        context = copy.deepcopy(context or example('Result')['context'])
        return self.r.ResultAuthority(context, 'key_a', signer.sign, signer.verify,
                                      lambda key_id: key_id == 'key_a')

    def record(self, number=0):
        """A deterministic host fixture: replay derives state from effective inputs."""
        digest = self.l.digest
        pick = self.pick()
        life_id = 'life_' + str(number)
        pick['life_id'] = life_id
        lock = dict(life_id=life_id, lock_ref='lock_' + str(number), state='prediction',
                    prediction_hash=digest({k: v for k, v in pick.items() if k != 'signature'}),
                    ledger_index='1', locked_before_start=True)
        event = example('ReplayPredictionLockEvent')
        event.update(index='1', tick='0', life_id=life_id)
        event['payload']['prediction_lock'] = lock
        start = example('ReplayLifeStartEvent')
        start.update(index='2', tick='0', life_id=life_id, payload=lock)
        events = []
        previous = '0' * 64
        for event in (event, start):
            event['record_hash'] = self.l.replay_event_hash(previous, event)
            previous = event['record_hash']
            events.append(event)
        life = example('LifeRecord')
        life.update(life_id=life_id, prediction_lock=lock, ko_count=str(number % 4))
        predictions = {lock['lock_ref']: {k: v for k, v in pick.items() if k != 'signature'}}
        record = dict(segment_id='segment_' + str(number), life_ids=[life_id],
                      nft_token_ids=[life['nft_token_id']], inputs_hash=digest(events),
                      seed_hash=digest(str(number)), rules_hash=self.context['rules_hash'],
                      final_state_hash=digest({'seed': str(number), 'kos': str(number % 4)}),
                      predictions_log_hash=self.l.prediction_log_hash(events, predictions),
                      completed=True, tick_count='1200', lives=[life], seed=str(number),
                      input_events=events)
        record['sealed_result_hash'] = self.l.sealed_hash(record)

        def replay(readonly):
            seed = int(readonly['seed'])
            derived = copy.deepcopy(life)
            derived['ko_count'] = str(seed % 4)
            return dict(final_state_hash=digest({'seed': str(seed), 'kos': str(seed % 4)}),
                        lives=[derived], predictions=copy.deepcopy(predictions))
        return record, replay

    def test_prediction_lock(self):
        ledger, binding, pick = self.ledger, self.binding, self.pick()
        reservation = ledger.reserve_life(binding, 'life_a', '100')
        self.assertEqual(reservation['prediction_deadline'], '100')
        self.refuse('prediction_closed', lambda: ledger.activate(binding, 'life_a', 'unknown', '0'))
        invalid = copy.deepcopy(pick)
        invalid['payload']['spread_bps']['one'] += 1
        self.refuse('bad_message', lambda: ledger.lock_prediction(binding, 'life_a', invalid, '1'))
        lock = ledger.lock_prediction(binding, 'life_a', pick, '2')
        self.assertEqual(lock, ledger.lock_prediction(binding, 'life_a', pick, '3'))
        rewritten = copy.deepcopy(pick)
        rewritten['payload']['zero_bps'] = 4000
        self.refuse('request_conflict', lambda: ledger.lock_prediction(binding, 'life_a', rewritten, '3'))
        changed = copy.deepcopy(pick)
        changed['sequence'] = '2'
        self.refuse('prediction_closed', lambda: ledger.lock_prediction(binding, 'life_a', changed, '3'))
        rotated = copy.deepcopy(binding)
        rotated.update(generation='3', grant_id='new_grant', session_key_id='new_session')
        later = copy.deepcopy(changed)
        later.update({k: v for k, v in rotated.items() if k in later})
        self.refuse('prediction_closed', lambda: ledger.lock_prediction(rotated, 'life_a', later, '3'))
        wrong_life = copy.deepcopy(pick)
        wrong_life['life_id'] = 'another'
        self.refuse('stale_slot', lambda: ledger.lock_prediction(binding, 'another', wrong_life, '4'))
        self.allowed = False
        self.refuse('stale_slot', lambda: ledger.lock_prediction(binding, 'life_a', pick, '4'))
        self.allowed = True
        ledger.activate(binding, 'life_a', lock['lock_ref'], '5')
        restored = self.l.Ledger(self.root / 'ledger.db', self.context, self.authorize)
        self.assertEqual(restored.prediction_lock('life_a'), lock)
        self.refuse('prediction_closed', lambda: restored.lock_prediction(binding, 'life_a', changed, '6'))
        ledger.reserve_life(binding, 'life_b', '100')
        self.refuse('prediction_closed', lambda: ledger.lock_prediction(binding, 'life_b', None, '99'))
        no_pick = ledger.lock_prediction(binding, 'life_b', None, '100')
        self.assertEqual((no_pick['state'], no_pick['prediction_hash']), ('none', None))
        late = copy.deepcopy(pick)
        late['life_id'] = 'life_b'
        self.refuse('prediction_closed', lambda: ledger.lock_prediction(binding, 'life_b', late, '101'))
        page = ledger.page()
        kinds = [event['kind'] for event in page['events']]
        self.assertLess(kinds.index('prediction_lock'), kinds.index('life_start'))
        ledger.activate(binding, 'life_b', no_pick['lock_ref'], '10')
        ledger.reserve_life(binding, 'life_c', '100')
        late['life_id'] = 'life_c'
        self.refuse('prediction_closed', lambda: ledger.lock_prediction(binding, 'life_c', late, '101'))
        backdated = copy.deepcopy(late)
        backdated['sent_at'] = '99'
        self.refuse('bad_message', lambda: ledger.lock_prediction(binding, 'life_c', backdated, '101'))

    def test_sealed_result(self):
        authority = self.authority()
        for number in range(20):
            with self.subTest(segment=number):
                record, replay = self.record(number)
                sealed = self.ledger.seal(record, replay)
                result = authority.sign_record(sealed, 'batch_' + str(number), replay)
                authority.verify_result(result)
                self.assertEqual(result['final_state_hash'], replay(record)['final_state_hash'])
                self.assertEqual(result['sealed_result_hash'], record['sealed_result_hash'])
                self.l.validate('Result', result)
                page = self.ledger.replay_page(record['segment_id'])
                self.l.validate('ReplayPage', page)
                damaged = copy.deepcopy(record)
                damaged['input_events'][0]['tick'] = '1'
                self.refuse('bad_message', lambda: authority.sign_record(damaged, 'damaged', replay))
                interrupted = copy.deepcopy(record)
                interrupted['completed'] = False
                self.refuse('bad_message', lambda: authority.sign_record(interrupted, 'cut', replay))
        connection = sqlite3.connect(self.root / 'ledger.db')
        self.addCleanup(connection.close)
        with self.assertRaises(sqlite3.IntegrityError):
            connection.execute("UPDATE records SET data='{}' WHERE position=1")
        connection.rollback()
        page = self.ledger.page()
        self.assertEqual(page['page_hash'], self.l.digest(page['events']))
        self.l.validate('LedgerPage', page)

    def test_forged_result(self):
        authority = self.authority()
        record, replay = self.record()
        result = authority.sign_record(record, 'batch_a', replay)
        for field, value in [('key_id', 'unknown'), ('nft_token_ids', ['changed']),
                             ('final_state_hash', 'f' * 64), ('signature', 'A' * 86),
                             ('domain', 'room.receipt.v1'), ('completed', False)]:
            with self.subTest(field=field):
                damaged = copy.deepcopy(result)
                damaged[field] = value
                self.refuse_any(lambda: authority.verify_result(damaged))
        bad_replay = lambda record: dict(final_state_hash='f' * 64, lives=[], predictions={})
        self.refuse('bad_message', lambda: authority.sign_record(record, 'bad', bad_replay))
        damaged = copy.deepcopy(record)
        damaged['input_events'].reverse()
        damaged['inputs_hash'] = self.l.digest(damaged['input_events'])
        damaged['sealed_result_hash'] = self.l.sealed_hash(damaged)
        self.refuse('bad_message', lambda: authority.sign_record(damaged, 'order', replay))
        def changed_forecast(record):
            outcome = replay(record)
            forecast = next(iter(outcome['predictions'].values()))
            forecast['payload']['zero_bps'] = 4000
            return outcome
        self.refuse('bad_message', lambda: authority.sign_record(record, 'forecast', changed_forecast))
        authority.key_allowed = lambda key_id: False
        self.refuse('proof_required', lambda: authority.verify_result(result))

    def refuse_any(self, call):
        with self.assertRaises(self.l.Refusal):
            call()

    def test_signed_context(self):
        schema = json.loads(Path(__file__).with_name('protocol.schema.json').read_text())
        for vector in schema['x-signing-examples']:
            unsigned = copy.deepcopy(vector['message'])
            if vector['exclude'] is not None:
                unsigned.pop(vector['exclude'])
            self.assertEqual(self.l.canonical(unsigned).decode(), vector['canonical_utf8'])
            self.assertEqual(self.l.digest(unsigned), vector['sha256'])
        self.assertEqual(self.l.canonical('\b\n\t'), b'"\\u0008\\u000a\\u0009"')
        self.refuse('bad_message', lambda: self.l.canonical(float('nan')))
        self.refuse('bad_message', lambda: self.l.canonical('\ud800'))
        authority = self.authority()
        record, replay = self.record()
        result = authority.sign_record(record, 'batch_a', replay)
        for field, value in [('room_id', 'other'), ('deployment_id', 'other'),
                             ('authority_epoch', '2'), ('rules_hash', 'b' * 64),
                             ('network_id', 'testnet'), ('contract_ids', {'market': 'market.testnet'}),
                             ('audience', 'near:mainnet:else.near:post_batch')]:
            with self.subTest(field=field):
                target = copy.deepcopy(result)
                target['context'][field] = value
                self.refuse_any(lambda: authority.verify_result(target))
                other_context = copy.deepcopy(authority.context)
                other_context[field] = value
                other = self.r.ResultAuthority.__new__(self.r.ResultAuthority)
                other.__dict__.update(authority.__dict__)
                other.context = other_context
                self.refuse('context_mismatch', lambda: other.verify_result(result))
        test_context = example('Result')['context']
        test_context.update(network_id='testnet', contract_ids={'market': 'market.testnet'},
                            audience='near:testnet:market.testnet:resolve')
        resolver = self.authority(test_context)
        resolved = resolver.sign_record(record, 'batch_a', replay)
        self.assertEqual(resolved['sealed_result_hash'], result['sealed_result_hash'])
        resolver.verify_result(resolved)
        self.refuse('context_mismatch', lambda: resolver.verify_result(result))

    def test_pending_retry(self):
        authority = self.authority()
        record, replay = self.record()
        batch_id = authority.batch_id(record['segment_id'])
        result = authority.sign_record(record, batch_id, replay)
        bridge = BatchFixture()
        writer = self.r.BatchWriter(self.root / 'batches.db', authority, bridge)
        ack = writer.submit(result)
        self.assertEqual(ack['state'], 'pending')
        self.assertIsNone(ack['chain_receipt'])
        backup = self.root / 'pending-backup.db'
        shutil.copyfile(self.root / 'batches.db', backup)
        self.refuse('request_conflict', lambda: writer.submit(result))
        bridge.hop_ready = True
        writer = self.r.BatchWriter(self.root / 'batches.db', authority, bridge)
        ack = writer.retry(result)
        self.assertEqual(ack['state'], 'confirmed')
        self.assertEqual(bridge.effects, 1)
        self.assertEqual(writer.retry(result), ack)
        self.assertEqual(bridge.effects, 1)
        # Restore an older, valid local database after the remote child hop succeeded.
        shutil.copyfile(backup, self.root / 'batches.db')
        current_context = copy.deepcopy(authority.context)
        current_context['authority_epoch'] = '2'
        current_authority = self.authority(current_context)
        current_result = current_authority.sign_record(record, batch_id, replay)
        writer = self.r.BatchWriter(self.root / 'batches.db', current_authority, bridge)
        self.refuse('context_mismatch', lambda: writer.retry(result))
        self.assertEqual(writer.retry(current_result)['state'], 'confirmed')
        self.assertEqual(bridge.effects, 1)
        crash_bridge = BatchFixture()
        crash_bridge.hop_ready = True
        crash_bridge.crash_after_publish = True
        crash_writer = self.r.BatchWriter(self.root / 'crashed-batches.db', current_authority, crash_bridge)
        self.refuse('recovery_pending', lambda: crash_writer.submit(current_result))
        self.assertEqual(crash_bridge.effects, 1)
        self.assertEqual(crash_writer.retry(current_result)['state'], 'confirmed')
        self.assertEqual(crash_bridge.effects, 1)
        alias = current_authority.sign_record(record, 'different_batch', replay)
        self.refuse('request_conflict', lambda: writer.submit(alias))
        bridge.unknown = True
        other_record, other_replay = self.record(1)
        other = current_authority.sign_record(other_record, current_authority.batch_id(other_record['segment_id']), other_replay)
        self.refuse('recovery_pending', lambda: writer.submit(other))
        self.assertEqual(bridge.effects, 1)

    def test_leave_mid_life(self):
        ledger, binding = self.ledger, self.binding
        ledger.reserve_life(binding, 'life_a', '100')
        lock = ledger.lock_prediction(binding, 'life_a', self.pick(), '1')
        ledger.activate(binding, 'life_a', lock['lock_ref'], '2')
        ack = ledger.release(binding, '7', '3')
        self.assertTrue(ack['revoked'])
        self.assertEqual(ledger.release(binding, '7', '4'), ack)
        self.refuse('stale_slot', lambda: ledger.activate(binding, 'life_a', lock['lock_ref'], '4'))
        self.assertEqual(ledger.prediction_lock('life_a'), lock)
        self.assertEqual([e['kind'] for e in ledger.page()['events']].count('leave'), 1)

    def test_transfer_after_pending_leave(self):
        for locked, rotated in ((False, False), (True, False), (True, True)):
            with self.subTest(locked=locked, rotated=rotated):
                path = self.root / f'transfer-{locked}-{rotated}.db'
                ledger = self.l.Ledger(path, self.context, self.authorize)
                seller = copy.deepcopy(self.binding)
                ledger.reserve_life(seller, 'old_life', '100')
                pick = self.pick()
                pick['life_id'] = 'old_life'
                lock = ledger.lock_prediction(seller, 'old_life', pick, '1') if locked else None
                self.refuse('request_conflict', lambda: ledger.reserve_life(seller, 'extra_life', '200'))
                if rotated:
                    seller.update(grant_id='rotated_grant', session_key_id='rotated_session', generation='3')
                    self.assertEqual(ledger.reserve_life(seller, 'old_life', '999')['prediction_deadline'], '100')
                ledger.release(seller, '7', '2')
                with ledger.store.transaction() as (_, rows):
                    history = copy.deepcopy(rows)
                ledger = self.l.Ledger(path, self.context, self.authorize)
                buyer = copy.deepcopy(seller)
                buyer.update(account_id='buyer.near', member_id='buyer', grant_id='buyer_grant',
                             session_key_id='buyer_session', generation='4')
                self.refuse('stale_slot', lambda: ledger.reserve_life(buyer, 'old_life', '200'))
                reserved = ledger.reserve_life(buyer, 'new_life', '200')
                self.assertEqual(reserved['binding'], buyer)
                self.assertEqual(ledger.reserve_life(buyer, 'new_life', '999'), reserved)
                self.refuse('request_conflict', lambda: ledger.reserve_life(buyer, 'extra_life', '200'))
                self.assertEqual(ledger.prediction_lock('old_life'), lock)
                with ledger.store.transaction() as (_, rows):
                    self.assertEqual(rows[:len(history)], history)
                # Even a freshly eligible former owner cannot revive the superseded life.
                former = copy.deepcopy(seller)
                former.update(grant_id='former_grant', session_key_id='former_session', generation='5')
                self.refuse('stale_slot', lambda: ledger.reserve_life(former, 'old_life', '200'))
                self.refuse('stale_slot', lambda: ledger.lock_prediction(former, 'old_life', None, '200'))
                self.refuse('stale_slot', lambda: ledger.activate(former, 'old_life',
                                                                lock['lock_ref'] if lock else 'absent', '3'))
                new_lock = ledger.lock_prediction(buyer, 'new_life', None, '200')
                ledger.activate(buyer, 'new_life', new_lock['lock_ref'], '4')
                restored = self.l.Ledger(path, self.context, self.authorize)
                self.assertEqual(restored.prediction_lock('old_life'), lock)
                self.assertEqual(restored.prediction_lock('new_life'), new_lock)
        self.same_owner_pending_leave_retry()

    def same_owner_pending_leave_retry(self):
        ledger, binding = self.ledger, self.binding
        reserved = ledger.reserve_life(binding, 'life_a', '100')
        lock = ledger.lock_prediction(binding, 'life_a', self.pick(), '1')
        ledger.release(binding, '1', '2')
        fresh = copy.deepcopy(binding)
        fresh.update(grant_id='fresh_grant', session_key_id='fresh_session', generation='3')
        retried = ledger.reserve_life(fresh, 'life_a', '999')
        self.assertEqual(retried, dict(reserved, binding=fresh))
        self.assertEqual(ledger.prediction_lock('life_a'), lock)
        ledger.activate(fresh, 'life_a', lock['lock_ref'], '3')

    def test_security_restore_fence(self):
        journal = JournalFixture(self.l)
        fence = self.l.RecoveryFence(self.context, journal)
        self.assertFalse(fence.ready)
        fence.recover(lambda state: True)
        backup = copy.deepcopy(dict(context=fence.context, high_water=fence.high_water))
        old = backup['context']
        fence.transition('ban', 'player.near', 'operator')
        fence.transition('revoke', 'old_grant', 'operator')
        fence.transition('generation', 'slot_1', 'operator', '9')
        restored = self.l.RecoveryFence(backup['context'], journal)
        restored.recover(lambda state: True)
        self.assertGreater(int(restored.context['authority_epoch']), int(old['authority_epoch']))
        self.assertFalse(restored.permits(old, 'someone.near', 'old_grant'))
        self.assertFalse(restored.permits(restored.context, 'player.near', 'new_grant'))
        self.assertFalse(restored.permits(restored.context, 'someone.near', 'old_grant'))
        self.assertTrue(restored.permits(restored.context, 'someone.near', 'new_grant', 'slot_1', '9'))
        self.assertFalse(restored.permits(restored.context, 'someone.near', 'new_grant', 'slot_1', '8'))
        journal.available = False
        self.refuse('recovery_pending', lambda: restored.transition('lift', 'player.near', 'operator'))
        self.assertFalse(restored.ready)
        journal.available = True
        journal.gap = True
        self.refuse('recovery_pending', lambda: restored.recover(lambda state: True))
        journal.gap = False
        self.refuse('recovery_pending', lambda: restored.recover(lambda state: None))
        self.assertFalse(restored.ready)
        restored.recover(lambda state: True)
        restored.transition('stop', 'room', 'operator')
        stopped = self.l.RecoveryFence(restored.context, journal)
        stopped.recover(lambda state: True)
        self.assertFalse(stopped.ready)
        stopped.transition('start', 'room', 'operator')
        self.assertTrue(stopped.ready)


class BatchFixture:
    """Host-owned atomic idempotency: a failed child hop keeps the row pending."""

    def __init__(self):
        self.rows = {}
        self.hop_ready = False
        self.effects = 0
        self.unknown = False
        self.crash_after_publish = False

    def lookup(self, context, batch_id):
        if self.unknown:
            return None
        return copy.deepcopy(self.rows.get(batch_id, {'state': 'missing'}))

    def submit(self, result):
        batch = result['batch_id']
        previous = self.rows.get(batch)
        if previous and previous['digest'] != result['sealed_result_hash']:
            raise ValueError('conflict')
        if previous and previous['state'] == 'confirmed':
            return copy.deepcopy(previous)
        state = 'confirmed' if self.hop_ready else 'pending'
        receipt = dict(transaction_id='transaction_a', receipt_id='receipt_a', confirmed_at='100')
        row = dict(state=state, digest=result['sealed_result_hash'],
                   chain_receipt=receipt if self.hop_ready else None)
        self.rows[batch] = row
        self.effects += int(self.hop_ready)
        if self.crash_after_publish:
            self.crash_after_publish = False
            raise OSError('reply_lost')
        return copy.deepcopy(row)


class JournalFixture:
    """Trusted remote fixture kept outside the restored local database."""

    def __init__(self, module):
        self.module = module
        self.events = []
        self.epoch = 1
        self.available = True
        self.gap = False

    def snapshot(self, context):
        if not self.available:
            raise OSError('unavailable')
        events = copy.deepcopy(self.events[1:] if self.gap else self.events)
        return dict(authority_epoch=str(self.epoch), high_water=str(len(self.events)), events=events)

    def advance_epoch(self, context, expected_high_water):
        if not self.available or expected_high_water != str(len(self.events)):
            raise OSError('unavailable')
        self.epoch = max(self.epoch, int(context['authority_epoch'])) + 1
        return self.snapshot(context)

    def append(self, context, event, expected_high_water):
        if not self.available or expected_high_water != str(len(self.events)):
            raise OSError('unavailable')
        self.events.append(dict(event, index=str(len(self.events) + 1)))
        return self.snapshot(context)


if __name__ == '__main__':
    unittest.main()
