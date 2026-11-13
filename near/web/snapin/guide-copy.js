/* snapin/guide-copy.js: every string of the snap-in guide as drawn on board 1, in one place. guide.js reads only from here,
 * so the words on screen are the board's words. {name}-style holes are filled with the player's own data, never samples.
 * A classic script; window.SnapGuideCopy. */
(function (root) {
  'use strict';
  var C = {
    eyebrow: 'Snap in · step {n} of 5',
    steps: ['Wallet', 'Fighter', 'Personality', 'AI', 'Snap in'],
    back: '← Back', keepWatching: 'Keep watching', close: 'Close',
    wallet: { title: 'Connect a NEAR wallet', line: 'Your wallet owns your Trenchie, a NEAR NFT. Its fights and gear are on testnet.',
      // the right column is the host's identity network (TESTNET in the rehearsal, MAINNET after the deploy), filled in by
      // guide.js; the throwaway account is not offered in chain mode (it cannot own the NFT)
      rows: [['choose', 'Connect wallet', '{network}'], ['dev-throwaway', 'Throwaway account', 'NO WALLET']],
      connected: 'Connected: {wallet}', other: 'Use another wallet', none: 'No wallet yet?', get: 'Find a wallet ↗', getUrl: 'https://wallet.near.org/',
      next: 'Next: fighter', needs: 'Connect a wallet' },
    fighter: { title: 'Pick your fighter', line: 'Five starter fighters. Free on testnet.', kit: 'Its starter kit', move: 'Weapon move', sig: 'Signature',
      use: 'Use this preset', build: 'Build a fighter',
      // what each move and signature does, in the board's words (Swing and Shockwave are drawn; the rest follow them)
      moves: { Swing: 'Swing: hits every foe in an arc in front of you.', Lunge: 'Lunge: dashes to the target and hits on arrival.', Beam: 'Beam: winds up, then hits along a line.',
               Lob: 'Lob: drops a burst into a marked circle.', Zap: 'Zap: hits one foe, then jumps to others.' },
      sigs: { Shockwave: 'Shockwave: a ring blast around you. It fires when a foe is close, or when your HP is low.' } },
    persona: { title: 'Name and personality', name: 'Name', free: '✓ Free', fixed: 'This Trenchie’s name and personality were fixed when it was minted. You can still choose its AI and change how it fights.', taken: '{taken} is in the ring, so we picked another name.',
      inRing: '✗ {name} is in the ring now. Pick another name.', temper: 'Temperament', quirks: 'Quirks', quirksMax: 'up to 2', next: 'Next: AI' },
    doors: { title: 'Choose its AI', line: 'Your Trenchie fights with your AI. You choose; there is no default.',
      keyGroup: 'API key, in this browser', planGroup: 'Your plan, through your own agent session',
      key: [['NEAR AI Cloud', 'KEY'], ['Claude', 'KEY'], ['Codex', 'KEY'], ['OpenRouter', 'KEY']],
      plan: [['Claude Code', 'PLAN'], ['Codex', 'PLAN']] },
    key: {
      other: 'Other AIs', getH: 'Get a key', pasteH: 'Paste it', field: 'API key', placeholder: 'Paste your key', test: 'Test',
      testing: 'Asking the provider…', ok: '✓ It answered: “{answer}”', wrong: '✗ The provider refused this key. Copy it again, all of it.',
      noCredits: '✗ The key works, but the account has no credits. Add credits, then test again.',
      cap: 'Hourly cap', caps: ['$0.10', '$0.20', '$0.50'], capOther: '$ other',
      capRule: 'At the cap, your Trenchie fights on its own tactics until the hour ends.',
      keyNote: 'Your key stays in this browser and goes only to the provider.',
      next: 'Next: check', needsBoth: 'Test your key and pick a cap', needsTest: 'Test your key', needsCap: 'Pick a cap',
      providers: {
        'NEAR AI Cloud': { title: 'NEAR AI Cloud key', open: 'Open the key page ↗', url: 'https://cloud.near.ai/signin',
          how: ['Sign in.', 'Add credits. $1 is enough to start.', 'Create a key and set its limit to $1.', 'Paste it here.'],
          cost: 'About $0.10 an hour in a busy fight.' },
        'Claude': { title: 'Claude API key', open: 'Open the Claude Console ↗', url: 'https://platform.claude.com/settings/keys',
          how: ['Sign in to the Claude Console.', 'Add credits under Billing.', 'Create a key under API keys. Set a spend limit under Limits.', 'Paste it here.'],
          cost: 'Not measured yet for this AI. Start with a low cap.' },
        'Codex': { title: 'Codex API key', open: 'Open the OpenAI platform ↗', url: 'https://platform.openai.com/api-keys',
          how: ['Sign in to the OpenAI platform.', 'Add credits under Billing.', 'Create a key under API keys. Set a budget under Limits.', 'Paste it here.'],
          cost: 'Not measured yet for this AI. Start with a low cap.' },
        'OpenRouter': { title: 'OpenRouter key', open: 'Open OpenRouter ↗', url: 'https://openrouter.ai/settings/keys',
          how: ['Sign in to OpenRouter.', 'Add credits.', 'Create a key and give it a credit limit.', 'Paste it here.'],
          cost: 'Not measured yet for this AI. Start with a low cap.' } } },
    plan: {
      'Claude Code': { title: 'Claude Code, on your plan', bin: 'claude', perms: 'Claude Code', planName: 'Claude', agent: 'claude-code' },
      'Codex': { title: 'Codex, on your plan', bin: 'codex -c sandbox_workspace_write.network_access=true', perms: 'Codex', planName: 'ChatGPT', agent: 'codex',
        download: ' Download the current client from the same site’s /snap-client.zip into a fresh folder first; do not use a local checkout.',
        networkNote: 'This lets Codex reach the internet so it can play. Run it in an empty folder.' },
      line: 'Your own {agent} session plays your Trenchie. It uses your {plan} plan, not a key.',
      copyH: 'Copy this line.', copy: 'Copy', copied: 'Copied',
      command: '{bin} "Join Trenchie Arena. Read {snap} and follow it.{download} Code {code}, Trenchie {name}."',
      paste: 'Paste it into a terminal, in an empty folder.', keepOpen: 'Keep this page open.',
      waiting: 'Waiting for your session · the code ends in {left}', joined: '✓ Your {agent} session joined.',
      expired: '✗ The code ran out before your session joined.', newCode: 'Get a new code', asking: 'Asking the arena for a code…',
      runsH: 'Where it runs', runs: 'Your session runs on your computer, under your {perms} permissions. It plays this Trenchie by sending orders to the arena.',
      limitH: 'Weekly limit', limits: ['5%', '10%', '20%'],
      limitRule: 'Your session’s own stop: it stops giving orders at this share of your plan’s week.',
      limitUnknown: 'If your session can’t report its use, the panel says “not reported”.',
      next: 'Next: check', needsJoin: 'Waiting for your session' },
    check: { title: 'Check your Trenchie', change: 'Change', setIt: 'Set it', notSet: 'Not set', answered: 'answered', joined: 'joined',
      rows: { wallet: 'Wallet', fighter: 'Fighter', name: 'Name', personality: 'Personality', ai: 'AI', cap: 'Hourly cap', stop: 'Weekly limit' },
      rulesH: 'Arena rules', orders: 'Orders', ordersV: 'one every {s} s', rounds: 'Rounds', roundsV: '{s} s, replayable',
      gear: 'Gear', gearV: 'A KO drops one item. A rival can grab it; ungrabbed for 30 s, it is gone.',
      notice: 'This is a testnet game. Your Trenchie’s name and lines are public. Your AI key stays in your browser and only goes to your AI provider.',
      snap: 'Snap in', needsCap: 'Needs an hourly cap', needsAI: 'Needs an AI', needsName: 'Needs a name', needsWallet: 'Needs a wallet', needsRules: 'Reading the arena rules…',
      joining: 'Snapping in…' }
  };
  // the trenchie panel on the arena page (board 1's fight, thinking, changecap, capped, bench, agent and closed states)
  C.panel = {
    life: 'Life {life} · {source}', session: '{agent} session', hp: 'HP', leave: 'Leave', leaving: '{name} is swimming home…', leaveFailed: 'Could not leave: {why}. Try Leave again.', leaveAgent: 'Ask your agent to leave the arena from its session.', close: 'Close panel',
    states: { fight: 'Fighting', thinking: 'Thinking…', bench: 'Bench · held', benchDown: 'Bench', capped: 'Own tactics' },
    gearH: 'Equipped', bag: 'Bag · {n}', bagHint: 'Swap on the bench.', slots: { head: 'Head', body: 'Body', weapon: 'Weapon', trinket: 'Trinket' },
    money: { hour: 'This hour {spent} of your {cap} cap', visit: 'This visit {visit}', rate: 'About $0.10 an hour', change: 'Change cap', resets: 'Resets at {time}', set: 'Set cap', caps: ['$0.10', '$0.20', '$0.50', '$1.00'] },
    plan: { reports: 'Plan this week: {pct}% of your {stop}% stop', from: 'from your session', unknown: 'Plan use this week: not reported by your {agent} session', stop: 'Its own stop: {stop}%' },
    order: { placeholder: 'Tell {short} what to do', hint: 'One order every 0.5 s', sent: 'Sent. One order every 0.5 s.', send: 'Send',
      noDoor: 'No AI door picked: {link} to give orders.', pickDoor: 'Pick an AI door' },   // not drawn on the sheet: chat.js's words for a trenchie with no AI door
    capped: { box: 'Cap reached. {short} fights on its own tactics until {time}.', raise: 'Raise cap' },
    agent: { box: 'Orders come from your {agent} session. Type them there; replies show here.', from: 'From your session', joined: 'Your {agent} session joined. Life {life}.' },
    joined: 'Snapped in. Life {life} on {door}.',
    bench: { h: 'On the bench', next: 'Next: life {n}', hold: 'Stay on the bench', held: 'The 45 s timer is stopped. {short} waits until you send it back in.',
      down: 'Back in the ring in {s} s.', tap: 'Tap an item to swap', only: 'Gear changes only on the bench.', send: 'Send back in' },
    thinking: '{short} is thinking… {s} s',
    receiptH: 'BEHAVIOUR SET', applied: 'applied {t} s after Send', why: 'Why: ',
    tab: { open: 'Open' }
  };
  C.fill = function (s, v) { return String(s).replace(/\{(\w+)\}/g, function (m, k) { return v && v[k] != null ? v[k] : m; }); };
  root.SnapGuideCopy = C;
  if (typeof module !== 'undefined') module.exports = C;
})(typeof globalThis !== 'undefined' ? globalThis : this);
