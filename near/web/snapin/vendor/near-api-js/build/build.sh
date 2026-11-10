#!/bin/sh
# Rebuild the two vendored bundles from the pinned inputs in this folder.
# Usage: sh build.sh <empty-scratch-dir>      (never run inside the repo; it needs registry.npmjs.org)
set -eu
OUT="${1:?scratch dir}"
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$OUT" && cp "$HERE"/package.json "$HERE"/package-lock.json "$HERE"/entry.mjs "$HERE"/entry-nc.mjs "$HERE"/util-shim.js "$OUT"/
cd "$OUT"
npm ci --ignore-scripts=false >/dev/null     # esbuild's postinstall fetches nothing extra; versions come from the lockfile
E=./node_modules/.bin/esbuild
$E entry.mjs    --bundle --format=iife --global-name=NearApi        --platform=browser --target=es2020 --minify-syntax --legal-comments=none --alias:util=./util-shim.js --outfile=out/near-api-js-7.3.1.min.js
$E entry-nc.mjs --bundle --format=iife --global-name=NearConnectLib --platform=browser --target=es2020 --minify-syntax --legal-comments=none --alias:util=./util-shim.js --outfile=out/near-connect-0.12.0.min.js
# drop the /** ... */ documentation blocks (they quote upstream URLs that the public-repo leak check reads as paths); code is untouched
for f in out/*.js; do perl -0pi -e 's{[ \t]*/\*\*.*?\*/[ \t]*\n?}{}gs' "$f"; done
shasum -a 256 out/*.js
