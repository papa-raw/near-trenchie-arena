// Snap a trenchie in through board 1's guide, the way a player does: the throwaway wallet, a battle option, its name, an AI
// key door (Test answered, an hourly cap), the check page, Snap in. For the cases that need a trenchie in the ring and
// test something else; board1_guide_case.cjs is the one that checks the guide's own screens.
// The case supplies the provider's answer to Test (its own route on the page's context); no key is real, nothing is spent.
//   const G = require('./board1_flow.cjs');
//   await G.snapIn(page, { url: base + '/web/snapin/index.html', name: 'Chatpip', preset: 'Survivor Beam', claim: false });
'use strict';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function act(p, a) { await p.click(`[data-act="${a}"]`); await sleep(250); }
async function ready(p) { await p.waitForFunction(() => window.__SNAPIN_READY === true, null, { timeout: 60000 }); }
// o: url (the guide, any query kept: ws=...), name, preset ('Brawler Swing' …), claim (true: Use this preset; default false:
// Build a fighter), door ('NEAR AI Cloud' default), key ('sk-case-…' default), cap ('0.20' default: board 1 snaps in only
// with an hourly cap, Pat's Q2), clearCapAfter (true: once in, the cap is removed again, for a case that tests what the page
// does with no cap), snap (default true), waitIn (ms, default 90000; 0 = do not wait), skipGoto (already on the guide)
async function snapIn(p, o) {
  o = Object.assign({ door: 'NEAR AI Cloud', key: 'sk-case-not-a-real-key-6986', cap: '0.20', snap: true, waitIn: 90000 }, o || {});
  if (!o.skipGoto) { const u = new URL(o.url); u.searchParams.set('step', 'wallet'); await p.goto(u.toString()); await ready(p); }
  if (!(await p.evaluate(() => !!Snapin.state.wallet))) await act(p, 'g:wallet:dev-throwaway');
  else await act(p, 'g:step:presets');
  if (o.preset) await act(p, 'g:preset:' + o.preset);
  await act(p, o.claim ? 'g:use' : 'g:build');
  await p.waitForFunction(() => Snapin.view.step === 'personality', null, { timeout: 30000 });
  await sleep(400);
  if (o.name) { await p.fill('#name', o.name); await sleep(500); }
  await p.waitForFunction(() => !document.querySelector('.bar .gold[disabled]'), null, { timeout: 15000 }).catch(() => {});
  await act(p, 'g:step:doors');
  await act(p, 'g:door:key:' + o.door);
  await p.fill('#key', o.key); await act(p, 'g:test');
  await p.waitForFunction(() => /It answered/.test(document.body.innerText), null, { timeout: 20000 });
  if (o.cap) await act(p, 'g:cap:' + o.cap);
  await act(p, 'g:step:agree');
  await p.waitForFunction(() => Snapin.view.terms && Snapin.view.terms.version && !!document.querySelector('[data-act="g:snap"]'), null, { timeout: 20000 });
  if (!o.snap) return null;
  const guideUrl = p.url();
  await act(p, 'g:snap');
  if (!o.waitIn && !o.clearCapAfter) return null;
  const where = await afterSnap(p, { timeout: o.waitIn || 90000, guideUrl, backToGuide: o.backToGuide !== false });
  if (o.clearCapAfter) await p.evaluate(() => { try { localStorage.removeItem('trenchie.snapin.cap'); } catch (e) { /* none */ } });
  return where;
}
// After Snap in: board 1 lands on the arena page's trenchie panel when this browser keeps the session (its key stored), or
// stays on the guide's ring view when it cannot. Waits for the trenchie to be in on whichever page holds it; with
// backToGuide, comes back to the guide's ring view (for a case that tests something there). Resolves 'arena' or 'guide'.
async function afterSnap(p, o) {
  const end = Date.now() + (o.timeout || 90000); let where = '';
  while (!where && Date.now() < end) {
    if (/\/web\/arena\.html/.test(p.url())) where = 'arena';
    else { const s = await p.evaluate(() => window.SnapRoom ? { phase: SnapRoom.status().phase, kept: SnapRoom.status().keyPersisted } : null).catch(() => null);
      if (s && s.phase === 'in' && s.kept === false) where = 'guide'; else if (s && s.phase === 'error') throw new Error('the join failed: ' + await p.evaluate(() => SnapRoom.status().message)); }
    if (!where) await sleep(300);
  }
  if (!where) throw new Error('after Snap in, neither the arena page nor the trenchie in the guide');
  if (where === 'arena') {
    await p.waitForFunction(() => window.SnapRoom && SnapRoom.status().phase === 'in', null, { timeout: Math.max(5000, end - Date.now()) });
    if (o.backToGuide && o.guideUrl) { const u = new URL(o.guideUrl); u.searchParams.set('step', 'ring'); await p.goto(u.toString()); await ready(p); await p.waitForFunction(() => SnapRoom.status().phase === 'in', null, { timeout: 30000 }); }
  }
  return where;
}
// the provider's answer to Test, on a browser context: 200 with a line, unless the case says otherwise
async function fakeNearAI(ctx, answer) {
  await ctx.route('https://cloud-api.near.ai/**', (r) => r.request().method() === 'OPTIONS'
    ? r.fulfill({ status: 204, headers: { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': 'POST' } })
    : r.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify({ choices: [{ message: { content: answer || 'hi' } }] }) }));
}
module.exports = { snapIn, afterSnap, fakeNearAI, act, ready };
