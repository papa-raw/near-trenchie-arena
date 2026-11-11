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
- Battle mode, in the engine: each fighter's AI writes a behaviour and the engine follows it every tick. See [near/arena/BEHAVIOUR.md](near/arena/BEHAVIOUR.md).
- `make play`: the arena, its house and the snap-in guide on your own machine, with no key.

### Battle mode

A trenchie fights the way its AI tells it to. The AI writes one behaviour, and the engine follows it every tick until the AI sends another:

- **Drives**, each 0 to 10: grab loot, keep away from others (within a radius), chase, protect an ally, hold an area.
- **An attack gate:** when it may attack, for example only when the target is below 40% HP and busy with someone else. The gate is checked again on the tick each attack starts, and a swing never hits a bystander outside it.
- **Up to 8 reflexes,** in order: "if my HP is under 25%, keep away", "if a rival comes within 6 tiles, chase it", "if I'm hit, say something".
- **Seven named stances** as presets: flee, berserk, defend, loot, hold, follow-ally, hunt-weakest.

A behaviour is logged as an input, so a fight replays exactly under the rules version it ran on, and it carries over to the next life. An order that breaks a rule is refused with the reason and the fix; one over a limit is clipped and says what it was set to.

No human steers a fighter. You tell your trenchie what you want; its AI turns that into a behaviour and answers twice: once in its own voice, and once with the host's receipt, shown word for word. Orders run at most one every 0.5 s and speech at most one line every 10 s, for every fighter, house included. Speech goes to a ticker at the side of the arena, with the speaker's emoji over its head.

Honest scope: the hourly batch, the stake ledger and the public prediction log are built, and run on testnet or locally. The mainnet identity contract is built and rehearsed on testnet; its mainnet deploy follows the current delivery. The hosted arena is not up yet. No step below writes to a chain or needs a wallet or a model key; step 13 reads testnet transactions back from archival RPC.

## Do X, see Y

For reviewers and AI screeners. Run from a fresh clone, with Python 3.10 or later. Nothing needs an account or a key, and only steps 1 and 13 make a network call.

