/* snapin/app.js: the snap-in screens as a product, built from the approved boards.
 *   flow      S1-redraw A : watch -> wallet -> fighter presets -> (build) -> personality -> AI doors -> agreement -> arena
 *   login     S4-redraw B : the AI doors as a stand-alone edge dock (also the "AI" step of the flow)
 *   workshop  S2-redraw A : Battle, Inventory, Look (S3 c Hat rack), Persona (the creator beside its file), Card, Agree, Respawn (the corner)
 * Every action is real or says why it is not: nothing here pretends a wallet, a mint or a provider call happened.
 * Needs: art/ska.js, ui.js, marks.js, doors.js, sheet.js, wallet.js, providers.js, card.js and the portrait stack (three + look3 + parts-s3). */
(function (root) {
  'use strict';
  var U = root.SnapUI, D = root.SnapDoors, esc = U.esc, btn = U.btn, receipt = U.receipt, chips = U.chips;
  var doc = root.document, SAVE = 'trenchie.snapin.v1';
  var q = new URLSearchParams(root.location.search);

  // ------------------------------------------------------------------ data (the drawn menu; art rows are pending, as the board said)
  var PRESETS = ['Brawler Swing', 'Hunter Lunge', 'Survivor Beam', 'Looter Lob', 'Brawler Zap'];
  var PRESET_LOOK = [
    { shape: 'bean', body: 'p07', tone: 'warm', eyes: 'keen', brows: 'none', mouth: 'smile', hair: 'cowlick', hairCol: 'p03', hat: 'st-cap' },
    { shape: 'pear', body: 'p15', tone: 'warm', eyes: 'sleepy', brows: 'none', mouth: 'smile', hair: 'puffs', hairCol: 'p03', hat: 'st-cap' },
    { shape: 'pebble', body: 'p12', tone: 'warm', eyes: 'happy', brows: 'none', mouth: 'smile', hair: 'fin', hairCol: 'p03', hat: 'st-cap' },
    { shape: 'bean', body: 'p07', tone: 'warm', eyes: 'keen', brows: 'none', mouth: 'smile', hair: 'none', hairCol: 'p03', hat: 'st-cap' },
    { shape: 'pear', body: 'p12', tone: 'warm', eyes: 'sleepy', brows: 'none', mouth: 'smile', hair: 'cowlick', hairCol: 'p03', hat: 'st-cap' }
  ];
  var PRESET_WEAPON = ['Bonk', 'Spear', 'Trout', 'Lob', 'Zap'];
  var ATTACK = { Swing: 'Hit nearby foes in an arc.', Lunge: 'Dash to the target; hit on arrival.', Beam: 'Wind up, then hit along a line.', Lob: 'Drop a burst into a marked circle.', Zap: 'Hit one foe, then jump to others.' };
  var NETWORK = 'testnet';   // the hackathon build is testnet only; mainnet waits on Pat's yes
  var CHAIN = null;          // a chain-mode host's chain_mode (near/chain/hosted_live.py): NETWORK becomes its identity network
  var STEP_BACK = { personality: ['personality', 'Change the name'], presets: ['presets', 'Pick another battle option'], agree: ['agree', 'Back to the arena rules'] };

  // ------------------------------------------------------------------ state
  var DEF = { preset: 'Brawler Swing', slots: { weapon: 'Bonk', head: 'Cap', body: 'Tee', trinket: 'Roll' }, look: null, lookEdited: false, temper: 'sunny', quirks: [], name: '', voice: '', wallet: null, door: null, agreed: false, resume: null,
              spread: [40, 30, 20, 10], zeroKo: 0, stake: false, move: false, lock: false };
  var P = Object.assign({}, DEF, U.store.json(SAVE, {}));
  P.slots = Object.assign({}, DEF.slots, P.slots || {});
  if (root.SnapSheet && !root.SnapSheet.TEMPERAMENTS.some(function (x) { return x.id === P.temper; })) P.temper = 'sunny';   // saved before the six real names
  // the arena this guide belongs to: the live page's ?ws= (passed by its call to action), kept for this tab
  // kept per tab (sessionStorage), so another tab's or yesterday's arena address never comes back
  var tabGet = function (k) { try { return root.sessionStorage.getItem(k); } catch (e) { return null; } }, tabSet = function (k, v) { try { root.sessionStorage.setItem(k, v); } catch (e) { /* this load only */ } };
  var WS = q.get('ws') || tabGet('trenchie.snapin.ws') || '';
  if (q.get('ws')) tabSet('trenchie.snapin.ws', q.get('ws'));
  var STEPS = ['wallet', 'presets', 'presets-empty', 'claimed', 'build', 'personality', 'doors', 'agree', 'ring'];
  // a step is reachable only once the steps before it are done: no wallet, the wallet step; not agreed, the terms
  var allowed = function (s) { if (STEPS.indexOf(s) < 0) return 'wallet'; if (s !== 'wallet' && !P.wallet) return 'wallet'; if (s === 'ring' && !P.agreed && !(root.SnapRoom && root.SnapRoom.saved())) return 'agree'; return s; };
  // from the arena's call to action a returning visitor picks up where they left off; a link that names a step opens it
  var firstStep = function () { var s = q.get('step'); if (q.get('from') === 'arena' && STEPS.indexOf(P.step) > 0) s = P.step; return allowed(STEPS.indexOf(s) >= 0 ? s : (P.step || 'wallet')); };
  var V = { mode: q.get('mode') || 'flow', step: firstStep(), tab: q.get('tab') || 'battle', openSlot: '', closed: false, msg: '', msgErr: false, busy: false, presetSheet: false };
  function arenaURL() { return '../arena.html' + (WS ? '?ws=' + encodeURIComponent(WS) : ''); }
  function backToArena() { save(); root.location.href = arenaURL(); }
  // one history entry per step, so the browser's Back goes to the previous step, and a reload lands on this one
  function stepURL(step) { var u = new URL(root.location.href); u.searchParams.set('step', step); u.searchParams.delete('from'); u.searchParams.delete('code'); if (WS) u.searchParams.set('ws', WS); return u.pathname + u.search; }
  function go(step, replace) {
    if (step === 'watch') return backToArena();
    step = allowed(step);
    if (step !== 'agree' && step !== 'ring') V.ticks = {};   // after a change, the terms are agreed again
    V.closed = false; V.step = step; V.msg = ''; V.flash = ''; V.confirmNew = false; P.step = step; save();
    try { root.history[replace ? 'replaceState' : 'pushState']({ step: step }, '', stepURL(step)); } catch (e) { /* file: or sandboxed: no history */ }
    if (step === 'doors') D.reset();
    if (root.SnapGuide) root.SnapGuide.leave(step);
    if (step === 'agree') loadTerms();
    render();
    if (boardMode()) root.SnapGuide.enter(step, guideHost);
  }
  function save() { try { var c = Object.assign({}, P); U.store.set(SAVE, JSON.stringify(c)); } catch (e) { /* kept in memory */ } }
  var app, cache = new Map();

  // ------------------------------------------------------------------ a new trenchie (Pat's items 33 and 25)
  // The draft (SAVE) is the trenchie: its name, battle option, claim, look, persona, terms and the fighter it put in the ring.
  // It is the player's work: nothing wipes it on its own. Only "Make a new trenchie", asked once in plain words, starts a
  // fresh draft, and that keeps what belongs to the player: the wallet and the AI door. The AI key and the cap live in their
  // own stores (doors.js), and a wallet library's own keys are never touched. The standing order the player's AI keeps for
  // the old trenchie goes with it.
  var GOAL_STORE = 'trenchie.snapin.brain.goal';
  function freshDraft() {
    var keep = { wallet: P.wallet, door: P.door };
    Object.keys(P).forEach(function (k) { delete P[k]; });
    Object.assign(P, JSON.parse(JSON.stringify(DEF)), keep);
    U.store.del(GOAL_STORE);
    V.ticks = {}; V.nextPreset = ''; V.pickMsg = ''; save();
  }
  function mineDriven() { var st = root.SnapRoom && root.SnapRoom.status(); return st && st.fighter && /^(in|joining|offline)$/.test(st.phase) ? st : null; }
  function hasDraft() { return !!(P.name || P.claim || P.fighter || P.ended || mineDriven()); }
  function draftName() { var st = mineDriven(); return st ? st.fighter.name : P.name || (P.fighter && P.fighter.name) || (P.ended && P.ended.name) || (P.claim && P.claim.name) || 'your Trenchie'; }
  // what a fresh start keeps, said only for what this browser actually holds
  function keptWords() {
    var k = [], door = P.door && P.door.door;
    if (P.wallet) k.push('your wallet');
    if (door) k.push('your AI door (' + door + (P.door.route === 'key' && U.store.get('trenchie.snapin.key.' + door) ? ' and its key' : '') + ')');
    if (capSet()) k.push('your hourly cap');
    return k.length ? 'Kept: ' + k.join(', ').replace(/, ([^,]*)$/, ' and $1') + '.' : '';
  }
  // the control asks once, in place: what it forgets, what happens to a trenchie in the ring, what it keeps
  function newButton(cls) {
    if (!V.confirmNew) return btn('Make a new Trenchie', 'new-trenchie', cls || 'textlink');
    var nm = draftName(), kept = keptWords();
    return '<div class="confirm-new" role="group" aria-label="Make a new Trenchie"><div class="sub"><b>' + esc('This forgets ' + nm + ': its name, look, temperament, quirks and voice' + (P.claim ? ', and its premint claim' : '') + '. Keep it or start fresh?') + '</b></div>' +
      (mineDriven() ? '<div class="sub">' + esc(nm + ' swims home first: this browser drives one Trenchie at a time.') + '</div>' : '') + (kept ? '<div class="sub">' + esc(kept) + '</div>' : '') +
      '<div class="row">' + btn('Start fresh', 'new-trenchie-yes', 'secondary') + btn('Keep ' + esc(nm), 'new-trenchie-no', 'textlink') + '</div></div>';
  }
  async function newTrenchie() {
    var st = mineDriven(), nm = draftName(), swim = null; V.confirmNew = false;
    if (st && st.phase === 'joining') return say('Wait for the snap-in to finish, then make a new Trenchie.', true);
    if (st) { V.flash = nm + ' is swimming home…'; render(); swim = { id: st.fighter.id, at: Date.now() }; try { await root.SnapRoom.leave(); } catch (e) { /* the lease sends it home */ } }
    freshDraft(); if (swim) { P.swimming = swim; save(); }   // kept across a reload: the next join waits for that swim home
    go(P.wallet ? 'presets' : 'wallet');
    V.flash = 'A new Trenchie: ' + nm + ' is forgotten. ' + keptWords(); render();
    try { root.scrollTo(0, 0); } catch (e) { /* no window */ }
  }
  // the trenchie this browser put in the ring is out of it (the arena restarted, every page was closed until the seat ran
  // out, or the browser lost its key): only the seat is gone. The draft stays, and the guide offers the two ways on.
  var ENDED = { context_mismatch: 'the arena restarted', not_found: 'the arena restarted', 'no-key': 'this browser no longer holds its key' };
  function seatEnded(f, code) { P.ended = { name: f.name, why: ENDED[code] || 'no page was open to keep it', at: Date.now() }; P.fighter = null; save(); render(); }
  function endedLine() {
    if (!P.ended || V.mode !== 'flow' || V.step === 'ring' || mineDriven()) return '';
    return '<div class="in-banner" role="status">' + esc('DEV ' + P.ended.name + ' is out of the arena (' + P.ended.why + '). Your Trenchie is kept.') + ' ' +
      btn('Snap ' + esc(P.ended.name) + ' back in', 'rejoin', 'textlink') + newButton() + '</div>';
  }

  var presetIdx = function () { return Math.max(0, PRESETS.indexOf(P.preset)); };
  function look() { return P.look || Object.assign({}, PRESET_LOOK[presetIdx()]); }
  function setPreset(name) {
    var i = PRESETS.indexOf(name); if (i < 0) return;
    P.preset = name; if (!P.lookEdited) P.look = null;   // a look the player styled stays when the battle option changes
    P.slots = { weapon: PRESET_WEAPON[i], head: 'Cap', body: 'Tee', trinket: 'Roll' }; save();
  }
  function portraitURL() {
    var lk = look();
    if (!P.lookEdited && PRESET_LOOK[presetIdx()] && JSON.stringify(lk) === JSON.stringify(PRESET_LOOK[presetIdx()])) return 'img/avatar-' + presetIdx() + '.png';
    var k = JSON.stringify(lk);
    if (!cache.has(k)) { try { cache.set(k, root.SKP.portrait({ s3: lk, w: 280, h: 300, dpr: 1, ground: false })); } catch (e) { return 'img/avatar-' + presetIdx() + '.png'; } }
    return cache.get(k);
  }
  var hero = function () { return '<div class="portrait"><img class="hero" src="' + portraitURL() + '" alt="' + esc(P.preset) + ' appearance preview"></div>'; };
  function sheetState() {
    var SS = root.SnapSheet, pr = SS && SS.PRESETS.filter(function (p) { return p.name === P.preset; })[0];
    return { name: P.name || 'Newcomer', temperament: P.temper, quirks: P.quirks, voice: P.voice, preset: pr ? pr.id : '', look: look(), door: D.state.door || (P.door && P.door.door) || '' };
  }
  // ------------------------------------------------------------------ the premint personas (one per battle option, fixed at mint)
  // premint/meta/options.json: option id -> {file, digest, name, temper, quirks, voice, look, ...}. A claim names that digest,
  // and while the claimed persona is unchanged the sheet sent and downloaded is the premint file itself, byte for byte.
  var PM = { opts: null, error: '', loading: false };
  // after a failed read it is tried again only when the player asks for it (Use this preset), never on every render
  function loadPremint(retry) {
    if (PM.opts) return Promise.resolve(); if (PM.loading) return PM.loading; if (PM.error && !retry) return Promise.resolve();
    PM.loading = root.fetch('premint/meta/options.json', { cache: 'no-store' }).then(function (r) { if (!r.ok) throw new Error('answered ' + r.status); return r.json(); })
      .then(function (j) { PM.opts = j; PM.error = ''; }, function (e) { PM.error = 'The premint personas could not be read (' + e.message + ').'; })
      .then(function () { PM.loading = false; if (V.mode === 'flow' && /^(presets|personality)$/.test(V.step)) render(); });
    return PM.loading;
  }
  function premintFor(id) { return PM.opts && PM.opts[id] || null; }
  function short(dg) { return dg ? dg.slice(0, 12) + '…' + dg.slice(-4) : ''; }
  function sameList(a, b) { return JSON.stringify((a || []).slice().sort()) === JSON.stringify((b || []).slice().sort()); }
  function claimIntact() {
    var c = P.claim; if (!c || !c.sheet) return false;
    return P.preset === c.preset && P.name === c.name && P.temper === c.temper && sameList(P.quirks, c.quirks) && (P.voice || '') === (c.voice || '') && JSON.stringify(look()) === JSON.stringify(c.look);
  }
  function adoptClaim() { var c = P.claim; P.name = c.name; P.temper = c.temper; P.quirks = (c.quirks || []).slice(); P.voice = c.voice || ''; P.look = Object.assign({}, c.look); P.lookEdited = false; save(); }
  // the battle option already claimed: going on keeps every choice made since (Back never wipes them; item 25).
  // "Restore <name>" on the Personality step brings the premint persona back when the player wants it.
  function claimedHere() { return !!(P.claim && P.claim.digest && P.claim.preset === P.preset); }
  async function claimOption() {
    if (claimedHere()) return go('personality');
    await loadPremint(true);   // pressed before the premint personas arrived (or after a failed read): wait for them rather than fail
    var id = presetId(), e = premintFor(id), SS = root.SnapSheet;
    if (!e) return say(PM.error ? PM.error + ' Claiming is off until they can; Build a fighter still works.' : 'The premint personas are still loading. Try again in a moment.', true);
    try {
      var sh = await root.fetch('premint/' + e.file, { cache: 'no-store' }).then(function (r) { if (!r.ok) throw new Error(e.file + ' answered ' + r.status); return r.json(); });
      var lk = await root.fetch('premint/' + e.look, { cache: 'no-store' }).then(function (r) { if (!r.ok) throw new Error(e.look + ' answered ' + r.status); return r.json(); });
      var dg = await SS.digest(sh);
      if (dg !== e.digest) return say('The ' + e.option + ' persona does not match its published digest, so it cannot be claimed. Pick another option or build a fighter.', true);
      P.claim = { preset: P.preset, option: id, dev: true, at: Date.now(), digest: dg, file: e.file, name: sh.game.name, temper: e.temper, quirks: e.quirks || [], voice: e.voice || '', look: lk.look, sheet: sh };
      adoptClaim(); go('personality');
    } catch (err) { say('The ' + (e.option || 'premint') + ' persona could not be read (' + err.message + '). Try again, or build a fighter.', true); }
  }
  function buildSheet() {
    var SS = root.SnapSheet; if (!SS) return null;
    if (claimIntact()) return JSON.parse(JSON.stringify(P.claim.sheet));   // the claimed premint persona, exactly as minted
    try { return SS.build(sheetState()); } catch (e) { return { error: e.message }; }
  }

  // ------------------------------------------------------------------ pieces
  function stepsBar() {
    var cur = V.step, order = [['wallet', 'Wallet'], ['presets', 'Fighter'], ['personality', 'Personality'], ['ai', 'AI'], ['agree', 'Agree']];
    return '<div class="steps">' + order.map(function (a) {
      var on = cur === a[0] || (a[0] === 'presets' && /^(build|claimed|presets-empty)$/.test(cur)) || (a[0] === 'ai' && cur === 'doors');
      return '<span class="' + (on ? 'on' : '') + '" ' + (on ? 'aria-label="' + a[1] + '"' : '') + '>' + a[1] + '</span>';
    }).join('') + '</div>';
  }
  function presetGrid() {
    return '<div class="options presets">' + PRESETS.map(function (name, i) {
      return btn('<img src="img/avatar-' + i + '.png" alt="' + name + ' appearance"><span>' + name + '</span><small>' + supplyText(i) + '</small>', 'preset:' + name, '', 'aria-pressed="' + (P.preset === name) + '" data-copies="' + (root.SNAPIN_SUPPLY ? root.SNAPIN_SUPPLY[i] : '') + '"');
    }).join('') + '</div>';
  }
  function supplyText(i) { var s = root.SNAPIN_SUPPLY; if (CHAIN) return chainSupply(); if (!s) return 'DEV · free'; return s[i] > 0 ? s[i] + ' / 10 left' : 'All claimed'; }   // the onchain count arrives with the premint
  // the gear the arena actually equips: a battle option is a whole kit (presets.py); there is no per-slot pick in the room
  function titleCase(w) { return String(w || '').split('_').map(function (x) { return x.charAt(0).toUpperCase() + x.slice(1); }).join(' '); }
  function kitCard() {
    var SS = root.SnapSheet, pr = SS && SS.PRESETS.filter(function (x) { return x.name === P.preset; })[0];
    if (!pr) return '';
    var mv = titleCase(pr.weapon);
    return receipt('<div class="eyebrow">' + esc(pr.name) + ' · its kit</div>' + U.line('Weapon move', esc(mv)) + '<div class="sub">' + esc(ATTACK[mv] || '') + '</div>' + U.line('Signature', esc(titleCase(pr.signature))) +
      U.line('Head, body', 'starter cap and tee') + '<div class="sub">The battle option is the whole kit. Items you win land in your bag.</div>');
  }
  function inventory() { return '<fieldset class="slot-group"><legend>Battle option</legend>' + presetGrid() + '</fieldset>' + kitCard(); }
  function appearance() {
    var S3 = root.S3, c = S3.SETS.c, labels = S3.PART, out = '';
    S3.SLOTS.forEach(function (k) {
      var opts = c[k].map(function (v) { return [v, labels[k].opts[v] || v]; });
      var cur = look()[k];
      out += '<fieldset class="slot-group"><legend>' + labels[k].label + '</legend><div class="options' + (k === 'body' || k === 'hairCol' ? ' swatches' : '') + '">' + opts.map(function (o) {
        return btn((k === 'body' || k === 'hairCol' ? '<i class="dot" style="background:' + esc(root.SKA.C(o[0])) + '"></i>' : '') + esc(o[1]), 'look:' + k + ':' + o[0], '', 'aria-pressed="' + (cur === o[0]) + '"');
      }).join('') + '</div></fieldset>';
    });
    return out;
  }
  function claimCard() {
    var c = P.claim; if (!c || !c.digest) return '';
    if (claimIntact()) return receipt('<div class="eyebrow">Claimed premint persona</div><h3>' + esc(c.name) + '</h3>' + U.line('Persona digest', '<span class="acct" title="' + esc(c.digest) + '">' + esc(short(c.digest)) + '</span>') +
      '<div class="sub">Its copies are minted with this persona. Change anything below and it becomes your own persona instead (a paid mint once minting is live).</div>');
    return receipt('<div class="eyebrow">Edited after the claim</div><div class="sub" role="status">This is your own persona now, not ' + esc(c.name) + '’s premint copy.</div>') + btn('Restore ' + esc(c.name), 'claim-restore', 'textlink');
  }
  function personality(file) {
    var SS = root.SnapSheet; if (!SS) return receipt('<h3>Personality</h3><div class="sub">The sheet module did not load. Reload the page.</div>');
    var t = SS.TEMPERAMENTS.filter(function (x) { return x.id === P.temper; })[0] || SS.TEMPERAMENTS[0], g = SS.guard(P.name || 'Newcomer');
    return '<fieldset class="slot-group"><legend>Temperament</legend><div class="row temper">' + SS.TEMPERAMENTS.map(function (x) { return btn(esc(x.name), 'temper:' + x.id, '', 'aria-pressed="' + (P.temper === x.id) + '"'); }).join('') + '</div></fieldset>' +
      '<div class="sub">' + esc(t.line) + '</div>' +
      '<fieldset class="slot-group"><legend>Quirks</legend><div class="row quirks">' + SS.QUIRKS.map(function (x) { return btn(esc(x.label), 'quirk:' + x.id, '', 'aria-pressed="' + (P.quirks.indexOf(x.id) >= 0) + '"'); }).join('') + '</div></fieldset>' +
      '<label class="field" for="name">Name</label><input id="name" value="' + esc(P.name) + '" maxlength="32" placeholder="Pip Shoals" autocomplete="off">' + (g.ok ? '' : '<div class="sub" role="alert">' + esc(g.reason) + '</div>') +
      '<label class="field" for="personality">Voice</label><textarea id="personality" maxlength="500" placeholder="Talks in charts. Swings first. Calls every KO a breakout.">' + esc(P.voice) + '</textarea>' +
      receipt('<div class="eyebrow">Voice preview · keyed lines</div>' + t.sample.slice(0, 2).map(function (l) { return '<h3>“' + esc(l) + '”</h3>'; }).join(''));
  }
  function agreement() {
    var t = V.terms, terms;
    if (t && t.error) terms = '<div class="sub" role="alert">' + esc(t.error) + '</div>' + btn('Try again', 'terms-reload', 'secondary');
    else if (!t) terms = '<div class="sub" role="status">Reading the arena rules…</div>';
    else terms = '<div class="eyebrow">Arena rules · version ' + esc(t.version) + '</div>' + U.line('Orders', 'one every ' + U.seconds(t.input_interval_ms)) + U.line('Rounds', U.seconds(t.segment_ms) + ', replayable');
    return receipt(terms) + receipt('<div class="checks"><label><input type="checkbox" id="agree-ai"' + tick('agree-ai') + '>' + aiTickText() + '</label><label><input type="checkbox" id="agree-public"' + tick('agree-public') + '>Persona and banter: public</label><label><input type="checkbox" id="agree-gear"' + tick('agree-gear') + '>Gear drops: a KO can knock one worn item loose; whoever grabs it keeps it (the house never takes yours); ungrabbed for 30 s, it is gone</label></div>') +
      chips([CHAIN ? NETWORK + ' · your wallet owns it' : 'testnet · DEV arena', 'AI · your choice']) + btn('Snap in', 'agree', 'main-action');
  }
  function shortAcct(a) { a = String(a || ''); return a.length > 28 ? a.slice(0, 12) + '…' + a.slice(-8) : a; }
  // the ticks are kept only while the page is open (a re-render keeps them; coming back after a change asks again)
  function tick(id) { return V.ticks && V.ticks[id] ? ' checked' : ''; }
  function brainOn() { return !!(root.SnapBrain && root.SnapBrain.on); }
  function capSet() { var c = Number(U.store.get('trenchie.snapin.cap')); return c > 0 ? c : 0; }
  function aiTickText() {
    if (!brainOn()) return 'Fights on the arena’s own tactics for now: your AI is saved but not wired in yet';
    if (!P.door || P.door.route === 'plan') return 'Your own agent drives it through the link you made';
    var c = capSet(); return c ? 'Uses the AI you picked, on your key, up to $' + c.toFixed(2) + ' an hour' : 'Fights on the arena’s own tactics until you set an hourly cap on the AI step';
  }
  function yoctoNear(y) { var s = String(y || '0').replace(/^0+/, '') || '0'; while (s.length < 25) s = '0' + s; var w = s.slice(0, -24).replace(/^0+/, '') || '0', f = s.slice(-24).replace(/0+$/, ''); return f ? w + '.' + f : w; }
  function chainSupply() { var o = P.wallet && P.wallet.chain && P.wallet.chain.offer; if (!o) return 'sign in to see'; return o.kind === 'claim' ? 'free claim · ' + o.held + ' left' : 'paid mint · ' + yoctoNear(o.cost_yocto) + ' NEAR'; }
  function walletName(id) { if (id === 'dev-throwaway') return 'Throwaway account (DEV)'; return P.wallet && P.wallet.id === id && P.wallet.name ? P.wallet.name : 'your wallet'; }
  function loadTerms() {
    if (!root.SnapRoom) { V.terms = { error: 'The arena client did not load. Reload the page.' }; return render(); }
    V.terms = null; render();
    root.SnapRoom.terms().then(function (t) { V.terms = t; if (V.step === 'agree') render(); }, function (e) { V.terms = { error: e.message }; if (V.step === 'agree') render(); });
  }

  // ------------------------------------------------------------------ the last step: the fighter goes into the DEV arena
  var JOIN_STEPS = [['key', 'Key made in this browser'], ['identity', 'Registered with the DEV arena'], ['join', 'Seat in the ring'], ['terms', 'Arena rules agreed'], ['control', 'Controls taken']];
  function claimLine() {
    // this battle option already claimed (the player came Back): show the player's own trenchie, never the preset's default
    if (claimedHere()) {
      var SS = root.SnapSheet, t = SS && SS.TEMPERAMENTS.filter(function (x) { return x.id === P.temper; })[0], c = P.claim;
      return receipt('<div class="eyebrow">Your Trenchie · ' + esc(P.preset) + '</div><h3>' + esc(P.name || c.name) + '</h3>' + U.line('Temperament', esc(t ? t.name : P.temper)) +
        (claimIntact() ? U.line('Persona digest', '<span class="acct" title="' + esc(c.digest) + '">' + esc(short(c.digest)) + '</span>') : '<div class="sub">' + esc('Your own edits, made from ' + c.name + '’s premint persona.') + '</div>'));
    }
    loadPremint();
    var e = premintFor(presetId());
    if (PM.error) return '<div class="sub" role="alert">' + esc(PM.error) + ' Claiming is off until they can; Build a fighter still works.</div>';
    if (!e) return '<div class="sub" role="status">Reading the premint personas…</div>';
    return receipt('<div class="eyebrow">' + esc(e.option) + ' comes as</div><h3>' + esc(e.name) + '</h3>' + U.line('Temperament', esc(e.temperament)) + U.line('Persona digest', '<span class="acct" title="' + esc(e.digest) + '">' + esc(short(e.digest)) + '</span>'));
  }
  function presetId() { var SS = root.SnapSheet, pr = SS && SS.PRESETS.filter(function (x) { return x.name === P.preset; })[0]; return pr ? pr.id : ''; }
  function elapsed(ms) { var sec = Math.max(0, Math.round(ms / 1000)); return (sec >= 60 ? Math.floor(sec / 60) + ' min ' : '') + (sec % 60) + ' s'; }
  // the player's AI (brain.js, another lane's file): its own status chip when it is loaded; until then, say plainly what drives the fighter
  var brainState = null;
  function brainLine() { return brainState && brainState.chip ? brainState.chip : 'Your Trenchie fights on the arena’s own tactics: orders from your AI are not wired in yet.'; }
  function ringView() {
    var st = root.SnapRoom ? root.SnapRoom.status() : { phase: 'error', message: 'The arena client did not load. Reload the page.' }, f = st.fighter, name = P.name || 'Newcomer';
    if (V.checking) return { head: 'Checking', content: receipt('<div class="sub" role="status">Checking that ' + esc(draftName()) + ' is still in the arena…</div>') };
    if (st.phase === 'joining') {
      var at = JOIN_STEPS.map(function (x) { return x[0]; }).indexOf(st.step);
      return { head: 'Snapping in', content: receipt('<div class="eyebrow">' + esc(name) + ' · ' + esc(P.preset) + '</div><ol class="join-steps">' + JOIN_STEPS.map(function (x, i) { if (CHAIN && x[0] === 'identity') x = ['identity', 'Registered with the arena (owner read on ' + NETWORK + ')'];
        return '<li class="' + (i < at ? 'done' : i === at ? 'now' : '') + '">' + (i < at ? '✓ ' : i === at ? '… ' : '') + esc(x[1]) + '</li>'; }).join('') + '</ol><div class="sub" role="status">' + esc(st.message) + '</div>') };
    }
    if (st.phase === 'in' && f) {
      var lp = f.lastPick, took = P.timing && P.timing.wallet && P.timing.ring ? elapsed(P.timing.ring - P.timing.wallet) : '';
      return { head: 'In the arena', content: '<div class="split ring-split"><div>' + hero() + receipt('<div class="eyebrow">' + (CHAIN ? 'Arena' : 'DEV arena') + ' · life ' + esc(f.lives || 1) + '</div><h2>' + (CHAIN ? '' : 'DEV ') + esc(f.name) + '</h2><div class="notice" style="margin-top:12px">Fight. Fall. Respawn.</div>' +
        (CHAIN && P.wallet && P.wallet.chain && P.wallet.chain.token ? U.line('Trenchie', esc(P.wallet.chain.token) + ' · owned by ' + esc(shortAcct(P.wallet.accountId)) + ' on ' + esc(NETWORK)) + (P.wallet.chain.tx ? U.line('Mint', esc(String(P.wallet.chain.tx).slice(0, 10)) + '…') : '') : '') +
        U.line('Battle option', esc(P.preset)) + U.line('Persona', claimIntact() ? esc(P.claim.name) + ' (premint, ' + esc(P.claim.digest.slice(0, 8)) + '…)' : 'your own') + U.line('Prediction for this life', esc(U.pickLine(lp))) +
        U.line('AI', esc(P.door ? P.door.identity + (brainOn() ? '' : ' (saved, not driving yet)') : 'none yet')) + (took ? U.line('Wallet to the ring', esc(took)) : '') +
        '<div class="sub" id="brain-chip">' + esc(brainLine()) + '</div><div class="sub">' + (st.keyPersisted === false ? 'This browser keeps your Trenchie only on this page (it cannot store the key): closing this page sends your Trenchie home.' : 'Keep this page or the arena page open: closing every tab sends your Trenchie home.') + '</div>' +
        (st.message ? '<div class="sub" role="status">' + esc(st.message) + '</div>' : '')) +
        '</div><div>' + (root.SnapChat ? receipt(root.SnapChat.html({ name: (CHAIN ? '' : 'DEV ') + f.name, card: true })) : '') + '</div></div>' + (st.keyPersisted === false ? '' : btn('Watch your Trenchie', 'watch-mine', 'main-action')) + '<div class="row">' + btn('Change next life', 'corner', 'textlink') + btn('Leave the arena', 'leave', 'textlink') + '</div>' + newButton() };
    }
    if (st.phase === 'elsewhere') return { head: 'In the arena', content: receipt('<div class="sub" role="status">' + esc(st.message) + '</div>') + btn('Watch the arena', 'step:watch', 'main-action') };
    if (st.phase === 'error') {
      var back = (/name/i.test(st.message) && STEP_BACK.personality) || (/battle option/i.test(st.message) && STEP_BACK.presets) || STEP_BACK.agree;
      // a choice to change (the name, the battle option) leads; a passing fault (the arena busy or away) leads with Try again
      var fix = back !== STEP_BACK.agree;
      return { head: 'Not in yet', content: receipt('<h2>' + esc(name) + ' is not in the ring</h2><div class="sub" role="alert">' + esc(st.message) + '</div>') +
        (fix ? btn(back[1], 'step:' + back[0], 'main-action') : btn('Try again', 'join', 'main-action')) +
        '<div class="row">' + (fix ? btn('Try again', 'join', 'textlink') : btn(back[1], 'step:' + back[0], 'textlink')) + btn('Keep watching', 'step:watch', 'textlink') + '</div>' + newButton() };
    }
    if (st.phase === 'offline') return { head: 'Reconnecting', content: receipt('<h2>' + esc(name) + ' is waiting</h2><div class="sub" role="alert">' + esc(st.message) + '</div><div class="sub">Your Trenchie keeps its seat while its lease lasts (about 30 s).</div>') +
        btn('Try again', 'resume', 'main-action') + btn('Keep watching', 'step:watch', 'textlink') + newButton() };
    if (st.phase === 'leaving') return { head: 'Leaving', content: receipt('<h2>' + esc(name) + '</h2><div class="sub" role="status">' + esc(st.message) + '</div>') };
    if (P.ended) return { head: 'Seat ended', content: hero() + receipt('<h2>' + esc('DEV ' + P.ended.name + ' is out of the arena') + '</h2><div class="sub" role="status">' + esc('Its seat ended: ' + P.ended.why + '. Your Trenchie is kept in this browser: its name, look, voice and battle option.') + '</div>') +
        btn('Snap ' + esc(P.ended.name) + ' back in', 'rejoin', 'main-action') + btn('Keep watching', 'step:watch', 'textlink') + newButton() };
    if (st.phase === 'ended') return { head: 'Swam home', content: receipt('<h2>' + esc(name) + ' left the ring</h2><div class="sub" role="status">' + esc(st.message) + '</div>') +
        btn('Snap in again', 'join', 'main-action') + btn('Keep watching', 'step:watch', 'textlink') + newButton() };
    return { head: P.left ? 'Swam home' : 'Ready', content: hero() + receipt('<h2>' + esc(name) + (P.left ? ' swam home' : '') + '</h2><div class="sub">' + (P.left ? 'Your Trenchie left the ring. ' : '') + 'Your choices are saved in this browser. Snap in to put your Trenchie in the ' + (CHAIN ? 'arena.' : 'DEV arena.') + '</div>') +
      btn('Snap in', 'join', 'main-action') + btn('Back to the arena rules', 'step:agree', 'textlink') + (hasDraft() ? newButton() : '') };
  }
  var joining = false;
  async function startJoin() {
    if (joining || !root.SnapRoom) return; joining = true;
    // the player chose: snap this trenchie back in (a failure shows its own reason). Its own held round result may be read
    // only when the trenchie snapping in is the one whose seat ended (another player's result is never read here)
    // and only within the host's grace for an unread result (180 s from its round's claim; 210 s from when this page saw the
    // seat end): a trenchie that lapsed long ago does not own whatever round is held now
    var ownHeld = !!(P.ended && String(P.ended.name || '').toLowerCase() === String(P.name || 'Newcomer').toLowerCase() && P.ended.at && Date.now() - P.ended.at < 210000);
    if (P.ended) { P.ended = null; save(); }
    var sh = buildSheet(), look = root.SnapSheet && root.SnapSheet.lookFile ? root.SnapSheet.lookFile(sheetState()) : null;
    if (sh && !sh.error) { P.sheet = sh; save(); }   // the player's AI reads it from here on either page (prompt prefix)
    var chain = null;
    if (CHAIN) {   // chain mode: the fighter joins only as a trenchie this wallet owns on the identity NFT
      var ch = P.wallet && P.wallet.chain;
      if (!ch) { joining = false; say('Sign in with your wallet first (step 1).', true); return; }
      try {
        say(ch.owned && ch.owned.length ? 'Checking ' + ch.owned[0].token_id + ' is still yours…' : ch.offer && ch.offer.kind === 'claim' && claimIntact() ? 'Claiming your free Trenchie on ' + NETWORK + '…' : 'Approve the paid mint in your wallet (' + yoctoNear(ch.offer && ch.offer.cost_yocto) + ' NEAR)…');
        if (!sh || sh.error) throw new Error((sh && sh.error) || 'the persona sheet could not be built');
        var t = await root.SnapIdentity.getTrenchie({ preset: presetId(), sheet: sh, claim: claimIntact() });
        ch.token = t.token_id; ch.tx = t.tx || null; ch.owned = [{ token_id: t.token_id }]; save();
        var spk = await root.SnapRoom.sessionKey();   // the room's session key, made now so the ticket names it
        chain = { ticket: await root.SnapIdentity.ticket(t.token_id, { session_public_key: spk, name: P.name || 'Newcomer', preset: presetId() }),
                  nft_token_id: t.token_id, network: NETWORK, session_public_key: spk };
      } catch (e) { joining = false; say('No Trenchie yet: ' + e.message, true); render(); return; }
    }
    try {
      // the trenchie a new one replaced may still be swimming home: the join waits for it (kept in the draft across a reload)
      var swim = P.swimming && Date.now() - P.swimming.at < 60000 ? P.swimming.id : null;
      await root.SnapRoom.join({ chain: chain, waitFor: swim, ownHeldResult: ownHeld, name: P.name || 'Newcomer', preset: presetId(), sheet: sh && !sh.error ? sh : null, look: look, termsVersion: P.termsVersion || '1',
        // no prediction by default: nothing picks a level for the player (the record files it as none); the player or their
        // AI picks one later (rules integer-16: one level, 1+ to 4+)
        order: { preset: presetId(), prediction: false },
        compute: { harness: 'browser', model: P.door && P.door.door ? String(P.door.door).slice(0, 96) : 'none-yet', source: 'owner', effort: 'standard' } });
      if (P.timing && P.timing.wallet && !P.timing.ring) { P.timing.ring = Date.now(); save(); }   // measured once: the first brawl after connecting
    } catch (e) { /* the status carries the message; the view shows it with a way back */ }
    joining = false; render();
  }
  function aiChip() { return P.wallet ? 'Wallet · ' + esc(P.wallet.network || NETWORK) + ' connected' + (P.wallet.accountId ? ' · ' + esc(shortAcct(P.wallet.accountId)) : '') : ''; }

  // ------------------------------------------------------------------ the corner (F22): the bench card at respawn, from the room's own data
  // /dev/corner (public, same origin): state, respawn time, last life with its prediction, owned items on the floor with their
  // timers, the locked pick for the next life; what the arena does not track it says so, and so does this card.
  var C = { data: null, error: '', now: 0, at: 0, timer: null, names: {} };
  function openCorner(replace) {
    V.mode = 'workshop'; V.tab = 'respawn'; V.closed = false; V.msg = '';
    try { var u = new URL(root.location.href); u.searchParams.set('mode', 'workshop'); u.searchParams.set('tab', 'respawn'); u.searchParams.delete('step'); root.history[replace ? 'replaceState' : 'pushState']({ mode: 'workshop', tab: 'respawn' }, '', u.pathname + u.search); } catch (e) { /* no history */ }
    render(); startCorner();
  }
  function presetName(id) { var SS = root.SnapSheet, pr = SS && SS.PRESETS.filter(function (x) { return x.id === id; })[0]; return pr ? pr.name : (id || ''); }
  function who(id) { if (!id) return ''; if (/^dev-/.test(id)) return 'DEV ' + id.slice(4).charAt(0).toUpperCase() + id.slice(5); return id.split('-').map(function (w) { return w.charAt(0).toUpperCase() + w.slice(1); }).join(' '); }
  // an item's display name from the item records the art module already holds (no request; an unknown id shows as itself)
  function itemName(id) { var I = root.ITEMS3 && root.ITEMS3[id]; return I && I.name ? I.name : String(id || ''); }
  function roomNow() { return C.now + Math.round(root.performance.now() - C.at); }
  function left(ms) { var s = Math.max(0, Math.ceil((ms - roomNow()) / 1000)); return Math.floor(s / 60) + ':' + ('0' + (s % 60)).slice(-2); }
  function cornerOpen() { return V.mode === 'workshop' && V.tab === 'respawn' && !V.closed; }
  function myFighter() { var st = root.SnapRoom && root.SnapRoom.status(); return (st && st.fighter && st.fighter.id) || ((root.SnapRoom && root.SnapRoom.saved()) || {}).id || ''; }
  async function pollCorner() {
    var id = myFighter();
    if (!id) { C.data = null; C.error = ''; return; }
    try {
      var r = await root.fetch('/dev/corner?fighter=' + encodeURIComponent(id), { cache: 'no-store' }), j = null;
      try { j = await r.json(); } catch (e) { j = null; }
      if (!r.ok || !j || j.error) { C.error = r.status === 502 || r.status === 404 ? 'Cannot reach the arena, so the corner has no fresh data. It retries every few seconds.' : 'The arena did not give the corner: ' + ((j && j.error) || r.status) + '.'; }
      else { var same = C.data && JSON.stringify(C.data) === JSON.stringify(j) && !C.error; C.data = j; C.error = ''; C.now = Number(r.headers.get('X-Dev-Now')) || C.now; C.at = root.performance.now(); if (same) return; }
    } catch (e) { if (C.error) return; C.error = 'Cannot reach the arena, so the corner has no fresh data. It retries every few seconds.'; }
    if (cornerOpen()) render();   // only when the room's answer changed: the countdowns tick in place, so typing is never interrupted
  }
  function cornerTick() {   // countdowns move every second without a re-render (focus stays put)
    [].forEach.call(app.querySelectorAll('[data-until]'), function (el) { el.textContent = left(Number(el.dataset.until)); });
  }
  // the corner reads the room every second while it is open (one small GET; a KO or a respawn shows within a second)
  function startCorner() {
    if (C.timer) return; pollCorner(); var busy = false;
    C.timer = root.setInterval(function () {
      if (!cornerOpen()) { root.clearInterval(C.timer); C.timer = null; return; }
      cornerTick(); if (!busy) { busy = true; pollCorner().then(function () { busy = false; }, function () { busy = false; }); }
    }, 1000);
  }
  function corner() {
    var st = root.SnapRoom ? root.SnapRoom.status() : {}, f = st.fighter, d = C.data, html = '';
    if (!myFighter()) return receipt('<h2>No Trenchie in the arena</h2><div class="sub">The corner shows your last life and sets up your next one once your Trenchie is in the ring.</div>') + btn('Snap in', 'mode:flow', 'main-action');
    // ---- the last life and the floor
    if (C.error && !d) html += receipt('<div class="sub" role="alert">' + esc(C.error) + '</div>');
    else if (!d) html += receipt('<div class="sub" role="status">Reading your corner from the arena…</div>');
    else {
      var L = d.last_life, state = d.state === 'ring' ? 'In the ring' : d.respawn_at_ms ? 'Respawn in <b data-until="' + esc(d.respawn_at_ms) + '">' + left(Number(d.respawn_at_ms)) + '</b>' : 'On the bench';
      var lifeNo = L && /:life:(\d+)$/.test(L.life_id) ? Number(L.life_id.match(/:life:(\d+)$/)[1]) + 1 : null, sp = L && L.prediction && L.prediction.spread_bps;
      html += receipt('<div class="eyebrow">' + esc(who(d.fighter_id)) + ' · ' + state + '</div>' +
        (L ? '<h2>Last life' + (lifeNo ? ' · life ' + lifeNo : '') + '</h2>' + U.line('KOs', esc(L.ko_count)) + U.line('Ended', L.ended === 'ko' ? 'KO’d' + (L.ended_by ? ' by ' + esc(who(L.ended_by)) : '') : L.ended === 'leave' ? 'swam home' : 'still going') +
            (sp ? U.line('You predicted', esc([sp.one, sp.two, sp.three, sp.four_plus].map(function (b, k) { return ['1', '2', '3', '4+'][k] + ': ' + (b / 100) + '%'; }).join(' · '))) + U.line('Zero KOs', esc((L.prediction.zero_bps || 0) / 100) + '%') : U.line('You predicted', 'nothing filed'))
          : '<h2>First life</h2><div class="sub">No life has ended yet.</div>') +
        '<h3>On the floor</h3>' + ((d.floor || []).length ? d.floor.map(function (x) { return U.line(esc(itemName(x.item_id)), 'leaves the floor in <b data-until="' + esc(x.returns_at_ms) + '">' + left(Number(x.returns_at_ms)) + '</b>'); }).join('') : '<div class="sub">None of your items is on the floor.</div>') +
        '<h3>Taken last life</h3><div class="sub">' + (d.untracked && d.untracked.taken ? 'Not tracked by the arena yet.' : (d.taken || []).map(function (x) { return esc(itemName(x.item_id)); }).join(', ') || 'Nothing.') + '</div>' +
        '<h3>Pending</h3>' + ((d.pending || []).length ? d.pending.map(function (x) { return U.line(x.kind === 'respawn_pick' ? 'Next life’s pick' : esc(x.kind), esc(x.kind === 'respawn_pick' ? 'locked' + (f && f.lastPick && f.lastPick.order ? ': ' + presetName(f.lastPick.order.preset) : '') : (x.text || ''))); }).join('') : '<div class="sub">Nothing waiting.</div>') +
        '<div class="sub">Item returns to your plot: not tracked by the arena yet.</div>' + (C.error ? '<div class="sub" role="alert">' + esc(C.error) + '</div>' : ''));
    }
    // ---- the next life: battle option and prediction, sent signed when the room announces the life
    var cur = (st.fighter && st.fighter.preset) || presetId(), total = P.spread.reduce(function (s2, n) { return s2 + Number(n || 0); }, 0);
    var opts = (root.SnapSheet ? root.SnapSheet.PRESETS : []).map(function (x) { return btn(esc(x.name), 'next-preset:' + x.id, '', 'aria-pressed="' + (V.nextPreset ? V.nextPreset === x.id : cur === x.id) + '"'); }).join('');
    html += '<div class="split"><div>' + receipt('<div class="eyebrow">Next life</div><h3>Battle option</h3><div class="sub">Your bag is empty in the DEV arena, so the menu is the five battle options.</div>') + '<div class="options presets-next">' + opts + '</div></div><div>' +
      receipt('<h3>KO prediction</h3><div class="sub">If you score at least one KO, how many?</div><div class="prediction">' + ['1', '2', '3', '4+'].map(function (n, k) { return '<label>' + n + '<input type="number" inputmode="numeric" data-spread="' + k + '" aria-label="' + n + ' KOs, percent" min="0" max="100" value="' + esc(P.spread[k]) + '"></label>'; }).join('') + '</div><div class="sub" style="margin-top:10px" id="spread-total" aria-live="polite">Spread totals ' + total + '%' + (total === 100 ? '' : ' (needs 100%)') + '</div>' +
        '<label class="field" for="zero-ko">Chance of zero KOs (%)</label><input id="zero-ko" type="number" inputmode="numeric" min="0" max="100" value="' + esc(P.zeroKo) + '"><div class="sub">Logged and scored; no NEAR can be added to it.</div>') + '</div></div>' +
      receipt('<h3>Add testnet NEAR, move, sale lock</h3><div class="row">' + btn('Add 0.01 testnet NEAR to the prediction', 'noop', '', 'disabled aria-disabled="true"') + btn('Move item', 'noop', '', 'disabled aria-disabled="true"') + btn('Sale lock', 'noop', '', 'disabled aria-disabled="true"') + '</div><div class="sub">These need the onchain market, which is not deployed yet. They are off in the DEV arena.</div>') +
      btn('Ready next life', 'ready', 'main-action') + '<div class="status" id="locked" aria-live="polite">' + esc(V.pickMsg || '') + '</div>' +
      '<div class="row">' + btn('Back to your Trenchie', 'back-ring', 'textlink') + btn('Watch your Trenchie', 'watch-mine', 'textlink') + '</div>';
    return html;
  }

  // ------------------------------------------------------------------ the Persona tab: the creator beside its file (F73)
  function personaFile() {
    var sh = buildSheet(), SS = root.SnapSheet, fails = [];
    if (sh && !sh.error && SS && SS.validate) fails = SS.validate(sh);
    var file = '';
    if (!sh) file = receipt('<h3>Persona file</h3><div class="sub">The sheet module did not load.</div>');
    else if (sh.error) file = receipt('<h3>Persona file</h3><div class="sub" role="alert">' + esc(sh.error) + '</div>');
    else {
      var gm = sh.game || {};
      file = receipt('<div class="eyebrow">Persona file · the same format the house uses</div><h3>' + esc(gm.name || P.name || 'Newcomer') + '</h3>' +
        U.line('file', esc((sh.identity && sh.identity.role || '') + '.json')) + U.line('fight', esc(gm.fight_style || '')) + U.line('temperament', esc(gm.temperament || '')) +
        U.line('format', 'ten core elements + game v2') + U.line('memory', 'none (the arena keeps none)') + U.line('AI', esc((sh.model_routing && sh.model_routing.compute_home && sh.model_routing.compute_home.name) || 'your pick') + ' · not in the file’s digest') +
        '<pre class="sheet-pre" aria-label="Sheet JSON">' + esc(JSON.stringify(sh, null, 1).slice(0, 1400)) + (JSON.stringify(sh).length > 1400 ? '\n…' : '') + '</pre>' +
        (fails.length ? '<div class="sub" role="alert">Sheet check: ' + esc(fails.join(' · ')) + '</div>' : '<div class="sub" role="status">Sheet check: passes</div>') +
        '<div class="row">' + btn('Download sheet', 'sheet-download', 'secondary') + btn('Copy sheet', 'sheet-copy', 'secondary') + btn('Download look', 'look-download', 'secondary') + '</div>' +
        '<div class="sub">The look file travels beside the sheet; the persona format has no look field.</div>');
    }
    return '<div class="split"><div>' + hero() + personality(true) + '</div><div>' + file + '</div></div>';
  }
  // ------------------------------------------------------------------ the card (F28) with the boldness gauge (W23), from real data
  // Record and gauge: exact per-persona summary of the whole predictions log; the public row window may be tailed.
  // A line's `score` is how far the spread sat from what happened (ranked probability score, millionths, 0 = perfect) and
  // `base_score` the published base rate on the same life. The needle (INFERRED from W23's words): 0.5 + skill / 2, with
  // skill = (sum base - sum score) / sum base, so the base rate sits mid-dial, beating it leans careful, doing worse leans
  // reckless; no needle under quote.py's MIN_LIVES (10 scored lives). Bag and serials: what the fighter wears now
  // (/room/observe). Scars are read from item KOs, which the DEV arena does not keep: the card says so.
  var MIN_LIVES = 10, CARD = { rows: null, summary: null, error: '', equipped: null, loading: false, gen: 0 };
  function mine(row, id) { return row && (row.persona === id || String(row.life || '').indexOf('/' + id + ':life:') >= 0); }
  async function loadCard() {
    var id = myFighter(); if (!id) return; var gen = ++CARD.gen; CARD.loading = true;   // a newer load always wins over one still in flight
    try {
      var r = await root.fetch('/house/predictions.jsonl', { cache: 'no-store' });
      if (!r.ok) throw new Error(r.status === 404 ? 'this arena serves no predictions log' : 'the predictions log answered ' + r.status);
      var rows = (await r.text()).split('\n').filter(Boolean).map(function (l) { try { return JSON.parse(l); } catch (e) { return null; } }).filter(function (x) { return mine(x, id); });
      var summary = null;
      if (r.headers.get('X-Log-Window') === 'tail') {
        var totals = await root.fetch('/house/predictions/summary?persona=' + encodeURIComponent(id), { cache: 'no-store' });
        if (!totals.ok) throw new Error('the complete prediction record answered ' + totals.status);
        summary = await totals.json();
        if (summary.scope !== 'all' || summary.persona !== id) throw new Error('the complete prediction record is unavailable');
      }
      if (gen !== CARD.gen) return;
      CARD.rows = rows; CARD.summary = summary; CARD.hash = summary ? summary.log_hash : r.headers.get('X-Log-Hash') || ''; CARD.error = ''; CARD.wait = 0;
    } catch (e) {
      if (gen !== CARD.gen) return; CARD.rows = null; CARD.summary = null; CARD.error = e.message === 'Failed to fetch' ? 'cannot reach the arena' : e.message;
      // an unreadable record is tried again, never shown as zero; 4 s, then 8, 16, 32, capped at 60 s, so a log that is gone for good is not hammered
      CARD.wait = Math.min(60000, CARD.wait ? CARD.wait * 2 : 4000);
      root.setTimeout(function () { if (gen === CARD.gen && V.mode === 'workshop' && V.tab === 'card') loadCard(); }, CARD.wait);
    }
    var eqd = null;
    try { var o = await root.fetch('/room/observe', { cache: 'no-store' }).then(function (x) { return x.json(); }); var me = (o.fighters || []).filter(function (f) { return f.fighter_id === id; })[0]; eqd = me ? me.equipped || [] : null; } catch (e) { eqd = null; }
    if (gen !== CARD.gen) return;
    CARD.equipped = eqd; CARD.loading = false; if (V.mode === 'workshop' && V.tab === 'card') render();
  }
  function cardRecord() {
    var rows = CARD.rows; if (!rows) return null;
    if (CARD.summary) {
      var total = CARD.summary, count = total.scored, score = total.score_sum, baseline = total.base_score_sum;
      return { lives: total.lives, kos: total.kos, scored: count, meanScore: count ? score / count / 1e6 : null,
        calibration: count >= MIN_LIVES && baseline > 0 ? Math.max(0, Math.min(1, 0.5 + (baseline - score) / baseline / 2)) : null };
    }
    var ended = rows.filter(function (x) { return x.actual != null; }), scored = ended.filter(function (x) { return x.prediction && x.score != null && x.base_score != null; });
    var sum = function (a, k) { return a.reduce(function (t, x) { return t + Number(x[k] || 0); }, 0); }, base = sum(scored, 'base_score'), ai = sum(scored, 'score');
    var cal = scored.length >= MIN_LIVES && base > 0 ? Math.max(0, Math.min(1, 0.5 + (base - ai) / base / 2)) : null;
    return { lives: ended.length, kos: sum(ended, 'actual'), scored: scored.length, meanScore: scored.length ? ai / scored.length / 1e6 : null, calibration: cal };
  }
  function cardTab() {
    if (!root.SnapCard) return receipt('<div class="sub">The card module did not load. Reload the page.</div>');
    var id = myFighter(); if (id && !CARD.rows && !CARD.loading && !CARD.error) loadCard();   // first look
    var rec = cardRecord(), slots = ['weapon', 'head', 'body', 'trinket'], eq = CARD.equipped || [];
    var bag = eq.length ? slots.map(function (k) { var e = eq.filter(function (x) { return x.slot === k; })[0]; return e ? itemName(e.item_id) : '–'; }) : [];
    // the sim numbers re-made legendaries from 1 (sim.py's serials); ':0' is an original with no serial
    var serials = eq.filter(function (x) { return x.serial_id && /:\d+$/.test(x.serial_id) && Number(x.serial_id.split(':').pop()) > 0; }).map(function (x) { return { name: itemName(x.item_id), n: Number(x.serial_id.split(':').pop()) }; });
    var note = !id ? 'Snap in to give the card a record: the gauge reads your AI’s scored lives from the public predictions log.'
      : CARD.error ? 'Record unavailable, retrying: ' + CARD.error + '. The gauge stays empty until it can be read.'
      : !rec ? 'Reading your record…'
      : rec.calibration == null ? 'The gauge needs ' + MIN_LIVES + ' scored lives; your AI has ' + rec.scored + '. Lives without a prediction are not scored.'
      : 'The gauge compares how far your AI’s spreads sat from what happened with the plain base rate, over ' + rec.scored + ' scored lives.';
    return '<div class="card-wrap">' + root.SnapCard.html({ name: P.name || 'Newcomer', tag: (P.name || 'Newcomer').split(' ')[0].slice(0, 12), portrait: portraitURL(), preset: P.preset, bag: bag, serials: serials,
        record: rec && rec.lives ? { lives: rec.lives, kos: rec.kos, meanScore: rec.meanScore, calibration: rec.calibration } : null, recordUnavailable: !!(id && CARD.error), state: null }) + '</div>' +
      '<div class="sub" role="status">' + esc(note) + '</div><div class="sub">Scars come from item KOs, which the DEV arena does not keep yet.' + (CARD.hash ? ' Log hash ' + esc(CARD.hash.slice(0, 12)) + '….' : '') + '</div>' +
      (id ? btn('Refresh the record', 'card-refresh', 'textlink') : btn('Snap in', 'mode:flow', 'main-action'));
  }

  // ------------------------------------------------------------------ views
  function viewFlow() {
    var s = V.step, head = '', content = '';
    content = stepsBar() + (V.flash ? '<div class="in-banner" role="status">' + esc(V.flash) + '</div>' : '') + endedLine();
    if (s !== 'ring') content += inBanner();
    if (s === 'wallet') {
      head = 'Own your persona';
      // the first screen: a returning browser sees its saved trenchie and the way to a new one
      if (hasDraft() && !P.ended && !mineDriven()) content += receipt('<div class="eyebrow">Your Trenchie</div><h3>' + esc(draftName()) + '</h3><div class="sub">Saved in this browser. Continue goes on with it.</div>' + newButton());
      if (P.wallet) {
        content += receipt('<div class="eyebrow">Connected · ' + esc(P.wallet.network) + '</div><h2 class="acct" title="' + esc(P.wallet.accountId) + '" aria-label="Account ' + esc(P.wallet.accountId) + '">' + esc(shortAcct(P.wallet.accountId)) + '</h2><div class="sub">' + esc(walletName(P.wallet.id)) +
          (P.wallet.id === 'dev-throwaway' ? ' · made in this browser, unfunded; nothing is created or signed onchain.' : '') + '</div>' +
          (P.wallet.chain ? '<div class="sub">Signed in. ' + (P.wallet.chain.owned && P.wallet.chain.owned.length ? 'Your Trenchie: ' + esc(P.wallet.chain.owned[0].token_id) + '.' : P.wallet.chain.offer && P.wallet.chain.offer.kind === 'claim' ? 'A free Trenchie is waiting for you (' + esc(P.wallet.chain.offer.held) + ' left).' : 'A new Trenchie is a paid mint: ' + esc(yoctoNear(P.wallet.chain.offer && P.wallet.chain.offer.cost_yocto)) + ' NEAR, signed in your wallet when you enter the arena.') + '</div>' : '') + '</div>') +
          btn('Continue', 'step:presets', 'main-action') + btn('Use another wallet', 'wallet-forget', 'textlink');
      } else {
        content += receipt(CHAIN ? '<h2>' + (NETWORK === 'mainnet' ? 'NEAR wallet' : 'Testnet wallet') + '</h2><div class="notice" style="margin-top:12px">Your wallet signs in (a message, no cost) and owns your Trenchie on ' + esc(NETWORK) + '. Its fights and gear are recorded on testnet under that Trenchie.</div>'
                                 : '<h2>Testnet wallet</h2><div class="notice" style="margin-top:12px">Your wallet will own your persona. In the DEV arena nothing is minted, signed or charged.</div>') + '<div class="button-list" style="margin-top:20px">' +
          btn('<span>Connect wallet</span><small>' + esc(NETWORK) + '</small><span class="symbol">→</span>', 'wallet:choose', 'door') +
          (CHAIN ? '</div>' : btn('<span>Throwaway account</span><small>DEV · no wallet needed</small><span class="symbol">→</span>', 'wallet-dev', 'door') + '</div>' +
          '<div class="sub">The throwaway account is an unfunded testnet account id made in this browser; nothing is created or signed onchain.</div>');
      }
      content += chips(['testnet · persona', 'Browser · connection']) + btn('Keep watching', 'step:watch', 'textlink');
    } else if (s === 'presets' || s === 'presets-empty') {
      head = 'Fighter presets';
      content += '<div class="row"><span class="chip mint">5 battle options</span><span class="chip">' + (CHAIN ? esc(chainSupply()) : 'DEV · free to try') + '</span></div>' + presetGrid() + (inventoryNote()) +
        claimLine() +
        '<div class="sub">' + (CHAIN ? (P.wallet && P.wallet.chain && P.wallet.chain.offer && P.wallet.chain.offer.kind === 'claim' ? 'Use this preset to claim its premint for free (one per wallet, first come); a fighter you build is a paid mint.' : 'Every free premint is claimed: a new Trenchie is a paid mint your wallet signs when you enter the arena.') : 'The onchain premint (5 presets × 10 copies, first come) is not deployed yet; a DEV claim is kept in this browser only.') + '</div>' +
        btn(claimedHere() ? 'Next: personality' : 'Use this preset', 'claim', 'main-action') + btn('Build a fighter', 'step:build', 'textlink');
    } else if (s === 'claimed') {
      head = 'Preset supply';
      content += receipt('<h2>' + esc(P.preset) + '</h2><div class="sub">All claimed</div>') + btn('Build a fighter', 'step:build', 'main-action') + btn('Pick another preset', 'step:presets', 'textlink') + btn('Keep watching', 'step:watch', 'textlink');
    } else if (s === 'build') {
      head = 'Fighter builder';
      content += '<div class="split"><div>' + hero() + appearance() + '</div><div>' + inventory() + '</div></div>' + btn('Next: personality', 'step:personality', 'main-action') + chips(CHAIN ? [chainSupply(), NETWORK] : ['DEV · free', 'testnet']);
    } else if (s === 'personality') {
      head = 'Personality'; content += claimCard() + personality() + btn('Next: pick AI', 'step:doors', 'main-action');
    } else if (s === 'agree') {
      head = 'Your say-so'; content += agreement();
    } else {
      var r = ringView(); head = r.head; content += r.content;
    }
    return { head: head, content: content };
  }
  function inventoryNote() { return kitCard(); }
  function viewWorkshop() {
    var tabs = [['battle', 'Battle'], ['inventory', 'Inventory'], ['look', 'Look'], ['persona', 'Persona'], ['card', 'Card'], ['agree', 'Agree'], ['respawn', 'Respawn']], t = V.tab, head = '', c = '';
    c = '<nav class="tabs" aria-label="Workshop">' + tabs.map(function (a) { return btn(a[1], 'tab:' + a[0], '', 'aria-label="' + a[1] + '" aria-current="' + (t === a[0] ? 'page' : 'false') + '" aria-pressed="' + (t === a[0]) + '"'); }).join('') + '</nav>';
    if (t === 'battle') { head = 'A few battle options'; c += presetGrid() + kitCard() + '<div class="sub">You can switch battle option for each new life in the corner.</div>' + btn('See the kit', 'tab:inventory', 'main-action'); }
    else if (t === 'inventory') { head = 'Inventory'; c += '<div class="split"><div class="desktop-portrait">' + hero() + '</div><div>' + inventory() + '</div></div>' + btn('Next: look', 'tab:look', 'main-action'); }
    else if (t === 'look') { head = 'Appearance'; c += '<div class="split"><div>' + hero() + '</div><div>' + appearance() + '</div></div>' + btn('Next: persona', 'tab:persona', 'main-action'); }
    else if (t === 'persona') { head = 'Persona'; c += personaFile() + btn('Review agreement', 'tab:agree', 'main-action'); }
    else if (t === 'card') { head = 'Card'; c += cardTab(); }
    else if (t === 'agree') { head = 'Your say-so'; c += agreement(); }
    else { head = 'Respawn corner'; c += corner(); }
    return { head: head, content: c };
  }
  // on any step before the ring, while this browser's fighter is in: say so, with the way back
  function inBanner() {
    var live = root.SnapRoom && root.SnapRoom.status();
    if (V.mode !== 'flow' || !live || !live.fighter || !/^(in|joining|offline)$/.test(live.phase)) return '';
    // on the first screen the banner also carries the way to a new trenchie (one place names the trenchie, not two)
    var first = V.step === 'wallet' ? newButton() : '';
    return '<div class="in-banner" role="status">' + esc((CHAIN ? '' : 'DEV ') + live.fighter.name) + ' is in the arena now. ' + btn('Back to your Trenchie', 'back-ring', 'textlink') + first + '</div>';
  }
  function viewLogin() {
    var v = D.view({ returning: !!root.SnapUI.store.get('trenchie.snapin.lastdoor'), walletChip: aiChip(), onContinue: V.mode === 'flow' ? 'Next: the arena rules' : 'Back to the arena' });
    return { head: v.head, content: inBanner() + v.html, ai: true };
  }

  // ------------------------------------------------------------------ render
  function render() {
    // keep keyboard focus on the same control across a re-render (a toggle, a status change)
    var fa = doc.activeElement, refocus = fa && fa.dataset && fa.dataset.act ? '[data-act="' + fa.dataset.act.replace(/"/g, '\\"') + '"]' : fa && fa.dataset && fa.dataset.spread != null ? '[data-spread="' + fa.dataset.spread + '"]' : (fa && fa.id && app.contains(fa) ? '#' + fa.id : '');
    var caret = fa && typeof fa.selectionStart === 'number' ? [fa.selectionStart, fa.selectionEnd] : null;
    css(boardMode());
    if (boardMode()) return renderBoard(refocus, caret);
    var flowAI = V.mode === 'flow' && (V.step === 'doors'), v = V.mode === 'login' || flowAI ? viewLogin() : V.mode === 'workshop' ? viewWorkshop() : viewFlow();
    var draft = v.ai ? 'b' : 'a', board = V.mode === 'login' || flowAI ? 'S4' : V.mode === 'workshop' ? 'S2' : 'S1';
    doc.body.className = 'draft-' + draft + ' board-' + board + (v.ai ? ' ai-mode' : '');
    if (V.closed) { app.innerHTML = '<div class="closed-preview">' + receipt('<h1>Arena</h1>' + btn('Open panel', 'reopen', 'main-action')) + '</div>'; }
    else app.innerHTML = '<main class="shell" data-material="wood"><div class="paper-surface"><header><div>' + (v.ai ? '' : '<div class="eyebrow">' + (V.mode === 'workshop' ? 'Persona workshop' : 'Snap into the arena') + '</div>') + '<h1>' + esc(v.head) + '</h1></div>' + btn('×', 'close', 'close', 'aria-label="Close panel"') + '</header>' + v.content + '<div class="status" id="feedback" aria-live="polite">' + esc(V.msg) + '</div></div></main>';
    var fb = doc.querySelector('#feedback'); if (fb && V.msgErr) fb.classList.add('err');
    if (root.SnapChat && app.querySelector('[data-chat]')) root.SnapChat.wire(app, render);
    if (refocus) { var back = app.querySelector(refocus); if (back) { back.focus({ preventScroll: true }); if (caret && typeof back.setSelectionRange === 'function') try { back.setSelectionRange(caret[0], caret[1]); } catch (e) { /* number inputs have no caret */ } } }
    root.requestAnimationFrame(function () { U.paint(app); root.__SNAPIN_READY = true; });
  }
  // ------------------------------------------------------------------ board 1: the guide's steps before the ring (guide.js)
  function boardMode() { return !!root.SnapGuide && V.mode === 'flow' && V.step !== 'ring' && !V.closed; }
  function css(board) {   // board 1's sheet and the older panels' sheet never apply together (their class names overlap)
    var a = doc.getElementById('css-snapin'), b = doc.getElementById('css-board1'); if (a) a.disabled = board; if (b) b.disabled = !board;
  }
  var lastPhone = null;
  function renderBoard(refocus, caret) {
    var G = root.SnapGuide; lastPhone = G.phone();
    doc.body.className = (lastPhone ? 'w390' : 'w1440') + ' b1';
    app.innerHTML = G.view(guideHost);
    if (refocus) { var back = app.querySelector(refocus); if (back) { back.focus({ preventScroll: true }); if (caret && typeof back.setSelectionRange === 'function') try { back.setSelectionRange(caret[0], caret[1]); } catch (e) { /* no caret */ } } }
    root.requestAnimationFrame(function () { G.paint(app); root.__SNAPIN_READY = true; });
  }
  function bl(act, label) { return '<a href="#" class="link" data-act="' + act + '">' + label + '</a>'; }
  // a returning player's own trenchie on the guide's screens: in the ring, out of it, or saved here (items 33 and 25)
  function newLink() {
    if (!V.confirmNew) return bl('new-trenchie', 'Make a new Trenchie');
    var nm = draftName(), kept = keptWords();
    return '<b>' + esc('This forgets ' + nm + ': its name, look, temperament, quirks and voice' + (P.claim ? ', and its premint claim' : '') + '. Keep it or start fresh?') + '</b> ' +
      (mineDriven() ? esc(nm + ' swims home first: this browser drives one Trenchie at a time.') + ' ' : '') + (kept ? esc(kept) + ' ' : '') + bl('new-trenchie-yes', 'Start fresh') + ' · ' + bl('new-trenchie-no', 'Keep ' + esc(nm));
  }
  function returningLine() {
    if (V.flash) return esc(V.flash);
    var live = mineDriven();
    if (live) return esc('DEV ' + live.fighter.name + ' is in the arena now.') + ' ' + bl('back-ring', 'Back to your Trenchie') + ' · ' + newLink();
    if (P.ended) return esc('DEV ' + P.ended.name + ' is out of the arena (' + P.ended.why + '). Your Trenchie is kept.') + ' ' + bl('rejoin', 'Snap ' + esc(P.ended.name) + ' back in') + ' · ' + newLink();
    if (V.step === 'wallet' && hasDraft()) return esc('Your Trenchie: ' + draftName() + ', saved in this browser.') + ' ' + newLink();
    return '';
  }
  async function ringNames() {   // the names in the ring now, squashed (an agent's fighter shows its id, "DEV lanternlou")
    var out = new Set();
    try { var o = await root.fetch('/room/observe', { cache: 'no-store' }).then(function (r) { return r.json(); }); (o.fighters || []).forEach(function (f) { var n = String(f.public_name || '').replace(/^DEV /, '').split(' · ')[0]; out.add(n.toLowerCase().replace(/[^a-z0-9]/g, '')); }); } catch (e) { /* no arena: nothing known to be taken */ }
    var mine = mineDriven(); if (mine) out.delete(String(mine.fighter.name).toLowerCase().replace(/[^a-z0-9]/g, ''));   // this browser's own trenchie is not a clash
    return out;
  }
  // chain mode for board 1's views: the host's identity network, and what this wallet's sign-in found (main's own sentences)
  function chainInfo() {
    var ch = P.wallet && P.wallet.chain;
    var signed = !CHAIN || !ch ? '' : 'Signed in. ' + (ch.owned && ch.owned.length ? 'Your Trenchie: ' + ch.owned[0].token_id + '.' : ch.offer && ch.offer.kind === 'claim' ? 'A free Trenchie is waiting for you (' + ch.offer.held + ' left).' : 'A new Trenchie is a paid mint: ' + yoctoNear(ch.offer && ch.offer.cost_yocto) + ' NEAR, signed in your wallet when you enter the arena.');
    var fighter = !CHAIN ? '' : ch && ch.offer && ch.offer.kind === 'claim' ? 'Use this preset to claim its premint for free (one per wallet, first come); a fighter you build is a paid mint.' : 'Every free premint is claimed: a new Trenchie is a paid mint your wallet signs when you enter the arena.';
    return { on: !!CHAIN, network: NETWORK, signed: signed, fighter: fighter };
  }
  // board 1: Snap in lands on the trenchie panel in the arena (SPEC state 'fight'), when the session can cross pages (its
  // key kept in this browser's storage); a browser that cannot keep it stays here, where the trenchie is safe while this
  // page is open (item 39's one real failure: moving pages lost the trenchie)
  async function snapIn() {
    // a plan door: the player's own agent session joined with the door's code; this page sends no join of its own, it
    // goes to the arena, where the panel reads the session's log by the code
    if (P.door && P.door.route === 'plan' && P.planCode) { save(); root.location.href = arenaURL(); return; }
    var cur = root.SnapRoom.status(); if (cur.fighter && /^(in|joining|offline)$/.test(cur.phase)) { go('ring'); return; }   // already in: no second join
    P.left = 0; go('ring'); await startJoin();
    var st = root.SnapRoom.status();
    if (st.phase === 'in' && st.fighter && st.keyPersisted !== false && V.step === 'ring') { save(); root.location.href = arenaURL() + (WS ? '&' : '?') + 'follow=' + encodeURIComponent(st.fighter.id); }
  }
  function devWallet() {
    var NA = root.NearApi; if (!NA || !NA.KeyPairEd25519) return say('The wallet library did not load. Reload the page.', true);
    var raw = NA.KeyPairEd25519.fromRandom().getPublicKey().data;   // the secret half is dropped at once: a throwaway id, never funded or used to sign
    var id = Array.prototype.map.call(raw, function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
    P.wallet = { id: 'dev-throwaway', accountId: id, network: NETWORK }; P.timing = { wallet: Date.now() }; go('presets');
  }
  // Agent codes carry the same page-key authority and confirmed token as a browser join. The sign-in id alone is
  // never a bearer credential; the identity module signs this request without another wallet sign-in.
  async function requestPlanCode(args) {
    if (!CHAIN) return root.SnapProviders.snap.requestCode(args);
    var ch = P.wallet && P.wallet.chain;
    if (!ch) throw new Error('Sign in with your wallet first (step 1).');
    var sh = buildSheet();
    if (!sh || sh.error) throw new Error((sh && sh.error) || 'the persona sheet could not be built');
    say(ch.owned && ch.owned.length ? 'Checking ' + ch.owned[0].token_id + ' is still yours…' : ch.offer && ch.offer.kind === 'claim' && claimIntact() ? 'Claiming your free Trenchie on ' + NETWORK + '…' : 'Approve the paid mint in your wallet (' + yoctoNear(ch.offer && ch.offer.cost_yocto) + ' NEAR)…');
    try {
      var token = await root.SnapIdentity.getTrenchie({ preset: presetId(), sheet: sh, claim: claimIntact() });
      ch.token = token.token_id; ch.tx = token.tx || ch.tx || null; ch.owned = [{ token_id: token.token_id }]; P.sheet = sh; save();
      var payload = { agent: args.agent, name: args.name || null, plan_stop_pct: args.planStop > 0 ? args.planStop : null,
                      preset: presetId(), sheet: sh, look: root.SnapSheet.lookFile(sheetState()) };
      var envelope = await root.SnapIdentity.codeRequest(payload, token.token_id);
      return await root.SnapProviders.snap.requestCode(args, { envelope: envelope });
    } finally { say(''); }
  }
  var guideHost = { P: P, V: V, go: function (s) { go(s); }, save: function () { save(); }, render: function () { render(); }, say: function (m, e) { say(m, e); }, backToArena: function () { backToArena(); },
    devWallet: function () { devWallet(); }, connectWallet: function (id) { connectWallet(id); }, setPreset: function (n) { setPreset(n); }, claim: function () { return claimOption(); },
    requestCode: requestPlanCode,
    ringNames: ringNames, loadTerms: function () { loadTerms(); }, chain: chainInfo, loadPremint: function () { return loadPremint(); }, shortAcct: function (a) { return shortAcct(a); }, snapIn: function () { snapIn(); }, returning: returningLine };
  function say(m, err) { V.msg = m; V.msgErr = !!err; var fb = doc.querySelector('#feedback'); if (fb) { fb.textContent = m; fb.classList.toggle('err', !!err); } else render(); }

  // ------------------------------------------------------------------ actions
  function download(name, text) {
    var a = doc.createElement('a'); a.href = 'data:application/json;charset=utf-8,' + encodeURIComponent(text); a.download = name; doc.body.appendChild(a); a.click(); a.remove();
  }
  async function connectWallet(id) {
    var W = root.SnapWallet; if (!W) return say('The wallet module did not load. Reload the page.', true);
    V.busy = true; say('Opening wallet chooser…');
    try {
      var r = await W.connect(id === 'choose' ? null : id, { network: NETWORK });
      if (r && (r.ok !== false) && (r.accountId || r.account) && CHAIN) {
        say('Sign the sign-in message in ' + (r.walletName || 'your wallet') + ' (a message, not a transaction: no cost)…');
        try {
          var si = await root.SnapIdentity.signIn();
          P.wallet = { id: r.walletId, name: r.walletName, accountId: si.account, network: si.network, chain: { owned: si.owned, offer: si.offer } }; P.timing = { wallet: Date.now() }; go('presets');
        } catch (e2) { P.wallet = null; say('Not signed in: ' + e2.message + '. Try again, or keep watching.', true); }
      }
      else if (r && (r.ok !== false) && (r.accountId || r.account)) { P.wallet = { id: r.walletId, name: r.walletName, accountId: r.accountId || r.account, network: r.network || NETWORK }; P.timing = { wallet: Date.now() }; go('presets'); }
      else if (r && (r.kind === 'no-list' || r.kind === 'framed')) say(r.message, true);   // said whole: no wallet was tried
      else say('Wallet not connected: ' + ((r && (r.message || r.reason)) || 'no answer') + '. Keep watching, or try another wallet.', true);
    } catch (e) { say('Wallet not connected: ' + (e && e.message ? e.message : 'the wallet did not answer') + '. Keep watching, or try another wallet.', true); }
    V.busy = false;
  }
  async function onClick(e) {
    var b = e.target.closest('[data-act],button'); if (!b || b.disabled) return;
    if (b.tagName === 'A') e.preventDefault();
    var a = b.dataset.act || '';
    if (a.indexOf('g:') === 0 && root.SnapGuide) return root.SnapGuide.act(a, guideHost, b);
    if (a.indexOf('ai:') === 0) {
      if (a === 'ai:authorize') { P.resume = { mode: V.mode, step: V.step }; save(); }
      await D.act(a); return;
    }
    if (a.indexOf('step:') === 0) go(a.slice(5));
    else if (a.indexOf('mode:') === 0) { V.mode = a.slice(5); V.msg = ''; render(); }
    else if (a.indexOf('tab:') === 0) { if (a === 'tab:respawn') return openCorner(); V.tab = a.slice(4); V.msg = ''; render(); }
    else if (a.indexOf('wallet:') === 0) connectWallet(a.slice(7));
    else if (a.indexOf('preset:') === 0) { var nm = a.slice(7), i = PRESETS.indexOf(nm); if (root.SNAPIN_SUPPLY && root.SNAPIN_SUPPLY[i] === 0) { P.preset = nm; go('claimed'); } else { setPreset(nm); render(); } }
    else if (a.indexOf('look:') === 0) { var l = a.split(':'); P.look = Object.assign({}, look()); P.look[l[1]] = l[2]; P.lookEdited = true; save(); render(); }
    else if (a.indexOf('temper:') === 0) { P.temper = a.slice(7); save(); render(); }
    else if (a.indexOf('quirk:') === 0) { var qk = a.slice(6), ix = P.quirks.indexOf(qk); if (ix >= 0) P.quirks.splice(ix, 1); else if (P.quirks.length < 3) P.quirks.push(qk); save(); render(); }
    else if (a === 'close') backToArena();   // × always returns to the live arena; the guide keeps its place
    else if (a === 'reopen') { V.closed = false; render(); }
    else if (a === 'agree') {
      if (![].slice.call(app.querySelectorAll('.checks input')).every(function (x) { return x.checked; })) return say('Tick all three to continue.', true);
      if (!V.terms || V.terms.error) return say('The arena rules have not loaded yet, so there is nothing to agree to. Press Try again above.', true);
      P.agreed = true; P.termsVersion = V.terms.version;
      var cur = root.SnapRoom.status(); if (cur.fighter && /^(in|joining|offline)$/.test(cur.phase)) { go('ring'); return; }   // already in: no second join
      P.left = 0; go('ring'); startJoin();
    }
    else if (a === 'terms-reload') loadTerms();
    else if (a === 'wallet-dev') devWallet();
    else if (a === 'wallet-forget') { P.wallet = null; save(); render(); }
    else if (a === 'claim') await claimOption();
    else if (a === 'claim-restore') { if (P.claim) { P.preset = P.claim.preset; adoptClaim(); render(); } }
    else if (a === 'join') startJoin();
    else if (a === 'new-trenchie-yes') await newTrenchie();
    else if (a === 'new-trenchie') { V.confirmNew = true; render(); var c = app.querySelector('.confirm-new'); if (c && c.scrollIntoView) c.scrollIntoView({ block: 'nearest' }); }
    else if (a === 'new-trenchie-no') { V.confirmNew = false; render(); }
    else if (a === 'rejoin') { go('ring'); startJoin(); }
    else if (a === 'resume') { if (root.SnapRoom) await root.SnapRoom.resume(); render(); }
    else if (a === 'watch-mine') { var st = root.SnapRoom && root.SnapRoom.status(); save(); root.location.href = arenaURL() + (st && st.fighter ? (WS ? '&' : '?') + 'follow=' + encodeURIComponent(st.fighter.id) : ''); }
    else if (a === 'corner') openCorner();
    else if (a === 'back-ring') { V.mode = 'flow'; V.closed = false; go('ring'); }
    else if (a.indexOf('next-preset:') === 0) { V.nextPreset = a.slice(12); V.pickMsg = ''; render(); }
    else if (a === 'card-refresh') { CARD.rows = null; CARD.error = ''; CARD.wait = 0; loadCard(); render(); }
    else if (a === 'noop') { /* a disabled control: its reason is printed beside it */ }
    else if (a === 'leave') { if (root.SnapRoom) await root.SnapRoom.leave(); P.left = Date.now(); save(); render(); }
    else if (a === 'ready') {
      var tot = P.spread.reduce(function (s2, n) { return s2 + Number(n || 0); }, 0), z = Number(P.zeroKo);
      if (tot !== 100 || P.spread.some(function (n) { return !(Number(n) >= 0 && Number(n) <= 100 && Number.isInteger(Number(n))); })) { V.pickMsg = 'The four KO chances are whole percents that add up to 100. They add up to ' + tot + '% now.'; return render(); }
      if (!(z >= 0 && z <= 100 && Number.isInteger(z))) { V.pickMsg = 'The chance of zero KOs is a whole percent from 0 to 100.'; return render(); }
      var cur = (root.SnapRoom.status().fighter || {}).preset || presetId(), pick = V.nextPreset || cur;
      try { await root.SnapRoom.setOrder({ preset: pick, spread: P.spread.map(Number), zero: z }); }
      catch (e) { V.pickMsg = 'Not saved: ' + e.message; return render(); }
      P.preset = presetName(pick); V.nextPreset = ''; save();
      V.pickMsg = 'Saved. Your next life fights as ' + presetName(pick) + ', predicting ' + P.spread.join('/') + ' and ' + z + '% for zero KOs. It is sent, signed, when the arena announces that life.';
      render();
    }
    else if (a === 'sheet-download') { var sh = buildSheet(); if (!sh || sh.error) return say('No sheet to download: ' + (sh && sh.error || 'the sheet module did not load'), true); download(sh.identity.role + '.json', JSON.stringify(sh, null, 2)); say('Sheet downloaded as ' + sh.identity.role + '.json.'); }
    else if (a === 'look-download') { var lf = root.SnapSheet && root.SnapSheet.lookFile(sheetState()); if (!lf) return say('The sheet module did not load.', true); download(lf.role + '.look.json', JSON.stringify(lf, null, 2)); say('Look file downloaded.'); }
    else if (a === 'sheet-copy') { var s2 = buildSheet(); var ok = s2 && !s2.error && await U.copyText(JSON.stringify(s2, null, 2)); say(ok ? 'Sheet copied.' : 'Could not copy. Use Download sheet.', !ok); }
    else if (a.indexOf('edit-slot:') === 0) { V.openSlot = a.slice(10); render(); }
  }
  function onInput(e) {
    var t = e.target;
    if (boardMode() && root.SnapGuide.input(t, guideHost)) return;
    if (t.type === 'checkbox') { V.ticks = V.ticks || {}; V.ticks[t.id] = t.checked; if (V.msgErr) say(''); }   // kept across re-renders; a tick clears the "Tick all three" note
    if (t.id === 'name') { P.name = t.value; save(); var g = root.SnapSheet && root.SnapSheet.guard(P.name || 'Newcomer'); var old = t.parentNode.querySelector('[role=alert]'); if (old) old.remove(); if (g && !g.ok) t.insertAdjacentHTML('afterend', '<div class="sub" role="alert">' + esc(g.reason) + '</div>'); }
    else if (t.id === 'personality') { P.voice = t.value; save(); }
    else if (t.id === 'zero-ko') { P.zeroKo = t.value; save(); }
    else if (t.dataset && t.dataset.spread != null) { P.spread[Number(t.dataset.spread)] = t.value; save(); var tot = P.spread.reduce(function (s, n) { return s + Number(n || 0); }, 0), el = doc.querySelector('#spread-total'); if (el) el.textContent = 'Spread totals ' + tot + '%' + (tot === 100 ? '' : ' (needs 100%)'); }
  }

  // ------------------------------------------------------------------ boot
  async function boot() {
    app = doc.querySelector('#app');
    await root.SKA.init();
    D.attach({ repaint: render, board: V.mode,
      persona: function () { return P.name || ''; },
      onConnected: function (info) { P.door = info; save(); if (V.mode === 'flow') { V.step = 'doors'; } render(); },
      onDisconnected: function () { P.door = null; save(); },
      onContinue: function () { if (V.mode === 'flow') go('agree'); else backToArena(); } });
    D.reset();
    // OpenRouter returns with ?code=...: finish the PKCE exchange and resume where the player left
    var code = q.get('code');
    if (code && /^[\w.-]{8,}$/.test(code)) {
      if (P.resume) { V.mode = P.resume.mode; V.step = P.resume.step; }
      try { root.history.replaceState(null, '', root.location.pathname + (V.mode !== 'flow' ? '?mode=' + V.mode : '')); } catch (e) { /* ignore */ }
      render(); await D.finishOpenRouter(code); return;
    }
    var aiState = q.get('ai'); if (aiState) { D.preview(aiState, q.get('door') || 'NEAR AI Cloud', q.get('route') !== 'plan'); if (V.mode === 'flow' && !q.get('step')) V.step = 'doors'; }
    if (V.mode === 'flow' && V.step === 'ai') V.step = 'doors';
    app.addEventListener('click', onClick); app.addEventListener('input', onInput);
    // Escape leaves the panel: in the flow that is back to the arena (progress is saved; the call to action resumes it)
    doc.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape' || V.closed || /^(INPUT|TEXTAREA|SELECT)$/.test((doc.activeElement || {}).tagName || '')) return;
      backToArena();
    });
    // Back and Forward walk the steps; the URL always names the step on screen, so a reload resumes it
    root.addEventListener('popstate', function (e) {
      var qs = new URLSearchParams(root.location.search);
      if (qs.get('mode') === 'workshop') { V.mode = 'workshop'; V.tab = qs.get('tab') || 'battle'; V.closed = false; render(); if (V.tab === 'respawn') startCorner(); return; }
      var st = (e.state && e.state.step) || qs.get('step');
      if (STEPS.indexOf(st) < 0) return;
      V.mode = 'flow';
      st = allowed(st);
      V.step = st; V.msg = ''; V.closed = false; P.step = st; save(); if (st === 'doors') D.reset(); if (st === 'agree') loadTerms(); render();
    });
    if (V.mode === 'flow') { P.step = V.step; save(); try { root.history.replaceState({ step: V.step }, '', stepURL(V.step)); } catch (e) { /* no history */ } }
    root.addEventListener('resize', function () { if (boardMode()) { if (root.SnapGuide.phone() !== lastPhone) render(); else root.SnapGuide.paint(app); } else U.paint(app); });
    // the last step follows the arena client's progress; a saved fighter carries on after a reload
    if (root.SnapBrain && root.SnapBrain.on) root.SnapBrain.on(function (b) { brainState = b; var el = doc.querySelector('#brain-chip'); if (el) el.textContent = brainLine(); });
    if (root.SnapRoom) {
      var lastPhase = '';
      var lastBanner = '';
      root.SnapRoom.on(function (st) {
        var k = st.phase + '|' + st.step + '|' + st.message + '|' + (st.fighter ? st.fighter.lives + (st.fighter.lastPick ? st.fighter.lastPick.state + (st.fighter.lastPick.seated ? '+seated' : '') : '') : '');
        if (k === lastPhase) return; lastPhase = k;
        if (st.phase === 'in' && st.fighter && (!P.fighter || P.fighter.id !== st.fighter.id || P.ended || P.swimming)) { P.fighter = { id: st.fighter.id, name: st.fighter.name }; P.left = 0; P.ended = null; P.swimming = null; save(); }
        if ((V.mode === 'flow' && V.step === 'ring' && !V.closed) || cornerOpen()) return render();
        // on any other step, only a change of the in-the-arena banner re-renders (focus and caret are kept)
        var banner = st.fighter && /^(in|joining|offline)$/.test(st.phase) ? 'on' : 'off';
        if (V.mode === 'flow' && banner !== lastBanner) { lastBanner = banner; render(); }
      });
      // a returning browser whose trenchie is no longer in the arena starts fresh instead of retrying it (item 33); one
      // that left on purpose keeps its returning screen; an arena that cannot be reached keeps the fighter (offline)
      var had = P.fighter && !P.left ? P.fighter : null; V.checking = !!had;
      root.SnapRoom.resume().then(function () {
        var st = root.SnapRoom.status(); V.checking = false;
        if (had && (st.phase === 'none' || st.phase === 'ended' || st.phase === 'error')) seatEnded(had, st.error && st.error.code); else render();
      }, function () { V.checking = false; render(); });   // the worker looks in IndexedDB itself; nothing saved answers 'none'
    }
    if (V.mode === 'flow' && V.step === 'agree') loadTerms();
    if (root.SnapIdentity) root.SnapIdentity.mode().then(function (m) { CHAIN = m; if (m) { NETWORK = m.identity_network; if (P.wallet) { P.wallet = null; save(); if (V.mode === 'flow' && V.step !== 'wallet') go('wallet'); } } render(); });   // chain mode: a page's sign-in lives in its memory, so a fresh page signs in again (a DEV wallet never carries over)
    render();
    if (boardMode()) root.SnapGuide.enter(V.step, guideHost);
    if (V.mode === 'workshop' && V.tab === 'respawn') startCorner();
  }
  root.Snapin = { boot: boot, state: P, view: V, render: render, buildSheet: buildSheet, setPreset: setPreset, corner: C };
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', boot); else boot();
})(typeof globalThis !== 'undefined' ? globalThis : this);
