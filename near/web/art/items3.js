/* items3.js — every item the 14 kits wear, drawn for look3 (ES module). Importing it registers the drawings.
 * Rules: one item per slot; hats clear the eyes by >= 0.05 H; big shapes in the pastel band, saturation only on a
 * small accent; the unlit face stays the lightest spot; a body item is a 2-tone shell on the body; a trinket is a
 * badge on the left hip on a plate in its tier colour. Item colours are palette ids, the same on every wearer.
 */
import * as THREE from 'three';
import { LOOK3 as L3 } from './look3.js';
(function () {
  'use strict';
  var K = L3.kit, M = K.M, MC = K.MC, mtx = K.mtx, FACE = K.FACE, BODY = K.BODY;
  var C = L3.C, H = BODY.H;
  var reg = L3.registerItem;
  var TIER_PLATE = { common: 'p06', rare: 'p10', legendary: 'p13' };

  // ================= HEAD (head-node space: origin on the axis at eye height; the crown starts at +0.082) =================
  var CROWN = 0.082;                                   // eye top is +0.030: 0.052 gap = 0.079 H
  var TOP = H - FACE.y;                                // the body's top, +0.251
  function crownR(dy) { return K.radiusAt(FACE.y + dy); }
  function lathe(pts, segs) { return new THREE.LatheGeometry(pts.map(function (p) { return new THREE.Vector2(p[0], p[1]); }), segs || 64); }
  function hatGroup(name, tilt) { var g = new THREE.Group(); g.name = 'item:' + name; g.rotation.x = tilt === undefined ? -0.12 : tilt; g.userData.natural = 'head'; return g; }

  // Hard Hat (c-head-builder): a sand dome, a short brim, one yellow ridge (the accent)
  reg('c-head-builder', function () {
    var g = hatGroup('c-head-builder'), r = crownR(CROWN) + 0.012;
    var dome = MC([
      { geo: new THREE.SphereGeometry(r, 32, 14, 0, Math.PI * 2, 0, Math.PI / 2), color: 'p05', m: mtx(0, CROWN, 0, 0, 0, 0, 1, 0.86, 1) },
      { geo: new THREE.CylinderGeometry(r + 0.03, r + 0.034, 0.018, 40), color: 'p05', m: mtx(0, CROWN + 0.006, 0.012) }]);
    var ridge = M(new THREE.TorusGeometry(r * 0.985, 0.012, 8, 24, Math.PI), 'p12');
    ridge.rotation.y = Math.PI / 2; ridge.scale.y = 0.86; ridge.position.y = CROWN + 0.004;
    g.add(dome, ridge); return g;
  });
  // Bucket Hat (c-head-maxi): a soft sky crown with a down-turned brim, one deeper band
  reg('c-head-maxi', function () {
    var g = hatGroup('c-head-maxi'), r = crownR(CROWN);
    var hat = M(lathe([[0.0001, TOP + 0.03], [r * 0.55, TOP + 0.028], [r * 0.82, TOP + 0.005], [r + 0.012, CROWN + 0.03],
      [r + 0.016, CROWN + 0.004], [r + 0.075, CROWN - 0.01], [r + 0.09, CROWN - 0.022], [r + 0.085, CROWN - 0.026]], 64), 'p09'); hat.material.side = THREE.DoubleSide;   // opaque from every side
    var band = M(new THREE.CylinderGeometry(r + 0.016, r + 0.018, 0.028, 40, 1, true), 'p10'); band.position.y = CROWN + 0.026;
    band.material.side = THREE.DoubleSide;
    g.add(hat, band); return g;
  });
  // Party Cone (c-head-degen): a lilac cone set on the crown at a jaunty tilt, a yellow pom (the accent)
  reg('c-head-degen', function () {
    var g = hatGroup('c-head-degen', 0), r = crownR(TOP - 0.05);
    var cone = M(new THREE.ConeGeometry(r * 0.78, 0.22, 28, 1), 'p11'); cone.position.set(0, TOP + 0.075, 0);
    var pom = M(new THREE.SphereGeometry(0.03, 14, 10), 'p12'); pom.position.set(0, TOP + 0.19, 0);
    var cap = new THREE.Group(); cap.add(cone, pom); cap.rotation.z = -0.22; cap.position.x = -0.02;
    g.add(cap); return g;
  });
  // Sweatband (c-head-speedrunner): a peach band round the crown, the knot's two tails at the back
  reg('c-head-speedrunner', function () {
    var g = hatGroup('c-head-speedrunner', -0.08), y = CROWN + 0.03, r = crownR(y) + 0.008;
    var band = M(new THREE.TorusGeometry(r, 0.022, 10, 40), 'p14'); band.rotation.x = Math.PI / 2; band.scale.z = 1.25; band.position.y = y;
    var tails = MC([
      { geo: new THREE.SphereGeometry(0.026, 12, 8), color: 'p14', m: mtx(0, y, -r - 0.01) },
      { geo: new THREE.ConeGeometry(0.02, 0.09, 8), color: 'p15', m: mtx(0.03, y - 0.05, -r - 0.025, 0.4, 0, 0.35) },
      { geo: new THREE.ConeGeometry(0.02, 0.08, 8), color: 'p15', m: mtx(-0.025, y - 0.045, -r - 0.025, 0.4, 0, -0.3) }]);
    g.add(band, tails); return g;
  });
  // Surveyor Hat (r-head-builder, rare): a sand pith helmet with a wide brim, a blue band (rare tier)
  reg('r-head-builder', function () {
    var g = hatGroup('r-head-builder'), r = crownR(CROWN);
    var hat = M(lathe([[0.0001, TOP + 0.05], [r * 0.5, TOP + 0.045], [r * 0.86, TOP - 0.01], [r + 0.012, CROWN + 0.04],
      [r + 0.014, CROWN + 0.008], [r + 0.075, CROWN - 0.004], [r + 0.085, CROWN - 0.01], [r + 0.08, CROWN - 0.013]], 64), 'p05'); hat.material.side = THREE.DoubleSide;
    var band = M(new THREE.CylinderGeometry(r + 0.016, r + 0.02, 0.03, 40, 1, true), 'p10'); band.position.y = CROWN + 0.028;
    band.material.side = THREE.DoubleSide;
    var knob = M(new THREE.SphereGeometry(0.022, 12, 8), 'p13'); knob.position.y = TOP + 0.05;
    g.add(hat, band, knob); return g;
  });
  // Aero Goggles (r-head-speedrunner, rare): a dark strap round the crown, two blue lenses pushed up on the forehead
  reg('r-head-speedrunner', function () {
    var g = hatGroup('r-head-speedrunner', 0), y = CROWN + 0.022, r = crownR(y) + 0.006;
    var strap = M(new THREE.TorusGeometry(r, 0.012, 8, 40), 'p03'); strap.rotation.x = Math.PI / 2; strap.position.y = y;
    var parts = [];
    [-1, 1].forEach(function (s) {
      var x = s * 0.062, z = Math.sqrt(Math.max(0, r * r - x * x)) + 0.004, ry = Math.asin(x / r);
      parts.push({ geo: new THREE.CylinderGeometry(0.04, 0.042, 0.028, 22), color: 'p03', m: mtx(x, y + 0.012, z, Math.PI / 2 - 0.25, ry, 0) });
      parts.push({ geo: new THREE.CylinderGeometry(0.031, 0.031, 0.03, 22), color: 'p10', m: mtx(x * 1.03, y + 0.014, z + 0.004, Math.PI / 2 - 0.25, ry, 0) });
    });
    g.add(strap, MC(parts)); return g;
  });
  // Neon Visor (r-head-degen, rare): an open lilac band with a curved bill; the crown shows through
  reg('r-head-degen', function () {
    var g = hatGroup('r-head-degen', 0.05), y = CROWN + 0.06, r = crownR(y) + 0.006;   // clear of the eyes at every facing (B3: it sat on the eye line)
    var band = new THREE.CylinderGeometry(r, r + 0.003, 0.04, 40, 1, true);
    var bill = new THREE.CylinderGeometry(r + 0.075, r + 0.075, 0.012, 32, 1, false, -Math.PI * 0.42, Math.PI * 0.84);
    var vis = MC([{ geo: band, color: 'p11', m: mtx(0, y, 0) }, { geo: bill, color: 'p11', m: mtx(0, y - 0.016, 0.012) }]);
    vis.material.side = THREE.DoubleSide;
    var edge = M(new THREE.TorusGeometry(r + 0.074, 0.006, 6, 30, Math.PI * 0.84), 'p12');
    edge.rotation.set(Math.PI / 2, 0, Math.PI * 0.08); edge.position.set(0, y - 0.016, 0.012);
    g.add(vis, edge); return g;
  });

  // ================= BODY: garment shells (mountBody = the body's bottom, on the axis) =================
  // A full body lathe, 1.4% larger, cut and painted by a canvas texture: u 0..1 round the body with the front at u=0.5,
  // v the profile parameter. The face patch's lowest point is 0.406 H; garment fronts stop at <= 0.385 H.
  var GW = 1024, GH = 512;
  function garment(name, draw, scale) {
    var cv = document.createElement('canvas'); cv.width = GW; cv.height = GH;
    var g = cv.getContext('2d');
    var api = {
      g: g,
      y: function (fracH) { return (1 - K.vAt(fracH * H)) * GH; },
      u: function (u) { return u * GW; },
      // a band whose top edge runs from frontTop (at u=0.5) to backTop (at u=0/1), smoothly
      band: function (color, bottom, frontTop, backTop, gapHalf) {
        g.fillStyle = C(color); g.beginPath();
        var n = 64, i, u, t;
        g.moveTo(0, api.y(bottom));
        for (i = 0; i <= n; i++) {
          u = i / n; var dd = Math.abs(u - 0.5), k = Math.min(1, Math.max(0, (dd - 0.16) / 0.18)); t = 1 - k * k * (3 - 2 * k);   // flat across the face's width (|u-0.5| <= 0.16), then up to the back
          var top = backTop + (frontTop - backTop) * t;
          if (gapHalf && Math.abs(u - 0.5) < gapHalf) top = bottom - 0.001;
          g.lineTo(api.u(u), api.y(top));
        }
        g.lineTo(GW, api.y(bottom)); g.closePath(); g.fill();
      },
      rect: function (color, u0, u1, f0, f1) { g.fillStyle = C(color); g.fillRect(api.u(u0), api.y(f1), api.u(u1) - api.u(u0), api.y(f0) - api.y(f1)); },
      dot: function (color, u, f, rpx) { g.fillStyle = C(color); g.beginPath(); g.ellipse(api.u(u), api.y(f), rpx * 1.25, rpx, 0, 0, Math.PI * 2); g.fill(); }
    };
    draw(api);
    var tex = new THREE.CanvasTexture(cv); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4;
    var geo = K.heightShade(K.bodyGeo(Math.PI, Math.PI * 2), H);       // seam at the back, u = 0.5 at the front
    var m = new THREE.Mesh(geo, K.mat('#FFFFFF', { vc: true })); m.material.map = tex; m.material.alphaTest = 0.5;
    m.castShadow = false; m.receiveShadow = true;
    var s = scale || 1.014; m.scale.set(s, 1, s); m.name = 'item:' + name;
    var grp = new THREE.Group(); grp.add(m); grp.userData.natural = 'body'; return grp;
  }
  // Overalls (c-body-builder): denim legs and a bib, two yellow buttons
  reg('c-body-builder', function () {
    return garment('c-body-builder', function (a) {
      a.band('p10', -0.01, 0.30, 0.30);
      a.rect('p10', 0.41, 0.59, 0.2, 0.385);
      a.dot('p12', 0.425, 0.355, 7); a.dot('p12', 0.575, 0.355, 7);
      a.rect('p03', 0, 1, 0.285, 0.30);                                    // the waist seam
    });
  });
  // Life Vest (c-body-maxi): a peach vest open at the front, two sand straps
  reg('c-body-maxi', function () {
    return garment('c-body-maxi', function (a) {
      a.band('p14', 0.12, 0.38, 0.55, 0.035);
      a.rect('p05', 0, 0.465, 0.2, 0.235); a.rect('p05', 0.535, 1, 0.2, 0.235);
      a.rect('p05', 0, 0.465, 0.3, 0.335); a.rect('p05', 0.535, 1, 0.3, 0.335);
    }, 1.03);
  });
  // Hawaiian Shirt (c-body-degen): a mint shirt with a V collar and a few big flowers
  reg('c-body-degen', function () {
    return garment('c-body-degen', function (a) {
      a.band('p07', 0.07, 0.36, 0.52);
      a.g.fillStyle = C('p07'); a.g.globalCompositeOperation = 'destination-out';
      a.g.beginPath(); a.g.moveTo(a.u(0.46), a.y(0.37)); a.g.lineTo(a.u(0.5), a.y(0.27)); a.g.lineTo(a.u(0.54), a.y(0.37)); a.g.closePath(); a.g.fill();
      a.g.globalCompositeOperation = 'source-over';
      [[0.38, 0.17, 'p14'], [0.6, 0.24, 'p12'], [0.12, 0.3, 'p14'], [0.8, 0.14, 'p14'], [0.95, 0.36, 'p12'], [0.25, 0.42, 'p12']]
        .forEach(function (f) { a.dot(f[2], f[0], f[1], 14); a.dot('p15', f[0], f[1], 5); });
    });
  });
  // Wetsuit (c-body-speedrunner): dark, with a sky stripe down each side
  reg('c-body-speedrunner', function () {
    return garment('c-body-speedrunner', function (a) {
      a.band('p01', -0.01, 0.34, 0.46);
      a.rect('p09', 0.235, 0.265, -0.01, 0.4); a.rect('p09', 0.735, 0.765, -0.01, 0.4);
    });
  });
  // Tool Belt Vest (r-body-builder, rare): a green vest open at the front, a brown belt with two pouches
  reg('r-body-builder', function () {
    return garment('r-body-builder', function (a) {
      a.band('p08', 0.15, 0.37, 0.54, 0.04);
      a.rect('p03', 0, 1, 0.09, 0.15);
      a.rect('p02', 0.36, 0.42, 0.04, 0.15); a.rect('p02', 0.58, 0.64, 0.04, 0.15);
      a.rect('p10', 0.385, 0.395, 0.1, 0.13);                              // rare tier stitch
    }, 1.02);
  });
  // Racing Jersey (r-body-speedrunner, rare): blue, two sand stripes
  reg('r-body-speedrunner', function () {
    return garment('r-body-speedrunner', function (a) {
      a.band('p10', 0.06, 0.37, 0.5);
      a.rect('p05', 0, 1, 0.2, 0.235); a.rect('p05', 0, 1, 0.27, 0.29);
    });
  });
  // Velvet Robe (r-body-degen, rare): lilac to the ground, a V at the neck, a gold hem (the accent)
  reg('r-body-degen', function () {
    return garment('r-body-degen', function (a) {
      a.band('p11', -0.01, 0.32, 0.58);
      a.g.globalCompositeOperation = 'destination-out';
      a.g.beginPath(); a.g.moveTo(a.u(0.46), a.y(0.33)); a.g.lineTo(a.u(0.5), a.y(0.22)); a.g.lineTo(a.u(0.54), a.y(0.33)); a.g.closePath(); a.g.fill();
      a.g.globalCompositeOperation = 'source-over';
      a.rect('p13', 0, 1, -0.01, 0.045);
    }, 1.02);
  });

  // ================= WEAPONS (mountWeapon: grip at the origin, shaft along +y), 0.4-0.7 H, leaning out =================
  function held(name, parts, opts) {
    opts = opts || {};
    var g = new THREE.Group(); g.name = 'item:' + name;
    parts.forEach(function (p) { g.add(p); });
    g.rotation.set(opts.rx === undefined ? 0.1 : opts.rx, 0, (opts.rz === undefined ? 0.3 : opts.rz) + 0.14); g.position.y = opts.y === undefined ? -0.02 : opts.y;
    g.scale.setScalar(0.95); g.rotation.z += 0.3;      // ~0.45 H, held out from the body
    return g;
  }
  function haft(len, y, color) { var h = M(new THREE.CylinderGeometry(0.016, 0.018, len, 12), color || 'p03'); h.position.y = y; return h; }
  function twistCone(r, h, turns) {
    var geo = new THREE.ConeGeometry(r, h, 12, 8), p = geo.attributes.position, v = new THREE.Vector3();
    for (var i = 0; i < p.count; i++) { v.fromBufferAttribute(p, i); var a = (v.y / h + 0.5) * Math.PI * 2 * turns, c = Math.cos(a), s = Math.sin(a); p.setXYZ(i, v.x * c - v.z * s, v.y, v.x * s + v.z * c); }
    geo.computeVertexNormals(); return geo;
  }
  // Narwhal Pike (c-lunge): a haft and a sand spiral tusk
  reg('c-lunge', function () {
    var tusk = M(twistCone(0.044, 0.26, 1.2), 'p05'); tusk.position.y = 0.31;
    return held('c-lunge', [haft(0.26, 0.03), tusk]);
  });
  // Swordfish Pike (r-lunge, rare): a haft, a flat blue bill, a fin collar
  reg('r-lunge', function () {
    var bill = M(new THREE.ConeGeometry(0.034, 0.3, 14), 'p10'); bill.scale.set(1.5, 1, 0.55); bill.position.y = 0.33;
    var fin = M(new THREE.SphereGeometry(0.04, 14, 10), 'p09'); fin.scale.set(1.2, 0.6, 0.5); fin.position.y = 0.18;
    return held('r-lunge', [haft(0.24, 0.03), bill, fin]);
  });
  // Oar Swipe (c-swing): a wooden oar, the blade up
  reg('c-swing', function () {
    var blade = M(new THREE.SphereGeometry(0.07, 18, 12), 'p02'); blade.scale.set(0.8, 1.7, 0.24); blade.position.y = 0.33;
    return held('c-swing', [haft(0.34, 0.08), blade], { rz: 0.34 });
  });
  // Captain's Oar (r-swing, rare): a blue blade with a gold collar
  reg('r-swing', function () {
    var blade = M(new THREE.SphereGeometry(0.07, 18, 12), 'p10'); blade.scale.set(0.85, 1.75, 0.24); blade.position.y = 0.34;
    var collar = M(new THREE.CylinderGeometry(0.026, 0.026, 0.03, 12), 'p13'); collar.position.y = 0.22;
    return held('r-swing', [haft(0.34, 0.08), blade, collar], { rz: 0.34 });
  });
  // Coconut Mortar (c-lob): a stubby bamboo tube, a coconut peeking out of it
  reg('c-lob', function () {
    var tube = M(new THREE.CylinderGeometry(0.058, 0.05, 0.17, 18), 'p02'); tube.position.y = 0.1;
    var nut = M(new THREE.SphereGeometry(0.05, 16, 12), 'p03'); nut.position.y = 0.19;
    return held('c-lob', [tube, nut], { rz: 0.45, rx: 0.2 });
  });
  // Lighthouse Lens (c-beam): a staff with a coral lantern and a yellow lens (the accent)
  reg('c-beam', function () {
    var lamp = MC([{ geo: new THREE.CylinderGeometry(0.034, 0.046, 0.08, 16), color: 'p14', m: mtx(0, 0.3, 0) },
                   { geo: new THREE.ConeGeometry(0.05, 0.04, 16), color: 'p15', m: mtx(0, 0.375, 0) }]);
    var lens = M(new THREE.SphereGeometry(0.026, 14, 10), 'p12'); lens.position.y = 0.335;
    return held('c-beam', [haft(0.3, 0.1), lamp, lens]);
  });
  // Prism Lens (r-beam, rare): a staff with a tall sky crystal
  reg('r-beam', function () {
    var crystal = M(new THREE.OctahedronGeometry(0.058, 0), 'p09'); crystal.scale.set(1, 1.5, 1); crystal.position.y = 0.33;
    var cap = M(new THREE.CylinderGeometry(0.026, 0.03, 0.03, 10), 'p10'); cap.position.y = 0.25;
    return held('r-beam', [haft(0.3, 0.1), crystal, cap]);
  });
  // Pebble Sling (c-shot): a handle, a Y fork, a grey pebble in the band
  function sling(name, forkColor, shotColor) {
    var fork = M(new THREE.TorusGeometry(0.055, 0.014, 8, 18, Math.PI), forkColor); fork.position.y = 0.13; fork.rotation.z = 0;
    var shot = M(new THREE.SphereGeometry(0.024, 12, 8), shotColor); shot.position.y = 0.165;
    var handle = M(new THREE.CylinderGeometry(0.018, 0.02, 0.16, 10), 'p03'); handle.position.y = 0.05;
    return held(name, [handle, fork, shot], { rz: 0.32 });
  }
  reg('c-shot', function () { return sling('c-shot', 'p02', 'p06'); });
  // Pearl Sling (r-shot, rare): a blue fork, a pearl
  reg('r-shot', function () { return sling('r-shot', 'p10', 'p05'); });
  // Moon Jelly Zapper (r-zap, rare): a staff topped with a lilac jelly bell and a sky frill
  function zapper(name, bell, frill) {
    var dome = M(new THREE.SphereGeometry(0.068, 20, 10, 0, Math.PI * 2, 0, Math.PI / 2), bell); dome.scale.y = 0.85; dome.position.y = 0.3;
    var fr = M(new THREE.TorusGeometry(0.058, 0.014, 8, 20), frill); fr.rotation.x = Math.PI / 2; fr.position.y = 0.3;
    return held(name, [haft(0.3, 0.1), dome, fr]);
  }
  reg('r-zap', function () { return zapper('r-zap', 'p11', 'p09'); });
  reg('c-zap', function () { return zapper('c-zap', 'p09', 'p07'); });

  // ================= TRINKETS: a badge on the left hip (mountTrinket faces out along +z), <= 0.08 wide =================
  function badge(name, tier, emblemParts) {
    var g = new THREE.Group(); g.name = 'item:' + name;
    var plate = M(new THREE.CylinderGeometry(0.04, 0.04, 0.012, 20), TIER_PLATE[tier] || 'p06');
    plate.rotation.x = Math.PI / 2; plate.position.z = 0.004; g.add(plate);
    if (emblemParts && emblemParts.length) { var e = MC(emblemParts); e.position.z = 0.012; g.add(e); }
    return g;
  }
  var B = function (id, parts) { reg(id, function (c) { return badge(id, (c.rec && c.rec.tier) || 'legendary', parts()); }); };
  function coins(color, n) { var o = []; for (var i = 0; i < n; i++) o.push({ geo: new THREE.CylinderGeometry(0.02, 0.02, 0.009, 14), color: color, m: mtx(0.003 * (i % 2), -0.012 + i * 0.011, 0.008, 0, 0, 0) }); return o; }
  B('leg-stack-sats', function () { return coins('p12', 3); });
  B('leg-ether-stack', function () { return coins('p11', 3); });
  B('leg-liquidity-wave', function () { return [{ geo: new THREE.SphereGeometry(0.02, 12, 8), color: 'p12', m: mtx(0, 0, 0.006, 0, 0, 0.5, 0.7, 1.7, 0.35) },
                                                 { geo: new THREE.BoxGeometry(0.008, 0.05, 0.004), color: 'p09', m: mtx(0, 0, 0.013, 0, 0, 0.5) }]; });
  B('leg-tinker-coil', function () { return [0, 1, 2].map(function (i) { return { geo: new THREE.TorusGeometry(0.016, 0.0045, 6, 16), color: 'p02', m: mtx(0, -0.012 + i * 0.012, 0.006, Math.PI / 2 - 0.3, 0, 0) }; }); });
  B('leg-laser-eyes', function () { return [{ geo: new THREE.OctahedronGeometry(0.02, 0), color: 'p15', m: mtx(0, 0, 0.008, 0, 0, 0, 1, 1, 0.6) }]; });
  B('leg-fast-finality', function () { return [{ geo: new THREE.BoxGeometry(0.012, 0.022, 0.006), color: 'p08', m: mtx(-0.009, -0.004, 0.006, 0, 0, 0.7) },
                                                { geo: new THREE.BoxGeometry(0.012, 0.042, 0.006), color: 'p08', m: mtx(0.008, 0.004, 0.006, 0, 0, -0.55) }]; });
  B('leg-lifeboat', function () { return [{ geo: new THREE.SphereGeometry(0.024, 14, 8, 0, Math.PI * 2, Math.PI / 2, Math.PI / 2), color: 'p02', m: mtx(0, 0.006, 0.006, 0, 0, 0, 1.3, 0.8, 0.55) }]; });
  B('leg-hydra-halo', function () { return [{ geo: new THREE.TorusGeometry(0.02, 0.006, 6, 20), color: 'p09', m: mtx(0, 0, 0.006) }]; });
  B('leg-loop-flywheel', function () { return [{ geo: new THREE.TorusGeometry(0.02, 0.007, 6, 18), color: 'p06', m: mtx(0, 0, 0.006) },
                                                 { geo: new THREE.CylinderGeometry(0.008, 0.008, 0.01, 10), color: 'p06', m: mtx(0, 0, 0.006, Math.PI / 2, 0, 0) }]; });
  B('leg-priority-fee', function () { return [{ geo: new THREE.BoxGeometry(0.008, 0.04, 0.006), color: 'p07', m: mtx(-0.014, -0.002, 0.006) },
                                                { geo: new THREE.BoxGeometry(0.008, 0.04, 0.006), color: 'p07', m: mtx(0.014, -0.002, 0.006) },
                                                { geo: new THREE.BoxGeometry(0.04, 0.008, 0.006), color: 'p07', m: mtx(0, 0.012, 0.008) }]; });
  B('leg-builder-census', function () { return [{ geo: new THREE.BoxGeometry(0.032, 0.042, 0.006), color: 'p02', m: mtx(0, 0, 0.005) },
                                                  { geo: new THREE.BoxGeometry(0.024, 0.028, 0.004), color: 'p05', m: mtx(0, -0.003, 0.009) }]; });
  B('leg-harvest-quake', function () { var o = [{ geo: new THREE.BoxGeometry(0.006, 0.05, 0.005), color: 'p03', m: mtx(0, -0.004, 0.006) }];
                                       [-1, 0, 1].forEach(function (i) { o.push({ geo: new THREE.BoxGeometry(0.005, 0.018, 0.005), color: 'p06', m: mtx(i * 0.009, 0.026, 0.006) }); }); return o; });
  B('leg-poker-face', function () { return [-1, 0, 1].map(function (i) { return { geo: new THREE.BoxGeometry(0.022, 0.032, 0.003), color: i ? 'p05' : 'p14', m: mtx(i * 0.01, 0, 0.005 + (i + 1) * 0.002, 0, 0, -i * 0.35) }; }); });
  B('leg-router-drone', function () { return [{ geo: new THREE.SphereGeometry(0.014, 12, 8), color: 'p05', m: mtx(0, -0.004, 0.008) },
                                                { geo: new THREE.CylinderGeometry(0.026, 0.026, 0.004, 16), color: 'p10', m: mtx(0, 0.012, 0.008) }]; });



  // ================= SIGNATURE PIECES (one unique piece per trenchie, kits.json signaturePiece) =================
  // Each carries that trenchie's caricature trait in a stylised, original way (no likeness traced; names stay spoofs).
  // HEAD pieces (head-node space)
  reg('sig-laser-sailor', function () {            // a navy captain's cap: flat crown, white peak, gold anchor badge
    var g = hatGroup('sig-laser-sailor', 0), r = crownR(CROWN);   // level on the crown
    var cap = M(lathe([[0.0001, TOP + 0.06], [r + 0.04, TOP + 0.06], [r + 0.045, TOP + 0.03], [r + 0.005, CROWN + 0.03], [r + 0.012, CROWN]]), 'p10');
    cap.material.side = THREE.DoubleSide;
    var peak = M(new THREE.CylinderGeometry(r + 0.06, r + 0.06, 0.014, 32, 1, false, -Math.PI * 0.32, Math.PI * 0.64), 'p05'); peak.position.y = CROWN + 0.004;
    var badge = M(new THREE.SphereGeometry(0.024, 12, 8), 'p13'); badge.scale.z = 0.4; badge.position.set(0, CROWN + 0.07, r + 0.018);
    g.add(cap, peak, badge); return g;
  });
  reg('sig-vitrenchik', function () {              // a unicorn hat: a soft lilac cap, one spiral horn, two small ears
    var g = hatGroup('sig-vitrenchik', -0.08), r = crownR(CROWN) + 0.014;
    var cap = M(new THREE.SphereGeometry(r, 40, 16, 0, Math.PI * 2, 0, Math.PI / 2), 'p07'); cap.scale.y = (TOP - CROWN + 0.03) / r; cap.position.y = CROWN;   // mint: contrasts the lilac body
    var horn = M(twistCone(0.045, 0.24, 3), 'p12'); horn.position.set(0, TOP + 0.15, 0.03); horn.rotation.x = 0.12;   // >= 0.15 H, upright
    var bands = MC([['p14', -0.075, 0.038], ['p09', -0.02, 0.027], ['p11', 0.035, 0.016]].map(function (b) { return { geo: new THREE.TorusGeometry(b[2], 0.006, 6, 20), color: b[0], m: mtx(0, b[1], 0, Math.PI / 2, 0, 0) }; }));
    bands.position.copy(horn.position); bands.rotation.copy(horn.rotation);   // the rainbow stripes
    var ears = MC([-1, 1].map(function (s) { return { geo: new THREE.ConeGeometry(0.03, 0.07, 14), color: 'p14', m: mtx(s * r * 0.62, TOP + 0.02, -0.01, 0, 0, -s * 0.5, 1.2, 1.2, 1.2) }; }));
    g.add(cap, horn, bands, ears); return g;
  });
  // ---- named hats. Our own simple marks, not logo files. ----
  reg('hat-eth', function () {                      // an Ethereum hat: a lilac cap with a two-tone diamond standing on top
    var g = hatGroup('hat-eth', -0.06), r = crownR(CROWN) + 0.014;
    var cap = M(new THREE.SphereGeometry(r, 40, 16, 0, Math.PI * 2, 0, Math.PI / 2), 'p11'); cap.scale.y = (TOP - CROWN + 0.02) / r; cap.position.y = CROWN;
    var band = M(new THREE.CylinderGeometry(r + 0.004, r + 0.006, 0.03, 40, 1, true), 'p10'); band.position.y = CROWN + 0.015; band.material.side = THREE.DoubleSide;
    var gem = MC([{ geo: new THREE.ConeGeometry(0.06, 0.1, 4), color: 'p10', m: mtx(0, TOP + 0.1, 0, 0, Math.PI / 4, 0) },
                  { geo: new THREE.ConeGeometry(0.06, 0.07, 4), color: 'p09', m: mtx(0, TOP + 0.015, 0, Math.PI, Math.PI / 4, 0) }]);
    g.add(cap, band, gem); return g;
  });
  reg('hat-near', function () {                     // a NEAR hat: a mint beanie with a folded brim and a dark N on the front
    var g = hatGroup('hat-near', -0.05), r = crownR(CROWN) + 0.012;
    var cap = M(new THREE.SphereGeometry(r, 40, 16, 0, Math.PI * 2, 0, Math.PI / 2), 'p07'); cap.scale.y = (TOP - CROWN + 0.05) / r; cap.position.y = CROWN;
    var fold = M(new THREE.CylinderGeometry(r + 0.016, r + 0.018, 0.05, 40), 'p08'); fold.position.y = CROWN + 0.02;
    var z = r + 0.02, y = CROWN + 0.02;
    var n = MC([{ geo: new THREE.BoxGeometry(0.012, 0.04, 0.006), color: 'p01', m: mtx(-0.018, y, z) }, { geo: new THREE.BoxGeometry(0.012, 0.04, 0.006), color: 'p01', m: mtx(0.018, y, z) },
                { geo: new THREE.BoxGeometry(0.012, 0.05, 0.006), color: 'p01', m: mtx(0, y, z + 0.001, 0, 0, 0.72) }]);
    g.add(cap, fold, n); return g;
  });
  reg('sig-eddie-lazertrench', function () {
    var g = new THREE.Group(); g.name = 'item:sig-eddie-lazertrench'; g.userData.natural = 'head';
    var e = 0.11, p = [], k = [-1, 1];
    k.forEach(function (a) { k.forEach(function (b) {
      p.push({ geo: new THREE.BoxGeometry(e * 2, 0.012, 0.012), color: 'p06', m: mtx(0, a * e, b * e) });
      p.push({ geo: new THREE.BoxGeometry(0.012, e * 2, 0.012), color: 'p06', m: mtx(a * e, 0, b * e) });
      p.push({ geo: new THREE.BoxGeometry(0.012, 0.012, e * 2), color: 'p06', m: mtx(a * e, b * e, 0) }); }); });
    var cube = MC(p); cube.position.set(0.3, TOP + 0.08, -0.02); cube.rotation.set(0.6, 0.7, 0.3); g.add(cube); return g;
  });
  // the named hats are these trenchies' signature pieces
  reg('sig-tommy-leeth', function (c) { return L3.makeItem('hat-eth', 'worn', { slot: 'head' }); });
  reg('sig-illia-trenchukhin', function (c) { return L3.makeItem('hat-near', 'worn', { slot: 'head' }); });
  reg('sig-trenchtoly', function () {              // a sweatband with a big stopwatch clipped to the front
    var g = hatGroup('sig-trenchtoly', -0.05), y = CROWN + 0.03, r = crownR(y) + 0.008;
    var band = M(new THREE.TorusGeometry(r, 0.022, 10, 40), 'p14'); band.rotation.x = Math.PI / 2; band.scale.z = 1.25; band.position.y = y;
    var watch = MC([{ geo: new THREE.CylinderGeometry(0.05, 0.05, 0.022, 24), color: 'p05', m: mtx(0, y + 0.04, r + 0.012, Math.PI / 2 - 0.2, 0, 0) },
                    { geo: new THREE.CylinderGeometry(0.012, 0.012, 0.03, 10), color: 'p13', m: mtx(0, y + 0.1, r + 0.0, 0, 0, 0) },
                    { geo: new THREE.BoxGeometry(0.006, 0.034, 0.004), color: 'p01', m: mtx(0.006, y + 0.05, r + 0.025, -0.2, 0, -0.5) }]);
    g.add(band, watch); return g;
  });
  reg('sig-kathie-moonwood', function () {         // a wide-brimmed hat with a crescent moon and a rising curve
    var g = hatGroup('sig-kathie-moonwood', -0.12), r = crownR(CROWN);
    var hat = M(lathe([[0.0001, TOP + 0.05], [r * 0.7, TOP + 0.045], [r + 0.01, CROWN + 0.04], [r + 0.012, CROWN + 0.004], [r + 0.12, CROWN - 0.012], [r + 0.13, CROWN - 0.02]]), 'p11');
    hat.material.side = THREE.DoubleSide;
    var moon = new THREE.Shape(); moon.absarc(0, 0, 0.045, 0.6, Math.PI * 2 - 0.6, false); moon.absarc(0.022, 0, 0.035, Math.PI * 2 - 0.9, 0.9, true);
    var mm = M(new THREE.ShapeGeometry(moon), 'p12'); mm.position.set(0, CROWN + 0.08, r + 0.004); g.add(hat, mm); return g;
  });
  reg('sig-mert-mumtrench', function () {          // an always-on headset: a band over the crown, two ear cups, a mic with a speech bubble
    // v3.3: the band hugs the scalp; the charcoal earcups sit ON the sides of the head at eye/ear height; a mic to the mouth
    var g = hatGroup('sig-mert-mumtrench', 0), ey = 0.005, re = crownR(ey) + 0.012, CH = '#3A3836';
    var band = M(new THREE.TorusGeometry(re, 0.013, 8, 40, Math.PI), CH); band.position.y = ey; band.scale.y = (TOP + 0.016 - ey) / re;
    var cups = MC([{ geo: new THREE.CylinderGeometry(0.048, 0.048, 0.035, 22), color: CH, m: mtx(re + 0.004, ey, -0.01, 0, 0, Math.PI / 2) },
                   { geo: new THREE.CylinderGeometry(0.048, 0.048, 0.035, 22), color: CH, m: mtx(-re - 0.004, ey, -0.01, 0, 0, Math.PI / 2) }]);
    g.add(band, cups); return g;                     // no mic: it crossed the mouth (face test); the blah bubbles carry the talk
  });
  reg('sig-hameme-pumpeshi', function () {         // a green card-dealer's visor with a spade on the band
    var g = hatGroup('sig-hameme-pumpeshi', 0.08), y = CROWN + 0.07, r = crownR(y) + 0.006;
    var vis = MC([{ geo: new THREE.CylinderGeometry(r, r + 0.004, 0.045, 40, 1, true), color: 'p08', m: mtx(0, y, 0) },
                  { geo: new THREE.CylinderGeometry(r + 0.085, r + 0.085, 0.01, 32, 1, false, -Math.PI * 0.4, Math.PI * 0.8), color: 'p07', m: mtx(0, y - 0.018, 0.012, -0.18, 0, 0) }]);
    vis.material.side = THREE.DoubleSide;
    var sp = new THREE.Shape(); sp.moveTo(0, 0.03); sp.bezierCurveTo(0.03, 0.0, 0.035, -0.025, 0.012, -0.02); sp.lineTo(0.008, -0.035); sp.lineTo(-0.008, -0.035); sp.lineTo(-0.012, -0.02); sp.bezierCurveTo(-0.035, -0.025, -0.03, 0.0, 0, 0.03);
    var spade = M(new THREE.ShapeGeometry(sp), 'p01'); spade.position.set(0, y + 0.004, r + 0.004); g.add(vis, spade); return g;
  });
  // BODY pieces (garment shells, plus one solid piece where the look needs it)
  reg('sig-satrenchi', function () {               // a long grey hooded cloak: the hood frames the pale face (the anonymous founder)
    var g = garment('sig-satrenchi', function (a) { a.band('p06', -0.01, 0.34, 0.66, 0.05); a.rect('p05', 0, 1, -0.01, 0.03); }, 1.03);
    var hoodGeo = K.bodyGeo(Math.PI * 0.32, Math.PI * 1.36);         // the back and the sides only: the face stays open
    var hood = new THREE.Mesh(hoodGeo, K.mat('p06')); hood.material.side = THREE.DoubleSide; hood.castShadow = true; hood.scale.set(1.09, 1.04, 1.09);
    hood.position.y = -0.005;
    var hp = hood.geometry.attributes.position; for (var i = 0; i < hp.count; i++) if (hp.getY(i) < H * 0.5) hp.setY(i, H * 0.5);   // the hood starts at the shoulders
    hood.geometry.computeVertexNormals(); g.add(hood); return g;
  });
  reg('sig-captain-banana-zone', function () {     // a loud banana-print beach shirt, buttons half done
    return garment('sig-captain-banana-zone', function (a) {
      a.band('p09', 0.06, 0.36, 0.52);
      [[0.36, 0.15], [0.62, 0.22], [0.12, 0.3], [0.82, 0.13], [0.95, 0.33], [0.25, 0.4], [0.7, 0.36], [0.47, 0.1]].forEach(function (b) {
        a.g.strokeStyle = C('p12'); a.g.lineWidth = 9; a.g.lineCap = 'round'; a.g.beginPath(); a.g.arc(a.u(b[0]), a.y(b[1]) - 14, 22, 0.4, Math.PI - 0.4); a.g.stroke(); });
      a.dot('p05', 0.5, 0.2, 5); a.dot('p05', 0.5, 0.28, 5);
    });
  });
  reg('sig-avichad', function () {                 // a cross-body satchel: a strap across the chest, the bag on the hip
    var g = garment('sig-avichad', function (a) {
      a.g.fillStyle = C('p03'); a.g.beginPath(); a.g.moveTo(a.u(0.3), a.y(0.12)); a.g.lineTo(a.u(0.34), a.y(0.1)); a.g.lineTo(a.u(0.7), a.y(0.38)); a.g.lineTo(a.u(0.66), a.y(0.4)); a.g.closePath(); a.g.fill();
      a.g.beginPath(); a.g.moveTo(a.u(0.7), a.y(0.38)); a.g.lineTo(a.u(0.95), a.y(0.55)); a.g.lineTo(a.u(0.99), a.y(0.53)); a.g.lineTo(a.u(0.74), a.y(0.36)); a.g.closePath(); a.g.fill();
    });
    var bag = MC([{ geo: new THREE.BoxGeometry(0.17, 0.14, 0.07), color: 'p02', m: mtx(0, 0, 0) }, { geo: new THREE.BoxGeometry(0.17, 0.05, 0.075), color: 'p03', m: mtx(0, 0.05, 0.002) },
                  { geo: new THREE.BoxGeometry(0.12, 0.03, 0.01), color: 'p05', m: mtx(0, 0.085, -0.01) }]);
    var a2 = -1.15; bag.position.set(Math.sin(a2) * 0.25, H * 0.16, Math.cos(a2) * 0.25); bag.rotation.y = a2; g.add(bag); return g;
  });
  reg('sig-kain-warrior', function () {            // patched work dungarees, a seed packet in the bib
    return garment('sig-kain-warrior', function (a) {
      a.band('p02', -0.01, 0.3, 0.3);
      a.rect('p02', 0.41, 0.59, 0.2, 0.37);
      a.rect('p14', 0.22, 0.28, 0.08, 0.16); a.rect('p07', 0.7, 0.76, 0.12, 0.2);
      a.rect('p12', 0.47, 0.53, 0.26, 0.34); a.dot('p08', 0.5, 0.31, 6);
    });
  });
  reg('sig-stepan-gershunode', function () {       // a slim harness: a belt, two straps, three drone clips on the shoulders
    var g = garment('sig-stepan-gershunode', function (a) {
      a.rect('p03', 0, 1, 0.16, 0.21); a.rect('p03', 0.38, 0.41, 0.21, 0.38); a.rect('p03', 0.59, 0.62, 0.21, 0.38);
      a.rect('p03', 0.05, 0.08, 0.21, 0.6); a.rect('p03', 0.92, 0.95, 0.21, 0.6);
    }, 1.016);
    var p = []; [-1, 1, 0].forEach(function (k, i) { var ang = k ? k * 1.35 : Math.PI, rr = K.radiusAt(H * 0.6) + 0.02;
      p.push({ geo: new THREE.BoxGeometry(0.06, 0.03, 0.06), color: 'p10', m: mtx(Math.sin(ang) * rr, H * 0.62, Math.cos(ang) * rr, 0, ang, 0) }); });
    g.add(MC(p)); return g;
  });

  // ================= LEGENDARY BACK PIECES (mountBack: origin on the back at half height, +y up, -z away from the body) =================
  //  the 14 must be nameable in silhouette. Each house legendary is unique, so it is worn big, on the back,
  // where it changes the outline and never touches the face. <= 3 meshes each (merged where they share a material).
  var BK = function (id, fn) { reg('back:' + id, function () { var g = new THREE.Group(); g.name = 'back:' + id; fn(g); return g; }); };
  function cyl(rt, rb, h, seg) { return new THREE.CylinderGeometry(rt, rb, h, seg || 20); }
  BK('leg-stack-sats', function (g) {                // a leaning column of gold coins, above the head
    var p = []; for (var i = 0; i < 9; i++) p.push({ geo: cyl(0.07, 0.07, 0.04, 24), color: i % 2 ? 'p13' : 'p12', m: mtx(0.012 * Math.sin(i * 1.7), 0.02 + i * 0.05, -0.08) });
    var m = MC(p); m.rotation.z = -0.18; g.add(m);
  });
  BK('leg-ether-stack', function (g) {               // a lilac coin tower topped with a diamond
    var p = []; for (var i = 0; i < 6; i++) p.push({ geo: cyl(0.065, 0.065, 0.04, 24), color: i % 2 ? 'p11' : 'p05', m: mtx(0, 0.02 + i * 0.05, -0.08) });
    p.push({ geo: new THREE.OctahedronGeometry(0.075, 0), color: 'p11', m: mtx(0, 0.4, -0.08, 0, 0.5, 0, 1, 1.4, 1) });
    var m = MC(p); m.rotation.z = 0.2; g.add(m);
  });
  BK('leg-liquidity-wave', function (g) {            // a banana surfboard upright on the back
    var m = MC([{ geo: new THREE.SphereGeometry(1, 28, 16), color: 'p12', m: mtx(0, 0.2, -0.06, 0, 0, 0, 0.095, 0.4, 0.028) },
                { geo: new THREE.BoxGeometry(0.02, 0.62, 0.06), color: 'p09', m: mtx(0, 0.2, -0.06) }]);
    m.rotation.z = -0.32; g.add(m);
  });
  BK('leg-tinker-coil', function (g) {               // a backpack with a copper coil and an antenna
    var pts = []; for (var i = 0; i <= 80; i++) { var a = i / 80 * Math.PI * 9; pts.push(new THREE.Vector3(Math.cos(a) * 0.06, 0.12 + i / 80 * 0.3, -0.12 + Math.sin(a) * 0.06)); }
    var coil = M(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), 160, 0.012, 6), 'p13'); g.add(coil);
    g.add(MC([{ geo: new THREE.BoxGeometry(0.2, 0.2, 0.1), color: 'p03', m: mtx(0, 0.0, -0.06) }, { geo: cyl(0.008, 0.008, 0.36), color: 'p03', m: mtx(0, 0.3, -0.12) }]));
    var ball = M(new THREE.SphereGeometry(0.035, 16, 12), 'p11'); ball.position.set(0, 0.5, -0.12); g.add(ball);
  });
  BK('leg-laser-eyes', function (g) {                // a ship's mast with a red pennant (the sailor)
    g.add(MC([{ geo: cyl(0.016, 0.02, 0.72), color: 'p02', m: mtx(0, 0.22, -0.07) }, { geo: cyl(0.05, 0.04, 0.05), color: 'p03', m: mtx(0, 0.5, -0.07) }]));
    var s = new THREE.Shape(); s.moveTo(0, 0); s.lineTo(0.26, -0.06); s.lineTo(0, -0.13);
    var f = M(new THREE.ShapeGeometry(s), 'p15'); f.material.side = THREE.DoubleSide; f.position.set(0.016, 0.56, -0.07); g.add(f);
  });
  BK('leg-fast-finality', function (g) {             // three green speed fins swept back
    var p = []; [-1, 0, 1].forEach(function (k) { p.push({ geo: new THREE.ConeGeometry(0.045, 0.34, 12), color: k ? 'p08' : 'p07', m: mtx(k * 0.09, 0.08 + (1 - Math.abs(k)) * 0.06, -0.2, -1.25, 0, k * 0.25) }); });
    g.add(MC(p));
  });
  BK('leg-lifeboat', function (g) {                  // a little wooden boat carried upturned, an arch over the head
    var hull = M(new THREE.SphereGeometry(1, 28, 12, 0, Math.PI * 2, 0, Math.PI / 2), 'p02'); hull.scale.set(0.22, 0.1, 0.09); hull.rotation.set(Math.PI - 0.5, 0, 0); hull.position.set(0, 0.2, -0.12);
    hull.material.side = THREE.DoubleSide; g.add(hull);
    var rim = M(new THREE.TorusGeometry(1, 0.06, 8, 40), 'p14'); rim.scale.set(0.22, 0.09, 0.22); rim.rotation.x = Math.PI / 2 - 0.5; rim.position.set(0, 0.2, -0.12); g.add(rim);
  });
  BK('leg-hydra-halo', function (g) {                // a halo of eight tiny heads, floating above the crown
    var p = [{ geo: new THREE.TorusGeometry(0.17, 0.014, 8, 48), color: 'p09', m: mtx(0, 0, 0, Math.PI / 2, 0, 0) }];
    for (var i = 0; i < 8; i++) { var a = i / 8 * Math.PI * 2; p.push({ geo: new THREE.SphereGeometry(0.03, 12, 8), color: 'p10', m: mtx(Math.cos(a) * 0.17, 0.02, Math.sin(a) * 0.17) }); }
    var m = MC(p); m.position.set(0, 0.42, 0.2); m.rotation.x = 0.25; g.add(m);
  });
  BK('leg-loop-flywheel', function (g) {             // a grey flywheel on the back, edge-on to the sides
    var p = [{ geo: new THREE.TorusGeometry(0.2, 0.035, 10, 40), color: 'p06', m: mtx(0, 0.14, -0.1) }, { geo: cyl(0.04, 0.04, 0.06), color: 'p13', m: mtx(0, 0.14, -0.1, Math.PI / 2, 0, 0) }];
    for (var i = 0; i < 4; i++) p.push({ geo: new THREE.BoxGeometry(0.4, 0.018, 0.018), color: 'p06', m: mtx(0, 0.14, -0.1, 0, 0, i * Math.PI / 4) });
    g.add(MC(p));
  });
  BK('leg-priority-fee', function (g) {              // a toll-gate boom: a post and a long striped arm out to the side
    var p = [{ geo: cyl(0.025, 0.025, 0.32), color: 'p07', m: mtx(0.05, 0.12, -0.09) }];
    for (var i = 0; i < 5; i++) p.push({ geo: new THREE.BoxGeometry(0.09, 0.035, 0.035), color: i % 2 ? 'p05' : 'p08', m: mtx(0.1 + i * 0.09, 0.26 + i * 0.03, -0.09, 0, 0, 0.32) });
    g.add(MC(p));
  });
  BK('leg-builder-census', function (g) {            // a big clipboard over the shoulder
    var m = MC([{ geo: new THREE.BoxGeometry(0.24, 0.32, 0.025), color: 'p02', m: mtx(0, 0.22, -0.06) },
                { geo: new THREE.BoxGeometry(0.19, 0.24, 0.01), color: 'p05', m: mtx(0, 0.2, -0.078) },
                { geo: new THREE.BoxGeometry(0.1, 0.04, 0.04), color: 'p06', m: mtx(0, 0.38, -0.06) }]);
    m.rotation.z = 0.35; g.add(m);
  });
  BK('leg-harvest-quake', function (g) {             // a pitchfork strapped across the back, tines high
    var p = [{ geo: cyl(0.013, 0.013, 0.72), color: 'p03', m: mtx(0, 0.18, -0.06) }, { geo: new THREE.BoxGeometry(0.14, 0.02, 0.02), color: 'p06', m: mtx(0, 0.54, -0.06) }];
    [-1, 0, 1].forEach(function (k) { p.push({ geo: new THREE.ConeGeometry(0.012, 0.14, 8), color: 'p06', m: mtx(k * 0.06, 0.62, -0.06) }); });
    var m = MC(p); m.rotation.z = -0.55; g.add(m);
  });
  BK('leg-poker-face', function (g) {                // a fan of cards behind the head, like a crest
    var p = []; for (var i = -2; i <= 2; i++) p.push({ geo: new THREE.BoxGeometry(0.1, 0.15, 0.006), color: i === 0 ? 'p15' : i % 2 ? 'p05' : 'p14', m: mtx(Math.sin(i * 0.38) * 0.14, 0.32 + Math.cos(i * 0.38) * 0.1, -0.05 - (i + 2) * 0.004, 0, 0, -i * 0.38) });
    g.add(MC(p));
  });
  BK('leg-router-drone', function (g) {              // a cream drone hovering off the shoulder
    var m = MC([{ geo: new THREE.SphereGeometry(0.06, 20, 14), color: 'p05', m: mtx(0, 0, 0) },
                { geo: new THREE.BoxGeometry(0.32, 0.016, 0.03), color: 'p06', m: mtx(0, 0.03, 0) },
                { geo: cyl(0.06, 0.06, 0.008, 20), color: 'p10', m: mtx(0.16, 0.05, 0) }, { geo: cyl(0.06, 0.06, 0.008, 20), color: 'p10', m: mtx(-0.16, 0.05, 0) }]);
    m.position.set(0.26, 0.42, 0.05); m.rotation.z = 0.15; g.add(m);
  });

  // ================= fallbacks: any item not drawn above still shows its slot and tier =================
  L3.registerFallback('trinket', function (rec) { return badge(rec.id, rec.tier, [{ geo: new THREE.SphereGeometry(0.016, 12, 8), color: rec.tier === 'rare' ? 'p09' : 'p05', m: mtx(0, 0, 0.006) }]); });
  L3.registerFallback('weapon', function (rec, c) {
    var map = { swing: 'c-swing', shot: 'c-shot', beam: 'c-beam', lob: 'c-lob', zap: 'c-zap', lunge: 'c-lunge' };
    return L3.makeItem(map[rec.weapon] || 'c-swing', c.mode, { slot: 'weapon' });
  });
  L3.registerFallback('head', function (rec, c) { return L3.makeItem(rec.tier === 'rare' ? 'r-head-builder' : 'c-head-maxi', c.mode, { slot: 'head' }); });
  L3.registerFallback('body', function (rec, c) { return L3.makeItem(rec.tier === 'rare' ? 'r-body-speedrunner' : 'c-body-degen', c.mode, { slot: 'body' }); });

  L3.ITEMS3 = 'items3 v0.2 (B3 v3.4) 2026-11-09';
})();
