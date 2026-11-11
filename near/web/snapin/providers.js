/* providers.js: the login doors' network calls (W2 spike).
 *
 * A classic script, no build step. In a page it sets window.SnapProviders; under node
 * it is module.exports. Every function returns a Promise of a plain object and never
 * throws for an HTTP or network error:
 *   ok:    {ok:true, ...}
 *   not:   {ok:false, kind:'bad-key'|'no-credits'|'expired'|'network'|'cors'|'rate'|'other', status, message}
 * Every function takes an optional LAST argument {fetch, ...} so a test can inject a fake.
 *
 * Keys: this file never logs a key and never stores one. The caller decides what to keep.
 * The only thing it writes to storage is the OpenRouter PKCE verifier (sessionStorage,
 * try/catch), which is not a key.
 *
 * Endpoints (each reached from a browser page with a fake key in the spike; the answers are logged in the build's verification log):
 *   NEAR AI Cloud  https://cloud-api.near.ai/v1/chat/completions   (Bearer key; no special header)
 *   Anthropic      https://api.anthropic.com/v1/messages            (needs anthropic-dangerous-direct-browser-access: true)
 *   OpenRouter     https://openrouter.ai/api/v1/...                 (no special header)
 * Hand-off doors (Claude Code, Codex): SnapProviders.snap.* talks to <base>/snap/code, which is NOT
 * a built endpoint yet (SNAP.md asserts no hosted origin); spike/snap-stub.py stands in for it.
 */
