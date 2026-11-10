"""Game-owned, durable held-premint onboarding with no payment collection."""
from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
import re
import secrets
import sqlite3

from .signing import account_id, canonical, encode, permit_bytes, persona_digest, session_key, verify
from .contract import Contract, PRESETS, PERMIT_TTL_MS

HOLD_MS = 15 * 60_000
CHALLENGE_MS = 60_000
DAY_MS = 24 * 60 * 60_000
MAX_PENDING_CHALLENGES = 512
MAX_PENDING_PER_PRINCIPAL = 5
# Unproved paid-wallet requests cannot consume the remaining448 arrival/claim rows.
MAX_PAID_WALLET_CHALLENGES = 64


class ArrivalRefusal(ValueError):
    """Bounded refusal code; never include proofs or credentials."""


class ArrivalService:
    """Only the game owns this store and its trusted contract/wallet adapters.

    Edge-supplied device/IP values must come from trusted request metadata.
    Public visitors supply no account name before claim. The implicit-address
    principal proves session possession, while fresh contract custody plus this
    persisted reservation establishes the token binding. It is never NFT owner
    evidence or proof of an already-created onchain visitor account.
    """

    def __init__(self, path: Path, *, contract: Contract, now_ms: Callable[[], int],
                 permit_sign: Callable[[bytes], bytes], permit_epoch: str,
                 wallet_verify: Callable[[str, bytes, str], bool],
                 name_allowed: Callable[[str], bool]) -> None:
        if contract.network_id != 'testnet':
            raise ArrivalRefusal('testnet_required')
        self.presets = deepcopy(PRESETS)
        self.path, self.contract, self.now_ms = path, contract, now_ms
        self.permit_sign, self.permit_epoch = permit_sign, permit_epoch
        self.wallet_verify, self.name_allowed = wallet_verify, name_allowed
        self._room_context: dict | None = None
        with self._db() as db:
            schema = '''
                CREATE TABLE IF NOT EXISTS config (name TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS inventory (token TEXT PRIMARY KEY, preset TEXT NOT NULL, digest TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS challenges (
                    nonce TEXT PRIMARY KEY, body TEXT NOT NULL, expires INTEGER NOT NULL, bucket TEXT NOT NULL, used INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS holds (
                    id TEXT PRIMARY KEY, token TEXT NOT NULL, public TEXT NOT NULL,
                    request TEXT NOT NULL, preset TEXT NOT NULL, digest TEXT NOT NULL,
                    until_ms INTEGER NOT NULL, created INTEGER NOT NULL, device TEXT NOT NULL, ip TEXT NOT NULL,
                    state TEXT NOT NULL, fought INTEGER NOT NULL DEFAULT 0, recipient TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS held_token ON holds(token) WHERE state IN ('held','claiming','claimed','expired');
                CREATE UNIQUE INDEX IF NOT EXISTS visitor_request ON holds(public,request);
            '''
            for statement in schema.split(';'):
                if statement.strip():
                    db.execute(statement)
            configuration = canonical(dict(network=contract.network_id, contract=contract.contract_id,
                custodian=contract.custodian, minter=contract.minter, presets=self.presets)).decode()
            prior = db.execute('SELECT value FROM config WHERE name=?', ('context',)).fetchone()
            if prior is not None and prior[0] != configuration:
                raise ArrivalRefusal('context_mismatch')
            db.execute('INSERT OR IGNORE INTO config VALUES (?,?)', ('context', configuration))
            self._inventory(db)

    def _inventory(self, db: sqlite3.Connection) -> None:
        contract = self.contract
        inventory = contract.inventory()
        expected = {preset: 10 for preset in self.presets}
        counts = {preset: sum(row['preset_id'] == preset for row in inventory) for preset in self.presets}
        if len(inventory) != 50 or counts != expected:
            raise ArrivalRefusal('invalid_inventory')
        for row in inventory:
            digest = persona_digest(self.presets[row['preset_id']])
            if row['persona_digest'] != digest:
                raise ArrivalRefusal('invalid_inventory')
            db.execute('INSERT OR IGNORE INTO inventory VALUES (?,?,?)', (row['token_id'], row['preset_id'], digest))
        persisted = {(row['token'], row['preset'], row['digest']) for row in db.execute('SELECT * FROM inventory')}
        expected_inventory = {(row['token_id'], row['preset_id'], row['persona_digest']) for row in inventory}
        if persisted != expected_inventory:
            raise ArrivalRefusal('invalid_inventory')
    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _token(self, token_id: str) -> dict:
        try:
            result = self.contract.token(token_id)
        except (OSError, KeyError, ValueError):
            raise ArrivalRefusal('ownership_unavailable') from None
        if not result or int(result.get('chain_height', '0')) <= 0:
            raise ArrivalRefusal('ownership_unavailable')
        return result

    def _safe(self, token: dict) -> bool:
        return token['owner_id'] == self.contract.custodian and token['sale_ready'] is True

    def _expire(self, db: sqlite3.Connection) -> None:
        db.execute("UPDATE holds SET state='expired' WHERE state='held' AND until_ms<=?", (self.now_ms(),))
        for row in db.execute("SELECT * FROM holds WHERE state='expired'").fetchall():
            token = self._token(row['token'])
            if self._safe(token):
                db.execute("UPDATE holds SET state='released' WHERE id=?", (row['id'],))
        db.execute('DELETE FROM challenges WHERE expires<=?', (self.now_ms(),))

    @staticmethod
    def _text(value: str, limit: int = 128) -> None:
        if type(value) is not str or not 1 <= len(value) <= limit:
            raise ArrivalRefusal('bad_message')

    def challenge(self, public: str, preset_id: str, request_id: str, *, device_id: str, ip: str) -> dict:
        account_id(public)
        for value in (request_id, device_id, ip):
            self._text(value)
        if preset_id not in self.presets:
            raise ArrivalRefusal('bad_message')
        with self._db() as db:
            self._expire(db)
            if db.execute('SELECT COUNT(*) FROM challenges').fetchone()[0] >= MAX_PENDING_CHALLENGES:
                raise ArrivalRefusal('rate_limited')
            if db.execute('SELECT COUNT(*) FROM challenges WHERE bucket=?', (ip,)).fetchone()[0] >= MAX_PENDING_PER_PRINCIPAL:
                raise ArrivalRefusal('rate_limited')
            body = dict(domain='game.arrival.v1', network_id='testnet', contract_id=self.contract.contract_id,
                public_key=public, preset_id=preset_id, request_id=request_id, device_id=device_id, ip=ip,
                nonce=secrets.token_hex(24), expires_at=str(self.now_ms() + CHALLENGE_MS))
            db.execute('INSERT INTO challenges(nonce,body,expires,bucket) VALUES (?,?,?,?)',
                       (body['nonce'], canonical(body).decode(), int(body['expires_at']), ip))
            return body

    def _challenge(self, db: sqlite3.Connection, challenge: dict) -> sqlite3.Row:
        if type(challenge) is not dict or type(challenge.get('nonce')) is not str:
            raise ArrivalRefusal('proof_required')
        row = db.execute('SELECT * FROM challenges WHERE nonce=?', (challenge['nonce'],)).fetchone()
        if row is None or row['expires'] <= self.now_ms() or row['body'] != canonical(challenge).decode():
            raise ArrivalRefusal('proof_required')
        return row

    def _held_result(self, row: sqlite3.Row) -> dict:
        return dict(state='held', reservation_id=row['id'], token_id=row['token'],
            account_id=account_id(row['public']), session_public_key=session_key(row['public']),
            persona_digest=row['digest'], preset_id=row['preset'], expires_at=str(row['until_ms']))

    def allocate(self, challenge: dict, visitor_signature: str) -> dict:
        with self._db() as db:
            receipt = self._challenge(db, challenge)
            public = challenge.get('public_key', '')
            if not verify(public, canonical(challenge), visitor_signature):
                raise ArrivalRefusal('proof_required')
            self._expire(db)
            prior = db.execute('SELECT * FROM holds WHERE public=? AND request=?',
                               (public, challenge['request_id'])).fetchone()
            if prior is not None:
                if prior['preset'] != challenge['preset_id'] or prior['state'] != 'held':
                    raise ArrivalRefusal('request_conflict')
                token = self._token(prior['token'])
                if token['owner_id'] != self.contract.custodian or token['persona_digest'] != prior['digest']:
                    raise ArrivalRefusal('ownership_unavailable')
                return self._held_result(prior)
            if receipt['used']:
                raise ArrivalRefusal('proof_required')
            db.execute('UPDATE challenges SET used=1 WHERE nonce=?', (challenge['nonce'],))
            self._limit(db, challenge)
            candidate = self._candidate(db, challenge['preset_id'])
            if candidate is None:
                occupied = db.execute("SELECT COUNT(*) FROM holds WHERE state IN ('held','claiming','claimed','expired')").fetchone()[0]
                return self._runout(public, challenge['preset_id'], occupied)
            reservation = 'hold-' + secrets.token_hex(24)
            db.execute('INSERT INTO holds(id,token,public,request,preset,digest,until_ms,created,device,ip,state) '
                       'VALUES (?,?,?,?,?,?,?,?,?,?,?)', (reservation, candidate['token'], public,
                       challenge['request_id'], candidate['preset'], candidate['digest'], self.now_ms() + HOLD_MS,
                       self.now_ms(), challenge['device_id'], challenge['ip'], 'held'))
            return self._held_result(db.execute('SELECT * FROM holds WHERE id=?', (reservation,)).fetchone())

    def _limit(self, db: sqlite3.Connection, challenge: dict) -> None:
        if db.execute("SELECT 1 FROM holds WHERE public=? AND state IN ('held','claiming')",
                      (challenge['public_key'],)).fetchone():
            raise ArrivalRefusal('request_conflict')
        if db.execute('SELECT 1 FROM holds WHERE created>? AND (public=? OR device=? OR ip=?)',
                      (self.now_ms() - DAY_MS, challenge['public_key'], challenge['device_id'], challenge['ip'])).fetchone():
            raise ArrivalRefusal('rate_limited')

    def _candidate(self, db: sqlite3.Connection, preset: str) -> sqlite3.Row | None:
        candidates = db.execute("SELECT * FROM inventory WHERE preset=? AND token NOT IN "
            "(SELECT token FROM holds WHERE state IN ('held','claiming','claimed','expired')) ORDER BY token", (preset,)).fetchall()
        for row in candidates:
            token = self._token(row['token'])
            if token['persona_digest'] == row['digest'] and self._safe(token):
                return row
        return None

    def _runout(self, public: str, preset: str, occupied: int, *, caller: str | None = None) -> dict:
        persona = deepcopy(self.presets[preset])
        if self.name_allowed(persona['name']) is not True:
            raise ArrivalRefusal('name_refused')
        payload = dict(domain='game.mint-permit.v1', schema='1', epoch=self.permit_epoch,
            network_id='testnet', contract_id=self.contract.contract_id, caller=account_id(public) if caller is None else caller,
            name=persona['name'], persona_digest=persona_digest(persona), preset_id=preset,
            nonce=secrets.token_hex(24), issued_at=str(self.now_ms()), expires_at=str(self.now_ms() + PERMIT_TTL_MS))
        try:
            raw_signature = self.permit_sign(permit_bytes(payload))
            if type(raw_signature) is not bytes or len(raw_signature) != 64:
                raise ValueError('invalid permit signature')
            signature = encode(raw_signature)
        except Exception:
            raise ArrivalRefusal('permit_unavailable') from None
        return dict(state='paid_mint_required', label='All claimed' if occupied == 50 else 'Preset unavailable', count=occupied,
            permit=dict(payload=payload, signature=signature), persona=persona, payment='direct_wallet_only')

    def paid_wallet_challenge(self, public: str, preset: str, recipient: str) -> dict:
        """Bind a new direct caller after explicit wallet connection at run-out."""
        account_id(public)
        self._account(recipient)
        if preset not in self.presets:
            raise ArrivalRefusal('bad_message')
        with self._db() as db:
            db.execute('DELETE FROM challenges WHERE expires<=?', (self.now_ms(),))
            bucket = 'paid-wallet:' + public
            if db.execute('SELECT COUNT(*) FROM challenges WHERE bucket=?', (bucket,)).fetchone()[0] >= MAX_PENDING_PER_PRINCIPAL:
                raise ArrivalRefusal('rate_limited')
            if db.execute("SELECT COUNT(*) FROM challenges WHERE bucket LIKE 'paid-wallet:%'").fetchone()[0] >= MAX_PAID_WALLET_CHALLENGES:
                raise ArrivalRefusal('rate_limited')
            if db.execute('SELECT COUNT(*) FROM challenges').fetchone()[0] >= MAX_PENDING_CHALLENGES:
                raise ArrivalRefusal('rate_limited')
            body = dict(domain='game.paid-mint-wallet.v1', network_id='testnet',
                contract_id=self.contract.contract_id, public_key=public, preset_id=preset,
                recipient=recipient, nonce=secrets.token_hex(24), expires_at=str(self.now_ms() + CHALLENGE_MS))
            db.execute('INSERT INTO challenges(nonce,body,expires,bucket) VALUES (?,?,?,?)',
                       (body['nonce'], canonical(body).decode(), int(body['expires_at']), bucket))
            return body

    def paid_wallet_permit(self, challenge: dict, *, visitor_signature: str, wallet_proof: str) -> dict:
        with self._db() as db:
            nonce = self._challenge(db, challenge)
            if nonce['used'] or challenge.get('domain') != 'game.paid-mint-wallet.v1':
                raise ArrivalRefusal('proof_required')
            if not verify(challenge['public_key'], canonical(challenge), visitor_signature):
                raise ArrivalRefusal('proof_required')
            try:
                proved = self.wallet_verify(challenge['recipient'], canonical(challenge), wallet_proof) is True
            except Exception:
                proved = False
            if not proved:
                raise ArrivalRefusal('proof_required')
            db.execute('UPDATE challenges SET used=1 WHERE nonce=?', (challenge['nonce'],))
            self._expire(db)
            occupied = db.execute("SELECT COUNT(*) FROM holds WHERE state IN ('held','claiming','claimed','expired')").fetchone()[0]
            return self._runout(challenge['public_key'], challenge['preset_id'], occupied, caller=challenge['recipient'])

    @staticmethod
    def _account(recipient: str) -> None:
        if type(recipient) is not str or not re.fullmatch(r'[a-z0-9]+(?:[-_.][a-z0-9]+)*', recipient) or not 2 <= len(recipient) <= 64:
            raise ArrivalRefusal('bad_message')

    def _hold(self, db: sqlite3.Connection, reservation: str, *, claimed: bool = False) -> sqlite3.Row:
        row = db.execute('SELECT * FROM holds WHERE id=?', (reservation,)).fetchone()
        allowed = ('held', 'claiming', 'claimed') if claimed else ('held',)
        if row is None or row['state'] not in allowed or (row['state'] == 'held' and row['until_ms'] <= self.now_ms()):
            raise ArrivalRefusal('hold_expired')
        return row

    def claim_challenge(self, reservation: str, recipient: str) -> dict:
        self._account(recipient)
        with self._db() as db:
            row = self._hold(db, reservation, claimed=True)
            body = dict(domain='game.claim.v1', network_id='testnet', contract_id=self.contract.contract_id,
                reservation_id=reservation, token_id=row['token'], persona_digest=row['digest'], recipient=recipient,
                nonce=secrets.token_hex(24), expires_at=str(self.now_ms() + CHALLENGE_MS))
            db.execute('DELETE FROM challenges WHERE expires<=?', (self.now_ms(),))
            if db.execute('SELECT COUNT(*) FROM challenges').fetchone()[0] >= MAX_PENDING_CHALLENGES:
                raise ArrivalRefusal('rate_limited')
            db.execute('INSERT INTO challenges(nonce,body,expires,bucket) VALUES (?,?,?,?)',
                       (body['nonce'], canonical(body).decode(), int(body['expires_at']), reservation))
            return body

    def claim(self, challenge: dict, *, visitor_signature: str, wallet_proof: str) -> dict:
        with self._db() as db:
            nonce = self._challenge(db, challenge)
            if nonce['used'] or challenge.get('domain') != 'game.claim.v1':
                raise ArrivalRefusal('proof_required')
            row = self._hold(db, challenge['reservation_id'], claimed=True)
            if not verify(row['public'], canonical(challenge), visitor_signature):
                raise ArrivalRefusal('proof_required')
            try:
                valid_wallet = self.wallet_verify(challenge['recipient'], canonical(challenge), wallet_proof) is True
            except Exception:
                valid_wallet = False
            if not valid_wallet:
                raise ArrivalRefusal('proof_required')
            self._recipient(row, challenge['recipient'])
            db.execute('UPDATE challenges SET used=1 WHERE nonce=?', (challenge['nonce'],))
            if row['state'] == 'claimed':
                return self._claimed(row)
            token = self._token(row['token'])
            if (row['state'] == 'claiming' and token['owner_id'] == row['recipient']
                    and token['persona_digest'] == row['digest']):
                db.execute("UPDATE holds SET state='claimed' WHERE id=?", (row['id'],))
                return self._claimed(row)
            if not self._safe(token):
                return dict(state='claim_pending', reason='sale_ready_required')
            db.execute("UPDATE holds SET state='claiming',recipient=? WHERE id=?", (challenge['recipient'], row['id']))
        # The durable claiming fence survives a lost receipt or host crash.
        # Never return this token to the pool while its write outcome is unknown.
        try:
            self.contract.claim(row['token'], challenge['recipient'], row['digest'], caller=self.contract.minter)
        except (OSError, ValueError):
            return dict(state='claim_pending', reason='confirmation_required')
        with self._db() as db:
            row = self._hold(db, row['id'], claimed=True)
            token = self._token(row['token'])
            if token['owner_id'] != row['recipient'] or token['persona_digest'] != row['digest']:
                return dict(state='claim_pending', reason='confirmation_required')
            db.execute("UPDATE holds SET state='claimed' WHERE id=?", (row['id'],))
            return self._claimed(row)

    @staticmethod
    def _recipient(row: sqlite3.Row, recipient: str) -> None:
        if row['recipient'] is not None and row['recipient'] != recipient:
            raise ArrivalRefusal('request_conflict')

    @staticmethod
    def _claimed(row: sqlite3.Row) -> dict:
        return dict(state='claimed', token_id=row['token'], recipient=row['recipient'], persona_digest=row['digest'])

    def counts(self) -> dict:
        with self._db() as db:
            self._expire(db)
            counts = {row['state']: row['n'] for row in db.execute('SELECT state,COUNT(*) AS n FROM holds GROUP BY state')}
            held = counts.get('held', 0) + counts.get('claiming', 0)
            claimed = counts.get('claimed', 0)
            return dict(total=50, held=held, claimed=claimed,
                        available=50 - held - claimed - counts.get('expired', 0))

    def bind_room(self, context: dict, *, allow_synthetic_context: bool = False) -> None:
        """Pin a copied-room fixture context; never derive trust from a join."""
        from room.policy import validate
        validate('MainnetContext', context)
        if context['contract_ids']['nft'] != self.contract.contract_id:
            raise ArrivalRefusal('context_mismatch')
        if context['network_id'] != self.contract.network_id:
            if not (allow_synthetic_context is True and getattr(self.contract, 'synthetic', False) is True):
                raise ArrivalRefusal('context_mismatch')
        self._room_context = deepcopy(context)

    def resolve_identity(self, request: dict) -> dict:
        """Fresh custody evidence only; wallet owner/sale authority never inferred."""
        from room.policy import BoundaryError, canonical_bytes, safe_error, validate
        try:
            validate('JoinRequest', request)
            if self._room_context is None or request['context'] != self._room_context:
                raise ArrivalRefusal('context_mismatch')
            challenge, proof = request['challenge'], request['proof']
            with self._db() as db:
                row = self._hold(db, proof['key_id'])
                expected = dict(account_id=account_id(row['public']), nft_token_id=row['token'], persona_digest=row['digest'])
                if proof['method_id'] != 'visitor_session_v1' or any(challenge[key] != value for key, value in expected.items()):
                    raise ArrivalRefusal('proof_required')
                if request['session_public_key'] != session_key(row['public']):
                    raise ArrivalRefusal('proof_required')
                if not verify(row['public'], canonical_bytes(request, exclude=('proof',)), proof['proof_bytes']):
                    raise ArrivalRefusal('proof_required')
                token = self._token(row['token'])
                if token['owner_id'] != self.contract.custodian or token['persona_digest'] != row['digest']:
                    raise ArrivalRefusal('proof_required')
                owner = dict(context=deepcopy(self._room_context), **expected, ownership_kind='custody',
                    custody_reservation_id=row['id'], checked_at=str(self.now_ms()))
                return dict(owner=owner, play_status='eligible', chain_height=token['chain_height'], sale_control_allowed=False)
        except (ArrivalRefusal, BoundaryError) as error:
            return safe_error('ownership_unavailable' if str(error) == 'ownership_unavailable' else 'proof_required')

    def fight_seen(self, reservation: str, completed_life: dict) -> None:
        """Trusted host-only notification from the engine completed-life stream."""
        with self._db() as db:
            held = self._hold(db, reservation)
            if completed_life.get("nft_token_id") != held["token"] or completed_life.get("completed") is not True:
                raise ArrivalRefusal("fight_first")
            db.execute('UPDATE holds SET fought=1 WHERE id=?', (reservation,))

    def next_step(self, reservation: str) -> str:
        with self._db() as db:
            row = self._hold(db, reservation, claimed=True)
            if row['state'] == 'claimed':
                return 'owned'
            return 'offer_claim' if row['fought'] else 'fight'

    @staticmethod
    def wallet_step(action: str) -> str:
        if action not in ('claim', 'stake'):
            raise ArrivalRefusal('bad_message')
        return 'connect_wallet'
