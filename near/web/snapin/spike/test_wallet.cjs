// node near/web/snapin/spike/test_wallet.cjs
// wallet.js against the VENDORED near-api-js 7.3.1 bundle and a fake near-connect (no network, no wallet).
'use strict';
const fs = require('fs'), path = require('path');
const NearApi = (0, eval)(fs.readFileSync(path.join(__dirname, '../vendor/near-api-js/near-api-js-7.3.1.min.js'), 'utf8') + ';NearApi');
const W = require('../wallet.js');
let fails = 0;
const ok = (n, c, d) => { if (!c) fails++; console.log((c ? 'PASS ' : 'FAIL ') + n + (c ? '' : '  -> ' + d)); };

// The adapter's non-UI cases use a case-supplied connector; the full stock popup is qa/wallet_manifest_case.cjs.
const METEOR = { id: 'meteor-wallet', name: 'Meteor Wallet', type: 'sandbox', features: { mainnet: true, testnet: true } };
function fakeLib({ reject, noAccounts, mainnetOnly } = {}) {
  const sent = [];
  class SandboxWallet {   // the selector's own sandboxed wallet, built from a manifest entry
    constructor(connector, manifest) { this.connector = connector; this.manifest = manifest; }
    async getAccounts() { const net = this.connector.network; return noAccounts ? [] : [{ accountId: net === 'testnet' ? 'tester.testnet' : 'tester.near' }]; }
    async signAndSendTransaction(p) { sent.push(p); if (reject) throw new Error('User rejected the request'); return { transaction: { hash: 'FAKEHASH' } }; }
  }
  class NearConnector {
    constructor(o) {
      this.network = o.network; this.given = o.manifest;
      this.manifest = { version: '1', wallets: [
        Object.assign({}, METEOR, { features: Object.assign({}, METEOR.features, { mainnet: true, testnet: !mainnetOnly }) }),
        { id: 'hot-wallet', name: 'HOT Wallet', type: 'sandbox', executor: 'https://example.invalid/hot.js', features: { mainnet: true } },
      ] };
      this.wallets = this.manifest.wallets.map((m) => new SandboxWallet(this, m));
      this.whenManifestLoaded = Promise.resolve();
    }
    get availableWallets() { return this.wallets.filter((w) => this.network !== 'testnet' || w.manifest.features.testnet); }
    async wallet(id) { const w = this.wallets.find((x) => x.manifest.id === id); if (!w) throw new Error('Wallet not found'); return w; }
    async connect({ walletId } = {}) { return this.wallet(walletId || this.availableWallets[0].manifest.id); }
  }
  return { NearConnectLib: { NearConnector, SandboxWallet }, NearApi, sent };   // connector supplies its own manifest and availableWallets
}

