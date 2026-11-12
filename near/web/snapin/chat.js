/* snapin/chat.js: the owner's order box beside the persona (the browser player's only way to steer; no direct controls).
 * The owner types an order in plain words; the player's AI (brain.js, SnapBrain.tell) answers in the trenchie's voice and
 * turns it into a behaviour the host acknowledges. Under the order: (1) the trenchie's reply, (2) the host's receipt verbatim
 * in a quiet mono line; a refused order shows the host's fixes. Drawn in the S1-redraw A ring-view vocabulary (receipt card,
 * the card's type and colours), no new chrome. A classic script: window.SnapChat.
 *   SnapChat.html({ name, compact })  -> markup (a form; the page wires it with SnapChat.wire(root, rerender))
 * When the AI cannot take orders (no brain.js on this page, no key, no cap, the cap reached, a permanent failure, no storage
 * for the hourly spend, no Web Locks), the box is off and says why in the AI's own words; with no AI door, or an agent door
 * (the agent takes orders in its own session), no form is drawn: only the heading and where orders go (a link to the AI step
 * when there is no door). SnapChat.html({ card: true }) when the fighter card beside it already says why. */
(function (root) {
  'use strict';
  var MAX = 300;
  // its own escape: the arena page has no ui.js, and an order or a reply is never trusted as markup
  var esc = function (s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); };
  var S = { draft: '', sending: false, error: '', last: null, turns: [], brain: null, hooked: false, more: false };
  // the guide's AI step, beside this script (the guide and arena.html load it from different folders); the arena's ws rides along
  var AI_STEP = (function () {
    try {
      var src = root.document && root.document.currentScript && root.document.currentScript.src, u = new URL('index.html', src || root.location.href);
      u.searchParams.set('step', 'doors'); var ws = new URLSearchParams(root.location.search).get('ws'); if (ws) u.searchParams.set('ws', ws);
      return u.pathname + u.search;
    } catch (e) { return 'index.html?step=doors'; }
  })();

  function brain() { return root.SnapBrain && typeof root.SnapBrain.tell === 'function' ? root.SnapBrain : null; }
  function hook(rerender) {
    if (S.hooked || !root.SnapBrain || !root.SnapBrain.on) return;
    S.hooked = true;
    root.SnapBrain.on(function (st) { S.brain = st; if (st && Array.isArray(st.conversation)) S.turns = st.conversation.slice(-20); if (rerender) rerender(); });
  }
  // brain.js's states that take no order: no key, no cap, the cap reached, a permanent failure, no storage for the hourly
  // spend, no Web Locks to share the cap between tabs
  var OFF_STATES = ['no-key', 'no-cap', 'capped', 'failed', 'no-storage', 'no-locks'];
  // why the box is off, or '' when it can take an order
  function offReason() {
    if (!root.SnapBrain) return 'Your trenchie can’t take orders on this page: its AI is not loaded here.';
    if (!brain()) return 'Your trenchie can’t take orders yet: this version of its AI has no order channel.';
    var st = S.brain && S.brain.state;
    // no AI door: orders have nowhere to go from this page (brain.js 'no-door'); an agent door: the agent takes orders in its
    // own session, through SNAP.md ('agent-door'). Both are known from the first frame (brain.js gateNow at the room's "in").
    if (st === 'no-door') return 'Pick an AI door to give orders.';
    if (st === 'agent-door') return 'Your agent drives this trenchie (it joined through SNAP.md); type orders in its session.';
    // every state in which brain.js sends no call: the box is off with the brain's own words (it never offers "Try again")
    if (OFF_STATES.indexOf(st) >= 0) return (S.brain.chip || 'Your AI is not driving right now.');
    return '';
  }
  // The host's receipt, exactly as it wrote it: the summary verbatim (escaped, never markup), its status only as a colour. The engine's
  // ack names the first fix in its summary, so only the fixes after the first are listed below it.
  function fixesOf(r) {
    var f = Array.isArray(r.fixes) ? r.fixes : [].concat(r.refused || [], r.clipped || []);
    return f.map(function (x) { return typeof x === 'string' ? x : (x && (x.fix || x.text)) || ''; }).filter(Boolean);
  }
  function receiptLine(r, compact) {
    if (!r) return '';
    var st = r.status || r.state || '', more = fixesOf(r).slice(1);
    var cls = 'chat-receipt' + (st === 'refused' ? ' refused' : st === 'clipped' ? ' clipped' : '') + (compact && !S.more ? ' folded' : '');
    var line = '<div class="' + cls + '" data-status="' + esc(st) + '">' + esc(r.summary || '') + '</div>';
    if (compact) return line + ((r.summary || '').length > 44 || more.length ? '<button type="button" class="chat-more" data-act="chat-more" aria-expanded="' + S.more + '">' + (S.more ? 'Less' : 'More') + '</button>' : '') + (S.more && more.length ? '<ul class="chat-fixes">' + more.map(function (f) { return '<li>' + esc(f) + '</li>'; }).join('') + '</ul>' : '');
    return line + (more.length ? '<ul class="chat-fixes">' + more.map(function (f) { return '<li>' + esc(f) + '</li>'; }).join('') + '</ul>' : '');
  }
  function turnsHtml(compact) {
    var t = S.turns.length ? S.turns : (S.last ? S.last.turns || [] : []);
    if (S.last) { var cut = -1; for (var i = t.length - 1; i >= 0; i--) if (t[i].who === 'owner') { cut = i; break; } if (cut >= 0) t = t.slice(0, cut); }   // the latest exchange is shown above, once
    if (!t.length) return '';
    var shown = t.slice(compact ? -2 : -6);
    return '<ol class="chat-turns" aria-label="Recent orders and replies">' + shown.map(function (x) {
      if (x.who === 'owner') return '<li class="owner"><span class="who">You</span>' + esc(x.text) + '</li>';
      if (x.who === 'trenchie') return '<li class="trenchie"><span class="who">' + esc(x.name || 'Your trenchie') + '</span>“' + esc(x.text) + '”</li>';
      return '<li class="host">' + receiptLine(x.receipt || { status: x.status || x.state, summary: x.text, fixes: x.fixes }) + '</li>';
    }).join('') + '</ol>';
  }
  // The two states that last until the player acts elsewhere (no AI door; an agent that takes orders in its own session): no
  // form at all, only the heading and one line. With o.card the fighter card beside it already says why, so the line is only
  // the way on; without it (arena.html) the line says both.
  function doorState() { var st = S.brain && S.brain.state; return root.SnapBrain && brain() && (st === 'no-door' || st === 'agent-door') ? st : ''; }
  function doorHtml(o, st) {
    var link = '<a class="chat-door-link" href="' + esc(AI_STEP) + '">Pick an AI door</a>';
    var line = st === 'no-door' ? (o.card ? link + ' to give orders.' : 'No AI door picked: ' + link + ' to give orders.')
      : (o.card ? 'Orders go to your agent: type them in its session.' : 'Your agent drives this trenchie (it joined through SNAP.md); type orders in its session.');
    return '<div class="chat chat-door' + (o.compact ? ' compact' : '') + '" data-chat data-door="' + st + '">' +
      '<div class="eyebrow">' + (o.compact ? 'Orders' : 'Orders for ' + esc(o.name || 'your trenchie')) + '</div>' +
      '<p class="sub" id="order-state" role="status">' + line + '</p></div>';
  }
  function html(o) {
    o = o || {};
    var door = doorState(); if (door) return doorHtml(o, door);
    var off = offReason(), n = S.draft.length, compact = !!o.compact, last = S.last;
    // brain.js's tell() answers the reply as a string (an older stand-in answered { text }): either reads
    var rt = last && last.reply ? (typeof last.reply === 'string' ? last.reply : last.reply.text) : '';
    var reply = rt ? '<div class="chat-reply' + (compact ? ' one-line' : '') + '" role="status" title="' + esc(rt) + '">“' + esc(rt) + '”</div>' : '';
    var receipt = last && last.receipt ? receiptLine(last.receipt, compact) : '';
    return '<form class="chat' + (compact ? ' compact' : '') + '" data-chat novalidate>' +
      (compact ? '' : '<div class="eyebrow">Orders for ' + esc(o.name || 'your trenchie') + '</div>') +
      '<label class="field" for="order">' + (compact ? 'Order' : 'Tell your trenchie what to do') + '</label>' +
      '<textarea id="order" maxlength="' + MAX + '" rows="' + (compact ? 1 : 2) + '" placeholder="' + (off ? '' : 'Grab the loot and stay away from fights') + '"' + (off ? ' disabled' : S.sending ? ' readonly aria-busy="true"' : '') + ' aria-describedby="order-count order-state">' + esc(S.draft) + '</textarea>' +
      '<div class="chat-row"><span class="sub" id="order-count">' + n + ' / ' + MAX + '</span>' +
      '<button type="submit" class="secondary chat-send" data-act="chat-send"' + (off || S.sending || !S.draft.trim() ? ' disabled aria-disabled="true"' : '') + '>' + (S.sending ? 'Sending…' : 'Send order') + '</button></div>' +
      '<div id="order-state" aria-live="polite">' + (off ? '<div class="sub" role="status">' + esc(off) + '</div>' : '') + (S.error ? '<div class="sub" role="alert">' + esc(S.error) + '</div>' : '') + reply + receipt + '</div>' +
      (compact ? '' : turnsHtml(false)) + '</form>';
  }
  async function send(rerender) {
    var b = brain(), text = S.draft.trim();
    if (!b || S.sending || offReason()) return;   // an off box sends nothing (Enter in a stale form included)
    if (!text || text.length > MAX) { S.error = 'Write what you want your trenchie to do (1–300 characters).'; return rerender && rerender(); }
    S.sending = true; S.error = ''; rerender && rerender();
    try {
      var r = await b.tell(text);
      if (r && (r.reply || r.receipt)) { S.last = r; S.draft = ''; }
      else S.error = (r && r.chip) || 'Your trenchie did not answer. Try again in a moment.';
    } catch (e) { S.error = 'The order did not go through: ' + (e && e.message ? e.message : 'no answer') + '. Try again.'; }
    S.sending = false; S.more = false; rerender && rerender();
    var box = root.document && root.document.querySelector('[data-chat] #order');   // a keyboard owner types the next order straight away
    if (box && !box.disabled) { box.focus({ preventScroll: true }); try { box.setSelectionRange(box.value.length, box.value.length); } catch (e) { /* none */ } }
  }
  // wire the box inside `scope`: typing keeps the draft (no re-render), Enter sends, Shift+Enter breaks a line
  function wire(scope, rerender) {
    hook(rerender);
    var form = scope.querySelector('[data-chat]'); if (!form || form.__wired) return; form.__wired = true;
    var ta = form.querySelector('#order'), count = form.querySelector('#order-count'), btn = form.querySelector('.chat-send');
    if (!ta || !count || !btn) return;   // a door state draws no form: nothing to wire
    ta.addEventListener('input', function () { S.draft = ta.value.slice(0, MAX); count.textContent = S.draft.length + ' / ' + MAX; var dis = !!offReason() || S.sending || !S.draft.trim(); btn.disabled = dis; btn.setAttribute('aria-disabled', String(dis)); });
    ta.addEventListener('keydown', function (e) { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(rerender); } });
    form.addEventListener('submit', function (e) { e.preventDefault(); send(rerender); });
    form.addEventListener('click', function (e) { var m = e.target.closest && e.target.closest('.chat-more'); if (m) { e.preventDefault(); S.more = !S.more; rerender && rerender(); var b = root.document.querySelector('[data-chat] .chat-more'); if (b) b.focus({ preventScroll: true }); } });
  }
  root.SnapChat = { html: html, wire: wire, send: send, state: S, MAX: MAX };
})(typeof globalThis !== 'undefined' ? globalThis : this);
