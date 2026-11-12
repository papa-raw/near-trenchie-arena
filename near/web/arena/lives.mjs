// Each fighter's current life as its name tag draws it: the predicted level (1-4, "L or more KOs", or none), its KOs
// this life, and the reward points a correct prediction earns. The host sends {fighter: {life, level, kos, points}} in
// the social frame (snap_local.public_lives) whenever it changes. Social frames are not buffered, the snapshots are
// (150 ms, buffer.mjs), so each change is applied only once the drawn picture has caught up with it: the circles fill
// on the KO the viewer sees, not before it.

export class Lives {
  constructor() { this.cur = new Map(); this.queue = []; this.met = new Set(); this.primed = false; }
  /** A social frame's lives map, received at `atMs` (page clock). null (socket closed) forgets everything. */
  receive(map, atMs) {
    if (map === null) { this.cur.clear(); this.queue = []; this.met.clear(); this.primed = false; return; }
    if (map && typeof map === 'object') this.queue.push({ at: atMs, map });
  }
  /** Apply every change received at or before `uptoMs`. Returns the predictions met by those changes:
   *  [{id, life, level, points}], one per life, never for a life already met when the page first saw it. */
  advance(uptoMs) {
    const out = [];
    while (this.queue.length && this.queue[0].at <= uptoMs) {
      const { map } = this.queue.shift();
      this.cur = new Map(Object.entries(map));
      for (const [id, v] of this.cur) {
        if (!Number.isInteger(v.level) || v.kos < v.level || this.met.has(v.life)) continue;
        this.met.add(v.life);
        if (this.primed) out.push({ id, life: v.life, level: v.level, points: v.points | 0 });
      }
      this.primed = true;
      const live = new Set([...this.cur.values()].map((v) => v.life));
      for (const life of this.met) if (!live.has(life)) this.met.delete(life);
    }
    return out;
  }
  /** The fighter's current life {life, level, kos, points}, or null. */
  get(id) { return this.cur.get(id) || null; }
}
