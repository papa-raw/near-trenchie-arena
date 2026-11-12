/* snapin/ui.js: shared helpers for the snap-in screens (join flow, login doors, workshop).
 * Look: the approved S1 A / S2 A / S4 B drawings (Candle Atoll materials from art/ska.js). Classic script, window.SnapUI.
 * Materials are painted into SVG layers behind each element by paint(); text always sits on plain cream surfaces. */
(function (root) {
  'use strict';
  var esc = function (s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); };
  var btn = function (t, act, cls, attr) { return '<button type="button" class="' + (cls || '') + '" data-act="' + esc(act || '') + '" ' + (attr || '') + '>' + t + '</button>'; };
  var receipt = function (s) { return '<div class="receipt" data-material="paper">' + s + '</div>'; };
  var chips = function (a) { return '<div class="ribbon">' + a.map(function (s) { return '<span>' + s + '</span>'; }).join('') + '</div>'; };
  var line = function (k, v) { return '<div class="line"><b>' + k + '</b><span>' + v + '</span></div>'; };
  // a duration in ms as the reader sees it: '500' -> '0.5 s', '60000' -> '60 s' (never rounded to a whole second)
  var seconds = function (ms) { var n = Number(ms); return Number.isFinite(n) && n >= 0 ? String(Math.round(n) / 1000) + ' s' : '?'; };

  // storage that never throws (private windows, blocked site data)
  var mem = {};
  var store = {
    get: function (k) { try { var v = root.localStorage.getItem(k); return v == null ? (mem[k] == null ? null : mem[k]) : v; } catch (e) { return mem[k] == null ? null : mem[k]; } },
    set: function (k, v) { mem[k] = v; try { root.localStorage.setItem(k, v); } catch (e) { /* kept in memory */ } },
    del: function (k) { delete mem[k]; try { root.localStorage.removeItem(k); } catch (e) { /* ignore */ } },
    json: function (k, d) { try { var v = store.get(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } }
  };

  // paint the wood / paper / enamel layers behind [data-material] elements and buttons
  function paint(scope) {
    var SKA = root.SKA; if (!SKA) return;
    (scope || document).querySelectorAll('[data-material],button').forEach(function (el) {
      var old = el.querySelector(':scope > svg.material'); if (old) old.remove();
      var r = el.getBoundingClientRect(), w = Math.round(r.width), h = Math.round(r.height);
      if (!w || !h) return;
      var art, pressed = el.getAttribute('aria-pressed') === 'true';
      if (el.dataset.material === 'wood') art = SKA.plank({ x: 0, y: 0, w: w, h: h, text: '', cords: true, cordLen: 12, color: '#c9966a' }).svg;
      else if (el.dataset.material === 'paper') art = '<path d="' + SKA.paperPath(0, 0, w, h) + '" fill="#fff8ea" stroke="#d8cdb8"/>';
      else art = SKA.plate({ x: 0, y: 0, w: w, h: h, r: 8, fill: pressed ? '#9fdcc5' : el.classList.contains('main-action') ? '#f7cf6b' : '#fff8ea', rim: '#a08252', screws: false, cast: 'sk-cast-sm' });
      if (el.tagName === 'BUTTON') {
        var fill = pressed ? '#9fdcc5' : el.classList.contains('main-action') ? '#f7cf6b' : '#fff8ea';
        art += '<rect x="5" y="5" width="' + Math.max(0, w - 10) + '" height="' + Math.max(0, h - 10) + '" rx="4" fill="' + fill + '"/>';
      }
      el.insertAdjacentHTML('afterbegin', SKA.svg(w, h, art, ' class="material" aria-hidden="true"'));
    });
  }

  function copyText(text) {
    try { if (root.navigator.clipboard && root.navigator.clipboard.writeText) return root.navigator.clipboard.writeText(text).then(function () { return true; }, function () { return false; }); } catch (e) { /* fall through */ }
    return Promise.resolve(false);
  }

  // the in-ring card's "Prediction for this life", from room.js's lastPick. A queued pick is one the room locked for this
  // life while the ring was full (or an owner check still ran): it fights on that lock once seated, so it is never "not
  // accepted"; room.js marks it seated when the public view shows the fighter in the ring.
  function pickLine(lp) {
    if (!lp) return 'not sent yet';
    if (lp.state === 'accepted') return 'locked in';
    if (lp.state === 'queued') return lp.seated ? 'locked in' : 'locked in; waiting for a seat';
    if (lp.state === 'none') return 'none (your AI chose none)';
    return 'not accepted';
  }

  root.SnapUI = { esc: esc, btn: btn, receipt: receipt, chips: chips, line: line, seconds: seconds, store: store, paint: paint, copyText: copyText, pickLine: pickLine };
})(typeof globalThis !== 'undefined' ? globalThis : this);
