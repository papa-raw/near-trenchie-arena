// The arena HUD, approved board 2 (direction C, "Wall sign", sheet r5-sheet2): the wall sign with its two boards, the
// one merged feed of paper slips, the corner buttons and "How it works", every trenchie's name tag with its prediction
// circles, the crowd card, the legendary floor sign and the pre-jump card. The HP candles under each body are still the
// approved panel art's (hud-art/hud-art.js, frozen), cloned per body. Everything that follows a body is placed every frame
// from the projected feet, so it never lags a moving trenchie; the rest is DOM that changes only when its data does.
import * as THREE from 'three';
import { placeQuirkPanel } from './hover.mjs';
import { isDev, shortName } from './names.mjs';
import { layoutTags, TIER } from './tag-layout.mjs';
import { placeReplayStatus } from './layout.mjs';
import { quirkText } from './quirks.mjs';
import { styleWord } from './style.mjs';
import { circlesModel, circlesNode, circlesKey, crowdGroups, cardSpot, reachFor } from './pips.mjs';
import { Feed, nameColour } from './feed.mjs';
import { Sign } from './sign.mjs';
import { Corner } from './corner.mjs';
import { Prejump } from './prejump.mjs';
import { Lives } from './lives.mjs';
import { itemStill, houseFace, playerFace } from './stills.mjs';
import { hudLayout, panelBoxes } from './hud-layout.mjs';

const LEG_FADE_MS = 300;

export class Hud {
  constructor({ stage, actors, KITS, ITEMS, root, status = null, itemRenderer = null, LOOK3 = null }) {
    this.statusEl = status; this.itemRenderer = itemRenderer; this.LOOK3 = LOOK3;
    this.stage = stage; this.actors = actors; this.KITS = KITS; this.ITEMS = ITEMS; this.root = root;
    this.w = innerWidth; this.h = innerHeight; this.followed = null; this.names = {}; this.boards = null;
    root.style.position = 'fixed'; root.style.pointerEvents = 'none';
    if (!document.querySelector('link[data-b2]')) { const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = new URL('./board2.css', import.meta.url).href; l.dataset.b2 = '1'; document.head.appendChild(l); }
    // name tags (Q18) with their circles, and the crowd cards
    this.tagLayer = document.createElement('div'); this.tagLayer.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:1;'; root.appendChild(this.tagLayer);
    this.tags = new Map(); this.cards = new Map(); this.styles = new Map(); this.bounties = new Set(); this.tagPrev = new Map(); this.tagRects = []; this.cardRects = [];
    // HP candles: drawn once per level by the panel art, then cloned per body every frame
    this.barLayer = document.createElement('div'); this.barLayer.className = 'ha-layer ha-candle'; this.barLayer.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none;z-index:2;'; root.insertBefore(this.barLayer, this.tagLayer);
    this.barHtml = null; this.barSize = null; this.bars = new Map(); this.building = false; this.barNarrow = null;
    // the legendary floor signs, one per legendary on the floor
    this.legLayer = document.createElement('div'); this.legLayer.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:2;'; root.appendChild(this.legLayer);
    this.legends = new Map();
    // the HUD proper: sign, feed, buttons, pre-jump cards
    this.ui = document.createElement('div'); this.ui.className = 'b2'; root.appendChild(this.ui);
    this.lives = new Lives();
    this.sign = new Sign(document, this.ui, { name: (id) => this.nameOf(id), face: (id) => this.faceOf(id), dev: isDev });
    this.feed = new Feed(document, this.ui, { name: (id) => this.nameOf(id), colour: (id) => this.colourOf(id), dev: isDev });
    this.feed.list.classList.add('arena-say-feed');
    this.onMute = null; this.soundState = 'waiting for a click';
    this.corner = new Corner(document, this.ui, { onSound: () => this.onMute && this.onMute() });
    this.prejump = new Prejump(document, this.ui);
    this.rects = {}; this.layoutAt = 0;
    this.idle(performance.now());   // the sign, the feed and the buttons are in place with their words before any arena answers
  }
  /** No snapshot to draw (no arena yet, or between reconnects): keep the fixed HUD laid out and worded. */
  idle(nowMs) { this.corner.setSound(this.soundState); this.layoutHud(nowMs); this.placeStatus(); }

