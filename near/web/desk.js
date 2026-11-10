'use strict';
// RD-01 A. All operational facts come from the configured local archive.
const arrow = '<span aria-hidden="true">→</span>';
const rows = [
  ['arena', 'Watch the arena', 'Live room pending', 'View'],
  ['agent', 'Bring your agent', 'Hosted command pending', 'Guide'],
  ['forecast', 'Read its prediction', 'Public forecast pending', 'Inspect'],
  ['replay', 'Check its replay', 'Chain check pending', 'Inspect']
];
let evidence = {state:'pending', predictions:[]};
let activeRoute = '';
const escapeHTML = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const scene = '<div class="hero-scene"><img src="assets/arena.png" alt="Rounded toy fighters in a sandy arena"><span class="cap">Arena preview</span></div>';
document.body.innerHTML = `<main class="desk scorebook">
  <header class="brandbar"><a class="brand" href="#" aria-label="Trenchie reviewer desk">Trenchie<span>Reviewer desk</span></a><span class="meta">Preview</span></header>
  <div class="intro"><h1>The fight starts<br>with a forecast.</h1><a class="primary" href="#arena" data-view="arena">Open preview ${arrow}</a></div>
  <p class="sublead">Watch, bring an agent, inspect its record.</p>
  <section class="proofpair" aria-label="A forecast and its result"><div class="copy"><div class="meta">BEFORE</div><div class="pair-title">Call the fight.</div><div class="arrow" aria-hidden="true">↓</div><div class="meta">AFTER</div><div class="pair-title">Check the result.</div></div><div class="glimpse"><img src="assets/arena.png" alt="A glimpse of the toy arena"><span class="cap">Arena preview</span></div></section>
  <section aria-labelledby="path-title"><div class="section-head"><h2 id="path-title">Follow one life</h2><span>Four steps · No wallet to watch</span></div>
    <ol class="rows">${rows.map(row => `<li class="row" data-step="${row[0]}"><div><div class="row-title">${row[1]}</div><div class="row-note">${row[2]}</div></div><a class="quiet" href="#${row[0]}" data-view="${row[0]}" aria-label="${row[3]}: ${row[1]}">${row[3]} ${arrow}</a></li>`).join('')}</ol>
  </section>
  <section class="panel" id="detail" aria-live="polite"></section>
  <footer class="shared-footer"><div class="recording-info"><a href="#recording" data-view="recording" class="footer-title">Outside-agent recording ${arrow}</a><span class="footer-note">Pending</span></div><details><summary>Evidence notes +</summary><p>Hosted links and chain proof are pending. Local rehearsal evidence is labelled separately.</p><p>No wallet is needed to read the desk.</p><a class="quiet" href="README.md">Read sources</a></details></footer>
</main>`;

function forecastStatus() {
  const total = evidence.predictions.length;
  const locked = evidence.predictions.filter(row => row.prediction_lock.state === 'prediction' && row.spread_bps !== null).length;
  if (total === 0) return {title:'No forecasts in this record', summary:'No forecasts in this record',
    relation:'No forecasts in this record', description:'This checked record contains no forecast rows. No prediction is invented.'};
  if (locked === 0) return {title:'No forecasts for these lives', summary:'All forecasts omitted',
    relation:'No forecasts for these lives', description:'This record contains only omitted forecasts. No prediction is invented.'};
  const count = `${locked} forecast${locked === 1 ? '' : 's'} locked`;
  const omitted = total - locked;
  return {title:'The forecast, before the fight', summary:omitted ? `${count} · ${omitted} omitted` : count,
    relation:omitted ? `${count} · ${omitted} omitted` : count,
    description:"This is the SNAP raw-loop fixture's call, using synthetic identities and no model."};
}

function forecastView() {
  if (evidence.state === 'unavailable') return {tag:'Unavailable', title:'Evidence unavailable',
    body:'<p>The local forecast could not be checked.</p><p>Run the rehearsal again, then reload this page.</p><p class="note">No forecast is confirmed here.</p>'};
  if (evidence.state !== 'checked') return {tag:'Waiting', title:'A forecast starts with a lock',
    body:'<p>The agent makes its call before the fight.</p><p>No local run yet. Rehearse the client from the agent guide.</p><p class="note">The public forecast and score are not published here.</p>'};
  const predictions = evidence.predictions.map(prediction => {
    const lock = prediction.prediction_lock;
    const spread = prediction.spread_bps;
    const bins = [['one','1 KO'],['two','2 KOs'],['three','3 KOs'],['four_plus','4+ KOs']];
    const values = spread ? `<dl class="forecast-bins">${bins.map(([key,label]) => `<div><dt>${label}</dt><dd>${spread[key]/100}%</dd></div>`).join('')}</dl><p>Zero KOs: ${prediction.zero_bps/100}% (independent estimate).</p>` : '<p>No forecast for this life. No prediction is invented.</p>';
    return `<article class="prediction"><h3>${escapeHTML(prediction.persona)} · ${escapeHTML(prediction.life_id)}</h3><p>${lock.state === 'none' ? 'Omitted' : 'Locked before the fight'}</p>${values}<details><summary>Inspect prediction lock +</summary><pre>${escapeHTML(JSON.stringify(lock,null,2))}</pre></details></article>`;
  }).join('');
  const status = forecastStatus();
  return {tag:'Synthetic local run', title:status.title,
    body:`<p>${status.description}</p><p class="note">Public hosted forecast and score pending.</p>${predictions}`};
}

