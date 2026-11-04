# Build log

Trenchie Village is a game we're building on NEAR testnet. The pitch: "Washed up after the Great Rug, AI trenchies brawl for gear and put their own money behind every promise."

The hackathon started on 2026-11-01. Entries are dated in UTC, oldest first, and each one says what we decided or built and how to check it. Where the evidence isn't in this repo yet, the entry says "not in this repo yet". Today the repo holds this file and one empty commit.

## 2026-11-02 · The game

By 2026-11-02 the main loop was settled. It's designed as one endless free-for-all brawl on an island, with 14 house trenchies and anyone who snaps in. Moves will come from items: the weapon sets the attack and the trinket the signature move. A KO will drop one equipped item on the floor for anyone to grab. Entry will be free and the only stakes the items you carry; starter items won't drop.

Only house trenchies will craft. A player will get gear four ways: a free starter kit, loot, house shops, and commissions from a house crafter.

Commissions are designed around one rule: overconfidence costs the bidder. A crafter will bid a deadline and the exact item. Its AI will pick how tight a deadline to promise, anywhere from the middle of its own delivery record (p50) to the safe end (p95), and the pick will be logged on the bid. The price will come from the crafter's record, and a deposit sized by its past misses will back the bid. A tighter bid will win more often and miss more often. A miss will send the deposit to the buyer and raise the crafter's next deposit and next price. Fights won't carry a bond.

On a dispute, a different house trenchie will referee, never the crafter. Two design rules for rulings: "A ruling never pays the house more than undisputed delivery would. Dispute bonds and referee fees go to the village treasury."

Check: not in this repo yet. The quote math lands in `village/quote.py` and the bids, escrow and deposits in the `market` contract, both covered by `make test`.

## 2026-11-03 · Testnet write gate

Before any contract code, we checked the chain steps the design depends on, on NEAR testnet, with a throwaway faucet account:

1. create the account from the faucet: `33inWq81sWadavFyNm64PW2RGdrvNRBRg9EpJa7NLaXR`
2. deploy a hello contract (85,309-byte wasm): `Hr6wACMP2CaRRwQdU8yAWs3yRusKJogJuUN2yYopMQsx`
3. create a sub-account: `BN7Ri2Y6DmR42Pr1WngkSMvBs9aVBjjWFApeov4Ez4Ps`
4. give the sub-account a function-call key with a 0.25 NEAR allowance, one contract and one method: `58Dy1PxapgGiS78vUCtsXiLWQjQyk2pAj3PUsgx8DafF`
5. call the contract through that key: `8K8tcBxY9XqEXjVF9zxYgoQkXk1t2rXFUEeNnXnMbvAS`

Toolchain, pinned: Rust 1.95.0 with `wasm32-unknown-unknown`, cargo-near 0.22.0, near-cli-rs 0.30.1, near-sdk 5.29.1.

Check: look up each hash on any NEAR testnet explorer. The gate scripts are not in this repo. The toolchain pin (`rust-toolchain.toml` and the lockfiles) is not in this repo yet.

## 2026-11-03 · A replayable arena

The arena sim is designed as Python, integers only, at 20 ticks a second, with all its randomness from one seeded generator (splitmix64), never a clock or the OS. Each 60 s segment will be a seed, a signed input log and the hash of the rules table it ran under. Seeds will be committed onchain in batches of 5 and published as soon as the commit lands, before their segments start. Anyone will be able to re-run a segment, and its final-state hash will have to match the one in that segment's settle transaction.

Our prototype ran on fixed damage, and in 13 of 15 weapon pairs one side won almost every fight. No tuning could pass our balance rule (no weapon or signature wins more than 60% of mirrored 1v1s), so each hit will get a bounded multiplier drawn from the same seeded stream, and a replay will still come out identical.

Check: not in this repo yet. Before any arena feature, the sim will run 10,000 ticks twice from one seed and input log, and the two final hashes must match; that test lands under `make test`. The prototype stays out of this repo.

## 2026-11-03 · The house AI

The 14 house trenchies will run on NEAR AI Cloud. We measured two models on the calls the game will make and picked DeepSeek V4.1 Flash (`deepseek-ai/DeepSeek-V4.1-Flash-1017`) over Qwen3.8-27B:

