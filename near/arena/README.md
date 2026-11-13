The arena engine uses only the Python standard library. Run the deterministic
core cases from this checkout:

```sh
python3 -B near/arena/test_sim.py Determinism
```

`Sim(seed, rules)` owns integer state. Enqueue `Input` records with effective
ticks, or use `receive` to stamp them two ticks after the engine clock. Stable
ordering is tick, kind, fighter id, sequence. Identical duplicate records are
idempotent; changed duplicates and past inputs refuse. Hashes include pending
inputs and the complete random-generator state. `export` and `restore` resume
at a tick boundary under exactly the same rules hash. A rules object is copied
and frozen at construction. All tuning, phase order, random-generator values
and the literal quarter-wave sine table live in that object.

The combat cases run independently:

```sh
python3 -B near/arena/test_sim.py Combat
```

Six weapons and six shared signatures plus Dodge Roll use one tick policy with
five styles. The mechanical catalog is folded into the rules hash, including
house kits and rivalries. Damage uses integer percentage multiplication, rounds
down before and after the optional seeded variance draw, and has a minimum of
one. Zero variance draws nothing. Balance values remain tuning inputs; no
balance outcome is implied by these cases.

A KO scatters exactly one worn non-default item three to four tiles before
boundary clamping. Six undamaged ticks complete a grab. Ownership changes
immediately; duplicate rows disappear and unclaimed floor items expire after
thirty seconds under integer-17. Older recorded segments keep their own table's lifetime.
House bodies refuse player-origin drops. A house kit returns
on its next life. Legendary serials increase on the first grab of a new copy.
Inventory entries and equipped rows remain distinct.

Standalone bodies respawn after forty-five seconds. A composed server sets
`managed` and logs each spawn after its admission and pre-life checks. Leaving
requires five undamaged seconds in the surf; disconnect starts a thirty-second
grace period. The engine never reads a wallet, provider, network, file or wall
clock.

The server composition cases run with an explicit local room double:

```sh
python3 -B near/arena/test_server.py Composition
python3 -B near/arena/test_sim.py Compatibility
```

`Arena` binds a supplied room factory to `ArenaBridge` before control is
accepted. The bridge implements the nine game callbacks from the room package.
It neither implements wallet proofs nor exposes an independent control route.
The room package supplies authentication, current grants, the shared house and
guest validator, receipts and result signatures. Game identity, profile,
pre-life eligibility, loadout, sale and transport adapters are injected. Missing
configuration keeps admission closed. Executing `server.py` alone reports that
dependency; there is no automatic stand-in for production.

The composition root owns absolute monotonic deadlines at twenty ticks per
second and seals segments after 1,200 ticks. At most sixteen members are
admitted; excess reservations return `room_full` for the room's spectator
queue. At most six bodies enter the ring; waiting members appear on the bench.
Bench order advances at each KO. The scheduler can return a ready body early
when fewer than four remain, and gives due bodies their next free place.
House identities yield only between lives, with a target of at least six
admitted members and a floor of two house members as outsiders join. A supplied
house runtime's `poll` must drain completed work and population requests through
the same bound room service, with its distinct local capability. It must never
wait for a model inside a tick. Provider calls and their budget policy belong
to that runtime adapter.

Each coming life has one immutable, durable prediction or explicit no-prediction
lock. A two-second prediction window is published as an absolute server-time
deadline; retries do not extend it. The optional zero-KO estimate is independent
of the four-bin spread. A chosen kit is a logged engine input. The
composition currently refuses testnet NEAR authorisations, paired item moves and sale
locks in a pick until their game adapters are integrated. It never acknowledges
those actions as applied. Sale-control delegates to its supplied game adapter;
an absent adapter returns `recovery_pending`.

Only the configured data volume is writable, defaulting to `/srv/arena/data`.
The append journal commits accepted inputs, life locks and sparse clock cuts;
it never stores snapshot frames. Recovery replays those records. A crash may
discard the uncommitted portion of the current second. Public projections are
selected before persistence: player spend and prompts are never retained by
the engine. Leaving retains its authoritative bag; a changed owner requires
explicit reconciliation before re-entry. Provider profiles cannot reintroduce
an old bag while changes are pending.

