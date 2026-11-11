// node near/web/snapin/test_providers.cjs
// Tests providers.js with an injected fake fetch. No network, no key. One PASS/FAIL line per case; exit 1 on any FAIL.
// PROVIDERS_PATH=<file> points the test at another file (used to show the test fails when the module is absent).
'use strict';
const path = require('path');
const target = process.env.PROVIDERS_PATH || path.join(__dirname, 'providers.js');

let fails = 0;
const ok = (name, cond, detail) => {
  if (!cond) fails++;
  console.log((cond ? 'PASS ' : 'FAIL ') + name + (cond ? '' : '  -> ' + detail));
};

let P;
try { P = require(target); } catch (e) {
  console.log('FAIL load providers.js  -> ' + e.message.split('\n')[0]);
  process.exit(1);
}

// ---- fake fetch ----
function reply(status, body, rawText) {
  const text = rawText !== undefined ? rawText : (body === undefined ? '' : JSON.stringify(body));
  return { status, ok: status >= 200 && status < 300, text: async () => text };
}
function fakeFetch(handler) {
  const calls = [];
  const f = async (url, init) => { calls.push({ url, init: init || {} }); return handler(url, init || {}, calls.length); };
  f.calls = calls;
  return f;
}
const KEY = 'sk-test-key-nearai-0123456789';
const sameShape = (r) => r && typeof r.ok === 'boolean' && (r.ok || ('kind' in r && 'status' in r && 'message' in r));

