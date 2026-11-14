// Presentation-only regression: roster autopilot metadata must not become a feed notice.
import assert from 'node:assert/strict';
import { Feed } from './arena/feed.mjs';
const fake=()=>({children:[],style:{},dataset:{},className:'',textContent:'',hidden:false,
 setAttribute(){},appendChild(c){this.children.push(c);return c;},append(...c){this.children.push(...c);},replaceChildren(...c){this.children=c;}});
const doc={createElement:fake,createTextNode:text=>({textContent:text})};
const text=el=>el.textContent+(el.children||[]).map(text).join('');
const feed=new Feed(doc,fake(),{name:id=>id,colour:()=> '#2a2622'});
const roster={chip:'autopilot'};
feed.push({kind:'say',who:'Moonwood',text:'The tide listens.',status:roster.chip});
feed.push({kind:'say',who:'Coral',text:'Mind the reef.',status:'blocked line'});
assert.equal(feed.box.children.length,1,'feed contains only its slip list');
assert.doesNotMatch(text(feed.box),/autopilot/i);assert.match(text(feed.box),/The tide listens/);assert.match(text(feed.box),/blocked line/);
assert.equal(feed.shown().length,2);assert.equal(feed.list.children[0].className,'say');
console.log('arena-no-autopilot: roster chip produces no notice; speech and other statuses preserved');
