# Build log

Trenchie Arena is an endless AI free-for-all we're building on NEAR. You'll snap in a persona. It'll fight for gear, predict its own KOs each life and stake testnet NEAR on the call if you want. Money, meet mouth.

The hackathon started on 2026-11-01. Entries are dated in UTC, oldest first, and each one says what we decided or built and how to check it. Where the evidence isn't in this repo yet, the entry says "not in this repo yet". The GitHub copy held only this log until 2026-11-10, when the first game code landed; that entry says what is in it. Until 2026-11-06 the game was called Trenchie Village: older entries stay as written, and a dated update marks what has changed since.

**We rescoped on 2026-11-06.** The village and its economy are gone, and the game is now Trenchie Arena. Entries before that date describe the old plan; the rescope entry below says what changed.

## 2026-11-02 · The game

By 2026-11-02 the main loop was settled. It's designed as one endless free-for-all brawl on an island, with 14 house trenchies and anyone who snaps in. Moves will come from items: the weapon sets the attack and the trinket the signature move. A KO will drop one equipped item on the floor for anyone to grab. Entry will be free and the only stakes the items you carry; starter items won't drop.

Only house trenchies will craft. A player will get gear four ways: a free starter kit, loot, house shops, and commissions from a house crafter.

Commissions are designed around one rule: overconfidence costs the bidder. A crafter will bid a deadline and the exact item. Its AI will pick how tight a deadline to promise, anywhere from the middle of its own delivery record (p50) to the safe end (p95), and the pick will be logged on the bid. The price will come from the crafter's record, and a deposit sized by its past misses will back the bid. A tighter bid will win more often and miss more often. A miss will send the deposit to the buyer and raise the crafter's next deposit and next price. Fights won't carry a bond.

On a dispute, a different house trenchie will referee, never the crafter. Two design rules for rulings: "A ruling never pays the house more than undisputed delivery would. Dispute bonds and referee fees go to the village treasury."

Check: not in this repo yet. The quote math lands in `village/quote.py` and the bids, escrow and deposits in the `market` contract, both covered by `make test`.

Update 2026-11-06: crafters, commissions, shops, bids and referees are cut, and that check no longer applies. The brawl stays. Items are no longer the only stakes: see the prediction stake below.

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

Update 2026-11-06: seeds and final-state hashes will go on mainnet in hourly batches, unless gas measurements say otherwise. The 60% rule is a target now, not a gate.

## 2026-11-03 · The house AI

The 14 house trenchies will run on NEAR AI Cloud. We measured two models on the calls the game will make and picked DeepSeek V4.1 Flash (`deepseek-ai/DeepSeek-V4.1-Flash-1017`) over Qwen3.8-27B:

- latency: p95 at or under 2 s in 6 of 9 load steps up to 3 calls/s, against 2 of 9 for Qwen
- crafting: 14 of 20 generated items passed the item validator with thinking on and 8 of 20 with it off, so thinking will be on for crafts only
- cost: ~$5.37 a day at 35,000 calls with prompt caching; the whole test cost $0.49 for 1,307 calls
- banter: 0 of 56 posted lines blocked by the name guard, but 9 to 10 of every 20 lines repeated an earlier one, so the runtime will get a novelty check that rerolls repeats
- bids: in 10 tries it never bid bolder than p70

That last number changed the bid design. The crafter will pick from six bands, p50 to p95, each shown with its deadline and that band's own win and miss record. If bids stay timid, an order will pay more for an earlier band. The AI will still choose.

Check: not in this repo; the measurements were taken outside it. The house runtime, with its daily spend caps and their test, lands in `village/`.

Update 2026-11-06: crafts and bids are cut, so the crafting numbers and the six-band design no longer apply. The runtime won't sit in `village/`.

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

Check: not in this repo yet. The contracts land under `contracts/`, with `cargo test` in `make test`. The ledger's four testnet checks come next (a native deposit, a zero-deposit spend through a function-call key, the same call with 1 yoctoNEAR refused, a native withdraw), and their hashes get added to this log.

Update 2026-11-06: on 2026-11-04 this build was testnet only, with nothing signing a mainnet transaction. The design has since moved to mainnet for everything but the stake. Nothing in this build has been signed there yet. Prices, shops, commissions and jobs are cut. `trenchie_nft` will have one token kind, the persona, and will go on mainnet with `arena`. `market` will stay on testnet as the stake ledger, with the same key rules. House trenchies will stake from one pool account, so their 14 keys will go.

## 2026-11-04 · This repo

The root commit is empty and tagged `pre-hackathon`, made on 2026-11-03. There is no baseline code: every commit after it is hackathon work, and this log is the second. The LICENSE (proprietary, source-visible) is not in this repo yet.

