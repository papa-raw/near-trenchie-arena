// Effects and the things on the floor: telegraphs in the one reserved danger hue, projectiles, loot with its tier glow, hit
// sparks, the KO ring, swing arcs. Telegraphs are drawn at the true hit area. At most 150 live effect shapes (feel row 14);
// when the cap bites, ambient bursts go first and telegraphs, the KO ring and bounty markers are never dropped.
import * as THREE from 'three';
import { milliToWorld } from './frame.mjs';
import { TICK_MS } from './buffer.mjs';
import { makeTelegraph, updateTelegraph, disposeTelegraph, telegraphHitArea, TELE_STYLES, TELE_DEFAULT } from './telegraph.mjs';
// The telegraph look: c (red candles, Pat's pick) by default; ?tele=a|b for the other drafts, ?tele=old for the earlier
// flat danger shape. An unknown value keeps the default.
export const teleLook = (search) => { try { const v = new URLSearchParams(search).get('tele'); return v === 'old' || (v !== null && Object.hasOwn(TELE_STYLES, v)) ? v : TELE_DEFAULT; } catch { return TELE_DEFAULT; } };
const TELE_LOOK = teleLook(globalThis.location?.search ?? '');
// The hit area a telegraph actually draws, for either look: shape (circle|ring|cone|line), radius in tiles, cone arc in radians
export function hitArea(m) {
  if (m.userData.shader) return telegraphHitArea(m);
  const g = m.geometry, P = g.parameters;
  const shape = g.type === 'RingGeometry' ? 'ring' : g.type === 'PlaneGeometry' ? 'line' : P.thetaLength < 2 * Math.PI - 1e-9 ? 'cone' : 'circle';
  return { shape, r: shape === 'line' ? P.width : (P.outerRadius ?? P.radius), arc: shape === 'cone' ? P.thetaLength : null, style: 'old' };
}
const dropTele = (m) => { if (m.userData.shader) disposeTelegraph(m); else { m.geometry.dispose(); m.material.dispose(); } };

export const DANGER = '#E84855';             // the one reserved danger hue: outside p01-p16, for telegraphs and live hazards only
export const EFFECT_CAP = 150;
export const TELE_POOL = 8;                  // spare telegraphs kept per shape and size
// signature shapes, from the rules table (ranges in tiles)
const SIG_SHAPE = {
  beam_sweep: { shape: 'cone', r: 4.5, arc: 60 }, blink_strike: { shape: 'circle', r: 1.2, at: 'target' }, shockwave: { shape: 'ring', r: 3 },
  magnet: { shape: 'circle', r: 4 }, bubble: { shape: 'ring', r: 1 }, chain_storm: { shape: 'ring', r: 4 }, dodge_roll: null,
};
const WEAPON_RANGE = { swing: 1.3, lunge: 2.5, zap: 3.5 };

const dangerMat = (o = 0.4) => new THREE.MeshBasicMaterial({ color: DANGER, transparent: true, opacity: o, depthWrite: false, side: THREE.DoubleSide });
const lerp = (a, b, k) => a + (b - a) * k;

export class Effects {
  constructor(scene, LOOK3, ITEMS, itemRenderer, details = null, look = null) {
    this.details = details; this.warnedMetadata = false;
    this.scene = scene; this.LOOK3 = LOOK3; this.ITEMS = ITEMS; this.itemRenderer = itemRenderer;
    this.tele = new Map(); this.telePool = new Map(); this.proj = new Map(); this.floor = new Map(); this.bursts = []; this.marks = new Map();
    this.counts = { effects: 0, peak: 0, telePeak: 0 };
    this.teleLook = look || TELE_LOOK;
    this.seenFirst = new Map();               // telegraph key -> first tick seen (the fill runs from there to resolveAt)
    this.crown = null;
    this.shake = { trauma: 0 };
  }

  get liveShapes() { return this.tele.size + this.proj.size + this.bursts.length + this.marks.size * 2; }

