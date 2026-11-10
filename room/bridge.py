"""Host interfaces. Validation and effects belong to the service and host adapters."""
from __future__ import annotations

from typing import Literal, Protocol, TypeAlias, TypedDict

Id: TypeAlias = str

TokenId: TypeAlias = str

AccountId: TypeAlias = str

Hash: TypeAlias = str

U64: TypeAlias = str

Amount: TypeAlias = str

SignedMilli: TypeAlias = int

Bps: TypeAlias = int

KeyBytes: TypeAlias = str

Signature: TypeAlias = str

Bytes: TypeAlias = str

OpaqueToken: TypeAlias = str

Label: TypeAlias = str

Text: TypeAlias = str

Audience: TypeAlias = str

ControlUrl: TypeAlias = str

class SessionPublicKey(TypedDict):
    algorithm: Literal['ed25519']
    public_key: KeyBytes

class MainnetContracts(TypedDict):
    nft: AccountId
    arena: AccountId

class TestnetContracts(TypedDict):
    market: AccountId

class MainnetContext(TypedDict):
    version: Literal[1]
    room_id: Id
    deployment_id: Id
    authority_epoch: U64
    rules_hash: Hash
    audience: Audience
    network_id: Literal['mainnet']
    contract_ids: MainnetContracts

class TestnetContext(TypedDict):
    version: Literal[1]
    room_id: Id
    deployment_id: Id
    authority_epoch: U64
    rules_hash: Hash
    audience: Audience
    network_id: Literal['testnet']
    contract_ids: TestnetContracts

Context: TypeAlias = MainnetContext | TestnetContext

ErrorCode: TypeAlias = Literal['bad_message', 'stale_slot', 'proof_required', 'room_full', 'version_mismatch', 'prediction_closed', 'request_conflict', 'context_mismatch', 'recovery_pending', 'rate_limited', 'admission_closed', 'ownership_unavailable', 'banned', 'not_found', 'result_pending', 'paid_mint_required']

class Error(TypedDict):
    type: Literal['error']
    code: ErrorCode
    request_id: Id | None
    retry_after_ms: U64 | None

Capability: TypeAlias = Literal['observe', 'intent', 'prediction', 'renew', 'leave', 'owner_settings', 'room_moderate']

class Offer(TypedDict):
    slot_id: Id
    capability: Literal['fighter']
    expires_at: U64

class Limits(TypedDict):
    type: Literal['limits']
    max_control_bytes: int
    max_depth: int
    max_array_items: int
    intent_interval_ms: U64
    heartbeat_ms: Literal['10000']
    reservation_ms: Literal['60000']
    disconnect_grace_ms: Literal['30000']
    unauthenticated_ms: Literal['10000']
    join_attempts_per_minute: int
    control_connections_per_persona: Literal[1]
    pending_requests: int
    pending_snapshot_frames: int
    max_replays: Literal[2]
    unauthenticated_connections: int
    unauthenticated_per_ip: int

class Manifest(TypedDict):
    type: Literal['manifest']
    context: MainnetContext
    room_id: Id
    protocol_version: Literal[1]
    rules_hash: Hash
    capacity: Literal[16]
    occupied: int
    offers: list[Offer]
    admission: Literal['closed', 'open', 'recovery_pending']
    limits: Limits
    proof_methods: list[Id]
    session_algorithm: Literal['ed25519']
    control_authentication: Literal['first_frame_v1']

class DeclaredCompute(TypedDict):
    harness: Label
    model: Label
    source: Label
    effort: Label

class WalletProof(TypedDict):
    method_id: Id
    key_id: Id
    proof_bytes: Bytes

SaleAction: TypeAlias = Literal['lock', 'unlock']

class JoinChallengeRequest(TypedDict):
    domain: Literal['room.join.v1']
    context: MainnetContext
    grant_id: None
    session_key_id: None
    account_id: AccountId
    nft_token_id: TokenId
    request_id: Id
    purpose: Literal['join']
    persona_digest: Hash
    session_public_key: SessionPublicKey

class SaleChallengeRequest(TypedDict):
    domain: Literal['room.sale-control.v1']
    context: MainnetContext
    grant_id: None
    session_key_id: None
    account_id: AccountId
    nft_token_id: TokenId
    request_id: Id
    purpose: Literal['sale_control']
    action: SaleAction

