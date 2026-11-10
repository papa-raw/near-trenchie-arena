"""Durable ordered history, immutable life fences and recovery authority.

SQLite transactions serialize local writers. Hashes detect damage, not rollback:
the authenticated remote journal and chain reconciliation supply freshness.
All host callbacks are trusted deployment adapters, never member-supplied code.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from jsonschema import Draft202012Validator


class Refusal(ValueError):
    """A bounded public refusal; never expose the rejected body."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def canonical(value):
    """Canonical UTF-8 JSON, including the required control-character escapes."""
    if value is None:
        return b'null'
    if type(value) is bool:
        return b'true' if value else b'false'
    if type(value) is int:
        return str(value).encode('ascii')
    if isinstance(value, str):
        text = '"'
        for char in value:
            number = ord(char)
            if 0xD800 <= number <= 0xDFFF:
                raise Refusal('bad_message')
            text += ('\\' + char if char in ('"', '\\') else
                     f'\\u{number:04x}' if number < 32 else char)
        return (text + '"').encode('utf-8')
    if isinstance(value, list):
        return b'[' + b','.join(canonical(item) for item in value) + b']'
    if isinstance(value, dict) and all(isinstance(key, str) and key.isascii() for key in value):
        return b'{' + b','.join(canonical(key) + b':' + canonical(value[key])
                                for key in sorted(value)) + b'}'
    raise Refusal('bad_message')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


@lru_cache(maxsize=1)
def _definitions():
    return json.loads(Path(__file__).with_name('protocol.schema.json').read_text())['$defs']


@lru_cache(maxsize=128)
def _validator(name):
    return Draft202012Validator({'$defs': _definitions(), '$ref': '#/$defs/' + name})


def validate(name, value):
    if not _validator(name).is_valid(value):
        raise Refusal('bad_message')
    canonical(value)
    return value


def replay_event_hash(previous_hash, event):
    """Hash each effective input with its predecessor, excluding its own hash."""
    return digest({'previous_hash': previous_hash,
                   'event': {key: value for key, value in event.items() if key != 'record_hash'}})


def sealed_hash(record):
    """Stable destination-independent result identity, without raw replay material."""
    fields = ('segment_id', 'life_ids', 'nft_token_ids', 'inputs_hash', 'seed_hash',
              'rules_hash', 'final_state_hash', 'predictions_log_hash', 'completed',
              'tick_count', 'lives')
    try:
        return digest({key: record[key] for key in fields})
    except KeyError:
        raise Refusal('bad_message') from None


def prediction_log_hash(events, predictions):
    """Commit full unsigned forecasts, including zero estimate, in lock order.

    The host's read-only replay adapter supplies a lock_ref -> unsigned forecast
    map; a no-answer lock maps to None. The bridge's public ReplayPick alone does
    not carry forecasts and therefore cannot establish their integrity.
    """
    rows = []
    for event in events:
        if event['kind'] != 'prediction_lock':
            continue
        lock = event['payload']['prediction_lock']
        if lock['lock_ref'] not in predictions:
            raise Refusal('bad_message')
        prediction = predictions[lock['lock_ref']]
        if lock['state'] == 'none':
            if prediction is not None:
                raise Refusal('bad_message')
        else:
            if not isinstance(prediction, dict) or 'signature' in prediction:
                raise Refusal('bad_message')
            validate('PredictionRequest', dict(prediction, signature='A' * 86))
            if (digest(prediction) != lock['prediction_hash'] or
                    prediction['life_id'] != event['life_id'] or
                    prediction['nft_token_id'] != event['nft_token_id'] or
                    sum(prediction['payload']['spread_bps'].values()) != 10000):
                raise Refusal('bad_message')
            for name in ('loadout', 'moves', 'lock'):
                if prediction['payload'][name] != event['payload'][name]:
                    raise Refusal('bad_message')
        rows.append({'life_id': event['life_id'], 'prediction_lock': lock,
                     'prediction': prediction})
    if set(predictions) != {row['prediction_lock']['lock_ref'] for row in rows}:
        raise Refusal('bad_message')
    return digest(rows)


