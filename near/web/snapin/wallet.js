/* wallet.js: the NEAR wallet door (W2 spike).
 *
 * A classic script. In a page it sets window.SnapWallet; under node it is module.exports.
 * It needs two vendored classic scripts loaded first (vendor/near-api-js/README.txt):
 *   near-api-js-7.3.1.min.js    -> window.NearApi
 *   near-connect-0.12.0.min.js  -> window.NearConnectLib   (wallet selector; the wallet list is its manifest)
 * Tests inject {NearApi, NearConnectLib} instead.
 *
 * Every function returns a Promise of a plain object; none throws for a wallet or network error:
 *   {ok:true, ...}  or  {ok:false, kind:'no-lib'|'no-list'|'framed'|'rejected'|'wrong-network'|'no-session'|'receiver'|'no-key'|'other', message}
 *
 * The guest key: generated in the page (near-api-js KeyPairEd25519), the secret held in a closure
 * (memory only), never sent anywhere, never returned. The connected wallet is asked to add ONE
 * function-call key: receiver = the market account only, a gas allowance, no deposit.
 *
 * The market account and the RPC come from chain.js (load it first); config.marketAccount = null asks for the old
 * receiver LABEL instead (tests only). testKey() makes the one zero-deposit call through the guest key.
 *
 * Wallet discovery and selection belong to NEAR Connect 0.12.0: its default runtime manifest, sandboxed wallet
 * integrations and injected-wallet detection. No app shortlist, executor pins or display-name matching.
 * https://docs.near.org/tools/near-connect
 */
(function (root) {
  'use strict';

  var LIST_FAILED = 'Wallet list didn’t load; try again.';
  var DEFAULT_ALLOWANCE_NEAR = '0.25';

  // chain.js names the deployed testnet market and the RPC (one file); a page that did not load it gets the label fallback
  var CHAIN = root.SNAPIN_CHAIN || (typeof module !== 'undefined' && module.exports && typeof require === 'function' ? (function () { try { return require('./chain.js'); } catch (e) { return null; } })() : null) || {};
  var config = { marketAccount: CHAIN.marketAccount || null, rpc: CHAIN.rpc || null }; // the market contract's full account id; the testnet RPC
  var TEST_GAS = '10000000000000';      // 10 Tgas for the test call, paid from the key's allowance
  var sessions = {};                    // network -> {connector, wallet, accountId, manifestId}
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

  // A null id opens NEAR Connect's own chooser; an explicit id is passed unchanged to the SDK. Call from a user click.
  async function connect(id, args, opts) {
    var network = (args && args.network) || 'mainnet';
    if (network !== 'mainnet' && network !== 'testnet') return fail('other', 'network must be mainnet or testnet');
    var L = libs(opts);
    if (!L.C || !L.C.NearConnector) return fail('no-lib', 'near-connect bundle not loaded');
    // Sign in from our top-level page; the SDK may otherwise accept a parent-frame wallet.
    try { if (root.top && root.top !== root) return fail('framed', 'Open this page in its own tab to sign in: wallets do not open inside another site.'); }
    catch (e) { return fail('framed', 'Open this page in its own tab to sign in: wallets do not open inside another site.'); }
    try {
      var connector = new L.C.NearConnector({ network: network });
      await connector.whenManifestLoaded;
      if (!connector.availableWallets.length) return fail('no-list', LIST_FAILED);
      var wallet = await connector.connect(id ? { walletId: id } : {});
      var accounts = await wallet.getAccounts({ network: network });
      if (!accounts || !accounts.length) return fail('rejected', 'wallet returned no account');
      var manifest = wallet.manifest;
      sessions[network] = { connector: connector, wallet: wallet, accountId: accounts[0].accountId, manifestId: manifest.id };
      return { ok: true, network: network, walletId: manifest.id, walletName: manifest.name, manifestId: manifest.id, accountId: accounts[0].accountId, accounts: accounts.map(function (a) { return a.accountId; }) };
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
    connect: connect, guestKey: guestKey, guestSign: guestSign, guestPublicKey: guestPublicKey,
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
