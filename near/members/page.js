// Member consent only. All outcomes come from the owner's authenticated room client.
const root = document.querySelector('#app');
let view = null, fault = null, busy = false, pending = null;
let screen = ['#room','#terms','#change'].includes(location.hash) ? location.hash.slice(1) : 'terms';
let step = 'review', reviewedVersion = null, reviewedProposal = null, changed = false;
let readGeneration = 0;
const html = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const button = (text, action, kind='primary') => `<button type="button" class="button ${kind}" data-action="${action}">${text}</button>`;
const back = () => button('Back','room','quiet');
const seconds = value => {
  const ms = BigInt(value), fraction = (ms % 1000n).toString().padStart(3,'0').replace(/0+$/,'');
  return `${ms / 1000n}${fraction ? '.'+fraction : ''} seconds`;
};
const timing = terms => `<dl class="rules"><div><dt>Input interval</dt><dd>${seconds(terms.input_interval_ms)}</dd></div><div><dt>Segment length</dt><dd>${seconds(terms.segment_ms)}</dd></div><div><dt>Game speed</dt><dd>${html(terms.simulation_hz)} Hz</dd></div></dl>`;
const rules = () => `<details data-detail="rules"><summary>All room rules</summary><ul><li>Fight state, predictions and results are public.</li><li>Your reasoning, keys and spend stay private.</li><li>The room takes no payments.</li><li>The room checks ownership or custody before you can play.</li><li>The room owner can remove or block members.</li><li>Completed records do not change.</li></ul></details>`;
const outcome = (tag,title,intro,tone='') => `<div class="outcome"><span class="result-tag ${tone}">${tag}</span><h1 tabindex="-1">${title}</h1><p class="intro">${intro}</p></div>`;
const memberName = () => view.snapshot.members.find(row=>row.member_id === view.snapshot.viewer_member_id)?.name || view.snapshot.viewer_member_id;
const effect = () => BigInt(view.snapshot.proposal.proposed_ms) < BigInt(view.snapshot.proposal.current_ms) ? 'more' : 'less';
const identity = () => `<div class="identity">Answer for <b>${html(memberName())}</b></div>`;
const proposalKey = () => view.snapshot.proposal ? JSON.stringify([view.snapshot.terms?.version,view.snapshot.proposal]) : '';
const comparison = (applied=false) => {
  const proposal = view.snapshot.proposal;
  return `<div class="compare ${applied ? 'applied' : ''}"><div class="compare-label">Input interval</div><div class="compare-values"><div><small>${applied ? 'Previous' : 'Current'}</small><strong>${seconds(proposal.current_ms)}</strong></div><span class="arrow" aria-hidden="true">→</span><div class="new"><small>${applied ? 'Current' : 'Proposed'}</small><strong>${seconds(applied ? view.snapshot.terms.input_interval_ms : proposal.proposed_ms)}</strong></div></div></div>`;
};
function boundary() {
  const current = /^segment:(0|[1-9][0-9]*)$/.exec(view.current_segment_id);
  const next = current && 'segment:' + (BigInt(current[1]) + 1n);
  return view.snapshot.proposal.boundary_segment_id === next ? 'the next segment' : html(view.snapshot.proposal.boundary_segment_id);
}
function answerList(label='Member answers') {
  const proposal = view.snapshot.proposal, snapshot = view.snapshot;
  const members = proposal.required_members.map(id => {
    const name = snapshot.members.find(row=>row.member_id === id)?.name || id;
    const answer = proposal.accepted_members.includes(id) ? 'Accepted' : proposal.declined_members.includes(id) ? 'Declined' : 'No answer';
    return `<li>${html(name)}${id === snapshot.viewer_member_id ? ' · You' : ''}<span>${answer}</span></li>`;
  }).join('');
  const expiry = new Date(Number(proposal.expires_at));
  const exactExpiry = Number.isSafeInteger(Number(proposal.expires_at)) && !Number.isNaN(expiry.getTime()) ? expiry.toISOString().replace('T',' ').replace('.000Z',' UTC') : html(proposal.expires_at)+' ms';
  return `<details data-detail="members"><summary>${label}</summary><ul class="members">${members}</ul>${proposal.state === 'pending' ? `<p>Answer before ${exactExpiry}.</p>` : ''}</details>`;
}
function unavailable() {
  const title = screen === 'change' ? 'Change unavailable' : 'Terms unavailable';
  const intro = screen === 'change' ? 'The room could not confirm this change.' : 'The room could not load the current terms.';
  const reason = screen === 'change' ? 'Your answer is not confirmed.' : 'You must read the terms before accepting.';
  return {state:'unavailable',status:'Unavailable',tone:'red',body:outcome(screen === 'change' ? 'Room change' : 'Room terms',title,intro,'red')+`<div class="empty-lines">${reason}</div>`,foot:back()+button('Refresh','refresh')};
}
function wallet() {
  return {state:'wallet',status:'Connect',tone:'',body:outcome('Your wallet','Connect to answer','Connect your NEAR wallet to accept for your persona.','expired')+(fault?.public_terms ? `<div class="group"><h3>Current game rules</h3>${timing(fault.public_terms)}</div>` : ''),foot:back()+button('Connect wallet','connect')};
}
function checking() {
  const terms = view.snapshot.terms;
  return {state:'sending',status:'Checking',tone:'',body:outcome('Sending your answer',screen === 'change' ? 'Checking your answer' : 'Checking acceptance',screen === 'change' ? 'The room has not confirmed your answer yet.' : 'Wait for the room to confirm your answer.','expired')+(screen === 'change' ? comparison()+'<p class="explain">Current terms still apply.</p>' : timing(terms)+'<p class="small-note">Keep these terms open while the room responds.</p>')+identity(),foot:back()+button('Check answer','check')};
}
function unpublished() {
  return {state:'empty',status:'Waiting',tone:'',body:outcome('No terms yet','The room is getting ready','The room has not published its terms.','expired')+'<div class="empty-lines">You can watch while you wait.<br>Play opens after you accept the terms.</div>',foot:back()+button('Refresh','refresh')};
}
function termsPage() {
  const terms = view.snapshot.terms;
  if (terms === null) return unpublished();
  if (terms.accepted) return {state:'accepted',status:'Accepted',tone:'green',body:outcome('✓ Answer recorded','Terms accepted',`${html(memberName())}${view.can_answer ? " can play under the current room terms." : " has accepted. Rejoin with control to play."}`)+timing(terms)+`<p class="explain">A proposed change needs a separate answer.</p><a class="answer-line" href="#change" data-action="change"><span>Room change</span><strong>${view.snapshot.proposal && (view.snapshot.proposal.state !== 'pending' || view.snapshot.proposal.accepted_members.includes(view.snapshot.viewer_member_id) || view.snapshot.proposal.declined_members.includes(view.snapshot.viewer_member_id)) ? 'View answer' : 'Review change'} →</strong></a>`+rules(),foot:button('Return to room','room')};
  if (step === 'policy') return {state:'policy',status:'Review',tone:'',body:'<div class="step-note">Then, the room rules</div><h1 tabindex="-1">Public play.<br>Private reasoning.</h1><section class="policy-block"><h3>Public</h3><p>Fight state, predictions, results and house spend.</p></section><section class="policy-block"><h3>Private</h3><p>Your reasoning, keys and spend.</p></section><section class="policy-block"><h3>Changing the rules</h3><p>All affected members must accept.</p><p>Changes start at a new segment.</p></section>'+rules()+identity()+(!view.can_answer ? '<p class="notice">Your grant allows watching. Rejoin with control to answer.</p>' : ''),foot:button('Back','terms','quiet')+(view.can_answer ? button('Accept terms','accept_terms') : button('Refresh','refresh'))};
  return {state:changed ? 'changed' : 'review',status:'Review',tone:'',body:`<div class="step-note">${changed ? 'New terms to review' : 'First, the game rules'}</div><h1 tabindex="-1">Before you play</h1><p class="intro">Review the terms for ${html(memberName())}.</p><section class="group">${timing(terms)}</section><div class="preview-result"><h3>Next, the room rules</h3><p>Review what is public and how rules change.</p></div>`+identity(),foot:back()+button('Review room rules','policy')};
}
function changeOutcome(state) {
  const proposal = view.snapshot.proposal, accepted = proposal.accepted_members.length, total = proposal.required_members.length;
  const count = `<div class="answer-line ${state === 'declined' ? 'red' : 'green'}"><span>Members accepted</span><strong>${accepted} of ${total}</strong></div>`;
  let body;
  if (state === 'answered') {
    const remaining = total-accepted;
    const waiting = remaining === 1 ? 'one more member' : `${remaining} more members`;
    body=outcome('✓ Your answer is recorded','You accepted',`The room is waiting for ${waiting}.`)+comparison()+count+'<p class="explain">Current terms still apply.</p>'+answerList();
  } else if (state === 'scheduled') {
    body=outcome('✓ Everyone accepted','Change agreed',`The change starts at ${boundary()}.`)+comparison()+count+`<p class="explain">Until then, the interval stays at ${seconds(view.snapshot.terms.input_interval_ms)}.</p>`+answerList();
  } else if (state === 'applied') {
    body=outcome('✓ Change is in use','Change applied',`The interval is now ${seconds(view.snapshot.terms.input_interval_ms)}.`)+comparison(true)+count+answerList();
  } else {
    const ownDecline = proposal.declined_members.includes(view.snapshot.viewer_member_id);
    const expired = state === 'expired';
    body=outcome(expired ? 'No answer needed' : ownDecline ? 'Your answer is recorded' : 'A member declined',expired ? 'The change expired' : ownDecline ? 'You declined' : 'Change declined',expired ? 'The room did not get every answer in time.' : 'This change will not take effect.',expired ? 'expired' : 'red')+comparison()+`<p class="outcome-rule">The input interval stays at <b>${seconds(view.snapshot.terms.input_interval_ms)}</b>.</p>`+(expired ? `<div class="answer-line"><span>Members accepted</span><strong>${accepted} of ${total}</strong></div>` : '')+answerList();
  }
  return {state,status:state === 'applied' ? 'Applied' : state === 'scheduled' ? 'Accepted' : state === 'declined' ? 'Declined' : state === 'expired' ? 'Expired' : 'Waiting',tone:state === 'scheduled'||state === 'applied' ? 'green' : state === 'declined' ? 'red' : '',body,foot:button('Return to room','room')};
}
function changePage() {
  const snapshot = view.snapshot, proposal = snapshot.proposal;
  if (snapshot.terms === null) return unpublished();
  if (!proposal) return {state:'empty',status:'Current',tone:'green',body:outcome('Room changes','No change to review','The current room terms still apply.','expired')+timing(snapshot.terms),foot:button('Return to room','room')};
  if (proposal.state === 'expired') return changeOutcome('expired');
  if (proposal.state === 'declined') return changeOutcome('declined');
  if (proposal.state === 'accepted') return changeOutcome('applied');
  if (proposal.accepted_members.length === proposal.required_members.length) return changeOutcome('scheduled');
  if (proposal.accepted_members.includes(snapshot.viewer_member_id)) return changeOutcome('answered');
  const canAnswer = view.can_answer && proposal.required_members.includes(snapshot.viewer_member_id);
  if (step === 'confirm') return {state:'confirm',status:'Waiting',tone:'',body:'<h1 tabindex="-1">Room change</h1><p class="intro">The room needs your answer.</p>'+comparison()+`<p class="explain">Your persona can send input ${effect()} often.</p><section class="policy"><h3>When it starts</h3><p>All affected members must accept.</p>`+`<p>The change starts at ${boundary()}.</p></section><div class="answer-line"><span>Your answer</span><strong>Waiting</strong></div>`+answerList(`${proposal.accepted_members.length} of ${proposal.required_members.length} members accepted`)+identity()+(!canAnswer ? '<p class="notice">Only affected members with control can answer.</p>' : ''),foot:back()+(canAnswer ? `<div class="actions">${button('Decline','decline_change','decline')}${button('Accept change','accept_change')}</div>` : button('Refresh','refresh'))};
  return {state:'review',status:'Waiting',tone:'',body:'<h1 tabindex="-1">Room change</h1><p class="intro">A change needs your answer.</p>'+comparison()+`<div class="preview-result"><h3>What this means</h3><p>Your persona can send input ${effect()} often.</p></div><div class="answer-line"><span>Your answer</span><strong>Waiting</strong></div>`+answerList(`${proposal.accepted_members.length} of ${proposal.required_members.length} members accepted`)+identity(),foot:back()+button('Review change','confirm')};
}
function roomPage() {
  if (fault || !view) {
    const room = fault?.room_label || view?.room_label || 'Room';
    return {state:'return',status:'Unavailable',tone:'red',body:`<h1 tabindex="-1">${html(room)}</h1><p class="intro">Private room details are unavailable.</p><p class="room-status">You can return to watch the room.</p><div class="room-return"><a href="#terms" data-action="terms">Room terms</a><a href="#change" data-action="change">Room change</a></div>`,foot:button('Refresh','refresh')};
  }
  const accepted = view.snapshot.terms?.accepted === true;
  const proposal = view.snapshot.proposal;
  const answer = proposal && (proposal.state !== 'pending' || proposal.accepted_members.includes(view.snapshot.viewer_member_id));
  return {state:'return',status:'Room',tone:'green',body:`<h1 tabindex="-1">${html(view.room_label)}</h1><p class="intro">Your persona · ${html(memberName())}</p><p class="room-status">${accepted ? 'Current terms accepted' : view.snapshot.terms === null ? 'Waiting for room terms' : 'Read room terms before playing'}</p><div class="room-return"><a href="#terms" data-action="terms">Room terms</a>${accepted ? `<a href="#change" data-action="change">${answer ? 'View change' : 'Review change'}</a>` : ''}</div>`,foot:button('Room terms','terms')};
}
function render() {
  let page;
  if (screen === 'room') page=roomPage();
  else if (fault?.error === 'wallet_disconnected') page=wallet();
  else if (fault && !pending || !view) page=unavailable();
  else if ((busy || pending) && screen !== 'room') page=checking();
  else page=screen === 'change' ? changePage() : termsPage();
  const open = [...root.querySelectorAll('details[open]')].map(node=>node.dataset.detail);
  const room = view?.room_label || fault?.room_label || 'Room';
  document.body.classList.toggle('room-screen',screen === 'room');
  document.body.classList.toggle('room-unknown',!!fault || !view);
  document.body.dataset.screen=screen;
  root.dataset.state=page.state;
  root.setAttribute('aria-busy',String(busy));
  root.innerHTML=`<header class="gamebar"><button class="brand" type="button" data-action="room">Trenchie</button><span class="wallet ${fault ? 'off' : ''}">${fault ? fault.wallet_connected === false ? 'Wallet disconnected' : 'Wallet state unknown' : view ? 'Wallet connected' : 'Checking wallet'}</span></header><div class="stage"><img class="room-scene" src="/arena.png" alt="" aria-hidden="true"><main class="paper"><header class="paper-head"><span class="room-tag">${html(room)}</span><span class="state ${page.tone}">${page.status}</span></header><div class="content" aria-live="polite">${page.body}</div><footer>${page.foot}</footer></main></div>`;
  for (const node of root.querySelectorAll('details')) node.open=open.includes(node.dataset.detail);
  document.fonts.ready.then(()=>{document.documentElement.dataset.ready='true';});
}
async function api(request) {
  const controller = new AbortController();
  const timeout=setTimeout(()=>controller.abort(),12000);
  try {
    const response = await fetch('/api/member',{method:request ? 'POST' : 'GET',cache:'no-store',credentials:'same-origin',signal:controller.signal,...(request ? {headers:{'Content-Type':'application/json','X-Member-Action':'explicit'},body:JSON.stringify(request)} : {})});
    const value=await response.json();
    if (!response.ok || value.error) throw value;
    return value;
  } finally {clearTimeout(timeout);}
}
function install(value) {
  const terms=value.snapshot.terms;
  const oldVersion=view?.snapshot.terms?.version || sessionStorage.getItem(`terms:${value.snapshot.room_id}`);
  const previousProposal=view?.snapshot.proposal?.proposal_id;
  const acceptedVersion=sessionStorage.getItem(`acceptedTerms:${value.snapshot.room_id}`);
  const priorVersion=acceptedVersion || oldVersion;
  changed=terms !== null && !terms.accepted && (changed || !!priorVersion && priorVersion !== terms.version);
  if (terms === null) {reviewedVersion=null;reviewedProposal=null;}
  if (terms === null || changed || previousProposal !== value.snapshot.proposal?.proposal_id) step='review';
  view=value;fault=null;pending=null;
  if (terms !== null) sessionStorage.setItem(`terms:${view.snapshot.room_id}`,terms.version);
  if (terms?.accepted) sessionStorage.setItem(`acceptedTerms:${view.snapshot.room_id}`,terms.version);
}
async function refresh() {
  if (busy) return;
  const generation=++readGeneration;
  try {const value=await api();if (generation === readGeneration) install(value);}
  catch (error) {if(generation === readGeneration) fault=error;}
  render();
}
async function answer(action) {
  if (busy || pending || !view?.can_answer || view.snapshot.terms === null) return;
  const request={action,terms_version:view.snapshot.terms.version};
  if (action === 'accept_terms' && reviewedVersion !== request.terms_version) {step='review';render();return;}
  if (action !== 'accept_terms') {
    if (reviewedProposal !== proposalKey()) {step='review';render();return;}
    request.proposal_id=view.snapshot.proposal.proposal_id;
  }
  busy=true;pending=request;fault=null;readGeneration++;render();
  try {install(await api(request));}
  catch (error) {
    if (error.error === 'version_mismatch') {pending=null;changed=true;step='review';}
    else if (error.error !== 'answer_uncertain' && error.error) {pending=null;fault=error;}
  } finally {busy=false;}
  if (changed) await refresh();
  render();
}
async function action(name) {
  if (name === 'refresh' || name === 'check') return refresh();
  if (name === 'connect') {
    try {install(await api({action:'connect'}));} catch (error) {fault=error;}
    render();return;
  }
  if (['accept_terms','accept_change','decline_change'].includes(name)) return answer(name);
  if (name === 'policy') {reviewedVersion=view.snapshot.terms.version;changed=false;step='policy';}
  else if (name === 'confirm') {reviewedProposal=proposalKey();step='confirm';}
  else {screen=name;step='review';location.hash=name;}
  render();
}
root.addEventListener('click',event=>{const target=event.target.closest('[data-action]');if(target){event.preventDefault();action(target.dataset.action);}});
window.addEventListener('hashchange',()=>{const next=location.hash.slice(1);if(['room','terms','change'].includes(next)){screen=next;step='review';render();}});
window.addEventListener('focus',()=>refresh());
setInterval(()=>{if(document.visibilityState === 'visible' && !busy) refresh();},10000);
await refresh();
