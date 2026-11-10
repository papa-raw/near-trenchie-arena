// W7: the 150 ms buffer draws from the past, never snaps to the newest snapshot, and plays a slow server as slow motion.
// Run: node near/web/arena-buffer-case.mjs
import assert from 'node:assert/strict';
import { SnapshotBuffer, TICK_MS, MIN_DELAY_MS, SNAP_TICKS } from './arena/buffer.mjs';

let checks = 0; const ok = (c, m) => { assert.ok(c, m); checks++; };
const mk = (tick) => ({ tick });
// run a stream: `gap(k)` is the page-ms between arrivals k-1 and k; the page samples every 16.7 ms
function run(b, ticks, gap, sampleEvery = 16.7) {
  let t = 1000, nextSample = 1000, out = [];
  for (let k = 0; k < ticks; k++) {
    t += gap(k); b.push(mk(k), t);
    while (nextSample <= t) { const s = b.sample(nextSample); if (s) out.push({ t: nextSample, lead: b.lead, ...s }); nextSample += sampleEvery; }
  }
  return { out, end: t };
}

// 1. steady 20 Hz: the viewer sits 3 ticks (150 ms) behind the newest snapshot and blends the pair around it
let b = new SnapshotBuffer(), r = run(b, 200, () => TICK_MS);
ok(Math.abs(b.delayMs - MIN_DELAY_MS) < 1e-6, 'zero jitter keeps the 150 ms floor, got ' + b.delayMs);
const tail = r.out.slice(-40), meanLead = tail.reduce((a, q) => a + q.lead, 0) / tail.length;
// the viewer draws at now - 150 ms: with arrivals on the 50 ms grid the newest snapshot is 2..3 ticks ahead of the render tick, 2.5 on average
ok(meanLead > 2.0 && meanLead < 2.9, 'steady state: the render tick trails the newest snapshot by 2..3 ticks (about 150 ms behind now), mean ' + meanLead.toFixed(2));
const late = r.out.slice(-1)[0];
ok(!late.held && late.a.tick <= late.tick && late.b.tick >= late.tick && late.b.tick - late.a.tick === 1, 'the pair brackets the render tick');
ok(r.out.every((s, i) => i === 0 || s.tick >= r.out[i - 1].tick - 1e-9), 'the render clock never runs backwards');
ok(r.out.slice(100).every((q) => !q.held), 'a healthy stream never holds once the ring has filled');

// 2. a server that runs at 12.5 Hz (80 ms per tick): playback slows to about 0.62x, no holds, and it says so (hz)
b = new SnapshotBuffer(); r = run(b, 200, () => 80);
ok(Math.abs(b.hz - 12.5) < 0.6, 'observed rate ' + b.hz.toFixed(1) + ' Hz');
const span = r.out.slice(-1)[0].tick - r.out.find((s) => s.t > 5000).tick, wall = (r.out.slice(-1)[0].t - r.out.find((s) => s.t > 5000).t) / TICK_MS;
ok(span / wall > 0.55 && span / wall < 0.7, 'plays at ~0.625x, got ' + (span / wall).toFixed(2));
ok(r.out.slice(150).filter((q) => q.held).length < 10, 'steering avoids held frames on a slow server');

// 3. jitter widens the delay: arrivals alternate on time / 100 ms late
b = new SnapshotBuffer(); run(b, 120, (k) => (k % 2 ? 100 : 0) + (k % 2 ? 0 : 0) + TICK_MS / 1);
ok(b.delayMs >= MIN_DELAY_MS, 'delay never below the floor');
b = new SnapshotBuffer(); run(b, 160, (k) => (k % 2 ? 125 : 25));
ok(b.jitter > 40 && b.delayMs > MIN_DELAY_MS + 30, 'adaptive floor jitter*4+5 exceeds 150 ms under wobble, delay ' + b.delayMs.toFixed(1));

// 4. a stall: the clock runs into the newest snapshot and holds it, counts it, then catches up at up to 1.25x
b = new SnapshotBuffer(); run(b, 60, () => TICK_MS);
let t = 1000 + 60 * TICK_MS, s;
for (let i = 0; i < 40; i++) { t += 16.7; s = b.sample(t); }
ok(s.held && b.late > 0, 'stalled stream holds the newest snapshot and counts it');
for (let k = 60; k < 120; k++) { t += 20; b.push(mk(k), t); for (let j = 0; j < 1; j++) s = b.sample(t); } // a burst: 50 Hz
ok(b.rate <= 1.25 + 1e-9, 'catch-up never exceeds 1.25x, got ' + b.rate.toFixed(2));

// 5. slow-mo (F18): scale 0.3 for 1.5 s, then the buffer catches up and the viewer is back within one buffer of live
b = new SnapshotBuffer(); let now = 1000, tk = 0;
const step = (ms) => { for (let e = 0; e < ms; e += 16.7) { now += 16.7; while (tk * TICK_MS + 1000 <= now) { b.push(mk(tk), tk * TICK_MS + 1000); tk++; } s = b.sample(now); } };
step(3000); const base = b.lead;
b.scale = 0.3; step(1500); const behind = b.lead; b.scale = 1;
ok(behind > base + 3.5, 'slow-mo drifts the viewer behind live: ' + base.toFixed(1) + ' -> ' + behind.toFixed(1) + ' ticks');
step(6000);
ok(Math.abs(b.lead - base) < 0.8, 'catch-up returns the viewer to within one buffer of live: ' + b.lead.toFixed(2) + ' ticks');
// beyond 3 s behind: snap to live
b.scale = 0.1; step(4000); b.scale = 1; const snapsBefore = b.snaps; step(300);
ok(b.snaps >= snapsBefore, 'a drift beyond 3 s jumps to live (snaps ' + b.snaps + ')'); ok(b.lead <= b.targetLead + SNAP_TICKS + 0.5, 'never more than 3 s behind');

// 6. duplicates and slightly old ticks are ignored; a restart (tick far back) clears the ring
b = new SnapshotBuffer(); b.push(mk(5), 0); b.push(mk(5), 10); b.push(mk(4), 20);
ok(b.ring.length === 1, 'duplicates and slightly old ticks dropped');
b.push(mk(1), 30);
ok(b.ring.length === 1 && b.ring[0].tick === 1, 'a segment restart clears the ring');
console.log('arena-buffer-case: ' + checks + ' checks passed');
