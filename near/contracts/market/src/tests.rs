use super::*;
use near_sdk::test_utils::{VMContextBuilder, get_logs};
use near_sdk::{PromiseResult, PublicKey, RuntimeFeesConfig, test_vm_config, testing_env};

const NEAR: u128 = 1_000_000_000_000_000_000_000_000;
const STAKE: u128 = NEAR / 100; // 0.01 NEAR a life
const T0: u64 = 1_800_000_000_000_000_000;

fn acc(name: &str) -> AccountId {
    name.parse().unwrap()
}

fn fc_key() -> PublicKey {
    "ed25519:6E8sCci9badyRkXb3JoRpBj5p8C6Tw41ELDZoiihKEtp".parse().unwrap()
}

fn other_key() -> PublicKey {
    "ed25519:DcA2MzgpJbrUATQLLceocVckhhAqrkingax4oJ9kZ847".parse().unwrap()
}

struct Env {
    balance: u128,
    now: u64,
    ctx: Option<near_sdk::VMContext>,
}

/// Run a call that must be refused on a scratch copy of the mocked storage, then
/// restore it: a panic unwinds through store collections, whose Drop flushes.
fn probe<R>(e: &Env, f: impl FnOnce() -> R) -> Result<R, String> {
    let snap = near_sdk::mock::with_mocked_blockchain(|b| b.take_storage());
    let install = |storage| {
        near_sdk::env::set_blockchain_interface(near_sdk::MockedBlockchain::new(
            e.ctx.clone().unwrap(),
            test_vm_config(),
            RuntimeFeesConfig::test(),
            vec![],
            storage,
            Default::default(),
            None,
        ))
    };
    install(snap.clone());
    let out = std::panic::catch_unwind(std::panic::AssertUnwindSafe(f));
    install(snap);
    out.map_err(|err| {
        err.downcast_ref::<String>()
            .cloned()
            .or_else(|| err.downcast_ref::<&str>().map(|s| s.to_string()))
            .unwrap_or_default()
    })
}

impl Env {
    fn call(&mut self, who: &str, deposit: u128, key: PublicKey) {
        self.balance += deposit;
        let ctx = VMContextBuilder::new()
            .current_account_id(acc("market.testnet"))
            .predecessor_account_id(acc(who))
            .signer_account_id(acc(who))
            .signer_account_pk(key)
            .attached_deposit(NearToken::from_yoctonear(deposit))
            .account_balance(NearToken::from_yoctonear(self.balance))
            .block_timestamp(self.now)
            .build();
        self.ctx = Some(ctx.clone());
        testing_env!(ctx);
    }
}

fn setup() -> (Market, Env) {
    let mut env = Env { balance: 5 * NEAR, now: T0, ctx: None };
    env.call("owner.testnet", 0, fc_key());
    let market = Market::new(
        acc("owner.testnet"),
        acc("resolver.testnet"),
        None,
        None,
        [4010, 3470, 1570, 640, 310],
    );
    (market, env)
}

fn funded(m: &mut Market, e: &mut Env, who: &str, amount: u128) {
    e.call(who, amount, other_key());
    m.deposit();
}

#[test]
fn deposit_charges_storage_once_and_stays_solvent() {
    let (mut m, mut e) = setup();
    e.call("alice.testnet", NEAR, other_key());
    let first = m.deposit().0;
    assert!(first < NEAR && first > NEAR - NEAR / 100, "storage fee is small: {first}");
    assert!(m.solvency().solvent);
    e.call("alice.testnet", NEAR, other_key());
    assert_eq!(m.deposit().0, first + NEAR, "second deposit pays no fee");
    assert!(m.solvency().solvent);
}

#[test]
#[should_panic(expected = "deposit needs attached NEAR")]
fn deposit_without_near_refused() {
    let (mut m, mut e) = setup();
    e.call("alice.testnet", 0, other_key());
    m.deposit();
}