  // ---- state-driven: telegraphs, projectiles and loot from the interpolated snapshot ----------------------------------
  sync(snapA, snapB, k, rt, nowMs, actorPos) {
    const b = snapB;
    // projectiles and telegraphs from `objects`
    const liveT = new Set(), liveP = new Set();
    const prev = new Map(snapA.objects.map((o) => [o.key, o]));
    for (const o of b.objects) {
      const a = prev.get(o.key) || o;
      if (o.kind === 'shot') {
        liveP.add(o.key); let m = this.proj.get(o.key);
        if (!m) { m = new THREE.Mesh(new THREE.SphereGeometry(0.17, 12, 8), new THREE.MeshToonMaterial({ color: '#3B2F25' })); m.castShadow = true; this.scene.add(m); this.proj.set(o.key, m); }
        const p = milliToWorld(lerp(a.x, o.x, k), lerp(a.y, o.y, k), 0.7); m.position.set(p.x, p.y, p.z);
      } else if (o.kind === 'lob') {
        liveP.add(o.key); let m = this.proj.get(o.key);
        if (!m) { m = new THREE.Mesh(new THREE.SphereGeometry(0.26, 12, 8), new THREE.MeshToonMaterial({ color: '#C9966A' })); m.castShadow = true; this.scene.add(m); this.proj.set(o.key, m); }
        const sx = a.x, sy = a.y; const first = this.seenFirst.get(o.key) ?? (this.seenFirst.set(o.key, rt), rt);
        const total = Math.max(1, o.resolveAt - first), q = Math.min(1, Math.max(0, (rt - first) / total));
        const p = milliToWorld(lerp(o.x, o.tx, q), lerp(o.y, o.ty, q), Math.sin(Math.PI * q) * 2.2 + 0.3); m.position.set(p.x, p.y, p.z);
        this.telegraph('t:' + o.key, liveT, { shape: 'circle', x: o.tx, y: o.ty, r: (o.radius || 1200) / 1000, from: first, to: o.resolveAt }, rt);
      } else if (o.kind === 'beam') {
        this.telegraph('t:' + o.key, liveT, { shape: 'line', x: o.x, y: o.y, angle: o.angle, r: o.range / 1000, width: Math.max(0.4, (o.width || 400) / 1000), from: this.first(o.key, rt), to: o.resolveAt }, rt);
      }
    }
    // signature casts
    for (const c of b.casts) {
      const bound = this.details?.geometry(c);
      const visual = SIG_SHAPE[c.sig];
      const sig = bound && visual ? { ...visual, r: c.sig === 'blink_strike' ? (bound.strikeRadiusMilli ?? visual.r * 1000) / 1000 : bound.radiusMilli / 1000, arc: bound.arcMillidegrees / 1000 } : visual;
      if (!bound && !this.warnedMetadata) { this.warnedMetadata = true; console.warn('Cast geometry metadata unavailable; using shared signature shapes'); }
      if (!sig) continue;
      const f = actorPos.get(c.who); if (!f) continue;
      const key = 'c:' + c.who + ':' + c.resolveAt;
      const s = sig.at === 'target' ? { x: c.x, y: c.y } : { x: f.f.x, y: f.f.y };
      const ang = Math.atan2(c.y - f.f.y, c.x - f.f.x) * 180 / Math.PI;
      this.telegraph(key, liveT, { shape: sig.shape, x: s.x, y: s.y, angle: ang, r: sig.r, arc: sig.arc, from: this.first(key, rt), to: c.resolveAt }, rt);
    }
    for (const [key, m] of this.tele) if (!liveT.has(key)) { this.scene.remove(m); this.releaseTele(m); this.tele.delete(key); this.seenFirst.delete(key); }
    this.counts.telePeak = Math.max(this.counts.telePeak, this.tele.size);
    for (const [key, m] of this.proj) if (!liveP.has(key)) { this.scene.remove(m); m.geometry.dispose(); m.material.dispose(); this.proj.delete(key); this.seenFirst.delete(key); }

    // loot on the floor, with its tier glow and an expiry that thins the ring
    const seen = new Set();
    for (const d of b.drops) {
      seen.add(d.key); let g = this.floor.get(d.key);
      if (!g) { g = this.makeLoot(d); this.floor.set(d.key, g); }
      const p = milliToWorld(d.x, d.y); g.position.set(p.x, 0, p.z);
      const left = Math.max(0, d.expires - rt), bob = Math.sin(nowMs / 400 + d.x) * 0.05;
      g.userData.floating.position.y = g.userData.restY + bob;
      g.visible = left >= 40 || Math.floor(nowMs / 120) % 2 === 0;
    }
    for (const [key, g] of this.floor) if (!seen.has(key)) { this.scene.remove(g); this.itemRenderer.dispose(g); this.floor.delete(key); }
  }

  first(key, rt) { if (!this.seenFirst.has(key)) this.seenFirst.set(key, rt); return this.seenFirst.get(key); }

