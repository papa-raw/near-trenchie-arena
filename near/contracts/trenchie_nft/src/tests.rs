use super::*;
use ed25519_dalek::{Signer, SigningKey};
use near_sdk::test_utils::{VMContextBuilder, get_logs};
use near_sdk::{RuntimeFeesConfig, test_vm_config, testing_env};

const NEAR: u128 = 1_000_000_000_000_000_000_000_000;
const T0: u64 = 1_800_000_000_000_000_000;
const MINT_COST: u128 = NEAR / 20;
const HOUR: u64 = 3_600 * 1_000_000_000;

fn acc(name: &str) -> AccountId {
    name.parse().unwrap()
}

fn digest(n: u8) -> String {
    format!("{:02x}", n).repeat(32)
}

fn permit_key() -> SigningKey {
    SigningKey::from_bytes(&[7u8; 32])
}

fn b64(raw: &[u8]) -> String {
    URL_SAFE_NO_PAD.encode(raw)
}

struct Env {
    balance: u128,
    now: u64,
    ctx: Option<near_sdk::VMContext>,
}

impl Env {
    fn call(&mut self, who: &str, deposit: u128) {
        self.call_as(who, who, deposit);
    }

    fn call_as(&mut self, predecessor: &str, signer: &str, deposit: u128) {
        self.balance += deposit;
        let ctx = VMContextBuilder::new()
            .current_account_id(acc("nft.testnet"))
            .predecessor_account_id(acc(predecessor))
            .signer_account_id(acc(signer))
            .attached_deposit(NearToken::from_yoctonear(deposit))
            .account_balance(NearToken::from_yoctonear(self.balance))
            .block_timestamp(self.now)
            .prepaid_gas(Gas::from_tgas(300))
            .build();
        self.ctx = Some(ctx.clone());
        testing_env!(ctx);
    }
}

/// Run a call that must be refused against a scratch copy of the mocked storage,
/// then restore it (a panic unwinds through store collections, whose Drop flushes).
fn refused<R>(e: &Env, nft: &mut TrenchieNft, f: impl FnOnce(&mut TrenchieNft) -> R) -> String {
    nft.flush();
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
    let mut copy: TrenchieNft = near_sdk::borsh::from_slice(&near_sdk::borsh::to_vec(nft).unwrap()).unwrap();
    let out = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        f(&mut copy);
    }));
    drop(copy);
    install(snap);
    let err = out.expect_err("call should have been refused");
    err.downcast_ref::<String>()
        .cloned()
        .or_else(|| err.downcast_ref::<&str>().map(|s| s.to_string()))
        .unwrap_or_default()
}

fn presets() -> Vec<String> {
    (1..=5).map(|i| format!("preset-{i}")).collect()
}

fn setup() -> (TrenchieNft, Env) {
    let mut e = Env { balance: 20 * NEAR, now: T0, ctx: None };
    e.call("owner.testnet", 0);
    let nft = TrenchieNft::new(
        acc("owner.testnet"),
        acc("minter.testnet"),
        Some(acc("arena.testnet")),
        acc("custody.testnet"),
        presets(),
        "testnet".into(),
        b64(permit_key().verifying_key().as_bytes()),
        "1".into(),
        U64(60_000),
        U128(MINT_COST),
        64,
        214,
        48,
        NFTContractMetadata {
            spec: "nft-1.0.0".into(),
            name: "Trenchie Arena".into(),
            symbol: "TRENCHIE".into(),
            icon: Some("data:image/svg+xml,<svg/>".into()),
            base_uri: None,
            reference: None,
            reference_hash: None,
        },
        None,
    );
    (nft, e)
}

fn mint(nft: &mut TrenchieNft, e: &mut Env, id: &str, owner: &str, n: u8) -> Persona {
    e.call("minter.testnet", 0);
    nft.mint_trenchie(id.into(), acc(owner), "preset-1".into(), digest(n), None)
}

fn entry(row: u16, serial: u16) -> Entry {
    Entry { row, serial, born_batch: 1, kos: 0, hands: 1, flags: 0 }
}

fn row(id: &str, bag: Vec<Entry>, sale_ready: Option<bool>) -> Row {
    Row { token_id: id.into(), bag, record: Record { lives: 3, kos: 2, skill: 120 }, sale_ready }
}

fn apply(nft: &mut TrenchieNft, e: &mut Env, batch: &str, rows: Vec<Row>) -> ApplyOutcome {
    e.call("arena.testnet", 0);
    nft.apply_rows(batch.into(), U64(nft.last_seq + 1), rows)
}

// ------------------------------------------------------------------- F24

#[test]
fn f24_mint_with_preset_and_empty_bag() {
    let (mut nft, mut e) = setup();
    let p = mint(&mut nft, &mut e, "house-1", "house.testnet", 1);
    assert_eq!(p.preset_id, "preset-1");
    assert!(p.bag.is_empty());
    assert!(!p.sale_ready, "a new persona can fight at once");
    assert!(get_logs().iter().any(|l| l.contains("\"nft_mint\"") && l.contains("nep171")));
}

