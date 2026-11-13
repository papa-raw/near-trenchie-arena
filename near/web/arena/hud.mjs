// The arena HUD, approved board 2 (direction C, "Wall sign", sheet r5-sheet2): the wall sign with its two boards, the
// one merged feed of paper slips, the corner buttons and "How it works", every trenchie's name tag with its prediction
// circles, the legendary floor sign and the pre-jump card. The HP candles under each body are still the
// approved panel art's (hud-art/hud-art.js, frozen), cloned per body. Everything that follows a body is placed every frame
// from the projected feet, so it never lags a moving trenchie; the rest is DOM that changes only when its data does.
import * as THREE from 'three';
import { placeQuirkPanel } from './hover.mjs';
import { isDev, shortName } from './names.mjs';
import { placeBanner, placeReplayStatus } from './layout.mjs';
import { HudPanelCache } from './hud-cache.mjs';
import { rosterLabels } from './roster.mjs';
import { quirkText } from './quirks.mjs';
import { styleWord } from './style.mjs';
import { circlesModel, circlesNode, circlesKey } from './pips.mjs';
import { Feed, nameColour } from './feed.mjs';
import { Corner } from './corner.mjs';
import { Prejump, DROP_DELAY_MS } from './prejump.mjs';
import { Lives } from './lives.mjs';
import { itemStill, houseFace, playerFace } from './stills.mjs';
import { hudLayout, panelBoxes, cornerHidden } from './hud-layout.mjs';
import { placeLegendSigns, bodyBox } from './legend-place.mjs';

const LEG_FADE_MS = 300;
const LEG_OPEN_MS = 3000;   // the complete floor announcement shows this long, then fades and leaves the DOM
const LEG_SCALE = 0.7;   // The whole floor sign (box, picture and lettering) is 30% smaller
const BANNER_SCALE = 0.8;   // Shrink the complete existing KOs/predictions stack by another 20%
const scaleBannerRects = (rects) => rects.map((r) => ({ ...r, x: r.x * BANNER_SCALE, y: r.y * BANNER_SCALE, w: r.w * BANNER_SCALE, h: r.h * BANNER_SCALE }));
const REMOUNT_MS = 600;   // the top-left KO banner (as at ebb97a0): redrawn when its content changes, at most this often
const BANNER_MS = 4200;   // the lead banner shows this long after the leader changes

