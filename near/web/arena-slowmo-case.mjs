// F18: a callout runs x0.3 for 1.5 s, then the viewer is back within one buffer of live; one legendary steal a minute; no stacking.
// Run: node near/web/arena-slowmo-case.mjs
import assert from 'node:assert/strict';
import { SnapshotBuffer, TICK_MS } from './arena/buffer.mjs';
import { Slowmo, SLOW_SCALE, SLOW_MS, STEAL_GAP_MS } from './arena/slowmo.mjs';

let checks = 0; const ok = (c, m) => { assert.ok(c, m); checks++; };
const b = new SnapshotBuffer(), sm = new Slowmo(b); let now = 1000, tk = 0;
const step = (ms) => { for (let e = 0; e < ms; e += 16.7) { now += 16.7; while (tk * TICK_MS + 1000 <= now) { b.push({ tick: tk }, tk * TICK_MS + 1000); tk++; } sm.update(now); b.sample(now); } };
step(3000); const live = b.lead;
ok(sm.trigger('leader_ko', now) && b.scale === SLOW_SCALE, 'a big KO starts x0.3');
const t0 = now; step(SLOW_MS - 50); ok(sm.active, 'still slow before 1.5 s');
step(200); ok(!sm.active && b.scale === 1, 'back to x1 after 1.5 s (' + (now - t0).toFixed(0) + ' ms)');
ok(b.lead > live + 3, 'the viewer is now behind live: ' + live.toFixed(1) + ' -> ' + b.lead.toFixed(1) + ' ticks');
let caught = null; const t1 = now; for (let i = 0; i < 600 && caught === null; i++) { step(16.7); if (Math.abs(b.lead - live) < 1.0) caught = now - t1; }
ok(caught !== null && caught < 6000, 'caught up to within one buffer of live in ' + (caught && caught.toFixed(0)) + ' ms');
ok(b.rate <= 1.25 + 1e-9, 'never faster than x1.25');
// rules: no stacking, one steal a minute
ok(sm.trigger('steal', now), 'a legendary steal starts a callout');
ok(!sm.trigger('leader_ko', now + 100), 'a second callout during the first is refused');
step(SLOW_MS + 100);
ok(!sm.trigger('steal', now), 'a second steal within the minute is refused');
ok(sm.trigger('leader_ko', now), 'but a leader KO is not held back by the steal cap');
step(SLOW_MS + 100); step(STEAL_GAP_MS);
ok(sm.trigger('steal', now), 'a steal a minute later runs');
// a long stall beyond 3 s jumps to live
step(SLOW_MS + 100); sm.until = now + 6000; b.scale = 0.05; step(5000); sm.until = 0; step(300);
ok(b.snaps >= 1 && b.lead < b.targetLead + 61, 'a drift past 3 s jumps to live');
console.log('arena-slowmo-case: ' + checks + ' checks passed');
