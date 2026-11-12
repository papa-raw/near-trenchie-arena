// window.ArenaView: the page's own panel follows a fighter without a click on the ring (board 1's Follow button).
// follow(id) opens the follow view on it now if it is in the ring, else waits until it is (a KO'd or held trenchie comes
// back later); it never toggles off, unlike a second click on the same body. unfollow() closes it; followed() names the
// fighter followed now (null when none). Each change is announced as an 'arenaview:follow' event with {id}.
export function arenaView({ inset, hud, positions, every = 400, setTimer = setInterval, clearTimer = clearInterval, announce }) {
  let waiting = null, wanted = null;
  const say = () => { if (announce) announce(inset.followId); };
  const stopWaiting = () => { if (waiting !== null) clearTimer(waiting); waiting = null; wanted = null; };
  const inRing = (id) => { const p = positions().get(id); return !!(p && p.state === 'alive'); };
  const show = (id) => { if (inset.followId !== id) inset.follow(id); hud.followed = inset.followId; say(); };
  const api = {
    follow(id) {
      stopWaiting();
      if (typeof id !== 'string' || !id) return false;
      if (inRing(id)) { show(id); return true; }
      wanted = id;
      waiting = setTimer(() => { if (wanted !== null && inRing(wanted)) { const w = wanted; stopWaiting(); show(w); } }, every);
      return false;
    },
    unfollow() { stopWaiting(); inset.clear(); hud.followed = null; say(); },
    followed() { return inset.followId; },
    waitingFor() { return wanted; },
    // the ring was clicked or the close mark used: a pending follow is dropped, the page hears the new state
    clicked() { stopWaiting(); hud.followed = inset.followId; say(); },
  };
  return api;
}
