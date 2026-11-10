// Render work and missed-frame measurements; the visual defect line always belongs to a human.
import * as THREE from 'three';

/** Drift-corrected render cap, shared by idle calibration and the measured run. */
export class FrameGate {
  constructor(fps = 0) { this.interval = fps > 0 ? 1000 / fps : 0; this.next = null; }
  ready(now) {
    if (!this.interval) return true;
    if (this.next === null) this.next = now;
    if (now + 0.5 < this.next) return false;
    this.next += (Math.floor(Math.max(0, now - this.next) / this.interval) + 1) * this.interval;
    return true;
  }
}

export async function measureIdle(renderer, camera, frames = 90, fps = 0) {
  const empty = new THREE.Scene(), gaps = [], gate = new FrameGate(fps); let last = null;
  await new Promise((res) => {
    const step = (t) => {
      if (gate.ready(t)) {
        renderer.render(empty, camera);
        if (last !== null) gaps.push(t - last);
        last = t;
        if (gaps.length >= frames) { res(); return; }
      }
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
  gaps.sort((a, b) => a - b); return gaps[Math.floor(gaps.length / 2)];
}
const pct = (arr, p) => { const s = arr.slice().sort((a, b) => a - b); return s.length ? s[Math.min(s.length - 1, Math.floor(p * s.length))] : 0; };

export class Budget {
  constructor(seconds, idleMs, { throttled = false } = {}) {
    this.seconds = seconds; this.idleMs = idleMs; this.throttled = throttled;
    this.render = []; this.gaps = []; this.long = []; this.last = null; this.t0 = null; this.done = false; this.result = null;
    this.peak = { calls: 0, triangles: 0, geometries: 0, textures: 0 };
  }
  sample(renderMs, nowMs, renderer, extra) {
    if (this.done) return;
    if (this.t0 === null) this.t0 = nowMs;
    if (this.last !== null) {
      const gap = nowMs - this.last; this.gaps.push(gap);
      if (gap > this.idleMs * 1.5) this.long.push(Math.round(nowMs - this.t0));
    }
    this.last = nowMs; this.render.push(renderMs);
    const i = renderer.info;
    for (const [key, value] of Object.entries({ calls: i.render.calls, triangles: i.render.triangles, geometries: i.memory.geometries, textures: i.memory.textures })) this.peak[key] = Math.max(this.peak[key], value);
    if (nowMs - this.t0 >= this.seconds * 1000) this.finish(renderer, extra);
  }
  finish(renderer, extra) {
    this.done = true;
    const info = renderer.info, over = (arr, lim) => arr.filter((v) => v > lim).length / Math.max(1, arr.length);
    const r = {
      seconds: this.seconds, elapsedMs: this.last - this.t0, frames: this.render.length, dpr: renderer.getPixelRatio(), viewport: [innerWidth, innerHeight],
      throttled: this.throttled, idleIntervalMs: +this.idleMs.toFixed(2),
      renderMs: { p50: +pct(this.render, .5).toFixed(2), p95: +pct(this.render, .95).toFixed(2), p99: +pct(this.render, .99).toFixed(2), max: +Math.max(...this.render).toFixed(2) },
      line1_p95RenderOver12ms: this.throttled ? null : pct(this.render, .95) > 12,
      line2_fracIntervalsOver1_5xIdle: over(this.gaps, this.idleMs * 1.5), line2_fail: over(this.gaps, this.idleMs * 1.5) > .01,
      line3_fracFramesOver50ms: over(this.gaps, 50), line3_fail: over(this.gaps, 50) > .01,
      line4: 'pending human review',
      longGapAtMs: this.long,
      info: { calls: info.render.calls, triangles: info.render.triangles, geometries: info.memory.geometries, textures: info.memory.textures },
      infoPeak: this.peak, ...extra,
    };
    this.result = r; window.BUDGET_RESULT = r;
    window.dispatchEvent(new CustomEvent('arena-budget-result', { detail: r }));
    console.info('Arena budget', r);
  }
}