Each segment file contains a boundary state, effective engine commands,
prediction records and the room-facing sealed metadata. Its sealed commitment
covers that complete material, and replay checks both that commitment and the
final state hash. Seed batches are supplied only after publication by the game
seed publisher; exhaustion pauses the engine. Input deduplication, receipt and
prediction caches are compacted at segment boundaries while preserving pending
inputs and current lives. Metrics retain a bounded sample window.

The full public map includes equipment, floor items, projectiles, telegraphs
and actions. Compact snapshots are encoded once each tick and fan out as the
same immutable bytes, with at most two pending frames per subscriber. A new
subscriber receives the current full snapshot. Two replays can execute at once;
their frames are cached only in memory, for at most eight segments. The supplied
transport binds loopback only, with compression disabled, and runs alongside
the authoritative clock. The separate web codec can replace the transport-side
adapter without changing simulation state.

The local double establishes isolated composition behavior. The installed room
also has separate real-service integration cases, described below. Production
wallet/signature adapters, browser transport, model calls, balances, chain writes
and host load remain separate integration work. These cases make no launch or
balance claim.

`room_host.RoomHost` assembles the installed `SlotStore`, `IdentityAuthority` and
`RoomService` against the actual engine bridge. Create a slot store with the
configured room id and capacity 16. Supply the host's canonical receipt signer,
session verifier, enabled wallet proof-method ids, durable one-use nonce
consumer, external security-journal callback and explicit recovery/admission
decisions. No callback creates keys or reads a provider configuration.

Pass the resulting `host` as Arena's `room_factory`, `host.sign_receipt` as
`receipt_signer`, `host.admission_ready` as `admission_gate`, `host.life_guard`
as `life_guard`, and the same millisecond clock to both. The game supplies
`profile_provider`, `identity_resolver` and `pick_resolver`: identity evidence
must independently verify wallet control and fresh owner/custody/lock state.
The signer, identity authority and service are created only once the actual
engine bridge exists, so none is bound to a stand-in. Reusing a bound host for
another engine refuses. Missing proof methods or readiness/admission callbacks
keep authority closed. Current life checks reauthenticate the actual grant and
generation against fresh game evidence. Only Arena.control reaches transports.

```sh
python3 -B near/arena/test_room_host.py CopiedRoom
```

These new cases exercise the real copied service, authority and durable slot
store with synthetic proof/signature/ownership adapters. They cover admission,
first-frame authentication, a pre-life prediction, a signed intent receipt,
public projection, signature refusal, ownership outage, closed gates, clock
refusal, a 1,200-tick engine seal, and an actual combat KO followed by the
service's next-life notice and another prediction. The fixture security recorder
is not a deployed external journal. No network, model, wallet or chain is used.
Without a public record adapter, result/replay/ledger reads refuse rather than
inventing records. The first-segment cold path below installs EngineRecords;
these older host cases retain their original scope.

`snap_client.SnapClient` supplies the owner-side canonical join, authenticated
control, exact-byte retry and public-read state machine. The runtime supplies
transport and its own proof/signature adapters. See [SNAP.md](../SNAP.md) for
the complete adapter contract and the new synthetic raw-loop process command.
`test_cold_join.py ColdJoin` covers client trust and retry behavior, a fresh
process through combat, synthetic record-response validation, and renewal
across the original join receipt's expiry. The client uses fresh signed ready
to confirm renewed authority. These older cases do not establish a complete
signed engine-result join.
Public prediction-row reads require a fresh verified signed result. Page inputs
must match that signed commitment; the full receipted lock and exact private
request choices must also match. A public page's own rehash is insufficient.

`engine_evidence.replay_evidence(archive)` is the read-only evidence input for
portable result assembly. It runs the actual archived engine commands, observes
every KO/leave step, derives life ids, KO counts and inventory hashes, and
compares those facts with the archived life rows. Full forecasts must match
their committed prediction locks and are returned without outer signatures.
The existing engine archive commitment and final-state check remain intact.
An already living body keeps its actual life id across segment boundaries.
Duplicated seal metadata must also agree with replay and native archive material:
segment label, completed-life list, current/completed/pending-join token set,
verified rules hash, actual seed and its hash, input hash and full forecast-log
hash. Rehashing an inconsistent header does not make it valid. Pending delayed
joins are included even when their bodies have not appeared at the boundary.

