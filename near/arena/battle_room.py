"""Battle frames beside the copied room: current grants, one sequence, signed ACKs."""
from copy import deepcopy

from room.policy import BoundaryError, GuestPolicy, canonical_bytes, digest, safe_error
from room.service import RoomService, DEFAULT_LIMITS
from room.slots import SlotError
try:
    from .battle_protocol import BINDING, KINDS, RECEIPT_DOMAIN, check_request, check_receipt
    from .battle_engine import refuse, checked_ack
except ImportError:
    from battle_protocol import BINDING, KINDS, RECEIPT_DOMAIN, check_request, check_receipt
    from battle_engine import refuse, checked_ack


class BattlePolicy(GuestPolicy):
    def authorize(self, binding, request, **options):
        # IdentityAuthority verified the original signed request before this policy call.
        # The shared feed owns the speech clock; keep the room's remaining checks intact.
        checked = request
        if request.get('kind') == 'intent' and request['payload'].get('say') is not None:
            checked = deepcopy(request)
            checked['payload']['say'] = None
        return super().authorize(binding, checked, **options)


class BattleRoomService(RoomService):
    def __init__(self, *args, battle_sign, battle_key_id, battle_speech=None, **options):
        self.battle_sign, self.battle_key_id, self.battle_speech = battle_sign, battle_key_id, battle_speech
        limits = deepcopy(options.get('limits') or DEFAULT_LIMITS)
        limits['intent_interval_ms'] = '500'
        options['limits'] = limits
        if options.get('policy') is None:
            options['policy'] = BattlePolicy(now_ms=options['now_ms'], max_control_bytes=limits['max_control_bytes'],
                                             max_depth=limits['max_depth'], max_array_items=limits['max_array_items'])
        elif not isinstance(options['policy'], BattlePolicy):
            raise ValueError('battle mode needs BattlePolicy; the copied room policy keeps its original limits')
        super().__init__(*args, **options)

    def _owner_interval(self, value):
        if not 500 <= int(value) <= 60000:
            raise BoundaryError('bad_message')
        self.limits['intent_interval_ms'] = value
        self.policy.intent_interval_ms = int(value)

    def _control(self, session, request):
        receipt = super()._control(session, request)
        if request['kind'] == 'intent' and request['payload']['say'] is not None and receipt.get('state') == 'accepted':
            self.battle_speech(session['binding'], dict(text=request['payload']['say'], emoji=None, sequence=request['sequence']))
        return receipt

    def _battle_session(self, connection_id, request):
        self._guard()
        connection = self._connections.get(connection_id)
        if connection is None or connection['session'] is None:
            raise BoundaryError('proof_required')
        session = self._sessions[connection['session']]
        binding = session['binding']
        self._context(request)
        if session['revoked'] or session['connection'] != connection_id:
            raise BoundaryError('proof_required')
        self._banned(binding['account_id'], binding['nft_token_id'])
        self.slots.authorize(session['record'])
        if any(request[key] != binding[key] for key in BINDING):
            raise BoundaryError('stale_slot')
        grant = self.identity.grant(binding['grant_id'])
        if 'intent' not in grant['capabilities']:
            raise BoundaryError('proof_required')
        try:
            verified = self.identity.verify_session(deepcopy(grant['session_public_key']),
                          canonical_bytes(request, exclude=('signature',)), request['signature']) is True
        except Exception:
            verified = False
        if not verified:
            raise BoundaryError('proof_required')
        checked = self.identity.authenticate_resume(dict(prior_grant_id=binding['grant_id'],
                          prior_generation=binding['generation'], resume_token=grant['token']))
        if checked['binding'] != binding:
            raise BoundaryError('stale_slot')
        return session

    def frame(self, connection_id, body):
        try:
            request = self._parse(body)
        except BoundaryError as error:
            return error.error()
        if type(request.get('kind')) is not str or request['kind'] not in KINDS:
            return super().frame(connection_id, body)
        if not self._pending.acquire(blocking=False):
            return safe_error('rate_limited')
        try:
            with self._lock:
                checkpoint, applied = None, False
                try:
                    check_request(request)
                    session = self._battle_session(connection_id, request)
                    sequence, fingerprint = int(request['sequence']), digest(request, exclude=('signature',))
                    prior = session['receipts'].get(sequence)
                    if prior is not None:
                        if prior[0] != fingerprint:
                            raise BoundaryError('request_conflict')
                        return deepcopy(prior[1])
                    if sequence <= session['sequence']:
                        raise BoundaryError('request_conflict')
                    session['sequence'] = sequence
                    try:
                        self._owner_control_consent(session['binding'])
                        # Rollover belongs to the host, before this request's
                        # mutation checkpoint; its writes cannot invalidate a refusal.
                        self.bridge.arena._prepare_segment()
                        checkpoint = self.bridge.arena.store.index
                        ack = self._battle_apply(session['binding'], request)
                        applied = self._battle_applied(ack, checkpoint)
                    except (BoundaryError, KeyError, TypeError, ValueError) as error:
                        if self._failed or self.bridge.arena.failed or self._battle_changed(checkpoint):
                            raise BoundaryError('recovery_pending') from None
                        code = error.code if isinstance(error, BoundaryError) else 'bad_message'
                        ack = self._refused_ack(session['binding'], request, code)
                    receipt = self._battle_receipt(request, ack)
                    if ack['status'] != 'refused':
                        self._security('battle_receipt', dict(session['binding'], sequence=request['sequence'], receipt=receipt))
                    session['receipts'][sequence] = (fingerprint, deepcopy(receipt))
                    while len(session['receipts']) > 64:
                        session['receipts'].pop(min(session['receipts']))
                    checkpoint, applied = None, False
                    return receipt
                finally:
                    # Close authority under the same lock as dispatch. Another
                    # frame cannot enter between an uncertain write and its fence.
                    # Engine failure also closes authority before a checkpoint.
                    if self.bridge.arena.failed or applied or self._battle_changed(checkpoint):
                        self._failed = True
        except (BoundaryError, SlotError) as error:
            return safe_error('recovery_pending' if self._failed else error.code)
        except Exception:
            # The locked finalizer fences unfinished effects. Failures before
            # mutation remain local; infrastructure keeps its existing fences.
            return safe_error('recovery_pending')
        finally:
            self._pending.release()

    def _battle_changed(self, checkpoint: int | None) -> bool:
        return checkpoint is not None and self.bridge.arena.store.index != checkpoint

    def _battle_applied(self, ack: dict, checkpoint: int) -> bool:
        """A refusal cannot describe an attempt that wrote the native journal."""
        if ack['status'] != 'refused':
            return True
        if self._battle_changed(checkpoint):
            raise BoundaryError('recovery_pending')
        return False

    def _battle_apply(self, binding, request):
        if request['kind'] == 'behaviour':
            return self.bridge.apply(binding, request)
        arena = self.bridge.arena
        member = self.bridge._member(binding)
        if member is None or member['released'] or request['life_id'] != member['life_id']:
            raise BoundaryError('stale_slot')
        if self.battle_speech is None:
            raise BoundaryError('recovery_pending')
        try:
            speech = self.battle_speech(binding, dict(request['payload'], sequence=request['sequence']))
            return speech_ack(speech, arena.sim.state['tick'], request['payload'].get('emoji'))
        except Exception:
            # The feed callback may have posted before failing; its effects are
            # outside the engine journal and cannot be proved absent or retried.
            self._failed = True
            raise BoundaryError('recovery_pending') from None

    def _refused_ack(self, binding, request, code):
        arena = self.bridge.arena
        fix = {'version_mismatch':'Read the current terms, accept that version, and retry.',
               'stale_slot':'Read the current life notice and send its life_id.',
               'recovery_pending':'Ask the operator to restore the host, then retry.'}.get(code, 'Read state and use the current grant, life and terms before retrying.')
        if request['kind'] == 'speech':
            return dict(type='speech_ack', status='refused', receive_tick=arena.sim.state['tick'],
                        speech=dict(refused=code), summary='Speech refused: ' + fix)
        ack = checked_ack(request['payload'], arena.sim.rules, binding['nft_token_id'], int(request['sequence']),
                          arena.sim.state['tick'], rules_hash=arena.context['rules_hash'])
        return refuse(ack, arena.sim.rules, code, fix)

    def _battle_receipt(self, request, ack):
        value = {key: deepcopy(request[key]) for key in BINDING}
        value.update(domain=RECEIPT_DOMAIN, type='battle_receipt', kind=request['kind'], sequence=request['sequence'],
                     life_id=request['life_id'], request_digest=digest(request, exclude=('signature',)),
                     ack=deepcopy(ack), key_id=self.battle_key_id, signature='A' * 86)
        check_receipt(value)
        value['signature'] = self.battle_sign(canonical_bytes(value, exclude=('signature',)))
        check_receipt(value)
        return value


def speech_ack(speech: dict, tick: int, chosen_emoji: str | None = None) -> dict:
    if speech.get('refused'):
        status = 'refused'
        if speech['refused'] == 'rate_limited':
            summary = f"Speech refused: one line per 10 s; wait {speech.get('retry_after_s', 10)} sim seconds, then send speech again."
        else:
            summary = 'Speech refused: change the line and send it again (' + str(speech['refused']) + ').'
    elif speech.get('muted'):
        status, summary = 'muted', 'Speech muted: guard list missing; ask the operator to load it.'
    elif speech.get('blocked'):
        status, summary = 'blocked', 'Speech blocked: replaced with ' + speech['text'] + '; change the line before speaking again.'
    else:
        status, summary = 'posted', 'Speech posted: ' + speech.get('text', '')
    if speech.get('emoji_fallback'):
        summary += ' Using the persona default emoji.' if chosen_emoji is None else ' Emoji replaced with the persona default; choose one from its set.'
    return dict(type='speech_ack', status=status, receive_tick=tick, speech=deepcopy(speech), summary=summary)
