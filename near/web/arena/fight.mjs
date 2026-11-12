// How fights move (board 3, A Heavy toon; final/SPEC.md): the impact stars and dust, the swing arc, the shot, lob and beam,
// the beam sweep, the shockwave, the KO's trailing stars and poof, and the dropped item's flight. Render-only.
//
// Every record is taken from a sim event or a sim object the first time the buffer shows it, with the positions of that
// tick; draw() then paints each one as a pure function of (records, render ms), where render ms = render tick x 50. So a
// replay, a scrub or slow-mo draws the same frame, and nothing here sends an input or moves a tick: an effect starts at its
// event's own tick (a beam charges in the 150 ms before its tick, from the buffer's look-ahead, as the attack pose does).
// The danger hue is never used here: the red candles stay the telegraph's (fx.mjs).
import * as THREE from 'three';
import { milliToWorld } from './frame.mjs';
import { TICK_MS } from './buffer.mjs';
import { crownOf } from './actors.mjs';

export const COL = { cream: '#FFF8EA', gold: '#F7CF6B', mint: '#9FDCC5', sky: '#A9D4F5', dust: '#E8D9B5', ball: '#8A5F3C', shade: '#3B2F25', white: '#FFFFFF' };
export const HEAVY_DAMAGE = 18;               // FEEL.heavyHit: a heavy hit gets the bigger star and 4 puffs
const KEEP_MS = 3000;                          // a record older than this draws nothing and is dropped
const clamp = (v, a, b) => Math.max(a, Math.min(b, v)), k01 = (t, a, b) => clamp((t - a) / (b - a), 0, 1);
const eOut = (k) => 1 - Math.pow(1 - k, 3);
const DEG = Math.PI / 180;
const HITSTOP_KO_MS = 200;

// sprite pictures, drawn once on a canvas (cream star with a gold edge; a soft round puff)
let TEX = null;
function textures() {
  if (TEX) return TEX;
  const tex = (draw, n = 128) => { const c = document.createElement('canvas'); c.width = c.height = n; draw(c.getContext('2d'), n); const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t; };
  TEX = {
    star: tex((g, n) => { g.translate(n / 2, n / 2); g.beginPath(); for (let i = 0; i < 8; i++) { const r = i % 2 ? n * 0.16 : n * 0.47, a = i * Math.PI / 4 - Math.PI / 2; g.lineTo(Math.cos(a) * r, Math.sin(a) * r); } g.closePath(); g.fillStyle = COL.cream; g.fill(); g.lineWidth = n * 0.04; g.strokeStyle = COL.gold; g.stroke(); }),
    puff: tex((g, n) => { const r = g.createRadialGradient(n / 2, n / 2, 0, n / 2, n / 2, n / 2); r.addColorStop(0, 'rgba(255,255,255,1)'); r.addColorStop(0.55, 'rgba(255,255,255,0.85)'); r.addColorStop(1, 'rgba(255,255,255,0)'); g.fillStyle = r; g.fillRect(0, 0, n, n); }),
  };
  return TEX;
}

export class Fight {
  constructor(scene) {
    this.scene = scene; this.group = new THREE.Group(); this.group.name = 'fight-fx'; scene.add(this.group);
    this.records = []; this.byKey = new Map();   // records in arrival order; objects (shot, lob, beam, sweep) by sim key
    this.sprites = []; this.used = 0; this.meshes = new Map(); this.live = 0; this.budget = 150;
    this.drops = new Map();                        // drop key -> {from, to, at} (its flight) or null (not a KO's)
    this.dropsFired = false;                       // onDrops has run: an unknown drop is in a snapshot ahead of its KO
    this.log = [];                                 // (kind, tick, first drawn render ms): the case reads it
    this.seq = 0;
  }