The witness returns `final_state_hash`, `lives`, `predictions` keyed by lock
reference, `input_lives` observed immediately before actual join/spawn/intent/leave
application, and `engine_commitment`. Each input witness binds its engine tick,
sequence, fighter and life, including same-tick ordering. Joins and spawns bind
their target life; intents and leaves bind their current recipient. A successful
full replay confirms that these inputs applied. The portable adapter consumes
each witness exactly once for the corresponding public join/life-start/intent/leave
row. Repeated enqueue history cannot publish one application twice, and raw
enqueue records alone do not establish application.
It copies the input archive and preserves
its ticks, indices, locks and bytes. It produces no room wire seal or signature.
The first-segment adapter below selects the forecasts actually used in its
portable event record. Cross-segment start/lock provenance remains a separate
source-owned contract and is refused by that adapter.

New witness cases: `python3 -B near/arena/test_engine_evidence.py EngineEvidence`
from the repository root. They use real archived combat, reject altered life
counts and forecasts even after an archive rehash, and replay a real life that
crosses a segment boundary with a signed leave and ordinary owner heartbeats.
Their synthetic authority and clock driver are fixture evidence only.

`portable_records.EngineRecords` composes the actual archive store, read-only
engine witness, portable Ledger and ResultAuthority. Its separate wire projection
orders effective events, keeps immutable prediction locks and their journal
indices, checks public gameplay rows against actual engine commands, and derives
the portable predecessor and full unsigned forecast hashes. Native archives are
unchanged. One successful native/portable projection is retained in memory,
keyed by the complete canonical native source, not merely its seal header.
Unchanged reads reuse those verified facts; changed source revalidates before
use. The ledger's full wire seal and current signing authority are still checked
on every result. Concurrent first verification refuses rather than repeating
engine work; at most 8 segments are kept, oldest dropped first.
Every sealed segment projects, with complete in-segment provenance only: a
result lists the lives locked, started and ended inside its segment, and a life
that carries in from an earlier segment is left out rather than given invented
carry-in history. Future-boundary rows and index collisions refuse. Until
sealing, results return `result_pending`.

From the repository root, the single cold case is:

```sh
python3 -B near/arena/test_snap_cold.py SnapCold.test_snap_only_temp_agent_accepts_predicts_fights_ko_and_signed_result
```

It extracts the executable program from SNAP.md verbatim into a clean temporary
owner folder and starts isolated Python. The cold process imports only the public
client/schema slice, joins from synthetic account proof, reads and explicitly
accepts the current arena rules, predicts, sends intents, renews, observes combat and a KO,
and verifies its own signed result and public lock. The parent drives the real
room and engine with synthetic adapters; it substitutes no result responses.
The same new case checks unchanged native archives, unsupported carry-in refusal,
pre-seal refusal and rehashed public-input contradictions. Real wallet proof,
Ed25519, TLS transport, settlement and deployed acceptance remain separate gates.

The installed service binds through
`room_service_factory(slots, identity, **service_options)`, supplied as Arena's
`room_factory`. It imports only the installed `room.service.RoomService`; a
missing copy raises an import error. The supplied identity, slot store and
service options own proofs, current authority, readiness and the external
security journal. No production double or automatic admission is installed.

Transport and house runtime receive the same `Arena.control` port. Its methods
are `request`, `open_control`, `frame`, `close_control`, `drain_private` and
`drain_snapshots`, matching the service's bytes-based ingress. The port exposes
no bridge or host-clock callback. Client identity and its distinct house
capability still come from ordinary service authentication. Host ticks invoke
service maintenance and snapshot publication; a host whose transport never calls
`drain_snapshots` passes `room_snapshots=False` and publishes none (the DEV and
hosted host, `snap_local.py`, does: its clients observe on demand, which still
projects and validates). That host's slot store is `room_host.HostSlotStore`,
which skips the per-tick `expire()` rewrite of the slot state until a lease could
lapse (and at least once a second). KOs notify `life_boundary` with
the current grant id after reserving the next engine life. Release retirement
does not invent a new life notification.