#[test]
fn f24_refusals_preset_cap_pause_minter_once_per_persona() {
    let (mut nft, mut e) = setup();
    e.call("minter.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.mint_trenchie("x".into(), acc("a.testnet"), "preset-9".into(), digest(1), None));
    assert!(err.contains("preset is not one fixed at init"), "{err}");
    e.call("mallory.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.mint_trenchie("x".into(), acc("a.testnet"), "preset-1".into(), digest(1), None));
    assert!(err.contains("only the snap minter"), "{err}");
    mint(&mut nft, &mut e, "a1", "a.testnet", 1);
    e.call("minter.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.mint_trenchie("a2".into(), acc("a.testnet"), "preset-1".into(), digest(1), None));
    assert!(err.contains("persona already minted"), "{err}");
    // Batch over the cap.
    nft.max_rows_per_batch = 2;
    e.call("arena.testnet", 0);
    mint(&mut nft, &mut e, "a2", "a.testnet", 2);
    mint(&mut nft, &mut e, "a3", "a.testnet", 3);
    e.call("arena.testnet", 0);
    let rows = vec![row("a1", vec![], None), row("a2", vec![], None), row("a3", vec![], None)];
    let err = refused(&e, &mut nft, |n| n.apply_rows("b1".into(), U64(n.last_seq + 1), rows));
    assert!(err.contains("over the row cap"), "{err}");
    // Paused: writes refused (apply, mint, claim); unpause restores.
    e.call("owner.testnet", 1);
    nft.pause();
    e.call("arena.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.apply_rows("b1".into(), U64(n.last_seq + 1), vec![row("a1", vec![], None)]));
    assert!(err.contains("paused"), "{err}");
    e.call("minter.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.mint_trenchie("a9".into(), acc("a.testnet"), "preset-1".into(), digest(9), None));
    assert!(err.contains("paused"), "{err}");
    e.call("mallory.testnet", 1);
    let err = refused(&e, &mut nft, |n| n.unpause());
    assert!(err.contains("owner only"), "{err}");
    e.call("owner.testnet", 1);
    nft.unpause();
    apply(&mut nft, &mut e, "b1", vec![row("a1", vec![], None)]);
}

#[test]
fn f24_mint_cap_bounds_the_minter() {
    let (mut nft, mut e) = setup();
    nft.mint_cap = 2;
    mint(&mut nft, &mut e, "a1", "a.testnet", 1);
    mint(&mut nft, &mut e, "a2", "a.testnet", 2);
    e.call("minter.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.mint_trenchie("a3".into(), acc("a.testnet"), "preset-1".into(), digest(3), None));
    assert!(err.contains("mint cap reached"), "{err}");
}

// ------------------------------------------------------------- F25, C11

#[test]
fn f25_a_pair_applies_both_sides() {
    let (mut nft, mut e) = setup();
    mint(&mut nft, &mut e, "a", "p1.testnet", 1);
    mint(&mut nft, &mut e, "b", "p2.testnet", 2);
    apply(&mut nft, &mut e, "b1", vec![row("a", vec![entry(3, 1), entry(4, 1)], None)]);
    // b takes a's row-3 copy at a KO: both sides in one batch, removals first.
    let out = apply(&mut nft, &mut e, "b2", vec![row("a", vec![entry(4, 1)], None), row("b", vec![entry(3, 1)], None)]);
    assert_eq!(out.rows, 2);
    assert_eq!(nft.serial_holder(3, 1), Some("b".into()));
    assert_eq!(nft.trenchie("a".into()).unwrap().bag, vec![entry(4, 1)]);
    assert_eq!(nft.trenchie("b".into()).unwrap().record, Record { lives: 3, kos: 2, skill: 120 });
    assert!(get_logs().iter().any(|l| l.contains("apply_rows") && l.contains("\"rows\":2")));
}

#[test]
fn f25_one_side_alone_refused_so_neither_applies() {
    let (mut nft, mut e) = setup();
    mint(&mut nft, &mut e, "a", "p1.testnet", 1);
    mint(&mut nft, &mut e, "b", "p2.testnet", 2);
    apply(&mut nft, &mut e, "b1", vec![row("a", vec![entry(3, 1)], None)]);
    // The add without the matching removal: the serial would sit on two bags.
    // (A row for a missing token no longer reverts the batch: see
    // m1_a_burned_token_row_is_skipped_and_the_batch_applies.)
    e.call("arena.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.apply_rows("b2".into(), U64(n.last_seq + 1), vec![row("b", vec![entry(3, 1)], None)]));
    assert!(err.contains("already on another bag"), "{err}");
    // Neither side changed and the batch id is still free.
    assert_eq!(nft.trenchie("b".into()).unwrap().bag, vec![]);
    assert_eq!(nft.serial_holder(3, 1), Some("a".into()));
    assert!(!nft.batch_applied("b2".into()));
}

#[test]
fn f25_bag_refusals_second_copy_and_49th_entry_and_unknown_row() {
    let (mut nft, mut e) = setup();
    mint(&mut nft, &mut e, "a", "p1.testnet", 1);
    e.call("arena.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.apply_rows("b".into(), U64(n.last_seq + 1), vec![row("a", vec![entry(3, 1), entry(3, 2)], None)]));
    assert!(err.contains("second copy of a row"), "{err}");
    let full: Vec<Entry> = (0..48).map(|r| entry(r, 1)).collect();
    apply(&mut nft, &mut e, "b-full", vec![row("a", full.clone(), None)]);
    let mut over = full.clone();
    over.push(entry(0, 2));
    e.call("arena.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.apply_rows("b".into(), U64(n.last_seq + 1), vec![row("a", over, None)]));
    assert!(err.contains("at most 48 entries"), "{err}");
    let err = refused(&e, &mut nft, |n| n.apply_rows("b".into(), U64(n.last_seq + 1), vec![row("a", vec![entry(48, 1)], None)]));
    assert!(err.contains("not in the rules table"), "{err}");
    let err = refused(&e, &mut nft, |n| n.apply_rows("b".into(), U64(n.last_seq + 1), vec![row("a", vec![], None), row("a", vec![], None)]));
    assert!(err.contains("appears twice"), "{err}");
}

#[test]
fn c11_a_serial_is_never_reused() {
    // The rule the sim needs (superseding the first
    // version's "leaving every bag retires"): a serialled copy is on one bag at
    // most; a burned copy is gone for good; a copy on the floor is unheld and
    // may come back (m3_ cases). The sim never reissues a serial.
    let (mut nft, mut e) = setup();
    mint(&mut nft, &mut e, "a", "p1.testnet", 1);
    mint(&mut nft, &mut e, "b", "p2.testnet", 2);
    apply(&mut nft, &mut e, "b1", vec![row("a", vec![entry(40, 1607)], Some(true))]);
    // On another bag: refused.
    e.call("arena.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.apply_rows("b2".into(), U64(n.last_seq + 1), vec![row("b", vec![entry(40, 1607)], None)]));
    assert!(err.contains("already on another bag"), "{err}");
    // Burned with its persona: retired, and a later add is refused.
    e.call("p1.testnet", 1);
    let _ = nft.nft_burn("a".into());
    assert!(nft.serial_retired(40, 1607));
    assert_eq!(nft.serial_holder(40, 1607), None);
    e.call("arena.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.apply_rows("b2".into(), U64(n.last_seq + 1), vec![row("b", vec![entry(40, 1607)], None)]));
    assert!(err.contains("serial reused"), "{err}");
    // The next serial of the same row is fine, and a move keeps its serial.
    mint(&mut nft, &mut e, "c", "p3.testnet", 3);
    apply(&mut nft, &mut e, "b3", vec![row("b", vec![entry(40, 1608)], None)]);
    apply(&mut nft, &mut e, "b4", vec![row("b", vec![], None), row("c", vec![entry(40, 1608)], None)]);
    assert_eq!(nft.serial_holder(40, 1608), Some("c".into()));
    assert!(!nft.serial_retired(40, 1608));
}

#[test]
fn f84_retry_with_the_same_batch_id_is_safe() {
    let (mut nft, mut e) = setup();
    mint(&mut nft, &mut e, "a", "p1.testnet", 1);
    let first = apply(&mut nft, &mut e, "b1", vec![row("a", vec![entry(3, 1)], None)]);
    assert!(!first.already_applied);
    let again = apply(&mut nft, &mut e, "b1", vec![row("a", vec![entry(3, 1)], None)]);
    assert!(again.already_applied);
    assert_eq!(nft.trenchie("a".into()).unwrap().bag, vec![entry(3, 1)]);
    e.call("mallory.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.apply_rows("b9".into(), U64(n.last_seq + 1), vec![]));
    assert!(err.contains("only arena"), "{err}");
}

// ------------------------------------------------------------------- F85

#[test]
fn f85_own_trenchie_move_applies_as_a_pair_and_locked_persona_refuses() {
    let (mut nft, mut e) = setup();
    mint(&mut nft, &mut e, "a", "p1.testnet", 1);
    mint(&mut nft, &mut e, "b", "p1.testnet", 2);
    apply(&mut nft, &mut e, "b1", vec![row("a", vec![entry(3, 1)], None)]);
    apply(&mut nft, &mut e, "b2", vec![row("a", vec![], None), row("b", vec![entry(3, 1)], None)]);
    assert_eq!(nft.serial_holder(3, 1), Some("b".into()));
    // b goes sale-ready (locked, out of play): its bag is frozen until a clearing batch.
    apply(&mut nft, &mut e, "b3", vec![row("b", vec![entry(3, 1)], Some(true))]);
    e.call("arena.testnet", 0);
    let err = refused(&e, &mut nft, |n| {
        n.apply_rows("b4".into(), U64(n.last_seq + 1), vec![row("b", vec![], None), row("a", vec![entry(3, 1)], None)])
    });
    assert!(err.contains("bag change on a sale-ready persona"), "{err}");
    // Unlock: the clearing batch (bag unchanged) clears the flag; then moves work again.
    apply(&mut nft, &mut e, "b4", vec![row("b", vec![entry(3, 1)], Some(false))]);
    apply(&mut nft, &mut e, "b5", vec![row("b", vec![], None), row("a", vec![entry(3, 1)], None)]);
    assert_eq!(nft.serial_holder(3, 1), Some("a".into()));
}

// ------------------------------------------------------------------- F86

fn sale_ready_pair() -> (TrenchieNft, Env) {
    let (mut nft, mut e) = setup();
    mint(&mut nft, &mut e, "ready", "seller.testnet", 1);
    mint(&mut nft, &mut e, "inplay", "seller.testnet", 2);
    apply(&mut nft, &mut e, "b1", vec![row("ready", vec![entry(3, 1)], Some(true))]);
    (nft, e)
}

#[test]
fn f86_every_ownership_path_refuses_without_sale_ready() {
    let (mut nft, mut e) = sale_ready_pair();
    e.call("seller.testnet", 1);
    let err = refused(&e, &mut nft, |n| n.nft_transfer(acc("buyer.testnet"), "inplay".into(), None, None));
    assert_eq!(err, NOT_SALE_READY);
    let err = refused(&e, &mut nft, |n| n.nft_transfer_call(acc("market.testnet"), "inplay".into(), None, None, "".into()));
    assert_eq!(err, NOT_SALE_READY);
    let err = refused(&e, &mut nft, |n| n.nft_burn("inplay".into()));
    assert_eq!(err, NOT_SALE_READY);
    // An approved marketplace can't get round it either.
    e.call("seller.testnet", NEAR / 100);
    nft.nft_approve("inplay".into(), acc("venue.testnet"), None);
    e.call("venue.testnet", 1);
    let err = refused(&e, &mut nft, |n| n.nft_transfer(acc("buyer.testnet"), "inplay".into(), Some(0), None));
    assert_eq!(err, NOT_SALE_READY);
    // Claim: a held premint not yet sale-ready.
    mint(&mut nft, &mut e, "held", "custody.testnet", 3);
    e.call("minter.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.claim("held".into(), acc("player.testnet"), digest(3)));
    assert_eq!(err, NOT_SALE_READY);
    // The sale-ready token transfers.
    e.call("seller.testnet", 1);
    nft.nft_transfer(acc("buyer.testnet"), "ready".into(), None, None);
    assert_eq!(nft.nft_token("ready".into()).unwrap().owner_id, acc("buyer.testnet"));
    assert_eq!(nft.trenchie("ready".into()).unwrap().bag, vec![entry(3, 1)], "a sale carries the bag");
}

/// Move B's item to A, lock A, sell A, keep the item. Closed: one batch
/// writes both sides, and A can't transfer before that batch; B stays in play.
#[test]
fn f86_trace_h1_move_lock_sell_is_closed() {
    let (mut nft, mut e) = setup();
    mint(&mut nft, &mut e, "A", "seller.testnet", 1);
    mint(&mut nft, &mut e, "B", "seller.testnet", 2);
    apply(&mut nft, &mut e, "b1", vec![row("B", vec![entry(9, 1)], None)]);
    // Before the batch: A is locked server-side but not sale-ready onchain.
    e.call("seller.testnet", 1);
    assert_eq!(refused(&e, &mut nft, |n| n.nft_transfer(acc("buyer.testnet"), "A".into(), None, None)), NOT_SALE_READY);
    // The batch writes the move and sets A's flag together.
    apply(&mut nft, &mut e, "b2", vec![row("B", vec![], None), row("A", vec![entry(9, 1)], Some(true))]);
    e.call("seller.testnet", 1);
    nft.nft_transfer(acc("buyer.testnet"), "A".into(), None, None);
    // The buyer has the item; B (in play) has nothing and can't be sold.
    assert_eq!(nft.trenchie("A".into()).unwrap().bag, vec![entry(9, 1)]);
    assert_eq!(nft.trenchie("B".into()).unwrap().bag, vec![]);
    e.call("seller.testnet", 1);
    assert_eq!(refused(&e, &mut nft, |n| n.nft_transfer(acc("buyer.testnet"), "B".into(), None, None)), NOT_SALE_READY);
}

/// §9a "Unlock during a sale": after the clearing batch the transfer refuses.
#[test]
fn f86_trace_unlock_clears_and_transfer_refuses() {
    let (mut nft, mut e) = sale_ready_pair();
    apply(&mut nft, &mut e, "b2", vec![row("ready", vec![entry(3, 1)], Some(false))]);
    e.call("seller.testnet", 1);
    assert_eq!(refused(&e, &mut nft, |n| n.nft_transfer(acc("buyer.testnet"), "ready".into(), None, None)), NOT_SALE_READY);
}

/// §9a "Failed hop, retried": a refused batch leaves the flag unset; the sale waits.
#[test]
fn f86_trace_failed_hop_leaves_flag_unset() {
    let (mut nft, mut e) = setup();
    mint(&mut nft, &mut e, "A", "seller.testnet", 1);
    nft.max_rows_per_batch = 1;
    e.call("arena.testnet", 0);
    let rows = vec![row("A", vec![], Some(true)), row("A2", vec![], None)];
    let err = refused(&e, &mut nft, |n| n.apply_rows("b1".into(), U64(n.last_seq + 1), rows));
    assert!(err.contains("row cap"), "{err}");
    assert!(!nft.trenchie("A".into()).unwrap().sale_ready);
    apply(&mut nft, &mut e, "b1", vec![row("A", vec![], Some(true))]);
    assert!(nft.trenchie("A".into()).unwrap().sale_ready);
}

// ------------------------------------------------------------------- F87

#[test]
fn f87_48h_timeout_keyed_to_apply_rows_and_a_failed_hop_does_not_reset_it() {
    let (mut nft, mut e) = setup();
    mint(&mut nft, &mut e, "A", "seller.testnet", 1);
    apply(&mut nft, &mut e, "b1", vec![row("A", vec![], None)]);
    let t_apply = e.now;
    // 47 h later a hop fails (refused apply_rows): the timer must not move.
    e.now = t_apply + 47 * HOUR;
    nft.max_rows_per_batch = 1;
    e.call("arena.testnet", 0);
    let _ = refused(&e, &mut nft, |n| n.apply_rows("b2".into(), U64(n.last_seq + 1), vec![row("A", vec![], None), row("x", vec![], None)]));
    assert_eq!(nft.contract_state().last_apply_ns.0, t_apply);
    e.call("seller.testnet", 1);
    assert_eq!(refused(&e, &mut nft, |n| n.nft_transfer(acc("buyer.testnet"), "A".into(), None, None)), NOT_SALE_READY);
    // At 48 h the guard stops applying.
    e.now = t_apply + 48 * HOUR;
    e.call("seller.testnet", 1);
    assert!(nft.contract_state().transfers_open);
    nft.nft_transfer(acc("buyer.testnet"), "A".into(), None, None);
    assert_eq!(nft.nft_token("A".into()).unwrap().owner_id, acc("buyer.testnet"));
    // The next batch closes it again.
    apply(&mut nft, &mut e, "b2", vec![row("A", vec![], None)]);
    e.call("buyer.testnet", 1);
    assert!(!nft.contract_state().transfers_open);
    assert_eq!(refused(&e, &mut nft, |n| n.nft_transfer(acc("x.testnet"), "A".into(), None, None)), NOT_SALE_READY);
}

#[test]
fn f87_end_game_opens_transfers_with_no_final_batch_and_closes_apply_rows() {
    let (mut nft, mut e) = setup();
    mint(&mut nft, &mut e, "A", "seller.testnet", 1);
    apply(&mut nft, &mut e, "b1", vec![row("A", vec![entry(2, 1)], None)]);
    e.call("mallory.testnet", 1);
    assert!(refused(&e, &mut nft, |n| n.end_game()).contains("owner only"));
    e.call("owner.testnet", 1);
    nft.end_game();
    e.call("seller.testnet", 1);
    nft.nft_transfer(acc("buyer.testnet"), "A".into(), None, None);
    assert_eq!(nft.trenchie("A".into()).unwrap().bag, vec![entry(2, 1)], "bags final as last written");
    e.call("arena.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.apply_rows("b2".into(), U64(n.last_seq + 1), vec![]));
    assert!(err.contains("apply_rows is closed"), "{err}");
}

// ------------------------------------------------------------------- F81

#[test]
fn f81_enumeration_and_metadata() {
    let (mut nft, mut e) = setup();
    mint(&mut nft, &mut e, "a", "p1.testnet", 1);
    mint(&mut nft, &mut e, "b", "p1.testnet", 2);
    mint(&mut nft, &mut e, "c", "p2.testnet", 3);
    assert_eq!(nft.nft_total_supply().0, 3);
    assert_eq!(nft.nft_supply_for_owner(acc("p1.testnet")).0, 2);
    let ids: Vec<String> = nft.nft_tokens(Some(U128(1)), Some(5)).into_iter().map(|t| t.token_id).collect();
    assert_eq!(ids, vec!["b", "c"]);
    let mine: Vec<String> =
        nft.nft_tokens_for_owner(acc("p1.testnet"), None, None).into_iter().map(|t| t.token_id).collect();
    assert_eq!(mine, vec!["a", "b"]);
    let meta = nft.nft_metadata();
    assert_eq!(meta.spec, "nft-1.0.0");
    assert!(meta.icon.unwrap().starts_with("data:image/svg+xml"));
}

#[test]
fn f81_approvals_approve_is_approved_revoke_revoke_all_and_stale_refused() {
    let (mut nft, mut e) = sale_ready_pair();
    e.call("seller.testnet", NEAR / 100);
    nft.nft_approve("ready".into(), acc("venue.testnet"), None);
    e.call("seller.testnet", NEAR / 100);
    nft.nft_approve("ready".into(), acc("venue2.testnet"), None);
    assert!(nft.nft_is_approved("ready".into(), acc("venue.testnet"), Some(0)));
    assert!(nft.nft_is_approved("ready".into(), acc("venue2.testnet"), Some(1)));
    assert!(!nft.nft_is_approved("ready".into(), acc("venue.testnet"), Some(1)));
    e.call("seller.testnet", 1);
    nft.nft_revoke("ready".into(), acc("venue2.testnet"));
    assert!(!nft.nft_is_approved("ready".into(), acc("venue2.testnet"), None));
    // Wrong approval id refused; the right one transfers.
    e.call("venue.testnet", 1);
    let err = refused(&e, &mut nft, |n| n.nft_transfer(acc("buyer.testnet"), "ready".into(), Some(7), None));
    assert!(err.contains("approval id does not match"), "{err}");
    e.call("venue.testnet", 1);
    nft.nft_transfer(acc("buyer.testnet"), "ready".into(), Some(0), None);
    assert!(get_logs().iter().any(|l| l.contains("\"authorized_id\":\"venue.testnet\"")));
    // Stale: the approval died with the transfer.
    assert!(nft.nft_token("ready".into()).unwrap().approved_account_ids.is_empty());
    e.call("venue.testnet", 1);
    let err = refused(&e, &mut nft, |n| n.nft_transfer(acc("x.testnet"), "ready".into(), Some(0), None));
    assert!(err.contains("not the owner or approved"), "{err}");
    // revoke_all.
    e.call("buyer.testnet", NEAR / 100);
    nft.nft_approve("ready".into(), acc("v3.testnet"), None);
    e.call("buyer.testnet", NEAR / 100);
    nft.nft_approve("ready".into(), acc("v4.testnet"), None);
    e.call("buyer.testnet", 1);
    nft.nft_revoke_all("ready".into());
    assert!(nft.nft_token("ready".into()).unwrap().approved_account_ids.is_empty());
    e.call("mallory.testnet", NEAR / 100);
    let err = refused(&e, &mut nft, |n| n.nft_approve("ready".into(), acc("v5.testnet"), None));
    assert!(err.contains("only the owner may approve"), "{err}");
}

/// A burn refunds the storage its owner paid (a paid mint's
/// bytes, open approvals), never storage the contract paid, and retires its serials.
#[test]
fn f81_burn_refunds_the_storage_its_owner_paid_and_retires_its_serials() {
    let (mut nft, mut e) = sale_ready_pair();
    // "ready" was minted by the snap minter: the contract paid its storage.
    e.call("seller.testnet", 1);
    let before_supply = nft.nft_total_supply().0;
    let refund = nft.nft_burn("ready".into()).0;
    assert_eq!(refund, 0, "storage the contract paid stays with the contract");
    assert!(transfers_to("seller.testnet").is_empty());
    assert_eq!(nft.nft_total_supply().0, before_supply - 1);
    assert!(nft.nft_token("ready".into()).is_none());
    assert!(nft.serial_retired(3, 1));
    assert!(get_logs().iter().any(|l| l.contains("\"nft_burn\"")));
    // A paid mint's owner gets its bytes back, never more than it paid.
    let p = permit("player.testnet", "n1", T0 / 1_000_000);
    e.call("player.testnet", MINT_COST);
    nft.paid_mint(p.clone(), sign(&p, &permit_key()));
    let paid_bytes = nft.tokens.get("paid-n1").unwrap().paid_bytes;
    assert!(paid_bytes > 0);
    apply(&mut nft, &mut e, "b2", vec![row("paid-n1", vec![], Some(true))]);
    e.call("player.testnet", 1);
    let refund = nft.nft_burn("paid-n1".into()).0;
    assert!(refund > 0 && refund <= paid_bytes as u128 * env::storage_byte_cost().as_yoctonear(), "{refund}");
    assert_eq!(transfers_to("player.testnet"), vec![refund]);
}

/// The yoctoNEAR of every Transfer receipt created for `who` in the last call.
fn transfers_to(who: &str) -> Vec<u128> {
    near_sdk::test_utils::get_created_receipts()
        .into_iter()
        .filter(|r| r.receiver_id == acc(who))
        .flat_map(|r| r.actions)
        .filter_map(|a| match a {
            near_sdk::mock::MockAction::Transfer { deposit, .. } => Some(deposit.as_yoctonear()),
            _ => None,
        })
        .collect()
}

fn byte() -> u128 {
    env::storage_byte_cost().as_yoctonear()
}

// ------------------------------------------------ review findings

/// Approvals are capped, so no owner can inflate every batch's gas.
#[test]
fn l1_a_ninth_approval_is_refused() {
    let (mut nft, mut e) = sale_ready_pair();
    for i in 0..MAX_APPROVALS {
        e.call("seller.testnet", NEAR / 100);
        nft.nft_approve("ready".into(), acc(&format!("v{i}.testnet")), None);
    }
    e.call("seller.testnet", NEAR / 100);
    let err = refused(&e, &mut nft, |n| n.nft_approve("ready".into(), acc("v9.testnet"), None));
    assert!(err.contains("at most 8 approvals"), "{err}");
    // Re-approving one already there is still fine.
    e.call("seller.testnet", NEAR / 100);
    nft.nft_approve("ready".into(), acc("v0.testnet"), None);
}

/// A paid mint is charged for every byte it adds, the nonce's included.
#[test]
fn l3_paid_mint_charges_the_storage_it_actually_adds() {
    let (mut nft, mut e) = setup();
    let p = permit("player.testnet", "n1", T0 / 1_000_000);
    e.call("player.testnet", MINT_COST);
    nft.flush();
    let before = env::storage_usage(); // measured inside the call's context (a new context resets the meter)
    nft.paid_mint(p.clone(), sign(&p, &permit_key()));
    nft.flush();
    let actual = env::storage_usage() - before;
    let charged = get_logs()
        .iter()
        .find(|l| l.contains("\"paid_mint\""))
        .and_then(|l| l.split("\"storage_bytes\":").nth(1))
        .and_then(|t| t.split(|c: char| !c.is_ascii_digit()).next())
        .and_then(|n| n.parse::<u64>().ok())
        .expect("paid_mint event with storage_bytes");
    assert_eq!(charged, actual, "charged bytes = bytes added");
}

/// Re-approving an account already approved refunds the unused deposit.
#[test]
fn l4_re_approval_refunds_the_unused_deposit() {
    let (mut nft, mut e) = sale_ready_pair();
    e.call("seller.testnet", NEAR / 100);
    nft.nft_approve("ready".into(), acc("venue.testnet"), None);
    e.call("seller.testnet", NEAR / 100);
    nft.nft_approve("ready".into(), acc("venue.testnet"), None);
    assert_eq!(transfers_to("seller.testnet"), vec![NEAR / 100], "same-length record: all of it back");
    assert!(nft.nft_is_approved("ready".into(), acc("venue.testnet"), Some(1)));
}

/// A move refunds the old owner's approval storage; on nft_transfer_call
/// only once the transfer stands (a bounce restores the approvals instead).
#[test]
fn l5_a_move_refunds_the_old_owners_approval_storage() {
    let (mut nft, mut e) = sale_ready_pair();
    for v in ["venue.testnet", "venue22.testnet"] {
        e.call("seller.testnet", NEAR / 100);
        nft.nft_approve("ready".into(), acc(v), None);
    }
    let want = ((4 + 13 + 8) + (4 + 15 + 8)) as u128 * byte();
    e.call("seller.testnet", 1);
    nft.nft_transfer(acc("buyer.testnet"), "ready".into(), None, None);
    assert_eq!(transfers_to("seller.testnet"), vec![want]);
    // transfer_call: nothing refunded on the first leg.
    e.call("buyer.testnet", NEAR / 100);
    nft.nft_approve("ready".into(), acc("venue.testnet"), None);
    e.call("buyer.testnet", 1);
    let _ = nft.nft_transfer_call(acc("shop.testnet"), "ready".into(), None, None, "m".into());
    assert!(transfers_to("buyer.testnet").is_empty());
}

/// A 60-character nonce would make a 65-character token id: refused up
/// front, consuming nothing; 59 characters mint.
#[test]
fn l7_a_nonce_too_long_for_its_token_id_is_refused() {
    let (mut nft, mut e) = setup();
    let now_ms = T0 / 1_000_000;
    let long = permit("player.testnet", &"n".repeat(60), now_ms);
    e.call("player.testnet", MINT_COST);
    let err = refused(&e, &mut nft, |n| n.paid_mint(long.clone(), sign(&long, &permit_key())));
    assert!(err.contains("invalid mint permit: nonce"), "{err}");
    let ok = permit("player.testnet", &"n".repeat(59), now_ms);
    e.call("player.testnet", MINT_COST);
    assert_eq!(nft.paid_mint(ok.clone(), sign(&ok, &permit_key())).token_id.len(), 64);
}

/// Views never wrap a large index to 0, and never panic on a missing token.
#[test]
fn l9_views_do_not_truncate_the_index_or_panic_on_a_missing_token() {
    let (nft, mut e) = sale_ready_pair();
    e.call("anyone.testnet", 0);
    assert_eq!(nft.nft_tokens(None, None).len(), 2);
    assert!(nft.nft_tokens(Some(U128(1u128 << 64)), None).is_empty());
    assert!(nft.nft_tokens_for_owner(acc("seller.testnet"), Some(U128(1u128 << 64)), None).is_empty());
    assert!(!nft.nft_is_approved("gone".into(), acc("venue.testnet"), None));
}

fn resolve_with(nft: &mut TrenchieNft, e: &mut Env, receiver_said: &[u8], approvals: BTreeMap<AccountId, u64>) -> bool {
    e.call("nft.testnet", 0);
    testing_env!(
        e.ctx.clone().unwrap(),
        test_vm_config(),
        RuntimeFeesConfig::test(),
        Default::default(),
        vec![near_sdk::PromiseResult::Successful(receiver_said.to_vec())]
    );
    nft.nft_resolve_transfer(acc("seller.testnet"), acc("shop.testnet"), "ready".into(), Some(approvals))
}

/// Nft_resolve_transfer, both ways. The receiver returns the token: it
/// goes back with its approvals restored and nothing refunded. The receiver
/// keeps it: the old owner's approval storage is refunded then.
#[test]
fn l10_resolve_transfer_returns_with_approvals_or_stands_and_refunds() {
    for (said, back) in [(&b"true"[..], true), (&b"false"[..], false)] {
        near_sdk::mock::with_mocked_blockchain(|b| drop(b.take_storage())); // a fresh chain each way
        let (mut nft, mut e) = sale_ready_pair();
        e.call("seller.testnet", NEAR / 100);
        nft.nft_approve("ready".into(), acc("venue.testnet"), None);
        let approvals = nft.tokens.get("ready").unwrap().approvals.clone();
        e.call("seller.testnet", 1);
        let _ = nft.nft_transfer_call(acc("shop.testnet"), "ready".into(), None, None, "m".into());
        assert_eq!(nft.nft_token("ready".into()).unwrap().owner_id, acc("shop.testnet"));
        let stood = resolve_with(&mut nft, &mut e, said, approvals.clone());
        let t = nft.nft_token("ready".into()).unwrap();
        if back {
            assert!(!stood);
            assert_eq!(t.owner_id, acc("seller.testnet"));
            assert_eq!(t.approved_account_ids, approvals, "approvals restored");
            assert!(transfers_to("seller.testnet").is_empty(), "no refund on a bounce");
            assert!(get_logs().iter().any(|l| l.contains("\"memo\":\"returned\"")));
        } else {
            assert!(stood);
            assert_eq!(t.owner_id, acc("shop.testnet"));
            assert!(t.approved_account_ids.is_empty());
            assert_eq!(transfers_to("seller.testnet"), vec![(4 + 13 + 8) as u128 * byte()]);
        }
    }
}

// ------------------------------------------------------------- F78 claim

#[test]
fn f78_claim_needs_minter_digest_custody_and_sale_ready() {
    let (mut nft, mut e) = setup();
    mint(&mut nft, &mut e, "preset-1-01", "custody.testnet", 1);
    e.call("minter.testnet", 0);
    assert_eq!(refused(&e, &mut nft, |n| n.claim("preset-1-01".into(), acc("p.testnet"), digest(1))), NOT_SALE_READY);
    apply(&mut nft, &mut e, "b1", vec![row("preset-1-01", vec![], Some(true))]);
    e.call("mallory.testnet", 0);
    assert!(refused(&e, &mut nft, |n| n.claim("preset-1-01".into(), acc("p.testnet"), digest(1))).contains("only the snap minter"));
    e.call("minter.testnet", 0);
    assert!(refused(&e, &mut nft, |n| n.claim("preset-1-01".into(), acc("p.testnet"), digest(2))).contains("does not match"));
    let p = nft.claim("preset-1-01".into(), acc("p.testnet"), digest(1));
    assert_eq!(p.owner_id, acc("p.testnet"));
    // Idempotent for the same claimer; refused for anyone else (no longer in custody).
    e.call("minter.testnet", 0);
    assert_eq!(nft.claim("preset-1-01".into(), acc("p.testnet"), digest(1)).owner_id, acc("p.testnet"));
    e.call("minter.testnet", 0);
    assert!(refused(&e, &mut nft, |n| n.claim("preset-1-01".into(), acc("q.testnet"), digest(1))).contains("not held for claim"));
}

// ------------------------------------------------------- F78 / W3 premint

fn premint_all(nft: &mut TrenchieNft, e: &mut Env) {
    for (i, preset) in presets().iter().enumerate() {
        e.call("minter.testnet", 0);
        let ids = nft.premint(preset.clone(), digest(0xf0 + i as u8), 10);
        assert_eq!(ids.len(), 10);
        assert_eq!(ids[0], format!("{preset}-00"));
        assert_eq!(ids[9], format!("{preset}-09"));
    }
}

/// W3 + F78: 50 held tokens (5 presets x 10, one digest a preset, empty bags,
/// in custody, sale-ready), claimed one by one; the 51st claim answers
/// paid_mint_required, and nothing over-allocates.
#[test]
fn f78_premint_holds_50_and_the_51st_claim_answers_paid_mint_required() {
    let (mut nft, mut e) = setup();
    premint_all(&mut nft, &mut e);
    let st = nft.premint_state();
    assert_eq!((st.cap, st.minted, st.held, st.claimed), (50, 50, 50, 0));
    assert_eq!(nft.nft_supply_for_owner(acc("custody.testnet")).0, 50);
    let t = nft.trenchie("preset-3-07".into()).unwrap();
    assert_eq!((t.owner_id.as_str(), t.preset_id.as_str(), t.persona_digest.clone(), t.bag.len(), t.sale_ready),
        ("custody.testnet", "preset-3", digest(0xf2), 0, true));
    for (i, preset) in presets().iter().enumerate() {
        for c in 0..10 {
            e.call("minter.testnet", 0);
            let to = format!("p{i}x{c}.testnet");
            assert_eq!(nft.claim(format!("{preset}-{c:02}"), acc(&to), digest(0xf0 + i as u8)).owner_id, acc(&to));
        }
    }
    let st = nft.premint_state();
    assert_eq!((st.held, st.claimed), (0, 50));
    // The 51st: every token is gone from custody, so the claim answers paid_mint_required.
    e.call("minter.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.claim("preset-1-00".into(), acc("late.testnet"), digest(0xf0)));
    assert!(err.contains("paid_mint_required: all held premints are claimed"), "{err}");
    assert_eq!(nft.nft_token("preset-1-00".into()).unwrap().owner_id, acc("p0x0.testnet"), "no over-allocation");
    // No 51st premint either.
    e.call("minter.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.premint("preset-1".into(), digest(0xf0), 1));
    assert!(err.contains("at most 10 premint copies"), "{err}");
}

#[test]
fn f78_premint_refusals_minter_cap_digest_preset_pause() {
    let (mut nft, mut e) = setup();
    e.call("mallory.testnet", 0);
    assert!(refused(&e, &mut nft, |n| n.premint("preset-1".into(), digest(0xf0), 10)).contains("only the snap minter"));
    e.call("minter.testnet", 0);
    assert!(refused(&e, &mut nft, |n| n.premint("preset-9".into(), digest(0xf0), 10)).contains("fixed at init"));
    e.call("minter.testnet", 0);
    nft.premint("preset-1".into(), digest(0xf0), 4);
    e.call("minter.testnet", 0);
    assert!(refused(&e, &mut nft, |n| n.premint("preset-1".into(), digest(0xf9), 1)).contains("share one persona digest"));
    e.call("minter.testnet", 0);
    assert!(refused(&e, &mut nft, |n| n.premint("preset-1".into(), digest(0xf0), 7)).contains("at most 10"));
    e.call("minter.testnet", 0);
    assert_eq!(nft.premint("preset-1".into(), digest(0xf0), 6), (4..10).map(|i| format!("preset-1-{i:02}")).collect::<Vec<_>>());
    // A custom mint can't take a premint digest, and a second preset can't reuse it.
    e.call("minter.testnet", 0);
    assert!(refused(&e, &mut nft, |n| n.mint_trenchie("x".into(), acc("p.testnet"), "preset-1".into(), digest(0xf0), None)).contains("already minted"));
    e.call("minter.testnet", 0);
    assert!(refused(&e, &mut nft, |n| n.premint("preset-2".into(), digest(0xf0), 1)).contains("already minted"));
    e.call("owner.testnet", 1);
    nft.pause();
    e.call("minter.testnet", 0);
    assert!(refused(&e, &mut nft, |n| n.premint("preset-2".into(), digest(0xf1), 1)).contains("paused"));
}

/// The total cap binds even with presets left (an init cap below 50).
#[test]
fn f78_premint_total_cap() {
    let (mut nft, mut e) = setup();
    nft.premint_cap = 12;
    e.call("minter.testnet", 0);
    nft.premint("preset-1".into(), digest(0xf0), 10);
    e.call("minter.testnet", 0);
    assert!(refused(&e, &mut nft, |n| n.premint("preset-2".into(), digest(0xf1), 3)).contains("premint cap reached"));
}

/// After run-out the room's permit names the preset persona (its premint
/// digest): paid copies of a preset mint, any number; a custom persona still
/// mints once.
#[test]
fn f78_run_out_paid_mints_copy_a_premint_preset() {
    let (mut nft, mut e) = setup();
    premint_all(&mut nft, &mut e);
    nft.premint_claimed = 50; // run-out: every premint is out of custody
    let now_ms = T0 / 1_000_000;
    for n in ["r1", "r2"] {
        let mut p = permit("player.testnet", n, now_ms);
        p.preset_id = "preset-2".into();
        p.persona_digest = digest(0xf1);
        e.call("player.testnet", MINT_COST);
        let t = nft.paid_mint(p.clone(), sign(&p, &permit_key()));
        assert_eq!((t.preset_id.as_str(), t.persona_digest.clone(), t.sale_ready), ("preset-2", digest(0xf1), false));
    }
    // The premint digest of one preset is not a copy of another preset.
    let mut p = permit("player.testnet", "r3", now_ms);
    p.preset_id = "preset-3".into();
    p.persona_digest = digest(0xf1);
    e.call("player.testnet", MINT_COST);
    assert!(refused(&e, &mut nft, |n| n.paid_mint(p.clone(), sign(&p, &permit_key()))).contains("persona already minted"));
    assert_eq!(nft.premint_state().minted, 50, "paid mints never touch the premint count");
}

// --------------------------------------------------------- F78 paid mint

fn permit(caller: &str, nonce: &str, now_ms: u64) -> MintPermit {
    MintPermit {
        domain: PERMIT_DOMAIN.into(),
        schema: PERMIT_SCHEMA.into(),
        epoch: "1".into(),
        network_id: "testnet".into(),
        contract_id: "nft.testnet".into(),
        caller: caller.into(),
        name: "Pebble".into(),
        persona_digest: digest(0xaa),
        preset_id: "preset-2".into(),
        nonce: nonce.into(),
        issued_at: now_ms.to_string(),
        expires_at: (now_ms + 60_000).to_string(),
    }
}

fn sign(p: &MintPermit, key: &SigningKey) -> String {
    b64(&key.sign(&p.signing_bytes()).to_bytes())
}

#[test]
fn f78_permit_bytes_match_the_frozen_encoding() {
    // The same bytes `near/onboarding/signing.py` permit_bytes() builds: u32 BE length + UTF-8, in field order.
    let p = permit("player.testnet", "n1", 5);
    let bytes = p.signing_bytes();
    assert_eq!(&bytes[..4], &(PERMIT_DOMAIN.len() as u32).to_be_bytes());
    assert_eq!(&bytes[4..4 + PERMIT_DOMAIN.len()], PERMIT_DOMAIN.as_bytes());
    assert!(bytes.ends_with(b"\x00\x00\x00\x0560005"));
}

#[test]
fn f78_paid_mint_valid_then_every_refusal() {
    let (mut nft, mut e) = setup();
    let now_ms = T0 / 1_000_000;
    let key = permit_key();
    let good = permit("player.testnet", "n1", now_ms);
    e.call("player.testnet", MINT_COST);
    let p = nft.paid_mint(good.clone(), sign(&good, &key));
    assert_eq!(p.token_id, "paid-n1");
    assert_eq!(p.owner_id, acc("player.testnet"));
    assert_eq!(p.preset_id, "preset-2");
    assert_eq!(nft.nft_token("paid-n1".into()).unwrap().metadata.title.as_deref(), Some("Pebble"));

    let try_mint = |e: &mut Env, nft: &mut TrenchieNft, pred: &str, signer: &str, deposit: u128, p: MintPermit, sig: String| {
        e.call_as(pred, signer, deposit);
        refused(e, nft, |n| n.paid_mint(p, sig))
    };
    let fresh = |nonce: &str| permit("player.testnet", nonce, now_ms);
    let signed = |p: &MintPermit| sign(p, &key);
    let mut cases: Vec<(&str, MintPermit, String, &str, &str, u128)> = Vec::new();
    // Reused nonce.
    cases.push(("nonce used", good.clone(), signed(&good), "player.testnet", "player.testnet", MINT_COST));
    // Bypass: a different caller (predecessor) presenting someone's permit, and a contract in between.
    let p = fresh("n2");
    cases.push(("caller", p.clone(), signed(&p), "other.testnet", "other.testnet", MINT_COST));
    cases.push(("direct wallet call", p.clone(), signed(&p), "relay.testnet", "player.testnet", MINT_COST));
    // Invalid signer: signed by another key.
    let rogue = SigningKey::from_bytes(&[9u8; 32]);
    cases.push(("signature", p.clone(), sign(&p, &rogue), "player.testnet", "player.testnet", MINT_COST));
    // Changed name / persona / preset after signing.
    for (field, want) in [("name", "signature"), ("persona", "signature"), ("preset", "signature")] {
        let mut changed = p.clone();
        let sig = signed(&p);
        match field {
            "name" => changed.name = "Boulder".into(),
            "persona" => changed.persona_digest = digest(0xbb),
            _ => changed.preset_id = "preset-3".into(),
        }
        cases.push((want, changed, sig, "player.testnet", "player.testnet", MINT_COST));
    }
    // Wrong contract / network / schema / epoch (each signed, so only the context check refuses).
    let mut c = fresh("n3");
    c.contract_id = "other-nft.testnet".into();
    cases.push(("contract", c.clone(), signed(&c), "player.testnet", "player.testnet", MINT_COST));
    let mut c = fresh("n4");
    c.network_id = "mainnet".into();
    cases.push(("network", c.clone(), signed(&c), "player.testnet", "player.testnet", MINT_COST));
    let mut c = fresh("n5");
    c.schema = "2".into();
    cases.push(("schema", c.clone(), signed(&c), "player.testnet", "player.testnet", MINT_COST));
    let mut c = fresh("n6");
    c.epoch = "0".into();
    cases.push(("epoch", c.clone(), signed(&c), "player.testnet", "player.testnet", MINT_COST));
    // Expired, future-issued, overlong.
    let mut c = fresh("n7");
    c.issued_at = (now_ms - 60_000).to_string();
    c.expires_at = now_ms.to_string();
    cases.push(("expired", c.clone(), signed(&c), "player.testnet", "player.testnet", MINT_COST));
    let mut c = fresh("n8");
    c.issued_at = (now_ms + 1).to_string();
    c.expires_at = (now_ms + 2).to_string();
    cases.push(("issued in the future", c.clone(), signed(&c), "player.testnet", "player.testnet", MINT_COST));
    let mut c = fresh("n9");
    c.expires_at = (now_ms + 60_001).to_string();
    cases.push(("lifetime too long", c.clone(), signed(&c), "player.testnet", "player.testnet", MINT_COST));
    // Wrong payment, preset outside the set, same persona twice.
    let c = fresh("n10");
    cases.push(("exactly the mint cost", c.clone(), signed(&c), "player.testnet", "player.testnet", MINT_COST - 1));
    let mut c = fresh("n11");
    c.preset_id = "preset-9".into();
    cases.push(("fixed at init", c.clone(), signed(&c), "player.testnet", "player.testnet", MINT_COST));
    let c = fresh("n12"); // same persona digest as the first mint
    cases.push(("persona already minted", c.clone(), signed(&c), "player.testnet", "player.testnet", MINT_COST));
    // Malformed signature encoding.
    let c = fresh("n13");
    cases.push(("signature encoding", c.clone(), "A".repeat(86) + "=", "player.testnet", "player.testnet", MINT_COST));

    for (want, p, sig, pred, signer, deposit) in cases {
        let err = try_mint(&mut e, &mut nft, pred, signer, deposit, p, sig);
        assert!(err.contains(want), "expected '{want}', got '{err}'");
    }
    // Nothing above minted or consumed anything: n2 still mints once with a fresh persona.
    let mut ok = fresh("n2");
    ok.persona_digest = digest(0xcc);
    e.call("player.testnet", MINT_COST);
    nft.paid_mint(ok.clone(), signed(&ok));
    assert_eq!(nft.nft_total_supply().0, 2);
}

#[test]
fn f78_rotation_invalidates_old_epoch_permits() {
    let (mut nft, mut e) = setup();
    let now_ms = T0 / 1_000_000;
    let old = permit("player.testnet", "n1", now_ms);
    let old_sig = sign(&old, &permit_key());
    let new_key = SigningKey::from_bytes(&[3u8; 32]);
    e.call("owner.testnet", 1);
    nft.rotate_permit_key(b64(new_key.verifying_key().as_bytes()), "2".into());
    e.call("player.testnet", MINT_COST);
    assert!(refused(&e, &mut nft, |n| n.paid_mint(old.clone(), old_sig.clone())).contains("epoch"));
    let mut fresh = old.clone();
    fresh.epoch = "2".into();
    e.call("player.testnet", MINT_COST);
    assert!(refused(&e, &mut nft, |n| n.paid_mint(fresh.clone(), sign(&fresh, &permit_key()))).contains("signature"));
    e.call("player.testnet", MINT_COST);
    nft.paid_mint(fresh.clone(), sign(&fresh, &new_key));
}

#[test]
fn f78_paused_refuses_claim_and_paid_mint() {
    let (mut nft, mut e) = setup();
    e.call("owner.testnet", 1);
    nft.pause();
    let p = permit("player.testnet", "n1", T0 / 1_000_000);
    e.call("player.testnet", MINT_COST);
    assert!(refused(&e, &mut nft, |n| n.paid_mint(p.clone(), sign(&p, &permit_key()))).contains("paused"));
    e.call("minter.testnet", 0);
    assert!(refused(&e, &mut nft, |n| n.claim("x".into(), acc("p.testnet"), digest(1))).contains("paused"));
}

// ------------------------------------------------ review findings

/// A persona burned while its row was in flight must not revert the batch:
/// its row is skipped and named, every other row applies.
#[test]
fn m1_a_burned_token_row_is_skipped_and_the_batch_applies() {
    let (mut nft, mut e) = sale_ready_pair();
    e.call("seller.testnet", 1);
    let _ = nft.nft_burn("ready".into());
    let out = apply(
        &mut nft,
        &mut e,
        "b2",
        vec![row("ready", vec![entry(3, 1)], Some(false)), row("inplay", vec![entry(5, 9)], None)],
    );
    assert_eq!(out.rows, 1, "only the live row applies");
    assert_eq!(out.skipped, vec!["ready".to_string()]);
    assert_eq!(nft.trenchie("inplay".into()).unwrap().bag, vec![entry(5, 9)]);
    assert!(nft.batch_applied("b2".into()));
    assert!(nft.serial_retired(3, 1), "the burned copy stays retired");
    assert!(get_logs().iter().any(|l| l.contains("\"apply_rows\"") && l.contains("\"skipped\":[\"ready\"]")));
}

// ------------------------------------------------ review findings

/// As the sim moves floor items: a KO'd legendary sits on the floor across
/// an hourly cut, so batch 2 writes the dropper's bag without it, and batch 3
/// writes it into the grabber's bag. The copy was unheld between, not gone.
#[test]
fn m3_a_floor_item_across_the_cut_is_grabbed_in_the_next_batch() {
    let (mut nft, mut e) = setup();
    mint(&mut nft, &mut e, "a", "p1.testnet", 1);
    mint(&mut nft, &mut e, "b", "p2.testnet", 2);
    apply(&mut nft, &mut e, "b1", vec![row("a", vec![entry(40, 1607)], None)]);
    apply(&mut nft, &mut e, "b2", vec![row("a", vec![], None)]);
    assert_eq!(nft.serial_holder(40, 1607), None);
    assert!(!nft.serial_retired(40, 1607), "on the floor, not gone");
    let out = apply(&mut nft, &mut e, "b3", vec![row("b", vec![entry(40, 1607)], None)]);
    assert_eq!(out.rows, 1);
    assert_eq!(nft.serial_holder(40, 1607), Some("b".into()));
}

/// Commons and rares carry serial 0 (no copy identity): the same row in two
/// bags is two copies, never "already on another bag".
#[test]
fn m3_serial_zero_is_not_tracked_per_copy() {
    let (mut nft, mut e) = setup();
    mint(&mut nft, &mut e, "a", "p1.testnet", 1);
    mint(&mut nft, &mut e, "b", "p2.testnet", 2);
    apply(&mut nft, &mut e, "b1", vec![row("a", vec![entry(3, 0)], None)]);
    apply(&mut nft, &mut e, "b2", vec![row("b", vec![entry(3, 0)], None)]);
    assert_eq!(nft.trenchie("b".into()).unwrap().bag, vec![entry(3, 0)]);
    assert_eq!(nft.serial_holder(3, 0), None);
    // Still one of each row per bag.
    e.call("arena.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.apply_rows("b3".into(), U64(n.last_seq + 1), vec![row("a", vec![entry(3, 0), entry(3, 0)], None)]));
    assert!(err.contains("second copy of a row"), "{err}");
}

// ------------------------------------------------ review findings

/// Rows are absolute, so a stale batch must never roll a newer one back.
/// apply_rows needs a seq above the last applied; an applied id is still the
/// no-op retry.
#[test]
fn h1_batches_apply_in_order_and_a_stale_one_cannot_roll_back() {
    let (mut nft, mut e) = setup();
    mint(&mut nft, &mut e, "p1", "a.testnet", 1);
    let old = Row { token_id: "p1".into(), bag: vec![entry(5, 0)], record: Record { lives: 3, kos: 2, skill: 120 }, sale_ready: None };
    let new = Row { token_id: "p1".into(), bag: vec![entry(5, 0), entry(6, 0)], record: Record { lives: 9, kos: 7, skill: 300 }, sale_ready: None };
    // b1 (seq 1) failed its hop; b2 (seq 2) landed.
    e.call("arena.testnet", 0);
    nft.apply_rows("b2".into(), U64(2), vec![new.clone()]);
    // The stale b1 retry is refused, under its own id or any other.
    e.call("arena.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.apply_rows("b1".into(), U64(1), vec![old.clone()]));
    assert!(err.contains("seq 1 is not after the last applied, 2"), "{err}");
    e.call("arena.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.apply_rows("b1x".into(), U64(2), vec![old.clone()]));
    assert!(err.contains("not after"), "{err}");
    // b2 again is the no-op retry.
    e.call("arena.testnet", 0);
    assert!(nft.apply_rows("b2".into(), U64(2), vec![new.clone()]).already_applied);
    let p = nft.trenchie("p1".into()).unwrap();
    assert_eq!((p.bag.len(), p.record.lives), (2, 9), "b2's state stands");
    assert_eq!(nft.contract_state().last_seq.0, 2);
}

/// The paid mint's metadata comes from the signed permit only.
#[test]
fn m1_paid_mint_metadata_is_the_permits_name_only() {
    let (mut nft, mut e) = setup();
    let good = permit("player.testnet", "n1", T0 / 1_000_000);
    e.call("player.testnet", MINT_COST);
    nft.paid_mint(good.clone(), sign(&good, &permit_key()));
    let md = nft.nft_token("paid-n1".into()).unwrap().metadata;
    assert_eq!(md, TokenMetadata { title: Some("Pebble".into()), ..Default::default() });
}

/// Any batch resets the 48 h exit, so an owner's own request lifts the
/// guard for that token after two more batches, even if none sets sale_ready.
#[test]
fn m2_an_owners_exit_request_lifts_the_guard_after_two_batches() {
    let (mut nft, mut e) = setup();
    mint(&mut nft, &mut e, "p1", "a.testnet", 1);
    mint(&mut nft, &mut e, "p2", "c.testnet", 2);
    e.call("mallory.testnet", 1);
    assert!(refused(&e, &mut nft, |n| n.request_exit("p1".into())).contains("only the owner"));
    e.call("a.testnet", 1);
    assert_eq!(nft.request_exit("p1".into()).0, 2);
    apply(&mut nft, &mut e, "empty-1", vec![]);
    e.call("a.testnet", 1);
    assert!(refused(&e, &mut nft, |n| n.nft_transfer(acc("b.testnet"), "p1".into(), None, None)).contains("sale-ready"));
    apply(&mut nft, &mut e, "empty-2", vec![]);
    assert!(!nft.contract_state().transfers_open, "the global exit stays shut");
    e.call("a.testnet", 1);
    nft.nft_transfer(acc("b.testnet"), "p1".into(), None, None);
    assert_eq!(nft.nft_token("p1".into()).unwrap().owner_id, acc("b.testnet"));
    // Only that token: p2 is still guarded; and the request died with the move.
    e.call("c.testnet", 1);
    assert!(refused(&e, &mut nft, |n| n.nft_transfer(acc("d.testnet"), "p2".into(), None, None)).contains("sale-ready"));
    assert_eq!(nft.tokens.get("p1").unwrap().exit_at_seq, 0);
}

// ------------------------------------------------ review findings

/// Every premint claimed: the counts stay exact (held 0, claimed 50), a premint can't be sent back into custody,
/// and the next ask answers run-out, never a panic in the views.
#[test]
fn n1_all_premints_claimed_counts_stay_exact() {
    let (mut nft, mut e) = setup();
    premint_all(&mut nft, &mut e);
    for (i, preset) in presets().iter().enumerate() {
        for k in 0..10 {
            e.call("minter.testnet", 0);
            nft.claim(format!("{preset}-{k:02}"), acc(&format!("p{i}{k}.testnet")), digest(0xf0 + i as u8));
        }
    }
    assert_eq!((nft.premint_state().held, nft.premint_state().claimed), (0, 50));
    e.call("p00.testnet", 1);
    let err = refused(&e, &mut nft, |n| n.nft_transfer(acc("custody.testnet"), "preset-1-00".into(), None, None));
    assert!(err.contains("custody holds only the premint"), "{err}");
    let st = nft.premint_state();
    assert_eq!((st.minted, st.held, st.claimed), (50, 0, 50));
    let _ = nft.contract_state();
    e.call("minter.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.claim("preset-1-00".into(), acc("later.testnet"), digest(0xf0)));
    assert!(err.contains("paid_mint_required"), "{err}");
}

/// Nobody can gift a token into custody (a claimed premint, a paid copy, any persona), so `held` counts only what
/// the premint minted there and a gift never blocks the paid copies after run-out.
#[test]
fn a_token_sent_into_custody_never_counts_as_held() {
    let (mut nft, mut e) = setup();
    premint_all(&mut nft, &mut e);
    e.call("minter.testnet", 0);
    nft.claim("preset-1-00".into(), acc("p.testnet"), digest(0xf0));
    assert_eq!(nft.premint_state().held, 49);
    e.call("p.testnet", 1);
    let err = refused(&e, &mut nft, |n| n.nft_transfer(acc("custody.testnet"), "preset-1-00".into(), None, None));
    assert!(err.contains("custody holds only the premint"), "{err}");
    e.call("p.testnet", 1);
    let err = refused(&e, &mut nft, |n| n.nft_transfer_call(acc("custody.testnet"), "preset-1-00".into(), None, None, "m".into()));
    assert!(err.contains("custody holds only the premint"), "{err}");
    assert_eq!((nft.premint_state().held, nft.premint_state().claimed), (49, 1));
}

/// A paid copy carries its preset's premint digest but is never counted as a premint: only `<preset>-NN` ids the
/// premint minted are.
#[test]
fn a_paid_copy_is_never_counted_as_a_premint() {
    let (mut nft, mut e) = setup();
    premint_all(&mut nft, &mut e);
    nft.premint_claimed = 50; // run-out
    let mut p = permit("player.testnet", "c1", T0 / 1_000_000);
    p.preset_id = "preset-2".into();
    p.persona_digest = digest(0xf1);
    e.call("player.testnet", MINT_COST);
    nft.paid_mint(p.clone(), sign(&p, &permit_key()));
    let copy = nft.tokens.get("paid-c1").unwrap().clone();
    let premint = nft.tokens.get("preset-2-04").unwrap().clone();
    assert_eq!(copy.persona_digest, premint.persona_digest, "same persona");
    assert!(!nft.is_premint("paid-c1", &copy), "a paid copy is not a premint");
    assert!(nft.is_premint("preset-2-04", &premint));
    assert!(!nft.is_premint("preset-2-10", &premint), "beyond the copies minted");
    assert!(!nft.is_premint("preset-3-04", &premint), "another preset's id");
}

/// F1: before any premint exists, a claim of a token not in custody is "not
/// held for claim"; paid_mint_required means the premint ran out.
#[test]
fn f1_no_premint_yet_means_not_held_not_run_out() {
    let (mut nft, mut e) = setup();
    mint(&mut nft, &mut e, "x", "p.testnet", 1);
    e.call("minter.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.claim("x".into(), acc("q.testnet"), digest(1)));
    assert!(err.contains("token is not held for claim") && !err.contains("paid_mint_required"), "{err}");
}

// ------------------------------------------------ identity-only mainnet

/// The mainnet deployment: `arena: None`. Mint, premint, claim and NEP-171 work; apply_rows is refused;
/// a minted token transfers at once (no sale-ready guard), so a sale moves the trenchie's testnet gear.
#[test]
fn identity_only_deployment_has_no_batches_and_no_sale_guard() {
    let (mut nft, mut e) = setup();
    nft.arena = None;
    mint(&mut nft, &mut e, "t1", "a.testnet", 1);
    e.call("arena.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.apply_rows("b1".into(), U64(1), vec![row("t1", vec![], None)]));
    assert!(err.contains("identity-only deployment"), "{err}");
    e.call("a.testnet", 1);
    nft.nft_transfer(acc("b.testnet"), "t1".into(), None, None);
    assert_eq!(nft.nft_token("t1".into()).unwrap().owner_id, acc("b.testnet"));
    assert_eq!(nft.contract_state().arena, None);
    // The premint and its claim still run.
    premint_all(&mut nft, &mut e);
    e.call("minter.testnet", 0);
    assert_eq!(nft.claim("preset-2-04".into(), acc("p.testnet"), digest(0xf1)).owner_id, acc("p.testnet"));
}

/// A copy of a premint persona exists only after run-out, through a paid mint with a valid
/// permit. The minter key alone never mints one, under any id; a paid copy before run-out is refused.
#[test]
fn a_premint_copy_needs_run_out_and_a_permit() {
    let (mut nft, mut e) = setup();
    premint_all(&mut nft, &mut e);
    for id in ["paid-abc", "x", "preset-2-10"] {
        e.call("minter.testnet", 0);
        let err = refused(&e, &mut nft, |n| n.mint_trenchie(id.into(), acc("m.testnet"), "preset-2".into(), digest(0xf1), None));
        assert!(err.contains("persona already minted"), "{id}: {err}");
    }
    let now_ms = T0 / 1_000_000;
    let mut p = permit("player.testnet", "c1", now_ms);
    p.preset_id = "preset-2".into();
    p.persona_digest = digest(0xf1);
    e.call("player.testnet", MINT_COST);
    let err = refused(&e, &mut nft, |n| n.paid_mint(p.clone(), sign(&p, &permit_key())));
    assert!(err.contains("only after run-out"), "{err}");
    nft.premint_claimed = 50; // every premint out of custody (the claim loop is f78_premint_holds_50_...)
    e.call("player.testnet", MINT_COST);
    let t = nft.paid_mint(p.clone(), sign(&p, &permit_key()));
    assert_eq!((t.token_id.as_str(), t.persona_digest.clone()), ("paid-c1", digest(0xf1)));
}