class LookupChallengeRequest(TypedDict):
    domain: Literal['room.sale-control.v1']
    context: MainnetContext
    grant_id: None
    session_key_id: None
    account_id: AccountId
    nft_token_id: TokenId
    request_id: Id
    purpose: Literal['sale_control_lookup']
    action: SaleAction
    original_digest: Hash

class JoinChallenge(TypedDict):
    domain: Literal['room.join.v1']
    context: MainnetContext
    grant_id: None
    session_key_id: None
    account_id: AccountId
    nft_token_id: TokenId
    request_id: Id
    purpose: Literal['join']
    persona_digest: Hash
    session_public_key: SessionPublicKey
    challenge_id: Id
    nonce: Id
    expires_at: U64
    key_id: Id
    signature: Signature

class SaleChallenge(TypedDict):
    domain: Literal['room.sale-control.v1']
    context: MainnetContext
    grant_id: None
    session_key_id: None
    account_id: AccountId
    nft_token_id: TokenId
    request_id: Id
    purpose: Literal['sale_control']
    action: SaleAction
    challenge_id: Id
    nonce: Id
    expires_at: U64
    key_id: Id
    signature: Signature

class LookupChallenge(TypedDict):
    domain: Literal['room.sale-control.v1']
    context: MainnetContext
    grant_id: None
    session_key_id: None
    account_id: AccountId
    nft_token_id: TokenId
    request_id: Id
    purpose: Literal['sale_control_lookup']
    action: SaleAction
    original_digest: Hash
    challenge_id: Id
    nonce: Id
    expires_at: U64
    key_id: Id
    signature: Signature

class ResumeBinding(TypedDict):
    prior_grant_id: Id
    prior_generation: U64
    resume_token: OpaqueToken

class JoinRequest(TypedDict):
    domain: Literal['room.join.v1']
    context: MainnetContext
    grant_id: None
    session_key_id: None
    challenge: JoinChallenge
    proof: WalletProof
    persona_digest: Hash
    session_public_key: SessionPublicKey
    request_id: Id
    declared_compute: DeclaredCompute
    resume: ResumeBinding | None

class OwnerBinding(TypedDict):
    context: MainnetContext
    account_id: AccountId
    nft_token_id: TokenId
    persona_digest: Hash
    ownership_kind: Literal['owner', 'custody']
    custody_reservation_id: Id | None
    checked_at: U64

class SlotBinding(TypedDict):
    context: MainnetContext
    grant_id: Id
    session_key_id: Id
    member_id: Id
    nft_token_id: TokenId
    persona_digest: Hash
    account_id: AccountId
    slot_id: Id
    generation: U64

class JoinAccepted(TypedDict):
    domain: Literal['room.receipt.v1']
    context: MainnetContext
    grant_id: Id
    session_key_id: Id
    member_id: Id
    nft_token_id: TokenId
    persona_digest: Hash
    account_id: AccountId
    slot_id: Id
    generation: U64
    expires_at: U64
    token: OpaqueToken
    control_url: ControlUrl
    session_public_key: SessionPublicKey
    capabilities: list[Capability]
    request_id: Id
    request_digest: Hash
    key_id: Id
    signature: Signature
    message_domain: Literal['room.join.v1']
    state: Literal['accepted']
    applied_tick: None
    boundary: None

class QueueStatus(TypedDict):
    domain: Literal['room.receipt.v1']
    context: MainnetContext
    grant_id: None
    session_key_id: None
    status: Literal['spectating']
    account_id: AccountId
    nft_token_id: TokenId
    queue_id: Id
    position: U64
    request_id: Id
    request_digest: Hash
    key_id: Id
    signature: Signature
    message_domain: Literal['room.join.v1']
    state: Literal['pending']
    applied_tick: None
    boundary: None

class ObservePayload(TypedDict):
    projection: Literal['public']

class IntentPayload(TypedDict):
    fighter_id: Id
    focus: Id | None
    avoid: Id | None
    loot: Literal['nearest', 'ignore']
    sig: Literal['auto', 'hold', 'use']
    leave: bool
    say: Text | None

class Loadout(TypedDict):
    menu_row: Id | None
    bag_serials: list[Id]

class Spread(TypedDict):
    one: Bps
    two: Bps
    three: Bps
    four_plus: Bps

class ItemMove(TypedDict):
    item_serial: Id
    from_nft_token_id: TokenId
    to_nft_token_id: TokenId