def verify_sealed(record, replay):
    """Require a complete seal and independent host replay before signing.

    replay(copy_of_record) returns final_state_hash, completed lives, and the full
    prediction map from its read-only source. It must actually run the archived
    engine/rules; a stored final-state echo is not a replay implementation.
    """
    record = copy.deepcopy(record)
    validate('SealedRecord', record)
    events = record['input_events']
    if record['inputs_hash'] != digest(events) or record['seed_hash'] != digest(record['seed']):
        raise Refusal('bad_message')
    if record['sealed_result_hash'] != sealed_hash(record):
        raise Refusal('bad_message')
    locks, started = {}, set()
    previous_hash, previous_index, previous_tick = '0' * 64, -1, -1
    for event in events:
        index, tick = int(event['index']), int(event['tick'])
        if index <= previous_index or tick < previous_tick or tick >= 1200:
            raise Refusal('bad_message')
        if event['record_hash'] != replay_event_hash(previous_hash, event):
            raise Refusal('bad_message')
        previous_hash, previous_index, previous_tick = event['record_hash'], index, tick
        life_id = event['life_id']
        if event['kind'] == 'prediction_lock':
            lock = event['payload']['prediction_lock']
            if (life_id in locks or life_id in started or lock['life_id'] != life_id or
                    lock['ledger_index'] != event['index']):
                raise Refusal('bad_message')
            locks[life_id] = (lock, event['nft_token_id'], event['fighter_id'])
        elif event['kind'] == 'life_start':
            if (life_id not in locks or life_id in started or
                    locks[life_id] != (event['payload'], event['nft_token_id'], event['fighter_id']) or
                    int(event['payload']['ledger_index']) >= index):
                raise Refusal('bad_message')
            started.add(life_id)
        elif event['kind'] in ('intent', 'leave') and life_id not in started:
            raise Refusal('bad_message')
    lives = record['lives']
    if (len(set(record['life_ids'])) != len(record['life_ids']) or
            len(set(record['nft_token_ids'])) != len(record['nft_token_ids']) or
            [life['life_id'] for life in lives] != record['life_ids'] or
            {life['nft_token_id'] for life in lives} != set(record['nft_token_ids'])):
        raise Refusal('bad_message')
    for life in lives:
        life_id = life['life_id']
        if (life_id not in started or life['prediction_lock'] != locks[life_id][0] or
                life['nft_token_id'] != locks[life_id][1]):
            raise Refusal('bad_message')
    try:
        outcome = replay(copy.deepcopy(record))
        if (outcome['final_state_hash'] != record['final_state_hash'] or
                outcome['lives'] != lives or
                prediction_log_hash(events, outcome['predictions']) != record['predictions_log_hash']):
            raise Refusal('bad_message')
    except (KeyError, TypeError, ValueError):
        raise Refusal('bad_message') from None
    return record


class OrderedStore:
    """Append-only SQLite records with checked predecessor hashes and FULL sync."""

    def __init__(self, path, identity):
        self.path = Path(path)
        with self.transaction() as (connection, rows):
            if not rows:
                self.add(connection, rows, 'identity', identity)
            elif rows[0]['kind'] != 'identity' or rows[0]['data'] != identity:
                raise Refusal('context_mismatch')

    @contextmanager
    def transaction(self):
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('BEGIN IMMEDIATE')
            connection.execute('CREATE TABLE IF NOT EXISTS records '
                               '(position INTEGER PRIMARY KEY, kind TEXT NOT NULL, data TEXT NOT NULL, '
                               'previous_hash TEXT NOT NULL, record_hash TEXT NOT NULL)')
            connection.execute("CREATE TRIGGER IF NOT EXISTS immutable_update BEFORE UPDATE ON records "
                               "BEGIN SELECT RAISE(ABORT,'immutable'); END")
            connection.execute("CREATE TRIGGER IF NOT EXISTS immutable_delete BEFORE DELETE ON records "
                               "BEGIN SELECT RAISE(ABORT,'immutable'); END")
            rows, previous = [], '0' * 64
            for position, kind, encoded, predecessor, record_hash in connection.execute(
                    'SELECT position,kind,data,previous_hash,record_hash FROM records ORDER BY position'):
                data = json.loads(encoded)
                row = dict(index=str(position), kind=kind, data=data, previous_hash=predecessor)
                if (position != len(rows) or predecessor != previous or digest(row) != record_hash or
                        canonical(data).decode() != encoded):
                    raise Refusal('recovery_pending')
                rows.append(dict(row, record_hash=record_hash))
                previous = record_hash
            yield connection, rows
            connection.execute('COMMIT')
        except BaseException:
            if connection.in_transaction:
                connection.execute('ROLLBACK')
            raise
        finally:
            connection.close()

    @staticmethod
    def add(connection, rows, kind, data):
        row = dict(index=str(len(rows)), kind=kind, data=copy.deepcopy(data),
                   previous_hash=rows[-1]['record_hash'] if rows else '0' * 64)
        record_hash = digest(row)
        connection.execute('INSERT INTO records VALUES (?,?,?,?,?)',
                           (len(rows), kind, canonical(data).decode(), row['previous_hash'], record_hash))
        row['record_hash'] = record_hash
        rows.append(row)
        return row


