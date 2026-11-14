/* identity.js: the hosted arena's chain mode in the guide. Your wallet signs in, and you get a trenchie on the identity NFT.
 *
 * A classic script: the guide loads it after wallet.js; the arena restores its saved page key.
 * In a page it sets window.SnapIdentity, under node it is module.exports.
 * Every step is one POST /dev/identity {"op": ...} to the host (near/chain/hosted_live.py), and nothing here pretends:
 *   mode()         GET /dev/health: the host's chain_mode block (identity network, contracts), or null on a DEV host
 *   signIn()       makes this page's own key (nonextractable WebCrypto Ed25519, kept in IndexedDB), asks
 *                  for a challenge that names that key, and the wallet signs it (NEP-413, no transaction, no cost).
 *                  The host gives a sign-in id that is useless without this page's key: every later step is signed
 *                  by it (an envelope: op, sign-in id, time, the payload as text), and each is accepted once.
 *   inspectOwned() reads an owned token's immutable persona without creating its inventory record.
 *   getTrenchie()  confirms a trenchie whose minted digest matches the supplied sheet; else a free claim of the chosen premint (only when the player
 *                  plays that premint's persona); else a paid mint the wallet signs itself with the host's permit for the
 *                  sheet the host checked. A mint the wallet sent is confirmed again on retry, never sent twice.
 *   ticket(token)  a signed one-use ticket for the room join (room.js sends it with the registration)
 *   leave(token)   a signed owner request: release the seat and end its agent pairing, with a fresh host owner read
 */