#[test]
fn zero_deposit_stake_through_a_key_then_daily_limit() {
    let (mut m, mut e) = setup();
    funded(&mut m, &mut e, "alice.testnet", NEAR);
    // 15 lives at 0.01 = 0.15 NEAR: exactly the guest limit.
    for _ in 0..15 {
        e.call("alice.testnet", 0, fc_key());
        m.stake(U128(STAKE));
        assert!(m.solvency().solvent);
    }
    let usage = m.key_use(acc("alice.testnet"), String::from(&fc_key())).unwrap();
    assert_eq!(usage.used.0, GUEST_DAILY_LIMIT);
    assert_eq!(m.stake_of(acc("alice.testnet")).unwrap().amount.0, 15 * STAKE);
    // The 16th on the same key, same day, is refused.
    e.call("alice.testnet", 0, fc_key());
    let refused = probe(&e, || clone_market(&m).stake(U128(STAKE)));
    assert!(refused.unwrap_err().contains("daily limit"));
    // Next UTC day the key may stake again.
    e.now += DAY_NS;
    e.call("alice.testnet", 0, fc_key());
    m.stake(U128(STAKE));
    assert_eq!(m.key_use(acc("alice.testnet"), String::from(&fc_key())).unwrap().used.0, STAKE);
}

#[test]
#[should_panic(expected = "daily limit for this key reached")]
fn over_limit_stake_refused() {
    let (mut m, mut e) = setup();
    funded(&mut m, &mut e, "alice.testnet", NEAR);
    e.call("alice.testnet", 0, fc_key());
    m.stake(U128(GUEST_DAILY_LIMIT + 1));
}

#[test]
fn full_access_stake_with_one_yocto_is_not_limited() {
    let (mut m, mut e) = setup();
    funded(&mut m, &mut e, "alice.testnet", NEAR);
    e.call("alice.testnet", 1, other_key());
    let stake = m.stake(U128(GUEST_DAILY_LIMIT * 2));
    assert_eq!(stake.amount.0, GUEST_DAILY_LIMIT * 2);
    assert!(m.key_use(acc("alice.testnet"), String::from(&other_key())).is_none());
    assert!(m.solvency().solvent);
}

#[test]
#[should_panic(expected = "stake takes no deposit, or exactly 1 yoctoNEAR")]
fn stake_with_other_deposit_refused() {
    let (mut m, mut e) = setup();
    funded(&mut m, &mut e, "alice.testnet", NEAR);
    e.call("alice.testnet", 2, other_key());
    m.stake(U128(STAKE));
}

#[test]
#[should_panic(expected = "ledger balance too low for this stake")]
fn stake_over_balance_refused() {
    let (mut m, mut e) = setup();
    funded(&mut m, &mut e, "alice.testnet", STAKE * 2);
    e.call("alice.testnet", 1, other_key());
    m.stake(U128(STAKE * 3));
}

