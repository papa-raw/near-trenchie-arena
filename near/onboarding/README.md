# Fight first, claim later

This local acceptance path connects a walletless visitor to the copied room and
the actual arena engine using game-owned custody evidence. Its contract adapter
is an in-process **testnet mock**. It has no RPC client, transaction signer,
network request or payment collection. It does not establish deployed wallet or
chain interoperability.

Install `near/requirements.txt` (it includes `near/onboarding/requirements.txt`), then run
`python3 -B near/onboarding/test_arrival.py Arrival` from the repository root.
`(cd near && make test-arrival)` selects the same four new cases. Normal source
checkouts must include the tracked `room/` copy.

## Runtime order

`runtime.FightFirstSession` holds an owner-supplied session signer, a pinned
`SnapClient`, and an explicit wallet callback. `begin()` allocates a held token
and joins through the ordinary room challenge/proof path. The visitor supplies
compute; this module never supplies house inference or collects model keys.
The owner runtime reads and explicitly accepts the arena rules, predicts and
fights using that client. No wallet callback runs along that path.
An interrupted admission can retry `begin()` on the same controller with the
same preset, request id, edge metadata and compute declaration. The native
client retains the exact signed join bytes, challenge and proof before POST.
If its accepted response is lost, retry replays those same bytes and verifies
the original receipt's signature, context and digest. It does not request a new
challenge or consume another custody-allocation quota. Native join proof
verification rechecks current custody; the original token, reservation and hold
expiry remain fixed. Holding a token is separate from successful admission;
an uncertain join never releases the hold. Changed bindings and a second begin
after successful admission refuse. Expired pending challenges refuse before
POST; native rate, grant and proof expiry limits are never extended. A later
expired session needs its separately proved reconciliation path.


The trusted engine host sends its completed-life record to
`ArrivalService.fight_seen`. Only then does the controller offer claim.
`claim()` invokes the wallet callback, obtains a one-use claim challenge and
submits both the visitor session signature and independently verified wallet
account-control proof. `stake_wallet()` is the other explicit wallet entry;
adding testnet NEAR to a prediction stays in its separate wallet flow. Wallet disconnection cannot
silently transfer a token.

This is the functional order and controller seam, not a new modal drawing.
The visual login-modal build remains dependent on its approved design reference.

## Custody and expiry

The mock starts with 50 already minted tokens: five fixed synthetic personas,
ten copies each, with empty bags. `contract.py` freezes those local presets.
They are fixtures, not a claim that production presets or NFT metadata are
implemented. Token selection and persisted quotas run in one SQLite
`BEGIN IMMEDIATE` transaction. Reopening the store retains inventory, hold
identity, original expiry and one-per-device/IP/session-per-day limits.
Device and IP values are trusted edge metadata, never arbitrary client fields.
These limits deter a single script; they do not establish one human per account.
Paid-wallet challenges share the 512-row short-lived challenge store, with a
persisted maximum of five per public key across recipient/preset choices and
64 paid-wallet rows across all keys. This leaves 448 rows for normal arrival
and claim; normal arrival retains its five-per-IP bound. TTL cleanup restores
capacity after 60 seconds. Limits run inside the same SQLite transaction as
challenge creation and survive a service restart.


A hold lasts **15 minutes**, long enough for a first fight and wallet handoff,
while bounding abandoned inventory. Identical signed retries preserve token and
expiry. At the deadline custody verification refuses immediately. A token
returns to the pool only when fresh contract state confirms custodian ownership
and `sale_ready`. Active or uncertain inventory stays quarantined. Fresh reads
must fail closed when ownership or chain state is unavailable.

The visitor principal is the lowercase hex Ed25519 session public key, matching
an implicit-address account shape. It is not evidence that an account has been
created onchain. Reservation state binds that principal to the exact token,
immutable persona digest, session key and expiry. `resolve_identity` verifies the
complete room join proof and fresh contract state on every authority check. It
returns `ownership_kind=custody`, never owner authority or sale permission.
The frozen room context carries mainnet metadata; the acceptance fixture uses
that unchanged schema as inert data with synthetic room keys and an explicitly
pinned mock NFT contract id. `bind_room` refuses this network mismatch by default;
only an explicit `allow_synthetic_context=True` with a synthetic contract adapter
permits this local fixture. A deployed testnet room needs its source-owned
network-context support; this code does not widen that wire contract. All contract code
paths stay in the testnet mock, with no mainnet operation.

A claim binds contract, network, hold, token, persona digest, recipient, nonce and
expiry. The wallet verifier must independently prove that exact recipient's
account control over the entire challenge. Neither proof alone can claim.
`claim` goes through the snap-minter port only after confirmed `sale_ready`.
An HTTP success is not confirmation: ownership is read back before returning
`claimed`. A durable `claiming` fence prevents expiry/reallocation after an
uncertain transfer. Re-proving the same target can reconcile a lost receipt.
Unknown transfer outcomes require adapter reconciliation and remain quarantined.
The mock models immediate confirmations; it does not implement hourly batching.

## Run-out and permit

The concurrent final-token case admits exactly one last hold. The next request
returns `paid_mint_required`, `All claimed`, count 50, a signed permit and the
exact persona; it creates no 51st held token. If only the selected preset is
exhausted, the label is `Preset unavailable` and the count reflects occupied
inventory. No request here accepts a deposit or payment credential.

Permit v1 bytes are the fixed `signing.PERMIT_FIELDS` sequence, each string
encoded as UTF-8 preceded by an unsigned 32-bit big-endian byte length. Fields
are domain, schema, key epoch, network, NFT contract, direct caller, exact name,
canonical immutable persona SHA-256, preset, nonce, issue and expiry times.
Missing/extra fields and nonstrings refuse. Permits last at most 60 seconds.
A dedicated injected Ed25519 signer has no wallet, mint or spending authority.
Its name guard must accept the exact final name before signing.

The mock independently checks signature, allowlisted key/current epoch, caller
and signer equality, pinned network/current contract, name/persona/preset,
issue/expiry/max TTL and unused nonce. It consumes nonce and mints atomically.
The synthetic cost is the string `100` yoctoNEAR, exclusively a test fixture.
Actual deployed pricing, storage, keys and contract execution remain outside
this local acceptance path. The direct caller in a run-out permit is the proved
implicit session principal. `paid_wallet_challenge` plus
`paid_wallet_permit` issue a fresh permit for a different wallet only after both
visitor and wallet proofs bind that caller; this module never rewrites
an already signed caller or sends a transaction on the visitor's behalf.

Run the two admission-retry/challenge-budget regression cases with
`python3 -B near/onboarding/test_recovery.py ArrivalRecovery`. They reuse only
fixture setup from the original acceptance file, not its test methods.

Run the lost-accepted-join case with
`python3 -B near/onboarding/test_join_reply.py LostJoinReply`. It calls fixture
setup only, preserves the exact pending POST through a lost response and
forged receipts, verifies usable recovered control, and checks expiry refusal.