class StakeReference(TypedDict):
    network_id: Literal['testnet']
    market: AccountId
    authorisation_id: Id
    stake_yocto: Amount

class PredictionPayload(TypedDict):
    loadout: Loadout
    spread_bps: Spread
    zero_bps: Bps
    stake: StakeReference | None
    moves: list[ItemMove]
    lock: bool

class RenewPayload(TypedDict):
    lease_until: U64

class LeavePayload(TypedDict):
    reason: Literal['leave', 'disconnect']

class ObserveRequest(TypedDict):
    domain: Literal['room.control.v1']
    context: MainnetContext
    grant_id: Id
    session_key_id: Id
    member_id: Id
    nft_token_id: TokenId
    persona_digest: Hash
    slot_id: Id
    generation: U64
    sequence: U64
    life_id: Id | None
    kind: Literal['observe']
    payload: ObservePayload
    signature: Signature

class IntentRequest(TypedDict):
    domain: Literal['room.control.v1']
    context: MainnetContext
    grant_id: Id
    session_key_id: Id
    member_id: Id
    nft_token_id: TokenId
    persona_digest: Hash
    slot_id: Id
    generation: U64
    sequence: U64
    life_id: Id
    kind: Literal['intent']
    payload: IntentPayload
    signature: Signature

class PredictionRequest(TypedDict):
    domain: Literal['room.prediction.v1']
    context: MainnetContext
    grant_id: Id
    session_key_id: Id
    member_id: Id
    nft_token_id: TokenId
    persona_digest: Hash
    slot_id: Id
    generation: U64
    sequence: U64
    life_id: Id
    kind: Literal['prediction']
    payload: PredictionPayload
    signature: Signature

class RenewRequest(TypedDict):
    domain: Literal['room.control.v1']
    context: MainnetContext
    grant_id: Id
    session_key_id: Id
    member_id: Id
    nft_token_id: TokenId
    persona_digest: Hash
    slot_id: Id
    generation: U64
    sequence: U64
    life_id: Id | None
    kind: Literal['renew']
    payload: RenewPayload
    signature: Signature

class LeaveRequest(TypedDict):
    domain: Literal['room.control.v1']
    context: MainnetContext
    grant_id: Id
    session_key_id: Id
    member_id: Id
    nft_token_id: TokenId
    persona_digest: Hash
    slot_id: Id
    generation: U64
    sequence: U64
    life_id: Id | None
    kind: Literal['leave']
    payload: LeavePayload
    signature: Signature

SequencedInput: TypeAlias = ObserveRequest | IntentRequest | PredictionRequest | RenewRequest | LeaveRequest

class SaleControlRequest(TypedDict):
    domain: Literal['room.sale-control.v1']
    context: MainnetContext
    grant_id: None
    session_key_id: None
    account_id: AccountId
    nft_token_id: TokenId
    request_id: Id
    purpose: Literal['sale_control']
    action: SaleAction
    challenge: SaleChallenge
    nonce: Id
    expires_at: U64
    wallet_proof: WalletProof

class SaleControlLookup(TypedDict):
    domain: Literal['room.sale-control.v1']
    context: MainnetContext
    grant_id: None
    session_key_id: None
    account_id: AccountId
    nft_token_id: TokenId
    request_id: Id
    purpose: Literal['sale_control_lookup']
    action: SaleAction
    challenge: LookupChallenge
    nonce: Id
    expires_at: U64
    wallet_proof: WalletProof
    original_digest: Hash

class WalletDigestWrapper(TypedDict):
    domain: Literal['room.join.v1', 'room.sale-control.v1']
    context: MainnetContext
    grant_id: None
    session_key_id: None
    purpose: Literal['join', 'sale_control', 'sale_control_lookup']
    account_id: AccountId
    nft_token_id: TokenId
    request_digest: Hash
    nonce: Id
    expires_at: U64

class Boundary(TypedDict):
    kind: Literal['pre_spawn', 'respawn', 'batch', 'applied', 'released']
    life_id: Id | None
    segment_id: Id | None
    not_before_ms: U64 | None

class PredictionLock(TypedDict):
    life_id: Id
    lock_ref: Id
    state: Literal['prediction', 'none']
    prediction_hash: Hash | None
    ledger_index: U64
    locked_before_start: Literal[True]

