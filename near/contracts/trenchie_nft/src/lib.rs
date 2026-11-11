//! `trenchie_nft`: persona tokens, one kind.
//!
//! - NEP-171 core, NEP-177 metadata, NEP-178 approvals, NEP-181 enumeration,
//!   NEP-297 events, burn (F81). No royalties, no NEP-199.
//! - Each token holds its preset, record and **inventory**: a bag of 12-byte
//!   entries, one of each rules-table row, 48 at most (F25). Only `apply_rows`,
//!   called by `arena`, changes a bag; a batch applies whole or not at all,
//!   removals before adds, so a serial is never on two bags (F84, C11).
//! - The sale-ready guard (F86): `nft_transfer`, `nft_transfer_call`, `claim`
//!   and `nft_burn` refuse a token without `sale_ready`. The exits (F87): 48 h
//!   with no successful `apply_rows` opens transfers until the next one lands;
//!   `end_game` opens them for good and closes `apply_rows`.
//! - Two deployments of one code: on mainnet it is the trenchie's identity only
//!   (`arena: null`: mint, premint, claim, paid mint, NEP-171; `apply_rows` refused, no sale-ready guard);
//!   on testnet the same code with an arena holds the inventory and records, filed under the mainnet
//!   token id, and whoever owns that id on mainnet controls the trenchie and its gear.
//! - Mints: `mint_trenchie` (the snap minter, init-fixed presets, once per
//!   persona, under a cap), `premint` (the snap minter fills the held premint,
//!   5 presets x 10 copies into custody), `claim` (the snap minter hands a held
//!   premint over; with none left it answers `paid_mint_required`),
//!   and `paid_mint`, a direct wallet-paid mint checked against a signed,
//!   short-lived mint permit.

use std::collections::BTreeMap;

use near_sdk::base64::Engine;
use near_sdk::base64::engine::general_purpose::URL_SAFE_NO_PAD;
use near_sdk::json_types::{U64, U128};
use near_sdk::serde_json::{self, json};
use near_sdk::store::{IterableSet, LookupMap, LookupSet};
use near_sdk::{
    AccountId, BorshStorageKey, Gas, NearToken, PanicOnDefault, Promise, PromiseOrValue,
    env, ext_contract, near, require,
};
pub use trenchie_rows::{Entry, MAX_BAG, Record, Row};

pub type TokenId = String;

pub const HOURS_48_NS: u64 = 48 * 3_600 * 1_000_000_000;
pub const PERMIT_DOMAIN: &str = "game.mint-permit.v1";
pub const PERMIT_SCHEMA: &str = "1";
pub const NOT_SALE_READY: &str = "persona not sale-ready: lock it and wait for the next batch";
const ONE_YOCTO: u128 = 1;
const GAS_FOR_RESOLVE_TRANSFER: Gas = Gas::from_tgas(10);
const GAS_FOR_NFT_TRANSFER_CALL: Gas = Gas::from_tgas(35);
const GAS_FOR_NFT_ON_APPROVE: Gas = Gas::from_tgas(10);
const MAX_ID_LEN: usize = 64;
/// A paid mint's token id is `"paid-" + nonce`, so a nonce is at most 59 characters.
const PAID_PREFIX: &str = "paid-";
/// At most this many approvals on one token, so no owner can inflate the gas of
/// every batch that loads it.
pub const MAX_APPROVALS: usize = 8;
/// Copies of one preset in the held premint (F78: 5 presets x 10).
pub const PREMINT_COPIES_PER_PRESET: u16 = 10;

#[derive(BorshStorageKey)]
#[near]
enum Key {
    Tokens,
    TokenIds,
    Owners,
    Digests,
    Serials,
    Retired,
    Batches,
    Nonces,
}

#[near(serializers = [borsh, json])]
#[derive(Clone, Debug, PartialEq, Default)]
pub struct TokenMetadata {
    pub title: Option<String>,
    pub description: Option<String>,
    pub media: Option<String>,
    pub media_hash: Option<String>,
    pub copies: Option<U64>,
    pub issued_at: Option<String>,
    pub expires_at: Option<String>,
    pub starts_at: Option<String>,
    pub updated_at: Option<String>,
    pub extra: Option<String>,
    pub reference: Option<String>,
    pub reference_hash: Option<String>,
}

#[near(serializers = [borsh, json])]
#[derive(Clone, Debug, PartialEq)]
pub struct NFTContractMetadata {
    pub spec: String,
    pub name: String,
    pub symbol: String,
    pub icon: Option<String>,
    pub base_uri: Option<String>,
    pub reference: Option<String>,
    pub reference_hash: Option<String>,
}

#[near(serializers = [borsh])]
#[derive(Clone, Debug, PartialEq)]
pub struct TokenState {
    pub owner_id: AccountId,
    pub preset_id: String,
    pub persona_digest: String,
    pub metadata: TokenMetadata,
    pub record: Record,
    pub bag: Vec<Entry>,
    pub sale_ready: bool,
    pub approvals: BTreeMap<AccountId, u64>,
    pub next_approval_id: u64,
    /// Storage bytes the owner paid for at mint (a paid mint); 0 when the
    /// contract paid (minter mints, premints). A burn refunds at most this plus
    /// the owner's approvals.
    pub paid_bytes: u64,
    /// The owner's per-token exit: once the batch sequence reaches
    /// this, the sale-ready guard is lifted for this token. 0 = none.
    pub exit_at_seq: u64,
}

/// NEP-171 `nft_token` view.
#[near(serializers = [json])]
#[derive(Debug, PartialEq)]
pub struct JsonToken {
    pub token_id: TokenId,
    pub owner_id: AccountId,
    pub metadata: TokenMetadata,
    pub approved_account_ids: BTreeMap<AccountId, u64>,
}

/// The persona view: everything a card reads.
#[near(serializers = [json])]
#[derive(Debug, PartialEq)]
pub struct Persona {
    pub token_id: TokenId,
    pub owner_id: AccountId,
    pub preset_id: String,
    pub persona_digest: String,
    pub record: Record,
    pub bag: Vec<Entry>,
    pub sale_ready: bool,
}

/// The twelve permit fields, in their frozen signing order
/// (`near/onboarding/signing.py` PERMIT_FIELDS); every value is a string.
#[near(serializers = [json])]
#[derive(Clone, Debug)]
pub struct MintPermit {
    pub domain: String,
    pub schema: String,
    pub epoch: String,
    pub network_id: String,
    pub contract_id: String,
    pub caller: String,
    pub name: String,
    pub persona_digest: String,
    pub preset_id: String,
    pub nonce: String,
    pub issued_at: String,
    pub expires_at: String,
}

