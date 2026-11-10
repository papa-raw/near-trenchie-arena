// W2 spike: a testnet guest function-call key, added by a throwaway account, read back over RPC.
//   NODE_USE_ENV_PROXY=1 node near/web/snapin/spike/guest-key.mjs [create|addkey|readback|all]
// Uses the VENDORED near-api-js 7.3.1 bundle (the same file a page loads), evaluated in node.
// Testnet only. Never prints a secret key. Keys live in ENV_FILE, outside the repo (chmod 600).
//   create   one faucet account via helper.testnet.near.org/account (the endpoint near-cli-rs
//            `sponsor-by-faucet-service` calls). Refuses if ENV_FILE already holds an account (one account only).
//            Any captcha / non-200 answer: stops, prints the reason. It never solves a captcha.
//   addkey   the account (full access) adds ONE function-call key: receiver 'market.<account>' (a label; the
//            contract is not deployed), methodNames [] (any method), allowance 0.25 NEAR, no deposit.
//   readback viewAccessKeyList over RPC and asserts permission.receiver_id, allowance, empty method_names.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BUNDLE = path.join(HERE, '..', 'vendor', 'near-api-js', 'near-api-js-7.3.1.min.js');
const ENV_FILE = process.env.ENV_FILE;      // required: a file outside the repo, chmod 600; no default path is baked in
if (!ENV_FILE) { console.error('ENV_FILE is required: the path of a key file outside the repo (chmod 600)'); process.exit(2); }
const RPC = process.env.NEAR_RPC || 'https://rpc.testnet.near.org';
const FAUCET = process.env.NEAR_FAUCET || 'https://helper.testnet.near.org/account';
const ALLOWANCE_NEAR = '0.25';

const N = (0, eval)(fs.readFileSync(BUNDLE, 'utf8') + ';NearApi');

function readEnv() {
  if (!fs.existsSync(ENV_FILE)) return {};
  const o = {};
  for (const line of fs.readFileSync(ENV_FILE, 'utf8').split('\n')) {
    const m = line.match(/^([A-Z0-9_]+)=(.*)$/);
    if (m) o[m[1]] = m[2];
  }
  return o;
}
function writeEnv(o) {
  const body = '# W2 spike throwaway TESTNET account + guest key. Secrets. Never commit, never print.\n' +
    Object.entries(o).map(([k, v]) => `${k}=${v}`).join('\n') + '\n';
  fs.writeFileSync(ENV_FILE, body, { mode: 0o600 });
  fs.chmodSync(ENV_FILE, 0o600);
}
const out = (o) => console.log(JSON.stringify(o, null, 1));
const provider = () => new N.JsonRpcProvider({ url: RPC });

async function create() {
  const env = readEnv();
  if (env.ACCOUNT_ID) return out({ step: 'create', skipped: 'ENV_FILE already holds an account (one account only)', accountId: env.ACCOUNT_ID });
  const accountId = `trenchie-w2-${new Date().toISOString().slice(0, 10).replace(/-/g, '')}.testnet`;
  const kp = N.KeyPairEd25519.fromRandom();
  const res = await fetch(FAUCET, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ newAccountId: accountId, newAccountPublicKey: kp.getPublicKey().toString() }),
  });
  const text = await res.text();
  if (res.status !== 200) {
    return out({ step: 'create', ok: false, status: res.status, body: text.slice(0, 300), note: 'STOP: not retried; a captcha or refusal goes to Pat' });
  }
  writeEnv({ NETWORK: 'testnet', ACCOUNT_ID: accountId, ACCOUNT_SECRET_KEY: kp.toString() });
  out({ step: 'create', ok: true, status: 200, accountId, publicKey: kp.getPublicKey().toString(), faucetBody: text.slice(0, 200) });
}

async function addkey() {
  const env = readEnv();
  if (!env.ACCOUNT_ID) throw new Error('run create first');
  if (env.GUEST_PUBLIC_KEY) return out({ step: 'addkey', skipped: 'a guest key was already added', txHash: env.GUEST_TX_HASH });
  const signer = N.KeyPairSigner.fromSecretKey(env.ACCOUNT_SECRET_KEY);
  const account = new N.Account(env.ACCOUNT_ID, provider(), signer);
  const guest = N.KeyPairEd25519.fromRandom(); // generated here, in memory; the secret goes only to ENV_FILE
  const receiver = `market.${env.ACCOUNT_ID}`;
  const res = await account.addFunctionCallAccessKey({
    publicKey: guest.getPublicKey().toString(), contractId: receiver, methodNames: [], allowance: N.nearToYocto(ALLOWANCE_NEAR),
  });
  const txHash = res.transaction.hash;
  writeEnv({ ...env, GUEST_PUBLIC_KEY: guest.getPublicKey().toString(), GUEST_SECRET_KEY: guest.toString(), GUEST_RECEIVER: receiver, GUEST_TX_HASH: txHash });
  out({ step: 'addkey', ok: true, txHash, signer: res.transaction.signer_id, receiver: res.transaction.receiver_id, guestPublicKey: guest.getPublicKey().toString(), status: Object.keys(res.status)[0], actions: res.transaction.actions });
}

async function readback() {
  const env = readEnv();
  if (!env.GUEST_PUBLIC_KEY) throw new Error('run addkey first');
  const list = await provider().viewAccessKeyList({ accountId: env.ACCOUNT_ID });
  const row = list.keys.find((k) => k.public_key === env.GUEST_PUBLIC_KEY);
  const fc = row && row.access_key.permission && row.access_key.permission.FunctionCall;
  const checks = {
    keyPresent: !!row,
    isFunctionCall: !!fc,
    receiver_id: fc && fc.receiver_id,
    receiverIsMarketLabel: !!fc && fc.receiver_id === `market.${env.ACCOUNT_ID}`,
    allowanceYocto: fc && fc.allowance,
    allowanceIs0_25NEAR: !!fc && fc.allowance === N.nearToYocto(ALLOWANCE_NEAR).toString(),
    method_names: fc && fc.method_names,
    anyMethod: !!fc && fc.method_names.length === 0,
    totalKeysOnAccount: list.keys.length,
  };
  const pass = checks.keyPresent && checks.isFunctionCall && checks.receiverIsMarketLabel && checks.allowanceIs0_25NEAR && checks.anyMethod;
  out({ step: 'readback', account: env.ACCOUNT_ID, publicKey: env.GUEST_PUBLIC_KEY, checks, readbackMatches: pass });
  process.exitCode = pass ? 0 : 1;
}

const cmd = process.argv[2] || 'all';
try {
  if (cmd === 'create' || cmd === 'all') await create();
  if (cmd === 'addkey' || cmd === 'all') await addkey();
  if (cmd === 'readback' || cmd === 'all') await readback();
} catch (e) {
  out({ ok: false, error: String(e && e.message || e).slice(0, 400) });
  process.exitCode = 1;
}
