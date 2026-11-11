// Public owner-read holds, in the B2 ticker vocabulary. No wallet or account data enters this notice.
const overlaps = (a, b, gap = 6) => a.x < b.x + b.w + gap && a.x + a.w + gap > b.x && a.y < b.y + b.h + gap && a.y + a.h + gap > b.y;
const HEALTH_POLL_MS = 30000, HEALTH_JITTER_MS = 5000, HEALTH_TIMEOUT_MS = 5000, HEALTH_BACKOFF_MS = 60000;
const HUD_OBSTACLES = '#world [data-panel]:not([data-kind="world"]), #world .collabel, #world .atag, .inset:not([hidden]), #status:not(.live), #snapin-cta, #diag, .arena-say-feed, .say-line, .say-emoji';
export function placeChainHold(size, obstacles, width, height) {
  const margin = 8, w = Math.min(size.w, width - 2 * margin), h = Math.min(size.h, height - 2 * margin);
  const right = width - w - margin, xs = [right, margin, (width - w) / 2], ys = new Set([margin]);
  for (const rect of obstacles) { ys.add(rect.y + rect.h + margin); ys.add(rect.y - h - margin); }
  let best = null, bestDistance = Infinity;
  for (const x of xs) for (const y of ys) {
    if (x < margin || y < margin || x + w > width - margin || y + h > height - margin) continue;
    const box = { x, y, w, h }, distance = (right - x) ** 2 + (y - margin) ** 2;
    if (distance < bestDistance && !obstacles.some((rect) => overlaps(box, rect))) { best = box; bestDistance = distance; }
  }
  return best;
}

export class ChainHold {
  constructor(element, { now = Date.now, random = Math.random } = {}) {
    this.element = element; this.message = ''; this.timer = null; this.request = null; this.position = ''; this.lastError = null;
    this.now = now; this.nextPollAt = 0; this.healthUrl = null; this.missingRoutes = new Set(); this.disabled = false;
    this.pollDelay = HEALTH_POLL_MS + Math.round(random() * HEALTH_JITTER_MS); this.pollToken = null; this.scheduledAt = 0;
    element.hidden = true; element.setAttribute('role', 'status'); element.setAttribute('aria-live', 'polite');
  }
  update(health) {
    const chain = health?.chain, count = chain?.lives_held_for_owner_read;
    this.element.hidden = !Number.isSafeInteger(count) || count <= 0;
    if (this.element.hidden) { this.message = ''; this.element.textContent = ''; return; }
    const age = chain.oldest_hold_s;
    const oldest = typeof age === 'number' && Number.isFinite(age) && age >= 0 ? Math.floor(age) + ' s' : 'unknown';
    this.message = 'Fighters waiting to respawn while owners are checked: ' + count + ' (longest ' + oldest + ')';
    if (this.element.textContent !== this.message) this.element.textContent = this.message;
    this.element.setAttribute('aria-label', this.message);
    const waiting = chain.owner_reads_waiting;
    this.element.title = Number.isSafeInteger(waiting) && waiting >= 0 ? 'Ownership checks pending: ' + waiting : '';
  }
  layout(width = innerWidth, height = innerHeight, obstacles = null) {
    if (this.element.hidden) return;
    const rects = obstacles || [...document.querySelectorAll(HUD_OBSTACLES)].filter((el) => !el.hidden && getComputedStyle(el).visibility !== 'hidden').map((el) => {
      const r = el.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height };
    }).filter((r) => r.w > 0 && r.h > 0);
    const r = this.element.getBoundingClientRect(), box = placeChainHold({ w: r.width, h: r.height }, rects, width, height);
    if (!box) { this.element.style.visibility = 'hidden'; return; }
    this.element.style.visibility = '';
    const position = 'translate(' + Math.round(box.x) + 'px,' + Math.round(box.y) + 'px)';
    if (position !== this.position) { this.position = position; this.element.style.transform = position; }
  }
  async readHealth(url, fetcher, signal) {
    this.healthUrl ||= url;
    let response = await fetcher(this.healthUrl, { cache: 'no-store', signal });
    if (response.status === 404) {
      this.missingRoutes.add(this.healthUrl);
      if (this.healthUrl === '/dev/health' && !this.missingRoutes.has('/health')) {
        this.healthUrl = '/health';
        response = await fetcher(this.healthUrl, { cache: 'no-store', signal });
      }
    }
    if (response.status === 404) {
      this.missingRoutes.add(this.healthUrl); this.disabled = true;
      if (this.timer !== null) clearTimeout(this.timer);
      this.timer = null; this.pollToken = null;
    }
    if (!response.ok) throw new Error('Health HTTP ' + response.status);
    return response.json();
  }
  async refresh(url, fetcher = globalThis.fetch) {
    if (this.request || this.disabled || this.now() < this.nextPollAt) return;
    const request = this.request = new AbortController(), timeout = setTimeout(() => request.abort(), HEALTH_TIMEOUT_MS);
    try {
      const health = await this.readHealth(url, fetcher, request.signal);
      if (this.request === request) { this.nextPollAt = 0; this.lastError = null; this.update(health); }
    } catch (error) {
      if (this.request === request) { this.nextPollAt = this.now() + HEALTH_BACKOFF_MS; this.lastError = String(error.message || error); }
      if (this.request === request && this.message) {
        this.element.textContent = this.message + ' · last check unavailable';
        this.element.setAttribute('aria-label', this.element.textContent);
      }
    } finally {
      clearTimeout(timeout);
      if (this.request === request) this.request = null;
      this.layout();
    }
  }
  startHealth(url = '/dev/health') {
    if (this.pollToken !== null || this.disabled) return;
    const token = this.pollToken = {};
    const poll = async () => {
      this.timer = null; this.scheduledAt = this.now() + this.pollDelay;
      try { await this.refresh(url); }
      finally {
        if (this.pollToken === token && !this.disabled) this.timer = setTimeout(poll, Math.max(0, this.scheduledAt - this.now(), this.nextPollAt - this.now()));
      }
    };
    const wait = Math.max(0, this.scheduledAt - this.now(), this.nextPollAt - this.now());
    if (wait) this.timer = setTimeout(poll, wait); else poll();
  }
  stopHealth() {
    this.pollToken = null;
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
    if (this.request) this.request.abort();
    this.request = null;
  }
}
