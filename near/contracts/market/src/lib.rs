//! `market`: the testnet stake ledger (F40, F76, F80; prd §4.3 "The stake ledger").
//!
//! Every amount is a `u128` of yoctoNEAR. Money enters only through the payable
//! `deposit` (a function-call key cannot attach a deposit, so only a full-access
//! key can pay in) and leaves only through `withdraw`, which asserts 1 yoctoNEAR
//! (so it too needs a full-access key), debits first and re-credits if the
//! transfer fails. `stake` moves ledger balance into an open stake for the
//! current stake batch; `resolve`, called only by the stake resolver, settles
//! that batch against the pot. `solvency()` checks
//! balance >= ledger + open stakes + pot + storage after every money method.
//!
//! Per-key daily limits bind zero-deposit `stake` calls, keyed by the signing
//! public key. A wallet-signed full-access call proves itself by attaching
//! exactly 1 yoctoNEAR, which a function-call key cannot do, and is not limited
//! (B107). The limit is read on the amount locked, which is the most a key can
//! lose in a day (prd §4.3: net-loss reading, INFERRED).

use near_sdk::json_types::{I128, U64, U128};
use near_sdk::store::LookupMap;
use near_sdk::{
    AccountId, BorshStorageKey, Gas, NearToken, PanicOnDefault, Promise, PromiseError, env, near,
    require,
};

/// 0.15 NEAR: the guest key's daily limit (decisions `:297`).
pub const GUEST_DAILY_LIMIT: u128 = 150_000_000_000_000_000_000_000;
/// Two hourly batches (prd §4.3 step 5, INFERRED).
pub const DEFAULT_STAKE_TIMEOUT_NS: u64 = 2 * 3_600 * 1_000_000_000;
const DAY_NS: u64 = 86_400 * 1_000_000_000;
const ONE_YOCTO: u128 = 1;
const GAS_FOR_WITHDRAW_CALLBACK: Gas = Gas::from_tgas(10);
const EVENT_STANDARD: &str = "trenchie_market";
const EVENT_VERSION: &str = "1.0.0";

#[derive(BorshStorageKey)]
#[near]
enum Key {
    Balances,
    Stakes,
    KeyUse,
    Batches,
}

#[near(serializers = [borsh, json])]
#[derive(Clone, Debug, PartialEq)]
pub struct Stake {
    pub amount: U128,
    pub batch: U64,
    pub locked_at: U64,
}

#[near(serializers = [borsh, json])]
#[derive(Clone, Debug, PartialEq)]
pub struct KeyUse {
    pub day: U64,
    pub used: U128,
}

#[near(serializers = [borsh, json])]
#[derive(Clone, Debug, PartialEq)]
pub struct BatchRecord {
    pub log_hash: String,
    pub results: u32,
    pub pot_after: U128,
    pub base_rate: [u16; 5],
    pub resolved_at: U64,
}

#[near(serializers = [json])]
#[derive(Clone, Debug)]
pub struct StakeResult {
    pub account_id: AccountId,
    /// Signed yoctoNEAR: the life results net of the stake, never below -stake.
    pub net: I128,
}

#[near(serializers = [json])]
#[derive(Debug, PartialEq)]
pub struct Solvency {
    pub balance: U128,
    pub ledger: U128,
    pub staked: U128,
    pub pot: U128,
    pub storage: U128,
    pub solvent: bool,
}

#[near(serializers = [json])]
#[derive(Debug, PartialEq)]
pub struct MarketState {
    pub owner: AccountId,
    pub resolver: AccountId,
    pub open_batch: U64,
    pub open_count: u32,
    pub pot: U128,
    pub base_rate: [u16; 5],
    pub daily_limit: U128,
    pub stake_timeout_ns: U64,
}

#[near(contract_state)]
#[derive(PanicOnDefault)]
pub struct Market {
    owner: AccountId,
    resolver: AccountId,
    balances: LookupMap<AccountId, u128>,
    stakes: LookupMap<AccountId, Stake>,
    key_use: LookupMap<String, KeyUse>,
    batches: LookupMap<u64, BatchRecord>,
    open_batch: u64,
    open_count: u32,
    total_ledger: u128,
    total_staked: u128,
    pot: u128,
    daily_limit: u128,
    stake_timeout_ns: u64,
    base_rate: [u16; 5],
}

