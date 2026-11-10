# Room protocol

Wire version **1**, schema version **1.2.1**. The schema identifier is
`urn:room:protocol:1.2.1`. This document freezes interfaces, not a running service.
All authentication, custody, persistence, recovery and deployment gates must be
implemented and independently checked before admission opens.

`protocol.schema.json` is the complete closed wire contract. Each definition has
valid `examples`; `x-wire-messages` enumerates transport forms. Every object field
is required, including fields whose value may be `null`. Every field is exercised
by its definition's examples. `x-invalid-examples` records broken messages.
Unknown fields, kinds, queries, duplicate JSON keys and noncanonical values refuse
before dispatch. No extension bag or executable input is accepted.

## The eight verbs

| Verb | Transport and exact schema definitions | Effect and authority |
|---|---|---|
| `seat` | `GET /room` → `Manifest`; `POST /room/challenge` accepts `JoinChallengeRequest`, `SaleChallengeRequest` or `LookupChallengeRequest` and returns its matching `JoinChallenge`, `SaleChallenge` or `LookupChallenge`; `POST /room/join` accepts `JoinRequest` → `JoinAccepted` or `QueueStatus`; socket `RenewRequest`, `LeaveRequest` → `Receipt` | Owner/custody proof reserves one persona and slot atomically. A queue entry spectates without control. Renewal uses server time; leave revokes immediately. |
| `observe` | `GET /room/observe` → `PublicSnapshot`; socket `ObserveRequest` → `PublicSnapshot` and a private `Receipt` | Public full arena state; no member credentials, prompts, reasoning or player spend. Spectators have no input authority. |
| `act` | Socket `IntentRequest` or `PredictionRequest` → `Receipt` | Same validator for house, browser and outside harness. The host applies intents on its clock; predictions use the pre-life fence. |
| `tick` | `GET /room/tick` → `Clock` | Read only. 20 Hz, 60 seconds, exactly 1,200 ticks per complete segment. No client clock/advance verb exists. |
| `limits` | `GET /room/limits` → `Limits` | Read only. Advertised server limits constrain every request. A guest cannot raise them. |
| `result` | `GET /room/result?segment_id=…` → `Result` or `Error`; writer callback → `BatchAcknowledgement` | Only a sealed complete segment is signed. Mainnet and testnet destinations require separate envelopes. A pending hop stays pending. |
| `replay` | `GET /room/replay?segment_id=…&after_index=…` → `ReplayPage` | Bounded engine-effective inputs and seed for deterministic replay. Two active replays; no stored snapshot stream is required. |
| `ledger` | `GET /room/ledger?after_index=…` → `LedgerPage` | Append-only public event projection and hashes. Private receipts remain on the member's authenticated connection. |

`ReadRequest` is the typed routing representation of those GET paths and query
parameters, never a GET body. `segment_id` is required only for result/replay;
`after_index` is allowed only for replay/ledger. A missing cursor starts at zero.
The adapter supplies required nulls in the typed representation. GET bodies and
unlisted query parameters refuse. Read-only routes require no slot token.
Result reads and replay pages share max_replays; saturation returns rate_limited
without waiting. ResultReader retains up to 128 successful engine outcomes by
segment and sealed hash, bound to the exact source record. A duplicate in-flight
verification refuses rate_limited. Cache hits recheck the seal and current signing
authority without running the engine again; evicted entries are verified anew.
Every transport can return `Error`; authenticated refusals also get a signed
`Receipt` when the request can be safely bound to current authority.

The separate owner-only route `POST /room/sale-control` accepts
`SaleControlRequest` or `SaleControlLookup` → `SaleAcknowledgement`. It grants no
slot and is not a ninth guest capability. Its challenge/proof does not require a
model key, active fighter or rejoin.

HTTPS and WSS are mandatory. `JoinAccepted.control_url` is the configured origin's
fixed `/room/control` endpoint. `Manifest.control_authentication` is
`first_frame_v1` for browser, native and house clients alike. The upgrade does
not require custom headers, cookies or a token in a URL or subprotocol. The
member must pin the configured origin and room verification keys before trusting
challenges, grants or receipts. A manifest is public configuration, not proof
of authority.

### Socket authentication

1. Connect using `new WebSocket(grant.control_url)` in a browser, or the same
   fixed URL in a native client. Before upgrade, the edge checks configured host,
   TLS, path, request size/rate and the exact allowed `Origin` when present.
   Reject an unapproved Origin, including `null`. Native clients may omit Origin;
   they receive the same proof checks. Origin alone never proves account control.
2. The server emits a signed `ControlChallenge`, with a random connection id,
   unpredictable nonce, current context and an expiry at most 10 seconds away.
   Until authenticated, this socket receives no member data and has no dispatch
   authority. Limits default to 32 unauthenticated connections globally and two
   per source IP, advertised by `Limits.unauthenticated_connections` and
   `unauthenticated_per_ip`. Refuse excess before allocating a challenge; reserve
   no fighter or slot. Apply the existing maximum bytes/depth/arrays to the
   handshake; allow one first client frame, within 10 seconds of upgrade.
3. That first client frame must be `ControlAuthenticate`, containing the opaque
   grant token, the complete challenge and the admitted session-key signature
   over the canonical request excluding only its own signature. Check challenge
   signature, current context, expiry, nonce and connection id against server
   state for this same connection. Check token expiry/revocation, current grant,
   session key, member/token/persona/slot/generation and fresh ownership/lock
   state before replay lookup or any member dispatch. The token alone cannot
   bind a new key. Durably consume the one-use connection challenge before
   enabling control; another socket or repeated authentication cannot reuse it.
4. Return signed `ControlReady` binding that connection, request id and exact
   authentication digest. Only now accept signed observe/intent/prediction/
   renew/leave messages through the common validator. Authentication is separate
   from their sequence counter and grants no action itself. The one-connection
   rule closes a prior socket before acknowledging a replacement. Lost ready
   frames require a new socket challenge; reconnect with expired/revoked grant
   requires ordinary fresh wallet proof and generation rotation.

For a positive browser exchange, the complete `ControlChallenge`,
`ControlAuthenticate` and `ControlReady` JSON examples below are the three
frames. The client verifies the challenge, adds its token and signature, sends
JSON with `socket.send`, verifies ready, then sends `PredictionRequest` or other
controls. Example signatures are structural placeholders. A first `IntentRequest`,
a missing/null token, malformed challenge or unknown field refuses with
`proof_required` or `bad_message` and closes the socket. Expired, replayed,
cross-connection or wrong-session challenges and stale grants refuse with
`proof_required` (context changes use `context_mismatch`); timeout closes without
dispatch. Corresponding malformed frames are in `x-invalid-examples`; runtime
signature/replay/Origin enforcement remains an implementation gate.
Tokens stay out of URLs, errors, logs and public state, including handshake logs.


## Authenticated owner inspector

Owner writes and the three member-consent handlers share the authenticated
service and declared contract. Member consent records exact versions, refuses
stale/replayed/expired answers and waits for unanimous acceptance at the host's
declared segment boundary. Source implementation alone does not establish
native application integration or live release acceptance.

Schema1.2 adds owner controls without adding guest gameplay verbs. Default
owner-settings grants require independent current NFT ownership. A custody guest
is never upgraded. Trusted IdentityAuthority configuration room_owner_accounts
selects room moderators at grant issuance. A client cannot request either role.

### Transport

Use the descriptor HTTPS base origin and fixed paths below. No redirects, credentials in URLs, cookies or HTTP auth. Canonical UTF-8 JSON follows room.protocol.canonical_bytes: ASCII keys sorted, compact JSON, integer or string numbers only, no duplicates, float, NaN or unknown keys. Maximum body is the service's advertised max_control_bytes. All endpoints use POST because even the private snapshot request authenticates a signed body. Public GET /room remains discovery only.

| Native action | POST path | action | payload (all listed fields required) |
|---|---|---|---|
| private refresh | /room/owner/snapshot | snapshot | {} or {expires_at:U64} |
| saveLimit | /room/owner/limit | save_limit | {person_cents: U64} |
| acceptTerms | /room/owner/terms/accept | accept_terms | {} |
| removeMember | /room/owner/members/remove | remove_member | {target_member_id: Id, reason: string(1..256)} |
| blockMember | /room/owner/members/block | block_member | {target_member_id: Id, reason: string(1..256)} |
| liftBlock | /room/owner/members/lift-block | lift_block | {target_member_id: Id, reason: string(1..256)} |
| acceptProposal | /room/owner/proposals/accept | accept_proposal | {proposal_id: Id} |
| declineProposal | /room/owner/proposals/decline | decline_proposal | {proposal_id: Id} |

### Request envelope

Every request has exactly: domain (constant room.owner.v1), context (existing MainnetContext), grant_id, session_key_id, member_id, nft_token_id, persona_digest, slot_id, generation (same types/values as JoinAccepted), token (JoinAccepted opaque token), kind (constant owner_control), action (table value), request_id (fresh Id), terms_version (U64 string), payload (table shape), signature (existing unpadded base64url Ed25519 Signature).

Sign the canonical entire request excluding only its top-level signature. In particular bind action, payload, token, terms_version and request_id. U64 uses canonical decimal strings. Snapshot uses terms_version "0" as an explicit read sentinel; it cannot write. Write version must equal current terms version, with proposal answers additionally tied to their named proposal/version. No owner/account/clock/effective-boundary input field exists. Reject route/action mismatches and unknown fields before dispatch. Use a new request_id for each operation. An identical previously accepted id returns request_conflict; reusing an id for different contents also refuses. Authenticate current grant/key/token/ownership/expiry/slot before any replay lookup. Lost replies are resolved by fresh snapshot, never optimistic UI success.

The service grants owner_settings only to a currently proved NFT owner, through trusted identity issuance; custody guests receive no such capability. The separate room_moderate capability is issued only for verified accounts in trusted server owner configuration, never client text. Save/consent/replies affect only the grant's authenticated member. Moderation requires room_moderate. A regular member may answer only its own required consent; the room owner cannot answer on behalf of another member. Reply answers never edit terms directly.

Self-consent and its recovery read use existing gameplay/read grants, including
verified held-premint custody. After the same current grant, token, key,
context, actor and slot checks, action authorization is:

| Action | Required capability |
|---|---|
| snapshot | observe |
| accept_terms, accept_proposal, decline_proposal | intent |
| save_limit | owner_settings |
| remove_member, block_member, lift_block | room_moderate |

A snapshot exposes only the authenticated viewer's private state. An observe-only
grant may read its state but cannot consent. Custody does not receive owner_settings
or room_moderate; its intent grant permits only its own consent and cannot save a
spend cap or moderate another member. Every affected gameplay member can answer
explicitly. The same self-bound signed snapshot resolves a lost consent reply.


### Signed reply

OwnerResponse has exactly: type="owner_response", domain="room.receipt.v1", context, grant_id, session_key_id, request_id, action, request_digest (SHA256 of request canonical bytes excluding signature), state (accepted|pending), snapshot (below), key_id, signature. Verify signature/context/request binding before displaying any outcome. A typed Error is the existing {type:"error",code,request_id:null,retry_after_ms:null|U64}; no success navigation from a refusal or transport error. Typed codes use existing proof_required/version_mismatch/request_conflict/banned/not_found/bad_message/rate_limited/recovery_pending as appropriate. Unavailable trusted state fails closed.

OwnerSnapshot has exactly:
- room_id: Id; name: bounded string; viewer_member_id: Id; is_room_owner: bool; declared_model: bounded string; grant_status: "verified".
- limits: null or {person_cents:U64,swarm_cents:U64,persona_cents:U64,used_cents:U64,held_cents:U64}. Only viewer's personal spend and caps. Effective=min(person,swarm,persona). Server cost port must commit a personal cap, preserving concurrent used/holds, before acknowledgement; absent cost port means limits null/save recovery_pending. No invented spend data.
- terms: null (authoritative unpublished) or {version:U64,input_interval_ms:U64,segment_ms:U64,simulation_hz:integer,accepted:bool}. Display exact milliseconds or exact fractional seconds. If a consumer cannot represent a value exactly, that terms view is unavailable; never round into a different promise.
- members: array max256 of {member_id:Id,name:bounded string,is_house:bool,place:"ring"|"bench"|"disconnected"|"blocked",connected?:bool,verified:bool}. Only a current room_moderate grant receives connected or the disconnected place; other callers receive ring/bench/blocked without transport status. No account caps or secrets. Trusted/public display labels only; do not substitute design fixture names.
- proposal: null or {proposal_id:Id,row:"input_interval_ms",current_ms:U64,proposed_ms:U64,effective_version:U64,boundary_segment_id:Id,required_members:array<Id>,accepted_members:array<Id>,declined_members:array<Id>,expires_at:U64,state:"pending"|"accepted"|"declined"|"expired"}. Cap each array at16. Match ids to members; own persona comes from viewer_member_id. No proposal creation write in this UI. Trusted host creates row-local proposal and affected set; all affected accept before effective host segment boundary; declined/expired/missing consent prevents application. Old members cannot continue under unaccepted new terms; old sealed history is immutable.
- moderation: null or {target_member_id:Id,target_name:bounded string,outcome:"removed"|"blocked"|"block_lifted",boundary:Boundary|null}. target_name is retained trusted display data captured with the moderation record, never supplied by the request and never reconstructed from a now-absent roster row. No fabricated outcomes. Remove invalidates all prior grants/connections/resume authority for that membership but permits a later fresh ownership proof/join. Block additionally retains account/token denial through reconnect/recovery until an explicit lift; lift never revives an old grant. Revocation is immediate even where fighter exit is pending; pending response state means retain the acknowledged waiting UI.
- waiting_count: integer|null; admission_closed:bool; max_message_bytes:integer.

