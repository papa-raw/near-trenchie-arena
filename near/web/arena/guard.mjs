/** Schedule the next frame even when one malformed render update fails. Report each message once. */
export function guardedFrame(draw, schedule = requestAnimationFrame, report = console.error, onError = () => {}) {
  const reported = new Set();
  function frame(now) {
    try { draw(now); }
    catch (error) { onError(error); const key = error?.message || String(error); if (!reported.has(key)) { reported.add(key); report(error); } }
    finally { schedule(frame); }
  }
  return frame;
}