class Receipt(TypedDict):
    domain: Literal['room.receipt.v1']
    context: Context
    grant_id: Id | None
    session_key_id: Id | None
    owner: OwnerBinding | None
    request_id: Id | None
    sequence: U64 | None
    message_domain: Literal['room.join.v1', 'room.control.v1', 'room.prediction.v1', 'room.sale-control.v1', 'room.result.v1']
    request_digest: Hash
    state: Literal['accepted', 'refused', 'pending']
    applied_tick: U64 | None
    boundary: Boundary | None
    prediction_lock: PredictionLock | None
    code: ErrorCode | None
    key_id: Id
    signature: Signature

class ChainReceipt(TypedDict):
    transaction_id: Id
    receipt_id: Id
    confirmed_at: U64

class SaleAcknowledgement(TypedDict):
    domain: Literal['room.receipt.v1']
    context: MainnetContext
    grant_id: None
    session_key_id: None
    owner: OwnerBinding
    action: SaleAction
    request_id: Id
    operation_digest: Hash
    authentication_digest: Hash
    state: Literal['pending', 'effective', 'confirmed', 'failed']
    boundary: Boundary
    batch_id: Id | None
    chain_receipt: ChainReceipt | None
    can_spawn: Literal[False]
    code: ErrorCode | None
    key_id: Id
    signature: Signature
    message_domain: Literal['room.sale-control.v1']

class Clock(TypedDict):
    type: Literal['clock']
    context: MainnetContext
    segment_id: Id
    tick: U64
    tick_hz: Literal[20]
    segment_seconds: Literal[60]
    segment_ticks: Literal['1200']

class PublicFighter(TypedDict):
    fighter_id: Id
    nft_token_id: TokenId
    persona_digest: Hash
    public_name: Label
    model: Label
    x_milli: SignedMilli
    y_milli: SignedMilli
    health_milli: U64
    state: Literal['ring', 'bench', 'disconnected']
    house: bool
    house_spend_microusd: U64 | None
    equipped: list[PublicEquipment]

class PublicItem(TypedDict):
    serial_id: Id
    item_id: Id
    holder_token_id: TokenId | None
    x_milli: SignedMilli
    y_milli: SignedMilli

class PublicSnapshot(TypedDict):
    type: Literal['snapshot']
    context: MainnetContext
    clock: Clock
    fighters: list[PublicFighter]
    items: list[PublicItem]
    snapshot_hash: Hash
    projection_version: Literal[1]
    projectiles: list[PublicProjectile]
    telegraphs: list[PublicTelegraph]
    actions: list[PublicAction]

class PublicEvent(TypedDict):
    index: U64
    tick: U64
    kind: Literal['join', 'leave', 'intent', 'prediction_lock', 'life_start', 'life_end', 'seal', 'sale_control', 'revoke', 'rules_change']
    member_id: Id | None
    life_id: Id | None
    request_digest: Hash | None
    record_hash: Hash

class LedgerPage(TypedDict):
    type: Literal['ledger']
    context: MainnetContext
    events: list[PublicEvent]
    next_index: U64 | None
    page_hash: Hash

class LifeRecord(TypedDict):
    life_id: Id
    nft_token_id: TokenId
    prediction_lock: PredictionLock
    ko_count: U64
    inventory_hash: Hash
    completed: Literal[True]

class SealedRecord(TypedDict):
    segment_id: Id
    life_ids: list[Id]
    nft_token_ids: list[TokenId]
    inputs_hash: Hash
    seed_hash: Hash
    rules_hash: Hash
    final_state_hash: Hash
    predictions_log_hash: Hash
    sealed_result_hash: Hash
    completed: Literal[True]
    tick_count: Literal['1200']
    lives: list[LifeRecord]
    seed: U64
    input_events: list[ReplayEvent]

class Result(TypedDict):
    domain: Literal['room.result.v1']
    context: Context
    grant_id: None
    session_key_id: None
    key_id: Id
    batch_id: Id
    segment_id: Id
    life_ids: list[Id]
    nft_token_ids: list[TokenId]
    inputs_hash: Hash
    seed_hash: Hash
    rules_hash: Hash
    final_state_hash: Hash
    predictions_log_hash: Hash
    sealed_result_hash: Hash
    completed: Literal[True]
    tick_count: Literal['1200']
    lives: list[LifeRecord]
    signature: Signature

