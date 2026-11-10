/* portrait.js: live three.js stills of a player's trenchie for the join flow and the workshop.
 * Uses the approved body and light from near/web/art (loaded by bridge.js as window.LOOK3), with the player part vocabulary of parts-s3.js;
 * a player face never uses a house caricature's combination.
 *
 *   SKP.portrait({ palette:['p10','p04'], face:{skin, eyes, hair, hairColor, brows, mouth, glasses}, kit:{head,body,weapon,trinket},
 *                  w, h, yaw, zoom, backdrop:true|false, ground:true|false, bg }) -> dataURL
 */
(function (root) {
  'use strict';
  var L = root.LOOK3, THREE = root.THREE, K = L.kit;
  var GROUND = '#E6D9A8', DPR = Math.min(2, root.devicePixelRatio || 1);
  L.setTreatment('cel');
  var STARTER = { weapon: 'st-bonk', trinket: 'st-roll', head: 'st-cap', body: 'st-tee' };
  var SKIN = { light: '#FBE7D6', warm: '#F3D2B3', tan: '#E4B993', deep: '#C79870' };
  var n = 0, R = null;
  // our own renderer with an alpha channel, so a trenchie stands on the page's art, not on a painted box
  function renderer(w, h, dpr) {
    if (!R) R = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true, premultipliedAlpha: false });
    R.setPixelRatio(dpr); R.setSize(w, h, false); R.setClearColor(0x000000, 0); return R;
  }
  function ortho(w, h, halfH, center, azDeg, elDeg) {
    var a = w / h, cam = new THREE.OrthographicCamera(-halfH * a, halfH * a, halfH, -halfH, 0.1, 60);
    var az = azDeg * Math.PI / 180, el = elDeg * Math.PI / 180;
    cam.position.set(center.x + Math.sin(az) * Math.cos(el) * 20, center.y + Math.sin(el) * 20, center.z + Math.cos(az) * Math.cos(el) * 20);
    cam.lookAt(center); return cam;
  }
  function portrait(o) {
    o = o || {};
    var w = o.w || 300, h = o.h || 320, id = 'sk-player-' + (n++);
    L.FACES[id] = Object.assign({ skin: SKIN.light, eyes: 'dot', mouth: 'smile' }, o.face || {});
    var scene = new THREE.Scene(), dpr = o.dpr || DPR, r = renderer(w, h, dpr);
    var lights = L.setupScene(scene, r, { extent: 1.4 });
    lights.dir.set(0.3, 4.2, 4.2).normalize(); lights.update(new THREE.Vector3(0, 0, 0));
    if (o.ground !== false) {
      var disc = K.M(new THREE.CylinderGeometry(o.discR || 0.62, (o.discR || 0.62) + 0.04, 0.08, 48), GROUND, { cast: false }); disc.position.y = -0.04; scene.add(disc);
    }
    var kit = Object.assign({}, STARTER, o.kit || {});
    Object.keys(kit).forEach(function (k) { if (kit[k] === null) delete kit[k]; });
    // o.s3: a player look from the game-artist's S3 parts (parts-s3.js), the player vocabulary disjoint from the house faces
    var t = o.s3 && root.S3 ? root.S3.make(o.s3, { items: o.items }) : L.makeTrenchie(o.row ? o.row : { trenchieId: id, paletteIds: o.palette || ['p10', 'p04'], kit: kit });
    t.object3d.rotation.y = o.yaw == null ? -0.38 : o.yaw; scene.add(t.object3d);
    var cam = ortho(w, h, o.zoom || 0.58, new THREE.Vector3(0, o.cy || 0.45, 0), o.az == null ? 16 : o.az, o.el == null ? 16 : o.el);
    if (o.bg) r.setClearColor(new THREE.Color(o.bg), 1);
    r.render(scene, cam); var url = r.domElement.toDataURL('image/png');
    scene.remove(t.object3d); t.dispose(); delete L.FACES[id];
    return url;
  }
  root.SKP = { portrait: portrait, SKIN: SKIN, STARTER: STARTER, VERSION: 'sk portrait 0.1 (2026-11-04)' };
})(typeof globalThis !== 'undefined' ? globalThis : this);
