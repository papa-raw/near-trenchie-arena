// The leaderboard (W6): KOs per hour played, with a 60-minute minimum, house trenchies in their own column, this hour's top 5.
//   rate = KOs in the window / max(hours played in the window, 1)
// so a trenchie that has played 20 minutes is ranked as if it had played an hour: a lucky first fight cannot top the board.
// Ties: more KOs, then fewer times knocked out per hour, then the id (a stable last resort).
// "This hour" is the default window (one hour), where the rate equals the KO count. A longer window (the nightly report) uses the
// same formula. The clock is the viewer's: this counts what this page has seen, from when it was opened. The server-side hourly
// board belongs to the host's report, and the panel says "since you arrived" until that exists.

export const HOUR_MS = 3600000;

export class Leaderboard {
  constructor({ windowMs = HOUR_MS, isHouse = () => false } = {}) {
    this.windowMs = windowMs; this.isHouse = isHouse;
    this.kos = [];            // {id, at}
    this.deaths = [];         // {id, at}: who was knocked out, the tie-break after KOs
    this.present = new Map(); // id -> [{from, to}] spans of being in the game (ring or bench)
    this.since = null;        // the first time this board saw anything
  }

  onKo(killerId, atMs, victimId) { if (killerId) this.kos.push({ id: killerId, at: atMs }); if (victimId) this.deaths.push({ id: victimId, at: atMs }); }

  // call every frame with the ids that are in the game (alive or waiting on the bench) at `nowMs`
  presence(ids, nowMs, gapMs = 1500) {
    if (this.since === null) this.since = nowMs;
    const here = new Set(ids);
    for (const id of here) {
      const spans = this.present.get(id) || []; const last = spans[spans.length - 1];
      if (last && nowMs - last.to <= gapMs) last.to = nowMs; else spans.push({ from: nowMs, to: nowMs });
      this.present.set(id, spans);
    }
  }

  playedMs(id, nowMs) {
    const lo = nowMs - this.windowMs; let t = 0;
    for (const s of this.present.get(id) || []) t += Math.max(0, Math.min(s.to, nowMs) - Math.max(s.from, lo));
    return t;
  }
  koCount(id, nowMs) { const lo = nowMs - this.windowMs; let n = 0; for (const k of this.kos) if (k.id === id && k.at > lo && k.at <= nowMs) n++; return n; }

  deathCount(id, nowMs) { const lo = nowMs - this.windowMs; let n = 0; for (const k of this.deaths) if (k.id === id && k.at > lo && k.at <= nowMs) n++; return n; }

  rate(id, nowMs) { return this.koCount(id, nowMs) / Math.max(this.playedMs(id, nowMs) / HOUR_MS, 1); }

  // every id the board knows, ranked: rate, then KOs, then id (a stable tie-break)
  rows(nowMs) {
    const ids = new Set([...this.present.keys(), ...this.kos.map((k) => k.id)]);
    const perH = (id, n) => n / Math.max(this.playedMs(id, nowMs) / HOUR_MS, 1);
    const rows = [...ids].map((id) => ({ id, house: this.isHouse(id), kos: this.koCount(id, nowMs), playedMs: this.playedMs(id, nowMs), perHour: this.rate(id, nowMs), deathsPerHour: perH(id, this.deathCount(id, nowMs)) }));
    return rows.sort((a, b) => b.perHour - a.perHour || b.kos - a.kos || a.deathsPerHour - b.deathsPerHour || (a.id < b.id ? -1 : 1));
  }
  // the board's two columns, top n each; `all` is the single ranking the on-screen card shows
  columns(nowMs, n = 5) {
    const rows = this.rows(nowMs);
    return { house: rows.filter((r) => r.house).slice(0, n), players: rows.filter((r) => !r.house).slice(0, n), all: rows.slice(0, n) };
  }
}
