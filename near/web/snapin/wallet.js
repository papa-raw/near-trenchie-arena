/* wallet.js: the NEAR wallet door (W2 spike).
 *
 * A classic script. In a page it sets window.SnapWallet; under node it is module.exports.
 * It needs two vendored classic scripts loaded first (vendor/near-api-js/README.txt):
 *   near-api-js-7.3.1.min.js    -> window.NearApi
 *   near-connect-0.12.0.min.js  -> window.NearConnectLib   (wallet selector; the wallet list is its manifest)
 * Tests inject {NearApi, NearConnectLib} instead.
 *
 * Every function returns a Promise of a plain object; none throws for a wallet or network error:
 *   {ok:true, ...}  or  {ok:false, kind:'no-lib'|'unknown-wallet'|'rejected'|'wrong-network'|'no-session'|'receiver'|'no-key'|'other', message}
 *
 * Status words: every shortlisted wallet is `declares: 'testnet'` (its own manifest says so; read from the
 * near-connect manifest). It stays "declares" until a real sign-in with that wallet is logged in the
 * build's verification log. Nothing here ever says a wallet "works".
 *
 * The guest key: generated in the page (near-api-js KeyPairEd25519), the secret held in a closure
 * (memory only), never sent anywhere, never returned. The connected wallet is asked to add ONE
 * function-call key: receiver = the market account only, a gas allowance, no deposit.
 *
 * The market account and the RPC come from chain.js (load it first); config.marketAccount = null asks for the old
 * receiver LABEL instead (tests only). testKey() makes the one zero-deposit call through the guest key.
 *
 * The wallet list: wallets-manifest.json beside this file, a reviewed copy served from this origin (never near-connect's
 * default list, which it fetches unpinned from GitHub branches at run time). Copied 2026-11-11 from near-connect's default
 * manifest at commit e71894f7e69d9ea66a4d185b1297ac1d34f16b2a (azbang/near-connect, which hot-dao/near-selector now
 * redirects to), upstream sha256 a90e85a75a154025297db2bbe06de940f3bbdcac4782e3f59eb01f8ed7fae580; our copy keeps the four
 * shortlisted entries and pins the GitHub-hosted executors to commits (its _reviewed block lists each pin and its sha256).
 * Copy sha256: 0abc49fb667fa81caf48ec3c6acfffa99f39453dce1326ea32cedc0f1a7ede6f. A wallet is picked by its manifest id AND its
 * executor URL (both pinned below), and must be the selector's own sandboxed wallet: never by display name, never a wallet a
 * parent frame or another script injected, and never inside a frame.
 */