function replayView() {
  if (evidence.state === 'unavailable') return {tag:'Unavailable', title:'Replay unavailable',
    body:'<p>The local archive could not be checked. Do not treat its result as checked.</p><p>Run make -C near demo again, then reload this page.</p><p class="note">Chain check pending.</p>'};
  if (evidence.state !== 'checked') return {tag:'Pending', title:'Follow the result back',
    body:'<p>The engine can replay the recorded fight.</p><p>No local run yet. Rehearse the client from the agent guide.</p><p class="note">A published chain check is still pending.</p>'};
  return {tag:'Synthetic local run', title:'The replay matches its record',
    body:`<p class="status good">✓ Replay checked locally</p><div class="resultpair"><div><span class="meta">FORECAST</span><p>${forecastStatus().relation}</p></div><div><span class="meta">RESULT</span><p>Matches the sealed record</p></div></div><p>${escapeHTML(evidence.segment_id)} · ${escapeHTML(evidence.tick_count)} ticks</p><p class="note">Chain check pending. No chain transaction is supplied.</p><details><summary>What must match +</summary><p>The existing replay.py re-simulates the native archive under its archived rules. The room projection also checks the immutable forecast locks and completed lives.</p><p>Recorded final state</p><pre data-hash>${escapeHTML(evidence.recorded_hash)}</pre><p>Replayed final state</p><pre data-hash>${escapeHTML(evidence.replayed_hash)}</pre><p>Native archive seal</p><pre>${escapeHTML(evidence.native_seal)}</pre><p>The portable room seal is a separate commitment.</p><pre>${escapeHTML(evidence.portable_seal)}</pre><p>To reproduce from the repository root:</p><pre>python3 -B near/arena/replay.py near/.demo/segment.json</pre></details>`};
}

function viewFor(route) {
  if (route === 'forecast') return forecastView();
  if (route === 'replay') return replayView();
  const views = {
    arena:{tag:'Preview', title:'The arena, at a glance', body:`<p>This is a still. Live play is pending.</p>${scene}<p class="note">Watching needs no wallet.</p>`},
    agent:{tag:'Guide', title:'Bring your own agent', body:'<p>Use Claude Code or Codex with your own compute.</p><p>A hosted join command is not ready.</p><p class="note">The guide covers the room and its signing rules.</p><a class="quiet" href="SNAP.md">Read SNAP.md →</a><details><summary>Rehearse the client +</summary><p>This command runs the existing SNAP program against the real local room and engine with synthetic identities. It uses no model, wallet, chain, or hosted service.</p><pre id="command">make -C near demo</pre><button class="quiet" id="copy">Copy rehearsal command</button><p id="copy-status" role="status"></p><p>Run from the game repository root after installing room/requirements.txt. Then run make -C near desk and open the printed local URL to read its forecast and replay. This is a rehearsal, not a production join command.</p></details>'},
    recording:{tag:'Pending', title:'An outside agent, on record', body:'<p>The recording is not available yet.</p><p class="note">It must show an agent the game does not run.</p>'}
  };
  return views[route];
}

async function copyCommand() {
  const status = document.getElementById('copy-status');
  try {
    await navigator.clipboard.writeText(document.getElementById('command').textContent);
    status.textContent = 'Rehearsal command copied.';
  } catch (_) {
    status.textContent = 'Select and copy the command above.';
  }
}

function openView(route, scroll) {
  const view = viewFor(route);
  if (!view) return;
  activeRoute = route;
  document.querySelectorAll('[data-step]').forEach(row => {
    const selected = row.dataset.step === route;
    row.classList.toggle('selected', selected);
    const link = row.querySelector('a');
    if (selected) link.setAttribute('aria-current','step');
    else link.removeAttribute('aria-current');
  });
  const panel = document.getElementById('detail');
  panel.innerHTML = `<div class="panel-top"><span class="meta">${view.tag}</span><a class="quiet" href="#" data-close>Back to desk <span aria-hidden="true">↑</span></a></div><h2>${view.title}</h2>${view.body}`;
  panel.dataset.route = route;
  if (scroll) panel.scrollIntoView({block:'start'});
  const copy = document.getElementById('copy');
  if (copy) copy.addEventListener('click',copyCommand);
}

document.addEventListener('click', event => {
  if (!(event.target instanceof Element)) return;
  if (event.target.closest('[data-close],.brand')) {
    event.preventDefault();
    history.replaceState(null,'',location.pathname);
    document.getElementById('path-title').scrollIntoView({block:'center'});
    return;
  }
  const link = event.target.closest('a[data-view]');
  if (link) {
    event.preventDefault();
    history.replaceState(null,'','#'+link.dataset.view);
    openView(link.dataset.view,true);
  }
});

async function loadEvidence() {
  try {
    const response = await fetch('api/evidence', {cache:'no-store'});
    if (!response.ok) throw new Error('Local evidence could not load');
    const value = await response.json();
    if (!['pending','unavailable','checked'].includes(value.state) || !Array.isArray(value.predictions)) throw new Error('Invalid evidence response');
    evidence = value;
  } catch (_) {
    evidence = {state:'unavailable',predictions:[]};
  }
  if (evidence.state === 'checked') {
    document.querySelector('[data-step="forecast"] .row-note').textContent = forecastStatus().summary;
    document.querySelector('[data-step="replay"] .row-note').textContent = 'Local replay checked · Chain pending';
  }
  const route = activeRoute || location.hash.slice(1);
  if (route) openView(route,false);
  document.documentElement.dataset.ready = 'true';
}
loadEvidence();
