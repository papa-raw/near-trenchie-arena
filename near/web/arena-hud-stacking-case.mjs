import assert from 'node:assert/strict';
import { HudPanelCache } from './arena/hud-cache.mjs';
class Svg {
  constructor() { this.children = []; this.style = {}; this.localName = 'svg'; this.outerHTML = '<svg width="100" height="40"><text>KO 2</text></svg>'; }
  cloneNode() { return new Svg(); }
  querySelector() { return null; }
  querySelectorAll() { return []; }
}
const blits = [];
globalThis.document = { createElement: () => ({ style: {}, getContext: () => ({ drawImage: (...args) => blits.push(args) }) }) };
const cache = new HudPanelCache({}); cache.backgrounds.get = async () => ({ width: 456, height: 336 });
for (const id of ['board','banner','btn0','btn1','feed','drop']) {
  const node = { style: {}, querySelector: () => new Svg(), replaceChildren(...children) { this.children = children; } };
  await cache.paintPanel(node);
  const [canvas, overlay] = node.children;
  assert.ok(['relative','absolute'].includes(overlay.style.position), id + ' text must be positioned above its canvas');
  assert.ok(Number(overlay.style.zIndex) > Number(canvas.style.zIndex || 0), id + ' text must have higher stacking order');
  assert.equal(node.style.isolation, 'isolate', id + ' panel has a local stacking context');
}
assert.equal(blits.length, 6);
process.stdout.write(JSON.stringify({ ok: true, panels: 6, positionedText: true, textAboveBackground: true }) + '\n');
