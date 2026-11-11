/* chain.js: the one place the snap-in pages name the chain they talk to. Testnet only.
 *
 * A classic script, loaded before wallet.js; in a page it sets window.SNAPIN_CHAIN, under node it is module.exports.
 *   marketAccount  the deployed testnet market contract: every guest key names it as its only receiver
 *   rpc            the testnet RPC the page sends its own guest-key calls to ("Test my key")
 * Change the market or the RPC here and nowhere else.
 */
(function (root) {
  'use strict';
  var chain = {
    network: 'testnet',
    marketAccount: 'market.trenchie-r4b-20261111.testnet',
    rpc: 'https://rpc.testnet.fastnear.com'
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = chain;
  else root.SNAPIN_CHAIN = chain;
})(typeof globalThis !== 'undefined' ? globalThis : (typeof window !== 'undefined' ? window : this));