Do not add optional fields to this closed shape. Signed terms:null means authoritative unpublished terms, with proposal:null; it never substitutes for a failed read. Other null fields mean unavailable, not zero/empty. Names, terms, proposals, budget and moderation history are trusted server inputs, never inferred from app swarms or fixtures. Member/proposal/budget state needs the host persistence/recovery port before acknowledgement; bans/removal feed the existing security journal and connection revoke paths and must remain effective after reconnect. Host-only proposal activation supplies the boundary, never a client clock.


### Trusted ports and recovery

RoomService accepts optional owner_state, owner_budget, owner_apply_terms and
owner_member_name host inputs. Missing budget data is null; a save with no budget
port refuses recovery_pending. owner_budget(binding, person_cents=None) returns
OwnerLimits for that authenticated account. Its setter must atomically update
only that account's personal limit, respect used/held commitments and enforce the
minimum of person/swarm/persona caps in the actual cost reservation path. A read
is not cost enforcement. The port must durably commit before returning. No
provider key, shared spend draw or automatic cap increase is introduced.

owner_member_name(binding) returns a trusted public display label. Without that
port the trusted member id is the display name; no fixture label is invented.
Roster history is bounded to256identities and signed roster to256, including every retained blocked lift target. Active admission remains16. Signed owner responses are bounded to512KiB separately from the advertised incoming-control request limit (at most16KiB).

security_event receives private owner_state checkpoints with full typed OwnerState,
plus owner_terms_boundary activation intentions. Its True means an authenticated
off-host security journal has durably committed the state through its high-water
mark; it cannot be a best-effort local log. The existing ready callback must stay
closed until recovery has reconciled these records, grant revocations, bans and
the current authority epoch. Restore owner_state only from that reconciled
checkpoint. export_owner_state() is an in-process private checkpoint, never a
public read. Requests are scoped by authenticated account and request id, retained
alongside the never-reused proposal_ids in that checkpoint. Proposal identity
history is bounded to 4096 entries; exhaustion refuses rather than reusing ids.
Private checkpoints without this required history must be reconciled by the host
before recovery; an absent history is not silently inferred from a live proposal.
Legacy `requests` ids remain permanent across fresh joins and recovery, with the
original 256/account and 4096/global cap for legacy snapshot payload `{}`. This
compatibility form still exhausts its read budget; renewing a grant does not
free ids. Clients that poll must use the signed expiring-read form below.

New non-snapshot operations use the separate permanent `write_requests` bank
(256/account, 4096/global). Even a full legacy bank has fresh write capacity;
no legacy id is deleted or classified by its text. The account/request-id
namespace is shared across all permanent ids and currently live reads.

Snapshot payload may instead be exactly `{expires_at:U64}`. The expiry is part
of the canonical signed request/digest, never a transport hint. The trusted
clock must satisfy `now < expires_at <= now + 15000` milliseconds. Invalid
windows refuse `proof_required`; altering expiry invalidates authentication.
These reads consume durable `read_requests` records `{account_id, request_id,
expires_at}` (64/account, 4096/global); duplicates refuse `request_conflict`
while live. Expired entries are pruned before capacity checks. Their old signed
requests remain invalid after pruning/recovery; a newly signed request may reuse
an expired read id, but never a permanent id. Each accepted read journals the
entire checkpoint and `read_clock_ms` high-water before its signed response.
Writes or legacy reads that prune expired entries advance that mark too. A slow
trusted callback cannot acknowledge a read after its signed expiry.
A clock behind the recovered mark, invalid clock or journal failure fences
authority as `recovery_pending` until reconciled recovery. No cached response
or authentication fact permits using an expired signature.
Every service clock sample is checked against that mark before use, including
samples after authentication and immediately before pruning or read admission.
An in-flight clock rollback cannot lower the mark or commit replay-bank changes.

Migration defaults missing `read_requests`/`write_requests` to `[]`,
`read_clock_ms` to `"0"`, and `terms_published` to `true` before validation.
Every original operation id is retained; existing checkpoints remain published.
Recovered duplicate account/id entries across banks or excess account capacity
refuse recovery rather than silently deduplicating authority.

Owner POSTs remain limited to60per edge IP and authenticated account per minute,
with the bucket table bounded to4096. Existing
body/depth/array/pending-request ceilings still apply before authentication.

A trusted initial checkpoint may explicitly set `terms_published=false`.
Its draft remains validated and bounded internally, but signed snapshots return
`terms:null` and `proposal:null`. Identity admission and watching stay available;
consent/proposal writes and prediction/intent/automatic activation stay closed
with `version_mismatch`. An error remains an error, never an unpublished success.
No browser route, URL, client history or owner HTTP operation can publish it.

`publish_owner_terms()` is a trusted in-process host call with no arguments.
It publishes the configured draft once, advances the version (draft1 becomes
published2), clears all old acceptance/proposal state and durably journals the
checkpoint before acknowledging. Repeated publication refuses `request_conflict`.
Journal failure fences authority and does not acknowledge. A published version
requires each member's fresh explicit acceptance, including members present
under draft1; the legacy version1 gameplay exception cannot bypass consent.
Recovery retains publication/version/acceptance exactly. Subsequent interval
changes still use unanimous proposals and the existing host boundary.

propose_owner_change is a trusted in-process API with proposal_id, proposed_ms,
boundary_segment_id, expires_at and required_members. It accepts one input-interval
row, a new version and the complete currently affected gameplay member set, an
expiry within24hours and an interval1000–60000ms. Admissions pause while that
proposal is pending. The public Limits advertises the currently effective interval;
its schema is U64, with the effective service bound enforced at composition.
The simulation stays20Hz and60seconds. Proposal answers never change that clock.

apply_owner_boundary(segment_id) can be called only by the trusted host at that
actual segment boundary. It requires every affected answer, the exact named
boundary, no decline/expiry and no newly omitted gameplay member. It journals
the intended transition, calls owner_apply_terms(new_terms), updates local
validation/advertised interval and durably checkpoints the effective version.
The callback must actually apply the accepted terms in the game engine before
returning True. Missing/failed ports or uncertain partial effects fence control;
recovery reconciles that transition before reopening. Changed terms gate fresh
gameplay members until their own current-version acceptance. Old records,
contexts and sealed segments are never rewritten. A deployment must rotate its
rules context/grants at its accepted protocol/rules transition; this port does
not silently reinterpret historical signed messages.

Moderation revokes locally before journal/bridge work; journal failure therefore
never leaves an old connection usable. Removal permits a new ordinary proof/join,
while block adds persistent account and token denial. A lift is journaled before
new requests can enter the service lock, and cannot reactivate a revoked grant.
Bridge release acknowledgements must bind the exact revoked session and legal
exit boundary. The trusted target display name survives roster removal and is
private to the authenticated moderator's outcome.

Native clients use an explicitly selected configured origin and locally trusted
verification key/session signing credential. A public manifest proves no owner
authority. Credential provisioning and deployed cost/journal/game adapter proofs
are host integration requirements, not supplied by these route definitions.

## Admission, slots and life boundaries

Capacity is 16 admitted fighters, with 4–6 in the ring and the rest on the bench.
House bodies yield only between lives, down to a floor of two; house fill keeps
at least six admitted when demand permits. Queue and ring arrival are first come
first served. A full room returns a signed `QueueStatus`; spectating confers no
fighter authority. At admission, `room_full` means no reservation or queue place
could be accepted. Premint stock is inventory, not admission capacity.

Admission capacity and ring capacity are separate. An admitted member's
prediction can receive a refused `room_full` receipt while six bodies are
pending or live in the ring, or while an earlier member has queue priority.
That member remains queued with its original coming life and any already
committed prediction lock. A refused activation does not undo the immutable
forecast. Host maintenance retries that same lock, including after the
two-second prediction deadline, and never substitutes a no-answer lock for it.
The identical control sequence still returns its original receipt; a fresh
prediction cannot replace a committed lock. A queued member's authenticated
`LifeNotice` exposes that retained fence until activation succeeds.

Capacity backpressure and an activation-time ownership refusal leave that
member queued; other members and the public clock continue. An ownership
refresh that revokes the grant, confirmed stale authority, or a closed life
retires only that session. Restored ownership needs fresh authority; it cannot
revive a revoked grant. If the bridge has already replaced that
exact binding, its `stale_slot` release response clears only the revoked local
session. Unexpected dependency errors, malformed acknowledgements and recovery
uncertainty still fence the room; they are not treated as ordinary queueing.

The shared slot writer has one state machine:
`offered → reserved → joined → disconnected → released`. An unused expired
reservation returns to offered. Every connected record has
`slot_id, generation, member_id, persona_digest, harness, model, source, effort,
grant, lease_until`. `grant` is a private grant reference, never a model key.
A remote member never writes a file or supplies executable launch content.
The public `Offer` exposes only slot, capability and expiry.

Reservation is 60 seconds, heartbeat 10 seconds and disconnect grace 30 seconds.
Expiry uses server time. Reconnect requires fresh proof plus the optional
`ResumeBinding`, rotates token/grant/session and generation, and revokes the old
connection before acknowledging the new one. A duplicate identical join returns
the same reservation, never a second body. A stale generation cannot renew,
act or release a replacement. Owner/custody and lock state are checked at join,
renewal, reconnect and transfer boundaries. Unknown chain state suspends control.
A held premint uses explicit bounded custody evidence, never false ownership.

### Game-owned first-token bootstrap

Before a token-specific `/room/challenge`, a newcomer calls the game adapter:

| Game-owned route | Input → output |
|---|---|
| `POST /game/custody/challenge` | `AllocationChallengeRequest` → signed `AllocationChallenge` or `Error` |
| `POST /game/custody/allocate` | `AllocationRequest` → signed `AllocationAccepted` or `Error` |

The challenge request has no token id: it binds account, chosen preset id,
persona digest, session public key, request id, current mainnet context and
`purpose = "premint"`. Its null grant/session ids confer no admission. The
game checks the preset's immutable persona digest and issues an expiring one-use
nonce under `room.join.v1`. Allocation repeats those exact bindings and the
complete signed challenge. A demonstrated wallet method proves account control
over the entire canonical allocation request excluding only `proof`; its method
wrapper must commit that exact digest and the premint purpose. The token-specific
`WalletDigestWrapper` is not used here because a token has not yet been selected.

`GameCustody.challenge` and `GameCustody.allocate` are typed game-owned adapters,
outside the room admission verbs and outside the copied implementation. The
common closed schema and bounded proof validator apply to both routes. Apply
the room's challenge/rate/size/depth limits before wallet/chain work. Nonces
expire within 60 seconds. No enabled demonstrated wallet method means
`proof_required`; no unproved allocation route exists.

After verifying proof and fresh chain custody/play status, the game atomically
selects and holds one eligible token of the chosen preset, first come first
served. The account can hold one unexpired allocation. A duplicate identical
request id and digest returns the same hold and original expiry, never a second
token or an extended hold. Validate current proof and authority before returning
a retry; a consumed challenge alone grants no new authority. For a lost reply,
obtain a fresh challenge with the original account/preset/digest/session/request
id and prove again; compare immutable allocation bindings, preserving the stored
hold. Changed immutable bindings under that id return `request_conflict`; a
different id during an active hold also refuses with `request_conflict`.
Concurrent last-token claims admit one hold. Unknown chain status returns
`ownership_unavailable`, without allocating. The hold lasts 60 seconds of server
time; expired unused inventory is released, not silently reassigned while active.

