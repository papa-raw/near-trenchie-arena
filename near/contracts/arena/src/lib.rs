//! `arena`: operator-only fight records (F5, C2, C5, C6, F84; prd §4.3).
//!
//! - No user methods (C2): joins and intents are signed server inputs. Every
//!   write is the arena operator's; the owner may only rotate the operator.
//! - `commit_seeds` (C6): one transaction fixes a batch of seeds,
//!   seed_i = sha256(operator secret ‖ the block's random seed ‖ u32be(i)), all
//!   published in that transaction's event and return value (B79, B103).
//! - `post_batch` (F84): stores the slim fight record (the hash of the segment
//!   list, KOs, the rows' digest, the MANIFEST flag), then calls
//!   `trenchie_nft.apply_rows`. If the hop fails the record stands as pending;
//!   a retry with the same batch id and the same content re-sends only the hop,
//!   and `trenchie_nft` applies a batch id once.
//! - Records are slim; MANIFEST-flagged records are never pruned; others are
//!   pruned past `keep_records` (300, decisions `:300`) (C5).

use near_sdk::json_types::U64;
use near_sdk::serde_json::{self, json};
use near_sdk::store::{LookupMap, LookupSet};
use near_sdk::{
    AccountId, BorshStorageKey, Gas, PanicOnDefault, Promise, PromiseError, env, ext_contract, near,
    require,
};
pub use trenchie_rows::{Entry, Record, Row};

pub const KEEP_RECORDS: u32 = 300;
pub const MAX_SEEDS_PER_COMMIT: u16 = 1_440;
/// Seeds listed in full in the commit's event; more than this and the event
/// carries the inputs only (a log line is capped at 16 KB).
pub const SEEDS_IN_EVENT: u16 = 120;
const GAS_FOR_ON_APPLY: Gas = Gas::from_tgas(10);
const ONE_YOCTO: u128 = 1;

#[derive(BorshStorageKey)]
#[near]
enum Key {
    Batches,
    Queue,
    Commits,
    Secrets,
}

/// One 60 s segment's hashes, as the room's sealed result carries them.
#[near(serializers = [borsh, json])]
#[derive(Clone, Debug, PartialEq)]
pub struct Segment {
    pub segment_id: String,
    /// The committed seed this segment ran on: `commit_id`'s seed `seed_index`.
    /// Seeds are consumed one each, strictly in commit order (critic M2).
    pub commit_id: U64,
    pub seed_index: u16,
    pub seed_hash: String,
    pub inputs_hash: String,
    pub rules_hash: String,
    pub final_state_hash: String,
    pub predictions_log_hash: String,
    pub kos: u32,
}

#[near(serializers = [borsh, json])]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Status {
    Pending,
    Applied,
}

#[near(serializers = [borsh, json])]
#[derive(Clone, Debug, PartialEq)]
pub struct BatchRecord {
    pub fight_hash: String,
    pub segments: u32,
    pub kos: u32,
    pub rows: u32,
    pub rows_digest: String,
    pub manifest: bool,
    pub status: Status,
    pub hops: u32,
    pub posted_at: U64,
}

#[near(serializers = [borsh, json])]
#[derive(Clone, Debug, PartialEq)]
pub struct Commit {
    pub commit_id: U64,
    pub block_height: U64,
    pub random_seed: String,
    pub secret: String,
    pub count: u16,
}

#[near(serializers = [json])]
#[derive(Debug, PartialEq)]
pub struct ArenaState {
    pub owner: AccountId,
    pub operator: AccountId,
    pub nft: AccountId,
    pub keep_records: u32,
    pub kept_non_manifest: U64,
    pub manifest_records: U64,
    pub commits: U64,
    /// The next seed a posted segment must use.
    pub next_seed: SeedRef,
}

#[near(serializers = [json])]
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SeedRef {
    pub commit_id: U64,
    pub seed_index: u16,
}

/// One committed seed in the forms the room uses: the 32 bytes, the u64 the
/// sim runs on (first 8 bytes, big-endian), and the sealed record's seed_hash
/// (sha256 of the canonical JSON string of that u64, quotes included).
#[near(serializers = [json])]
#[derive(Clone, Debug, PartialEq)]
pub struct SeedView {
    pub seed: String,
    pub seed_u64: U64,
    pub seed_hash: String,
}

#[ext_contract(ext_nft)]
pub trait TrenchieNftRows {
    fn apply_rows(&mut self, batch_id: String, rows: Vec<Row>);
}

