// compare.js — renders the 14 house models and the 6 presets with the ES modules and diffs the house ones
// against the stored reference renders (ref/b3-v34/<id>.png, 540x580, made at DPR 2).
import * as THREE from 'three';
import { LOOK3, HOUSE_IDS, ROSTER, makeHouse, makePreset, PRESET_IDS, setupLight } from './index.js';

const W = 270, H = 290, DPR = 2, SEA = '#ECEEEA', SAND = '#D9D9D4';
const errors = [];
addEventListener('error', (e) => errors.push(String(e.message)));
const origErr = console.error; console.error = function () { errors.push([].join.call(arguments, ' ')); origErr.apply(console, arguments); };

function ortho(w, h, halfH, center, azDeg, elDeg) {
  const a = w / h, cam = new THREE.OrthographicCamera(-halfH * a, halfH * a, halfH, -halfH, 0.1, 60);
  const az = azDeg * Math.PI / 180, el = elDeg * Math.PI / 180;
  cam.position.set(center.x + Math.sin(az) * Math.cos(el) * 20, center.y + Math.sin(el) * 20, center.z + Math.cos(az) * Math.cos(el) * 20);
  cam.lookAt(center); return cam;
}

const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(DPR); renderer.setSize(W, H, false);
const scene = new THREE.Scene();
setupLight(scene, renderer, { extent: 1.2 });
const disc = LOOK3.kit.M(new THREE.CylinderGeometry(0.62, 0.64, 0.06, 48), SAND, { cast: false });
disc.position.y = -0.03; scene.add(disc);
const cam = ortho(W, H, 0.56, new THREE.Vector3(0, 0.43, 0), 16, 18);
renderer.setClearColor(new THREE.Color(SEA), 1);

function shoot(obj3d) {
  obj3d.rotation.y = -0.38; scene.add(obj3d);
  renderer.render(scene, cam);
  const cv = document.createElement('canvas'); cv.width = W * DPR; cv.height = H * DPR;
  cv.getContext('2d').drawImage(renderer.domElement, 0, 0);
  scene.remove(obj3d); return cv;
}
function pixels(src) {
  const cv = document.createElement('canvas'); cv.width = W * DPR; cv.height = H * DPR;
  const g = cv.getContext('2d', { willReadFrequently: true }); g.drawImage(src, 0, 0);
  return g.getImageData(0, 0, W * DPR, H * DPR);
}
function loadImg(src) { return new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error('missing ' + src)); i.src = src; }); }

const THRESH = 8, MAX_DIFF_FRACTION = 0.002;   // a pair passes when under 0.2% of pixels differ by more than 8/255
const results = [];
const grid = document.getElementById('grid');
for (const id of HOUSE_IDS) {
  const row = ROSTER.find((r) => r.trenchieId === id);
  const t = makeHouse(id);
  const live = shoot(t.object3d);
  const meshes = t.meshCount(); t.dispose();
  const card = document.createElement('div'); card.className = 'pair';
  let metric;
  try {
    const ref = await loadImg('ref/b3-v34/' + id + '.png');
    const a = pixels(ref), b = pixels(live);
    let over = 0, sum = 0; const n = a.width * a.height;
    for (let i = 0; i < a.data.length; i += 4) {
      const d = Math.max(Math.abs(a.data[i] - b.data[i]), Math.abs(a.data[i + 1] - b.data[i + 1]), Math.abs(a.data[i + 2] - b.data[i + 2]));
      sum += d; if (d > THRESH) over++;
    }
    const frac = over / n, pass = frac <= MAX_DIFF_FRACTION && a.width === b.width && a.height === b.height;
    results.push({ id, over, frac, mean: sum / n, pass, meshes });
    metric = '<span class="' + (pass ? 'ok' : 'bad') + '">' + (pass ? 'MATCH' : 'DIFFERS') + '</span> ' + (frac * 100).toFixed(3) + '% of pixels over ' + THRESH + '/255 · mean ' + (sum / n).toFixed(3) + ' · ' + meshes + ' meshes';
    card.innerHTML = '<div class="imgs"><div class="cell"><img alt="" src="ref/b3-v34/' + id + '.png"><span class="cap">reference (B3 v3.4)</span></div><div class="cell live"><span class="cap">module render</span></div></div>';
  } catch (e) {
    results.push({ id, pass: false, error: String(e) }); metric = '<span class="bad">NO REFERENCE</span> ' + e.message;
    card.innerHTML = '<div class="imgs"><div class="cell live"><span class="cap">module render</span></div></div>';
  }
  card.querySelector('.live').prepend(live);
  card.insertAdjacentHTML('beforeend', '<div class="name">' + row.name + ' <span style="font-weight:400;color:var(--mute)">· ' + row.tag + '</span></div><div class="metric">' + metric + '</div>');
  grid.appendChild(card);
}

// presets: the same framing, the starter kit, one per shape (body colours vary so the shapes read apart)
const COL = ['p07', 'p09', 'p11', 'p12', 'p14', 'p08'], TONE = ['warm', 'light', 'tan', 'deep', 'warm', 'light'];
const pbox = document.getElementById('presets');
PRESET_IDS.forEach((sid, i) => {
  const t = makePreset({ shape: sid, body: COL[i], tone: TONE[i] });
  const cv = shoot(t.object3d); t.dispose();
  const card = document.createElement('div'); card.className = 'pair';
  card.appendChild(cv); card.insertAdjacentHTML('beforeend', '<div class="name">' + sid[0].toUpperCase() + sid.slice(1) + '</div>');
  pbox.appendChild(card);
});

const passed = results.filter((r) => r.pass).length;
const ok = passed === HOUSE_IDS.length && PRESET_IDS.length === 6 && errors.length === 0;
document.getElementById('summary').innerHTML = '<b class="' + (ok ? 'ok' : 'bad') + '">' + passed + '/' + HOUSE_IDS.length + ' house models match</b> · ' + PRESET_IDS.length + ' presets drawn · console errors: ' + errors.length + ' · ' + LOOK3.VERSION + ' · three r' + THREE.REVISION + ' · DPR ' + devicePixelRatio;
document.getElementById('foot').textContent = 'Pass rule: under ' + (MAX_DIFF_FRACTION * 100) + '% of pixels differ by more than ' + THRESH + '/255 against the stored 2x reference.';
window.__ART = { results, errors, passed, presets: PRESET_IDS.length, ok };
window.__ART_DONE = true;
