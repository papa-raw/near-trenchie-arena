# Arena budget check

From the repository root, run:

```sh
python3 -B near/web/arena_budget.py
```

The command records 65 seconds from seed 417, serves the `near/` tree on localhost:8088, and opens Chrome. It uses only Python's standard library. It never connects to a hosted room. During a coordinated run, put this command through the coordinator's simulation-slot wrapper. Ctrl-C stops the server. `--port`, `--seed`, and `--no-open` are available.

The recording contains 16 fighters and complete starting kits. A labelled render-only stress projection holds all sixteen alive, fixes their positions, and keeps 150 live effect shapes alongside the island and real-time shadows. Every mesh primitive occurs in the equipped specs; the item trees supply groups. It retains the recorded attacks, casts, loot and other events, but suppresses KO/respawn events that would hide bodies. This projection changes no sim rule or ItemSpec. The ordinary arena continues to read its live spectator socket.

1. In Chrome, keep the tab visible, set the viewport you will use, open DevTools, disable cache, and reload the printed URL. Keep CPU throttling off and DPR forced to 2. Allow empty-scene calibration, four seconds of warm-up and a full 60-second measurement.
2. Save `window.BUDGET_RESULT` from DevTools (`copy(JSON.stringify(window.BUDGET_RESULT, null, 2))`). It contains p95 render work, missed-interval fraction, frames over 50 ms, the last and peak `renderer.info`, density, primitive coverage, seed, DPR and cap. Lines 1–3 fail at >12 ms, >1%, >1% respectively; line 4 stays pending.
3. Set DevTools CPU throttling to **4×**, append `&fps=30&throttle=4`, and reload the same URL. Save that result too. Idle calibration uses the same 30 fps cap, so the cap itself is not counted as missed frames. The throttle flag records your setting; it does not turn on DevTools throttling. Line 1 is unjudged here; lines 2–4 still apply.
4. For the eye check, reload with `&crowd=1`, then `&crowd=2`, then `&crowd=3`. Each seed puts ten fully equipped bodies inside one 3-tile cluster. View each scene three times at both machine settings; record z-fighting, shadow acne and shimmering edges. Line 4 fails if a defect appears on two of the three viewings. Only the human viewer supplies this result.
5. Keep both numeric logs and the eye-check record. Confirm 16 fighters, 150 effects, full primitive coverage, real shadows and zero console errors; inspect a legendary held by a stranger at 60 px for its gold ring, and hover/focus a name for its style word. Apply quality levers only after a recorded failure, then repeat the same scenes and settings.

The capped idle interval is measured first on an empty scene. Raw rAF intervals have no independent pass/fail threshold. `line1_p95RenderOver12ms` is `null` in a throttled run. `arena-budget-result` is dispatched when the measurement finishes; `window.BUDGET_RESULT` is reset by reloading the page. No code declares the eye check passed.

Item rendering is shared through `web/items3d.js`: published kit specs for common/rare/legendary rows, the approved named drawings for the fourteen house signature clothes (which have no ItemSpecs), with owned meshes under each fighter's joints. Replacing gear or removing loot frees its geometry and materials. Missing asset files stop startup with an actionable message. An unknown runtime row or an item build error draws a neutral labelled placeholder and warns once per row; the next animation frame is always scheduled even if a render update fails. Serve the whole `near/` directory so `items/` is reachable.

The spectator socket opts in with `styles=1` to receive separate `spectator_styles` JSON messages (version 1): a full map on connect, then one delta per changed server-state map. A delta maps fighter ids to one of the five public style words in lower case; `null` removes a departed fighter. Revisions increase once per change; a connection that missed a revision through backpressure receives a full map. Both local spectator hosts serialize each message once and reuse the bytes. Canonical and compact tick messages retain their frozen format and ordering for clients that do not opt in. The UI uses the server map for players and houses, with the approved house roster as a fallback before the first metadata message. It never guesses a player's style. Disconnect clears the map; reconnect supplies a full map again.

Focused checks:

```sh
node --no-warnings --experimental-loader ./near/web/arena-view-remainder-loader.mjs near/web/arena-view-remainder-node.mjs
python3 -B near/web/arena-budget-record-case.py
```

