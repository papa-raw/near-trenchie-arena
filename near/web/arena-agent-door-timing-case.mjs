import assert from 'node:assert/strict';
import { chooseFocus, retargetResult } from './arena-agent-door-timing.mjs';

const snapshot = { fighters: [
  { id: 'dev-shoal', status: 0, x: 0, y: 0 },
  { id: 'far', status: 0, x: 24000, y: 0 },
  { id: 'current', status: 0, x: 100, y: 0 },
  { id: 'near', status: 0, x: 1000, y: 0 },
] };
assert.equal(chooseFocus(snapshot, 'dev-shoal', 'current', 12000), 'near', 'the ordered enemy must be in view');
assert.equal(chooseFocus(snapshot, 'dev-shoal', ['current', 'near'], 12000), null,
  'the rendered target and current native target are both excluded');
assert.equal(chooseFocus(snapshot, 'absent', 'current', 12000), null, 'wait while the owner is not alive in the snapshot');
const slow = retargetResult({ appliedTick: 100, switchedTick: 130, commandStartedMs: 0, frameArrivedMs: 5000, visibleMs: 5200 });
assert.equal(slow.within, true, 'CLI startup and honest sim slow motion do not consume the 40-tick engine budget');
assert.equal(slow.focusTicks, 30);
assert.equal(slow.renderLatencyMs, 200);
assert.equal(retargetResult({ appliedTick: 100, switchedTick: 141, commandStartedMs: 0, frameArrivedMs: 100, visibleMs: 200 }).within,
  false, 'an engine miss cannot pass because the fixture advances fast');
assert.equal(retargetResult({ appliedTick: 100, switchedTick: 110, commandStartedMs: 0, frameArrivedMs: 3000, visibleMs: 5001 }).within,
  false, 'rendering still has its own two-second delivery bound');
process.stdout.write(JSON.stringify({ ok: true, checks: 8 }) + '\n');
