/* hud-art/hud-art.js — the arena HUD drawn as game art (2026-11-03).
 *
 * One include. Three concepts (the art-direction bibles), each a full HUD set:
 *   sand   SANDBOX TRENCHES: driftwood plank on toothpick legs, a cocktail-stick pennant, a feed written in the sand,
 *          toy bottle-cap buttons. Seeded by Pat's B2 v2 pick "b" (painted plank + gold pennant).
 *   riso   RISO PUMP: printed in three inks (pink, blue, yellow) with real overprint (multiply), halftone screens at
 *          each ink's angle, plates misregistered 1-2 px, torn paper, masking tape, rubber stamps.
 *   candle CANDLE ATOLL: thermal ticker tape, enamel price tags on string, a till receipt for the drop (research M3),
 *          candlestick HP bars.
 *
 * API (the contract with the arena view):
 *   HUDART.mount(el, {concept, w, h, fighters:[{x,y,row,hp,tag,name,kos,state}], lead:{tag,kos}, feed:[{kind,a,b,item}]})
 *     -> Promise (resolves when the fonts are in and the HUD is drawn; el.dataset.hudReady = '1').
 *     x, y are frame pixels at each trenchie's feet. w < 600 draws the phone layout (U1/F3).
 *   HUDART.panels(concept, opts) -> Promise<[{id, title, node, w, h}]>: each panel alone, for the 2x craft sheet.
 *
 * Craft rules kept here (pack §3b U1-U8 + review F1-F4):
 *   - Light: one key from the upper left, banded in three crisp tones (B1-B), cast shadows down-right, hard-edged.
 *   - U4: the feed has no panel; corner pieces are opaque; transient pieces 80-90%.
 *   - U5: bars under the feet for everyone, a name for two (the leader and the followed one).
 *   - U6/F1: feed names are dark fills (body colour pushed toward p01 until >= 4.5:1 on the ground), no outline.
 *   - U8/F2: the top 3 are portrait chips (face on the body colour, hat in the second colour) + one number.
 *   - F3: phone = one-line banner, 2 feed lines.
 * Original art only: every shape is drawn here in code. Fonts are OFL, vendored in hud-art/fonts (LICENSES.txt).
 */