Receipt and prediction commitments use the frozen canonical wire bytes,
excluding only the outer signature. All control characters use lowercase
Unicode escapes; Unicode text and literal backslashes remain distinct. These
wire commitments do not change archived simulation hashes. Release reports the
member's last accepted control sequence rather than the engine input counter.
The composed room rejects clocks other than 20 Hz and 1,200-tick segments.

Host binding cases: `python3 -B near/arena/test_bridge.py FrozenBridge`.
They run with an explicit fixture authority, without wallet or model access.
When `room/bridge.py` is installed at the repository root, each fake dispatch
also checks arguments and replies against its actual structural types. Before
installation, set `ROOM_CONTRACT_DIR` to a directory containing the frozen
bridge and schema to enable that same check without copying files. Without
either source, the portable dispatch/clock cases still run; they do not claim
full frozen-type conformance. A wrong request kind, missing activation argument
or incompatible service constructor fails the fixture's boundary check.
Full service authentication, queue/life integration and launch remain separate
checks after the exact room copy and operational adapters are installed.

House targeting cases: `python3 -B near/arena/test_policy.py Bounty`.
The named-item hunt adds 150 only while an enemy wears the house identity's
legendary. A bag entry does not activate it, and the hunt has no time limit.

Optional-control cases: `python3 -B near/arena/test_policy.py Knobs`.
All four controls stay off by default. Misses consume the shared random stream
only for shot, beam and beam sweep. The looter can return from fleeing after
the survivor interval; the melee dash has its own cooldown. When enabled, the
beam slowdown covers windup and active sweeps under integer-4 rules. Earlier
tables retain their earlier behavior. Comparative measurements belong to the
balance report; enabling a control requires an operator choice.

Rival targeting cases: `python3 -B near/arena/test_policy.py Rivalry`.
Integer-5 gives house rivals the 300 term and permits seeking them beyond the
ordinary policy search radius, across the whole ring. This policy radius does
not affect the full public map. Earlier tables keep their recorded policy.

Replay cases: `python3 -B near/arena/test_replay.py Replay`.
`python3 -B near/arena/replay.py /path/to/segment.json` resolves the segment's
exact archived rules and prints the independently reproduced final-state hash.
Unknown rules, changed sealed material, invalid commands and changed final
states refuse. Frames are produced only in memory. Concurrent duplicate
requests share a computation; at most two workers run, eight requests wait
or run, and eight completed segments remain cached.

The transport receives an `open_replay` callback as `replay`. Await it, subscribe
to the returned channel, and run its `play()` task until completion or client
disconnect. The channel sends verified frames at twenty ticks per second using
the same `Fanout` as live delivery, with independent bounded subscriber queues.
Playback does not change live state. The transport also receives `health`, to
expose at `/health`: free disk bytes, engine tick, failure flag, and green,
amber below 5 GB or red below 2 GB. Actual HTTP and WebSocket routing remain the
injected transport's responsibility.

Boundary regression cases: `python3 -B near/arena/test_returns.py Returned`.
Release durably cancels queued activation before logging leave. Recovery
reconstructs the same per-tick command log and publishes or validates every
completed seal before advancing to another segment. A failed seal closes
admission. Integer-6 also makes Dodge Roll respond to live Beam and Lob warning
geometry; earlier rules retain their recorded trigger behavior.

Balance cases run with `python3 -B near/arena/test_balance.py Baseline Sweep Summary`.
The measurement command uses the actual integer engine and managed lives:

```sh
python3 -I near/arena/balance.py --seeds 1 --ticks 1200 --workers 2 --output balance-initial.json
python3 -I near/arena/balance.py --rules-hash 629573d443c3034e96ddcaca3a00194e8a3349ebf3baa17862962e0426df2bd7 --seeds 1 --ticks 1200 --workers 2 --output balance-tuned.json
python3 -I near/arena/balance_summary.py balance-initial.json --json balance-summary.json --markdown balance-summary.md
```