export class Hud {
  constructor({ stage, actors, KITS, ITEMS, root, status = null, itemRenderer = null, LOOK3 = null }) {
    this.statusEl = status; this.itemRenderer = itemRenderer; this.LOOK3 = LOOK3;
    this.stage = stage; this.actors = actors; this.KITS = KITS; this.ITEMS = ITEMS; this.root = root;
    this.w = innerWidth; this.h = innerHeight; this.followed = null; this.names = {}; this.boards = null;
    root.style.position = 'fixed'; root.style.pointerEvents = 'none';
    if (!document.querySelector('link[data-b2]')) { const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = new URL('./board2.css', import.meta.url).href; l.dataset.b2 = '1'; document.head.appendChild(l); }
    // name tags (Q18) with their circles, and the crowd cards
    this.tagLayer = document.createElement('div'); this.tagLayer.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:1;'; root.appendChild(this.tagLayer);
    this.tags = new Map(); this.styles = new Map(); this.bounties = new Set(); this.tagRects = []; this.cardRects = [];
    // HP candles: drawn once per level by the panel art, then cloned per body every frame
    this.barLayer = document.createElement('div'); this.barLayer.className = 'ha-layer ha-candle'; this.barLayer.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none;z-index:2;'; root.insertBefore(this.barLayer, this.tagLayer);
    this.barHtml = null; this.barSize = null; this.bars = new Map(); this.building = false; this.barNarrow = null;
    // the legendary floor signs, one per legendary on the floor
    this.legLayer = document.createElement('div'); this.legLayer.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:2;'; root.appendChild(this.legLayer);
    this.legends = new Map();
    // the HUD proper: sign, feed, buttons, pre-jump cards
    this.ui = document.createElement('div'); this.ui.className = 'b2'; root.appendChild(this.ui);
    this.lives = new Lives();
    // the top-left KO banner, as at ebb97a0: the panel art's hanging tags (House, and Players when any), their labels, the lead banner
    this.layerHost = document.createElement('div'); this.layerHost.style.cssText = 'position:absolute;left:0;top:0;z-index:3;'; root.appendChild(this.layerHost);
    this.cardLayer = document.createElement('div'); this.cardLayer.className = 'ha-layer ha-candle'; this.cardLayer.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none;z-index:3;transform-origin:0 0;transform:scale(' + BANNER_SCALE + ');'; root.appendChild(this.cardLayer);
    this.artCache = null; this.artRects = {}; this.cardList = []; this.cardRects = []; this.mounting = false; this.lastMount = 0; this.sig = ''; this.bannerLead = null; this.leadAt = 0; this.board = null; this.roster = null;
    this.feed = new Feed(document, this.ui, { name: (id) => this.nameOf(id), colour: (id) => this.colourOf(id), dev: isDev });
    this.feed.list.classList.add('arena-say-feed');
    this.onMute = null; this.soundState = 'waiting for a click';
    this.corner = new Corner(document, this.ui, { onSound: () => this.onMute && this.onMute() });
    this.prejump = new Prejump(document, this.ui);
    this.rects = {}; this.layoutAt = 0;
    this.idle(performance.now());   // the sign, the feed and the buttons are in place with their words before any arena answers
  }
  /** No snapshot to draw (no arena yet, or between reconnects): keep the fixed HUD laid out and worded. */
  idle(nowMs) { this.corner.setSound(this.soundState); this.layoutHud(nowMs); this.placeLegends(null, nowMs); this.placeStatus(); }

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
  setBoards(json) { this.boards = json; }

