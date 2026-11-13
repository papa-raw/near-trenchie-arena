/* snapin/guide.js: the snap-in guide as drawn on board 1: one step a screen on a wood sign, the step names as links, a
 * key or plan screen for the AI, and a check page before Snap in. Every word comes from guide-copy.js.
 *   wallet -> fighter -> personality -> AI (doors, then one door's key or plan screen) -> check -> Snap in
 * One gold button a screen, bottom right; a greyed gold button always says beside it exactly what is missing. Back is a
 * link bottom left and never resets a choice.
 * app.js owns the state (the draft P, the view V, go, save, join) and calls SnapGuide.view(host) / act(a, host).
 * No silent fallback: a door that cannot work from the browser is not offered, and a failed call says what failed. */
(function (root) {
  'use strict';
  var C = root.SnapGuideCopy, F = C.fill;
  var KEY_STORE = 'trenchie.snapin.key.', CAP_STORE = 'trenchie.snapin.cap', LAST_STORE = 'trenchie.snapin.lastdoor';
  var QUIRK_ORDER = ['sea-puns', 'caps', 'lowercase', 'hums', 'polite', 'counts-kos', 'weather', 'pauses'];
  var MOVE = { swing: 'Swing', lunge: 'Lunge', beam: 'Beam', lob: 'Lob', zap: 'Zap' };
  var SIG = { shockwave: 'Shockwave', blink_strike: 'Blink Strike', bubble: 'Bubble', magnet: 'Magnet', chain_storm: 'Chain Storm' };
  // the four signatures the board does not draw, said the same way, from what the arena does (arena/sim.py)
  var SIG_LINE = { 'Blink Strike': 'Blink Strike: you vanish and reappear behind a foe with a hit.', 'Bubble': 'Bubble: a shield closes around you and soaks up hits.',
                   'Magnet': 'Magnet: a shield, and floor items pull toward you.', 'Chain Storm': 'Chain Storm: a strike that jumps from foe to foe.' };
  var g = { keyText: '', keyStatus: '', keyMsg: '', answer: '', code: null, codeErr: '', expired: false, poll: null, tick: null, copied: false, requesting: false,
            name: { checked: '', free: null, picked: '' }, joining: false };
  var keyTest = 0;   // replies belong to one test of one selected door and key
  var esc = function (s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); };
  var nb = function (s) { return String(s).replace(/(\d) (s|tiles|of 10)\b/g, '$1&nbsp;$2'); };
  function b(act, label, cls, attr) { return '<button type="button" class="' + (cls || 'plate') + '"' + (act ? ' data-act="' + act + '"' : '') + (attr ? ' ' + attr : '') + '>' + label + '</button>'; }
  function lnk(act, label, attr) { return '<a href="#" class="link"' + (act ? ' data-act="' + act + '"' : '') + (attr ? ' ' + attr : '') + '>' + label + '</a>'; }
  function store() { return root.SnapUI.store; }
  function phone() { return (root.innerWidth || 1440) <= 600; }

  // ------------------------------------------------------------------ where the player is
  function stepIx(h) { var s = h.V.step; return s === 'wallet' ? 0 : /^(presets|presets-empty|claimed|build)$/.test(s) ? 1 : s === 'personality' ? 2 : s === 'doors' ? 3 : 4; }
  function pick(h) { return h.P.pick || null; }   // the door on screen in step 4: {route: 'key'|'plan', door}
  function cap() { var c = Number(store().get(CAP_STORE)); return c > 0 ? c : 0; }
  function keyOf(door) { return store().get(KEY_STORE + door) || ''; }
  function keyDoorOk(h, door) { var d = h.P.door; return !!(d && d.route === 'key' && d.door === door && keyOf(door)); }
  function aiReady(h) {
    var d = h.P.door, p = pick(h); if (!d || !d.door) return false;
    if (p && (p.route !== d.route || p.door !== (d.route === 'plan' ? d.identity : d.door))) return false;
    return d.route === 'plan' ? true : !!keyOf(d.door) && cap() > 0;
  }
  function nameOk(h) { var n = (h.P.name || '').trim(), SS = root.SnapSheet; return !!n && (!SS || SS.guard(n).ok) && g.name.free !== false; }
  function done(h, i) {
    var P = h.P;
    if (i === 0) return !!P.wallet;
    if (i === 1) return !!P.fighterChosen;
    if (i === 2) return !!P.fighterChosen && !!(P.name || '').trim();
    if (i === 3) return aiReady(h);
    return false;
  }
  // a door the browser can drive: the brain's providers (NEAR AI Cloud, Claude Console, OpenRouter); Codex's key door
  // waits for its OpenAI provider and its browser (CORS) check, so it is not offered until providers.js has one
  function keyDoorOffered(door) { var P = root.SnapProviders; if (door === 'Codex') return !!(P && P.codex && P.codex.corsChecked); return true; }

  // ------------------------------------------------------------------ pieces
  function stepsNav(h) {
    var cur = stepIx(h), tgt = ['wallet', 'presets', 'personality', 'doors', 'agree'], onCheck = cur === 4;
    return '<nav class="steps" aria-label="Steps">' + C.steps.map(function (n, i) {
      var d = done(h, i) && i !== cur, need = onCheck && i < 4 && !done(h, i);   // the step on screen is underlined, not ticked
      return '<a href="#" data-act="g:step:' + tgt[i] + '" class="' + (i === cur ? 'on ' : '') + (need ? 'need' : d ? 'done' : 'todo') + '"' + (i === cur ? ' aria-current="step"' : '') + '>' + n + '</a>';
    }).join('') + '</nav>';
  }
  function returning(h) {   // a returning player's own trenchie (items 33 and 25): the way back and the way to a new one
    var r = h.returning ? h.returning() : '';
    return r ? '<div class="note" role="status" style="margin:0 0 12px">' + r + '</div>' : '';
  }
  function walletBody(h) {
    var w = C.wallet, P = h.P, ch = h.chain ? h.chain() : { on: false, network: 'testnet', signed: '' }, net = ch.known ? String(ch.network || 'testnet').toUpperCase() : ch.retrying ? 'Retrying…' : 'Loading…';
    return returning(h) + '<p class="lead">' + w.line + '</p>' + (P.wallet ? '<p class="chipok">' + esc(F(w.connected, { wallet: h.shortAcct(P.wallet.accountId) })) + ' · ' + lnk('g:wallet-forget', w.other) + '</p>' + (ch.signed ? '<p class="note" style="margin:0 0 10px">' + esc(ch.signed) + '</p>' : '') : '') + '<div class="list">' +
      w.rows.filter(function (r) { return r[0] !== 'dev-throwaway' || (ch.known === true && !ch.on); }).map(function (r) { return '<button type="button" class="li' + (P.wallet && P.wallet.id === r[0] ? ' sel' : '') + '" data-act="g:wallet:' + r[0] + '"' + (ch.known ? '' : ' disabled') + '><span>' + r[1] + '</span><span class="r">' + F(r[2], { network: net }) + '</span></button>'; }).join('') +
      '</div><p class="small" style="margin:12px 0 0">' + w.none + ' <a href="' + w.getUrl + '" target="_blank" rel="noopener noreferrer">' + w.get + '</a></p>';
  }
  function kitOf(h) { var SS = root.SnapSheet, pr = SS && SS.PRESETS.filter(function (x) { return x.name === h.P.preset; })[0]; return pr ? { move: MOVE[pr.weapon] || pr.weapon, sig: SIG[pr.signature] || pr.signature } : null; }
  function fighterBody(h) {
    if (h.loadPremint) h.loadPremint();   // the premint personas, ready by the time Use this preset is pressed
    var f = C.fighter, k = kitOf(h), names = (root.SnapSheet ? root.SnapSheet.PRESETS : []).map(function (x) { return x.name; });
    var tip = k && (f.sigs[k.sig] || SIG_LINE[k.sig]);
    var ch = h.chain ? h.chain() : null;   // chain mode: whether a fighter is a free claim or a paid mint, said plainly
    return returning(h) + '<p class="lead">' + (ch && ch.on && ch.fighter ? esc(ch.fighter) : f.line) + '</p><div class="presets">' + names.map(function (p, i) { return '<button type="button" class="preset" data-act="g:preset:' + esc(p) + '" aria-pressed="' + (h.P.preset === p) + '"><img src="img/avatar-' + i + '.png" alt="">' + p + '</button>'; }).join('') + '</div>' +
      (k ? '<div class="kit"><div class="eyebrow">' + f.kit + '</div><div class="kv"><b>' + f.move + '</b><span>' + k.move + '<span class="info" tabindex="0" title="' + esc(f.moves[k.move] || '') + '" aria-label="' + esc(f.moves[k.move] || '') + '">i</span></span></div>' +
        '<div class="kv"><b>' + f.sig + '</b><span>' + k.sig + '<span class="info on" tabindex="0" aria-label="' + esc(tip || '') + '">i</span></span></div>' + (tip ? '<div class="tip">' + tip + '</div>' : '') + '</div>' : '');
  }
  function personaBody(h) {
    var p = C.persona, P = h.P, SS = root.SnapSheet, gd = SS && P.name ? SS.guard(P.name) : { ok: true };
    var st = !P.name ? '' : !gd.ok ? '<span class="bad small" style="white-space:nowrap">✗</span>' : g.name.free === false ? '<span class="bad small" style="white-space:nowrap">✗</span>' : g.name.free === true && g.name.checked === P.name ? '<span class="ok small" style="white-space:nowrap">' + p.free + '</span>' : '';
    var line = !gd.ok ? '<p class="note bad" role="alert" style="margin:6px 0 16px">' + esc(gd.reason) + '</p>' : g.name.free === false ? '<p class="note bad" role="alert" style="margin:6px 0 16px">' + esc(F(p.inRing, { name: P.name })) + '</p>' :
      g.name.picked ? '<p class="note" style="margin:6px 0 16px">' + esc(F(p.taken, { taken: g.name.picked })) + '</p>' : '<p class="note" style="margin:6px 0 16px"></p>';
    // the board's eight quirks, plus any other the draft already carries (a premint persona's), so it can be taken off
    var ids = QUIRK_ORDER.concat((P.quirks || []).filter(function (id) { return QUIRK_ORDER.indexOf(id) < 0; }));
    var temps = SS ? SS.TEMPERAMENTS : [], quirks = SS ? ids.map(function (id) { return SS.QUIRKS.filter(function (q) { return q.id === id; })[0]; }).filter(Boolean) : [];
    var t = temps.filter(function (x) { return x.id === P.temper; })[0] || temps[0], short = String(P.name || '').trim().split(/\s+/)[0] || '';
    var body = returning(h) + '<label class="f" for="name">' + p.name + '</label><div class="row"><input id="name" value="' + esc(P.name) + '" maxlength="32" autocomplete="off" aria-label="Name">' + st + '</div>' + line +
      '<label class="f">' + p.temper + '</label><div class="chipline">' + temps.map(function (x) { return '<button type="button" class="chip' + (x.id === P.temper ? ' on' : '') + '" data-act="g:temper:' + x.id + '" aria-pressed="' + (x.id === P.temper) + '">' + x.name + '</button>'; }).join('') + '</div>' +
      '<label class="f" style="margin-top:16px">' + p.quirks + ' <span class="muted" style="font-weight:400">· ' + p.quirksMax + '</span></label><div class="chipline">' + quirks.map(function (q) { var on = (P.quirks || []).indexOf(q.id) >= 0; return '<button type="button" class="chip' + (on ? ' on' : '') + '" data-act="g:quirk:' + q.id + '" aria-pressed="' + on + '">' + q.label + '</button>'; }).join('') + '</div>' +
      (t && short ? '<p class="small" style="margin:16px 0 0"><span class="who">' + esc(short) + '</span> “' + esc(t.sample[0]) + '”</p>' : '');
    return h.fixedPersona && h.fixedPersona() ? '<p class="note" role="status">' + esc(p.fixed) + '</p><fieldset disabled style="border:0;padding:0;margin:0;min-width:0">' + body + '</fieldset>' : body;
  }
  function doorLabel(name) {
    return '<span class="door-label">' + root.SnapMarks.mark(name === 'Claude Code' ? 'Claude' : name) + '<span>' + esc(name) + '</span></span>';
  }
  function doorsBody(h) {
    var d = C.doors;
    return returning(h) + '<p class="lead">' + d.line + '</p><div class="group-h">' + d.keyGroup + '</div>' +
      d.key.filter(function (r) { return keyDoorOffered(r[0]); }).map(function (r) { return '<button type="button" class="door2" data-act="g:door:key:' + r[0] + '">' + doorLabel(r[0]) + '<span class="r">' + r[1] + '</span></button>'; }).join('') +
      '<div class="group-h">' + d.planGroup + '</div>' +
      d.plan.map(function (r) { return '<button type="button" class="door2" data-act="g:door:plan:' + r[0] + '">' + doorLabel(r[0]) + '<span class="r">' + r[1] + '</span></button>'; }).join('');
  }
  function keyStatus(h, door) {
    var k = C.key;
    if (g.keyStatus === 'testing') return '<p class="small st" role="status">' + k.testing + '</p>';
    if (g.keyStatus === 'wrong') return '<p class="bad small st" role="alert">' + k.wrong + '</p>';
    if (g.keyStatus === 'nocredit') return '<p class="bad small st" role="alert">' + k.noCredits + '</p>';
    if (g.keyStatus === 'error') return '<p class="bad small st" role="alert">✗ ' + esc(g.keyMsg) + '</p>';
    if (g.keyStatus === 'ok' || keyDoorOk(h, door)) return '<p class="ok small st" role="status">' + esc(F(k.ok, { answer: g.answer || (h.P.door && h.P.door.hi) || '' })) + '</p>';
    return '<p class="small st"></p>';
  }
  function tested(h, door) { return g.keyStatus === 'ok' || (g.keyStatus === '' && keyDoorOk(h, door)); }
  function mask(k) { return k ? k.slice(0, 3) + '••••••••••••' + k.slice(-4) : ''; }
  function keyBody(h, door) {
    var k = C.key, pv = k.providers[door], c = cap(), saved = keyDoorOk(h, door) && !g.keyText;
    var how = '<ol class="how plain">' + pv.how.map(function (x, i) { return '<li' + (i === 3 ? ' class="now"' : '') + '><span>' + x + '</span>' + (i === 0 ? '<a href="' + pv.url + '" target="_blank" rel="noopener noreferrer">' + pv.open + '</a>' : '<span></span>') + '</li>'; }).join('') + '</ol>';
    var other = c && k.caps.indexOf('$' + c.toFixed(2)) < 0 ? c.toFixed(2) : '';
    var paste = '<label class="f" for="key">' + k.field + '</label><div class="row"><input id="key" autocomplete="off" spellcheck="false" ' + (saved ? 'type="text" value="' + esc(mask(keyOf(door))) + '" data-saved="1"' : 'type="password" value="' + esc(g.keyText) + '" placeholder="' + k.placeholder + '"') + ' aria-label="' + k.field + '">' + b('g:test', k.test, 'plate', g.keyStatus === 'testing' ? 'disabled' : '') + '</div>' + keyStatus(h, door) +
      '<div class="hr"></div><label class="f">' + k.cap + '</label><div class="chipline">' + k.caps.map(function (x) { var on = c && x === '$' + c.toFixed(2); return '<button type="button" class="chip' + (on ? ' on' : '') + '" data-act="g:cap:' + x.slice(1) + '" aria-pressed="' + !!on + '">' + x + '</button>'; }).join('') +
      '<input id="cap-other" style="width:104px" inputmode="decimal" placeholder="' + k.capOther + '" aria-label="Other cap" value="' + esc(other) + '"></div>' +
      '<p class="note" style="margin:8px 0 0">' + pv.cost + ' ' + k.capRule + '</p><p class="fine" style="margin:12px 0 0">' + k.keyNote + '</p>';
    if (phone()) return returning(h) + '<div class="eyebrow" style="margin-bottom:8px">' + k.getH + '</div>' + how + '<div style="margin-top:16px">' + paste + '</div>';
    return returning(h) + '<div class="two"><div><div class="eyebrow" style="margin-bottom:10px">' + k.getH + '</div>' + how + '</div><div style="padding-top:26px">' + paste + '</div></div>';
  }
  function left() { if (!g.code) return ''; var s = Math.max(0, Math.ceil((g.code.expiresAt - Date.now()) / 1000)); return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2); }
  function planJoined(h, agent) { var d = h.P.door; return !!(d && d.route === 'plan' && d.identity === agent && g.code === null) || g.joinedFor === agent; }
  function command(agent, h) {
    var a = C.plan[agent], nm = String(h.P.name || '').replace(/["$`\\\n\r]/g, ' ').trim().slice(0, 40);
    return g.code ? F(C.plan.command, { bin: a.bin, snap: g.code.snapUrl, download: a.download || '', code: g.code.code, name: nm }) : '';
  }
  function planBody(h, agent) {
    var p = C.plan, a = p[agent], joined = planJoined(h, agent), stop = h.P.planStop || '10%';
    var status = joined ? '<p class="ok small st" role="status">' + esc(F(p.joined, { agent: agent })) + '</p>' :
      g.codeErr ? '<p class="bad small st" role="alert">✗ ' + esc(g.codeErr) + ' ' + lnk('g:newcode', p.newCode) + '</p>' :
      g.expired ? '<p class="bad small st" role="alert">' + p.expired + ' ' + lnk('g:newcode', p.newCode) + '</p>' :
      g.code ? '<p class="small st" role="status"><span class="dots"><i></i><i></i><i></i></span> ' + esc(F(p.waiting, { left: '' })) + '<span id="code-left">' + left() + '</span></p>' :
      '<p class="small st" role="status">' + p.asking + '</p>';
    return returning(h) + (agent === 'Codex' ? '' : '<p class="lead">' + esc(F(p.line, { agent: agent, plan: a.planName })) + '</p>') +
      '<ol class="how plain"><li class="now"><span>' + p.copyH + '</span>' + b('g:copy', g.copied ? p.copied : p.copy, 'plate', g.code ? '' : 'disabled') + '</li></ol>' +
      '<pre class="cmd" aria-label="Command">' + esc(command(agent, h)) + '</pre>' +
      (a.networkNote ? '<p class="small">' + esc(a.networkNote) + '</p>' : '') +
      '<ol class="how plain" style="counter-reset:n 1"><li><span>' + p.paste + '</span><span></span></li><li><span>' + p.keepOpen + '</span><span></span></li></ol>' + status +
      '<div class="hr"></div><div class="eyebrow" style="margin-bottom:6px">' + p.runsH + '</div><p class="small" style="margin:0">' + esc(F(p.runs, { perms: a.perms })) + '</p>' +
      '<div class="hr"></div><label class="f">' + p.limitH + '</label><div class="chipline">' + p.limits.map(function (x) { return '<button type="button" class="chip' + (x === stop ? ' on' : '') + '" data-act="g:stop:' + x + '" aria-pressed="' + (x === stop) + '">' + x + '</button>'; }).join('') + '</div>' +
      '<p class="note" style="margin:8px 0 0">' + p.limitRule + ' ' + p.limitUnknown + '</p>';
  }
  function checkBody(h) {
    var c = C.check, P = h.P, d = P.door, plan = d && d.route === 'plan', t = h.V.terms, temps = root.SnapSheet ? root.SnapSheet.TEMPERAMENTS : [];
    var tn = (temps.filter(function (x) { return x.id === P.temper; })[0] || {}).name || '', qs = (P.quirks || []).map(function (id) { var q = root.SnapSheet && root.SnapSheet.QUIRKS.filter(function (x) { return x.id === id; })[0]; return q ? q.label : id; });
    var row = function (label, value, act, missing, setIt) { return '<div class="li ck"><b>' + label + '</b><span>' + (missing ? '<span class="bad">' + c.notSet + '</span>' : esc(value)) + '</span>' + lnk(act, missing && setIt ? c.setIt : c.change) + '</div>'; };
    var rows = row(c.rows.wallet, P.wallet ? h.shortAcct(P.wallet.accountId) : '', 'g:step:wallet', !P.wallet) + row(c.rows.fighter, P.fighterChosen ? P.preset : '', 'g:step:presets', !P.fighterChosen) +
      row(c.rows.name, P.name, 'g:step:personality', !(P.name || '').trim()) + row(c.rows.personality, [tn].concat(qs).filter(Boolean).join(' · '), 'g:step:personality', !tn) +
      row(c.rows.ai, d && d.door ? (plan ? d.identity : d.door) + ' · ' + (plan ? c.joined : c.answered) : '', 'g:ai', !(d && d.door)) +
      (plan ? row(c.rows.stop, P.planStop || '10%', 'g:ai', false) : row(c.rows.cap, cap() ? '$' + cap().toFixed(2) : '', 'g:ai', !cap(), true));
    var rules = t && t.version ? [[c.orders, F(c.ordersV, { s: secs(t.input_interval_ms) })], [c.rounds, F(c.roundsV, { s: secs(t.segment_ms) })], [c.gear, c.gearV]] : [[c.gear, c.gearV]];
    return returning(h) + '<div class="list">' + rows + '</div><div style="margin-top:18px"><div class="eyebrow" style="margin-bottom:6px">' + c.rulesH + '</div><div class="rules">' +
      rules.map(function (r) { return '<div class="kv"><b>' + r[0] + '</b><span>' + nb(esc(r[1])) + '</span></div>'; }).join('') + '</div>' +
      (t && t.error ? '<p class="bad small" role="alert">' + esc(t.error) + ' ' + lnk('g:terms', 'Try again') + '</p>' : '') + '<p class="fine" style="margin:8px 0 0">' + c.notice + '</p></div>';
  }
  function secs(ms) { var s = Number(ms) / 1000; return String(Math.round(s * 10) / 10); }
  // what the check page's Snap in still needs, first missing first (one reason, beside the button)
  function checkNeeds(h) {
    var c = C.check, P = h.P, d = P.door;
    if (!P.wallet) return c.needsWallet;
    if (!P.fighterChosen || !(P.name || '').trim() || !nameOk(h)) return c.needsName;
    if (!d || !d.door) return c.needsAI;
    if (d.route !== 'plan' && !cap()) return c.needsCap;
    if (d.route !== 'plan' && !keyOf(d.door)) return c.needsAI;
    if (!h.V.terms || !h.V.terms.version) return c.needsRules;
    return '';
  }

  // ------------------------------------------------------------------ the sign
  function view(h) {
    var V = h.V, s = V.step, k = C.key, title, body, back = '', right = '', pk = pick(h), wide = false;
    var gold = function (act, label) { return b(act, label, 'gold main'); };
    var off = function (label, why) { return '<span class="needs" id="needs">' + why + '</span><button type="button" class="gold main" disabled aria-describedby="needs">' + label + '</button>'; };
    if (s === 'wallet') { title = C.wallet.title; body = walletBody(h); right = h.P.wallet ? gold('g:step:presets', C.wallet.next) : off(C.wallet.next, C.wallet.needs); }
    else if (stepIx(h) === 1) { title = C.fighter.title; body = fighterBody(h); back = 'wallet'; right = gold('g:use', C.fighter.use) + b('g:build', C.fighter.build, 'plate pairbtn'); }
    else if (s === 'personality') { title = C.persona.title; body = personaBody(h); back = 'presets'; right = nameOk(h) ? gold('g:step:doors', C.persona.next) : off(C.persona.next, C.check.needsName); }
    else if (s === 'doors' && (!pk || (pk.route === 'key' && !k.providers[pk.door]) || (pk.route === 'plan' && !C.plan[pk.door]))) { title = C.doors.title; body = doorsBody(h); back = 'personality'; }
    else if (s === 'doors' && pk.route === 'key') {
      title = k.providers[pk.door].title; body = keyBody(h, pk.door); back = 'doors'; wide = true;
      var tst = tested(h, pk.door), bad = g.keyStatus === 'wrong' || g.keyStatus === 'nocredit' || g.keyStatus === 'error';
      right = tst && cap() ? gold('g:step:agree', k.next) : off(k.next, bad ? k.needsTest : !tst && !cap() ? k.needsBoth : !tst ? k.needsTest : k.needsCap);
    } else if (s === 'doors') {
      title = C.plan[pk.door].title; body = planBody(h, pk.door); back = 'doors';
      right = planJoined(h, pk.door) ? gold('g:step:agree', C.plan.next) : off(C.plan.next, g.expired || g.codeErr ? C.plan.newCode : C.plan.needsJoin);
    } else {
      title = C.check.title; body = checkBody(h); back = 'doors';
      var why = checkNeeds(h);
      right = g.joining ? off(C.check.snap, C.check.joining) : why ? off(C.check.snap, why) : gold('g:snap', C.check.snap);
    }
    var geo = phone() ? 'left:6px;right:6px;top:52px;bottom:6px' : 'left:50%;top:50%;transform:translate(-50%,-50%);max-height:min(850px,calc(100vh - 24px));width:' + (wide ? 920 : 740) + 'px';
    var backLink = back ? lnk(back === 'doors' && s === 'doors' ? 'g:other' : 'g:step:' + back, C.back) : '<a href="#" class="link kw" data-act="g:watch">' + C.keepWatching + '</a>';
    return '<div class="stage dim"></div><div class="sign" data-material="wood" style="' + geo + '"><div class="face"><div class="face-head"><div><div class="eyebrow">' + F(C.eyebrow, { n: stepIx(h) + 1 }) + '</div><h1>' + title + '</h1></div><div class="row">' +
      (s === 'doors' && pk ? lnk('g:other', k.other) : '') + b('g:close', '×', 'close plate', 'aria-label="' + C.close + '"') + '</div></div>' + stepsNav(h) +
      '<div class="face-body"><p id="feedback" class="small ' + (V.msgErr ? 'bad' : 'ok') + '" role="status" aria-live="polite" style="margin:0 0 ' + (V.msg ? '10px' : '0') + '">' + esc(V.msg || '') + '</p>' + body + '</div><div class="bar">' + backLink + '<div class="right">' + right + '</div></div></div></div>';
  }
  // the board's materials: the wood sign and the plates (gold for the one forward action, greyed when off)
  function paint(scope) {
    var SKA = root.SKA; if (!SKA) return;
    (scope || root.document).querySelectorAll('[data-material],button').forEach(function (el) {
      if (/\b(li|door2|chip|slot|link|preset)\b/.test(el.className)) return;
      var old = el.querySelector(':scope > svg.material'); if (old) old.remove();
      var r = el.getBoundingClientRect(), w = Math.round(r.width), hh = Math.round(r.height); if (!w || !hh) return;
      var art, pressed = el.getAttribute('aria-pressed') === 'true', gold = el.classList.contains('gold'), offd = el.disabled;
      if (el.dataset.material === 'wood') art = SKA.plank({ x: 0, y: 0, w: w, h: hh, text: '', cords: !phone() && hh > 400, cordLen: 12, color: '#c9966a' }).svg;
      else { var fill = offd ? '#eee3c6' : pressed ? '#9fdcc5' : gold ? '#f7cf6b' : '#fff8ea'; art = SKA.plate({ x: 0, y: 0, w: w, h: hh, r: 8, fill: fill, rim: offd ? '#c9bb9c' : '#a08252', screws: false, cast: 'sk-cast-sm' }) + '<rect x="5" y="5" width="' + Math.max(0, w - 10) + '" height="' + Math.max(0, hh - 10) + '" rx="4" fill="' + fill + '"/>'; }
      el.insertAdjacentHTML('afterbegin', SKA.svg(w, hh, art, ' class="material" aria-hidden="true" preserveAspectRatio="none"'));
    });
  }

  // ------------------------------------------------------------------ the AI door: a key, tested from this browser
  async function testKey(h, door) {
    var attempt = ++keyTest;
    var el = root.document.querySelector('#key'), P = root.SnapProviders;
    var key = el && !el.dataset.saved ? el.value.trim() : g.keyText || keyOf(door);
    if (!key) { g.keyStatus = 'error'; g.keyMsg = C.key.placeholder + '.'; return h.render(); }
    g.keyText = el && !el.dataset.saved ? key : ''; g.keyStatus = 'testing'; h.render();
    var fn = P && (door === 'NEAR AI Cloud' ? P.nearai : door === 'Claude' ? P.claude : door === 'OpenRouter' ? P.openrouter : door === 'Codex' ? P.codex : null);
    if (!fn) { g.keyStatus = 'error'; g.keyMsg = 'This AI cannot be reached from the browser yet.'; return h.render(); }
    var r; try { r = await fn.test(key); } catch (e) { r = { ok: false, kind: 'other', message: e.message }; }
    // A later test, edited key or different door supersedes this reply, including failures.
    var selected = pick(h);
    if (attempt !== keyTest || !selected || selected.route !== 'key' || selected.door !== door) return;
    if (r && r.ok) {
      store().set(KEY_STORE + door, key); store().set(LAST_STORE, door); g.keyText = ''; g.keyStatus = 'ok'; g.answer = r.say || '';
      h.P.door = { door: door, route: 'key', identity: door === 'Claude' ? 'Claude Console' : door, keyMask: mask(key), hi: g.answer }; h.save();
    } else { g.keyStatus = r && r.kind === 'bad-key' ? 'wrong' : r && r.kind === 'no-credits' ? 'nocredit' : 'error'; g.keyMsg = (r && r.message) || 'The call failed.'; }
    h.render();
  }
  function setCap(v) { var n = Number(v); if (n > 0 && n <= 100) store().set(CAP_STORE, String(n)); else if (v === '' || v == null) store().del(CAP_STORE); }

  // ------------------------------------------------------------------ the AI door: a plan, through the player's own agent session
  function stopPlan() { if (g.poll) root.clearInterval(g.poll); if (g.tick) root.clearInterval(g.tick); g.poll = g.tick = null; }
  async function requestCode(h, agent) {
    if (g.requesting) return;
    g.requesting = true;
    var P = root.SnapProviders; stopPlan(); g.code = null; g.codeErr = ''; g.expired = false; g.copied = false; g.joinedFor = ''; h.render();
    if (!P || !P.snap) { g.requesting = false; g.codeErr = 'The snap module did not load.'; return h.render(); }
    var r, args = { agent: C.plan[agent].agent, name: h.P.name || '', planStop: parseInt(h.P.planStop || '10%', 10) };
    try { r = await (h.requestCode ? h.requestCode(args) : P.snap.requestCode(args)); }
    catch (e) { r = { ok: false, message: e.message }; }
    finally { g.requesting = false; }
    // A different door may have been picked while the wallet confirmed the token; never show the old door's code.
    if (!h.P.pick || h.P.pick.route !== 'plan' || h.P.pick.door !== agent) {
      if (h.P.pick && h.P.pick.route === 'plan') return requestCode(h, h.P.pick.door);
      return;
    }
    if (!r || !r.ok) { g.codeErr = (r && r.message) || 'The arena did not give a code.'; return h.render(); }
    g.code = { code: r.code, expiresAt: r.expiresAt, snapUrl: r.snapUrl || '' }; h.render();
    g.tick = root.setInterval(function () { var el = root.document.querySelector('#code-left'); if (el) el.textContent = left(); if (g.code && Date.now() > g.code.expiresAt) { g.expired = true; stopPlan(); h.render(); } }, 1000);
    g.poll = root.setInterval(async function () {
      if (!g.code) return; var p = null; try { p = await P.snap.poll(g.code.code); } catch (e) { p = null; }
      if (p && p.joined) {
        stopPlan(); g.joinedFor = agent; store().set(LAST_STORE, agent === 'Codex' ? 'Codex' : 'Claude');
        // the code is kept with the draft: the arena page's panel reads the session's log by it (/snap/code/<code>/log)
        h.P.door = { door: agent === 'Codex' ? 'Codex' : 'Claude', route: 'plan', identity: agent, keyMask: '', hi: '' }; h.P.planCode = g.code && g.code.code; h.save(); h.render();
      }
    }, 3000);
  }

  // ------------------------------------------------------------------ actions (data-act="g:…")
  async function act(a, h, el) {
    var x = a.slice(2), P = h.P;
    if (x.indexOf('step:') === 0) { var st = x.slice(5); if (st === 'doors' && P.pick && h.V.step !== 'doors') { /* keep the door on screen */ } if (st !== 'doors') { /* leaving step 4 keeps the pick */ } return h.go(st); }
    if (x === 'close' || x === 'watch') return h.backToArena();
    if (x.indexOf('wallet:') === 0) { var id = x.slice(7); return id === 'dev-throwaway' ? h.devWallet() : h.connectWallet(id); }
    if (x === 'wallet-forget') { P.wallet = null; h.save(); return h.render(); }
    if (h.fixedPersona && h.fixedPersona() && /^(build|temper:|quirk:)/.test(x)) return h.say(C.persona.fixed, true);
    if (x.indexOf('preset:') === 0) { h.setPreset(x.slice(7)); return h.render(); }
    if (x === 'use') { P.fighterChosen = true; h.save(); return h.claim(); }
    if (x === 'build') { P.fighterChosen = true; P.claim = null; if (!P.name) P.name = ''; h.save(); return h.go('personality'); }
    if (x.indexOf('temper:') === 0) { P.temper = x.slice(7); h.save(); return h.render(); }
    if (x.indexOf('quirk:') === 0) { var q = x.slice(6), qs = P.quirks || (P.quirks = []), i = qs.indexOf(q); if (i >= 0) qs.splice(i, 1); else if (qs.length < 2) qs.push(q); h.save(); return h.render(); }
    if (x.indexOf('door:') === 0) {
      var parts = x.split(':'), route = parts[1], door = parts.slice(2).join(':');
      keyTest++;
      P.pick = { route: route, door: door }; h.save(); g.keyStatus = ''; g.keyText = ''; g.keyMsg = '';
      if (route === 'plan') { h.go('doors'); return requestCode(h, door); }
      return h.go('doors');
    }
    if (x === 'other') { keyTest++; stopPlan(); P.pick = null; h.save(); return h.go('doors'); }
    if (x === 'ai') { if (P.door && P.door.door) P.pick = { route: P.door.route, door: P.door.route === 'plan' ? P.door.identity : P.door.door }; h.save(); return h.go('doors'); }
    if (x === 'test') return testKey(h, P.pick.door);
    if (x.indexOf('cap:') === 0) { setCap(x.slice(4)); return h.render(); }
    if (x === 'newcode') return requestCode(h, P.pick.door);
    if (x === 'copy') { var cmd = command(P.pick.door, h), ok = cmd && await root.SnapUI.copyText(cmd); g.copied = !!ok; h.render(); if (!ok) h.say('Could not copy. Select the line and copy it by hand.', true); return; }
    if (x.indexOf('stop:') === 0) { P.planStop = x.slice(5); h.save(); return h.render(); }
    if (x === 'terms') return h.loadTerms();
    if (x === 'snap') {
      if (checkNeeds(h)) return h.render();
      P.agreed = true; P.termsVersion = h.V.terms.version; h.save();
      return h.snapIn();
    }
  }
  // typing: the key (kept for Test), the other cap, the name (checked against the ring)
  var nameTimer = null;
  function input(t, h) {
    if (t.id === 'key') { keyTest++; delete t.dataset.saved; g.keyText = t.value; g.keyStatus = ''; return true; }
    if (t.id === 'cap-other') { setCap(t.value.trim()); refreshBar(h); return true; }
    if (t.id === 'name') { if (h.fixedPersona && h.fixedPersona()) return true; h.P.name = t.value; h.save(); g.name.picked = ''; g.name.free = null; root.clearTimeout(nameTimer); nameTimer = root.setTimeout(function () { checkName(h); }, 350); refreshBar(h); return true; }
    return false;
  }
  function refreshBar(h) {   // the bar and the name status change while typing; the field keeps focus (render keeps it)
    h.render();
  }
  // is the name free in the ring right now? (item 26: a default name never matches a fighter in the ring)
  async function checkName(h) {
    var n = String(h.P.name || '').trim(); if (!n) return;
    var taken = await h.ringNames(); g.name.checked = n; g.name.free = !taken.has(squash(n)); h.render();
  }
  function squash(x) { return String(x).toLowerCase().replace(/[^a-z0-9]/g, ''); }
  // entering the name step: a default name (empty, or the claimed premint's own) that is in the ring gets a free variant
  async function enterPersona(h) {
    var P = h.P, base = String(P.name || '').trim(), isDefault = !base || (P.claim && base === P.claim.name) || base === 'Newcomer';
    if (h.fixedPersona && h.fixedPersona()) { g.name.checked = P.name; g.name.free = true; g.name.picked = ''; h.render(); return; }
    if (!isDefault) return checkName(h);
    var taken = await h.ringNames(), name = base || 'Newcomer', n = 2;
    if (String(P.name || '').trim() !== base) return checkName(h);   // the player typed a name meanwhile: theirs stands
    if (taken.has(squash(name))) { var orig = name; while (taken.has(squash(orig + ' ' + n))) n++; name = orig + ' ' + n; g.name.picked = orig; } else g.name.picked = '';
    if (P.name !== name) { P.name = name; h.save(); }
    g.name.checked = name; g.name.free = true; h.render();
  }
  function leave(step) { if (step !== 'doors') stopPlan(); }
  function enter(step, h) {
    if (step === 'personality') enterPersona(h);
    if (step === 'doors' && h.P.pick && h.P.pick.route === 'plan' && !g.code && !g.poll && !planJoined(h, h.P.pick.door)) requestCode(h, h.P.pick.door);
  }
  root.SnapGuide = { view: view, act: act, input: input, paint: paint, enter: enter, leave: leave, aiReady: aiReady, state: g, phone: phone, checkNeeds: checkNeeds };
})(typeof globalThis !== 'undefined' ? globalThis : this);