The default plan measures variance 10, 15, 20, 25 and 30 with all optional
controls off, then each single control at variance 20. Set
`--comparison-variance` to another measured value to move those comparisons.
Positive-density scenarios run for 4,800 ticks by default so repeat deaths can
be observed across respawns; change that with `--density-ticks`. Other samples
run for the requested 1,200 ticks. Increase `--seeds` for a larger sample.
`--checkpoint` retains checksummed measurements for interrupted local runs.
`--resume-source` may point at the preceding measurement script after a
scheduling-only edit: its measurement functions and constants must match
structurally, or reuse refuses. No code from that file is executed.
A change confined to the named leave-policy block invalidates the escape and
stop-at-one families; other families are retained only after source comparison.

Integer-9 ports the baseline threat sidestep, 350-speed/250-radius shot,
50% weapon/signature counter cycles and shot recharge slowdown. Counters apply
after base damage rounding and before seeded variance. These rules include
the earlier warning-trigger fix and the tuned weapon/signature constants.
Integer-10 is a separate tuning candidate:
the hunt weight is 100. Select it with `--rules-hash` using its canonical hash;
it does not replace the default table or enable an optional control.

Integer-11 is the default table with fourteen named legendary quirks. Its
`item_quirks` data contains each one-line description and item-local overrides
of the existing signature parameters. The quirks travel with a grabbed copy,
for house and player holders alike. All item stat budgets remain unchanged;
the new tradeoffs are unmeasured, with no balance certification. The default
hunt weight remains 150 and optional controls remain off. Released tables
remain available for exact replay.

Under this table, each signature binds its item, effective range, damage
percentage, tier and signature parameters when its cast starts. A grab during
the warning cannot change that cast; sweeps and shield pops retain their bound
parameters through export/restore. Tables without `item_quirks` retain their
previous cast behavior. Quirk overrides accept only existing positive integer
signature parameters; malformed quirk records refuse during rules validation.
The public room snapshot's cast telegraphs use the same bound range percentage
and signature parameters as resolution. Legacy casts retain their shared-table
fallback. This projection leaves the frozen compact tick format unchanged.
Stack Sats changes shield burst size and loot cadence; Priority Fee changes
them in the opposite direction. Both retain the base shield-to-cooldown ratio,
so their descriptions make no claim of lower shield throughput.

The focused cases are `python3 -B near/arena/test_quirks.py Quirks Bindings
QuirkReplay QuirkData`. Passing `--rules near/arena/rules/integer-9.json Quirks`
is the intentional negative baseline: all fourteen quirk cases fail there.
The replay case seals a seeded 1,200-tick segment starting with active casts
and reproduces its state hash twice using the archived new table.
The focused projection regression is `python3 -B near/arena/test_quirk_telegraphs.py
Telegraphs ShieldText`: six quirk shapes, their boundaries, a changed live range
stat after casting, the legacy fallback and the shield/cadence descriptions.

The report contains random default and mixed builds across all five styles,
the five closed presets, mirrored pairs, loot rates, 52/72-point builds,
pick pressure, item-density pairs with the hunt on and off, conservative
inventory picks and escape trajectories. Admitted crowd sizes are 2/6/10/16;
at most six bodies fight at once. In the fourteen-item small-crowd scenario,
excess items are held in bags, and only present house identities can hunt.

All seven balance fields retain observations and denominators. Worn-item KO
indices use time in hand; survival cohorts use the starting kit. Completed
life averages exclude the separately counted unfinished lives. Zero-KO lives
remain in the five-bin base-rate spread. The rare/newcomer set-piece readout
uses the first rare life: it must defeat all distinct newcomers before dying,
with at least N-1 KOs. Surviving winners count; unresolved runs stay censored.
The stop-at-one
and shared-owner scenarios measure fight trajectories; prediction-log scoring
and settling testnet NEAR on predictions require their separate game adapters.
The summary also scores a clearly labelled counterfactual all-on-one attacker
policy against those observed trajectories. Its five-bin ranked score keeps
zero outcomes, and its empirical own-base diagnostic remains unset below ten
lives. These are synthetic diagnostic rows, with no model call, pre-life
signature, live trailing calibration or NEAR transfer claimed.

