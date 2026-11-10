// Canvas is a texture sink here; actual three.js geometry, materials, joints and disposal run unchanged.
import { readFile } from 'node:fs/promises';
const web = new URL('./', import.meta.url);
const gradient = { addColorStop() {} };
const context = new Proxy({ measureText: (text) => ({ width: text.length * 8 }), createLinearGradient: () => gradient, createRadialGradient: () => gradient,
  createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4) }) }, { get: (o, key) => key in o ? o[key] : () => {} });
globalThis.document = { createElement: () => ({ width: 128, height: 128, getContext: () => context }) };
globalThis.window = { dispatchEvent() {} }; globalThis.innerWidth = 1440; globalThis.innerHeight = 900;
globalThis.CustomEvent = class { constructor(type, opts) { this.type = type; this.detail = opts.detail; } };
globalThis.fetch = async (input) => {
  const path = input instanceof URL ? input : new URL(input, web);
  try { const text = await readFile(path, 'utf8'); return { ok: true, status: 200, json: async () => JSON.parse(text) }; }
  catch (e) { throw new Error('Asset read: ' + path + ': ' + e.message); }
};
// This permits the exact new case to demonstrate the missing adapter at the frozen baseline without editing it.
if (process.env.ARENA_TEST_ROOT) await import(new URL('near/web/items3d.js', 'file://' + process.env.ARENA_TEST_ROOT + '/'));
const { check } = await import('./arena-view-remainder-checks.mjs');
process.stdout.write(JSON.stringify(await check({ render: false })) + '\n');
