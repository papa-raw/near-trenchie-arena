// Node texture sink only: geometry and the arena scene builders run unchanged.
import { readFile } from 'node:fs/promises';
const web = new URL('./', import.meta.url), gradient = { addColorStop() {} };
const context = new Proxy({ measureText: (s) => ({ width: s.length * 8 }), createLinearGradient: () => gradient, createRadialGradient: () => gradient,
  createImageData: (w, h) => ({ data: new Uint8ClampedArray(w * h * 4) }) }, { get: (o, k) => k in o ? o[k] : () => {} });
globalThis.document = { createElement: () => ({ width: 128, height: 128, getContext: () => context }) };
globalThis.window = { dispatchEvent() {} };
globalThis.fetch = async (input) => { const u = input instanceof URL ? input : new URL(input, web); return { ok: true, status: 200, json: async () => JSON.parse(await readFile(u, 'utf8')) }; };
