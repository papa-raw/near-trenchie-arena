/* snapin/card.js: the persona card (F28) with the boldness gauge (W23), drawn as an enamel plate on the Candle Atoll materials.
 * It draws only what it is given: the persona (name, tag, portrait, bag) and, when the arena has them, the record and the state.
 * No record means an empty gauge that says so; nothing is invented. window.SnapCard.html(opts) -> markup, svg(opts) -> svg string.
 *   opts = { name, tag, portrait (url), preset, bag:[item names], serials:[{name,n}], scars:int,
 *            record: { lives, kos, meanScore (0..1 or null), calibration (0..1: 0 reckless, 1 careful; null = unscored) } | null,
 *            state: 'pending' | 'locked' | 'sale-ready' | null, lines: [[label, value, tone]] }  */
(function (root) {
  'use strict';
  var K = root.SKA, INK = '#2A2622';
  var W = 340, H = 610;   // the bag one item a line, then the gauge below the record line, its end labels and its caption

  function gauge(cx, cy, r, cal) {
    var s = '', a0 = Math.PI, i;
    // five enamel bands from reckless (coral) to careful (mint), drawn as arcs
    var cols = ['#D97A6E', '#F6A796', '#F7CF6B', '#BFE3CF', '#7FCBAE'];
    for (i = 0; i < 5; i++) {
      var t0 = a0 + (Math.PI * i) / 5 + 0.02, t1 = a0 + (Math.PI * (i + 1)) / 5 - 0.02;
      var x0 = cx + Math.cos(t0) * r, y0 = cy + Math.sin(t0) * r, x1 = cx + Math.cos(t1) * r, y1 = cy + Math.sin(t1) * r;
      var xi0 = cx + Math.cos(t0) * (r - 14), yi0 = cy + Math.sin(t0) * (r - 14), xi1 = cx + Math.cos(t1) * (r - 14), yi1 = cy + Math.sin(t1) * (r - 14);
      s += '<path d="M' + K.f1(x0) + ' ' + K.f1(y0) + 'A' + r + ' ' + r + ' 0 0 1 ' + K.f1(x1) + ' ' + K.f1(y1) + 'L' + K.f1(xi1) + ' ' + K.f1(yi1) + 'A' + (r - 14) + ' ' + (r - 14) + ' 0 0 0 ' + K.f1(xi0) + ' ' + K.f1(yi0) + 'Z" fill="' + cols[i] + '" stroke="#9A8F7C" stroke-width="1.2"/>';
    }
    if (cal != null) {
      var ang = a0 + Math.PI * Math.max(0, Math.min(1, cal)), nx = cx + Math.cos(ang) * (r - 4), ny = cy + Math.sin(ang) * (r - 4);
      s += '<path d="M' + cx + ' ' + cy + 'L' + K.f1(nx) + ' ' + K.f1(ny) + '" stroke="' + INK + '" stroke-width="3.4" stroke-linecap="round"/><circle cx="' + cx + '" cy="' + cy + '" r="6" fill="' + INK + '"/>';
    } else {
      s += '<circle cx="' + cx + '" cy="' + cy + '" r="6" fill="#9A8F7C"/>';
    }
    s += K.text(cx - r - 2, cy + 20, 'reckless', { fs: 11, wt: 700, anchor: 'start', fill: '#7A2E22' }) + K.text(cx + r + 2, cy + 20, 'careful', { fs: 11, wt: 700, anchor: 'end', fill: '#1F5E4A' });
    return s;
  }

  function svg(o) {
    o = o || {};
    var rec = o.record || null, name = String(o.name || 'Newcomer'), s = '';
    var fs = 28; while (fs > 16 && K.tw(name, K.lil(fs)) > W - 70) fs -= 2;
    s += K.plate({ x: 6, y: 6, w: W - 12, h: H - 12, r: 16, fill: '#FFF8EA', rim: '#8A5F3C', screws: true, cast: 'sk-cast' });
    s += '<text x="' + W / 2 + '" y="52" text-anchor="middle" font-family=\'"Lilita One"\' font-size="' + fs + '" fill="' + INK + '">' + K.esc(name) + '</text>';
    if (o.tag) s += K.text(W / 2, 70, '“' + o.tag + '” in the arena', { fs: 11, anchor: 'middle', fill: '#655541' });
    s += '<path d="M28 80H' + (W - 28) + '" stroke="#C9BC98" stroke-width="2" stroke-dasharray="3 5"/>';
    // portrait on a mint disc
    s += '<ellipse cx="' + W / 2 + '" cy="188" rx="86" ry="82" fill="#DDEBE6" stroke="#9A8F7C" stroke-width="2"/>';
    if (o.portrait) s += '<image href="' + K.esc(o.portrait) + '" x="' + (W / 2 - 100) + '" y="92" width="200" height="214" preserveAspectRatio="xMidYMid meet"/>';
    // state chip
    var st = o.state;
    if (st) {
      var lab = st === 'pending' ? 'Yours, pending' : st === 'locked' ? 'Locked' : st === 'sale-ready' ? 'Sale-ready' : st;
      s += K.enamelTag({ x: W / 2 - 52, y: 296, h: 26, fs: 11.5, label: lab, sel: st === 'sale-ready' }).svg;
    }
    // bag: four slot lines (items are inventory data on the persona NFT, not NFT media)
    var bag = (o.bag || []).slice(0, 4), slots = ['Weapon', 'Head', 'Body', 'Trinket'];
    // one item a line, trimmed to the plate's width so a long name never runs into its neighbour or off the card
    var fit = function (t, fs, wt) { var max = W - 56, f = (wt === 700 ? '700 ' : '400 ') + fs + 'px "Space Mono"'; if (!K.tw || K.tw(t, f) <= max) return t; while (t.length > 4 && K.tw(t + '…', f) > max) t = t.slice(0, -1); return t + '…'; };
    bag.forEach(function (it, i) { s += K.text(28, 338 + i * 19, fit(slots[i] + ' · ' + it, 11.5, i === 0 ? 700 : 400), { fs: 11.5, wt: i === 0 ? 700 : 400 }); });
    if (o.serials && o.serials.length) s += K.text(28, 338 + 4 * 19 + 4, fit(o.serials.map(function (x) { return x.name + ' #' + x.n; }).join('  '), 11, 700), { fs: 11, wt: 700, fill: '#8A5F3C' });
    // record
    var ry = 446;
    s += K.text(28, ry, rec ? 'Lives ' + rec.lives + ' · KOs ' + rec.kos + (o.scars ? ' · Scars ' + o.scars : '') : (o.recordUnavailable ? 'Record unavailable, retrying' : 'No lives yet'), { fs: 12, wt: 700 });   // a log that cannot be read is not a log with no lives
    s += '<path d="M28 ' + (ry + 8) + 'H' + (W - 28) + '" stroke="#C9BC98" stroke-width="1.5" stroke-dasharray="3 5"/>';
    // the boldness gauge (W23): how far the AI's spreads sit from what happened
    var cal = rec && rec.calibration != null ? rec.calibration : null;
    s += gauge(W / 2, ry + 90, 62, cal);   // the arc's top (ry + 28) clears the record line (ry + 8)
    // the mean score is the ranked probability score of the AI's spreads: 0 is spot on, 1 as far off as a spread can be
    var under = !rec ? (o.recordUnavailable ? 'The gauge waits for the record' : 'No lives scored yet') : (rec.meanScore != null ? 'Mean score ' + Number(rec.meanScore).toFixed(2) + ' (0 = spot on)' : 'No scored lives') + ' · ' + rec.lives + (rec.lives === 1 ? ' life' : ' lives');
    s += K.text(W / 2, ry + 136, under, { fs: 11.5, anchor: 'middle', fill: '#4A443A' });   // below the reckless/careful labels (ry + 110)
    return K.svg(W, H, s, ' role="img" aria-label="' + K.esc(name) + ' persona card" style="width:100%;height:auto;max-width:' + W + 'px"');
  }

  root.SnapCard = { svg: svg, html: function (o) { return '<div class="persona-card">' + svg(o) + '</div>'; }, W: W, H: H };
})(typeof globalThis !== 'undefined' ? globalThis : this);