class BatchAcknowledgement(TypedDict):
    domain: Literal['room.receipt.v1']
    context: Context
    grant_id: None
    session_key_id: None
    batch_id: Id
    result_digest: Hash
    state: Literal['pending', 'confirmed', 'failed']
    chain_receipt: ChainReceipt | None
    key_id: Id
    signature: Signature
    message_domain: Literal['room.result.v1']

class ReplayPage(TypedDict):
    type: Literal['replay']
    context: MainnetContext
    segment_id: Id
    seed: U64
    rules_hash: Hash
    input_events: list[ReplayEvent]
    next_index: U64 | None
    inputs_hash: Hash
    predictions_log_hash: Hash
    final_state_hash: Hash

class ReadRequest(TypedDict):
    verb: Literal['seat', 'observe', 'tick', 'limits', 'result', 'replay', 'ledger']
    segment_id: Id | None
    after_index: U64 | None

class ReservedLife(TypedDict):
    binding: SlotBinding
    life_id: Id
    prediction_deadline: U64

class FighterBinding(TypedDict):
    binding: SlotBinding
    life_id: Id
    fighter_id: Id
    lock_ref: Id
    start_tick: U64

class IdentityEvidence(TypedDict):
    owner: OwnerBinding
    play_status: Literal['eligible', 'locked', 'sale_ready', 'unknown']
    chain_height: U64
    sale_control_allowed: bool

class ReleaseAck(TypedDict):
    binding: SlotBinding
    last_sequence: U64
    boundary: Boundary
    revoked: Literal[True]

class ReplayPick(TypedDict):
    loadout: Loadout
    moves: list[ItemMove]
    lock: bool
    prediction_lock: PredictionLock

class ReplayJoinEvent(TypedDict):
    index: U64
    tick: U64
    kind: Literal['join']
    fighter_id: Id
    nft_token_id: TokenId
    life_id: Id
    payload: PublicFighter
    record_hash: Hash

class ReplayIntentEvent(TypedDict):
    index: U64
    tick: U64
    kind: Literal['intent']
    fighter_id: Id
    nft_token_id: TokenId
    life_id: Id
    payload: IntentPayload
    record_hash: Hash

class ReplayPredictionLockEvent(TypedDict):
    index: U64
    tick: U64
    kind: Literal['prediction_lock']
    fighter_id: Id
    nft_token_id: TokenId
    life_id: Id
    payload: ReplayPick
    record_hash: Hash

class ReplayLifeStartEvent(TypedDict):
    index: U64
    tick: U64
    kind: Literal['life_start']
    fighter_id: Id
    nft_token_id: TokenId
    life_id: Id
    payload: PredictionLock
    record_hash: Hash

class ReplayLeaveEvent(TypedDict):
    index: U64
    tick: U64
    kind: Literal['leave']
    fighter_id: Id
    nft_token_id: TokenId
    life_id: Id
    payload: LeavePayload
    record_hash: Hash

ReplayEvent: TypeAlias = ReplayJoinEvent | ReplayIntentEvent | ReplayPredictionLockEvent | ReplayLifeStartEvent | ReplayLeaveEvent

class PublicEquipment(TypedDict):
    slot: Literal['weapon', 'trinket', 'head', 'body']
    item_id: Id
    serial_id: Id | None
    tier: Literal['common', 'rare', 'legendary']

class PublicProjectile(TypedDict):
    projectile_id: Id
    fighter_id: Id
    item_id: Id
    x_milli: SignedMilli
    y_milli: SignedMilli
    vx_milli_per_tick: SignedMilli
    vy_milli_per_tick: SignedMilli
    radius_milli: U64
    expires_tick: U64

class PublicTelegraph(TypedDict):
    telegraph_id: Id
    fighter_id: Id
    item_id: Id
    shape: Literal['circle', 'cone', 'line']
    x_milli: SignedMilli
    y_milli: SignedMilli
    direction_x_milli: SignedMilli
    direction_y_milli: SignedMilli
    radius_milli: U64
    width_milli: U64
    arc_millidegrees: U64
    start_tick: U64
    end_tick: U64

class PublicAction(TypedDict):
    index: U64
    tick: U64
    fighter_id: Id
    target_fighter_id: Id | None
    kind: Literal['move', 'attack', 'pickup', 'equip', 'drop', 'use', 'damage', 'ko', 'respawn', 'banter', 'leave']
    item_serial_id: Id | None
    x_milli: SignedMilli | None
    y_milli: SignedMilli | None
    value_milli: SignedMilli | None
    text: Text | None

