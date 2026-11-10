// The 150 ms interpolation buffer (W7). The arena draws only from here: a ring of snapshots keyed by server tick, read a fixed
// distance behind the newest one. That distance is max(150 ms, jitter * 4 + 5 ms) (prd.md §4.10). Never snaps to the newest
// snapshot.
//
// The render clock is a tick pointer, not a wall-clock mapping. It advances 1 tick per 50 ms of page time, steered by how many
// ticks sit buffered ahead of it ("lead"): short of the target it slows (down to half speed), long of it it speeds up (to 1.25x),
// so a server that runs under 20 Hz plays back as honest slow motion instead of a stream of held frames, and a burst after a
// stall is caught up at 1.25x. Slow-mo callouts (F18) multiply the rate by `scale`; the same steering is their catch-up.
// If the clock falls more than SNAP_TICKS behind (3 s), it jumps to live.

export const TICK_MS = 50;
export const MIN_DELAY_MS = 150;
export const SNAP_TICKS = 60;
const RING = 96;               // 4.8 s of ticks
const GAPS = 80;

export class SnapshotBuffer {
  constructor() {
    this.ring = []; this.clock = null; this.lastNow = null; this.lastArrival = null;
    this.gaps = [];             // recent page-ms per server tick between arrivals
    this.jitter = 0;            // mean |gap - median gap|, ms
    this.hz = 20;               // observed snapshot rate
    this.late = 0;              // frames where the clock ran into the newest snapshot (the viewer saw a hold)
    this.snaps = 0;             // times the clock jumped to live
    this.scale = 1;             // viewer speed from slow-mo callouts (1 = live)
    this.rate = 1;              // the steering rate last frame
    this.count = 0;
  }

  get delayMs() { return Math.max(MIN_DELAY_MS, this.jitter * 4 + 5); }
  get targetLead() { return this.delayMs / TICK_MS; }
  get newest() { return this.ring.length ? this.ring[this.ring.length - 1] : null; }
  get lead() { const n = this.newest; return n && this.clock !== null ? n.tick - this.clock : 0; }
  get behindMs() { return this.lead * TICK_MS; }

  push(snap, now) {
    const last = this.newest;
    if (last && snap.tick <= last.tick) {
      if (snap.tick < last.tick - 2) { this.ring.length = 0; this.clock = null; this.gaps.length = 0; this.lastArrival = null; } // the server restarted a segment: start over
      else return;                                                                                                        // a duplicate
    }
    if (this.lastArrival !== null && this.newest && ++this.count > 6) { // the connect burst is not network jitter
      const per = (now - this.lastArrival) / Math.max(1, snap.tick - this.newest.tick);
      this.gaps.push(per); if (this.gaps.length > GAPS) this.gaps.shift();
      const sorted = this.gaps.slice().sort((a, b) => a - b), med = sorted[sorted.length >> 1];
      this.jitter = this.gaps.reduce((a, g) => a + Math.abs(g - med), 0) / this.gaps.length;
      this.hz = Math.min(20, 1000 / Math.max(1, med));
    }
    this.lastArrival = now;
    this.ring.push(snap);
    if (this.ring.length > RING) this.ring.shift();
  }

  // Advance the clock to page time `now` and return the pair to blend, or null before the first snapshot.
  sample(now) {
    const r = this.ring, last = this.newest;
    if (!last) return null;
    const dt = this.lastNow === null ? 0 : Math.min(250, Math.max(0, now - this.lastNow)); this.lastNow = now;
    if (this.clock === null) this.clock = Math.max(r[0].tick, last.tick - this.targetLead);
    const err = (last.tick - this.clock + 0.5) - this.targetLead; // ticks of surplus (+) or shortfall (-); +0.5: between arrivals the lead saws from n to n-1
    this.rate = Math.min(1.25, Math.max(0.4, (this.hz / 20) * (1 + err * 0.15))); // feed-forward on the observed snapshot rate, feedback on the buffered lead
    this.clock += dt / TICK_MS * this.rate * this.scale;
    if (last.tick - this.clock > this.targetLead + SNAP_TICKS) { this.clock = last.tick - this.targetLead; this.snaps++; }
    let held = false;
    if (this.clock >= last.tick) { this.clock = last.tick; held = true; this.late++; }
    const rt = this.clock;
    if (rt <= r[0].tick) return { a: r[0], b: r[0], k: 0, tick: r[0].tick, held };
    let i = r.length - 2;
    while (i > 0 && r[i].tick > rt) i--;
    const a = r[i], b = r[i + 1], span = Math.max(1, b.tick - a.tick), k = Math.min(1, Math.max(0, (rt - a.tick) / span));
    return { a, b, k, tick: rt, held };
  }
}
