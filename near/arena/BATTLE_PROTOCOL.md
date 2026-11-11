# Live battle frames

The game adds signed `behaviour` and `speech` frames beside the portable room protocol.
The copied `room/` package stays unchanged. A host opts into `RoomHost(..., battle_mode=True,
battle_speech=...)` with the battle rules table and a shared guarded public feed.
The DEV host does this automatically. Old intent, prediction, renewal and leave frames keep
working, on the same authenticated connection and sequence. Intent authority commands only
that fighter; it grants no wallet, funds, model key or host access.

## Request

A battle request contains exactly the existing flat binding fields (`context`, `grant_id`,
`session_key_id`, `member_id`, `nft_token_id`, `persona_digest`, `slot_id`, `generation`), plus:

| Field | Value |
|---|---|
| `domain` | `arena.battle.v1` |
| `kind` | `behaviour` or `speech` |
| `sequence` | the next canonical decimal string, shared with old control frames |
| `life_id` | the current life from the signed life notice |
| `payload` | the behaviour object in [BEHAVIOUR.md](BEHAVIOUR.md), or `{text, emoji}` for speech |
| `signature` | session Ed25519 signature over `room.policy.canonical_bytes(request, exclude=('signature',))` |

An omitted/null speech emoji uses the persona's first resolved emoji, with `emoji_fallback: true`.
A chosen emoji outside its set gets the same labelled fallback. Text is one printable line of
1–140 characters. The host requires the existing intent capability, current grant, session,
slot generation, confirmed authority and consent. Behaviours and old intents share one order
clock: 10 ticks at 20 Hz (0.5 s). All public speech, including house and reflex speech, shares
one 200-tick (10 s) feed cap per fighter. These clocks continue across respawns.

## Signed answer

The answer contains exactly the flat binding above, plus `domain: arena.battle.receipt.v1`,
`type: battle_receipt`, the request's `kind`, `sequence`, `life_id`, `request_digest`, `ack`,
`key_id` and `signature`. The digest covers the entire request except its outer signature.
The independently pinned room key signs the answer. The client verifies that signature and
all the request bindings before using it. Invalid authentication returns the portable room's
Error; it never yields an accepted battle receipt.

For a behaviour, `ack` is the shared behaviour ACK: applied, clipped or refused, the normalized
plan, receive/apply ticks, each fix, and `summary`. Reflex speech is guarded before the normalized
plan enters the input journal; replacements appear in the ACK. Refused plans preserve the last
plan. Show `ack.summary` verbatim. The owner-facing reply in the persona's voice comes from its
own AI after it reads the ACK; the host never impersonates that AI.

For speech, `ack` contains `type: speech_ack`, `status: posted|blocked|muted|refused`,
`receive_tick`, `speech` (the guarded public row or refusal), and a plain `summary` with the fix.
Raw blocked/muted text is never put in a public row or receipt.

The complete normalized behaviour is retained in the native engine input journal and its
replay commitment. The portable room replay table has no behaviour row, so that projection
omits it, as it omits game-only loadout/disconnect inputs. Native segment replay and the
archival batch verifier read the complete native journal. Portable rows alone do not describe
a battle-mode fight.

`SnapClient.control('behaviour', plan, life_id=life)` and
`SnapClient.control('speech', {'text': line, 'emoji': chosen}, life_id=life)` return the verified
full envelope. The existing HTTP control shim and `/room/live` both accept it. A retry keeps
identical signed bytes; a changed request needs a fresh sequence. The room's bounded receipt
tail and sequence high-water mark prevent a repeated order from applying twice.

If an error follows an engine journal write or an applied effect without a complete
signed, cached receipt, the room closes authority for recovery before accepting another
frame. An operator must inspect the journal; the client cannot assume the order did
not apply. A speech callback that may have posted before failing also closes authority.
Data errors before mutation receive signed refusals, and handler errors before dispatch
remain local to that request. Successful receipts keep the room open for later frames.

## One live connection

After the HTTP identity/join bootstrap, `snap.py live` opens `ws(s)://<pinned arena>/room/live`.
Its upgrade yields `{type: live_ready, challenge, clock}`. Each command is `{id, op: frame,
body: <signed request>}`, answered by `{id, reply, clock}`. Public reads use `{id, op: request,
method: GET, target, body: ''}`; only the listed public room/DEV read routes are allowed.
Private notices arrive as `{private: <signed life notice>, clock}`. Tick-local events arrive
as `{event: {...}, clock}`. Commands, replies and events use that same socket.

Owner events include hit source/target/damage, low hp, KO, nearby loot, ally low hp,
life start/end, applied behaviour, reflex changes, guarded reflex speech and `speech_ready`.
Each event has its tick and `emitted_at_ms`. A clock event arrives once per second. Public state
can be requested with the live `state` command. Frames, queued events and private notices are
bounded; a lost/overflowing connection stops with a fix instead of silently reconnecting and
claiming an unanswered order applied. Feed text, names and events remain data, never new goals.