impl MintPermit {
    /// v1 bytes: each field's UTF-8, prefixed by its u32 big-endian length.
    pub fn signing_bytes(&self) -> Vec<u8> {
        let fields = [
            &self.domain,
            &self.schema,
            &self.epoch,
            &self.network_id,
            &self.contract_id,
            &self.caller,
            &self.name,
            &self.persona_digest,
            &self.preset_id,
            &self.nonce,
            &self.issued_at,
            &self.expires_at,
        ];
        let mut out = Vec::new();
        for field in fields {
            require!(field.len() <= 1024, "invalid permit value");
            out.extend_from_slice(&(field.len() as u32).to_be_bytes());
            out.extend_from_slice(field.as_bytes());
        }
        out
    }
}

#[near(serializers = [json])]
#[derive(Debug, PartialEq)]
pub struct ContractState {
    pub owner: AccountId,
    pub minter: AccountId,
    /// `null` on an identity-only deployment (mainnet): no batches, no inventory, no sale-ready guard.
    pub arena: Option<AccountId>,
    pub custodian: AccountId,
    pub presets: Vec<String>,
    pub network_id: String,
    pub permit_epoch: String,
    pub mint_cost: U128,
    pub mint_cap: u32,
    pub minted_by_minter: u32,
    pub max_rows_per_batch: u32,
    pub row_count: u16,
    pub paused: bool,
    pub ended: bool,
    pub last_apply_ns: U64,
    /// The last batch applied: every batch applies in order, seq = last + 1.
    pub last_seq: U64,
    pub transfers_open: bool,
    pub premint: PremintState,
}

/// The held premint (F78, W3): `cap` tokens at most, `held` in custody now,
/// `claimed` out of custody now (claimed, moved on or burned). At `held == 0`
/// with `minted > 0` the room answers `paid_mint_required`.
#[near(serializers = [json])]
#[derive(Debug, PartialEq, Clone)]
pub struct PremintState {
    pub cap: u32,
    pub minted: u32,
    pub held: u32,
    pub claimed: u32,
    pub per_preset: Vec<(String, u16)>,
}

#[near(serializers = [json])]
#[derive(Debug, PartialEq)]
pub struct ApplyOutcome {
    pub batch_id: String,
    pub rows: u32,
    pub already_applied: bool,
    /// Rows whose persona no longer exists (burned while the row was in
    /// flight): skipped and named, never a reason to revert the batch.
    pub skipped: Vec<String>,
}

#[ext_contract(ext_receiver)]
pub trait NonFungibleTokenReceiver {
    fn nft_on_transfer(
        &mut self,
        sender_id: AccountId,
        previous_owner_id: AccountId,
        token_id: TokenId,
        msg: String,
    ) -> PromiseOrValue<bool>;
}

#[ext_contract(ext_approval_receiver)]
pub trait NonFungibleTokenApprovalReceiver {
    fn nft_on_approve(&mut self, token_id: TokenId, owner_id: AccountId, approval_id: u64, msg: String);
}

#[near(contract_state)]
#[derive(PanicOnDefault)]
pub struct TrenchieNft {
    owner: AccountId,
    minter: AccountId,
    arena: Option<AccountId>,
    custodian: AccountId,
    presets: Vec<String>,
    network_id: String,
    permit_public_key: [u8; 32],
    permit_epoch: String,
    permit_ttl_ms: u64,
    mint_cost: u128,
    mint_cap: u32,
    minted_by_minter: u32,
    max_rows_per_batch: u32,
    row_count: u16,
    paused: bool,
    ended: bool,
    last_apply_ns: u64,
    last_seq: u64,
    metadata: NFTContractMetadata,
    tokens: LookupMap<TokenId, TokenState>,
    token_ids: IterableSet<TokenId>,
    owners: LookupMap<AccountId, Vec<TokenId>>,
    digests: LookupSet<String>,
    serials: LookupMap<u32, TokenId>,
    retired: LookupSet<u32>,
    batches: LookupSet<String>,
    nonces: LookupSet<String>,
    premint_cap: u32,
    premint_claimed: u32,
    /// preset -> (its premint persona digest, copies minted).
    premints: BTreeMap<String, (String, u16)>,
}

fn emit(standard: &str, version: &str, event: &str, data: serde_json::Value) {
    env::log_str(&format!(
        "EVENT_JSON:{}",
        json!({"standard": standard, "version": version, "event": event, "data": [data]})
    ));
}

fn is_hex64(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

fn is_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= MAX_ID_LEN
        && value.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_' || b == b'.')
}

/// Storage bytes a token's approvals add to its record: each entry's borsh
/// form (a u32 length, the account id, a u64 approval id). The record's key is
/// unchanged by them, so this is exactly what clearing them frees.
fn approvals_bytes(approvals: &BTreeMap<AccountId, u64>) -> u64 {
    approvals.keys().map(|a| 4 + a.as_str().len() as u64 + 8).sum()
}

fn parse_ms(value: &str) -> u64 {
    require!(
        !value.is_empty() && value.len() <= 20 && value.bytes().all(|b| b.is_ascii_digit()),
        "invalid permit time"
    );
    require!(value == "0" || !value.starts_with('0'), "invalid permit time");
    value.parse::<u64>().unwrap_or_else(|_| env::panic_str("invalid permit time"))
}

fn decode_b64url<const N: usize>(value: &str, what: &str) -> [u8; N] {
    let raw = URL_SAFE_NO_PAD
        .decode(value)
        .unwrap_or_else(|_| env::panic_str(&format!("invalid {what} encoding")));
    require!(URL_SAFE_NO_PAD.encode(&raw) == value, format!("invalid {what} encoding"));
    raw.try_into().unwrap_or_else(|_| env::panic_str(&format!("invalid {what} length")))
}