  // ---- records, from the buffer ------------------------------------------------------------------------------------------
  // snap: the snapshot whose tick fired; pos(id) -> world {x,z} at that tick; tip(id) -> the weapon mount's world point now
  onEvent(ev, tick, pos, tip) {
    if (ev.kind === 'hit') {
      const s = pos(ev.source), d = pos(ev.target); if (!d) return;
      this.add({ kind: 'hit', tick, s: s || d, d, heavy: ev.damage >= HEAVY_DAMAGE, move: ev.move || '', sid: ev.source || null, tid: ev.target });
    } else if (ev.kind === 'attack' && ev.weapon === 'swing') {
      // the slam: its floor band is aimed from the swinger to the one it slams (else along its facing)
      const p = pos(ev.fighter); if (!p) return;
      const t = ev.target && pos(ev.target), aim = t ? Math.atan2(t.z - p.z, t.x - p.x) * 180 / Math.PI : p.dir;
      this.add({ kind: 'arc', tick, p, dir: aim, id: ev.fighter });
    } else if (ev.kind === 'ko') {
      const d = pos(ev.fighter); if (!d) return;
      this.add({ kind: 'ko', tick, d, id: ev.fighter, by: ev.source || null });
    }
  }
  // sim objects and casts from every snapshot the buffer takes in (main.mjs's look-ahead loop), so none is skipped between frames
  // reachOf(cast): the cast's own radius in tiles (the cast metadata's bound), when known
  onObjects(snap, pos, tip, reachOf = () => null) {
    for (const o of snap.objects) {
      if (this.byKey.has(o.key)) continue;
      const owner = this.ownerOf(snap, o);
      if (o.kind === 'shot') {
        const from = owner && tip(owner) || { ...milliToWorld(o.x, o.y, 0.7) }, to = milliToWorld(o.tx, o.ty, 0.7);
        this.add({ kind: 'shot', key: o.key, tick: snap.tick, from, to, start: milliToWorld(o.x, o.y) });
      } else if (o.kind === 'lob') {
        const from = owner && tip(owner) || milliToWorld(o.x, o.y, 0.9);
        this.add({ kind: 'lob', key: o.key, tick: snap.tick, from, to: milliToWorld(o.tx, o.ty, 0.2), at: o.resolveAt });
      } else if (o.kind === 'beam') {   // the sim resolves an object on the tick after its resolveAt: that is the hit's tick
        this.add({ kind: 'beam', key: o.key, tick: o.resolveAt + 1, owner, angle: o.angle, range: o.range, x: o.x, y: o.y, width: 1, end: o.resolveAt + 1 });
      } else if (o.kind === 'beam_sweep') {
        this.add({ kind: 'sweep', key: o.key, tick: o.resolveAt + 1, owner, angle: o.angle, range: o.range, x: o.x, y: o.y, width: 1.3, end: o.until + 1 });
      }
    }
    for (const c of snap.casts) {
      if (c.sig !== 'shockwave') continue;
      const key = 'wave:' + c.who + ':' + c.resolveAt; if (this.byKey.has(key)) continue;
      // its hits land the tick after; it reaches everyone the sim pushes: the cast's own radius (3 tiles by the rules table)
      const p = pos(c.who); if (p) this.add({ kind: 'wave', key, tick: c.resolveAt + 1, p, r: reachOf(c) || 3 });
    }
  }
  // the shot's owner is the attacker whose attack event fired it; a beam or sweep carries it in its origin
  ownerOf(snap, o) {
    let best = null, bd = 1e9;
    for (const f of snap.fighters) { const d = Math.hypot(f.x - o.x, f.y - o.y); if (f.status === 0 && d < bd) { bd = d; best = f.id; } }
    return bd <= 1500 ? best : null;
  }
  add(r) { r.uid = ++this.seq; r.seen = null; this.records.push(r); if (r.key) this.byKey.set(r.key, r); }

