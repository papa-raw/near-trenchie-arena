/* wallet.js: the NEAR wallet door (W2 spike, task r3-snapin-screens).
 *
 * A classic script. In a page it sets window.SnapWallet; under node it is module.exports.
 * It needs two vendored classic scripts loaded first (vendor/near-api-js/README.txt):
 *   near-api-js-7.3.1.min.js    -> window.NearApi
 *   near-connect-0.12.0.min.js  -> window.NearConnectLib   (wallet selector; the wallet list is its manifest)
 * Tests inject {NearApi, NearConnectLib} instead.
 *
 * Every function returns a Promise of a plain object; none throws for a wallet or network error:
 *   {ok:true, ...}  or  {ok:false, kind:'no-lib'|'unknown-wallet'|'rejected'|'wrong-network'|'no-session'|'receiver'|'other', message}
 *
 * Status words: every shortlisted wallet is `declares: 'testnet'` (its own manifest says so; read from the
 * near-connect manifest). It stays "declares" until a real sign-in with that wallet is logged in the
 * build's verification log. Nothing here ever says a wallet "works".
 *
 * The guest key: generated in the page (near-api-js KeyPairEd25519), the secret held in a closure
 * (memory only), never sent anywhere, never returned. The connected wallet is asked to add ONE
 * function-call key: receiver = the market account only, a gas allowance, no deposit.
 */
