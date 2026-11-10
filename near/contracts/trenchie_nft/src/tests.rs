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
        acc("arena.testnet"),
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
    nft.apply_rows(batch.into(), rows)
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
    let err = refused(&e, &mut nft, |n| n.apply_rows("b1".into(), rows));
    assert!(err.contains("over the row cap"), "{err}");
    // Paused: writes refused (apply, mint, claim); unpause restores.
    e.call("owner.testnet", 1);
    nft.pause();
    e.call("arena.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.apply_rows("b1".into(), vec![row("a1", vec![], None)]));
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
    // (A row for a missing token no longer reverts the batch: critic M1, see
    // m1_a_burned_token_row_is_skipped_and_the_batch_applies.)
    e.call("arena.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.apply_rows("b2".into(), vec![row("b", vec![entry(3, 1)], None)]));
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
    let err = refused(&e, &mut nft, |n| n.apply_rows("b".into(), vec![row("a", vec![entry(3, 1), entry(3, 2)], None)]));
    assert!(err.contains("second copy of a row"), "{err}");
    let full: Vec<Entry> = (0..48).map(|r| entry(r, 1)).collect();
    apply(&mut nft, &mut e, "b-full", vec![row("a", full.clone(), None)]);
    let mut over = full.clone();
    over.push(entry(0, 2));
    e.call("arena.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.apply_rows("b".into(), vec![row("a", over, None)]));
    assert!(err.contains("at most 48 entries"), "{err}");
    let err = refused(&e, &mut nft, |n| n.apply_rows("b".into(), vec![row("a", vec![entry(48, 1)], None)]));
    assert!(err.contains("not in the rules table"), "{err}");
    let err = refused(&e, &mut nft, |n| n.apply_rows("b".into(), vec![row("a", vec![], None), row("a", vec![], None)]));
    assert!(err.contains("appears twice"), "{err}");
}

#[test]
fn c11_a_serial_is_never_reused() {
    // The rule agreed with the sim (board 02:35, superseding the first
    // version's "leaving every bag retires"): a serialled copy is on one bag at
    // most; a burned copy is gone for good; a copy on the floor is unheld and
    // may come back (m3_ cases). The sim never reissues a serial.
    let (mut nft, mut e) = setup();
    mint(&mut nft, &mut e, "a", "p1.testnet", 1);
    mint(&mut nft, &mut e, "b", "p2.testnet", 2);
    apply(&mut nft, &mut e, "b1", vec![row("a", vec![entry(40, 1607)], Some(true))]);
    // On another bag: refused.
    e.call("arena.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.apply_rows("b2".into(), vec![row("b", vec![entry(40, 1607)], None)]));
    assert!(err.contains("already on another bag"), "{err}");
    // Burned with its persona: retired, and a later add is refused.
    e.call("p1.testnet", 1);
    let _ = nft.nft_burn("a".into());
    assert!(nft.serial_retired(40, 1607));
    assert_eq!(nft.serial_holder(40, 1607), None);
    e.call("arena.testnet", 0);
    let err = refused(&e, &mut nft, |n| n.apply_rows("b2".into(), vec![row("b", vec![entry(40, 1607)], None)]));
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
    let err = refused(&e, &mut nft, |n| n.apply_rows("b9".into(), vec![]));
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
        n.apply_rows("b4".into(), vec![row("b", vec![], None), row("a", vec![entry(3, 1)], None)])
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

/// §9a H1: move B's item to A, lock A, sell A, keep the item. Closed: one batch
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
    let err = refused(&e, &mut nft, |n| n.apply_rows("b1".into(), rows));
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
    let _ = refused(&e, &mut nft, |n| n.apply_rows("b2".into(), vec![row("A", vec![], None), row("x", vec![], None)]));
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
    let err = refused(&e, &mut nft, |n| n.apply_rows("b2".into(), vec![]));
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

#[test]
fn f81_burn_refunds_storage_and_retires_its_serials() {
    let (mut nft, mut e) = sale_ready_pair();
    e.call("seller.testnet", 1);
    let before_supply = nft.nft_total_supply().0;
    let _ = nft.nft_burn("ready".into());
    assert_eq!(nft.nft_total_supply().0, before_supply - 1);
    assert!(nft.nft_token("ready".into()).is_none());
    assert!(nft.serial_retired(3, 1));
    let receipts = near_sdk::test_utils::get_created_receipts();
    let refund = receipts.iter().find(|r| r.receiver_id == acc("seller.testnet")).expect("a refund receipt");
    let paid = refund.actions.iter().find_map(|a| match a {
        near_sdk::mock::MockAction::Transfer { deposit, .. } => Some(deposit.as_yoctonear()),
        _ => None,
    });
    assert!(paid.unwrap() > 0, "burn refunds the freed storage");
    assert!(get_logs().iter().any(|l| l.contains("\"nft_burn\"")));
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
    let p = nft.paid_mint(good.clone(), sign(&good, &key), None);
    assert_eq!(p.token_id, "paid-n1");
    assert_eq!(p.owner_id, acc("player.testnet"));
    assert_eq!(p.preset_id, "preset-2");
    assert_eq!(nft.nft_token("paid-n1".into()).unwrap().metadata.title.as_deref(), Some("Pebble"));

    let try_mint = |e: &mut Env, nft: &mut TrenchieNft, pred: &str, signer: &str, deposit: u128, p: MintPermit, sig: String| {
        e.call_as(pred, signer, deposit);
        refused(e, nft, |n| n.paid_mint(p, sig, None))
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
    nft.paid_mint(ok.clone(), signed(&ok), None);
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
    assert!(refused(&e, &mut nft, |n| n.paid_mint(old.clone(), old_sig.clone(), None)).contains("epoch"));
    let mut fresh = old.clone();
    fresh.epoch = "2".into();
    e.call("player.testnet", MINT_COST);
    assert!(refused(&e, &mut nft, |n| n.paid_mint(fresh.clone(), sign(&fresh, &permit_key()), None)).contains("signature"));
    e.call("player.testnet", MINT_COST);
    nft.paid_mint(fresh.clone(), sign(&fresh, &new_key), None);
}

#[test]
fn f78_paused_refuses_claim_and_paid_mint() {
    let (mut nft, mut e) = setup();
    e.call("owner.testnet", 1);
    nft.pause();
    let p = permit("player.testnet", "n1", T0 / 1_000_000);
    e.call("player.testnet", MINT_COST);
    assert!(refused(&e, &mut nft, |n| n.paid_mint(p.clone(), sign(&p, &permit_key()), None)).contains("paused"));
    e.call("minter.testnet", 0);
    assert!(refused(&e, &mut nft, |n| n.claim("x".into(), acc("p.testnet"), digest(1))).contains("paused"));
}

// ------------------------------------------------------- critic M1 (r4)

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

// ------------------------------------------------------- critic M3 (r4)

/// Agreed with the sim (board 02:35): a KO'd legendary sits on the floor across
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
    let err = refused(&e, &mut nft, |n| n.apply_rows("b3".into(), vec![row("a", vec![entry(3, 0), entry(3, 0)], None)]));
    assert!(err.contains("second copy of a row"), "{err}");
}
