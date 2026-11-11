// Telegraphs (AOE): Pat picked c, red candles (2026-11-11), the default look. a and b stay for comparison (?tele=a|b);
// ?tele=old draws the earlier flat danger shape (fx.mjs).
// Each telegraph is one shader quad drawn at the true hit area (a signed-distance shape: circle, ring, cone, line), in the
// one reserved danger hue with a cream highlight and a darker value of the same hue; c adds one instanced mesh.
// Timing is read from the shape, not from the opacity: a = the fill blooms out to the rim, b = hazard tape zips shut,
// c = red candles print taller around the rim.
import * as THREE from 'three';

const DANGER = new THREE.Color('#E84855'), DEEP = new THREE.Color('#A8283A'), CREAM = new THREE.Color('#FFF8EA');
const SHAPE = { circle: 0, ring: 1, cone: 2, line: 3 };
export const TELE_STYLES = { a: 0, b: 1, c: 2 };
export const TELE_DEFAULT = 'c';

const VERT = `
varying vec2 vP;
void main() { vP = position.xy; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;

const FRAG = `
precision highp float;
varying vec2 vP;
uniform int uShape; uniform int uStyle;
uniform float uR; uniform float uHalf; uniform float uW; uniform float uBand; uniform float uP; uniform float uT;
uniform vec3 uDanger; uniform vec3 uDeep; uniform vec3 uCream;
const float PI = 3.14159265;
float sdPie(vec2 p, vec2 c, float r) { p.x = abs(p.x); float l = length(p) - r; float m = length(p - c * clamp(dot(p, c), 0.0, r)); return max(l, m * sign(c.y * p.x - c.x * p.y)); }
float sdBox(vec2 p, vec2 b) { vec2 d = abs(p) - b; return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0); }
// d: signed distance to the hit area's edge (negative inside); t: 0 at the origin of the attack, 1 at its far edge;
// u: position along the rim, 0..1 from the start of the tape (draft b)
void shape(vec2 p, out float d, out float t, out float u) {
  float len = length(p);
  if (uShape == 3) { d = sdBox(p - vec2(uR * 0.5, 0.0), vec2(uR * 0.5, uW * 0.5)); t = clamp(p.x / uR, 0.0, 1.0); u = t; }
  else if (uShape == 2) { vec2 q = vec2(p.y, p.x); d = sdPie(q, vec2(sin(uHalf), cos(uHalf)), uR); t = len / uR; u = t; }
  else if (uShape == 1) { d = abs(len - (uR - uBand * 0.5)) - uBand * 0.5; t = clamp((len - (uR - uBand)) / uBand, 0.0, 1.0); u = abs(atan(p.x, p.y)) / PI; }
  else { d = len - uR; t = len / uR; u = abs(atan(p.x, p.y)) / PI; }
}
void main() {
  float d, t, u; shape(vP, d, t, u);
  float aa = fwidth(d) * 1.2;
  float inside = 1.0 - smoothstep(-aa, aa, d);
  if (inside <= 0.0 && d > 0.3) discard;
  vec3 col = uDanger; float a = 0.0;
  float pulse = uP > 0.8 ? 0.5 + 0.5 * sin(uT * 18.0) : 0.0;
  if (uStyle == 0) {
    // a: fill bloom. A faint wash, a crisp rim with a cream inner line, and a solid fill that grows from the origin
    // and meets the rim at the hit.
    float wash = 0.10 * inside;
    float rim = (1.0 - smoothstep(-aa, aa, abs(d + 0.05) - 0.05 - pulse * 0.02));
    float cream = (1.0 - smoothstep(-aa, aa, abs(d + 0.135) - 0.022)) * inside;
    float grow = uP;
    float fill = (1.0 - smoothstep(grow - 0.012, grow, t)) * inside;
    float lead = (1.0 - smoothstep(0.0, 0.035, abs(t - grow))) * inside * step(0.02, grow) * (uShape == 1 ? 0.0 : 1.0);
    a = max(wash, fill * (0.22 + 0.14 * uP));
    col = uDanger;
    col = mix(col, uCream, cream * 0.9); a = max(a, cream * 0.85);
    col = mix(col, mix(uDanger, uCream, 0.35), lead); a = max(a, lead * 0.85);
    col = mix(col, uDeep, rim * 0.25); a = max(a, rim * 0.95);
  } else if (uStyle == 1) {
    // b: hazard tape. A striped danger-and-cream band is laid along the rim from the attack's start; when it closes,
    // it hits. Faint hatching inside; the unlaid rim shows as a thin dashed line.
    float band = (1.0 - smoothstep(-aa, aa, abs(d + uBand * 0.5) - uBand * 0.5));
    float laid = 1.0 - smoothstep(uP - 0.01, uP, u);
    float stripe = step(0.5, fract((vP.x + vP.y) / 0.34 - uT * 0.35));
    vec3 tape = mix(uDanger, uCream, stripe);
    float hatch = step(0.86, fract((vP.x - vP.y) / 0.55)) * inside;
    float dash = (1.0 - smoothstep(-aa, aa, abs(d + 0.03) - 0.03)) * step(0.45, fract(u * (uShape == 3 ? 6.0 : 14.0) * max(1.0, uR * 0.5)));
    a = 0.07 * inside + hatch * 0.10;
    col = uDanger;
    col = mix(col, uDanger, dash); a = max(a, dash * 0.7 * (1.0 - laid * band));
    // the tape edge: a deep line on both sides of the band so it reads on coral and sand alike
    float edge = (1.0 - smoothstep(-aa, aa, abs(abs(d + uBand * 0.5) - uBand * 0.5) - 0.018)) * laid;
    col = mix(col, tape, band * laid); a = max(a, band * laid * (0.92 + pulse * 0.08));
    col = mix(col, uDeep, edge); a = max(a, edge);
  } else {
    // c: red candles. Flat part: a soft danger vignette that deepens toward the rim and a thin rim line; the candles
    // themselves are instanced meshes standing on the rim (see buildCandles).
    float vig = smoothstep(0.0, 1.0, clamp(1.0 + d / max(0.6, uR * 0.55), 0.0, 1.0)) * inside;
    float rim = (1.0 - smoothstep(-aa, aa, abs(d + 0.03) - 0.03));
    a = vig * (0.12 + 0.22 * uP) + rim * 0.85;
    col = mix(uDanger, uDeep, rim * 0.4);
  }
  if (a <= 0.003) discard;
  gl_FragColor = vec4(col, a);
}`;

// rim points for the candles, in the quad's local frame (x along the attack, y across), spaced ~0.85 tiles
function rimPoints(t) {
  const pts = [], gap = 0.85, inset = 0.08;
  if (t.shape === 'line') {
    const n = Math.max(2, Math.round(t.r / gap));
    for (let i = 0; i <= n; i++) { const x = (i / n) * t.r; pts.push([x, t.width / 2 - inset], [x, -t.width / 2 + inset]); }
  } else if (t.shape === 'cone') {
    const half = t.arc * Math.PI / 360, arcN = Math.max(2, Math.round(t.r * 2 * half / gap)), sideN = Math.max(1, Math.round(t.r / gap));
    for (let i = 0; i <= arcN; i++) { const a = -half + (i / arcN) * 2 * half; pts.push([Math.cos(a) * (t.r - inset), Math.sin(a) * (t.r - inset)]); }
    for (let i = 1; i < sideN; i++) { const k = (i / sideN) * t.r; pts.push([Math.cos(half) * k, Math.sin(half) * k], [Math.cos(-half) * k, Math.sin(-half) * k]); }
  } else {
    const r = t.r - inset, n = Math.max(6, Math.round(2 * Math.PI * r / gap));
    for (let i = 0; i < n; i++) { const a = (i / n) * 2 * Math.PI; pts.push([Math.cos(a) * r, Math.sin(a) * r]); }
  }
  return pts;
}

let candleGeo = null;
function candleGeometry() {
  if (candleGeo) return candleGeo;
  // one unit-tall candle: a rounded body and a thin wick through it (a red candle, the island's "price fell" mark)
  const body = new THREE.CylinderGeometry(0.09, 0.09, 0.66, 10, 1); body.translate(0, 0.47, 0);
  const wick = new THREE.CylinderGeometry(0.022, 0.022, 1.0, 5, 1); wick.translate(0, 0.5, 0);
  const merge = (gs) => {
    const pos = [], nor = [], idx = []; let off = 0;
    const out = new THREE.BufferGeometry();
    gs.forEach((g, gi) => { const p = g.attributes.position.array, n = g.attributes.normal.array, ix = g.index.array;
      out.addGroup(idx.length, ix.length, gi); pos.push(...p); nor.push(...n); for (const i of ix) idx.push(i + off); off += p.length / 3; });
    out.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); out.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3)); out.setIndex(idx); return out;
  };
  candleGeo = merge([body, wick]); body.dispose(); wick.dispose();
  return candleGeo;
}
const candleMat = [new THREE.MeshToonMaterial({ color: DANGER }), new THREE.MeshToonMaterial({ color: DEEP })]; // body, wick

function buildCandles(t) {
  const pts = rimPoints(t);
  const im = new THREE.InstancedMesh(candleGeometry(), candleMat, pts.length);
  im.userData.pts = pts; im.castShadow = false; im.frustumCulled = false;   // effects cast no shadow (budget lever 2)
  return im;
}

export function makeTelegraph(t, style) {
  const st = TELE_STYLES[Object.hasOwn(TELE_STYLES, style) ? style : TELE_DEFAULT];
  let geo;
  const pad = 0.12;
  if (t.shape === 'line') { geo = new THREE.PlaneGeometry(t.r + pad * 2, t.width + pad * 2); geo.translate(t.r / 2, 0, 0); }
  else geo = new THREE.PlaneGeometry(2 * (t.r + pad), 2 * (t.r + pad));
  const mat = new THREE.ShaderMaterial({
    vertexShader: VERT, fragmentShader: FRAG, transparent: true, depthWrite: false, side: THREE.DoubleSide,
    uniforms: {
      uShape: { value: SHAPE[t.shape] ?? 0 }, uStyle: { value: st }, uR: { value: t.r }, uHalf: { value: (t.arc || 60) * Math.PI / 360 },
      uW: { value: t.width || 0.4 }, uBand: { value: t.shape === 'ring' ? 0.3 : 0.26 }, uP: { value: 0 }, uT: { value: 0 },
      uDanger: { value: DANGER }, uDeep: { value: DEEP }, uCream: { value: CREAM },
    },
  });
  const quad = new THREE.Mesh(geo, mat); quad.rotation.x = -Math.PI / 2; quad.renderOrder = 3;
  const g = new THREE.Group(); g.add(quad); g.userData.quad = quad;
  if (st === 2) { const c = buildCandles(t); g.add(c); g.userData.candles = c; }
  return g;
}

const M = new THREE.Matrix4(), Q = new THREE.Quaternion(), S = new THREE.Vector3(), P = new THREE.Vector3();
// p: 0 at first sight, 1 at the hit. angleDeg: the sim's clockwise-from-above angle. seconds: sim time, so a replay
// animates the same way every time.
export function updateTelegraph(g, p, angleDeg, seconds) {
  const u = g.userData.quad.material.uniforms; u.uP.value = p; u.uT.value = seconds;
  const yaw = -(angleDeg || 0) * Math.PI / 180;
  g.rotation.y = yaw;
  const c = g.userData.candles;
  if (c) {
    // each candle prints taller as the hit nears, staggered round the rim so the ring reads as a moving chart
    const pts = c.userData.pts;
    for (let i = 0; i < pts.length; i++) {
      const wob = 0.5 + 0.5 * Math.sin(i * 2.399 + seconds * 3.0);
      const h = 0.12 + p * (0.35 + 0.18 * wob);
      P.set(pts[i][0], 0, -pts[i][1]); S.set(1, h, 1); M.compose(P, Q, S); c.setMatrixAt(i, M);
    }
    c.instanceMatrix.needsUpdate = true;
  }
}

// What a telegraph draws, read back from the shader's own inputs: its shape, radius (tiles) and arc (radians, cones).
const SHAPE_NAME = Object.fromEntries(Object.entries(SHAPE).map(([k, v]) => [v, k]));
export function telegraphHitArea(g) {
  const u = g.userData.quad.material.uniforms, shape = SHAPE_NAME[u.uShape.value];
  return { shape, r: u.uR.value, arc: shape === 'cone' ? 2 * u.uHalf.value : null, style: u.uStyle.value };
}

export function disposeTelegraph(g) {
  const q = g.userData.quad; q.geometry.dispose(); q.material.dispose();
  if (g.userData.candles) g.userData.candles.dispose();
}