`AllocationAccepted.owner` is an explicit custody `OwnerBinding` with a non-null
reservation id, exact account/token/persona/context and checked-at time. The
signed result additionally binds preset, session public key, original request id,
authenticated request digest and hold expiry. It grants no slot and is not an
ownership transfer. Client copies its owner account/token/persona digest and
session key into `JoinChallengeRequest`, then uses ordinary join proof. The
room's `resolve_identity` independently looks up the game-held reservation for
those exact bindings, checks expiry and fresh chain state, and atomically binds
it at successful admission; it never trusts a caller-supplied reservation id.
An expired hold needs a new allocation; successful admission retains only the
game's bounded custody authority until claim, expiry or revocation. Wallet-paid
mint and later held-token claim remain game contract operations with independent
confirmed receipts, never assumed from an HTTP reply.

No eligible premint returns `paid_mint_required` and no hold. The browser then
uses the existing direct wallet-paid game contract method, waits for confirmed
ownership and starts ordinary join with that new token. There is no room payment
endpoint, charge, mint grant or claim authority. These are interface defaults;
allocation races, custody abuse bounds and onchain confirmation still need
implementation evidence before opening.

The host reserves the coming life with `reserve_life`. The service sends a
signed `LifeNotice` on the authenticated connection only, before the first
prediction and at every respawn. Its `reservation` contains `binding`, engine
`life_id` and absolute server-time `prediction_deadline`; the signed outer
member/grant/session/slot/generation/context must exactly match the inner binding
and current authority. `prediction_lock` is null while awaiting an answer, or
the immutable lock when already committed. This is a notification, never a
client command or public snapshot field. The member uses that exact reserved
life id in its signed `PredictionRequest`; receipts bind the resulting lock.

`ControlReady.next_life` returns the current reservation on each authenticated
socket, or null if none exists. A later reservation always emits `LifeNotice`.
On reconnect preserve the same life id and original deadline, read the durable
lock, update the current authority binding and re-sign the notice. Reconnect
must never extend the deadline, clear a lock or reopen a closed prediction.
Expired awaiting reservations first take the no-answer lock path before their
status is delivered. After life start `next_life` is null until a new reservation;
recover earlier receipts from the service's current authenticated retry path.
Only one pending life exists per admitted persona. Superseded notices cannot
authorise a stale life, and a slow connection's pending notice uses the existing
bounded pending-request limit; overflow closes the connection for resync rather
than dropping the current reservation silently.

Exactly one accepted signed forecast locks that life. `lock_prediction` durably
records the canonical
unsigned prediction's SHA-256 and lock event before `activate` can append life
start. Its returned `lock_ref` is mandatory for activation. The spread has four
integer basis-point bins, sums to 10,000 and has no zero-KO stake bin.
`PredictionPayload.zero_bps` is a separate independent, unstaked estimate in
0–10,000 basis points, inclusive. For example 4000 logs a 40% zero-KO chance.
It is retained in the immutable prediction log for calibration, excluded from
the four-bin sum and payout spread, and never creates a zero-KO stake market.
Invalid spread allows one more attempt within the pre-spawn window. Deadline
without a valid answer commits `PredictionLock.state = "none"`, with a required
null hash; reuse the last loadout without inventing a forecast or score.

A lock is immutable even before spawn. A fresh sequence, new key, leave,
reconnect or restored generation cannot replace it. An identical retry returns
the original receipt only after checking current authority; a changed retry is
`request_conflict`, a new prediction for a closed life is `prediction_closed`.
The ledger, not a client timestamp, orders the fence. Recovery uncertainty keeps
activation closed. `PredictionPayload.stake` references an independently approved
testnet game authorisation; a session grant never authorises wallet spending.
Items, loadout ownership and paired same-owner moves are checked by the host;
no floor, worn or locked item may move. At least one legal menu row or bag choice
is required; duplicates, incompatible choices and invalid item ownership refuse.

The model intent fields are `focus, avoid, loot, sig, leave, say`, for its own
`fighter_id`. An enemy may be an attack focus; it cannot become the controlled
subject. One intent per two seconds, with banter limited to one line per thirty
seconds. Item/gear changes occur only at the respawn fence. The deterministic
host policy supplies tick-by-tick movement and autopilot; extra calls never
advance time. `x_milli`, `y_milli` and `health_milli` use integer thousandths.
All arena state is public. House spend uses integer millionths of USD; for a
player `house_spend_microusd` must be null. No player-spend field exists.

### Public fight projection

`PublicSnapshot.projection_version = 1` fixes the tactical projection independently
of private engine objects. Each fighter has `equipped` entries for the weapon,
trinket, head and body slots: catalog row, optional owned serial and tier. Defaults
have null serials. Emit one entry per occupied slot, never duplicate slots, and
validate catalog/serial ownership at the host boundary. The `items` array is the
full public floor/inventory location projection; equipped rows also appear on
their fighter. Public `projectiles` include source fighter/item, position,
per-tick velocity, radius and expiry tick. Public `telegraphs` include source,
item, circle/cone/line shape, origin, direction (unit vector scaled by 1000),
radius, width, arc in millidegrees and start/end ticks; unused shape dimensions
are zero. All coordinates/distances use the arena's integer thousandths.

`actions` contains public engine-effective game actions since the preceding tick,
with monotonically increasing action index, tick, actor, optional target/item,
position, numeric effect and public text. Damage values are positive damage
dealt; irrelevant fields are required nulls. Banter is the submitted public line,
never reasoning. Initial/cold readers receive the full current tactical state;
historical actions come from the game's public fight log, not private receipts.
The host assigns ids, times and values and checks all references. Spectators,
players and outside agents receive the same public projection and hash at a
given tick. No credential, inference prompt, reasoning or player spend is
serialised. Bounded arrays use advertised limits; do not truncate active fight
facts silently. Admission/load throttles keep the measured projection within
limits before opening. Hashes cover canonical complete projected state, and
unknown projection versions refuse rather than discarding fields.

## Wallet proof and offline sale control

Session signatures use Ed25519, with 32-byte keys and 64-byte signatures encoded
as unpadded base64url. Room `key_id` values resolve pinned verification keys and
algorithms in trusted deployment configuration. Unknown keys or methods refuse;
there is no algorithm fallback from client data.

`WalletProof.method_id` selects a method in the configured, demonstrated wallet
adapter registry. Its bounded base64url `proof_bytes` are interpreted only by
that method, for the declared key and account. The `wallet_digest_v1` method id
in examples is illustrative; no interoperability is claimed for any wallet.
Admission stays closed until a method proves account control, exact request
binding and support for the intended wallets, including a demonstrated alternative
where direct message signing is unavailable. Merely displaying an NFT is no proof.
`Manifest.proof_methods` is empty until those methods are enabled.

For token-specific join and sale requests, the wallet adapter signs either the
complete canonical request with only its
`proof`/`wallet_proof` field excluded, or a method wrapper that commits precisely
the `WalletDigestWrapper` canonical bytes and purpose. The wrapper includes the
same context, explicit null grant/session ids, current account/token, fresh
challenge nonce/expiry and SHA-256 of that complete unsigned request. No wrapper
may omit or reinterpret that digest. Nested room challenge signatures remain
inside the signed request. The challenge's account, token, persona, session key,
action, purpose, expiry, request id and context must equal the request bindings.
A challenge is one-use, bounded and durably consumed before effect dispatch.

Sale control proves the current owner again with a fresh chain read. A `lock`
takes effect at the next respawn, or the next batch for an already absent owner.
The first batch at least 60 seconds after leaving play resolves changes and can
set sale readiness. `unlock` queues clearing; no spawn is allowed until that
clearing batch is confirmed and current ownership is rechecked. A transfer while
waiting invalidates the former owner's operation. Failed/unknown receipts remain
pending or failed. Neither HTTP acceptance nor `state = "effective"` proves chain
completion. Even a confirmed acknowledgement has `can_spawn = false`: later play
requires ordinary fresh admission, and bans remain enforced.

For retry/status, request a `LookupChallenge` with purpose
`sale_control_lookup`, original request id, action, owner/token and original
digest; submit `SaleControlLookup` using that fresh nonce/expiry/proof. Its signed
lookup purpose and `original_digest` identify immutable stored operation bytes.
Check current ownership/context and consume the fresh nonce before returning
stored status. Do not dispatch the operation again. Authentication fields may
change; original account/token/action and operation digest cannot. Reusing only
the old proof/nonce refuses. `SaleAcknowledgement` separates `operation_digest`
from the fresh `authentication_digest`. It includes boundary, pending/effective/
confirmed/failed state, batch and eventual transaction/receipt identity. Confirmed
requires both batch and chain receipt. This route never reaches `activate`.

## Signed context, canonical bytes and receipts

Every signed object carries `domain` and
`context = {version, room_id, deployment_id, authority_epoch, rules_hash, audience,
network_id, contract_ids}`. Network is explicit. Mainnet context has exactly NFT
and arena contracts; testnet context has exactly its market contract. Account and
token representations remain byte-for-byte chain values. Compare all context
fields against trusted configuration and the accepted grant before signature
acceptance as authority, replay lookup, dispatch or settlement. A client cannot
change the configuration by supplying a context.

| Domain | Signed authority |
|---|---|
| `room.join.v1` | Join challenges and wallet join proof |
| `room.control.v1` | Observe, intent, renew and leave |
| `room.prediction.v1` | Pre-life signed pick, on the same socket |
| `room.sale-control.v1` | Sale challenge, operation or fresh lookup purpose |
| `room.receipt.v1` | Room grant, queue, receipt and destination acknowledgement |
| `room.result.v1` | Sealed completed result for exactly one destination |

Control/wallet audience is the configured HTTPS origin plus purpose, such as
`https://arena.example/room#control`. Mainnet result audience names the exact
`near:mainnet:arena.near:post_batch` destination; optional testnet resolution uses
its own `near:testnet:market.testnet:resolve` audience and separately signed result
with the same `sealed_result_hash`. No result/control/receipt domain substitutes
for another. Join and wallet-only bodies require null grant/session ids; control
requires both real ids plus member/token/persona/slot/generation binding. Result
bodies require null grant/session ids and the room key, batch, segment, life ids,
NFT ids, all sealed hashes and completion.

Epoch, generation, sequence, tick, expiry and counters are unsigned 64-bit decimal
strings, no leading zero except `0`; amounts are unsigned 128-bit decimal strings.
Hashes are lowercase 64-character SHA-256 hex. Only schema integer fields use JSON
numbers; floats, NaN and infinity refuse. Keys, signatures and proof bytes have one
unpadded base64url encoding; reject alternative encodings and nonzero unused bits.
Identifiers, strings, arrays, bytes, depth and queue sizes are bounded.
Scalar patterns use `(?![\s\S])` to require the actual end of the entire string
in Python and ECMAScript validators; a final line feed is not an accepted suffix.

Signing bytes are UTF-8 JSON of the entire typed object excluding only its own
signature/proof field. Sort ASCII object keys recursively, preserve array order,
use no whitespace, and reject duplicate keys. Escape quote and backslash with a
single backslash; every control code U+0000–001F uses lowercase `\u00xx`, including
newline and tab. All other Unicode is literal UTF-8. Reject invalid UTF-8 and
unpaired surrogates; do not normalise Unicode. Noncanonical input refuses, rather
than being silently repaired. A signed challenge embedded in a request remains
complete. Digest is SHA-256 of those same canonical unsigned bytes.

`x-signing-examples` contains the literal canonical UTF-8 string and digest for
every domain, the wallet wrapper and the distinct sale lookup. JSON-encoded
`canonical_utf8` must first be decoded once; the resulting string is the exact
signing text. Example keys, signatures, proof bytes and repeated hashes are
structural placeholders, not valid cryptographic or chain evidence. The wrapper
vector's digest matches the join vector; the lookup vector names the original
sale-operation digest. Every vector's typed message validates against its named
schema. Production parsers must check canonical bytes as well as schema shape.

Sequence identity is context/grant/session/sequence. Check current epoch, grant,
expiry and owner before consulting its replay entry. Identical content returns
the stored receipt; changed content refuses. A historical receipt is audit data,
never new authority. Receipts bind message domain, digest, request id or sequence,
owner or grant/session, accepted/refused/pending state and applied tick/boundary.
Never echo a token or private request body in an error. Log bounded reason codes,
not credentials. Separate result signer, writer and minter keys are required;
only the capped writer reaches its configured destination. Gas settings must be
explicitly approved before writes open. Breach pauses writes and revokes epochs.

## Recovery and rules changes

On boot or restore, admission, control, life activation and settlement start
closed. Before acknowledging a revoke, ban/lift, refill/generation or key transition,
persist it in an authenticated off-host append-only security journal outside the
backup rollback scope. Its monotonic high-water mark cannot be lowered. Immediate
local emergency denial works during journal outage, but cannot be acknowledged
as durable or followed by reopening until reconciliation.

