// Board 1's trenchie panel on the arena page, each state reached for real on the real DEV arena and read off the screen
// against SPEC.md's lines for that state: the panel's own words in order, with this run's values where the sheet drew its
// sample (the name, the four items, HP, the money, the times). The log's entries are the arena's own and are checked by kind.
// SPEC's 2026-11-13 panel supersession: red Leave replaces Follow; Chat is default, gear/bench are behind Gear.
//   fight      a trenchie snapped in through the guide (NEAR AI Cloud, cap $0.20) lands here
//   thinking   an order while its model call is out (the case's provider answers after 15 s), then the reply and its receipt
//   changecap  Change cap: $0.10 $0.20 $0.50 $1.00 and Set cap; $0.50 set shows in the money line
//   capped     the hour's spend at the cap (a labelled fixture: the spend window the brain reads), Raise cap
//   bench      after a real KO, Stay on the bench: held, the 45 s stopped, Send back in
//   closed     × leaves the edge tab with Open; Open brings the panel back
//   agent-codex  a Codex session joined with the door's code (snap.py live --code --fifo): its session line, "not reported",
//              its note (the order in its owner's words, reply, why) joined to its flee receipt, the read-only order box
//   agent-claude the same for a Claude Code session that reports its plan use: "Plan this week: 4% of your 10% stop"
// The provider's answers are the case's (no key, no spend). usage: node .../board1_panel_case.cjs <SPEC.md>
'use strict';
const path = require('path'), fs = require('fs'), os = require('os');
const { chromium } = require('playwright');
if (!process.env.CASE_TIMEOUT_MS) process.env.CASE_TIMEOUT_MS = '1500000';   // seven states over real KOs and respawns: 25 min at most
const HOSTS = require('./hosts.cjs'), G = require('./board1_flow.cjs');
let pass = 0, fail = 0;
const T0 = Date.now(), at = () => '[' + Math.round((Date.now() - T0) / 1000) + ' s]';
const ok = (c, m) => { if (c) { pass++; console.log('PASS', m, at()); } else { fail++; console.log('FAIL', m, at()); } };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const SPEC = process.argv[2] || process.env.SPEC_MD;
if (!SPEC || !fs.existsSync(SPEC)) { console.log('FAIL give the path to SPEC.md (argument or SPEC_MD)'); process.exit(1); }
const COPY = {};
fs.readFileSync(SPEC, 'utf8').split(/\n### `/).slice(1).forEach((sec) => { const id = sec.slice(0, sec.indexOf('`')), m = sec.match(/```\n([\s\S]*?)\n```/); if (m) COPY[id] = m[1].split('\n').map((l) => l.trim()).filter(Boolean); });
const TMP = fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), 'board1-panel-'));
const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
(async () => {
  const port = 20000 + Math.floor(Math.random() * 20000), arenaUrl = 'http://127.0.0.1:' + port;
  const arena = await HOSTS.start(['near/arena/snap_local.py', '--port', String(port)], (o) => (o.match(/X-Dev-Admin: (\S+)/) || [])[1]);
  const web = await HOSTS.start(['near/web/snapin/serve.py', '--port', '0', '--arena', arenaUrl], (o) => (o.match(/http:\/\/127\.0\.0\.1:(\d+)\//) || [])[1]);
  const guide = 'http://127.0.0.1:' + web.m + '/web/snapin/index.html?ws=' + encodeURIComponent('ws://127.0.0.1:' + port);
  let b = null; const errs = [];
  try {
    b = await chromium.launch({ args: ['--single-process', '--no-zygote'] });
    const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } });
    // the provider: Test's hello, then the brain's order call (a behaviour and an in-voice reply), slow on purpose
    let slow = 0;
    await ctx.route('https://cloud-api.near.ai/**', async (r) => {
      if (r.request().method() === 'OPTIONS') return r.fulfill({ status: 204, headers: { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': 'POST' } });
      const body = r.request().postData() || '', order = /Middle it is|own words|owner/i.test(body) && /behaviour/.test(body);
      if (order && slow) await sleep(slow);
      const content = order ? JSON.stringify({ behaviour: { v: 1, drives: { loot: 8, hold_area: 7 }, area: 'middle', radius: 3 }, reply: 'Middle it is. Loot first, fists second.' }) : 'Ahoy! Ready when you are.';
      return r.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': '*' }, body: JSON.stringify({ choices: [{ message: { content } }], usage: { prompt_tokens: 700, completion_tokens: 40 } }) });
    });
    const p = await ctx.newPage(); p.on('pageerror', (e) => errs.push(e.message));
    // On the arena page this single-process Chromium is starved by the WebGL loop and Playwright's own click stalls at
    // "waiting for locator"; so a click here is what a player's click resolves to: the element must be the topmost thing
    // at its centre (hit-tested in the page), then it is clicked there. Typing goes in the same way.
    const tapOn = async (pg, sel) => {
      for (let i = 0; i < 30; i++) {
        const r = await pg.evaluate((s) => { const e = document.querySelector(s); if (!e) return 'absent'; const b = e.getBoundingClientRect(); if (!b.width) return 'no box';
          const top = document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2); if (!(top === e || e.contains(top))) return 'covered by ' + (top && top.tagName + '.' + top.className);
          if (e.disabled) return 'disabled'; e.click(); return 'ok'; }, sel).catch((x) => 'err ' + x.message);
        if (r === 'ok') { await sleep(250); return; }
        if (i === 29) throw new Error('could not click ' + sel + ': ' + r + ' (panel: ' + (await pg.evaluate(() => (document.getElementById('b1-panel') || {}).innerText || '')).replace(/\s+/g, ' ').slice(0, 160) + ')');
        await sleep(300);
      }
    };
    const tap = (sel) => tapOn(p, sel);
    const type = (pg, sel, text) => pg.evaluate(([s, t]) => { const e = document.querySelector(s); if (!e) return false; e.focus(); e.value = t; e.dispatchEvent(new Event('input', { bubbles: true })); return true; }, [sel, text]);
    const lines = async () => (await p.evaluate(() => { const e = document.getElementById('b1-panel'); return e && !e.hidden ? e.innerText : ''; })).replace(/\u00a0/g, ' ').split('\n').map((l) => l.trim()).filter(Boolean);
    // in order: each expected line (a string or a regex) found after the previous one
    const inOrder = (want, got) => { let j = 0; for (const g of got) { const w = want[j]; if (w === undefined) break; if (typeof w === 'string' ? g === w : w.test(g)) j++; } return j === want.length ? '' : 'missing: ' + String(want[j]); };
    const TABS = ['Chat', /^Gear(?:\s*●)?$/];
    // Read Gear from its visible pane, against the same host corner used by the panel; restore Chat afterward.
    // This preserves the equipped names/bag checks after their move out of the conversation.
    async function checkGear(pg, id) {
      await tapOn(pg, '[data-pn="tab:gear"]');
      for (const width of [1440, 390]) {
        await pg.setViewportSize({ width, height: width === 390 ? 844 : 900 }); await sleep(900);
        const g = await pg.evaluate(() => {
          const panel = document.getElementById('b1-panel'), corner = SnapPanel.state.corner, b = corner && corner.bench;
          if (!panel || !b) return { error: 'no host gear reading' };
          const pane = panel.querySelector('#pn-gear'), chat = panel.querySelector('#pn-chat');
          if (!pane || !chat) return { error: 'Chat/Gear panes missing' };
          const bench = pane.querySelector('.benchb');
          const slots = ['head', 'body', 'weapon', 'trinket'];
          const equipped = slots.map((slot) => (b.equipped || []).find((item) => item.slot === slot)).filter(Boolean).map((item) => item.name);
          const shown = Array.from(pane.querySelectorAll(bench ? '.gear .slot b' : '.gearrow .gi span')).map((node) => node.textContent);
          const expectedBag = (b.bag || []).map((item) => item.name), shownBag = Array.from(pane.querySelectorAll('.bag .slot b')).map((node) => node.textContent);
          const bag = pane.querySelector('.bagl'), tab = panel.querySelector('#pn-tab-gear'), heading = pane.querySelector(bench ? '.eyebrow' : '.gearrow .gh');
          return { selected: tab && tab.getAttribute('aria-selected') === 'true', visible: !!pane && !pane.hidden && pane.clientHeight > 0,
            chatHidden: !!chat && chat.hidden, equipped, shown, bench: !!bench, expectedBag, shownBag,
            bagLine: bag && bag.textContent, bagCount: expectedBag.length, heading: heading && heading.textContent,
            headingVisible: !!heading && heading.getBoundingClientRect().height > 0 };
        });
        ok(!g.error && g.selected && g.visible && g.chatHidden && g.equipped.length > 0 && JSON.stringify(g.shown) === JSON.stringify(g.equipped) &&
          g.heading === (g.bench ? 'Equipped · Tap an item to swap' : 'Equipped') && (width === 390 || g.headingVisible) &&
          (g.bench ? JSON.stringify(g.shownBag) === JSON.stringify(g.expectedBag) : g.bagLine === 'Bag · ' + g.bagCount),
        `${id} Gear at ${width}: equipped names and bag match the host in their own visible pane${g.error ? ' | ' + g.error : ' | ' + JSON.stringify(g)}`);
      }
      await pg.setViewportSize({ width: 1440, height: 900 }); await tapOn(pg, '[data-pn="tab:chat"]');
    }
    // One reading at 1440 and at 390 ('' when both hold); the phone layout hides the rate.
    async function read(want, only390) {
      const m1440 = inOrder(want, await lines());
      await p.setViewportSize({ width: 390, height: 844 }); await sleep(900);
      const want390 = only390 || want.map((w) => typeof w === 'string' && / · About \$0\.10 an hour$/.test(w) ? new RegExp('^' + esc(w.replace(/ · About \$0\.10 an hour$/, '')) + '( · About \\$0\\.10 an hour)?$') : w instanceof RegExp && / · About /.test(w.source) ? new RegExp(w.source.replace(/ · About \\\$0\\\.10 an hour\$$/, '( · About \\$0\\.10 an hour)?$')) : w).map((w) => w instanceof RegExp && / · Resets at /.test(w.source) ? new RegExp(w.source.replace(' · Resets at \\d\\d:\\d\\d$', '( · Resets at \\d\\d:\\d\\d)?$')) : w);   // the phone hides the rate and reset tail (.w390 .rate)
      const m390 = inOrder(want390, await lines());
      await p.setViewportSize({ width: 1440, height: 900 }); await sleep(600);
      return (m1440 ? '1440 ' + m1440 : '') + (m390 ? ' 390 ' + m390 : '');
    }
    // the arena KOs a newcomer often: a state is read again (its precondition first, when it has one) until a reading holds,
    // for at most 240 s of readings per state. A reading of the page takes 3-9 s while the machine is loaded (the software
    // WebGL loop holds the page's thread), so a count of tries would run a missing state for ten minutes before saying so.
    async function check(id, want, note, prepare, want390) {
      let miss = 'not read'; const until = Date.now() + 240000;
      for (let k = 0; miss && Date.now() < until; k++) { if (prepare) await prepare(k); for (let i = 0; i < 4 && Date.now() < until; i++) { miss = await read(want, want390); if (!miss) break; await sleep(400); } }
      ok(!miss, `${id}: the panel shows SPEC's lines for this state, in order, at 1440 and 390${note ? ' ' + note : ''}${miss ? ' | ' + miss : ''}`);
      return !miss;
    }
    // 390 with the panel open (found in review): the sheet starts at y 290 or lower in every state, the
    // arena draws above it with the ring's centre in the free strip between the sign and the sheet (f-fight-390.png keeps the
    // ring in view), and no corner button touches the sign's boards
    async function layout390(id) {
      await p.setViewportSize({ width: 390, height: 844 }); await sleep(1500);
      const g = await p.evaluate(() => {
        const r = (e) => { if (!e) return null; const b = e.getBoundingClientRect(); return b.width > 0 && b.height > 0 ? { l: b.left, t: b.top, r: b.right, b: b.bottom } : null; };
        const ring = window.__arenaRingOutline ? window.__arenaRingOutline() : [], n = ring.length || 1;
        return { panel: r(document.querySelector('[data-arena-panel]')), board: r(document.querySelector('#world [data-panel="board"]')),
          btns: ['btn0', 'btn1'].map((k) => r(document.querySelector('#world [data-panel="' + k + '"]'))).filter(Boolean),
          canvas: r(document.getElementById('stage')), cx: ring.reduce((t, q) => t + q[0], 0) / n, cy: ring.reduce((t, q) => t + q[1], 0) / n };
      });
      await p.setViewportSize({ width: 1440, height: 900 }); await sleep(800);
      const top = g.board ? g.board.b : 0, hit = (a, c) => a && c && a.l < c.r && a.r > c.l && a.t < c.b && a.b > c.t;
      const ringIn = g.panel && g.cx > 0 && g.cx < 390 && g.cy > top && g.cy < g.panel.t;
      ok(g.panel && g.panel.t >= 290 && ringIn && !g.btns.some((x) => hit(x, g.board)),
        `${id} at 390: the panel starts at y ${g.panel && Math.round(g.panel.t)} (>= 290), the ring's centre is at y ${Math.round(g.cy)} in the free strip ${Math.round(top)}-${g.panel && Math.round(g.panel.t)} (canvas ${g.canvas && Math.round(g.canvas.b)} px tall), ${g.board ? 'no corner button on the sign\'s boards' : 'no wall sign on this tree (main took it out), so no board to cover'}`);
    }
    // ---- fight
    const where = await G.snapIn(p, { url: guide, name: 'Barnacle Bertie', preset: 'Brawler Swing', backToGuide: false });
    ok(where === 'arena', `Snap in lands on the arena page (${where})`);
    await p.waitForFunction(() => { const e = document.getElementById('b1-panel'); return e && /Fighting/.test(e.innerText); }, null, { timeout: 60000 }).catch(() => {});
    const items = (await p.evaluate(() => (SnapPanel.state.corner && SnapPanel.state.corner.bench && SnapPanel.state.corner.bench.equipped || []).map((x) => [x.slot, x.name])));
    const order = ['head', 'body', 'weapon', 'trinket'], names = order.map((k) => (items.find((x) => x[0] === k) || [])[1]).filter(Boolean);
    const HEAD = ['Barnacle Bertie', /^Life \d+ · NEAR AI Cloud$/, 'HP', /^\d+\/\d+$/];
    ok(await p.evaluate(() => document.querySelector('#pn-tab-chat[aria-selected="true"]') && !document.getElementById('pn-chat').hidden && document.getElementById('pn-gear').hidden), 'Chat is the default pane after Snap in');
    // Capped: Chat offers Raise cap instead of Send; Gear stays in its own pane in or out of the ring.
    const ownTactics = () => p.waitForFunction(() => { const e = document.getElementById('b1-panel'), c = SnapPanel.state.corner, bn = c && c.bench; return e && /Own tactics/.test(e.innerText) && /Cap reached/.test(e.innerText) && !(bn && (bn.held || bn.down)); }, null, { timeout: 90000 }).catch(() => {});
    const fighting = () => p.waitForFunction(() => { const e = document.getElementById('b1-panel'); return e && /Fighting/.test(e.innerText) && document.getElementById('pn-order'); }, null, { timeout: 120000 }).catch(() => {});
    await check('fight', [...HEAD, 'Fighting', 'Leave', '×', 'This hour $0.00 of your $0.20 cap', 'This visit $0.00 · About $0.10 an hour', 'Change cap', ...TABS, /^\d\d:\d\d Snapped in\. Life 1 on NEAR AI Cloud\.$/, 'One order every 0.5 s', 'Send'], `(items: ${names.join(', ')})`, fighting);
    for (const width of [1440, 390]) {
      await p.setViewportSize({ width, height: width === 390 ? 844 : 900 }); await sleep(900);
      ok(await p.evaluate(() => { const panel = document.getElementById('b1-panel'), leave = panel.querySelector('[data-pn="leave"]'); return !!leave && getComputedStyle(leave).color === 'rgb(194, 69, 58)' && !panel.querySelector('[data-pn="follow"]'); }), `header at ${width}: red Leave replaces Follow`);
    }
    await p.setViewportSize({ width: 1440, height: 900 });
    await checkGear(p, 'fight');
    await layout390('fight');
    // ---- thinking, then the reply and its receipt
    slow = 15000;   // the answer stays out long enough for a reading at 1440 and one at 390 (each 3-9 s on a loaded machine)
    // each try: the trenchie fighting, the order sent, the model's answer 15 s away (under the brain's 20 s call limit)
    const sendOrder = async () => {
      for (let k = 0; k < 8; k++) {   // wait for the live-fight state used by the thinking copy check
        await fighting();
        if (!(await type(p, '#pn-order', 'Stay near the middle and grab loot.'))) continue;
        try { await tap('[data-pn="send"]'); } catch (e) { continue; }
        await p.waitForFunction(() => /is thinking…/.test(document.getElementById('b1-panel').innerText), null, { timeout: 15000 }).catch(() => {});
        return;
      }
    };
    await check('thinking', [...HEAD, 'Thinking…', 'Leave', '×', /^This hour \$\d\.\d\d of your \$0\.20 cap$/, /^This visit \$\d\.\d\d · About \$0\.10 an hour$/, 'Change cap', ...TABS, 'Stay near the middle and grab loot.', /^\d\d:\d\d$/, /^Barnacle is thinking… \d+\.\d s$/, 'Sent. One order every 0.5 s.', 'Send'], '', async (k) => { if (k) await p.waitForFunction(() => !/is thinking…/.test(document.getElementById('b1-panel').innerText), null, { timeout: 30000 }).catch(() => {}); await sendOrder(); });
    slow = 0;
    await p.waitForFunction(() => /BEHAVIOUR SET/.test(document.getElementById('b1-panel').innerText), null, { timeout: 30000 }).catch(() => {});
    const t = await lines();
    ok(t.some((l) => /^Barnacle“Middle it is\. Loot first, fists second\.”$|^Barnacle “Middle it is/.test(l) || l === '“Middle it is. Loot first, fists second.”') && t.includes('BEHAVIOUR SET') && t.some((l) => /^applied \d+\.\d s after Send$/.test(l)),
      `after the reply: the trenchie's line, BEHAVIOUR SET and "applied N s after Send" (SPEC fight's entry) (${t.filter((l) => /applied|BEHAVIOUR|Middle/.test(l)).join(' / ')})`);
    // ---- changecap
    await tap('[data-pn="capedit"]'); await sleep(500);
    await check('changecap', [...HEAD, /^(Fighting|Bench)/, 'Leave', '×', /^This hour \$\d\.\d\d of your \$0\.20 cap$/, /^This visit \$\d\.\d\d/, '$0.10', '$0.20', '$0.50', '$1.00', 'Set cap', ...TABS]);
    await tap('[data-pn="cap:0.5"]'); await tap('[data-pn="setcap"]'); await sleep(1500);
    ok((await lines()).some((l) => /^This hour \$\d\.\d\d of your \$0\.50 cap$/.test(l)), 'Set cap $0.50: the money line reads the new cap');
    // ---- capped (fixture: the hour's spend window at the cap; real spend needs real model calls)
    await p.evaluate(() => { const now = Date.now(); localStorage.setItem('trenchie.snapin.brain.spend', JSON.stringify([{ at: now - 1000, usd: 0.5 }])); });
    await p.waitForFunction(() => /Own tactics/.test(document.getElementById('b1-panel').innerText), null, { timeout: 40000 }).catch(() => {});
    await check('capped', [...HEAD, 'Own tactics', 'Leave', '×', 'This hour $0.50 of your $0.50 cap', /^This visit \$\d\.\d\d · Resets at \d\d:\d\d$/, 'Change cap', ...TABS, /^Cap reached\. Barnacle fights on its own tactics until \d\d:\d\d\.$/, '$1.00', '$2.00', '$5.00', 'Raise cap'], '(the spend window is a labelled fixture)', ownTactics);
    await tap('[data-pn="raisecap"]'); await sleep(2500);
    await p.evaluate(() => localStorage.setItem('trenchie.snapin.brain.spend', '[]'));
    // ---- bench: after a real KO, Stay on the bench
    await p.waitForFunction(() => { const b = SnapPanel.state.corner && SnapPanel.state.corner.bench; return b && (b.down || b.held); }, null, { timeout: 150000 }).catch(() => {});
    const down = await p.evaluate(() => { const b = SnapPanel.state.corner && SnapPanel.state.corner.bench; return !!(b && (b.down || b.held)); });
    ok(await p.evaluate(() => !!document.querySelector('#pn-tab-chat[aria-selected="true"]') && /gear can be changed/i.test(document.getElementById('pn-tab-gear').getAttribute('aria-label') || '')), 'a KO marks Gear ready without switching away from Chat');
    await tap('[data-pn="tab:gear"]');
    if (down) await tap('[data-pn="hold"]');
    await p.waitForFunction(() => /Bench · held/.test(document.getElementById('b1-panel').innerText), null, { timeout: 20000 }).catch(() => {});
    await check('bench', ['Barnacle Bertie', /^Life \d+ · NEAR AI Cloud$/, 'HP', /^0\/\d+$/, 'Bench · held', 'Leave', '×', /^This hour \$\d\.\d\d of your \$\d\.\d\d cap$/, /^This visit/, 'Change cap', ...TABS, 'On the bench', /^Next: life \d+$/, 'Stay on the bench', 'The 45 s timer is stopped. Barnacle waits until you send it back in.', /^EQUIPPED · TAP AN ITEM TO SWAP$/i, 'Head', /./, 'Body', /./, 'Weapon', /./, 'Trinket', /./, 'Send back in'], down ? '(after a real KO, Gear selected)' : '(NO KO within 150 s)', undefined,
      ['Barnacle Bertie', /^Life \d+ · NEAR AI Cloud$/, 'HP', /^0\/\d+$/, 'Bench · held', 'Leave', '×', /^This hour \$\d\.\d\d of your \$\d\.\d\d cap$/, /^This visit \$\d\.\d\d$/, 'Change cap', ...TABS, 'On the bench', /^Next: life \d+$/, 'Stay on the bench', 'The 45 s timer is stopped. Barnacle waits until you send it back in.', /^EQUIPPED · TAP AN ITEM TO SWAP$/i, /./, /./, /./, /./, 'Send back in']);   // 390's gear tiles retain the names but omit slot words
    await layout390('bench');
    const bl = await lines(), hl = Number((bl.find((l) => /^Life \d+ · /.test(l)) || '').replace(/^Life (\d+).*/, '$1')), nl = Number((bl.find((l) => /^Next: life \d+$/.test(l)) || '').replace(/^Next: life /, ''));
    const hostNext = await p.evaluate(() => { const c = SnapPanel.state.corner; return c && c.bench ? c.bench.next_life : null; });
    ok(hl > 0 && nl === hl + 1 && nl === hostNext, `bench: the header is the life just ended and Next is the host's coming life ("Life ${hl}", "Next: life ${nl}", the host's bench.next_life ${hostNext})`);
    await checkGear(p, 'bench');
    await check('bench-chat', ['Bench · held', 'Leave', '×', ...TABS, /KO’d by|KO'd by/, 'One order every 0.5 s', 'Send'], '(the KO log and order box stay in Chat while Gear holds the bench)');
    await tap('[data-pn="tab:gear"]');
    await p.evaluate(() => { const send = document.querySelector('[data-pn="sendback"]'); if (send) send.scrollIntoView({ block: 'nearest' }); });
    await tap('[data-pn="sendback"]').catch(() => {});
    await p.waitForFunction(() => !/Bench · held/.test(document.getElementById('b1-panel').innerText), null, { timeout: 20000 }).catch(() => {});
    ok(!/Bench · held/.test((await lines()).join('\n')), 'Send back in releases the hold');
    // ---- closed
    await tap('[data-pn="close"]'); await sleep(800);
    const tab = (await p.evaluate(() => document.getElementById('b1-panel').innerText)).split('\n').map((l) => l.trim()).filter(Boolean);
    ok(tab.includes('Barnacle') && tab.includes('Open') && !(await p.$('[data-arena-panel]')), `closed: the edge tab with the short name and Open; the panel box is gone (${tab.join(' / ').slice(0, 80)})`);
    await tap('[data-pn="open"]'); await sleep(800);
    ok(!!(await p.$('[data-arena-panel]')) && await p.evaluate(() => !!document.querySelector('#pn-tab-chat[aria-selected="true"]')), 'Open brings the panel back with Chat selected');
    // ---- agent-codex and agent-claude: a session joined with the door's code, driving through its private pipe
    // (snap.py live --fifo, as the hosted door runs it; the guarded child's stdin is /dev/null). Each session sends flee and
    // a note (the order in its owner's words, its reply and why), as SNAP.md's door steps say; the Claude Code session also
    // reports its plan use (4%); the Codex one cannot.
    // each agent state is bounded (a wedged single-process Chromium can hang a call with no timeout): a hang FAILs with its stage
    let stage = '';
    const agentState = (o) => { let t; const hang = new Promise((r) => { t = setTimeout(r, 300000); }).then(() => ok(false, `${o.id}: hung for 300 s at: ${stage}`));
      return Promise.race([agentState1(o).finally(() => clearTimeout(t)), hang]); };
    const agentState1 = async (o) => {
      stage = 'browser relaunch';
      // a fresh browser per player (one single-process Chromium does not survive a second context here)
      await b.close().catch(() => {}); b = await chromium.launch({ args: ['--single-process', '--no-zygote'] });
      const q = await (await b.newContext({ viewport: { width: 1440, height: 900 } })).newPage(); q.on('pageerror', (e) => errs.push(o.id + ' page: ' + e.message));
      await q.goto(guide.replace('index.html?', 'index.html?step=wallet&')); await G.ready(q);
      await G.act(q, 'g:wallet:dev-throwaway'); await G.act(q, 'g:build'); await q.waitForFunction(() => Snapin.view.step === 'personality', null, { timeout: 20000 });
      await q.fill('#name', o.name); await sleep(600); await G.act(q, 'g:step:doors'); await G.act(q, 'g:door:plan:' + o.agent);
      await q.waitForFunction(() => window.SnapGuide && SnapGuide.state.code, null, { timeout: 20000 });
      stage = 'session start';
      const code = await q.evaluate(() => SnapGuide.state.code.code), dir = path.join(TMP, o.id), fifo = path.join(dir, 'orders');
      fs.mkdirSync(dir, { recursive: true });
      const live = HOSTS.host(['-I', path.join(HOSTS.REPO, 'near/arena/snap.py'), '--url', arenaUrl, '--state', path.join(dir, 'state.json'), 'live', '--code', code, '--name', o.name, '--preset', 'hunter-lunge', '--accept-terms', '1', '--seconds', '150', '--fifo', fifo], { cwd: dir, stdio: ['pipe', 'pipe', 'pipe'] });
      const events = []; let buf = '';
      live.stdout.on('data', (d) => { buf += d; let i; while ((i = buf.indexOf('\n')) >= 0) { const l = buf.slice(0, i); buf = buf.slice(i + 1); try { events.push(JSON.parse(l)); } catch (e) { /* a plain line */ } } });
      await q.waitForFunction(() => /session joined/.test(document.body.innerText), null, { timeout: 45000 }).catch(() => {});
      for (let i = 0; i < 100 && !fs.existsSync(fifo); i++) await sleep(300);
      // an order is taken once the session's life has started (before it the host answers "Wait for life_start")
      const id = 'dev-' + o.name.toLowerCase().replace(/[^a-z0-9]/g, '');
      for (let i = 0; i < 90; i++) {
        const pl = await fetch(arenaUrl + '/dev/players').then((r) => r.json()).catch(() => []);
        if (pl.some((x) => x.fighter_id === id && x.state === 'ring')) break;
        await sleep(500);
      }
      stage = 'orders through the pipe';
      const lines = ['flee', JSON.stringify({ note: { order: 'run away from everyone', reply: 'Tide’s out, so am I. Catch me if you can.', why: 'you asked me to avoid every fight.' } })];
      if (o.planPct != null) lines.push(JSON.stringify({ plan: { week_used_pct: o.planPct } }));
      // one line at a time, each after the last one's ack (the session takes one order every 0.5 s)
      const acks = [];
      for (const l of lines) {
        const n = events.filter((e) => e.kind === 'ack').length;
        await fs.promises.writeFile(fifo, l + '\n');
        for (let i = 0; i < 60 && events.filter((e) => e.kind === 'ack').length <= n; i++) await sleep(300);
        const a = events.filter((e) => e.kind === 'ack')[n];
        acks.push(a ? (a.receipt && a.receipt.ack && a.receipt.ack.status) || '?' : 'none');
      }
      stage = 'Snap in and the panel';
      await G.act(q, 'g:step:agree'); await q.waitForFunction(() => !!document.querySelector('[data-act="g:snap"]'), null, { timeout: 20000 }).catch(() => {});
      await G.act(q, 'g:snap'); await q.waitForURL(/arena\.html/, { timeout: 20000 }).catch(() => {});
      await q.waitForFunction((a) => { const e = document.getElementById('b1-panel'); return e && e.innerText.includes(a + ' session'); }, o.agent, { timeout: 30000 }).catch(() => {});
      const ql = async () => (await q.evaluate(() => { const e = document.getElementById('b1-panel'); return e && !e.hidden ? e.innerText : ''; })).replace(/\u00a0/g, ' ').split('\n').map((l) => l.trim()).filter(Boolean);
      const short = o.name.split(' ')[0];
      const want = [o.name, new RegExp('^Life \\d+ · ' + esc(o.agent) + ' session$'), 'HP', /^\d+\/\d+$/, /^(Fighting|Bench)/, 'Leave', '×', ...o.money, ...TABS,
        new RegExp('^\\d\\d:\\d\\d Your ' + esc(o.agent) + ' session joined\\. Life 1\\.$'), 'From your session', '“run away from everyone”', /^\d\d:\d\d$/,
        new RegExp('^' + esc(short) + ' ?“Tide’s out, so am I\\. Catch me if you can\\.”$'), 'BEHAVIOUR SET', /^applied \d+\.\d s after Send$/, 'Why: you asked me to avoid every fight.',
        'Orders come from your ' + o.agent + ' session. Type them there; replies show here.'];
      let aw = '', got = [];
      for (let i = 0; i < 25; i++) { got = await ql(); aw = inOrder(want, got); if (!aw) break; await sleep(1000); }
      const want390 = want;
      const at390 = aw ? '' : (await q.setViewportSize({ width: 390, height: 844 }), await sleep(900), inOrder(want390, await ql()));
      ok(!aw && !at390, `${o.id}: Snap in from the plan door sends no join of its own and the panel follows the session: SPEC's lines in order at 1440 and 390 (${o.what}), the session's note joined to its flee receipt, the read-only box (the session's acks: ${acks.join(', ')})${aw || at390 ? ' | ' + (aw || '390 ' + at390) + ' | ' + got.join(' / ').slice(0, 1500) : ''}`);
      await checkGear(q, o.id);
      live.kill();
    };
    await agentState({ id: 'agent-codex', agent: 'Codex', name: 'Codex Pip', planPct: null, money: ['Plan use this week: not reported by your Codex session', 'Its own stop: 10%'], what: '"not reported"' });
    await agentState({ id: 'agent-claude', agent: 'Claude Code', name: 'Kelp Pip', planPct: 4, money: ['Plan this week: 4% of your 10% stop', 'from your session'], what: 'its reported 4% of the 10% stop' });
    ok(errs.length === 0, 'no page errors' + (errs.length ? ': ' + errs.slice(0, 4).join(' | ') : ''));
  } catch (e) { ok(false, 'case crashed: ' + String(e && e.stack || e).slice(0, 500)); }
  if (b) await b.close().catch(() => {});
  await fetch(arenaUrl + '/dev/shutdown', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Dev-Admin': arena.m } }).catch(() => {});
  ok((await HOSTS.finish()).length === 0, 'no host this case started survives it');
  fs.rmSync(TMP, { recursive: true, force: true });
  console.log(`${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