#[near]
impl TrenchieNft {
    #[init]
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        owner: AccountId,
        minter: AccountId,
        arena: Option<AccountId>,
        custodian: AccountId,
        presets: Vec<String>,
        network_id: String,
        permit_public_key: String,
        permit_epoch: String,
        permit_ttl_ms: U64,
        mint_cost: U128,
        mint_cap: u32,
        max_rows_per_batch: u32,
        row_count: u16,
        metadata: NFTContractMetadata,
        premint_cap: Option<u32>,
    ) -> Self {
        require!(!presets.is_empty() && presets.iter().all(|p| is_id(p)), "invalid presets");
        require!(network_id == "testnet" || network_id == "mainnet", "network_id must be testnet or mainnet");
        require!(metadata.spec == "nft-1.0.0", "metadata spec must be nft-1.0.0");
        require!(permit_ttl_ms.0 > 0 && max_rows_per_batch > 0 && row_count > 0, "invalid limits");
        Self {
            owner,
            minter,
            arena,
            custodian,
            presets,
            network_id,
            permit_public_key: decode_b64url::<32>(&permit_public_key, "permit public key"),
            permit_epoch,
            permit_ttl_ms: permit_ttl_ms.0,
            mint_cost: mint_cost.0,
            mint_cap,
            minted_by_minter: 0,
            max_rows_per_batch,
            row_count,
            paused: false,
            ended: false,
            last_apply_ns: env::block_timestamp(),
            last_seq: 0,
            metadata,
            tokens: LookupMap::new(Key::Tokens),
            token_ids: IterableSet::new(Key::TokenIds),
            owners: LookupMap::new(Key::Owners),
            digests: LookupSet::new(Key::Digests),
            serials: LookupMap::new(Key::Serials),
            retired: LookupSet::new(Key::Retired),
            batches: LookupSet::new(Key::Batches),
            nonces: LookupSet::new(Key::Nonces),
            premint_cap: premint_cap.unwrap_or(50),
            premint_claimed: 0,
            premints: BTreeMap::new(),
        }
    }

    // ------------------------------------------------------------------ mints

    /// The snap minter mints one persona with an init-fixed preset and an empty bag.
    /// Storage comes from the contract's balance (a function-call key can't pay).
    pub fn mint_trenchie(
        &mut self,
        token_id: TokenId,
        owner_id: AccountId,
        preset_id: String,
        persona_digest: String,
        metadata: Option<TokenMetadata>,
    ) -> Persona {
        require!(env::predecessor_account_id() == self.minter, "only the snap minter may mint");
        self.assert_writable();
        require!(self.minted_by_minter < self.mint_cap, "mint cap reached");
        self.minted_by_minter += 1;
        // Never a copy of a premint persona: the minter key mints only fresh personas (the scarcity is 50 premints,
        // first come, first served, then a paid mint at cost).
        self.internal_mint(token_id, owner_id, preset_id, persona_digest, metadata.unwrap_or_default())
    }

    /// The held premint (F78, W3): the snap minter mints `copies` more of one
    /// init-fixed preset into custody, ids `<preset>-00`, `<preset>-01`, ...,
    /// empty bags. Every copy of a preset carries that preset's one persona
    /// digest (so the room's claim and run-out permit name the same persona).
    /// Bounded by `premint_cap` in total and 10 copies a preset; storage from
    /// the contract's balance. Premints are minted sale-ready: an empty bag
    /// that nobody has played, so the pool can hand it out; once it plays, the
    /// writer locks it like any persona (a bag change needs `sale_ready` false).
    pub fn premint(&mut self, preset_id: String, persona_digest: String, copies: u16) -> Vec<TokenId> {
        require!(env::predecessor_account_id() == self.minter, "only the snap minter may mint");
        self.assert_writable();
        require!(self.presets.contains(&preset_id), "preset is not one fixed at init");
        require!(is_hex64(&persona_digest), "persona digest must be 64 lowercase hex characters");
        require!(copies >= 1, "copies must be at least 1");
        let (digest, done) = match self.premints.get(&preset_id) {
            Some((d, n)) => {
                require!(*d == persona_digest, "a preset's premint copies share one persona digest");
                (d.clone(), *n)
            }
            None => {
                require!(self.digests.insert(persona_digest.clone()), "persona already minted");
                (persona_digest, 0)
            }
        };
        require!(done + copies <= PREMINT_COPIES_PER_PRESET, "at most 10 premint copies of a preset");
        let minted = self.premint_minted();
        require!(minted + copies as u32 <= self.premint_cap, "premint cap reached");
        let custodian = self.custodian.clone();
        let mut ids = Vec::with_capacity(copies as usize);
        for i in done..done + copies {
            let token_id = format!("{preset_id}-{i:02}");
            require!(is_id(&token_id), "invalid token id");
            require!(!self.tokens.contains_key(&token_id), "token id already minted");
            self.insert_token(&token_id, &custodian, preset_id.clone(), digest.clone(), TokenMetadata::default(), true, 0);
            ids.push(token_id);
        }
        self.premints.insert(preset_id.clone(), (digest, done + copies));
        emit("nep171", "1.2.0", "nft_mint", json!({"owner_id": custodian, "token_ids": ids, "memo": "premint"}));
        ids
    }

    /// The direct wallet-paid mint: the player pays `mint_cost` in one wallet
    /// transaction against a short-lived permit signed by the mint-permit key.
    /// Any failure mints nothing and consumes nothing.
    #[payable]
    ///
    /// The token's metadata is built here from the signed permit alone (title =
    /// the guarded name); nothing unsigned from the caller is stored.
    pub fn paid_mint(&mut self, permit: MintPermit, signature: String) -> Persona {
        self.assert_writable();
        let caller = env::predecessor_account_id();
        require!(caller == env::signer_account_id(), "paid mint must be a direct wallet call");
        require!(permit.domain == PERMIT_DOMAIN && permit.schema == PERMIT_SCHEMA, "invalid mint permit: schema");
        require!(permit.epoch == self.permit_epoch, "invalid mint permit: epoch");
        require!(permit.network_id == self.network_id, "invalid mint permit: network");
        require!(permit.contract_id == env::current_account_id().as_str(), "invalid mint permit: contract");
        require!(permit.caller == caller.as_str(), "invalid mint permit: caller");
        let issued = parse_ms(&permit.issued_at);
        let expires = parse_ms(&permit.expires_at);
        let now = env::block_timestamp_ms();
        require!(issued <= now, "invalid mint permit: issued in the future");
        require!(now < expires, "invalid mint permit: expired");
        require!(expires - issued <= self.permit_ttl_ms, "invalid mint permit: lifetime too long");
        require!(
            is_id(&permit.nonce) && permit.nonce.len() <= MAX_ID_LEN - PAID_PREFIX.len(),
            "invalid mint permit: nonce"
        );
        require!(!self.nonces.contains(&permit.nonce), "invalid mint permit: nonce used");
        require!(!permit.name.trim().is_empty(), "invalid mint permit: name");
        require!(
            env::attached_deposit().as_yoctonear() == self.mint_cost,
            "attach exactly the mint cost"
        );
        let signature = decode_b64url::<64>(&signature, "signature");
        require!(
            env::ed25519_verify(&signature, permit.signing_bytes(), &self.permit_public_key),
            "invalid mint permit: signature"
        );
        // Measure before the nonce is written: it is storage this mint adds.
        self.flush();
        let before = env::storage_usage();
        self.nonces.insert(permit.nonce.clone());
        let metadata = TokenMetadata { title: Some(permit.name.clone()), ..Default::default() };
        let token_id = format!("{PAID_PREFIX}{}", permit.nonce);
        // A run-out paid mint of a premint preset carries that preset's digest:
        // a copy of the preset, not a second claim on a custom persona.
        let preset_copy = self.premints.get(&permit.preset_id).is_some_and(|(d, _)| *d == permit.persona_digest);
        if preset_copy {
            // The only route to a copy of a premint persona: after run-out, through a permit, paid at cost.
            require!(
                self.premint_minted() > 0 && self.premint_held() == 0,
                "a copy of a premint persona mints only after run-out: claim a held premint while any is left"
            );
        }
        let persona = if preset_copy {
            require!(self.presets.contains(&permit.preset_id), "preset is not one fixed at init");
            require!(!self.tokens.contains_key(&token_id), "token id already minted");
            self.insert_token(&token_id, &caller, permit.preset_id, permit.persona_digest, metadata, false, 0);
            emit("nep171", "1.2.0", "nft_mint", json!({"owner_id": caller, "token_ids": [token_id]}));
            self.persona_view(&token_id)
        } else {
            self.internal_mint(token_id.clone(), caller, permit.preset_id, permit.persona_digest, metadata)
        };
        self.flush();
        let bytes = env::storage_usage() - before;
        let cost = bytes as u128 * env::storage_byte_cost().as_yoctonear();
        require!(cost <= self.mint_cost, "mint cost does not cover storage");
        let mut token = self.token(&token_id);
        token.paid_bytes = bytes;
        self.tokens.insert(token_id.clone(), token);
        self.flush();
        emit("trenchie", "1.0.0", "paid_mint", json!({"token_id": token_id, "storage_bytes": bytes, "storage_cost": U128(cost)}));
        persona
    }

    /// The snap minter hands a held premint to its claimer. Needs `sale_ready`
    /// (or an open exit) like any change of owner.
    pub fn claim(&mut self, token_id: TokenId, to: AccountId, persona_hash: String) -> Persona {
        require!(env::predecessor_account_id() == self.minter, "only the snap minter may claim");
        self.assert_writable();
        let token = self.token(&token_id);
        require!(token.persona_digest == persona_hash, "persona hash does not match");
        if token.owner_id == to {
            return self.persona_view(&token_id);
        }
        if token.owner_id != self.custodian {
            // Run-out (F78, W3): the premint exists and none of it is in custody.
            if self.premint_minted() > 0 && self.premint_held() == 0 {
                env::panic_str("paid_mint_required: all held premints are claimed");
            }
            env::panic_str("token is not held for claim");
        }
        self.assert_transferable(&token);
        let minter = self.minter.clone();
        self.internal_transfer_unguarded(&token_id, &to, Some(&minter), Some("claim"), true);
        self.persona_view(&token_id)
    }

    // ------------------------------------------------------------ the batch

    /// Apply one hourly batch (F84): one row per persona touched, its bag as it
    /// stands. Only `arena` may call. Whole or nothing: any refusal panics and
    /// reverts every row. A batch id already applied is a no-op, so retries are
    /// safe. Rows are absolute, so batches apply strictly in order: `seq` must
    /// be above the last applied one, so a stale retry can never roll a newer
    /// batch back. Arena sends one batch at a time, so seqs arrive
    /// as 1, 2, 3, ...; a gap is a batch the owner's key abandoned.
    pub fn apply_rows(&mut self, batch_id: String, seq: U64, rows: Vec<Row>) -> ApplyOutcome {
        require!(
            self.arena.is_some(),
            "identity-only deployment: inventory and records live on testnet, filed under this token id"
        );
        require!(Some(env::predecessor_account_id()) == self.arena, "only arena may apply rows");
        require!(!self.ended, "the game has ended: apply_rows is closed");
        require!(!self.paused, "paused");
        require!(is_id(&batch_id), "invalid batch id");
        if self.batches.contains(&batch_id) {
            return ApplyOutcome { batch_id, rows: rows.len() as u32, already_applied: true, skipped: Vec::new() };
        }
        require!(
            seq.0 > self.last_seq,
            format!("batches apply in order: seq {} is not after the last applied, {}", seq.0, self.last_seq)
        );
        require!(rows.len() as u32 <= self.max_rows_per_batch, "batch over the row cap");

        // A persona burned while its row was in flight is skipped and named, so
        // one owner's burn can never revert every other row of the batch.
        let mut skipped: Vec<String> = Vec::new();
        let rows: Vec<Row> = rows
            .into_iter()
            .filter(|r| {
                let live = self.tokens.contains_key(&r.token_id);
                if !live {
                    skipped.push(r.token_id.clone());
                }
                live
            })
            .collect();

        // Load every touched token once; a token appears in one row at most.
        let mut states: Vec<TokenState> = Vec::with_capacity(rows.len());
        let mut seen = std::collections::BTreeSet::new();
        for row in &rows {
            require!(seen.insert(row.token_id.clone()), "a persona appears twice in one batch");
            let state = self.token(&row.token_id);
            require!(row.bag.len() <= MAX_BAG, "a bag holds at most 48 entries");
            let mut rows_in_bag = std::collections::BTreeSet::new();
            for entry in &row.bag {
                require!(entry.row < self.row_count, "entry row is not in the rules table");
                require!(rows_in_bag.insert(entry.row), "a second copy of a row in one bag");
            }
            if state.sale_ready && state.bag != row.bag {
                env::panic_str("bag change on a sale-ready persona");
            }
            states.push(state);
        }

        // Removals first, across the whole batch. Only serialled copies (serial
        // != 0) have an identity to track. A copy that leaves every bag is
        // unheld, not gone: it may be on the floor across the cut and grabbed
        // in a later batch (as the sim moves floor items).
        // Only `nft_burn` retires a serial.
        for (row, state) in rows.iter().zip(&states) {
            let new_keys: std::collections::BTreeSet<u32> = row.bag.iter().map(Entry::key).collect();
            for old in &state.bag {
                if old.serial != 0 && !new_keys.contains(&old.key()) {
                    self.serials.remove(&old.key());
                }
            }
        }
        // Then adds.
        for (row, state) in rows.iter().zip(&states) {
            let old_keys: std::collections::BTreeSet<u32> = state.bag.iter().map(Entry::key).collect();
            for entry in &row.bag {
                let key = entry.key();
                if entry.serial == 0 || old_keys.contains(&key) {
                    continue;
                }
                require!(!self.retired.contains(&key), "serial reused: that copy was burned");
                require!(self.serials.get(&key).is_none(), "serial already on another bag");
                self.serials.insert(key, row.token_id.clone());
            }
        }
        for (row, mut state) in rows.iter().cloned().zip(states) {
            state.bag = row.bag;
            state.record = row.record;
            if let Some(flag) = row.sale_ready {
                state.sale_ready = flag;
            }
            self.tokens.insert(row.token_id, state);
        }
        self.batches.insert(batch_id.clone());
        self.last_seq = seq.0;
        self.last_apply_ns = env::block_timestamp();
        emit("trenchie", "1.0.0", "apply_rows", json!({"batch_id": batch_id, "seq": seq, "rows": rows.len(), "skipped": skipped}));
        ApplyOutcome { batch_id, rows: rows.len() as u32, already_applied: false, skipped }
    }

    // ------------------------------------------------------- NEP-171 core

    #[payable]
    pub fn nft_transfer(
        &mut self,
        receiver_id: AccountId,
        token_id: TokenId,
        approval_id: Option<u64>,
        memo: Option<String>,
    ) {
        require!(env::attached_deposit().as_yoctonear() == ONE_YOCTO, "Requires attached deposit of exactly 1 yoctoNEAR");
        let sender = env::predecessor_account_id();
        self.internal_transfer(&sender, &receiver_id, &token_id, approval_id, memo, true);
    }

    #[payable]
    pub fn nft_transfer_call(
        &mut self,
        receiver_id: AccountId,
        token_id: TokenId,
        approval_id: Option<u64>,
        memo: Option<String>,
        msg: String,
    ) -> PromiseOrValue<bool> {
        require!(env::attached_deposit().as_yoctonear() == ONE_YOCTO, "Requires attached deposit of exactly 1 yoctoNEAR");
        require!(
            env::prepaid_gas() > GAS_FOR_NFT_TRANSFER_CALL.saturating_add(GAS_FOR_RESOLVE_TRANSFER),
            "more gas is required"
        );
        let sender = env::predecessor_account_id();
        let (previous_owner, previous_approvals) =
            self.internal_transfer(&sender, &receiver_id, &token_id, approval_id, memo, false);
        ext_receiver::ext(receiver_id.clone())
            .with_static_gas(GAS_FOR_NFT_TRANSFER_CALL)
            .nft_on_transfer(sender, previous_owner.clone(), token_id.clone(), msg)
            .then(
                Self::ext(env::current_account_id())
                    .with_static_gas(GAS_FOR_RESOLVE_TRANSFER)
                    .nft_resolve_transfer(previous_owner, receiver_id, token_id, Some(previous_approvals)),
            )
            .into()
    }

    /// Undo a transfer the receiver returned. Not guarded: it only reverts a
    /// transfer that passed the guard.
    #[private]
    pub fn nft_resolve_transfer(
        &mut self,
        previous_owner_id: AccountId,
        receiver_id: AccountId,
        token_id: TokenId,
        approved_account_ids: Option<BTreeMap<AccountId, u64>>,
    ) -> bool {
        let must_return = match env::promise_result_checked(0, 16) {
            Ok(value) => serde_json::from_slice::<bool>(&value).unwrap_or(true),
            Err(_) => true,
        };
        // The previous owner's approvals were cleared at the transfer without a
        // refund; they are refunded only once the transfer stands, so a bounce
        // that restores them can't be looped to drain the contract.
        let stands = |this: &Self| {
            if let Some(approvals) = &approved_account_ids {
                this.refund(&previous_owner_id, approvals_bytes(approvals) as u128 * env::storage_byte_cost().as_yoctonear());
            }
            true
        };
        if !must_return {
            return stands(self);
        }
        let Some(token) = self.tokens.get(&token_id).cloned() else {
            return stands(self); // burned meanwhile
        };
        if token.owner_id != receiver_id {
            return stands(self); // moved on meanwhile
        }
        self.internal_transfer_unguarded(&token_id, &previous_owner_id, None, Some("returned"), true);
        if let Some(approvals) = approved_account_ids {
            let mut token = self.token(&token_id);
            token.approvals = approvals;
            self.tokens.insert(token_id, token);
        }
        false
    }

    pub fn nft_token(&self, token_id: TokenId) -> Option<JsonToken> {
        self.tokens.get(&token_id).map(|t| JsonToken {
            token_id: token_id.clone(),
            owner_id: t.owner_id.clone(),
            metadata: t.metadata.clone(),
            approved_account_ids: t.approvals.clone(),
        })
    }

    // ---------------------------------------------------- NEP-178 approvals

    #[payable]
    pub fn nft_approve(&mut self, token_id: TokenId, account_id: AccountId, msg: Option<String>) -> Option<Promise> {
        let attached = env::attached_deposit().as_yoctonear();
        require!(attached > 0, "Requires attached deposit of at least 1 yoctoNEAR");
        let owner = env::predecessor_account_id();
        let mut token = self.token(&token_id);
        require!(token.owner_id == owner, "only the owner may approve");
        let before = env::storage_usage();
        let approval_id = token.next_approval_id;
        token.next_approval_id += 1;
        let is_new = token.approvals.insert(account_id.clone(), approval_id).is_none();
        require!(!is_new || token.approvals.len() <= MAX_APPROVALS, "at most 8 approvals on a token");
        self.tokens.insert(token_id.clone(), token);
        self.tokens.flush();
        let cost = env::storage_usage().saturating_sub(before) as u128 * env::storage_byte_cost().as_yoctonear();
        require!(attached >= cost, "attach enough to cover the approval's storage");
        // Whatever the approval's storage didn't use goes back, new or re-approval.
        self.refund(&owner, attached - cost);
        msg.map(|msg| {
            ext_approval_receiver::ext(account_id)
                .with_static_gas(GAS_FOR_NFT_ON_APPROVE)
                .nft_on_approve(token_id, owner, approval_id, msg)
        })
    }

    #[payable]
    pub fn nft_revoke(&mut self, token_id: TokenId, account_id: AccountId) {
        require!(env::attached_deposit().as_yoctonear() == ONE_YOCTO, "Requires attached deposit of exactly 1 yoctoNEAR");
        let mut token = self.token(&token_id);
        require!(token.owner_id == env::predecessor_account_id(), "only the owner may revoke");
        if token.approvals.remove(&account_id).is_some() {
            self.store_and_refund(token_id, token);
        }
    }

    #[payable]
    pub fn nft_revoke_all(&mut self, token_id: TokenId) {
        require!(env::attached_deposit().as_yoctonear() == ONE_YOCTO, "Requires attached deposit of exactly 1 yoctoNEAR");
        let mut token = self.token(&token_id);
        require!(token.owner_id == env::predecessor_account_id(), "only the owner may revoke");
        if !token.approvals.is_empty() {
            token.approvals.clear();
            self.store_and_refund(token_id, token);
        }
    }

    pub fn nft_is_approved(&self, token_id: TokenId, approved_account_id: AccountId, approval_id: Option<u64>) -> bool {
        // A missing token has no approvals: false, never a panic.
        let Some(token) = self.tokens.get(&token_id) else {
            return false;
        };
        match token.approvals.get(&approved_account_id) {
            Some(id) => approval_id.is_none_or(|want| want == *id),
            None => false,
        }
    }

    // ------------------------------------------------- NEP-177 / NEP-181

    pub fn nft_metadata(&self) -> NFTContractMetadata {
        self.metadata.clone()
    }

    pub fn nft_total_supply(&self) -> U128 {
        U128(self.token_ids.len() as u128)
    }

    pub fn nft_tokens(&self, from_index: Option<U128>, limit: Option<u64>) -> Vec<JsonToken> {
        let start = from_index.map(|v| usize::try_from(v.0).unwrap_or(usize::MAX)).unwrap_or(0);
        self.token_ids
            .iter()
            .skip(start)
            .take(limit.unwrap_or(50) as usize)
            .filter_map(|id| self.nft_token(id.clone()))
            .collect()
    }

    pub fn nft_supply_for_owner(&self, account_id: AccountId) -> U128 {
        U128(self.owners.get(&account_id).map(|v| v.len()).unwrap_or(0) as u128)
    }

    pub fn nft_tokens_for_owner(&self, account_id: AccountId, from_index: Option<U128>, limit: Option<u64>) -> Vec<JsonToken> {
        let start = from_index.map(|v| usize::try_from(v.0).unwrap_or(usize::MAX)).unwrap_or(0);
        self.owners
            .get(&account_id)
            .map(|ids| {
                ids.iter()
                    .skip(start)
                    .take(limit.unwrap_or(50) as usize)
                    .filter_map(|id| self.nft_token(id.clone()))
                    .collect()
            })
            .unwrap_or_default()
    }

    // --------------------------------------------------------------- burn

    /// Burn a sale-ready persona. The storage it frees goes back to its owner
    /// only as far as the owner paid for it: a paid mint's bytes and its open
    /// approvals. Storage the contract paid (minter mints, premints, bag
    /// growth from `apply_rows`) stays with the contract. Returns
    /// the refund in yoctoNEAR.
    #[payable]
    pub fn nft_burn(&mut self, token_id: TokenId) -> U128 {
        require!(env::attached_deposit().as_yoctonear() == ONE_YOCTO, "Requires attached deposit of exactly 1 yoctoNEAR");
        let owner = env::predecessor_account_id();
        let token = self.token(&token_id);
        require!(token.owner_id == owner, "only the owner may burn");
        self.assert_transferable(&token);
        self.flush();
        let before = env::storage_usage();
        if owner == self.custodian && self.is_premint(&token_id, &token) {
            self.premint_claimed += 1; // gone from custody for good
        }
        for entry in token.bag.iter().filter(|e| e.serial != 0) {
            self.serials.remove(&entry.key());
            self.retired.insert(entry.key());
        }
        self.tokens.remove(&token_id);
        self.token_ids.remove(&token_id);
        self.owner_index_remove(&owner, &token_id);
        self.flush();
        let byte = env::storage_byte_cost().as_yoctonear();
        let freed = before.saturating_sub(env::storage_usage()) as u128 * byte;
        let owner_paid = token.paid_bytes as u128 * byte + approvals_bytes(&token.approvals) as u128 * byte;
        let refund = freed.min(owner_paid);
        emit("nep171", "1.2.0", "nft_burn", json!({"owner_id": owner, "token_ids": [token_id]}));
        self.refund(&owner, refund);
        U128(refund)
    }

    // ----------------------------------------------------- owner (the owner's key)

    /// The owner's own exit from the sale-ready guard. Any batch
    /// resets the 48 h exit, so an operator could keep one persona from sale
    /// for good. A wallet-signed request lifts the guard for this token once
    /// two more batches have applied, whether or not they set `sale_ready`.
    /// An honest operator locks the persona (sets `sale_ready`) within those
    /// two batches anyway; this is the floor when it doesn't.
    #[payable]
    pub fn request_exit(&mut self, token_id: TokenId) -> U64 {
        require!(env::attached_deposit().as_yoctonear() == ONE_YOCTO, "Requires attached deposit of exactly 1 yoctoNEAR");
        let mut token = self.token(&token_id);
        require!(token.owner_id == env::predecessor_account_id(), "only the owner may request an exit");
        if token.exit_at_seq == 0 || token.exit_at_seq > self.last_seq + 2 {
            token.exit_at_seq = self.last_seq + 2;
        }
        let at = token.exit_at_seq;
        self.tokens.insert(token_id.clone(), token);
        emit("trenchie", "1.0.0", "request_exit", json!({"token_id": token_id, "exit_at_seq": U64(at)}));
        U64(at)
    }

    /// the owner's key: take out balance above what storage locks, keeping `reserve`
    /// for future function-call mints (the mint_cost surplus over storage).
    #[payable]
    pub fn withdraw_surplus(&mut self, amount: U128, reserve: U128) -> Promise {
        self.assert_owner();
        self.flush();
        let locked = env::storage_usage() as u128 * env::storage_byte_cost().as_yoctonear();
        let balance = env::account_balance().as_yoctonear();
        require!(
            balance >= locked + reserve.0 + amount.0,
            "withdraw would leave less than storage plus the reserve"
        );
        emit("trenchie", "1.0.0", "withdraw_surplus", json!({"amount": amount, "to": self.owner}));
        Promise::new(self.owner.clone()).transfer(NearToken::from_yoctonear(amount.0))
    }

    /// Upgrade entry: deploy new code and call this in the same
    /// transaction with the contract account's own key. Today it reads the
    /// current layout unchanged; a release that changes the layout replaces
    /// this body with the conversion from the old one.
    #[private]
    #[init(ignore_state)]
    pub fn migrate() -> Self {
        env::state_read().unwrap_or_else(|| env::panic_str("no state to migrate"))
    }

    /// The owner's emergency stop for the writes our own keys make: `mint_trenchie`,
    /// `premint`, `claim`, `paid_mint` and `apply_rows`. By design it never
    /// freezes a holder's own token: transfers, approvals and burns by owners
    /// stay open, so a compromised host key can be stopped without the
    /// contract ever holding players' property hostage.
    #[payable]
    pub fn pause(&mut self) {
        self.assert_owner();
        self.paused = true;
        emit("trenchie", "1.0.0", "pause", json!({"paused": true}));
    }

    #[payable]
    pub fn unpause(&mut self) {
        self.assert_owner();
        self.paused = false;
        emit("trenchie", "1.0.0", "pause", json!({"paused": false}));
    }

    /// Planned shutdown: opens every transfer for good and closes `apply_rows`.
    /// Does not depend on a final batch.
    #[payable]
    pub fn end_game(&mut self) {
        self.assert_owner();
        self.ended = true;
        emit("trenchie", "1.0.0", "end_game", json!({"last_apply_ns": U64(self.last_apply_ns)}));
    }

    #[payable]
    pub fn set_max_rows_per_batch(&mut self, max_rows_per_batch: u32) {
        self.assert_owner();
        require!(max_rows_per_batch > 0, "invalid limit");
        self.max_rows_per_batch = max_rows_per_batch;
    }

    /// Rotate the permit key; outstanding permits of the old epoch stop working.
    #[payable]
    pub fn rotate_permit_key(&mut self, permit_public_key: String, permit_epoch: String) {
        self.assert_owner();
        require!(permit_epoch != self.permit_epoch, "a rotation needs a new epoch");
        self.permit_public_key = decode_b64url::<32>(&permit_public_key, "permit public key");
        self.permit_epoch = permit_epoch;
    }

    #[payable]
    pub fn set_minter(&mut self, minter: AccountId) {
        self.assert_owner();
        self.minter = minter;
    }

    // -------------------------------------------------------------- views

    pub fn trenchie(&self, token_id: TokenId) -> Option<Persona> {
        self.tokens.get(&token_id).map(|_| self.persona_view(&token_id))
    }

    pub fn serial_holder(&self, row: u16, serial: u16) -> Option<TokenId> {
        self.serials.get(&(((row as u32) << 16) | serial as u32)).cloned()
    }

    pub fn serial_retired(&self, row: u16, serial: u16) -> bool {
        self.retired.contains(&(((row as u32) << 16) | serial as u32))
    }

    pub fn batch_applied(&self, batch_id: String) -> bool {
        self.batches.contains(&batch_id)
    }

    pub fn contract_state(&self) -> ContractState {
        ContractState {
            owner: self.owner.clone(),
            minter: self.minter.clone(),
            arena: self.arena.clone(),
            custodian: self.custodian.clone(),
            presets: self.presets.clone(),
            network_id: self.network_id.clone(),
            permit_epoch: self.permit_epoch.clone(),
            mint_cost: U128(self.mint_cost),
            mint_cap: self.mint_cap,
            minted_by_minter: self.minted_by_minter,
            max_rows_per_batch: self.max_rows_per_batch,
            row_count: self.row_count,
            paused: self.paused,
            ended: self.ended,
            last_apply_ns: U64(self.last_apply_ns),
            last_seq: U64(self.last_seq),
            transfers_open: self.exits_open(),
            premint: self.premint_state(),
        }
    }

    pub fn premint_state(&self) -> PremintState {
        PremintState {
            cap: self.premint_cap,
            minted: self.premint_minted(),
            held: self.premint_held(),
            claimed: self.premint_claimed,
            per_preset: self.premints.iter().map(|(p, (_, n))| (p.clone(), *n)).collect(),
        }
    }
}

