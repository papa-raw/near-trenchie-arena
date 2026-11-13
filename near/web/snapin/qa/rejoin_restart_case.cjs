// One real-browser regression: restart the hosted HTTP process under a seated browser player.
// NODE_PATH=<Playwright module directory> node near/web/snapin/qa/rejoin_restart_case.cjs
// External chains are local fixtures; wallet/page/control signatures and room admission are real.
'use strict';
const assert = require('assert'), fs = require('fs'), path = require('path'), crypto = require('crypto');
const { chromium } = require('playwright');
const HOSTS = require('./hosts.cjs');
const ROOT = HOSTS.REPO, PORT = Number(process.env.REJOIN_TEST_PORT || 18736), origin = `http://127.0.0.1:${PORT}`;
const tmp = fs.mkdtempSync(path.join(require('os').tmpdir(), 'trenchie-rejoin-'));
const wallet = crypto.generateKeyPairSync('ed25519');
const raw = wallet.publicKey.export({ format: 'jwk' }).x;
function b58(bytes) {
  const alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
  let x = BigInt('0x' + bytes.toString('hex')), s = '';
  while (x) { s = alphabet[Number(x % 58n)] + s; x /= 58n; }
  for (const b of bytes) { if (b) break; s = '1' + s; }
  return s;
}
const publicKey = 'ed25519:' + b58(Buffer.from(raw, 'base64url'));
let signatures = 0, browser;
async function until(check, timeout) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    if (await check()) return;
    await new Promise(r => setTimeout(r, 100));
  }
  throw new Error('fixture condition timed out');
}
function start() {
  const h = HOSTS.host(['-I', 'near/chain/test_identity_persist.py', '--host', path.join(tmp, 'state'), String(PORT), publicKey, 'player-one.testnet']);
  let log = '';
  h.stdout.on('data', b => { log += b; }); h.stderr.on('data', b => { log += b; });
  return { child: h, log: () => log };
}
async function stop(host) {
  if (host.child.exitCode !== null) return;
  await new Promise(resolve => { host.child.once('exit', resolve); host.child.kill('SIGTERM'); });
}
(async () => {
  try {
    browser = await chromium.launch(process.env.HTTPS_PROXY ? {
      args: ['--single-process', '--no-zygote', '--proxy-bypass-list=<-loopback>'], proxy: { server: process.env.HTTPS_PROXY }
    } : {});
    const context = await browser.newContext();
    await context.route('**/case.html', route => route.fulfill({ contentType: 'text/html', body: '<!doctype html><script src="/web/snapin/identity.js"></script><script src="/web/snapin/room.js"></script><script src="/web/snapin/brain.js"></script>' }));
    await context.route('**/web/snapin/*.js', route => {
      const file = path.basename(new URL(route.request().url()).pathname);
      return route.fulfill({ contentType: 'text/javascript', body: fs.readFileSync(path.join(ROOT, 'near/web/snapin', file)) });
    });
    const p = await context.newPage();
    const errors = [];
    p.on('pageerror', e => errors.push(e.message));
    await p.exposeFunction('signWallet', args => {
      signatures++;
      const message = Buffer.from(args.message), recipient = Buffer.from(args.recipient);
      const tag = Buffer.alloc(4), ml = Buffer.alloc(4), rl = Buffer.alloc(4);
      tag.writeUInt32LE(2 ** 31 + 413); ml.writeUInt32LE(message.length); rl.writeUInt32LE(recipient.length);
      const digest = crypto.createHash('sha256').update(Buffer.concat([tag, ml, message, Buffer.from(args.nonce, 'base64url'), rl, recipient, Buffer.from([0])])).digest();
      return { ok: true, accountId: 'player-one.testnet', publicKey, signature: crypto.sign(null, digest, wallet.privateKey).toString('base64') };
    });
    let host = start();
    await p.goto(origin + '/case.html');
    async function ready() {
      await until(() => p.evaluate(async () => { try { return !!(await (await fetch('/dev/health', { cache: 'no-store' })).json()).chain_mode; } catch { return false; } }), 20000);
    }
    await ready();
    const sheet = JSON.parse(fs.readFileSync(path.join(ROOT, 'near/web/snapin/premint/pike-pennywhistle.json')));
    await p.evaluate(async sheet => {
      window.id = SnapIdentity.make({ wallet: { signMessage: args => window.signWallet(args) } });
      if (!(await id.mode())) throw new Error('fixture has no chain mode: ' + (await (await fetch('/dev/health', { cache: 'no-store' })).text()).slice(0,300)); await id.signIn();
      const token = await id.getTrenchie({ preset: 'hunter-lunge', tokenId: 'preset-2-00' });
      const key = await SnapRoom.sessionKey();
      localStorage.setItem('trenchie.snapin.v1', JSON.stringify({ name: 'Pike', sheet, door: { door: 'NEAR AI Cloud', route: 'key' } }));
      localStorage.setItem('trenchie.snapin.cap', '7.5');
      localStorage.setItem('trenchie.snapin.brain.goal', 'Guard the shore');
      localStorage.setItem('trenchie.snapin.brain.spend', JSON.stringify([{ at: Date.now(), usd: 0.25 }]));
      window.kept = Object.fromEntries(['trenchie.snapin.v1','trenchie.snapin.cap','trenchie.snapin.brain.goal','trenchie.snapin.brain.spend'].map(k => [k, localStorage.getItem(k)]));
      await SnapRoom.join({ name: 'Pike', preset: 'hunter-lunge', sheet, termsVersion: '1', order: { preset: 'hunter-lunge', prediction: false },
        chain: { nft_token_id: token.token_id, network: 'testnet', session_public_key: key,
          ticket: await id.ticket(token.token_id, { session_public_key: key, name: 'Pike', preset: 'hunter-lunge' }) } });
      SnapRoom.on(s => { window.lastRoom = s; });
    }, sheet);
    await until(() => p.evaluate(async () => {
      const ob = await SnapRoom.observe();
      return SnapRoom.status().phase === 'in' && ob.fighters.some(f => f.nft_token_id === 'preset-2-00' && f.state === 'ring');
    }), 20000);
    await p.evaluate(() => SnapRoom.setOrder({ spread: [10, 20, 30, 40], zero: 17, prediction: false }));
    const before = await p.evaluate(() => SnapRoom.status().fighter.life);
    await stop(host); host = start(); await ready();
    const returned = Date.now();
    try {
      await until(() => p.evaluate(async () => {
        const ob = await SnapRoom.observe();
        return SnapRoom.status().phase === 'in' && ob.fighters.some(f => f.nft_token_id === 'preset-2-00' && f.state === 'ring');
      }), 10000);
    } catch {
      throw new Error('no automatic seated return after restart: ' + JSON.stringify(await p.evaluate(() => SnapRoom.status())));
    }
    const ms = Date.now() - returned;
    assert.strictEqual(signatures, 1, 'no second wallet message');
    assert(await p.evaluate(() => Object.entries(kept).every(([k,v]) => localStorage.getItem(k) === v)), 'same AI, cap, goal and spend');
    assert.strictEqual(await p.evaluate(() => SnapRoom.status().fighter.id), 'preset-2-00');
    assert.deepStrictEqual(await p.evaluate(() => SnapRoom.status().fighter.lastPick.order.spread), [10,20,30,40], 'current choices survive');
    assert.strictEqual(await p.evaluate(() => SnapRoom.status().fighter.lastPick.order.zero), 17);
    assert.strictEqual(errors.length, 0, errors.join('\n'));
    // A player who leaves from a live seat stays out after another restart.
    await p.evaluate(() => SnapRoom.leave());
    await stop(host); host = start(); await ready(); await p.waitForTimeout(1500);
    assert(await p.evaluate(async () => !(await SnapRoom.observe()).fighters.some(f => f.nft_token_id === 'preset-2-00')), 'left fighter stays out');
    // Set up a fresh seat explicitly only to test the independent Stay on the bench choice.
    await p.evaluate(async sheet => {
      await id.getTrenchie({ preset: 'hunter-lunge', tokenId: 'preset-2-00' });
      const key = await SnapRoom.sessionKey();
      await SnapRoom.join({ name: 'Pike', preset: 'hunter-lunge', sheet, termsVersion: '1', order: { preset: 'hunter-lunge', prediction: false },
        chain: { nft_token_id: 'preset-2-00', network: 'testnet', session_public_key: key,
          ticket: await id.ticket('preset-2-00', { session_public_key: key, name: 'Pike', preset: 'hunter-lunge' }) } });
      const r = await SnapRoom.bench({ hold: true });
      if (r.ack.status !== 'applied') throw new Error('fixture hold was refused');
    }, sheet);
    await stop(host); host = start(); await ready();
    await p.waitForTimeout(2500);
    assert(await p.evaluate(async () => !(await SnapRoom.observe()).fighters.some(f => f.nft_token_id === 'preset-2-00')), 'held fighter stays out after restart');
    console.log(JSON.stringify({ case: 'browser rejoin after host restart', seatedBefore: true, lifeBefore: before, returnedMs: ms, walletSignatures: signatures, sameSettings: true, benchAndLeaveExcluded: true }));
  } finally {
    if (browser) await browser.close();
    const left = await HOSTS.finish();
    fs.rmSync(tmp, { recursive: true, force: true });
    assert.strictEqual(left.length, 0, 'fixture hosts stopped');
  }
})().catch(e => { console.error(e.stack); process.exitCode = 1; });
