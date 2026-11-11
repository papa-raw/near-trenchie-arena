/* parts-s3.js: the player skin parts (face, hair, hat, body shape), drawn on the approved body from near/web/art.
 * Classic script; bridge.js loads it after the art modules (window.THREE and window.LOOK3 must exist).
 *
 * The anti-likeness rule, by design: a player face is built from a vocabulary DISJOINT from the house caricature parts.
 *   House-only (never offered): specs (round, square), one raised brow,
 *   level thin brows, laser and glow eyes, the hood, bald scalps, the house hair styles, every named hat and signature piece.
 *   Player parts: their own eyes, brows, mouths and hair, with hair in palette colours. No trenchie has facial hair (Pat 2026-11-06).
 *   Shared with the house: only the species base (dot eyes, the small smile), the face tones and the body colours.
 * S3.check() measures this against LOOK3.FACES so the claim on the board is computed, not written.
 */
(function (root) {
  'use strict';
  var THREE = root.THREE, L = root.LOOK3, K = L.kit, FACE = K.FACE, BODY = K.BODY;
  var MC = K.MC, BC = K.BC, M = K.M, mtx = K.mtx;
  var TOP = BODY.H - FACE.y, CROWN = 0.082;
  var rF = K.radiusAt(FACE.y);   // re-read per trenchie in make(): the shape changes it
  function at(x, dy, out) { return K.surfZ(FACE.y + dy, x, out || 0.002); }
  function ry(x) { return Math.asin(Math.max(-1, Math.min(1, x / rF))); }
  function crownR(dy) { return K.radiusAt(FACE.y + dy); }

  // ---------------- the catalogue: every player part, with its label ----------------
  var TONES = { light: '#FBE7D6', warm: '#F3D2B3', tan: '#E4B993', deep: '#C79870' };
  // six body shapes (prd.md:585 "6 body presets"): the B1 gumdrop lathe with its width, squareness, top and base flare
  // changed, the height kept, so the face, hats and hands still sit on it. Cosmetic only: every shape fights the same (B8).
  var SHAPES = {
    // v0.5 (a review found Gumdrop/Acorn and Pear/Pebble read as twins): pushed apart in width, taper and height. sy scales
    // the whole body from the ground (the face and kit ride along), so a shape also changes how tall it stands.
    gumdrop:  { R: 0.226, n: 2.7, flare: 0.035, e: 2.1, sy: 1 },      // B1's approved body
    bean:     { R: 0.172, n: 2.4, flare: 0.0,   e: 2.4, sy: 1.12 },   // tall and slim
    dumpling: { R: 0.29,  n: 3.0, flare: 0.1,   e: 1.9, sy: 0.84 },   // short and wide
    pear:     { R: 0.188, n: 2.4, flare: 0.58,  e: 2.1, sy: 1 },      // the weight at the bottom
    pebble:   { R: 0.232, n: 5.0, flare: 0.0,   e: 3.0, sy: 0.94 },   // a soft box
    acorn:    { R: 0.252, n: 2.6, flare: -0.4,  e: 2.6, sy: 1.04 }    // the weight at the top
  };
  var PART = {
    shape:   { label: 'Body shape', opts: { gumdrop: 'Gumdrop', bean: 'Bean', dumpling: 'Dumpling', pear: 'Pear', pebble: 'Pebble', acorn: 'Acorn' } },
    body:    { label: 'Body colour', opts: { p07: 'Mint', p09: 'Sky', p11: 'Lilac', p12: 'Butter', p14: 'Peach', p08: 'Fern', p10: 'Harbour', p15: 'Coral',
                                             p02: 'Driftwood', p03: 'Cocoa', p05: 'Sand', p06: 'Slate', p13: 'Honey', p01: 'Ink', p04: 'Cream', p16: 'Alarm' } },
    tone:    { label: 'Face tone', opts: { light: 'Shell', warm: 'Dune', tan: 'Toast', deep: 'Cocoa' } },
    eyes:    { label: 'Eyes', opts: { dot: 'Dots', sleepy: 'Sleepy', sparkle: 'Sparkle', happy: 'Happy', wink: 'Wink', keen: 'Keen' } },
    brows:   { label: 'Brows', opts: { none: 'None', arch: 'Arched', worried: 'Worried', cross: 'Cross', dash: 'Dashes' } },
    mouth:   { label: 'Mouth', opts: { smile: 'Smile', o: 'Oh', cat: 'Kitty', gap: 'Buck tooth', blep: 'Blep', wave: 'Wobbly' } },
    hair:    { label: 'Hair', opts: { none: 'Smooth', sprout: 'Sprout', knot: 'Top knot', puffs: 'Cloud', cowlick: 'Cowlick', fin: 'Fin', buns: 'Twin buns' } },
    hairCol: { label: 'Hair colour', opts: { p01: 'Ink', p03: 'Cocoa', p12: 'Butter', p11: 'Lilac', p14: 'Peach', p07: 'Mint', p10: 'Harbour', p15: 'Coral' } },
    hat:     { label: 'Hat', opts: { 'st-cap': 'Sun Cap', hide: 'Hat off', 'c-head-maxi': 'Bucket Hat', 'c-head-degen': 'Party Cone',
                                     'c-head-speedrunner': 'Sweatband', 'c-head-builder': 'Hard Hat' } }
  };
  // the three option sets: how many choices per slot (the drafts)
  var SETS = {
    a: { name: 'Pocket', blurb: 'Three or four choices per face slot. Every choice is a big, different read at 56 px; a newcomer is done in under a minute.',
         shape: ['gumdrop', 'bean', 'dumpling'], body: ['p07', 'p09', 'p11', 'p12', 'p14', 'p08', 'p10', 'p15'], tone: ['light', 'warm', 'tan', 'deep'],
         eyes: ['dot', 'sleepy', 'sparkle'], brows: ['none', 'arch', 'worried'], mouth: ['smile', 'o', 'cat', 'gap'],
         hair: ['none', 'sprout', 'knot', 'puffs'], hairCol: ['p01', 'p03', 'p12', 'p11'], hat: ['st-cap', 'hide'] },
    b: { name: 'Locker', blurb: 'The spec\u2019s full menu: 6 shapes \u00d7 the 16 palette colours (prd.md:585), and every player face part. More room to be yourself; the 56 px panel below shows which face parts survive at game size.',
         shape: ['gumdrop', 'bean', 'dumpling', 'pear', 'pebble', 'acorn'],
         body: ['p07', 'p09', 'p11', 'p12', 'p14', 'p08', 'p10', 'p15', 'p02', 'p03', 'p05', 'p06', 'p13', 'p01', 'p04', 'p16'], tone: ['light', 'warm', 'tan', 'deep'],
         eyes: ['dot', 'sleepy', 'sparkle', 'happy', 'wink', 'keen'], brows: ['none', 'arch', 'worried', 'cross', 'dash'],
         mouth: ['smile', 'o', 'cat', 'gap', 'blep', 'wave'],
         hair: ['none', 'sprout', 'knot', 'puffs', 'cowlick', 'fin', 'buns'], hairCol: ['p01', 'p03', 'p12', 'p11', 'p14', 'p07', 'p10', 'p15'], hat: ['st-cap', 'hide'] },
    c: { name: 'Hat rack', blurb: 'Set b, and the starting hat is picked from the five commons (or off). Needs your yes on a contract change: the starter mint fixes 4 item hashes today (B106).',
         shape: null, body: null, tone: null, eyes: null, brows: null, mouth: null, hair: null, hairCol: null,
         hat: ['st-cap', 'c-head-maxi', 'c-head-degen', 'c-head-speedrunner', 'c-head-builder', 'hide'] }
  };
  ['shape', 'body', 'tone', 'eyes', 'brows', 'mouth', 'hair', 'hairCol'].forEach(function (k) { SETS.c[k] = SETS.b[k]; });
  var SLOTS = ['shape', 'body', 'tone', 'eyes', 'brows', 'mouth', 'hair', 'hairCol', 'hat'];
  var DEFAULT = { shape: 'gumdrop', body: 'p07', tone: 'warm', eyes: 'dot', brows: 'none', mouth: 'smile', hair: 'none', hairCol: 'p03', hat: 'st-cap' };

  // ---------------- the starter kit, drawn for this board (no drawing existed: st-cap fell back to the Bucket Hat) ----------------
  // Sun Cap: option 3's cap, a peach dome, a coral bill and button
  L.registerItem('st-cap', function () {
    var g = new THREE.Group(); g.name = 'item:st-cap'; g.rotation.x = -0.1; g.userData.natural = 'head';
    var r = crownR(CROWN) + 0.012;
    // the dome follows the wearer's own profile (6 shapes), 0.012 proud of it, closed at the top
    var pts = []; for (var i = 0; i <= 14; i++) { var dy = CROWN + (TOP - 0.012 - CROWN) * i / 14; pts.push(new THREE.Vector2(crownR(dy) + 0.012, dy)); }
    pts.push(new THREE.Vector2(crownR(TOP - 0.03) * 0.55 + 0.012, TOP + 0.022)); pts.push(new THREE.Vector2(0.0001, TOP + 0.03));
    var dome = M(new THREE.LatheGeometry(pts, 64), 'p14'); dome.material.side = THREE.DoubleSide;
    var bill = M(new THREE.CylinderGeometry(r * 0.95, r * 0.95, 0.016, 40, 1, false, -Math.PI * 0.42, Math.PI * 0.84), 'p15');
    bill.scale.z = 1.55; bill.position.set(0, CROWN + 0.004, 0.012);
    var btn = M(new THREE.SphereGeometry(0.02, 14, 10), 'p15'); btn.position.y = TOP + 0.03;
    g.add(dome, bill, btn); return g;
  });
  // Beach Tee: a sand tee with one sky stripe (a two-tone split, R11)
  L.registerItem('st-tee', function () {
    var N = 256, cv = document.createElement('canvas'); cv.width = cv.height = N; var g = cv.getContext('2d');
    function y(f) { return (1 - K.vAt(f * BODY.H)) * N; }
    g.fillStyle = L.C('p05'); g.fillRect(0, y(0.36), N, y(0.06) - y(0.36));
    g.fillStyle = L.C('p09'); g.fillRect(0, y(0.24), N, y(0.19) - y(0.24));
    var tex = new THREE.CanvasTexture(cv); tex.colorSpace = THREE.SRGBColorSpace;
    var geo = K.heightShade(K.bodyGeo(Math.PI, Math.PI * 2), BODY.H);
    var m = new THREE.Mesh(geo, K.mat('#FFFFFF', { vc: true })); m.material.map = tex; m.material.alphaTest = 0.5; m.castShadow = false; m.receiveShadow = true;
    m.scale.set(1.014, 1, 1.014); m.name = 'item:st-tee';
    var grp = new THREE.Group(); grp.add(m); grp.userData.natural = 'body'; return grp;
  });
  // Driftwood Bonk: a pale, bent stick with one knot
  L.registerItem('st-bonk', function () {
    var g = new THREE.Group(); g.name = 'item:st-bonk';
    var curve = new THREE.CatmullRomCurve3([new THREE.Vector3(0, -0.04, 0), new THREE.Vector3(0.012, 0.12, 0), new THREE.Vector3(-0.01, 0.26, 0), new THREE.Vector3(0.02, 0.36, 0)]);
    var stick = M(new THREE.TubeGeometry(curve, 24, 0.024, 12, false), 'p02');
    var tip = M(new THREE.SphereGeometry(0.034, 16, 12), 'p02'); tip.position.set(0.02, 0.36, 0);
    var knot = M(new THREE.SphereGeometry(0.016, 12, 8), 'p03'); knot.position.set(0.02, 0.2, 0.012);
    g.add(stick, tip, knot);
    g.rotation.set(0.1, 0, 0.3 + 0.14 + 0.3); g.position.y = -0.02; g.scale.setScalar(0.95);
    return g;
  });

  // ---------------- drawing the player face parts ----------------
  var my = -0.032;   // the mouth line (look3's)
  function eyesParts(kind) {
    var P = [], ex = FACE.eyeDX, R = FACE.eyeR;
    function dot(x, r) { P.push({ geo: new THREE.CircleGeometry(r, 24), color: 'p01', m: mtx(x, 0, at(x, 0, 0.003), 0, ry(x), 0, 1, 1.12, 1) });
      P.push({ geo: new THREE.CircleGeometry(r * 0.3, 12), color: 'p04', m: mtx(x - r * 0.34, r * 0.42, at(x - r * 0.34, r * 0.42, 0.0045), 0, ry(x)) }); }
    function arc(x) { P.push({ geo: new THREE.TorusGeometry(0.022, 0.0068, 6, 16, Math.PI), color: 'p01', m: mtx(x, -0.008, at(x, 0, 0.003), 0, ry(x), 0, 1, 0.9, 0.4) }); }
    [-1, 1].forEach(function (s) {
      var x = s * ex;
      if (kind === 'sleepy') {   // half-closed: the lower half of a dot under a straight lid
        P.push({ geo: new THREE.CircleGeometry(R, 24, Math.PI, Math.PI), color: 'p01', m: mtx(x, 0.004, at(x, 0, 0.003), 0, ry(x)) });
        P.push({ geo: new THREE.PlaneGeometry(R * 2.5, 0.0075), color: 'p01', m: mtx(x, 0.006, at(x, 0, 0.0035), 0, ry(x), s * 0.08) });
      } else if (kind === 'sparkle') {   // big round eyes, two catch-lights
        P.push({ geo: new THREE.CircleGeometry(R * 1.3, 28), color: 'p01', m: mtx(x, 0.002, at(x, 0, 0.003), 0, ry(x), 0, 1, 1.1, 1) });
        P.push({ geo: new THREE.CircleGeometry(R * 0.42, 14), color: 'p04', m: mtx(x - R * 0.4, R * 0.5, at(x - R * 0.4, R * 0.5, 0.0045), 0, ry(x)) });
        P.push({ geo: new THREE.CircleGeometry(R * 0.2, 10), color: 'p04', m: mtx(x + R * 0.45, -R * 0.4, at(x + R * 0.45, -R * 0.4, 0.0045), 0, ry(x)) });
      } else if (kind === 'happy') arc(x);
      else if (kind === 'wink') { if (s > 0) arc(x); else dot(x, R); }
      else if (kind === 'keen') {   // a dot cut flat on top by a slanted lid: determined
        dot(x, R);
        P.push({ geo: new THREE.PlaneGeometry(R * 2.8, 0.008), color: 'p01', m: mtx(x, R * 0.62, at(x, 0, 0.005), 0, ry(x), s * 0.32) });
      } else dot(x, R);
    });
    return P;
  }
  function browParts(kind, col) {
    var P = [], ex = FACE.eyeDX;
    if (!kind || kind === 'none') return P;
    [-1, 1].forEach(function (s) {
      var x = s * ex, y = 0.052;
      if (kind === 'arch') P.push({ geo: new THREE.TorusGeometry(0.026, 0.0062, 6, 16, Math.PI * 0.7), color: col, m: mtx(x, y - 0.02, at(x, y, 0.003), 0, ry(x), Math.PI * 0.15, 1, 1, 0.4) });
      if (kind === 'worried') P.push({ geo: new THREE.PlaneGeometry(0.04, 0.009), color: col, m: mtx(x, y, at(x, y, 0.003), 0, ry(x), -s * 0.38) });
      if (kind === 'cross') P.push({ geo: new THREE.PlaneGeometry(0.042, 0.01), color: col, m: mtx(x, y - 0.004, at(x, y, 0.003), 0, ry(x), s * 0.4) });
      if (kind === 'dash') P.push({ geo: new THREE.CircleGeometry(0.011, 16), color: col, m: mtx(x, y, at(x, y, 0.003), 0, ry(x), 0, 1.5, 0.75, 1) });
    });
    return P;
  }
  function mouthParts(kind) {
    var P = [];
    if (kind === 'o') P.push({ geo: new THREE.CircleGeometry(0.0135, 20), color: 'p01', m: mtx(0, my - 0.006, at(0, my, 0.002), 0, 0, 0, 1, 1.25, 1) });
    if (kind === 'cat') [-1, 1].forEach(function (s) { P.push({ geo: new THREE.TorusGeometry(0.0115, 0.0052, 6, 14, Math.PI), color: 'p01', m: mtx(s * 0.0115, my + 0.002, at(s * 0.0115, my, 0.002), 0, ry(s * 0.0115), Math.PI, 1, 1, 0.5) }); });
    if (kind === 'gap') {
      P.push({ geo: new THREE.TorusGeometry(0.023, 0.0058, 6, 16, Math.PI), color: 'p01', m: mtx(0, my + 0.002, at(0, my, 0.002), 0, 0, Math.PI, 1.05, 0.7, 0.5) });
      P.push({ geo: new THREE.PlaneGeometry(0.016, 0.016), color: 'p01', m: mtx(0, my - 0.016, at(0, my - 0.012, 0.0025)) });
      P.push({ geo: new THREE.PlaneGeometry(0.011, 0.011), color: '#FFFFFF', m: mtx(0, my - 0.0155, at(0, my - 0.012, 0.0035)) });
    }
    if (kind === 'blep') {
      P.push({ geo: new THREE.TorusGeometry(0.019, 0.0055, 6, 14, Math.PI), color: 'p01', m: mtx(0, -0.03 - my + my, at(0, my, 0.002), 0, 0, Math.PI, 1, 1, 0.5) });
      P.push({ geo: new THREE.CircleGeometry(0.0105, 16, Math.PI, Math.PI), color: 'p15', m: mtx(0.007, my - 0.016, at(0.007, my - 0.016, 0.0028)) });
    }
    if (kind === 'wave') {
      var pts = []; for (var i = 0; i <= 16; i++) { var x = -0.03 + 0.06 * i / 16; pts.push(new THREE.Vector3(x, my + 0.0055 * Math.sin(i / 16 * Math.PI * 3), at(x, my, 0.002))); }
      P.push({ geo: new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 32, 0.0042, 6, false), color: 'p01' });
    }
    return P;
  }
  function hairParts(kind, col) {
    var H = [];
    if (kind === 'sprout') {   // a short stem and two leaves, the island's own hair
      H.push({ geo: new THREE.CylinderGeometry(0.011, 0.013, 0.09, 8), color: col, m: mtx(0, TOP + 0.035, 0.01) });
      [-1, 1].forEach(function (s) { H.push({ geo: new THREE.SphereGeometry(0.068, 18, 12), color: col, m: mtx(s * 0.06, TOP + 0.09, 0.01, 0, 0, -s * 0.5, 1, 0.42, 0.62) }); });
    }
    if (kind === 'knot') { H.push({ geo: new THREE.SphereGeometry(0.062, 22, 16), color: col, m: mtx(0, TOP + 0.04, -0.01) });
      H.push({ geo: new THREE.TorusGeometry(0.03, 0.009, 8, 20), color: 'p15', m: mtx(0, TOP + 0.0, -0.01, Math.PI / 2) }); }
    if (kind === 'puffs') [[-0.07, 0.0, 0.02], [0.07, 0.0, 0.02], [0, 0.03, -0.03], [0, 0.0, 0.07]].forEach(function (p, i) {
      H.push({ geo: new THREE.SphereGeometry(i === 2 ? 0.085 : 0.075, 22, 16), color: col, m: mtx(p[0], TOP + p[1] - 0.01, p[2] - 0.02, 0, 0, 0, 1, 0.8, 1) }); });
    if (kind === 'cowlick') H.push({ geo: new THREE.TorusGeometry(0.05, 0.017, 8, 24, Math.PI * 1.5), color: col, m: mtx(0, TOP + 0.04, 0.05, 0, Math.PI / 2, 0.4) });
    if (kind === 'fin') H.push({ geo: new THREE.SphereGeometry(0.1, 28, 18), color: col, m: mtx(0, TOP - 0.01, -0.01, 0, 0, 0, 0.28, 0.75, 1.5) });
    if (kind === 'buns') [-1, 1].forEach(function (s) { H.push({ geo: new THREE.SphereGeometry(0.06, 20, 14), color: col, m: mtx(s * 0.13, TOP - 0.03, -0.01) }); });
    return H;
  }

  // a thin cream rim round every player face: the face stays the lightest-edged spot on any body colour and tone
  // (a deep tone on a butter body otherwise sinks into it), and it marks a player face apart from the 14 house faces
  function faceRim() {
    var phiL = Math.PI, rf = K.radiusAt(FACE.y), cy = FACE.y + FACE.maskDY, hw = FACE.maskW + 0.009, hh = FACE.maskH + 0.009;
    var N = 512, cv = document.createElement('canvas'); cv.width = cv.height = N; var g = cv.getContext('2d');
    var du = hw / (phiL * rf), dv = (K.vAt(cy + hh) - K.vAt(cy - hh)) / 2;
    g.fillStyle = '#fff'; g.beginPath(); g.ellipse(0.5 * N, (1 - K.vAt(cy)) * N, du * N, dv * N, 0, 0, Math.PI * 2); g.fill();
    var tex = new THREE.CanvasTexture(cv); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4;
    var m = new THREE.Mesh(K.bodyGeo(-phiL / 2, phiL), new THREE.MeshBasicMaterial({ color: new THREE.Color(L.C('p04')), map: tex, alphaTest: 0.5 }));
    m.scale.set(1.003, 1, 1.003); m.position.y = -FACE.y; m.name = 's3-faceRim'; m.castShadow = m.receiveShadow = false; return m;
  }

  // ---------------- one player trenchie from a look ----------------
  var n = 0, STATS = { made: 0, buried: 0, buriedLooks: [] };
  function make(look, opts) {
    look = Object.assign({}, DEFAULT, look || {}); opts = opts || {};
    var id = 's3-player-' + (n++);
    // look3 reads a face config by trenchie id; 'x' suppresses its default smile when the player mouth is drawn here
    L.FACES[id] = { skin: TONES[look.tone], eyes: 'dot', mouth: look.mouth === 'smile' ? 'smile' : 'x' };
    var kit = { weapon: 'st-bonk', body: 'st-tee', trinket: 'st-roll' };
    if (look.hat !== 'hide') kit.head = look.hat;
    if (opts.items === false) kit = look.hat !== 'hide' ? { head: look.hat } : {};
    var B = K.BODY, keep = { R: B.R, n: B.n, flare: B.flare, e: B.e }, SH = SHAPES[look.shape] || SHAPES.gumdrop;
    Object.assign(B, { R: SH.R, n: SH.n, flare: SH.flare, e: SH.e });   // look3 reads BODY live while it builds; restored at once
    var t;
    // every part that sits on the surface is built while the shape is applied (surfZ and radiusAt read BODY live)
    try {
      rF = K.radiusAt(FACE.y);
      t = L.makeTrenchie({ trenchieId: id, paletteIds: [look.body, 'p04'], kit: kit });
      var J = t.joints, face = J.face, col = look.hairCol;
      if (opts.rim !== false) face.add(faceRim());
      if (look.eyes !== 'dot') { J.eyes.visible = false; }
      var P = [].concat(look.eyes !== 'dot' ? eyesParts(look.eyes) : [], browParts(look.brows, look.brows === 'none' ? null : 'p01'),
        look.mouth !== 'smile' ? mouthParts(look.mouth) : []);
      // guard: a face part whose front-most point is under the face mask (the mask is the body scaled 1.006) cannot be seen
      var bad = 0;
      P.forEach(function (pt) { var g = pt.geo.clone(); if (pt.m) g.applyMatrix4(pt.m); var pa = g.attributes.position, front = -1;
        for (var i = 0; i < pa.count; i++) { var x = pa.getX(i), r = K.radiusAt(FACE.y + pa.getY(i)) * 1.006; front = Math.max(front, pa.getZ(i) - Math.sqrt(Math.max(0, r * r - x * x))); }
        g.dispose(); if (front <= 0.0004) bad++; });
      STATS.made++; if (bad) { STATS.buried++; STATS.buriedLooks.push(look.shape + '/' + look.eyes + '/' + look.brows + '/' + look.mouth + ':' + bad); }
      if (P.length) { var fx = BC(P); fx.name = 's3-faceFx'; face.add(fx); }
      if (look.hat === 'hide' && look.hair !== 'none') { var h = MC(hairParts(look.hair, col)); h.name = 's3-hair'; J.head.add(h); }
    } finally { Object.assign(B, keep); rF = K.radiusAt(FACE.y); delete L.FACES[id]; }
    if (SH.sy !== 1) t.joints.base.scale.y = SH.sy;   // the contact shadow sits on root, outside base, so it stays flat
    t.look = look; return t;
  }

  // ---------------- the likeness check: player parts vs the house caricature parts (LOOK3.FACES) ----------------
  function houseParts() {
    var F = L.FACES || {}, out = {};
    Object.keys(F).forEach(function (id) {
      if (/^s3-/.test(id)) return; var f = F[id], p = [];
      if (f.eyes && f.eyes !== 'dot') p.push('eyes:' + f.eyes);
      if (f.glasses) p.push('glasses:' + f.glasses);
      if (f.brows) p.push('brows:' + f.brows);
      if (f.mouth && f.mouth !== 'smile') p.push('mouth:' + f.mouth);
      if (f.hair) p.push('hair:' + f.hair);
      if (f.sigHat) p.push('named-hat');
      if (f.gag) p.push('gag:' + f.gag);
      out[id] = p;
    });
    return out;
  }
  function playerParts(set) {
    var S = SETS[set], p = [];
    S.eyes.forEach(function (v) { if (v !== 'dot') p.push('eyes:' + v); });
    S.brows.forEach(function (v) { if (v !== 'none') p.push('brows:' + v); });
    S.mouth.forEach(function (v) { if (v !== 'smile') p.push('mouth:' + v); });
    S.hair.forEach(function (v) { if (v !== 'none') p.push('hair:' + v); });
    return p;
  }
  function check(set) {
    var H = houseParts(), P = playerParts(set), worst = 0, shared = [];
    Object.keys(H).forEach(function (id) { var s = H[id].filter(function (x) { return P.indexOf(x) >= 0; }); if (s.length > worst) worst = s.length; s.forEach(function (x) { if (shared.indexOf(x) < 0) shared.push(x); }); });
    var houseTotal = 0; Object.keys(H).forEach(function (id) { houseTotal += H[id].length; });
    return { houses: Object.keys(H).length, houseParts: houseTotal, playerParts: P.length, maxShared: worst, shared: shared };
  }
  function combos(set) { var S = SETS[set], c = 1; SLOTS.forEach(function (k) { c *= S[k].length; }); return c; }
  // with the hat on, the hair choice is hidden: distinct LOOKS, not distinct records
  function looks(set) { var S = SETS[set], c = 1; SLOTS.forEach(function (k) { if (k !== 'hair' && k !== 'hat') c *= S[k].length; });
    var hatsOn = S.hat.filter(function (h) { return h !== 'hide'; }).length; return c * (hatsOn + S.hair.length); }
  // a seeded pick (splitmix-ish, so the board is the same every load)
  function rng(seed) { var s = seed >>> 0; return function () { s = (s + 0x9E3779B9) >>> 0; var z = s; z = Math.imul(z ^ (z >>> 16), 0x85EBCA6B) >>> 0; z = Math.imul(z ^ (z >>> 13), 0xC2B2AE35) >>> 0; return ((z ^ (z >>> 16)) >>> 0) / 4294967296; }; }
  function random(set, seed) { var S = SETS[set], r = rng(seed), lk = {}; SLOTS.forEach(function (k) { lk[k] = S[k][Math.floor(r() * S[k].length)]; }); return lk; }

  root.S3 = { VERSION: 'parts-s3 v0.6 (S3 draft) 2026-11-06', SHAPES: SHAPES, PART: PART, SETS: SETS, SLOTS: SLOTS, DEFAULT: DEFAULT, TONES: TONES,
    make: make, STATS: STATS, check: check, combos: combos, looks: looks, random: random, houseParts: houseParts };
})(typeof globalThis !== 'undefined' ? globalThis : this);
