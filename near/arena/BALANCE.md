Engine balance measurements

Build evidence; independent balance review pending. One local fixture seed per cell.
Ordinary samples: 1,200 ticks. Positive-density samples: 4,800 ticks. Each table measures five baseline variances and four single controls at variance 20.

Observed exceedance counts use proposed thresholds. Missing cells remain missing; these rows are not verdicts.

| Rules | Variance | Control | KOs | Lift >1.5x | Rare beats 1 / loses to 2 (bps) | Moves >2x | Kit KO/survival >2x | Styles dominated | Hunt streak | Hunt <half | Missing lift/pairs |
|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|
| integer-9 | 10 | baseline | 3480 | 6 | missing/missing | 6 | 101/1 | 0 | 2 | 5 | 30/2 |
| integer-9 | 15 | baseline | 3443 | 9 | missing/missing | 5 | 121/1 | 0 | 2 | 9 | 26/8 |
| integer-9 | 20 | baseline | 3523 | 4 | missing/missing | 3 | 82/0 | 1 | 2 | 4 | 29/8 |
| integer-9 | 20 | beam_fire_slow | 3622 | 6 | missing/missing | 2 | 81/0 | 0 | 2 | 4 | 28/9 |
| integer-9 | 20 | looter_reengage | 3568 | 6 | missing/missing | 3 | 81/0 | 1 | 2 | 5 | 27/7 |
| integer-9 | 20 | melee_gap_closer | 3822 | 5 | missing/missing | 3 | 110/0 | 1 | 2 | 4 | 28/8 |
| integer-9 | 20 | misses | 3385 | 2 | missing/missing | 3 | 114/2 | 0 | 2 | 1 | 38/9 |
| integer-9 | 25 | baseline | 3476 | 10 | missing/missing | 3 | 104/1 | 0 | 2 | 7 | 25/9 |
| integer-9 | 30 | baseline | 3478 | 2 | missing/missing | 4 | 113/0 | 0 | 3 | 4 | 31/7 |
| integer-10 | 10 | baseline | 3428 | 7 | missing/missing | 6 | 101/1 | 0 | 2 | 6 | 30/7 |
| integer-10 | 15 | baseline | 3414 | 9 | missing/missing | 5 | 121/1 | 0 | 3 | 6 | 26/12 |
| integer-10 | 20 | baseline | 3555 | 5 | missing/missing | 3 | 82/0 | 1 | 3 | 9 | 29/10 |
| integer-10 | 20 | beam_fire_slow | 3601 | 3 | missing/missing | 2 | 81/0 | 0 | 2 | 3 | 28/10 |
| integer-10 | 20 | looter_reengage | 3568 | 5 | missing/missing | 3 | 81/0 | 1 | 2 | 10 | 27/10 |
| integer-10 | 20 | melee_gap_closer | 3804 | 5 | missing/missing | 3 | 110/0 | 1 | 2 | 7 | 28/11 |
| integer-10 | 20 | misses | 3360 | 2 | missing/missing | 3 | 114/2 | 0 | 2 | 0 | 38/7 |
| integer-10 | 25 | baseline | 3459 | 8 | missing/missing | 3 | 104/1 | 0 | 3 | 3 | 25/12 |
| integer-10 | 30 | baseline | 3505 | 5 | missing/missing | 4 | 113/0 | 0 | 3 | 4 | 31/8 |

The stronger-build signal is the rare-vs-default duel rate; the JSON retains all point-stratified rates.
Style outcomes use matched crowd builds; starting-kit survival cohorts and actual time-in-hand KO indices are both retained.
See balance-report.json for all seven fields, denominators, missing cells, life/base-rate distributions and synthetic abuse diagnostics.
No optional control or candidate is enabled by this report. Production trailing prediction-log scoring and settlement are not exercised.

The first candidate still has observed exceedances. Balance acceptance remains open; no candidate or optional control is enabled.

Every configuration retains all mirrored weapon, signature, preset and loot pairs in mirrored_duels: wins, draws, runs, decisive denominator, left rate, distinct outcomes and within/outside/unmeasured target status. The 40–60% target remains descriptive. Archived measurements were reused without another sweep.

Rare/newcomer rates are withdrawn because the archived life rows omitted attacker and life IDs. Affected runs are explicitly evidence-missing and censored in JSON. Future measurements count only distinct newcomers defeated by the rare fighter during its first life; surviving winners still count. No replacement sweep was run.