class ControlChallenge(TypedDict):
    domain: Literal['room.receipt.v1']
    context: MainnetContext
    grant_id: None
    session_key_id: None
    type: Literal['control_challenge']
    connection_id: Id
    nonce: Id
    expires_at: U64
    key_id: Id
    signature: Signature

class ControlAuthenticate(TypedDict):
    domain: Literal['room.control.v1']
    context: MainnetContext
    grant_id: Id
    session_key_id: Id
    member_id: Id
    nft_token_id: TokenId
    persona_digest: Hash
    slot_id: Id
    generation: U64
    kind: Literal['authenticate']
    request_id: Id
    token: OpaqueToken
    challenge: ControlChallenge
    signature: Signature

class LifeNotice(TypedDict):
    domain: Literal['room.receipt.v1']
    context: MainnetContext
    grant_id: Id
    session_key_id: Id
    member_id: Id
    nft_token_id: TokenId
    persona_digest: Hash
    slot_id: Id
    generation: U64
    type: Literal['life_notice']
    reservation: ReservedLife
    prediction_lock: PredictionLock | None
    key_id: Id
    signature: Signature

class ControlReady(TypedDict):
    domain: Literal['room.receipt.v1']
    context: MainnetContext
    grant_id: Id
    session_key_id: Id
    member_id: Id
    nft_token_id: TokenId
    persona_digest: Hash
    slot_id: Id
    generation: U64
    type: Literal['control_ready']
    connection_id: Id
    request_id: Id
    request_digest: Hash
    next_life: LifeNotice | None
    key_id: Id
    signature: Signature

class AllocationChallengeRequest(TypedDict):
    domain: Literal['room.join.v1']
    context: MainnetContext
    grant_id: None
    session_key_id: None
    account_id: AccountId
    preset_id: Id
    persona_digest: Hash
    session_public_key: SessionPublicKey
    request_id: Id
    purpose: Literal['premint']

class AllocationChallenge(TypedDict):
    domain: Literal['room.join.v1']
    context: MainnetContext
    grant_id: None
    session_key_id: None
    account_id: AccountId
    preset_id: Id
    persona_digest: Hash
    session_public_key: SessionPublicKey
    request_id: Id
    purpose: Literal['premint']
    challenge_id: Id
    nonce: Id
    expires_at: U64
    key_id: Id
    signature: Signature

class AllocationRequest(TypedDict):
    domain: Literal['room.join.v1']
    context: MainnetContext
    grant_id: None
    session_key_id: None
    account_id: AccountId
    preset_id: Id
    persona_digest: Hash
    session_public_key: SessionPublicKey
    request_id: Id
    purpose: Literal['premint']
    challenge: AllocationChallenge
    proof: WalletProof

class AllocationAccepted(TypedDict):
    domain: Literal['room.receipt.v1']
    context: MainnetContext
    grant_id: None
    session_key_id: None
    type: Literal['allocation_accepted']
    owner: OwnerBinding
    preset_id: Id
    session_public_key: SessionPublicKey
    expires_at: U64
    request_id: Id
    request_digest: Hash
    key_id: Id
    signature: Signature



class OwnerSnapshotRequest(TypedDict):
    domain: Literal['room.owner.v1']
    context: MainnetContext
    grant_id: Id
    session_key_id: Id
    member_id: Id
    nft_token_id: TokenId
    persona_digest: Hash
    slot_id: Id
    generation: U64
    kind: Literal['owner_control']
    payload: dict[str, object]
    signature: Signature
    token: OpaqueToken
    request_id: Id
    terms_version: U64
    action: Literal['snapshot']


class OwnerSaveLimitRequest(TypedDict):
    domain: Literal['room.owner.v1']
    context: MainnetContext
    grant_id: Id
    session_key_id: Id
    member_id: Id
    nft_token_id: TokenId
    persona_digest: Hash
    slot_id: Id
    generation: U64
    kind: Literal['owner_control']
    payload: dict[str, object]
    signature: Signature
    token: OpaqueToken
    request_id: Id
    terms_version: U64
    action: Literal['save_limit']


class OwnerAcceptTermsRequest(TypedDict):
    domain: Literal['room.owner.v1']
    context: MainnetContext
    grant_id: Id
    session_key_id: Id
    member_id: Id
    nft_token_id: TokenId
    persona_digest: Hash
    slot_id: Id
    generation: U64
    kind: Literal['owner_control']
    payload: dict[str, object]
    signature: Signature
    token: OpaqueToken
    request_id: Id
    terms_version: U64
    action: Literal['accept_terms']