(function (root) {
  'use strict';

  var NEARAI_URL = 'https://cloud-api.near.ai/v1/chat/completions';
  var NEARAI_MODEL = 'deepseek-ai/DeepSeek-V4.1-Flash-1017';
  var ANTHROPIC_URL = 'https://api.anthropic.com/v1/messages';
  var ANTHROPIC_MODEL = 'claude-haiku-5-5';
  var OPENROUTER_BASE = 'https://openrouter.ai/api/v1';
  var OPENROUTER_AUTH = 'https://openrouter.ai/auth';
  // Cheap, long-lived default; the caller may pass {model}. UNVERIFIED that it is live on the day of play.
  var OPENROUTER_MODEL = 'openai/gpt-6-luna';   // current and cheap on openrouter.ai's model list, read 2026-11-11
  var HI_PROMPT = 'Say hi in five words.';
  var VERIFIER_KEY = 'trenchie.snap.orVerifier';
  var TIMEOUT_MS = 20000;

  /* ---------- helpers ---------- */

  function getFetch(opts) {
    var f = opts && opts.fetch ? opts.fetch : (typeof globalThis !== 'undefined' ? globalThis.fetch : null);
    if (typeof f !== 'function') return null;
    return opts && opts.fetch ? f : f.bind(globalThis);
  }

  function mask(key) {
    if (typeof key !== 'string' || key.length < 8) return '…';
    return '…' + key.slice(-4);
  }

  function scrub(text, key) {
    var s = String(text == null ? '' : text);
    if (key && typeof key === 'string' && key.length >= 8) s = s.split(key).join(mask(key));
    return s.length > 240 ? s.slice(0, 240) + '…' : s;
  }

  function errMessage(body, text) {
    if (body && typeof body === 'object') {
      if (body.error && typeof body.error === 'object' && body.error.message) return String(body.error.message);
      if (typeof body.error === 'string') return body.error;
      if (body.message) return String(body.message);
    }
    return text || '';
  }

  // status + provider message -> kind. Pure, exported for tests.
  function classify(status, message) {
    var m = String(message || '');
    if (status === 401) return 'bad-key';
    if (status === 402) return 'no-credits';
    if (status === 429 || status === 529) return 'rate';
    if (status === 403) return /limit|credit|quota|billing|balance/i.test(m) ? 'no-credits' : 'expired';
    // Anthropic reports an empty balance as 400 invalid_request_error "credit balance is too low".
    if (status >= 400 && status < 500 && /credit balance|insufficient (credits|funds|balance)|out of credits|quota/i.test(m)) return 'no-credits';
    return 'other';
  }

  function fail(kind, status, message, key) {
    return { ok: false, kind: kind, status: status, message: scrub(message, key) };
  }

  // A thrown fetch (a browser TypeError) cannot say why. Probe: a no-cors GET to the same
  // origin resolves (opaque) when the host is reachable, so the throw was CORS; it throws
  // too when the network is down. Disabled with {probe:false}.
  async function classifyThrown(err, url, f, opts, key) {
    var name = err && err.name;
    var msg = (err && err.message) || String(err);
    if (name === 'AbortError' || name === 'TimeoutError') return fail('network', 0, 'timeout', key);
    if (typeof navigator !== 'undefined' && navigator && navigator.onLine === false) return fail('network', 0, 'offline', key);
    if (opts && opts.probe === false) return fail('cors', 0, msg, key);
    try {
      var origin = new URL(url).origin + '/';
      await f(origin, { method: 'GET', mode: 'no-cors', credentials: 'omit' });
      return fail('cors', 0, msg, key);
    } catch (e2) {
      return fail('network', 0, msg, key);
    }
  }

  async function call(url, init, opts, key) {
    var f = getFetch(opts);
    if (!f) return fail('other', 0, 'no fetch available');
    var ctl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    var timer = ctl ? setTimeout(function () { ctl.abort(); }, (opts && opts.timeoutMs) || TIMEOUT_MS) : null;
    if (ctl) init.signal = ctl.signal;
    var res;
    try {
      res = await f(url, init);
    } catch (err) {
      if (timer) clearTimeout(timer);
      return classifyThrown(err, url, f, opts, key);
    }
    if (timer) clearTimeout(timer);
    var text = '';
    var body = null;
    try { text = await res.text(); } catch (e) { text = ''; }
    try { body = text ? JSON.parse(text) : null; } catch (e) { body = null; }
    return { res: res, status: res.status, body: body, text: text };
  }

  function isFail(r) { return r && r.ok === false && r.kind; }

  function httpFail(r, key) {
    var msg = errMessage(r.body, r.text);
    return fail(classify(r.status, msg), r.status, msg, key);
  }

  function bearerJson(key, extra) {
    var h = { 'content-type': 'application/json', authorization: 'Bearer ' + key };
    if (extra) for (var k in extra) h[k] = extra[k];
    return h;
  }

  function chatSay(body) {
    try {
      var c = body.choices[0].message.content;
      return typeof c === 'string' ? c.trim() : '';
    } catch (e) { return ''; }
  }

  /* ---------- NEAR AI Cloud ---------- */

  var nearai = {
    // Browser fetch, a tiny prompt. The thinking flag is off, as the house runtime does.
    test: async function (key, opts) {
      var r = await call(NEARAI_URL, {
        method: 'POST',
        headers: bearerJson(key),
        body: JSON.stringify({
          model: (opts && opts.model) || NEARAI_MODEL,
          messages: [{ role: 'user', content: HI_PROMPT }],
          max_tokens: 24,
          stream: false,
          chat_template_kwargs: { enable_thinking: false }
        })
      }, opts, key);
      if (isFail(r)) return r;
      if (r.status !== 200) return httpFail(r, key);
      return { ok: true, say: chatSay(r.body), status: r.status };
    }
  };

  /* ---------- Claude Console key ("Use plan credits") ---------- */

  var claude = {
    test: async function (key, opts) {
      var headers = {
        'content-type': 'application/json',
        'x-api-key': key,
        'anthropic-version': '2023-06-01'
      };
      // Without this opt-in header Anthropic refuses the browser preflight (400 "Disallowed CORS origin").
      // {optIn:false} exists only so the spike page can show that failure.
      if (!opts || opts.optIn !== false) headers['anthropic-dangerous-direct-browser-access'] = 'true';
      var r = await call(ANTHROPIC_URL, {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({
          model: (opts && opts.model) || ANTHROPIC_MODEL,
          max_tokens: 24,
          messages: [{ role: 'user', content: HI_PROMPT }]
        })
      }, opts, key);
      if (isFail(r)) return r;
      if (r.status !== 200) return httpFail(r, key);
      var say = '';
      try { say = r.body.content.filter(function (b) { return b.type === 'text'; }).map(function (b) { return b.text; }).join('').trim(); } catch (e) { say = ''; }
      return { ok: true, say: say, status: r.status };
    }
  };

  /* ---------- OpenRouter (PKCE) ---------- */

  function b64url(bytes) {
    var s = '';
    for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
    var b = typeof btoa === 'function' ? btoa(s) : Buffer.from(s, 'binary').toString('base64');
    return b.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function getCrypto(opts) {
    if (opts && opts.crypto) return opts.crypto;
    if (typeof globalThis !== 'undefined' && globalThis.crypto && globalThis.crypto.subtle) return globalThis.crypto;
    return null;
  }

  // RFC 7636 section 4.2: challenge = BASE64URL(SHA256(ASCII(verifier))).
  async function pkceChallenge(verifier, opts) {
    var c = getCrypto(opts);
    if (!c) throw new Error('WebCrypto unavailable');
    var data = new TextEncoder().encode(verifier);
    var digest = await c.subtle.digest('SHA-256', data);
    return b64url(new Uint8Array(digest));
  }

  function newVerifier(opts) {
    var c = getCrypto(opts);
    if (!c) throw new Error('WebCrypto unavailable');
    var bytes = new Uint8Array(32); // 32 random bytes -> 43 base64url chars (RFC 7636 min length)
    c.getRandomValues(bytes);
    return b64url(bytes);
  }

  function store(opts) {
    try { return (opts && opts.storage) || (typeof sessionStorage !== 'undefined' ? sessionStorage : null); } catch (e) { return null; }
  }

  var openrouter = {
    pkceChallenge: pkceChallenge,

    // Returns {url, verifier, state}. The verifier also goes to sessionStorage so the redirect-back page can finish().
    begin: async function (args, opts) {
      try {
        args = args || {};
        var callback = String(args.callbackUrl || '');
        if (!callback) return fail('other', 0, 'callbackUrl is required');
        if (args.state) {
          var u = new URL(callback);
          if (!u.searchParams.has('state')) u.searchParams.set('state', args.state);
          callback = u.toString();
        }
        var verifier = newVerifier(opts);
        var challenge = await pkceChallenge(verifier, opts);
        var st = store(opts);
        try { if (st) st.setItem(VERIFIER_KEY, JSON.stringify({ verifier: verifier, state: args.state || null })); } catch (e) { /* storage may be blocked */ }
        var url = OPENROUTER_AUTH +
          '?callback_url=' + encodeURIComponent(callback) +
          '&code_challenge=' + challenge +
          '&code_challenge_method=S256' +
          '&key_label=Trenchie%20Arena';
        return { ok: true, url: url, verifier: verifier, state: args.state || null };
      } catch (e) {
        return fail('other', 0, (e && e.message) || String(e));
      }
    },

    // Swap the one-time code for a key billed to the player. The key is returned, never stored.
    finish: async function (args, opts) {
      args = args || {};
      var verifier = args.verifier;
      if (!verifier) {
        try {
          var st = store(opts);
          var raw = st && st.getItem(VERIFIER_KEY);
          verifier = raw ? JSON.parse(raw).verifier : null;
        } catch (e) { verifier = null; }
      }
      if (!args.code || !verifier) return fail('other', 0, 'code and verifier are both required');
      var r = await call(OPENROUTER_BASE + '/auth/keys', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ code: args.code, code_verifier: verifier, code_challenge_method: 'S256' })
      }, opts, null);
      if (isFail(r)) return r;
      if (r.status !== 200 || !r.body || typeof r.body.key !== 'string') return httpFail(r, r.body && r.body.key);
      try { var st2 = store(opts); if (st2) st2.removeItem(VERIFIER_KEY); } catch (e) { /* ignore */ }
      return { ok: true, key: r.body.key, status: r.status };
    },

    test: async function (key, opts) {
      var r = await call(OPENROUTER_BASE + '/chat/completions', {
        method: 'POST',
        headers: bearerJson(key, { 'x-title': 'Trenchie Arena' }),
        body: JSON.stringify({
          model: (opts && opts.model) || OPENROUTER_MODEL,
          messages: [{ role: 'user', content: HI_PROMPT }],
          max_tokens: 24
        })
      }, opts, key);
      if (isFail(r)) return r;
      if (r.status !== 200) return httpFail(r, key);
      return { ok: true, say: chatSay(r.body), status: r.status };
    }
  };

  /* ---------- hand-off doors: Claude Code, Codex ---------- */

  var AGENTS = { 'claude-code': true, codex: true };

  function shq(s) { return "'" + String(s).replace(/'/g, "'\\''") + "'"; }

  // The prompt is what the player's own agent receives. Under 1000 chars (Claude Code's review
  // warning starts there; its hard cap is 5000). No cwd. It names SNAP.md and the one-time code.
  function buildPrompt(code, snapMdUrl, name) {
    var p = 'Join Trenchie Arena. Read ' + snapMdUrl + ' and follow it. Use one-time code ' + code +
      (name ? ' for the trenchie "' + String(name).replace(/["\n\r]/g, ' ').slice(0, 40) + '"' : '') +
      '. Only contact the host that serves SNAP.md. Do not put any API key or wallet key in the room.';
    return p;
  }

  function buildHandoff(a) {
    var prompt = buildPrompt(a.code, a.snapMdUrl, a.name);
    if (prompt.length >= 1000) return { ok: false, prompt: prompt };
    var host = '';
    try { host = new URL(a.snapMdUrl).host; } catch (e) { host = ''; }
    var link, command;
    if (a.agent === 'claude-code') {
      link = 'claude-cli://open?q=' + encodeURIComponent(prompt);
      command = 'claude' + (host ? ' --allowedTools ' + shq('WebFetch(domain:' + host.replace(/:\d+$/, '') + ')') : '') + ' ' + shq(prompt);
    } else {
      link = 'codex://new?prompt=' + encodeURIComponent(prompt);
      command = 'codex ' + shq(prompt);
    }
    return { ok: true, prompt: prompt, link: link, command: command };
  }

  function snapBase(opts) {
    var b = (opts && opts.baseUrl != null) ? opts.baseUrl : snap.baseUrl;
    return String(b || '').replace(/\/+$/, '');
  }

  function defaultSnapMd(opts, serverUrl) {
    if (serverUrl) return serverUrl;
    if (opts && opts.snapMdUrl) return opts.snapMdUrl;
    if (snap.snapMdUrl) return snap.snapMdUrl;
    try { if (typeof location !== 'undefined' && location.origin && location.origin !== 'null') return location.origin + '/SNAP.md'; } catch (e) { /* not a page */ }
    return '/SNAP.md';
  }

  function toMs(v) {
    if (typeof v === 'number') return v < 1e12 ? v * 1000 : v; // seconds or ms
    var t = Date.parse(v);
    return isNaN(t) ? null : t;
  }

  var snap = {
    baseUrl: '',      // '' = same origin. Set to e.g. 'http://127.0.0.1:8777' for the stub.
    snapMdUrl: null,  // overrides the derived SNAP.md URL
    buildHandoff: buildHandoff,

    // POST <base>/snap/code {agent, name} -> {code, expires_at, snap_url?, command?}
    // Returns {ok, code, expiresAt (ms), command, link}.
    requestCode: async function (args, opts) {
      args = args || {};
      if (!AGENTS[args.agent]) return fail('other', 0, "agent must be 'claude-code' or 'codex'");
      var r = await call(snapBase(opts) + '/snap/code', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ agent: args.agent, name: args.name || null })
      }, opts, null);
      if (isFail(r)) return r;
      if (r.status !== 200 || !r.body || typeof r.body.code !== 'string') return httpFail(r, null);
      var exp = toMs(r.body.expires_at != null ? r.body.expires_at : r.body.expiresAt);
      var h = buildHandoff({ agent: args.agent, code: r.body.code, snapMdUrl: defaultSnapMd(opts, r.body.snap_url), name: args.name });
      if (!h.ok) return fail('other', 0, 'hand-off prompt over 1000 characters');
      return { ok: true, status: r.status, code: r.body.code, expiresAt: exp, command: h.command, link: h.link, prompt: h.prompt, stub: r.body.stub === true };
    },

    // GET <base>/snap/code/<code> -> {joined, expired?}
    poll: async function (code, opts) {
      var r = await call(snapBase(opts) + '/snap/code/' + encodeURIComponent(code), { method: 'GET' }, opts, null);
      if (isFail(r)) return r;
      if (r.status === 404 || (r.body && r.body.expired === true)) return fail('expired', r.status, 'code expired or unknown');
      if (r.status !== 200 || !r.body) return httpFail(r, null);
      return { ok: true, status: r.status, joined: r.body.joined === true };
    }
  };

  var api = {
    nearai: nearai, claude: claude, openrouter: openrouter, snap: snap,
    mask: mask, classify: classify,
    constants: { NEARAI_URL: NEARAI_URL, NEARAI_MODEL: NEARAI_MODEL, ANTHROPIC_URL: ANTHROPIC_URL, ANTHROPIC_MODEL: ANTHROPIC_MODEL, OPENROUTER_BASE: OPENROUTER_BASE, OPENROUTER_MODEL: OPENROUTER_MODEL }
  };

  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.SnapProviders = api;
})(typeof globalThis !== 'undefined' ? globalThis : (typeof window !== 'undefined' ? window : this));
