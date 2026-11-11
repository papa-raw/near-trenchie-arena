/* Persona emoji set for the creator's sheet (Battle mode, Pat 2026-11-11): the glyphs a persona's AI picks from
   when it speaks, one per line, shown over its fighter. Same rules as near/lore/emoji.py (the host checks again):
   5-8 unique single emoji, each 1-4 code points, pictographic or a modifier (FE0F, 200D, 1F3FB-1F3FF, 20E3), at most
   16 UTF-8 bytes, no ASCII. A sheet without a valid set writes no game.emoji, and the temperament's default applies.
   A classic script, loaded by art/bridge.js before sheet.js: window.SnapEmoji. No DOM, no fetch. */
(function (root) {
  'use strict';
  var DEFAULTS = {"sunny": ["😄", "☀️", "🌈", "🎉", "😎", "🤙"], "deadpan": ["😐", "🙄", "🫠", "🗿", "☕", "🧊"], "earnest": ["🙏", "💪", "🫡", "📣", "✊", "🤝"], "gruff": ["😤", "💢", "👊", "🔥", "🪓", "🐗"], "serene": ["😌", "🌊", "🍃", "🧘", "🌙", "🪷"], "restless": ["⚡", "🏃", "🌀", "😵‍💫", "🐇", "🚀"]};
  var SUGGEST = {"sunny": ["😄", "☀️", "🌈", "🎉", "😎", "🤙", "🌞", "🥳", "😆", "🍹", "🌻", "👋"], "deadpan": ["😐", "🙄", "🫠", "🗿", "☕", "🧊", "😑", "🤷", "🫤", "📎", "🪨", "🤔"], "earnest": ["🙏", "💪", "🫡", "📣", "✊", "🤝", "🤗", "📚", "🌟", "🙌", "🫶", "📝"], "gruff": ["😤", "💢", "👊", "🔥", "🪓", "🐗", "😠", "🦬", "🪵", "🔨", "🐻", "🥊"], "serene": ["😌", "🌊", "🍃", "🧘", "🌙", "🪷", "🌿", "🕊️", "🌅", "🫖", "🌸", "☁️"], "restless": ["⚡", "🏃", "🌀", "😵‍💫", "🐇", "🚀", "💨", "🏎️", "⏩", "🐿️", "🌪️", "⏱️"]};
  var MIN_SET = 5, MAX_SET = 8, MAX_POINTS = 4, MAX_BYTES = 16;
  var PICTO = /^\p{Extended_Pictographic}$/u;

  var TEXT_DEFAULT = [0xA9, 0xAE, 0x203C, 0x2049, 0x2122, 0x2139, 0x24C2, 0x3030, 0x303D, 0x3297, 0x3299];
  function textDefault(cp) { return TEXT_DEFAULT.indexOf(cp) >= 0 || (cp >= 0x2194 && cp <= 0x21AA); }
  function isSkin(cp) { return cp >= 0x1F3FB && cp <= 0x1F3FF; }

  function isModifier(cp) {
    return cp === 0xFE0F || cp === 0x200D || cp === 0x20E3 || (cp >= 0x1F3FB && cp <= 0x1F3FF);
  }

  function checkGlyph(g) {
    if (typeof g !== 'string' || g === '') return 'an emoji is a non-empty string';
    var points = Array.from(g);
    var bytes = new TextEncoder().encode(g).length;
    if (points.length > MAX_POINTS || bytes > MAX_BYTES) return JSON.stringify(g) + ' is longer than one emoji';
    for (var i = 0; i < points.length; i++) {
      var cp = points[i].codePointAt(0);
      if (cp < 0x80) return JSON.stringify(g) + ' holds ASCII; an emoji set holds emoji only';
      var picto = PICTO.test(points[i]);
      if (i === 0 ? !picto : !(picto || isModifier(cp))) return JSON.stringify(g) + ' is not an emoji';
    }
    var cps = points.map(function (p) { return p.codePointAt(0); });
    if (textDefault(cps[0]) && cps[1] !== 0xFE0F) return JSON.stringify(g) + ' is a text symbol; as an emoji it needs U+FE0F after it';
    for (var k = 0; k < cps.length; k++) {
      if (cps[k] !== 0x200D) continue;
      var before = cps[k - 1], after = cps[k + 1];
      var okBefore = k > 0 && (PICTO.test(String.fromCodePoint(before)) || before === 0xFE0F || isSkin(before));
      if (!okBefore || k === cps.length - 1 || !PICTO.test(String.fromCodePoint(after))) return JSON.stringify(g) + ' has a joiner that joins nothing';
    }
    return null;
  }

  function checkSet(list) {
    if (!Array.isArray(list) || list.length < MIN_SET || list.length > MAX_SET) return 'an emoji set holds 5 to 8 emoji';
    var seen = {};
    for (var i = 0; i < list.length; i++) {
      var reason = checkGlyph(list[i]);
      if (reason) return reason;
      var same = list[i].replace(/\uFE0F/g, '');      // ☀ and ☀️ are one emoji
      if (seen[same]) return 'an emoji set holds each emoji once';
      seen[same] = true;
    }
    return null;
  }

  function suggest(temperament) {
    return (SUGGEST[String(temperament || '').toLowerCase()] || []).slice();
  }

  var api = { checkSet: checkSet, checkGlyph: checkGlyph, DEFAULTS: DEFAULTS, suggest: suggest };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.SnapEmoji = api;
})(typeof window !== 'undefined' ? window : this);