class OwnerRemoveMemberRequest(TypedDict):
    domain: Literal['room.owner.v1']
    context: MainnetContext
    grant_id: Id
    session_key_id: Id
    member_id: Id
    nft_token_id: TokenId
    persona_digest: Hash
    slot_id: Id
    generation: U64
    kind: Literal['owner_control']
    payload: dict[str, object]
    signature: Signature
    token: OpaqueToken
    request_id: Id
    terms_version: U64
    action: Literal['remove_member']


class OwnerBlockMemberRequest(TypedDict):
    domain: Literal['room.owner.v1']
    context: MainnetContext
    grant_id: Id
    session_key_id: Id
    member_id: Id
    nft_token_id: TokenId
    persona_digest: Hash
    slot_id: Id
    generation: U64
    kind: Literal['owner_control']
    payload: dict[str, object]
    signature: Signature
    token: OpaqueToken
    request_id: Id
    terms_version: U64
    action: Literal['block_member']


class OwnerLiftBlockRequest(TypedDict):
    domain: Literal['room.owner.v1']
    context: MainnetContext
    grant_id: Id
    session_key_id: Id
    member_id: Id
    nft_token_id: TokenId
    persona_digest: Hash
    slot_id: Id
    generation: U64
    kind: Literal['owner_control']
    payload: dict[str, object]
    signature: Signature
    token: OpaqueToken
    request_id: Id
    terms_version: U64
    action: Literal['lift_block']


class OwnerAcceptProposalRequest(TypedDict):
    domain: Literal['room.owner.v1']
    context: MainnetContext
    grant_id: Id
    session_key_id: Id
    member_id: Id
    nft_token_id: TokenId
    persona_digest: Hash
    slot_id: Id
    generation: U64
    kind: Literal['owner_control']
    payload: dict[str, object]
    signature: Signature
    token: OpaqueToken
    request_id: Id
    terms_version: U64
    action: Literal['accept_proposal']


class OwnerDeclineProposalRequest(TypedDict):
    domain: Literal['room.owner.v1']
    context: MainnetContext
    grant_id: Id
    session_key_id: Id
    member_id: Id
    nft_token_id: TokenId
    persona_digest: Hash
    slot_id: Id
    generation: U64
    kind: Literal['owner_control']
    payload: dict[str, object]
    signature: Signature
    token: OpaqueToken
    request_id: Id
    terms_version: U64
    action: Literal['decline_proposal']


OwnerRequest: TypeAlias = OwnerSnapshotRequest | OwnerSaveLimitRequest | OwnerAcceptTermsRequest | OwnerRemoveMemberRequest | OwnerBlockMemberRequest | OwnerLiftBlockRequest | OwnerAcceptProposalRequest | OwnerDeclineProposalRequest


class OwnerLimits(TypedDict):
    person_cents: U64
    swarm_cents: U64
    persona_cents: U64
    used_cents: U64
    held_cents: U64


class OwnerTerms(TypedDict):
    version: U64
    input_interval_ms: U64
    segment_ms: Literal['60000']
    simulation_hz: Literal[20]


class OwnerTermsView(TypedDict):
    version: U64
    input_interval_ms: U64
    segment_ms: Literal['60000']
    simulation_hz: Literal[20]
    accepted: bool


class _OwnerMemberOptional(TypedDict, total=False):
    connected: bool


class OwnerMember(_OwnerMemberOptional):
    member_id: Id
    name: str
    is_house: bool
    place: Literal['ring', 'bench', 'disconnected', 'blocked']
    verified: bool


class OwnerProposal(TypedDict):
    proposal_id: Id
    row: Literal['input_interval_ms']
    current_ms: U64
    proposed_ms: U64
    effective_version: U64
    boundary_segment_id: Id
    required_members: list[Id]
    accepted_members: list[Id]
    declined_members: list[Id]
    expires_at: U64
    state: Literal['pending', 'accepted', 'declined', 'expired']


class OwnerModeration(TypedDict):
    target_member_id: Id
    target_name: str
    outcome: Literal['removed', 'blocked', 'block_lifted']
    boundary: Boundary | None


