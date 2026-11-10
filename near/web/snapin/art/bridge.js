/* bridge.js: loads the approved trenchie modules (near/web/art) and three as ES modules, hands them to the page's classic
 * scripts as window.THREE and window.LOOK3, then loads those scripts in order. The page's own art is only what the player
 * look needs on top of the approved body: parts-s3.js (the player face, hair and hat parts) and portrait.js (the still). */
import * as THREE from 'three';
import { LOOK3 } from '../../art/index.js';

window.THREE = THREE;
window.LOOK3 = LOOK3;

const SCRIPTS = ['art/parts-s3.js', 'art/portrait.js', 'ui.js', 'marks.js', 'providers.js',
  'vendor/near-api-js/near-api-js-7.3.1.min.js', 'vendor/near-api-js/near-connect-0.12.0.min.js',
  'wallet.js', 'sheet.js', 'doors.js', 'card.js', 'app.js'];

for (const src of SCRIPTS) {
  await new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src; s.async = false;
    s.onload = resolve; s.onerror = () => reject(new Error('could not load ' + src));
    document.head.appendChild(s);
  });
}