impl TrenchieNft {
    fn assert_owner(&self) {
        require!(env::attached_deposit().as_yoctonear() == ONE_YOCTO, "Requires attached deposit of exactly 1 yoctoNEAR");
        require!(env::predecessor_account_id() == self.owner, "owner only");
    }

    fn assert_writable(&self) {
        require!(!self.paused, "paused");
        require!(!self.ended, "the game has ended");
    }

    /// The 48 h exit and `end_game` lift the sale-ready guard.
    fn exits_open(&self) -> bool {
        self.ended || env::block_timestamp() >= self.last_apply_ns.saturating_add(HOURS_48_NS)
    }

    fn assert_transferable(&self, token: &TokenState) {
        // Identity-only (mainnet): the gear and records live on testnet under this token id and
        // follow whoever owns it here, so a sale moves them and no bag can go stale under a sale.
        if self.arena.is_none() {
            return;
        }
        let own_exit = token.exit_at_seq != 0 && self.last_seq >= token.exit_at_seq;
        if !self.exits_open() && !own_exit {
            require!(token.sale_ready, NOT_SALE_READY);
        }
    }

    fn token(&self, token_id: &str) -> TokenState {
        self.tokens
            .get(token_id)
            .cloned()
            .unwrap_or_else(|| env::panic_str("token not found"))
    }