#[near(contract_state)]
#[derive(PanicOnDefault)]
pub struct Arena {
    owner: AccountId,
    operator: AccountId,
    nft: AccountId,
    keep_records: u32,
    batches: LookupMap<String, BatchRecord>,
    queue: LookupMap<u64, String>,
    queue_head: u64,
    queue_tail: u64,
    manifest_records: u64,
    commits: LookupMap<u64, Commit>,
    next_commit: u64,
    secrets: LookupSet<String>,
    seed_commit: u64,
    seed_index: u16,
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn is_hex64(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

fn is_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_' || b == b'.')
}

fn from_hex32(value: &str) -> [u8; 32] {
    require!(is_hex64(value), "secret must be 64 lowercase hex characters");
    let mut out = [0u8; 32];
    for (i, chunk) in value.as_bytes().chunks(2).enumerate() {
        out[i] = u8::from_str_radix(std::str::from_utf8(chunk).unwrap(), 16).unwrap();
    }
    out
}

/// seed_i = sha256(secret ‖ random_seed ‖ u32be(i)).
pub fn derive_seed(secret: &[u8; 32], random_seed: &[u8; 32], i: u32) -> [u8; 32] {
    let mut msg = Vec::with_capacity(68);
    msg.extend_from_slice(secret);
    msg.extend_from_slice(random_seed);
    msg.extend_from_slice(&i.to_be_bytes());
    env::sha256_array(&msg)
}

/// The u64 the sim runs on: the seed's first 8 bytes, big-endian.
pub fn seed_u64(seed: &[u8; 32]) -> u64 {
    u64::from_be_bytes(seed[..8].try_into().unwrap())
}

/// The sealed record's seed_hash: sha256 of the canonical JSON string of the
/// u64 seed, quotes included (agreed with the room, board 02:35).
pub fn seed_hash(value: u64) -> String {
    hex(&env::sha256_array(format!("\"{value}\"").as_bytes()))
}

fn emit(event: &str, data: serde_json::Value) {
    env::log_str(&format!(
        "EVENT_JSON:{}",
        json!({"standard": "trenchie_arena", "version": "1.0.0", "event": event, "data": [data]})
    ));
}

#[near]
impl Arena {
    #[init]
    pub fn new(owner: AccountId, operator: AccountId, nft: AccountId, keep_records: Option<u32>) -> Self {
        let keep_records = keep_records.unwrap_or(KEEP_RECORDS);
        require!(keep_records > 0, "keep_records must be positive");
        Self {
            owner,
            operator,
            nft,
            keep_records,
            batches: LookupMap::new(Key::Batches),
            queue: LookupMap::new(Key::Queue),
            queue_head: 0,
            queue_tail: 0,
            manifest_records: 0,
            commits: LookupMap::new(Key::Commits),
            next_commit: 0,
            secrets: LookupSet::new(Key::Secrets),
            seed_commit: 0,
            seed_index: 0,
        }
    }

    /// Fix the next `count` seeds from a secret and this block's random seed.
    /// Nothing is drawn from them in this call.
    pub fn commit_seeds(&mut self, secret: String, count: u16) -> Vec<String> {
        self.assert_operator();
        require!(count >= 1 && count <= MAX_SEEDS_PER_COMMIT, "count must be 1 to 1440");
        let secret_bytes = from_hex32(&secret);
        require!(self.secrets.insert(secret.clone()), "secret already committed");
        let random = env::random_seed_array();
        let seeds: Vec<String> = (0..count as u32).map(|i| hex(&derive_seed(&secret_bytes, &random, i))).collect();
        let commit = Commit {
            commit_id: U64(self.next_commit),
            block_height: U64(env::block_height()),
            random_seed: hex(&random),
            secret,
            count,
        };
        let mut data = json!(commit);
        if count <= SEEDS_IN_EVENT {
            data["seeds"] = json!(seeds);
        }
        emit("commit_seeds", data);
        self.commits.insert(self.next_commit, commit);
        self.next_commit += 1;
        seeds
    }