Recovery atomically advances the off-host authority epoch and invalidates every
restored grant, token, resume credential, challenge and replay authorisation.
Rebuild bans, revocations and generations through the trusted high-water mark;
fresh wallet proof cannot bypass a retained ban. Reconcile current ownership,
sale flags and chain batch receipts; retain newer confirmed results. Retry only
pending original ids/digests, freshly signed in the current epoch. Conflicting
digests, missing journal intervals, unknown chain status or unavailable freshness
evidence keep affected control and all settlement closed. A restored checksum
alone proves no freshness. Preserve immutable life locks and sealed history.
Intentional stop stays stopped; interrupted segments never become completed results.

Gameplay terms and rules hashes remain fixed for each segment. Proposed changes
name an effective boundary/version; every affected member accepts before continuing,
or leaves and rejoins. Completed records are never reinterpreted. Emergency bans
and credential revocations apply immediately and are recorded durably.

## Host bridge

`bridge.py` contains structural types, the nine `GameBridge` declarations and
the two `GameCustody` bootstrap declarations only, with no implementation logic.
The host composition root supplies the engine, schedule, seeds, fight policy,
items, respawn, public snapshot projection, replay simulation and chain adapters.
The service owns proofs, reservations, grants/generations, validation, projections,
signed receipts and result authority. Every ingress uses that same validator;
there is no unchecked house/browser route.

| Typed call | Required boundary |
|---|---|
| `resolve_identity(proof)` → `IdentityEvidence` | Independently prove wallet and fresh chain owner/custody/lock evidence. Unknown fails closed. |
| `reserve_life(slot_binding)` → `ReservedLife` | Engine allocates one coming life, with a pre-spawn deadline; service signs/delivers `LifeNotice` and replays current status in `ControlReady`. |
| `lock_prediction(binding, life_id, signed_pick_or_none)` → `PredictionLock` | Durable immutable hash/no-prediction fence before any life start. |
| `activate(slot_binding, life_id, lock_ref)` → `FighterBinding` | Verify the committed lock and current authority before activation. |
| `observe(binding)` → `PublicSnapshot` | Explicit full public projection; null binding is a spectator. |
| `apply(binding, sequenced_input)` → `Receipt` | Only validated `IntentRequest`, queued for host clock. Prediction cannot use this call. |
| `release(binding)` → `ReleaseAck` | Revoke immediately; engine removes at legal boundary exactly once. |
| `sale_control(owner_binding, action, request_id)` → `SaleAcknowledgement` | Wallet-only validated owner reaches only the game's sale state machine. |
| `seal(segment_id)` → `SealedRecord` | Read-only completed record, immutable inputs/seed/rules/final/prediction hashes. |
| `GameCustody.challenge(request)` → `AllocationChallenge` | Game-owned bounded preset/account/session challenge before selecting a token. |
| `GameCustody.allocate(request)` → `AllocationAccepted` | Game-owned proof and atomic inventory hold; no slot or room payment authority. |

Every call can return `Error`. These types do not implement verification or
persistence. The common validator must recheck ownership, generation, life and
tick window at application, not merely at parsing. `PublicEvent` is the bounded
ledger summary. `ReplayEvent` additionally carries engine-effective input payloads
and lock references; replay pages hash and concatenate those in ledger order.
Credentials and private receipts never enter that public projection. Forecast
content remains in the public prediction log referenced by its hash.

## Errors

| Code | Meaning and caller action |
|---|---|
| `bad_message` | Schema, unknown field/verb, malformed canonical bytes or illegal payload; correct the request. |
| `stale_slot` | Grant generation/life binding no longer current; prove again. |
| `proof_required` | Missing, expired, consumed, revoked or invalid authentication; obtain fresh proof. |
| `room_full` | At admission, no seat/reservation/queue place accepted. At activation, the admitted member stays queued with its coming life and committed fence; the host retries without stopping the clock. |
| `version_mismatch` | Unsupported version or unaccepted rules; fetch current manifest, never downgrade. |
| `prediction_closed` | Life already locked, deadline passed or activation begun; do not replace it. |
| `request_conflict` | Same request id/sequence with changed immutable content; do not change the stored operation. |
| `context_mismatch` | Wrong room, deployment, epoch, audience, network or contracts; no dispatch. |
| `recovery_pending` | Trusted recovery fence incomplete; authority remains closed. |
| `rate_limited` | Size/rate/backlog limit reached; obey bounded retry delay. |
| `admission_closed` | Room intentionally closed or stop state active; public reads may remain available. |
| `ownership_unavailable` | No fresh independent chain evidence; never assume ownership. |
| `banned` | Current account/token denied play; offline sale proof does not lift the ban. |
| `not_found` | Unknown public record; no private existence detail is disclosed. |
| `result_pending` | No completed signed result or still-pending destination; not onchain confirmation. |
| `paid_mint_required` | No eligible held inventory; browser uses a direct wallet-paid game contract route. The room takes no payment. |

Every code has a complete `Error.examples` instance in the schema, including its
required nulls and retry delay. Error messages expose only these bounded codes,
request ids where safe, and retry delays; no raw exception, token or member data.

## Source and copy

Copy exactly these 17 files from one full committed source hash to `room/` at
the destination repository root:

```text
__init__.py
service.py
protocol.py
protocol.schema.json
slots.py
identity.py
policy.py
ledger.py
results.py
bridge.py
ROOM.md
requirements.txt
test_room.py
test_identity.py
test_policy.py
test_recovery.py
mutants.py
```

This is the final file allowlist, not a claim every implementation exists now.
The private exporter must refuse missing, extra, linked or uncommitted files,
extract only these committed paths, scan public text and credentials, compare
exact bytes and replace the destination atomically. No scrubbing during copy.
A failed name is fixed in source. Public dependencies are pinned in
`requirements.txt`; all other imports resolve within the copy or standard library.
The destination `room-source.json` contains only the full source commit string,
for example `"0123456789abcdef0123456789abcdef01234567"`, with no file map, repository
path or additional metadata. The private manifest and export/gate tools stay
outside the copy. A changed schema/bridge hash invalidates dependent integration
evidence until rebuilt. Licence and baseline attribution belong in the destination
README using its permitted public wording.

Do not export any other private source. The receiving project's whole-repository
public-content, private-path, name and credential gates also cover every copied
file, comments, tests, documentation, log template and onchain-id setting. No
private names, paths, planning identifiers or review references belong here.
The static interface gate is not deployment, wallet interoperability, copy
comparison or security evidence. No admission or settlement is authorised by it.

## Field catalogue and examples

The Python `protocol.parse_message(raw, **limits)` entry point decodes one
canonical UTF-8 JSON object with byte, nesting and array bounds. Duplicate
keys, floats, invalid Unicode and noncanonical bytes refuse. `protocol.decode`
additionally takes a schema definition name and enforces that closed message
shape. Both share the policy validator, bounded errors and canonical signing
bytes; the service delegates to this same decoder before dispatch. Structural
budget refusals use `rate_limited`; malformed input uses `bad_message`.

Every object field appears below. Exact bounds, required nulls, conditional
constraints, all nested and wire examples, invalid examples and literal signing
vectors are in `protocol.schema.json`.

**Id**: `string`. Example: `"member_a"`.

**TokenId**: `string`. Example: `"persona-雪"`.

**AccountId**: `string`. Example: `"player.near"`.

**Hash**: `string`. Example: `"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"`.

**U64**: `string`. Example: `"0"`.

**Amount**: `string`. Example: `"10000000000000000000000"`.

**SignedMilli**: `integer`. Example: `1250`.

**Bps**: `integer`. Example: `2500`.

**KeyBytes**: `string`. Example: `"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"`.

**Signature**: `string`. Example: `"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"`.

**Bytes**: `string`. Example: `"AA"`.

**OpaqueToken**: `string`. Example: `"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"`.

**Label**: `string`. Example: `"external"`.

**Text**: `string`. Example: `"Ready for the next life."`.

**Audience**: `string`. Example: `"https://arena.example/room#control"`.

**ControlUrl**: `string`. Example: `"wss://arena.example/room/control"`.

**SessionPublicKey**: `algorithm: "ed25519"`, `public_key: KeyBytes`.

**MainnetContracts**: `nft: AccountId`, `arena: AccountId`.

**TestnetContracts**: `market: AccountId`.

**MainnetContext**: `version: 1`, `room_id: Id`, `deployment_id: Id`, `authority_epoch: U64`, `rules_hash: Hash`, `audience: Audience`, `network_id: "mainnet"`, `contract_ids: MainnetContracts`.

**TestnetContext**: `version: 1`, `room_id: Id`, `deployment_id: Id`, `authority_epoch: U64`, `rules_hash: Hash`, `audience: Audience`, `network_id: "testnet"`, `contract_ids: TestnetContracts`.

**Context**: `MainnetContext | TestnetContext`. Example: `{"version": 1, "room_id": "arena", "deployment_id": "deployment_a", "authority_epoch": "1", "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "audience": "https://arena.example/room#control", "network_id": "mainnet", "contract_ids": {"nft": "personas.near", "arena": "arena.near"}}`.

**ErrorCode**: `"bad_message" | "stale_slot" | "proof_required" | "room_full" | "version_mismatch" | "prediction_closed" | "request_conflict" | "context_mismatch" | "recovery_pending" | "rate_limited" | "admission_closed" | "ownership_unavailable" | "banned" | "not_found" | "result_pending" | "paid_mint_required"`. Example: `"bad_message"`.

**Error**: `type: "error"`, `code: ErrorCode`, `request_id: Id | null`, `retry_after_ms: U64 | null`.

**Capability**: `"observe" | "intent" | "prediction" | "renew" | "leave"`. Example: `"observe"`.

**Offer**: `slot_id: Id`, `capability: "fighter"`, `expires_at: U64`.

**Limits**: `type: "limits"`, `max_control_bytes: integer`, `max_depth: integer`, `max_array_items: integer`, `intent_interval_ms: "2000"`, `heartbeat_ms: "10000"`, `reservation_ms: "60000"`, `disconnect_grace_ms: "30000"`, `unauthenticated_ms: "10000"`, `join_attempts_per_minute: integer`, `control_connections_per_persona: 1`, `pending_requests: integer`, `pending_snapshot_frames: integer`, `max_replays: 2`, `unauthenticated_connections: integer`, `unauthenticated_per_ip: integer`.

**Manifest**: `type: "manifest"`, `context: MainnetContext`, `room_id: Id`, `protocol_version: 1`, `rules_hash: Hash`, `capacity: 16`, `occupied: integer`, `offers: array<Offer>`, `admission: "closed" | "open" | "recovery_pending"`, `limits: Limits`, `proof_methods: array<Id>`, `session_algorithm: "ed25519"`, `control_authentication: "first_frame_v1"`.

**DeclaredCompute**: `harness: Label`, `model: Label`, `source: Label`, `effort: Label`.

**WalletProof**: `method_id: Id`, `key_id: Id`, `proof_bytes: Bytes`.

**SaleAction**: `"lock" | "unlock"`. Example: `"lock"`.

**JoinChallengeRequest**: `domain: "room.join.v1"`, `context: MainnetContext`, `grant_id: null`, `session_key_id: null`, `account_id: AccountId`, `nft_token_id: TokenId`, `request_id: Id`, `purpose: "join"`, `persona_digest: Hash`, `session_public_key: SessionPublicKey`.

**SaleChallengeRequest**: `domain: "room.sale-control.v1"`, `context: MainnetContext`, `grant_id: null`, `session_key_id: null`, `account_id: AccountId`, `nft_token_id: TokenId`, `request_id: Id`, `purpose: "sale_control"`, `action: SaleAction`.

**LookupChallengeRequest**: `domain: "room.sale-control.v1"`, `context: MainnetContext`, `grant_id: null`, `session_key_id: null`, `account_id: AccountId`, `nft_token_id: TokenId`, `request_id: Id`, `purpose: "sale_control_lookup"`, `action: SaleAction`, `original_digest: Hash`.

**JoinChallenge**: `domain: "room.join.v1"`, `context: MainnetContext`, `grant_id: null`, `session_key_id: null`, `account_id: AccountId`, `nft_token_id: TokenId`, `request_id: Id`, `purpose: "join"`, `persona_digest: Hash`, `session_public_key: SessionPublicKey`, `challenge_id: Id`, `nonce: Id`, `expires_at: U64`, `key_id: Id`, `signature: Signature`.

**SaleChallenge**: `domain: "room.sale-control.v1"`, `context: MainnetContext`, `grant_id: null`, `session_key_id: null`, `account_id: AccountId`, `nft_token_id: TokenId`, `request_id: Id`, `purpose: "sale_control"`, `action: SaleAction`, `challenge_id: Id`, `nonce: Id`, `expires_at: U64`, `key_id: Id`, `signature: Signature`.