fn emit(event: &str, data: near_sdk::serde_json::Value) {
    env::log_str(&format!(
        "EVENT_JSON:{}",
        near_sdk::serde_json::json!({
            "standard": EVENT_STANDARD,
            "version": EVENT_VERSION,
            "event": event,
            "data": [data],
        })
    ));
}

fn is_hex64(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}

#[near]
impl Market {
    /// `base_rate`: the published spread in basis points over 0, 1, 2, 3, 4+ KOs.
    #[init]
    pub fn new(
        owner: AccountId,
        resolver: AccountId,
        daily_limit: Option<U128>,
        stake_timeout_ns: Option<U64>,
        base_rate: [u16; 5],
    ) -> Self {
        require!(
            base_rate.iter().map(|v| *v as u32).sum::<u32>() == 10_000,
            "base_rate must sum to 10000 basis points"
        );
        Self {
            owner,
            resolver,
            balances: LookupMap::new(Key::Balances),
            stakes: LookupMap::new(Key::Stakes),
            key_use: LookupMap::new(Key::KeyUse),
            batches: LookupMap::new(Key::Batches),
            open_batch: 0,
            open_count: 0,
            total_ledger: 0,
            total_staked: 0,
            pot: 0,
            daily_limit: daily_limit.map(|v| v.0).unwrap_or(GUEST_DAILY_LIMIT),
            stake_timeout_ns: stake_timeout_ns.map(|v| v.0).unwrap_or(DEFAULT_STAKE_TIMEOUT_NS),
            base_rate,
        }
    }

    // ---------------------------------------------------------------- money in

    /// Native NEAR into the ledger. The first deposit pays its own record's storage.
    #[payable]
    pub fn deposit(&mut self) -> U128 {
        let account = env::predecessor_account_id();
        let attached = env::attached_deposit().as_yoctonear();
        require!(attached > 0, "deposit needs attached NEAR");
        let before = env::storage_usage();
        let is_new = !self.balances.contains_key(&account);
        let current = self.balances.get(&account).copied().unwrap_or(0);
        self.balances.insert(account.clone(), current);
        self.balances.flush();
        let fee = self.storage_cost_since(before);
        if is_new {
            require!(attached > fee, "first deposit must cover its storage fee");
        }
        let credit = attached - fee;
        let balance = current + credit;
        self.balances.insert(account.clone(), balance);
        self.total_ledger += credit;
        emit(
            "deposit",
            near_sdk::serde_json::json!({
                "account_id": account, "amount": U128(attached), "storage_fee": U128(fee),
                "balance": U128(balance),
            }),
        );
        self.assert_solvent();
        U128(balance)
    }

    // --------------------------------------------------------------- staking

    /// Lock `amount` from the ledger for the open stake batch.
    /// Zero deposit: the signing key's daily limit applies.
    /// Exactly 1 yoctoNEAR attached: a full-access call, not limited (B107).
    #[payable]
    pub fn stake(&mut self, amount: U128) -> Stake {
        let account = env::predecessor_account_id();
        require!(account == env::signer_account_id(), "stake must be signed by the staking account");
        let attached = env::attached_deposit().as_yoctonear();
        require!(
            attached == 0 || attached == ONE_YOCTO,
            "stake takes no deposit, or exactly 1 yoctoNEAR from a full-access key"
        );
        let amount = amount.0;
        require!(amount > 0, "stake amount must be positive");
        let mut balance = self.balances.get(&account).copied().unwrap_or_else(|| {
            env::panic_str("no ledger balance: deposit first")
        });
        balance += attached;
        self.total_ledger += attached;
        let before = env::storage_usage();
        if attached == 0 {
            let key = format!("{}:{}", account, String::from(&env::signer_account_pk()));
            let day = env::block_timestamp() / DAY_NS;
            let mut usage = self
                .key_use
                .get(&key)
                .cloned()
                .unwrap_or(KeyUse { day: U64(day), used: U128(0) });
            if usage.day.0 != day {
                usage = KeyUse { day: U64(day), used: U128(0) };
            }
            let used = usage.used.0 + amount;
            require!(used <= self.daily_limit, "daily limit for this key reached");
            usage.used = U128(used);
            self.key_use.insert(key, usage);
        }
        let stake = match self.stakes.get(&account).cloned() {
            Some(open) => {
                require!(
                    open.batch.0 == self.open_batch,
                    "previous stake unresolved: wait for its resolve or refund"
                );
                Stake { amount: U128(open.amount.0 + amount), batch: open.batch, locked_at: open.locked_at }
            }
            None => {
                self.open_count += 1;
                Stake { amount: U128(amount), batch: U64(self.open_batch), locked_at: U64(env::block_timestamp()) }
            }
        };
        self.stakes.insert(account.clone(), stake.clone());
        self.stakes.flush();
        self.key_use.flush();
        let fee = self.storage_cost_since(before);
        require!(balance >= amount + fee, "ledger balance too low for this stake");
        balance -= amount + fee;
        self.balances.insert(account.clone(), balance);
        self.total_ledger -= amount + fee;
        self.total_staked += amount;
        emit(
            "stake",
            near_sdk::serde_json::json!({
                "account_id": account, "amount": U128(amount), "batch": stake.batch,
                "limited": attached == 0, "storage_fee": U128(fee),
            }),
        );
        self.assert_solvent();
        stake
    }