  // ---- names, colours and faces ------------------------------------------------------------------------------------
  nameRoster() { return [...this.KITS.roster, ...(this.KITS.players || [])]; }
  rowOf(id) { return this.nameRoster().find((r) => r.trenchieId === id) || null; }
  /** The trenchie's name, never an id: the roster tag (Q18), a player's name, or the host's names map. A DEV identity
   *  carries a DEV chip wherever its name shows (the feed and the sign draw it beside the name, names.mjs isDev). */
  nameOf(id) {
    if (id == null) return '';
    const row = this.rowOf(id);
    return row ? (row.tag || row.name) : ((this.names && this.names[id]) || (isDev(id) ? id.slice(4) : id));
  }
  tagOf(id) { return isDev(id) ? this.nameOf(id) + ' DEV' : this.nameOf(id); }   // the follow view's caption and the moments (plain text)
  colourOf(id) {
    const row = this.rowOf(id), pal = (this.LOOK3 && this.LOOK3.PAL) || {};
    const p = row && row.paletteIds && row.paletteIds[0];
    return nameColour(pal[p] || p || null);
  }
  faceOf(id) {
    if ((this.KITS.roster || []).some((r) => r.trenchieId === id)) return houseFace(id);
    return playerFace((this.KITS.players || []).find((r) => r.trenchieId === id));
  }

  /** The KO leader of the hour: the most KOs on the sign's hour board, players and house together; null when none. */
  leader() {
    const b = this.boards && this.boards.boards && this.boards.boards.most_kos_hour;
    if (!b) return null;
    const rows = [...(b.players || []), ...(b.house || [])].filter((r) => r.kos > 0).sort((x, y) => y.kos - x.kos || y.lives - x.lives || (x.persona < y.persona ? -1 : 1));
    return rows.length ? rows[0].persona : null;
  }
  setBoards(json) { this.boards = json; this.sign.setData(json); }

  // ---- events --------------------------------------------------------------------------------------------------------
  // a KO, with whether it was an ambush (moments.mjs)
  onKo(ev, ambush) { this.feed.push({ kind: 'ko', who: ev.source || null, victim: ev.fighter, ambush: !!ambush }); }
  // a moment worked out by moments.mjs (a legendary on the sand, a legendary grabbed by a stranger, a near-death escape)
  onMoment(m) {
    if (m.kind === 'legendary_drop') { if (!(m.fighter && this.feed.upgradeKo(m.fighter, m.item))) { if (m.fighter) this.feed.push({ kind: 'leg', who: null, victim: m.fighter, item: m.item, moment: m.kind }); } }
    else if (m.kind === 'legendary_steal') this.feed.push({ kind: 'leg', steal: true, who: m.fighter, from: m.other, item: m.item, moment: m.kind });
    else if (m.kind === 'near_death') this.feed.push({ kind: 'escape', who: m.fighter, hp: Number(/(\d+) HP/.exec(m.text || '')?.[1] || 0), moment: m.kind });
  }
  // a life starts: its prediction line and, if it predicts, the pre-jump card. Returns how long the body's drop waits (ms).
  onRespawn(ev, nowMs) {
    const v = this.lives.get(ev.fighter), level = v && v.life === ev.life_id ? v.level : null;
    if (!Number.isInteger(level)) return 0;
    this.feed.push({ kind: 'pred', who: ev.fighter, level });
    return this.prejump.start(ev.fighter, this.tagOf(ev.fighter), level, nowMs) ? 250 : 0;
  }
  // a legendary on the floor: its sign, anchored to the item
  onLegendDrop(d) {
    const it = this.ITEMS[d.item]; if (!it || it.tier !== 'legendary' || this.legends.has(d.key)) return;
    const sign = document.createElement('div'); sign.className = 'legsign'; sign.dataset.drop = d.key;
    const pic = this.itemRenderer ? itemStill(this.itemRenderer, this.LOOK3, d.item) : null;
    if (pic) { const img = document.createElement('img'); img.src = pic; img.alt = ''; sign.appendChild(img); } else { const s = document.createElement('span'); s.className = 'noimg'; sign.appendChild(s); }
    const t = document.createElement('span'), b = document.createElement('b'); b.textContent = 'LEGENDARY:'; t.append(b, document.createTextNode(' ' + String(it.name).toUpperCase())); sign.appendChild(t);
    const pin = document.createElement('i'); pin.className = 'legpin';
    this.legLayer.append(sign, pin);
    this.legends.set(d.key, { sign, pin, x: d.x / 1000, z: d.y / 1000, gone: null, w: 0, h: 0 });
  }
  // each drawn snapshot's drops: a new legendary gets its sign; one that left the floor (grabbed, or gone after 60 s) fades
  syncDrops(drops, nowMs) {
    const here = new Set();
    for (const d of drops) { here.add(d.key); this.onLegendDrop(d); }
    for (const [key, lg] of this.legends) if (!here.has(key) && lg.gone == null) lg.gone = nowMs;
  }