**LookupChallenge**: `domain: "room.sale-control.v1"`, `context: MainnetContext`, `grant_id: null`, `session_key_id: null`, `account_id: AccountId`, `nft_token_id: TokenId`, `request_id: Id`, `purpose: "sale_control_lookup"`, `action: SaleAction`, `original_digest: Hash`, `challenge_id: Id`, `nonce: Id`, `expires_at: U64`, `key_id: Id`, `signature: Signature`.

**ResumeBinding**: `prior_grant_id: Id`, `prior_generation: U64`, `resume_token: OpaqueToken`.

**JoinRequest**: `domain: "room.join.v1"`, `context: MainnetContext`, `grant_id: null`, `session_key_id: null`, `challenge: JoinChallenge`, `proof: WalletProof`, `persona_digest: Hash`, `session_public_key: SessionPublicKey`, `request_id: Id`, `declared_compute: DeclaredCompute`, `resume: ResumeBinding | null`.

**OwnerBinding**: `context: MainnetContext`, `account_id: AccountId`, `nft_token_id: TokenId`, `persona_digest: Hash`, `ownership_kind: "owner" | "custody"`, `custody_reservation_id: Id | null`, `checked_at: U64`.

**SlotBinding**: `context: MainnetContext`, `grant_id: Id`, `session_key_id: Id`, `member_id: Id`, `nft_token_id: TokenId`, `persona_digest: Hash`, `account_id: AccountId`, `slot_id: Id`, `generation: U64`.

**JoinAccepted**: `domain: "room.receipt.v1"`, `context: MainnetContext`, `grant_id: Id`, `session_key_id: Id`, `member_id: Id`, `nft_token_id: TokenId`, `persona_digest: Hash`, `account_id: AccountId`, `slot_id: Id`, `generation: U64`, `expires_at: U64`, `token: OpaqueToken`, `control_url: ControlUrl`, `session_public_key: SessionPublicKey`, `capabilities: array<Capability>`, `request_id: Id`, `request_digest: Hash`, `key_id: Id`, `signature: Signature`, `message_domain: "room.join.v1"`, `state: "accepted"`, `applied_tick: null`, `boundary: null`.

**QueueStatus**: `domain: "room.receipt.v1"`, `context: MainnetContext`, `grant_id: null`, `session_key_id: null`, `status: "spectating"`, `account_id: AccountId`, `nft_token_id: TokenId`, `queue_id: Id`, `position: U64`, `request_id: Id`, `request_digest: Hash`, `key_id: Id`, `signature: Signature`, `message_domain: "room.join.v1"`, `state: "pending"`, `applied_tick: null`, `boundary: null`.

**ObservePayload**: `projection: "public"`.

**IntentPayload**: `fighter_id: Id`, `focus: Id | null`, `avoid: Id | null`, `loot: "nearest" | "ignore"`, `sig: "auto" | "hold" | "use"`, `leave: boolean`, `say: Text | null`.

**Loadout**: `menu_row: Id | null`, `bag_serials: array<Id>`.

**Spread**: `one: Bps`, `two: Bps`, `three: Bps`, `four_plus: Bps`.

**ItemMove**: `item_serial: Id`, `from_nft_token_id: TokenId`, `to_nft_token_id: TokenId`.

**StakeReference**: `network_id: "testnet"`, `market: AccountId`, `authorisation_id: Id`, `stake_yocto: Amount`.

**PredictionPayload**: `loadout: Loadout`, `spread_bps: Spread`, `zero_bps: Bps`, `stake: StakeReference | null`, `moves: array<ItemMove>`, `lock: boolean`.

**RenewPayload**: `lease_until: U64`.

**LeavePayload**: `reason: "leave" | "disconnect"`.

**ObserveRequest**: `domain: "room.control.v1"`, `context: MainnetContext`, `grant_id: Id`, `session_key_id: Id`, `member_id: Id`, `nft_token_id: TokenId`, `persona_digest: Hash`, `slot_id: Id`, `generation: U64`, `sequence: U64`, `life_id: Id | null`, `kind: "observe"`, `payload: ObservePayload`, `signature: Signature`.

**IntentRequest**: `domain: "room.control.v1"`, `context: MainnetContext`, `grant_id: Id`, `session_key_id: Id`, `member_id: Id`, `nft_token_id: TokenId`, `persona_digest: Hash`, `slot_id: Id`, `generation: U64`, `sequence: U64`, `life_id: Id`, `kind: "intent"`, `payload: IntentPayload`, `signature: Signature`.

**PredictionRequest**: `domain: "room.prediction.v1"`, `context: MainnetContext`, `grant_id: Id`, `session_key_id: Id`, `member_id: Id`, `nft_token_id: TokenId`, `persona_digest: Hash`, `slot_id: Id`, `generation: U64`, `sequence: U64`, `life_id: Id`, `kind: "prediction"`, `payload: PredictionPayload`, `signature: Signature`.

**RenewRequest**: `domain: "room.control.v1"`, `context: MainnetContext`, `grant_id: Id`, `session_key_id: Id`, `member_id: Id`, `nft_token_id: TokenId`, `persona_digest: Hash`, `slot_id: Id`, `generation: U64`, `sequence: U64`, `life_id: Id | null`, `kind: "renew"`, `payload: RenewPayload`, `signature: Signature`.

**LeaveRequest**: `domain: "room.control.v1"`, `context: MainnetContext`, `grant_id: Id`, `session_key_id: Id`, `member_id: Id`, `nft_token_id: TokenId`, `persona_digest: Hash`, `slot_id: Id`, `generation: U64`, `sequence: U64`, `life_id: Id | null`, `kind: "leave"`, `payload: LeavePayload`, `signature: Signature`.

**SequencedInput**: `ObserveRequest | IntentRequest | PredictionRequest | RenewRequest | LeaveRequest`. Example: `{"domain": "room.control.v1", "context": {"version": 1, "room_id": "arena", "deployment_id": "deployment_a", "authority_epoch": "1", "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "audience": "https://arena.example/room#control", "network_id": "mainnet", "contract_ids": {"nft": "personas.near", "arena": "arena.near"}}, "grant_id": "grant_a", "session_key_id": "session_a", "member_id": "member_a", "nft_token_id": "persona-雪", "persona_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "slot_id": "slot_1", "generation": "2", "sequence": "1", "life_id": null, "kind": "observe", "payload": {"projection": "public"}, "signature": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}`.

**SaleControlRequest**: `domain: "room.sale-control.v1"`, `context: MainnetContext`, `grant_id: null`, `session_key_id: null`, `account_id: AccountId`, `nft_token_id: TokenId`, `request_id: Id`, `purpose: "sale_control"`, `action: SaleAction`, `challenge: SaleChallenge`, `nonce: Id`, `expires_at: U64`, `wallet_proof: WalletProof`.

**SaleControlLookup**: `domain: "room.sale-control.v1"`, `context: MainnetContext`, `grant_id: null`, `session_key_id: null`, `account_id: AccountId`, `nft_token_id: TokenId`, `request_id: Id`, `purpose: "sale_control_lookup"`, `action: SaleAction`, `challenge: LookupChallenge`, `nonce: Id`, `expires_at: U64`, `wallet_proof: WalletProof`, `original_digest: Hash`.

**WalletDigestWrapper**: `domain: "room.join.v1" | "room.sale-control.v1"`, `context: MainnetContext`, `grant_id: null`, `session_key_id: null`, `purpose: "join" | "sale_control" | "sale_control_lookup"`, `account_id: AccountId`, `nft_token_id: TokenId`, `request_digest: Hash`, `nonce: Id`, `expires_at: U64`.

**Boundary**: `kind: "pre_spawn" | "respawn" | "batch" | "applied" | "released"`, `life_id: Id | null`, `segment_id: Id | null`, `not_before_ms: U64 | null`.

**PredictionLock**: `life_id: Id`, `lock_ref: Id`, `state: "prediction" | "none"`, `prediction_hash: Hash | null`, `ledger_index: U64`, `locked_before_start: true`.

**Receipt**: `domain: "room.receipt.v1"`, `context: Context`, `grant_id: Id | null`, `session_key_id: Id | null`, `owner: OwnerBinding | null`, `request_id: Id | null`, `sequence: U64 | null`, `message_domain: "room.join.v1" | "room.control.v1" | "room.prediction.v1" | "room.sale-control.v1" | "room.result.v1"`, `request_digest: Hash`, `state: "accepted" | "refused" | "pending"`, `applied_tick: U64 | null`, `boundary: Boundary | null`, `prediction_lock: PredictionLock | null`, `code: ErrorCode | null`, `key_id: Id`, `signature: Signature`.

**ChainReceipt**: `transaction_id: Id`, `receipt_id: Id`, `confirmed_at: U64`.

**SaleAcknowledgement**: `domain: "room.receipt.v1"`, `context: MainnetContext`, `grant_id: null`, `session_key_id: null`, `owner: OwnerBinding`, `action: SaleAction`, `request_id: Id`, `operation_digest: Hash`, `authentication_digest: Hash`, `state: "pending" | "effective" | "confirmed" | "failed"`, `boundary: Boundary`, `batch_id: Id | null`, `chain_receipt: ChainReceipt | null`, `can_spawn: false`, `code: ErrorCode | null`, `key_id: Id`, `signature: Signature`, `message_domain: "room.sale-control.v1"`.

**Clock**: `type: "clock"`, `context: MainnetContext`, `segment_id: Id`, `tick: U64`, `tick_hz: 20`, `segment_seconds: 60`, `segment_ticks: "1200"`.

**PublicFighter**: `fighter_id: Id`, `nft_token_id: TokenId`, `persona_digest: Hash`, `public_name: Label`, `model: Label`, `x_milli: SignedMilli`, `y_milli: SignedMilli`, `health_milli: U64`, `state: "ring" | "bench" | "disconnected"`, `house: boolean`, `house_spend_microusd: U64 | null`, `equipped: array<PublicEquipment>`.

**PublicItem**: `serial_id: Id`, `item_id: Id`, `holder_token_id: TokenId | null`, `x_milli: SignedMilli`, `y_milli: SignedMilli`.

**PublicSnapshot**: `type: "snapshot"`, `context: MainnetContext`, `clock: Clock`, `fighters: array<PublicFighter>`, `items: array<PublicItem>`, `snapshot_hash: Hash`, `projection_version: 1`, `projectiles: array<PublicProjectile>`, `telegraphs: array<PublicTelegraph>`, `actions: array<PublicAction>`.

**PublicEvent**: `index: U64`, `tick: U64`, `kind: "join" | "leave" | "intent" | "prediction_lock" | "life_start" | "life_end" | "seal" | "sale_control" | "revoke" | "rules_change"`, `member_id: Id | null`, `life_id: Id | null`, `request_digest: Hash | null`, `record_hash: Hash`.

**LedgerPage**: `type: "ledger"`, `context: MainnetContext`, `events: array<PublicEvent>`, `next_index: U64 | null`, `page_hash: Hash`.

**LifeRecord**: `life_id: Id`, `nft_token_id: TokenId`, `prediction_lock: PredictionLock`, `ko_count: U64`, `inventory_hash: Hash`, `completed: true`.

**SealedRecord**: `segment_id: Id`, `life_ids: array<Id>`, `nft_token_ids: array<TokenId>`, `inputs_hash: Hash`, `seed_hash: Hash`, `rules_hash: Hash`, `final_state_hash: Hash`, `predictions_log_hash: Hash`, `sealed_result_hash: Hash`, `completed: true`, `tick_count: "1200"`, `lives: array<LifeRecord>`, `seed: U64`, `input_events: array<ReplayEvent>`.

**Result**: `domain: "room.result.v1"`, `context: Context`, `grant_id: null`, `session_key_id: null`, `key_id: Id`, `batch_id: Id`, `segment_id: Id`, `life_ids: array<Id>`, `nft_token_ids: array<TokenId>`, `inputs_hash: Hash`, `seed_hash: Hash`, `rules_hash: Hash`, `final_state_hash: Hash`, `predictions_log_hash: Hash`, `sealed_result_hash: Hash`, `completed: true`, `tick_count: "1200"`, `lives: array<LifeRecord>`, `signature: Signature`.

**BatchAcknowledgement**: `domain: "room.receipt.v1"`, `context: Context`, `grant_id: null`, `session_key_id: null`, `batch_id: Id`, `result_digest: Hash`, `state: "pending" | "confirmed" | "failed"`, `chain_receipt: ChainReceipt | null`, `key_id: Id`, `signature: Signature`, `message_domain: "room.result.v1"`.

**ReplayPage**: `type: "replay"`, `context: MainnetContext`, `segment_id: Id`, `seed: U64`, `rules_hash: Hash`, `input_events: array<ReplayEvent>`, `next_index: U64 | null`, `inputs_hash: Hash`, `predictions_log_hash: Hash`, `final_state_hash: Hash`.

