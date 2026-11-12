// The phone camera follows the action (board 3, final/SPEC.md section 8). On a narrow screen the whole ring is about 21 tiles
// across, so a body is about 24 px tall; here the view zooms to 2.8x on the action, so a body is about 60 px:
//   playing  on your own trenchie (the followed one),
//   watching on the busiest fight: the latest KO (its KO-er and the flying body), else the latest exchange of hits.
// A change of subject blends pan and zoom over 300 ms (ease-out). Desktop keeps the game's framing. Render-only: it moves the
// camera after scene.placeCamera(), along the camera's own right and up axes, and leaves the frustum (and its pan) alone.
import * as THREE from 'three';

export const PHONE_ZOOM = 2.8;
export const BLEND_MS = 300;
const HOLD_MS = 1500;         // a subject is kept at least this long, so two quick fights don't jerk the view
const IDLE_MS = 4000;         // nothing for this long: back to the whole ring
const eOut = (k) => 1 - Math.pow(1 - Math.min(1, Math.max(0, k)), 3);

// The subject at render ms `rtMs`: {key, ids} or null. records: fight.mjs records (kind, tick, ids); followId: your trenchie.
export function pickSubject(records, rtMs, followId, tickMs = 50) {
  if (followId) return { key: 'follow:' + followId, ids: [followId] };
  let ko = null, hit = null;
  for (const r of records) {
    const t = rtMs - r.tick * tickMs; if (t < 0) continue;
    if (r.kind === 'ko' && t < 2200 && (!ko || r.tick > ko.tick)) ko = r;
    if (r.kind === 'hit' && t < IDLE_MS && (!hit || r.tick > hit.tick)) hit = r;
  }
  if (ko) return { key: 'ko:' + ko.uid, ids: [ko.id, ko.by].filter(Boolean) };
  if (hit) return { key: 'pair:' + [hit.sid, hit.tid].sort().join('|'), ids: [hit.sid, hit.tid].filter(Boolean) };
  return null;
}

export class CamFollow {
  constructor(stage) { this.stage = stage; this.shown = { x: 0, z: 0, zoom: 1 }; this.subject = null; this.since = -1e9; this.from = null; this.at = -1e9; }

  // where(id) -> world {x, z} of a body now (its drawn position, KO flight included), or null
  apply(nowMs, rtMs, records, followId, where) {
    const { camera, view } = this.stage;
    if (!view.narrow) { if (camera.zoom !== 1) { camera.zoom = 1; camera.updateProjectionMatrix(); } this.shown = { ...this.home(), zoom: 1 }; this.subject = null; return; }
    if (!this.subject) this.shown = { ...this.home(), zoom: 1 };
    let pick = pickSubject(records, rtMs, followId);
    if (this.subject && pick && pick.key !== this.subject.key && nowMs - this.since < HOLD_MS && !pick.key.startsWith('ko:') && !pick.key.startsWith('follow:')) pick = this.subject;
    const key = pick ? pick.key : 'ring';
    if (!this.subject || this.subject.key !== key) { this.from = { ...this.shown }; this.at = nowMs; this.since = nowMs; this.subject = pick || { key: 'ring', ids: [] }; }
    // the target: the centre of the subject's bodies, or the ring's centre at zoom 1
    let tx = 0, tz = 0, n = 0;
    for (const id of this.subject.ids) { const p = where(id); if (p) { tx += p.x; tz += p.z; n++; } }
    const target = n ? { x: tx / n, z: tz / n, zoom: PHONE_ZOOM } : { ...this.home(), zoom: 1 };
    const g = eOut((nowMs - this.at) / BLEND_MS), f = this.from || target;
    this.shown = { x: f.x + (target.x - f.x) * g, z: f.z + (target.z - f.z) * g, zoom: f.zoom + (target.zoom - f.zoom) * g };
    this.place(this.shown);
  }

  // the point (at chest height) the game's own framing puts at the view's centre: the whole-ring view, unchanged
  home() {
    const { camera } = this.stage; camera.updateMatrixWorld();
    const r = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0), u = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1), f = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 2).negate();
    const c = camera.position.clone().addScaledVector(r, (camera.left + camera.right) / 2).addScaledVector(u, (camera.top + camera.bottom) / 2);
    c.addScaledVector(f, (0.6 - c.y) / f.y);
    return { x: c.x, z: c.z };
  }

  // zoom about the frustum's own centre (pads and pan kept), then slide so the point sits there
  place({ x, z, zoom }) {
    const { camera } = this.stage;
    camera.zoom = zoom; camera.updateProjectionMatrix(); camera.updateMatrixWorld();
    const r = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0), u = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1);
    const cx = (camera.left + camera.right) / 2, cy = (camera.top + camera.bottom) / 2;   // an orthographic zoom keeps this centre
    const rel = new THREE.Vector3(x, 0.6, z).sub(camera.position);
    camera.position.addScaledVector(r, rel.dot(r) - cx).addScaledVector(u, rel.dot(u) - cy);
    camera.updateMatrixWorld();
  }
}