  telegraph(key, live, t, rt) {
    live.add(key); let m = this.tele.get(key);
    const geometryKey = [t.shape, t.r, t.arc, t.width].join(':');
    if (m && m.userData.geometryKey !== geometryKey) { this.scene.remove(m); this.releaseTele(m); m = null; }
    if (!m) { m = this.telePool.get(geometryKey)?.pop() || this.teleMesh(t); if (!m.parent) this.scene.add(m); m.userData.geometryKey = geometryKey; m.userData.shape = { shape: t.shape, r: t.r, arc: t.arc, width: t.width }; this.tele.set(key, m); }
    const p = Math.min(1, Math.max(0, (rt - t.from) / Math.max(1, t.to - t.from)));
    if (m.userData.shader) { updateTelegraph(m, p, t.shape === 'line' || t.shape === 'cone' ? t.angle : 0, rt * TICK_MS / 1000); const w = milliToWorld(t.x, t.y, 0.03); m.position.set(w.x, w.y, w.z); return; }
    if (t.shape === 'line' || t.shape === 'cone') m.rotation.z = -(t.angle || 0) * Math.PI / 180;
    m.material.opacity = 0.2 + 0.5 * p * p + (p > 0.7 ? 0.12 * Math.sin(rt * 5) : 0); // slow start so a viewer sees it begin, pulse in the last stretch
    const w = milliToWorld(t.x, t.y, 0.03); m.position.set(w.x, w.y, w.z);
  }

  // An expired telegraph waits in a small pool by shape and size: a new one of the same shape takes it instead of building a
  // shader material and a candle mesh again (a busy ring starts several a second). Beyond TELE_POOL a shape's spares are freed.
  releaseTele(m) {
    const k = m.userData.geometryKey, list = this.telePool.get(k) || [];
    if (list.length < TELE_POOL) { list.push(m); this.telePool.set(k, list); } else dropTele(m);
  }

  teleMesh(t) {
    if (this.teleLook !== 'old') { const g = makeTelegraph(t, this.teleLook); g.userData.shader = true; this.scene.add(g); return g; }
    let geo;
    if (t.shape === 'line') { geo = new THREE.PlaneGeometry(t.r, t.width); geo.translate(t.r / 2, 0, 0); }
    else if (t.shape === 'cone') geo = new THREE.CircleGeometry(t.r, 28, -(t.arc * Math.PI / 360), t.arc * Math.PI / 180);
    else if (t.shape === 'ring') geo = new THREE.RingGeometry(Math.max(0.1, t.r - 0.3), t.r, 48);
    else geo = new THREE.CircleGeometry(t.r, 40);
    const m = new THREE.Mesh(geo, dangerMat()); m.rotation.x = -Math.PI / 2; m.renderOrder = 3;
    if (t.shape === 'line' || t.shape === 'cone') m.rotation.z = -(t.angle || 0) * Math.PI / 180; // sim angle: clockwise seen from above
    this.scene.add(m); return m;
  }

  makeLoot(d) {
    const g = this.itemRenderer.floor(d.item);
    this.scene.add(g); return g;
  }

  // ---- event-driven bursts ---------------------------------------------------------------------------------------------
  burst(kind, x, z, nowMs, opts = {}) {
    if (this.liveShapes >= EFFECT_CAP && kind !== 'ko') return; // the cap: ambient bursts yield, the KO ring never does
    let mesh;
    if (kind === 'spark') {
      mesh = new THREE.Mesh(new THREE.IcosahedronGeometry(0.16, 0), new THREE.MeshBasicMaterial({ color: opts.color || '#FFF8EA', transparent: true, opacity: 1, depthWrite: false }));
      mesh.position.set(x, 1.0, z); mesh.userData = { kind, t0: nowMs, life: 260 };
    } else if (kind === 'ko') {
      mesh = new THREE.Mesh(new THREE.RingGeometry(0.5, 0.75, 40), new THREE.MeshBasicMaterial({ color: '#FFF8EA', transparent: true, opacity: 0.95, depthWrite: false, side: THREE.DoubleSide }));
      mesh.rotation.x = -Math.PI / 2; mesh.position.set(x, 0.04, z); mesh.userData = { kind, t0: nowMs, life: 380 };
    } else if (kind === 'arc') { // a swing: a crescent in front of the attacker at its true reach
      const reach = opts.reach || 1.3, half = (opts.half || 60) * Math.PI / 180;
      mesh = new THREE.Mesh(new THREE.RingGeometry(reach * 0.55, reach, 24, 1, -half, 2 * half), new THREE.MeshBasicMaterial({ color: '#FFF8EA', transparent: true, opacity: 0.85, depthWrite: false, side: THREE.DoubleSide }));
      mesh.rotation.x = -Math.PI / 2; mesh.rotation.z = -(opts.angle || 0) * Math.PI / 180; mesh.position.set(x, 0.55, z); mesh.userData = { kind, t0: nowMs, life: 180 };
    } else if (kind === 'dust') {
      mesh = new THREE.Mesh(new THREE.SphereGeometry(0.2, 8, 6), new THREE.MeshBasicMaterial({ color: '#F7F0DC', transparent: true, opacity: 0.7, depthWrite: false }));
      mesh.position.set(x, 0.15, z); mesh.userData = { kind, t0: nowMs, life: 420, vx: opts.vx || 0, vz: opts.vz || 0 };
    }
    if (!mesh) return;
    mesh.renderOrder = 4; this.scene.add(mesh); this.bursts.push(mesh);
  }