**ReadRequest**: `verb: "seat" | "observe" | "tick" | "limits" | "result" | "replay" | "ledger"`, `segment_id: Id | null`, `after_index: U64 | null`.

**ReservedLife**: `binding: SlotBinding`, `life_id: Id`, `prediction_deadline: U64`.

**FighterBinding**: `binding: SlotBinding`, `life_id: Id`, `fighter_id: Id`, `lock_ref: Id`, `start_tick: U64`.

**IdentityEvidence**: `owner: OwnerBinding`, `play_status: "eligible" | "locked" | "sale_ready" | "unknown"`, `chain_height: U64`, `sale_control_allowed: boolean`.

**ReleaseAck**: `binding: SlotBinding`, `last_sequence: U64`, `boundary: Boundary`, `revoked: true`.

**ReplayPick**: `loadout: Loadout`, `moves: array<ItemMove>`, `lock: boolean`, `prediction_lock: PredictionLock`.

**ReplayJoinEvent**: `index: U64`, `tick: U64`, `kind: "join"`, `fighter_id: Id`, `nft_token_id: TokenId`, `life_id: Id`, `payload: PublicFighter`, `record_hash: Hash`.

**ReplayIntentEvent**: `index: U64`, `tick: U64`, `kind: "intent"`, `fighter_id: Id`, `nft_token_id: TokenId`, `life_id: Id`, `payload: IntentPayload`, `record_hash: Hash`.

**ReplayPredictionLockEvent**: `index: U64`, `tick: U64`, `kind: "prediction_lock"`, `fighter_id: Id`, `nft_token_id: TokenId`, `life_id: Id`, `payload: ReplayPick`, `record_hash: Hash`.

**ReplayLifeStartEvent**: `index: U64`, `tick: U64`, `kind: "life_start"`, `fighter_id: Id`, `nft_token_id: TokenId`, `life_id: Id`, `payload: PredictionLock`, `record_hash: Hash`.

**ReplayLeaveEvent**: `index: U64`, `tick: U64`, `kind: "leave"`, `fighter_id: Id`, `nft_token_id: TokenId`, `life_id: Id`, `payload: LeavePayload`, `record_hash: Hash`.

**ReplayEvent**: `ReplayJoinEvent | ReplayIntentEvent | ReplayPredictionLockEvent | ReplayLifeStartEvent | ReplayLeaveEvent`. Example: `{"index": "4", "tick": "40", "kind": "join", "fighter_id": "fighter_a", "nft_token_id": "persona-雪", "life_id": "life_a", "payload": {"fighter_id": "fighter_a", "nft_token_id": "persona-雪", "persona_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "public_name": "Snow", "model": "declared-model", "x_milli": 1250, "y_milli": -250, "health_milli": "100000", "state": "ring", "house": false, "house_spend_microusd": null, "equipped": [{"slot": "weapon", "item_id": "st-bonk", "serial_id": null, "tier": "common"}]}, "record_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}`.

**PublicEquipment**: `slot: "weapon" | "trinket" | "head" | "body"`, `item_id: Id`, `serial_id: Id | null`, `tier: "common" | "rare" | "legendary"`.

**PublicProjectile**: `projectile_id: Id`, `fighter_id: Id`, `item_id: Id`, `x_milli: SignedMilli`, `y_milli: SignedMilli`, `vx_milli_per_tick: SignedMilli`, `vy_milli_per_tick: SignedMilli`, `radius_milli: U64`, `expires_tick: U64`.

**PublicTelegraph**: `telegraph_id: Id`, `fighter_id: Id`, `item_id: Id`, `shape: "circle" | "cone" | "line"`, `x_milli: SignedMilli`, `y_milli: SignedMilli`, `direction_x_milli: SignedMilli`, `direction_y_milli: SignedMilli`, `radius_milli: U64`, `width_milli: U64`, `arc_millidegrees: U64`, `start_tick: U64`, `end_tick: U64`.

**PublicAction**: `index: U64`, `tick: U64`, `fighter_id: Id`, `target_fighter_id: Id | null`, `kind: "move" | "attack" | "pickup" | "equip" | "drop" | "use" | "damage" | "ko" | "respawn" | "banter" | "leave"`, `item_serial_id: Id | null`, `x_milli: SignedMilli | null`, `y_milli: SignedMilli | null`, `value_milli: SignedMilli | null`, `text: Text | null`.

**ControlChallenge**: `domain: "room.receipt.v1"`, `context: MainnetContext`, `grant_id: null`, `session_key_id: null`, `type: "control_challenge"`, `connection_id: Id`, `nonce: Id`, `expires_at: U64`, `key_id: Id`, `signature: Signature`.

**ControlAuthenticate**: `domain: "room.control.v1"`, `context: MainnetContext`, `grant_id: Id`, `session_key_id: Id`, `member_id: Id`, `nft_token_id: TokenId`, `persona_digest: Hash`, `slot_id: Id`, `generation: U64`, `kind: "authenticate"`, `request_id: Id`, `token: OpaqueToken`, `challenge: ControlChallenge`, `signature: Signature`.

**LifeNotice**: `domain: "room.receipt.v1"`, `context: MainnetContext`, `grant_id: Id`, `session_key_id: Id`, `member_id: Id`, `nft_token_id: TokenId`, `persona_digest: Hash`, `slot_id: Id`, `generation: U64`, `type: "life_notice"`, `reservation: ReservedLife`, `prediction_lock: PredictionLock | null`, `key_id: Id`, `signature: Signature`.

**ControlReady**: `domain: "room.receipt.v1"`, `context: MainnetContext`, `grant_id: Id`, `session_key_id: Id`, `member_id: Id`, `nft_token_id: TokenId`, `persona_digest: Hash`, `slot_id: Id`, `generation: U64`, `type: "control_ready"`, `connection_id: Id`, `request_id: Id`, `request_digest: Hash`, `next_life: LifeNotice | null`, `key_id: Id`, `signature: Signature`.

**AllocationChallengeRequest**: `domain: "room.join.v1"`, `context: MainnetContext`, `grant_id: null`, `session_key_id: null`, `account_id: AccountId`, `preset_id: Id`, `persona_digest: Hash`, `session_public_key: SessionPublicKey`, `request_id: Id`, `purpose: "premint"`.

**AllocationChallenge**: `domain: "room.join.v1"`, `context: MainnetContext`, `grant_id: null`, `session_key_id: null`, `account_id: AccountId`, `preset_id: Id`, `persona_digest: Hash`, `session_public_key: SessionPublicKey`, `request_id: Id`, `purpose: "premint"`, `challenge_id: Id`, `nonce: Id`, `expires_at: U64`, `key_id: Id`, `signature: Signature`.

**AllocationRequest**: `domain: "room.join.v1"`, `context: MainnetContext`, `grant_id: null`, `session_key_id: null`, `account_id: AccountId`, `preset_id: Id`, `persona_digest: Hash`, `session_public_key: SessionPublicKey`, `request_id: Id`, `purpose: "premint"`, `challenge: AllocationChallenge`, `proof: WalletProof`.

**AllocationAccepted**: `domain: "room.receipt.v1"`, `context: MainnetContext`, `grant_id: null`, `session_key_id: null`, `type: "allocation_accepted"`, `owner: OwnerBinding`, `preset_id: Id`, `session_public_key: SessionPublicKey`, `expires_at: U64`, `request_id: Id`, `request_digest: Hash`, `key_id: Id`, `signature: Signature`.

These transport examples are complete typed objects. The schema also supplies examples for every nested definition and error code.

<!-- example:Manifest -->
```json
{
  "type": "manifest",
  "context": {
    "version": 1,
    "room_id": "arena",
    "deployment_id": "deployment_a",
    "authority_epoch": "1",
    "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "audience": "https://arena.example/room#control",
    "network_id": "mainnet",
    "contract_ids": {
      "nft": "personas.near",
      "arena": "arena.near"
    }
  },
  "room_id": "arena",
  "protocol_version": 1,
  "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "capacity": 16,
  "occupied": 6,
  "offers": [
    {
      "slot_id": "slot_1",
      "capability": "fighter",
      "expires_at": "1900000060000"
    }
  ],
  "admission": "closed",
  "limits": {
    "type": "limits",
    "max_control_bytes": 16384,
    "max_depth": 16,
    "max_array_items": 64,
    "intent_interval_ms": "2000",
    "heartbeat_ms": "10000",
    "reservation_ms": "60000",
    "disconnect_grace_ms": "30000",
    "unauthenticated_ms": "10000",
    "join_attempts_per_minute": 5,
    "control_connections_per_persona": 1,
    "pending_requests": 16,
    "pending_snapshot_frames": 2,
    "max_replays": 2,
    "unauthenticated_connections": 32,
    "unauthenticated_per_ip": 2
  },
  "proof_methods": [],
  "session_algorithm": "ed25519",
  "control_authentication": "first_frame_v1"
}
```

<!-- example:JoinChallengeRequest -->
```json
{
  "domain": "room.join.v1",
  "context": {
    "version": 1,
    "room_id": "arena",
    "deployment_id": "deployment_a",
    "authority_epoch": "1",
    "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "audience": "https://arena.example/room#control",
    "network_id": "mainnet",
    "contract_ids": {
      "nft": "personas.near",
      "arena": "arena.near"
    }
  },
  "grant_id": null,
  "session_key_id": null,
  "account_id": "player.near",
  "nft_token_id": "persona-雪",
  "request_id": "request_a",
  "purpose": "join",
  "persona_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "session_public_key": {
    "algorithm": "ed25519",
    "public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
  }
}
```

<!-- example:JoinRequest -->
```json
{
  "domain": "room.join.v1",
  "context": {
    "version": 1,
    "room_id": "arena",
    "deployment_id": "deployment_a",
    "authority_epoch": "1",
    "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "audience": "https://arena.example/room#control",
    "network_id": "mainnet",
    "contract_ids": {
      "nft": "personas.near",
      "arena": "arena.near"
    }
  },
  "grant_id": null,
  "session_key_id": null,
  "challenge": {
    "domain": "room.join.v1",
    "context": {
      "version": 1,
      "room_id": "arena",
      "deployment_id": "deployment_a",
      "authority_epoch": "1",
      "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "audience": "https://arena.example/room#control",
      "network_id": "mainnet",
      "contract_ids": {
        "nft": "personas.near",
        "arena": "arena.near"
      }
    },
    "grant_id": null,
    "session_key_id": null,
    "account_id": "player.near",
    "nft_token_id": "persona-雪",
    "request_id": "request_a",
    "purpose": "join",
    "persona_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "session_public_key": {
      "algorithm": "ed25519",
      "public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    },
    "challenge_id": "challenge_a",
    "nonce": "nonce_a",
    "expires_at": "1900000060000",
    "key_id": "room_key_a",
    "signature": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
  },
  "proof": {
    "method_id": "wallet_digest_v1",
    "key_id": "wallet_key_a",
    "proof_bytes": "AA"
  },
  "persona_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "session_public_key": {
    "algorithm": "ed25519",
    "public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
  },
  "request_id": "request_a",
  "declared_compute": {
    "harness": "external",
    "model": "declared-model",
    "source": "own-provider",
    "effort": "high"
  },
  "resume": null
}
```

<!-- example:JoinAccepted -->
```json
{
  "domain": "room.receipt.v1",
  "context": {
    "version": 1,
    "room_id": "arena",
    "deployment_id": "deployment_a",
    "authority_epoch": "1",
    "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "audience": "https://arena.example/room#control",
    "network_id": "mainnet",
    "contract_ids": {
      "nft": "personas.near",
      "arena": "arena.near"
    }
  },
  "grant_id": "grant_a",
  "session_key_id": "session_a",
  "member_id": "member_a",
  "nft_token_id": "persona-雪",
  "persona_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "account_id": "player.near",
  "slot_id": "slot_1",
  "generation": "2",
  "expires_at": "1900000060000",
  "token": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "control_url": "wss://arena.example/room/control",
  "session_public_key": {
    "algorithm": "ed25519",
    "public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
  },
  "capabilities": [
    "observe",
    "intent",
    "prediction",
    "renew",
    "leave"
  ],
  "request_id": "request_a",
  "request_digest": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "key_id": "room_key_a",
  "signature": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
  "message_domain": "room.join.v1",
  "state": "accepted",
  "applied_tick": null,
  "boundary": null
}
```