/// F76: one batch resolves, the pot balances, solvency() true.
#[test]
fn one_batch_resolves_and_the_pot_balances() {
    let (mut m, mut e) = setup();
    for who in ["alice.testnet", "bob.testnet", "carol.testnet"] {
        funded(&mut m, &mut e, who, NEAR);
        e.call(who, 0, fc_key());
        m.stake(U128(10 * STAKE));
    }
    // Each balance as it was, plus its stake record's storage, which comes back at resolve.
    let before: Vec<u128> = ["alice.testnet", "bob.testnet", "carol.testnet"]
        .iter()
        .map(|a| m.balance_of(acc(a)).0 + m.stake_of(acc(a)).unwrap().storage_fee.0)
        .collect();
    // Bob loses 3 zero-KO lives whole (0.03) to the pot; alice and carol are paid 0.02 + 0.01 from it.
    let results = vec![
        StakeResult { account_id: acc("alice.testnet"), net: I128(2 * STAKE as i128) },
        StakeResult { account_id: acc("bob.testnet"), net: I128(-(3 * STAKE as i128)) },
        StakeResult { account_id: acc("carol.testnet"), net: I128(STAKE as i128) },
    ];
    e.call("resolver.testnet", 0, fc_key());
    m.close_batch();
    let rec = m.resolve(U64(0), results, I128(0), [4000, 3500, 1500, 700, 300], "ab".repeat(32));
    assert_eq!(rec.results, 3);
    assert_eq!(rec.pot_after.0, 0);
    assert_eq!(m.balance_of(acc("alice.testnet")).0, before[0] + 12 * STAKE);
    assert_eq!(m.balance_of(acc("bob.testnet")).0, before[1] + 7 * STAKE);
    assert_eq!(m.balance_of(acc("carol.testnet")).0, before[2] + 11 * STAKE);
    assert!(m.stake_of(acc("alice.testnet")).is_none());
    assert_eq!(m.state().open_batch.0, 1);
    assert_eq!(m.state().base_rate, [4000, 3500, 1500, 700, 300]);
    let s = m.solvency();
    assert!(s.solvent);
    assert_eq!(s.staked.0, 0);
    assert!(get_logs().iter().any(|l| l.contains("\"event\":\"resolve\"")));
    // Batch 1: a 0-KO stake is lost whole to the pot, which rolls over.
    e.call("bob.testnet", 0, fc_key());
    m.stake(U128(STAKE));
    e.call("resolver.testnet", 0, fc_key());
    m.close_batch();
    let rec = m.resolve(
        U64(1),
        vec![StakeResult { account_id: acc("bob.testnet"), net: I128(-(STAKE as i128)) }],
        I128(STAKE as i128),
        [4000, 3500, 1500, 700, 300],
        "cd".repeat(32),
    );
    assert_eq!(rec.pot_after.0, STAKE);
    assert!(m.solvency().solvent);
}

fn resolve_panics(m: &Market, e: &mut Env, who: &str, batch: u64, results: Vec<StakeResult>, pot: i128) -> String {
    // The resolver closed the open batch first (in-memory, as close_batch does).
    let mut c = clone_market(m);
    if c.closed.is_none() {
        c.closed = Some(Closed { batch: U64(c.open_batch), stakes: c.open_count, opened_at: U64(c.batch_opened_at) });
        c.open_batch += 1;
        c.open_count = 0;
    }
    e.call(who, 0, fc_key());
    probe(e, move || c.resolve(U64(batch), results, I128(pot), [4000, 3500, 1500, 700, 300], "ef".repeat(32)))
    .expect_err("resolve should refuse")
}

#[test]
fn resolve_refusals() {
    let (mut m, mut e) = setup();
    for who in ["alice.testnet", "bob.testnet"] {
        funded(&mut m, &mut e, who, NEAR);
        e.call(who, 0, fc_key());
        m.stake(U128(STAKE));
    }
    let ok = |net_a: i128, net_b: i128| {
        vec![
            StakeResult { account_id: acc("alice.testnet"), net: I128(net_a) },
            StakeResult { account_id: acc("bob.testnet"), net: I128(net_b) },
        ]
    };
    let s = STAKE as i128;
    assert!(resolve_panics(&m, &mut e, "mallory.testnet", 0, ok(0, 0), 0).contains("only the stake resolver"));
    assert!(resolve_panics(&m, &mut e, "resolver.testnet", 1, ok(0, 0), 0).contains("not the closed stake batch"));
    assert!(resolve_panics(&m, &mut e, "resolver.testnet", 0, ok(s, 0), 0).contains("sum to zero"));
    assert!(resolve_panics(&m, &mut e, "resolver.testnet", 0, ok(-2 * s, 2 * s), 0).contains("lose more than itself"));
    assert!(resolve_panics(&m, &mut e, "resolver.testnet", 0, ok(s, 0), -s).contains("below zero"));
    assert!(
        resolve_panics(&m, &mut e, "resolver.testnet", 0, ok(0, 0)[..1].to_vec(), 0)
            .contains("exactly one result")
    );
    let dup = vec![
        StakeResult { account_id: acc("alice.testnet"), net: I128(0) },
        StakeResult { account_id: acc("alice.testnet"), net: I128(0) },
    ];
    assert!(resolve_panics(&m, &mut e, "resolver.testnet", 0, dup, 0).contains("no open stake"));
}