    fn persona_view(&self, token_id: &str) -> Persona {
        let t = self.token(token_id);
        Persona {
            token_id: token_id.to_string(),
            owner_id: t.owner_id,
            preset_id: t.preset_id,
            persona_digest: t.persona_digest,
            record: t.record,
            bag: t.bag,
            sale_ready: t.sale_ready,
        }
    }

    fn flush(&mut self) {
        self.tokens.flush();
        self.token_ids.flush();
        self.owners.flush();
        self.serials.flush();
    }

    fn premint_minted(&self) -> u32 {
        self.premints.values().map(|(_, n)| *n as u32).sum()
    }

    /// `premint_claimed` counts premint tokens that have left custody (claimed,
    /// moved on, or burned). Custody can't receive a token after the premint,
    /// so each leaves once and `held` never re-arms.
    fn premint_held(&self) -> u32 {
        self.premint_minted().saturating_sub(self.premint_claimed)
    }

    /// A premint token is one the premint minted: its id is `<preset>-NN` within the copies minted, and it carries
    /// that preset's digest. A paid copy shares the digest but never the id, so it is never counted as a premint.
    fn is_premint(&self, token_id: &str, token: &TokenState) -> bool {
        let Some((digest, copies)) = self.premints.get(&token.preset_id) else {
            return false;
        };
        *digest == token.persona_digest
            && token_id
                .strip_prefix(token.preset_id.as_str())
                .and_then(|rest| rest.strip_prefix('-'))
                .is_some_and(|n| n.len() == 2 && n.bytes().all(|b| b.is_ascii_digit()) && n.parse::<u16>().is_ok_and(|n| n < *copies))
    }