(function (root) {
  'use strict';

  // F71 shortlist: our id, the label, and the reviewed manifest's id and executor URL (wallets-manifest.json). A manifest entry
  // is used only when both match exactly; a look-alike (another id, or the same id with another executor) is refused.
  var SHORTLIST = [
    { id: 'meteor', name: 'Meteor', manifestId: 'meteor-wallet', executor: 'https://raw.githubusercontent.com/Meteor-Wallet/meteor_wallet_sdk/6369ad789d2f3aaf8e6ccb065021723111027174/storage/meteor-near-connect-latest.js' },
    { id: 'intear', name: 'Intear', manifestId: 'intear-wallet', executor: 'https://wallet.intear.tech/near-selector.js' },
    { id: 'nightly', name: 'Nightly', manifestId: 'nightly-wallet', executor: 'https://raw.githubusercontent.com/azbang/near-connect/e71894f7e69d9ea66a4d185b1297ac1d34f16b2a/repository/nightly.js' },
    { id: 'ethereum-wallets', name: 'Ethereum Wallets', manifestId: 'ethereum-wallets', executor: 'https://evm-on-near.dev/executor.js' }
  ];
  // the reviewed list's address, beside this script (the pages that load it sit at different depths)
  var MANIFEST_URL = (function () {
    try { var src = root.document && root.document.currentScript && root.document.currentScript.src; return src ? new URL('wallets-manifest.json', src).href : null; } catch (e) { return null; }
  })();
  var LIST_FAILED = 'Wallet list didn’t load; try again.';
  var DEFAULT_ALLOWANCE_NEAR = '0.25';

  // chain.js names the deployed testnet market and the RPC (one file); a page that did not load it gets the label fallback
  var CHAIN = root.SNAPIN_CHAIN || (typeof module !== 'undefined' && module.exports && typeof require === 'function' ? (function () { try { return require('./chain.js'); } catch (e) { return null; } })() : null) || {};
  var config = { marketAccount: CHAIN.marketAccount || null, rpc: CHAIN.rpc || null }; // the market contract's full account id; the testnet RPC
  var TEST_GAS = '10000000000000';      // 10 Tgas for the test call, paid from the key's allowance
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

  // The selector always gets our list (the reviewed file, or a test's own): with no manifest it would fetch its GitHub default.
  function newConnector(L, network, opts) {
    var o = { network: network };
    if (opts && opts.connectorOptions) for (var k in opts.connectorOptions) o[k] = opts.connectorOptions[k];
    o.manifest = (opts && opts.manifest) || MANIFEST_URL;
    if (!o.manifest) return null;
    return new L.C.NearConnector(o);
  }

  // Must be called from a user gesture (a click): the wallet opens a popup or an iframe.
  async function connect(id, args, opts) {
    var network = (args && args.network) || 'mainnet';
    if (network !== 'mainnet' && network !== 'testnet') return fail('other', 'network must be mainnet or testnet');
    var entry = SHORTLIST.filter(function (w) { return w.id === id; })[0];
    if (!entry) return fail('unknown-wallet', 'not on the F71 shortlist: ' + id);
    var L = libs(opts);
    if (!L.C || !L.C.NearConnector || !L.C.SandboxWallet) return fail('no-lib', 'near-connect bundle not loaded');
    // a parent frame can hand the selector a wallet of its own under a shortlisted id: sign in only from a top-level page
    try { if (root.top && root.top !== root) return fail('framed', 'Open this page in its own tab to sign in: wallets do not open inside another site.'); }
    catch (e) { return fail('framed', 'Open this page in its own tab to sign in: wallets do not open inside another site.'); }
    try {
      var connector = newConnector(L, network, opts);
      if (!connector) return fail('no-list', LIST_FAILED);
      await connector.whenManifestLoaded.catch(function () { /* handled below: empty list */ });
      var wallets = (connector.manifest && connector.manifest.wallets) || [];
      if (!wallets.length) return fail('no-list', LIST_FAILED);
      var found = wallets.filter(function (m) { return m && m.id === entry.manifestId; })[0];
      if (!found) return fail('unknown-wallet', entry.name + ' is not in the reviewed wallet list');
      if (found.executor !== entry.executor || found.type !== 'sandbox') return fail('untrusted-wallet', entry.name + '’s entry is not the reviewed one, so it was not opened');
      var declared = !!(found.features && found.features[network]);
      if (!declared) return fail('wrong-network', entry.name + ' does not declare ' + network);
      // the wallet the selector will open: its own sandboxed wallet built from that entry, not one injected under the same id
      var mine = function (w) { return !!w && w instanceof L.C.SandboxWallet && !!w.manifest && w.manifest.id === entry.manifestId && w.manifest.executor === entry.executor && !w.manifest.debug; };
      var registered = await connector.wallet(found.id).catch(function () { return null; });
      if (!mine(registered)) return fail('untrusted-wallet', entry.name + ' was replaced on this page by a wallet that is not the reviewed one, so it was not opened');
      var wallet = await connector.connect({ walletId: found.id });
      if (wallet !== registered || !mine(wallet)) return fail('untrusted-wallet', entry.name + ' was swapped while it opened; sign-in not kept');
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
      guest = { accountId: accountId, publicKey: publicKey, keyPair: kp, receiver: receiver };
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

  // "Test my key": ONE function call to the market, signed by the in-memory guest key, attaching 0 NEAR. It calls the
  // market's balance_of (a read) as a transaction, so nothing changes; the gas comes from the key's allowance. The answer
  // is the transaction hash (for the checker) and this account's market balance in yoctoNEAR.
  async function testKey(args, opts) {
    var L = libs(opts);
    if (!L.A || !L.A.Account || !L.A.KeyPairSigner || !L.A.JsonRpcProvider) return fail('no-lib', 'near-api-js bundle not loaded');
    if (!guest) return fail('no-key', 'add the guest key first: there is no guest key in this page');
    var rpcUrl = (args && args.rpc) || config.rpc;
    if (!rpcUrl && !(opts && opts.provider)) return fail('other', 'no testnet RPC configured (chain.js)');
    try {
      var provider = (opts && opts.provider) || new L.A.JsonRpcProvider({ url: rpcUrl });
      var account = new L.A.Account(guest.accountId, provider, new L.A.KeyPairSigner(guest.keyPair));
      var call = L.A.actions.functionCall('balance_of', { account_id: guest.accountId }, BigInt(TEST_GAS), BigInt(0));
      var res = await account.signAndSendTransaction({ receiverId: guest.receiver, actions: [call] });
      var tx = (res && res.transaction) || {}, status = (res && res.status) || {};
      if (!('SuccessValue' in status)) return fail('other', 'the call did not succeed: ' + JSON.stringify(status).slice(0, 200));
      var balance = null;
      try { balance = JSON.parse(typeof atob === 'function' ? atob(status.SuccessValue) : Buffer.from(status.SuccessValue, 'base64').toString()); } catch (e) { /* not JSON */ }
      return { ok: true, txHash: tx.hash || null, accountId: guest.accountId, receiver: guest.receiver, method: 'balance_of', deposit: '0', publicKey: guest.publicKey, marketBalanceYocto: balance };
    } catch (e) {
      return fail(errKind(e), e && e.message || e);
    }
  }
  function forgetGuestKey() { guest = null; }

  // NEP-413 sign-in: the connected wallet signs {message, recipient, nonce (32 bytes)} with a key of the account. No transaction,
  // no cost. The host checks the signature and reads that key on the network as a full-access key (near/chain/identity.py).
  async function signMessage(args) {
    var network = (args && args.network) || 'testnet';
    var s = sessions[network];
    if (!s) return fail('no-session', 'connect a wallet on ' + network + ' first');
    try {
      var nonce = args.nonce instanceof Uint8Array ? args.nonce : b64urlBytes(args.nonce);
      if (!nonce || nonce.length !== 32) return fail('other', 'the sign-in code is not 32 bytes');
      var r = await s.wallet.signMessage({ message: args.message, recipient: args.recipient, nonce: nonce, network: network });
      if (!r || !r.signature || !r.publicKey) return fail('rejected', 'the wallet returned no signature');
      return { ok: true, accountId: r.accountId || s.accountId, publicKey: r.publicKey, signature: r.signature };
    } catch (e) { return fail(errKind(e), e && e.message || e); }
  }
  function b64urlBytes(text) {
    try {
      var v = String(text).replace(/-/g, '+').replace(/_/g, '/'); while (v.length % 4) v += '=';
      var bin = (typeof atob === 'function' ? atob(v) : Buffer.from(v, 'base64').toString('binary')), out = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
      return out;
    } catch (e) { return null; }
  }

  // One function call the wallet signs and sends itself (a full-access signature: it may attach a deposit, as paid_mint needs).
  // args: {network, receiverId, methodName, args, gas (string), deposit (yoctoNEAR string)}. Answers the transaction hash.
  async function callContract(args) {
    var network = (args && args.network) || 'testnet';
    var s = sessions[network];
    if (!s) return fail('no-session', 'connect a wallet on ' + network + ' first');
    if (!/^[a-z0-9._-]{2,64}$/.test(String(args.receiverId || ''))) return fail('receiver', 'not a valid account id: ' + args.receiverId);
    if (!/^[0-9]+$/.test(String(args.deposit || '0')) || !/^[0-9]+$/.test(String(args.gas || ''))) return fail('other', 'gas and deposit are whole-number strings');
    var action = { type: 'FunctionCall', params: { methodName: args.methodName, args: args.args, gas: String(args.gas), deposit: String(args.deposit || '0') } };
    try {
      var outcome = await s.wallet.signAndSendTransaction({ network: network, signerId: s.accountId, receiverId: args.receiverId, actions: [action] });
      var tx = outcome && outcome.transaction && outcome.transaction.hash;
      var st = outcome && outcome.status;
      if (st && typeof st === 'object' && 'Failure' in st) return fail('other', 'the call failed onchain: ' + JSON.stringify(st.Failure).slice(0, 200));
      return { ok: true, txHash: tx || null, accountId: s.accountId };
    } catch (e) { return fail(errKind(e), e && e.message || e); }
  }
  function account(network) { var s = sessions[network || 'testnet']; return s ? s.accountId : null; }

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
    forgetGuestKey: forgetGuestKey, importCheck: importCheck, config: config, testKey: testKey,
    signMessage: signMessage, callContract: callContract, account: account,
    _reset: function () { sessions = {}; guest = null; },
    // node checks only: a connected wallet stand-in (signMessage, signAndSendTransaction), as connect() would hold it
    _adoptSession: function (network, wallet, accountId) { sessions[network] = { wallet: wallet, accountId: accountId, shortId: 'test' }; },
    // node checks only: hold a guest key that was added outside a page (the live test-key run), the same way guestKey does
    _adoptGuest: function (accountId, keyPair, receiver) { guest = { accountId: accountId, publicKey: keyPair.getPublicKey().toString(), keyPair: keyPair, receiver: receiver }; }
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.SnapWallet = api;
})(typeof globalThis !== 'undefined' ? globalThis : (typeof window !== 'undefined' ? window : this));