(function (root) {
  'use strict';
  var VERSION = 'hud-art 0.3 (2026-11-03, B2 v3.1 legibility)';
  var HERE = (function () {
    var s = document.currentScript && document.currentScript.src;
    return s ? s.replace(/[^/]*$/, '') : 'hud-art/';
  })();

  // ------------------------------------------------------------------ palette (look/tokens.js p01-p16) and concept inks
  var P = { p01: '#3B2F25', p02: '#C9966A', p03: '#8A5F3C', p04: '#FFF8EA', p05: '#D8CDB8', p06: '#A3A9B2', p07: '#9FDCC5',
    p08: '#5FB79A', p09: '#A9D4F5', p10: '#6FA3D6', p11: '#D3BEF0', p12: '#F7CF6B', p13: '#D39E2A', p14: '#F6A796',
    p15: '#D97A6E', p16: '#FF3B30' };
  var INK = { paper: '#F4EFE3', pink: '#FF48B0', blue: '#0078BF', yellow: '#FFE800' };
  var GROUND = { sand: '#F2DDB0', riso: '#F4EFE3', candle: '#E6D9A8' };   // candle: the cream plateau the feed sits on (board AD c)

  // ------------------------------------------------------------------ small helpers
  function hex2rgb(h) { h = h.replace('#', ''); return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)]; }
  function rgb2hex(c) { return '#' + c.map(function (v) { v = Math.max(0, Math.min(255, Math.round(v))); return (v < 16 ? '0' : '') + v.toString(16); }).join(''); }
  function C(id) { return P[id] || id; }
  function mix(a, b, k) { var x = hex2rgb(C(a)), y = hex2rgb(C(b)); return rgb2hex(x.map(function (v, i) { return v + (y[i] - v) * k; })); }
  function lum(h) { var c = hex2rgb(C(h)).map(function (v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; }
  function contrast(a, b) { var x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }
  // U6/F1: the body colour darkened toward p01 (start ~35%) until it reads at >= 4.5:1 on the ground behind it
  function darkName(hex, ground, target) { target = target || 4.5; for (var k = 0.35; k < 0.97; k += 0.03) { var c = mix(hex, '#1E1712', k); if (contrast(c, ground) >= target) return c; } return '#1E1712'; }
  var NAME_T = 6;   // candle name target: >= 4.5:1 measured on the PNG (review M2), with headroom for antialiasing and fibre
  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  function rng(seed) { var a = seed >>> 0 || 1; return function () { a |= 0; a = a + 0x6D2B79F5 | 0; var t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  function hash(s) { var h = 2166136261; for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
  function f1(v) { return Math.round(v * 10) / 10; }
  // a closed Catmull-Rom spline through points -> smooth hand-drawn outline
  function spline(pts, closed) {
    var n = pts.length, d = 'M' + f1(pts[0][0]) + ' ' + f1(pts[0][1]);
    var last = closed ? n : n - 1;
    for (var i = 0; i < last; i++) {
      var p0 = pts[(i - 1 + n) % n], p1 = pts[i], p2 = pts[(i + 1) % n], p3 = pts[(i + 2) % n];
      if (!closed) { if (i === 0) p0 = p1; if (i + 2 >= n) p3 = p2; }
      d += 'C' + f1(p1[0] + (p2[0] - p0[0]) / 6) + ' ' + f1(p1[1] + (p2[1] - p0[1]) / 6) + ' ' + f1(p2[0] - (p3[0] - p1[0]) / 6) + ' ' + f1(p2[1] - (p3[1] - p1[1]) / 6) + ' ' + f1(p2[0]) + ' ' + f1(p2[1]);
    }
    return d + (closed ? 'Z' : '');
  }
  // an irregular rounded slab: points around a rect, each nudged by jit, corners cut by r
  function slab(x, y, w, h, r, jit, seed, step) {
    var R = rng(seed), pts = [], st = step || 22;
    function J() { return (R() - 0.5) * 2 * jit; }
    function edge(x0, y0, x1, y1) { var L = Math.hypot(x1 - x0, y1 - y0), n = Math.max(1, Math.round(L / st)); for (var i = 0; i < n; i++) { var t = i / n; pts.push([x0 + (x1 - x0) * t + J() * 0.4, y0 + (y1 - y0) * t + J()]); } }
    edge(x + r, y, x + w - r, y); pts.push([x + w - r * 0.3 + J(), y + r * 0.3 + J()]);
    edge(x + w, y + r, x + w, y + h - r); pts.push([x + w - r * 0.3 + J(), y + h - r * 0.3 + J()]);
    edge(x + w - r, y + h, x + r, y + h); pts.push([x + r * 0.3 + J(), y + h - r * 0.3 + J()]);
    edge(x, y + h - r, x, y + r); pts.push([x + r * 0.3 + J(), y + r * 0.3 + J()]);
    return spline(pts, true);
  }
  // a torn edge polygon (paper, tape ends): straight run with fine random teeth
  function torn(x, y, w, h, seed, tooth, sides) {
    var R = rng(seed), t = tooth || 1.6, pts = [], S = sides || 'tblr';
    function run(x0, y0, x1, y1, rough) { var L = Math.hypot(x1 - x0, y1 - y0), n = Math.max(2, Math.round(L / (rough ? 3 : 40))); for (var i = 0; i < n; i++) { var k = i / n, nx = -(y1 - y0) / L, ny = (x1 - x0) / L, o = rough ? (R() - 0.5) * 2 * t + Math.sin(k * 9 + seed) * t * 0.6 : 0; pts.push([x0 + (x1 - x0) * k + nx * o, y0 + (y1 - y0) * k + ny * o]); } }
    run(x, y, x + w, y, S.indexOf('t') >= 0); run(x + w, y, x + w, y + h, S.indexOf('r') >= 0);
    run(x + w, y + h, x, y + h, S.indexOf('b') >= 0); run(x, y + h, x, y, S.indexOf('l') >= 0);
    return 'M' + pts.map(function (p) { return f1(p[0]) + ' ' + f1(p[1]); }).join('L') + 'Z';
  }
  function svg(w, h, body, extra) {
    return '<svg xmlns="http://www.w3.org/2000/svg" width="' + f1(w) + '" height="' + f1(h) + '" viewBox="0 0 ' + f1(w) + ' ' + f1(h) + '" overflow="visible"' + (extra || '') + '>' + body + '</svg>';
  }
  var MC = document.createElement('canvas').getContext('2d');
  function tw(text, font) { MC.font = font; return MC.measureText(text).width; }

  // ------------------------------------------------------------------ fonts (OFL, vendored) and the page CSS
  var FONTS = [
    ['Lilita One', 'LilitaOne-400.woff2', '400'], ['Fredoka', 'Fredoka-var.woff2', '300 700'],
    ['Anton', 'Anton-400.woff2', '400'], ['Archivo Narrow', 'ArchivoNarrow-var.woff2', '400 700'],
    ['Space Mono', 'SpaceMono-400.woff2', '400'], ['Space Mono', 'SpaceMono-700.woff2', '700'], ['DotGothic16', 'DotGothic16-400.woff2', '400']
  ];
  var FACE = {
    sand: { disp: '"Lilita One", "Fredoka", system-ui, sans-serif', text: '"Fredoka", system-ui, sans-serif' },
    riso: { disp: '"Anton", "Archivo Narrow", Impact, sans-serif', text: '"Archivo Narrow", "Arial Narrow", sans-serif' },
    candle: { disp: '"DotGothic16", "Space Mono", monospace', text: '"Space Mono", ui-monospace, monospace' }
  };
  var injected = false, fontsReady = null;
  function inject() {
    if (injected) return; injected = true;
    var css = FONTS.map(function (f) { return '@font-face{font-family:"' + f[0] + '";src:url("' + HERE + 'fonts/' + f[1] + '") format("woff2");font-weight:' + f[2] + ';font-display:block}'; }).join('\n');
    css += '\n.ha-layer{position:absolute;left:0;top:0;pointer-events:none;transform-origin:0 0;font-kerning:normal}' +
      '.ha-layer .ha-p{position:absolute;left:0;top:0}' +
      '.ha-layer svg{display:block;overflow:visible}' +
      '.ha-layer text{font-variant-numeric:tabular-nums}';
    var st = document.createElement('style'); st.id = 'hud-art-css'; st.textContent = css; document.head.appendChild(st);
    var d = document.createElement('div'); d.id = 'hud-art-defs'; d.setAttribute('aria-hidden', 'true');
    d.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden';
    d.innerHTML = svg(0, 0, '<defs>' + DEFS() + '</defs>');
    document.body.appendChild(d);
  }
  function loadFonts() {
    if (fontsReady) return fontsReady;
    var probes = ['400 40px "Lilita One"', '600 20px "Fredoka"', '400 40px "Anton"', '700 20px "Archivo Narrow"', '400 20px "Space Mono"', '700 20px "Space Mono"', '400 30px "DotGothic16"'];
    fontsReady = Promise.all(probes.map(function (p) { return document.fonts.load(p, 'Aa0▲'); })).then(function () { return document.fonts.ready; });
    return fontsReady;
  }

  // ------------------------------------------------------------------ shared filters and screens (one <defs> per page)
  // discrete transfer table: n steps over 0..1, value v[i] for each band
  function bands(n, fn) { var a = []; for (var i = 0; i < n; i++) a.push(fn((i + 0.5) / n).toFixed(3)); return a.join(' '); }
  function toonChain(inBlur, scale, shade, hi, shadeA, hiA, cut) {
    // B1-B's light on a flat object: a blurred alpha height-field lit from the upper left (azimuth 225, elev 42),
    // then cut into three crisp bands: shade on the down-right rims, untouched mid, a highlight on the up-left rims.
    cut = cut || [0.42, 0.86];
    return '<feGaussianBlur in="SourceAlpha" stdDeviation="' + inBlur + '" result="hb"/>' +
      '<feDiffuseLighting in="hb" surfaceScale="' + scale + '" diffuseConstant="1" lighting-color="#fff" result="lit"><feDistantLight azimuth="225" elevation="42"/></feDiffuseLighting>' +
      '<feColorMatrix in="lit" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  1 0 0 0 0" result="la"/>' +
      '<feComponentTransfer in="la" result="shm"><feFuncA type="discrete" tableValues="' + bands(40, function (t) { return t < cut[0] ? shadeA : 0; }) + '"/></feComponentTransfer>' +
      '<feComponentTransfer in="la" result="him"><feFuncA type="discrete" tableValues="' + bands(40, function (t) { return t > cut[1] ? hiA : 0; }) + '"/></feComponentTransfer>' +
      '<feFlood flood-color="' + shade + '"/><feComposite in2="shm" operator="in" result="shc"/>' +
      '<feFlood flood-color="' + hi + '"/><feComposite in2="him" operator="in" result="hic"/>';
  }
  function DEFS() {
    var d = '';
    // --- sand: driftwood. Grain streaks (stretched noise, dark and bleached), then the toon bevel, then a hard cast shadow.
    d += '<filter id="ha-wood" x="-8%" y="-15%" width="125%" height="150%" color-interpolation-filters="sRGB">' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.006 0.19" numOctaves="4" seed="4" result="n"/>' +
      '<feColorMatrix in="n" type="matrix" values="0 0 0 0 0.36  0 0 0 0 0.24  0 0 0 0 0.15  3.2 0 0 0 -1.62" result="dk"/>' +
      '<feColorMatrix in="n" type="matrix" values="0 0 0 0 1  0 0 0 0 0.95  0 0 0 0 0.86  0 -3.4 0 0 1.25" result="lt"/>' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="9" result="fine"/>' +
      '<feColorMatrix in="fine" type="matrix" values="0 0 0 0 0.3  0 0 0 0 0.2  0 0 0 0 0.12  0 0 0 0.55 -0.2" result="fn"/>' +
      '<feMerge result="g"><feMergeNode in="SourceGraphic"/><feMergeNode in="lt"/><feMergeNode in="dk"/><feMergeNode in="fn"/></feMerge>' +
      '<feComposite in="g" in2="SourceAlpha" operator="in" result="wood"/>' +
      toonChain(2.4, 5, '#4A3424', '#FFF3D6', 0.42, 0.55) +
      '<feMerge result="lit2"><feMergeNode in="wood"/><feMergeNode in="shc"/><feMergeNode in="hic"/></feMerge>' +
      '<feComposite in="lit2" in2="SourceAlpha" operator="in"/></filter>';
    d += '<filter id="ha-wood-gold" x="-8%" y="-15%" width="125%" height="150%" color-interpolation-filters="sRGB">' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.006 0.19" numOctaves="4" seed="4" result="n"/>' +
      '<feColorMatrix in="n" type="matrix" values="0 0 0 0 0.36  0 0 0 0 0.24  0 0 0 0 0.15  3.2 0 0 0 -1.62" result="dk"/>' +
      '<feColorMatrix in="n" type="matrix" values="0 0 0 0 1  0 0 0 0 0.95  0 0 0 0 0.86  0 -3.4 0 0 1.25" result="lt"/>' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="9" result="fine"/>' +
      '<feColorMatrix in="fine" type="matrix" values="0 0 0 0 0.3  0 0 0 0 0.2  0 0 0 0 0.12  0 0 0 0.55 -0.2" result="fn"/>' +
      '<feMerge result="g"><feMergeNode in="SourceGraphic"/><feMergeNode in="lt"/><feMergeNode in="dk"/><feMergeNode in="fn"/></feMerge>' +
      '<feComposite in="g" in2="SourceAlpha" operator="in" result="wood"/>' +
      toonChain(2.4, 5, '#2F4F52', '#FFE3A0', 0.42, 0.6) +
      '<feMerge result="lit2"><feMergeNode in="wood"/><feMergeNode in="shc"/><feMergeNode in="hic"/></feMerge>' +
      '<feComposite in="lit2" in2="SourceAlpha" operator="in"/></filter>';
    // --- a hard toon cast shadow, down-right, onto sand (warm, never black: "shadows go to cool/warm, not black")
    d += '<filter id="ha-cast-sand" x="-10%" y="-10%" width="130%" height="140%"><feOffset in="SourceAlpha" dx="5" dy="6" result="o"/>' +
      '<feFlood flood-color="#9C7550" flood-opacity="0.42"/><feComposite in2="o" operator="in" result="s"/>' +
      '<feMerge><feMergeNode in="s"/><feMergeNode in="SourceGraphic"/></feMerge></filter>';
    d += '<filter id="ha-cast-sm" x="-10%" y="-10%" width="140%" height="160%"><feOffset in="SourceAlpha" dx="2.5" dy="3" result="o"/>' +
      '<feFlood flood-color="#9C7550" flood-opacity="0.45"/><feComposite in2="o" operator="in" result="s"/>' +
      '<feMerge><feMergeNode in="s"/><feMergeNode in="SourceGraphic"/></feMerge></filter>';
    // --- sign paint on wood: brush wobble + dry-brush gaps along the grain
    d += '<filter id="ha-paint" x="-5%" y="-20%" width="110%" height="140%">' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.7" numOctaves="2" seed="7" result="n"/>' +
      '<feDisplacementMap in="SourceGraphic" in2="n" scale="1.4" xChannelSelector="R" yChannelSelector="G" result="d"/>' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.06 0.16" numOctaves="2" seed="12" result="w"/>' +
      '<feColorMatrix in="w" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 -14 0 10.2" result="wm"/>' +
      '<feComposite in="d" in2="wm" operator="in"/></filter>';
    // --- cloth: a fine weave + the toon bevel (for the pennant)
    d += '<pattern id="ha-weave" width="3" height="3" patternUnits="userSpaceOnUse"><rect width="3" height="1" fill="#000" opacity="0.07"/><rect width="1" height="3" fill="#fff" opacity="0.10"/></pattern>';
    d += '<filter id="ha-cloth" x="-5%" y="-15%" width="115%" height="140%" color-interpolation-filters="sRGB">' +
      toonChain(1.6, 3, '#7A4E10', '#FFF6C8', 0.38, 0.6) +
      '<feMerge result="m"><feMergeNode in="SourceGraphic"/><feMergeNode in="shc"/><feMergeNode in="hic"/></feMerge><feComposite in="m" in2="SourceAlpha" operator="in"/></filter>';
    // --- plastic bottle cap (glossy toy plastic): stronger, cleaner bands
    d += '<filter id="ha-plastic" x="-10%" y="-10%" width="125%" height="125%" color-interpolation-filters="sRGB">' +
      toonChain(2.2, 6, '#2A1E18', '#FFFFFF', 0.30, 0.75, [0.40, 0.84]) +
      '<feMerge result="m"><feMergeNode in="SourceGraphic"/><feMergeNode in="shc"/><feMergeNode in="hic"/></feMerge><feComposite in="m" in2="SourceAlpha" operator="in"/></filter>';
    // --- writing in the sand: the letters are a groove. Lit from the upper left, the groove's upper-left wall is in shade
    //     (inside the letter), its lower-right lip catches the light (outside it). Slight finger wobble.
    d += '<filter id="ha-engrave" x="-4%" y="-30%" width="108%" height="160%">' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.25" numOctaves="1" seed="21" result="n"/>' +
      '<feDisplacementMap in="SourceGraphic" in2="n" scale="1.1" xChannelSelector="R" yChannelSelector="G" result="g"/>' +
      '<feOffset in="g" dx="1.7" dy="1.9" result="go"/>' +
      '<feComposite in="g" in2="go" operator="out" result="wall"/>' +
      '<feFlood flood-color="#2B1E12" flood-opacity="0.7"/><feComposite in2="wall" operator="in" result="wallc"/>' +
      '<feComposite in="go" in2="g" operator="out" result="lip"/>' +
      '<feFlood flood-color="#FFFBEF" flood-opacity="1"/><feComposite in2="lip" operator="in" result="lipc"/>' +
      '<feMorphology in="g" operator="dilate" radius="1.6" result="dl"/><feOffset in="dl" dx="-1" dy="-1" result="dlo"/><feComposite in="dlo" in2="g" operator="out" result="rimo"/>' +
      '<feFlood flood-color="#B08A58" flood-opacity="0.5"/><feComposite in2="rimo" operator="in" result="rimc"/>' +
      '<feMerge><feMergeNode in="rimc"/><feMergeNode in="lipc"/><feMergeNode in="g"/><feMergeNode in="wallc"/></feMerge></filter>';
    // --- riso: ink texture (uneven coverage + speckle), stamp (rough edge, big voids), tape fibre, paper fibre edge
    d += '<filter id="ha-ink" x="-3%" y="-3%" width="106%" height="106%">' +
      '<feTurbulence type="fractalNoise" baseFrequency="1.1" numOctaves="2" seed="31" result="n"/>' +
      '<feColorMatrix in="n" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  -4 0 0 0 3.05" result="m"/>' +
      '<feComposite in="SourceGraphic" in2="m" operator="in"/></filter>';
    d += '<filter id="ha-stamp" x="-8%" y="-8%" width="116%" height="116%">' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.55" numOctaves="2" seed="41" result="n"/>' +
      '<feDisplacementMap in="SourceGraphic" in2="n" scale="2.2" xChannelSelector="R" yChannelSelector="G" result="d"/>' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.16" numOctaves="3" seed="43" result="v"/>' +
      '<feColorMatrix in="v" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 -5.5 0 0 3.6" result="vm"/>' +
      '<feComposite in="d" in2="vm" operator="in"/></filter>';
    d += '<filter id="ha-stamp-sm" x="-8%" y="-8%" width="116%" height="116%">' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.7" numOctaves="2" seed="45" result="n"/>' +
      '<feDisplacementMap in="SourceGraphic" in2="n" scale="1.1" xChannelSelector="R" yChannelSelector="G" result="d"/>' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.3" numOctaves="2" seed="47" result="v"/>' +
      '<feColorMatrix in="v" type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 -6 0 0 4.6" result="vm"/>' +
      '<feComposite in="d" in2="vm" operator="in"/></filter>';
    d += '<filter id="ha-tape" x="-2%" y="-10%" width="104%" height="120%">' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.02 0.9" numOctaves="2" seed="51" result="n"/>' +
      '<feColorMatrix in="n" type="matrix" values="0 0 0 0 0.55  0 0 0 0 0.48  0 0 0 0 0.3  0 0.5 0 0 -0.15" result="f"/>' +
      '<feComposite in="f" in2="SourceAlpha" operator="in" result="fi"/>' +
      '<feMerge><feMergeNode in="SourceGraphic"/><feMergeNode in="fi"/></feMerge></filter>';
    d += '<filter id="ha-paper" x="-3%" y="-6%" width="106%" height="112%">' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="3" seed="61" result="n"/>' +
      '<feColorMatrix in="n" type="matrix" values="0 0 0 0 0.45  0 0 0 0 0.40  0 0 0 0 0.32  0 0 0.28 0 -0.08" result="f"/>' +
      '<feComposite in="f" in2="SourceAlpha" operator="in" result="fi"/>' +
      '<feMerge><feMergeNode in="SourceGraphic"/><feMergeNode in="fi"/></feMerge></filter>';
    // halftone screens, one angle per ink as on a real riso drum (yellow 0, pink 75, blue 15) and two densities
    [['pink', INK.pink, 75], ['blue', INK.blue, 15], ['yellow', INK.yellow, 0]].forEach(function (k) {
      [['30', 0.95], ['55', 1.35], ['80', 1.75]].forEach(function (t) {
        d += '<pattern id="ha-dot-' + k[0] + t[0] + '" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(' + k[2] + ')"><circle cx="2" cy="2" r="' + t[1] + '" fill="' + k[1] + '"/></pattern>';
      });
    });
    // --- candle: thermal print (faint banding + dropouts), enamel bevel, and the faceted toon for tags
    // ha-thermal (print dropouts on text) is retired: Pat 17:3x "no distressed text anywhere". The id stays as a pass-through
    // so older callers render crisp; the paper itself keeps its fibre, blotches, curls and stamps.
    d += '<filter id="ha-thermal" x="0" y="0" width="100%" height="100%"><feOffset in="SourceGraphic" dx="0" dy="0"/></filter>';
    d += '<filter id="ha-enamel" x="-10%" y="-10%" width="125%" height="125%" color-interpolation-filters="sRGB">' +
      toonChain(1.5, 4, '#1F2B2A', '#FFFFFF', 0.32, 0.8, [0.40, 0.80]) +
      '<feMerge result="m"><feMergeNode in="SourceGraphic"/><feMergeNode in="shc"/><feMergeNode in="hic"/></feMerge><feComposite in="m" in2="SourceAlpha" operator="in"/></filter>';
    [['ha-cast-sea', 2, 2.2, 9, 5, 1.4], ['ha-cast-sea-sm', 1.2, 1.4, 5, 3, 0.9]].forEach(function (c) {
      d += '<filter id="' + c[0] + '" x="-10%" y="-15%" width="140%" height="160%">' +
        '<feOffset in="SourceAlpha" dx="' + c[1] + '" dy="' + c[2] + '" result="o1"/><feFlood flood-color="#2F6A70" flood-opacity="0.34"/><feComposite in2="o1" operator="in" result="s1"/>' +
        '<feOffset in="SourceAlpha" dx="' + c[3] + '" dy="' + c[4] + '" result="o2"/><feGaussianBlur in="o2" stdDeviation="' + c[5] + '" result="o2b"/><feFlood flood-color="#3F8088" flood-opacity="0.24"/><feComposite in2="o2b" operator="in" result="s2"/>' +
        '<feMerge><feMergeNode in="s2"/><feMergeNode in="s1"/><feMergeNode in="SourceGraphic"/></feMerge></filter>';
    });
    // thermal paper lit by the gold key: fibre, a warm lit rim up-left, a cool mint shade rim down-right (three bands)
    d += '<filter id="ha-therm" x="-4%" y="-10%" width="108%" height="125%" color-interpolation-filters="sRGB">' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.9 0.6" numOctaves="3" seed="81" result="n"/>' +
      '<feColorMatrix in="n" type="matrix" values="0 0 0 0 0.55  0 0 0 0 0.5  0 0 0 0 0.4  0 0 0.42 0 -0.12" result="fib"/>' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.012 0.002" numOctaves="2" seed="83" result="bl"/>' +
      '<feColorMatrix in="bl" type="matrix" values="0 0 0 0 0.85  0 0 0 0 0.78  0 0 0 0 0.6  0 0 0 0.5 -0.18" result="blot"/>' +
      toonChain(1.8, 3.5, '#5E9A9E', '#FFE3A0', 0.42, 0.7, [0.44, 0.84]) +
      '<feMerge result="m"><feMergeNode in="SourceGraphic"/><feMergeNode in="blot"/><feMergeNode in="fib"/><feMergeNode in="shc"/><feMergeNode in="hic"/></feMerge><feComposite in="m" in2="SourceAlpha" operator="in"/></filter>';
    // the thermal-print fade: print is darkest where the head pressed hardest, paler toward the right edge
    d += '<linearGradient id="ha-fade" x1="0" x2="1" y1="0" y2="0"><stop offset="0" stop-color="#F7F0DC" stop-opacity="0"/><stop offset="0.55" stop-color="#F7F0DC" stop-opacity="0.08"/><stop offset="1" stop-color="#F7F0DC" stop-opacity="0.42"/></linearGradient>';
    // curl shading for rolled paper ends
    d += '<linearGradient id="ha-curlL" x1="0" x2="1"><stop offset="0" stop-color="#8E8468"/><stop offset="0.45" stop-color="#E9E0C6"/><stop offset="1" stop-color="#C9BC98"/></linearGradient>';
    d += '<linearGradient id="ha-curlR" x1="1" x2="0"><stop offset="0" stop-color="#8E8468"/><stop offset="0.45" stop-color="#E9E0C6"/><stop offset="1" stop-color="#C9BC98"/></linearGradient>';
    return d;
  }

  // ------------------------------------------------------------------ the portrait chip (U8/F2): the trenchie's own face
  // A round body in its first palette colour, the hat band in its second, the cream face patch offset right (as in B1),
  // two dot eyes, a smile, blush. Toon-banded by hand: a lit crescent up-left, a shade crescent down-right.
  function chip(row, r, style, uid) {
    var pal = (row && row.paletteIds) || ['p06', 'p04'], body = C(pal[0]), hat = C(pal[1] || 'p04');
    var id = 'hc' + uid, s = '';
    if (style === 'riso') return risoChip(row, r, uid);
    var lit = mix(body, '#FFFFFF', 0.28), shd = mix(body, 'p01', 0.3), rim = mix(body, 'p01', 0.62);
    if (hat === body || contrast(hat, body) < 1.25) hat = mix(hat, 'p01', 0.25);
    s += '<defs><clipPath id="' + id + '"><circle r="' + r + '"/></clipPath></defs>';
    s += '<g clip-path="url(#' + id + ')">';
    s += '<circle r="' + r + '" fill="' + body + '"/>';
    s += '<circle cx="' + f1(-r * 0.28) + '" cy="' + f1(-r * 0.3) + '" r="' + f1(r * 0.98) + '" fill="' + lit + '" opacity="0.55"/>';
    s += '<circle cx="' + f1(-r * 0.12) + '" cy="' + f1(-r * 0.1) + '" r="' + f1(r * 0.98) + '" fill="' + body + '"/>';
    s += '<path d="M' + f1(-r) + ' ' + f1(r * 0.55) + 'Q0 ' + f1(r * 0.9) + ' ' + f1(r) + ' ' + f1(-r * 0.15) + 'L' + f1(r) + ' ' + f1(r) + 'L' + f1(-r) + ' ' + f1(r) + 'Z" fill="' + shd + '"/>';
    // hat: a cap over the top third, with its own lit edge
    s += '<path d="M' + f1(-r * 1.05) + ' ' + f1(-r * 0.32) + 'Q0 ' + f1(-r * 0.5) + ' ' + f1(r * 1.05) + ' ' + f1(-r * 0.22) + 'L' + f1(r) + ' ' + f1(-r) + 'L' + f1(-r) + ' ' + f1(-r) + 'Z" fill="' + hat + '"/>';
    s += '<path d="M' + f1(-r * 1.05) + ' ' + f1(-r * 0.32) + 'Q0 ' + f1(-r * 0.5) + ' ' + f1(r * 1.05) + ' ' + f1(-r * 0.22) + '" fill="none" stroke="' + mix(hat, 'p01', 0.35) + '" stroke-width="' + f1(r * 0.1) + '"/>';
    s += '<path d="M' + f1(-r * 0.5) + ' ' + f1(-r * 0.82) + 'Q' + f1(-r * 0.1) + ' ' + f1(-r * 0.98) + ' ' + f1(r * 0.35) + ' ' + f1(-r * 0.86) + '" fill="none" stroke="#fff" stroke-opacity="0.55" stroke-width="' + f1(r * 0.12) + '" stroke-linecap="round"/>';
    s += '</g>';
    // the face patch (never shaded: B1 R7 keeps the face in one lit band)
    var fx = r * 0.16, fy = r * 0.2;
    s += '<ellipse cx="' + f1(fx) + '" cy="' + f1(fy) + '" rx="' + f1(r * 0.55) + '" ry="' + f1(r * 0.47) + '" fill="#FFF8EA"/>';
    s += '<circle cx="' + f1(fx - r * 0.2) + '" cy="' + f1(fy - r * 0.06) + '" r="' + f1(r * 0.085) + '" fill="#2B211A"/>';
    s += '<circle cx="' + f1(fx + r * 0.2) + '" cy="' + f1(fy - r * 0.06) + '" r="' + f1(r * 0.085) + '" fill="#2B211A"/>';
    s += '<path d="M' + f1(fx - r * 0.08) + ' ' + f1(fy + r * 0.12) + 'q' + f1(r * 0.08) + ' ' + f1(r * 0.08) + ' ' + f1(r * 0.16) + ' 0" fill="none" stroke="#2B211A" stroke-width="' + f1(Math.max(1, r * 0.06)) + '" stroke-linecap="round"/>';
    s += '<ellipse cx="' + f1(fx - r * 0.36) + '" cy="' + f1(fy + r * 0.1) + '" rx="' + f1(r * 0.1) + '" ry="' + f1(r * 0.06) + '" fill="#F2A3A0" opacity="0.85"/>';
    s += '<ellipse cx="' + f1(fx + r * 0.36) + '" cy="' + f1(fy + r * 0.1) + '" rx="' + f1(r * 0.1) + '" ry="' + f1(r * 0.06) + '" fill="#F2A3A0" opacity="0.85"/>';
    s += '<circle r="' + f1(r - 0.6) + '" fill="none" stroke="' + rim + '" stroke-width="1.6"/>';
    return s;
  }
  // riso: the body as the nearest ink overprint (halftones multiplied), the face as bare paper, eyes in blue ink
  var OVER = [['pink'], ['blue'], ['yellow'], ['pink', 'yellow'], ['blue', 'yellow'], ['pink', 'blue']];
  var OVERHEX = { pink: INK.pink, blue: INK.blue, yellow: INK.yellow, 'pink,yellow': '#FF8A5C', 'blue,yellow': '#2E9B6B', 'pink,blue': '#6B4FA0' };
  function inkFor(hex) {
    var best = null, bd = 1e9, c = hex2rgb(C(hex));
    OVER.forEach(function (o) {
      [['30', 0.35], ['55', 0.6], ['80', 0.85]].forEach(function (t) {
        var target = hex2rgb(mix(INK.paper, OVERHEX[o.join(',')], t[1])), d2 = 0;
        for (var i = 0; i < 3; i++) d2 += (target[i] - c[i]) * (target[i] - c[i]);
        if (d2 < bd) { bd = d2; best = { inks: o, t: t[0] }; }
      });
    });
    // greys and very light bodies: blue at 30% reads as a grey on riso paper
    var l = lum(hex), sat = (function () { var m = Math.max.apply(null, c), n = Math.min.apply(null, c); return (m - n) / 255; })();
    if (sat < 0.12) best = { inks: l > 0.5 ? ['blue'] : ['blue', 'pink'], t: l > 0.5 ? '30' : '55' };
    return best;
  }
  function risoChip(row, r, uid) {
    var pal = (row && row.paletteIds) || ['p06', 'p04'], ink = inkFor(pal[0]), hatInk = inkFor(pal[1] || 'p04');
    var id = 'hc' + uid, s = '<defs><clipPath id="' + id + '"><circle r="' + r + '"/></clipPath></defs>';
    var R = rng(hash(uid + 'r')), dx = function () { return f1((R() - 0.5) * 3); };
    s += '<g clip-path="url(#' + id + ')">';
    ink.inks.forEach(function (k) { s += '<rect x="' + f1(-r - 2) + '" y="' + f1(-r - 2) + '" width="' + f1(2 * r + 4) + '" height="' + f1(2 * r + 4) + '" fill="url(#ha-dot-' + k + (ink.inks.length > 1 ? '55' : '80') + ')" style="mix-blend-mode:multiply" transform="translate(' + dx() + ' ' + dx() + ')"/>'; });
    // hat band: solid ink, misregistered
    s += '<path transform="translate(' + dx() + ' ' + dx() + ')" d="M' + f1(-r * 1.1) + ' ' + f1(-r * 0.3) + 'Q0 ' + f1(-r * 0.5) + ' ' + f1(r * 1.1) + ' ' + f1(-r * 0.2) + 'L' + f1(r) + ' ' + f1(-r * 1.1) + 'L' + f1(-r) + ' ' + f1(-r * 1.1) + 'Z" fill="' + INK[hatInk.inks[0]] + '" style="mix-blend-mode:multiply" filter="url(#ha-ink)"/>';
    s += '</g>';
    var fx = r * 0.16, fy = r * 0.2;
    s += '<ellipse cx="' + f1(fx) + '" cy="' + f1(fy) + '" rx="' + f1(r * 0.55) + '" ry="' + f1(r * 0.47) + '" fill="' + INK.paper + '"/>';
    s += '<g fill="' + INK.blue + '" style="mix-blend-mode:multiply"><circle cx="' + f1(fx - r * 0.2) + '" cy="' + f1(fy - r * 0.06) + '" r="' + f1(r * 0.09) + '"/><circle cx="' + f1(fx + r * 0.2) + '" cy="' + f1(fy - r * 0.06) + '" r="' + f1(r * 0.09) + '"/></g>';
    s += '<path d="M' + f1(fx - r * 0.08) + ' ' + f1(fy + r * 0.12) + 'q' + f1(r * 0.08) + ' ' + f1(r * 0.08) + ' ' + f1(r * 0.16) + ' 0" fill="none" stroke="' + INK.blue + '" stroke-width="' + f1(Math.max(1, r * 0.07)) + '" stroke-linecap="round"/>';
    s += '<g fill="url(#ha-dot-pink80)" style="mix-blend-mode:multiply"><ellipse cx="' + f1(fx - r * 0.36) + '" cy="' + f1(fy + r * 0.12) + '" rx="' + f1(r * 0.12) + '" ry="' + f1(r * 0.08) + '"/><ellipse cx="' + f1(fx + r * 0.36) + '" cy="' + f1(fy + r * 0.12) + '" rx="' + f1(r * 0.12) + '" ry="' + f1(r * 0.08) + '"/></g>';
    s += '<circle r="' + f1(r - 0.5) + '" fill="none" stroke="' + INK.blue + '" stroke-width="1.5" style="mix-blend-mode:multiply" transform="translate(' + dx() + ' ' + dx() + ')"/>';
    return s;
  }

  // ------------------------------------------------------------------ icons (drawn to match each material)
  function iconSound(c, sw) { return '<g fill="none" stroke="' + c + '" stroke-width="' + sw + '" stroke-linecap="round" stroke-linejoin="round"><path d="M-7 -3v6h4l5 4v-14l-5 4z" fill="' + c + '"/><path d="M5 -4.5a6.5 6.5 0 0 1 0 9"/></g>'; }
  function iconMenu(c, sw) { return '<g stroke="' + c + '" stroke-width="' + sw + '" stroke-linecap="round"><path d="M-6.5 -5h13M-6.5 0h13M-6.5 5h13"/></g>'; }
  function crown(c, s) { return '<path d="M' + -s + ' ' + s * 0.55 + 'L' + -s + ' ' + -s * 0.35 + 'L' + -s * 0.5 + ' ' + s * 0.1 + 'L0 ' + -s * 0.6 + 'L' + s * 0.5 + ' ' + s * 0.1 + 'L' + s + ' ' + -s * 0.35 + 'L' + s + ' ' + s * 0.55 + 'Z" fill="' + c + '" stroke-linejoin="round"/>'; }
  // a KO "pow": a small burst
  function burst(r, n, seed) { var R = rng(seed), pts = []; for (var i = 0; i < n * 2; i++) { var a = i / (n * 2) * Math.PI * 2 - Math.PI / 2, rr = i % 2 ? r * (0.5 + R() * 0.12) : r * (0.92 + R() * 0.12); pts.push([Math.cos(a) * rr, Math.sin(a) * rr]); } return 'M' + pts.map(function (p) { return f1(p[0]) + ' ' + f1(p[1]); }).join('L') + 'Z'; }
  function star(r) { var pts = []; for (var i = 0; i < 10; i++) { var a = i / 10 * Math.PI * 2 - Math.PI / 2, rr = i % 2 ? r * 0.45 : r; pts.push([Math.cos(a) * rr, Math.sin(a) * rr]); } return 'M' + pts.map(function (p) { return f1(p[0]) + ' ' + f1(p[1]); }).join('L') + 'Z'; }

  // ------------------------------------------------------------------ data normalisation
  // a fighter's KITS row: given directly, or looked up by tag / name / trenchieId (anchors may carry row as a number)
  function rosterRow(f) {
    if (f && f.row && typeof f.row === 'object' && f.row.paletteIds) return f.row;
    var R = (root.KITS && root.KITS.roster) || (root.ITEMS_API && root.ITEMS_API.ROSTER) || [], k = f && (f.tag || f.name || f.trenchieId);
    return R.filter(function (r) { return r.tag === k || r.name === k || r.trenchieId === k || r.name === (f && f.name); })[0] || {};
  }
  function norm(o) {
    var F = (o.fighters || []).map(function (f, i) {
      var row = rosterRow(f); return { i: i, id: f.id || f.trenchieId || row.trenchieId, x: f.x, y: f.y, row: row, hp: f.hp == null ? 1 : f.hp, tag: f.tag || row.tag || row.name || ('#' + i), kos: f.kos || 0, state: f.state || '', name: f.name || row.name };
    });
    function find(k) { if (k == null) return null; if (typeof k === 'object') return F.filter(function (f) { return f.row === k || f.tag === k.tag; })[0] || { tag: k.tag || k.name, row: k }; var hit = F.filter(function (f) { return f.tag === k || f.name === k || f.row.trenchieId === k || f.row.name === k; })[0]; if (hit) return hit; var rr = rosterRow({ tag: k, name: k, trenchieId: k }); return { tag: rr.tag || String(k), row: rr }; }
    var byKo = F.slice().sort(function (a, b) { return b.kos - a.kos || a.i - b.i; });
    var lead = (o.lead && find(o.lead.tag)) || byKo[0];
    if (lead && o.lead && o.lead.kos != null) lead.kos = Math.max(lead.kos, o.lead.kos);
    byKo = F.slice().sort(function (a, b) { return (b === lead) - (a === lead) || b.kos - a.kos || a.i - b.i; });
    var followed = F.filter(function (f) { return /follow/.test(f.state); })[0] || byKo[1] || F[0];
    var feed = (o.feed || []).map(function (e) { return { kind: e.kind, a: find(e.a), b: find(e.b), item: e.item }; });
    var drop = feed.filter(function (e) { return e.kind === 'drop'; }).pop();
    return { F: F, top: byKo.slice(0, Math.max(1, Math.min(5, o.topN || 3))), lead: lead, followed: followed, feed: feed, drop: drop, w: o.w || 1440, h: o.h || 900, narrow: (o.w || 1440) < 600, concept: o.concept || 'sand', mark: o.mark || '▲' };
  }
  function bodyHex(f) { return C(((f && f.row && f.row.paletteIds) || ['p06'])[0]); }
  function itemName(e) { var it = e.item; if (!it) return 'a legendary'; return typeof it === 'string' ? it : (it.name || it.id || 'a legendary'); }

  // ================================================================== SAND
  var SAND = {
    // the top-3 board: a driftwood plank on two toothpick legs pushed into the sand, three painted portrait chips with
    // painted numbers, a nail at each end, and the leader's cocktail-stick pennant pushed into the plank (one ribbon, U8)
    board: function (D, uid) {
      var n = D.narrow ? 2.4 : 3, r = D.narrow ? 14 : 17, gap = D.narrow ? 46 : 58, padL = D.narrow ? 16 : 20, ph = D.narrow ? 46 : 56;
      var font = '400 ' + (D.narrow ? 21 : 25) + 'px "Lilita One"';
      var cols = D.top.map(function (f) { return 2 * r + 7 + tw(String(f.kos), font); });
      var pw = padL * 2 + cols.reduce(function (a, b) { return a + b; }, 0) + (D.top.length - 1) * (gap - 2 * r - 2) * 0.35 + 6;
      var W = pw + 24, H = ph + 46, ox = 6, oy = 30, s = '';
      // toothpick legs (behind the plank), each with a little sand mound at its foot
      [0.2, 0.8].forEach(function (k, i) {
        var lx = ox + pw * k, top = oy + 8, bot = oy + ph + 14;
        s += '<g filter="url(#ha-cast-sm)"><path d="M' + f1(lx - 2.6) + ' ' + top + 'L' + f1(lx + 2.6) + ' ' + top + 'L' + f1(lx + 1.8) + ' ' + bot + 'L' + f1(lx) + ' ' + (bot + 5) + 'L' + f1(lx - 1.8) + ' ' + bot + 'Z" fill="#E8C98E"/>' +
          '<path d="M' + f1(lx + 0.6) + ' ' + top + 'L' + f1(lx + 2.6) + ' ' + top + 'L' + f1(lx + 1.8) + ' ' + bot + 'L' + f1(lx + 0.4) + ' ' + bot + 'Z" fill="#C9A06A"/></g>';
        s += '<path d="M' + f1(lx - 11) + ' ' + (bot + 3) + 'Q' + f1(lx - 3) + ' ' + (bot - 4) + ' ' + f1(lx + 2) + ' ' + (bot - 1) + 'Q' + f1(lx + 8) + ' ' + (bot - 3) + ' ' + f1(lx + 13) + ' ' + (bot + 3) + 'Z" fill="#E9CF9B"/>' +
          '<path d="M' + f1(lx + 2) + ' ' + (bot - 1) + 'Q' + f1(lx + 8) + ' ' + (bot - 3) + ' ' + f1(lx + 13) + ' ' + (bot + 3) + 'L' + f1(lx + 4) + ' ' + (bot + 3) + 'Z" fill="#C9A675"/>';
      });
      // the plank: an irregular slab, driftwood colour, grain + toon bevel from the filter, then cracks, knots, a split end
      var seed = hash(uid + 'plank');
      var pl = slab(ox, oy, pw, ph, 9, 1.6, seed, 26);
      s += '<g filter="url(#ha-cast-sand)"><path d="' + pl + '" fill="#5A3A22" stroke="#5A3A22" stroke-width="3.2" stroke-linejoin="round"/><path d="' + pl + '" fill="#B98E62" filter="url(#ha-wood)"/></g>';
      var R = rng(seed);
      s += '<g fill="none" stroke="#6E4B2E" stroke-linecap="round" opacity="0.7">' +
        '<path d="M' + f1(ox + pw - 4) + ' ' + f1(oy + ph * 0.62) + 'q-' + f1(pw * 0.08) + ' -2 -' + f1(pw * 0.16) + ' 1" stroke-width="1.3"/>' +
        '<path d="M' + f1(ox + 3) + ' ' + f1(oy + ph * 0.3) + 'q' + f1(pw * 0.05) + ' 1.5 ' + f1(pw * 0.09) + ' -0.5" stroke-width="1.1"/>' +
        '<ellipse cx="' + f1(ox + pw * (0.55 + R() * 0.1)) + '" cy="' + f1(oy + ph * 0.82) + '" rx="5" ry="1.8" stroke-width="1.2"/><ellipse cx="' + f1(ox + pw * (0.55 + R() * 0.1)) + '" cy="' + f1(oy + ph * 0.82) + '" rx="2.2" ry="0.8" stroke-width="1"/></g>';
      // nails: a domed head, rust ring, a lit dot up-left
      [[ox + 8, oy + ph / 2], [ox + pw - 8, oy + ph / 2]].forEach(function (p) {
        s += '<circle cx="' + f1(p[0] + 0.8) + '" cy="' + f1(p[1] + 1) + '" r="3.6" fill="#8B5A33" opacity="0.6"/><circle cx="' + f1(p[0]) + '" cy="' + f1(p[1]) + '" r="2.9" fill="#6D6A66"/><circle cx="' + f1(p[0] - 0.9) + '" cy="' + f1(p[1] - 0.9) + '" r="1.1" fill="#D9D3C8"/>';
      });
      // chips + painted numbers (cream sign paint, dry-brushed)
      var x = ox + padL + 4, cy = oy + ph / 2 + 1, paint = '';
      D.top.forEach(function (f, i) {
        s += '<g transform="translate(' + f1(x + r) + ' ' + f1(cy) + ')">' + chip(f.row, r, 'paint', uid + 'c' + i) + '</g>';
        paint += '<text x="' + f1(x + 2 * r + 5) + '" y="' + f1(cy + (D.narrow ? 7.5 : 9)) + '" font-family=\'"Lilita One"\' font-size="' + (D.narrow ? 21 : 25) + '" fill="#FFF3DA">' + f.kos + '</text>';
        x += cols[i] + (gap - 2 * r - 2) * 0.35;
      });
      s += '<g filter="url(#ha-paint)">' + paint + '</g>';
      s += '<g opacity="0.35" filter="url(#ha-paint)" transform="translate(0.8 1)" style="mix-blend-mode:multiply">' + paint.replace(/#FFF3DA/g, '#5A3B22') + '</g>';
      // the leader's pennant: a cocktail stick pushed into the plank's top edge behind chip 1, a gold swallowtail with a crown
      var px = ox + padL + 4 + r - 2, ptop = 2;
      s += '<g filter="url(#ha-cast-sm)"><path d="M' + f1(px - 1.3) + ' ' + ptop + 'L' + f1(px + 1.3) + ' ' + ptop + 'L' + f1(px + 1.1) + ' ' + (oy + 4) + 'L' + f1(px - 1.1) + ' ' + (oy + 4) + 'Z" fill="#E8C98E"/>' +
        '<circle cx="' + f1(px) + '" cy="' + (ptop) + '" r="2" fill="#E8C98E"/>' +
        '<path d="M' + f1(px + 1.2) + ' ' + (ptop + 2) + 'L' + f1(px + 30) + ' ' + (ptop + 3.5) + 'L' + f1(px + 23) + ' ' + (ptop + 9.5) + 'L' + f1(px + 30) + ' ' + (ptop + 16) + 'L' + f1(px + 1.2) + ' ' + (ptop + 17) + 'Z" fill="#E9B23A" filter="url(#ha-cloth)"/>' +
        '<g transform="translate(' + f1(px + 11.5) + ' ' + (ptop + 10) + ')">' + crown('#7A4E10', 4.6) + '</g></g>';
      return { svg: svg(W, H, s), w: W, h: H, box: [ox, 0, pw + 8, oy + ph + 20] };
    },
    // the lead banner: a cocktail-stick flag laid across — gold cloth wrapped round the stick, a swallowtail, a stitched
    // hem, toon fold bands, painted letters
    banner: function (D, uid, text) {
      var fs = D.narrow ? 26 : 44, font = '400 ' + fs + 'px "Lilita One"', t = text;
      var maxW = D.w * (D.narrow ? 0.8 : 0.42);
      var tws = tw(t, font), bw = tws + (D.narrow ? 54 : 92);
      if (bw > maxW) { t = text.replace(' takes the lead', ' leads'); tws = tw(t, font); bw = tws + (D.narrow ? 54 : 92); }
      var bh = Math.round(fs * 1.38), tail = Math.round(bh * 0.55), stickY = 7, top = stickY + 3, W = bw + tail + 34, H = bh + top + 16;
      var x0 = 14, x1 = x0 + bw, s = '';
      // cloth: a slight sag on the bottom edge, swallowtail on the right, wrapped round the stick at the top
      var sag = 3.5;
      var cloth = 'M' + x0 + ' ' + top + 'L' + x1 + ' ' + top + 'L' + (x1 + tail) + ' ' + (top + 1) + 'L' + f1(x1 + tail * 0.42) + ' ' + f1(top + bh * 0.52) + 'L' + (x1 + tail) + ' ' + (top + bh + 2) + 'L' + x1 + ' ' + (top + bh) + 'Q' + f1((x0 + x1) / 2) + ' ' + f1(top + bh + sag) + ' ' + x0 + ' ' + (top + bh) + 'Z';
      s += '<g filter="url(#ha-cast-sand)"><path d="' + cloth + '" fill="#E9B23A" filter="url(#ha-cloth)"/></g>';
      s += '<path d="' + cloth + '" fill="url(#ha-weave)"/>';
      // fold bands: two soft vertical folds, crisp-edged (toon), darker on the right of each crease
      var R = rng(hash(uid + 'fold'));
      [0.3 + R() * 0.08, 0.7 + R() * 0.06].forEach(function (k) {
        var fx = x0 + bw * k;
        s += '<path d="M' + f1(fx) + ' ' + (top + 3) + 'L' + f1(fx + 10) + ' ' + (top + 3) + 'L' + f1(fx + 7) + ' ' + f1(top + bh) + 'L' + f1(fx - 2) + ' ' + f1(top + bh) + 'Z" fill="#B97C14" opacity="0.22"/>';
        s += '<path d="M' + f1(fx - 6) + ' ' + (top + 3) + 'L' + f1(fx) + ' ' + (top + 3) + 'L' + f1(fx - 2) + ' ' + f1(top + bh) + 'L' + f1(fx - 8) + ' ' + f1(top + bh) + 'Z" fill="#FFF0B0" opacity="0.28"/>';
      });
      // stitched hem near the bottom, and the wrap round the stick (a rolled sleeve with its own shade band)
      s += '<path d="M' + (x0 + 6) + ' ' + f1(top + bh - 5) + 'Q' + f1((x0 + x1) / 2) + ' ' + f1(top + bh - 5 + sag) + ' ' + (x1 + 2) + ' ' + f1(top + bh - 5) + '" fill="none" stroke="#8A5A10" stroke-width="1.3" stroke-dasharray="4 3" opacity="0.7"/>';
      s += '<rect x="' + (x0 - 2) + '" y="' + (stickY - 4) + '" width="' + (bw + 6) + '" height="9" rx="4" fill="#D9A02C"/><rect x="' + (x0 - 2) + '" y="' + (stickY + 1.5) + '" width="' + (bw + 6) + '" height="3.5" rx="1.7" fill="#9E6A12" opacity="0.55"/><rect x="' + x0 + '" y="' + (stickY - 3) + '" width="' + (bw + 2) + '" height="1.8" rx="0.9" fill="#FFF0B0" opacity="0.7"/>';
      // the stick: pale wood, pointed both ends, poking out each side
      s += '<g filter="url(#ha-cast-sm)"><path d="M' + (x0 - 12) + ' ' + stickY + 'L' + (x0 - 2) + ' ' + (stickY - 2.2) + 'L' + (x1 + 22) + ' ' + (stickY - 2.2) + 'L' + (x1 + 32) + ' ' + stickY + 'L' + (x1 + 22) + ' ' + (stickY + 2.2) + 'L' + (x0 - 2) + ' ' + (stickY + 2.2) + 'Z" fill="#EBCB91"/>' +
        '<path d="M' + (x0 - 12) + ' ' + stickY + 'L' + (x0 - 2) + ' ' + (stickY + 0.4) + 'L' + (x1 + 22) + ' ' + (stickY + 0.4) + 'L' + (x1 + 32) + ' ' + stickY + 'L' + (x1 + 22) + ' ' + (stickY + 2.2) + 'L' + (x0 - 2) + ' ' + (stickY + 2.2) + 'Z" fill="#C49A62"/></g>';
      // painted letters, dark brown sign paint with a dry-brush edge
      var ty = top + bh * 0.5 + fs * 0.36, tx = x0 + (bw) / 2 + 2;
      s += '<g filter="url(#ha-paint)"><text x="' + f1(tx) + '" y="' + f1(ty) + '" text-anchor="middle" font-family=\'"Lilita One"\' font-size="' + fs + '" fill="#4A2E12">' + esc(t) + '</text></g>';
      return { svg: svg(W, H, s), w: W, h: H, box: [x0 - 12, 0, bw + tail + 44, H] };
    },
    // the feed: written in the sand with a finger. No panel (U4). Names in the darkened body colour (U6/F1), one icon per
    // line, the older lines half washed by the tide.
    feed: function (D, uid) {
      var lines = D.feed.filter(function (e) { return e.kind !== 'drop' || true; }).slice(-(D.narrow ? 2 : 3));
      var fs = D.narrow ? 16 : 19, lh = Math.round(fs * 1.55), font = '600 ' + fs + 'px "Fredoka"', W = 10, H = lines.length * lh + 10, s = '';
      var g = GROUND.sand;
      lines.forEach(function (e, i) {
        var y = 6 + (i + 1) * lh - lh * 0.32, x = 26, parts = [];
        var age = lines.length - 1 - i, op = [1, 0.86, 0.72][age] || 0.72;
        if (e.kind === 'ko') parts = [[e.a.tag, darkName(bodyHex(e.a), g)], [' KO’d ', '#6A4B2C'], [e.b.tag, darkName(bodyHex(e.b), g)]];
        else parts = [[e.a.tag, darkName(bodyHex(e.a), g)], [' found ', '#6A4B2C'], [itemName(e), '#7A4E10']];
        var icon = e.kind === 'ko' ? '<path d="' + burst(7.5, 7, hash(uid + i)) + '" fill="#8A5A2E"/>' : '<path d="' + star(7.5) + '" fill="#9E6A12"/>';
        s += '<g opacity="' + op + '"><g transform="translate(9 ' + f1(y - fs * 0.34) + ')" filter="url(#ha-engrave)">' + icon + '</g><g filter="url(#ha-engrave)"><text x="' + x + '" y="' + f1(y) + '" font-family=\'"Fredoka"\' font-weight="600" font-size="' + fs + '">';
        parts.forEach(function (p) { s += '<tspan fill="' + p[1] + '">' + esc(p[0]) + '</tspan>'; });
        s += '</text></g></g>';
        W = Math.max(W, x + tw(parts.map(function (p) { return p[0]; }).join(''), font) + 8);
      });
      return { svg: svg(W, H, s), w: W, h: H, box: [0, 0, W, H] };
    },
    // a name tag: a chip of driftwood lying on the sand under the feet, the name painted cream
    tag: function (D, uid, f, lead) {
      var fs = D.narrow ? 13 : 15, font = '400 ' + fs + 'px "Lilita One"', t = f.tag, tw0 = tw(t, font) + (lead ? fs * 1.1 : 0);
      var w = tw0 + 16, h = fs + 9, s = '';
      var tp = slab(1, 1, w, h, 4, 0.8, hash(uid + t), 14);
      s += '<g filter="url(#ha-cast-sm)"><path d="' + tp + '" fill="#5A3A22" stroke="#5A3A22" stroke-width="2.4" stroke-linejoin="round"/><path d="' + tp + '" fill="#B98E62" filter="url(#ha-wood)"/></g>';
      var x = 9;
      if (lead) { s += '<g transform="translate(' + f1(x + fs * 0.4) + ' ' + f1(h / 2 + 1) + ')">' + crown('#F7CF6B', fs * 0.36) + '</g>'; x += fs * 1.0; }
      s += '<g filter="url(#ha-paint)"><text x="' + f1(x) + '" y="' + f1(h / 2 + fs * 0.36 + 1) + '" font-family=\'"Lilita One"\' font-size="' + fs + '" fill="#FFF3DA">' + esc(t) + '</text></g>';
      return { svg: svg(w + 6, h + 6, s), w: w + 6, h: h + 6 };
    },
    // the HP bar for everyone (U5): a short trench dug in the sand, filled with tide water (sea teal), coral when low
    bar: function (D, f) {
      var w = D.narrow ? 30 : 36, h = 6, k = Math.max(0, Math.min(1, f.hp)), low = k < 0.4, s = '';
      s += '<rect x="0" y="0" width="' + w + '" height="' + h + '" rx="3" fill="#C9A675"/>';
      s += '<rect x="0" y="0" width="' + w + '" height="2.2" rx="1.1" fill="#8E6A42" opacity="0.8"/>';
      s += '<rect x="1" y="1.4" width="' + f1((w - 2) * k) + '" height="' + (h - 2.4) + '" rx="2" fill="' + (low ? '#D97A6E' : '#5AB4C8') + '"/>';
      s += '<rect x="1.5" y="1.8" width="' + f1(Math.max(0, (w - 3) * k - 2)) + '" height="1.2" rx="0.6" fill="#FFFFFF" opacity="0.55"/>';
      s += '<path d="M0.5 ' + (h + 0.6) + 'H' + (w - 0.5) + '" stroke="#FFF8EA" stroke-width="1.2" opacity="0.9" stroke-linecap="round"/>';
      return { svg: svg(w, h + 2, s), w: w, h: h + 2 };
    },
    // the legendary drop, at the event: a little gold flag on a toothpick pushed into the sand beside the finder
    drop: function (D, uid, e) {
      var fs = D.narrow ? 13 : 15, font = '400 ' + fs + 'px "Lilita One"', t = itemName(e), w = tw(t, font) + 34, fh = fs + 14, stick = fh + 30, s = '';
      var x0 = 4, top = 4;
      s += '<g filter="url(#ha-cast-sm)"><path d="M' + (x0 - 1.4) + ' ' + top + 'L' + (x0 + 1.4) + ' ' + top + 'L' + (x0 + 1.1) + ' ' + (top + stick) + 'L' + x0 + ' ' + (top + stick + 4) + 'L' + (x0 - 1.1) + ' ' + (top + stick) + 'Z" fill="#E8C98E"/><circle cx="' + x0 + '" cy="' + top + '" r="2.2" fill="#E8C98E"/>';
      s += '<path d="M' + (x0 + 1.3) + ' ' + (top + 2) + 'L' + (x0 + w) + ' ' + (top + 3) + 'Q' + (x0 + w - 6) + ' ' + f1(top + 2 + fh / 2) + ' ' + (x0 + w) + ' ' + (top + fh + 1) + 'L' + (x0 + 1.3) + ' ' + (top + fh + 2) + 'Z" fill="#F7CF6B" filter="url(#ha-cloth)"/></g>';
      s += '<path d="M' + (x0 + 1.3) + ' ' + (top + 2) + 'L' + (x0 + w) + ' ' + (top + 3) + 'Q' + (x0 + w - 6) + ' ' + f1(top + 2 + fh / 2) + ' ' + (x0 + w) + ' ' + (top + fh + 1) + 'L' + (x0 + 1.3) + ' ' + (top + fh + 2) + 'Z" fill="url(#ha-weave)"/>';
      s += '<g transform="translate(' + (x0 + 12) + ' ' + f1(top + 2 + fh / 2) + ')"><path d="' + star(6.5) + '" fill="#B5560E"/></g>';
      s += '<g filter="url(#ha-paint)"><text x="' + (x0 + 22) + '" y="' + f1(top + 2 + fh / 2 + fs * 0.36) + '" font-family=\'"Lilita One"\' font-size="' + fs + '" fill="#4A2E12">' + esc(t) + '</text></g>';
      s += '<path d="M' + (x0 - 8) + ' ' + (top + stick + 4) + 'Q' + x0 + ' ' + (top + stick - 2) + ' ' + (x0 + 9) + ' ' + (top + stick + 4) + 'Z" fill="#E9CF9B"/>';
      return { svg: svg(w + 14, stick + top + 8, s), w: w + 14, h: stick + top + 8, foot: [x0, top + stick + 3] };
    },
    // buttons: toy bottle caps (glossy plastic, crimped rim) with the icon embossed
    button: function (D, uid, kind, i) {
      var r = D.narrow ? 17 : 20, col = i ? '#5AB4C8' : '#D97A6E', s = '', n = 21, pts = [];
      for (var k = 0; k < n * 2; k++) { var a = k / (n * 2) * Math.PI * 2, rr = k % 2 ? r - 1.6 : r; pts.push([r + 2 + Math.cos(a) * rr, r + 2 + Math.sin(a) * rr]); }
      s += '<g filter="url(#ha-cast-sand)"><path d="M' + pts.map(function (p) { return f1(p[0]) + ' ' + f1(p[1]); }).join('L') + 'Z" fill="' + col + '" filter="url(#ha-plastic)"/></g>';
      s += '<circle cx="' + (r + 2) + '" cy="' + (r + 2) + '" r="' + (r - 4.5) + '" fill="' + mix(col, 'p01', 0.12) + '"/>';
      s += '<circle cx="' + (r + 2) + '" cy="' + (r + 2) + '" r="' + (r - 4.5) + '" fill="none" stroke="' + mix(col, 'p01', 0.35) + '" stroke-width="1.2"/>';
      var ic = kind === 'sound' ? iconSound : iconMenu, sc = D.narrow ? 0.85 : 1;
      s += '<g transform="translate(' + (r + 2.8) + ' ' + (r + 2.8) + ') scale(' + sc + ')" opacity="0.55">' + ic(mix(col, 'p01', 0.55), 2.6) + '</g>';
      s += '<g transform="translate(' + (r + 2) + ' ' + (r + 2) + ') scale(' + sc + ')">' + ic('#FFF8EA', 2.6) + '</g>';
      return { svg: svg(2 * r + 10, 2 * r + 10, s), w: 2 * r + 10, h: 2 * r + 10 };
    }
  };

  // ================================================================== RISO
  // Everything is one of three inks (or their overprint), laid with mix-blend-mode multiply, each plate nudged 1-2 px.
  function plate(dx, dy, inner) { return '<g transform="translate(' + dx + ' ' + dy + ')" style="mix-blend-mode:multiply">' + inner + '</g>'; }
  function tape(x, y, w, h, rot, seed) {
    return '<g transform="translate(' + f1(x) + ' ' + f1(y) + ') rotate(' + rot + ')"><path d="' + torn(-w / 2, -h / 2, w, h, seed, 1.4, 'lr') + '" fill="#E9DDB0" fill-opacity="0.82" filter="url(#ha-tape)"/>' +
      '<path d="M' + f1(-w / 2 + 2) + ' ' + f1(-h / 2 + 1.5) + 'H' + f1(w / 2 - 2) + '" stroke="#FFFFFF" stroke-opacity="0.5" stroke-width="1"/></g>';
  }
  var RISO = {
    board: function (D, uid) {
      var r = D.narrow ? 14 : 17, fs = D.narrow ? 26 : 31, font = '400 ' + fs + 'px "Anton"';
      var cols = D.top.map(function (f) { return 2 * r + 6 + tw(String(f.kos), font) + 12; });
      var pw = cols.reduce(function (a, b) { return a + b; }, 0) + 22, ph = 2 * r + 22, ox = 6, oy = 12, s = '';
      // a torn paper scrap, slightly rotated, fibre edge in a lighter paper
      s += '<g transform="rotate(-1.6 ' + f1(ox + pw / 2) + ' ' + f1(oy + ph / 2) + ')">';
      s += '<path d="' + torn(ox - 1, oy - 1, pw + 2, ph + 2, hash(uid + 'f'), 2.2) + '" fill="#FBF8F0"/>';
      s += '<path d="' + torn(ox, oy, pw, ph, hash(uid + 'p'), 1.7) + '" fill="#F6F1E4" filter="url(#ha-paper)"/>';
      // a yellow halftone flood behind the leader, as a highlighter swipe
      s += plate(1, 0, '<path d="' + torn(ox + 8, oy + 6, cols[0] + 2, ph - 12, hash(uid + 'y'), 1.2) + '" fill="url(#ha-dot-yellow80)"/>');
      var x = ox + 12, cy = oy + ph / 2;
      D.top.forEach(function (f, i) {
        s += '<g transform="translate(' + f1(x + r) + ' ' + f1(cy) + ')">' + chip(f.row, r, 'riso', uid + 'c' + i) + '</g>';
        var tx = x + 2 * r + 6, ty = cy + fs * 0.36;
        s += plate(1.6, 1.2, '<text x="' + f1(tx) + '" y="' + f1(ty) + '" font-family="Anton" font-size="' + fs + '" fill="' + INK.pink + '" filter="url(#ha-ink)">' + f.kos + '</text>');
        s += plate(0, 0, '<text x="' + f1(tx) + '" y="' + f1(ty) + '" font-family="Anton" font-size="' + fs + '" fill="' + INK.blue + '" filter="url(#ha-ink)">' + f.kos + '</text>');
        x += cols[i];
      });
      // the leader: a pink rubber stamp, a crown in a circle, pressed at an angle over the scrap's corner
      s += plate(0, 0, '<g transform="translate(' + f1(ox + 13) + ' ' + f1(oy + 2) + ') rotate(-14)" filter="url(#ha-stamp)"><circle r="11" fill="none" stroke="' + INK.pink + '" stroke-width="2.4"/><g transform="translate(0 0.5)">' + crown(INK.pink, 6) + '</g></g>');
      s += '</g>';
      s += tape(ox + pw - 8, oy + 2, 40, 13, 32, hash(uid + 't1'));
      s += tape(ox + 6, oy + ph - 2, 34, 12, 38, hash(uid + 't2'));
      return { svg: svg(pw + 30, ph + 30, s), w: pw + 30, h: ph + 30 };
    },
    // the banner: a condensed headline printed pink + blue (purple where they overlap), on a yellow halftone strip cut
    // with pinking shears, taped down at both ends, a little crooked
    banner: function (D, uid, text) {
      var fs = D.narrow ? 30 : 52, t = text.toUpperCase(), font = '400 ' + fs + 'px "Anton"', tws = tw(t, font), maxW = D.w * (D.narrow ? 0.8 : 0.42);
      if (tws + 60 > maxW) { t = t.replace(' TAKES THE LEAD', ' LEADS'); tws = tw(t, font); }
      var bw = tws + (D.narrow ? 40 : 64), bh = Math.round(fs * 1.28), ox = 18, oy = 12, s = '';
      // pinking-shear edge on top and bottom
      var zig = function (y0, dir) { var d = '', n = Math.round(bw / 7); for (var i = 0; i <= n; i++) d += 'L' + f1(ox + i * bw / n) + ' ' + f1(y0 + (i % 2 ? dir * 3 : 0)); return d; };
      var shape = 'M' + ox + ' ' + oy + zig(oy, -1).slice(0) + 'L' + (ox + bw) + ' ' + (oy + bh) + zig(oy + bh, 1).split('L').reverse().join('L').replace(/L$/, '') + 'Z';
      shape = 'M' + ox + ' ' + oy + zig(oy, -1) + 'L' + (ox + bw) + ' ' + (oy + bh);
      var n = Math.round(bw / 7); for (var i = n; i >= 0; i--) shape += 'L' + f1(ox + i * bw / n) + ' ' + f1(oy + bh + (i % 2 ? 3 : 0));
      shape += 'Z';
      s += '<g transform="rotate(-1.2 ' + f1(ox + bw / 2) + ' ' + f1(oy + bh / 2) + ')">';
      s += '<path d="' + shape + '" fill="' + INK.paper + '"/>';
      s += plate(0, 0, '<path d="' + shape + '" fill="url(#ha-dot-yellow80)"/>');
      s += plate(-1, 1, '<path d="' + shape + '" fill="url(#ha-dot-pink30)" opacity="0.7"/>');
      var tx = ox + bw / 2, ty = oy + bh / 2 + fs * 0.36;
      s += plate(2, 1.5, '<text x="' + f1(tx) + '" y="' + f1(ty) + '" text-anchor="middle" font-family="Anton" font-size="' + fs + '" letter-spacing="0.5" fill="' + INK.pink + '" filter="url(#ha-ink)">' + esc(t) + '</text>');
      s += plate(0, 0, '<text x="' + f1(tx) + '" y="' + f1(ty) + '" text-anchor="middle" font-family="Anton" font-size="' + fs + '" letter-spacing="0.5" fill="' + INK.blue + '" filter="url(#ha-ink)">' + esc(t) + '</text>');
      s += '</g>';
      s += tape(ox + 4, oy + 4, 44, 15, -38, hash(uid + 'a')) + tape(ox + bw - 4, oy + bh - 2, 44, 15, -36, hash(uid + 'b'));
      return { svg: svg(bw + ox * 2 + 10, bh + oy * 2 + 8, s), w: bw + ox * 2 + 10, h: bh + oy * 2 + 8 };
    },
    // the feed: printed lines, no panel. Names in blue ink over a highlighter swipe in their own overprint; the KO is a
    // pink rubber stamp; the newest at the bottom; older lines printed lighter (a fading drum)
    feed: function (D, uid) {
      var lines = D.feed.slice(-(D.narrow ? 2 : 3)), fs = D.narrow ? 16 : 19, lh = Math.round(fs * 1.6), font = '700 ' + fs + 'px "Archivo Narrow"', s = '', W = 10;
      lines.forEach(function (e, i) {
        var y = 4 + (i + 1) * lh - lh * 0.3, x = 2, age = lines.length - 1 - i, op = [1, 0.86, 0.72][age] || 0.72;
        var g = '<g opacity="' + op + '">';
        function name(f) {
          var w = tw(f.tag, font), ink = inkFor(bodyHex(f)), sw = '';
          // the name's colour as an underline swipe (Armello's clan underline), each ink its own plate
          ink.inks.forEach(function (k, j) { sw += plate(j * 1.2, j * 0.6, '<path d="M' + f1(x - 1) + ' ' + f1(y + 2.6) + 'L' + f1(x + w + 1) + ' ' + f1(y + 1.8) + 'L' + f1(x + w) + ' ' + f1(y + 5.4) + 'L' + f1(x - 1.5) + ' ' + f1(y + 5.8) + 'Z" fill="' + INK[k] + '"/>'); });
          sw += plate(0, 0, '<text x="' + f1(x) + '" y="' + f1(y) + '" font-family=\'"Archivo Narrow"\' font-weight="700" font-size="' + fs + '" fill="' + INK.blue + '">' + esc(f.tag) + '</text>');
          x += w + 7; return sw;
        }
        g += name(e.a);
        if (e.kind === 'ko') {
          var sw2 = fs * 1.75;
          g += plate(0, 0, '<g transform="translate(' + f1(x + sw2 / 2) + ' ' + f1(y - fs * 0.33) + ') rotate(' + (i % 2 ? 4 : -5) + ')" filter="url(#ha-stamp-sm)"><rect x="' + f1(-sw2 / 2) + '" y="' + f1(-fs * 0.6) + '" width="' + f1(sw2) + '" height="' + f1(fs * 1.2) + '" rx="2" fill="' + INK.pink + '"/><text y="' + f1(fs * 0.38) + '" text-anchor="middle" font-family="Anton" font-size="' + f1(fs * 1.02) + '" letter-spacing="0.5" fill="' + INK.paper + '">KO</text></g>');
          x += sw2 + 7; g += name(e.b);
        } else {
          var t = 'got ', w2 = tw(t, font);
          g += plate(0, 0, '<text x="' + f1(x) + '" y="' + f1(y) + '" font-family=\'"Archivo Narrow"\' font-weight="500" font-size="' + fs + '" fill="' + INK.blue + '">' + t + '</text>'); x += w2;
          var it = itemName(e), w3 = tw(it, font);
          g += plate(1, 1, '<rect x="' + f1(x - 3) + '" y="' + f1(y - fs * 0.78) + '" width="' + f1(w3 + 6) + '" height="' + f1(fs * 0.98) + '" fill="' + INK.yellow + '"/>');
          g += plate(0, 0, '<text x="' + f1(x) + '" y="' + f1(y) + '" font-family=\'"Archivo Narrow"\' font-weight="700" font-size="' + fs + '" fill="' + INK.blue + '">' + esc(it) + '</text>'); x += w3 + 4;
        }
        s += g + '</g>'; W = Math.max(W, x + 6);
      });
      return { svg: svg(W, lines.length * lh + 10, s), w: W, h: lines.length * lh + 10 };
    },
    tag: function (D, uid, f, lead) {
      var fs = D.narrow ? 13 : 15, font = '700 ' + fs + 'px "Archivo Narrow"', w = tw(f.tag, font) + (lead ? fs : 0) + 18, h = fs + 8, s = '';
      s += '<path d="' + torn(2, 2, w, h, hash(uid + f.tag), 1.3, 'lr') + '" fill="#E9DDB0" fill-opacity="0.9" filter="url(#ha-tape)"/>';
      var x = 10;
      if (lead) { s += plate(0, 0, '<g transform="translate(' + f1(x + fs * 0.35) + ' ' + f1(2 + h / 2) + ')">' + crown(INK.pink, fs * 0.36) + '</g>'); x += fs * 0.95; }
      s += plate(0, 0, '<text x="' + f1(x) + '" y="' + f1(2 + h / 2 + fs * 0.36) + '" font-family=\'"Archivo Narrow"\' font-weight="700" font-size="' + fs + '" fill="' + INK.blue + '">' + esc(f.tag) + '</text>');
      return { svg: svg(w + 4, h + 4, s), w: w + 4, h: h + 4 };
    },
    bar: function (D, f) {
      var w = D.narrow ? 30 : 36, h = 6, k = Math.max(0, Math.min(1, f.hp)), low = k < 0.4, s = '';
      s += plate(0, 0, '<rect x="0.5" y="0.5" width="' + (w - 1) + '" height="' + (h - 1) + '" fill="none" stroke="' + INK.blue + '" stroke-width="1"/>');
      if (low) s += plate(0.6, 0, '<rect x="1.5" y="1.5" width="' + f1((w - 3) * k) + '" height="' + (h - 3) + '" fill="' + INK.pink + '"/>');
      else s += plate(0.8, 0.3, '<rect x="1.5" y="1.5" width="' + f1((w - 3) * k) + '" height="' + (h - 3) + '" fill="' + INK.yellow + '"/>') + plate(0, 0, '<rect x="1.5" y="1.5" width="' + f1((w - 3) * k) + '" height="' + (h - 3) + '" fill="url(#ha-dot-blue80)"/>');
      return { svg: svg(w + 2, h + 2, s), w: w + 2, h: h + 2 };
    },
    // the drop: a starburst sticker, yellow solid + pink halftone, the item in blue, "LEGENDARY!" in pink
    drop: function (D, uid, e) {
      var fs = D.narrow ? 14 : 17, it = itemName(e).toUpperCase(), w = Math.max(tw(it, '400 ' + fs + 'px "Anton"'), 60) + 34, R0 = w / 2, s = '';
      var cx = R0 + 4, cy = R0 * 0.62 + 4, n = 16, pts = [], Rr = rng(hash(uid + 'burst'));
      for (var i = 0; i < n * 2; i++) { var a = i / (n * 2) * Math.PI * 2, rr = i % 2 ? 0.8 : 1 + Rr() * 0.06; pts.push([cx + Math.cos(a) * R0 * rr, cy + Math.sin(a) * R0 * 0.62 * rr]); }
      var d = 'M' + pts.map(function (p) { return f1(p[0]) + ' ' + f1(p[1]); }).join('L') + 'Z';
      s += '<path d="' + d + '" fill="#FBF8F0" transform="translate(1.5 1.5)" opacity="0.9"/>';
      s += plate(0, 0, '<path d="' + d + '" fill="' + INK.yellow + '"/>') + plate(-1.5, 1.2, '<path d="' + d + '" fill="none" stroke="' + INK.pink + '" stroke-width="1.6"/>');
      var lw = tw('LEGENDARY', '400 ' + f1(fs * 0.62) + 'px "Anton"') + 10;
      s += plate(0.8, 0.6, '<g transform="translate(' + f1(cx) + ' ' + f1(cy - fs * 0.5) + ') rotate(-4)" filter="url(#ha-stamp-sm)"><rect x="' + f1(-lw / 2) + '" y="' + f1(-fs * 0.42) + '" width="' + f1(lw) + '" height="' + f1(fs * 0.84) + '" rx="1.5" fill="' + INK.pink + '"/><text y="' + f1(fs * 0.24) + '" text-anchor="middle" font-family="Anton" font-size="' + f1(fs * 0.62) + '" letter-spacing="1" fill="' + INK.yellow + '">LEGENDARY</text></g>');
      s += plate(0, 0, '<text x="' + f1(cx) + '" y="' + f1(cy + fs * 0.78) + '" text-anchor="middle" font-family="Anton" font-size="' + fs + '" fill="' + INK.blue + '">' + esc(it) + '</text>');
      // a pointer down to the finder, drawn as a pen line in blue
      s += plate(0, 0, '<path d="M' + f1(cx - R0 * 0.35) + ' ' + f1(cy + R0 * 0.5) + 'q-6 14 -14 22" fill="none" stroke="' + INK.blue + '" stroke-width="1.6" stroke-linecap="round"/>');
      var W = 2 * R0 + 12, H = R0 * 1.24 + 34;
      return { svg: svg(W, H, s), w: W, h: H, foot: [cx - R0 * 0.35 - 14, cy + R0 * 0.5 + 22] };
    },
    button: function (D, uid, kind, i) {
      var r = D.narrow ? 17 : 20, s = '', cx = r + 3, cy = r + 3;
      s += '<circle cx="' + (cx + 1.5) + '" cy="' + (cy + 1.5) + '" r="' + r + '" fill="#FBF8F0"/>';
      s += plate(0, 0, '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="' + (i ? INK.blue : INK.pink) + '" filter="url(#ha-ink)"/>');
      s += plate(1.4, -1, '<circle cx="' + cx + '" cy="' + cy + '" r="' + (r - 3) + '" fill="url(#ha-dot-yellow55)"/>');
      var ic = kind === 'sound' ? iconSound : iconMenu;
      s += '<g transform="translate(' + cx + ' ' + cy + ')">' + ic(INK.paper, 2.6) + '</g>';
      return { svg: svg(2 * r + 8, 2 * r + 8, s), w: 2 * r + 8, h: 2 * r + 8 };
    }
  };

  // ================================================================== CANDLE
  var GREEN = '#2E8B6A', RED = '#C2453A', THERM = '#F7F0DC', INKD = '#2A2622';
  // twisted cord: a dark core, a light twist dashed over it, sagging between two points
  function cord(x0, y0, x1, y1, sag) {
    var d = 'M' + f1(x0) + ' ' + f1(y0) + 'Q' + f1((x0 + x1) / 2) + ' ' + f1((y0 + y1) / 2 + sag) + ' ' + f1(x1) + ' ' + f1(y1);
    return '<path d="' + d + '" fill="none" stroke="#6E5236" stroke-width="2" stroke-linecap="round"/><path d="' + d + '" fill="none" stroke="#D2AE7E" stroke-width="1.3" stroke-dasharray="1.3 1.7" stroke-linecap="round"/>';
  }
  // chipped enamel: a few flecks where the enamel broke off and the metal shows
  function flecks(w, h, seed) {
    var R = rng(seed), o = '';
    for (var i = 0; i < 3; i++) { var x = (i === 0 ? 0.3 : 0.55 + R() * 0.4) * w, y = (R() < 0.5 ? 0.12 : 0.86) * h, r = 0.9 + R() * 1.2; o += '<path d="M' + f1(x - r) + ' ' + f1(y) + 'l' + f1(r * 0.8) + ' ' + f1(-r * 0.7) + 'l' + f1(r * 1.3) + ' ' + f1(r * 0.4) + 'l' + f1(-r * 0.6) + ' ' + f1(r * 0.9) + 'z" fill="#B9B4AA"/><path d="M' + f1(x - r * 0.4) + ' ' + f1(y - r * 0.3) + 'l' + f1(r * 0.6) + ' 0" stroke="#FFFFFF" stroke-width="0.6" opacity="0.8"/>'; }
    return o;
  }
  function tagShape(w, h) { var c = h * 0.42; return 'M' + c + ' 0H' + w + 'V' + h + 'H' + c + 'L0 ' + f1(h / 2) + 'Z'; }
  // dot-matrix text with the I cells closed up (review M1: DotGothic16 is monospaced in Latin, so "SA I LOR"); {markup, w}
  var I_PULL = 0.17;
  function dotText(t, fs) {
    var out = '', pull = 0;
    for (var i = 0; i < t.length; i++) {
      var ch = t[i], dx = 0;
      if (ch === 'I') dx -= I_PULL; if (i > 0 && t[i - 1] === 'I') dx -= I_PULL;
      pull += -dx;
      out += dx ? '<tspan dx="' + f1(dx * fs) + '">' + esc(ch) + '</tspan>' : esc(ch);
    }
    return { markup: out, w: tw(t, '400 ' + fs + 'px "DotGothic16"') - pull * fs };
  }
  function woodBanner(D, uid, text) {
    var fs = D.narrow ? 21 : 46, font = '400 ' + fs + 'px "Lilita One"', t = text, maxW = D.w * (D.narrow ? 0.8 : 0.42);
    var pen = Math.round(fs * 1.25), tws = tw(t, font), pw = tws + pen + (D.narrow ? 34 : 56);
    if (pw > maxW) { t = text.replace(' takes the lead', ' leads'); tws = tw(t, font); pw = tws + pen + (D.narrow ? 34 : 56); }
    var ph = Math.round(fs * 1.42), ox = 8, oy = D.narrow ? 14 : 22, s = '', seed = hash(uid + 'sign');
    // the cords run up off the top of the screen, knotted through two holes in the plank
    var hx = [ox + pw * 0.14, ox + pw * 0.86];
    s += '<g filter="url(#ha-cast-sea-sm)">' + cord(hx[0] - 6, -oy - 40, hx[0], oy + 6, 0) + cord(hx[1] + 6, -oy - 40, hx[1], oy + 6, 0) + '</g>';
    var pl = slab(ox, oy, pw, ph, 8, 1.4, seed, 28);
    s += '<g filter="url(#ha-cast-sea)"><path d="' + pl + '" fill="#4A3220" stroke="#4A3220" stroke-width="3.2" stroke-linejoin="round"/><path d="' + pl + '" fill="#B98E62" filter="url(#ha-wood-gold)"/></g>';
    var R = rng(seed);
    s += '<g fill="none" stroke="#6E4B2E" stroke-linecap="round" opacity="0.6"><path d="M' + f1(ox + pw - 3) + ' ' + f1(oy + ph * 0.7) + 'q-' + f1(pw * 0.05) + ' -2 -' + f1(pw * 0.1) + ' 1" stroke-width="1.3"/>' +
      '<ellipse cx="' + f1(ox + pw * (0.3 + R() * 0.4)) + '" cy="' + f1(oy + ph * 0.84) + '" rx="5" ry="1.6" stroke-width="1.1"/></g>';
    // the holes, with the cord knot sitting on the plank face
    hx.forEach(function (x) { s += '<circle cx="' + f1(x) + '" cy="' + f1(oy + 7) + '" r="3.4" fill="#2E2016"/><path d="M' + f1(x - 3.2) + ' ' + f1(oy + 5) + 'q3.2 4.5 6.4 0" fill="none" stroke="#6E5236" stroke-width="2.4" stroke-linecap="round"/><path d="M' + f1(x - 2.6) + ' ' + f1(oy + 5.4) + 'q2.6 3.4 5.2 0" fill="none" stroke="#D2AE7E" stroke-width="1" stroke-dasharray="1.2 1.4"/>'; });
    // the gold pennant, swallow-tailed, pinned over the left end, a crown painted on it
    var px = ox + 12, py = oy + ph * 0.5, pwid = pen, phh = Math.round(fs * 0.9);
    var pd = 'M' + f1(px) + ' ' + f1(py - phh / 2) + 'H' + f1(px + pwid) + 'L' + f1(px + pwid - phh * 0.32) + ' ' + f1(py) + 'L' + f1(px + pwid) + ' ' + f1(py + phh / 2) + 'H' + f1(px) + 'Z';
    s += '<g filter="url(#ha-cast-sea-sm)"><path d="' + pd + '" fill="#E9B23A" filter="url(#ha-cloth)"/></g><path d="' + pd + '" fill="url(#ha-weave)"/>';
    s += '<g transform="translate(' + f1(px + pwid * 0.42) + ' ' + f1(py + 1) + ')">' + crown('#7A4E10', fs * 0.2) + '</g>';
    s += '<circle cx="' + f1(px + 4) + '" cy="' + f1(py) + '" r="2.4" fill="#6D6A66"/><circle cx="' + f1(px + 3.3) + '" cy="' + f1(py - 0.7) + '" r="0.9" fill="#E6E0D4"/>';
    // clean sign-paint lettering: cream paint with a thin painted shadow, no distress (Pat: "too distressed")
    var tx = px + pwid + (pw - (px - ox) - pwid - tws) / 2, ty = oy + ph / 2 + fs * 0.35;
    s += '<text x="' + f1(tx + 1.4) + '" y="' + f1(ty + 2) + '" font-family=\'"Lilita One"\' font-size="' + fs + '" fill="#3A2616" opacity="0.55">' + esc(t) + '</text>';
    s += '<text x="' + f1(tx) + '" y="' + f1(ty) + '" font-family=\'"Lilita One"\' font-size="' + fs + '" fill="#FFF4DC">' + esc(t) + '</text>';
    return { svg: svg(pw + ox * 2 + 10, ph + oy + 14, s), w: pw + ox * 2 + 10, h: ph + oy + 14 };
  }
  var CANDLE = {
    // the top 3: enamel price tags hung on a string; each a chip + ▲ count; the leader's tag green with a gold ATH ribbon
    board: function (D, uid) {
      var r = D.narrow ? 12 : 14, fs = D.narrow ? 17 : 20, font = '700 ' + fs + 'px "Space Mono"', s = '', x = 14, th = 2 * r + 12, tops = [];
      var items = D.top.map(function (f, i) { var w = th * 0.42 + 2 * r + 12 + tw(D.mark + f.kos, font) + 10; return { f: f, w: w }; });   // the mark: ▲ KOs, or ✓ correct predictions
      var W = items.reduce(function (a, b) { return a + b.w + 10; }, 0) + 20, sy = 6;
      // the string, sagging between nails
      s += '<g filter="url(#ha-cast-sea-sm)">' + cord(4, sy, W - 4, sy, 20) + '</g>';
      s += '<circle cx="4" cy="' + sy + '" r="2.4" fill="#5E646C"/><circle cx="' + (W - 4) + '" cy="' + sy + '" r="2.4" fill="#5E646C"/>';
      items.forEach(function (it, i) {
        var f = it.f, lead = i === 0, ty = sy + 16 + (i === 1 ? 3 : 0), col = lead ? '#9FDCC5' : '#F7F0DC', rim = lead ? '#3E8E73' : '#9A8F7C';
        var sag = sy + 10 * (1 - Math.pow((x + 8) / (W / 2) - 1, 2));
        s += '<g filter="url(#ha-cast-sea-sm)">' + cord(x + 8, sag, x + th * 0.42 * 0.55, ty + th / 2 - 1, 2) + '</g>';
        s += '<g' + (f.id ? ' data-fighter-id="' + esc(f.id) + '"' : '') + ' data-tile-width="' + f1(it.w) + '" data-tile-height="' + f1(th) + '" transform="translate(' + f1(x) + ' ' + f1(ty) + ') rotate(' + (i === 1 ? 3 : i === 2 ? -2.5 : -1) + ' 0 ' + f1(th / 2) + ')" filter="url(#ha-cast-sea-sm)">';
        s += '<path d="' + tagShape(it.w, th) + '" fill="' + rim + '" filter="url(#ha-enamel)"/>';
        s += '<path d="' + tagShape(it.w, th) + '" transform="translate(2.2 2.2) scale(' + f1((it.w - 4.4) / it.w * 1000) / 1000 + ' ' + f1((th - 4.4) / th * 1000) / 1000 + ')" fill="' + col + '" filter="url(#ha-enamel)"/>';
        s += flecks(it.w, th, hash(uid + 'f' + i));
        s += '<circle cx="' + f1(th * 0.42 * 0.55) + '" cy="' + f1(th / 2) + '" r="3.6" fill="#D9D3C8" stroke="#8A8378" stroke-width="1.2"/><circle cx="' + f1(th * 0.42 * 0.55) + '" cy="' + f1(th / 2) + '" r="1.6" fill="#6E5236"/><path d="M' + f1(th * 0.42 * 0.55 - 1.5) + ' ' + f1(th / 2 - 1.5) + 'l3 3" stroke="#D2AE7E" stroke-width="1.2"/>';
        s += '<g transform="translate(' + f1(th * 0.42 + r + 4) + ' ' + f1(th / 2) + ')">' + chip(f.row, r, 'enamel', uid + 'c' + i) + '</g>';
        s += '<text x="' + f1(th * 0.42 + 2 * r + 10) + '" y="' + f1(th / 2 + fs * 0.36) + '" font-family=\'"Space Mono"\' font-weight="700" font-size="' + fs + '" fill="' + (lead ? '#1F5E4A' : INKD) + '"><tspan fill="' + GREEN + '" font-size="' + f1(fs * 0.8) + '">' + D.mark + '</tspan>' + f.kos + '</text>';
        if (lead) {   // the ATH ribbon: gold foil folded over the tag's top edge
          var rx = it.w - 34;
          s += '<path d="M' + rx + ' -3H' + (rx + 26) + 'V' + 9 + 'L' + (rx + 13) + ' 5L' + rx + ' 9Z" fill="#E9B23A" filter="url(#ha-cloth)"/><text x="' + (rx + 13) + '" y="3.6" text-anchor="middle" font-family=\'"Space Mono"\' font-weight="700" font-size="7.5" fill="#5A3A0A">ATH</text>';
        }
        s += '</g>';
        x += it.w + 10;
      });
      return { svg: svg(W + 8, sy + th + 30, s), w: W + 8, h: sy + th + 30 };
    },
    banner: function (D, uid, text) { return woodBanner(D, uid, text); },
    // (v3, retired by Pat 17:2x "too distressed"): a strip of ticker tape, curled at both ends, dot-matrix print
    tickerBanner: function (D, uid, text) {
      var fs = D.narrow ? 24 : 40, t = text.toUpperCase(), font = '400 ' + fs + 'px "DotGothic16"', tws = tw(t, font), maxW = D.w * (D.narrow ? 0.8 : 0.42);
      if (tws + 120 > maxW) { t = t.replace(' TAKES THE LEAD', ' LEADS'); tws = tw(t, font); }
      var mark = '▲ ', mw = tw(mark, font), bw = tws + mw + (D.narrow ? 40 : 60), bh = Math.round(fs * 1.45), curl = Math.round(bh * 0.42), ox = curl + 8, oy = 6, s = '';
      // curled ends: the paper rolls back on itself; the inside of the roll is in shade
      [[ox, -1], [ox + bw, 1]].forEach(function (c) {
        var x = c[0], d = c[1];
        s += '<path d="M' + x + ' ' + oy + 'q' + f1(d * curl * 1.1) + ' ' + f1(bh * 0.15) + ' ' + f1(d * curl * 0.9) + ' ' + f1(bh * 0.55) + 'q' + f1(-d * curl * 0.2) + ' ' + f1(bh * 0.4) + ' ' + f1(-d * curl * 0.9) + ' ' + f1(bh * 0.45) + 'Z" fill="url(#ha-curl' + (d < 0 ? 'L' : 'R') + ')" filter="url(#ha-cast-sea-sm)"/>';
        s += '<path d="M' + x + ' ' + (oy + bh) + 'q' + f1(d * curl * 0.7) + ' -2 ' + f1(d * curl * 0.9) + ' ' + f1(-bh * 0.45) + '" fill="none" stroke="#B8AC8C" stroke-width="1.2"/>';
      });
      s += '<g filter="url(#ha-cast-sea)"><rect x="' + ox + '" y="' + oy + '" width="' + bw + '" height="' + bh + '" fill="' + THERM + '" filter="url(#ha-therm)"/></g>';
      s += '<rect x="' + ox + '" y="' + oy + '" width="' + bw + '" height="3" fill="#FFFFFF" opacity="0.7"/><rect x="' + ox + '" y="' + (oy + bh - 3) + '" width="' + bw + '" height="3" fill="#D9CFB4" opacity="0.8"/>';
      // perforation + a faint green-bar band (the old fan-fold printer paper)
      s += '<path d="M' + (ox + 8) + ' ' + (oy + 6) + 'H' + (ox + bw - 8) + '" stroke="#B8AC8C" stroke-width="1.2" stroke-dasharray="1.5 3.5"/>';
      s += '<rect x="' + ox + '" y="' + f1(oy + bh * 0.58) + '" width="' + bw + '" height="' + f1(bh * 0.3) + '" fill="#9FDCC5" opacity="0.18"/>';
      var dt = dotText(t, fs), tx = ox + (bw - dt.w - mw) / 2, ty = oy + bh / 2 + fs * 0.4;
      s += '<g filter="url(#ha-thermal)"><text x="' + f1(tx) + '" y="' + f1(ty) + '" font-family="DotGothic16" font-size="' + fs + '" fill="' + INKD + '"><tspan fill="' + GREEN + '">' + mark + '</tspan>' + dt.markup + '</text></g>';
      s += '<rect x="' + ox + '" y="' + oy + '" width="' + bw + '" height="' + bh + '" fill="url(#ha-fade)"/>';
      // a faint "TX" stamp (research M3), off-register, in red
      s += '<g transform="translate(' + f1(tx + mw * 0.3) + ' ' + f1(oy + bh - 6) + ') rotate(-8)" opacity="0.55" filter="url(#ha-stamp)"><rect x="-15" y="-9" width="30" height="14" rx="2" fill="none" stroke="' + RED + '" stroke-width="1.4"/><text y="2" text-anchor="middle" font-family=\'"Space Mono"\' font-weight="700" font-size="9" fill="' + RED + '">TX OK</text></g>';
      return { svg: svg(bw + ox * 2, bh + oy * 2 + 8, s), w: bw + ox * 2, h: bh + oy * 2 + 8 };
    },
    // the feed: a ticker, no panel. Mono text with tabular numerals; names dark fills; a red ▼ for a KO, a gold ◆ for a drop
    feed: function (D, uid) {
      var lines = D.feed.slice(-(D.narrow ? 2 : 3)), fs = D.narrow ? 16 : 17, lh = Math.round(fs * 1.7), font = '700 ' + fs + 'px "Space Mono"', s = '', W = 10, g = GROUND.candle;
      lines.forEach(function (e, i) {
        var y = 4 + (i + 1) * lh - lh * 0.32, age = lines.length - 1 - i, op = [1, 0.86, 0.72][age] || 0.72;
        var parts = e.kind === 'ko' ? [[e.a.tag, darkName(bodyHex(e.a), g, NAME_T), 1], [' ▼ ', RED], ['KO ', INKD], [e.b.tag, darkName(bodyHex(e.b), g, NAME_T), 1]]
          : [[e.a.tag, darkName(bodyHex(e.a), g, NAME_T), 1], [' ◆ ', '#9E6A12'], ['FILL ', INKD], [itemName(e), '#6A420C']];
        // names stay solid on every line (review M2); only the verb and item fade with age (U6)
        s += '<text x="2" y="' + f1(y) + '" font-family=\'"Space Mono"\' font-weight="700" font-size="' + fs + '" style="paint-order:stroke" stroke="#FFF8E6" stroke-width="3" stroke-opacity="0.7" stroke-linejoin="round">';
        parts.forEach(function (p) { s += '<tspan fill="' + p[1] + '"' + (p[2] ? ' data-nm="1"' : ' fill-opacity="' + op + '"') + '>' + esc(p[0]) + '</tspan>'; });
        s += '</text>';
        W = Math.max(W, 8 + tw(parts.map(function (p) { return p[0]; }).join(''), font));
      });
      return { svg: svg(W, lines.length * lh + 10, s), w: W, h: lines.length * lh + 10 };
    },
    tag: function (D, uid, f, lead) {
      var fs = D.narrow ? 15 : 17, font = '700 ' + fs + 'px "Space Mono"', h = fs + 10, w = h * 0.42 + tw(f.tag, font) + (lead ? fs : 0) + 14, s = '';
      s += '<g filter="url(#ha-cast-sea-sm)"><path d="' + tagShape(w, h) + '" fill="' + (lead ? '#3E8E73' : '#9A8F7C') + '" filter="url(#ha-enamel)"/>';
      s += '<path d="' + tagShape(w, h) + '" transform="translate(1.6 1.6) scale(' + f1((w - 3.2) / w * 1000) / 1000 + ' ' + f1((h - 3.2) / h * 1000) / 1000 + ')" fill="' + (lead ? '#9FDCC5' : THERM) + '"/></g>';
      s += '<circle cx="' + f1(h * 0.42 * 0.6) + '" cy="' + f1(h / 2) + '" r="2" fill="#BFE6EA" stroke="#8A8378" stroke-width="1"/>';
      var x = h * 0.42 + 4;
      if (lead) { s += '<g transform="translate(' + f1(x + fs * 0.4) + ' ' + f1(h / 2 + 0.5) + ')">' + crown('#B07A12', fs * 0.36) + '</g>'; x += fs * 0.95; }
      s += '<text data-nm="1" x="' + f1(x) + '" y="' + f1(h / 2 + fs * 0.36) + '" font-family=\'"Space Mono"\' font-weight="700" font-size="' + fs + '" fill="' + INKD + '">' + esc(f.tag) + '</text>';
      return { svg: svg(w + 4, h + 4, s), w: w + 4, h: h + 4 };
    },
    // HP as a candlestick lying on its side: a body (green, red when low) with a wick at each end
    bar: function (D, f) {
      var w = D.narrow ? 30 : 36, h = 6, k = Math.max(0, Math.min(1, f.hp)), low = k < 0.4, s = '', bw = Math.max(3, (w - 8) * k);
      s += '<path d="M0 ' + h / 2 + 'H' + w + '" stroke="' + INKD + '" stroke-width="1.2" opacity="0.55"/>';
      s += '<rect x="4" y="0" width="' + f1(w - 8) + '" height="' + h + '" fill="none" stroke="' + INKD + '" stroke-opacity="0.25" stroke-width="1"/>';
      s += '<rect x="4" y="0" width="' + f1(bw) + '" height="' + h + '" fill="' + (low ? RED : GREEN) + '"/><rect x="4" y="0.6" width="' + f1(bw) + '" height="1.6" fill="#FFFFFF" opacity="0.4"/>';
      return { svg: svg(w, h + 1, s), w: w, h: h + 1 };
    },
    // the drop: a till receipt (research M3), torn zigzag at the bottom, dot-matrix lines, pinned at the event
    drop: function (D, uid, e) {
      var fs = D.narrow ? 11 : 12.5, it = itemName(e).toUpperCase(), lines = ['** LEGENDARY **', it, 'QTY 1   #' + ('00' + (hash(it) % 997)).slice(-3)];
      var w = Math.max.apply(null, lines.map(function (l) { return tw(l, '400 ' + fs + 'px "Space Mono"'); })) + 22, lh = fs * 1.35, h = lines.length * lh + 16, s = '';
      var n = Math.round(w / 6), d = 'M0 0H' + f1(w) + 'V' + f1(h);
      for (var i = n; i >= 0; i--) d += 'L' + f1(i * w / n) + ' ' + f1(h + (i % 2 ? 4 : 0));
      d += 'Z';
      s += '<g transform="translate(6 4) rotate(2)"><g filter="url(#ha-cast-sea)"><path d="' + d + '" fill="' + THERM + '" filter="url(#ha-therm)"/></g>';
      s += '<g filter="url(#ha-thermal)">';
      lines.forEach(function (l, j) { s += '<text x="' + f1(w / 2) + '" y="' + f1(10 + (j + 0.8) * lh) + '" text-anchor="middle" font-family=\'"Space Mono"\' font-weight="' + (j === 1 ? 700 : 400) + '" font-size="' + f1(j === 1 ? fs * 1.15 : fs) + '" fill="' + (j === 0 ? '#9E6A12' : INKD) + '">' + esc(l) + '</text>'; });
      s += '</g><path d="M6 ' + f1(10 + lh * 1.1) + 'H' + f1(w - 6) + '" stroke="' + INKD + '" stroke-dasharray="2 2" stroke-width="0.8" opacity="0.5"/>';
      s += '<circle cx="' + f1(w / 2) + '" cy="-1" r="3.2" fill="#C2453A"/><circle cx="' + f1(w / 2 - 1) + '" cy="-2" r="1.1" fill="#FFFFFF" opacity="0.7"/></g>';
      return { svg: svg(w + 16, h + 16, s), w: w + 16, h: h + 16, foot: [w / 2, h + 12] };
    },
    button: function (D, uid, kind, i) {
      var r = D.narrow ? 16 : 19, s = '', c = r + 3;
      s += '<g filter="url(#ha-cast-sea)"><circle cx="' + c + '" cy="' + c + '" r="' + r + '" fill="#9A8F7C" filter="url(#ha-enamel)"/><circle cx="' + c + '" cy="' + c + '" r="' + (r - 3) + '" fill="' + (i ? '#F6A796' : '#9FDCC5') + '" filter="url(#ha-enamel)"/></g>';
      var ic = kind === 'sound' ? iconSound : iconMenu;
      s += '<g transform="translate(' + c + ' ' + c + ') scale(' + (D.narrow ? 0.85 : 0.95) + ')">' + ic(INKD, 2.4) + '</g>';
      return { svg: svg(2 * c + 4, 2 * c + 4, s), w: 2 * c + 4, h: 2 * c + 4 };
    }
  };

  // receipt paper: a strip with a perforated top and a zigzag-torn bottom
  function receipt(w, h, seed) {
    var n = Math.max(4, Math.round(w / 6)), d = 'M0 0H' + f1(w) + 'V' + f1(h);
    for (var i = n; i >= 0; i--) d += 'L' + f1(i * w / n) + ' ' + f1(h + (i % 2 ? 4 : 0));
    return d + 'Z';
  }
  var CANDLE_B = Object.assign({}, CANDLE, {
    // the top 3 as a till receipt (a two-column ledger): chip, name, dotted leader, right-aligned count; the leader
    // stamped ATH in red; a perforated top, a torn bottom
    board: function (D, uid) {
      var r = D.narrow ? 12 : 11, fs = D.narrow ? 16 : 14, font = '700 ' + fs + 'px "Space Mono"', lh = 2 * r + 8, s = '';
      // on the phone the ledger prints ticker symbols (SAIL, BANA) to stay inside U1's 8%
      // phone: chips and counts only (U8), never a cut name (review H1)
      var sym = function (f) { return D.narrow ? '' : f.tag; };
      var nameW = D.narrow ? 0 : Math.max.apply(null, D.top.map(function (f) { return tw(sym(f), font); })), numW = tw('\u25B2' + '88', font);
      var w = 12 + 2 * r + 8 + nameW + 18 + numW + 12, h = D.top.length * lh + 18, ox = 4, oy = 4;
      s += '<g transform="translate(' + ox + ' ' + oy + ') rotate(-1 ' + f1(w / 2) + ' 0)">';
      s += '<g filter="url(#ha-cast-sea)"><path d="' + receipt(w, h, hash(uid)) + '" fill="' + THERM + '" filter="url(#ha-therm)"/></g>';
      s += '<path d="M6 4H' + f1(w - 6) + '" stroke="#B8AC8C" stroke-width="1.1" stroke-dasharray="1.5 3"/>';
      s += '<g filter="url(#ha-thermal)">';
      D.top.forEach(function (f, i) {
        var cy = 10 + i * lh + lh / 2, x = 12;
        s += '</g><g transform="translate(' + f1(x + r) + ' ' + f1(cy) + ')">' + chip(f.row, r, 'enamel', uid + 'l' + i) + '</g><g filter="url(#ha-thermal)">';
        x += 2 * r + 8;
        if (sym(f)) s += '</g><text data-nm="1" x="' + f1(x) + '" y="' + f1(cy + fs * 0.36) + '" font-family=\'"Space Mono"\' font-weight="700" font-size="' + fs + '" fill="' + darkName(bodyHex(f), THERM, NAME_T) + '">' + esc(sym(f)) + '</text><g filter="url(#ha-thermal)">';
        s += '<path d="M' + f1(x + (sym(f) ? tw(sym(f), font) + 4 : 0)) + ' ' + f1(cy + fs * 0.3) + 'H' + f1(w - 14 - numW) + '" stroke="' + INKD + '" stroke-width="1.4" stroke-dasharray="1 3" opacity="0.45"/>';
        s += '<text x="' + f1(w - 10) + '" y="' + f1(cy + fs * 0.36) + '" text-anchor="end" font-family=\'"Space Mono"\' font-weight="700" font-size="' + fs + '" fill="' + INKD + '"><tspan fill="' + GREEN + '" font-size="' + f1(fs * 0.8) + '">\u25B2</tspan>' + f.kos + '</text>';
      });
      s += '</g>';
      var sy = 10 + lh / 2;
      s += '<g transform="translate(' + f1(w - 30) + ' ' + f1(sy - 13) + ') rotate(-12)" opacity="0.85" filter="url(#ha-stamp-sm)"><rect x="-17" y="-7" width="34" height="13" rx="2" fill="none" stroke="' + RED + '" stroke-width="1.5"/><text y="3.4" text-anchor="middle" font-family=\'"Space Mono"\' font-weight="700" font-size="9.5" letter-spacing="1" fill="' + RED + '">ATH</text></g>';
      s += '</g>';
      return { svg: svg(w + 14, h + 16, s), w: w + 14, h: h + 16 };
    },
    banner: function (D, uid, text) { return woodBanner(D, uid, text); },
    // (v3, retired by Pat 17:2x): a stamped ticket — notched ends, a perforated stub, a red TX stamp
    ticketBanner: function (D, uid, text) {
      var fs = D.narrow ? 22 : 36, t = text.toUpperCase(), font = '400 ' + fs + 'px "DotGothic16"', tws = tw(t, font), maxW = D.w * (D.narrow ? 0.8 : 0.42);
      if (tws + 120 > maxW) { t = t.replace(' TAKES THE LEAD', ' LEADS'); tws = tw(t, font); }
      var stub = Math.round(fs * 1.5), bw = stub + tws + (D.narrow ? 34 : 52), bh = Math.round(fs * 1.55), nr = bh * 0.16, ox = 6, oy = 6, s = '';
      var d = 'M0 0H' + f1(bw) + 'V' + f1(bh / 2 - nr) + 'A' + f1(nr) + ' ' + f1(nr) + ' 0 0 0 ' + f1(bw) + ' ' + f1(bh / 2 + nr) + 'V' + f1(bh) + 'H0V' + f1(bh / 2 + nr) + 'A' + f1(nr) + ' ' + f1(nr) + ' 0 0 0 0 ' + f1(bh / 2 - nr) + 'Z';
      s += '<g transform="translate(' + ox + ' ' + oy + ') rotate(-0.8 ' + f1(bw / 2) + ' ' + f1(bh / 2) + ')">';
      s += '<g filter="url(#ha-cast-sea)"><path d="' + d + '" fill="' + THERM + '" filter="url(#ha-therm)"/></g>';
      s += '<path d="' + d + '" fill="none" stroke="#C9BC98" stroke-width="1.2" transform="translate(3 3) scale(' + f1((bw - 6) / bw * 1000) / 1000 + ' ' + f1((bh - 6) / bh * 1000) / 1000 + ')"/>';
      s += '<rect x="0" y="0" width="' + stub + '" height="' + bh + '" fill="#9FDCC5" opacity="0.55"/>';
      s += '<path d="M' + stub + ' 5V' + f1(bh - 5) + '" stroke="#8A7F66" stroke-width="1.6" stroke-dasharray="2 3.5"/>';
      s += '<path d="M' + f1(stub / 2) + ' ' + f1(bh / 2 - fs * 0.38) + 'L' + f1(stub / 2 + fs * 0.42) + ' ' + f1(bh / 2 + fs * 0.32) + 'H' + f1(stub / 2 - fs * 0.42) + 'Z" fill="' + GREEN + '"/>';
      var dt = dotText(t, fs);
      s += '<g filter="url(#ha-thermal)"><text x="' + f1(stub + (bw - stub - dt.w) / 2) + '" y="' + f1(bh / 2 + fs * 0.4) + '" font-family="DotGothic16" font-size="' + fs + '" fill="' + INKD + '">' + dt.markup + '</text></g>';
      s += '<g transform="translate(' + f1(stub - 2) + ' ' + f1(bh - 9) + ') rotate(-14)" opacity="0.8" filter="url(#ha-stamp)"><rect x="-22" y="-10" width="44" height="17" rx="2" fill="none" stroke="' + RED + '" stroke-width="1.8"/><text y="3.6" text-anchor="middle" font-family=\'"Space Mono"\' font-weight="700" font-size="10.5" letter-spacing="1" fill="' + RED + '">TX OK</text></g>';
      s += '</g>';
      return { svg: svg(bw + 20, bh + 22, s), w: bw + 20, h: bh + 22 };
    },
    // the feed prints on a receipt as it happens (M3): the newest line at the bottom, the roll curling up at the top
    feed: function (D, uid) {
      var lines = D.feed.slice(-(D.narrow ? 2 : 3)), fs = D.narrow ? 16 : 14.5, lh = Math.round(fs * 1.7), font = '700 ' + fs + 'px "Space Mono"', s = '', W = 10;
      var rows = lines.map(function (e) {
        return e.kind === 'ko' ? [[e.a.tag, darkName(bodyHex(e.a), THERM, NAME_T), 1], [' \u25BC ', RED], ['KO ', INKD], [e.b.tag, darkName(bodyHex(e.b), THERM, NAME_T), 1]]
          : [[e.a.tag, darkName(bodyHex(e.a), THERM, NAME_T), 1], [' \u25C6 ', '#9E6A12'], ['FILL ', INKD], [itemName(e), '#6A420C']];
      });
      rows.forEach(function (r) { W = Math.max(W, tw(r.map(function (p) { return p[0]; }).join(''), font)); });
      var w = W + 24, curl = 9, h = rows.length * lh + 12, ox = 4, oy = curl + 4;
      s += '<g filter="url(#ha-cast-sea)"><path d="M0 ' + oy + 'H' + f1(w) + 'V' + f1(oy + h) + 'H0Z" fill="' + THERM + '" filter="url(#ha-therm)"/></g>';
      // the curl: the paper rolls back over the top edge
      s += '<path d="M0 ' + oy + 'Q' + f1(w / 2) + ' ' + f1(oy - curl * 1.4) + ' ' + f1(w) + ' ' + oy + 'V' + f1(oy + 3) + 'Q' + f1(w / 2) + ' ' + f1(oy - curl * 0.6) + ' 0 ' + f1(oy + 3) + 'Z" fill="#D9CFB4"/>';
      s += '<path d="M0 ' + f1(oy + 3) + 'Q' + f1(w / 2) + ' ' + f1(oy - curl * 0.6) + ' ' + f1(w) + ' ' + f1(oy + 3) + '" fill="none" stroke="#B8AC8C" stroke-width="1"/>';
      rows.forEach(function (r, i) {   // names solid and unfiltered (review M2); the rest fades with age
        var y = oy + 8 + (i + 1) * lh - lh * 0.32, age = rows.length - 1 - i, op = [1, 0.86, 0.72][age] || 0.72;
        s += '<text x="12" y="' + f1(y) + '" font-family=\'"Space Mono"\' font-weight="700" font-size="' + fs + '">';
        r.forEach(function (p) { s += '<tspan fill="' + p[1] + '"' + (p[2] ? ' data-nm="1"' : ' fill-opacity="' + op + '"') + '>' + esc(p[0]) + '</tspan>'; });
        s += '</text>';
      });
      return { svg: svg(w + ox + 8, oy + h + 10, s), w: w + ox + 8, h: oy + h + 10 };
    }
  });
  var PAINT = { sand: SAND, riso: RISO, candle: CANDLE };
  var VARIANT = { candle: { b: CANDLE_B } };

  // ------------------------------------------------------------------ build: every panel for a concept
  function build(o) {
    var D = norm(o), K = (o.draft && VARIANT[D.concept] && VARIANT[D.concept][o.draft]) || PAINT[D.concept] || SAND, uid = D.concept + (D.narrow ? 'n' : 'w') + (o.seed || ''), out = [];
    var lead = D.lead, leadText = (lead ? lead.tag : 'Someone') + ' takes the lead';
    out.push({ id: 'board', title: 'Top KOs', p: K.board(D, uid) });
    out.push({ id: 'banner', title: 'Takes the lead', p: K.banner(D, uid, leadText) });
    out.push({ id: 'feed', title: 'Kill feed', p: K.feed(D, uid) });
    if (D.drop) out.push({ id: 'drop', title: 'Legendary drop', p: K.drop(D, uid, D.drop), at: D.drop.a });
    var tags = [];
    if (lead) tags.push([lead, true]);
    if (D.followed && D.followed !== lead) tags.push([D.followed, false]);
    tags.forEach(function (t, i) { out.push({ id: 'tag' + i, title: i ? 'Name tag' : 'Name tag (leader)', p: K.tag(D, uid, t[0], t[1]), at: t[0], tag: true }); });
    D.F.forEach(function (f, i) { out.push({ id: 'bar' + i, title: 'HP', p: K.bar(D, f), at: f, bar: true }); });
    out.push({ id: 'btn0', title: 'Sound', p: K.button(D, uid, 'sound', 0) });
    out.push({ id: 'btn1', title: 'Menu', p: K.button(D, uid, 'menu', 1) });
    return { D: D, panels: out };
  }
  function node(p) { var d = document.createElement('div'); d.className = 'ha-p'; d.innerHTML = p.svg; return d; }

  // ------------------------------------------------------------------ mount: lay the panels out on a frame (U1, U5, U7)
  function mount(el, o) {
    inject();
    return loadFonts().then(function () {
      var B = build(o), D = B.D, W = D.w, H = D.h, m = D.narrow ? 10 : 18;
      var layer = document.createElement('div'); layer.className = 'ha-layer ha-' + D.concept; layer.style.width = W + 'px'; layer.style.height = H + 'px';
      layer.dataset.concept = D.concept;
      var old = el.querySelector(':scope > .ha-layer'); if (old) old.remove();
      var rects = [];
      // k: phone corner pieces are drawn at the same craft and scaled down whole (F3/U1), never re-laid as smaller boxes
      function put(p, x, y, id, kind, k) { k = k || 1; var n = node(p.p); n.style.transform = 'translate(' + f1(x) + 'px,' + f1(y) + 'px)' + (k !== 1 ? ' scale(' + k + ')' : ''); n.style.transformOrigin = '0 0'; n.dataset.panel = id; if (kind) n.dataset.kind = kind; layer.appendChild(n); var r = { id: id, kind: kind || 'corner', x: x, y: y, w: p.p.w * k, h: p.p.h * k }; rects.push(r); return r; }
      var kc = D.narrow ? 0.72 : 1;
      var byId = {}; B.panels.forEach(function (p) { byId[p.id] = p; });
      // corners: the board top-left, buttons bottom-right, the feed bottom-left; the banner centred in the upper third
      var br = put(byId.board, m - 4, m - 6, 'board', null, kc);
      var bn = byId.banner.p; put(byId.banner, (W - bn.w) / 2, D.narrow ? br.y + br.h + 2 : H * 0.045, 'banner', 'transient');
      put(byId.feed, m, H - byId.feed.p.h * kc - m, 'feed', null, kc);
      var b1 = byId.btn1.p, b0 = byId.btn0.p;
      put(byId.btn1, W - m - b1.w * kc, H - m - b1.h * kc, 'btn1', null, kc);
      put(byId.btn0, W - m - (b1.w + 6 + b0.w) * kc, H - m - b0.h * kc, 'btn0', null, kc);
      // under the feet (U5): a bar for everyone, a name for two; then the drop beside its finder
      B.panels.forEach(function (p) {
        if (!p.at || p.at.x == null) return;
        if (p.bar) put(p, p.at.x - p.p.w / 2, p.at.y + (D.narrow ? 4 : 6), p.id, 'world');
        else if (p.tag) put(p, p.at.x - p.p.w / 2, p.at.y + (D.narrow ? 12 : 15), p.id, 'world');
      });
      if (byId.drop && byId.drop.at && byId.drop.at.x != null) {
        // the anchor point each concept names (a stick foot in the sand, a pointer tip, a pin) goes just right of the body;
        // sand plants its stick in the ground beside the feet, the others float beside the head
        var dp = byId.drop.p, ft = dp.foot || [0, dp.h], half = D.narrow ? 16 : 24, a = byId.drop.at;
        var fx = a.x + half + 4, fy = D.concept === 'sand' ? a.y + 2 : a.y - (D.narrow ? 30 : 44);
        var x = fx - ft[0], y = fy - ft[1];
        if (D.concept !== 'sand') x = a.x + half + 2;
        if (x + dp.w > W - m) x = a.x - half - dp.w;
        var bodyH = D.narrow ? 60 : 74, bodies = D.F.map(function (f) { return { x: f.x - half, y: f.y - bodyH, w: 2 * half, h: bodyH + 8 }; });
        var hit = function (x0, y0) { return bodies.concat(rects).some(function (r) { return (!r.id || r.kind === 'world' && /^tag/.test(r.id) || r.kind !== 'world') && x0 < r.x + r.w && x0 + dp.w > r.x && y0 < r.y + r.h && y0 + dp.h > r.y; }); };
        var tries = [[x, y], [a.x - half - dp.w, y], [x, y - 30], [a.x - half - dp.w, y - 30], [x + 40, y], [x, y - 60], [a.x - half - dp.w, y - 60], [x + 40, y - 40], [a.x - dp.w / 2, a.y - bodyH - dp.h - 4]];
        var pick = tries.filter(function (t) { return !hit(Math.max(m, t[0]), Math.max(m, t[1])); })[0] || tries[0];
        put(byId.drop, Math.max(m, pick[0]), Math.max(m, pick[1]), 'drop', 'world');
      }
      el.appendChild(layer);
      // U1 on the frame: the share of the screen the corner + transient pieces cover; the world pieces separately
      var area = 0, world = 0, cx0 = W * 0.2, cx1 = W * 0.8, cy0 = H * 0.2, cy1 = H * 0.8, centre = [];
      rects.forEach(function (r) {
        var a = r.w * r.h; if (r.kind === 'world') world += a; else area += a;
        if (r.kind !== 'world' && r.x + r.w > cx0 && r.x < cx1 && r.y + r.h > cy0 && r.y < cy1) centre.push(r.id);
      });
      var trans = rects.filter(function (r) { return r.kind === 'transient'; }).reduce(function (a, r) { return a + r.w * r.h; }, 0);
      var meas = { hudPct: +(100 * area / (W * H)).toFixed(1), cornerPct: +(100 * (area - trans) / (W * H)).toFixed(1), worldPct: +(100 * world / (W * H)).toFixed(1), centre: centre, rects: rects };
      layer.dataset.hudPct = meas.hudPct; el.dataset.hudReady = '1';
      return meas;
    });
  }
  function panels(concept, o) {
    inject();
    return loadFonts().then(function () {
      var B = build(Object.assign({}, o, { concept: concept }));
      var seen = {}, list = [];
      var K = (o.draft && VARIANT[concept] && VARIANT[concept][o.draft]) || PAINT[concept] || SAND;
      B.panels.forEach(function (p) {
        var key = p.bar ? 'bar' : p.id; if (seen[key]) return; seen[key] = 1;
        if (p.bar) {   // review L1: three states side by side (full, hurt, low) so the card reads as candlesticks
          var parts = [0.95, 0.55, 0.2].map(function (hp) { return K.bar(B.D, { hp: hp }); }), gap = 10, x = 0, inner = '';
          parts.forEach(function (q) { inner += '<g transform="translate(' + x + ' 4)">' + q.svg + '</g>'; x += q.w + gap; });
          var bw = x - gap, bh = parts[0].h + 8;
          list.push({ id: 'bars', title: 'HP: full, hurt, low', node: node({ svg: svg(bw, bh, inner) }), w: bw, h: bh });
          return;
        }
        list.push({ id: p.id, title: p.title, node: node(p.p), w: p.p.w, h: p.p.h });
      });
      return list;
    });
  }

  root.HUDART = { VERSION: VERSION, mount: mount, panels: panels, _darkName: darkName, _contrast: contrast, _inkFor: inkFor };
})(typeof window !== 'undefined' ? window : this);
