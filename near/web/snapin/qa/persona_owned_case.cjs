// A real guide/Claude API door must join an owned premint with its minted sheet, despite a stale different draft.
// NODE_PATH=<Playwright module directory> node near/web/snapin/qa/persona_owned_case.cjs
// External chains are local fixtures; wallet/page/control signatures and room admission are real.
'use strict';
const assert = require('assert'), fs = require('fs'), path = require('path'), crypto = require('crypto');
const { chromium } = require('playwright');
const HOSTS = require('./hosts.cjs');
const ROOT = HOSTS.REPO, PORT = Number(process.env.REJOIN_TEST_PORT || 18736), origin = `http://127.0.0.1:${PORT}`;
const tmp = fs.mkdtempSync(path.join(require('os').tmpdir(), 'trenchie-persona-'));
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
    try { if (await check()) return; } catch (e) { if (!/Execution context was destroyed/.test(e.message)) throw e; }
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
    await context.route((url) => !['127.0.0.1','localhost'].includes(url.hostname), route => route.abort());
    await context.route('https://api.anthropic.com/v1/messages', route => route.fulfill({ json: {
      content: [{ type: 'text', text: 'The fixture AI is ready.' }], usage: { input_tokens: 1, output_tokens: 1 }
    }, headers: { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*' } }));
    await context.route(origin + '/web/**', route => {
      const url = new URL(route.request().url()), rel = decodeURIComponent(url.pathname.slice('/web/'.length));
      const file = path.resolve(ROOT,'near/web',rel);
      if (!file.startsWith(path.join(ROOT,'near/web') + path.sep)) return route.abort();
      if (url.pathname === '/web/arena.html') return route.fulfill({ contentType: 'text/html', body: '<!doctype html><p>Joined the arena</p>' });
      if (!fs.existsSync(file) || !fs.statSync(file).isFile()) return route.continue();
      const mime = { '.js':'text/javascript','.mjs':'text/javascript','.css':'text/css','.html':'text/html','.json':'application/json','.png':'image/png','.svg':'image/svg+xml','.woff2':'font/woff2' };
      return route.fulfill({ contentType: mime[path.extname(file)] || 'application/octet-stream', body: fs.readFileSync(file) });
    });
    await context.route(origin+'/ready.html',route=>route.fulfill({contentType:'text/html',body:'<!doctype html>'}));
    const p = await context.newPage();
    p.on('pageerror', e=>console.error('fixture pageerror: '+e.message));
    await p.exposeFunction('signWallet', args => {
      signatures++;
      const message=Buffer.from(args.message), recipient=Buffer.from(args.recipient);
      const tag=Buffer.alloc(4), ml=Buffer.alloc(4), rl=Buffer.alloc(4);
      tag.writeUInt32LE(2**31+413); ml.writeUInt32LE(message.length); rl.writeUInt32LE(recipient.length);
      const digest=crypto.createHash('sha256').update(Buffer.concat([tag,ml,message,Buffer.from(args.nonce,'base64url'),rl,recipient,Buffer.from([0])])).digest();
      return { ok:true,accountId:'player-one.testnet',publicKey,signature:crypto.sign(null,digest,wallet.privateKey).toString('base64') };
    });
    start();
    await p.goto(origin+'/ready.html');
    await until(()=>p.evaluate(async()=>{try{return !!(await (await fetch('/dev/health',{cache:'no-store'})).json()).chain_mode;}catch{return false;}}),20000);
    await p.goto(origin+'/web/snapin/index.html?step=wallet');
    await until(() => p.evaluate(() => !!window.__SNAPIN_READY && !!window.SnapIdentity?.state().mode),20000);
    await p.evaluate(() => {
      SnapWallet.connect=async () => ({ ok:true,accountId:'player-one.testnet',walletId:'fixture',network:'testnet' });
      SnapWallet.signMessage=args=>window.signWallet(args);
    });
    // This is the stale local Brawler draft shown when the same wallet already owns a Hunter NFT.
    await p.evaluate(async () => {
      const meta=await (await fetch('premint/meta/options.json')).json(), e=meta['brawler-swing'];
      const sheet=await (await fetch('premint/'+e.file)).json(), look=await (await fetch('premint/'+e.look)).json();
      Object.assign(Snapin.state,{preset:'Brawler Swing',name:e.name,temper:e.temper,quirks:e.quirks,voice:e.voice,look:look.look,
        claim:{preset:'Brawler Swing',option:'brawler-swing',digest:e.digest,name:e.name,temper:e.temper,quirks:e.quirks,voice:e.voice,look:look.look,sheet}});
    });
    await p.click('[data-act="g:wallet:choose"]');
    await until(() => p.evaluate(() => Snapin.view.step==='presets' && !!Snapin.state.wallet?.chain),15000);
    await p.click('[data-act="g:use"]');
    await until(() => p.evaluate(() => Snapin.view.step==='personality' && SnapGuide.state.name.free===true),10000);
    assert.equal(await p.inputValue('#name'),'Pike Pennywhistle');
    assert.equal(await p.isDisabled('#name'),true,'minted name cannot be edited');
    assert.match(await p.innerText('body'),/fixed when it was minted/);
    await p.click('[data-act="g:step:doors"]');
    await p.click('[data-act="g:door:key:Claude"]');
    await p.fill('#key','fixture-not-a-real-key'); await p.click('[data-act="g:test"]');
    await until(() => p.evaluate(() => SnapGuide.state.keyStatus==='ok'),10000);
    await p.click('[data-act="g:cap:0.20"]'); await p.click('[data-act="g:step:agree"]');
    await until(() => p.evaluate(() => !!Snapin.view.terms?.version),10000);
    const mismatch=await p.evaluate(async()=>{
      const wrong=await (await fetch('premint/barnacle-bertie.json')).json();
      try { await SnapIdentity.getTrenchie({preset:'brawler-swing',sheet:wrong}); return ''; } catch(e) {return e.message;}
    });
    assert.match(mismatch,/fixed personality/,'owned token selection refuses a different sheet');
    await p.click('[data-act="g:snap"]');
    await until(() => p.evaluate(async () => {
      if (window.SnapRoom?.status().phase==='error') throw new Error('Claude browser join refused: '+SnapRoom.status().message);
      const ob=await (await fetch('/room/observe')).json();
      return ob.fighters?.some(f=>f.nft_token_id==='preset-2-00' && f.state==='ring');
    }),20000);
    assert.equal(signatures,1);
    const kept=await p.evaluate(()=>({draft:JSON.parse(localStorage.getItem('trenchie.snapin.v1')),cap:localStorage.getItem('trenchie.snapin.cap'),key:localStorage.getItem('trenchie.snapin.key.Claude')}));
    assert.equal(kept.draft.sheet.game.name,'Pike Pennywhistle'); assert.equal(kept.draft.preset,'Hunter Lunge');
    assert.equal(kept.cap,'0.2'); assert.equal(kept.key,'fixture-not-a-real-key');
    console.log('persona-owned-case: stale Bertie draft + owned Hunter joins through Claude API with exact Pike sheet; key/cap retained; one wallet signature');
  } finally {
    if (browser) await browser.close();
    assert.deepEqual(await HOSTS.finish(),[]); fs.rmSync(tmp,{recursive:true,force:true});
  }
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