(function (root) {
  'use strict';

  function b64url(bytes) {
    var s = ''; var a = new Uint8Array(bytes); for (var i = 0; i < a.length; i++) s += String.fromCharCode(a[i]);
    return (typeof btoa === 'function' ? btoa(s) : Buffer.from(s, 'binary').toString('base64')).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }
  async function sha256hex(text) {
    var d = await root.crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
    return Array.prototype.map.call(new Uint8Array(d), function (b) { return ('0' + b.toString(16)).slice(-2); }).join('');
  }

  async function post(fetchFn, body) {
    // Ownership reads can be retried safely. Bound the request and body read so a stalled host
    // releases the guide's Checking state; wallet approvals and mint submissions keep their own flow.
    var read = body.op === 'inspect' || body.op === 'confirm';
    var abort = read && root.AbortController ? new root.AbortController() : null;
    var timeout = abort ? root.setTimeout(function () { abort.abort(); }, 15000) : null;
    try {
      var r = await fetchFn('/dev/identity', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body), signal: abort ? abort.signal : undefined });
      var data = null; try { data = await r.json(); } catch (e) { if (abort && abort.signal.aborted) throw e; /* not JSON */ }
      if (!r.ok || !data || data.error) throw new Error((data && data.error) || ('the host answered ' + r.status));
      return data;
    } catch (e) {
      if (abort && abort.signal.aborted) throw new Error('The ownership check took too long. Try again; if it keeps happening, sign in again.');
      throw e;
    } finally { if (timeout !== null) root.clearTimeout(timeout); }
  }

  function make(deps) {
    deps = deps || {};
    var fetchFn = deps.fetch || (root.fetch && root.fetch.bind(root));
    var W = function () { return deps.wallet || root.SnapWallet; };
    var state = { mode: null, modeKnown: false, signin: null, account: null, owned: [], offer: null, pending: null };
    var pageKey = null;   // {privateKey, pub}: only its public half leaves this browser
    async function authorization(write) {
      if (!root.indexedDB) return;
      var db = await new Promise(function (resolve, reject) {
        var r = root.indexedDB.open('trenchie-snapin', 1);
        r.onupgradeneeded = function () { r.result.createObjectStore('keys'); };
        r.onsuccess = function () { resolve(r.result); }; r.onerror = function () { reject(r.error); };
      });
      return new Promise(function (resolve, reject) {
        var tx = db.transaction('keys', write ? 'readwrite' : 'readonly'), store = tx.objectStore('keys');
        var r = write ? store.put({ state: state, pageKey: pageKey }, 'identity') : store.get('identity');
        tx.oncomplete = function () { db.close(); resolve(r.result); };
        tx.onerror = function () { db.close(); reject(tx.error); };
        tx.onabort = function () { db.close(); reject(tx.error); };
      });
    }
    async function restoreAuthorization(refresh) {
      if (!refresh && state.signin && pageKey) return;
      var saved = await authorization(false).catch(function () { return null; });
      if (saved && saved.state && saved.pageKey) { state = saved.state; pageKey = saved.pageKey; }
    }

    async function newPageKey() {
      var kp = await root.crypto.subtle.generateKey({ name: 'Ed25519' }, false, ['sign', 'verify']);
      var raw = await root.crypto.subtle.exportKey('raw', kp.publicKey);
      return { privateKey: kp.privateKey, pub: b64url(raw) };
    }
    async function envelope(op, payload) {
      await restoreAuthorization();
      if (!state.signin || !pageKey) throw new Error('sign in with your wallet first');
      // a random nonce in every payload: two identical steps in one millisecond still sign differently (Ed25519 is deterministic)
      var n = new Uint8Array(12); root.crypto.getRandomValues(n);
      var text = JSON.stringify(Object.assign({}, payload || {}, { _n: b64url(n) })), at = String(Date.now());
      var msg = 'trenchie-desk|' + op + '|' + state.signin + '|' + at + '|' + (await sha256hex(text));
      var sig = await root.crypto.subtle.sign({ name: 'Ed25519' }, pageKey.privateKey, new TextEncoder().encode(msg));
      return { op: op, signin: state.signin, at: at, payload: text, sig: b64url(sig) };
    }
    async function step(op, payload) { return post(fetchFn, await envelope(op, payload)); }

    async function mode() {
      state.modeKnown = false;
      // Give a health read ten seconds, so a stalled request can retry after a restart.
      var abort = root.AbortController ? new root.AbortController() : null;
      var timeout = abort ? root.setTimeout(function () { abort.abort(); }, 10000) : null;
      try {
        var r = await fetchFn('/dev/health', { cache: 'no-store', signal: abort ? abort.signal : undefined }); var h = await r.json();
        state.modeKnown = !!(r.ok && h && typeof h === 'object' && !Array.isArray(h) && !h.error);
        state.mode = state.modeKnown && h.chain_mode ? h.chain_mode : null;
      } catch (e) { state.mode = null; }   // unknown mode keeps wallet actions disabled until a retry succeeds
      finally { if (timeout !== null) root.clearTimeout(timeout); }
      return state.mode;
    }

    async function signIn() {
      if (!state.mode) throw new Error('this arena is not in chain mode');
      if (!root.crypto || !root.crypto.subtle) throw new Error('this browser cannot make a page key (WebCrypto)');
      var net = state.mode.identity_network;
      pageKey = await newPageKey();
      var ch = await post(fetchFn, { op: 'challenge', page_key: pageKey.pub });
      var s = await W().signMessage({ network: net, message: ch.message, recipient: ch.recipient, nonce: ch.nonce });
      if (!s || !s.ok) throw new Error('The wallet did not sign in: ' + ((s && s.message) || 'no answer'));
      var out = await post(fetchFn, { op: 'signin', account_id: s.accountId, public_key: s.publicKey, signature: s.signature, nonce: ch.nonce });
      state.signin = out.signin; state.account = out.account_id; state.owned = out.trenchies || []; state.offer = out.offer;
      await authorization(true).catch(function () { /* no IndexedDB: this page can still play while open */ });
      return { account: out.account_id, owned: state.owned, offer: out.offer, network: net };
    }

    // o: {preset (battle option slug), sheet (the persona sheet), claim, tokenId, newFighter (claim or mint another)}
    async function getTrenchie(o) {
      if (!state.signin) throw new Error('sign in with your wallet first');
      var net = state.mode.identity_network;
      if (state.pending) {   // a mint the wallet already sent: confirm it again, never mint (and pay) twice
        var cp = await step('confirm', { token_id: state.pending.token_id, tx: state.pending.tx });
        var was = state.pending; state.pending = null; state.owned = [{ token_id: cp.token_id }];
        return Object.assign({ how: 'paid', tx: was.tx }, cp);
      }
      var owned = o.newFighter === true ? [] : o.tokenId ? [{ token_id: o.tokenId }] : state.owned;
      if (owned.length) {
        var sheets = root.SnapSheet || (typeof require === 'function' && require('./sheet.js'));
        if (!o.sheet || !sheets) throw new Error('Send the original persona sheet for your owned Trenchie.');
        var digest = await sheets.digest(o.sheet);
        for (var i = 0; i < owned.length; i++) {
          var found = await step('inspect', { token_id: owned[i].token_id });
          if (found.persona_digest === digest) return Object.assign({ how: 'owned' }, await step('confirm', { token_id: found.token_id }));
        }
        throw new Error('Your owned Trenchie has a fixed personality. Restore its original persona before snapping in.');
      }
      if (state.offer && state.offer.kind === 'claim' && o.claim) {
        var c1 = await step('claim', { preset: o.preset });
        state.owned = [{ token_id: c1.token_id }];
        return Object.assign({ how: 'claim', tx: c1.claim_tx }, c1);
      }
      var p = await step('permit', { preset: o.preset, sheet: o.sheet });
      var sent = await W().callContract({ network: net, receiverId: p.contract_id, methodName: p.method, args: p.args,
                                          gas: String(p.tgas) + '000000000000', deposit: p.deposit_yocto });
      if (!sent || !sent.ok) throw new Error('The mint was not sent: ' + ((sent && sent.message) || 'no answer'));
      state.pending = { token_id: p.token_id, tx: sent.txHash };
      var c2 = await step('confirm', { token_id: p.token_id, tx: sent.txHash });
      state.pending = null; state.owned = [{ token_id: p.token_id }];
      return Object.assign({ how: 'paid', tx: sent.txHash, cost_yocto: p.deposit_yocto }, c2);
    }

    // the room join's ticket: signed by this page's key, for this token, one use, within a minute
    // o: {session_public_key, name, preset}: the ticket signs what the room will seat, so it can't seat another key
    async function ticket(tokenId, o) {
      o = o || {};
      var payload = { nft_token_id: tokenId, session_public_key: o.session_public_key, name: o.name, preset: o.preset };
      if (o.rejoin === true) payload.rejoin = true;
      return envelope('register', payload);
    }
    // the agent door's code request in chain mode (POST /snap/code): the code args, signed, for this token
    async function codeRequest(args, tokenId) { return envelope('code', Object.assign({}, args, { nft_token_id: tokenId })); }

    return { mode: mode, signIn: signIn, getTrenchie: getTrenchie, ticket: ticket, codeRequest: codeRequest,
             // The owner may have renewed the sign-in in another guide tab while this arena stayed open.
             leave: async function (tokenId) { await restoreAuthorization(true); return step('leave', { nft_token_id: tokenId }); },
             inspectOwned: function (tokenId) { return step('inspect', { token_id: tokenId }); },
             state: function () { return state; } };
  }

  var api = make();
  api.make = make;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.SnapIdentity = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
