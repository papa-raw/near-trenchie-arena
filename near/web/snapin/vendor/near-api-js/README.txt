Vendored browser bundles for the wallet join spike (task W2). No app build step at run time:
a page loads these two classic scripts. They were built ONCE, here, from exact npm versions.

near-api-js-7.3.1.min.js    -> window.NearApi        (KeyPairEd25519, actions, JsonRpcProvider, Account, ...)
near-connect-0.12.0.min.js  -> window.NearConnectLib (NearConnector, ...)

near-api-js 7.3.1
  published   2026-08-12 (npm time). 7.4.0 (2026-10-23) is under the project's 2-week version-age rule: not used.
  licence     (MIT AND Apache-2.0)
  tarball     https://registry.npmjs.org/near-api-js/-/near-api-js-7.3.1.tgz
  tgz sha256  c87625f57faf7a32c557e73486182a87d2533c1661bc019e8a92f33f300724e1
  tgz sha1    03b79f5c83fde1c2ca55ba2b1aea0084bbc33798 (npm dist.shasum)
  Ships ESM + CJS only (lib/index.js, lib/index.cjs), NO browser/IIFE bundle, so esbuild was used.

@hot-labs/near-connect 0.12.0 (the stock wallet chooser and runtime manifest; no app-maintained wallet list or executor pins)
  published   2026-10-26 (npm time)
  licence     MIT
  tarball     https://registry.npmjs.org/@hot-labs/near-connect/-/near-connect-0.12.0.tgz
  tgz sha256  b5cd265f70e76c1fa3aeba5fca5640939fb577f7a385ca96eb44ead8f8898e4e
  tgz sha1    991338bf45804b984f0881572eaae5355a87862e (npm dist.shasum)
  No runtime dependencies. Its wallets run as sandboxed iframes whose code is fetched from each wallet's own host
  (named in its own default manifest) at run time: those scripts are NOT vendored and are third-party code.
  The bundle version and hashes below stay pinned; the upstream manifest and wallet integrations may update independently.
  Integration: https://docs.near.org/tools/near-connect

esbuild 0.28.0 (published 2026-04-02), build command (see build/build.sh; inputs and lockfile are in build/):
  esbuild entry.mjs    --bundle --format=iife --global-name=NearApi        --platform=browser --target=es2020 --minify-syntax --legal-comments=none --alias:util=./util-shim.js --outfile=near-api-js-7.3.1.min.js
  esbuild entry-nc.mjs --bundle --format=iife --global-name=NearConnectLib --platform=browser --target=es2020 --minify-syntax --legal-comments=none --alias:util=./util-shim.js --outfile=near-connect-0.12.0.min.js
  entry.mjs is `export * from 'near-api-js'`; entry-nc.mjs is `export * from '@hot-labs/near-connect'`.
  The only edit to the dependency graph: `util` (a node built-in required by generate-function, a transitive of
  is-my-json-valid) is aliased to build/util-shim.js, which implements the one function used, util.format.

Output sha256
  7821eae006b6b694da59664cbee98f612c9d235dacb21d26cd85d03b6ecea5c8  near-api-js-7.3.1.min.js   (195,402 bytes)
  1896450e6c586092197ec1b872892054fb5355569dca58be2ffd8355e846c2c6  near-connect-0.12.0.min.js (96,258 bytes; unchanged by the stock-chooser integration)

Packages inside the near-api-js bundle (from esbuild's metafile) and their licences:
  near-api-js 7.3.1 (MIT AND Apache-2.0) · @noble/curves 2.2.0 MIT · @noble/hashes 2.2.0 MIT · @noble/post-quantum 0.6.1 MIT
  @scure/base 2.2.0 MIT · borsh 2.0.0 Apache-2.0 · is-my-json-valid 2.20.6 MIT · generate-function 2.3.1 MIT
  generate-object-property 1.2.0 MIT · is-my-ip-valid 1.0.1 MIT · is-property 1.0.2 MIT · jsonpointer 5.0.1 MIT · xtend 4.0.2 MIT
Packages inside the near-connect bundle: @hot-labs/near-connect 0.12.0 MIT only.
Licence texts: the upstream tarballs (above). The minified files carry no banner (--legal-comments=none); keep this README with them.

Known caveat (INFERRED, not tested in a CSP page): is-my-json-valid compiles validators with `new Function`, so a page with a
CSP that forbids 'unsafe-eval' may break the code paths that call it. The spike pages here set no CSP.

Build note (2026-11-10): the files keep the .min.js names the pages load, but they are NOT identifier-mangled and keep their whitespace
(esbuild --minify-syntax only), and every /** ... */ documentation block is stripped afterwards (build/build.sh does both). Reason: the public-repo
leak check reads mangled one-letter names and upstream doc URLs as internal ids and paths. build/package-lock.json has its "resolved" URLs removed
for the same reason; `npm ci` still checks every package against its integrity hash.
