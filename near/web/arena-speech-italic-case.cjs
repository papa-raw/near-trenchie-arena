// The actual speech renderer and stylesheet: only dialogue gets italic type, including after a feed redraw.
// NODE_PATH=<Playwright module directory> node near/web/arena-speech-italic-case.cjs
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require('playwright');

(async () => {
  const [source, css] = await Promise.all(['feed.mjs', 'board2.css'].map((file) => fs.readFile(path.join(__dirname, 'arena', file), 'utf8')));
  const browser = await chromium.launch(process.env.HTTPS_PROXY ? {
    args: ['--single-process', '--no-zygote', '--proxy-bypass-list=<-loopback>'], proxy: { server: process.env.HTTPS_PROXY },
  } : {});
  try {
    const page = await browser.newPage();
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 900 });
      await page.setContent('<style>' + css + '</style><div class="b2" id="root"></div>');
      const result = await page.evaluate(async (moduleSource) => {
        const url = URL.createObjectURL(new Blob([moduleSource], { type: 'text/javascript' }));
        const { Feed } = await import(url); URL.revokeObjectURL(url);
        const feed = new Feed(document, document.getElementById('root'), { name: () => 'Coral Clerk', colour: () => '#123456' });
        const dialogue = '“Count <shells>, then foam.”';
        feed.push({ kind: 'ko', who: 'coral', victim: 'pebble' });
        feed.push({ kind: 'pred', who: 'coral', level: 2 });
        feed.push({ kind: 'res', who: 'coral', level: 2, points: 40 });
        feed.push({ kind: 'say', who: 'coral', emoji: '🐚', text: dialogue, status: 'guarded' });
        feed.render();
        const say = feed.list.querySelector('li.say'), spoken = say.querySelector('.line em');
        return { dialogue: spoken?.textContent, dialogueStyle: spoken && getComputedStyle(spoken).fontStyle,
          whoStyle: getComputedStyle(say.querySelector('.who')).fontStyle,
          whoColour: getComputedStyle(say.querySelector('.who')).color,
          emoji: say.querySelector('.emo').textContent, emojiStyle: getComputedStyle(say.querySelector('.emo')).fontStyle,
          status: getComputedStyle(say.querySelector('.status')).fontStyle,
          events: [...feed.list.querySelectorAll('li:not(.say) .line')].map((line) => ({ style: getComputedStyle(line).fontStyle, italics: line.querySelectorAll('em').length })),
          injectedElements: say.querySelectorAll('shells').length };
      }, source);
      assert.equal(result.dialogueStyle, 'italic', width + ': dialogue is italic');
      assert.equal(result.dialogue, '“Count <shells>, then foam.”');
      assert.equal(result.whoStyle, 'normal'); assert.equal(result.whoColour, 'rgb(18, 52, 86)');
      assert.equal(result.emoji, '🐚'); assert.equal(result.emojiStyle, 'normal'); assert.equal(result.status, 'normal');
      assert.equal(result.events.length, 3); assert.ok(result.events.every((e) => e.style === 'normal' && !e.italics));
      assert.equal(result.injectedElements, 0, 'dialogue stays text');
    }
    process.stdout.write('arena-speech-italic-case: dialogue italic; names, colour, emoji, statuses and events unchanged at 1440/390\n');
  } finally { await browser.close(); }
})().catch((e) => { process.stderr.write(e.stack + '\n'); process.exitCode = 1; });