(async () => {
  // ---- 200 on each door ----
  {
    const f = fakeFetch(() => reply(200, { choices: [{ message: { content: ' hi there, trenchie friend ' } }] }));
    const r = await P.nearai.test(KEY, { fetch: f });
    ok('nearai 200 -> {ok,say,status}', r.ok === true && r.say === 'hi there, trenchie friend' && r.status === 200, JSON.stringify(r));
    const c = f.calls[0], body = JSON.parse(c.init.body);
    ok('nearai url + model + thinking off + max_tokens small',
      c.url === 'https://cloud-api.near.ai/v1/chat/completions' && body.model === 'deepseek-ai/DeepSeek-V4.1-Flash-1017' &&
      body.chat_template_kwargs && body.chat_template_kwargs.enable_thinking === false && body.max_tokens <= 64, JSON.stringify(body));
    ok('nearai sends Bearer key, no anthropic header', c.init.headers.authorization === 'Bearer ' + KEY && !('anthropic-dangerous-direct-browser-access' in c.init.headers), JSON.stringify(Object.keys(c.init.headers)));
  }
  {
    const f = fakeFetch(() => reply(200, { content: [{ type: 'text', text: 'hello from haiku' }] }));
    const r = await P.claude.test(KEY, { fetch: f });
    ok('claude 200 -> {ok,say,status}', r.ok === true && r.say === 'hello from haiku' && r.status === 200, JSON.stringify(r));
    const c = f.calls[0], h = c.init.headers;
    ok('claude url + x-api-key + version + opt-in header',
      c.url === 'https://api.anthropic.com/v1/messages' && h['x-api-key'] === KEY && h['anthropic-version'] === '2023-06-01' &&
      h['anthropic-dangerous-direct-browser-access'] === 'true' && h['content-type'] === 'application/json', JSON.stringify(h).replace(KEY, 'KEY'));
    ok('claude model claude-haiku-5-5', JSON.parse(c.init.body).model === 'claude-haiku-5-5', c.init.body);
    const f2 = fakeFetch(() => reply(200, { content: [{ type: 'text', text: 'x' }] }));
    await P.claude.test(KEY, { fetch: f2, optIn: false });
    ok('claude optIn:false drops the header (spike use only)', !('anthropic-dangerous-direct-browser-access' in f2.calls[0].init.headers), '');
  }
  {
    const f = fakeFetch(() => reply(200, { choices: [{ message: { content: 'hi from router' } }] }));
    const r = await P.openrouter.test('sk-or-v1-fake-0123456789', { fetch: f });
    ok('openrouter 200 -> {ok,say,status}', r.ok === true && r.say === 'hi from router', JSON.stringify(r));
    ok('openrouter url', f.calls[0].url === 'https://openrouter.ai/api/v1/chat/completions', f.calls[0].url);
  }

  // ---- kind mapping, per door ----
  const cases = [
    [401, { error: { message: 'Invalid or expired API key' } }, 'bad-key'],
    [402, { error: { message: 'Insufficient credits' } }, 'no-credits'],
    [403, { error: { message: 'Forbidden' } }, 'expired'],
    [403, { error: { message: 'Key limit exceeded' } }, 'no-credits'],
    [429, { error: { message: 'slow down' } }, 'rate'],
    [529, { error: { message: 'overloaded' } }, 'rate'],
    [400, { error: { message: 'Your credit balance is too low to access the API' } }, 'no-credits'],
    [500, { error: { message: 'boom' } }, 'other'],
    [400, { error: { message: 'Invalid code' } }, 'other'],
  ];
  const doors = [['nearai', P.nearai], ['claude', P.claude], ['openrouter', P.openrouter]];
  for (const [dname, d] of doors) {
    for (const [status, body, kind] of cases) {
      const f = fakeFetch(() => reply(status, body));
      const r = await d.test(KEY, { fetch: f });
      ok(`${dname} ${status} "${body.error.message.slice(0, 22)}" -> ${kind}`, r.ok === false && r.kind === kind && r.status === status && sameShape(r) && typeof r.message === 'string', JSON.stringify(r));
    }
  }
  {
    const f = fakeFetch(() => reply(502, undefined, '<html>bad gateway</html>'));
    const r = await P.nearai.test(KEY, { fetch: f });
    ok('non-JSON error body still maps (502 -> other, message from text)', r.ok === false && r.kind === 'other' && /bad gateway/.test(r.message), JSON.stringify(r));
  }
  {
    const f = fakeFetch(() => reply(401, { error: { message: 'bad key ' + KEY } }));
    const r = await P.nearai.test(KEY, { fetch: f });
    ok('key never echoed in message (masked)', r.ok === false && r.message.indexOf(KEY) === -1 && r.message.indexOf(P.mask(KEY)) !== -1, JSON.stringify(r));
  }
  ok('mask() shows only the last 4', P.mask(KEY) === '…' + KEY.slice(-4) && P.mask('short') === '…' && P.mask(undefined) === '…', P.mask(KEY));

  // ---- thrown TypeError: cors vs network ----
  {
    const f = fakeFetch((url, init) => {
      if (init.mode === 'no-cors') return reply(0, undefined, ''); // host reachable (opaque)
      throw new TypeError('Failed to fetch');
    });
    const r = await P.claude.test(KEY, { fetch: f, optIn: false });
    ok('TypeError + reachable host (no-cors probe resolves) -> cors', r.ok === false && r.kind === 'cors' && r.status === 0, JSON.stringify(r));
    ok('probe is a keyless no-cors GET to the origin', f.calls.length === 2 && f.calls[1].init.mode === 'no-cors' && !f.calls[1].init.headers && f.calls[1].url === 'https://api.anthropic.com/', JSON.stringify(f.calls.map((c) => [c.url, c.init.mode])));
  }
  {
    const f = fakeFetch(() => { throw new TypeError('Failed to fetch'); });
    const r = await P.nearai.test(KEY, { fetch: f });
    ok('TypeError + unreachable host (probe throws too) -> network', r.ok === false && r.kind === 'network' && r.status === 0, JSON.stringify(r));
  }
  {
    const f = fakeFetch(() => { throw new TypeError('Failed to fetch'); });
    const r = await P.nearai.test(KEY, { fetch: f, probe: false });
    ok('probe:false -> cors without a second request', r.kind === 'cors' && f.calls.length === 1, JSON.stringify(r));
  }
  {
    const f = fakeFetch(() => { const e = new Error('aborted'); e.name = 'AbortError'; throw e; });
    const r = await P.nearai.test(KEY, { fetch: f });
    ok('AbortError (timeout) -> network', r.kind === 'network' && /timeout/.test(r.message), JSON.stringify(r));
  }

  // ---- PKCE ----
  const RFC_VERIFIER = 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk';
  const RFC_CHALLENGE = 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM';
  {
    const c = await P.openrouter.pkceChallenge(RFC_VERIFIER);
    ok('PKCE S256: RFC 7636 appendix B vector', c === RFC_CHALLENGE, c);
  }
  {
    const mem = {}; const storage = { setItem: (k, v) => { mem[k] = v; }, getItem: (k) => (k in mem ? mem[k] : null), removeItem: (k) => { delete mem[k]; } };
    const r = await P.openrouter.begin({ callbackUrl: 'https://game.example/login?door=openrouter', state: 'st-123' }, { storage });
    const u = new URL(r.url);
    ok('begin: url is openrouter.ai/auth with S256', r.ok && u.origin + u.pathname === 'https://openrouter.ai/auth' && u.searchParams.get('code_challenge_method') === 'S256' && u.searchParams.get('key_label') === 'Trenchie Arena', r.url);
    ok('begin: verifier is base64url, 43 chars', /^[A-Za-z0-9_-]{43}$/.test(r.verifier), r.verifier);
    ok('begin: challenge === S256(verifier), no padding', u.searchParams.get('code_challenge') === (await P.openrouter.pkceChallenge(r.verifier)) && !/[=+/]/.test(u.searchParams.get('code_challenge')), r.url);
    const cb = new URL(u.searchParams.get('callback_url'));
    ok('begin: callback carries the state and the original query', cb.searchParams.get('state') === 'st-123' && cb.searchParams.get('door') === 'openrouter', cb.toString());
    ok('begin: verifier stored in sessionStorage-like store, not the key store', JSON.parse(mem['trenchie.snap.orVerifier']).verifier === r.verifier, JSON.stringify(mem));
    const r2 = await P.openrouter.begin({ callbackUrl: 'https://game.example/' }, { storage });
    ok('begin: two verifiers differ', r2.verifier !== r.verifier, '');
    // finish reads the verifier back when not passed
    const f = fakeFetch(() => reply(200, { key: 'sk-or-v1-fakereturnedkey0001', user_id: 'u' }));
    const fin = await P.openrouter.finish({ code: 'abc' }, { fetch: f, storage });
    const sent = JSON.parse(f.calls[0].init.body);
    ok('finish: POST /auth/keys {code, code_verifier, code_challenge_method:S256} -> {ok,key}',
      fin.ok === true && fin.key === 'sk-or-v1-fakereturnedkey0001' && f.calls[0].url === 'https://openrouter.ai/api/v1/auth/keys' &&
      sent.code === 'abc' && sent.code_challenge_method === 'S256' && sent.code_verifier === r2.verifier, JSON.stringify([fin, sent]));
    ok('finish: verifier removed after success', !('trenchie.snap.orVerifier' in mem), JSON.stringify(mem));
  }
  {
    const f = fakeFetch(() => reply(400, { error: { message: 'Invalid code', code: 400 } }));
    const r = await P.openrouter.finish({ code: 'fake', verifier: RFC_VERIFIER }, { fetch: f });
    ok('finish: fake code -> {kind:other, status:400, "Invalid code"}', r.ok === false && r.kind === 'other' && r.status === 400 && r.message === 'Invalid code', JSON.stringify(r));
    const r2 = await P.openrouter.finish({ code: 'x' }, { fetch: f, storage: { getItem: () => null, setItem() {}, removeItem() {} } });
    ok('finish: no verifier anywhere -> other, no request sent', r2.ok === false && r2.kind === 'other' && f.calls.length === 1, JSON.stringify(r2));
  }

  // ---- hand-off doors ----
  {
    const f = fakeFetch((url, init) => {
      if (init.method === 'POST') return reply(200, { code: 'CORAL-482', expires_at: Date.now() + 300000, snap_url: 'http://127.0.0.1:8777/SNAP.md' });
      return reply(200, { joined: false });
    });
    const opts = { fetch: f, baseUrl: 'http://127.0.0.1:8777' };
    const r = await P.snap.requestCode({ agent: 'claude-code', name: 'Pebble' }, opts);
    ok('requestCode claude-code -> {ok,code,expiresAt,command,link}', r.ok && r.code === 'CORAL-482' && typeof r.expiresAt === 'number' && r.command && r.link, JSON.stringify(r));
    ok('requestCode: POST <base>/snap/code', f.calls[0].url === 'http://127.0.0.1:8777/snap/code' && f.calls[0].init.method === 'POST', f.calls[0].url);
    ok('claude link: claude-cli://open?q=<prompt>, prompt < 1000 chars, no cwd', r.link.startsWith('claude-cli://open?q=') && decodeURIComponent(r.link.slice(20)) === r.prompt && r.prompt.length < 1000 && !/cwd/.test(r.link), r.link);
    ok('prompt names SNAP.md and the code', /SNAP\.md/.test(r.prompt) && r.prompt.includes('CORAL-482'), r.prompt);
    ok('claude command pre-allows only the endpoint host', /^claude --allowedTools 'WebFetch\(domain:127\.0\.0\.1\)' '/.test(r.command), r.command);
    const x = await P.snap.requestCode({ agent: 'codex' }, opts);
    ok('codex link: codex://new?prompt=<text>', x.ok && x.link.startsWith('codex://new?prompt=') && decodeURIComponent(x.link.slice(19)) === x.prompt && x.command.startsWith("codex '"), JSON.stringify(x));
    const bad = await P.snap.requestCode({ agent: 'gemini' }, opts);
    ok('requestCode: unknown agent -> other, no request', bad.ok === false && bad.kind === 'other' && f.calls.length === 2, JSON.stringify(bad));
    const p = await P.snap.poll('CORAL-482', opts);
    ok('poll -> {ok, joined:false}', p.ok === true && p.joined === false && f.calls[2].url === 'http://127.0.0.1:8777/snap/code/CORAL-482', JSON.stringify(p));
    const f404 = fakeFetch(() => reply(404, { error: 'unknown code' }));
    const p2 = await P.snap.poll('NOPE', { fetch: f404, baseUrl: 'http://x' });
    ok('poll 404 -> expired', p2.ok === false && p2.kind === 'expired' && p2.status === 404, JSON.stringify(p2));
    const f500 = fakeFetch(() => reply(404, undefined, 'Not Found'));
    const none = await P.snap.requestCode({ agent: 'codex' }, { fetch: f500, baseUrl: '' });
    ok('requestCode with no endpoint (404) -> {ok:false,kind:other,status:404}', none.ok === false && none.kind === 'other' && none.status === 404, JSON.stringify(none));
    const quote = await P.snap.requestCode({ agent: 'codex', name: 'a\'b"c' }, opts);
    // Round-trip through a real shell: the quoted prompt must come back byte for byte.
    const out = require('child_process').execFileSync('sh', ['-c', 'printf %s ' + quote.command.slice('codex '.length)]).toString();
    ok("shell quoting: a ' in the name round-trips through sh", quote.ok && out === quote.prompt, JSON.stringify([out, quote.prompt]));
  }

  console.log(fails ? `\n${fails} FAIL` : '\nall PASS');
  process.exit(fails ? 1 : 0);
})().catch((e) => { console.log('FAIL test crashed -> ' + (e && e.stack || e)); process.exit(1); });