  tick(nowMs) {
    for (let i = this.bursts.length - 1; i >= 0; i--) {
      const m = this.bursts[i], u = m.userData, k = (nowMs - u.t0) / u.life;
      if (k >= 1) { this.scene.remove(m); m.geometry.dispose(); m.material.dispose(); this.bursts.splice(i, 1); continue; }
      if (u.kind === 'spark') { m.scale.setScalar(1 + k * 1.4); m.position.y = 1.0 + k * 0.6; m.material.opacity = 1 - k; }
      else if (u.kind === 'ko') { const r = 0.5 + 1.7 * (1 - Math.pow(1 - k, 3)); m.scale.setScalar(r / 0.62); m.material.opacity = 0.95 * (1 - k); }
      else if (u.kind === 'arc') m.material.opacity = 0.85 * (1 - k);
      else if (u.kind === 'dust') { m.position.x += u.vx * 0.016; m.position.z += u.vz * 0.016; m.scale.setScalar(1 + k * 1.2); m.material.opacity = 0.7 * (1 - k); }
    }
    this.counts.effects = this.liveShapes; this.counts.peak = Math.max(this.counts.peak, this.counts.effects);
  }

  // bounty markers (F20): a slow gold ring under a trenchie that wears a legendary from someone else's kit
  setBounty(positions, nowMs) {
    this.bounty = this.bounty || [];
    while (this.bounty.length < positions.length) {
      const m = new THREE.Group(); m.position.y = 0.06;
      // Dark gold rim carries contrast on the sand; the inner gold keeps the holder cue. Both sit above telegraphs.
      for (const [inner, outer, color, name, lift] of [[.60, .82, '#73501C', 'bounty-rim', 0], [.65, .76, '#E9B23A', 'bounty-gold', .002]]) {
        const ring = new THREE.Mesh(new THREE.RingGeometry(inner, outer, 40), new THREE.MeshBasicMaterial({ color, depthWrite: false, side: THREE.DoubleSide }));
        ring.name = name; ring.rotation.x = -Math.PI / 2; ring.position.y = lift; ring.renderOrder = 5; m.add(ring);
      }
      this.scene.add(m); this.bounty.push(m);
    }
    this.bounty.forEach((m, i) => { const p = positions[i]; m.visible = !!p; if (p) { m.position.x = p.x; m.position.z = p.z; const k = 1 + 0.08 * Math.sin(nowMs / 260); m.scale.set(k, 1, k); } });
    this.marks.clear(); positions.forEach((p, i) => { if (p) this.marks.set(i, p); }); // counted against the 150 live shapes
  }

  // the gold crown over the hour's KO leader (Q9), render-only
  setCrown(pos, yTop, nowMs) {
    if (!pos) { if (this.crown) this.crown.visible = false; return; }
    if (!this.crown) {
      const g = new THREE.Group(), gold = new THREE.MeshToonMaterial({ color: '#F7CF6B' });
      g.add(new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.22, 0.1, 16, 1, true), gold));
      for (let i = 0; i < 5; i++) { const a = i / 5 * Math.PI * 2, c = new THREE.Mesh(new THREE.ConeGeometry(0.06, 0.16, 6), gold); c.position.set(Math.cos(a) * 0.2, 0.12, Math.sin(a) * 0.2); g.add(c); }
      g.traverse((o) => { if (o.isMesh) o.castShadow = false; }); this.scene.add(g); this.crown = g;
    }
    this.crown.visible = true; this.crown.position.set(pos.x, yTop + Math.sin(nowMs / 300) * 0.03, pos.z); this.crown.rotation.y = nowMs / 700;
  }
}