class Ledger:
    """Internal methods accept current validated bindings, never raw wire frames."""

    def __init__(self, path, context, authorize):
        validate('MainnetContext', context)
        self.context = copy.deepcopy(context)
        self.authorize = authorize
        identity = {k: v for k, v in context.items() if k != 'authority_epoch'}
        self.store = OrderedStore(path, identity)

    def _current(self, binding, rows):
        validate('SlotBinding', binding)
        if binding['context'] != self.context:
            raise Refusal('context_mismatch')
        try:
            allowed = self.authorize(copy.deepcopy(binding))
        except Exception:
            raise Refusal('recovery_pending') from None
        if (allowed is not True or any(
                row['kind'] == 'release' and row['data']['binding']['grant_id'] == binding['grant_id']
                for row in rows)):
            raise Refusal('stale_slot')

    @staticmethod
    def _life(rows, life_id):
        if any(row['kind'] == 'retirement' and row['data']['life_id'] == life_id for row in rows):
            raise Refusal('stale_slot')
        for row in rows:
            if row['kind'] == 'reservation' and row['data']['life_id'] == life_id:
                return row['data']
        raise Refusal('stale_slot')

    @staticmethod
    def _same_persona(reservation, binding):
        if any(reservation['binding'][key] != binding[key]
               for key in ('account_id', 'nft_token_id', 'persona_digest')):
            raise Refusal('stale_slot')

    def reserve_life(self, binding, life_id, deadline):
        reservation = dict(binding=copy.deepcopy(binding), life_id=life_id, prediction_deadline=deadline)
        validate('ReservedLife', reservation)
        with self.store.transaction() as (connection, rows):
            self._current(binding, rows)
            for row in rows:
                if row['kind'] == 'reservation' and row['data']['life_id'] == life_id:
                    self._same_persona(self._life(rows, life_id), binding)
                    return dict(row['data'], binding=copy.deepcopy(binding))
            retirements = []
            retired = {row['data']['life_id'] for row in rows if row['kind'] == 'retirement'}
            for row in rows:
                if (row['kind'] == 'reservation' and
                        row['data']['binding']['nft_token_id'] == binding['nft_token_id'] and
                        row['data']['life_id'] not in retired and
                        not any(r['kind'] == 'activation' and r['data']['life_id'] == row['data']['life_id']
                                for r in rows)):
                    # A leave survives reopen and session rotation. Preserve its
                    # pending life for a same-life retry until the engine chooses
                    # a replacement, then retire it without rewriting its lock.
                    released = any(
                        r['kind'] == 'release' and int(r['index']) > int(row['index']) and
                        all(r['data']['binding'][key] == row['data']['binding'][key]
                            for key in ('account_id', 'nft_token_id', 'persona_digest'))
                        for r in rows)
                    if not released:
                        raise Refusal('request_conflict')
                    retirements.append(row['data']['life_id'])
            for previous_life in retirements:
                self.store.add(connection, rows, 'retirement', dict(life_id=previous_life,
                                                                  replacement_life_id=life_id))
            self.store.add(connection, rows, 'reservation', reservation)
        return reservation

    @staticmethod
    def _lock(rows, life_id):
        return next((copy.deepcopy(row['data']['lock']) for row in rows
                     if row['kind'] == 'prediction' and row['data']['lock']['life_id'] == life_id), None)

    def prediction_lock(self, life_id):
        validate('Id', life_id)
        with self.store.transaction() as (_, rows):
            return self._lock(rows, life_id)

    def lock_prediction(self, binding, life_id, pick_or_none, now_ms):
        validate('U64', now_ms)
        with self.store.transaction() as (connection, rows):
            self._current(binding, rows)
            reservation = self._life(rows, life_id)
            self._same_persona(reservation, binding)
            prediction_hash = None
            if pick_or_none is not None:
                validate('PredictionRequest', pick_or_none)
                if (pick_or_none['life_id'] != life_id or any(
                        pick_or_none[key] != binding[key] for key in
                        ('context', 'grant_id', 'session_key_id', 'member_id', 'nft_token_id',
                         'persona_digest', 'slot_id', 'generation'))):
                    raise Refusal('stale_slot')
                if sum(pick_or_none['payload']['spread_bps'].values()) != 10000:
                    raise Refusal('bad_message')
                prediction_hash = digest({key: value for key, value in pick_or_none.items()
                                          if key != 'signature'})
            existing = self._lock(rows, life_id)
            if existing is not None:
                if existing['prediction_hash'] == prediction_hash and (
                        (existing['state'] == 'none') == (pick_or_none is None)):
                    return existing
                original = next(row['data']['prediction'] for row in rows if row['kind'] == 'prediction'
                                and row['data']['lock']['life_id'] == life_id)
                if original is not None and pick_or_none is not None and all(
                        original[key] == pick_or_none[key]
                        for key in ('context', 'grant_id', 'session_key_id', 'sequence')):
                    raise Refusal('request_conflict')
                raise Refusal('prediction_closed')
            if ((pick_or_none is None) != (int(now_ms) >= int(reservation['prediction_deadline'])) or
                    any(row['kind'] == 'activation' and row['data']['life_id'] == life_id for row in rows)):
                raise Refusal('prediction_closed')
            lock = dict(life_id=life_id, lock_ref='lock_' + digest([life_id, len(rows)])[:48],
                        state='none' if pick_or_none is None else 'prediction',
                        prediction_hash=prediction_hash, ledger_index=str(len(rows)), locked_before_start=True)
            validate('PredictionLock', lock)
            unsigned = ({key: value for key, value in pick_or_none.items() if key != 'signature'}
                        if pick_or_none is not None else None)
            self.store.add(connection, rows, 'prediction', dict(lock=lock, prediction=unsigned,
                                                              binding=copy.deepcopy(binding), tick='0'))
        return lock

    def activate(self, binding, life_id, lock_ref, tick):
        validate('U64', tick)
        with self.store.transaction() as (connection, rows):
            self._current(binding, rows)
            reservation = self._life(rows, life_id)
            self._same_persona(reservation, binding)
            lock = self._lock(rows, life_id)
            if lock is None or lock['lock_ref'] != lock_ref:
                raise Refusal('prediction_closed')
            for row in rows:
                if row['kind'] == 'activation' and row['data']['life_id'] == life_id:
                    return copy.deepcopy(row['data'])
            activation = dict(binding=copy.deepcopy(binding), life_id=life_id, lock_ref=lock_ref, tick=tick)
            self.store.add(connection, rows, 'activation', activation)
        return activation

    def release(self, binding, last_sequence, tick):
        validate('SlotBinding', binding)
        validate('U64', last_sequence)
        validate('U64', tick)
        with self.store.transaction() as (connection, rows):
            for row in rows:
                if row['kind'] == 'release' and row['data']['binding'] == binding:
                    return copy.deepcopy(row['data']['ack'])
            self._current(binding, rows)
            ack = dict(binding=copy.deepcopy(binding), last_sequence=last_sequence,
                       boundary=dict(kind='released', life_id=None, segment_id=None, not_before_ms=None),
                       revoked=True)
            validate('ReleaseAck', ack)
            self.store.add(connection, rows, 'release', dict(binding=copy.deepcopy(binding), ack=ack, tick=tick))
        return ack

    def append(self, kind, tick, member_id=None, life_id=None, request_digest=None):
        """Append a bounded public fact from the trusted service or engine."""
        event = dict(index='0', tick=tick, kind=kind, member_id=member_id,
                     life_id=life_id, request_digest=request_digest, record_hash='0' * 64)
        validate('PublicEvent', event)
        if kind in ('prediction_lock', 'life_start', 'seal'):
            raise Refusal('bad_message')
        with self.store.transaction() as (connection, rows):
            event['index'] = str(len(rows))
            row = self.store.add(connection, rows, 'event', event)
            return dict(event, record_hash=row['record_hash'])

    def seal(self, record, replay):
        checked = verify_sealed(record, replay)
        if checked['rules_hash'] != self.context['rules_hash']:
            raise Refusal('context_mismatch')
        with self.store.transaction() as (connection, rows):
            for row in rows:
                if row['kind'] == 'sealed' and row['data']['segment_id'] == checked['segment_id']:
                    if row['data'] != checked:
                        raise Refusal('request_conflict')
                    return copy.deepcopy(row['data'])
            self.store.add(connection, rows, 'sealed', checked)
        return checked

    def sealed(self, segment_id):
        validate('Id', segment_id)
        with self.store.transaction() as (_, rows):
            for row in rows:
                if row['kind'] == 'sealed' and row['data']['segment_id'] == segment_id:
                    return copy.deepcopy(row['data'])
        raise Refusal('not_found')

    def replay_page(self, segment_id, after_index=None):
        record = self.sealed(segment_id)
        cursor = self._cursor(after_index)
        events = [event for event in record['input_events'] if int(event['index']) >= cursor]
        selected = events[:128]
        return dict(type='replay', context=copy.deepcopy(self.context), segment_id=segment_id,
                    seed=record['seed'], rules_hash=record['rules_hash'], input_events=selected,
                    next_index=events[128]['index'] if len(events) > 128 else None,
                    **{key: record[key] for key in ('inputs_hash', 'predictions_log_hash', 'final_state_hash')})

    @staticmethod
    def _cursor(after_index):
        if after_index is None:
            return 0
        validate('U64', after_index)
        return int(after_index)

    def page(self, after_index=None):
        cursor = self._cursor(after_index)
        with self.store.transaction() as (_, rows):
            events = []
            for row in rows:
                kind, data = row['kind'], row['data']
                if int(row['index']) < cursor:
                    continue
                if kind == 'event':
                    event = dict(data, record_hash=row['record_hash'])
                elif kind in ('prediction', 'activation', 'release', 'sealed'):
                    names = dict(prediction='prediction_lock', activation='life_start', release='leave', sealed='seal')
                    event = dict(index=row['index'], tick=data.get('tick', '0'), kind=names[kind],
                                 member_id=data.get('binding', {}).get('member_id'),
                                 life_id=data.get('life_id', data.get('lock', {}).get('life_id')),
                                 request_digest=data.get('lock', {}).get('prediction_hash'),
                                 record_hash=row['record_hash'])
                else:
                    continue
                events.append(event)
        selected = events[:128]
        return dict(type='ledger', context=copy.deepcopy(self.context), events=selected,
                    next_index=events[128]['index'] if len(events) > 128 else None,
                    page_hash=digest(selected))