  // ---- HP candles (the approved panel art, cloned per body) -------------------------------------------------------------
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
  placeBars(list) {
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
  resize(w, h) { this.w = w; this.h = h; this.layoutAt = 0; }

  // ---- the fixed HUD: buttons, sign, feed (re-laid out when the window or board 1's panel changes) ---------------------
  layoutHud(nowMs) {
    if (nowMs - this.layoutAt < 250) return;
    this.layoutAt = nowMs;
    const view = { w: this.w, h: this.h }, corner = this.corner.rect();
    const L = hudLayout(view, panelBoxes(document), { w: corner.w || 260, h: corner.h || 44 });
    this.corner.place(L); this.corner.box.classList.toggle('phone', L.phone);
    this.sign.layout(view, L.free); this.panTarget = L.pan;
    this.feed.setNarrow(L.phone);
    this.feed.box.classList.toggle('phone', L.phone); this.feed.box.classList.toggle('n3', L.phone); this.feed.box.classList.toggle('n5', !L.phone);
    this.feed.box.classList.toggle('hidden', L.feedHidden);
    // the feed sits above the buttons on a phone (they share the bottom edge)
    this.feed.box.style.bottom = (L.phone ? L.bottom + (corner.h || 44) + 8 : 16) + 'px';
    const rect = (el) => { const r = el.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; };
    this.rects = { board: this.sign.rect(), feed: L.feedHidden ? null : rect(this.feed.box), btn0: rect(this.corner.sound), btn1: rect(this.corner.menu) };
    this.cardRects = [this.rects.board];   // the quirk panel keeps off the sign (hover.mjs)
  }

  // ---- name tags, circles and crowd cards -----------------------------------------------------------------------------
  // (the tag fixtures in the quirk and agent-review cases build a bare Hud: lives, cards and rects are optional here)
  placeTags(pos, lead, nowMs = 0) {
    const narrow = this.w < 600, seen = new Set(), items = [], lives = this.lives, rects = this.rects || {};
    const focusTargets = new Set([...pos].filter(([id, q]) => isDev(id) && q.f.status === 0 && q.f.target).map(([, q]) => q.f.target));
    const mine = this.followed != null ? pos.get(this.followed) : null, myTarget = mine && mine.f.status === 0 ? mine.f.target : null;
    if (myTarget) focusTargets.add(myTarget);
    const must = new Set([this.followed, myTarget].filter((id) => id != null));
    for (const [id, q] of pos) {
      if (q.f.status === 2 || q.state === 'ko') continue;
      const head = (q.state === 'bench' ? 1.45 : 1.6) + (q.lift || 0), sp = this.toScreen(q.x, head, q.z);
      let el = this.tags.get(id);
      if (!el) {
        el = document.createElement('div'); el.className = 'atag';
        const nm = document.createElement('span'); nm.className = 'tname'; nm.textContent = shortName(this.nameRoster(), id); el.appendChild(nm);
        if (isDev(id)) { const c = document.createElement('span'); c.className = 'dev'; c.textContent = 'DEV'; el.appendChild(c); }
        const circ = document.createElement('span'); circ.className = 'circ'; circ.dataset.key = ''; el.appendChild(circ);
        this.tagLayer.appendChild(el); this.tags.set(id, el);
      }
      el.setAttribute('data-fighter-id', id); el.setAttribute('data-target', q.f.target || '');
      // the circles: alive fighters with a counted prediction for this life
      const life = lives ? lives.get(id) : null, m = q.state === 'alive' && life ? circlesModel(life.level, life.kos) : null, key = circlesKey(m), circ = el.querySelector('.circ');
      if (circ.dataset.key !== key) { circ.dataset.key = key; circ.replaceChildren(...(m ? [Object.assign(document.createElement('span'), { className: 'sep' }), circlesNode(document, m)] : [])); }
      const row = this.rowOf(id), word = styleWord(this.styles.get(id) || (row && row.fightStyle));
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
      el.title = (row ? row.name : this.nameOf(id)) + (word ? ' · ' + word : ''); el.setAttribute('aria-label', el.title + (m ? ' · predicts ' + m.n + '+ KOs, ' + (m.filled + m.extra) + ' so far' : '') + (text ? ' · ' + text : ''));
      seen.add(id); items.push({ id, el, q, m, x: sp.x, y: sp.y, depth: q.x + q.z, landing: !!this.prejump && this.prejump.active(id, nowMs) });
    }
    for (const [id, el] of this.tags) if (!seen.has(id)) { el.remove(); this.tags.delete(id); }
    // the crowd rule: three or more alive fighters within reach share one card; your own fighter keeps its own tag
    const alive = items.filter((it) => it.q.state === 'alive' && !it.landing && it.id !== this.followed);
    const groups = crowdGroups(alive.map((it) => ({ id: it.id, x: it.x, y: it.y })), reachFor(this.w));
    const grouped = new Set(groups.flat());
    const prevLayout = this.tagPrev || new Map();
    const solo = items.filter((it) => !grouped.has(it.id) && !it.landing);
    for (const it of items) {
      it.base = 'atag' + (it.id === lead ? ' lead' : '') + (it.id === this.followed ? ' followed' : '') + (it.q.state === 'bench' ? ' bench' : '') + (narrow ? ' narrow' : '') + (this.bounties.has(it.id) ? ' bounty' : '') + (focusTargets.has(it.id) ? ' focus-target' : '');
      if (!grouped.has(it.id) && !it.landing) it.el.className = it.base + (prevLayout.get(it.id)?.shown === false ? ' tag-hidden' : '');
    }
    const layout = layoutTags(solo.map((it) => ({ id: it.id, ax: it.x, ay: it.y, w: it.el.offsetWidth || 50, h: it.el.offsetHeight || 16, depth: it.depth,
      tier: must.has(it.id) ? TIER.must : it.id === lead || this.bounties.has(it.id) ? TIER.notable : TIER.other })), { w: this.w, h: this.h, prev: prevLayout, obstacles: [...(this.barRects || []), ...(rects.board ? [rects.board] : [])] });
    // a fighter in a crowd card counts as shown: when the crowd breaks up its own tag comes back at once, not after
    // the newly-shown wait (tag-layout SHOW_AFTER), so a tag never blinks out between the card and its own place
    for (const id of grouped) layout.set(id, { x: 0, y: 0, w: 0, h: 0, shown: true, slot: 0, streak: Math.max(1, prevLayout.get(id)?.streak || 0) });
    this.tagPrev = layout;
    const placed = [];
    for (const it of items) {
      if (grouped.has(it.id) || it.landing) { const cls = it.base + ' tag-hidden'; if (it.el.className !== cls) it.el.className = cls; continue; }   // in a card, or still landing
      const r = layout.get(it.id);
      if (r.shown) placed.push({ id: it.id, x: r.x, y: r.y, w: r.w, h: r.h });
      const cls = it.base + (r.shown ? '' : ' tag-hidden');
      if (it.el.className !== cls) it.el.className = cls;
      it.el.style.transform = 'translate(' + r.x.toFixed(1) + 'px,' + r.y.toFixed(1) + 'px)';
    }
    if (groups.length || (this.cards && this.cards.size)) this.placeCards(groups, items, alive, lead, placed);
    this.tagRects = placed;
    for (const it of items) {
      const panel = it.el.querySelector('.quirk-line');
      if (!panel?.textContent || !it.el.matches?.(':hover, :focus-within')) continue;
      const anchor = placed.find((rect) => rect.id === it.id); if (!anchor) continue;
      const box = placeQuirkPanel(anchor, { w: panel.offsetWidth || 230, h: panel.offsetHeight || 60 }, placed, this.w, this.h, this.cardRects || []);
      panel.style.left = (box.x - anchor.x) + 'px'; panel.style.top = (box.y - anchor.y) + 'px';
    }
  }
  placeCards(groups, items, alive, lead, placed) {
    const byId = new Map(items.map((it) => [it.id, it])), keep = new Set();
    const rects = this.rects || {}, sign = rects.board, top = sign ? sign.y + sign.h + 8 : 8;
    this.cards = this.cards || new Map();
    const lows = [rects.feed, rects.btn0, rects.btn1].filter(Boolean).map((r) => r.y);
    const view = { w: this.w, h: this.h, top, bottom: (lows.length ? Math.min(...lows) : this.h) - 8 };
    for (const ids of groups) {
      const key = ids.join('|'); keep.add(key);
      let c = this.cards.get(key);
      if (!c) { const el = document.createElement('div'); el.className = 'gcard'; el.dataset.fighters = key; this.tagLayer.appendChild(el); c = { el, sig: '' }; this.cards.set(key, c); }
      const rows = ids.map((id) => { const life = this.lives ? this.lives.get(id) : null; return { id, m: life ? circlesModel(life.level, life.kos) : null }; });
      const sig = rows.map((r) => r.id + (r.id === lead ? '*' : '') + circlesKey(r.m)).join(',');
      if (sig !== c.sig) {
        c.sig = sig;
        const h = document.createElement('div'); h.className = 'gh'; h.textContent = ids.length + ' here';
        c.el.replaceChildren(h, ...rows.map((r) => {
          const row = document.createElement('div'); row.className = 'gr' + (r.id === lead ? ' lead' : ''); row.dataset.fighterId = r.id;
          const nm = document.createElement('span'); nm.className = 'nm2'; nm.textContent = shortName(this.nameRoster(), r.id);
          if (isDev(r.id)) { const d = document.createElement('span'); d.className = 'dev'; d.textContent = 'DEV'; nm.appendChild(d); }
          row.appendChild(nm); if (r.m) row.appendChild(circlesNode(document, r.m));
          return row;
        }));
        c.el.setAttribute('aria-label', ids.length + ' here: ' + ids.map((id) => this.nameOf(id)).join(', '));
      }
      const w = c.el.offsetWidth || 140, hgt = c.el.offsetHeight || 22 + 16 * ids.length;
      const members = ids.map((id) => ({ id, x: byId.get(id).x, y: byId.get(id).y }));
      const others = alive.filter((it) => !ids.includes(it.id)).map((it) => ({ id: it.id, x: it.x, y: it.y }));
      const spot = cardSpot(members, others, { w, h: hgt }, view);
      const bx = Math.max(8, Math.min(this.w - w - 8, spot.box.x)), by = Math.max(8, Math.min(this.h - hgt - 8, spot.box.y));
      c.el.dataset.pos = spot.pos; c.el.style.transform = 'translate(' + bx.toFixed(1) + 'px,' + by.toFixed(1) + 'px)';
      placed.push({ id: key, x: bx, y: by, w, h: hgt });
    }
    for (const [key, c] of this.cards) if (!keep.has(key)) { c.el.remove(); this.cards.delete(key); }
  }

  // ---- the legendary floor signs ------------------------------------------------------------------------------------
  placeLegends(nowMs) {
    const phone = this.w <= 600;
    for (const [key, lg] of this.legends) {
      const fade = lg.gone == null ? 1 : 1 - (nowMs - lg.gone) / LEG_FADE_MS;
      if (fade <= 0) { lg.sign.remove(); lg.pin.remove(); this.legends.delete(key); continue; }
      const at = this.toScreen(lg.x, 0.05, lg.z);
      if (!lg.w) { lg.w = lg.sign.offsetWidth; lg.h = lg.sign.offsetHeight; }
      lg.sign.classList.toggle('phone', phone);
      const x = Math.max(6, Math.min(this.w - lg.w - 6, at.x - lg.w / 2)), y = Math.max(6, at.y - 22 - lg.h);
      lg.sign.style.transform = 'translate(' + x.toFixed(1) + 'px,' + y.toFixed(1) + 'px)'; lg.sign.style.opacity = fade.toFixed(3);
      lg.pin.style.transform = 'translate(' + at.x.toFixed(1) + 'px,' + at.y.toFixed(1) + 'px)'; lg.pin.style.opacity = fade.toFixed(3);
    }
  }

  toScreen(x, y, z) {
    const v = new THREE.Vector3(x, y, z).project(this.stage.camera);
    return { x: (v.x + 1) / 2 * this.w, y: (1 - v.y) / 2 * this.h };
  }

  /** Each frame. lead: the KO leader's id (alive) or null; delayMs: the snapshot buffer's delay (lives catch up to it). */
  frame({ pos, lead, nowMs, delayMs = 150 }) {
    const list = [];
    for (const [id, p] of pos) if (p.state === 'alive') { const s = this.toScreen(p.x, 0, p.z), a = this.actors.get(id); list.push({ id, x: s.x, y: s.y, hp: Math.max(0, Math.min(1, p.f.hp / (a ? a.hpMax : 100))) }); }
    this.list = list;   // the fighters on screen this frame (read by the review tooling)
    for (const met of this.lives.advance(nowMs - delayMs)) this.feed.push({ kind: 'res', who: met.id, level: met.level, points: met.points });
    this.corner.setSound(this.soundState);
    this.layoutHud(nowMs);
    this.placeBars(list);
    this.placeTags(pos, lead, nowMs);
    this.placeLegends(nowMs);
    this.prejump.frame(nowMs, (id) => { const p = pos.get(id); return p ? this.toScreen(p.x, 0.6, p.z) : null; },
      (id) => { const p = pos.get(id); return p ? this.toScreen(p.x, 1.6, p.z) : null; });
    this.placeStatus();
    // the picture pans so the ring stays in the free part beside an open panel, eased over ~150 ms
    if (this.stage.setPan) { const t = this.panTarget || 0, k = Math.min(1, (nowMs - (this.panAt || nowMs)) / 150); this.panAt = nowMs; this.stage.setPan((this.stage.view.panPx || 0) + (t - (this.stage.view.panPx || 0)) * (k || 1)); }
  }
  // the page's status pill (a replay, or "No arena at … retrying") stands clear of the feed and the corner buttons
  placeStatus() {
    const el = this.statusEl;
    if (!el || el.classList.contains('live')) return;
    const w = el.offsetWidth || 150, h = el.offsetHeight || 28, r = this.rects;
    const corner = r.btn0 && r.btn1 ? { x: Math.min(r.btn0.x, r.btn1.x), y: Math.min(r.btn0.y, r.btn1.y), w: Math.max(r.btn0.x + r.btn0.w, r.btn1.x + r.btn1.w) - Math.min(r.btn0.x, r.btn1.x), h: Math.max(r.btn0.h, r.btn1.h) } : null;
    let box = placeReplayStatus({ x: (this.w - w) / 2, y: this.h - h - 10, w, h }, corner, this.w, this.h);
    box = placeReplayStatus(box, r.feed, this.w, this.h);
    el.style.left = box.x + 'px'; el.style.top = box.y + 'px'; el.style.bottom = 'auto'; el.style.transform = 'none';
  }
}
