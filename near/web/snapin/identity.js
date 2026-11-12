/* identity.js: the hosted arena's chain mode in the guide. Your wallet signs in, and you get a trenchie on the identity NFT.
 *
 * A classic script, loaded after wallet.js; in a page it sets window.SnapIdentity, under node it is module.exports.
 * Every step is one POST /dev/identity {"op": ...} to the host (near/chain/hosted_live.py), and nothing here pretends:
 *   mode()         GET /dev/health: the host's chain_mode block (identity network, contracts), or null on a DEV host
 *   signIn()       makes this page's own key (WebCrypto Ed25519, memory only, never sent but its public half), asks
 *                  for a challenge that names that key, and the wallet signs it (NEP-413, no transaction, no cost).
 *                  The host gives a sign-in id that is useless without this page's key: every later step is signed
 *                  by it (an envelope: op, sign-in id, time, the payload as text), and each is accepted once.
 *   getTrenchie()  confirms a trenchie the wallet owns; else a free claim of the chosen premint (only when the player
 *                  plays that premint's persona); else a paid mint the wallet signs itself with the host's permit for the
 *                  sheet the host checked. A mint the wallet sent is confirmed again on retry, never sent twice.
 *   ticket(token)  a signed one-use ticket for the room join (room.js sends it with the registration)
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
    var r = await fetchFn('/dev/identity', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
    var data = null; try { data = await r.json(); } catch (e) { /* not JSON */ }
    if (!r.ok || !data || data.error) throw new Error((data && data.error) || ('the host answered ' + r.status));
    return data;
  }

  function make(deps) {
    deps = deps || {};
    var fetchFn = deps.fetch || (root.fetch && root.fetch.bind(root));
    var W = function () { return deps.wallet || root.SnapWallet; };
    var state = { mode: null, signin: null, account: null, owned: [], offer: null, pending: null };
    var pageKey = null;   // {privateKey, pub}: memory only

    async function newPageKey() {
      var kp = await root.crypto.subtle.generateKey({ name: 'Ed25519' }, false, ['sign', 'verify']);
      var raw = await root.crypto.subtle.exportKey('raw', kp.publicKey);
      return { privateKey: kp.privateKey, pub: b64url(raw) };
    }
    async function envelope(op, payload) {
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
      try {
        var r = await fetchFn('/dev/health', { cache: 'no-store' }); var h = await r.json();
        state.mode = h && h.chain_mode ? h.chain_mode : null;
      } catch (e) { state.mode = null; }
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
      return { account: out.account_id, owned: state.owned, offer: out.offer, network: net };
    }

    // o: {preset (battle option slug), sheet (the persona sheet), claim (true: the player plays the premint persona), tokenId}
    async function getTrenchie(o) {
      if (!state.signin) throw new Error('sign in with your wallet first');
      var net = state.mode.identity_network;
      if (state.pending) {   // a mint the wallet already sent: confirm it again, never mint (and pay) twice
        var cp = await step('confirm', { token_id: state.pending.token_id, tx: state.pending.tx });
        var was = state.pending; state.pending = null; state.owned = [{ token_id: cp.token_id }];
        return Object.assign({ how: 'paid', tx: was.tx }, cp);
      }
      var pick = o.tokenId || (state.owned[0] && state.owned[0].token_id);
      if (pick) return Object.assign({ how: 'owned' }, await step('confirm', { token_id: pick }));
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
    async function ticket(tokenId, o) { o = o || {}; return envelope('register', { nft_token_id: tokenId, session_public_key: o.session_public_key, name: o.name, preset: o.preset }); }
    // the agent door's code request in chain mode (POST /snap/code): the code args, signed, for this token
    async function codeRequest(args, tokenId) { return envelope('code', Object.assign({}, args, { nft_token_id: tokenId })); }

    return { mode: mode, signIn: signIn, getTrenchie: getTrenchie, ticket: ticket, codeRequest: codeRequest,
             state: function () { return state; } };
  }

  var api = make();
  api.make = make;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.SnapIdentity = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
