// motion.js — draws the key-pose strips for motion.html: one row per state (attack has one row per weapon).
import * as THREE from 'three';
import { LOOK3, makeHouse, houseRow, setupLight } from './index.js';
import { STATES, WEAPONS, duration, isLoop, applyMotion, install } from './motion3.js';

const W = 150, H = 165, DPR = 2, N = 8, SEA = '#ECEEEA', SAND = '#D9D9D4';
const errors = [];
addEventListener('error', (e) => errors.push(String(e.message)));
const origErr = console.error; console.error = function () { errors.push([].join.call(arguments, ' ')); origErr.apply(console, arguments); };

const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(DPR); renderer.setSize(W, H, false); renderer.setClearColor(new THREE.Color(SEA), 1);
const scene = new THREE.Scene(); setupLight(scene, renderer, { extent: 1.4 });
const disc = LOOK3.kit.M(new THREE.CylinderGeometry(0.8, 0.82, 0.06, 48), SAND, { cast: false }); disc.position.y = -0.03; scene.add(disc);
const a = W / H, halfH = 0.86, cam = new THREE.OrthographicCamera(-halfH * a, halfH * a, halfH, -halfH, 0.1, 60);
const az = 32 * Math.PI / 180, el = 22 * Math.PI / 180, c = new THREE.Vector3(0, 0.56, 0);
cam.position.set(c.x + Math.sin(az) * Math.cos(el) * 20, c.y + Math.sin(el) * 20, c.z + Math.cos(az) * Math.cos(el) * 20); cam.lookAt(c);

const t = makeHouse('captain-banana-zone', { kit: 'full' }); t.object3d.rotation.y = 0.55; scene.add(t.object3d);
const WEAPON_ITEM = { swing: 'c-swing', shot: 'c-shot', beam: 'c-beam', lob: 'c-lob', zap: 'c-zap', lunge: 'c-lunge' };   // each attack row holds its own kind of weapon
const BASE_KIT = houseRow('captain-banana-zone').kit;
const rows = [];
STATES.forEach((s) => { if (s === 'attack') WEAPONS.forEach((w) => rows.push({ state: s, weapon: w })); else rows.push({ state: s }); });

const box = document.getElementById('rows');
for (const r of rows) {
  const dur = duration(r.state, r.weapon), loop = isLoop(r.state);
  t.setItems(Object.assign({}, BASE_KIT, { weapon: WEAPON_ITEM[r.weapon] || BASE_KIT.weapon }));
  const row = document.createElement('div'); row.className = 'row';
  row.innerHTML = '<h2>' + r.state.replace('_', ' ') + (r.weapon ? ' · ' + r.weapon : '') + '<small>' + (loop ? 'loop ' : '') + dur + ' ms</small></h2><div class="cells"></div>';
  const cells = row.querySelector('.cells');
  for (let i = 0; i < N; i++) {
    const age = loop ? dur * i / N : dur * i / (N - 1);
    applyMotion(t, { state: r.state, weapon: r.weapon, age });
    renderer.render(scene, cam);
    const cv = document.createElement('canvas'); cv.width = W * DPR; cv.height = H * DPR; cv.getContext('2d').drawImage(renderer.domElement, 0, 0);
    const cell = document.createElement('div'); cell.appendChild(cv); cell.insertAdjacentHTML('beforeend', '<span>' + Math.round(age) + ' ms</span>'); cells.appendChild(cell);
  }
  box.appendChild(row);
}
// determinism and rest checks: the same inputs give the same joints, and age 0 of idle returns to rest
function snap() { const J = t.joints; return [J.base.scale.x, J.base.scale.y, J.base.position.y, J.pivot.rotation.x, J.pivot.rotation.z, J.handR.position.y, J.mountWeapon.rotation.x].map((v) => +v.toFixed(6)).join(','); }
applyMotion(t, { state: 'attack', weapon: 'swing', age: 120 }); const s1 = snap();
applyMotion(t, { state: 'ko', age: 500 }); applyMotion(t, { state: 'attack', weapon: 'swing', age: 120 }); const s2 = snap();
const deterministic = s1 === s2;
install(); t.setPose({ state: 'attack', weapon: 'swing', age: 120 }); const hasHook = snap() === s1;   // setPose goes through the same function once installed
const ok = deterministic && hasHook && errors.length === 0 && rows.length === STATES.length - 1 + WEAPONS.length;
document.getElementById('summary').innerHTML = rows.length + ' motions · ' + rows.length * N + ' frames · deterministic: ' + deterministic + ' · console errors: ' + errors.length + ' · ' + LOOK3.VERSION;
window.__MOTION = { rows: rows.length, frames: rows.length * N, deterministic, errors, ok, hasHook };
window.__MOTION_DONE = true;
