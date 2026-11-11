// The HUD, drawn by the approved panel art (board B2 a "Ticker and tags", frozen v3.1: hud-art/hud-art.js, never edited here).
// HUDART lays the panels out as SVG; we feed it the live state at ~4 Hz and re-place the pieces that follow a body (HP candles,
// name tags) every frame from the projected feet, so they never lag a moving trenchie.
import * as THREE from 'three';
import { placeQuirkPanel } from './hover.mjs';
import { HudPanelCache } from './hud-cache.mjs';
import { isDev, shortName, tagText } from './names.mjs';
import { layoutTags, TIER } from './tag-layout.mjs';
import { placeBanner, placeReplayStatus } from './layout.mjs';
import { rosterLabels } from './roster.mjs';
import { quirkText } from './quirks.mjs';
import { styleWord } from './style.mjs';

const REMOUNT_MS = 600;
const BANNER_MS = 4200;

export class Hud {
  constructor({ stage, actors, KITS, ITEMS, root, status = null }) {
    this.statusEl = status;
    this.artCache = new HudPanelCache(window.HUDART, { dpr: stage.renderer.getPixelRatio() });
    this.stage = stage; this.actors = actors; this.KITS = KITS; this.ITEMS = ITEMS; this.root = root;
    this.w = innerWidth; this.h = innerHeight;
    this.feed = []; this.mounting = false; this.lastMount = 0; this.world = []; this.lastLead = null; this.leadAt = 0; this.followed = null;
    root.style.position = 'fixed'; root.style.pointerEvents = 'none';
    this.layerHost = document.createElement('div'); this.layerHost.style.cssText = 'position:absolute;left:0;top:0;'; this.layerHost.style.zIndex = '3'; root.appendChild(this.layerHost);
    this.soundState = 'waiting for a click'; this.onMute = null; this.onMenu = null;
    // a small tag for every trenchie (Q18): quiet, high contrast, tight above the head
    this.tagLayer = document.createElement('div'); this.tagLayer.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:1;'; root.appendChild(this.tagLayer);
    this.tags = new Map(); this.styles = new Map(); this.bounties = new Set();
    this.speakers = new Set(); this.tagPrev = new Map();   // ids speaking now (Social.speaking); last frame's tag layout
    // the legendary receipt: anchored to the item on the floor, then to its holder, with a short leader
    this.recLayer = document.createElement('div'); this.recLayer.className = 'ha-layer ha-candle'; this.recLayer.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none;z-index:2;';
    this.leader = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); this.leader.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%;overflow:visible;pointer-events:none;z-index:2;';
    this.leaderLine = document.createElementNS('http://www.w3.org/2000/svg', 'path'); this.leaderLine.setAttribute('fill', 'none'); this.leaderLine.setAttribute('stroke', '#3B2F25'); this.leaderLine.setAttribute('stroke-width', '2'); this.leaderLine.setAttribute('stroke-dasharray', '3 3'); this.leaderLine.setAttribute('stroke-linecap', 'round');
    this.leaderDot = document.createElementNS('http://www.w3.org/2000/svg', 'circle'); this.leaderDot.setAttribute('r', '4'); this.leaderDot.setAttribute('fill', '#F7CF6B'); this.leaderDot.setAttribute('stroke', '#3B2F25'); this.leaderDot.setAttribute('stroke-width', '1.5');
    this.leader.append(this.leaderLine, this.leaderDot); root.append(this.leader, this.recLayer);
    this.legend = null; this.rects = {};
    // HP candles: drawn once per level by the panel art, then cloned per body every frame, so the SVG filters are not
    // rasterised again on every hit (the budget test: a 4 Hz redraw of the whole HUD cost 9-12% of frames over 1.5x the idle interval)
    this.barLayer = document.createElement('div'); this.barLayer.className = 'ha-layer ha-candle'; this.barLayer.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none;z-index:2;'; root.insertBefore(this.barLayer, this.layerHost);
    // the leaderboard cards: B2 a's top tag string, once for the house and once for players (prd: the house in its own column)
    this.cardLayer = document.createElement('div'); this.cardLayer.className = 'ha-layer ha-candle'; this.cardLayer.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none;z-index:3;'; root.appendChild(this.cardLayer);
    this.cards = []; this.cardsBox = null; this.tagRects = [];
    this.barHtml = null; this.barSize = null; this.bars = new Map(); this.building = false; this.sig = ''; this.barNarrow = null;
  }

  async buildBars() {
    if (this.building || !window.HUDART) return; this.building = true;
    const narrow = this.w < 600, html = [], host = document.createElement('div'); host.style.cssText = 'position:fixed;left:-6000px;top:0;width:' + this.w + 'px;height:' + this.h + 'px;pointer-events:none;'; document.body.appendChild(host);
    let size = null;
    for (let b = 0; b <= 10; b++) {
      await window.HUDART.mount(host, { concept: 'candle', draft: 'a', w: this.w, h: this.h, fighters: [{ x: 120, y: 200, tag: 'x', hp: b / 10, kos: 0, name: 'x' }], feed: [] });
      const node = host.querySelector('[data-panel="bar0"]'); if (!node) { this.building = false; host.remove(); return; }
      html.push(node.innerHTML); size = size || { w: node.firstElementChild ? node.firstElementChild.getBoundingClientRect().width || 46 : 46, h: 14 };
      await new Promise((r) => setTimeout(r, 0));
    }
    host.remove(); this.barHtml = html; this.barSize = size; this.barNarrow = narrow; this.building = false;
    for (const [, b] of this.bars) { b.el.remove(); } this.bars.clear();
  }

  placeBars(list, pos) {
    if (!this.barHtml || this.barNarrow !== (this.w < 600)) { if (!this.building) this.buildBars(); if (!this.barHtml) return; }
    const narrow = this.w < 600, seen = new Set(), bars = [];
    for (const f of list) {
      seen.add(f.id); const bucket = Math.max(0, Math.min(10, Math.round(f.hp * 10)));
      let b = this.bars.get(f.id);
      if (!b) { const el = document.createElement('div'); el.className = 'ha-p'; el.style.cssText = 'position:absolute;left:0;top:0;will-change:transform;'; this.barLayer.appendChild(el); b = { el, bucket: -1 }; this.bars.set(f.id, b); }
      if (b.bucket !== bucket) { b.el.innerHTML = this.barHtml[bucket]; b.bucket = bucket; const r = b.el.firstElementChild ? b.el.firstElementChild.getBoundingClientRect() : null; b.w = (r && r.width) || 46; b.h = (r && r.height) || 8; }
      const bx = f.x - (b.w || 46) / 2, by = f.y + (narrow ? 4 : 6);
      b.el.style.transform = 'translate(' + bx.toFixed(1) + 'px,' + by.toFixed(1) + 'px)';
      bars.push({ id: f.id, x: bx, y: by, w: b.w || 46, h: b.h || 8 });
    }
    this.barRects = bars;   // the tags keep clear of these (tag-layout obstacles)
    for (const [id, b] of this.bars) if (!seen.has(id)) { b.el.remove(); this.bars.delete(id); }
  }
  resize(w, h) { this.w = w; this.h = h; this.layerHost.style.width = w + 'px'; this.layerHost.style.height = h + 'px'; this.lastMount = 0; }

  tagOf(id) { return tagText(this.nameRoster(), id); } // the text the panel art and the inset caption draw: a DEV identity carries the word
  nameRoster() { return [...this.KITS.roster, ...(this.KITS.players || [])]; }
  itemName(row) { const it = this.ITEMS[row]; return it ? it.name : row; }

  onEvent(ev, snap) {
    if (ev.kind === 'ko') this.feed.push({ kind: 'ko', a: ev.source ? this.tagOf(ev.source) : null, b: this.tagOf(ev.fighter) });
    else if (ev.kind === 'grab' && !ev.destroyed) {
      const it = this.ITEMS[ev.row];
      if (it && it.tier === 'legendary') {
        this.feed.push({ kind: 'drop', a: this.tagOf(ev.fighter), b: this.tagOf(ev.fighter), item: it.name });
        const lg = this.legend; if (lg && lg.row === ev.row) { lg.holder = ev.fighter; lg.grabbedAt = performance.now(); lg.floor = null; }
        else this.startLegend({ row: ev.row, name: it.name, holder: ev.fighter, grabbedAt: performance.now() });
      }
    } else if (ev.kind === 'floor_loss' && this.legend && this.legend.key === ev.drop) { this.legend.gone = performance.now(); }
    if (this.feed.length > 8) this.feed.shift();
  }

  // a legendary appeared on the floor: draw its receipt beside it (the item itself is drawn by fx.mjs)
  onLegendDrop(d, nowMs) {
    const it = this.ITEMS[d.item]; if (!it || it.tier !== 'legendary') return;
    this.startLegend({ row: d.item, name: it.name, key: d.key, floor: { x: d.x / 1000, z: d.y / 1000 }, appearedAt: nowMs });
  }
  startLegend(o) {
    if (this.legend && this.legend.node) this.legend.node.remove();
    const lg = this.legend = { appearedAt: performance.now(), holder: null, grabbedAt: null, floor: null, gone: null, node: null, w: 0, h: 0, ...o };
    const tag = this.tagOf(o.holder || 'floor');
    window.HUDART.panels('candle', { w: this.w, h: this.h, fighters: [{ x: 0, y: 0, tag, name: tag, hp: 1 }], feed: [{ kind: 'drop', a: tag, b: tag, item: o.name }] }).then(async (list) => {
      const p = list.find((q) => q.id === 'drop'); if (!p || this.legend !== lg) return;
      const painted = await this.artCache.prepare(p.node); if (this.legend !== lg) return;
      lg.node = painted; lg.w = p.w; lg.h = p.h; p.node.style.transformOrigin = '0 0'; p.node.style.position = 'absolute'; p.node.style.left = '0'; p.node.style.top = '0'; p.node.style.opacity = '0'; this.recLayer.appendChild(painted);
    }).catch((error) => console.error('HUD receipt failed', error));
  }
  placeLegend(pos, nowMs) {
    const lg = this.legend; if (!lg) return;
    const now = performance.now(), age = now - lg.appearedAt;
    const life = lg.grabbedAt ? 3200 : 9000, since = lg.grabbedAt ? now - lg.grabbedAt : age;
    const end = lg.gone ? 600 : life;
    if (since > end + 700 || (lg.gone && now - lg.gone > 700)) { if (lg.node) lg.node.remove(); this.legend = null; this.leaderLine.setAttribute('d', ''); this.leaderDot.setAttribute('r', '0'); return; }
    if (!lg.node) return;
    let ax, ay;
    if (lg.holder) { const q = pos.get(lg.holder); if (!q) return; const sp = this.toScreen(q.x, 2.05, q.z); ax = sp.x; ay = sp.y; }
    else if (lg.floor) { const sp = this.toScreen(lg.floor.x, 0.9, lg.floor.z); ax = sp.x; ay = sp.y; }
    else return;
    const k = this.w < 600 ? 0.55 : 0.72, rw = lg.w * k, rh = lg.h * k, lift = lg.holder ? 26 : 54;
    // four places around the anchor; take the one that covers the fewest tags, inside the screen
    const cands = [[ax + 14, ay - lift - rh], [ax - 14 - rw, ay - lift - rh], [ax + 14, ay + 26], [ax - 14 - rw, ay + 26]].map(([cx, cy]) => [Math.max(6, Math.min(this.w - rw - 6, cx)), Math.max(6, Math.min(this.h - rh - 6, cy))]);
    const cover = ([cx, cy]) => this.tagRects.reduce((a, r) => a + Math.max(0, Math.min(cx + rw, r.x + r.w) - Math.max(cx, r.x)) * Math.max(0, Math.min(cy + rh, r.y + r.h) - Math.max(cy, r.y)), 0);
    let [x, y] = cands[0], best = cover(cands[0]);
    for (const c of cands.slice(1)) { const v = cover(c); if (v < best - 1) { best = v; [x, y] = c; } }
    lg.node.style.transform = 'translate(' + x.toFixed(1) + 'px,' + y.toFixed(1) + 'px) scale(' + k + ')';
    const fade = since > end ? Math.max(0, 1 - (since - end) / 700) : Math.min(1, age / 200);
    lg.node.style.opacity = String(fade); this.leader.style.opacity = String(fade);
    const below = y > ay, bx = Math.max(x + 14, Math.min(x + rw - 14, ax)), by = below ? y + 2 : y + rh - 2;
    this.leaderLine.setAttribute('d', 'M' + bx.toFixed(1) + ' ' + by.toFixed(1) + ' L' + ax.toFixed(1) + ' ' + ay.toFixed(1)); this.leaderDot.setAttribute('cx', ax.toFixed(1)); this.leaderDot.setAttribute('cy', ay.toFixed(1)); this.leaderDot.setAttribute('r', '4');
  }

  // every trenchie's tag: quiet, small, tight above the head. In a crowd tags move a row up or half a tag aside, or fade
  // out (tag-layout.mjs); your fighter, its focus target and the speaker always show, then the leader and bounties.
  placeTags(pos, lead) {
    const narrow = this.w < 600, seen = new Set(), items = [];
    const focusTargets = new Set([...pos].filter(([id, q]) => isDev(id) && q.f.status === 0 && q.f.target).map(([, q]) => q.f.target));
    const mine = this.followed != null ? pos.get(this.followed) : null, myTarget = mine && mine.f.status === 0 ? mine.f.target : null;
    if (myTarget) focusTargets.add(myTarget);
    const must = new Set([this.followed, myTarget, ...(this.speakers || [])].filter((id) => id != null));
    for (const [id, q] of pos) {
      if (q.f.status === 2 || q.state === 'ko') continue;
      const head = (q.state === 'bench' ? 1.45 : 1.6) + (q.lift || 0), sp = this.toScreen(q.x, head, q.z);
      let el = this.tags.get(id);
      if (!el) { el = document.createElement('div'); el.className = 'atag'; el.textContent = shortName(this.nameRoster(), id); if (isDev(id)) { const c = document.createElement('span'); c.className = 'dev'; c.textContent = 'DEV'; el.appendChild(c); } this.tagLayer.appendChild(el); this.tags.set(id, el); }
      el.setAttribute('data-fighter-id', id); el.setAttribute('data-target', q.f.target || '');
      const row = this.nameRoster().find((r) => r.trenchieId === id), word = styleWord(this.styles.get(id) || (row && row.fightStyle));
      let style = el.querySelector('.style-word');
      if (!style) { style = document.createElement('span'); style.className = 'style-word'; el.appendChild(style); }
      let focus = el.querySelector('.focus-mark');
      if (!focus) { focus = document.createElement('span'); focus.className = 'focus-mark'; el.appendChild(focus); }
      focus.textContent = isDev(id) && q.f.target ? '→ ' + shortName(this.nameRoster(), q.f.target) : '';
      let notice = el.querySelector('.name-notice');
      if (!notice) { notice = document.createElement('span'); notice.className = 'name-notice'; el.appendChild(notice); }
      notice.textContent = row?.nameNotice || '';
      let quirk = el.querySelector('.quirk-line');
      if (!quirk) { quirk = document.createElement('span'); quirk.className = 'quirk-line'; el.appendChild(quirk); }
      const text = quirkText(q.f, this.details?.rules);
      quirk.textContent = text ? shortName(this.nameRoster(), id) + ' · ' + text : '';
      style.textContent = word ? ' · ' + word : ''; el.tabIndex = 0; el.style.pointerEvents = 'auto';
      el.title = (row ? row.name : id) + (word ? ' · ' + word : ''); el.setAttribute('aria-label', el.title + (text ? ' · ' + text : ''));
      seen.add(id); items.push({ id, el, q, x: sp.x, y: sp.y, depth: q.x + q.z });
    }
    for (const [id, el] of this.tags) if (!seen.has(id)) { el.remove(); this.tags.delete(id); }
    // the class first, so each tag is measured at its drawn size; a hidden tag keeps tag-hidden while it is measured, or its
    // fade would restart every frame and it would never quite disappear
    const prevLayout = this.tagPrev || new Map();
    for (const it of items) it.el.className = (it.base = 'atag' + (it.id === lead ? ' lead' : '') + (it.id === this.followed ? ' followed' : '') + (it.q.state === 'bench' ? ' bench' : '') + (narrow ? ' narrow' : '') + (this.bounties.has(it.id) ? ' bounty' : '') + (focusTargets.has(it.id) ? ' focus-target' : '')) + (prevLayout.get(it.id)?.shown === false ? ' tag-hidden' : '');
    const layout = layoutTags(items.map((it) => ({ id: it.id, ax: it.x, ay: it.y, w: it.el.offsetWidth || 50, h: it.el.offsetHeight || 16, depth: it.depth,
      tier: must.has(it.id) ? TIER.must : it.id === lead || this.bounties.has(it.id) ? TIER.notable : TIER.other })), { w: this.w, h: this.h, prev: prevLayout, obstacles: this.barRects || [] });
    this.tagPrev = layout;
    const placed = [];
    for (const it of items) {
      const r = layout.get(it.id);
      if (r.shown) placed.push({ id: it.id, x: r.x, y: r.y, w: r.w, h: r.h });
      const cls = it.base + (r.shown ? '' : ' tag-hidden');   // faded out: no free place near its fighter this frame
      if (it.el.className !== cls) it.el.className = cls;
      it.el.style.transform = 'translate(' + r.x.toFixed(1) + 'px,' + r.y.toFixed(1) + 'px)';
    }
    this.tagRects = placed;
    // The body is separate from the pill's width, so expansion cannot shove neighbouring labels.
    for (const it of items) {
      const panel = it.el.querySelector('.quirk-line');
      if (!panel?.textContent || !it.el.matches?.(':hover, :focus-within')) continue;
      const anchor = placed.find((rect) => rect.id === it.id);
      const box = placeQuirkPanel(anchor, { w: panel.offsetWidth || 230, h: panel.offsetHeight || 60 }, placed, this.w, this.h, this.cardRects || []);
      panel.style.left = (box.x - anchor.x) + 'px'; panel.style.top = (box.y - anchor.y) + 'px';
    }
  }

  toScreen(x, y, z) {
    const v = new THREE.Vector3(x, y, z).project(this.stage.camera);
    return { x: (v.x + 1) / 2 * this.w, y: (1 - v.y) / 2 * this.h };
  }

  frame({ pos, kos, lead, rt, nowMs, snap }) {
    // who is on screen
    const list = [];
    for (const [id, p] of pos) if (p.state === 'alive') { const s = this.toScreen(p.x, 0, p.z), a = this.actors.get(id); list.push({ id, x: s.x, y: s.y, hp: Math.max(0, Math.min(1, p.f.hp / (a ? a.hpMax : 100))), kos: kos.get(id) || 0 }); }
    this.list = list;
    if (lead !== this.lastLead) { this.lastLead = lead; this.leadAt = nowMs; }
    this.allIds = [...pos.keys()].filter((id) => pos.get(id).f.status !== 2);
    const rl = this.roster ? rosterLabels(this.roster, this.w < 600) : null; // the host's public roster projection
    const top = (this.board ? this.board.rows(nowMs).slice(0, 5).map((r) => r.id + ':' + Math.round(r.perHour)) : []).join(','), sig = [lead, top, this.feed.length, this.feed.length ? this.feed[this.feed.length - 1].b : '', list.length, this.w, this.h, rl ? rl.house + rl.players : ''].join('|');
    if (!this.mounting && sig !== this.sig && nowMs - this.lastMount > REMOUNT_MS && window.HUDART) { this.sig = sig; this.remount(list, lead, nowMs); } // the panel art is redrawn when its content changes, not on a clock
    this.placeBars(list, pos);
    const banner = this.layerHost.querySelector('[data-panel="banner"]');
    if (banner) banner.style.display = lead && nowMs - this.leadAt < BANNER_MS && this.leadAt > 0 && nowMs > 8000 ? '' : 'none';
    this.applyBanner();
    this.placeTags(pos, lead); this.placeLegend(pos, nowMs); this.placeStatus();
  }

  remount(list, lead, nowMs) {
    this.mounting = true; this.lastMount = nowMs; (this.mountLog = this.mountLog || []).push(nowMs);
    if (!list.length) { this.mounting = false; return; }
    const effLead = lead || list[0].id; // with no KOs yet the panel art names the first body; we say so by naming it ourselves
    const fol = this.followed && list.some((f) => f.id === this.followed) ? this.followed : (list.filter((f) => f.id !== effLead).sort((a, b) => b.kos - a.kos)[0] || list[0]).id;
    const rows = this.board ? this.board.rows(nowMs) : [], rateOf = new Map(rows.map((r) => [r.id, Math.round(r.perHour)]));
    const inGame = (this.allIds || list.map((f) => f.id)).filter((id, i, a) => a.indexOf(id) === i);
    const rl = this.roster ? rosterLabels(this.roster) : null;
    const isHouse = (id) => (rl && rl.houseIds.size ? rl.houseIds.has(id) : (this.KITS.roster || []).some((r) => r.trenchieId === id));
    const rank = new Map(rows.map((r, i) => [r.id, i])), byRank = (a, b) => (rank.has(a) ? rank.get(a) : 99) - (rank.has(b) ? rank.get(b) : 99);
    const houseIds = inGame.filter(isHouse).sort(byRank), mainIds = (houseIds.length ? houseIds : inGame).slice(0, this.w < 700 ? 3 : 5); // the card shows the top few: build only those
    this.playerIds = inGame.filter((id) => !isHouse(id));
    const fighters = mainIds.map((id) => { const f = list.find((q) => q.id === id) || { x: -999, y: -999, hp: 1 }; return { x: f.x, y: f.y, tag: this.tagOf(id), hp: f.hp, kos: this.board ? (rateOf.get(id) || 0) : f.kos, state: id === fol ? 'followed' : '', name: this.tagOf(id) }; });
    const o = { concept: 'candle', draft: 'a', w: this.w, h: this.h, fighters, topN: this.w < 700 ? 3 : 5, lead: { tag: this.tagOf(effLead), kos: this.board ? (rateOf.get(effLead) || 0) : this.stageKos(effLead) }, feed: this.feed.slice(-4) };
    this.artCache.mount(this.layerHost, o, { only: ['board', 'banner', 'feed', 'btn0', 'btn1'] }).then((meas) => {
      const layer = this.layerHost.querySelector(':scope > .ha-layer'); if (!layer) { this.mounting = false; return; }
      layer.style.pointerEvents = 'none';
      this.world = []; this.rects = {};
      const narrow = this.w < 600;
      for (const r of meas.rects) this.rects[r.id] = r;
      const own = layer.querySelector('[data-panel="drop"]'); if (own) own.style.display = 'none'; // the receipt is drawn anchored to its item (placeLegend), never as this free-floating one
      for (const r of meas.rects) {
        const node = layer.querySelector('[data-panel="' + r.id + '"]'); if (!node) continue;
        if (r.kind === 'world') {
          const m = /^(bar|tag)(\d+)$/.exec(r.id); if (!m) continue;
          // bar<i> belongs to fighter i; tag<j> to the leader (0) or the followed fighter (1)
          node.style.display = 'none'; // the bars are cloned per body (placeBars); the two enamel name tags give way to the small tag every trenchie wears
        }
      }
      const b0 = layer.querySelector('[data-panel="btn0"]'), b1 = layer.querySelector('[data-panel="btn1"]');
      if (b0) { b0.style.pointerEvents = 'auto'; b0.style.cursor = 'pointer'; b0.onclick = () => this.onMute && this.onMute(); b0.title = 'Sound: ' + this.soundState; b0.setAttribute('role', 'button'); b0.setAttribute('aria-label', 'Sound ' + this.soundState); b0.style.opacity = this.soundState === 'muted' ? '0.45' : this.soundState === 'on' ? '1' : '0.8'; }
      if (b1) { b1.style.pointerEvents = 'auto'; b1.style.cursor = 'pointer'; b1.onclick = () => this.onMenu && this.onMenu(); }
      if (this.rects.board) { this.cardRects = this.estimateCards(this.rects.board, this.playerIds.length > 0); this.applyBanner(); }
      return this.buildCards(this.playerIds, rateOf, o.topN, this.rects.board).then(() => { this.mounting = false; }); // the main mount's own board is the house card; players, if any, get a second card
    }).catch((e) => { this.mounting = false; console.error('HUD mount failed', e); });
  }
  // the lead banner clears every card (layout.mjs); called each frame and right after a redraw, so a fresh node never shows at its natural place
  applyBanner() {
    const banner = this.layerHost.querySelector('[data-panel="banner"]'), N = this.rects.banner; if (!banner || !N) return;
    const p = placeBanner(N, this.cardRects || [], this.w); if (p) banner.style.transform = 'translate(' + p.x + 'px,' + p.y + 'px)';
  }
  placeStatus() {
    const el = this.statusEl;
    if (!el || !el.classList.contains('replay')) return;
    const w = el.offsetWidth || 150, h = el.offsetHeight || 28;
    const box = placeReplayStatus({ x: (this.w - w) / 2, y: this.h - h - 10, w, h }, this.rects.feed, this.w, this.h);
    el.style.left = box.x + 'px'; el.style.top = box.y + 'px'; el.style.bottom = 'auto'; el.style.transform = 'none';
  }
  // before the second card exists, what the cards will cover (the House card, its label, and a Players card if players are in the game)
  estimateCards(B, withPlayers) {
    const narrow = this.w < 600, off = narrow ? 2 : -3, rects = [{ x: B.x, y: B.y, w: B.w, h: B.h }, { x: B.x + 8, y: B.y + B.h + off, w: 60, h: 16 }];
    if (withPlayers) { const y2 = B.y + B.h + 22; rects.push({ x: B.x, y: y2, w: Math.max(90, B.w * 0.5), h: B.h }, { x: B.x + 8, y: y2 + B.h + off, w: 150, h: 16 }); }
    return rects;
  }

  // the house card is the main mount's own board; players, if any, get a second B2 a string under it (a second mount, only then).
  // Each card has a small label, the last one carries the caption.
  async buildCards(playerIds, rateOf, topN, B) {
    if (!B) return;
    const kc = this.w < 600 ? 0.72 : 1, rl = this.roster ? rosterLabels(this.roster, this.w < 600) : null;
    const made = [{ name: 'House', detail: rl ? rl.houseDetail : null, node: null, w: B.w, h: B.h }];
    if (playerIds.length) {
      const host = this.playerHost || (this.playerHost = document.createElement('div')); host.style.cssText = 'position:fixed;left:-6000px;top:0;width:' + this.w + 'px;height:' + this.h + 'px;pointer-events:none;'; document.body.appendChild(host);
      const fighters = playerIds.map((id) => ({ x: -999, y: -999, tag: this.tagOf(id), hp: 1, kos: rateOf.get(id) || 0, name: this.tagOf(id) })), lead = fighters.slice().sort((a, b) => b.kos - a.kos)[0];
      const meas = await this.artCache.mount(host, { concept: 'candle', draft: 'a', w: this.w, h: this.h, fighters, topN, lead: { tag: lead.tag, kos: lead.kos }, feed: [] }, { only: ['board'] });
      const node = this.artCache.panel(host, 'board'), r = meas.rects.find((q) => q.id === 'board'); host.remove();
      if (node && r) made.push({ name: rl ? rl.players : 'Players', node, w: r.w, h: r.h });
    }
    for (const c of this.cards) { c.label.remove(); if (c.label.detailTag) c.label.detailTag.remove(); if (c.node) c.node.remove(); } this.cards = [];
    let y = B.y; const rects = [];
    made.forEach((m, i) => {
      if (m.node) { m.node.style.position = 'absolute'; m.node.style.left = '0'; m.node.style.top = '0'; m.node.style.transformOrigin = '0 0'; m.node.style.transform = 'translate(' + B.x + 'px,' + y + 'px)' + (kc !== 1 ? ' scale(' + kc + ')' : ''); this.cardLayer.appendChild(m.node); }
      const label = document.createElement('div'); label.className = 'atag collabel' + (this.w < 600 ? ' narrow' : ''); label.dataset.card = i ? 'players' : 'house'; label.textContent = i === made.length - 1 ? m.name + ' · since you arrived' : m.name;
      label.style.cssText += 'position:absolute;left:0;top:0;'; label.style.transform = 'translate(' + (B.x + 8) + 'px,' + (y + m.h + (this.w < 600 ? 2 : -3)) + 'px)'; this.cardLayer.appendChild(label);
      if (m.detail) {   // the roster's count, meter or chip, its own tag beside the card's label
        const tag = document.createElement('div'); tag.className = 'atag collabel roster' + (this.w < 600 ? ' narrow' : ''); tag.dataset.card = 'house-roster'; tag.textContent = m.detail;
        tag.style.cssText += 'position:absolute;left:0;top:0;'; tag.style.transform = 'translate(' + (B.x + 8 + (label.offsetWidth || 60) + 6) + 'px,' + (y + m.h + (this.w < 600 ? 2 : -3)) + 'px)'; this.cardLayer.appendChild(tag);
        label.detailTag = tag;
      }
      this.cards.push({ node: m.node, label }); rects.push({ x: B.x, y, w: m.w, h: m.h }, { x: B.x + 8, y: y + m.h + (this.w < 600 ? 2 : -3), w: label.offsetWidth || 60, h: label.offsetHeight || 16 }); y += m.h + 22;
    });
    this.cardRects = rects; this.applyBanner();
    this.cardsBox = { right: B.x + Math.max(...made.map((m) => m.w)), bottom: y };
  }
  stageKos(id) { return (window.ARENA && window.ARENA.kos.get(id)) || 0; }
}