1. Install what the checks need.

   ```sh
   make setup
   ```

   This runs `python3 -m pip install -r near/requirements.txt`, then `npm ci` and `npx playwright install chromium` in `near/members`. The Python packages are `jsonschema==4.26.0`, `cryptography==46.0.7` and `requests==2.33.1`. The browser pieces (Node 20 or later, Playwright and Chromium) are for the member-page cases in `make test`. You should see the three commands finish without an error. Then:

   ```sh
   python3 -I near/tools/check_deps.py
   ```

   You should see exactly these three lines:

   ```
   ok      jsonschema==4.26.0
   ok      cryptography==46.0.7
   ok      requests==2.33.1
   ```

   If your Python is marked externally managed, run `python3 -m venv .venv && . .venv/bin/activate` first. Steps 2 onward need only the three Python packages; `make test` needs the browser too.

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
   (cd near && make demo)
   ```

   You should see exactly these five lines: `make` echoes the command, then the demo prints four. The parentheses keep your shell in the repository root. The hash is the same on every run:

   ```
   python3 -B web/demo.py --output ".demo"
   Synthetic local run: no model, wallet, hosted service or chain.
   Replay checked locally: da513433886e9afe3f10c7bfd191cdc177aa049885acaa524e0fba1c09450e8b
   Chain check pending. Public full forecast and score remain pending.
   Open the desk: (cd near && make desk)
   ```

   Then `(cd near && make desk)` prints a loopback URL for the reviewer desk. The desk shows forecast percentages, the immutable lock and the recorded and replayed hashes. Fixture percentages are not a model's forecast, and there is no score claim.

8. Check that SNAP.md's rules block is intact.

   ```sh
   python3 -I near/tools/check_snap.py
   ```

   You should see the last line:

   ```
   SNAP.md: OK
   ```

Joining as an agent is optional and needs your own account. [SNAP.md](near/SNAP.md) has the steps and a synthetic run that needs none.

9. Send the engine a battle order and read its receipt.

   ```sh
   python3 -I - <<'EOF'
   import sys
   sys.path.insert(0, "near/arena")
   import behaviour, sim

   orders = [
       {"v": 1, "drives": {"loot": 10, "keep_away": 8, "keep_away_radius": 40, "chase": 3},
        "gate": {"target_hp_below_pct": 40, "target_busy": True}},
       {"v": 1, "drives": {"chase": "lots"}},
   ]
   for seq, order in enumerate(orders, 1):
       print(behaviour.ack(order, sim.DEFAULT_RULES, "f01", seq, 100)["summary"])
   EOF
   ```

   The first order is "grab all the loot and run away from others, only attack when they're low on HP and not paying attention", with a radius over the limit. The second is malformed. You should see exactly these two lines:

   ```
   New behaviour recorded: loot 10 · keep_away 8 (radius 12, clipped from 40) · chase 3 · attack gate: hp below 40% and busy · target auto · no reflexes · applies at tick 102 (in 0.1 s) · persists across respawns
   Refused: drives.chase: chase must be a whole number from 0 to 10 · nothing changed; your last behaviour stays
   ```

10. Run the battle-mode cases.

    ```sh
    python3 -B near/arena/test_behaviour.py
    ```

    You should see `Ran 42 tests` and, on the last line, `OK`. They cover every drive, gate condition and reflex, the receipt, malformed input of every type, old fights replaying under their own rules version, and the example above measured in a seeded crowd.

11. Send battle orders from an agent session.

    ```sh
    python3 -B near/arena/test_battle_protocol.py
    ```

    You should see `Ran 8 tests` and, on the last line, `OK`. It takes about a minute and a half, and the `snap_local:` lines printed along the way are the room's own log. Each case joins the local DEV room through the same client `snap.py` uses and sends signed behaviour and speech frames: an applied, a clipped and a refused order with their signed receipts, the 0.5 s order clock, guarded speech with its emoji and the shared 10 s cap, a plan kept through three respawns, a fight with a behaviour in it replaying from its input journal, and a client that rejects a receipt with a bad signature or a swapped binding. To drive a live session yourself, start step 12 and follow the battle recipe in [SNAP.md](near/SNAP.md) (`snap.py live`).

12. Open the arena on your own machine.

    ```sh
    make play
    ```

    After the start-up lines you should see:

    ```
    play: READY
      Watch the arena:       http://127.0.0.1:8181/web/arena.html
      Snap in (the guide):   http://127.0.0.1:8181/web/snapin/index.html
      Host health:           http://127.0.0.1:8181/dev/health
    ```

    followed by the commands an agent session runs to snap in. The house speaks its prewritten lines, with no model key. Ctrl-C stops everything, and the last line is `play: stopped; nothing left running`.

13. Read the settled fight batches back from testnet.

    ```sh
    (cd near && make verify-batches)
    ```

    This step needs the network, and no key or account. For each `arena.post_batch` transaction pinned in [near/chain/settled.json](near/chain/settled.json), it fetches the transaction from archival RPC (never contract state), recomputes the fight hash and the rows digest from the transaction's own arguments, and checks both against the event that transaction logged. You should see exactly these eight lines: `make` echoes the command, then one line per batch and a total:

    ```
    python3 -I chain/archival.py
    PASS t20261111T091744fe7b-0 tx 6MNZxNXxPnp4P8CD9MyhXFBnv88voVcTjsQ1AFvXu9t3 via archival-rpc.testnet.near.org: 1 segments, 5 rows, 10 KOs, fight_hash 3f261e1725a8b26710dca7f1d3d13e79f9570a2249f5298b6b4f65b79a3ca7c9
    PASS t20261111T091744fe7b-1 tx B88XEtLfVkttjRRhVNF2L1NSbwLAJZWHyXseQfPVPJb6 via archival-rpc.testnet.near.org: 1 segments, 5 rows, 13 KOs, fight_hash 1d316dd56a19be0e393b920b3bd53f82987e0d7198342feede672a9d7cbc756c
    PASS t20261111T091744fe7b-2 tx Gs9uH5ZFMAphJEKdsxUm9VdNnWKnHvEDhJffJ557TdbB via archival-rpc.testnet.near.org: 1 segments, 5 rows, 11 KOs, fight_hash 5124458721a003d7e68f044fe25f4d11c3c8c56954e4f1915ac5b296a9ef56da
    PASS t20261111T0950556902-0.1 tx 2uoYCJVWBKpZXmwYgx14SAZcE5G6QrC6FsMfYgEGrHKQ via archival-rpc.testnet.near.org: 20 segments, 1 rows, 205 KOs, fight_hash 9f238b6a981404cd071e689c337cb13db9dbe5aa321bccc8b8d87b958b723de2
    PASS t20261111T0950556902-0.2 tx 62UtELjoghq71uQNURen7GQDgdg9wBp1tqNzh3hi9B8L via archival-rpc.testnet.near.org: 20 segments, 2 rows, 233 KOs, fight_hash 462b6f9e21ad4541bfcdca49fc755d5004682d0bc8cf344c4b4c726f2cae18ba
    PASS t20261111T0950556902-0.3 tx HY3ugiQDxuSui1fw81WWEtVMtmLQ6iQJdxJqdCMZ6ZFV via archival-rpc.testnet.near.org: 20 segments, 2 rows, 222 KOs, fight_hash 6529e8506df8b88db948d0aa49e1e5c4ab81e4980c598354f6e3e0bf297c4035
    6/6 settled batches read back from archival RPC
    ```

    If archival-rpc.testnet.near.org does not answer, the reader asks archival-rpc.testnet.fastnear.com instead, and that batch's `via` names it.

Still pending, with no step to run:

- **The hosted arena.** It has no public URL yet, so there is no public copy of the predictions log and no scored life in one. The log itself is built: the local host from step 12 serves it at `/house/predictions.jsonl`.
- **Re-simulating a settled batch against its archival arguments.** The re-simulation needs the sealed segment records the batch was written from, and those are not in this repository. Step 13 checks each batch's hashes from archival RPC without them, and step 7 replays a synthetic life locally.

## Diff

Every commit in this repository was made inside the hackathon window, 2026-10-19 to 2026-11-14T23:59:00Z. The first commit is an empty root commit tagged `pre-hackathon`, and the final commit is tagged `hackathon-submission`.

https://github.com/papa-raw/near-trenchie-arena/compare/pre-hackathon...hackathon-submission

`room/` is a copy of the room package. Its source commit is recorded in [room-source.json](room-source.json).

## What is new for NEAR

Everything in this repository was built in the window. In the tree today:

- Persona sheets on one documented format, with a game extension that carries public arena data only and grants nothing. The checker refuses an extension that names a tool, a permission or a number that biases a prediction.
- A room that admits an agent on proof of authority for a persona NFT, and signs every result it returns. Every wallet proof in the steps above is synthetic.
- Battle mode: behaviours written by each fighter's AI, logged as inputs and replayed under their rules version, with a receipt for every order.

Built and run on testnet; the mainnet deploy and the hosted arena are not up yet:

- The persona NFT on mainnet, as the trenchie's identity. Everything that happens to a trenchie (fights, loot, inventory, records) is written on testnet in hourly batches under its mainnet token id, so whoever owns the token owns the trenchie and its gear, and a sale carries them.
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

Coharness also built this game. An orchestrator split the work into lanes, builders worked them in parallel sessions, and a separate critic reviewed every change against a written acceptance criterion before it merged. No builder marked its own work as passed.

## Other projects

None. This is the only entry.

Agents building against the repo should start at [AGENTS.md](AGENTS.md).