(function (root) {
  'use strict';

  // F71 shortlist. `match` finds the entry in the near-connect manifest by name (ids are the manifest's, not ours).
  var SHORTLIST = [
    { id: 'meteor', name: 'Meteor', match: /meteor/i },
    { id: 'intear', name: 'Intear', match: /intear/i },
    { id: 'nightly', name: 'Nightly', match: /nightly/i },
    { id: 'ethereum-wallets', name: 'Ethereum Wallets', match: /ethereum/i }
  ];
  var DEFAULT_ALLOWANCE_NEAR = '0.25';

  var config = { marketAccount: null }; // full account id of the market contract, e.g. 'market.<root>.testnet'
  var sessions = {};                    // network -> {connector, wallet, accountId, manifestId, shortId}
  var guest = null;                     // {accountId, publicKey, keyPair}  (memory only)

  function libs(opts) {
    var A = (opts && opts.NearApi) || root.NearApi;
    var C = (opts && opts.NearConnectLib) || root.NearConnectLib;
    return { A: A, C: C };
  }
  function fail(kind, message) { return { ok: false, kind: kind, message: String(message == null ? '' : message).slice(0, 240) }; }
  function errKind(e) {
    var m = String((e && e.message) || e || '');
    if (/reject|cancel|denied|declin|closed|abort/i.test(m)) return 'rejected';
    return 'other';
  }

  function list() {
    return SHORTLIST.map(function (w) { return { id: w.id, name: w.name, declares: 'testnet', verified: false }; });
  }

  function newConnector(L, network, opts) {
    var o = { network: network };
    if (opts && opts.manifest) o.manifest = opts.manifest; // tests / offline; default = the library's own manifest URLs
    if (opts && opts.connectorOptions) for (var k in opts.connectorOptions) o[k] = opts.connectorOptions[k];
    return new L.C.NearConnector(o);
  }

  // Must be called from a user gesture (a click): the wallet opens a popup or an iframe.
  async function connect(id, args, opts) {
    var network = (args && args.network) || 'mainnet';
    if (network !== 'mainnet' && network !== 'testnet') return fail('other', 'network must be mainnet or testnet');
    var entry = SHORTLIST.filter(function (w) { return w.id === id; })[0];
    if (!entry) return fail('unknown-wallet', 'not on the F71 shortlist: ' + id);
    var L = libs(opts);
    if (!L.C || !L.C.NearConnector) return fail('no-lib', 'near-connect bundle not loaded');
    try {
      var connector = newConnector(L, network, opts);
      await connector.whenManifestLoaded.catch(function () { /* handled below: empty list */ });
      var found = (connector.manifest && connector.manifest.wallets || []).filter(function (m) { return entry.match.test(m.name || '') || entry.match.test(m.id || ''); })[0];
      if (!found) return fail('unknown-wallet', entry.name + ' is not in the manifest the selector loaded (manifest wallets: ' + ((connector.manifest && connector.manifest.wallets) || []).length + ')');
      var declared = !!(found.features && found.features[network]);
      if (!declared) return fail('wrong-network', entry.name + ' does not declare ' + network);
      var wallet = await connector.connect({ walletId: found.id });
      var accounts = await wallet.getAccounts({ network: network });
      if (!accounts || !accounts.length) return fail('rejected', 'wallet returned no account');
      sessions[network] = { connector: connector, wallet: wallet, accountId: accounts[0].accountId, manifestId: found.id, shortId: id };
      return { ok: true, network: network, walletId: id, manifestId: found.id, accountId: accounts[0].accountId, accounts: accounts.map(function (a) { return a.accountId; }), declaredInManifest: true };
    } catch (e) {
      return fail(errKind(e), e && e.message || e);
    }
  }

  // Ask the connected TESTNET wallet to add ONE function-call key for this page's in-memory key.
  async function guestKey(args, opts) {
    args = args || {};
    var network = args.network || 'testnet';
    if (network !== 'testnet') return fail('wrong-network', 'the guest key is testnet only');
    var L = libs(opts);
    if (!L.A || !L.A.KeyPairEd25519) return fail('no-lib', 'near-api-js bundle not loaded');
    var s = sessions.testnet;
    if (!s) return fail('no-session', 'connect a wallet on testnet first');
    var accountId = args.accountId || s.accountId;
    if (accountId !== s.accountId) return fail('no-session', 'the connected testnet account is ' + s.accountId + ', not ' + accountId);

    var receiver = args.receiver || 'market';
    var label = false;
    if (receiver === 'market') {
      if (config.marketAccount) receiver = config.marketAccount;
      else { receiver = 'market.' + accountId; label = true; } // spike only: a receiver LABEL, the contract need not exist
    }
    if (!/^[a-z0-9._-]{2,64}$/.test(receiver)) return fail('receiver', 'not a valid account id: ' + receiver);

    var allowanceNear = String(args.allowanceNear != null ? args.allowanceNear : DEFAULT_ALLOWANCE_NEAR);
    var allowance;
    try { allowance = L.A.nearToYocto(allowanceNear).toString(); } catch (e) { return fail('other', 'bad allowanceNear: ' + allowanceNear); }

    var kp = L.A.KeyPairEd25519.fromRandom();
    var publicKey = kp.getPublicKey().toString();
    var action = { type: 'AddKey', params: { publicKey: publicKey, accessKey: { permission: { receiverId: receiver, allowance: allowance, methodNames: [] } } } };
    try {
      var outcome = await s.wallet.signAndSendTransaction({ network: 'testnet', signerId: accountId, receiverId: accountId, actions: [action] });
      guest = { accountId: accountId, publicKey: publicKey, keyPair: kp };
      var txHash = outcome && outcome.transaction && outcome.transaction.hash;
      return { ok: true, publicKey: publicKey, accountId: accountId, receiver: receiver, receiverIsLabel: label, allowance: allowance, txHash: txHash || null };
    } catch (e) {
      return fail(errKind(e), e && e.message || e); // the secret was never stored: `guest` is set only after success
    }
  }

  // The page signs with the in-memory guest key; the secret itself is never handed out.
  function guestSign(bytes) {
    if (!guest) return null;
    return guest.keyPair.sign(bytes).signature; // Uint8Array
  }
  function guestPublicKey() { return guest ? guest.publicKey : null; }
  function forgetGuestKey() { guest = null; }

  // The 7.3.1 import check, in the page: loads, makes a key, builds an AddKey action object.
  function importCheck(opts) {
    var L = libs(opts), r = { nearApi: { ok: false }, nearConnect: { ok: false } };
    try {
      var kp = L.A.KeyPairEd25519.fromRandom();
      r.nearApi = {
        ok: true, exports: Object.keys(L.A).length,
        publicKeyPrefix: kp.getPublicKey().toString().slice(0, 8),
        hasAddFunctionCallAccessKey: typeof L.A.actions.addFunctionCallAccessKey === 'function',
        nearToYocto_0_25: L.A.nearToYocto('0.25').toString()
      };
    } catch (e) { r.nearApi = { ok: false, error: String(e && e.message || e) }; }
    try { r.nearConnect = { ok: typeof L.C.NearConnector === 'function', exports: Object.keys(L.C).length }; } catch (e) { r.nearConnect = { ok: false, error: String(e && e.message || e) }; }
    return r;
  }

  var api = {
    list: list, connect: connect, guestKey: guestKey, guestSign: guestSign, guestPublicKey: guestPublicKey,
    forgetGuestKey: forgetGuestKey, importCheck: importCheck, config: config,
    _reset: function () { sessions = {}; guest = null; }
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.SnapWallet = api;
})(typeof globalThis !== 'undefined' ? globalThis : (typeof window !== 'undefined' ? window : this));