/// F76: one stake refunds on a timeout.
#[test]
fn stake_refunds_on_timeout() {
    let (mut m, mut e) = setup();
    funded(&mut m, &mut e, "alice.testnet", NEAR);
    e.call("alice.testnet", 0, fc_key());
    m.stake(U128(5 * STAKE));
    let after_stake = m.balance_of(acc("alice.testnet")).0;
    let record_fee = m.stake_of(acc("alice.testnet")).unwrap().storage_fee.0;
    assert!(record_fee > 0);
    // Too early: refused.
    e.now += DEFAULT_STAKE_TIMEOUT_NS - 1;
    e.call("anyone.testnet", 0, fc_key());
    let early = probe(&e, || clone_market(&m).refund_stake(acc("alice.testnet")));
    assert!(early.unwrap_err().contains("not timed out"));
    e.now += 1;
    e.call("anyone.testnet", 0, fc_key());
    assert_eq!(m.refund_stake(acc("alice.testnet")).0, 5 * STAKE);
    assert_eq!(m.balance_of(acc("alice.testnet")).0, after_stake + 5 * STAKE + record_fee, "stake plus its record's storage");
    assert_eq!(m.state().open_count, 0);
    assert!(get_logs().iter().any(|l| l.contains("stake_refund") && l.contains("no result within the timeout")));
    assert!(m.solvency().solvent);
    // The refund voided batch 0: no result for it lands any more; batch 1 is open.
    assert_eq!(m.state().open_batch.0, 1);
    let late = resolve_panics(&m, &mut e, "resolver.testnet", 0, vec![], 0);
    assert!(late.contains("not the closed stake batch"), "{late}");
    e.call("resolver.testnet", 0, fc_key());
    m.close_batch();
    m.resolve(U64(1), vec![], I128(0), [4000, 3500, 1500, 700, 300], "00".repeat(32));
}

#[test]
fn withdraw_debits_first_and_recredits_on_failure() {
    let (mut m, mut e) = setup();
    funded(&mut m, &mut e, "alice.testnet", NEAR);
    let start = m.balance_of(acc("alice.testnet")).0;
    e.call("alice.testnet", 1, other_key());
    let _ = m.withdraw(U128(NEAR / 2));
    assert_eq!(m.balance_of(acc("alice.testnet")).0, start - NEAR / 2, "debited before the transfer runs");
    // The transfer leaves the contract's balance: mirror it, then check solvency.
    e.balance -= NEAR / 2;
    e.call("alice.testnet", 0, other_key());
    assert!(m.solvency().solvent);
    // Callback with a failed transfer: re-credit (the refund comes back to the contract).
    e.balance += NEAR / 2;
    let ctx = VMContextBuilder::new()
        .current_account_id(acc("market.testnet"))
        .predecessor_account_id(acc("market.testnet"))
        .account_balance(NearToken::from_yoctonear(e.balance))
        .build();
    testing_env!(ctx, test_vm_config(), RuntimeFeesConfig::test(), Default::default(), vec![PromiseResult::Failed]);
    assert!(!m.on_withdraw(acc("alice.testnet"), U128(NEAR / 2), Err(PromiseError::Failed)));
    assert_eq!(m.balance_of(acc("alice.testnet")).0, start);
    assert!(m.solvency().solvent);
}

#[test]
#[should_panic(expected = "exactly 1 yoctoNEAR")]
fn withdraw_without_one_yocto_refused() {
    let (mut m, mut e) = setup();
    funded(&mut m, &mut e, "alice.testnet", NEAR);
    e.call("alice.testnet", 0, fc_key());
    let _ = m.withdraw(U128(1));
}

#[test]
#[should_panic(expected = "ledger balance too low")]
fn withdraw_over_balance_refused() {
    let (mut m, mut e) = setup();
    funded(&mut m, &mut e, "alice.testnet", NEAR);
    e.call("alice.testnet", 1, other_key());
    let _ = m.withdraw(U128(2 * NEAR));
}

