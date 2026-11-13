/* snapin/panel.js: the player's own trenchie panel on the arena page, as drawn on board 1 (on the right; a bottom sheet on a
 * phone; a tab at the edge when closed). Its parts and where each comes from, never a sample:
 *   head        the draft's name and battle option, the life, the AI it fights with; HP from /dev/corner; a state pill
 *   gear        the four equipped items and the bag (/dev/corner bench.equipped, bench.bag)
 *   money       a key door: this hour's spend against the cap and this visit's (the brain's spend window, shared by every tab);
 *               a plan door: the session's weekly use against its own stop (/snap/code/<code>/log), or "not reported"
 *   log         the arena's events for this trenchie (/dev/corner events or the code log), the player's orders with the
 *               trenchie's reply and the host's receipt, "thinking…" while the AI's call is out
 *   order box   Send (a key door), Raise cap (capped), Send back in (on the bench), or where orders go (a plan door)
 *   bench       Stay on the bench, the equipped items and the bag to swap (SnapRoom.bench)
 * A part whose source has nothing to say is left out rather than drawn with made-up numbers. window.SnapPanel. */
(function (root) {
  'use strict';
  var doc = root.document, C = root.SnapGuideCopy && root.SnapGuideCopy.panel, F = root.SnapGuideCopy && root.SnapGuideCopy.fill;
  // the guide's AI step, beside this script, with the arena's ws (as chat.js builds it)
  var AI_STEP = (function () {
    try {
      var src = doc && doc.currentScript && doc.currentScript.src, u = new URL('index.html', src || root.location.href);
      u.searchParams.set('step', 'doors'); var ws = new URLSearchParams(root.location.search).get('ws'); if (ws) u.searchParams.set('ws', ws);
      return u.pathname + u.search;
    } catch (e) { return 'snapin/index.html?step=doors'; }
  })();
  if (!C) return;
  var SAVE = 'trenchie.snapin.v1', CAP_STORE = 'trenchie.snapin.cap', SPEND_STORE = 'trenchie.snapin.brain.spend', OPEN_STORE = 'trenchie.panel.open', TURNS = 'trenchie.panel.turns.';
  var PRESETS = ['Brawler Swing', 'Hunter Lunge', 'Survivor Beam', 'Looter Lob', 'Brawler Zap'];
  var SLOTS = ['head', 'body', 'weapon', 'trinket'];
  var ICON = {   // one drawing per slot (the item's own still is the card's)
    head: '<path d="M6 25h28l-3-4H9z" fill="#e8925f"/><path d="M10 21c0-8 4-13 10-13s10 5 10 13z" fill="#f2a46d"/><circle cx="20" cy="8" r="2.2" fill="#d97757"/>',
    body: '<path d="M12 8l4 3h8l4-3 5 6-3 18H10L7 14z" fill="#c9966a"/><path d="M20 11v21" stroke="#8a5f3c" stroke-width="2"/>',
    weapon: '<path d="M9 33L30 8" stroke="#a0683c" stroke-width="4.5" stroke-linecap="round"/><circle cx="24" cy="15" r="2" fill="#6e4b2e"/>',
    trinket: '<path d="M20 7c8 0 13 7 13 14-4 7-22 7-26 0 0-7 5-14 13-14z" fill="#a9d4f5"/><path d="M20 8v19M13 11l4 15M27 11l-4 15" stroke="#6fa3d6" stroke-width="1.6"/>'
  };
  var esc = function (s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); };
  var nb = function (s) { return String(s).replace(/(\d) (s|tiles|of 10)\b/g, '$1&nbsp;$2'); };
  var ls = { get: function (k) { try { return root.localStorage.getItem(k); } catch (e) { return null; } }, set: function (k, v) { try { root.localStorage.setItem(k, v); } catch (e) { /* this page only */ } } };
  var ss = { get: function (k) { try { return JSON.parse(root.sessionStorage.getItem(k) || 'null'); } catch (e) { return null; } }, set: function (k, v) { try { root.sessionStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* memory */ } } };
  var ico = function (slot, s) { return '<svg viewBox="0 0 40 40" width="' + s + '" height="' + s + '" aria-hidden="true">' + (ICON[slot] || '') + '</svg>'; };
  var hhmm = function (ms) { var d = new Date(ms); return ('0' + d.getHours()).slice(-2) + ':' + ('0' + d.getMinutes()).slice(-2); };
  var usd = function (n) { return '$' + (Math.round(Number(n || 0) * 100) / 100).toFixed(2); };
  function phone() { return (root.innerWidth || 1440) <= 600; }
  function draft() { try { return JSON.parse(ls.get(SAVE) || '{}') || {}; } catch (e) { return {}; } }

  var S = { open: ls.get(OPEN_STORE) !== '0', tab: 'chat', capEdit: false, capPick: null, raisePick: null, corner: null, codeLog: null, brain: null, draft: '', sending: false,
            note: '', turns: [], visit: Date.now(), timer: null, el: null, room: null, swapMsg: '', leaving: false, leaveMsg: '' };

  // ------------------------------------------------------------------ who is mine, from which source
  function mine() {
    var R = root.SnapRoom, st = R && R.status(), P = draft(), door = P.door || {};
    if (door.route === 'plan' && P.planCode && S.codeLog && S.codeLog.joined) {
      var L = S.codeLog; return { id: L.fighter_id, name: P.name || L.name, preset: P.preset, life: L.life, agent: door.identity === 'Codex' ? 'Codex' : 'Claude Code', plan: true };
    }
    if (st && st.fighter && /^(in|joining|offline|leaving)$/.test(st.phase)) {
      // the host's bench.next_life is the coming life (on the bench, life_id already names it): the header shows the life just
      // ended while the trenchie is down or held, the current one in the ring
      var c = S.corner, bn = c && c.bench, life = bn && bn.next_life ? ((bn.down || bn.held) ? bn.next_life - 1 : bn.next_life) : (st.fighter.lives || 1);
      return { id: st.fighter.id, name: P.name || st.fighter.name, preset: P.preset, life: life, door: door.door || '', plan: false };
    }
    return null;
  }
  function shortOf(n) { return String(n || '').trim().split(/\s+/)[0] || ''; }
  function avatar(m) { var i = PRESETS.indexOf(m.preset); return './snapin/img/avatar-' + (i < 0 ? 0 : i) + '.png'; }

  // ------------------------------------------------------------------ the parts
  function stateOf(m) {
    var b = S.brain || {}, c = S.corner || {}, bench = c.bench || {};
    if (!m.plan && b.thinking) return ['thinking', ''];
    if (!m.plan && capped()) return ['capped', ' warn'];
    if (bench.held) return ['bench', ' bench'];
    if (bench.down) return ['benchDown', ' bench'];
    return ['fight', ''];
  }
  function head(m) {
    var st = stateOf(m), hp = m.plan ? S.codeLog && S.codeLog.hp : S.corner && S.corner.hp, max = m.plan ? S.codeLog && S.codeLog.max_hp : S.corner && S.corner.max_hp;
    var hpRow = hp != null && max ? '<div class="hprow"><span class="hpl">' + C.hp + '</span><div class="hp grow" role="img" id="pn-hpbar" aria-label="HP ' + hp + ' of ' + max + '"><i style="width:' + Math.max(0, Math.min(100, Math.round(100 * hp / max))) + '%"></i></div><span class="hpn" id="pn-hpn">' + hp + '/' + max + '</span><span class="state' + st[1] + '">' + C.states[st[0]] + '</span></div>' : '';
    var source = m.plan ? F(C.session, { agent: m.agent }) : m.door;
    var room = root.SnapRoom, rs = room && room.status(), remote = m.plan && !(rs && rs.fighter && rs.fighter.id === m.id);
    var busy = S.leaving || (rs && /^(joining|leaving)$/.test(rs.phase));
    var leave = '<button type="button" class="plate leave" data-pn="leave"' + (busy || remote || !room || !room.leave ? ' disabled' : '') + (remote ? ' title="' + C.leaveAgent + '"' : '') + '>' + C.leave + '</button>';
    return '<div class="ph"><img src="' + avatar(m) + '" alt=""><div class="ph-mid"><h2>' + esc(m.name) + '</h2><div class="sub">' + esc(F(C.life, { life: m.life || 1, source: source }).replace(/ · $/, ''))   /* no AI door: no source after the dot */ + '</div>' + hpRow + '</div>' +
      '<div class="ph-r"><div class="icons">' + leave + '<button type="button" class="ib plate" data-pn="close" aria-label="' + C.close + '">×</button></div></div></div>';
  }
  function equipped() { var b = S.corner && S.corner.bench; return b && Array.isArray(b.equipped) ? SLOTS.map(function (k) { return b.equipped.filter(function (x) { return x.slot === k; })[0]; }).filter(Boolean) : []; }
  function bag() { var b = S.corner && S.corner.bench; return b && Array.isArray(b.bag) ? b.bag : []; }
  function gearRow(m) {
    if (!m.plan && onBench()) return '';
    var eq = equipped(); if (!eq.length) return '';
    return '<div class="gearrow"><span class="gh">' + C.gearH + '</span>' + eq.map(function (g) { return '<span class="gi" title="' + esc(C.slots[g.slot] || g.slot) + '">' + ico(g.slot, 26) + '<span>' + esc(g.name) + '</span></span>'; }).join('') +
      '<a href="#" class="link bagl" title="' + C.bagHint + '" data-pn="bag">' + F(C.bag, { n: bag().length }) + '</a></div>';
  }
  function spendRows() { try { var r = JSON.parse(ls.get(SPEND_STORE) || '[]'); return Array.isArray(r) ? r.filter(function (x) { return x && typeof x.at === 'number' && typeof x.usd === 'number'; }) : []; } catch (e) { return []; } }
  // The cap is the stored one: the brain reads that same key at every step (≤ 5 s), so a cap just set shows at once instead of
  // the brain's copy from its last step. The brain's "capped" counts only while this hour's spend still reaches the cap.
  function cap() { var b = S.brain || {}, c = Number(ls.get(CAP_STORE)); if (!(c > 0) && b.capUsd != null) c = Number(b.capUsd); return c > 0 ? c : 0; }
  function hourSpend() { var b = S.brain || {}, hourAgo = Date.now() - 3600000; return b.spendHourUsd != null ? Number(b.spendHourUsd) : spendRows().filter(function (x) { return x.at > hourAgo; }).reduce(function (t, x) { return t + x.usd; }, 0); }
  function capped() { return !!(S.brain && S.brain.state === 'capped' && hourSpend() >= cap()); }
  function money(m) {
    var M = C.money;
    if (m.plan) {
      var pl = S.codeLog && S.codeLog.plan || {}, stop = pl.stop_pct;
      if (stop == null) return '';
      if (pl.week_used_pct == null) return '<div class="mny"><div>' + esc(F(C.plan.unknown, { agent: m.agent })) + '</div><div class="muted">' + F(C.plan.stop, { stop: stop }) + '</div></div>';
      return '<div class="mny"><div class="spread"><span>' + F(C.plan.reports, { pct: pl.week_used_pct, stop: stop }) + '</span><span class="muted">' + C.plan.from + '</span></div><div class="meter"><i style="width:' + Math.min(100, Math.round(100 * pl.week_used_pct / stop)) + '%"></i></div></div>';
    }
    var c = cap(); if (!c) return '';
    var rows = spendRows(), hourAgo = Date.now() - 3600000, hour = hourSpend();
    var visit = rows.filter(function (x) { return x.at >= S.visit; }).reduce(function (t, x) { return t + x.usd; }, 0), full = capped();
    var oldest = rows.filter(function (x) { return x.at > hourAgo; }).map(function (x) { return x.at; }).sort()[0];
    var tail = full && oldest ? ' · ' + F(M.resets, { time: hhmm(oldest + 3600000) }) : m.door === 'NEAR AI Cloud' ? ' · ' + M.rate : '';
    var s = '<div class="mny"><div>' + F(M.hour, { spent: usd(full ? c : hour), cap: usd(c) }) + '</div><div class="meter' + (full ? ' full' : '') + '"><i style="width:' + Math.min(100, Math.round(100 * (full ? 1 : hour / c))) + '%"></i></div>' +
      '<div class="spread"><span class="muted">' + F(M.visit, { visit: usd(visit) }) + '<span class="rate">' + tail + '</span></span>' + (S.capEdit ? '' : '<a href="#" class="link" data-pn="capedit">' + M.change + '</a>') + '</div>';
    if (S.capEdit) {
      var pick = S.capPick != null ? S.capPick : c;
      s += '<div class="capedit"><div class="chipline">' + M.caps.map(function (x) { var v = Number(x.slice(1)), on = Math.abs(v - pick) < 1e-9; return '<button type="button" class="chip' + (on ? ' on' : '') + '" data-pn="cap:' + v + '" aria-pressed="' + on + '">' + x + '</button>'; }).join('') + '</div><button type="button" class="plate" data-pn="setcap">' + M.set + '</button></div>';
    }
    return s + '</div>';
  }
  function slip(r, appliedS) {
    if (!r) return '';
    var items = String(r.summary || '').replace(/^New behaviour recorded:\s*/, '').split(/\s+·\s+/).filter(Boolean);
    return '<div class="slip"><div class="h"><span>' + C.receiptH + '</span>' + (appliedS != null ? '<span>' + nb(F(C.applied, { t: appliedS })) + '</span>' : '') + '</div><ul>' + items.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>' + (r.why ? '<div class="why">' + C.why + esc(r.why) + '</div>' : '') + '</div>';
  }
  function logEntries(m) {
    var out = [], short = shortOf(m.name);
    var evs = m.plan ? (S.codeLog && S.codeLog.log || []) : (S.corner && S.corner.events || []);
    evs.forEach(function (e) {
      // an order the session posted (its words, reply and why) and the host's receipt for it; a session that sends only the
      // behaviour leaves the words empty, and the receipt still shows
      if (e.kind === 'order') out.push({ at: e.at_ms, html: (e.order ? '<div class="you ses"><span class="sl">' + C.agent.from + '</span>“' + esc(e.order) + '”<span class="t">' + hhmm(e.at_ms) + '</span></div>' : '') +
        (e.reply || e.receipt ? '<div class="reply"><span class="who">' + esc(short) + '</span>' + (e.reply ? '“' + esc(e.reply) + '”' : '') + slip(e.receipt ? Object.assign({ why: e.why }, e.receipt) : null, e.receipt && e.receipt.applies_in_ms != null ? (e.receipt.applies_in_ms / 1000).toFixed(1) : null) + '</div>' : '') });
      else {
        // the host's join line names no door; the sheet's does: "Snapped in. Life 1 on NEAR AI Cloud." or "Your Codex session joined. Life 1."
        var jl = e.kind === 'joined' && /Life (\d+)/.exec(e.text || ''), text = !jl ? e.text : m.plan ? F(C.agent.joined, { agent: m.agent, life: jl[1] }) : m.door ? F(C.joined, { life: jl[1], door: m.door }) : e.text;
        out.push({ at: e.at_ms, html: '<div class="ev"><span class="t">' + hhmm(e.at_ms) + '</span> ' + esc(text) + '</div>' });
      }
    });
    if (!m.plan) S.turns.forEach(function (t) {
      out.push({ at: t.at, html: '<div class="you">' + esc(t.text) + '<span class="t">' + hhmm(t.at) + '</span></div>' +
        (t.reply || t.receipt ? '<div class="reply"><span class="who">' + esc(short) + '</span>' + (t.reply ? '“' + esc(t.reply) + '”' : '') + slip(t.receipt, t.appliedMs != null ? (t.appliedMs / 1000).toFixed(1) : null) + '</div>' : '') +
        (t.chip ? '<div class="ev">' + esc(t.chip) + '</div>' : '') });
    });
    out.sort(function (a, b) { return a.at - b.at; });
    var h = out.map(function (x) { return x.html; }).join('');
    var th = S.brain && S.brain.thinking;
    if (!m.plan && th) h += '<div class="thinking"><span class="dots"><i></i><i></i><i></i></span><span id="pn-think">' + nb(F(C.thinking, { short: esc(short), s: ((Date.now() - th.since) / 1000).toFixed(1) })) + '</span></div>';
    return '<div class="log" id="pn-log">' + h + '</div>';
  }
  function onBench() { var b = S.corner && S.corner.bench; return !!(b && (b.held || b.down)); }
  function benchBlock(m) {
    var b = S.corner.bench, short = shortOf(m.name), eq = equipped(), bg = bag();
    var note = b.held ? F(C.bench.held, { short: esc(short) }) : b.respawn_in_ms != null ? F(C.bench.down, { s: '<span id="pn-down">' + Math.ceil(b.respawn_in_ms / 1000) + '</span>' }) : '';
    return '<div class="benchb"><div class="spread"><b class="bh">' + C.bench.h + '</b><span>' + F(C.bench.next, { n: b.next_life || (m.life || 1) + 1 }) + '</span></div>' +
      '<button type="button" class="switch' + (b.hold ? '' : ' off') + '" data-pn="hold" role="switch" aria-checked="' + !!b.hold + '"><i></i>' + C.bench.hold + '</button>' + (note ? '<p class="note">' + nb(note) + '</p>' : '') +
      '<div class="eyebrow">' + C.gearH + ' · ' + C.bench.tap + '</div><div class="gear">' + eq.map(function (g) { return '<button type="button" class="slot" data-pn="slot:' + g.slot + '"><span class="ico">' + ico(g.slot, 28) + '</span><span><span class="muted">' + esc(C.slots[g.slot]) + '</span><b>' + esc(g.name) + '</b></span></button>'; }).join('') + '</div>' +
      (bg.length ? '<div class="eyebrow" style="margin-top:10px">' + F(C.bag, { n: bg.length }) + '</div><div class="bag">' + bg.map(function (g) { return '<button type="button" class="slot" data-pn="equip:' + esc(g.slot) + ':' + esc(g.item_id) + '"><span class="ico">' + ico(g.slot, 24) + '</span><span><b>' + esc(g.name) + '</b><span class="muted">' + esc(C.slots[g.slot] || g.slot) + '</span></span></button>'; }).join('') + '</div>' : '') +
      (S.swapMsg ? '<p class="note" style="margin:8px 0 0">' + esc(S.swapMsg) + '</p>' : '') + '</div>';
  }
  function raiseOptions() { var c = cap(); return [0.3, 0.5, 1, 2, 5].filter(function (v) { return v > c + 1e-9; }).slice(0, 3); }
  function orderBox(m) {
    var O = C.order, short = shortOf(m.name);
    if (m.plan) return '<div class="order"><div class="readonly">' + esc(F(C.agent.box, { agent: m.agent })) + '</div></div>';
    // no AI door: no box that invites an order nothing can carry; where orders come from instead (chat.js's rule)
    if (!m.door) return '<div class="order"><div class="readonly">' + F(O.noDoor, { link: '<a class="link nodoor" href="' + esc(AI_STEP) + '">' + O.pickDoor + '</a>' }) + '</div></div>';
    if (capped()) {
      var rows = spendRows(), hourAgo = Date.now() - 3600000, oldest = rows.filter(function (x) { return x.at > hourAgo; }).map(function (x) { return x.at; }).sort()[0], opts = raiseOptions(), pick = S.raisePick != null ? S.raisePick : opts[0];
      return '<div class="order"><div class="blocked">' + esc(F(C.capped.box, { short: short, time: oldest ? hhmm(oldest + 3600000) : '' })) + '</div><div class="row"><div class="chipline grow">' + opts.map(function (v) { var on = v === pick; return '<button type="button" class="chip' + (on ? ' on' : '') + '" data-pn="raise:' + v + '" aria-pressed="' + on + '">' + usd(v) + '</button>'; }).join('') + '</div><button type="button" class="gold" data-pn="raisecap">' + C.capped.raise + '</button></div></div>';
    }
    return '<div class="order"><textarea id="pn-order" maxlength="300" placeholder="' + esc(F(O.placeholder, { short: short })) + '" aria-label="Order">' + esc(S.draft) + '</textarea><div class="spread"><span class="muted">' + nb(S.sending || (S.brain && S.brain.thinking) ? O.sent : O.hint) + (S.note ? ' ' + esc(S.note) : '') + '</span><button type="button" class="gold" data-pn="send"' + (S.sending ? ' disabled' : '') + '>' + O.send + '</button></div></div>';
  }
  function closedTab(m) {
    var short = shortOf(m.name), hp = m.plan ? S.codeLog && S.codeLog.hp : S.corner && S.corner.hp, max = m.plan ? S.codeLog && S.codeLog.max_hp : S.corner && S.corner.max_hp;
    var bar = hp != null && max ? '<span class="hp"' + (phone() ? ' style="display:block;width:120px"' : '') + '><i style="width:' + Math.round(100 * hp / max) + '%"></i></span>' : '';
    var line = lastLine(m), toast = line ? '<div class="toast" style="' + (phone() ? 'left:12px;right:12px;bottom:92px;max-width:none' : 'right:118px;top:150px') + '"><span class="who">' + esc(short) + '</span> “' + esc(line) + '”</div>' : '';
    if (phone()) return '<button type="button" class="plate pill" data-pn="open"><img src="' + avatar(m) + '" alt=""><span class="grow"><b>' + esc(short) + '</b>' + bar + '</span><span>' + C.tab.open + ' ▲</span></button>' + toast;
    return '<button type="button" class="edge-tab plate" data-pn="open"><img src="' + avatar(m) + '" alt=""><b>' + esc(short) + '</b>' + bar + '<span>' + C.tab.open + '</span></button>' + toast;
  }
  function lastLine(m) {
    if (m.plan) { var o = (S.codeLog && S.codeLog.log || []).filter(function (e) { return e.kind === 'order' && e.reply; }).pop(); return o ? o.reply : ''; }
    var conv = S.brain && S.brain.conversation || [], t = conv.filter(function (x) { return x && x.who === 'trenchie' && x.text; }).pop();
    return t ? t.text : '';
  }
  function html(m) {
    if (!S.open) return closedTab(m);
    var bench = !m.plan && onBench(), g = phone() ? 'left:0;right:0;top:290px;bottom:0' : 'right:12px;top:12px;bottom:12px;width:460px';
    var chat = S.tab === 'chat', gear = bench ? benchBlock(m) + (S.corner.bench.held ? '<div class="order"><button type="button" class="gold" data-pn="sendback">' + C.bench.send + '</button></div>' : '') : gearRow(m);
    var tabs = '<div class="pn-tabs" role="tablist" aria-label="Your Trenchie">' +
      '<button type="button" class="plate" id="pn-tab-chat" role="tab" aria-controls="pn-chat" aria-selected="' + chat + '" tabindex="' + (chat ? '0' : '-1') + '" data-pn="tab:chat">Chat</button>' +
      '<button type="button" class="plate" id="pn-tab-gear" role="tab" aria-controls="pn-gear" aria-selected="' + !chat + '" tabindex="' + (chat ? '-1' : '0') + '" data-pn="tab:gear"' + (bench ? ' aria-label="Gear: gear can be changed now"' : '') + '>Gear' + (bench ? ' <span class="gear-ready" aria-hidden="true">●</span>' : '') + '</button></div>';
    // data-arena-panel: the arena HUD keeps clear of this box while it is open (agreed with board 2's HUD); closed, it is not drawn
    return '<div class="sign pnl' + (bench ? ' onbench' : '') + '" data-arena-panel data-material="wood" style="' + g + '"><div class="face">' + head(m) + (S.leaveMsg ? '<div class="leave-msg" role="status">' + esc(S.leaveMsg) + '</div>' : '') + money(m) + tabs +
      '<div class="pn-pane chat-pane" id="pn-chat" role="tabpanel" aria-labelledby="pn-tab-chat"' + (chat ? '' : ' hidden') + '>' + logEntries(m) + orderBox(m) + '</div>' +
      '<div class="pn-pane gear-pane" id="pn-gear" role="tabpanel" aria-labelledby="pn-tab-gear" tabindex="0"' + (chat ? ' hidden' : '') + '>' + (gear || '<div class="readonly">Gear will appear here when the arena reports it.</div>') + '</div></div></div>';
  }

  // ------------------------------------------------------------------ draw, paint, keep focus and the log's place
  function render() {
    var m = mine(), el = S.el;
    if (!m) { if (el) { el.innerHTML = ''; el.hidden = true; } root.dispatchEvent(new root.CustomEvent('snappanel', { detail: { shown: false } })); return; }
    if (!el) { el = S.el = doc.createElement('div'); el.id = 'b1-panel'; doc.body.appendChild(el); }
    el.hidden = false; el.className = 'b1p ' + (phone() ? 'w390' : 'w1440') + ' final';
    var f = doc.activeElement, keep = f && f.id === 'pn-order' ? [f.selectionStart, f.selectionEnd] : null, log = el.querySelector('#pn-log');
    if (log && log.clientHeight) { S.logAtEnd = log.scrollTop + log.clientHeight >= log.scrollHeight - 8; S.logTop = log.scrollTop; }
    var gear = el.querySelector('#pn-gear'); if (gear && gear.clientHeight) S.gearTop = gear.scrollTop;
    el.innerHTML = html(m); S.lastShape = shape(); S.lastLog = logShape();
    var nl = el.querySelector('#pn-log'); if (nl) nl.scrollTop = S.logAtEnd !== false ? nl.scrollHeight : S.logTop || 0;
    var ng = el.querySelector('#pn-gear'); if (ng) ng.scrollTop = S.gearTop || 0;
    if (keep && S.tab === 'chat') { var t = el.querySelector('#pn-order'); if (t) { t.focus({ preventScroll: true }); try { t.setSelectionRange(keep[0], keep[1]); } catch (e) { /* none */ } } }
    root.requestAnimationFrame(function () { paint(el); });
    root.dispatchEvent(new root.CustomEvent('snappanel', { detail: { shown: true, open: S.open } }));
  }
  function paint(scope) {
    var SKA = root.SKA; if (!SKA || !SKA.plate) return;
    scope.querySelectorAll('[data-material],button').forEach(function (el) {
      if (/\b(chip|slot|link|switch)\b/.test(el.className)) return;
      var old = el.querySelector(':scope > svg.material'); if (old) old.remove();
      var r = el.getBoundingClientRect(), w = Math.round(r.width), hh = Math.round(r.height); if (!w || !hh) return;
      var art, gold = el.classList.contains('gold'), offd = el.disabled;
      if (el.dataset.material === 'wood') art = SKA.plank({ x: 0, y: 0, w: w, h: hh, text: '', cords: false, cordLen: 12, color: '#c9966a' }).svg;
      else { var fill = offd ? '#eee3c6' : gold ? '#f7cf6b' : el.classList.contains('leave') ? '#f9e5dc' : el.getAttribute('aria-selected') === 'true' ? '#9fdcc5' : '#fff8ea'; art = SKA.plate({ x: 0, y: 0, w: w, h: hh, r: 8, fill: fill, rim: offd ? '#c9bb9c' : '#a08252', screws: false, cast: 'sk-cast-sm' }) + '<rect x="5" y="5" width="' + Math.max(0, w - 10) + '" height="' + Math.max(0, hh - 10) + '" rx="4" fill="' + fill + '"/>'; }
      el.insertAdjacentHTML('afterbegin', SKA.svg(w, hh, art, ' class="material" aria-hidden="true"'));
    });
  }

  // ------------------------------------------------------------------ the sources, read once a second
  async function poll() {
    // a bench answer outranks a reading that left before it (Send back in, then a reading still saying "held", redrew the hold)
    var P = draft(), door = P.door || {}, t0 = Date.now(), keep = function (j) { if (j && S.benchAt && t0 <= S.benchAt && S.corner && S.corner.bench) j.bench = S.corner.bench; return j; };
    try {
      if (door.route === 'plan' && P.planCode) {
        var r = await root.fetch('/snap/code/' + encodeURIComponent(P.planCode) + '/log', { cache: 'no-store' });
        S.codeLog = r.ok ? await r.json() : null;
        // the gear the session's trenchie wears, from the same public corner as a key door's
        if (S.codeLog && S.codeLog.fighter_id) { var g2 = await root.fetch('/dev/corner?fighter=' + encodeURIComponent(S.codeLog.fighter_id), { cache: 'no-store' }); var j2 = g2.ok ? await g2.json() : null; S.corner = j2 && !j2.error ? j2 : null; }
      } else {
        var st = root.SnapRoom && root.SnapRoom.status(), id = st && st.fighter && st.fighter.id;
        if (id) { var c = await root.fetch('/dev/corner?fighter=' + encodeURIComponent(id), { cache: 'no-store' }); var j = c.ok ? await c.json() : null; S.corner = j && !j.error ? keep(j) : null; }
      }
    } catch (e) { /* the arena away: the parts with no fresh data keep their last reading */ }
    // redraw only when what the panel shows has changed (a redraw every second replaced the very link being clicked);
    // the running counters change in place
    var sh = shape(); if (sh !== S.lastShape) { S.lastShape = sh; render(); } else { if (logShape() !== S.lastLog) relog(); tickLive(); }
  }
  function tickLive() {
    var th = doc.getElementById('pn-think'), m = mine();
    if (th && S.brain && S.brain.thinking && m) th.textContent = F(C.thinking, { short: shortOf(m.name), s: ((Date.now() - S.brain.thinking.since) / 1000).toFixed(1) });
    var src = m && m.plan ? S.codeLog : S.corner, bar = doc.getElementById('pn-hpbar'), hpn = doc.getElementById('pn-hpn');
    if (src && src.hp != null && src.max_hp && bar && hpn) { var pct = Math.max(0, Math.min(100, Math.round(100 * src.hp / src.max_hp))); bar.firstChild.style.width = pct + '%'; bar.setAttribute('aria-label', 'HP ' + src.hp + ' of ' + src.max_hp); hpn.textContent = src.hp + '/' + src.max_hp; }
    var dn = doc.getElementById('pn-down'), b = S.corner && S.corner.bench;
    if (dn && b && b.respawn_in_ms != null) dn.textContent = Math.ceil(b.respawn_in_ms / 1000);
  }
  // the log alone: in a busy fight the arena's events come every second, and only the log is redrawn for them (a whole
  // redraw replaced the Send button under the player's click)
  function logShape() { return JSON.stringify([S.corner && S.corner.events, S.codeLog && S.codeLog.log]); }
  function relog() {
    var m = mine(), log = S.el && S.el.querySelector('#pn-log'); S.lastLog = logShape();
    if (!m || !log) return render();
    var atEnd = log.scrollTop + log.clientHeight >= log.scrollHeight - 8, top = log.scrollTop, tmp = doc.createElement('div');
    tmp.innerHTML = logEntries(m); var fresh = tmp.firstChild; log.replaceWith(fresh); fresh.scrollTop = atEnd ? fresh.scrollHeight : top;
  }
  // everything the panel draws, except the log and the counters tickLive keeps current
  function shape() {
    var c = S.corner ? Object.assign({}, S.corner, { events: null, hp: S.corner.hp == null ? null : 1, bench: S.corner.bench ? Object.assign({}, S.corner.bench, { respawn_in_ms: S.corner.bench.respawn_in_ms == null ? null : 1, remaining_ms: null }) : null, respawn_at_ms: null }) : null;
    var b = S.brain || {};
    var L = S.codeLog ? Object.assign({}, S.codeLog, { log: null, hp: S.codeLog.hp == null ? null : 1 }) : null;
    return JSON.stringify([c, L, b.state, !!b.thinking, b.spendHourUsd, b.capUsd, cap(), capped(), (b.conversation || []).length, b.lastOrderTiming, S.turns, S.open, S.tab, S.capEdit, S.capPick, S.raisePick, S.sending, S.note, S.swapMsg, S.leaving, S.leaveMsg, phone()]);
  }

  // ------------------------------------------------------------------ actions
  async function send() {
    var B = root.SnapBrain, t = (S.draft || '').trim(); if (!t || S.sending || !B || typeof B.tell !== 'function') return;
    var m = mine(); if (!m) return;
    var turn = { at: Date.now(), text: t, reply: '', receipt: null, appliedMs: null, chip: '' };
    S.turns.push(turn); S.draft = ''; S.sending = true; S.note = ''; render();
    var r; try { r = await B.tell(t); } catch (e) { r = { chip: e.message }; }
    var tim = S.brain && S.brain.lastOrderTiming;   // brain.js: receipt_ms (Send to receipt) + applies_in_ms (the arena's own delay)
    turn.reply = r && r.reply || ''; turn.receipt = r && r.receipt || null; turn.chip = r && !r.reply && !r.receipt && r.chip ? r.chip : '';
    turn.appliedMs = tim && tim.order === t && tim.receipt_ms != null ? tim.receipt_ms + (tim.applies_in_ms || 0) : turn.receipt ? Date.now() - turn.at + (turn.receipt.applies_in_ms || 0) : null;
    S.sending = false; ss.set(TURNS + m.id, S.turns.slice(-40)); render();
  }
  async function bench(payload) {
    if (!root.SnapRoom || !root.SnapRoom.bench) return;
    try { var env = await root.SnapRoom.bench(payload), ack = env && env.ack; S.swapMsg = ack && ack.summary || ''; if (ack && ack.bench && S.corner) { S.corner.bench = ack.bench; S.benchAt = Date.now(); } } catch (e) { S.swapMsg = e.message; }
    render();
  }
  function setCap(v) { if (v > 0) ls.set(CAP_STORE, String(v)); }
  async function leave() {
    var R = root.SnapRoom, rs = R && R.status(), m = mine();
    if (!m || !R || !R.leave || !rs || !rs.fighter || rs.fighter.id !== m.id || S.leaving || /^(joining|leaving)$/.test(rs.phase)) return;
    S.leaving = true; S.leaveMsg = F(C.leaving, { name: m.name }); render();
    try {
      await R.leave();
      var P = draft(); P.left = Date.now(); ls.set(SAVE, JSON.stringify(P));
      S.codeLog = null;
      var guide = new URL(AI_STEP, root.location.href); guide.searchParams.set('step', 'ring');
      root.location.href = guide.pathname + guide.search;
    } catch (e) { S.leaveMsg = F(C.leaveFailed, { why: e && e.message || 'the arena did not answer' }); }
    S.leaving = false; render();
  }
  function selectTab(tab) {
    S.tab = tab; render();
    var button = S.el.querySelector('#pn-tab-' + tab); if (button) button.focus({ preventScroll: true });
  }
  doc.addEventListener('click', function (e) {
    var b = e.target.closest('[data-pn]'); if (!b || !S.el || !S.el.contains(b) || b.disabled) return;
    if (b.tagName === 'A') e.preventDefault();
    var a = b.dataset.pn;
    if (a === 'close') { S.open = false; ls.set(OPEN_STORE, '0'); render(); }
    else if (a === 'open') { S.open = true; S.tab = 'chat'; ls.set(OPEN_STORE, '1'); render(); }
    else if (a === 'tab:chat' || a === 'tab:gear') selectTab(a.slice(4));
    else if (a === 'leave') leave();
    else if (a === 'capedit') { S.capEdit = true; S.capPick = null; render(); }
    else if (a.indexOf('cap:') === 0) { S.capPick = Number(a.slice(4)); render(); }
    else if (a === 'setcap') { if (S.capPick != null) setCap(S.capPick); S.capEdit = false; render(); }
    else if (a.indexOf('raise:') === 0) { S.raisePick = Number(a.slice(6)); render(); }
    else if (a === 'raisecap') { var o = raiseOptions(); setCap(S.raisePick != null ? S.raisePick : o[0]); S.raisePick = null; render(); }
    else if (a === 'send') send();
    else if (a === 'hold') bench({ hold: !(S.corner && S.corner.bench && S.corner.bench.hold) });
    else if (a === 'sendback') bench({ hold: false });
    else if (a.indexOf('equip:') === 0) { var p = a.split(':'); bench({ equip: { slot: p[1], item_id: p.slice(2).join(':') } }); }
  });
  doc.addEventListener('input', function (e) { if (e.target && e.target.id === 'pn-order') S.draft = e.target.value; });
  doc.addEventListener('keydown', function (e) {
    if (e.target && e.target.id === 'pn-order' && e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
    else if (e.target && /^(pn-tab-chat|pn-tab-gear)$/.test(e.target.id) && /^(ArrowLeft|ArrowRight|Home|End)$/.test(e.key)) {
      e.preventDefault(); selectTab(e.key === 'Home' ? 'chat' : e.key === 'End' ? 'gear' : S.tab === 'chat' ? 'gear' : 'chat');
    }
  });
  root.addEventListener('resize', function () { render(); });

  function start() {
    if (S.timer) return;
    // brain.js arrives after this script on the arena page: hook it once it is there
    var hookBrain = root.setInterval(function () { if (root.SnapBrain && root.SnapBrain.on && !S.brainHooked) { S.brainHooked = true; root.SnapBrain.on(function (b) { S.brain = b; }); root.clearInterval(hookBrain); } }, 500);
    if (root.SnapRoom && root.SnapRoom.on) root.SnapRoom.on(function () { var m = mine(); if (m && !S.turnsFor) { S.turnsFor = m.id; S.turns = ss.get(TURNS + m.id) || []; } render(); });
    S.timer = root.setInterval(poll, 1000); poll();
  }
  root.SnapPanel = { start: start, render: render, state: S, mine: mine };
})(typeof globalThis !== 'undefined' ? globalThis : this);
