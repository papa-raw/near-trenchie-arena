// Timing and eligibility used by the real agent-door browser case.
export function chooseFocus(snapshot, fighterId, current, viewRadius) {
  const own = snapshot.fighters.find((f) => f.id === fighterId && f.status === 0);
  if (!own) return null;
  const excluded = new Set(Array.isArray(current) ? current : [current]);
  // Choose a close enemy, leaving room for movement while the CLI starts.
  return snapshot.fighters.filter((f) => f.id !== fighterId && !excluded.has(f.id) && f.status === 0)
    .map((f) => ({ id: f.id, distance: Math.hypot(f.x - own.x, f.y - own.y) }))
    .filter((f) => f.distance <= viewRadius / 2).sort((a, b) => a.distance - b.distance)[0]?.id || null;
}

export function retargetResult({ appliedTick, switchedTick, commandStartedMs, frameArrivedMs, visibleMs }) {
  // The engine contract is40 ticks AFTER apply (test_focus.py); rendering has
  // a separate wall-clock delivery bound. Python startup belongs to neither.
  const focusTicks = switchedTick - appliedTick;
  const renderLatencyMs = Math.max(0, visibleMs - frameArrivedMs);
  return { within: focusTicks >= 0 && focusTicks <= 40 && renderLatencyMs <= 2000,
    focusTicks, renderLatencyMs, commandToVisibleMs: visibleMs - commandStartedMs };
}