#[test]
#[should_panic(expected = "previous stake unresolved")]
fn stake_across_batches_refused_until_resolved() {
    let (mut m, mut e) = setup();
    funded(&mut m, &mut e, "alice.testnet", NEAR);
    e.call("alice.testnet", 0, fc_key());
    m.stake(U128(STAKE));
    // A stake left over from an older batch: simulate by rolling the batch.
    m.open_batch += 1; // the resolver moved on without alice (never happens through resolve)
    e.call("alice.testnet", 0, fc_key());
    m.stake(U128(STAKE));
}

/// When the resolver is late past the timeout, a loser who can see
/// a losing life must not refund alone while the winners are later paid from
/// the pot. The first refund voids the whole batch: no result for it lands,
/// every other stake in it refunds at once, and the pot is untouched.
#[test]
fn l11_a_timeout_refund_voids_the_whole_batch_and_the_pot_is_untouched() {
    let (mut m, mut e) = setup();
    for who in ["alice.testnet", "bob.testnet", "carol.testnet"] {
        funded(&mut m, &mut e, who, NEAR);
    }
    // Batch 0: carol's 0-KO life feeds the pot.
    e.call("carol.testnet", 0, fc_key());
    m.stake(U128(STAKE));
    e.call("resolver.testnet", 0, fc_key());
    m.close_batch();
    m.resolve(U64(0), vec![StakeResult { account_id: acc("carol.testnet"), net: I128(-(STAKE as i128)) }],
        I128(STAKE as i128), [4000, 3500, 1500, 700, 300], "aa".repeat(32));
    assert_eq!(m.state().pot.0, STAKE);
    // Batch 1: alice (who will lose) and bob (who will win) stake; the resolver goes quiet.
    for who in ["alice.testnet", "bob.testnet"] {
        e.call(who, 0, fc_key());
        m.stake(U128(STAKE));
    }
    e.now += DEFAULT_STAKE_TIMEOUT_NS;
    e.call("alice.testnet", 0, fc_key());
    m.refund_stake(acc("alice.testnet"));
    // The resolver comes back with bob's win paid from the pot: refused.
    let late = resolve_panics(&m, &mut e, "resolver.testnet", 1,
        vec![StakeResult { account_id: acc("bob.testnet"), net: I128(STAKE as i128) }], -(STAKE as i128));
    assert!(late.contains("not the closed stake batch"), "{late}");
    // Bob refunds at once, no second wait; the pot never moved.
    e.call("anyone.testnet", 0, fc_key());
    assert_eq!(m.refund_stake(acc("bob.testnet")).0, STAKE);
    assert_eq!(m.state().pot.0, STAKE);
    assert!(m.solvency().solvent);
    // A fresh stake goes to the new open batch.
    e.call("bob.testnet", 0, fc_key());
    assert_eq!(m.stake(U128(STAKE)).batch.0, 2);
}

/// A stake record's storage is paid by the staker and comes back
/// when the record goes. A full-access stake (no key-use record) that nets 0
/// returns the balance to exactly where it was, plus the 1 yoctoNEAR it attached.
#[test]
fn l12_a_resolved_or_refunded_stake_returns_its_record_storage() {
    let (mut m, mut e) = setup();
    for who in ["alice.testnet", "bob.testnet"] {
        funded(&mut m, &mut e, who, NEAR);
    }
    let a0 = m.balance_of(acc("alice.testnet")).0;
    let b0 = m.balance_of(acc("bob.testnet")).0;
    e.call("alice.testnet", 1, other_key());
    m.stake(U128(STAKE));
    e.call("resolver.testnet", 0, fc_key());
    m.close_batch();
    m.resolve(U64(0), vec![StakeResult { account_id: acc("alice.testnet"), net: I128(0) }],
        I128(0), [4000, 3500, 1500, 700, 300], "bb".repeat(32));
    assert_eq!(m.balance_of(acc("alice.testnet")).0, a0 + 1, "resolve returns the record's storage");
    e.call("bob.testnet", 1, other_key());
    m.stake(U128(STAKE));
    e.now += DEFAULT_STAKE_TIMEOUT_NS;
    e.call("anyone.testnet", 0, fc_key());
    m.refund_stake(acc("bob.testnet"));
    assert_eq!(m.balance_of(acc("bob.testnet")).0, b0 + 1, "a refund returns it too");
    assert!(m.solvency().solvent);
}

