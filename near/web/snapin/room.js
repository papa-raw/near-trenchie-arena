/* snapin/room.js: the browser's own room client and keeper, so a fighter made in the guide fights in the arena.
 *
 * A classic script; window.SnapRoom. It speaks the same signed room protocol as near/arena/snap_client.py and the
 * keeper in near/arena/snap.py, over the same origin (snapin/serve.py in DEV; nginx when hosted):
 *   identity (DEV) -> manifest -> join challenge -> join (session-key proof) -> terms snapshot -> accept terms
 *   -> control challenge -> authenticate -> per life: the prediction (the respawn pick: preset, spread, zero) -> renew.
 * Every reply the room signs is checked against the room key the identity call returned; a reply that fails the check
 * is refused, never used.
 *
 * The session key: an Ed25519 key made by WebCrypto in this browser, NOT extractable (the page itself cannot read
 * the private half), kept in IndexedDB so a reload or the arena page can carry on with the same fighter. Only the
 * public half ever leaves the browser. Without IndexedDB (some private windows) the key lives in memory and a reload
 * starts over; the guide says so.
 *
 * One tab drives the fighter at a time (a Web Lock); the lease the room grants is renewed every few seconds while
 * a page holding the lock is open. Closing every tab stops the renewals and the room sends the fighter home.
 * An open chain-mode keeper returns after a host restart using the saved wallet authorization and original choices;
 * a bench hold or an explicit leave disables that return. Expired wallet authorization still requires sign-in.
 *
 * DEV: the identity is a session key, not a wallet or an NFT; the host labels the fighter "DEV" everywhere.
 */
