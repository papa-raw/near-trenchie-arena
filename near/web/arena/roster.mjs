// The public roster projection: the host's /house/roster, polled at the status writer's 5 s period.
// It feeds the HUD's card labels: who is admitted (house and players, bench included), the house's metered
// spend today, and the autopilot chip when the house's model calls are stopped. Only public fields arrive here.

export const PERIOD_MS = 5000;

/** The roster route on the same host as the spectator socket. */
export function rosterUrl(wsUrl) {
  const u = new URL(wsUrl);
  u.protocol = u.protocol === 'wss:' ? 'https:' : 'http:';
  u.pathname = '/house/roster'; u.search = ''; u.hash = '';
  return u.href;
}

function dollars(micro) {
  const d = Number(micro || 0) / 1e6;
  return '$' + (d < 0.1 ? d.toFixed(3) : d.toFixed(2));
}

/** The card labels from one projection. Narrow screens drop the meter, never the count or the chip. */
export function rosterLabels(roster, narrow = false) {
  const rows = (roster && roster.members) || [];
  const house = rows.filter((r) => r.house).length, players = rows.length - house;
  // The card labels stay the approved board's words ("House", "Players"; the last card adds "since you arrived", which is
  // about the faces' KO counts). The roster's count, meter and chip are a separate tag beside the House label, so the
  // caption never reads as "admitted since you arrived".
  let h = house + ' admitted';
  if (roster && roster.chip) h += ' · ' + roster.chip;
  else if (!narrow && roster) h += ' · ' + dollars(roster.house_spend_today_microusd) + ' today';
  if (roster && roster.battle_style) h += ' · ' + roster.battle_style;   // "lean" while building, "full" on judging days
  // The Players card keeps its approved board label (B2 a v3.1); the count rides on the House label only.
  return { house: 'House', houseDetail: h, players: 'Players', admitted: rows.length, houseCount: house, playerCount: players,
           houseIds: new Set(rows.filter((r) => r.house && r.id).map((r) => r.id)) };
}

/** Polls the projection; a failed poll keeps the last good one and says so once on the console. */
export class RosterFeed {
  // The default calls the page's fetch as a plain function: stored and called as a method, a browser throws
  // "Illegal invocation", so it is never kept unbound.
  constructor(url, onRoster, { fetchFn = (...a) => globalThis.fetch(...a), periodMs = PERIOD_MS } = {}) {
    this.url = url; this.onRoster = onRoster; this.fetchFn = fetchFn; this.periodMs = periodMs; this.timer = null; this.warned = false;
  }
  async poll() {
    try {
      const r = await this.fetchFn(this.url, { cache: 'no-store' });
      if (!r.ok) throw new Error('roster ' + r.status);
      this.onRoster(await r.json()); this.warned = false;
    } catch (e) { if (!this.warned) { this.warned = true; console.warn('roster unavailable: the card labels show the last roster', String(e)); } }
  }
  start() { this.poll(); this.timer = setInterval(() => this.poll(), this.periodMs); return this; }
  stop() { clearInterval(this.timer); this.timer = null; }
}