  // ---- events --------------------------------------------------------------------------------------------------------
  // a KO, with whether it was an ambush (moments.mjs)
  onKo(ev, ambush) { this.feed.push({ kind: 'ko', who: ev.source || null, victim: ev.fighter, ambush: !!ambush }); }
  // a moment worked out by moments.mjs (a legendary on the sand, a legendary grabbed by a stranger, a near-death escape)
  onMoment(m) {
    if (m.kind === 'legendary_drop') { if (!(m.fighter && this.feed.upgradeKo(m.fighter, m.item))) { if (m.fighter) this.feed.push({ kind: 'leg', who: null, victim: m.fighter, item: m.item, moment: m.kind }); } }
    else if (m.kind === 'legendary_steal') this.feed.push({ kind: 'leg', steal: true, who: m.fighter, from: m.other, item: m.item, moment: m.kind });
    else if (m.kind === 'near_death') this.feed.push({ kind: 'escape', who: m.fighter, hp: Number(/(\d+) HP/.exec(m.text || '')?.[1] || 0), moment: m.kind });
  }
  // A life starts: its prediction line and stationary fading card. Returns the fade duration (ms).
  onRespawn(ev, nowMs) {
    const v = this.lives.get(ev.fighter), level = v && v.life === ev.life_id ? v.level : null;
    if (!Number.isInteger(level)) return 0;
    this.feed.push({ kind: 'pred', who: ev.fighter, level });
    return this.prejump.start(ev.fighter, this.tagOf(ev.fighter), level, nowMs) ? DROP_DELAY_MS : 0;
  }
  // a legendary on the floor: its sign, anchored to the item
  onLegendDrop(d, nowMs = performance.now()) {
    const it = this.ITEMS[d.item]; if (!it || it.tier !== 'legendary' || this.legends.has(d.key)) return;
    const sign = document.createElement('div'); sign.className = 'legsign'; sign.dataset.drop = d.key;
    const pic = this.itemRenderer ? itemStill(this.itemRenderer, this.LOOK3, d.item) : null;
    if (pic) { const img = document.createElement('img'); img.className = 'legend-glow'; img.src = pic; img.alt = ''; sign.appendChild(img); } else { const s = document.createElement('span'); s.className = 'noimg legend-glow'; sign.appendChild(s); }
    const t = document.createElement('span'), name = document.createElement('span');
    name.className = 'legname'; name.textContent = String(it.name).toUpperCase();
    t.className = 'legtext'; t.appendChild(name); sign.appendChild(t);
    sign.title = String(it.name).toUpperCase(); sign.setAttribute('aria-label', sign.title);   // the shorter forms keep their words here
    const pin = document.createElement('i'); pin.className = 'legpin';
    this.legLayer.append(sign, pin);
    const lg = { sign, pin, x: d.x / 1000, z: d.y / 1000, gone: null, w: 0, h: 0 };
    this.wireLegend(lg, nowMs); this.legends.set(d.key, lg);
  }
  // During the announcement, tap or hover opens a collision-shortened picture; neither extends its deadline.
  wireLegend(lg, nowMs = performance.now()) {
    lg.showUntil = nowMs + LEG_OPEN_MS; lg.openUntil = 0; lg.hover = false;
    lg.sign.addEventListener('click', (e) => { if (lg.form !== 'picture') return; e.stopPropagation(); lg.openUntil = lg.sign.classList.contains('open') ? 0 : lg.showUntil; });   // a tap on the open sign closes it
    lg.sign.addEventListener('pointerenter', (e) => { if (e.pointerType === 'mouse') lg.hover = true; });
    lg.sign.addEventListener('pointerleave', () => { if (lg.hover) { lg.hover = false; lg.openUntil = performance.now(); } });
  }
  // each drawn snapshot's drops: a new legendary gets its sign; one that left the floor (grabbed or expired) fades
  syncDrops(drops, nowMs) {
    const here = new Set();
    for (const d of drops) { here.add(d.key); this.onLegendDrop(d, nowMs); }
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
    const full = this.corner.full = this.corner.compact ? (this.corner.full || { w: 260, h: 44 }) : { w: corner.w || 260, h: corner.h || 44 };   // the worded size, measured while worded
    const L = hudLayout(view, panelBoxes(document), full);
    this.corner.setCompact(L.compact); this.corner.place(L); this.corner.box.classList.toggle('phone', L.phone);
    this.panTarget = L.pan;
    // a phone with the panel open: the compact buttons sit above the sheet, under the plank; never on it
    const hidden = cornerHidden(L, view, this.bannerBox()); this.corner.box.hidden = hidden;
    this.feed.setNarrow(L.phone);
    this.feed.box.classList.toggle('phone', L.phone); this.feed.box.classList.toggle('n3', L.phone); this.feed.box.classList.toggle('n5', !L.phone);
    this.feed.box.classList.toggle('hidden', L.feedHidden);
    // the feed sits above the buttons on a phone (they share the bottom edge)
    this.feed.box.style.bottom = (L.phone ? L.bottom + (corner.h || 44) + 8 : 16) + 'px';
    const rect = (el) => { const r = el.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; };
    const cta = document.getElementById('snapin-cta'), ctaRect = cta ? rect(cta) : null;   // the guide and its snap-in button (when shown)
    this.rects = { board: this.bannerBox(), feed: L.feedHidden ? null : rect(this.feed.box), btn0: hidden ? null : rect(this.corner.sound), btn1: hidden ? null : rect(this.corner.menu), cta: ctaRect && ctaRect.w > 0 ? ctaRect : null };
    this.cardRects = (this.bannerRects || []).slice();   // the quirk panel keeps off the banner's cards (hover.mjs)
  }

