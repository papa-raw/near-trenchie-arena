// identity.js + wallet.js in chain mode: a page key named in the wallet's sign-in, every later step signed by it,
// then a free claim or a wallet-signed paid mint, and a one-use ticket for the room join.
//   node near/web/snapin/test_identity.cjs
// The host is a fake /dev/identity that checks each envelope the way near/chain/identity.py does (the Ed25519 signature
// over "trenchie-desk|op|signin|at|sha256(payload)" by the key the challenge named); the wallet is a stand-in with
// near-connect's signMessage and signAndSendTransaction.
'use strict';
const assert = require('assert');
const crypto = require('crypto');
const W = require('./wallet.js');
const identity = require('./identity.js');

const b64u = (b) => Buffer.from(b).toString('base64url');

function host(offer) {
  const seen = [];
  let pageKey = null;
  const fetch = async (url, init) => {
    if (url === '/dev/health') return { ok: true, json: async () => ({ chain_mode: { identity_network: 'testnet', identity_nft: 'nft.id.testnet' } }) };
    const body = JSON.parse(init.body);
    assert.strictEqual(init.headers['content-type'], 'application/json');
    let args = body;
    if (body.sig) {   // a signed step: verify it with the page key, then read its payload
      const msg = `trenchie-desk|${body.op}|${body.signin}|${body.at}|${crypto.createHash('sha256').update(body.payload).digest('hex')}`;
      const key = crypto.createPublicKey({ key: { kty: 'OKP', crv: 'Ed25519', x: pageKey }, format: 'jwk' });
      assert.ok(crypto.verify(null, Buffer.from(msg), key, Buffer.from(body.sig, 'base64url')), 'envelope signed by the page key');
      assert.ok(Math.abs(Number(body.at) - Date.now()) < 60000);
      args = Object.assign({ op: body.op }, JSON.parse(body.payload));
      assert.strictEqual(typeof args._n, 'string', 'every envelope carries a random nonce'); delete args._n;
    }
    if (body.op === 'challenge') pageKey = body.page_key;
    seen.push(args);
    const reply = {
      challenge: { nonce: Buffer.alloc(32, 7).toString('base64url'), message: 'Sign in (page key ' + body.page_key + ')', recipient: 'https://arena.example' },
      signin: { signin: 'S1', account_id: 'p.testnet', trenchies: [], offer },
      claim: { token_id: 'hunter-lunge-00', account_id: 'p.testnet', claim_tx: 'CLAIMTX', shadow_tx: 'SH1' },
      permit: { contract_id: 'nft.id.testnet', method: 'paid_mint', args: { permit: { nonce: 'h1' }, signature: 'sig' }, deposit_yocto: '10000000000000000000000', tgas: 50, token_id: 'paid-h1' },
      confirm: { token_id: args.token_id, account_id: 'p.testnet', shadow_tx: 'SH2' }
    }[body.op];
    return { ok: !!reply, json: async () => reply || { error: 'unknown op' } };
  };
  return { fetch, seen, key: () => pageKey };
}

function wallet() {
  const calls = [];
  return {
    calls,
    signMessage: async (p) => { calls.push(['sign', p]); return { accountId: 'p.testnet', publicKey: 'ed25519:PK', signature: 'SIG' }; },
    signAndSendTransaction: async (p) => { calls.push(['send', p]); return { transaction: { hash: 'MINTTX' }, status: { SuccessValue: '' } }; }
  };
}
const SHEET = { game: { name: 'Pebble' } };