The first uses real three.js geometry and a canvas texture sink; it makes no GPU or visual claim. A browser version is `node near/web/arena-view-remainder-case.mjs` (set `CHROME_BIN` if needed). It records console exceptions and saves a screenshot; its 60 px strip is evidence for a human, never an automatic visual verdict. The recording check starts a sim, so use the simulation wrapper when required by your run.

## Earlier live-stream measurements

These historical measurements used fourteen fighters and older items. They do not satisfy the full scene above.

Machine: the build Mac (shared with other jobs, so runs vary), Chrome, 1920 x 856 CSS px, DPR forced to 2, 60 Hz display.
Not run: the 4x CPU-throttled run with the 30 fps cap (the browser tool that sets throttling was not available), a real phone,
and line 4 (a person looks).

| Run | What changed | p50 / p95 render ms | Line 1 | Line 2 (over 25 ms) | Line 3 (over 50 ms) | draw calls / triangles |
|---|---|---|---|---|---|---|
| 1 | first build, 819 x 856 window | 9.5 / 12.6 | fail | 0.06% pass | 0% pass | 1064 / 574k |
| 2 | 1920 x 856, nothing changed | 6.7 / 9.0 | pass | 8.8% fail | 0.1% pass | 1020 / 543k |
| 3 | lever 1: shadow map 1024 | 9.6 / 12.3 | fail | 11.8% fail | 0.1% pass | 1031 / 540k |
| 4 | panel art redraw switched off (diagnostic) | 9.5 / 11.5 | pass | 0% pass | 0% pass | 1034 / 548k |
| 5-7 | panel art redrawn on change only, HP candles cloned | 10.2 / 13.1, 9.0 / 11.7, 10.8 / 14.4 | fail, pass, fail | 15.4%, 0.08%, 12.5% | 0% | 1015-1036 / 553-573k |
| 8-9 | island merged to a few meshes, shore bodies cast no shadow | 6.3 / 8.8, 6.5 / 9.4 | pass, pass | 0.08%, 0% pass | 0% pass | 452-534 / 416-542k |

Reading: before the last change the test failed on lines 1 and 2 in most runs, and which way a run went followed the load on the
machine. Merging the static island (about 250 meshes to a handful) and keeping shore bodies out of the shadow pass halves the
draw calls and put both runs inside lines 1 to 3 with margin (p95 9 ms against 12). The lever list in the spec was not needed in
order: the shadow map change (lever 1) did not move line 2. Two passing runs are not a soak: the full test is to be repeated by the
reviewer and again at Pat's own window size.


## Arena render-cost changes

The complete scene failed on the build Mac: review measurements at DPR 2 were p95 29.6 and 31.9 ms, about 1,778 draw calls and 1.08 million triangles. That measured failure enabled the ordered rendering changes below. The following counts are a **Node scene-graph proxy**, not `renderer.info` or GPU timing. Colour and one shadow pass are counted, including double-sided transparent passes and instance multiplicity, without camera-frustum culling. The proxy deliberately overcounts geometry outside the camera. Shadow-map resolution changes its fill cost, not the counts.

| Step, in order | Static full-kit calls / triangles | Recorded-scene peak calls / triangles |
|---|---|---|
| Before changes | 1,596 / 1,007,034 | Not measured in Node before changes; Chrome result above |
| 1: shadow map 1024, one key light | 1,596 / 1,007,034 | Not measured separately |
| 2: no effect shadows | 1,446 / 1,004,034 | Not measured separately |
| 3a: repeated actor primitive instances | 789 / 1,004,034 | Not measured separately |
| 3b: static item primitives merged with vertex colours, after fitting | 371 / 1,004,034 | Not measured separately |
| 3c: arena-only sampled smooth grids | 371 / 515,890 | 655 / 622,306: floor loot still used unmerged full-detail primitives |
| 3d: same merge/sample path for floor loot | 371 / 515,890 | 519 / 574,290 |
| Final proxy with leader crown and correct per-item tier-glow restoration | 393 / 515,982 | **525 / 574,382** |

The final recording case decodes all 1,301 recorded ticks and counts 1,285 distinct or periodic floor/cast/object states. It retains sixteen complete kits, island geometry, real shadow casters, live telegraphs, loot, the crown, and a top-up to 150 effects. It checks both agreed proxy bounds: at most 550 calls and 600,000 triangles. Event-driven burst animation and real GPU scheduling remain covered by the browser run; these numbers do not claim the numeric budget lines pass. No DPR, effect-count, aggro-line, fighter-count or low-tier lever was applied. DPR remains 2 in the budget command.