    /// The stake resolver posts one stake batch (F80). `market` can't check the
    /// numbers; it checks they conserve: every open stake of the batch gets one
    /// result, no stake loses more than itself, and stakes plus pot sum to zero.
    pub fn resolve(
        &mut self,
        batch: U64,
        results: Vec<StakeResult>,
        pot_delta: I128,
        base_rate: [u16; 5],
        log_hash: String,
    ) -> BatchRecord {
        require!(env::predecessor_account_id() == self.resolver, "only the stake resolver may resolve");
        require!(batch.0 == self.open_batch, "batch is not the open stake batch");
        require!(results.len() as u32 == self.open_count, "every open stake needs exactly one result");
        require!(
            base_rate.iter().map(|v| *v as u32).sum::<u32>() == 10_000,
            "base_rate must sum to 10000 basis points"
        );
        require!(is_hex64(&log_hash), "log_hash must be 64 lowercase hex characters");
        let mut net_sum: i128 = 0;
        for result in &results {
            let stake = self
                .stakes
                .remove(&result.account_id)
                .unwrap_or_else(|| env::panic_str("result for an account with no open stake"));
            require!(stake.batch.0 == self.open_batch, "result for a stake of another batch");
            let amount = stake.amount.0 as i128;
            let net = result.net.0;
            require!(net >= -amount, "a stake cannot lose more than itself");
            let returned = (amount + net) as u128;
            let balance = self.balances.get(&result.account_id).copied().unwrap_or(0) + returned;
            self.balances.insert(result.account_id.clone(), balance);
            self.total_staked -= stake.amount.0;
            self.total_ledger += returned;
            net_sum += net;
        }
        require!(net_sum + pot_delta.0 == 0, "stakes and pot must sum to zero");
        let pot = self.pot as i128 + pot_delta.0;
        require!(pot >= 0, "the pot cannot go below zero");
        self.pot = pot as u128;
        self.base_rate = base_rate;
        let record = BatchRecord {
            log_hash,
            results: results.len() as u32,
            pot_after: U128(self.pot),
            base_rate,
            resolved_at: U64(env::block_timestamp()),
        };
        self.batches.insert(self.open_batch, record.clone());
        emit(
            "resolve",
            near_sdk::serde_json::json!({
                "batch": U64(self.open_batch), "results": record.results, "pot_delta": pot_delta,
                "pot_after": record.pot_after, "log_hash": record.log_hash,
            }),
        );
        self.open_batch += 1;
        self.open_count = 0;
        self.assert_solvent();
        record
    }

    /// Anyone may refund a stake whose result never came within the timeout
    /// (two batches, INFERRED). The refund is logged so the page can say so.
    pub fn refund_stake(&mut self, account_id: AccountId) -> U128 {
        let stake = self
            .stakes
            .get(&account_id)
            .cloned()
            .unwrap_or_else(|| env::panic_str("no open stake"));
        require!(
            env::block_timestamp() >= stake.locked_at.0 + self.stake_timeout_ns,
            "stake has not timed out"
        );
        self.stakes.remove(&account_id);
        if stake.batch.0 == self.open_batch {
            self.open_count -= 1;
        }
        let balance = self.balances.get(&account_id).copied().unwrap_or(0) + stake.amount.0;
        self.balances.insert(account_id.clone(), balance);
        self.total_staked -= stake.amount.0;
        self.total_ledger += stake.amount.0;
        emit(
            "stake_refund",
            near_sdk::serde_json::json!({
                "account_id": account_id, "amount": stake.amount, "batch": stake.batch,
                "reason": "no result within the timeout",
            }),
        );
        self.assert_solvent();
        stake.amount
    }

    // -------------------------------------------------------------- money out