    /// Custody only ever receives tokens from the premint mint (a transfer into it is refused), so a premint leaving
    /// custody is counted once and nothing re-arms `held`.
    fn count_custody_move(&mut self, token_id: &str, token: &TokenState, from: &AccountId) {
        if *from == self.custodian && self.is_premint(token_id, token) {
            self.premint_claimed += 1;
        }
    }

    fn refund(&self, to: &AccountId, amount: u128) {
        if amount > 0 {
            let _ = Promise::new(to.clone()).transfer(NearToken::from_yoctonear(amount));
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn insert_token(
        &mut self,
        token_id: &TokenId,
        owner_id: &AccountId,
        preset_id: String,
        persona_digest: String,
        metadata: TokenMetadata,
        sale_ready: bool,
        paid_bytes: u64,
    ) {
        self.tokens.insert(
            token_id.clone(),
            TokenState {
                owner_id: owner_id.clone(),
                preset_id,
                persona_digest,
                metadata,
                record: Record::default(),
                bag: Vec::new(),
                sale_ready,
                approvals: BTreeMap::new(),
                next_approval_id: 0,
                paid_bytes,
                exit_at_seq: 0,
            },
        );
        self.token_ids.insert(token_id.clone());
        self.owner_index_add(owner_id, token_id);
    }

    fn internal_mint(
        &mut self,
        token_id: TokenId,
        owner_id: AccountId,
        preset_id: String,
        persona_digest: String,
        metadata: TokenMetadata,
    ) -> Persona {
        require!(is_id(&token_id), "invalid token id");
        require!(self.presets.contains(&preset_id), "preset is not one fixed at init");
        require!(is_hex64(&persona_digest), "persona digest must be 64 lowercase hex characters");
        require!(!self.tokens.contains_key(&token_id), "token id already minted");
        require!(self.digests.insert(persona_digest.clone()), "persona already minted");
        self.insert_token(&token_id, &owner_id, preset_id, persona_digest, metadata, false, 0);
        emit("nep171", "1.2.0", "nft_mint", json!({"owner_id": owner_id, "token_ids": [token_id]}));
        self.persona_view(&token_id)
    }

    /// Every ownership change by an owner or an approved account goes through here,
    /// so the sale-ready guard and the approval checks hold on every path.
    fn internal_transfer(
        &mut self,
        sender: &AccountId,
        receiver: &AccountId,
        token_id: &TokenId,
        approval_id: Option<u64>,
        memo: Option<String>,
        refund_approvals: bool,
    ) -> (AccountId, BTreeMap<AccountId, u64>) {
        let token = self.token(token_id);
        self.assert_transferable(&token);
        let authorized = if *sender != token.owner_id {
            let Some(id) = token.approvals.get(sender) else {
                env::panic_str("sender is not the owner or approved");
            };
            if let Some(want) = approval_id {
                require!(want == *id, "approval id does not match");
            }
            Some(sender.clone())
        } else {
            None
        };
        require!(token.owner_id != *receiver, "the token owner and the receiver should differ");
        require!(
            *receiver != self.custodian,
            "custody holds only the premint: a token can't be sent into it"
        );
        let previous = (token.owner_id.clone(), token.approvals.clone());
        let memo_ref = memo.as_deref();
        self.move_token(token_id, receiver, authorized.as_ref(), memo_ref, refund_approvals);
        previous
    }

    fn internal_transfer_unguarded(
        &mut self,
        token_id: &TokenId,
        receiver: &AccountId,
        authorized: Option<&AccountId>,
        memo: Option<&str>,
        refund_approvals: bool,
    ) {
        self.move_token(token_id, receiver, authorized, memo, refund_approvals);
    }

    /// A move clears the token's approvals; their storage, which the old owner
    /// paid, goes back to the old owner, except on the first leg of
    /// `nft_transfer_call`, where `nft_resolve_transfer` refunds it once the
    /// transfer stands.
    fn move_token(
        &mut self,
        token_id: &TokenId,
        receiver: &AccountId,
        authorized: Option<&AccountId>,
        memo: Option<&str>,
        refund_approvals: bool,
    ) {
        let mut token = self.token(token_id);
        let old_owner = token.owner_id.clone();
        if old_owner != *receiver {
            self.count_custody_move(token_id, &token, &old_owner);
        }
        token.exit_at_seq = 0;
        if refund_approvals {
            self.refund(&old_owner, approvals_bytes(&token.approvals) as u128 * env::storage_byte_cost().as_yoctonear());
        }
        self.owner_index_remove(&old_owner, token_id);
        self.owner_index_add(receiver, token_id);
        token.owner_id = receiver.clone();
        token.approvals.clear();
        self.tokens.insert(token_id.clone(), token);
        let mut data = json!({"old_owner_id": old_owner, "new_owner_id": receiver, "token_ids": [token_id]});
        if let Some(a) = authorized {
            data["authorized_id"] = json!(a);
        }
        if let Some(m) = memo {
            data["memo"] = json!(m);
        }
        emit("nep171", "1.2.0", "nft_transfer", data);
    }

    fn owner_index_add(&mut self, owner: &AccountId, token_id: &TokenId) {
        let mut ids = self.owners.get(owner).cloned().unwrap_or_default();
        ids.push(token_id.clone());
        self.owners.insert(owner.clone(), ids);
    }

    fn owner_index_remove(&mut self, owner: &AccountId, token_id: &TokenId) {
        let mut ids = self.owners.get(owner).cloned().unwrap_or_default();
        ids.retain(|id| id != token_id);
        if ids.is_empty() {
            self.owners.remove(owner);
        } else {
            self.owners.insert(owner.clone(), ids);
        }
    }

    fn store_and_refund(&mut self, token_id: TokenId, token: TokenState) {
        let owner = token.owner_id.clone();
        let before = env::storage_usage();
        self.tokens.insert(token_id, token);
        self.tokens.flush();
        let freed = before.saturating_sub(env::storage_usage()) as u128 * env::storage_byte_cost().as_yoctonear();
        if freed > 0 {
            let _ = Promise::new(owner).transfer(NearToken::from_yoctonear(freed));
        }
    }
}

#[cfg(test)]
mod tests;
