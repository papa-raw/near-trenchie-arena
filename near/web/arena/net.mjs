// The spectator socket: one text frame per server tick, never any input from us. Reconnects with backoff and says what state
// it is in (gate 6: no silent fallback). The frame decoder is arena/codec.mjs.
import { decode } from './codec.mjs';
import { StyleState } from './style.mjs';

export class Net {
  constructor(url, { onSnapshot, onStatus, onStyles = () => {}, onMetadata = () => {}, onSocial = () => {} }) {
    this.onSocial = onSocial; this.onMetadata = onMetadata; this.styles = new StyleState(); this.onStyles = onStyles;
    this.url = url; this.onSnapshot = onSnapshot; this.onStatus = onStatus;
    this.ws = null; this.tries = 0; this.frames = 0; this.bytes = 0; this.bad = 0; this.closed = false;
    this.connect();
  }
  connect() {
    if (this.closed) return;
    this.onStatus({ state: 'connecting', url: this.url, tries: this.tries });
    let ws;
    try { const url = new URL(this.url); url.searchParams.set("styles", "1"); ws = new WebSocket(url.href); } catch (e) { this.onStatus({ state: 'error', url: this.url, message: String(e) }); this.retry(); return; }
    this.ws = ws;
    ws.onopen = () => { this.tries = 0; this.onStatus({ state: 'live', url: this.url }); };
    ws.onmessage = (m) => {
      const text = typeof m.data === 'string' ? m.data : null;
      if (text === null) { this.bad++; return; }
      this.bytes += text.length; this.frames++;
      let snap;
      try {
        const value = JSON.parse(text);
        if (value?.type === 'spectator_social') { this.onSocial(value); return; }
        if (value?.type === 'spectator_styles') {
          const next = new StyleState(); next.map = this.styles.map; next.revision = this.styles.revision;
          next.apply(value); this.onMetadata(value); this.styles = next; this.onStyles(this.styles.map); return;
        }
        snap = decode(value);
      } catch (e) { this.bad++; this.onStatus({ state: 'bad-frame', url: this.url, message: String(e.message || e) }); return; }
      this.onSnapshot(snap);
    };
    ws.onclose = () => { this.onSocial(null); this.onMetadata(null); this.styles = new StyleState(); this.onStyles(this.styles.map); if (!this.closed) { this.onStatus({ state: 'closed', url: this.url }); this.retry(); } };
    ws.onerror = () => {};
  }
  retry() { this.tries++; setTimeout(() => this.connect(), Math.min(5000, 400 * 2 ** Math.min(this.tries, 4))); }
  close() { this.closed = true; if (this.ws) this.ws.close(); }
}