<!-- example:IntentRequest -->
```json
{
  "domain": "room.control.v1",
  "context": {
    "version": 1,
    "room_id": "arena",
    "deployment_id": "deployment_a",
    "authority_epoch": "1",
    "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "audience": "https://arena.example/room#control",
    "network_id": "mainnet",
    "contract_ids": {
      "nft": "personas.near",
      "arena": "arena.near"
    }
  },
  "grant_id": "grant_a",
  "session_key_id": "session_a",
  "member_id": "member_a",
  "nft_token_id": "persona-雪",
  "persona_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "slot_id": "slot_1",
  "generation": "2",
  "sequence": "1",
  "life_id": "life_a",
  "kind": "intent",
  "payload": {
    "fighter_id": "fighter_a",
    "focus": "fighter_b",
    "avoid": null,
    "loot": "nearest",
    "sig": "hold",
    "leave": false,
    "say": "Ready for the next life."
  },
  "signature": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
}
```

<!-- example:PredictionRequest -->
```json
{
  "domain": "room.prediction.v1",
  "context": {
    "version": 1,
    "room_id": "arena",
    "deployment_id": "deployment_a",
    "authority_epoch": "1",
    "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "audience": "https://arena.example/room#control",
    "network_id": "mainnet",
    "contract_ids": {
      "nft": "personas.near",
      "arena": "arena.near"
    }
  },
  "grant_id": "grant_a",
  "session_key_id": "session_a",
  "member_id": "member_a",
  "nft_token_id": "persona-雪",
  "persona_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "slot_id": "slot_1",
  "generation": "2",
  "sequence": "1",
  "life_id": "life_a",
  "kind": "prediction",
  "payload": {
    "loadout": {
      "menu_row": "preset_a",
      "bag_serials": []
    },
    "spread_bps": {
      "one": 4000,
      "two": 3000,
      "three": 2000,
      "four_plus": 1000
    },
    "zero_bps": 0,
    "stake": null,
    "moves": [],
    "lock": false
  },
  "signature": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
}
```

<!-- example:SaleControlRequest -->
```json
{
  "domain": "room.sale-control.v1",
  "context": {
    "version": 1,
    "room_id": "arena",
    "deployment_id": "deployment_a",
    "authority_epoch": "1",
    "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "audience": "https://arena.example/room#control",
    "network_id": "mainnet",
    "contract_ids": {
      "nft": "personas.near",
      "arena": "arena.near"
    }
  },
  "grant_id": null,
  "session_key_id": null,
  "account_id": "player.near",
  "nft_token_id": "persona-雪",
  "request_id": "request_a",
  "purpose": "sale_control",
  "action": "lock",
  "challenge": {
    "domain": "room.sale-control.v1",
    "context": {
      "version": 1,
      "room_id": "arena",
      "deployment_id": "deployment_a",
      "authority_epoch": "1",
      "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "audience": "https://arena.example/room#control",
      "network_id": "mainnet",
      "contract_ids": {
        "nft": "personas.near",
        "arena": "arena.near"
      }
    },
    "grant_id": null,
    "session_key_id": null,
    "account_id": "player.near",
    "nft_token_id": "persona-雪",
    "request_id": "request_a",
    "purpose": "sale_control",
    "action": "lock",
    "challenge_id": "challenge_a",
    "nonce": "nonce_a",
    "expires_at": "1900000060000",
    "key_id": "room_key_a",
    "signature": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
  },
  "nonce": "nonce_a",
  "expires_at": "1900000060000",
  "wallet_proof": {
    "method_id": "wallet_digest_v1",
    "key_id": "wallet_key_a",
    "proof_bytes": "AA"
  }
}
```

<!-- example:SaleControlLookup -->
```json
{
  "domain": "room.sale-control.v1",
  "context": {
    "version": 1,
    "room_id": "arena",
    "deployment_id": "deployment_a",
    "authority_epoch": "1",
    "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "audience": "https://arena.example/room#control",
    "network_id": "mainnet",
    "contract_ids": {
      "nft": "personas.near",
      "arena": "arena.near"
    }
  },
  "grant_id": null,
  "session_key_id": null,
  "account_id": "player.near",
  "nft_token_id": "persona-雪",
  "request_id": "request_a",
  "purpose": "sale_control_lookup",
  "action": "lock",
  "challenge": {
    "domain": "room.sale-control.v1",
    "context": {
      "version": 1,
      "room_id": "arena",
      "deployment_id": "deployment_a",
      "authority_epoch": "1",
      "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "audience": "https://arena.example/room#control",
      "network_id": "mainnet",
      "contract_ids": {
        "nft": "personas.near",
        "arena": "arena.near"
      }
    },
    "grant_id": null,
    "session_key_id": null,
    "account_id": "player.near",
    "nft_token_id": "persona-雪",
    "request_id": "request_a",
    "purpose": "sale_control_lookup",
    "action": "lock",
    "original_digest": "0db6d8a313064032d215f568e0412cf018bda5319400258b79ec6c36fe8ebe33",
    "challenge_id": "challenge_a",
    "nonce": "nonce_a",
    "expires_at": "1900000060000",
    "key_id": "room_key_a",
    "signature": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
  },
  "nonce": "nonce_a",
  "expires_at": "1900000060000",
  "wallet_proof": {
    "method_id": "wallet_digest_v1",
    "key_id": "wallet_key_a",
    "proof_bytes": "AA"
  },
  "original_digest": "0db6d8a313064032d215f568e0412cf018bda5319400258b79ec6c36fe8ebe33"
}
```

<!-- example:SaleAcknowledgement -->
```json
{
  "domain": "room.receipt.v1",
  "context": {
    "version": 1,
    "room_id": "arena",
    "deployment_id": "deployment_a",
    "authority_epoch": "1",
    "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "audience": "https://arena.example/room#control",
    "network_id": "mainnet",
    "contract_ids": {
      "nft": "personas.near",
      "arena": "arena.near"
    }
  },
  "grant_id": null,
  "session_key_id": null,
  "owner": {
    "context": {
      "version": 1,
      "room_id": "arena",
      "deployment_id": "deployment_a",
      "authority_epoch": "1",
      "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "audience": "https://arena.example/room#control",
      "network_id": "mainnet",
      "contract_ids": {
        "nft": "personas.near",
        "arena": "arena.near"
      }
    },
    "account_id": "player.near",
    "nft_token_id": "persona-雪",
    "persona_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "ownership_kind": "owner",
    "custody_reservation_id": null,
    "checked_at": "1900000000000"
  },
  "action": "lock",
  "request_id": "request_a",
  "operation_digest": "0db6d8a313064032d215f568e0412cf018bda5319400258b79ec6c36fe8ebe33",
  "authentication_digest": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "state": "pending",
  "boundary": {
    "kind": "batch",
    "life_id": "life_a",
    "segment_id": "segment_a",
    "not_before_ms": "1900000060000"
  },
  "batch_id": null,
  "chain_receipt": null,
  "can_spawn": false,
  "code": null,
  "key_id": "room_key_a",
  "signature": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
  "message_domain": "room.sale-control.v1"
}
```

<!-- example:Receipt -->
```json
{
  "domain": "room.receipt.v1",
  "context": {
    "version": 1,
    "room_id": "arena",
    "deployment_id": "deployment_a",
    "authority_epoch": "1",
    "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "audience": "https://arena.example/room#control",
    "network_id": "mainnet",
    "contract_ids": {
      "nft": "personas.near",
      "arena": "arena.near"
    }
  },
  "grant_id": "grant_a",
  "session_key_id": "session_a",
  "owner": null,
  "request_id": null,
  "sequence": "1",
  "message_domain": "room.prediction.v1",
  "request_digest": "bac36268970a6b8155f8421c2321631f1825d39bf652a26ba04d0f8ecf6509e9",
  "state": "accepted",
  "applied_tick": null,
  "boundary": {
    "kind": "pre_spawn",
    "life_id": "life_a",
    "segment_id": "segment_a",
    "not_before_ms": null
  },
  "prediction_lock": {
    "life_id": "life_a",
    "lock_ref": "lock_a",
    "state": "prediction",
    "prediction_hash": "bac36268970a6b8155f8421c2321631f1825d39bf652a26ba04d0f8ecf6509e9",
    "ledger_index": "4",
    "locked_before_start": true
  },
  "code": null,
  "key_id": "room_key_a",
  "signature": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
}
```

<!-- example:Result -->
```json
{
  "domain": "room.result.v1",
  "context": {
    "version": 1,
    "room_id": "arena",
    "deployment_id": "deployment_a",
    "authority_epoch": "1",
    "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "audience": "near:mainnet:arena.near:post_batch",
    "network_id": "mainnet",
    "contract_ids": {
      "nft": "personas.near",
      "arena": "arena.near"
    }
  },
  "grant_id": null,
  "session_key_id": null,
  "key_id": "result_key_a",
  "batch_id": "batch_a",
  "segment_id": "segment_a",
  "life_ids": [
    "life_a"
  ],
  "nft_token_ids": [
    "persona-雪"
  ],
  "inputs_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "seed_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "final_state_hash": "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
  "predictions_log_hash": "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
  "sealed_result_hash": "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff",
  "completed": true,
  "tick_count": "1200",
  "lives": [
    {
      "life_id": "life_a",
      "nft_token_id": "persona-雪",
      "prediction_lock": {
        "life_id": "life_a",
        "lock_ref": "lock_a",
        "state": "prediction",
        "prediction_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "ledger_index": "4",
        "locked_before_start": true
      },
      "ko_count": "2",
      "inventory_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
      "completed": true
    }
  ],
  "signature": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
}
```


<!-- example:ControlChallenge -->
```json
{
  "domain": "room.receipt.v1",
  "context": {
    "version": 1,
    "room_id": "arena",
    "deployment_id": "deployment_a",
    "authority_epoch": "1",
    "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "audience": "https://arena.example/room#control",
    "network_id": "mainnet",
    "contract_ids": {
      "nft": "personas.near",
      "arena": "arena.near"
    }
  },
  "grant_id": null,
  "session_key_id": null,
  "type": "control_challenge",
  "connection_id": "connection_a",
  "nonce": "nonce_a",
  "expires_at": "1900000010000",
  "key_id": "room_key_a",
  "signature": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
}
```


<!-- example:ControlAuthenticate -->
```json
{
  "domain": "room.control.v1",
  "context": {
    "version": 1,
    "room_id": "arena",
    "deployment_id": "deployment_a",
    "authority_epoch": "1",
    "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "audience": "https://arena.example/room#control",
    "network_id": "mainnet",
    "contract_ids": {
      "nft": "personas.near",
      "arena": "arena.near"
    }
  },
  "grant_id": "grant_a",
  "session_key_id": "session_a",
  "member_id": "member_a",
  "nft_token_id": "persona-雪",
  "persona_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "slot_id": "slot_1",
  "generation": "2",
  "kind": "authenticate",
  "request_id": "auth_a",
  "token": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "challenge": {
    "domain": "room.receipt.v1",
    "context": {
      "version": 1,
      "room_id": "arena",
      "deployment_id": "deployment_a",
      "authority_epoch": "1",
      "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "audience": "https://arena.example/room#control",
      "network_id": "mainnet",
      "contract_ids": {
        "nft": "personas.near",
        "arena": "arena.near"
      }
    },
    "grant_id": null,
    "session_key_id": null,
    "type": "control_challenge",
    "connection_id": "connection_a",
    "nonce": "nonce_a",
    "expires_at": "1900000010000",
    "key_id": "room_key_a",
    "signature": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
  },
  "signature": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
}
```


<!-- example:ControlReady -->
```json
{
  "domain": "room.receipt.v1",
  "context": {
    "version": 1,
    "room_id": "arena",
    "deployment_id": "deployment_a",
    "authority_epoch": "1",
    "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "audience": "https://arena.example/room#control",
    "network_id": "mainnet",
    "contract_ids": {
      "nft": "personas.near",
      "arena": "arena.near"
    }
  },
  "grant_id": "grant_a",
  "session_key_id": "session_a",
  "member_id": "member_a",
  "nft_token_id": "persona-雪",
  "persona_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "slot_id": "slot_1",
  "generation": "2",
  "type": "control_ready",
  "connection_id": "connection_a",
  "request_id": "auth_a",
  "request_digest": "48c73aa512599f1c597985fbb593f00b47b28e7e847f288dbf8e5c4866738a71",
  "next_life": {
    "domain": "room.receipt.v1",
    "context": {
      "version": 1,
      "room_id": "arena",
      "deployment_id": "deployment_a",
      "authority_epoch": "1",
      "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "audience": "https://arena.example/room#control",
      "network_id": "mainnet",
      "contract_ids": {
        "nft": "personas.near",
        "arena": "arena.near"
      }
    },
    "grant_id": "grant_a",
    "session_key_id": "session_a",
    "member_id": "member_a",
    "nft_token_id": "persona-雪",
    "persona_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "slot_id": "slot_1",
    "generation": "2",
    "type": "life_notice",
    "reservation": {
      "binding": {
        "context": {
          "version": 1,
          "room_id": "arena",
          "deployment_id": "deployment_a",
          "authority_epoch": "1",
          "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          "audience": "https://arena.example/room#control",
          "network_id": "mainnet",
          "contract_ids": {
            "nft": "personas.near",
            "arena": "arena.near"
          }
        },
        "grant_id": "grant_a",
        "session_key_id": "session_a",
        "member_id": "member_a",
        "nft_token_id": "persona-雪",
        "persona_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "account_id": "player.near",
        "slot_id": "slot_1",
        "generation": "2"
      },
      "life_id": "life_a",
      "prediction_deadline": "1900000030000"
    },
    "prediction_lock": null,
    "key_id": "room_key_a",
    "signature": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
  },
  "key_id": "room_key_a",
  "signature": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
}
```