    /// Store the batch's fight record, then hop to `trenchie_nft.apply_rows`.
    pub fn post_batch(&mut self, batch_id: String, segments: Vec<Segment>, rows: Vec<Row>, manifest: bool) -> Option<Promise> {
        self.assert_operator();
        require!(is_id(&batch_id), "invalid batch id");
        require!(!segments.is_empty(), "a batch has at least one segment");
        for s in &segments {
            require!(is_id(&s.segment_id), "invalid segment id");
            for h in [&s.seed_hash, &s.inputs_hash, &s.rules_hash, &s.final_state_hash, &s.predictions_log_hash] {
                require!(is_hex64(h), "segment hashes must be 64 lowercase hex characters");
            }
        }
        let fight_hash = hex(&env::sha256_array(&near_sdk::borsh::to_vec(&segments).unwrap()));
        let rows_digest = hex(&env::sha256_array(&near_sdk::borsh::to_vec(&rows).unwrap()));
        let kos = segments.iter().map(|s| s.kos).sum();
        let mut record = match self.batches.get(&batch_id).cloned() {
            Some(existing) => {
                require!(
                    existing.fight_hash == fight_hash
                        && existing.rows_digest == rows_digest
                        && existing.manifest == manifest,
                    "batch id reused with different content"
                );
                if existing.status == Status::Applied {
                    emit("post_batch", json!({"batch_id": batch_id, "already_applied": true}));
                    return None;
                }
                existing
            }
            None => {
                // Bind every segment to the next committed seed, one use each,
                // in commit order, so the operator can't choose among seeds (M2).
                for s in &segments {
                    require!(
                        s.commit_id.0 == self.seed_commit && s.seed_index == self.seed_index,
                        "a segment must use the next committed seed, in order"
                    );
                    let count = self
                        .commits
                        .get(&self.seed_commit)
                        .map(|c| c.count)
                        .unwrap_or_else(|| env::panic_str("the next committed seed is not committed yet"));
                    let value = seed_u64(&self.seed_bytes(self.seed_commit, self.seed_index));
                    require!(s.seed_hash == seed_hash(value), "seed_hash is not the committed seed's");
                    if self.seed_index + 1 == count {
                        self.seed_commit += 1;
                        self.seed_index = 0;
                    } else {
                        self.seed_index += 1;
                    }
                }
                let record = BatchRecord {
                    fight_hash,
                    segments: segments.len() as u32,
                    kos,
                    rows: rows.len() as u32,
                    rows_digest,
                    manifest,
                    status: Status::Pending,
                    hops: 0,
                    posted_at: U64(env::block_timestamp()),
                };
                self.remember(&batch_id, manifest);
                record
            }
        };
        record.hops += 1;
        emit(
            "post_batch",
            json!({"batch_id": batch_id, "fight_hash": record.fight_hash, "segments": record.segments,
                   "kos": record.kos, "rows": record.rows, "manifest": manifest, "hop": record.hops}),
        );
        self.batches.insert(batch_id.clone(), record);
        Some(
            ext_nft::ext(self.nft.clone())
                .with_static_gas(Gas::from_tgas(0))
                .with_unused_gas_weight(1)
                .apply_rows(batch_id.clone(), rows)
                .then(
                    Self::ext(env::current_account_id())
                        .with_static_gas(GAS_FOR_ON_APPLY)
                        .with_unused_gas_weight(0)
                        .on_apply(batch_id),
                ),
        )
    }

    /// The hop's result: applied, or pending for a retry with the same batch id.
    #[private]
    pub fn on_apply(&mut self, batch_id: String, #[callback_result] result: Result<serde_json::Value, PromiseError>) -> bool {
        let applied = result.is_ok();
        if let Some(mut record) = self.batches.get(&batch_id).cloned() {
            if applied {
                record.status = Status::Applied;
                self.batches.insert(batch_id.clone(), record);
            }
        }
        emit(
            "apply_result",
            json!({"batch_id": batch_id, "status": if applied { "applied" } else { "pending" }}),
        );
        applied
    }

    #[payable]
    pub fn set_operator(&mut self, operator: AccountId) {
        require!(env::attached_deposit().as_yoctonear() == ONE_YOCTO, "Requires attached deposit of exactly 1 yoctoNEAR");
        require!(env::predecessor_account_id() == self.owner, "owner only");
        self.operator = operator;
    }

    // ------------------------------------------------------------------ views

    pub fn get_batch(&self, batch_id: String) -> Option<BatchRecord> {
        self.batches.get(&batch_id).cloned()
    }

    pub fn get_commit(&self, commit_id: U64) -> Option<Commit> {
        self.commits.get(&commit_id.0).cloned()
    }

    pub fn seed(&self, commit_id: U64, index: u16) -> String {
        hex(&self.seed_bytes(commit_id.0, index))
    }

    pub fn seed_record(&self, commit_id: U64, index: u16) -> SeedView {
        let bytes = self.seed_bytes(commit_id.0, index);
        let value = seed_u64(&bytes);
        SeedView { seed: hex(&bytes), seed_u64: U64(value), seed_hash: seed_hash(value) }
    }

    pub fn state(&self) -> ArenaState {
        ArenaState {
            owner: self.owner.clone(),
            operator: self.operator.clone(),
            nft: self.nft.clone(),
            keep_records: self.keep_records,
            kept_non_manifest: U64(self.queue_tail - self.queue_head),
            manifest_records: U64(self.manifest_records),
            commits: U64(self.next_commit),
            next_seed: SeedRef { commit_id: U64(self.seed_commit), seed_index: self.seed_index },
        }
    }
}

impl Arena {
    fn seed_bytes(&self, commit_id: u64, index: u16) -> [u8; 32] {
        let commit = self.commits.get(&commit_id).unwrap_or_else(|| env::panic_str("no such commit"));
        require!(index < commit.count, "index past the commit's count");
        derive_seed(&from_hex32(&commit.secret), &from_hex32(&commit.random_seed), index as u32)
    }

    fn assert_operator(&self) {
        require!(env::predecessor_account_id() == self.operator, "only the arena operator may write");
    }

    /// Track a new record; prune the oldest non-MANIFEST ones past `keep_records`.
    fn remember(&mut self, batch_id: &str, manifest: bool) {
        if manifest {
            self.manifest_records += 1;
            return;
        }
        self.queue.insert(self.queue_tail, batch_id.to_string());
        self.queue_tail += 1;
        while self.queue_tail - self.queue_head > self.keep_records as u64 {
            if let Some(old) = self.queue.remove(&self.queue_head) {
                self.batches.remove(&old);
                emit("prune", json!({"batch_id": old}));
            }
            self.queue_head += 1;
        }
    }
}

#[cfg(test)]
mod tests;