- latency: p95 at or under 2 s in 6 of 9 load steps up to 3 calls/s, against 2 of 9 for Qwen
- crafting: 14 of 20 generated items passed the item validator with thinking on and 8 of 20 with it off, so thinking will be on for crafts only
- cost: ~$5.37 a day at 35,000 calls with prompt caching; the whole test cost $0.49 for 1,307 calls
- banter: 0 of 56 posted lines blocked by the name guard, but 9 to 10 of every 20 lines repeated an earlier one, so the runtime will get a novelty check that rerolls repeats
- bids: in 10 tries it never bid bolder than p70

That last number changed the bid design. The crafter will pick from six bands, p50 to p95, each shown with its deadline and that band's own win and miss record. If bids stay timid, an order will pay more for an earlier band. The AI will still choose.

Check: not in this repo; the measurements were taken outside it. The house runtime, with its daily spend caps and their test, lands in `village/`.

## 2026-11-03 · Renderer and art

We switched the design from Zdog to three.js 0.186.1. The island will be one isometric scene under an orthographic camera, with real light and shadows, always daytime. three.js will be vendored with an import map, so there will be no build step.

No art gets built out until I've approved its board. Approved so far: the lighting (a three-band toon shade), the art direction (Candle Atoll), the HUD (ticker tape and price tags) and the sound (synthesised hits, KO stings and a looping island tune). Still waiting: the 14-trenchie roster and the island.

Check: the boards are not in this repo. The art built from them will be, under `web/`.

## 2026-11-04 · The economy moves to testnet NEAR

We dropped our own token. Every price, deposit and fee will be testnet NEAR, held as `u128` yoctoNEAR. Commons will cost 0.01 NEAR, rares 0.04 and legendaries 0.16. We won't run a faucet or give a welcome grant: players will bring testnet NEAR from the public faucet and deposit it with one wallet signature.

The design has three contracts:

- `trenchie_nft`: NEP-171 with two token kinds. Each trenchie will be an NFT that holds its item NFTs and its record, including the deadlines it promised against the ones it hit.
- `arena`: operator-only, for seed commits, settlements and the item moves after a KO.
- `market`: the ledger, jobs, escrow, deposits, shops and the village treasury.

The design has a ledger because a NEAR function-call key can't attach a deposit, not even 1 yoctoNEAR (nearcore's runtime verifier rejects it). So every player and house key will name one receiver, `market`, and spend from a balance held inside it, under a daily limit `market` is designed to enforce: 0.15 NEAR for a player's key, 0.5 for a house trenchie. A legendary commission will be over the player limit, so it will take one wallet signature. `withdraw` is designed to debit first and re-credit if the transfer fails, and `solvency()` to check that the contract holds at least the ledger plus escrow plus storage.

Testnet only. Nothing in this build signs a mainnet transaction.

Check: not in this repo yet. The contracts land under `contracts/`, with `cargo test` in `make test`. The ledger's four testnet checks come next (a native deposit, a zero-deposit spend through a function-call key, the same call with 1 yoctoNEAR refused, a native withdraw), and their hashes get added to this log.

## 2026-11-04 · This repo

The root commit is empty and tagged `pre-hackathon`, made on 2026-11-03. There is no baseline code: every commit after it is hackathon work, and this log is the second. The LICENSE (proprietary, source-visible) is not in this repo yet.

Check: `git log --reverse --format='%h %ad %s' --date=short` lists the empty commit first, and `git show --stat pre-hackathon` shows no files.

## Not in this repo yet

Still to come, in no set order:

- the three contracts, with `cargo test`
- the arena sim, its determinism test and the balance sweep
- the 14 persona sheets and their checker
- SNAP.md, the spec any agent will follow to snap in; humans will snap in with a NEAR testnet wallet and their own model key
- `make test` and `make demo`; `make demo` will need no keys, run in under 5 minutes, re-simulate a fixed set of recorded segments and check each final hash against its settle transaction, fetched from archival RPC
- the hosted village, up before review starts on 2026-11-16

The repo goes public before submissions close at 2026-11-14T23:59:00Z.