(async () => {
  // a paid mint (the rehearsal is in run-out): the page sends its sheet, never a name or digest of its own
  W._reset(); const w1 = wallet(); W._adoptSession('testnet', w1, 'p.testnet');
  const h1 = host({ kind: 'paid', cost_yocto: '10000000000000000000000' });
  const id1 = identity.make({ fetch: h1.fetch, wallet: W });
  assert.ok(await id1.mode());
  const si = await id1.signIn();
  assert.deepStrictEqual([si.account, si.offer.kind], ['p.testnet', 'paid']);
  assert.strictEqual(Buffer.from(h1.key(), 'base64url').length, 32, 'the page sends its public key');
  const sign = w1.calls[0][1];
  assert.ok(sign.message.includes(h1.key()), 'the wallet signs a message naming the page key');
  assert.ok(sign.nonce instanceof Uint8Array && sign.nonce.length === 32 && sign.nonce[0] === 7, 'the nonce goes to the wallet as 32 bytes');
  const t = await id1.getTrenchie({ preset: 'looter-lob', sheet: SHEET, claim: false });
  assert.deepStrictEqual(h1.seen[2], { op: 'permit', preset: 'looter-lob', sheet: SHEET });
  const send = w1.calls[1][1];
  assert.deepStrictEqual(send.actions, [{ type: 'FunctionCall', params: { methodName: 'paid_mint', args: { permit: { nonce: 'h1' }, signature: 'sig' }, gas: '50000000000000', deposit: '10000000000000000000000' } }]);
  assert.deepStrictEqual(h1.seen[3], { op: 'confirm', token_id: 'paid-h1', tx: 'MINTTX' });
  assert.deepStrictEqual([t.how, t.token_id, t.tx], ['paid', 'paid-h1', 'MINTTX']);
  const ticket = await id1.ticket('paid-h1');
  const tp = JSON.parse(ticket.payload); delete tp._n;
  assert.deepStrictEqual([ticket.op, ticket.signin, tp], ['register', 'S1', { nft_token_id: 'paid-h1' }]);
  await h1.fetch('/dev/identity', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(Object.assign({}, ticket, { op: 'confirm', payload: ticket.payload })) })
    .then(() => assert.fail('a ticket signed for register must not verify as another op'), (e) => assert.ok(/envelope signed by the page key/.test(e.message)));

  // a confirm that fails after the wallet sent the mint: the retry confirms that token again, never a second paid_mint
  W._reset(); const w4 = wallet(); W._adoptSession('testnet', w4, 'p.testnet');
  const h4 = host({ kind: 'paid', cost_yocto: '10000000000000000000000' });
  let failOnce = true;
  const flaky = async (url, init) => {
    if (init && init.body && JSON.parse(init.body).op === 'confirm' && failOnce) { failOnce = false; return { ok: false, json: async () => ({ error: 'paid-h1 is owned by nobody on the identity NFT' }) }; }
    return h4.fetch(url, init);
  };
  const id4 = identity.make({ fetch: flaky, wallet: W });
  await id4.mode(); await id4.signIn();
  await assert.rejects(id4.getTrenchie({ preset: 'looter-lob', sheet: SHEET }), /owned by nobody/);
  const again = await id4.getTrenchie({ preset: 'looter-lob', sheet: SHEET });
  assert.deepStrictEqual([again.token_id, again.tx], ['paid-h1', 'MINTTX']);
  assert.strictEqual(w4.calls.filter((x) => x[0] === 'send').length, 1, 'one paid_mint sent, however many confirms');

  // a free claim only when the player plays the premint persona; a built fighter is a paid mint even while claims last
  W._reset(); const w2 = wallet(); W._adoptSession('testnet', w2, 'p.testnet');
  const h2 = host({ kind: 'claim', held: 3, cost_yocto: '0' });
  const id2 = identity.make({ fetch: h2.fetch, wallet: W });
  await id2.mode(); await id2.signIn();
  const c = await id2.getTrenchie({ preset: 'hunter-lunge', sheet: SHEET, claim: true });
  assert.deepStrictEqual([c.how, c.token_id, c.tx], ['claim', 'hunter-lunge-00', 'CLAIMTX']);
  assert.strictEqual(w2.calls.filter((x) => x[0] === 'send').length, 0, 'a claim sends no wallet transaction');
  const id5 = identity.make({ fetch: host({ kind: 'claim', held: 3, cost_yocto: '0' }).fetch, wallet: W });
  await id5.mode(); await id5.signIn();
  assert.strictEqual((await id5.getTrenchie({ preset: 'hunter-lunge', sheet: SHEET, claim: false })).how, 'paid');

  // no sign-in, no trenchie; a refused signature says so
  const id3 = identity.make({ fetch: h2.fetch, wallet: W });
  await assert.rejects(id3.getTrenchie({ preset: 'x' }), /sign in with your wallet first/);
  W._reset();
  await id3.mode();
  await assert.rejects(id3.signIn(), /did not sign in: connect a wallet on testnet first/);
  console.log('test_identity.cjs: 5 cases OK');
})().catch((e) => { console.error(e); process.exit(1); });
