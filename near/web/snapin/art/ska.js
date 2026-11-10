/* ska.js: the snap-in and skinner screens drawn as Candle Atoll objects.
 * Board art only, never game code. The material vocabulary is B2 a's (Pat APPROVED 17:32, frozen hud-art/frozen/B2-a-v3.1):
 * enamel price tags on twisted cord, a driftwood plank with a gold pennant, thermal till paper with a red pin, the toon bevel
 * lit from the upper left, mint cast shadows. Type: Lilita One (display, signs only) + Space Mono (all text); OFL, vendored in
 * hud-art/fonts. Every shape is drawn here in code; nothing is copied from any game.
 */
(function (root) {
  'use strict';
  var FONT_DIR = (function () { var s = document.currentScript && document.currentScript.src; return s ? s.replace(/art\/[^/]*$/, 'fonts/') : '../fonts/'; })();
  var P = { p01: '#3B2F25', p02: '#C9966A', p03: '#8A5F3C', p04: '#FFF8EA', p05: '#D8CDB8', p06: '#A3A9B2', p07: '#9FDCC5',
    p08: '#5FB79A', p09: '#A9D4F5', p10: '#6FA3D6', p11: '#D3BEF0', p12: '#F7CF6B', p13: '#D39E2A', p14: '#F6A796', p15: '#D97A6E', p16: '#FF3B30' };
  var INK = '#2A2622', GREEN = '#2E8B6A', RED = '#C2453A', THERM = '#F7F0DC', MINT = '#9FDCC5', GOLD = '#E9B23A', WOODD = '#4A3220';
  function C(c) { return P[c] || c; }
  function f1(v) { return Math.round(v * 10) / 10; }
  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  function rng(seed) { var a = seed >>> 0 || 1; return function () { a |= 0; a = a + 0x6D2B79F5 | 0; var t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  function hash(s) { var h = 2166136261; s = String(s); for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
  function hex2rgb(h) { h = C(h).replace('#', ''); return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)]; }
  function rgb2hex(c) { return '#' + c.map(function (v) { v = Math.max(0, Math.min(255, Math.round(v))); return (v < 16 ? '0' : '') + v.toString(16); }).join(''); }
  function mix(a, b, k) { var x = hex2rgb(a), y = hex2rgb(b); return rgb2hex(x.map(function (v, i) { return v + (y[i] - v) * k; })); }
  function lum(h) { var c = hex2rgb(h).map(function (v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; }
  function contrast(a, b) { var x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }
  var MC = document.createElement('canvas').getContext('2d');
  function tw(text, font) { MC.font = font; return MC.measureText(text).width; }
  function mono(fs, wt) { return (wt || 400) + ' ' + fs + 'px "Space Mono"'; }
  function lil(fs) { return '400 ' + fs + 'px "Lilita One"'; }

  // ---------------------------------------------------------------- paths
  function spline(pts, closed) {
    var n = pts.length, d = 'M' + f1(pts[0][0]) + ' ' + f1(pts[0][1]), last = closed ? n : n - 1;
    for (var i = 0; i < last; i++) {
      var p0 = pts[(i - 1 + n) % n], p1 = pts[i], p2 = pts[(i + 1) % n], p3 = pts[(i + 2) % n];
      if (!closed) { if (i === 0) p0 = p1; if (i + 2 >= n) p3 = p2; }
      d += 'C' + f1(p1[0] + (p2[0] - p0[0]) / 6) + ' ' + f1(p1[1] + (p2[1] - p0[1]) / 6) + ' ' + f1(p2[0] - (p3[0] - p1[0]) / 6) + ' ' + f1(p2[1] - (p3[1] - p1[1]) / 6) + ' ' + f1(p2[0]) + ' ' + f1(p2[1]);
    }
    return d + (closed ? 'Z' : '');
  }
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
  function svg(w, h, body, extra) { return '<svg xmlns="http://www.w3.org/2000/svg" width="' + f1(w) + '" height="' + f1(h) + '" viewBox="0 0 ' + f1(w) + ' ' + f1(h) + '" overflow="visible"' + (extra || '') + '>' + body + '</svg>'; }

  // ---------------------------------------------------------------- defs (copied from B2 a's hud-art 0.3 with an sk- prefix, so a board needs no HUD mount)
  function bands(n, fn) { var a = []; for (var i = 0; i < n; i++) a.push(fn((i + 0.5) / n).toFixed(3)); return a.join(' '); }
  function toonChain(inBlur, scale, shade, hi, shadeA, hiA, cut) {
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
    d += '<filter id="sk-wood" x="-8%" y="-15%" width="125%" height="150%" color-interpolation-filters="sRGB">' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.006 0.19" numOctaves="4" seed="4" result="n"/>' +
      '<feColorMatrix in="n" type="matrix" values="0 0 0 0 0.36  0 0 0 0 0.24  0 0 0 0 0.15  3.2 0 0 0 -1.62" result="dk"/>' +
      '<feColorMatrix in="n" type="matrix" values="0 0 0 0 1  0 0 0 0 0.95  0 0 0 0 0.86  0 -3.4 0 0 1.25" result="lt"/>' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="9" result="fine"/>' +
      '<feColorMatrix in="fine" type="matrix" values="0 0 0 0 0.3  0 0 0 0 0.2  0 0 0 0 0.12  0 0 0 0.55 -0.2" result="fn"/>' +
      '<feMerge result="g"><feMergeNode in="SourceGraphic"/><feMergeNode in="lt"/><feMergeNode in="dk"/><feMergeNode in="fn"/></feMerge>' +
      '<feComposite in="g" in2="SourceAlpha" operator="in" result="wood"/>' + toonChain(2.4, 5, '#2F4F52', '#FFE3A0', 0.42, 0.6) +
      '<feMerge result="lit2"><feMergeNode in="wood"/><feMergeNode in="shc"/><feMergeNode in="hic"/></feMerge><feComposite in="lit2" in2="SourceAlpha" operator="in"/></filter>';
    // a wider board: the same grain stretched for big planks (the grain frequency is per user unit, so big planks need a lower one)
    d += '<filter id="sk-wood-big" x="-4%" y="-6%" width="110%" height="115%" color-interpolation-filters="sRGB">' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.004 0.09" numOctaves="4" seed="14" result="n"/>' +
      '<feColorMatrix in="n" type="matrix" values="0 0 0 0 0.36  0 0 0 0 0.24  0 0 0 0 0.15  3.0 0 0 0 -1.55" result="dk"/>' +
      '<feColorMatrix in="n" type="matrix" values="0 0 0 0 1  0 0 0 0 0.95  0 0 0 0 0.86  0 -3.2 0 0 1.2" result="lt"/>' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.7" numOctaves="2" seed="19" result="fine"/>' +
      '<feColorMatrix in="fine" type="matrix" values="0 0 0 0 0.3  0 0 0 0 0.2  0 0 0 0 0.12  0 0 0 0.45 -0.18" result="fn"/>' +
      '<feMerge result="g"><feMergeNode in="SourceGraphic"/><feMergeNode in="lt"/><feMergeNode in="dk"/><feMergeNode in="fn"/></feMerge>' +
      '<feComposite in="g" in2="SourceAlpha" operator="in" result="wood"/>' + toonChain(3.2, 6, '#2F4F52', '#FFE3A0', 0.38, 0.55) +
      '<feMerge result="lit2"><feMergeNode in="wood"/><feMergeNode in="shc"/><feMergeNode in="hic"/></feMerge><feComposite in="lit2" in2="SourceAlpha" operator="in"/></filter>';
    d += '<pattern id="sk-weave" width="3" height="3" patternUnits="userSpaceOnUse"><rect width="3" height="1" fill="#000" opacity="0.07"/><rect width="1" height="3" fill="#fff" opacity="0.10"/></pattern>';
    d += '<filter id="sk-cloth" x="-5%" y="-15%" width="115%" height="140%" color-interpolation-filters="sRGB">' + toonChain(1.6, 3, '#7A4E10', '#FFF6C8', 0.38, 0.6) +
      '<feMerge result="m"><feMergeNode in="SourceGraphic"/><feMergeNode in="shc"/><feMergeNode in="hic"/></feMerge><feComposite in="m" in2="SourceAlpha" operator="in"/></filter>';
    d += '<filter id="sk-enamel" x="-10%" y="-10%" width="125%" height="125%" color-interpolation-filters="sRGB">' + toonChain(1.5, 4, '#1F2B2A', '#FFFFFF', 0.32, 0.8, [0.40, 0.80]) +
      '<feMerge result="m"><feMergeNode in="SourceGraphic"/><feMergeNode in="shc"/><feMergeNode in="hic"/></feMerge><feComposite in="m" in2="SourceAlpha" operator="in"/></filter>';
    d += '<filter id="sk-enamel-big" x="-6%" y="-6%" width="115%" height="115%" color-interpolation-filters="sRGB">' + toonChain(2.6, 5, '#1F2B2A', '#FFFFFF', 0.28, 0.75, [0.38, 0.82]) +
      '<feMerge result="m"><feMergeNode in="SourceGraphic"/><feMergeNode in="shc"/><feMergeNode in="hic"/></feMerge><feComposite in="m" in2="SourceAlpha" operator="in"/></filter>';
    [['sk-cast', 2, 2.2, 9, 5, 1.4], ['sk-cast-sm', 1.2, 1.4, 5, 3, 0.9], ['sk-cast-lg', 4, 4.5, 16, 10, 3]].forEach(function (c) {
      d += '<filter id="' + c[0] + '" x="-10%" y="-15%" width="140%" height="160%">' +
        '<feOffset in="SourceAlpha" dx="' + c[1] + '" dy="' + c[2] + '" result="o1"/><feFlood flood-color="#2F6A70" flood-opacity="0.34"/><feComposite in2="o1" operator="in" result="s1"/>' +
        '<feOffset in="SourceAlpha" dx="' + c[3] + '" dy="' + c[4] + '" result="o2"/><feGaussianBlur in="o2" stdDeviation="' + c[5] + '" result="o2b"/><feFlood flood-color="#3F8088" flood-opacity="0.24"/><feComposite in2="o2b" operator="in" result="s2"/>' +
        '<feMerge><feMergeNode in="s2"/><feMergeNode in="s1"/><feMergeNode in="SourceGraphic"/></feMerge></filter>';
    });
    d += '<filter id="sk-therm" x="-4%" y="-6%" width="108%" height="115%" color-interpolation-filters="sRGB">' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.9 0.6" numOctaves="3" seed="81" result="n"/>' +
      '<feColorMatrix in="n" type="matrix" values="0 0 0 0 0.55  0 0 0 0 0.5  0 0 0 0 0.4  0 0 0.42 0 -0.12" result="fib"/>' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.012 0.002" numOctaves="2" seed="83" result="bl"/>' +
      '<feColorMatrix in="bl" type="matrix" values="0 0 0 0 0.85  0 0 0 0 0.78  0 0 0 0 0.6  0 0 0 0.5 -0.18" result="blot"/>' +
      toonChain(1.8, 3.5, '#5E9A9E', '#FFE3A0', 0.42, 0.7, [0.44, 0.84]) +
      '<feMerge result="m"><feMergeNode in="SourceGraphic"/><feMergeNode in="blot"/><feMergeNode in="fib"/><feMergeNode in="shc"/><feMergeNode in="hic"/></feMerge><feComposite in="m" in2="SourceAlpha" operator="in"/></filter>';
    // a soft frosted look for the live island behind a screen (the world stays visible, quieter)
    d += '<filter id="sk-hush" x="0" y="0" width="100%" height="100%"><feGaussianBlur stdDeviation="3"/><feColorMatrix type="matrix" values="0.78 0.12 0.1 0 0.06  0.1 0.8 0.1 0 0.06  0.1 0.12 0.78 0 0.05  0 0 0 1 0"/></filter>';
    d += '<filter id="sk-stamp" x="-8%" y="-8%" width="116%" height="116%">' +
      '<feTurbulence type="fractalNoise" baseFrequency="0.55" numOctaves="2" seed="41" result="n"/>' +
      '<feDisplacementMap in="SourceGraphic" in2="n" scale="1.2" xChannelSelector="R" yChannelSelector="G"/></filter>';
    d += '<linearGradient id="sk-glass" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#E9FBF4" stop-opacity="0.75"/><stop offset="1" stop-color="#9FDCC5" stop-opacity="0.35"/></linearGradient>';
    d += '<linearGradient id="sk-foil" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stop-color="#FFE7A0"/><stop offset="0.45" stop-color="#E9B23A"/><stop offset="0.55" stop-color="#FFF2C4"/><stop offset="1" stop-color="#C98F1C"/></linearGradient>';
    return d;
  }
  var injected = false, ready = null;
  var FONTS = [['Lilita One', 'LilitaOne-400.woff2', '400'], ['Space Mono', 'SpaceMono-400.woff2', '400'], ['Space Mono', 'SpaceMono-700.woff2', '700']];
  function init() {
    if (!injected) {
      injected = true;
      var st = document.createElement('style');
      st.textContent = FONTS.map(function (f) { return '@font-face{font-family:"' + f[0] + '";src:url("' + FONT_DIR + f[1] + '") format("woff2");font-weight:' + f[2] + ';font-display:block}'; }).join('\n');
      document.head.appendChild(st);
      var d = document.createElement('div'); d.setAttribute('aria-hidden', 'true'); d.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden';
      d.innerHTML = svg(0, 0, '<defs>' + DEFS() + '</defs>'); document.body.appendChild(d);
    }
    if (!ready) ready = Promise.all(['400 40px "Lilita One"', '400 20px "Space Mono"', '700 20px "Space Mono"'].map(function (p) { return document.fonts.load(p, 'Aa0▲'); })).then(function () { return document.fonts.ready; });
    return ready;
  }

  // ---------------------------------------------------------------- materials
  // twisted cord: a dark core and a light twist dashed over it
  function cord(x0, y0, x1, y1, sag, wide) {
    var d = 'M' + f1(x0) + ' ' + f1(y0) + 'Q' + f1((x0 + x1) / 2) + ' ' + f1((y0 + y1) / 2 + (sag || 0)) + ' ' + f1(x1) + ' ' + f1(y1), k = wide || 1;
    return '<path d="' + d + '" fill="none" stroke="#6E5236" stroke-width="' + 2 * k + '" stroke-linecap="round"/><path d="' + d + '" fill="none" stroke="#D2AE7E" stroke-width="' + 1.3 * k + '" stroke-dasharray="' + 1.3 * k + ' ' + 1.7 * k + '" stroke-linecap="round"/>';
  }
  function nail(x, y) { return '<circle cx="' + f1(x) + '" cy="' + f1(y) + '" r="2.6" fill="#5E646C"/><circle cx="' + f1(x - 0.8) + '" cy="' + f1(y - 0.8) + '" r="0.9" fill="#D9DDE2"/>'; }
  function pin(x, y, col) { return '<circle cx="' + f1(x) + '" cy="' + f1(y) + '" r="3.6" fill="' + (col || RED) + '"/><circle cx="' + f1(x - 1.1) + '" cy="' + f1(y - 1.1) + '" r="1.2" fill="#FFFFFF" opacity="0.75"/>'; }
  function flecks(w, h, seed) {
    var R = rng(seed), o = '';
    for (var i = 0; i < 3; i++) { var x = (i === 0 ? 0.3 : 0.55 + R() * 0.4) * w, y = (R() < 0.5 ? 0.12 : 0.86) * h, r = 0.9 + R() * 1.2; o += '<path d="M' + f1(x - r) + ' ' + f1(y) + 'l' + f1(r * 0.8) + ' ' + f1(-r * 0.7) + 'l' + f1(r * 1.3) + ' ' + f1(r * 0.4) + 'l' + f1(-r * 0.6) + ' ' + f1(r * 0.9) + 'z" fill="#B9B4AA"/>'; }
    return o;
  }
  function tagShape(w, h) { var c = h * 0.42; return 'M' + f1(c) + ' 0H' + f1(w) + 'V' + f1(h) + 'H' + f1(c) + 'L0 ' + f1(h / 2) + 'Z'; }
  function rrect(x, y, w, h, r) { return 'M' + f1(x + r) + ' ' + f1(y) + 'H' + f1(x + w - r) + 'Q' + f1(x + w) + ' ' + f1(y) + ' ' + f1(x + w) + ' ' + f1(y + r) + 'V' + f1(y + h - r) + 'Q' + f1(x + w) + ' ' + f1(y + h) + ' ' + f1(x + w - r) + ' ' + f1(y + h) + 'H' + f1(x + r) + 'Q' + f1(x) + ' ' + f1(y + h) + ' ' + f1(x) + ' ' + f1(y + h - r) + 'V' + f1(y + r) + 'Q' + f1(x) + ' ' + f1(y) + ' ' + f1(x + r) + ' ' + f1(y) + 'Z'; }

  // an enamel price tag: o = {x, y, w?, h, label, icon?(svg at 0,0 sized h*0.5), fill, rim, sel, fs, sub, rot, hole: true}
  // sel = this choice is picked: mint enamel with a gold ribbon edge (as B2 a's leader tag); unpicked = cream enamel
  function enamelTag(o) {
    var h = o.h || 34, fs = o.fs || Math.round(h * 0.42), font = mono(fs, 700), lw = o.label ? tw(o.label, font) : 0;
    var iw = o.icon ? h * 0.62 : 0, w = o.w || (h * 0.42 + 10 + iw + lw + 14 + (o.sub ? tw(o.sub, mono(fs * 0.78)) + 8 : 0));
    var sel = !!o.sel, col = o.fill || (sel ? MINT : THERM), rim = o.rim || (sel ? '#3E8E73' : '#9A8F7C'), s = '';
    s += '<g transform="translate(' + f1(o.x || 0) + ' ' + f1(o.y || 0) + ') rotate(' + (o.rot || 0) + ' 0 ' + f1(h / 2) + ')" filter="url(#sk-cast-sm)">';
    s += '<path d="' + tagShape(w, h) + '" fill="' + rim + '" filter="url(#sk-enamel)"/>';
    s += '<path d="' + tagShape(w, h) + '" transform="translate(2.2 2.2) scale(' + f1((w - 4.4) / w * 1000) / 1000 + ' ' + f1((h - 4.4) / h * 1000) / 1000 + ')" fill="' + col + '" filter="url(#sk-enamel)"/>';
    s += flecks(w, h, hash((o.label || '') + w));
    if (o.hole !== false) { var gx = h * 0.42 * 0.55; s += '<circle cx="' + f1(gx) + '" cy="' + f1(h / 2) + '" r="3.4" fill="#D9D3C8" stroke="#8A8378" stroke-width="1.1"/><circle cx="' + f1(gx) + '" cy="' + f1(h / 2) + '" r="1.5" fill="#6E5236"/>'; }
    var x = h * 0.42 + 8;
    if (o.icon && !o.label) s += '<g transform="translate(' + f1((h * 0.42 + w) / 2 + 1) + ' ' + f1(h / 2) + ')">' + o.icon + '</g>';
    else if (o.icon) { s += '<g transform="translate(' + f1(x + iw / 2) + ' ' + f1(h / 2) + ')">' + o.icon + '</g>'; x += iw + 2; }
    if (o.label) s += '<text x="' + f1(x) + '" y="' + f1(h / 2 + fs * 0.36) + '" font-family=\'"Space Mono"\' font-weight="700" font-size="' + fs + '" fill="' + (o.ink || (sel ? '#1F5E4A' : INK)) + '">' + esc(o.label) + (o.sub ? '<tspan font-weight="400" font-size="' + f1(fs * 0.78) + '" fill="#6E6556" dx="8">' + esc(o.sub) + '</tspan>' : '') + '</text>';
    if (sel) {   // the gold ribbon folded over the top edge: "picked"
      var rx = w - 26; s += '<path d="M' + f1(rx) + ' -3H' + f1(rx + 18) + 'V' + 10 + 'L' + f1(rx + 9) + ' 6L' + f1(rx) + ' 10Z" fill="' + GOLD + '" filter="url(#sk-cloth)"/><path d="M' + f1(rx + 4.5) + ' 1.8l3 3 5.5-6" fill="none" stroke="#5A3A0A" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>';
    }
    s += '</g>';
    return { svg: s, w: w, h: h };
  }
  // a round enamel swatch (palette colour), hung from a nail: o = {x, y, r, color, sel}
  function swatch(o) {
    var r = o.r || 16, c = C(o.color), s = '';
    s += '<g transform="translate(' + f1(o.x) + ' ' + f1(o.y) + ')" filter="url(#sk-cast-sm)"><circle r="' + f1(r) + '" fill="' + (o.sel ? '#3E8E73' : '#9A8F7C') + '" filter="url(#sk-enamel)"/>';
    s += '<circle r="' + f1(r - 2.6) + '" fill="' + c + '" filter="url(#sk-enamel)"/>';
    s += '<circle cx="0" cy="' + f1(-r + 5) + '" r="2" fill="#D9D3C8" stroke="#8A8378" stroke-width="0.9"/>';
    if (o.sel) s += '<circle r="' + f1(r + 4) + '" fill="none" stroke="' + GOLD + '" stroke-width="2.6"/><circle r="' + f1(r + 4) + '" fill="none" stroke="#FFF2C4" stroke-width="0.9" stroke-dasharray="2 3"/>';
    s += '</g>';
    return s;
  }
  // the driftwood plank sign (B2 a's lead sign): o = {x, y, w?, h?, text, fs, pennant: 'crown'|'arrow'|null, cords: true, seed, color}
  function plank(o) {
    var fs = o.fs || 30, font = lil(fs), t = o.text || '', tws = tw(t, font), pen = o.pennant ? Math.round(fs * 1.2) : 0;
    var w = o.w || (tws + pen + (o.pennant ? 44 : 40)), h = o.h || Math.round(fs * 1.55), ox = o.x || 0, oy = o.y || 0, seed = o.seed || hash(t + 'pl'), s = '';
    var hx = [ox + w * 0.13, ox + w * 0.87];
    if (o.cords) s += '<g filter="url(#sk-cast-sm)">' + cord(hx[0] - 5, oy - (o.cordLen || 40), hx[0], oy + 6, 0) + cord(hx[1] + 5, oy - (o.cordLen || 40), hx[1], oy + 6, 0) + '</g>';
    var pl = slab(ox, oy, w, h, 8, 1.4, seed, 28);
    s += '<g filter="url(#' + (o.flat ? 'sk-cast-sm' : 'sk-cast') + ')"><path d="' + pl + '" fill="' + WOODD + '" stroke="' + WOODD + '" stroke-width="3.2" stroke-linejoin="round"/><path d="' + pl + '" fill="' + (o.color || '#B98E62') + '" filter="url(#' + (w > 500 ? 'sk-wood-big' : 'sk-wood') + ')"/></g>';
    var R = rng(seed);
    s += '<g fill="none" stroke="#6E4B2E" stroke-linecap="round" opacity="0.55"><path d="M' + f1(ox + w - 3) + ' ' + f1(oy + h * 0.7) + 'q-' + f1(w * 0.05) + ' -2 -' + f1(w * 0.1) + ' 1" stroke-width="1.3"/><ellipse cx="' + f1(ox + w * (0.3 + R() * 0.4)) + '" cy="' + f1(oy + h * 0.84) + '" rx="5" ry="1.6" stroke-width="1.1"/></g>';
    if (o.cords) hx.forEach(function (x) { s += '<circle cx="' + f1(x) + '" cy="' + f1(oy + 7) + '" r="3.4" fill="#2E2016"/><path d="M' + f1(x - 3.2) + ' ' + f1(oy + 5) + 'q3.2 4.5 6.4 0" fill="none" stroke="#6E5236" stroke-width="2.4" stroke-linecap="round"/>'; });
    var tx = ox + (w - tws - pen) / 2 + pen, ty = oy + h / 2 + fs * 0.35;
    if (o.pennant) {
      var px = ox + 12, py = oy + h * 0.5, pwid = pen, phh = Math.round(fs * 0.86);
      var pd = 'M' + f1(px) + ' ' + f1(py - phh / 2) + 'H' + f1(px + pwid) + 'L' + f1(px + pwid - phh * 0.32) + ' ' + f1(py) + 'L' + f1(px + pwid) + ' ' + f1(py + phh / 2) + 'H' + f1(px) + 'Z';
      s += '<g filter="url(#sk-cast-sm)"><path d="' + pd + '" fill="' + GOLD + '" filter="url(#sk-cloth)"/></g><path d="' + pd + '" fill="url(#sk-weave)"/>';
      s += '<g transform="translate(' + f1(px + pwid * 0.42) + ' ' + f1(py + 1) + ')">' + (o.pennant === 'arrow' ? icon('arrow', '#7A4E10', fs * 0.42) : o.pennant === 'key' ? icon('key', '#7A4E10', fs * 0.42) : crown('#7A4E10', fs * 0.2)) + '</g>';
      s += nail(px + 4, py);
      tx = px + pwid + (w - (px - ox) - pwid - tws) / 2;
    }
    s += '<text x="' + f1(tx + 1.4) + '" y="' + f1(ty + 2) + '" font-family=\'"Lilita One"\' font-size="' + fs + '" fill="#3A2616" opacity="0.55">' + esc(t) + '</text>';
    s += '<text x="' + f1(tx) + '" y="' + f1(ty) + '" font-family=\'"Lilita One"\' font-size="' + fs + '" fill="#FFF4DC">' + esc(t) + '</text>';
    return { svg: s, w: w, h: h };
  }
  // thermal till paper: a strip with a zigzag-torn bottom (and top, if torn:'both'), fibre and the toon bevel
  function paperPath(x, y, w, h, torn) {
    var n = Math.max(4, Math.round(w / 7)), d = 'M' + f1(x) + ' ' + f1(y);
    if (torn === 'both') { for (var j = 0; j <= n; j++) d += 'L' + f1(x + j * w / n) + ' ' + f1(y - (j % 2 ? 4 : 0)); } else d += 'H' + f1(x + w);
    d += 'V' + f1(y + h);
    for (var i = n; i >= 0; i--) d += 'L' + f1(x + i * w / n) + ' ' + f1(y + h + (i % 2 ? 4 : 0));
    return d + 'Z';
  }
  function paper(x, y, w, h, o) {
    o = o || {};
    var s = '<g filter="url(#' + (o.cast || 'sk-cast') + ')"><path d="' + paperPath(x, y, w, h, o.torn) + '" fill="' + (o.fill || THERM) + '" filter="url(#sk-therm)"/></g>';
    if (o.band) s += '<rect x="' + f1(x) + '" y="' + f1(y + o.band[0]) + '" width="' + f1(w) + '" height="' + f1(o.band[1]) + '" fill="' + MINT + '" opacity="0.2"/>';
    if (o.pin) s += pin(x + w / 2, y + 2);
    return s;
  }
  // a big enamel plate (a sign of painted tin on the wall): o = {x,y,w,h,fill,rim,r}
  function plate(o) {
    var r = o.r == null ? 14 : o.r, s = '';
    s += '<g filter="url(#' + (o.cast || 'sk-cast') + ')"><path d="' + rrect(o.x, o.y, o.w, o.h, r) + '" fill="' + (o.rim || '#9A8F7C') + '" filter="url(#sk-enamel-big)"/>';
    s += '<path d="' + rrect(o.x + 3, o.y + 3, o.w - 6, o.h - 6, Math.max(2, r - 3)) + '" fill="' + (o.fill || THERM) + '" filter="url(#sk-enamel-big)"/></g>';
    s += flecks(o.w, o.h, hash('pl' + o.w + o.h)).replace(/<path d="M/g, '<path transform="translate(' + f1(o.x) + ' ' + f1(o.y) + ')" d="M');
    if (o.screws !== false) [[o.x + 10, o.y + 10], [o.x + o.w - 10, o.y + 10], [o.x + 10, o.y + o.h - 10], [o.x + o.w - 10, o.y + o.h - 10]].forEach(function (p) { s += nail(p[0], p[1]); });
    return s;
  }
  // text helpers (all Space Mono; never distressed)
  function text(x, y, t, o) {
    o = o || {};
    return '<text x="' + f1(x) + '" y="' + f1(y) + '"' + (o.anchor ? ' text-anchor="' + o.anchor + '"' : '') + ' font-family=\'"Space Mono"\' font-weight="' + (o.wt || 400) + '" font-size="' + (o.fs || 14) + '" fill="' + (o.fill || INK) + '"' + (o.ls ? ' letter-spacing="' + o.ls + '"' : '') + (o.op ? ' opacity="' + o.op + '"' : '') + '>' + (o.raw ? t : esc(t)) + '</text>';
  }
  function title(x, y, t, fs, o) { o = o || {}; return '<text x="' + f1(x + 1.2) + '" y="' + f1(y + 1.8) + '"' + (o.anchor ? ' text-anchor="' + o.anchor + '"' : '') + ' font-family=\'"Lilita One"\' font-size="' + fs + '" fill="' + (o.shadow || '#2F6A70') + '" opacity="0.35">' + esc(t) + '</text><text x="' + f1(x) + '" y="' + f1(y) + '"' + (o.anchor ? ' text-anchor="' + o.anchor + '"' : '') + ' font-family=\'"Lilita One"\' font-size="' + fs + '" fill="' + (o.fill || INK) + '">' + esc(t) + '</text>'; }
  // wrap a line of Space Mono into a width; returns lines
  function wrap(t, fs, w, wt) { var words = String(t).split(' '), lines = [], cur = ''; words.forEach(function (wd) { var tr = cur ? cur + ' ' + wd : wd; if (tw(tr, mono(fs, wt)) > w && cur) { lines.push(cur); cur = wd; } else cur = tr; }); if (cur) lines.push(cur); return lines; }
  function para(x, y, t, fs, w, o) { o = o || {}; var lh = o.lh || Math.round(fs * 1.45), s = ''; wrap(t, fs, w, o.wt).forEach(function (l, i) { s += text(x, y + i * lh, l, Object.assign({ fs: fs }, o)); }); return { svg: s, h: wrap(t, fs, w, o.wt).length * lh }; }

  // ---------------------------------------------------------------- icons (drawn at the origin, size ~s)
  function crown(c, s) { return '<path d="M' + -s + ' ' + s * 0.55 + 'L' + -s + ' ' + -s * 0.35 + 'L' + -s * 0.5 + ' ' + s * 0.1 + 'L0 ' + -s * 0.6 + 'L' + s * 0.5 + ' ' + s * 0.1 + 'L' + s + ' ' + -s * 0.35 + 'L' + s + ' ' + s * 0.55 + 'Z" fill="' + c + '" stroke-linejoin="round"/>'; }
  function icon(kind, c, s) {
    s = s || 10; c = c || INK; var k = s / 10, sw = f1(2 * k), g = '<g fill="none" stroke="' + c + '" stroke-width="' + sw + '" stroke-linecap="round" stroke-linejoin="round" transform="scale(' + f1(k * 100) / 100 + ')">', e = '</g>';
    switch (kind) {
      case 'chain': return g + '<rect x="-9" y="-4" width="10" height="8" rx="4" transform="rotate(-30)"/><rect x="-1" y="-4" width="10" height="8" rx="4" transform="rotate(-30)"/>' + e;
      case 'browser': return g + '<rect x="-9" y="-7" width="18" height="14" rx="2"/><path d="M-9 -3H9"/><circle cx="-6" cy="-5" r="0.4"/><path d="M-2 3.5v-2.5a2 2 0 0 1 4 0v2.5" stroke-width="1.6"/>' + e;
      case 'eye': return g + '<path d="M-10 0Q0 -9 10 0Q0 9 -10 0Z"/><circle r="3" fill="' + c + '"/>' + e;
      case 'fist': return g + '<path d="M-6 -2v-3a2 2 0 0 1 4 0v1-2a2 2 0 0 1 4 0v2-1a2 2 0 0 1 4 0v5c0 4-3 7-7 7h-1c-3 0-5-2-6-4l-2-3a1.6 1.6 0 0 1 2.6-2l1.4 1.5"/>' + e;
      case 'crosshair': return g + '<circle r="7"/><path d="M0 -10v5M0 5v5M-10 0h5M5 0h5"/>' + e;
      case 'bag': return g + '<path d="M-7 -2h14l-1.5 10h-11Z"/><path d="M-3.5 -2v-2a3.5 3.5 0 0 1 7 0v2"/>' + e;
      case 'shield': return g + '<path d="M0 -9l7 3v4c0 5-3 8-7 10c-4-2-7-5-7-10v-4Z"/>' + e;
      case 'shoe': return g + '<path d="M-9 4v-6l4-1l3 3l4 0l6 2c1 0 1 2 0 2h-17Z"/><path d="M-3 0l1-2M0 1l1-2"/>' + e;
      case 'shuffle': return g + '<path d="M-9 -5h4l8 10h5M-9 5h4l2-2.5M3 -5h5"/><path d="M5 -8l3 3-3 3M5 2l3 3-3 3"/>' + e;
      case 'key': return g + '<circle cx="-4" cy="0" r="4.5"/><path d="M0.5 0h9M6 0v3.5M9 0v2.5"/>' + e;
      case 'wallet': return g + '<path d="M-9 -4h16a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-14a2 2 0 0 1-2-2Z"/><path d="M-9 -4l11-4l2 4"/><circle cx="5" cy="2.5" r="1.2" fill="' + c + '"/>' + e;
      case 'arrow': return g + '<path d="M-8 0h15M2 -5l5 5-5 5"/>' + e;
      case 'check': return g + '<path d="M-7 0l4.5 4.5 9-9"/>' + e;
      case 'home': return g + '<path d="M-8 -1l8-7 8 7M-6 -3v10h12v-10"/><path d="M-1.5 7v-5h3v5"/>' + e;
      case 'drop': return g + '<path d="M-6 -6h12l-2 13h-8Z"/><path d="M-3 -2h6"/>' + e;
      case 'bubble': return g + '<path d="M-9 -7h18v11h-10l-5 4v-4h-3Z"/><path d="M-5 -2.5h10M-5 0.8h6"/>' + e;
      case 'tap': return g + '<path d="M-8 -4h9v-3h4v3h3v5h-3"/><path d="M5 4.5v0.5M5 8v0.5" stroke-width="2.6"/>' + e;
      case 'coin': return g + '<ellipse rx="8" ry="8"/><path d="M-3 -3.5l6 0M0 -5.5v11M-3 3.5h6"/>' + e;
      case 'flag': return g + '<path d="M-6 9v-18M-6 -8h12l-3 4 3 4h-12"/>' + e;
      case 'plot': return g + '<path d="M-10 2l10-6 10 6-10 6Z"/><path d="M0 -4v-6l5 2-5 2"/>' + e;
      case 'board': return g + '<rect x="-9" y="-8" width="18" height="12" rx="1"/><path d="M-5 4v5M5 4v5M-5 -4h7M-5 -1h10"/>' + e;
      case 'sword': return g + '<path d="M-8 8l12-12M2 -10h8v8M-8 2l6 6M-10 10l2-2"/>' + e;
      case 'moon': return g + '<path d="M3 -8a8 8 0 1 0 5 13a7 7 0 0 1-5-13Z"/>' + e;
      case 'warn': return g + '<path d="M0 -9l9 16h-18Z"/><path d="M0 -3v4M0 4v0.5"/>' + e;
      case 'pen': return g + '<path d="M-8 8l2-6 10-10 4 4-10 10Z"/><path d="M2 -4l4 4"/>' + e;
      default: return '';
    }
  }
  // the portrait chip (B2 a): round body, hat band, the cream face patch, two dots and a smile
  function chip(pal, r, uid) {
    var body = C(pal[0]), hat = C(pal[1] || 'p04'), id = 'skc' + uid, s = '';
    var lit = mix(body, '#FFFFFF', 0.28), shd = mix(body, 'p01', 0.3), rim = mix(body, 'p01', 0.62);
    if (hat === body || contrast(hat, body) < 1.25) hat = mix(hat, 'p01', 0.25);
    s += '<defs><clipPath id="' + id + '"><circle r="' + r + '"/></clipPath></defs><g clip-path="url(#' + id + ')"><circle r="' + r + '" fill="' + body + '"/>';
    s += '<circle cx="' + f1(-r * 0.28) + '" cy="' + f1(-r * 0.3) + '" r="' + f1(r * 0.98) + '" fill="' + lit + '" opacity="0.55"/><circle cx="' + f1(-r * 0.12) + '" cy="' + f1(-r * 0.1) + '" r="' + f1(r * 0.98) + '" fill="' + body + '"/>';
    s += '<path d="M' + f1(-r) + ' ' + f1(r * 0.55) + 'Q0 ' + f1(r * 0.9) + ' ' + f1(r) + ' ' + f1(-r * 0.15) + 'L' + f1(r) + ' ' + f1(r) + 'L' + f1(-r) + ' ' + f1(r) + 'Z" fill="' + shd + '"/>';
    s += '<path d="M' + f1(-r * 1.05) + ' ' + f1(-r * 0.32) + 'Q0 ' + f1(-r * 0.5) + ' ' + f1(r * 1.05) + ' ' + f1(-r * 0.22) + 'L' + f1(r) + ' ' + f1(-r) + 'L' + f1(-r) + ' ' + f1(-r) + 'Z" fill="' + hat + '"/></g>';
    var fx = r * 0.16, fy = r * 0.2;
    s += '<ellipse cx="' + f1(fx) + '" cy="' + f1(fy) + '" rx="' + f1(r * 0.55) + '" ry="' + f1(r * 0.47) + '" fill="#FFF8EA"/>';
    s += '<circle cx="' + f1(fx - r * 0.2) + '" cy="' + f1(fy - r * 0.06) + '" r="' + f1(r * 0.085) + '" fill="#2B211A"/><circle cx="' + f1(fx + r * 0.2) + '" cy="' + f1(fy - r * 0.06) + '" r="' + f1(r * 0.085) + '" fill="#2B211A"/>';
    s += '<path d="M' + f1(fx - r * 0.08) + ' ' + f1(fy + r * 0.12) + 'q' + f1(r * 0.08) + ' ' + f1(r * 0.08) + ' ' + f1(r * 0.16) + ' 0" fill="none" stroke="#2B211A" stroke-width="' + f1(Math.max(1, r * 0.06)) + '" stroke-linecap="round"/>';
    s += '<circle r="' + f1(r - 0.6) + '" fill="none" stroke="' + rim + '" stroke-width="1.6"/>';
    return s;
  }
  // Satrenchi's chip: the dark hood with two soft lights (approved as is, B3 v3)
  function satChip(r) {
    var s = '<circle r="' + r + '" fill="#A3A9B2"/><path d="M' + f1(-r * 0.92) + ' ' + f1(r * 0.4) + 'Q' + f1(-r * 0.9) + ' ' + f1(-r * 0.95) + ' 0 ' + f1(-r * 0.95) + 'Q' + f1(r * 0.9) + ' ' + f1(-r * 0.95) + ' ' + f1(r * 0.92) + ' ' + f1(r * 0.4) + 'Z" fill="#7E858E"/>';
    s += '<ellipse cx="' + f1(r * 0.08) + '" cy="' + f1(r * 0.05) + '" rx="' + f1(r * 0.55) + '" ry="' + f1(r * 0.5) + '" fill="#2F2A26"/>';
    s += '<circle cx="' + f1(-r * 0.12) + '" cy="' + f1(r * 0.02) + '" r="' + f1(r * 0.1) + '" fill="#F7CF6B"/><circle cx="' + f1(r * 0.28) + '" cy="' + f1(r * 0.02) + '" r="' + f1(r * 0.1) + '" fill="#F7CF6B"/>';
    s += '<circle r="' + f1(r - 0.6) + '" fill="none" stroke="#4E535A" stroke-width="1.6"/>';
    return s;
  }
  // Satrenchi says: a torn stub of till paper pinned beside its chip. o = {x, y, w, lines:[..], fs, tail:'left'|'up'|null}
  function satSays(o) {
    var fs = o.fs || 14, lh = Math.round(fs * 1.45), lines = [], w = o.w || 300;
    w = Math.min(w, Math.max.apply(null, (o.lines || ['']).map(function (l) { return tw(l, mono(fs)); })) + 34);   // a short line gets a short stub
    (o.lines || []).forEach(function (l) { lines = lines.concat(wrap(l, fs, w - 28)); });
    var h = lines.length * lh + 18, s = '', x = o.x, y = o.y, r = o.chip || 18;
    if (o.img) {   // the rendered Satrenchi (B3, approved as is) in an enamel disc
      var cx = x - r - 12, cy = y + r * 0.7, id = 'sat' + hash(o.lines.join('') + x + y);
      s += '<g filter="url(#sk-cast-sm)"><circle cx="' + f1(cx) + '" cy="' + f1(cy) + '" r="' + f1(r + 3) + '" fill="#9A8F7C" filter="url(#sk-enamel)"/><circle cx="' + f1(cx) + '" cy="' + f1(cy) + '" r="' + f1(r) + '" fill="#DDEBE6"/></g>';
      s += '<defs><clipPath id="' + id + '"><circle cx="' + f1(cx) + '" cy="' + f1(cy) + '" r="' + f1(r) + '"/></clipPath></defs><image href="' + o.img + '" x="' + f1(cx - r) + '" y="' + f1(cy - r) + '" width="' + f1(2 * r) + '" height="' + f1(2 * r) + '" clip-path="url(#' + id + ')"/>';
    } else s += '<g transform="translate(' + f1(x - r - 10) + ' ' + f1(y + r * 0.6) + ')" filter="url(#sk-cast-sm)">' + satChip(r) + '</g>';
    s += '<g transform="rotate(' + (o.rot == null ? -1.2 : o.rot) + ' ' + f1(x) + ' ' + f1(y) + ')">' + paper(x, y, w, h, { cast: 'sk-cast-sm' }) + pin(x + 14, y + 3);
    lines.forEach(function (l, i) { s += text(x + 14, y + 12 + (i + 0.78) * lh, l, { fs: fs, fill: INK }); });
    s += '</g>';
    return { svg: s, w: w + r * 2 + 10, h: h };
  }
  // a rubber stamp (red ink, off-register): o = {x,y,text,rot,fs}
  function stamp(o) { var fs = o.fs || 12, w = tw(o.text, mono(fs, 700)) + 16, h = fs + 10; return '<g transform="translate(' + f1(o.x) + ' ' + f1(o.y) + ') rotate(' + (o.rot || -8) + ')" opacity="' + (o.op || 0.8) + '" filter="url(#sk-stamp)"><rect x="' + f1(-w / 2) + '" y="' + f1(-h / 2) + '" width="' + f1(w) + '" height="' + f1(h) + '" rx="3" fill="none" stroke="' + (o.color || RED) + '" stroke-width="1.8"/><text y="' + f1(fs * 0.36) + '" text-anchor="middle" font-family=\'"Space Mono"\' font-weight="700" font-size="' + fs + '" fill="' + (o.color || RED) + '">' + esc(o.text) + '</text></g>'; }

  // the mint seal: a gold foil rosette with two ribbon tails, pressed onto the card (the mint moment; no reference exists, research §2)
  function seal(cx, cy, r, big, small) {
    var s = '', n = 18, pts = [];
    for (var i = 0; i < n * 2; i++) { var a = i / (n * 2) * Math.PI * 2, rr = i % 2 ? r * 0.88 : r; pts.push([cx + Math.cos(a) * rr, cy + Math.sin(a) * rr]); }
    s += '<g filter="url(#sk-cast)">';
    [[-0.5, '#2E8B6A'], [0.5, '#3E8E73']].forEach(function (t) { var x0 = cx + t[0] * r * 0.55; s += '<path d="M' + f1(x0 - r * 0.22) + ' ' + f1(cy + r * 0.4) + 'L' + f1(x0 + t[0] * r * 0.5 - r * 0.2) + ' ' + f1(cy + r * 1.7) + 'L' + f1(x0 + t[0] * r * 0.5) + ' ' + f1(cy + r * 1.5) + 'L' + f1(x0 + t[0] * r * 0.5 + r * 0.2) + ' ' + f1(cy + r * 1.75) + 'L' + f1(x0 + r * 0.22) + ' ' + f1(cy + r * 0.4) + 'Z" fill="' + t[1] + '" filter="url(#sk-cloth)"/>'; });
    s += '<path d="M' + pts.map(function (p) { return f1(p[0]) + ' ' + f1(p[1]); }).join('L') + 'Z" fill="url(#sk-foil)" filter="url(#sk-enamel-big)"/></g>';
    s += '<circle cx="' + f1(cx) + '" cy="' + f1(cy) + '" r="' + f1(r * 0.7) + '" fill="none" stroke="#9E6A12" stroke-width="1.6" stroke-dasharray="1.6 2.6"/>';
    s += text(cx, cy - r * 0.2, small, { fs: Math.round(r * 0.2), wt: 700, fill: '#6A420C', anchor: 'middle', ls: 1 });
    s += '<text x="' + f1(cx) + '" y="' + f1(cy + r * 0.32) + '" text-anchor="middle" font-family=\'"Lilita One"\' font-size="' + Math.round(r * 0.48) + '" fill="#5A3A0A">' + esc(big) + '</text>';
    return s;
  }
  // soft gold rays behind a moment (the coin-light of Candle Atoll)
  function rays(cx, cy, r, n, op) { var gid = 'skray' + hash(cx + ',' + cy + ',' + r); var s = '<defs><radialGradient id="' + gid + '" gradientUnits="userSpaceOnUse" cx="' + f1(cx) + '" cy="' + f1(cy) + '" r="' + f1(r) + '"><stop offset="0" stop-color="#FFF2C4" stop-opacity="1"/><stop offset="0.35" stop-color="#FFE7A0" stop-opacity="0.7"/><stop offset="1" stop-color="#FFE7A0" stop-opacity="0"/></radialGradient></defs><g opacity="' + (op || 0.5) + '" fill="url(#' + gid + ')">'; for (var i = 0; i < n; i++) { var a0 = i / n * Math.PI * 2, a1 = a0 + Math.PI / n * 0.9; s += '<path d="M' + f1(cx) + ' ' + f1(cy) + 'L' + f1(cx + Math.cos(a0) * r) + ' ' + f1(cy + Math.sin(a0) * r) + 'L' + f1(cx + Math.cos(a1) * r) + ' ' + f1(cy + Math.sin(a1) * r) + 'Z"/>'; } return s + '</g>'; }

  root.SKA = { seal: seal, rays: rays, VERSION: 'sk-art 0.1 (2026-11-04)', P: P, C: C, INK: INK, GREEN: GREEN, RED: RED, THERM: THERM, MINT: MINT, GOLD: GOLD, init: init, svg: svg, f1: f1, esc: esc, tw: tw, mono: mono, lil: lil,
    mix: mix, contrast: contrast, rng: rng, hash: hash, slab: slab, cord: cord, nail: nail, pin: pin, enamelTag: enamelTag, swatch: swatch, plank: plank, paper: paper, paperPath: paperPath,
    plate: plate, text: text, title: title, wrap: wrap, para: para, icon: icon, crown: crown, chip: chip, satChip: satChip, satSays: satSays, stamp: stamp, rrect: rrect };
})(typeof globalThis !== 'undefined' ? globalThis : this);
