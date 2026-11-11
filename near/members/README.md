# Member room page

A member reviews current terms and explicitly accepts them, or accepts/declines
a proposed input-interval change for their own persona. Answers and timing come
from authenticated room snapshots. The page exposes no moderation, spend-cap or
publishing action, and no grant token or signing key reaches the browser.

The installed room is the exact `305e06df45d25e2268f89cf7d94b439ddc2dd887`
export, including reviewed members source `1a489964`. Source provenance is in
[room-source.json](../../room-source.json); source semantics are in
[ROOM.md](../../room/ROOM.md). Copied room files are never patched locally.
Independent game integration review remains separate from source acceptance.

For an interactive rehearsal with synthetic identity and the real local room:

```sh
python3 -B near/members/local_demo.py
python3 -B near/members/local_demo.py --proposal
python3 -B near/members/local_demo.py --unpublished
```

Run one at a time and open its printed localhost URL. The proposal option uses
two other members' actual signed answers. Unpublished starts from an explicit
trusted source checkpoint; it does not substitute a snapshot. The clock is held
for inspection. These are local synthetic rehearsals, not deployed wallet proof.
The ordinary demo server exposes no test controls or publication route.

## Owner runtime

Supply this member's already joined, proved `near.arena.snap_client.SnapClient`.
Wallet/session signing and pinned room verification stay in the owner runtime.
The optional `connect` callback is the existing own-wallet/admission flow. An
unjoined pinned `public_client` reads public timing while disconnected; a trusted
`room_label` preserves room identity without inventing private authentication.

```python
from near.members.runtime import MemberSession, member_server

session = MemberSession(own_joined_client, connect=own_wallet_admission,
                        public_client=anonymous_pinned_client,
                        room_label=trusted_room_label)
httpd = member_server(session)
print(f"http://127.0.0.1:{httpd.server_port}/")
try:
    httpd.serve_forever()
finally:
    httpd.server_close()
```

Run from the repository root and open its exact127.0.0.1 URL. This loopback owner
adapter is separate from the room's deployed HTTPS/WSS transport. Same-origin
checks and an explicit action header protect private requests. The browser sends
only its own choice plus the exact reviewed version/proposal. SnapClient signs
and verifies the full context, actor and request digest. An uncertain write is
never resent: Check answer performs a fresh signed read.

## Reads and publication

Every member snapshot uses a fresh id and a signed15-second expiry. The client
also refuses a genuine signed reply received after that expiry. Source keeps a
bounded durable expiring-read bank, separate from permanent write and legacy
operation ids. Expired ids may be pruned only with the persisted clock fence;
old ids and write replay protection are retained. This restores read/write
capacity without clearing an exhausted account's old history. The member client
uses no empty-payload legacy-read fallback. Focus and visible10-second polling
therefore reconcile current state without consuming permanent write capacity.
The owner runtime must supply a synchronized millisecond clock.

Only a verified `OwnerSnapshot.terms is None` means No terms yet. Failed or
missing data means Unavailable. A trusted startup checkpoint can explicitly set
`terms_published=False`; legacy checkpoints default to published. The host-only
`service.publish_owner_terms()` durably publishes that configured draft once,
advances its version and clears prior acceptance. It is not an HTTP action.
Do not infer publication from a browser URL or mutate a live service's private
state. Later interval changes retain the unanimous/boundary mechanism.

The unpublished view has no consent controls. Return shows Waiting for room
terms, outages stay Unavailable, and publication requires fresh timing/policy
review before the member accepts. Local history never supplies acceptance.
Read-only members can inspect state but receive no consent authority. Four of
four answers means scheduled until the host confirms application; then the
comparison labels Previous and fresh Current. Own decline and another member's
decline remain distinct. Return/reload retain only current source-backed facts.

Fault room returns keep trusted room identity, unknown/disconnected auth, both
quiet navigation links and a single Refresh action. They expose no stale
persona, acceptance or timing. The arena is contextual static art, not a live
population map. All review captures wait for current fonts/images and paint.

## Focused cases

Prerequisites: Python3.10+, pinned requirements (`near/requirements.txt`), Node20+, Playwright and
Chromium. Install the locked browser dependency:

```sh
python3 -m pip install -r near/requirements.txt
npm ci --prefix near/members
cd near/members && npx playwright install chromium
```

The new source integration cases can be run individually from the repo root:

```sh
python3 -B near/members/test_member_source.py MemberSource.test_repeated_signed_reads_preserve_renewed_member_and_write_replay_guard
python3 -B near/members/test_member_source.py MemberSource.test_signed_read_expiry_rejects_exact_replay_tampering_and_stale_request
python3 -B near/members/test_member_source.py MemberSource.test_signed_read_reply_arriving_after_its_expiry_is_not_current
python3 -B near/members/test_member_unpublished.py MemberUnpublished.test_signed_unpublished_state_stays_distinct_from_failure_and_publish_requires_review
```

The first case makes300renewed reads at six/minute, then records own consent and
refuses its replay. The HMAC cases reject exact read replay, altered signed expiry,
expired requests and late genuine responses, and permit a fresh subsequent read.
The unpublished case uses the actual signed-null state, failure/recovery, trusted
publication7→8, explicit own acceptance and reload, with board-size and responsive
captures. No browser response or signed snapshot is substituted.

Existing approved-board, recovery and presentation cases remain separately
available in test_members.py, test_member_repair.py and test_member_presentation.py.
`(cd near && make test-members-source)` selects only the four source integration cases.
Set MEMBER_SHOTS to retain captures; otherwise browser cases use temporary output.
Chromium honors an existing HTTPS_PROXY/HTTP_PROXY for the permitted local fixture;
these cases create no proxy or network grant. All identity/wallet/signature/journal
and clock adapters are explicitly synthetic. Source publication is not proof of
live engine-rule application, real wallet/Ed25519, chain, TLS or deployment.
