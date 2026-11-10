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
  var MENU = { weapon: ['Bonk', 'Spear', 'Bow', 'Trout', 'Lob', 'Zap'], head: ['Cap', 'Hood', 'Helm'], body: ['Tee', 'Coat', 'Shell'], trinket: ['Roll', 'Charm', 'Bell'] };
  var KNOWN_ART = { Bonk: 1, Cap: 1, Tee: 1, Roll: 1 };
  var ATTACK = { Swing: 'Hit nearby foes in an arc.', Lunge: 'Dash to the target; hit on arrival.', Beam: 'Wind up, then hit along a line.', Lob: 'Drop a burst into a marked circle.', Zap: 'Hit one foe, then jump to others.' };
  var WALLETS = [['meteor', 'Meteor'], ['intear', 'Intear'], ['nightly', 'Nightly'], ['ethereum-wallets', 'Ethereum Wallets']];

  // ------------------------------------------------------------------ state
  var DEF = { preset: 'Brawler Swing', slots: { weapon: 'Bonk', head: 'Cap', body: 'Tee', trinket: 'Roll' }, look: null, lookEdited: false, temper: 'sunny', quirks: [], name: '', voice: '', wallet: null, door: null, agreed: false, resume: null,
              spread: [40, 30, 20, 10], zeroKo: 0, stake: false, move: false, lock: false };
  var P = Object.assign({}, DEF, U.store.json(SAVE, {}));
  P.slots = Object.assign({}, DEF.slots, P.slots || {});
  if (root.SnapSheet && !root.SnapSheet.TEMPERAMENTS.some(function (x) { return x.id === P.temper; })) P.temper = 'sunny';   // saved before the six real names
  var V = { mode: q.get('mode') || 'flow', step: q.get('step') || 'watch', tab: q.get('tab') || 'battle', openSlot: '', closed: false, msg: '', msgErr: false, busy: false, presetSheet: false };
  function save() { try { var c = Object.assign({}, P); U.store.set(SAVE, JSON.stringify(c)); } catch (e) { /* kept in memory */ } }
  var app, cache = new Map();

  var presetIdx = function () { return Math.max(0, PRESETS.indexOf(P.preset)); };
  function look() { return P.look || Object.assign({}, PRESET_LOOK[presetIdx()]); }
  function setPreset(name) {
    var i = PRESETS.indexOf(name); if (i < 0) return;
    P.preset = name; P.look = null; P.lookEdited = false; P.slots = { weapon: PRESET_WEAPON[i], head: 'Cap', body: 'Tee', trinket: 'Roll' }; save();
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
  function buildSheet() { var SS = root.SnapSheet; if (!SS) return null; try { return SS.build(sheetState()); } catch (e) { return { error: e.message }; } }

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
  function supplyText(i) { var s = root.SNAPIN_SUPPLY; if (!s) return 'Count pending'; return s[i] > 0 ? s[i] + ' / 10 left' : 'All claimed'; }
  function slotGroup(key, title, values, swatch) {
    var cur = (P.slots[key] != null ? P.slots[key] : (look()[key]));
    if (V.openSlot !== key && V.compact) return '<div class="slot-summary">' + btn(title + ' · ' + esc(String(cur)), 'edit-slot:' + key, 'slot-toggle') + '</div>';
    return '<fieldset class="slot-group"><legend>' + title + '</legend><div class="options' + (swatch ? ' swatches' : '') + '">' + values.map(function (v) {
      var label = typeof v === 'object' ? v[1] : v, val = typeof v === 'object' ? v[0] : v;
      return btn((swatch ? '<i class="dot" style="background:' + esc(root.SKA.C(val)) + '"></i>' : '') + esc(label), 'slot:' + key + ':' + val, '', 'aria-pressed="' + (cur === val) + '" data-slot="' + key + '"');
    }).join('') + '</div></fieldset>';
  }
  function inventory() {
    var h = slotGroup('weapon', 'Weapon', MENU.weapon) + slotGroup('head', 'Head', MENU.head) + slotGroup('body', 'Body', MENU.body) + slotGroup('trinket', 'Trinket', MENU.trinket);
    var pending = Object.keys(P.slots).map(function (k) { return P.slots[k]; }).filter(function (n) { return !KNOWN_ART[n]; });
    return h + (pending.length ? '<div class="sub" role="status">Art pending: ' + esc(pending.join(', ')) + '. The portrait shows what exists.</div>' : '');
  }
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
    return receipt('<div class="checks"><label><input type="checkbox" id="agree-ai">Uses the AI you picked</label><label><input type="checkbox" id="agree-public">Persona and banter: public</label><label><input type="checkbox" id="agree-gear">Gear drops; rivals keep it</label></div><div class="sub">Unclaimed drops disappear.</div>') +
      chips(['Mainnet · persona NFT', 'AI · your choice']) + btn('Snap in', 'agree', 'main-action');
  }
  function aiChip() { return P.wallet ? 'Wallet · ' + esc(P.wallet.network || 'mainnet') + ' connected' + (P.wallet.accountId ? ' · ' + esc(P.wallet.accountId) : '') : ''; }

  // ------------------------------------------------------------------ the corner (F22): the bench card at respawn
  function corner() {
    var c = root.SnapCorner && root.SnapCorner.data, last;
    if (c) {
      last = receipt('<div class="eyebrow">Last life</div><h2>Life ' + esc(c.life) + '</h2>' + U.line('Result', esc(c.result)) + U.line('Prediction', esc(c.prediction)) + (c.spread ? '<div class="sub">' + esc(c.spread) + '</div>' : '') +
        '<h3>Taken items</h3>' + (c.taken || []).map(function (t) { return U.line(esc(t[0]), esc(t[1])); }).join('') + '<h3>Floor</h3>' + (c.floor || []).map(function (t) { return U.line(esc(t[0]), esc(t[1])); }).join('') + '<h3>Pending lines</h3>' + (c.pending || []).map(function (t) { return U.line(esc(t[0]), esc(t[1])); }).join(''));
    } else last = receipt('<div class="eyebrow">Last life</div><h2>No life yet</h2><div class="sub">Your last life, what you took, what is on the floor and its timer show here once the arena sends them.</div>');
    var total = P.spread.reduce(function (s, n) { return s + Number(n || 0); }, 0);
    return last + '<div class="split"><div>' + receipt('<div class="eyebrow">Next life · inventory</div><h3>Loadout</h3>') + inventory() + '<div class="sub" style="margin-top:12px">Menu + your bag</div></div><div>' +
      receipt('<h3>KO prediction</h3><div class="prediction">' + ['1', '2', '3', '4+'].map(function (n, i) { return '<label>' + n + '<input type="number" data-spread="' + i + '" aria-label="' + n + ' KOs percent" min="0" max="100" value="' + esc(P.spread[i]) + '"></label>'; }).join('') + '</div><div class="sub" style="margin-top:10px" id="spread-total">Spread totals ' + total + '%</div><label class="field" for="zero-ko">Zero KO chance</label><input id="zero-ko" type="number" min="0" max="100" value="' + esc(P.zeroKo) + '"><div class="sub">Logged only · unstaked</div>') + '</div></div>' +
      '<div class="stake"><div class="testnet">TESTNET · optional stake</div>' + btn(P.stake ? 'Stake: on' : 'Stake: off', 'stake', '', 'aria-pressed="' + P.stake + '"') + '<span class="notice"> 0.01 testnet NEAR / life</span><div class="sub" style="margin-top:10px">0 KOs loses the stake.</div></div>' +
      receipt('<h3>Optional choices</h3><div class="row">' + btn('Move item', 'move', '', 'aria-pressed="' + P.move + '"') + btn('Sale lock', 'sale-lock', '', 'aria-pressed="' + P.lock + '"') + '</div>' +
        (P.move ? '<div class="sub">Unworn bag items only.</div><label class="field" for="move-item">Bag item</label><input id="move-item" placeholder="Choose bag item"><label class="field" for="move-to">Your other trenchie</label><input id="move-to" placeholder="Persona token">' : '') +
        (P.lock ? '<div class="sub">Sits out for sale.</div><div class="sub">About two hours.</div>' : '') + U.line('move?', P.move ? 'On' : 'Off') + U.line('lock?', P.lock ? 'On' : 'Off')) +
      btn(P.lock ? 'Confirm sale lock' : 'Ready next life', 'ready', 'main-action') + '<div class="status" id="locked"></div>';
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
  function cardTab() {
    if (!root.SnapCard) return receipt('<div class="sub">The card module did not load.</div>');
    return '<div class="card-wrap">' + root.SnapCard.html({ name: P.name || 'Newcomer', tag: (P.name || 'Newcomer').split(' ')[0].slice(0, 12), portrait: portraitURL(), preset: P.preset, bag: Object.keys(P.slots).map(function (k) { return P.slots[k]; }), record: root.SnapCorner && root.SnapCorner.record || null, state: root.SnapCorner && root.SnapCorner.cardState || null }) + '</div>' +
      '<div class="sub">The card draws from your persona and the arena’s record. With no lives yet, the gauge stays empty and says so.</div>';
  }

  // ------------------------------------------------------------------ views
  function viewFlow() {
    var s = V.step, head = '', content = '';
    if (s === 'watch') return { watch: true, content: '<div class="watch">' + receipt('<div class="eyebrow">Never-ending FFA</div><h1>Money, meet mouth.</h1>' + btn('Snap in your trenchie', 'step:wallet', 'main-action')) + '</div>' };
    content = stepsBar();
    if (s === 'wallet') {
      head = 'Own your persona';
      content += receipt('<h2>Mainnet NFT</h2><div class="notice" style="margin-top:12px">Your wallet owns it.</div>') + '<div class="button-list" style="margin-top:20px">' +
        WALLETS.map(function (w) { return btn('<span>' + w[1] + '</span><small>declares testnet</small><span class="symbol">→</span>', 'wallet:' + w[0], 'door'); }).join('') + '</div>' + chips(['onchain · persona', 'Browser · connection']) +
        btn('Keep watching', 'step:watch', 'textlink');
    } else if (s === 'presets' || s === 'presets-empty') {
      head = 'Fighter presets';
      content += '<div class="row"><span class="chip mint">First come</span><span class="chip">5 presets × 10 copies</span></div>' + presetGrid() + (inventoryNote()) + btn('Use this preset', 'step:personality', 'main-action') + btn('Build a fighter', 'step:build', 'textlink');
    } else if (s === 'claimed') {
      head = 'Preset supply';
      content += receipt('<h2>' + esc(P.preset) + '</h2><div class="sub">All claimed</div>') + btn('Paid mint', 'step:build', 'main-action') + btn('Keep watching', 'step:watch', 'main-action') + '<div class="sub" style="margin-top:14px">Mint price before signing.</div>';
    } else if (s === 'build') {
      head = 'Fighter builder';
      content += '<div class="split"><div>' + hero() + appearance() + '</div><div>' + inventory() + '</div></div>' + btn('Next: personality', 'step:personality', 'main-action') + chips(['onchain · NFT']);
    } else if (s === 'personality') {
      head = 'Personality'; content += personality() + btn('Next: pick AI', 'step:doors', 'main-action');
    } else if (s === 'agree') {
      head = 'Your say-so'; content += agreement();
    } else {
      head = 'Arena';
      var sh = buildSheet();
      content += hero() + receipt('<h2>' + esc(P.name || 'Newcomer') + '</h2><div class="notice" style="margin-top:12px">Fight. Fall. Respawn.</div>') +
        receipt('<div class="eyebrow">Saved in this browser</div>' + U.line('Preset', esc(P.preset)) + U.line('AI', esc(P.door ? P.door.identity : 'not connected')) + U.line('Wallet', esc(P.wallet ? (P.wallet.accountId || P.wallet.id) : 'none')) +
          '<div class="sub">The hosted arena is not live yet, so nothing has been minted or sent. Your sheet is ready to download.</div>') +
        (sh && !sh.error ? btn('Download sheet', 'sheet-download', 'main-action') : '') + btn('Open workshop', 'mode:workshop', 'textlink') + btn('Watch the arena', 'step:watch', 'textlink');
    }
    return { head: head, content: content };
  }
  function inventoryNote() { return (P.preset && !KNOWN_ART[PRESET_WEAPON[presetIdx()]]) ? '<div class="sub" role="status">Some weapon art pending</div>' : ''; }
  function viewWorkshop() {
    var tabs = [['battle', 'Battle'], ['inventory', 'Inventory'], ['look', 'Look'], ['persona', 'Persona'], ['card', 'Card'], ['agree', 'Agree'], ['respawn', 'Respawn']], t = V.tab, head = '', c = '';
    c = '<nav class="tabs" aria-label="Workshop">' + tabs.map(function (a) { return btn(a[1], 'tab:' + a[0], '', 'aria-label="' + a[1] + '" aria-current="' + (t === a[0] ? 'page' : 'false') + '" aria-pressed="' + (t === a[0]) + '"'); }).join('') + '</nav>';
    if (t === 'battle') { head = 'A few battle options'; c += presetGrid() + receipt(U.line(esc(P.preset), 'Preset sheet') + '<div class="sub">' + esc(ATTACK[P.preset.split(' ')[1]]) + ' Inventory changes each respawn.</div>') + btn('Pick inventory', 'tab:inventory', 'main-action'); }
    else if (t === 'inventory') { head = 'Inventory'; c += '<div class="split"><div class="desktop-portrait">' + hero() + '</div><div><div class="eyebrow">Starting menu</div>' + inventory() + '</div></div>' + btn('Next: look', 'tab:look', 'main-action'); }
    else if (t === 'look') { head = 'Appearance'; c += '<div class="split"><div>' + hero() + '</div><div>' + appearance() + '</div></div>' + btn('Next: persona', 'tab:persona', 'main-action'); }
    else if (t === 'persona') { head = 'Persona'; c += personaFile() + btn('Review agreement', 'tab:agree', 'main-action'); }
    else if (t === 'card') { head = 'Card'; c += cardTab(); }
    else if (t === 'agree') { head = 'Your say-so'; c += agreement(); }
    else { head = 'Respawn corner'; c += corner(); }
    return { head: head, content: c };
  }
  function viewLogin() {
    var v = D.view({ returning: !!root.SnapUI.store.get('trenchie.snapin.lastdoor'), walletChip: aiChip(), onContinue: V.mode === 'flow' ? 'Review terms' : 'Back to the arena' });
    return { head: v.head, content: v.html, ai: true };
  }

  // ------------------------------------------------------------------ render
  function render() {
    var flowAI = V.mode === 'flow' && (V.step === 'doors'), v = V.mode === 'login' || flowAI ? viewLogin() : V.mode === 'workshop' ? viewWorkshop() : viewFlow();
    var draft = v.ai ? 'b' : 'a', board = V.mode === 'login' || flowAI ? 'S4' : V.mode === 'workshop' ? 'S2' : 'S1';
    doc.body.className = 'draft-' + draft + ' board-' + board + (v.ai ? ' ai-mode' : '');
    if (V.closed) { app.innerHTML = '<div class="closed-preview">' + receipt('<h1>Arena</h1>' + btn('Open panel', 'reopen', 'main-action')) + '</div>'; }
    else if (v.watch) app.innerHTML = v.content;
    else app.innerHTML = '<main class="shell" data-material="wood"><div class="paper-surface"><header><div>' + (v.ai ? '' : '<div class="eyebrow">' + (V.mode === 'workshop' ? 'Persona workshop' : 'Snap into the arena') + '</div>') + '<h1>' + esc(v.head) + '</h1></div>' + btn('×', 'close', 'close', 'aria-label="Close panel"') + '</header>' + v.content + '<div class="status" id="feedback" aria-live="polite">' + esc(V.msg) + '</div></div></main>';
    var fb = doc.querySelector('#feedback'); if (fb && V.msgErr) fb.classList.add('err');
    root.requestAnimationFrame(function () { U.paint(app); root.__SNAPIN_READY = true; });
  }
  function say(m, err) { V.msg = m; V.msgErr = !!err; var fb = doc.querySelector('#feedback'); if (fb) { fb.textContent = m; fb.classList.toggle('err', !!err); } else render(); }

  // ------------------------------------------------------------------ actions
  function download(name, text) {
    var a = doc.createElement('a'); a.href = 'data:application/json;charset=utf-8,' + encodeURIComponent(text); a.download = name; doc.body.appendChild(a); a.click(); a.remove();
  }
  async function connectWallet(id) {
    var W = root.SnapWallet; if (!W) return say('The wallet module did not load. Reload the page.', true);
    V.busy = true; say('Opening ' + id + '…');
    try {
      var r = await W.connect(id, { network: 'mainnet' });
      if (r && (r.ok !== false) && (r.accountId || r.account)) { P.wallet = { id: id, accountId: r.accountId || r.account, network: r.network || 'mainnet' }; save(); V.step = 'presets'; V.msg = ''; render(); }
      else say('Wallet not connected: ' + ((r && (r.message || r.reason)) || 'no answer') + '. Keep watching, or try another wallet.', true);
    } catch (e) { say('Wallet not connected: ' + (e && e.message ? e.message : 'the wallet did not answer') + '. Keep watching, or try another wallet.', true); }
    V.busy = false;
  }
  async function onClick(e) {
    var b = e.target.closest('button'); if (!b || b.disabled) return;
    var a = b.dataset.act || '';
    if (a.indexOf('ai:') === 0) {
      if (a === 'ai:authorize') { P.resume = { mode: V.mode, step: V.step }; save(); }
      await D.act(a); return;
    }
    if (a.indexOf('step:') === 0) { V.closed = false; V.step = a.slice(5); V.msg = ''; if (V.step === 'doors') D.reset(); render(); }
    else if (a.indexOf('mode:') === 0) { V.mode = a.slice(5); V.msg = ''; render(); }
    else if (a.indexOf('tab:') === 0) { V.tab = a.slice(4); V.msg = ''; render(); }
    else if (a.indexOf('wallet:') === 0) connectWallet(a.slice(7));
    else if (a.indexOf('preset:') === 0) { var nm = a.slice(7), i = PRESETS.indexOf(nm); if (root.SNAPIN_SUPPLY && root.SNAPIN_SUPPLY[i] === 0) { P.preset = nm; V.step = 'claimed'; } else setPreset(nm); render(); }
    else if (a.indexOf('slot:') === 0) { var p = a.split(':'); P.slots[p[1]] = p[2]; save(); render(); }
    else if (a.indexOf('look:') === 0) { var l = a.split(':'); P.look = Object.assign({}, look()); P.look[l[1]] = l[2]; P.lookEdited = true; save(); render(); }
    else if (a.indexOf('temper:') === 0) { P.temper = a.slice(7); save(); render(); }
    else if (a.indexOf('quirk:') === 0) { var qk = a.slice(6), ix = P.quirks.indexOf(qk); if (ix >= 0) P.quirks.splice(ix, 1); else if (P.quirks.length < 3) P.quirks.push(qk); save(); render(); }
    else if (a === 'stake') { P.stake = !P.stake; save(); render(); }
    else if (a === 'move') { P.move = !P.move; save(); render(); }
    else if (a === 'sale-lock') { P.lock = !P.lock; save(); render(); }
    else if (a === 'close') { V.closed = true; render(); }
    else if (a === 'reopen') { V.closed = false; render(); }
    else if (a === 'agree') {
      if (![].slice.call(app.querySelectorAll('.checks input')).every(function (x) { return x.checked; })) return say('Tick all three to continue.', true);
      P.agreed = true; save(); V.step = 'ring'; render();
    }
    else if (a === 'ready') {
      var total = P.spread.reduce(function (s, n) { return s + Number(n || 0); }, 0), out = doc.querySelector('#locked');
      if (total !== 100) { out.textContent = 'Spread must total 100%.'; out.classList.add('err'); return; }
      var pick = { life: 'next', loadout: Object.assign({}, P.slots), spread: P.spread.map(Number), zeroKo: Number(P.zeroKo) || 0, stake: P.stake, move: P.move, lock: P.lock, at: new Date().toISOString() };
      U.store.set('trenchie.snapin.respawn', JSON.stringify(pick)); save();
      try { root.dispatchEvent(new root.CustomEvent('snapin:respawn-ready', { detail: pick })); } catch (er) { /* no listener */ }
      out.classList.remove('err'); out.textContent = (P.lock ? 'Sale lock requested.' : 'Next life ready.') + ' Saved in this browser; the arena reads it at respawn.';
    }
    else if (a === 'sheet-download') { var sh = buildSheet(); if (!sh || sh.error) return say('No sheet to download: ' + (sh && sh.error || 'the sheet module did not load'), true); download(sh.identity.role + '.json', JSON.stringify(sh, null, 2)); say('Sheet downloaded as ' + sh.identity.role + '.json.'); }
    else if (a === 'look-download') { var lf = root.SnapSheet && root.SnapSheet.lookFile(sheetState()); if (!lf) return say('The sheet module did not load.', true); download(lf.role + '.look.json', JSON.stringify(lf, null, 2)); say('Look file downloaded.'); }
    else if (a === 'sheet-copy') { var s2 = buildSheet(); var ok = s2 && !s2.error && await U.copyText(JSON.stringify(s2, null, 2)); say(ok ? 'Sheet copied.' : 'Could not copy. Use Download sheet.', !ok); }
    else if (a.indexOf('edit-slot:') === 0) { V.openSlot = a.slice(10); render(); }
  }
  function onInput(e) {
    var t = e.target;
    if (t.id === 'name') { P.name = t.value; save(); var g = root.SnapSheet && root.SnapSheet.guard(P.name || 'Newcomer'); var old = t.parentNode.querySelector('[role=alert]'); if (old) old.remove(); if (g && !g.ok) t.insertAdjacentHTML('afterend', '<div class="sub" role="alert">' + esc(g.reason) + '</div>'); }
    else if (t.id === 'personality') { P.voice = t.value; save(); }
    else if (t.id === 'zero-ko') { P.zeroKo = t.value; save(); }
    else if (t.dataset && t.dataset.spread != null) { P.spread[Number(t.dataset.spread)] = t.value; save(); var tot = P.spread.reduce(function (s, n) { return s + Number(n || 0); }, 0), el = doc.querySelector('#spread-total'); if (el) el.textContent = 'Spread totals ' + tot + '%'; }
  }

  // ------------------------------------------------------------------ boot
  async function boot() {
    app = doc.querySelector('#app');
    await root.SKA.init();
    D.attach({ repaint: render, board: V.mode,
      persona: function () { return P.name || ''; },
      onConnected: function (info) { P.door = info; save(); if (V.mode === 'flow') { V.step = 'doors'; } render(); },
      onDisconnected: function () { P.door = null; save(); },
      onContinue: function () { if (V.mode === 'flow') { V.step = 'agree'; } else { V.closed = true; } render(); } });
    D.reset();
    // OpenRouter returns with ?code=...: finish the PKCE exchange and resume where the player left
    var code = q.get('code');
    if (code && /^[\w.-]{8,}$/.test(code)) {
      if (P.resume) { V.mode = P.resume.mode; V.step = P.resume.step; }
      try { root.history.replaceState(null, '', root.location.pathname + (V.mode !== 'flow' ? '?mode=' + V.mode : '')); } catch (e) { /* ignore */ }
      render(); await D.finishOpenRouter(code); return;
    }
    var aiState = q.get('ai'); if (aiState) { D.preview(aiState, q.get('door') || 'NEAR AI Cloud', q.get('route') !== 'plan'); if (V.mode === 'flow' && V.step === 'watch') V.step = 'doors'; }
    if (V.mode === 'flow' && V.step === 'ai') V.step = 'doors';
    app.addEventListener('click', onClick); app.addEventListener('input', onInput);
    doc.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !V.closed && !(V.mode === 'flow' && V.step === 'watch')) { V.closed = true; render(); } });
    root.addEventListener('resize', function () { U.paint(app); });
    render();
  }
  root.Snapin = { boot: boot, state: P, view: V, render: render, buildSheet: buildSheet, setPreset: setPreset };
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', boot); else boot();
})(typeof globalThis !== 'undefined' ? globalThis : this);