Full tessellation is now the default; `&tessellation=reduced` explicitly enables sampled geometry and `&tessellation=full` keeps full geometry. Cards and kit/legendary close-ups retain their original geometry. The arena keeps more samples on larger silhouettes than tiny badges, samples only smooth grid primitives, and retains authored positions, normals, UVs, colours and post-fit contours. Cylinder clothing fits and all ItemSpecs/body specs stay unchanged. Repeated meshes keep their source ownership under actor joints; instances copy world transforms and per-instance colour. Flash state and shadow state partition batches. Item and instance resources are released on replacement or departure. The review must compare `tessellation=full` with the default at both the normal arena zoom and the follow inset; a visibly faceted part reverts.

The holder ring has a dark gold outer rim (#73501C) around its gold centre. Its calculated contrast is 6.38:1 on #F7F0DC and at least 5.99:1 on the measured sand #F6EAB3. The browser fixture now includes the floor colour below the actual item-equipped actors and its 60 px strip. The rim sits above telegraphs. Calculated contrast is evidence for the human legibility check, not that check's verdict.

New focused cases (the first starts a sim, so use your run's simulation wrapper):

```sh
python3 -B near/web/arena-view-recorded-cost-case.py
node --no-warnings --experimental-loader ./near/web/arena-view-remainder-loader.mjs near/web/arena-view-resilience-case.mjs
```

The geometry-cost case failed before at 1,596 calls / 1,007,034 triangles; the unknown-row case failed before from `ItemRenderer.build` during `Actors.setItems`. The final new cases pass. The resilience case also covers finite tier-glow restoration after merging, actor instance ownership and disposal, and rescheduling after a thrown frame. The existing browser case is mapped as `arena-view-browser` with a Chrome/WebGL requirement; it is for the review and is not run by the build. The real DPR-2 timing, default/inset look comparison, 4x/30-fps run and eye check remain unmeasured by this build.

## Bound cast details and quirk text

Opted-in spectators (`styles=1`) now receive optional `tick`, `casts` and `rules` fields on the existing version-1 `spectator_styles` message. A full message includes the active rules' signature parameters and plain quirk lines. Each cast is keyed by `who:resolveAt` and carries its source item, signature, start/end tick, shape, bound radius in milli-tiles and arc in millidegrees. A delta adds a cast once and removes it when it ends. Both hosts serialize once and send the same metadata bytes to every opted-in spectator **before** the corresponding canonical/compact tick; other clients receive exactly their existing tick stream. Backpressure resyncs the whole active map. No field enters the sim or frozen tick encoding.

The view uses the bound record instead of the fighter's current trinket or current stats. This matters for a grab during the wind-up and a reconnect after it: neither changes the original cast's range or arc. Finished records remain for six seconds so a newer removal cannot erase geometry still in the delayed buffer. Disconnect clears them; a clock reset clears history on the next metadata update. Recorded scenes include the same metadata revisions, applied before their matching recorded frames. If geometry metadata is absent, the view draws its shared signature shape and warns once; later metadata replaces that fallback. Radius/shape changes rebuild the mesh, and the cone follows the current aim direction.

The equipped item's quirk line comes from the active server rules and appears as plain text beside the style word on the existing name tag's hover and keyboard-focus states. Equipping a different item updates the line; an item without a quirk clears it. No new drawing is added. The metadata retains the public projection's selection reach, while the client preserves each signature's approved visual shape. Blink uses a separate 1.2-tile target marker, rather than painting the selection reach as an area of damage.

New focused checks compare the real three.js telegraph meshes with the actual server projection for all six range/arc quirks at 100%, 125% and 150% range, after a trinket/stat swap. They also cover metadata-before-tick ordering, shared bytes, no opt-in, backpressure, client disconnect/reset, recorded delivery and the one-time fallback warning. The new hover case checks actual tag text, item changes and focus selectors. Run simulation cases through the run's simulation wrapper when required:

```sh
python3 -B near/arena/test_spectator_quirks.py CastMetadata
python3 -B near/web/arena-quirk-geometry-case.py
node --no-warnings --experimental-loader ./near/web/arena-view-remainder-loader.mjs near/web/arena-quirk-hover-case.mjs
```

The extended recorded cost case with metadata active peaks at 500 calls / 571,734 triangles over 1,301 ticks and 1,300 counted states, still inside the agreed Node proxy limits. It makes no real timing or visual PASS claim. The prior step table remains the measured history before bound cast details.


## Panel paint caching and full-detail default

The independent Chrome measurements found render work at p95 2.4 ms but missed frame lines with the HUD on; `nohud` passed at 60 fps. Full tessellation measured the same frame timing as reduced detail and looked smoother in the follow inset. Full detail is therefore restored as the arena and `Actors` defaults. Reduced detail remains an explicit diagnostic switch. The coordinator adjusted the Node proxy accordingly: **default full detail must stay at or below 550 calls and log its triangle count**; only explicit reduced mode has the 600,000-triangle bound. Default recorded proxy: 500 calls / 1,094,054 triangles. Explicit reduced: 500 / 571,734. Both span 1,301 ticks and 1,300 counted states. The real DPR-2 lines still determine the default scene result.

The traced paint path was `Hud.frame` -> `remount` -> the frozen `HUDART.mount`, which discarded and rebuilt the entire SVG layer. Its filtered wood, enamel, fabric and shadow art was invalidated together even when only a board count changed. The frozen art file is unchanged. A new adapter builds the approved art offscreen, keeps unchanged visible panel nodes, and replaces only a panel whose SVG content changed. Filtered backgrounds are split from text, rasterized once per background/palette/size/DPR and cached (128 entries, shared pending decodes). A changed number blits the cached background into a canvas and keeps the new text as SVG, with its original font and attributes. The same path handles player cards and legendary receipts; unused world panels are omitted from the main layer. Background object URLs are revoked, removed panel references are released and diagnostic timing samples are bounded.

New case evidence: the old HUD replaced an identical board node on a repeated update; the adapter now paints five initial panels, zero for an unchanged update and one board for one changed count. The case also uses the real frozen art generator: 20 unchanged updates retain the panels, then one count change paints one board. Its JavaScript generation maxima were 1.96–4.64 ms in Node's font/canvas sink across the focused runs. This is **not** a browser filter, raster or long-task measurement. Inspect `ARENA.hud.artCache.stats` and `.backgrounds.rasters` in Chrome, and repeat the normal DPR-2 budget run with the HUD visible. Initial texture decoding occurs before a newly painted layer is attached. Any browser long task or changed layering in the approved art remains a review finding.

A caught frame error now sets the visible status to `Render error` even when the same error has already been logged once. The guard still schedules the next frame. Its new case demonstrates leaving `Live` on every failing frame, one console report for duplicate errors, and continued scheduling.

Focused new/extended cases:

```sh
node --no-warnings --experimental-loader ./near/web/arena-view-remainder-loader.mjs near/web/arena-hud-redraw-case.mjs
node near/web/arena-frame-status-case.mjs
python3 -B near/web/arena-view-recorded-cost-case.py
python3 -B near/web/arena-view-recorded-cost-case.py --reduced
```

Simulation recording commands use the simulation-slot wrapper during a coordinated run. No Node check claims W10's real browser timing or the human eye check has passed.


## Signature shapes and bounded hover text

The visual shape belongs to each signature: beam sweep is a cone; shockwave, bubble and chain storm keep their edge rings; magnet is a circle; blink is a small circle at its target; dodge roll has no danger shape. Bound metadata supplies radius and arc without replacing those shapes. For blink, `radiusMilli` remains the original target-selection reach, while optional `strikeRadiusMilli` is the approved 1,200-milli target marker. It is a visual marker for a single-target strike, not an area-of-effect rule. New hosts supply it, and clients receiving older metadata retain the same 1.2-tile marker. No sim or rules-table value changes.

The quirk line now wraps inside a 230-pixel body under or beside the name pill. The body stays within the viewport and chooses a position that clears neighbouring tags and cards. Focus/hover makes a benched or distant tag fully opaque. The native title stays short; the complete quirk remains in its accessible label. `web/arena-quirk-hover-fixture.html` exercises real tags and the same page CSS with a focused benched fighter; `HOVER_FIXTURE.check()` reports width, neighbour overlap, opacity and viewport bounds. Check it at desktop and 390 px. A focused fixture is evidence for the review, not an automatic browser verdict from this build.

Spectator rule dictionaries are converted once per rules hash and reused across publish calls and game instances with that hash. The new cache case fails against the prior source (44 conversions in its scenario) and passes with one conversion. The new shape case fails before on the oversized blink marker and passes with all six visual shapes plus the absent dodge shape. Placement cases show no overlap at 390 and 1440 px. The existing focused cross-language case still checks bound selection reach/arc at 100/125/150 percent through item swaps, and separately checks the blink strike marker; metadata transport/client/replay cases stay intact. The full-detail cost remains 500 calls / 1,094,054 triangles.


## Cached-panel text stacking

Every cached panel creates an isolated local stacking context. Its positioned background canvas has z-index 0 and the SVG text overlay is positioned relative with z-index 1. This applies to leaderboard, banner, both buttons, feed and legendary receipt; the cache and redraw cadence stay unchanged. The new focused `node near/web/arena-hud-stacking-case.mjs` fails against the previous painter's static overlay and passes all six panel kinds after the change. Chrome still supplies the text-visibility verdict and checks that the already measured DPR-2 timing holds.


## Hover ownership and replay-status clearance

The hover body now starts with the trenchie's short name. Candidate positions come from the anchor and neighbouring rectangle edges, rather than only the far screen edges. Other tags are hard obstacles. Among candidates with zero tag overlap and at most 32 square pixels of card contact, the nearest centre-to-centre position wins; a completely clear but distant position cannot outrank it. The all-house case checks every one of the 14 tags at 1780 and 390 px against a 240 CSS-pixel centre-distance bound. Before, a case placed the body about 830 px away; after, its maximum is 192.4 px with zero tag overlap. Names and the text remain plain DOM text.

`arena-quirk-hover-fixture.html` now contains all 14 tags. In Chrome at each viewport, run `await HOVER_FIXTURE.checkAll()`; each result reports the owning id, short-name prefix, centre distance/bound, tag overlap, opacity and viewport containment. The Node case checks the placement rule and the existing hover case checks the actual text prefix. The browser fixture is for the review to establish the painted result.

The replay-only `Recorded arena` pill is placed from the measured feed rectangle. When its natural bottom-centre position intersects the feed (including the phone layout), it sits eight pixels above the feed instead. Live status remains hidden as before. The focused status case reproduces overlap at 390 before and clears it after; `arena-replay-status-fixture.html` uses the real frozen feed art and page CSS, exposing `STATUS_FIXTURE.check()` for the browser review.

```sh
node --no-warnings --experimental-loader ./near/web/arena-view-remainder-loader.mjs near/web/arena-hover-near-case.mjs
node near/web/arena-replay-status-case.mjs
```

These are layout/text changes only. No new scene or simulation cost measurement was run, and no browser visual verdict is claimed by the builder.

## AOE telegraphs: red candles

Pat picked draft c, red candles, as the telegraph look (2026-11-11). It is the default; `?tele=a` and `?tele=b` show the other drafts and `?tele=old` the earlier flat danger shape. `&tele_n=N` adds N view-only stress telegraphs to the budget scene (lobbed circles of 1.2 to 4 tiles, which carry the most candles, and beam lines; each lives 2 s), and the result records `teleLook`, `teleStress` and `telegraphsLive` (min and max over the measured frames).

Each telegraph is one shader quad plus one instanced candle mesh. The candles cast no shadow (lever 2, already in force for effects). An expired telegraph waits in a pool by shape and size (at most 8 a shape) and is reused: before the pool, every telegraph built a new material and candle mesh, and crowd 2 failed line 2 (3.1% at 1455x748; the old flat look 1.8% on the same run pair). With the pool, the budget scene and crowds 1 to 3 pass lines 1 to 3 at 12 to 18 live telegraphs, and crowd 2 passes at 20 to 26. The runs, with `renderer.info`, viewport and machine load, are kept with the review notes, outside this repo. No DPR, effect-count, aggro-line, fighter-count or low-tier lever was used. Line 4 and the 4x throttled run belong to a human viewer.