The checked-in report records one seed per cell as exploratory observations.
It retains missing cells and exceedances and carries no balance certification.
The compact JSON and table compare the baseline and the first tuning candidate;
complete raw measurements can be regenerated by the commands above. Threshold
locking, final tuning acceptance and optional-control selection remain review
decisions.

The focused application-cardinality regression builds an actual room/engine
archive and duplicates a join enqueue plus its public metadata, recomputing the
native commitments. The engine still applies that join once; result publication
must refuse without signing or changing the source archive. Its intact controls
still sign, and a duplicated life-start also remains refused. Run only the new
case with `python3 -B near/arena/test_record_applications.py
RecordApplications.test_join_and_spawn_cannot_publish_one_application_twice`.

## Rules table integer-12: a focus order lands

`integer-12` changes one constant from `integer-11`: `focus_weight` 150 -> 2700. A
focus order (`intent --focus <id>`) on an enemy in view now takes the target on
the first policy tick after it applies (receive tick + 2), whatever was held
before. 2700 is the smallest round number above the sticky bound: a focused enemy
with base score 0 must beat `sticky_percent` (125%) of the largest score any other
target can reach (guardian, 2150). At 1000 a brawler or guardian holding a close,
hurt, just-hit enemy kept it. `integer-11` stays on disk, so its segments replay
under their own hash. The case is `python3 -B near/arena/test_focus.py`.

## Rules table integer-13: battle mode

`integer-13` is `integer-12` plus battle mode: a fighter's AI sends a **behaviour**
(drives, an attack gate, a target mode and up to 8 reflexes; the schema is
`BEHAVIOUR.md`) that the engine runs every tick and keeps across respawns. Four keys
change and nothing else: `version`, `input_kinds` (adds `behaviour`),
`intent_interval` 40 -> 10 (one order per 0.5 s, shared by behaviours and intents)
and the new `behaviour` block (limits and the seven stance presets).
`behaviour.py` normalises a behaviour and writes the host's ACK receipt; the engine
accepts only the normalised form, so a replay never re-runs a clip. A fighter
without a behaviour runs the style AI exactly as in `integer-12`, and `integer-11`
and `integer-12` stay on disk for their segments. The cases are
`python3 -B near/arena/test_behaviour.py`; `python3 -I near/arena/battle_measure.py`
prints Pat's example measured in seeded crowds and the tick cost at 16 fighters x 8
reflexes.

## Rules table integer-14: chase seeks out of view

`integer-14` is `integer-13` plus one key, `behaviour.chase_seek: true`. A fighter
on a behaviour with `chase` above 0 and no target in view walks toward the nearest
enemy anywhere on the ring that passes its gate, the way rival seek already works
for house rivals. Under `integer-13` two berserkers who spawn out of each other's
view stood still for the whole segment (`BATTLE-BALANCE.md` finding 4); under
`integer-14` they meet and land a hit within about 3 s. `integer-13` stays on disk
and keeps its own behaviour for its segments. The cases are `ChaseSeek` in
`python3 -B near/arena/test_behaviour.py`.

## Rules table integer-15: no stepping back and forth on the spot

`integer-15` is `integer-14` plus one key, `steer_band: 1000` (one tile). Under
`integer-14` every drive switched on or off at its edge (the keep-away radius, weapon
reach, the hold radius, the ally radius, a drop) and the summed pull always moved the
fighter a full stride, so a fighter on an edge stepped across it and straight back,
tick after tick: a body vibrating on the spot. Under `integer-15` each pull is
continuous at its edge (keep-away is zero at the radius and full touching; chase is
full outside reach and eases to nothing at three quarters of reach; hold, protect and
loot ease in over one tile) and the step is as long as the net pull against the
drives that pull at all, so drives that balance leave the fighter standing. A fighter
with no behaviour, in the survivor or looter style, backs off and closes in the same
way around its preferred distance. In a 5-fighter crowd the visible back-and-forth
fell from 93, 148 and 27 reversals per 1000 alive ticks to at most 2. `integer-14`
stays on disk and keeps its own movement for its segments. The cases are `Steering`
in `python3 -B near/arena/test_behaviour.py`.