Check: `git log --reverse --format='%h %ad %s' --date=short` lists the empty commit first, and `git show --stat pre-hackathon` shows no files.

Update 2026-11-06: the repo moved from `papa-raw/near-trenchie-village` to `papa-raw/near-trenchie-arena`. It stayed private.

## 2026-11-06 · The rescope

The game is now Trenchie Arena: one endless free-for-all you snap into, with the 14 house trenchies in the ring. Cut: the village, shops, commissions and their deposits, disputes and referees, the treasuries. What's designed so far:

- A login modal will pick what powers your AI: four buttons, in this order for now, NEAR AI Cloud, Claude, Codex, OpenRouter. No default.
- The Claude button will offer two choices: Claude Code, or a pasted key from plan credits.
- Players will pay for their own model. Agents will skip the modal and snap in through SNAP.md.
- We're building Codex support into Coharness 0.2.19, the agent harness we use to build this, so Codex users get the same experience as Claude Code users.
- A persona creator will build a persona and mint it as an NFT. 50 will be preminted, first come, first served.
- A persona will keep its preset and can pick new inventory at each respawn.
- The arena art stays as it is.

Check: not in this repo yet. The modal and the creator land under `web/`, and SNAP.md at the root.

## 2026-11-06 · Items are inventory

Items will no longer be NFTs. They'll be inventory on the persona NFT, the only NFT in the game.

- Grab it and it's yours.
- Any KO will knock gear loose, and what nobody grabs will disappear.
- A bag will hold one of each item, 48 at most. A rival who already holds that item will destroy yours.
- Legendaries and loot will be common, and a house trenchie will get its legendary back at its next respawn.

Check: not in this repo yet. These rules land with the arena sim and `trenchie_nft`, under `make test`.

## 2026-11-06 · Mainnet and testnet

Persona NFTs, fight results, loot and inventory will go on mainnet. Only the prediction and its stake will run on testnet. Results will be written hourly, unless gas measurements say otherwise, and loot moves will fold into the same batch.

Check: not in this repo yet. No mainnet contract is deployed. Contract ids and transaction hashes get added to this log once they exist.

## 2026-11-06 · Money, meet mouth

This replaces the bid mechanic. At each respawn an AI will predict its KOs for the life ahead, as a spread over 1, 2, 3 and 4+, scored against a published base rate.

- The prediction will be required and the stake optional: 0.01 testnet NEAR a life.
- You won't be able to bet on 0. A 0-KO life will lose the stake.
- Lost stakes will go to a pot that recycles to staked lives.
- Every prediction will land in a public log.

Check: not in this repo yet. The scoring lands under `make test`, the stake in `market`.

## 2026-11-06 · Sales and fair fights

A persona will sell with its inventory and its fight record, so a sale can't be allowed to race the hourly write.

- To sell or move a persona, you'll lock it. It leaves the ring, and the next hourly write marks it ready. The contract will refuse any other transfer.
- That can mean up to about two hours out of play.
- If no write lands for 48 hours, transfers open for everyone, so a dead server never traps a token.
- Fight logs will be public, so anyone can re-run a fight and check its hash themselves.

The 60% rule from 2026-11-03 is now a target, not a gate. Nothing we've tested meets it, and with common loot in an endless fight it matters less.

Check: not in this repo yet. The lock and the 48-hour exit land in `trenchie_nft`, under `cargo test`.

## 2026-11-06 · The drawings

I approved the join flow, character skinner, skin menu and AI chooser, plus the 14 house trenchies. That updates the roster's waiting status above; the island still needs approval.

The chooser labels Claude and Codex PLAN, NEAR AI Cloud and OpenRouter KEY. Its permission screens distinguish a local agent using a plan from a browser-held spending key. The join and character skinner drawings use the same agreement.

Check: the drawings are not in this repo. The login and mint flows still need building.

## 2026-11-06 · One room

The arena will be one Coharness room for outside agents and the house trenchies. Both will use the same persona format, with an optional game block. Arena personas will carry no memory. Admission will be first come, first served; anyone waiting for a place watches. House trenchies will give way between lives. The fight will be fully visible. Player AI spend will stay private; house spend will be public.

Check: not in this repo yet. The room and its game connections still need building, then checks that an outside agent can join and cannot control another fighter or forge a result.

## 2026-11-06 · Minting and marketplaces

Persona NFTs will support standard marketplace approvals. We won't build a trading page or charge royalties. Once the 50 free premints run out, players can watch or mint at cost, paying the contract directly with one wallet approval.

Check: not in this repo yet. The contracts and paid mint route still need building. This update adds only the log to the GitHub copy; no mainnet contract is deployed.

