/* bridge.js: loads the approved trenchie modules (near/web/art) and three as ES modules, hands them to the page's classic
 * scripts as window.THREE and window.LOOK3, then loads those scripts in order. The page's own art is only what the player
 * look needs on top of the approved body: parts-s3.js (the player face, hair and hat parts) and portrait.js (the still). */
import * as THREE from 'three';
import { LOOK3, ITEMS } from '../../art/index.js';

window.THREE = THREE;
window.LOOK3 = LOOK3;
window.ITEMS3 = ITEMS;   // every item's record by id (name, slot, tier): the guide names items from it, no fetch

const SCRIPTS = ['art/parts-s3.js', 'art/portrait.js', 'ui.js', 'marks.js', 'providers.js',
  'vendor/near-api-js/near-api-js-7.3.1.min.js', 'vendor/near-api-js/near-connect-0.12.0.min.js',
  'chain.js', 'wallet.js', 'identity.js', 'emoji-set.js', 'sheet.js', 'doors.js', 'card.js', 'room.js', 'brain.js', 'chat.js', 'app.js'];
// brain.js (the player's AI) and emoji-set.js (the emoji rules) are other lanes' files and optional: without it the guide still works and says the fighter is on
// the arena's own tactics; every other script is required.
const OPTIONAL = new Set(['brain.js', 'emoji-set.js']);   // emoji-set.js: the persona emoji rules (battle mode); without it no sheet carries a set

for (const src of SCRIPTS) {
  await new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src; s.async = false;
    s.onload = resolve; s.onerror = () => (OPTIONAL.has(src) ? resolve() : reject(new Error('could not load ' + src)));
    document.head.appendChild(s);
  });
}
