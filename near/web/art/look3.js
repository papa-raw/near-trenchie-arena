/* look3.js — the three.js look: B1 three-band toon, RIG3 joints, the 14 house bodies (ES module).
 * import * as THREE comes from the page's import map ('three'). Units: 1 world unit = 1 tile, y up, local front = +z.
 * API: see LOOK3 at the bottom (makeTrenchie, makeItem, setupScene, RIG, kit). Items are drawn by items3.js,
 * faces by faces3.js; both register into LOOK3 when imported.
 */
import * as THREE from 'three';
const root = { ITEMS: null, LOOK3: null, MOTION3: null };
(function () {
  'use strict';

  var VERSION = 'look3 v0.5 (B3 v3.4: no facial hair) 2026-11-09';

  // ---- palette (tokens.json p01-p16; one source would be LOOK_TOKENS when the page loads it) ----
  var PAL = (root.LOOK_TOKENS && root.LOOK_TOKENS.palette) || {
    p01: '#3B2F25', p02: '#C9966A', p03: '#8A5F3C', p04: '#FFF8EA', p05: '#D8CDB8', p06: '#A3A9B2', p07: '#9FDCC5', p08: '#5FB79A',
    p09: '#A9D4F5', p10: '#6FA3D6', p11: '#D3BEF0', p12: '#F7CF6B', p13: '#D39E2A', p14: '#F6A796', p15: '#D97A6E', p16: '#FF3B30' };
  function C(c) { return (typeof c === 'string' && PAL[c]) ? PAL[c] : c; }
  function mix(a, b, k) { return '#' + new THREE.Color(C(a)).lerp(new THREE.Color(C(b)), k).getHexString(); }

  // ---- treatments (step-1 drafts) ----
  // Light intensities are three r155+ units
  // (a directional or ambient light of intensity PI returns the albedo), so a palette hex renders as itself on the lit side.
  // Key light (0.3, 4.2, 4.2): 45 deg elevation, ~30 deg left of the arena camera, so a toon band edge
  // never crosses a face. Satrenchi's face patch is also unlit.
  var KEY55 = [0.3, 4.2, 4.2];
  var TREATMENTS = {
    clay:  { id: 'clay',  name: 'A · Soft clay',
             blurb: 'Smooth shading with no bands, a very soft cast shadow. The gentlest; closest to option 3 with real light.',
             seg: 1, flat: false, toon: false,
             sun: { color: '#FFF3DE', intensity: 2.1, dir: KEY55 },
             hemi: { sky: '#E4EEF5', ground: '#C4B194', intensity: 1.75 },
             shadow: { type: 'vsm', radius: 12, samples: 16 }, contact: 0.38 },
    cel:   { id: 'cel',   name: 'B · Three-band toon',
             blurb: 'Light, mid and shade bands with crisp edges, and a sharper shadow. The most defined; the approved look.',
             seg: 1, flat: false, toon: true,
             sun: { color: '#FFF3DF', intensity: 2.4, dir: KEY55 },
             hemi: { sky: '#E4EEF5', ground: '#B9A88C', intensity: 1.6 },
             shadow: { type: 'pcf', radius: 4 }, contact: 0.38 },
    facet: { id: 'facet', name: 'C · Faceted low-poly',
             blurb: 'Fewer flat faces catch the light in planes; a lower sun and longer shadows. Closest to Bad North.',
             seg: 0, flat: true, toon: false,
             sun: { color: '#FFF1DC', intensity: 2.5, dir: [-0.62, 0.62, 0.48] },
             hemi: { sky: '#E4EEF5', ground: '#BCA98A', intensity: 1.6 },
             shadow: { type: 'pcf', radius: 3 }, contact: 0.34 }
  };
  var T = TREATMENTS.cel;
  function setTreatment(id) { T = TREATMENTS[id] || TREATMENTS.cel; return T; }

  // ---- materials ----
  var toonRamp = null;
  function ramp() {
    if (toonRamp) return toonRamp;
    var d = new Uint8Array([110, 190, 255, 255]);      // shade, mid, a wide light band
    toonRamp = new THREE.DataTexture(d, d.length, 1, THREE.RedFormat);
    toonRamp.minFilter = toonRamp.magFilter = THREE.NearestFilter; toonRamp.needsUpdate = true;
    return toonRamp;
  }
  function mat(c, o) {
    o = o || {};
    var color = new THREE.Color(C(c)), m;
    if (o.basic) m = new THREE.MeshBasicMaterial({ color: color });
    else if (T.toon) m = new THREE.MeshToonMaterial({ color: color, gradientMap: ramp() });
    else m = new THREE.MeshLambertMaterial({ color: color, flatShading: !!T.flat && !o.smooth });
    if (o.vc) m.vertexColors = true;
    if (o.opacity !== undefined) { m.transparent = true; m.opacity = o.opacity; m.depthWrite = false; }
    m.userData.base = color.clone();
    return m;
  }
  // mesh with shadows. No outlines or rims anywhere.
  function M(geo, c, o) {
    o = o || {};
    var m = new THREE.Mesh(geo, mat(c, o));
    m.castShadow = o.cast !== false; m.receiveShadow = o.receive !== false;
    return m;
  }
  // height shading, 0.78 at the feet to 1.0 at 71% of the height (vertex colours multiply the material colour)
  function heightShade(geo, h) {
    var p = geo.attributes.position, c = new Float32Array(p.count * 3);
    for (var i = 0; i < p.count; i++) { var k = Math.min(1, Math.max(0, p.getY(i) / (0.71 * h))), v = 0.78 + 0.22 * k; c[i * 3] = c[i * 3 + 1] = c[i * 3 + 2] = v; }
    geo.setAttribute('color', new THREE.BufferAttribute(c, 3)); return geo;
  }
  function sphere(r, o) {
    o = o || {};
    if (T.flat) return new THREE.IcosahedronGeometry(r, o.facetDetail !== undefined ? o.facetDetail : 1);
    return new THREE.SphereGeometry(r, o.w || 40, o.h || 26, 0, Math.PI * 2, o.thetaStart || 0, o.thetaLength || Math.PI);
  }

  // ---- the body: a gumdrop lathe (option 3's round pill, a little fuller at the base) ----
  var BODY = { R: 0.226, H: 0.66, lift: 0.06, n: 2.7, flare: 0.035, e: 2.1 };   // W/H = 0.69 at the widest
  function profile(nPts) {
    var pts = [];
    for (var i = 0; i <= nPts; i++) {
      var th = -Math.PI / 2 + Math.PI * i / nPts, c = Math.cos(th), s = Math.sin(th);
      var y = BODY.H / 2 + BODY.H / 2 * Math.sign(s) * Math.pow(Math.abs(s), 2 / BODY.e);
      var r = BODY.R * Math.pow(Math.abs(c), 2 / BODY.n) * (1 + BODY.flare * (1 - y / BODY.H));
      pts.push(new THREE.Vector2(Math.max(r, 1e-4), y));
    }
    pts[0].x = 1e-4; pts[pts.length - 1].x = 1e-4;
    return pts;
  }
  // body radius at a height above the body's own bottom (for placing the face, hat and hands on the surface)
  function radiusAt(y) {
    var p = profile(200);
    for (var i = 1; i < p.length; i++) if (p[i].y >= y) { var a = p[i - 1], b = p[i], k = (y - a.y) / Math.max(1e-6, b.y - a.y); return a.x + (b.x - a.x) * k; }
    return 0;
  }
  function bodyGeo(phiStart, phiLength) {
    var segs = T.flat ? 10 : 72;
    if (phiLength) segs = Math.round(segs * phiLength / (Math.PI * 2));   // phiStart must sit on a body facet edge
    return new THREE.LatheGeometry(profile(T.flat ? 8 : 36), segs, phiStart || 0, phiLength || Math.PI * 2);
  }
  // profile parameter v (LatheGeometry's uv.y) for a height above the body bottom
  function vAt(y) { var k = Math.max(-1, Math.min(1, 2 * y / BODY.H - 1)),   // clamped: asin of |s| > 1 is NaN and silently breaks canvas paths
     s = Math.sign(k) * Math.pow(Math.abs(k), BODY.e / 2); return (Math.asin(s) + Math.PI / 2) / Math.PI; }
  // a face decal that hugs the body: the front half of the body lathe, 0.6% larger, cut to an oval by alpha
  function faceDecalTexture(cy, hw, hh, rF, phiLength) {
    var N = 512, cv = document.createElement('canvas'); cv.width = cv.height = N;
    var g = cv.getContext('2d'), u0 = 0.5, v0 = vAt(cy);
    var du = hw / (phiLength * rF), dv = (vAt(cy + hh) - vAt(cy - hh)) / 2;
    g.fillStyle = '#fff'; g.beginPath();
    g.ellipse(u0 * N, (1 - v0) * N, du * N, dv * N, 0, 0, Math.PI * 2); g.fill();
    var t = new THREE.CanvasTexture(cv); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; return t;
  }
  function surfZ(y, x, out) { var r = radiusAt(y); return Math.sqrt(Math.max(0, r * r - x * x)) + (out || 0) + (T.flat ? 0.012 : 0); }

  // ---- RIG3 v1 ----
  var PIVOT_Y = BODY.lift + BODY.H * 0.42;                 // body centre of mass (lean/squash about here)
  var FACE = { y: BODY.H * 0.62, eyeDX: 0.080, eyeR: 0.027, maskW: 0.165, maskH: 0.125, maskDY: -0.016 };   // eyes 0.085 H, 0.12 H above centre, ~0.25 H apart // in body space (above the body bottom)
  var RIG = {
    version: 'RIG3 v1',
    units: '1 world unit = 1 tile; y up; sim (x,y) milli-tiles -> world (x/1000, 0, y/1000)',
    front: '+z (local); LOOK3.facingRotY(f) = PI/2 - f*PI/8 maps sim facing 0..15 (0 = east, clockwise) onto root.rotation.y',
    joints: {
      root: 'ground point under the body; render3 owns position + rotation.y (facing). Never scaled.',
      base: 'child of root at y=0: squash/stretch (scale.set(w,h,w), feet stay planted) and hop (position.y)',
      pivot: 'child of base at y=' + PIVOT_Y.toFixed(3) + ': lean (rotation.x fwd/back, rotation.z side), body sway, recoil offsets',
      body: 'the body mesh (child of pivot); owned by look3 — do not scale it',
      head: 'child of pivot at the face height: nod/tilt (rotation.x/z, small); carries face + mountHead',
      face: 'child of head: eyes, blush, mouth (setFace switches normal|hurt|ko|blink)',
      handR: 'weapon hand (character right = local -x); child of pivot; motion moves it freely',
      handL: 'off hand (local +x); child of pivot',
      mountWeapon: 'child of handR: held weapon, its grip at the origin, shaft along local +y',
      mountHead: 'child of head: hat/visor (worn head item)',
      mountBody: 'child of pivot: worn body item (vest, belt) wraps the body',
      mountTrinket: 'child of pivot, on the left hip: badge-size trinket',
      mountBack: 'RIG3 v1.1 (additive): child of pivot, on the back at half height: a legendary worn on the back',
      footL: 'child of base, +x', footR: 'child of base, -x',
      shadow: 'child of root: contact shadow disc (never scaled by motion)'
    },
    pivotY: PIVOT_Y,
    bodyR: BODY.R, bodyH: BODY.H, bodyLift: BODY.lift,
    facePatch: null   // filled below: an ellipse on the front of the body, in pivot space
  };
  (function () {   // the drawn face patch itself (the mask decal), so the rule and the art cannot drift apart
    var cy = FACE.y + FACE.maskDY, r = +radiusAt(cy).toFixed(3);
    RIG.facePatch = { center: [0, +(BODY.lift + cy - PIVOT_Y).toFixed(3), r], halfW: FACE.maskW, halfH: FACE.maskH, frontZ: r,
      note: 'pivot space; no item (held or worn) may enter the box x in [-halfW, halfW], y in [cy-halfH, cy+halfH], z > frontZ - 0.08, seen from any camera within 60 deg of the front' };
  })();

  function facingRotY(f) { return Math.PI / 2 - (f || 0) * Math.PI / 8; }

  // ---- contact shadow texture (soft disc under the feet) ----
  var contactTex = null;
  function contactTexture() {
    if (contactTex) return contactTex;
    var cv = document.createElement('canvas'); cv.width = cv.height = 128;
    var g = cv.getContext('2d'), gr = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    gr.addColorStop(0, 'rgba(59,47,37,1)'); gr.addColorStop(0.45, 'rgba(59,47,37,0.75)'); gr.addColorStop(1, 'rgba(59,47,37,0)');
    g.fillStyle = gr; g.fillRect(0, 0, 128, 128);
    contactTex = new THREE.CanvasTexture(cv); contactTex.colorSpace = THREE.SRGBColorSpace;
    return contactTex;
  }
  function contactShadow(r, opacity) {
    var m = new THREE.Mesh(new THREE.PlaneGeometry(r * 2, r * 2),
      new THREE.MeshBasicMaterial({ map: contactTexture(), transparent: true, opacity: opacity, depthWrite: false }));
    m.rotation.x = -Math.PI / 2; m.position.y = 0.004; m.renderOrder = 1; m.name = 'shadow';
    return m;
  }

  // ---- merged meshes ( budget: the face and the feet are one mesh each, coloured per vertex) ----
  // parts: [{geo, color, m: Matrix4}] -> one non-indexed BufferGeometry with position, normal, color
  var _v = null;
  function mergeColored(parts) {
    var pos = [], nor = [], col = [];
    parts.forEach(function (pt) {
      var g = pt.geo.index ? pt.geo.toNonIndexed() : pt.geo.clone();
      if (pt.m) g.applyMatrix4(pt.m);
      if (!g.attributes.normal) g.computeVertexNormals();
      var c = new THREE.Color(C(pt.color)), p = g.attributes.position, n = g.attributes.normal;
      for (var i = 0; i < p.count; i++) { pos.push(p.getX(i), p.getY(i), p.getZ(i)); nor.push(n.getX(i), n.getY(i), n.getZ(i)); col.push(c.r, c.g, c.b); }
      g.dispose();
    });
    var out = new THREE.BufferGeometry();
    out.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    out.setAttribute('normal', new THREE.Float32BufferAttribute(nor, 3));
    out.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
    return out;
  }
  function mtx(x, y, z, rx, ry, rz, sx, sy, sz) {
    return new THREE.Matrix4().compose(new THREE.Vector3(x || 0, y || 0, z || 0),
      new THREE.Quaternion().setFromEuler(new THREE.Euler(rx || 0, ry || 0, rz || 0)),
      new THREE.Vector3(sx === undefined ? 1 : sx, sy === undefined ? (sx === undefined ? 1 : sx) : sy, sz === undefined ? (sx === undefined ? 1 : sx) : sz));
  }
  // a lit mesh from coloured parts (vertex colours on a white material)
  function MC(parts, o) { var m = M(mergeColored(parts), '#FFFFFF', Object.assign({ vc: true }, o || {})); return m; }
  // an unlit mesh from coloured parts (the face)
  function BC(parts) { var m = new THREE.Mesh(mergeColored(parts), new THREE.MeshBasicMaterial({ vertexColors: true })); m.castShadow = false; m.receiveShadow = false; return m; }

  // ---- kits ----
  // Every trenchie: body = paletteIds[0]; an unlit cream face patch; p05 feet (option 3).
  function kitLook(kit) {
    var pid = kit.paletteIds || ['p07', 'p04'];
    var fc = (root.LOOK3 && root.LOOK3.FACES && root.LOOK3.FACES[kit.trenchieId]) || {};
    return { body: pid[0], face: fc.skin || 'p04', mask: !!fc.skin || pid[0] !== 'p04', feet: 'p05', fc: fc };
  }

  // ---- the trenchie ----
  function makeTrenchie(kit) {
    kit = kit || {};
    var L = kitLook(kit);
    var J = {};
    function node(name, parent, x, y, z) { var o = new THREE.Group(); o.name = name; o.position.set(x || 0, y || 0, z || 0); if (parent) parent.add(o); J[name] = o; return o; }

    var rootN = node('root'); rootN.userData.look3 = VERSION; rootN.userData.trenchieId = kit.trenchieId || null;
    var base = node('base', rootN);
    var pivot = node('pivot', base, 0, PIVOT_Y, 0);

    // body
    var body = M(heightShade(bodyGeo(), BODY.H), L.body, { vc: true }); body.name = 'body';
    body.position.y = BODY.lift - PIVOT_Y; pivot.add(body); J.body = body;

    // head node at face height (on the axis); face features sit on the surface
    var faceAbs = BODY.lift + FACE.y;
    var head = node('head', pivot, 0, faceAbs - PIVOT_Y, 0);
    var face = node('face', head);
    var rF = radiusAt(FACE.y);

    if (L.mask) {                                        // the pale face: unlit, so no light band can cross it
      var phiL = T.flat ? Math.PI * 2 * 6 / 10 : Math.PI;
      var FM = L.fc || {};   // a face may widen its patch (Mert v3.3: the face and the bald scalp read as one head)
      var mm = mat(L.face, { basic: true }); mm.map = faceDecalTexture(FACE.y + FACE.maskDY + (FM.maskDY || 0), FM.maskW || FACE.maskW, FM.maskH || FACE.maskH, rF, phiL); mm.alphaTest = 0.5;
      var mk = new THREE.Mesh(bodyGeo(-phiL / 2, phiL), mm); mk.receiveShadow = false; mk.castShadow = false;
      mk.scale.set(1.006, 1, 1.006); mk.position.y = -FACE.y; mk.name = 'mask';
      face.add(mk);
    }
    // eyes + catch-lights: one unlit mesh (blink = scale.y)
    var FC = L.fc || {}, eyeCol = FC.eyes === 'laser' ? '#E8322A' : FC.eyes === 'glow' ? '#F7CF6B' : 'p01';
    var eyeParts = [], xParts = [];
    [-1, 1].forEach(function (s) {
      var x = s * FACE.eyeDX, z = surfZ(FACE.y, x, 0), ry = Math.asin(x / rF);
      eyeParts.push({ geo: new THREE.SphereGeometry(FACE.eyeR * (FC.eyes === 'glow' ? 0.6 : 1), 16, 12), color: eyeCol, m: mtx(x, 0, z, 0, ry, 0, 1, 1.12, 0.38) });
      var cl = new THREE.Vector3(-0.36 * FACE.eyeR, 0.42 * FACE.eyeR * 1.12, 0.9 * FACE.eyeR * 0.38 + 0.002).applyAxisAngle(new THREE.Vector3(0, 1, 0), ry);
      eyeParts.push({ geo: new THREE.SphereGeometry(0.0075, 10, 8), color: 'p04', m: mtx(x + cl.x, cl.y, z + cl.z) });
      [-1, 1].forEach(function (d) { xParts.push({ geo: new THREE.BoxGeometry(0.055, 0.013, 0.008), color: 'p01', m: mtx(x, 0, surfZ(FACE.y, x, 0.003), 0, ry, d * Math.PI / 4) }); });
    });
    var eyes = BC(eyeParts); eyes.name = 'eyes'; face.add(eyes); J.eyes = eyes;
    faceExtras(face, FC, rF, L);
    var xeyes = BC(xParts); xeyes.name = 'xeyes'; xeyes.visible = false; face.add(xeyes); J.xeyes = xeyes;
    // mouth + blush: one unlit mesh
    var mParts = (FC.mouth && FC.mouth !== 'smile') ? [] : [{ geo: new THREE.TorusGeometry(0.019, 0.0055, 6, 14, Math.PI), color: 'p01', m: mtx(0, -0.03, surfZ(FACE.y - 0.03, 0, 0.001), 0, 0, Math.PI, 1, 1, 0.5) }];
    if (FC.eyes !== 'glow') [-1, 1].forEach(function (s) {
      var bx = s * (FACE.eyeDX + 0.036), by = -0.04;
      mParts.push({ geo: new THREE.CircleGeometry(0.022, 20), color: 'p14', m: mtx(bx, by, surfZ(FACE.y + by, bx, 0.002), 0, Math.asin(bx / radiusAt(FACE.y + by)), 0, 1.3, 0.8, 1) });
    });
    var mouth = mParts.length ? BC(mParts) : new THREE.Group(); mouth.name = 'mouth'; face.add(mouth); J.mouth = mouth;

    // hands (body-coloured, option 3), tucked half into the outline
    var hy = BODY.lift + BODY.H * 0.30 - PIVOT_Y, hr = radiusAt(BODY.H * 0.30);
    var handR = node('handR', pivot, -(hr - 0.004), hy, 0.075);
    var handL = node('handL', pivot, (hr - 0.022), hy - 0.012, 0.06);
    [handR, handL].forEach(function (h) { var m = M(sphere(0.054, { w: 28, h: 18, facetDetail: 1 }), L.body); m.name = 'hand'; h.add(m); });
    node('mountWeapon', handR);
    node('mountHead', head, 0, 0, 0);
    node('mountBody', pivot, 0, BODY.lift - PIVOT_Y, 0);     // body-space origin (the body's bottom)
    node('mountBack', pivot, 0, BODY.lift + BODY.H * 0.5 - PIVOT_Y, -radiusAt(BODY.H * 0.5));   // RIG3 v1.1 (additive): the back
    var ty = BODY.H * 0.17, tr = radiusAt(ty);
    var mT = node('mountTrinket', pivot, Math.sin(0.95) * tr, BODY.lift + ty - PIVOT_Y, Math.cos(0.95) * tr); mT.rotation.y = 0.95;

    // feet: one mesh, planted on base (RIG3 keeps footL/footR as nodes for motion; the mesh rides on footL's twin)
    var footL = node('footL', base, 0.098, 0.042, 0.03), footR = node('footR', base, -0.098, 0.042, 0.03);
    [footL, footR].forEach(function (f) { var m = M(sphere(0.074, { w: 28, h: 18, facetDetail: 1 }), L.feet); m.scale.set(1, 0.6, 1.18); m.name = 'foot'; f.add(m); });

    // contact shadow
    var sh = contactShadow(BODY.R * 2 * 1.4 / 2, T.contact); sh.scale.y = 0.8; rootN.add(sh); J.shadow = sh;   //

    var api = {
      object3d: rootN, joints: J, kit: kit,
      setItems: function (items) { setItemsOn(J, items || {}, L); },
      setFace: function (mode) {
        eyes.visible = mode !== 'ko' && mode !== 'hurt'; xeyes.visible = !eyes.visible;
        eyes.scale.y = mode === 'blink' ? 0.15 : 1;
      },
      setPose: function (p) {   // the default idle; a motion module replaces this (RIG3 joints)
        p = p || {};
        if (root.MOTION3 && root.MOTION3.apply) return root.MOTION3.apply(api, p);
        var t = p.t || 0, b = Math.sin(t * 2.4);
        base.scale.set(1 + 0.015 * b, 1 - 0.02 * b, 1 + 0.015 * b);
        if (p.facing !== undefined) rootN.rotation.y = facingRotY(p.facing);
      },
      flash: function () {
        rootN.traverse(function (o) { if (o.isMesh && o.material && o.material.emissive) { o.material.emissive.setRGB(1, 1, 1); o.material.emissiveIntensity = 0.6; } });
        setTimeout(function () { rootN.traverse(function (o) { if (o.isMesh && o.material && o.material.emissive) o.material.emissive.setRGB(0, 0, 0); }); }, 90);
      },
      meshCount: function () { var n = 0; rootN.traverseVisible(function (o) { if (o.isMesh && o.name !== 'shadow') n++; }); return n; },
      dispose: function () { rootN.traverse(function (o) { if (o.isMesh) { o.geometry.dispose(); o.material.dispose(); } }); }
    };
    if (kit.kit) api.setItems(kit.kit);
    return api;
  }

  // ---- caricature face parts (faces3.js configs): glasses, brows, mouths, hair, ears. Unlit features, lit hair. ----
  function faceExtras(face, FC, rF, Lk) {
    if (!FC || !Object.keys(FC).length) return;
    var P = [], H2 = [], ex = FACE.eyeDX;
    function at(x, dy, out) { return surfZ(FACE.y + dy, x, out || 0.002); }
    function ry(x) { return Math.asin(Math.max(-1, Math.min(1, x / rF))); }
    // mouths
    var my = -0.032;
    if (FC.mouth === 'grin' || FC.mouth === 'beam') P.push({ geo: new THREE.TorusGeometry(FC.mouth === 'beam' ? 0.034 : 0.026, 0.006, 6, 18, Math.PI), color: 'p01', m: mtx(0, my + 0.004, at(0, my), 0, 0, Math.PI, 1, 0.8, 0.5) });
    if (FC.mouth === 'beam') P.push({ geo: new THREE.CircleGeometry(0.03, 20, Math.PI, Math.PI), color: '#FFFFFF', m: mtx(0, my + 0.003, at(0, my, 0.003), 0, 0, 0, 1, 0.55, 1) });
    if (FC.mouth === 'laugh') { P.push({ geo: new THREE.CircleGeometry(0.03, 20, Math.PI, Math.PI), color: 'p01', m: mtx(0, my + 0.006, at(0, my, 0.003), 0, 0, 0, 1, 1, 1) });
                                P.push({ geo: new THREE.CircleGeometry(0.014, 14, Math.PI, Math.PI), color: 'p15', m: mtx(0, my - 0.012, at(0, my - 0.012, 0.004), 0, 0, 0, 1, 0.8, 1) }); }
    if (FC.mouth === 'flat' || FC.mouth === 'calm') P.push({ geo: new THREE.BoxGeometry(FC.mouth === 'calm' ? 0.026 : 0.032, 0.006, 0.004), color: 'p01', m: mtx(0, my, at(0, my)) });
    if (FC.mouth === 'smirk') P.push({ geo: new THREE.TorusGeometry(0.02, 0.0055, 6, 14, Math.PI * 0.6), color: 'p01', m: mtx(0.006, my, at(0, my), 0, 0, Math.PI * 1.15, 1, 1, 0.5) });
    if (FC.mouth === 'teeth') {      // a clean white grin with a thin dark outline (v3.3)
      P.push({ geo: new THREE.CircleGeometry(0.033, 24, Math.PI, Math.PI), color: 'p01', m: mtx(0, my + 0.006, at(0, my, 0.0025), 0, 0, 0, 1, 0.78, 1) });
      P.push({ geo: new THREE.CircleGeometry(0.027, 24, Math.PI, Math.PI), color: '#FFFFFF', m: mtx(0, my + 0.0035, at(0, my, 0.0035), 0, 0, 0, 1, 0.72, 1) });
    }
    if (FC.mouth === 'talk') P.push({ geo: new THREE.CircleGeometry(0.014, 16), color: 'p01', m: mtx(0, my, at(0, my), 0, 0, 0, 1.3, 0.8, 1) });
    // eyes: the censor bar, laser streaks
    if (FC.eyes === 'bar') P.push({ geo: new THREE.BoxGeometry(ex * 2 + 0.07, 0.036, 0.008), color: 'p01', m: mtx(0, 0.002, at(0, 0, 0.012)) });
    // laser eyes: red eyes only at rest; the beam belongs to the Laser Eyes signature when it fires
    // brows
    if (FC.brows) [-1, 1].forEach(function (s) { var raised = FC.brows === 'raised' && s > 0; P.push({ geo: new THREE.BoxGeometry(0.034, 0.008, 0.004), color: 'p01', m: mtx(s * ex, raised ? 0.05 : 0.04, at(s * ex, 0.04, 0.003), 0, ry(s * ex), raised ? -0.35 * s : 0.1 * s) }); });
    // glasses: square rings round each eye (never over the pupils), a bridge
    // glasses: FLAT on one plane in front of the face (not bent round the body), mirror-identical rims centred
    // on the eyes and just framing them, a straight bridge at eye height, no temple arms, one dark colour, no fill
    if (FC.glasses) {
      var square = FC.glasses === 'square', gz = surfZ(FACE.y, 0.03, 0.012), ri = 0.036, ro = 0.0415;
      function rimGeo() {
        if (!square) return new THREE.RingGeometry(ri, ro, 40);
        function rr(w, h, rad) { var sh = new THREE.Shape(), x = -w / 2, y = -h / 2;
          sh.moveTo(x + rad, y); sh.lineTo(x + w - rad, y); sh.quadraticCurveTo(x + w, y, x + w, y + rad); sh.lineTo(x + w, y + h - rad); sh.quadraticCurveTo(x + w, y + h, x + w - rad, y + h);
          sh.lineTo(x + rad, y + h); sh.quadraticCurveTo(x, y + h, x, y + h - rad); sh.lineTo(x, y + rad); sh.quadraticCurveTo(x, y, x + rad, y); return sh; }
        var outer = rr(0.088, 0.07, 0.016), inner = rr(0.077, 0.059, 0.012); outer.holes.push(new THREE.Path(inner.getPoints(24)));
        return new THREE.ShapeGeometry(outer, 24);
      }
      [-1, 1].forEach(function (s) { P.push({ geo: rimGeo(), color: 'p01', m: mtx(s * ex, 0.0, gz) }); });
      var gap = 2 * ex - 2 * (square ? 0.044 : ro) + 0.006;
      P.push({ geo: new THREE.PlaneGeometry(gap, 0.0055), color: 'p01', m: mtx(0, 0.006, gz) });
    }
    if (P.length) { var fx = BC(P); fx.name = 'faceFx'; face.add(fx); }
    // hair (lit, on the crown): bald gets a skin dome; caps and hair styles change the outline
    var hc = FC.hairColor || '#3B2F25', crownY = 0.075, top = BODY.H - FACE.y;
    function crownR2(dy) { return radiusAt(FACE.y + dy); }
    if (FC.hair === 'bald') H2.push({ geo: new THREE.SphereGeometry(crownR2(crownY) + 0.004, 40, 16, 0, Math.PI * 2, 0, Math.PI / 2), color: FC.skin, m: mtx(0, crownY, 0, 0, 0, 0, 1, (top - crownY) / crownR2(crownY) + 0.02, 1) });
    if (FC.hair === 'short' || FC.hair === 'receding' || FC.hair === 'swept' || FC.hair === 'tousled' || FC.hair === 'quiff' || FC.hair === 'pompadour' || FC.hair === 'spiky') {
      var r0 = crownR2(crownY) + 0.008;
      H2.push({ geo: new THREE.SphereGeometry(r0, 40, 16, 0, Math.PI * 2, 0, Math.PI / 2), color: hc, m: mtx(0, crownY + 0.02 + (FC.hair === 'receding' ? 0.025 : 0), -0.01, 0, 0, 0, 1, (top - crownY - 0.02) / r0 + 0.04, 1) });
      if (FC.hair === 'quiff') { H2.push({ geo: new THREE.SphereGeometry(0.08, 24, 16), color: hc, m: mtx(0, top + 0.03, 0.08, -0.6, 0, 0, 1.2, 0.8, 1) });
        H2.push({ geo: new THREE.ConeGeometry(0.06, 0.16, 16), color: hc, m: mtx(0, top + 0.1, 0.1, 0.75, 0, 0) }); }   // a pointed quiff: the outline
      if (FC.hair === 'pompadour') H2.push({ geo: new THREE.SphereGeometry(0.12, 28, 18), color: hc, m: mtx(0, top + 0.07, 0.06, -0.45, 0, 0, 1.4, 1.15, 1.1) });   // tall
      if (FC.hair === 'swept') H2.push({ geo: new THREE.SphereGeometry(0.1, 28, 18), color: hc, m: mtx(0, top + 0.01, -0.04, 0.5, 0, 0, 1.25, 0.55, 1.2) });
      if (FC.hair === 'tousled') for (var t = 0; t < 9; t++) { var a = t / 9 * Math.PI * 2; H2.push({ geo: new THREE.SphereGeometry(0.06, 14, 10), color: hc, m: mtx(Math.cos(a) * 0.12, top + (t % 2) * 0.04, Math.sin(a) * 0.11) }); }
      if (FC.hair === 'spiky') for (var k = -2; k <= 2; k++) H2.push({ geo: new THREE.ConeGeometry(0.04, 0.17 - Math.abs(k) * 0.02, 10), color: hc, m: mtx(k * 0.055, top + 0.04, 0.06 - Math.abs(k) * 0.01, 0.45, 0, -k * 0.28) });
    }
    if (FC.hair === 'bob') { var rb = crownR2(crownY) + 0.012;   // a cap over the crown and two side curtains to the jaw, face open
      H2.push({ geo: new THREE.SphereGeometry(rb, 40, 16, 0, Math.PI * 2, 0, Math.PI / 2), color: hc, m: mtx(0, crownY - 0.01, -0.005, 0, 0, 0, 1.04, (top - crownY + 0.03) / rb, 1.04) });
      [-1, 1].forEach(function (s) { H2.push({ geo: new THREE.SphereGeometry(0.085, 24, 16), color: hc, m: mtx(s * (rF + 0.03), -0.03, -0.03, 0, 0, s * 0.42, 0.85, 1.55, 1.15) }); }); }   // flared bob
    if (FC.hair === 'cap-black') { var rc = crownR2(crownY) + 0.012;
      H2.push({ geo: new THREE.SphereGeometry(rc, 40, 16, 0, Math.PI * 2, 0, Math.PI / 2), color: '#2E2A27', m: mtx(0, crownY, 0, 0, 0, 0, 1, 0.9, 1) });
      H2.push({ geo: new THREE.CylinderGeometry(rc + 0.09, rc + 0.09, 0.014, 32, 1, false, -Math.PI * 0.3, Math.PI * 0.6), color: '#2E2A27', m: mtx(0, crownY + 0.016, 0.05, -0.15, 0, 0, 1, 1, 0.95) }); }   // the peak sticks out, lifted and shortened so the eyes and mouth show (B3 v3.4)
    // Mert's gag: small 'blah' speech bubbles drifting round the head, camera-facing sprites, off the face
    if (FC.gag === 'blah') ['blah', 'blah', '\u2026'].forEach(function (txt, i) {
      var cv = document.createElement('canvas'); cv.width = 128; cv.height = 80; var g = cv.getContext('2d');
      g.fillStyle = '#FFF8EA'; g.strokeStyle = '#3B2F25'; g.lineWidth = 5;
      g.beginPath(); g.roundRect(6, 6, 116, 52, 22); g.moveTo(34, 56); g.lineTo(26, 74); g.lineTo(52, 56); g.fill(); g.stroke();
      g.fillStyle = '#3B2F25'; g.font = 'bold 30px ui-rounded, system-ui, sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle'; g.fillText(txt, 64, 33);
      var tex = new THREE.CanvasTexture(cv); tex.colorSpace = THREE.SRGBColorSpace;
      var sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false })); sp.scale.set(0.2, 0.125, 1);
      var a = [2.3, 0.8, 3.6][i]; sp.position.set(Math.cos(a) * 0.3, top + 0.04 + i * 0.07, Math.sin(a) * 0.12 - 0.05); sp.name = 'gag'; face.parent.add(sp);
    });
    if (FC.hair === 'bald-skin') {   // the scalp in the face's own (unlit) skin, one head with the face, and one soft shine (v3.3)
      var rs = crownR2(crownY) + 0.003, sk = BC([
        { geo: new THREE.SphereGeometry(rs, 40, 16, 0, Math.PI * 2, 0, Math.PI / 2), color: FC.skin, m: mtx(0, crownY - 0.012, 0, 0, 0, 0, 1.01, (top - crownY + 0.034) / rs, 1.01) },
        { geo: new THREE.CircleGeometry(0.03, 18), color: '#FBEBDD', m: (function () { var hy = (top - crownY + 0.034), n = new THREE.Vector3(-0.35, 0.8, 0.48).normalize(), p = new THREE.Vector3(n.x * rs * 1.01, crownY - 0.012 + n.y * hy + 0.004, n.z * rs * 1.01 + 0.004);
          return new THREE.Matrix4().compose(p, new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 0, 1), n), new THREE.Vector3(1.4, 0.8, 1)); })() }]);
      sk.name = 'scalp'; face.parent.add(sk);
    }
    if (FC.ears) [-1, 1].forEach(function (s) { var x = s * (rF + 0.012); H2.push({ geo: new THREE.SphereGeometry(0.035, 16, 12), color: Lk.body, m: mtx(x, 0.0, -0.01, 0, 0, 0, 0.55, 1, 0.9) }); });
    if (H2.length) { var hair = MC(H2); hair.name = 'hair'; face.parent.add(hair); hair.material.side = THREE.DoubleSide; }
  }

  function clearMount(m) { while (m.children.length) m.remove(m.children[0]); }
  function setItemsOn(J, items, L) {
    ['mountWeapon', 'mountHead', 'mountBody', 'mountTrinket', 'mountBack'].forEach(function (k) { clearMount(J[k]); });
    var map = { head: 'mountHead', weapon: 'mountWeapon', body: 'mountBody', trinket: 'mountTrinket' };
    Object.keys(map).forEach(function (slot) {
      if (!items[slot]) return;
      // a legendary with a back piece is worn on the back (its silhouette names the trenchie); otherwise the slot's mount
      if (slot === 'trinket' && (LOOK3_OPTS.backPieces || (L && L.fc && L.fc.back)) && ITEM_DRAW['back:' + items[slot]]) { var b = ITEM_DRAW['back:' + items[slot]]({ slot: slot }); b.userData.itemId = items[slot]; J.mountBack.add(b); return; }
      var g = makeItem(items[slot], 'worn', { slot: slot, wearer: L });
      // a drawing knows where it is worn (hats on the head, garments on the body), whatever slot the kit filed it under
      var nat = g && g.userData.natural, mount = nat === 'head' ? 'mountHead' : nat === 'body' ? 'mountBody' : map[slot];
      if (g) J[mount].add(g);
    });
  }

  // ---- items: drawn by look3/items3.js through LOOK3.registerItem(id, fn). Unknown ids get a per-slot fallback. ----
  var ITEM_DRAW = {}, FALLBACK = {}, LOOK3_OPTS = { backPieces: false }; // back legendaries off (badge, or shown when used)
  function registerItem(id, fn) { ITEM_DRAW[id] = fn; }
  function registerFallback(slot, fn) { FALLBACK[slot] = fn; }
  function itemRecord(id) { var I = root.ITEMS || (root.ITEMS_API && root.ITEMS_API.ITEMS) || {}; return I[id] || null; }
  function makeItem(itemId, mode, ctx) {
    ctx = ctx || {};
    var rec = itemRecord(itemId), f = ITEM_DRAW[itemId], slot = ctx.slot || (rec && rec.slot);
    if (!f && slot && FALLBACK[slot]) f = function (c) { return FALLBACK[slot](rec || { id: itemId, slot: slot, tier: 'common' }, c); };
    if (!f) return null;
    var g = f(Object.assign({ rec: rec, mode: mode || 'worn' }, ctx)); g.name = g.name || 'item:' + itemId;
    g.userData.itemId = itemId; g.userData.mode = mode || 'worn';
    return g;
  }

  // ---- step-1 ground patch: a small diorama of sand with a grass edge ----
  function makeGroundPatch() {
    var g = new THREE.Group(); g.name = 'groundPatch';
    var sand = mix(mix('p04', 'p12', 0.30), 'p02', 0.10), side = mix('p02', 'p04', 0.30);
    var segs = T.flat ? 9 : 48;
    var top = M(new THREE.CylinderGeometry(0.9, 0.93, 0.10, segs), sand, { cast: false });
    top.position.y = -0.05; g.add(top);
    var cliff = M(new THREE.CylinderGeometry(0.93, 0.82, 0.22, segs), side, { cast: false });
    cliff.position.y = -0.21; g.add(cliff);
    // grass tufts and pebbles (sparse: empty space around the fighter)
    var tufts = [[-0.66, 0.30], [0.62, -0.46]];
    tufts.forEach(function (t, i) {
      for (var k = 0; k < 3; k++) {
        var c = M(new THREE.ConeGeometry(0.03, 0.13 - k * 0.02, T.flat ? 4 : 6), k ? 'p08' : 'p07');
        c.position.set(t[0] + (k - 1) * 0.035, 0.05, t[1] + (k % 2) * 0.02); c.rotation.z = (k - 1) * 0.25; g.add(c);
      }
    });
    [[0.52, 0.5, 0.045], [-0.5, -0.42, 0.06]].forEach(function (s) {
      var r = M(new THREE.IcosahedronGeometry(s[2], T.flat ? 0 : 1), 'p06');
      r.scale.y = 0.6; r.position.set(s[0], s[2] * 0.3, s[1]); g.add(r);
    });
    return g;
  }

  // ---- scene setup: one sun + sky fill, shadows ----
  function setupScene(scene, renderer, opts) {
    opts = opts || {}; var ext = opts.extent || 1.6;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.NoToneMapping;            // keep the palette true
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = T.shadow.type === 'vsm' ? THREE.VSMShadowMap : THREE.PCFShadowMap;
    var hemi = T.ambient ? new THREE.AmbientLight(new THREE.Color(T.ambient.color), T.ambient.intensity)
                         : new THREE.HemisphereLight(new THREE.Color(T.hemi.sky), new THREE.Color(T.hemi.ground), T.hemi.intensity);
    scene.add(hemi);
    var key = new THREE.DirectionalLight(new THREE.Color(T.sun.color), T.sun.intensity);
    var d = new THREE.Vector3().fromArray(T.sun.dir).normalize();
    key.position.copy(d).multiplyScalar(6 + ext); key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048); key.shadow.radius = T.shadow.radius; if (T.shadow.samples) key.shadow.blurSamples = T.shadow.samples;
    key.shadow.bias = T.shadow.type === 'vsm' ? -0.0006 : -0.0008; key.shadow.normalBias = T.flat ? 0.03 : 0.02;
    var sc = key.shadow.camera; sc.left = -ext; sc.right = ext; sc.top = ext; sc.bottom = -ext; sc.near = 0.5; sc.far = 14 + ext * 2;
    scene.add(key); scene.add(key.target);
    return { key: key, fill: hemi, dir: d,
      update: function (center) { key.target.position.copy(center); key.position.copy(center).addScaledVector(d, 6 + ext); } };
  }

  root.LOOK3 = { VERSION: VERSION, setItemRecords: function (m) { root.ITEMS = m; }, setMotion: function (m) { root.MOTION3 = m; }, PAL: PAL, TREATMENTS: TREATMENTS, RIG: RIG, setTreatment: setTreatment,
    treatment: function () { return T; }, setupScene: setupScene, makeTrenchie: makeTrenchie, makeItem: makeItem,
    makeGroundPatch: makeGroundPatch, facingRotY: facingRotY, radiusAt: radiusAt, mix: mix, C: C,
    registerItem: registerItem, registerFallback: registerFallback, itemRecord: itemRecord,
    // drawing kit for items3.js (and env3.js): the same materials, light response and budgets as the bodies
    kit: { M: M, MC: MC, BC: BC, mat: mat, mtx: mtx, mergeColored: mergeColored, heightShade: heightShade, bodyGeo: bodyGeo,
           radiusAt: radiusAt, vAt: vAt, surfZ: surfZ, FACE: FACE, BODY: BODY, PIVOT_Y: PIVOT_Y, T: function () { return T; } } };
})();
export const LOOK3 = root.LOOK3;
export default LOOK3;