  // The drops of a snapshot the buffer fires, after that tick's KOs: a new drop within 2 ticks of a KO and near the KO'd body
  // flies there from the body (one object, flight to rest); any other drop (one already lying there) has no flight.
  onDrops(snap) {
    this.dropsFired = true;
    for (const d of snap.drops) {
      if (this.drops.has(d.key)) continue;
      const to = milliToWorld(d.x, d.y);
      let best = null, bd = 6;
      for (const r of this.records) if (r.kind === 'ko' && Math.abs(r.tick - snap.tick) <= 2) { const L = Math.hypot(r.d.x - to.x, r.d.z - to.z); if (L < bd) { bd = L; best = r; } }
      this.drops.set(d.key, best ? { from: best.d, to, at: best.tick * TICK_MS + HITSTOP_KO_MS } : null);
    }
  }
  // the drop's pose at render ms: hidden in the body until the freeze ends, then 700 ms, two bounces peaking 1.6 tiles
  dropPose(key, rtMs) {
    if (!this.drops.has(key)) return this.dropsFired ? { hidden: true } : null;   // ahead of the render tick: its KO has not fired yet
    const f = this.drops.get(key); if (!f) return null;
    if (rtMs < f.at) return { hidden: true };
    const k = k01(rtMs, f.at, f.at + 700), e = eOut(k);
    return { x: f.from.x + (f.to.x - f.from.x) * e, y: Math.abs(Math.sin(Math.PI * 2 * k)) * (1 - k) * 1.6, z: f.from.z + (f.to.z - f.from.z) * e, spin: k < 1 ? k * 8 : 0, landed: k >= 1 };
  }

  // ---- drawing -------------------------------------------------------------------------------------------------------
  sprite(map, x, y, z, size, opacity, rot = 0, color = COL.white) {
    if (opacity <= 0.01 || size <= 0 || this.live >= this.budget) return;
    let s = this.sprites[this.used];
    if (!s) { s = new THREE.Sprite(new THREE.SpriteMaterial({ transparent: true, depthWrite: false, depthTest: false })); s.renderOrder = 6; this.group.add(s); this.sprites.push(s); }
    this.used++; this.live++;
    s.material.map = map; s.material.color.set(color); s.material.opacity = opacity; s.material.rotation = rot;
    s.position.set(x, y, z); s.scale.set(size, size, 1); s.visible = true;
  }
  mesh(key, make) {
    if (this.live >= this.budget) return null;
    let m = this.meshes.get(key);
    if (!m) { m = make(); m.renderOrder = 5; this.group.add(m); this.meshes.set(key, m); }
    m.visible = true; m.userData.used = true; this.live++;
    return m;
  }

  // ctx: { actors (Actors), budget (shapes left under the 150 cap) }
  draw(rtMs, ctx) {
    const T = textures();
    this.used = 0; this.live = 0; this.budget = ctx.budget;
    for (const m of this.meshes.values()) { m.visible = false; m.userData.used = false; }
    const tipOf = (id) => { const a = id && ctx.actors.get(id); if (!a) return null; a.J.mountWeapon.updateWorldMatrix(true, false); return a.J.mountWeapon.getWorldPosition(new THREE.Vector3()); };
    const bodyOf = (id) => { const a = id && ctx.actors.get(id); return a ? a.h.object3d : null; };
    // the most important first: when the cap bites, dust and arcs go before KOs, projectiles and beams
    const order = { ko: 0, shot: 1, lob: 1, beam: 1, sweep: 1, wave: 2, hit: 3, arc: 4 };
    const live = this.records.filter((r) => rtMs - r.tick * TICK_MS < KEEP_MS);
    if (live.length !== this.records.length) {
      for (const r of this.records) if (!live.includes(r)) { if (r.key) this.byKey.delete(r.key); this.free(r); }
      this.records = live;
    }
    const sorted = live.slice().sort((a, b) => order[a.kind] - order[b.kind]);
    for (const r of sorted) {
      const t = rtMs - r.tick * TICK_MS, n0 = this.live;
      if (r.kind === 'hit') this.impact(T, r, t);
      else if (r.kind === 'arc') { const a = ctx.actors.get(r.id); this.arc(r, t, a && a.slam); }
      else if (r.kind === 'ko') this.ko(T, r, t, bodyOf(r.id));
      else if (r.kind === 'shot') this.shot(T, r, rtMs, ctx);
      else if (r.kind === 'lob') this.lob(T, r, rtMs);
      else if (r.kind === 'beam' || r.kind === 'sweep') this.beam(T, r, rtMs, tipOf(r.owner));
      else if (r.kind === 'wave') this.wave(T, r, t);
      if (this.live > n0 && r.seen === null) { r.seen = rtMs; this.log.push({ kind: r.kind, tick: r.tick, firstMs: rtMs }); if (this.log.length > 400) this.log.shift(); }
    }
    for (let i = this.used; i < this.sprites.length; i++) this.sprites[i].visible = false;
  }
  free(r) {
    for (const [key, m] of this.meshes) if (key.startsWith(r.uid + ':')) { this.group.remove(m); m.geometry.dispose(); m.material.dispose(); this.meshes.delete(key); }
  }
  keyOf(r, part) { return r.uid + ':' + part; }