  // ---- individual name tags and circles -----------------------------------------------------------------------------
  // (the tag fixtures in the quirk and agent-review cases build a bare Hud: lives and rects are optional here)
  placeTags(pos, lead, nowMs = 0) {
    const narrow = this.w < 600, seen = new Set(), items = [], lives = this.lives, rects = this.rects || {};
    const focusTargets = new Set([...pos].filter(([id, q]) => isDev(id) && q.f.status === 0 && q.f.target).map(([, q]) => q.f.target));
    const mine = this.followed != null ? pos.get(this.followed) : null, myTarget = mine && mine.f.status === 0 ? mine.f.target : null;
    if (myTarget) focusTargets.add(myTarget);
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
      seen.add(id); items.push({ id, el, q, m, x: sp.x, y: sp.y, landing: !!this.prejump && this.prejump.active(id, nowMs) });
    }
    for (const [id, el] of this.tags) if (!seen.has(id)) { el.remove(); this.tags.delete(id); }
    // Every fighter keeps its own tag directly above its head; overlap never hides or merges tags.
    const placed = [];
    for (const it of items) {
      const cls = 'atag' + (it.id === lead ? ' lead' : '') + (it.id === this.followed ? ' followed' : '') + (it.q.state === 'bench' ? ' bench' : '') + (narrow ? ' narrow' : '') + (this.bounties.has(it.id) ? ' bounty' : '') + (focusTargets.has(it.id) ? ' focus-target' : '') + (it.landing ? ' tag-hidden' : '');
      if (it.el.className !== cls) it.el.className = cls;
      if (it.landing) continue;
      const w = it.el.offsetWidth || 50, h = it.el.offsetHeight || 16;
      const r = { id: it.id, x: it.x - w / 2, y: it.y - h - 2, w, h };
      placed.push(r);
      it.el.style.transform = 'translate(' + r.x.toFixed(1) + 'px,' + r.y.toFixed(1) + 'px)';
    }
    this.tagRects = placed;
    for (const it of items) {
      const panel = it.el.querySelector('.quirk-line');
      if (!panel?.textContent || !it.el.matches?.(':hover, :focus-within')) continue;
      const anchor = placed.find((rect) => rect.id === it.id); if (!anchor) continue;
      const box = placeQuirkPanel(anchor, { w: panel.offsetWidth || 230, h: panel.offsetHeight || 60 }, placed, this.w, this.h, this.cardRects || []);
      panel.style.left = (box.x - anchor.x) + 'px'; panel.style.top = (box.y - anchor.y) + 'px';
    }
  }
  // ---- the legendary floor signs ------------------------------------------------------------------------------------
  // Each sign keeps its pin on the item and takes the first clear spot around it (legend-place.mjs): clear of the bodies,
  // the individual tags, the fixed HUD and the other signs; with no clear spot, its short form (the picture alone).
  placeLegends(pos, nowMs) {
    const phone = this.w <= 600, live = [];
    for (const [key, lg] of this.legends) {
      const fade = lg.gone == null ? 1 : 1 - (nowMs - lg.gone) / LEG_FADE_MS;
      if (fade <= 0) { lg.sign.remove(); lg.pin.remove(); this.legends.delete(key); continue; }
      if (nowMs >= lg.showUntil + LEG_FADE_MS) {
        // Keep only the record until the floor item departs: repeated snapshots must not create a new announcement.
        lg.sign.remove(); lg.pin.remove(); continue;
      }
      if (lg.phone !== phone) { lg.phone = phone; lg.sign.classList.toggle('phone', phone); lg.w = 0; }
      if (!lg.w) {   // measure each form once: the full sign, the picture and the name, the picture alone (a square)
        const c = lg.sign.classList; c.remove('short', 'nameonly', 'open');
        lg.w = lg.sign.offsetWidth * LEG_SCALE; lg.h = lg.sign.offsetHeight * LEG_SCALE;
        c.add('nameonly'); lg.nw = lg.sign.offsetWidth * LEG_SCALE; lg.nh = lg.sign.offsetHeight * LEG_SCALE; c.remove('nameonly');
        c.add('short'); lg.cw = lg.sign.offsetWidth * LEG_SCALE; lg.ch = lg.sign.offsetHeight * LEG_SCALE; c.remove('short'); lg.form = null;
      }
      const at = this.toScreen(lg.x, 0.05, lg.z);
      // The item can outlast its announcement; every part of the announcement shares this fixed deadline.
      const labelFade = Math.max(0, Math.min(1, (lg.showUntil + LEG_FADE_MS - nowMs) / LEG_FADE_MS));
      live.push({ key, lg, fade, labelFade, at, ax: at.x, ay: at.y, w: lg.w, h: lg.h, nw: lg.nw, nh: lg.nh, cw: lg.cw, ch: lg.ch });
    }
    if (!live.length) { this.legendRects = []; return; }
    const bodies = [...(pos || new Map())].filter(([, q]) => q.state === 'alive' && q.f.status !== 2)
      .map(([, q]) => bodyBox(this.toScreen(q.x, 0, q.z), this.toScreen(q.x, 1.5 + (q.lift || 0), q.z)));
    const r = this.rects || {}, fixed = [r.board, r.feed, r.btn0, r.btn1, r.cta].filter(Boolean);
    const spots = placeLegendSigns(live, [...bodies, ...(this.tagRects || []), ...fixed], { w: this.w, h: this.h }, fixed);
    for (const s of live) {
      const p = spots.get(s.key), lg = s.lg;
      lg.pin.style.transform = 'translate(' + s.at.x.toFixed(1) + 'px,' + s.at.y.toFixed(1) + 'px)'; lg.pin.style.opacity = (s.fade * s.labelFade).toFixed(3);
      lg.sign.style.visibility = p.hidden ? 'hidden' : '';   // off screen, or no room even for the picture: the pin alone
      if (p.hidden) { lg.sign.dataset.pos = 'hidden: ' + p.hidden; continue; }
      if (lg.form !== p.form) { lg.form = p.form; lg.sign.classList.toggle('nameonly', p.form === 'name'); lg.sign.classList.toggle('short', p.form === 'picture'); lg.sign.dataset.form = p.form; }
      // the picture, opened (tap or hover): the full sign over the picture's spot, kept on screen, above the rest
      const open = p.form === 'picture' && (lg.hover || (lg.openUntil > 0 && nowMs < lg.openUntil + LEG_FADE_MS));
      if (lg.sign.classList.contains('open') !== open) lg.sign.classList.toggle('open', open);
      const x = open ? Math.max(6, Math.min(this.w - 6 - lg.w, p.x)) : p.x;
      lg.sign.dataset.pos = p.pos;
      lg.sign.style.transform = 'translate(' + x.toFixed(1) + 'px,' + p.y.toFixed(1) + 'px) scale(' + LEG_SCALE + ')';
      lg.sign.style.opacity = (s.fade * s.labelFade).toFixed(3);
    }
    this.legendRects = live.map((s) => spots.get(s.key)).filter((p) => !p.hidden);   // read by the review tooling
  }

  toScreen(x, y, z) {
    const v = new THREE.Vector3(x, y, z).project(this.stage.camera);
    const vw = this.stage.view.w || this.w, vh = this.stage.view.h || this.h;   // the canvas's size (a phone with board 1's panel open draws only above it)
    return { x: (v.x + 1) / 2 * vw, y: (1 - v.y) / 2 * vh };
  }

  /** Each frame. lead: the KO leader's id (alive) or null; delayMs: the snapshot buffer's delay (lives catch up to it). */
  frame({ pos, lead, nowMs, delayMs = 150 }) {
    const list = [];
    for (const [id, p] of pos) if (p.state === 'alive') { const s = this.toScreen(p.x, 0, p.z), a = this.actors.get(id); list.push({ id, x: s.x, y: s.y, hp: Math.max(0, Math.min(1, p.f.hp / (a ? a.hpMax : 100))) }); }
    this.list = list;   // the fighters on screen this frame (read by the review tooling)
    this.frameBanner(pos, list, nowMs);
    for (const met of this.lives.advance(nowMs - delayMs)) this.feed.push({ kind: 'res', who: met.id, level: met.level, points: met.points });
    this.corner.setSound(this.soundState);
    this.layoutHud(nowMs);
    this.placeBars(list);
    this.placeTags(pos, lead, nowMs);
    this.placeLegends(pos, nowMs);
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

  /** Correct predictions today, house and players together, from the live record (/house/leaderboards.json): the
   *  banner's predictions string. [{id, n}] best first; empty while nobody has one today. */
  correctToday() {
    const b = this.boards && this.boards.boards && this.boards.boards.most_correct_day;
    if (!b) return [];
    return [...(b.players || []), ...(b.house || [])].filter((r) => r.correct > 0).sort((x, y) => y.correct - x.correct || (x.persona < y.persona ? -1 : 1)).map((r) => ({ id: r.persona, n: r.correct }));
  }

  // ---- the top-left KO banner, as at ebb97a0 (hud-art's candle board: hanging tags, faces, ▲ KOs per hour played, ATH;
  // a Players string under the House one when players are in; their labels; the lead banner) ---------------------------
  bannerBox() {
    const r = this.bannerRects; if (!r || !r.length) return null;
    const x = Math.min(...r.map((q) => q.x)), y = Math.min(...r.map((q) => q.y)), right = Math.max(...r.map((q) => q.x + q.w)), bottom = Math.max(...r.map((q) => q.y + q.h));
    return { x, y, w: right - x, h: bottom - y };
  }
  frameBanner(pos, list, nowMs) {
    const rows = this.board ? this.board.rows(nowMs) : [], top1 = rows[0];
    const lead = top1 && top1.kos > 0 && pos.get(top1.id) && pos.get(top1.id).state === 'alive' ? top1.id : null;   // the board's leader: KOs per hour played
    if (lead !== this.bannerLead) { this.bannerLead = lead; this.leadAt = nowMs; }
    this.allIds = [...pos.keys()].filter((id) => pos.get(id).f.status !== 2);
    const rl = this.roster ? rosterLabels(this.roster, this.w < 600) : null;
    const top = rows.slice(0, 5).map((r) => r.id + ':' + Math.round(r.perHour)).join(','), preds = this.correctToday().slice(0, 5).map((r) => r.id + ':' + r.n).join(',');
    const sig = [lead, top, preds, list.length, this.w, this.h, rl ? rl.house + rl.players : ''].join('|');
    if (!this.mounting && sig !== this.sig && nowMs - this.lastMount > REMOUNT_MS && window.HUDART) { this.sig = sig; this.remount(list, lead, nowMs); }
    const banner = this.layerHost.querySelector('[data-panel="banner"]');
    if (banner) banner.style.display = lead && nowMs - this.leadAt < BANNER_MS && this.leadAt > 0 && nowMs > 8000 ? '' : 'none';
    this.applyBanner();
  }
  remount(list, lead, nowMs) {
    this.mounting = true; this.lastMount = nowMs;
    if (!list.length) { this.mounting = false; return; }
    if (!this.artCache) this.artCache = new HudPanelCache(window.HUDART);
    const effLead = lead || list[0].id;   // with no KOs yet the panel art names the first body; we say so by naming it ourselves
    const rows = this.board ? this.board.rows(nowMs) : [], rateOf = new Map(rows.map((r) => [r.id, Math.round(r.perHour)]));
    const inGame = (this.allIds || list.map((f) => f.id)).filter((id, i, a) => a.indexOf(id) === i);
    const rl = this.roster ? rosterLabels(this.roster) : null;
    const isHouse = (id) => (rl && rl.houseIds.size ? rl.houseIds.has(id) : (this.KITS.roster || []).some((r) => r.trenchieId === id));
    const rank = new Map(rows.map((r, i) => [r.id, i])), byRank = (a, b) => (rank.has(a) ? rank.get(a) : 99) - (rank.has(b) ? rank.get(b) : 99);
    const houseIds = inGame.filter(isHouse).sort(byRank), mainIds = (houseIds.length ? houseIds : inGame).slice(0, this.w < 700 ? 3 : 5);
    this.playerIds = inGame.filter((id) => !isHouse(id));
    const fighters = mainIds.map((id) => { const f = list.find((q) => q.id === id) || { x: -999, y: -999, hp: 1 }; return { x: f.x, y: f.y, tag: this.tagOf(id), hp: f.hp, kos: rateOf.get(id) || 0, state: '', name: this.tagOf(id) }; });
    const o = { concept: 'candle', draft: 'a', w: this.w, h: this.h, fighters, topN: this.w < 700 ? 3 : 5, lead: { tag: this.tagOf(effLead), kos: rateOf.get(effLead) || 0 }, feed: [] };
    this.artCache.mount(this.layerHost, o, { only: ['board', 'banner'] }).then((meas) => {
      const layer = this.layerHost.querySelector(':scope > .ha-layer'); if (!layer) { this.mounting = false; return; }
      layer.style.pointerEvents = 'none';
      this.artRects = {}; for (const r of meas.rects) this.artRects[r.id] = r;
      if (this.artRects.board) { this.bannerRects = this.estimateCards(this.artRects.board, this.playerIds.length > 0, this.correctToday().length > 0); this.applyBanner(); }
      return this.buildCards(this.playerIds, rateOf, o.topN, this.artRects.board).then(() => { this.mounting = false; this.layoutAt = 0; });
    }).catch((e) => { this.mounting = false; console.error('HUD mount failed', e); });
  }
  // the lead banner clears every card (layout.mjs); called each frame and right after a redraw
  applyBanner() {
    const banner = this.layerHost.querySelector('[data-panel="banner"]'), N = this.artRects.banner; if (!banner || !N) return;
    const p = placeBanner(N, this.bannerRects || [], this.w); if (p) banner.style.transform = 'translate(' + p.x + 'px,' + p.y + 'px)';
  }
  // The internal layout keeps Nov 12's 80% ropes and wooden labels; BANNER_SCALE shrinks the complete stack together.
  // ("KOs", "Predictions") in place of the old text labels. Screen layout, top down: the KOs label, the house rope, the
  // players' rope when any, then the Predictions label and its rope.
  bannerLayout(B) { const narrow = this.w < 600; return { S: 0.8, LH: narrow ? 14 : 17, gap: narrow ? 4 : 6, kc: narrow ? 0.72 : 1 }; }
  // before the other ropes exist, what the banner will cover (for the lead banner's place)
  estimateCards(B, withPlayers, withPredictions = false) {
    const { S, LH, gap } = this.bannerLayout(B), x = B.x * S, rects = [{ x, y: B.y * S, w: 60, h: LH }, { x, y: B.y * S + LH, w: B.w * S, h: B.h * S }];
    let y = B.y * S + LH + B.h * S + gap;
    if (withPlayers) { rects.push({ x, y, w: Math.max(90, B.w * 0.5) * S, h: B.h * S }); y += B.h * S + gap; }
    if (withPredictions) rects.push({ x, y, w: 110, h: LH }, { x, y: y + LH, w: B.w * S, h: B.h * S });
    return scaleBannerRects(rects);
  }
  ropeLabel(text, x, y) {
    const el = document.createElement('div'); el.className = 'ropelabel' + (this.w < 600 ? ' narrow' : ''); el.textContent = text;
    el.style.transform = 'translate(' + x.toFixed(1) + 'px,' + y.toFixed(1) + 'px)'; this.cardLayer.appendChild(el); return el;
  }
  // the house rope is the main mount's own board (scaled in place); players, if any, get a second rope under it; correct
  // predictions today, when any, one more rope under its own label
  async buildCards(playerIds, rateOf, topN, B) {
    if (!B) return;
    const { S, LH, gap, kc } = this.bannerLayout(B);
    const made = [];
    if (playerIds.length) {
      const host = this.playerHost || (this.playerHost = document.createElement('div')); host.style.cssText = 'position:fixed;left:-6000px;top:0;width:' + this.w + 'px;height:' + this.h + 'px;pointer-events:none;'; document.body.appendChild(host);
      const fighters = playerIds.map((id) => ({ x: -999, y: -999, tag: this.tagOf(id), hp: 1, kos: rateOf.get(id) || 0, name: this.tagOf(id) })), lead = fighters.slice().sort((a, b) => b.kos - a.kos)[0];
      const meas = await this.artCache.mount(host, { concept: 'candle', draft: 'a', w: this.w, h: this.h, fighters, topN, lead: { tag: lead.tag, kos: lead.kos }, feed: [] }, { only: ['board'] });
      const node = this.artCache.panel(host, 'board'), r = meas.rects.find((q) => q.id === 'board'); host.remove();
      if (node && r) made.push({ node, w: r.w, h: r.h, label: null });
    }
    // correct predictions today: one more rope in the same style (✓ in place of ▲), house and players together, from the
    // live record; hidden while nobody has one
    const preds = this.correctToday().slice(0, topN);
    if (preds.length) {
      const host = this.predHost || (this.predHost = document.createElement('div')); host.style.cssText = 'position:fixed;left:-6000px;top:0;width:' + this.w + 'px;height:' + this.h + 'px;pointer-events:none;'; document.body.appendChild(host);
      const fighters = preds.map((p) => ({ x: -999, y: -999, tag: this.tagOf(p.id), hp: 1, kos: p.n, name: this.tagOf(p.id) }));
      const meas = await this.artCache.mount(host, { concept: 'candle', draft: 'a', w: this.w, h: this.h, fighters, topN, mark: '✓', lead: { tag: fighters[0].tag, kos: fighters[0].kos }, feed: [] }, { only: ['board'] });
      const node = this.artCache.panel(host, 'board'), r = meas.rects.find((q) => q.id === 'board'); host.remove();
      if (node && r) made.push({ node, w: r.w, h: r.h, label: 'Predictions' });
    }
    for (const c of this.cardList) { if (c.label) c.label.remove(); if (c.node) c.node.remove(); } this.cardList = [];
    // the house rope lives outside cardLayer: apply the same whole-stack scale to it and its label offset
    const house = this.layerHost.querySelector('[data-panel="board"]'), x = B.x * S, rects = [];
    if (house) { house.style.transformOrigin = '0 0'; house.style.scale = String(S * BANNER_SCALE); house.style.translate = '0 ' + (LH * BANNER_SCALE) + 'px'; }
    const top = B.y * S, ko = this.ropeLabel('KOs', x + 10, top);
    this.cardList.push({ node: null, label: ko }); rects.push({ x: x + 10, y: top, w: ko.offsetWidth || 40, h: ko.offsetHeight || LH }, { x, y: top + LH, w: B.w * S, h: B.h * S });
    let y = top + LH + B.h * S + gap;
    for (const m of made) {
      let label = null;
      if (m.label) { label = this.ropeLabel(m.label, x + 10, y); rects.push({ x: x + 10, y, w: label.offsetWidth || 90, h: label.offsetHeight || LH }); y += LH; }
      m.node.style.position = 'absolute'; m.node.style.left = '0'; m.node.style.top = '0'; m.node.style.transformOrigin = '0 0';
      m.node.style.transform = 'translate(' + x.toFixed(1) + 'px,' + y.toFixed(1) + 'px) scale(' + (kc * S).toFixed(3) + ')'; this.cardLayer.appendChild(m.node);
      // The art's measured w/h already include its phone scale kc; apply only the remaining rope scale here.
      rects.push({ x, y, w: m.w * S, h: m.h * S }); y += m.h * S + gap;
      this.cardList.push({ node: m.node, label });
    }
    this.bannerRects = scaleBannerRects(rects); this.applyBanner();
  }

}