/// A copy for panic probes; `probe` restores the storage the copy may have flushed.
fn clone_market(m: &Market) -> Market {
    near_sdk::borsh::from_slice(&near_sdk::borsh::to_vec(m).unwrap()).unwrap()
}

/// The resolver closes the batch before it reads it, so a stake
/// that lands in between goes to the next batch and can't fail the resolve;
/// a 1-yoctoNEAR stake is refused.
#[test]
fn m3_a_late_stake_joins_the_next_batch_and_dust_stakes_are_refused() {
    let (mut m, mut e) = setup();
    for who in ["a.testnet", "b.testnet"] {
        funded(&mut m, &mut e, who, NEAR);
    }
    e.call("a.testnet", 0, fc_key());
    m.stake(U128(STAKE));
    e.call("mallory.testnet", 0, fc_key());
    assert!(probe(&e, || clone_market(&m).close_batch()).unwrap_err().contains("only the stake resolver"));
    e.call("resolver.testnet", 0, fc_key());
    let closed = m.close_batch();
    assert_eq!((closed.batch.0, closed.stakes), (0, 1));
    // b stakes after the close: it joins batch 1; dust is refused.
    e.call("b.testnet", 0, fc_key());
    assert!(probe(&e, || clone_market(&m).stake(U128(1))).unwrap_err().contains("at least 0.01 NEAR"));
    e.call("b.testnet", 0, fc_key());
    assert_eq!(m.stake(U128(STAKE)).batch.0, 1);
    // A second close waits for the resolve; then batch 0 resolves with a's result alone.
    e.call("resolver.testnet", 0, fc_key());
    assert!(probe(&e, || clone_market(&m).close_batch()).unwrap_err().contains("resolve the closed batch first"));
    e.call("resolver.testnet", 0, fc_key());
    m.resolve(U64(0), vec![StakeResult { account_id: acc("a.testnet"), net: I128(0) }], I128(0),
        [4010, 3470, 1570, 640, 310], "ab".repeat(32));
    assert_eq!(m.stake_of(acc("b.testnet")).unwrap().batch.0, 1);
    assert_eq!(m.state().closed, None);
    assert!(m.solvency().solvent);
}

/// For the resolver (for the stake resolver): the stakes of a batch are listed
/// in staking order, each with every part as it landed (a top-up keeps its own
/// time); the list goes with the resolve, and its storage came from the stakers.
#[test]
fn l15_batch_stakes_list_every_stake_and_each_part_with_its_time() {
    let (mut m, mut e) = setup();
    for who in ["a.testnet", "b.testnet"] {
        funded(&mut m, &mut e, who, NEAR);
    }
    let b0 = m.balance_of(acc("b.testnet")).0;
    e.call("a.testnet", 0, fc_key());
    m.stake(U128(STAKE));
    e.now += 600 * 1_000_000_000;
    e.call("b.testnet", 1, other_key());
    m.stake(U128(STAKE));
    e.now += 600 * 1_000_000_000;
    e.call("a.testnet", 0, fc_key());
    m.stake(U128(2 * STAKE));
    let list = m.batch_stakes(U64(0), None, None);
    assert_eq!(list.iter().map(|s| s.account_id.as_str()).collect::<Vec<_>>(), ["a.testnet", "b.testnet"]);
    let a = &list[0].stake;
    assert_eq!(a.amount.0, 3 * STAKE);
    assert_eq!(a.parts, vec![
        StakePart { amount: U128(STAKE), at: U64(T0) },
        StakePart { amount: U128(2 * STAKE), at: U64(T0 + 1_200 * 1_000_000_000) },
    ]);
    assert_eq!(m.batch_stakes(U64(0), Some(1), Some(5)).len(), 1);
    e.call("resolver.testnet", 0, fc_key());
    m.close_batch();
    e.call("resolver.testnet", 0, fc_key());
    m.resolve(U64(0), vec![
        StakeResult { account_id: acc("a.testnet"), net: I128(0) },
        StakeResult { account_id: acc("b.testnet"), net: I128(0) },
    ], I128(0), [4010, 3470, 1570, 640, 310], "ab".repeat(32));
    assert!(m.batch_stakes(U64(0), None, None).is_empty(), "the list goes with the resolve");
    assert_eq!(m.balance_of(acc("b.testnet")).0, b0 + 1, "b's record and list storage came back");
    assert!(m.solvency().solvent);
}