  // 4. the impact star on the struck side (0.5 tiles toward the attacker, 0.1 down from the chest, never the face) and dust
  impact(T, r, t) {
    if (t < 0 || t > 520) return;
    const dx = r.s.x - r.d.x, dz = r.s.z - r.d.z, L = Math.hypot(dx, dz) || 1, size = r.heavy ? 0.8 : 0.55;
    // the contact point: 0.5 tiles toward the attacker, under the face; a slam's lands where the head lands, on the crown
    const c = r.move === 'swing' ? crownOf(r.s, r.d) : { x: r.d.x + dx / L * 0.5, y: 0.6, z: r.d.z + dz / L * 0.5 };
    if (t <= 150) this.sprite(T.star, c.x, c.y, c.z, size * (0.5 + 0.5 * eOut(k01(t, 0, 50))), 1 - k01(t, 80, 150), r.tick * 0.7);
    if (t <= 380) for (let i = 0; i < (r.heavy ? 4 : 2); i++) {
      const a = i * 2.1 + r.tick, k = eOut(k01(t, 0, 380));
      this.sprite(T.puff, r.d.x + Math.cos(a) * 0.7 * k, 0.12 + 0.15 * k, r.d.z + Math.sin(a) * 0.7 * k, 0.35 + 0.35 * k, 0.7 * (1 - k), 0, COL.dust);
    }
  }
  // the slam (SPEC section 2a): a flat white band on the floor at the sim's hit range (1.0 to 1.3 tiles, +-60 degrees of the aim,
  // y 0.05) from the hit tick, growing 0.8 -> 1 in 60 ms and fading from 0.9 between 80 and 220 ms; and a thin band just inside
  // the head's path, around the hand in the slam plane, from 60 ms before the hit to 120 ms after it
  arc(r, t, slam) {
    if (t >= 0 && t < 220) {
      const m = this.mesh(this.keyOf(r, 'band'), () => new THREE.Mesh(new THREE.RingGeometry(1.0, 1.3, 32, 1, -Math.PI / 3, 2 * Math.PI / 3), new THREE.MeshBasicMaterial({ color: COL.white, transparent: true, side: THREE.DoubleSide, depthWrite: false })));
      if (m) {
        // laid flat, the ring's plane angle phi faces world -phi: a turn of -(aim) centres it on the aim
        m.position.set(r.p.x, 0.05, r.p.z); m.rotation.set(-Math.PI / 2, 0, -(r.dir || 0) * DEG);
        m.scale.setScalar(0.8 + 0.2 * eOut(k01(t, 0, 60))); m.material.opacity = 0.9 * (1 - k01(t, 80, 220));
      }
    }
    if (!slam || t < -60 || t > 120) return;
    const tr = this.mesh(this.keyOf(r, 'trail'), () => new THREE.Mesh(new THREE.RingGeometry(1, 1.32, 16, 1, 0, 0.9), new THREE.MeshBasicMaterial({ color: COL.white, transparent: true, side: THREE.DoubleSide, depthWrite: false })));
    if (!tr) return;
    const rad = slam.Lc * 0.78; tr.scale.set(rad, rad, 1);
    tr.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(slam.u, UP, new THREE.Vector3().crossVectors(slam.u, UP))).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), slam.phi));
    tr.position.copy(slam.H); tr.material.opacity = 0.75 * k01(t, -60, -30) * (1 - k01(t, 20, 120));
  }
  // 5. the shot: a gold ball on the sim's own path (its interpolated position), rising 0.25 tiles mid-flight, a trail, a muzzle star
  shot(T, r, rtMs, ctx) {
    const o = ctx.objects && ctx.objects.get(r.key);
    if (!o || rtMs < r.tick * TICK_MS) return;   // gone from the sim (it hit or ran out), or not fired yet at this render tick
    const total = Math.hypot(r.to.x - r.start.x, r.to.z - r.start.z) || 1, q = clamp(1 - Math.hypot(r.to.x - o.x, r.to.z - o.z) / total, 0, 1);
    const y = r.from.y + (r.to.y - r.from.y) * q + Math.sin(Math.PI * q) * 0.25;
    const m = this.mesh(this.keyOf(r, 'ball'), () => new THREE.Mesh(new THREE.SphereGeometry(0.2, 12, 8), new THREE.MeshLambertMaterial({ color: COL.gold, emissive: '#7A5A10', emissiveIntensity: 0.4 })));
    if (m) m.position.set(o.x, y, o.z);
    const dx = (r.to.x - r.start.x) / total, dz = (r.to.z - r.start.z) / total;
    for (let i = 1; i <= 4; i++) { const back = i * 0.06 * total; this.sprite(T.puff, o.x - dx * back, y, o.z - dz * back, 0.45 - i * 0.07, 0.7 - i * 0.15, 0, COL.gold); }
    const t = rtMs - r.tick * TICK_MS;
    if (t < 90) this.sprite(T.star, r.from.x, r.from.y, r.from.z, 0.9, 1 - k01(t, 0, 90));
  }
  // the lob: a ball on a 3.0-tile arc over the sim's flight, its ground shadow growing and darkening so the landing reads first
  lob(T, r, rtMs) {
    const t0 = r.tick * TICK_MS, t1 = r.at * TICK_MS;
    if (rtMs < t0 || rtMs >= t1) return;
    const k = k01(rtMs, t0, t1), x = r.from.x + (r.to.x - r.from.x) * k, z = r.from.z + (r.to.z - r.from.z) * k;
    const m = this.mesh(this.keyOf(r, 'ball'), () => new THREE.Mesh(new THREE.SphereGeometry(0.28, 12, 8), new THREE.MeshLambertMaterial({ color: COL.ball })));
    if (m) { m.position.set(x, r.from.y + (r.to.y - r.from.y) * k + Math.sin(Math.PI * k) * 3.0, z); m.rotation.set(rtMs * 0.02, 0, rtMs * 0.01); }
    this.sprite(T.puff, x, 0.05, z, 0.3 + 0.5 * k, 0.35 * k, 0, COL.shade);
  }
  // the beam and the beam sweep: a 150 ms charge at the weapon, then an open sky cylinder (pulsing +-18%) round a white core from
  // the weapon to its end; the sweep turns across its 60 degrees over the sim's own duration; both fade 120 ms after the end
  beam(T, r, rtMs, tip) {
    const start = r.tick * TICK_MS, end = Math.max(r.end * TICK_MS, start + TICK_MS);
    if (rtMs < start - 150 || rtMs >= end + 120) return;
    const from = tip || new THREE.Vector3(r.x / 1000, 0.8, r.y / 1000);
    if (rtMs < start) { const k = k01(rtMs, start - 150, start); this.sprite(T.puff, from.x, from.y, from.z, 0.3 + 0.6 * k, 0.9, 0, COL.sky); return; }
    let ang = r.angle;
    if (r.kind === 'sweep') ang += 60 * k01(rtMs, start, r.end * TICK_MS);
    const ex = r.x + Math.cos(ang * DEG) * r.range, ey = r.y + Math.sin(ang * DEG) * r.range;
    const to = new THREE.Vector3(ex / 1000, 0.7, ey / 1000), fade = 1 - k01(rtMs, end, end + 120);
    const len = from.distanceTo(to), mid = from.clone().add(to).multiplyScalar(0.5), dir = to.clone().sub(from).normalize();
    const q = new THREE.Quaternion().setFromUnitVectors(UP, dir), pul = 1 + 0.18 * Math.sin(rtMs / 25), w = r.width;
    const o = this.mesh(this.keyOf(r, 'outer'), () => new THREE.Mesh(new THREE.CylinderGeometry(1, 1, 1, 14, 1, true), new THREE.MeshBasicMaterial({ color: COL.sky, transparent: true, opacity: 0.55, depthWrite: false, side: THREE.DoubleSide })));
    if (o) { o.position.copy(mid); o.quaternion.copy(q); o.scale.set(w * 0.32 * pul * fade, len, w * 0.32 * pul * fade); }
    const c = this.mesh(this.keyOf(r, 'core'), () => new THREE.Mesh(new THREE.CylinderGeometry(1, 1, 1, 10), new THREE.MeshBasicMaterial({ color: COL.white })));
    if (c) { c.position.copy(mid); c.quaternion.copy(q); c.scale.set(w * 0.12 * fade, len, w * 0.12 * fade); }
    this.sprite(T.star, to.x, to.y, to.z, 1 + 0.3 * Math.sin(rtMs / 30), fade, rtMs * 0.01);
  }
  // 7. the shockwave: a mint torus growing to 3 tiles over 450 ms and fading 350-750 ms, 10 dust puffs riding its edge
  wave(T, r, t) {
    if (t < 0 || t > 750) return;
    const k = eOut(k01(t, 0, 450)), R = r.r * k, fade = 1 - k01(t, 350, 750);
    const m = this.mesh(this.keyOf(r, 'torus'), () => new THREE.Mesh(new THREE.TorusGeometry(1, 0.08, 6, 48), new THREE.MeshBasicMaterial({ color: COL.mint, transparent: true, depthWrite: false })));
    if (m) { m.position.set(r.p.x, 0.12, r.p.z); m.rotation.x = Math.PI / 2; m.scale.set(Math.max(0.01, R), Math.max(0.01, R), 1 + 2 * (1 - k)); m.material.opacity = fade; }
    for (let i = 0; i < 10; i++) { const a = i / 10 * Math.PI * 2; this.sprite(T.puff, r.p.x + Math.cos(a) * R, 0.25, r.p.z + Math.sin(a) * R, 0.7, 0.75 * fade, 0, COL.dust); }
  }
  // 6. the KO: 3 small stars trailing the launched body, then the poof (1 to 3.5 tiles, +1300 to +1800 ms after the freeze)
  ko(T, r, t, body) {
    const ts = t - HITSTOP_KO_MS; if (ts < 0 || ts > 1800) return;
    const p = body ? body.position : { x: r.d.x, y: 0, z: r.d.z };
    if (ts < 650) for (let i = 1; i <= 3; i++) this.sprite(T.star, p.x - i * 0.3, p.y + 0.8, p.z - i * 0.1, 0.5 - i * 0.1, 0.9 - i * 0.25, ts * 0.01);
    if (ts > 1300) this.sprite(T.puff, p.x, 0.7, p.z, 1 + 2.5 * eOut(k01(ts, 1300, 1700)), 1 - k01(ts, 1500, 1800), 0, COL.cream);
  }
}

const UP = new THREE.Vector3(0, 1, 0);
