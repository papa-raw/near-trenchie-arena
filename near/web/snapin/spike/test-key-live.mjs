// W2 live check of "Test my key": SnapWallet.testKey() against the deployed testnet market, on a throwaway account.
//   ENV_FILE=<key file outside the repo> NODE_USE_ENV_PROXY=1 node near/web/snapin/spike/test-key-live.mjs
// ENV_FILE is the W2 spike's throwaway TESTNET account (guest-key.mjs created it; chmod 600, never committed).
// What a wallet does in the browser, this does in node with the account's own full-access key, then the page's code runs:
//   1. remove the account's earlier guest key if it names another receiver (the old spike's label), so the account holds
//      one limited key only;
//   2. add ONE function-call key: receiver = chain.js's market, any method, 0.25 NEAR allowance, no deposit;
//   3. SnapWallet.testKey(): one balance_of call to the market, signed by that guest key, 0 NEAR attached.
// It prints the hashes and the account, never a secret. Testnet only. Check the result with the read-only checker:
//   python3 check_wallet_key.py <account> --tx <testKey hash> --market <market> --rpc <rpc>
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const ENV_FILE = process.env.ENV_FILE;
if (!ENV_FILE) { console.error('ENV_FILE is required: the throwaway account key file outside the repo (chmod 600)'); process.exit(2); }
const N = (0, eval)(fs.readFileSync(path.join(HERE, '..', 'vendor', 'near-api-js', 'near-api-js-7.3.1.min.js'), 'utf8') + ';NearApi');
const CHAIN = require('../chain.js');
const W = require('../wallet.js');
const env = Object.fromEntries(fs.readFileSync(ENV_FILE, 'utf8').split('\n').map((l) => l.match(/^([A-Z0-9_]+)=(.*)$/)).filter(Boolean).map((m) => [m[1], m[2]]));
if (env.NETWORK !== 'testnet' || !env.ACCOUNT_ID || !env.ACCOUNT_SECRET_KEY) { console.error('ENV_FILE does not hold a testnet throwaway account'); process.exit(2); }
const out = (o) => console.log(JSON.stringify(o, null, 1));

const provider = new N.JsonRpcProvider({ url: CHAIN.rpc });
const owner = new N.Account(env.ACCOUNT_ID, provider, N.KeyPairSigner.fromSecretKey(env.ACCOUNT_SECRET_KEY));
try {
  // 1. the account's other limited keys (the earlier spike's label key) go, so the checker sees one guest key only
  const keys = (await provider.viewAccessKeyList({ accountId: env.ACCOUNT_ID })).keys;
  for (const k of keys) {
    const fc = k.access_key.permission && k.access_key.permission.FunctionCall;
    if (fc && fc.receiver_id !== CHAIN.marketAccount) {
      const r = await owner.deleteKey(k.public_key);   // 7.3.1: positional
      out({ step: 'delete earlier guest key', publicKey: k.public_key, receiver: fc.receiver_id, txHash: r.transaction.hash });
    }
  }
  // 2. ONE function-call key for the market, as the wallet adds it (receiver, allowance, no deposit)
  const guest = N.KeyPairEd25519.fromRandom();
  const add = await owner.addFunctionCallAccessKey({ publicKey: guest.getPublicKey().toString(), contractId: CHAIN.marketAccount, methodNames: [], allowance: N.nearToYocto('0.25') });
  out({ step: 'add guest key', account: env.ACCOUNT_ID, publicKey: guest.getPublicKey().toString(), receiver: CHAIN.marketAccount, txHash: add.transaction.hash });
  // 3. the page's own code: SnapWallet.testKey()
  W._adoptGuest(env.ACCOUNT_ID, guest, CHAIN.marketAccount);
  const r = await W.testKey({}, { NearApi: N });
  out({ step: 'SnapWallet.testKey()', result: r });
  process.exitCode = r.ok ? 0 : 1;
} catch (e) {
  out({ ok: false, error: String(e && e.message || e).slice(0, 400) });
  process.exitCode = 1;
}