class OwnerSnapshot(TypedDict):
    room_id: Id
    name: str
    viewer_member_id: Id
    is_room_owner: bool
    declared_model: str
    grant_status: Literal['verified']
    limits: OwnerLimits | None
    terms: OwnerTermsView | None
    members: list[OwnerMember]
    proposal: OwnerProposal | None
    moderation: OwnerModeration | None
    waiting_count: int | None
    admission_closed: bool
    max_message_bytes: int


class OwnerResponse(TypedDict):
    type: Literal['owner_response']
    domain: Literal['room.receipt.v1']
    context: MainnetContext
    grant_id: Id
    session_key_id: Id
    request_id: Id
    action: Literal['snapshot', 'save_limit', 'accept_terms', 'remove_member', 'block_member', 'lift_block', 'accept_proposal', 'decline_proposal']
    request_digest: Hash
    state: Literal['accepted', 'pending']
    snapshot: OwnerSnapshot
    key_id: Id
    signature: Signature


class OwnerMemberRecord(TypedDict):
    member_id: Id
    account_id: AccountId
    nft_token_id: TokenId
    name: str


class OwnerConsent(TypedDict):
    member_id: Id
    version: U64


class OwnerOperation(TypedDict):
    account_id: AccountId
    request_id: Id


class OwnerReadOperation(TypedDict):
    account_id: AccountId
    request_id: Id
    expires_at: U64


class OwnerModerationRecord(TypedDict):
    viewer_account_id: AccountId
    outcome: OwnerModeration


class _OwnerStateOptional(TypedDict, total=False):
    read_requests: list[OwnerReadOperation]
    write_requests: list[OwnerOperation]
    read_clock_ms: U64
    terms_published: bool


class OwnerState(_OwnerStateOptional):
    context: MainnetContext
    terms: OwnerTerms
    accepted: list[OwnerConsent]
    members: list[OwnerMemberRecord]
    proposal: OwnerProposal | None
    proposal_ids: list[Id]
    moderation: list[OwnerModerationRecord]
    requests: list[OwnerOperation]
    denied_accounts: list[AccountId]
    denied_tokens: list[TokenId]


class GameBridge(Protocol):
    """Receives only validated bindings; never accept unvalidated client dictionaries."""

    def resolve_identity(self, proof: JoinRequest | SaleControlRequest | SaleControlLookup) -> IdentityEvidence | Error:
        """Fresh wallet control plus chain owner/custody and lock evidence; unknown fails closed."""
        ...

    def reserve_life(self, slot_binding: SlotBinding) -> ReservedLife | Error:
        """Reserve one engine-owned coming life, preserving an existing reservation on retry."""
        ...

    def lock_prediction(self, binding: SlotBinding, life_id: Id, signed_pick_or_none: PredictionRequest | None) -> PredictionLock | Error:
        """Durably commit once before activation; None closes the life without a forecast."""
        ...

    def activate(self, slot_binding: SlotBinding, life_id: Id, lock_ref: Id) -> FighterBinding | Error:
        """Require the committed pre-start lock; session rotation never resets a life lock."""
        ...

    def observe(self, binding: SlotBinding | None) -> PublicSnapshot | Error:
        """Project public arena facts; None is a spectator with no member authority."""
        ...

    def apply(self, binding: SlotBinding, sequenced_input: IntentRequest) -> Receipt | Error:
        """Enqueue intent for the host clock; prediction uses the separate lock fence."""
        ...

    def release(self, binding: SlotBinding) -> ReleaseAck | Error:
        """Revoke immediately and request the legal leave boundary exactly once."""
        ...

    def sale_control(self, owner_binding: OwnerBinding, action: SaleAction, request_id: Id) -> SaleAcknowledgement | Error:
        """Wallet-only idempotent effect; unlock never permits spawn before confirmation."""
        ...

    def seal(self, segment_id: Id) -> SealedRecord | Error:
        """Read-only complete 1200-tick record with ordered input and prediction hashes."""
        ...


class GameCustody(Protocol):
    """Game-owned bootstrap; holds are inventory, never admission or payment."""

    def challenge(self, request: AllocationChallengeRequest) -> AllocationChallenge | Error:
        """Issue a bounded one-use preset/account/session challenge without selecting a token."""
        ...

    def allocate(self, request: AllocationRequest) -> AllocationAccepted | Error:
        """Prove account and atomically hold one eligible token; identical retries preserve expiry."""
        ...
