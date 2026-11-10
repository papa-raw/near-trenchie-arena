# Pinned versions

Every dependency this repository uses or has committed to using, with its exact version. The first table is what the tree imports or ships today. The second names what the plan adds; each row moves to the first table, with its licence recorded in the README, when it enters the tree.

## In the tree today

| Component | Version | Where | Pinned in |
|---|---|---|---|
| Python | 3.10 or later; the checks were run on 3.14.7 | everything | README |
| jsonschema | 4.26.0 | `room/`, `near/lore/` | `near/requirements.txt` |
| cryptography | 46.0.7 | `near/onboarding/` | `near/requirements.txt` |
| Playwright (browser cases only, optional) | 1.64.1 | `near/members/`, `near/web/` | `near/members/package.json` |
| Fredoka, Lilita One, Space Mono (fonts, OFL 1.1) | as downloaded 2026-11-03 | `near/members/fonts/` | `near/members/fonts/LICENSES.txt` |

Install the Python packages with `python3 -m pip install -r near/requirements.txt`. Everything else is the Python standard library.

## Named by the plan, not in the tree yet

| Component | Version |
|---|---|
| three.js (vendored) | 0.186.1 |
| websockets | 17.3 |
| near-api-js | 7.3.1 |
| rustup | 1.95.0 (target `wasm32-unknown-unknown`) |
| cargo-near | 0.22.0 |
| near-cli-rs | 0.30.1 |
| near-sdk-rs | pinned when the first contract is committed |
