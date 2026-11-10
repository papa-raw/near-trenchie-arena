use super::*;
use near_sdk::mock::MockAction;
use near_sdk::test_utils::{VMContextBuilder, get_created_receipts, get_logs};
use near_sdk::{NearToken, RuntimeFeesConfig, test_vm_config, testing_env};

const NEAR: u128 = 1_000_000_000_000_000_000_000_000;

fn acc(name: &str) -> AccountId {
    name.parse().unwrap()
}

fn call(who: &str, deposit: u128) -> near_sdk::VMContext {
    let ctx = VMContextBuilder::new()
        .current_account_id(acc("arena.testnet"))
        .predecessor_account_id(acc(who))
        .signer_account_id(acc(who))
        .attached_deposit(NearToken::from_yoctonear(deposit))
        .account_balance(NearToken::from_yoctonear(50 * NEAR))
        .random_seed([42u8; 32])
        .block_height(1_234)
        .prepaid_gas(Gas::from_tgas(300))
        .build();
    testing_env!(ctx.clone());
    ctx
}

fn refused<R>(ctx: near_sdk::VMContext, arena: &mut Arena, f: impl FnOnce(&mut Arena) -> R) -> String {
    arena.batches.flush();
    arena.queue.flush();
    arena.commits.flush();
    let snap = near_sdk::mock::with_mocked_blockchain(|b| b.take_storage());
    let install = |storage| {
        near_sdk::env::set_blockchain_interface(near_sdk::MockedBlockchain::new(
            ctx.clone(),
            test_vm_config(),
            RuntimeFeesConfig::test(),
            vec![],
            storage,
            Default::default(),
            None,
        ))
    };
    install(snap.clone());
    let mut copy: Arena = near_sdk::borsh::from_slice(&near_sdk::borsh::to_vec(arena).unwrap()).unwrap();
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

fn setup(keep: Option<u32>) -> Arena {
    call("owner.testnet", 0);
    Arena::new(acc("owner.testnet"), acc("operator.testnet"), acc("nft.testnet"), keep)
}

/// An arena with one day-long commit (commit 0, 1440 seeds) to post against.
fn seeded() -> Arena {
    let mut a = setup(None);
    call("operator.testnet", 0);
    a.commit_seeds("cd".repeat(32), MAX_SEEDS_PER_COMMIT);
    a
}

/// A segment run on commit 0's seed `i`, its seed_hash as the room seals it.
fn seg(a: &Arena, i: u16) -> Segment {
    seg_tagged(a, i, i as u32)
}

fn seg_tagged(a: &Arena, i: u16, tag: u32) -> Segment {
    Segment {
        segment_id: format!("seg-{i}"),
        commit_id: U64(0),
        seed_index: i,
        seed_hash: a.seed_record(U64(0), i).seed_hash,
        inputs_hash: "02".repeat(32),
        rules_hash: "03".repeat(32),
        final_state_hash: format!("{:064x}", tag),
        predictions_log_hash: "05".repeat(32),
        kos: 2,
    }
}

fn rows() -> Vec<Row> {
    vec![Row {
        token_id: "preset-1-01".into(),
        bag: vec![Entry { row: 3, serial: 1, born_batch: 1, kos: 0, hands: 1, flags: 0 }],
        record: Record { lives: 1, kos: 2, skill: 0 },
        sale_ready: None,
    }]
}

fn hop_calls() -> Vec<(String, String)> {
    get_created_receipts()
        .into_iter()
        .flat_map(|r| {
            let to = r.receiver_id.to_string();
            r.actions.into_iter().filter_map(move |a| match a {
                MockAction::FunctionCallWeight { method_name, .. } => {
                    Some((to.clone(), String::from_utf8(method_name).unwrap()))
                }
                _ => None,
            })
        })
        .collect()
}

#[test]
fn f84_post_batch_stores_the_hash_then_hops_to_apply_rows() {
    let mut a = seeded();
    let segs = vec![seg(&a, 0), seg(&a, 1)];
    call("operator.testnet", 0);
    let _ = a.post_batch("b1".into(), segs.clone(), rows(), false);
    let calls = hop_calls();
    assert!(calls.contains(&("nft.testnet".into(), "apply_rows".into())), "{calls:?}");
    assert!(calls.contains(&("arena.testnet".into(), "on_apply".into())), "{calls:?}");
    let rec = a.get_batch("b1".into()).unwrap();
    assert_eq!(rec.status, Status::Pending, "pending until the hop's result lands");
    assert_eq!((rec.segments, rec.kos, rec.rows, rec.hops), (2, 4, 1, 1));
    let expect = hex(&env::sha256_array(&near_sdk::borsh::to_vec(&segs).unwrap()));
    assert_eq!(rec.fight_hash, expect);
    assert!(get_logs().iter().any(|l| l.contains("\"post_batch\"") && l.contains(&expect)));
}

#[test]
fn f84_failed_hop_stays_pending_and_a_retry_resends_only_the_hop() {
    let mut a = seeded();
    let s0 = seg(&a, 0);
    let other = seg_tagged(&a, 0, 9);
    call("operator.testnet", 0);
    let _ = a.post_batch("b1".into(), vec![s0.clone()], rows(), false);
    // The hop failed: the hash stands, rows stay pending.
    call("arena.testnet", 0);
    assert!(!a.on_apply("b1".into(), Err(PromiseError::Failed)));
    assert_eq!(a.get_batch("b1".into()).unwrap().status, Status::Pending);
    assert!(get_logs().iter().any(|l| l.contains("\"status\":\"pending\"")));
    // Retry with the same id and content: one more hop, the same record.
    call("operator.testnet", 0);
    let _ = a.post_batch("b1".into(), vec![s0.clone()], rows(), false);
    assert!(hop_calls().contains(&("nft.testnet".into(), "apply_rows".into())));
    let rec = a.get_batch("b1".into()).unwrap();
    assert_eq!(rec.hops, 2);
    assert_eq!(a.state().kept_non_manifest.0, 1, "no second record");
    call("arena.testnet", 0);
    assert!(a.on_apply("b1".into(), Ok(json!({"already_applied": false}))));
    assert_eq!(a.get_batch("b1".into()).unwrap().status, Status::Applied);
    // Once applied, a further retry sends nothing.
    call("operator.testnet", 0);
    assert!(a.post_batch("b1".into(), vec![s0.clone()], rows(), false).is_none());
    assert!(hop_calls().is_empty());
    // The same id with other content is refused.
    let ctx = call("operator.testnet", 0);
    let err = refused(ctx, &mut a, |x| x.post_batch("b1".into(), vec![other.clone()], rows(), false));
    assert!(err.contains("different content"), "{err}");
}

#[test]
fn c2_no_user_methods_every_write_is_the_operators() {
    let mut a = seeded();
    let s1 = seg(&a, 0);
    let ctx = call("player.testnet", 0);
    assert!(refused(ctx.clone(), &mut a, |x| x.post_batch("b1".into(), vec![s1.clone()], rows(), false)).contains("only the arena operator"));
    assert!(refused(ctx.clone(), &mut a, |x| x.commit_seeds("aa".repeat(32), 5)).contains("only the arena operator"));
    let ctx = call("player.testnet", 1);
    assert!(refused(ctx, &mut a, |x| x.set_operator(acc("player.testnet"))).contains("owner only"));
    // on_apply is #[private]: the wasm entry wrapper refuses any caller but arena
    // itself. Unit calls bypass that wrapper, so it is checked on testnet (G0 log).
}

/// C5's done-when: 301 non-MANIFEST records plus 40 MANIFEST ones: after the
/// 301st, the oldest non-MANIFEST is gone, 300 remain, all 40 MANIFEST remain.
#[test]
fn c5_the_301st_record_prunes_exactly_the_oldest() {
    let mut a = seeded();
    for i in 0..40u16 {
        let s = seg(&a, i);
        call("operator.testnet", 0);
        let _ = a.post_batch(format!("m{i}"), vec![s], rows(), true);
    }
    for i in 0..300u16 {
        let s = seg(&a, 40 + i);
        call("operator.testnet", 0);
        let _ = a.post_batch(format!("n{i}"), vec![s], rows(), false);
    }
    assert!(a.get_batch("n0".into()).is_some());
    let s = seg(&a, 340);
    call("operator.testnet", 0);
    let _ = a.post_batch("n300".into(), vec![s], rows(), false);
    assert!(a.get_batch("n0".into()).is_none(), "the oldest non-MANIFEST record is gone");
    assert!(a.get_batch("n1".into()).is_some());
    assert_eq!(a.state().kept_non_manifest.0, 300);
    assert!((0..40).all(|i| a.get_batch(format!("m{i}")).is_some()));
    assert!(get_logs().iter().any(|l| l.contains("\"prune\"") && l.contains("\"n0\"")));
}

#[test]
fn c6_commit_fixes_and_publishes_a_batch_of_seeds() {
    let mut a = setup(None);
    call("operator.testnet", 0);
    let secret = "ab".repeat(32);
    let seeds = a.commit_seeds(secret.clone(), 60);
    assert_eq!(seeds.len(), 60);
    let want0 = hex(&derive_seed(&[0xab; 32], &[42u8; 32], 0));
    assert_eq!(seeds[0], want0);
    assert_eq!(a.seed(U64(0), 59), seeds[59]);
    let c = a.get_commit(U64(0)).unwrap();
    assert_eq!((c.block_height.0, c.count), (1_234, 60));
    assert_eq!(c.random_seed, "2a".repeat(32));
    let log = get_logs().into_iter().find(|l| l.contains("commit_seeds")).unwrap();
    assert!(log.contains(&want0) && log.contains(&seeds[59]), "all seeds published at the commit");
    // A day-long commit carries the inputs in its event; the seeds are its return value.
    call("operator.testnet", 0);
    assert_eq!(a.commit_seeds("ac".repeat(32), MAX_SEEDS_PER_COMMIT).len(), 1_440);
    let ctx = call("operator.testnet", 0);
    assert!(refused(ctx.clone(), &mut a, |x| x.commit_seeds(secret.clone(), 0)).contains("1 to 1440"));
    assert!(refused(ctx, &mut a, |x| x.commit_seeds("zz".repeat(32), 5)).contains("hex"));
}

#[test]
fn post_batch_refuses_malformed_segments() {
    let mut a = seeded();
    let mut bad = seg(&a, 0);
    let ctx = call("operator.testnet", 0);
    bad.rules_hash = "XYZ".into();
    assert!(refused(ctx.clone(), &mut a, |x| x.post_batch("b".into(), vec![bad], rows(), false)).contains("64 lowercase hex"));
    assert!(refused(ctx, &mut a, |x| x.post_batch("b".into(), vec![], rows(), false)).contains("at least one segment"));
}

// ------------------------------------------------------- critic M2 (r4)

/// The seed forms agree with the room's sealed record, checked against a
/// vector computed outside Rust (Python hashlib, 2026-11-10):
/// secret ab*32, random_seed 0x2a*32, i = 0 and 1.
#[test]
fn m2_seed_record_matches_the_room_encoding() {
    let mut a = setup(None);
    call("operator.testnet", 0);
    a.commit_seeds("ab".repeat(32), 2);
    let r0 = a.seed_record(U64(0), 0);
    assert_eq!(r0.seed, "551193331f834e859f538b7fc778c40c80d13b01be4bf36a1dcd095e30b6ccea");
    assert_eq!(r0.seed_u64.0, 6_129_842_415_609_269_893);
    assert_eq!(r0.seed_hash, "e73ba3e7212c0d868fdc3499e0c7426f6360a38a5ca71238cadd30a8de78e01d");
    let r1 = a.seed_record(U64(0), 1);
    assert_eq!(r1.seed_u64.0, 13_991_534_661_924_932_593);
    assert_eq!(r1.seed_hash, "0ea75bbf989864ad7c40ee979fd1a8ca963485903af4e9d90530b3a4550ad241");
}

/// Every posted segment consumes the next committed seed, one use each, in
/// commit order; its seed_hash must be that seed's. The operator can't pick.
#[test]
fn m2_segments_consume_committed_seeds_in_order() {
    let mut a = setup(None);
    call("operator.testnet", 0);
    a.commit_seeds("cd".repeat(32), 2);
    call("operator.testnet", 0);
    a.commit_seeds("ef".repeat(32), 3);
    let s0 = seg(&a, 0);
    let s1 = seg(&a, 1);
    let ctx = call("operator.testnet", 0);
    // A seed never committed.
    let mut forged = s0.clone();
    forged.seed_hash = "07".repeat(32);
    assert!(refused(ctx.clone(), &mut a, |x| x.post_batch("b".into(), vec![forged.clone()], rows(), false)).contains("committed seed"));
    // Skipping ahead in the commit.
    assert!(refused(ctx.clone(), &mut a, |x| x.post_batch("b".into(), vec![s1.clone()], rows(), false)).contains("next committed seed"));
    // Jumping to the later commit while the first has seeds left.
    let mut later = s0.clone();
    later.commit_id = U64(1);
    later.seed_hash = a.seed_record(U64(1), 0).seed_hash;
    assert!(refused(ctx.clone(), &mut a, |x| x.post_batch("b".into(), vec![later.clone()], rows(), false)).contains("next committed seed"));
    // In order: 0 then 1 of commit 0, in one batch.
    let _ = a.post_batch("b1".into(), vec![s0.clone(), s1.clone()], rows(), false);
    assert_eq!(a.state().next_seed, SeedRef { commit_id: U64(1), seed_index: 0 });
    // A used seed can't run a second segment.
    let mut again = s0.clone();
    again.final_state_hash = "08".repeat(32);
    let ctx = call("operator.testnet", 0);
    assert!(refused(ctx, &mut a, |x| x.post_batch("b2".into(), vec![again.clone()], rows(), false)).contains("next committed seed"));
    // A retry of the pending batch consumes nothing.
    call("operator.testnet", 0);
    let _ = a.post_batch("b1".into(), vec![s0, s1], rows(), false);
    assert_eq!(a.state().next_seed, SeedRef { commit_id: U64(1), seed_index: 0 });
    // Commit 1 follows.
    call("operator.testnet", 0);
    let _ = a.post_batch("b2".into(), vec![later], rows(), false);
    assert_eq!(a.state().next_seed, SeedRef { commit_id: U64(1), seed_index: 1 });
}

/// The same secret can't be committed twice.
#[test]
fn m2_a_repeated_secret_is_refused() {
    let mut a = setup(None);
    call("operator.testnet", 0);
    a.commit_seeds("cd".repeat(32), 5);
    let ctx = call("operator.testnet", 0);
    assert!(refused(ctx, &mut a, |x| x.commit_seeds("cd".repeat(32), 5)).contains("secret already committed"));
}