(async () => {
  ok('importCheck on the vendored bundle', W.importCheck({ NearApi, NearConnectLib: { NearConnector() {} } }).nearApi.nearToYocto_0_25 === '250000000000000000000000', JSON.stringify(W.importCheck({ NearApi, NearConnectLib: {} })));

  let o = fakeLib();
  let r = await W.connect('meteor-wallet', { network: 'testnet' }, o);
  ok('connect meteor testnet -> account', r.ok && r.accountId === 'tester.testnet' && r.manifestId === 'meteor-wallet', JSON.stringify(r));
  r = await W.connect('intear-wallet', { network: 'testnet' }, o);
  ok('connect intear: the connector refuses an absent wallet', !r.ok && r.kind === 'other', JSON.stringify(r));
  r = await W.connect(null, { network: 'testnet' }, fakeLib({ mainnetOnly: true }));
  ok('no compatible wallets from the connector -> no-list', !r.ok && r.kind === 'no-list', JSON.stringify(r));
  r = await W.connect('meteor-wallet', { network: 'testnet' }, fakeLib({ noAccounts: true }));
  ok('connect with no account returned -> rejected', !r.ok && r.kind === 'rejected', JSON.stringify(r));

  W._reset();
  r = await W.guestKey({ network: 'testnet' }, fakeLib());
  ok('guestKey before connect -> no-session', !r.ok && r.kind === 'no-session', JSON.stringify(r));

  o = fakeLib();
  await W.connect('meteor-wallet', { network: 'testnet' }, o);
  r = await W.guestKey({ accountId: 'tester.testnet', network: 'testnet', receiver: 'market', allowanceNear: '0.25' }, o);
  const a = o.sent[0] && o.sent[0].actions[0];
  const MARKET = require('../chain.js').marketAccount;
  ok('with no console edit, the receiver is the deployed testnet market from chain.js (' + MARKET + ')', W.config.marketAccount === MARKET && MARKET === 'market.trenchie-r4b-20261111.testnet' && W.config.rpc === require('../chain.js').rpc, JSON.stringify(W.config));
  ok('guestKey ok: publicKey, the chain.js market as receiver, no secret in result', r.ok && /^ed25519:/.test(r.publicKey) && r.receiver === MARKET && r.receiverIsLabel === false && !/secret|private/i.test(JSON.stringify(r)), JSON.stringify(r));
  ok('exactly ONE AddKey, function-call permission, receiver market only, allowance 0.25 NEAR in yocto, no deposit',
    o.sent.length === 1 && o.sent[0].actions.length === 1 && a.type === 'AddKey' && a.params.publicKey === r.publicKey &&
    a.params.accessKey.permission.receiverId === MARKET && a.params.accessKey.permission.allowance === '250000000000000000000000' &&
    !('deposit' in a.params) && o.sent[0].receiverId === 'tester.testnet', JSON.stringify(o.sent));
  ok('secret key never in the wallet request', !/secret|ed25519:[1-9A-HJ-NP-Za-km-z]{80,}/.test(JSON.stringify(o.sent)), '');
  const sig = W.guestSign(new Uint8Array([1, 2, 3]));
  const pk = NearApi.PublicKey.from(W.guestPublicKey());
  ok('guestSign verifies against the published key; secret stays inside', sig instanceof Uint8Array && pk.verify(new Uint8Array([1, 2, 3]), sig) && W.guestPublicKey() === r.publicKey, '');
  W.forgetGuestKey();
  ok('forgetGuestKey clears it', W.guestSign(new Uint8Array([1])) === null && W.guestPublicKey() === null, '');

  W.config.marketAccount = 'market.trenchie-village.testnet';
  r = await W.guestKey({ network: 'testnet', receiver: 'market' }, o);
  ok('configured market account is used, not a label', r.ok && r.receiver === 'market.trenchie-village.testnet' && r.receiverIsLabel === false, JSON.stringify(r));
  W.config.marketAccount = null;
  r = await W.guestKey({ network: 'testnet', receiver: 'market' }, o);
  ok('config.marketAccount = null falls back to the old receiver label (tests only)', r.ok && r.receiver === 'market.tester.testnet' && r.receiverIsLabel === true, JSON.stringify(r));
  W.config.marketAccount = MARKET;
  r = await W.guestKey({ network: 'mainnet' }, o);
  ok('guestKey on mainnet refused', !r.ok && r.kind === 'wrong-network', JSON.stringify(r));
  r = await W.guestKey({ network: 'testnet', accountId: 'someone.else.testnet' }, o);
  ok('guestKey for a different account than the connected one refused', !r.ok && r.kind === 'no-session', JSON.stringify(r));
  r = await W.guestKey({ network: 'testnet', receiver: 'Bad Receiver!' }, o);
  ok('invalid receiver id refused before any wallet call', !r.ok && r.kind === 'receiver', JSON.stringify(r));

  W._reset(); o = fakeLib({ reject: true });
  await W.connect('meteor-wallet', { network: 'testnet' }, o);
  r = await W.guestKey({ network: 'testnet' }, o);
  ok('wallet rejects AddKey -> rejected, and no key kept', !r.ok && r.kind === 'rejected' && W.guestPublicKey() === null, JSON.stringify(r));

  // Test my key: refused plainly with no guest key in the page; the live call is spike/test-key-live.mjs (testnet)
  W._reset();
  r = await W.testKey({}, { NearApi });
  ok('testKey with no guest key -> no-key, nothing sent', !r.ok && r.kind === 'no-key', JSON.stringify(r));
  r = await W.testKey({}, { NearApi: {} });
  ok('testKey without the near-api-js bundle -> no-lib', !r.ok && r.kind === 'no-lib', JSON.stringify(r));

  console.log(fails ? `\n${fails} FAIL` : '\nall PASS');
  process.exit(fails ? 1 : 0);
})().catch((e) => { console.log('FAIL crashed -> ' + (e.stack || e)); process.exit(1); });
