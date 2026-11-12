"""Closed game-owned battle envelopes; the portable room protocol is unchanged."""
from room.policy import BoundaryError, canonical_bytes, validate
from room.protocol import parse_message

BINDING = ('context', 'grant_id', 'session_key_id', 'member_id', 'nft_token_id', 'persona_digest', 'slot_id', 'generation')
KINDS = frozenset(('behaviour', 'speech', 'bench', 'note'))
REQUEST_DOMAIN = 'arena.battle.v1'
REJOIN_WINDOW_MS = 30_000   # a signed rejoin must be this fresh (wall clock) on the host that checks it


def rejoin_message(round_index, public_key, at_ms):
    """The bytes a live session signs with its own session key to rejoin round `round_index` as the identity that key
    already holds. Bound to that round and a wall-clock time, so it can't be replayed into another round or kept."""
    return f"arena.rejoin.v1|{int(round_index)}|{public_key}|{int(at_ms)}".encode()
RECEIPT_DOMAIN = 'arena.battle.receipt.v1'
REQUEST_FIELDS = frozenset((*BINDING, 'domain', 'kind', 'sequence', 'life_id', 'payload', 'signature'))
RECEIPT_FIELDS = frozenset((*BINDING, 'domain', 'type', 'kind', 'sequence', 'life_id', 'request_digest', 'ack', 'key_id', 'signature'))
BEHAVIOUR_ACK_FIELDS = frozenset(('type', 'v', 'fighter', 'seq', 'status', 'receive_tick', 'apply_tick', 'applies_in_ms',
                                 'behaviour', 'clipped', 'refused', 'notes', 'summary', 'rules_hash'))
SPEECH_ACK_FIELDS = frozenset(('type', 'status', 'receive_tick', 'speech', 'summary'))
# The bench (Q5): hold the trenchie on the bench, send it back in, or swap a bag item on for the next life.
BENCH_ACK_FIELDS = frozenset(('type', 'status', 'receive_tick', 'bench', 'summary'))
BENCH_SLOTS = ('body', 'head', 'trinket', 'weapon')
# An agent session's note to its owner's panel (never the public feed): the order in the owner's words, the reply in
# the trenchie's voice, why it set what it set, and the plan's weekly use when the session can report it.
NOTE_ACK_FIELDS = frozenset(('type', 'status', 'receive_tick', 'summary'))
NOTE_TEXT_MAX = 300


def _require(condition):
    if not condition:
        raise BoundaryError('bad_message')


def _binding(value):
    validate('MainnetContext', value['context'])
    for field in ('grant_id', 'session_key_id', 'member_id', 'slot_id', 'life_id'):
        validate('Id', value[field])
    validate('TokenId', value['nft_token_id'])
    validate('Hash', value['persona_digest'])
    validate('U64', value['generation'])
    validate('U64', value['sequence'])
    validate('Signature', value['signature'])
    _require(type(value['kind']) is str and value['kind'] in KINDS)


def check_request(value):
    _require(type(value) is dict and set(value) == REQUEST_FIELDS)
    parse_message(canonical_bytes(value))
    _require(value['domain'] == REQUEST_DOMAIN)
    _binding(value)
    if value['kind'] == 'speech':
        payload = value['payload']
        _require(type(payload) is dict and {'text'} <= set(payload) <= {'text', 'emoji'})
        _require(type(payload['text']) is str and 1 <= len(payload['text']) <= 140 and payload['text'].isprintable())
        emoji = payload.get('emoji')
        _require(emoji is None or type(emoji) is str and len(emoji) <= 64)
    elif value['kind'] == 'bench':
        _check_bench(value['payload'])
    elif value['kind'] == 'note':
        _check_note(value['payload'])
    return value


def _check_bench(payload):
    _require(type(payload) is dict and len(payload) == 1)
    if 'hold' in payload:
        _require(type(payload['hold']) is bool)
        return
    _require(set(payload) == {'equip'} and type(payload['equip']) is dict and set(payload['equip']) == {'slot', 'item_id'})
    _require(payload['equip']['slot'] in BENCH_SLOTS)
    item = payload['equip']['item_id']
    _require(type(item) is str and 1 <= len(item) <= 64 and item.isprintable())


def _note_text(value, limit=NOTE_TEXT_MAX):
    _require(type(value) is str and 1 <= len(value) <= limit and value.isprintable())


def _check_note(payload):
    _require(type(payload) is dict and payload and set(payload) <= {'seq', 'order', 'reply', 'why', 'plan'})
    if 'seq' in payload:
        _require(type(payload['seq']) is str and payload['seq'].isdigit() and len(payload['seq']) <= 20)
    for field in ('order', 'reply', 'why'):
        if field in payload:
            _note_text(payload[field])
    _require(any(field in payload for field in ('order', 'reply', 'why', 'plan')))
    if 'plan' in payload:
        plan = payload['plan']
        _require(type(plan) is dict and set(plan) == {'week_used_pct'})
        used = plan['week_used_pct']
        _require(used is None or type(used) is int and 0 <= used <= 100)


def _whole(value):
    return type(value) is int and 0 <= value < 2 ** 64


def _behaviour_ack(ack, value):
    _require(set(ack) == BEHAVIOUR_ACK_FIELDS and ack['type'] == 'behaviour_ack' and type(ack['v']) is int and ack['v'] == 1)
    _require(ack['fighter'] == value['nft_token_id'] and type(ack['seq']) is int and ack['seq'] == int(value['sequence']))
    _require(ack['rules_hash'] == value['context']['rules_hash'])
    _require(ack['status'] in ('applied', 'clipped', 'refused'))
    for field in ('clipped', 'refused', 'notes'):
        _require(type(ack[field]) is list and len(ack[field]) <= 256)
    _require(all(type(item) is str for item in ack['notes']))
    for field in ('clipped', 'refused'):
        _require(all(type(item) is dict and type(item.get('fix')) is str for item in ack[field]))
    if ack['status'] == 'refused':
        _require(ack['apply_tick'] is None and ack['applies_in_ms'] is None and ack['behaviour'] is None and bool(ack['refused']))
    else:
        _require(_whole(ack['apply_tick']) and _whole(ack['applies_in_ms']) and not ack['refused'])
        _require(ack['apply_tick'] >= ack['receive_tick'] and type(ack['behaviour']) is dict)


def check_receipt(value):
    _require(type(value) is dict and set(value) == RECEIPT_FIELDS)
    _require(len(canonical_bytes(value)) <= 65536 and value['domain'] == RECEIPT_DOMAIN and value['type'] == 'battle_receipt')
    _binding(value)
    validate('Hash', value['request_digest'])
    validate('Id', value['key_id'])
    ack = value['ack']
    _require(type(ack) is dict and _whole(ack.get('receive_tick')))
    _require(type(ack.get('summary')) is str and 1 <= len(ack['summary']) <= 32768)
    if value['kind'] == 'behaviour':
        _behaviour_ack(ack, value)
    elif value['kind'] == 'bench':
        _require(set(ack) == BENCH_ACK_FIELDS and ack['type'] == 'bench_ack' and ack['status'] in ('applied', 'refused'))
        _require(type(ack['bench']) is dict)
    elif value['kind'] == 'note':
        _require(set(ack) == NOTE_ACK_FIELDS and ack['type'] == 'note_ack' and ack['status'] in ('kept', 'refused'))
    else:
        _require(set(ack) == SPEECH_ACK_FIELDS and ack['type'] == 'speech_ack' and type(ack['speech']) is dict)
        _require(ack['status'] in ('posted', 'blocked', 'muted', 'refused'))
    return value