class RecoveryFence:
    """Fresh authority from a trusted remote journal, never a restored checksum.

    journal.snapshot(context), advance_epoch(context, expected_high_water), and
    append(context, event, expected_high_water) are authenticated atomic host
    operations. They return {authority_epoch, high_water, events}; events have
    contiguous one-based indexes. They must persist before returning and be
    scoped to the configured room/deployment independently of member input.
    """

    def __init__(self, context, journal, now_ms=None):
        validate('MainnetContext', context)
        self.context = copy.deepcopy(context)
        self.journal = journal
        self.now_ms = now_ms or (lambda: str(time.time_ns() // 1_000_000))
        self.ready = False
        self.reconciled = False
        self.high_water = '0'
        self.state = dict(bans=set(), revocations=set(), generations={}, keys={}, stopped=False)

    def _snapshot(self, snapshot):
        validate('U64', snapshot['authority_epoch'])
        validate('U64', snapshot['high_water'])
        events = snapshot['events']
        if (int(snapshot['high_water']) < int(self.high_water) or
                int(snapshot['authority_epoch']) < int(self.context['authority_epoch']) or
                len(events) != int(snapshot['high_water'])):
            raise Refusal('recovery_pending')
        state = dict(bans=set(), revocations=set(), generations={}, keys={}, stopped=False)
        for index, event in enumerate(events, 1):
            if event['index'] != str(index):
                raise Refusal('recovery_pending')
            self._apply(state, event)
        self.high_water = snapshot['high_water']
        self.context['authority_epoch'] = snapshot['authority_epoch']
        self.state = state

    @staticmethod
    def _apply(state, event):
        kind, subject = event['kind'], event['subject']
        if kind == 'ban':
            state['bans'].add(subject)
        elif kind == 'lift':
            state['bans'].discard(subject)
        elif kind == 'revoke':
            state['revocations'].add(subject)
        elif kind == 'generation':
            validate('U64', event['value'])
            if int(event['value']) <= int(state['generations'].get(subject, '0')):
                raise Refusal('recovery_pending')
            state['generations'][subject] = event['value']
        elif kind == 'key':
            state['keys'][subject] = event['value']
        elif kind == 'stop':
            state['stopped'] = True
        elif kind == 'start':
            state['stopped'] = False
        else:
            raise Refusal('recovery_pending')

    def recover(self, reconcile):
        self.ready = False
        self.reconciled = False
        try:
            self._snapshot(self.journal.snapshot(copy.deepcopy(self.context)))
            prior_epoch = int(self.context['authority_epoch'])
            self._snapshot(self.journal.advance_epoch(copy.deepcopy(self.context), self.high_water))
            if int(self.context['authority_epoch']) <= prior_epoch:
                raise Refusal('recovery_pending')
            if reconcile(copy.deepcopy(self.state)) is not True:
                raise Refusal('recovery_pending')
            # Observe concurrent revocations before opening after a long chain read.
            mark, epoch = self.high_water, self.context['authority_epoch']
            self._snapshot(self.journal.snapshot(copy.deepcopy(self.context)))
            if (mark, epoch) != (self.high_water, self.context['authority_epoch']):
                raise Refusal('recovery_pending')
            self.reconciled = True
            self.ready = not self.state['stopped']
        except (OSError, KeyError, TypeError, ValueError):
            self.ready = False
            self.reconciled = False
            raise Refusal('recovery_pending') from None
        return copy.deepcopy(self.context)

    def transition(self, kind, subject, actor, value=None, *, reason='security_transition', scope='room'):
        """Commit remotely before acknowledging; failure immediately closes authority."""
        if not self.reconciled:
            raise Refusal('recovery_pending')
        occurred_at = self.now_ms()
        validate('U64', occurred_at)
        validate('Label', actor)
        validate('Text', reason)
        validate('Label', scope)
        event = dict(kind=kind, subject=subject, actor=actor, value=value,
                     reason=reason, scope=scope, occurred_at=occurred_at)
        try:
            candidate = copy.deepcopy(self.state)
            self._apply(candidate, event)
            previous = int(self.high_water)
            snapshot = self.journal.append(copy.deepcopy(self.context), event, self.high_water)
            self._snapshot(snapshot)
            if int(self.high_water) != previous + 1 or snapshot['events'][-1] != dict(event, index=self.high_water):
                raise Refusal('recovery_pending')
            self.ready = not self.state['stopped']
        except (OSError, KeyError, TypeError, ValueError):
            self.ready = False
            self.reconciled = False
            raise Refusal('recovery_pending') from None
        return self.high_water

    def permits(self, context, account_id, grant_id, slot_id=None, generation=None, nft_token_id=None):
        if not self.ready or context != self.context:
            return False
        try:
            mark, epoch = self.high_water, self.context['authority_epoch']
            self._snapshot(self.journal.snapshot(copy.deepcopy(self.context)))
            if (mark, epoch) != (self.high_water, self.context['authority_epoch']):
                self.ready = False
                self.reconciled = False
                return False
        except (OSError, KeyError, TypeError, ValueError):
            self.ready = False
            self.reconciled = False
            return False
        return (account_id not in self.state['bans'] and nft_token_id not in self.state['bans'] and
                grant_id not in self.state['revocations'] and
                (slot_id not in self.state['generations'] or self.state['generations'][slot_id] == generation))
