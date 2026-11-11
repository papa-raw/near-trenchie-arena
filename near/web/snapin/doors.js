/* snapin/doors.js: the login modal, "Choose the AI entrance" (approved board S4-redraw B, the edge dock).
 * Four doors in Pat's fixed order, no default: NEAR AI Cloud, Claude, Codex, OpenRouter. Each door makes one real call from its path:
 *   NEAR AI Cloud, Claude (Console key), OpenRouter: a key the player pastes (or gets by OpenRouter's PKCE return) is tested by a
 *   browser-direct "Say hi" call. Claude Code and Codex hand off through SNAP.md: the page asks for a one-time code, shows the command
 *   and the app link, and polls until the agent arrives. Keys stay in this browser (O10) and never go to our server.
 * Depends on window.SnapUI, SnapMarks and SnapProviders (providers.js). No silent fallback: a path that cannot run says so on screen. */
(function (root) {
  'use strict';
  var U = root.SnapUI, M = root.SnapMarks, esc = U.esc, btn = U.btn;
  var KEY_ROUTING_COPY = 'Sends it only to {door}.';   // swappable string (cors-1 verified the browser-direct route for all three key doors)
  var KEY_PAGES = {   // where the player makes the key; each is the provider's own page
    'NEAR AI Cloud': 'https://cloud.near.ai/signin',
    Claude: 'https://platform.claude.com/settings/keys',
    OpenRouter: 'https://openrouter.ai/settings/keys'
  };
  var CREDIT_PAGES = { 'NEAR AI Cloud': 'https://cloud.near.ai/signin', Claude: 'https://platform.claude.com/settings/billing', OpenRouter: 'https://openrouter.ai/settings/credits' };
  var GET_PAGES = { 'Claude Code': 'https://code.claude.com/docs/en/quickstart', Codex: 'https://learn.chatgpt.com/docs/quickstart', 'NEAR AI Cloud': 'https://cloud.near.ai/signin', OpenRouter: 'https://openrouter.ai/', Console: 'https://platform.claude.com/' };
  var KEY_STORE = 'trenchie.snapin.key.';   // + door; kept only in this browser
  var LAST_STORE = 'trenchie.snapin.lastdoor';
  var CAP_STORE = 'trenchie.snapin.cap';

  var s = { state: 'doors', door: '', keyRoute: false, help: false, panel: false, feedback: '', busy: false, error: '', cap: '', keyText: '',
            code: null, codeError: '', expired: false, polling: null, hi: '' };
  var host = { repaint: function () {}, onConnected: function () {}, onClose: function () {}, board: 'login' };

  var identity = function () { return s.door === 'Claude' ? (s.keyRoute ? 'Claude Console' : 'Claude Code') : s.door; };
  var line = function (t) { return '<div class="consent-line">' + t + '</div>'; };
  var stateLine = function (t, err) { return '<div class="connection-state' + (err ? ' error-state' : '') + '" role="' + (err ? 'alert' : 'status') + '">' + t + '</div>'; };
  var providers = function () { return root.SnapProviders || null; };
  function keyOf(door) { return U.store.get(KEY_STORE + door) || ''; }
  function maskKey(k) { return k ? 'Key …' + k.slice(-4) : ''; }

  // ------------------------------------------------------------------ views
  function doors(returning) {
    var last = U.store.get(LAST_STORE), quick = '';
    if (returning && last) quick = btn(M.mark(last) + '<span>Continue with ' + esc(last) + '</span><span aria-hidden="true">↗</span>', 'ai:return', 'return-door');
    return quick + '<div class="ai-doors">' + M.P.map(function (n, i) {
      return btn(M.mark(n) + '<span class="door-name">' + n + '</span><span class="door-tag">' + M.tag(n) + '</span><span class="door-arrow" aria-hidden="true">↗</span>', 'ai:door:' + n, 'ai-door door-' + i);
    }).join('') + '</div>';
  }
  var helpCopy = function () { return '<aside class="ai-help"><h2>Before you choose</h2><div class="help-entry"><b>PLAN</b><span>Your own agent.</span><span>Your computer stays on.</span></div><div class="help-entry"><b>KEY</b><span>Your own spending key.</span><span>Provider credits required.</span></div><div class="help-foot">You choose. No default.</div></aside>'; };
  // Cost per hour while your trenchie is in the ring, in battle mode. The AI calls when the fight changes, not on a clock: a
  // plan (re)write on hits (at most every 20 s), a KO, low hp or the owner's order; a line at most every 10 s; a prediction once
  // a life. NEAR AI Cloud is measured: the real brain.js loop on DeepSeek V4.1 Flash for 6 sim minutes against the live DEV
  // crowd's rhythm (a hit every ~10 s, a KO every 2 min) on a fake clock, so the fight is simulated and the model calls are
  // real: 25 plans, 35 lines, 3 predictions, mean $0.000166 a call, about $0.10 an hour (measured by
  // near/web/snapin/brain_cost_live_check.cjs at e1a05d0; its output brain_cost_live.json at 7e996d8). Claude (Haiku 5.5:
  // $0.10 in / $0.50 out / $0.01 cached per million) and OpenRouter's default (openai/gpt-6-luna, the same $0.10 / $0.50 /
  // $0.01 on openrouter.ai's model list) are list prices for the same token mix, read 2026-11-11.
  // "Never more than your cap": brain.js reserves each call's worst case in the shared spend window before sending it and
  // does not send a call that could pass the cap (brain.js at df092fa; the cost check above is brain_cost_live.json at 7e996d8).
  var COST = {
    'NEAR AI Cloud': { hour: '≈ $0.10', basis: 'Measured: the real AI loop on DeepSeek V4.1 Flash through 6 minutes of a simulated fight.' },
    Claude: { hour: '≈ $0.04', basis: 'List price, Claude Haiku 5.5, for the same calls.' },
    OpenRouter: { hour: '≈ $0.04', basis: 'List price, GPT-6 Luna (read 2026-11-11), for the same calls.' }
  };
  var RHYTHM = 'Your AI calls when the fight changes: a new plan on hits (at most every 20 s), a KO, low hp or your order; a line at most every 10 s; a prediction once a life. More in a busy brawl, less in a calm one.';
  // this hour's spend, from the player's AI (brain.js) when it is on this page
  var brain = null, brainHooked = false;   // brain.js loads after this file: hook it the first time it is needed
  function hookBrain() { if (!brainHooked && root.SnapBrain && root.SnapBrain.on) { brainHooked = true; root.SnapBrain.on(function (x) { brain = x; }); } return brainHooked; }
  // the cap the player saved (the brain reads the same key once it is in the ring; until then its capUsd is null)
  function storedCap() { var c = Number(U.store.get(CAP_STORE)); return c > 0 ? c : 0; }
  function spendLine() {
    hookBrain();
    if (!brain) return 'Nothing spent: your AI is not wired in on this page.';
    return 'Spent this hour: $' + Number(brain.spendHourUsd || 0).toFixed(3) + (storedCap() ? ' of your $' + storedCap().toFixed(2) + ' cap' : ' (no cap set: your AI waits for one)') + '.';
  }
  function cost(plan) {
    var c = COST[s.door] || null, enforced = hookBrain();
    return '<div class="ai-cost"><b>Real money</b>' + (plan ? line('Your plan’s usage limits apply. This page charges nothing.') :
      '<div class="cost-row"><span>Cost per hour</span><strong>' + esc(c ? c.hour : 'unknown') + '</strong></div><small>' + esc(c ? c.basis : '') + ' ' + RHYTHM + '</small>' +
      '<label for="cap">Hourly cap (USD)</label><input id="cap" type="number" min="0" step="0.05" placeholder="e.g. 0.20" value="' + esc(s.cap) + '">' +
      '<small>' + (enforced ? 'At 80% of the cap your AI calls every 30 s; at 100% it stops until the hour rolls on. It never spends more than your cap: a call that could pass it is not sent.' : 'Your AI is not wired in on this page, so nothing is spent and the cap has nothing to stop.') + '</small>') + '</div>';
  }
  function consent(plan) {
    var nm = s.door === 'Claude' ? 'Console' : s.door;
    return '<section class="consent" aria-label="Permission summary"><h2>' + (plan ? 'Trenchie Arena requests' : 'How your key is handled') + '</h2>' +
      (plan ? [line('Your agent sends us moves.'), line('Runs on your computer.'), line('Uses your own plan.'), line('Its permission prompts apply.'), line('We cannot constrain it.')].join('') :
        [line('<b>This page holds your spending key.</b>'), line('It spends ' + nm + ' credits.'), line('Stored in this browser.'), line(KEY_ROUTING_COPY.replace('{door}', s.door === 'Claude' ? 'Claude Console' : s.door)), line('Set provider limits yourself.')].join('')) + '</section>';
  }
  function providerLinks(plan) {
    var label = s.door === 'Claude' ? (plan ? 'Claude Code' : 'Console') : s.door;
    return '<div class="get-row"><span>Need ' + esc(label) + '?</span>' + btn('Get it', 'ai:get', 'textlink') + '</div>';
  }
  function handoff() {
    var agent = s.door === 'Codex' ? 'Codex' : 'Claude Code', c = s.code;
    var codeBox = '<div class="pair-code"><span>One-time code</span><strong>' + (s.expired ? 'Code expired' : c ? esc(c.code) : s.codeError ? 'No code' : 'Asking…') + '</strong><small>' +
      (s.expired ? 'Create another code.' : c ? 'Expires in <span id="code-left">' + esc(left()) + '</span>' : s.codeError ? esc(s.codeError) : 'Waiting for the snap endpoint.') + '</small></div>';
    var cmd = c && !s.expired ? esc(c.command) : '(no command until a code is issued)';
    return consent(true) + codeBox + (c && c.stub ? line('This is a local test endpoint, not the hosted arena.') : '') + '<pre class="command-preview" aria-label="Command">' + cmd + '</pre>' +
      btn(s.expired || s.codeError ? 'New code' : 'Copy command', s.expired || s.codeError ? 'ai:renew' : 'ai:copy', 'main-action') +
      (c && c.link ? btn('Open app', 'ai:app', 'textlink') : '') +
      '<div class="wait-line" role="status">' + (s.expired ? 'Nothing happened? Try again.' : c ? 'Waiting for your agent…' : '') + '</div>' +
      (s.fallbackOpen ? '<div class="consent-line">Nothing happened? Copy the command and paste it in your own terminal.' + (agent === 'Codex' ? ' The app link opens the ChatGPT desktop app and does not send the prompt.' : ' If the link did nothing, Claude Code is not set up to open links yet; the command always works.') + '</div>' : btn('Nothing happened?', 'ai:fallback', 'textlink')) +
      cost(true) + providerLinks(true);
  }
  function left() { if (!s.code) return ''; var ms = Math.max(0, s.code.expiresAt - Date.now()), m = Math.floor(ms / 60000), sec = Math.floor(ms / 1000) % 60; return (m < 10 ? '0' : '') + m + ':' + (sec < 10 ? '0' : '') + sec; }
  function creditsHelper() {
    return '<details class="plan-credit-help"><summary>Not linked yet?</summary><ol><li><span>Max/Ultra: Settings → Billing</span><span>Team: Organization settings → Billing</span><span>API credits</span><a href="https://claude.ai/" target="_blank" rel="noopener noreferrer">Open Claude</a></li><li>Link Console organization</li><li>Create key</li></ol><div class="sub">Max, Ultra or Team</div><div class="sub">New subscribers: 7 days</div></details>';
  }
  function keyPanel() {
    var near = s.door === 'NEAR AI Cloud', cons = s.door === 'Claude';
    return consent(false) + (near ? '<div class="key-steps"><span>Google, GitHub or NEAR</span><span>Two Terms ticks; screening</span><span>Credits → API Keys</span><span>Create key; set Limit</span></div>' :
      cons ? '<div class="key-steps"><span>Console → API Keys</span><span>Create key → copy</span></div>' + creditsHelper() :
      '<div class="key-steps"><span>Review access at OpenRouter.</span><span>Set expiry and credit limit.</span></div>') +
      (s.door === 'OpenRouter' ? btn('Review authorization', 'ai:authorize', 'main-action') : btn('Open key page', 'ai:key-page', 'main-action')) +
      providerLinks(false) + cost(false) +
      (s.door !== 'OpenRouter' ? '<label class="field" for="key">' + (cons ? 'Console API key' : 'API key') + '</label><input id="key" type="password" placeholder="Paste key" autocomplete="off" spellcheck="false" value="' + esc(s.keyText) + '">' + btn(s.busy ? 'Asking…' : 'Say hi', 'ai:test', 'secondary', s.busy ? 'disabled' : '') : '') +
      '<div class="wait-line">' + (s.state === 'waiting' ? 'Waiting in the other tab…' : '') + '</div>' + (s.error ? stateLine(esc(s.error), true) : '');
  }
  function account() {
    var plan = !s.keyRoute && (s.door === 'Claude' || s.door === 'Codex');
    return btn(M.mark(s.door) + '<span>' + (plan ? 'Your plan' : esc(maskKey(keyOf(s.door)) || 'Key')) + '</span><span class="connected-dot">●</span>', 'ai:panel', 'connection-chip') +
      (s.panel ? '<section class="connection-panel">' + line(plan ? 'Agent link active.' : spendLine()) + (plan ? '' : btn('Say hi', 'ai:say-hi', 'secondary')) + btn('Switch AI', 'ai:switch', 'secondary') + (!plan ? btn('Add credits', 'ai:topup', 'secondary') : '') + btn('Disconnect', 'ai:disconnect', 'secondary') +
        (!plan ? line('Forgets this browser’s key.') + line('Delete at provider to revoke.') + btn('Provider key page', 'ai:revoke', 'textlink') : line('Ends this arena link.')) + '</section>' : '') +
      (s.hi ? '<div class="ai-feedback" role="status">“' + esc(s.hi) + '”</div>' : '') + btn('Connection details', 'ai:panel', 'textlink');
  }
  function view(o) {
    o = o || {};
    var st = s.state, head = '', content = '';
    if (st === 'doors') { head = 'AI controls your persona'; content = '<div class="chooser-layout">' + doors(o.returning) + (s.help ? helpCopy() : '') + '</div>' + btn('What you need', 'ai:help', 'help-toggle'); }
    else if (st === 'claude') { head = 'Claude'; content = '<div class="claude-paths">' + btn('<strong>Claude Code</strong><span>Your agent · PLAN</span>', 'ai:plan', 'path-card') + btn('<strong>Use plan credits</strong><span>Console API key · KEY</span>', 'ai:credits', 'path-card') + '</div>' + providerLinks(true); }
    else if (st === 'handoff') { head = s.door === 'Codex' ? 'Codex' : 'Claude Code'; content = handoff(); }
    else if (st === 'near' || st === 'router' || st === 'credits' || st === 'waiting') { head = identity(); content = keyPanel(); }
    else if (st === 'connected') { head = identity(); content = stateLine('Ready to fight') + account() + (o.onContinue ? '<button class="main-action" data-act="ai:continue">' + esc(o.onContinue) + '</button>' : ''); }
    else if (st === 'disconnected') { head = identity(); content = stateLine('AI disconnected') + (s.keyRoute ? line('This browser forgot the key.') + line('Provider access still exists.') : line('This arena link ended.')) + btn('Choose AI', 'ai:switch', 'main-action'); }
    else if (st === 'bad-key' || st === 'no-credits' || st === 'key-expired' || st === 'blocked') {
      head = identity();
      content = stateLine(({ 'bad-key': 'Key not accepted', 'no-credits': 'No credits left', 'key-expired': 'Key expired', blocked: 'Call could not be made' })[st], true) + line(esc(s.error || 'Your persona is waiting.')) +
        btn(st === 'no-credits' ? 'Add credits' : 'Paste new key', st === 'no-credits' ? 'ai:topup' : 'ai:new-key', 'main-action');
    }
    var back = st === 'doors' ? '' : btn('Other AIs', 'ai:switch', 'ai-back');
    return { head: head, html: '<div class="ai-drawing layout-b ' + (s.help ? 'help-open' : '') + '" data-ai-state="' + st + '">' + (o.walletChip ? '<div class="wallet-chip">' + esc(o.walletChip) + '</div>' : '') + back + content + '<div class="ai-feedback" id="ai-feedback" role="status"></div></div>' };
  }

  // ------------------------------------------------------------------ actions (real calls)
  function say(msg) { var n = root.document && root.document.querySelector('#ai-feedback'); if (n) n.textContent = msg; }
  function go(state) { s.state = state; s.error = state === 'doors' ? '' : s.error; host.repaint(); }
  function openTab(url) { try { root.open(url, '_blank', 'noopener,noreferrer'); } catch (e) { /* popup blocked */ } }
  function stopPolling() { if (s.polling) { root.clearInterval(s.polling); s.polling = null; } }
  function mapKind(kind) { return kind === 'bad-key' ? 'bad-key' : kind === 'no-credits' ? 'no-credits' : kind === 'expired' ? 'key-expired' : 'blocked'; }

  async function testKey() {
    var P = providers(); var el = root.document.querySelector('#key'); if (el) s.keyText = el.value.trim();
    var capEl = root.document.querySelector('#cap'); if (capEl) { s.cap = capEl.value; U.store.set(CAP_STORE, s.cap); }
    if (!P) { s.error = 'The provider module did not load. Reload the page.'; return go('blocked'); }
    if (!s.keyText) { s.error = 'Paste a key first.'; host.repaint(); return; }
    s.busy = true; s.error = ''; host.repaint();
    var fn = s.door === 'NEAR AI Cloud' ? P.nearai : s.door === 'Claude' ? P.claude : P.openrouter;
    var r = await fn.test(s.keyText);
    s.busy = false;
    if (r && r.ok) { U.store.set(KEY_STORE + s.door, s.keyText); s.keyText = ''; s.hi = r.say || ''; connected(); }
    else { s.error = (r && r.message) || 'The call failed.'; go(mapKind(r && r.kind)); }
  }
  function connected() {
    U.store.set(LAST_STORE, s.door); s.state = 'connected'; s.panel = false; stopPolling(); host.repaint();
    host.onConnected({ door: s.door, route: s.keyRoute ? 'key' : 'plan', identity: identity(), keyMask: s.keyRoute ? maskKey(keyOf(s.door)) : '' });
  }
  async function requestCode() {
    var P = providers(); s.code = null; s.codeError = ''; s.expired = false; stopPolling();
    if (!P || !P.snap) { s.codeError = 'The snap module did not load.'; return host.repaint(); }
    var r = await P.snap.requestCode({ agent: s.door === 'Codex' ? 'codex' : 'claude-code', name: host.persona ? host.persona() : '' });
    if (!r || !r.ok) { s.codeError = (r && r.message) || 'The snap endpoint did not answer.'; return host.repaint(); }
    s.code = r; host.repaint();
    s.polling = root.setInterval(async function () {
      if (s.code && Date.now() > s.code.expiresAt) { s.expired = true; stopPolling(); return host.repaint(); }
      var tick = root.document.querySelector('#code-left'); if (tick) tick.textContent = left();
      var p = await P.snap.poll(s.code.code);
      if (p && p.joined) connected();
    }, 3000);
  }
  async function finishOpenRouter(code) {
    var P = providers(); s.door = 'OpenRouter'; s.keyRoute = true;
    if (!P) { s.error = 'The provider module did not load.'; return go('blocked'); }
    var verifier = U.store.get('trenchie.snapin.or.verifier') || ''; if (!verifier && root.sessionStorage) { try { verifier = root.sessionStorage.getItem('trenchie.snapin.or.verifier') || ''; } catch (e) { /* none */ } }
    s.busy = true; s.state = 'router'; host.repaint();
    var r = await P.openrouter.finish({ code: code, verifier: verifier });
    if (!r || !r.ok) { s.busy = false; s.error = (r && r.message) || 'OpenRouter did not return a key.'; return go('blocked'); }
    var t = await P.openrouter.test(r.key); s.busy = false;
    U.store.set(KEY_STORE + 'OpenRouter', r.key);   // the key is the player's; a zero-credit key is still theirs
    if (t && t.ok) { s.hi = t.say || ''; return connected(); }
    s.error = (t && t.message) || 'The first call failed.'; go(mapKind(t && t.kind));
  }

  async function act(a) {
    if (a.indexOf('ai:') !== 0) return false;
    var x = a.slice(3); s.feedback = '';
    if (x.indexOf('door:') === 0) {
      s.door = x.slice(5); s.keyRoute = M.tag(s.door) === 'KEY'; s.panel = false; s.error = ''; s.keyText = '';
      if (s.door === 'Codex') { go('handoff'); requestCode(); }
      else go(({ 'NEAR AI Cloud': 'near', Claude: 'claude', OpenRouter: 'router' })[s.door]);
    }
    else if (x === 'return') {
      var last = U.store.get(LAST_STORE); if (!last) return true;
      s.door = last; s.keyRoute = M.tag(last) === 'KEY' && !(last === 'Claude' && !keyOf('Claude'));
      if (s.keyRoute && keyOf(last)) connected(); else if (last === 'Codex' || last === 'Claude') { go('handoff'); requestCode(); } else go(({ 'NEAR AI Cloud': 'near', OpenRouter: 'router' })[last] || 'doors');
    }
    else if (x === 'plan') { s.door = 'Claude'; s.keyRoute = false; go('handoff'); requestCode(); }
    else if (x === 'credits') { s.door = 'Claude'; s.keyRoute = true; s.error = ''; go('credits'); }
    else if (x === 'switch') { stopPolling(); s.panel = false; s.help = false; s.fallbackOpen = false; go('doors'); }
    else if (x === 'help') { s.help = !s.help; go('doors'); }
    else if (x === 'panel') { s.panel = !s.panel; go('connected'); }
    else if (x === 'test') await testKey();
    else if (x === 'say-hi') { s.keyText = keyOf(s.door); s.busy = false; var P = providers(); var fn = P && (s.door === 'NEAR AI Cloud' ? P.nearai : s.door === 'Claude' ? P.claude : P.openrouter); if (fn) { var r = await fn.test(s.keyText); if (r && r.ok) { s.hi = r.say || ''; } else { s.error = (r && r.message) || 'The call failed.'; s.keyText = ''; return go(mapKind(r && r.kind)); } } s.keyText = ''; go('connected'); }
    else if (x === 'disconnect') { U.store.del(KEY_STORE + s.door); stopPolling(); s.panel = false; s.hi = ''; go('disconnected'); host.onDisconnected && host.onDisconnected(); }
    else if (x === 'new-key') { s.keyRoute = true; s.error = ''; s.keyText = ''; go(s.door === 'NEAR AI Cloud' ? 'near' : s.door === 'Claude' ? 'credits' : 'router'); }   // the refused key is not offered again
    else if (x === 'fallback') { s.fallbackOpen = true; host.repaint(); }
    else if (x === 'renew') { go('handoff'); requestCode(); }
    else if (x === 'authorize') {
      var Pr = providers(); if (!Pr) { s.error = 'The provider module did not load.'; return go('blocked'); }
      var b = await Pr.openrouter.begin({ callbackUrl: root.location.origin + root.location.pathname, state: 'r3' });
      if (b && b.url) { U.store.set('trenchie.snapin.or.verifier', b.verifier || ''); root.location.href = b.url; } else { s.error = 'Could not start the OpenRouter authorization.'; go('blocked'); }
    }
    else if (x === 'key-page') { openTab(KEY_PAGES[s.door]); s.state = 'waiting'; host.repaint(); }
    else if (x === 'copy') { var ok = s.code ? await U.copyText(s.code.command) : false; say(ok ? 'Command copied.' : 'Could not copy. Select the command above and copy it by hand.'); }
    else if (x === 'app') { if (s.code && s.code.link) { say('Opening the app. Press Enter there.'); root.location.href = s.code.link; } }
    else if (x === 'topup') openTab(CREDIT_PAGES[s.door]);
    else if (x === 'get') openTab(GET_PAGES[s.door === 'Claude' ? (s.keyRoute ? 'Console' : 'Claude Code') : s.door]);
    else if (x === 'revoke') openTab(KEY_PAGES[s.door]);
    else if (x === 'continue') host.onContinue && host.onContinue();
    else say('That button does nothing here. Reload the page if this keeps happening.');
    return true;
  }

  root.SnapDoors = {
    KEY_ROUTING_COPY: KEY_ROUTING_COPY, state: s, view: view, act: act, finishOpenRouter: finishOpenRouter,
    attach: function (h) { Object.assign(host, h); },
    reset: function () { stopPolling(); s.state = 'doors'; s.door = ''; s.keyRoute = false; s.help = false; s.panel = false; s.error = ''; s.keyText = ''; s.code = null; s.expired = false; s.fallbackOpen = false; s.hi = ''; s.cap = U.store.get(CAP_STORE) || ''; },
    isConnected: function () { return s.state === 'connected'; }, identity: identity,
    // QA jump to a named state (the URL ?step= deep link); never used by the product path
    preview: function (state, door, keyRoute) { s.door = door || s.door; s.keyRoute = !!keyRoute; s.state = state; s.error = state === 'blocked' || /key|credits/.test(state) ? 'Preview state.' : ''; }
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