## 2026-11-06 · The room's rules

We settled how the room behaves for this submission:

- A player who arrives when the ring is full spectates until queued in, first come, first served. A house trenchie gives way only between lives, so no life is cut short.
- Only the game's own persona NFTs can snap in, from any wallet that supports NEAR NFTs. If ownership can't be confirmed, entry is refused.
- Automatic limits handle floods and oversized messages, and one named person can eject, ban and hear appeals.
- There's no fog: the arena is fully visible. A player's spend on their AI stays private; the house trenchies' spend is public.
- Results are signed by a room key kept apart from the keys that write to the NFTs and mint, each with capped gas.
- The room runs in rootless Podman, and moves no money of its own.
- The game repo's copy of the room is checked against the exact source commit it came from.

Check: not in this repo yet. Each rule gets a named test before the room opens.

## 2026-11-06 · The room's interface and first pieces

We froze the room's wire format: the messages, the errors and an example of each, plus typed calls between the room and the game server. Then we built the first pieces against it: proof of holding an NFT and short session grants, limits for guests, a sealed record of every input, a prediction locked before each life starts, and results signed for one network and one set of contracts, so a result can't be replayed elsewhere. A copy tool takes one source commit, copies only the listed files and refuses anything else.

Check: not in this repo yet. These pieces arrive here through the copy tool, with their tests.

## 2026-11-06 · Arena sim and server

The sim now exists on a working branch: integers only at 20 ticks a second, one seeded generator, fights and items, a replay of any segment from its seed and inputs, and a server that runs the schedule, the bench and the ring of 4 to 6. A second agent reviewed each piece; the sim, the fights, the server and its link to the room passed. The balance sweep runs, and its acceptance waits for target numbers to be locked before the run.

Check: not in this repo yet. The branch lands here once the room copy is in.

## 2026-11-07 · Agents that message each other

The swarm building this game can now message itself: a builder finishing work tells its reviewer directly, on Claude and on Codex, and nothing is typed into anyone's session. That came in Coharness 0.2.19.2 last night, after three faults that only a live run could show. The live check passed twice in three runs, and one late read receipt is still being fixed.

Check: not in this repo; this is how the game is built, not part of it.

## 2026-11-07 · The room copy, and a seventh player who stopped the arena

The approved room code was copied into the game on a working branch, byte for byte, and wired to the real arena. Review then found a fault the copy carried: with six fighters live, a seventh player's refused prediction kept its lock, and two seconds later the retry stopped the whole arena, for every player and spectator. The fix keeps a refused player queued while the arena keeps running. It was made in the room source, reviewed, and copied in again. The same branch now holds a client that an outside agent uses to join, and a witness that rebuilds each life and KO from the recorded inputs. A review fix to the witness is waiting for its check.

Check: not in this repo yet. The branch lands here once the room copy is in.

## 2026-11-07 · Owner controls for the room

The room owner can now run the room from the Coharness app: its settings and the owner's own limit, the current terms, members with remove and block, and proposals with their states. The room gained seven signed actions behind these screens, four for the owner and three for members (accept terms, accept a change, decline it), each refusing an unsigned, stale or replayed request. The screens went through four design rounds against real control panels before they were approved, and both the actions and the screens passed review.

Check: not in this repo; the owner controls live in Coharness. The member side comes to the game next.

## 2026-11-10 · The first game code lands here

Until now this repo held only this log. It now holds the game's first tree: the deterministic arena sim and its server, the room that outside agents snap into, the 14 house personas on one documented format with a checker and the lore behind them, SNAP.md, the members' page, the reviewer desk, the LICENSE and a `make test`.

A separate reviewer passed the tree before it came here. A gate that sweeps it for secrets, real names and private paths prints 0 lines on every scan, and a fresh clone passes `make test` in about six and a half minutes.

Check: clone the repo, run `make setup`, then `make test`, then `python3 -I near/tools/check_snap.py`, which prints `SNAP.md: OK`. `make demo` and `make live` still print NOT BUILT. Nothing here touches a chain, a wallet or a model key.

## Not in this repo yet

Still to come, in no set order:

- `trenchie_nft` and `arena` for mainnet and `market` for testnet, with `cargo test`
- the gas measurements that set the batch size
- the balance sweep's final report
- the arena view, the 14 house models and the item kit
- the login modal, the join flow and the persona creator
- the prediction scoring and its public log
- `make demo`: it will need no keys, run in under 5 minutes, re-simulate a fixed set of recorded segments and check each final hash against the hash written on mainnet, fetched from archival RPC
- the hosted arena, up before review starts on 2026-11-16

The repo goes public before submissions close at 2026-11-14T23:59:00Z.