    /// Native NEAR out. Full-access only (1 yoctoNEAR). Debit first; the callback
    /// re-credits if the transfer fails.
    #[payable]
    pub fn withdraw(&mut self, amount: U128) -> Promise {
        require!(
            env::attached_deposit().as_yoctonear() == ONE_YOCTO,
            "Requires attached deposit of exactly 1 yoctoNEAR"
        );
        let account = env::predecessor_account_id();
        let amount = amount.0;
        require!(amount > 0, "withdraw amount must be positive");
        let balance = self.balances.get(&account).copied().unwrap_or(0);
        require!(balance >= amount, "ledger balance too low");
        self.balances.insert(account.clone(), balance - amount);
        self.total_ledger -= amount;
        // The 1 yoctoNEAR stays with the contract as surplus, so solvency only grows.
        emit(
            "withdraw",
            near_sdk::serde_json::json!({"account_id": account, "amount": U128(amount)}),
        );
        Promise::new(account.clone()).transfer(NearToken::from_yoctonear(amount)).then(
            Self::ext(env::current_account_id())
                .with_static_gas(GAS_FOR_WITHDRAW_CALLBACK)
                .on_withdraw(account, U128(amount)),
        )
    }

    #[private]
    pub fn on_withdraw(
        &mut self,
        account_id: AccountId,
        amount: U128,
        #[callback_result] result: Result<(), PromiseError>,
    ) -> bool {
        if result.is_ok() {
            return true;
        }
        let balance = self.balances.get(&account_id).copied().unwrap_or(0) + amount.0;
        self.balances.insert(account_id.clone(), balance);
        self.total_ledger += amount.0;
        emit(
            "withdraw_failed",
            near_sdk::serde_json::json!({"account_id": account_id, "amount": amount, "recredited": true}),
        );
        false
    }

    // ------------------------------------------------------------------ owner

    #[payable]
    pub fn set_resolver(&mut self, resolver: AccountId) {
        self.assert_owner();
        self.resolver = resolver;
    }

    #[payable]
    pub fn set_daily_limit(&mut self, daily_limit: U128) {
        self.assert_owner();
        self.daily_limit = daily_limit.0;
    }

    // ------------------------------------------------------------------ views

    pub fn solvency(&self) -> Solvency {
        let balance = env::account_balance().as_yoctonear();
        let storage = env::storage_usage() as u128 * env::storage_byte_cost().as_yoctonear();
        let owed = self.total_ledger + self.total_staked + self.pot + storage;
        Solvency {
            balance: U128(balance),
            ledger: U128(self.total_ledger),
            staked: U128(self.total_staked),
            pot: U128(self.pot),
            storage: U128(storage),
            solvent: balance >= owed,
        }
    }

    pub fn balance_of(&self, account_id: AccountId) -> U128 {
        U128(self.balances.get(&account_id).copied().unwrap_or(0))
    }

    pub fn stake_of(&self, account_id: AccountId) -> Option<Stake> {
        self.stakes.get(&account_id).cloned()
    }

    pub fn key_use(&self, account_id: AccountId, public_key: String) -> Option<KeyUse> {
        self.key_use.get(&format!("{}:{}", account_id, public_key)).cloned()
    }

    pub fn batch(&self, batch: U64) -> Option<BatchRecord> {
        self.batches.get(&batch.0).cloned()
    }

    pub fn state(&self) -> MarketState {
        MarketState {
            owner: self.owner.clone(),
            resolver: self.resolver.clone(),
            open_batch: U64(self.open_batch),
            open_count: self.open_count,
            pot: U128(self.pot),
            base_rate: self.base_rate,
            daily_limit: U128(self.daily_limit),
            stake_timeout_ns: U64(self.stake_timeout_ns),
        }
    }
}

impl Market {
    fn assert_owner(&self) {
        require!(env::attached_deposit().as_yoctonear() == ONE_YOCTO, "Requires attached deposit of exactly 1 yoctoNEAR");
        require!(env::predecessor_account_id() == self.owner, "owner only");
    }

    fn storage_cost_since(&self, before: u64) -> u128 {
        let after = env::storage_usage();
        after.saturating_sub(before) as u128 * env::storage_byte_cost().as_yoctonear()
    }

    fn assert_solvent(&mut self) {
        self.balances.flush();
        self.stakes.flush();
        self.key_use.flush();
        self.batches.flush();
        require!(self.solvency().solvent, "insolvent: balance below ledger + stakes + pot + storage");
    }
}

#[cfg(test)]
mod tests;
