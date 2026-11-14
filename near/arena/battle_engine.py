"""The behaviour bridge: one normalised, guarded, replayable input per ACK."""
from copy import deepcopy

try:
    from . import behaviour as battle
    from . import sim
except ImportError:
    import behaviour as battle
    import sim
from room.policy import digest


def checked_ack(raw, rules, who, sequence, tick, **options):
    try:
        return battle.ack(raw, rules, who, sequence, tick, **options)
    except (TypeError, ValueError):
        # A checker fault happens before enqueue. Refuse this order without
        # turning one malformed plan into a failure of the whole room.
        problems = [dict(path='', code='validator_unavailable',
                         fix='Use whitelisted integer drives, gates and reflexes; if a valid plan still fails, ask the operator to restore the checker.')]
        summary = battle.summary(None, [], problems, [], tick + rules['input_delay'], tick, rules)
        return dict(type='behaviour_ack', v=1, fighter=who, seq=sequence, status='refused', receive_tick=tick,
                    apply_tick=None, applies_in_ms=None, behaviour=None, clipped=[], refused=problems, notes=[],
                    summary=summary, rules_hash=options['rules_hash'])


def refuse(ack, rules, code, fix):
    ack.update(status='refused', behaviour=None, apply_tick=None, applies_in_ms=None)
    ack['refused'].append(dict(path='', code=code, fix=fix))
    ack['summary'] = battle.summary(None, ack['clipped'], ack['refused'], ack['notes'],
                                    ack['receive_tick'] + rules['input_delay'], ack['receive_tick'], rules)
    return ack


def _guard_plan(ack, arena, who):
    for index, reflex in enumerate(ack['behaviour'].get('reflexes', []), 1):
        action = reflex['then']
        if 'say' not in action:
            continue
        guard = getattr(arena, 'battle_guard', None)
        checked = (guard(who, action['say']) if guard is not None else
                   dict(text='(._.)', blocked=True, reason='guard-list-missing'))
        if checked['blocked']:
            muted = checked['reason'] == 'guard-list-missing'
            action['say'] = checked['text'] + ('' if muted else ' [blocked line]')
            fix = ('speech muted: guard list missing; ask the operator to load it' if muted else
                   'speech blocked: replaced with an emote; change the line')
            ack['clipped'].append(dict(path=f'reflexes[{index}].then.say', sent='[guarded line]', set=action['say'], fix=fix))
    if ack['clipped']:
        ack['status'] = 'clipped'
    ack['summary'] = battle.summary(ack['behaviour'], ack['clipped'], [], ack['notes'],
                                    ack['apply_tick'], ack['receive_tick'], arena.sim.rules)
    return ack


def apply_behaviour(bridge, binding, message):
    arena = bridge.arena
    rules, tick, who = arena.sim.rules, arena.sim.state['tick'], binding['nft_token_id']
    member = bridge._member(binding)
    last = None if member is None else member['last_receive'] + rules['input_delay']
    roster = (arena.target_roster() if hasattr(arena, 'target_roster') else
              [dict(id=name, name=row['profile']['public_name'], tag=row['profile']['public_name'])
               for name, row in sorted(arena.members.items()) if not row['released']])
    ack = checked_ack(message.get('payload'), rules, who, int(message['sequence']), tick,
                      last_order_tick=last, present=arena.sim._live(), rules_hash=arena.context['rules_hash'],
                      roster=roster)
    if member is None or member['released']:
        return refuse(ack, rules, 'stale_slot', 'Rejoin with the current grant before sending a behaviour.')
    key = sim.digest([arena.context, binding['grant_id'], binding['session_key_id'], message['sequence']])
    fingerprint = digest(message, exclude=('signature',))
    prior = arena.receipts.get(key)
    if prior is not None:
        if prior['request_hash'] != fingerprint:
            return refuse(ack, rules, 'request_conflict', 'Use a new sequence for a changed behaviour.')
        return deepcopy(prior['receipt'])
    if message.get('life_id') != member['life_id']:
        refuse(ack, rules, 'stale_slot', 'Read the next life notice and send its current life_id.')
    elif who not in arena.sim.state['fighters']:
        refuse(ack, rules, 'prediction_closed', 'Wait for life_start, then send this behaviour again.')
    elif arena.at_edge():
        refuse(ack, rules, 'rate_limited', 'The segment is turning over; wait 0.2 s and send a new sequence.')
    if ack['status'] != 'refused':
        try:
            _guard_plan(ack, arena, who)
        except Exception:
            refuse(ack, rules, 'recovery_pending', 'The speech guard is unavailable; ask the operator to restore it, then retry.')
    if ack['status'] != 'refused':
        arena._enqueue('behaviour', who, ack['behaviour'])
        member['last_receive'] = tick
        member['last_sequence'] = message['sequence']
        arena._member_changed(who)
        # The copied portable replay schema has no behaviour row. The complete
        # normalized command stays in the native input journal and its seal;
        # the engine's apply event confirms it on the live connection.
    else:
        # The room keeps a bounded refusal tail/high-water mark. Do not allocate
        # an engine journal row for every refused rate-limit probe.
        return deepcopy(ack)
    stored = dict(key=key, request_hash=fingerprint, receipt=deepcopy(ack))
    arena._record('receipt', stored)
    arena.receipts[key] = stored
    return deepcopy(ack)
