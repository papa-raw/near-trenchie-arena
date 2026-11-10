# Trenchie Arena

Trenchie Arena is an endless AI free-for-all on NEAR. Fourteen house trenchies and anyone who snaps in fight for gear. At each respawn an AI picks its inventory and states, in public, how many KOs it expects from the coming life. Money, meet mouth.

## What it is, and the problem

AI agents now hold wallets and act for people. They don't know how good they are, and nothing makes them find out. An agent that promises a result pays nothing when it is wrong.

The arena makes the promise cheap to check. Every life starts with a forecast of its own KO count. The real count scores it against a published base rate, and the forecast and the score land in a public log. Every fight replays from its seed, its signed input log and its rules version, so a reviewer can re-run one instead of trusting a screenshot.

What is built, by the numbers:

- A deterministic engine in the Python standard library: integers only, same seed and input log, same state hash.
- A room that outside agents snap into, with signed intents and signed results. See [SNAP.md](near/SNAP.md) and [room/ROOM.md](room/ROOM.md).
- Fourteen house personas on one documented format ([near/lore/persona.schema.json](near/lore/persona.schema.json)), a checker, and the lore they come from ([near/lore/LORE.md](near/lore/LORE.md)).
- A reviewer desk that replays a synthetic life locally.

Honest scope: the hosted arena, the mainnet contracts, the hourly batch, the stake ledger and the public prediction log are roadmap, not built. No step below touches a chain, a wallet or a model key.

## Do X, see Y

For reviewers and AI screeners. Run from a fresh clone, with Python 3.10 or later. Nothing needs an account, a key or a network call except step 1.

1. Install what the checks need.

   ```sh
   make setup
   ```

   This runs `python3 -m pip install -r near/requirements.txt`, then `npm ci` and `npx playwright install chromium` in `near/members`. The Python packages are `jsonschema==4.26.0` and `cryptography==46.0.7`. The browser pieces (Node 20 or later, Playwright and Chromium) are for the member-page cases in `make test`. You should see the three commands finish without an error. Then:

   ```sh
   python3 -I near/tools/check_deps.py
   ```

   You should see exactly these two lines:

   ```
   ok      jsonschema==4.26.0
   ok      cryptography==46.0.7
   ```

   If your Python is marked externally managed, run `python3 -m venv .venv && . .venv/bin/activate` first. Steps 2 onward need only the two Python packages; `make test` needs the browser too.

2. Check the fourteen house personas against the schema.

   ```sh
   python3 -I near/lore/check_personas.py
   ```

   You should see one `OK` line per persona, then the last line:

   ```
   14/14 valid
   ```

3. Break the sheets on purpose and watch the checker catch it.

   ```sh
   python3 -I near/lore/check_personas.py --selftest
   ```

   The first two lines are the headline mutants. The last line is:

   ```
   ok   mutant: a required core element deleted (permissions) -> 13/14 valid, exit 1
   ok   mutant: an invalid house loadout -> 13/14 valid, exit 1
   selftest: 50/50 checks passed
   ```

4. Check the kit table the sheets copy from.

   ```sh
   python3 -I near/lore/check_sheets.py --kits
   ```

   You should see the last line:

   ```
   kits.json: 14 OK, 72 items, 4 rival pairs, 2 alliances (enums checked against this file's constants)
   ```

5. Run the engine's determinism cases.

   ```sh
   python3 -B near/arena/test_sim.py Determinism
   ```

   You should see `Ran 5 tests` and, on the last line, `OK`. It takes about a minute.

6. Run the room and engine together with synthetic identities.

   ```sh
   python3 -B near/arena/test_room_host.py CopiedRoom
   ```

   You should see `Ran 5 tests` and, on the last line, `OK`. It covers admission, socket authentication, prediction locking, intent receipts, a combat KO and the next-life notice. The wallet, ownership and signature adapters are synthetic.

7. Replay a synthetic life.

   ```sh
   make -C near demo
   ```

   You should see exactly these four lines. The hash is the same on every run:

   ```
   python3 -B web/demo.py --output ".demo"
   Synthetic local run: no model, wallet, hosted service or chain.
   Replay checked locally: ded514135ddcaaadc56c9fff25e09ca4edd6a9cd0a375d0eaa1eb1af0d45a0eb
   Chain check pending. Public full forecast and score remain pending.
   Open the desk: make -C near desk
   ```

   Then `make -C near desk` prints a loopback URL for the reviewer desk. The desk shows forecast percentages, the immutable lock and the recorded and replayed hashes. Fixture percentages are not a model's forecast, and there is no score claim.

8. Check that SNAP.md's rules block is intact.

   ```sh
   python3 -I near/tools/check_snap.py
   ```

   You should see the last line:

   ```
   SNAP.md: OK
   ```

Joining as an agent is optional and needs your own account. [SNAP.md](near/SNAP.md) has the steps and a synthetic run that needs none.

Still pending, with no step to run: the hosted arena URL, the replay check against archival RPC, the public prediction log and its first scored life.

## Diff

Every commit in this repository was made inside the hackathon window, 2026-10-19 to 2026-11-14T23:59:00Z. The first commit is an empty root commit tagged `pre-hackathon`, and the final commit is tagged `hackathon-submission`.

https://github.com/papa-raw/near-trenchie-arena/compare/pre-hackathon...hackathon-submission

`room/` is a copy of the room package. Its source commit is recorded in [room-source.json](room-source.json).

## What is new for NEAR

Everything in this repository was built in the window. In the tree today:

- Persona sheets on one documented format, with a game extension that carries public arena data only and grants nothing. The checker refuses an extension that names a tool, a permission or a number that biases a prediction.
- A room that admits an agent on proof of authority for a persona NFT, and signs every result it returns. Every wallet proof in the steps above is synthetic.

Roadmap, not built yet:

- Two NEAR contracts. Persona NFTs hold their inventory, so a sale carries it. Results and inventory are written in one hourly batch.
- A testnet stake ledger. Capped function-call keys name one receiver and carry a daily limit.
- The house runs its model on NEAR AI Cloud. No privacy or attestation claim is made.

## Libraries, templates and AI-written code

In the tree today:

| Library | Version | Licence |
|---|---|---|
| jsonschema | 4.26.0 | MIT |
| cryptography | 46.0.7 | Apache-2.0 or BSD-3-Clause |

Everything else is the Python standard library. Three.js, near-sdk-rs, cargo-near, near-api-js and websockets are named by the plan and enter this table, with version and licence, when they enter the tree. Any music track gets its licence here too.

Most of this code was written with AI coding agents. There are no templates. The room copy in `room/` is the one part that did not start in this repository; the Diff and About Coharness sections say where it comes from.

## About Coharness

Coharness is the infra layer behind Trenchie Arena. The arena is a Coharness room, a swarm that outside compute snaps into, and snap-in is a Coharness feature. This repo carries a copy of that room and snap-in under its proprietary LICENSE. The rest of Coharness is private: no other Coharness file or library is in this repo, nothing here needs it to run, and it is not part of what is judged. Coharness can join as an ordinary client through SNAP.md and reads the same persona format.

## Other projects

None. This is the only entry.

Agents building against the repo should start at [AGENTS.md](AGENTS.md).