<!-- example:LifeNotice -->
```json
{
  "domain": "room.receipt.v1",
  "context": {
    "version": 1,
    "room_id": "arena",
    "deployment_id": "deployment_a",
    "authority_epoch": "1",
    "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "audience": "https://arena.example/room#control",
    "network_id": "mainnet",
    "contract_ids": {
      "nft": "personas.near",
      "arena": "arena.near"
    }
  },
  "grant_id": "grant_a",
  "session_key_id": "session_a",
  "member_id": "member_a",
  "nft_token_id": "persona-雪",
  "persona_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "slot_id": "slot_1",
  "generation": "2",
  "type": "life_notice",
  "reservation": {
    "binding": {
      "context": {
        "version": 1,
        "room_id": "arena",
        "deployment_id": "deployment_a",
        "authority_epoch": "1",
        "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "audience": "https://arena.example/room#control",
        "network_id": "mainnet",
        "contract_ids": {
          "nft": "personas.near",
          "arena": "arena.near"
        }
      },
      "grant_id": "grant_a",
      "session_key_id": "session_a",
      "member_id": "member_a",
      "nft_token_id": "persona-雪",
      "persona_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "account_id": "player.near",
      "slot_id": "slot_1",
      "generation": "2"
    },
    "life_id": "life_a",
    "prediction_deadline": "1900000030000"
  },
  "prediction_lock": null,
  "key_id": "room_key_a",
  "signature": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
}
```


<!-- example:AllocationChallengeRequest -->
```json
{
  "domain": "room.join.v1",
  "context": {
    "version": 1,
    "room_id": "arena",
    "deployment_id": "deployment_a",
    "authority_epoch": "1",
    "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "audience": "https://arena.example/room#control",
    "network_id": "mainnet",
    "contract_ids": {
      "nft": "personas.near",
      "arena": "arena.near"
    }
  },
  "grant_id": null,
  "session_key_id": null,
  "account_id": "player.near",
  "preset_id": "preset_a",
  "persona_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "session_public_key": {
    "algorithm": "ed25519",
    "public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
  },
  "request_id": "allocation_a",
  "purpose": "premint"
}
```


<!-- example:AllocationChallenge -->
```json
{
  "domain": "room.join.v1",
  "context": {
    "version": 1,
    "room_id": "arena",
    "deployment_id": "deployment_a",
    "authority_epoch": "1",
    "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "audience": "https://arena.example/room#control",
    "network_id": "mainnet",
    "contract_ids": {
      "nft": "personas.near",
      "arena": "arena.near"
    }
  },
  "grant_id": null,
  "session_key_id": null,
  "account_id": "player.near",
  "preset_id": "preset_a",
  "persona_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "session_public_key": {
    "algorithm": "ed25519",
    "public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
  },
  "request_id": "allocation_a",
  "purpose": "premint",
  "challenge_id": "allocation_challenge_a",
  "nonce": "allocation_nonce_a",
  "expires_at": "1900000060000",
  "key_id": "room_key_a",
  "signature": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
}
```


<!-- example:AllocationRequest -->
```json
{
  "domain": "room.join.v1",
  "context": {
    "version": 1,
    "room_id": "arena",
    "deployment_id": "deployment_a",
    "authority_epoch": "1",
    "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "audience": "https://arena.example/room#control",
    "network_id": "mainnet",
    "contract_ids": {
      "nft": "personas.near",
      "arena": "arena.near"
    }
  },
  "grant_id": null,
  "session_key_id": null,
  "account_id": "player.near",
  "preset_id": "preset_a",
  "persona_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "session_public_key": {
    "algorithm": "ed25519",
    "public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
  },
  "request_id": "allocation_a",
  "purpose": "premint",
  "challenge": {
    "domain": "room.join.v1",
    "context": {
      "version": 1,
      "room_id": "arena",
      "deployment_id": "deployment_a",
      "authority_epoch": "1",
      "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "audience": "https://arena.example/room#control",
      "network_id": "mainnet",
      "contract_ids": {
        "nft": "personas.near",
        "arena": "arena.near"
      }
    },
    "grant_id": null,
    "session_key_id": null,
    "account_id": "player.near",
    "preset_id": "preset_a",
    "persona_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "session_public_key": {
      "algorithm": "ed25519",
      "public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    },
    "request_id": "allocation_a",
    "purpose": "premint",
    "challenge_id": "allocation_challenge_a",
    "nonce": "allocation_nonce_a",
    "expires_at": "1900000060000",
    "key_id": "room_key_a",
    "signature": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
  },
  "proof": {
    "method_id": "wallet_digest_v1",
    "key_id": "wallet_key_a",
    "proof_bytes": "AA"
  }
}
```


<!-- example:AllocationAccepted -->
```json
{
  "domain": "room.receipt.v1",
  "context": {
    "version": 1,
    "room_id": "arena",
    "deployment_id": "deployment_a",
    "authority_epoch": "1",
    "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "audience": "https://arena.example/room#control",
    "network_id": "mainnet",
    "contract_ids": {
      "nft": "personas.near",
      "arena": "arena.near"
    }
  },
  "grant_id": null,
  "session_key_id": null,
  "type": "allocation_accepted",
  "owner": {
    "context": {
      "version": 1,
      "room_id": "arena",
      "deployment_id": "deployment_a",
      "authority_epoch": "1",
      "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "audience": "https://arena.example/room#control",
      "network_id": "mainnet",
      "contract_ids": {
        "nft": "personas.near",
        "arena": "arena.near"
      }
    },
    "account_id": "player.near",
    "nft_token_id": "persona-雪",
    "persona_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "ownership_kind": "custody",
    "custody_reservation_id": "custody_a",
    "checked_at": "1900000000000"
  },
  "preset_id": "preset_a",
  "session_public_key": {
    "algorithm": "ed25519",
    "public_key": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
  },
  "expires_at": "1900000060000",
  "request_id": "allocation_a",
  "request_digest": "820ec9df4da58b65f885603a5a4c84252427891d947af75ad2aefa19bc33c9ab",
  "key_id": "room_key_a",
  "signature": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
}
```


<!-- example:PublicSnapshot -->
```json
{
  "type": "snapshot",
  "context": {
    "version": 1,
    "room_id": "arena",
    "deployment_id": "deployment_a",
    "authority_epoch": "1",
    "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "audience": "https://arena.example/room#control",
    "network_id": "mainnet",
    "contract_ids": {
      "nft": "personas.near",
      "arena": "arena.near"
    }
  },
  "clock": {
    "type": "clock",
    "context": {
      "version": 1,
      "room_id": "arena",
      "deployment_id": "deployment_a",
      "authority_epoch": "1",
      "rules_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "audience": "https://arena.example/room#control",
      "network_id": "mainnet",
      "contract_ids": {
        "nft": "personas.near",
        "arena": "arena.near"
      }
    },
    "segment_id": "segment_a",
    "tick": "40",
    "tick_hz": 20,
    "segment_seconds": 60,
    "segment_ticks": "1200"
  },
  "fighters": [
    {
      "fighter_id": "fighter_a",
      "nft_token_id": "persona-雪",
      "persona_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "public_name": "Snow",
      "model": "declared-model",
      "x_milli": 1250,
      "y_milli": -250,
      "health_milli": "100000",
      "state": "ring",
      "house": false,
      "house_spend_microusd": null,
      "equipped": [
        {
          "slot": "weapon",
          "item_id": "st-bonk",
          "serial_id": null,
          "tier": "common"
        }
      ]
    }
  ],
  "items": [
    {
      "serial_id": "serial_a",
      "item_id": "gear_a",
      "holder_token_id": null,
      "x_milli": 1250,
      "y_milli": -250
    }
  ],
  "snapshot_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "projection_version": 1,
  "projectiles": [
    {
      "projectile_id": "projectile_a",
      "fighter_id": "fighter_a",
      "item_id": "c-lob",
      "x_milli": 1250,
      "y_milli": -250,
      "vx_milli_per_tick": 100,
      "vy_milli_per_tick": -100,
      "radius_milli": "250",
      "expires_tick": "60"
    }
  ],
  "telegraphs": [
    {
      "telegraph_id": "telegraph_a",
      "fighter_id": "fighter_a",
      "item_id": "c-beam",
      "shape": "line",
      "x_milli": 1250,
      "y_milli": -250,
      "direction_x_milli": 1000,
      "direction_y_milli": 0,
      "radius_milli": "3000",
      "width_milli": "250",
      "arc_millidegrees": "0",
      "start_tick": "40",
      "end_tick": "50"
    }
  ],
  "actions": [
    {
      "index": "4",
      "tick": "40",
      "fighter_id": "fighter_a",
      "target_fighter_id": "fighter_b",
      "kind": "damage",
      "item_serial_id": null,
      "x_milli": 1250,
      "y_milli": -250,
      "value_milli": 1000,
      "text": null
    }
  ]
}
```

## Member consent controls

The private inspector uses signed `POST /room/owner/terms/accept`
(`accept_terms`, empty payload), `POST /room/owner/proposals/accept`
(`accept_proposal`, `{proposal_id}`) and `POST /room/owner/proposals/decline`
(`decline_proposal`, `{proposal_id}`). The `/owner/` prefix does not allow a room
operator to answer for another member. Every route derives the member from the
current authenticated grant. The request's member, token, persona, session key,
slot and generation must match that grant; no account, actor, client clock or
effective-boundary override is accepted.

`OwnerRequest` signs the canonical entire envelope excluding only `signature`.
The envelope binds `domain: room.owner.v1`, `kind: owner_control`, context,
grant/session/member/token/persona/slot/generation, opaque `token`, `action`,
fresh `request_id`, canonical decimal `terms_version` and the closed `payload`.
The path and signed action must agree. Every write supplies the exact current
terms version shown in the private snapshot. A proposal answer also names its
immutable proposal id, which binds its proposed value, next version, affected
members, expiry and segment boundary. Neither an old version nor an old proposal
id can answer a newer change. Terms acceptance records only that member and the
exact current version. Answering a proposal does not directly edit terms.

The trusted host creates row-local proposals. Each affected member must answer
for itself; a missing answer keeps the proposal pending. Accepting returns a
signed `OwnerResponse` with `state: pending` until the host reaches the declared
segment boundary. A decline is an acknowledged recorded answer and leaves the
proposal declined; it prevents application. At the exact expiry, further answers
are refused, and even an earlier unanimous but unactivated proposal expires.
Only the trusted host may activate at the named boundary, after checking every
required acceptance again. A different boundary, missing consent, decline or
expiry leaves the effective terms unchanged. Completed segment records are
never rewritten by a consent operation.

Successful replies bind context, grant, session key, action, request id and the
unsigned request digest, and contain the private `OwnerSnapshot`. Clients verify
the room signature and all those bindings before displaying an outcome. A lost
reply requires a fresh signed snapshot request; replaying an accepted request id
returns `request_conflict`, including reuse for different contents. Current
authority is checked before any replay lookup. No error contains credentials.

| Refusal | Meaning |
|---|---|
| `proof_required` | No current authenticated membership, bad signature/token, expired/revoked grant or member outside the proposal's affected set. |
| `stale_slot` | Claimed member/session/persona/slot/generation differs from the authenticated binding. |
| `version_mismatch` | Terms version is stale or the proposal is no longer pending, including expiry. |
| `not_found` | The named proposal is absent or was superseded. |
| `request_conflict` | A request id was consumed, or the member already answered that proposal. |
| `bad_message` | Closed schema, canonical encoding or route/action validation failed. |
| `banned` | The authenticated account or token is denied. |
| `recovery_pending` | Trusted persistence, readiness or boundary application is unavailable. |

The host's security journal must durably checkpoint the full private owner state
before acknowledging consent or replies, and restore that reconciled state on
restart. This includes exact-version acceptance, proposal answers/outcomes and
consumed request ids. In-memory mutation is not persistence. An unknown journal
or host-application outcome fences writes until recovery reconciles it; it never
produces optimistic success. The host applies changed gameplay terms through
its configured boundary adapter, with the same version used by the room's input
gate. Old members without acceptance cannot continue under changed terms.