(function (root) {
  'use strict';
  var SAVE = 'trenchie.snapin.room.v1', DB = 'trenchie-snapin', STORE = 'keys', KEY_ID = 'session';
  // the room takes a signed member read that expires within 15 s of its clock (room/service.py _OWNER_READ_WINDOW_MS); now()
  // below runs ahead of the room's between replies, so a read asks for 1 s less (as snap_client.py _MEMBER_READ_TTL_MS)
  var MEMBER_READ_TTL_MS = 15000 - 1000, ORDER_DEFAULT = { preset: null, spread: [40, 30, 20, 10], zero: 0 };
  var enc = new TextEncoder();

  // ------------------------------------------------------------------ canonical bytes (room/policy.py _canonical)
  function canon(v) {
    if (v === null || typeof v === 'boolean') return JSON.stringify(v);
    if (typeof v === 'number') { if (!Number.isInteger(v)) throw new Error('bad_message'); return String(v); }
    if (typeof v === 'string') {
      var out = '"';
      for (var i = 0; i < v.length; i++) {
        var c = v.charCodeAt(i);
        if (c >= 0xD800 && c <= 0xDFFF) {   // a surrogate pair is one character to Python; a lone half is refused there
          var d = v.charCodeAt(i + 1);
          if (c <= 0xDBFF && d >= 0xDC00 && d <= 0xDFFF) { out += v[i] + v[i + 1]; i++; continue; }
          throw new Error('bad_message');
        }
        out += c < 32 ? '\\u' + ('000' + c.toString(16)).slice(-4) : (v[i] === '"' || v[i] === '\\') ? '\\' + v[i] : v[i];
      }
      return out + '"';
    }
    if (Array.isArray(v)) return '[' + v.map(canon).join(',') + ']';
    if (typeof v === 'object') {
      var keys = Object.keys(v);
      if (keys.some(function (k) { return /[^\x00-\x7f]/.test(k); })) throw new Error('bad_message');
      keys.sort(function (a, b) { return a < b ? -1 : a > b ? 1 : 0; });
      return '{' + keys.map(function (k) { return canon(k) + ':' + canon(v[k]); }).join(',') + '}';
    }
    throw new Error('bad_message');
  }
  function without(v, exclude) { var o = {}; Object.keys(v).forEach(function (k) { if (exclude.indexOf(k) < 0) o[k] = v[k]; }); return o; }
  function canonicalBytes(v, exclude) { return enc.encode(canon(exclude ? without(v, exclude) : v)); }
  function hex(buf) { return Array.prototype.map.call(new Uint8Array(buf), function (b) { return ('0' + b.toString(16)).slice(-2); }).join(''); }
  async function digest(v, exclude) { return hex(await root.crypto.subtle.digest('SHA-256', canonicalBytes(v, exclude))); }
  function b64url(bytes) { var s = ''; new Uint8Array(bytes).forEach(function (b) { s += String.fromCharCode(b); }); return root.btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''); }
  function unb64url(t) { t = t.replace(/-/g, '+').replace(/_/g, '/'); while (t.length % 4) t += '='; var s = root.atob(t), u = new Uint8Array(s.length); for (var i = 0; i < s.length; i++) u[i] = s.charCodeAt(i); return u; }
  function concat(a, b) { var u = new Uint8Array(a.length + b.length); u.set(a, 0); u.set(b, a.length); return u; }
  var clone = function (v) { return JSON.parse(JSON.stringify(v)); };
  var same = function (a, b) { try { return canon(a) === canon(b); } catch (e) { return false; } };

  // ------------------------------------------------------------------ errors in plain words, each with its way out
  var WORDS = {
    proof_required: 'The arena did not accept this browser’s key. Snap in again to make a fresh one.',
    admission_closed: 'The arena is not taking new fighters right now. Keep watching and try again in a minute.',
    context_mismatch: 'The arena restarted since this fighter joined. Snap in again; your choices are kept.',
    stale_slot: 'Your seat was given up (the lease ran out). Snap in again; your choices are kept.',
    request_conflict: 'Two tabs tried to drive the same fighter. Close the other tab, then reload this one.',
    rate_limited: 'The arena is busy at a segment boundary. Trying again…',
    prediction_closed: 'The pick for this life closed before it arrived; it applies to your next life.',
    version_mismatch: 'The arena rules changed while you were reading them. Read them again and agree.',
    bad_message: 'The arena sent something this page could not read. Reload the page.',
    bad_receipt: 'The arena’s answer did not check out, so it was not used. Try again.',
    not_found: 'The arena does not know this fighter any more. Snap in again; your choices are kept.',
    challenge_expired: 'The arena’s handshake timed out on a busy machine. Trying again…',
    unreachable: 'Cannot reach the arena right now. Try again in a moment.'
  };
  // a code from the host is shown only as a known word or a plain identifier; anything else (it is unsigned) is "unknown error"
  function Refusal(code, detail) {
    var c = typeof code === 'string' && /^[a-z_]{1,40}$/.test(code) ? code : 'unknown_error';
    var e = new Error(WORDS[c] || (c === 'unknown_error' ? 'The arena answered with an unknown error. Try again.' : 'The arena said: ' + c + '.'));
    e.code = c; e.detail = typeof detail === 'string' ? detail.slice(0, 200) : ''; return e;
  }

  // ------------------------------------------------------------------ the session key (WebCrypto Ed25519, not extractable)
  var memKey = null, keyPersisted = false;
  function idb() {
    return new Promise(function (res, rej) {
      try { var r = root.indexedDB.open(DB, 1); r.onupgradeneeded = function () { r.result.createObjectStore(STORE); }; r.onsuccess = function () { res(r.result); }; r.onerror = function () { rej(r.error); }; }
      catch (e) { rej(e); }
    });
  }
  async function idbDo(mode, fn) {
    var db = await idb();
    return new Promise(function (res, rej) { var tx = db.transaction(STORE, mode), q = fn(tx.objectStore(STORE)); tx.oncomplete = function () { db.close(); res(q && q.result); }; tx.onerror = function () { db.close(); rej(tx.error); }; });
  }
  async function loadKey() {
    if (memKey) return memKey;
    try { var k = await idbDo('readonly', function (s) { return s.get(KEY_ID); }); if (k && k.privateKey && k.publicRaw) { memKey = k; keyPersisted = true; } } catch (e) { /* no IndexedDB: memory only */ }
    return memKey;
  }
  async function newKey() {
    var pair = await root.crypto.subtle.generateKey({ name: 'Ed25519' }, false, ['sign', 'verify']);
    var raw = await root.crypto.subtle.exportKey('raw', pair.publicKey);   // the public half only; the private half stays unreadable
    memKey = { privateKey: pair.privateKey, publicRaw: b64url(raw) };
    try { await idbDo('readwrite', function (s) { return s.put(memKey, KEY_ID); }); keyPersisted = true; } catch (e) { keyPersisted = false; }
    return memKey;
  }
  var premade = null;   // a session key made ahead of a chain-mode join, so the page can sign a ticket naming it
  async function forgetKey() { memKey = null; try { await idbDo('readwrite', function (s) { return s.delete(KEY_ID); }); } catch (e) { /* none */ } }
  async function sign(bytes) { var k = await loadKey(); return b64url(await root.crypto.subtle.sign({ name: 'Ed25519' }, k.privateKey, bytes)); }
  var roomKeys = {};
  async function verifyRoom(pub, bytes, sig) {
    try {
      if (!roomKeys[pub]) roomKeys[pub] = await root.crypto.subtle.importKey('raw', unb64url(pub), { name: 'Ed25519' }, false, ['verify']);
      return await root.crypto.subtle.verify({ name: 'Ed25519' }, roomKeys[pub], unb64url(sig), bytes);
    } catch (e) { return false; }
  }

  // ------------------------------------------------------------------ transport: same-origin fetch, room time from X-Dev-Now
  var seen = { now: 0, at: 0, paused: false };
  function now() { return seen.paused ? seen.now : seen.now + Math.round(root.performance.now() - seen.at); }
  async function call(method, target, body) {
    var r;
    try { r = await root.fetch(target, { method: method, headers: method === 'POST' ? { 'Content-Type': 'application/json' } : {}, body: method === 'POST' ? (body || new Uint8Array(0)) : undefined, cache: 'no-store' }); }
    catch (e) { throw Refusal('unreachable'); }
    var t = r.headers.get('X-Dev-Now'); if (t) { seen.now = Number(t); seen.at = root.performance.now(); seen.paused = r.headers.get('X-Dev-Paused') === '1'; }
    var v; try { v = await r.json(); } catch (e) { throw Refusal(r.status === 502 || r.status === 404 ? 'unreachable' : 'bad_message'); }   // 404: a page server with no room behind it
    if (r.status === 502) throw Refusal('unreachable');
    return v;
  }
  // a segment boundary answers rate_limited for a moment: the same bytes again shortly, never new ones
  async function send(method, target, body) {
    for (var i = 0; i < 40; i++) {
      var v = await call(method, target, body);
      if (v && v.type === 'error' && v.code === 'rate_limited') { await sleep(Math.min(1000, Number(v.retry_after_ms) || 250)); continue; }
      return v;
    }
    throw Refusal('rate_limited');
  }
  var sleep = function (ms) { return new Promise(function (r) { setTimeout(r, ms); }); };

  // ------------------------------------------------------------------ the client (snap_client.SnapClient, the parts a player uses)
  var S = null;   // the saved session: {ident, grant, seq, connection, order, life, lives, joinedAt, round}
  // the session lives in IndexedDB beside the key (a worker has no localStorage); writes are queued in order
  var saving = Promise.resolve();
  function persist() { var snap = S ? JSON.stringify(S) : null; saving = saving.then(function () { return idbDo('readwrite', function (st) { return snap ? st.put(snap, SAVE) : st.delete(SAVE); }); }).catch(function () { /* memory only */ }); return saving; }
  async function restore() { try { await saving; var v = JSON.parse((await idbDo('readonly', function (st) { return st.get(SAVE); })) || 'null'); return v && v.ident && v.grant ? v : null; } catch (e) { return null; } }
  function binding() { var g = S.grant, b = {}; ['context', 'grant_id', 'session_key_id', 'member_id', 'nft_token_id', 'persona_digest', 'slot_id', 'generation'].forEach(function (k) { b[k] = clone(g[k]); }); return b; }
  function checked(v, ctx) {
    if (v && v.type === 'error') throw Refusal(v.code);
    if (v && v.error) throw Object.assign(new Error(v.error), { code: 'host' });
    if (!v || !same(v.context, ctx || S.ident.context)) throw Refusal('context_mismatch');
    return v;
  }
  async function verified(v, ctx, ident) {
    v = checked(v, ctx); ident = ident || S.ident;
    if (v.key_id !== ident.key_id || !(await verifyRoom(ident.room_public_key, canonicalBytes(v, ['signature']), v.signature))) throw Refusal('proof_required');
    return v;
  }
  function unexpired(v) { if (Number(v.expires_at) <= now()) throw Refusal('proof_required'); }
  async function signed(v) { v.signature = await sign(canonicalBytes(v, ['signature'])); return v; }
  function controlUrl(ctx) { return 'wss://' + new URL(ctx.audience).host + '/room/control'; }

  async function member(route, action, version, requestId, payload) {
    var req = await signed(Object.assign(binding(), { domain: 'room.owner.v1', token: S.grant.token, kind: 'owner_control', action: action, request_id: requestId, terms_version: version, payload: payload || {} }));
    var reply = await verified(await send('POST', '/room/owner/' + route, canonicalBytes(req)));
    var d = await digest(req, ['signature']);
    if (reply.grant_id !== req.grant_id || reply.session_key_id !== req.session_key_id || reply.request_id !== requestId || reply.action !== action || reply.request_digest !== d ||
        reply.snapshot.viewer_member_id !== req.member_id || reply.snapshot.room_id !== S.ident.context.room_id) throw Refusal('context_mismatch');
    if (action === 'accept_terms' && (reply.state !== 'accepted' || !reply.snapshot.terms || reply.snapshot.terms.version !== version || reply.snapshot.terms.accepted !== true)) throw Refusal('version_mismatch');
    return reply.snapshot;
  }
  // control frames go one at a time: the room refuses a sequence number lower than one it has seen
  var chain = Promise.resolve();
  function serial(fn) { var p = chain.then(fn, fn); chain = p.catch(function () { /* the caller handles it */ }); return p; }
  function control(kind, payload, lifeId) { return serial(function () { return controlNow(kind, payload, lifeId); }); }
  async function controlNow(kind, payload, lifeId) {
    var DOMAIN = kind === 'prediction' ? 'room.prediction.v1' : 'room.control.v1';
    var seq = S.seq; S.seq = seq + 1; await persist();   // the high-water mark moves before the send, so a reload never reuses a number
    var req = await signed(Object.assign(binding(), { domain: DOMAIN, sequence: String(seq), life_id: lifeId == null ? null : lifeId, kind: kind, payload: payload }));
    var reply = await verified(await send('POST', '/room/control/frame?cid=' + encodeURIComponent(S.connection), canonicalBytes(req)));
    var d = await digest(req, ['signature']);
    if (reply.grant_id !== req.grant_id || reply.session_key_id !== req.session_key_id || reply.sequence !== req.sequence || reply.message_domain !== DOMAIN || reply.request_digest !== d) throw Refusal('context_mismatch');
    if (kind === 'prediction' && reply.state === 'accepted' && (!reply.prediction_lock || reply.prediction_lock.life_id !== lifeId || reply.prediction_lock.prediction_hash !== d)) throw Refusal('prediction_closed');
    return reply;
  }
  // ------------------------------------------------------------------ battle frames (the host's signed battle envelope v1)
  // The same control connection and the same sequence as every other frame; the reply is the room's signed battle_receipt,
  // accepted only after its signature (the pinned room key), its binding, kind, sequence, life and request digest all check.
  // The caller gets the whole envelope; a UI shows envelope.ack.summary verbatim.
  var BATTLE = 'arena.battle.v1', BATTLE_RECEIPT = 'arena.battle.receipt.v1';
  function battle(kind, payload) { return serial(function () { return battleNow(kind, payload); }); }
  async function battleNow(kind, payload) {
    if (!S || !S.connection || !S.life) throw Refusal('not_found');
    var seq = S.seq; S.seq = seq + 1; await persist();
    var req = await signed(Object.assign(binding(), { domain: BATTLE, kind: kind, sequence: String(seq), life_id: S.life, payload: payload }));
    var reply = await send('POST', '/room/control/frame?cid=' + encodeURIComponent(S.connection), canonicalBytes(req));
    if (reply && reply.type === 'error') throw Refusal(reply.code);   // the room's own refusal, as it says it
    try { reply = await verified(reply); } catch (e) { throw Refusal('bad_receipt'); }
    var d = await digest(req, ['signature']), b = binding();
    if (reply.domain !== BATTLE_RECEIPT || reply.type !== 'battle_receipt' || reply.kind !== kind || reply.sequence !== req.sequence || reply.life_id !== req.life_id || reply.request_digest !== d ||
        Object.keys(b).some(function (k) { return !same(reply[k], b[k]); })) throw Refusal('bad_receipt');
    if (!reply.ack || typeof reply.ack !== 'object' || typeof reply.ack.summary !== 'string') throw Refusal('bad_receipt');
    return reply;
  }

  async function notice(n) {
    n = await verified(n);
    var b = binding(), bad = Object.keys(b).some(function (k) { return !same(n[k], b[k]); });
    if (bad || !same(n.reservation.binding, Object.assign({}, b, { account_id: S.grant.account_id }))) throw Refusal('stale_slot');
    return n;
  }
  async function authenticate() {
    for (var tries = 0; ; tries++) {
      try { return await authenticateOnce(); }
      catch (e) { if (e.code !== 'challenge_expired' || tries >= 2) throw e.code === 'challenge_expired' ? Refusal('proof_required') : e; await sleep(1000 * (tries + 1)); }   // the room keeps 2 open challenges per address for 10 s
    }
  }
  async function authenticateOnce() {
    var ch = await verified(await send('POST', '/room/control/open', new Uint8Array(0)));
    if (Number(ch.expires_at) <= now()) throw Refusal('challenge_expired');
    var rid = 'web-control-' + now();
    var req = await signed(Object.assign(binding(), { domain: 'room.control.v1', kind: 'authenticate', request_id: rid, token: S.grant.token, challenge: ch }));
    var ready = await verified(await send('POST', '/room/control/frame?cid=' + encodeURIComponent(ch.connection_id), canonicalBytes(req)));
    var d = await digest(req, ['signature']), b = binding();
    if (Object.keys(b).some(function (k) { return !same(ready[k], b[k]); }) || ready.connection_id !== ch.connection_id || ready.request_id !== rid || ready.request_digest !== d) throw Refusal('context_mismatch');
    S.connection = ch.connection_id; S.lastRenew = now(); persist();
    if (ready.next_life) await filePrediction(await notice(ready.next_life));
    return ready;
  }

  // ------------------------------------------------------------------ join retries under the room's join limit
  // The room allows 5 join attempts a minute per address and per account (room/service.py _attempt,
  // join_attempts_per_minute), and a try is a challenge plus a join: 2 attempts. A challenge is used up by its join
  // (room/identity.py resolve pops it before the chain read), so it can't be reused. So at most 2 tries in any
  // JOIN_WINDOW_MS of room time (4 attempts, one spare; the room counts on its own clock, which a join hold freezes for
  // up to 10 s): a quick second try JOIN_GAP_MS of real time after the first (a read that lands in a few seconds seats
  // at once), then each try waits until the try before last has left the window on the room's clock. The page asks for
  // up to JOIN_WAIT_MS of real time.
  var JOIN_GAP_MS = 8000, JOIN_WINDOW_MS = 63000, JOIN_WAIT_MS = 180000, JOIN_REFRESH_MS = 1000;
  function joinNextAt(tries) {   // room time from which the next try fits the window (tries: room times so far)
    return tries.length >= 2 ? tries[tries.length - 2] + JOIN_WINDOW_MS : -Infinity;
  }
  async function joinWithWait(tryOnce, io) {
    var started = io.real(), tries = [], reply;
    for (;;) {
      tries.push(io.room());
      var sent = io.real();
      reply = await tryOnce();
      if (!(reply && reply.type === 'error' && reply.code === 'ownership_unavailable')) return reply;
      if (io.real() - started >= JOIN_WAIT_MS) return reply;
      // the window waits on the room's clock, refreshed by a read that costs no attempt (it stands still while paused)
      var next = joinNextAt(tries);
      while (io.real() - sent < JOIN_GAP_MS || io.room() < next) {
        io.waiting(Math.max(1, Math.ceil(Math.max(JOIN_GAP_MS - (io.real() - sent), next - io.room()) / 1000)));
        await io.sleep(JOIN_REFRESH_MS);
        await io.refresh();
      }
    }
  }

  // ------------------------------------------------------------------ the keeper: per-life pick, lease renewals
  var SEAT_QUEUE_CODES = ['room_full', 'ownership_unavailable'];   // the room locked the pick and queued the seat
  function predictionPayload(o) {
    var s = (o.spread || ORDER_DEFAULT.spread).map(function (n) { return Math.round(Number(n) * 100); });
    return { loadout: { menu_row: o.preset, bag_serials: [] }, spread_bps: { one: s[0], two: s[1], three: s[2], four_plus: s[3] }, zero_bps: Math.round(Number(o.zero || 0) * 100), stake: null, moves: [], lock: false };
  }
  async function filePrediction(n) {
    var life = n.reservation.life_id;
    if (S.life !== life) { S.lives = (S.lives || 0) + 1; S.life = life; S.lifeAt = Date.now(); }
    persist();
    // Re-authentication can announce this life again. Ready edits the following life, so keep this one's decision.
    if (S.lastPick && S.lastPick.life === life && /^(none|accepted|queued)$/.test(S.lastPick.state)) { emit(); return null; }
    if (now() >= Number(n.reservation.prediction_deadline)) { note('The pick for ' + life + ' closed before this page could send it; the room used its default.'); return null; }
    // the player's AI may choose to file no prediction for a life (F75's explicit marker): nothing is sent and the room locks "none"
    if (S.order && S.order.prediction === false) { S.lastPick = { life: life, state: 'none', order: clone(S.order), at: Date.now() }; persist(); emit(); return null; }
    var r = await control('prediction', predictionPayload(S.order), life);
    // a full ring (or an owner check still running) refuses the seat, not the pick: the room has locked this prediction
    // for this life and seats it, same life and same lock, when a place opens (as snap.py: SEAT_QUEUE_CODES)
    var state = r.state === 'refused' && SEAT_QUEUE_CODES.indexOf(r.code) >= 0 ? 'queued' : r.state;
    S.lastPick = { life: life, state: state, reason: r.state === 'accepted' ? null : (r.reason || r.code || null), order: clone(S.order), at: Date.now() }; persist(); emit();   // a refusal keeps its reason
    return r;
  }
  var listeners = [], status = { phase: 'idle', step: '', message: '', error: null }, loop = null, notes = [];
  function emit() { var s = api.status(); listeners.forEach(function (f) { try { f(s); } catch (e) { /* listener */ } }); }
  function set(phase, step, message, error) { status = { phase: phase, step: step || '', message: message || '', error: error ? { code: error.code || '', message: error.message || String(error), detail: error.detail || '' } : null }; emit(); }
  function note(m) { notes.push({ at: Date.now(), text: m }); notes = notes.slice(-5); emit(); }

  async function tick() {
    if (!S || !S.connection) return;
    var lim = S.limits || { heartbeat_ms: 10000 };
    if (now() - (S.lastRenew || 0) >= Number(lim.heartbeat_ms) - 2000) { await control('renew', { lease_until: String(now() + 30000) }, null); S.lastRenew = now(); persist(); }
    var list = await send('GET', '/room/control/private?cid=' + encodeURIComponent(S.connection));
    if (list && list.type === 'error') throw Refusal(list.code);
    for (var i = 0; i < (list || []).length; i++) { var n = await notice(list[i]); if (n.reservation.life_id !== S.life) await filePrediction(n); }
    // a queued pick (locked, seat refused while the ring was full) is seated with the same lock when a place opens; the
    // public view says when this fighter is in the ring, at no join attempt
    var lp = S.lastPick;
    if (lp && lp.state === 'queued' && !lp.seated && lp.life === S.life && Date.now() - (S.seatCheckAt || 0) >= 2000) {
      S.seatCheckAt = Date.now();
      var ob = null; try { ob = await call('GET', '/room/observe'); } catch (e) { ob = null; }
      if (seatSeen(ob, S.ident.nft_token_id)) { lp.seated = Date.now(); persist(); emit(); }
    }
  }
  function seatSeen(ob, token) {
    return !!(ob && (ob.fighters || []).some(function (f) { return f.nft_token_id === token && (f.state === 'ring' || f.state === 'disconnected'); }));
  }
  async function rejoinRestart() {
    var saved = S;
    if (!saved || !saved.rejoin || !saved.rejoin.chain || saved.benchHold || stopped || status.phase === 'leaving') return false;
    var health = await call('GET', '/dev/health');
    if (!health.room_public_key || health.room_public_key === saved.ident.room_public_key) return false;
    if (!root.SnapIdentity && typeof root.importScripts === 'function') root.importScripts('identity.js');
    if (!root.SnapIdentity) throw Refusal('proof_required');
    var options = clone(saved.rejoin), key = await loadKey();
    if (!key) throw Refusal('proof_required');
    options.order = clone(saved.order); options.rejoining = true;
    options.waitFor = null; options.ownHeldResult = false;
    options.chain.session_public_key = key.publicRaw;
    options.chain.ticket = await root.SnapIdentity.ticket(saved.ident.nft_token_id, {
      session_public_key: key.publicRaw, name: options.name, preset: options.preset, rejoin: true
    });
    if (S !== saved || !saved.rejoin || saved.benchHold || stopped || status.phase === 'leaving') return false;
    set('joining', 'identity', 'The arena restarted. Bringing your Trenchie back…');
    await joinOnce(options, saved);
    return true;
  }
  async function recoverRestart(error) {
    if (['proof_required', 'stale_slot', 'context_mismatch', 'not_found'].indexOf(error.code) < 0) return false;
    return rejoinRestart();
  }
  function runLoop() {
    if (loop) return;
    var fails = 0;
    loop = (async function () {
      while (S && S.connection && !stopped) {
        // a tick that comes back after the session ended (a leave, an error) is stale: it never brings back 'in'; and a leave
        // in progress keeps saying 'leaving' (the keeper still renews the seat until the leave frame lands)
        try { await tick(); fails = 0; if (S && !stopped && status.phase !== 'in' && status.phase !== 'leaving') set('in', 'ring', ''); }
        catch (e) {
          if (!S || stopped) break;
          fails++;
          try { if (await recoverRestart(e)) { fails = 0; continue; } } catch (recovery) { e = recovery; }
          if (e.code === 'unreachable' && (fails < 20 || S.rejoin)) { if (status.phase !== 'leaving') set('offline', '', 'Lost the arena for a moment. Retrying…', e); await sleep(1500); continue; }
          if (e.code === 'proof_required' || e.code === 'stale_slot' || e.code === 'context_mismatch' || e.code === 'not_found') { await end(e); return; }
          if (fails >= 5) { await end(e); return; }
        }
        await sleep(400);
      }
    })().finally(function () { loop = null; });
  }
  var stopped = false;
  async function end(err) { stopped = true; S = null; await persist(); set('ended', '', err ? err.message : 'Your Trenchie swam home.', err || null); }

  // one tab drives the fighter: the lock is held while this page runs the keeper
  var holding = false;
  function withLock(fn) {
    if (!root.navigator.locks || holding) return fn();   // this worker already holds it: never "another tab" for its own lock
    return new Promise(function (res, rej) {
      root.navigator.locks.request('trenchie-keeper', { ifAvailable: true }, async function (lock) {
        if (!lock) { set('elsewhere', '', 'Your Trenchie is being driven from another tab. Close that tab to drive it here.'); res(false); return; }
        holding = true;
        try { await fn(); res(true); } catch (e) { holding = false; rej(e); return; }
        await new Promise(function (hold) { var t = setInterval(function () { if (!S || stopped) { clearInterval(t); hold(); } }, 1000); });
        holding = false;
      }).catch(rej);
    });
  }

  // ------------------------------------------------------------------ the public api
  var api = {
    canonicalBytes: canonicalBytes, digest: digest, canon: canon, WORDS: WORDS,
    supported: function () { return !!(root.crypto && root.crypto.subtle && root.fetch && root.TextEncoder); },
    saved: async function () { var v = await restore(); return v ? { id: v.ident.nft_token_id, name: v.name } : null; },
    status: function () { return Object.assign({}, status, { fighter: S && S.ident ? { id: S.ident.nft_token_id, name: S.name, preset: S.order && S.order.preset, life: S.life, lives: S.lives || 0, lastPick: S.lastPick || null, joinedAt: S.joinedAt } : null, keyPersisted: keyPersisted, notes: notes.slice() }); },
    on: function (f) { listeners.push(f); f(api.status()); return function () { listeners = listeners.filter(function (x) { return x !== f; }); }; },
    terms: async function () { var t = await send('GET', '/dev/terms'); if (!t || t.error || !t.version) throw Refusal('bad_message'); return t; },
    /* join: {name, preset, sheet?, look?, termsVersion, order:{preset, spread:[4 percents], zero}}; resolves to the status when the fighter is in */
    /* sessionKey: make this browser's session key now and answer its public half (chain mode: the page's register ticket
       names it, so a seen ticket can't seat another key); the next join uses it */
    sessionKey: async function () { await forgetKey(); var k = await newKey(); premade = k.publicRaw; return k.publicRaw; },
    join: async function (o) {
      stopped = false;
      try { return await joinOnce(o); }
      catch (e) { S = null; stopped = true; await persist(); set('error', status.step, e.message, e); throw e; }
    },
    /* resume: carry on with a saved fighter (after a reload, or on the arena page) */
    resume: async function () {
      if (S && S.connection && loop) return api.status();   // already driving (and retrying if the arena is away)
      var saved = await restore(); if (!saved) { set('none', '', ''); return null; }   // 'none': checked, nothing saved
      S = saved; stopped = false;
      if (!(await loadKey())) { await end(Object.assign(new Error('This browser forgot the fighter’s key (private window or cleared site data). Snap in again; your choices are kept.'), { code: 'no-key' })); return api.status(); }
      await withLock(async function () {
        set('joining', 'control', 'Reconnecting to your Trenchie…');
        try { await call('GET', '/dev/clock'); await authenticate(); set('in', 'ring', ''); runLoop(); }
        catch (e) {
          try { if (await recoverRestart(e)) return; } catch (recovery) { e = recovery; }
          if (e.code === 'unreachable') { set('offline', '', e.message, e); runLoop(); return; }
          await end(e);
        }
      });
      return api.status();
    },
    /* an order for this life (the player's AI): {focus, avoid, loot, sig, say}; fields left out keep the room's defaults.
       Orders are spaced 2 s apart on room time; one refused for spacing is sent again once. Resolves to the room's receipt. */
    intent: async function (o) {
      if (!S || !S.connection || !S.life) throw Refusal('not_found');
      o = o || {};
      var payload = { fighter_id: S.ident.nft_token_id, focus: o.focus == null ? null : String(o.focus), avoid: o.avoid == null ? null : String(o.avoid),
                      loot: o.loot === 'ignore' ? 'ignore' : 'nearest', sig: /^(hold|use)$/.test(o.sig) ? o.sig : 'auto', leave: false, say: o.say == null ? null : String(o.say).slice(0, 280) };
      for (var k = 0; k < 2; k++) {
        var r = await control('intent', payload, S.life);
        if (r.state === 'accepted' || r.code !== 'rate_limited') return r;
        await sleep(2100);
      }
      return r;
    },
    /* a behaviour for this life (the player's AI, the engine's raw behaviour object): the room's signed battle_receipt, checked */
    behaviour: function (payload) { if (!payload || typeof payload !== 'object') return Promise.reject(Refusal('bad_message')); return battle('behaviour', payload); },
    /* the bench (board 1): {hold: true|false} (false = Send back in) or {equip: {slot, item_id}}; the room's signed battle_receipt,
       checked; ack {type: 'bench_ack', status: 'applied'|'refused', bench, summary} */
    bench: function (payload) {
      if (!payload || typeof payload !== 'object') return Promise.reject(Refusal('bad_message'));
      if (S && typeof payload.hold === 'boolean') { S.benchHold = payload.hold; persist(); }
      return battle('bench', payload);
    },
    /* a line for the feed with its emoji (or null): the room's signed battle_receipt, checked; ack.summary says posted/blocked/muted */
    speech: function (o) { o = o || {}; var t = String(o.text == null ? '' : o.text).trim(); if (!t) return Promise.reject(Refusal('bad_message')); return battle('speech', { text: t, emoji: o.emoji == null ? null : String(o.emoji) }); },
    /* the next life's pick (the corner): applies from the next life the room announces */
    setOrder: function (o) {
      if (!S) return false; o = Object.assign({}, o);
      if (o.prediction === undefined && (o.spread || o.zero != null)) o.prediction = true;   // a new spread means: file it
      S.order = Object.assign({}, S.order, o); persist(); emit(); return true;
    },
    leave: async function () {
      if (!S) return;
      S.rejoin = null; await persist();   // the player's leave choice wins even if the host disappears during it
      var who = S.name, id = S.ident.nft_token_id;
      set('leaving', '', 'Swimming home…');
      // the fighter swims home (an order with leave), then the seat is given up; if either fails the lease ends it within 30 s
      for (var k = 0; k < 3; k++) {   // orders are spaced 2 s apart on room time: a refused-for-spacing order is sent again
        try { if (!S.connection || !S.life) break; var rr = await control('intent', { fighter_id: id, focus: null, avoid: null, loot: 'nearest', sig: 'auto', leave: true, say: null }, S.life); if (rr.state === 'accepted' || rr.code !== 'rate_limited') break; } catch (e) { break; }
        await sleep(2100);
      }
      try { if (S.connection) await control('leave', { reason: 'leave' }, S.life); } catch (e) { /* lease */ }
      lastLeft = { name: String(who || '').toLowerCase(), id: id, at: Date.now() };
      await end(null);
      // then read the round's result once, in the background: the DEV host holds the next join while a left player's result is unread
      (async function () { for (var i = 0; i < 4; i++) { try { var r = await call('GET', '/room/result?segment_id=segment%3A0'); if (r && r.type !== 'error') return; } catch (e) { return; } await sleep(1500); } })();
    },
    observe: async function () { return send('GET', '/room/observe'); },
    _now: now
  };
  var lastLeft = null;
  // the round's signed result, read from the public endpoint and kept in this browser (IndexedDB 'last-result', else memory)
  var lastResult = null;
  async function keepResult() {
    try {
      var r = await call('GET', '/room/result?segment_id=segment%3A0');
      if (!r || r.type === 'error' || r.error) return null;
      lastResult = { at: Date.now(), result: r };
      try { await idbDo('readwrite', function (st) { return st.put(JSON.stringify(lastResult), 'last-result'); }); } catch (e) { /* memory only */ }
      note('Read and kept the last round’s result.');
      return r;
    } catch (e) { return null; }
  }
  async function joinOnce(o, previous) {
    var ran = await withLock(async function () {
        set('joining', 'key', 'Making this browser’s key…');
        if (!api.supported()) throw Object.assign(new Error('This browser cannot make the key the arena needs (WebCrypto Ed25519). Use a current Chrome, Edge, Firefox or Safari.'), { code: 'unsupported' });
        var k;   // chain mode: the key the page's ticket already names (sessionKey below); else a fresh one
        if (o.rejoining) { k = await loadKey(); if (!k) throw Refusal('proof_required'); }
        else if (o.chain && premade && memKey && memKey.publicRaw === premade && o.chain.session_public_key === premade) k = memKey;
        else { await forgetKey(); k = await newKey(); }
        premade = null;
        // a new trenchie right after this browser's last one left: the host frees the seat at once but keeps the old fighter
        // until it has swum home, and refuses that seat meanwhile (stale_slot). Wait for it on the public view, which costs
        // no join attempt (the host allows only a few a minute per address), then join.
        // The page names it (o.waitFor, kept in its draft across a reload); this worker also remembers its own last leave.
        var swimmer = o.waitFor || (lastLeft && Date.now() - lastLeft.at < 60000 ? lastLeft.id : null);
        for (var sw = 0; sw < 30 && swimmer; sw++) {
          var ob = null; try { ob = await call('GET', '/room/observe'); } catch (e) { break; }
          if (!(ob && ob.fighters || []).some(function (f) { return f.fighter_id === swimmer; })) break;
          set('joining', 'identity', 'Your last Trenchie is still swimming home…'); await sleep(1000);
        }
        set('joining', 'identity', o.chain ? 'Registering ' + o.chain.nft_token_id + ' with the arena (owner read on ' + o.chain.network + ')…' : 'Registering your Trenchie with the DEV arena…');
        await call('GET', '/dev/clock');
        var body = { name: o.name, preset: o.preset, public_key: k.publicRaw }; if (o.sheet) body.sheet = o.sheet; if (o.look) body.look = o.look;
        if (o.chain) { body.ticket = o.chain.ticket; body.nft_token_id = o.chain.nft_token_id; }   // chain mode: a one-use ticket signed by the page that signed in
        var ident = await call('POST', '/dev/identity', enc.encode(JSON.stringify(body)));
        if (previous && (S !== previous || !previous.rejoin || previous.benchHold || stopped)) return;
        // this browser's own fighter, still swimming home from a leave a moment ago: wait for it rather than call it a clash
        for (var w = 0; w < 15 && ident && /seated right now/.test(ident.error || '') && lastLeft && lastLeft.name === String(o.name).toLowerCase() && Date.now() - lastLeft.at < 45000; w++) {
          set('joining', 'identity', 'Your Trenchie is still swimming home from the last round…'); await sleep(2000);
          ident = await call('POST', '/dev/identity', enc.encode(JSON.stringify(body)));
        }
        // the last round's result is still unread (a seat that lapsed with no page open): the DEV host holds new joins until
        // its player reads it, or until its grace ends. Only that player's own browser reads it (o.ownHeldResult: the draft's
        // ended trenchie is the one snapping back in) and keeps it here, which lifts the hold; anyone else waits out the
        // host's own countdown and never reads another fighter's result. A browser player never gets a command to run.
        var mineHeld = !!o.ownHeldResult;
        for (var u = 0; u < 200 && ident && /result its player has not read/.test(ident.error || ''); u++) {
          var secs = Number(((ident.error || '').match(/retry in (\d+) s/) || [])[1]) || 0;
          set('joining', 'identity', mineHeld && u === 0 ? 'Reading the last round’s result…' : (mineHeld ? 'Back in the ring in ' : 'In the ring in ') + Math.max(1, secs) + ' s…');
          if (mineHeld && u % 5 === 0) await keepResult();
          await sleep(1000);
          ident = await call('POST', '/dev/identity', enc.encode(JSON.stringify(body)));
        }
        if (!ident || !ident.nft_token_id) throw Object.assign(new Error(friendlyHost(ident && ident.error)), { code: 'host', detail: ident && ident.error });
        S = { ident: ident, grant: null, seq: 1, connection: null, order: Object.assign({}, ORDER_DEFAULT, o.order || {}, { preset: (o.order && o.order.preset) || o.preset }), name: o.name, life: null, lives: 0, joinedAt: Date.now() };
        if (o.chain) { S.rejoin = clone(o); delete S.rejoin.chain.ticket; }
        set('joining', 'join', 'Asking the room for a seat…');
        var manifest = checked(await send('GET', '/room'), ident.context);
        if (manifest.admission !== 'open') throw Refusal('admission_closed');
        if ((manifest.proof_methods || []).indexOf(ident.proof_method) < 0) throw Refusal('proof_required');
        // a token's first life waits for the chain's owner and inventory reads: the room answers ownership_unavailable
        // until they land (server.py reserve_life), so the join is asked again (joinWithWait: paced under the room's limit)
        var spk = clone(ident.session_public_key), rid, creq, ch, jreq, grant;
        grant = await joinWithWait(async function () {
          rid = 'web-join-' + now();
          creq = { domain: 'room.join.v1', context: clone(ident.context), grant_id: null, session_key_id: null, account_id: ident.account_id, nft_token_id: ident.nft_token_id,
                       persona_digest: ident.persona_digest, session_public_key: spk, request_id: rid, purpose: 'join' };
          ch = await verified(await send('POST', '/room/challenge', canonicalBytes(creq)), ident.context, ident);
          if (Object.keys(creq).some(function (k2) { return !same(ch[k2], creq[k2]); })) throw Refusal('context_mismatch');
          unexpired(ch);
          jreq = { domain: 'room.join.v1', context: clone(ident.context), grant_id: null, session_key_id: null, challenge: ch, persona_digest: ident.persona_digest,
                       session_public_key: spk, request_id: rid, declared_compute: o.compute || { harness: 'browser', model: 'player-choice', source: 'owner', effort: 'standard' }, resume: null };
          jreq.proof = { method_id: ident.proof_method, key_id: 'dev_local', proof_bytes: await sign(concat(enc.encode('dev-wallet|'), canonicalBytes(jreq))) };
          return send('POST', '/room/join', canonicalBytes(jreq));
        }, { room: now, real: function () { return root.performance.now(); }, sleep: sleep,
             refresh: function () { return call('GET', '/dev/clock').catch(function () { return null; }); },
             waiting: function (secs) { set('joining', 'join', 'Waiting for the chain to read your Trenchie’s owner… asking again in ' + secs + ' s'); } });
        if (grant && grant.status === 'spectating') throw Object.assign(new Error('The ring is full: you are queued as a spectator. Keep watching; try again when a seat frees up.'), { code: 'queued' });
        grant = await verified(grant, ident.context, ident);
        var jd = await digest(jreq, ['proof']);
        if (grant.account_id !== ident.account_id || grant.nft_token_id !== ident.nft_token_id || grant.request_id !== rid || grant.request_digest !== jd || grant.message_domain !== 'room.join.v1') throw Refusal('context_mismatch');
        if (grant.control_url !== controlUrl(ident.context) || grant.persona_digest !== ident.persona_digest || !same(grant.session_public_key, spk)) throw Refusal('context_mismatch');
        unexpired(grant);
        S.grant = grant; persist();
        set('joining', 'terms', 'Agreeing to the arena rules…');
        var snap = await member('snapshot', 'snapshot', '0', 'web-read-terms-' + now(), { expires_at: String(now() + MEMBER_READ_TTL_MS) });
        if (!snap.terms || snap.terms.version !== o.termsVersion) throw Object.assign(new Error('The arena rules are now version ' + (snap.terms && snap.terms.version) + '; you agreed to version ' + o.termsVersion + '. Read them again and agree.'), { code: 'version_mismatch' });
        await member('terms/accept', 'accept_terms', snap.terms.version, 'web-accept-terms-' + now());
        S.limits = (checked(await send('GET', '/room'), ident.context).limits) || { heartbeat_ms: '10000' };
        set('joining', 'control', 'Taking the controls…');
        await authenticate();
        set('in', 'ring', ''); runLoop();
    });
    return api.status();   // ran === false: another tab drives this fighter; the status says so
  }
  function friendlyHost(e) {
    e = String(e || 'no answer');
    if (/seated right now/.test(e)) return 'A fighter with that name is in the ring right now.';
    if (/name needs letters/.test(e)) return 'The name needs at least one letter or digit.';
    if (/preset must be one of|unknown preset/.test(e)) return 'The arena does not know this battle option yet (' + e + ').';
    if (/result its player has not read/.test(e)) return 'The arena is still finishing the last round. Snap in again in a minute.';   // never the agent's command
    return 'The arena refused the fighter: ' + e;
  }

  // ------------------------------------------------------------------ where it runs
  // In a page this file starts itself again as a dedicated Worker and talks to it: the keeper then runs on its own
  // thread, so a busy page (the arena's WebGL) or a background tab's slowed timers never let the lease lapse.
  // The worker holds the key, the session and the tab lock; the page gets plain status objects.
  var inWorker = typeof root.document === 'undefined' && typeof root.postMessage === 'function' && typeof root.importScripts === 'function';
  if (inWorker) {
    api.on(function (st) { root.postMessage({ status: st }); });
    root.onmessage = async function (e) {
      var m = e.data || {}, fn = api[m.cmd];
      try { var r = typeof fn === 'function' ? await fn(m.arg) : undefined; root.postMessage({ id: m.id, ok: true, r: r === undefined ? null : JSON.parse(JSON.stringify(r)) }); }
      catch (err) { root.postMessage({ id: m.id, ok: false, message: err.message, code: err.code || '' }); }
    };
    return;
  }
  var src = root.document.currentScript && root.document.currentScript.src, worker = null, seq = 0, waiting = {}, last = api.status(), subs = [], FLAG = 'trenchie.snapin.fighter';
  function flag(v) { try { if (v) root.localStorage.setItem(FLAG, JSON.stringify(v)); else root.localStorage.removeItem(FLAG); } catch (e) { /* this page only */ } }
  function boot() {
    if (worker || !src || !root.Worker) return worker;
    worker = new root.Worker(src);
    worker.onmessage = function (e) {
      var m = e.data || {};
      if (m.status) {
        last = m.status;
        if (last.fighter && /^(in|joining|offline|elsewhere)$/.test(last.phase)) flag({ id: last.fighter.id, name: last.fighter.name });
        else if (/^(ended|error|none)$/.test(last.phase)) flag(null);   // a fresh worker's first 'idle' is not news
        subs.forEach(function (f) { try { f(last); } catch (x) { /* listener */ } });
      } else if (m.id && waiting[m.id]) { var w = waiting[m.id]; delete waiting[m.id]; if (m.ok) w[0](m.r); else w[1](Object.assign(new Error(m.message), { code: m.code })); }
    };
    worker.onerror = function (e) { last = Object.assign({}, last, { phase: 'error', message: 'The arena client stopped: ' + (e.message || 'worker error') + '. Reload the page.' }); subs.forEach(function (f) { f(last); }); };
    return worker;
  }
  function ask(cmd, arg) {
    if (!boot()) return Promise.reject(Object.assign(new Error('This browser cannot run the arena client (no Web Worker). Use a current Chrome, Edge, Firefox or Safari.'), { code: 'unsupported' }));
    return new Promise(function (res, rej) { var id = ++seq; waiting[id] = [res, rej]; worker.postMessage({ id: id, cmd: cmd, arg: arg }); });
  }
  root.SnapRoom = {
    canonicalBytes: canonicalBytes, digest: digest, canon: canon, WORDS: WORDS,
    // pure pieces the worker runs, for the tests: the join pacing, the queued-pick seat check, the member-read expiry
    joinWithWait: joinWithWait, seatSeen: seatSeen, MEMBER_READ_TTL_MS: MEMBER_READ_TTL_MS, joinNextAt: joinNextAt,
    supported: function () { return !!(root.Worker && root.crypto && root.crypto.subtle); },
    // a quick, synchronous hint for the page (the worker confirms on resume): is a fighter saved in this browser?
    saved: function () { try { return JSON.parse(root.localStorage.getItem(FLAG) || 'null'); } catch (e) { return null; } },
    status: function () { return last; },
    on: function (f) { subs.push(f); f(last); boot(); return function () { subs = subs.filter(function (x) { return x !== f; }); }; },
    terms: function () { return ask('terms'); },
    sessionKey: function () { return ask('sessionKey'); },
    join: function (o) { return ask('join', o); },
    resume: function () { return ask('resume'); },
    setOrder: function (o) { return ask('setOrder', o); },
    intent: function (o) { return ask('intent', o); },
    behaviour: function (p) { return ask('behaviour', p); },
    bench: function (p) { return ask('bench', p); },
    speech: function (o) { return ask('speech', o); },
    leave: function () { return ask('leave'); },
    observe: function () { return ask('observe'); },
    now: function () { return ask('_now'); }
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