/// Each refund credits exactly the storage it frees. The first staker
/// used to be charged the batch list's own entry too, so its refund credited
/// storage still in use while other stakes stayed in the list. (c refunds
/// first so the batch's void entry exists before the measured refunds.)
#[test]
fn n2_a_refund_credits_exactly_the_storage_it_frees() {
    let (mut m, mut e) = setup();
    for who in ["a.testnet", "b.testnet", "c.testnet"] {
        funded(&mut m, &mut e, who, NEAR);
        e.call(who, 0, fc_key());
        m.stake(U128(STAKE));
    }
    e.now += DEFAULT_STAKE_TIMEOUT_NS;
    e.call("anyone.testnet", 0, fc_key());
    m.refund_stake(acc("c.testnet"));
    for who in ["a.testnet", "b.testnet"] {
        e.call("anyone.testnet", 0, fc_key());
        m.assert_solvent();
        let fee = m.stake_of(acc(who)).unwrap().storage_fee.0;
        let before = env::storage_usage();
        m.refund_stake(acc(who));
        let freed = (before - env::storage_usage()) as u128 * env::storage_byte_cost().as_yoctonear();
        if who == "a.testnet" {
            assert_eq!(fee, freed, "the first staker's refund credits only what it frees");
        } else {
            assert!(freed > fee, "the last refund also frees the list and void entries, which were the contract's");
        }
    }
    assert!(m.solvency().solvent);
}

/// r5-predict: anyone seeds the reward fund; it adds exactly the deposit, credits no ledger account, stays
/// solvent, and a later resolve pays a correct prediction from it.
#[test]
fn fund_rewards_adds_to_the_fund_and_pays_a_later_resolve() {
    let (mut m, mut e) = setup();
    let ledger_before = m.solvency();
    e.call("operator.testnet", 50 * STAKE, other_key());
    assert_eq!(m.fund_rewards().0, 50 * STAKE);
    assert_eq!(m.state().pot.0, 50 * STAKE);
    assert_eq!(m.balance_of(acc("operator.testnet")).0, 0, "the seed credits no account");
    assert!(m.solvency().solvent);
    assert_eq!(m.solvency().ledger.0, ledger_before.ledger.0);
    funded(&mut m, &mut e, "alice.testnet", NEAR);
    e.call("alice.testnet", 0, fc_key());
    m.stake(U128(STAKE));
    let before = m.balance_of(acc("alice.testnet")).0 + m.stake_of(acc("alice.testnet")).unwrap().storage_fee.0;
    // a correct 2+ at 3.5714x: 0.01 comes back with 0.025714 from the fund
    let gain = STAKE * 25714 / 10_000;
    e.call("resolver.testnet", 0, fc_key());
    m.close_batch();
    let rec = m.resolve(U64(0), vec![StakeResult { account_id: acc("alice.testnet"), net: I128(gain as i128) }],
                        I128(-(gain as i128)), [4010, 3470, 1570, 640, 310], "cd".repeat(32));
    assert_eq!(rec.pot_after.0, 50 * STAKE - gain);
    assert_eq!(m.balance_of(acc("alice.testnet")).0, before + STAKE + gain);
    assert!(m.solvency().solvent);
    e.call("bob.testnet", 0, other_key());
    assert!(probe(&e, || m.fund_rewards()).unwrap_err().contains("fund_rewards needs attached NEAR"));
}
