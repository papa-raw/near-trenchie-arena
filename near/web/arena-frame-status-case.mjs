import assert from 'node:assert/strict';
import { guardedFrame } from './arena/guard.mjs';
const scheduled = []; let status = 'Live', reports = 0;
const frame = guardedFrame(() => { throw new Error('bad draw'); }, (fn) => scheduled.push(fn), () => reports++, () => { status = 'Render error'; });
frame(1); assert.equal(status, 'Render error', 'throwing frame leaves Live visibly');
status = 'Live'; scheduled.shift()(2); assert.equal(status, 'Render error'); assert.equal(reports, 1); assert.equal(scheduled.length, 1);
process.stdout.write(JSON.stringify({ ok: true, status, consoleReports: reports, continued: true }) + '\n');
