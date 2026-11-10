// Slow-mo callouts (F18). On a big KO (the board leader goes down) or a legendary steal, the viewer's clock runs at x0.3 for 1.5 s,
// then the buffer's own steering catches up at up to x1.25 until the viewer is within one buffer of live; a drift past 3 s jumps to
// live. It is client-side only: the server never pauses. At most one legendary-steal callout a minute per viewer.
export const SLOW_SCALE = 0.3, SLOW_MS = 1500, STEAL_GAP_MS = 60000;

export class Slowmo {
  constructor(buffer) { this.buffer = buffer; this.until = 0; this.lastSteal = -1e9; this.count = { leader_ko: 0, steal: 0 }; this.kind = null; }
  // returns true if a callout started
  trigger(kind, nowMs) {
    if (nowMs < this.until) return false;                                  // one at a time
    if (kind === 'steal') { if (nowMs - this.lastSteal < STEAL_GAP_MS) return false; this.lastSteal = nowMs; }
    this.until = nowMs + SLOW_MS; this.kind = kind; this.count[kind] = (this.count[kind] || 0) + 1; this.buffer.scale = SLOW_SCALE; return true;
  }
  update(nowMs) { if (this.buffer.scale !== 1 && nowMs >= this.until) { this.buffer.scale = 1; this.kind = null; } }
  get active() { return this.buffer.scale !== 1; }
}
