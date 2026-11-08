/*
 * لایه‌ی سیگنالینگ
 * ────────────────────────────────────────────────────────────
 * مسیر اصلی: WebSocket  (/ws)
 * مسیر پشتیبان: SSE + POST  (برای شبکه‌هایی مثل بعضی پروکسی‌های شرکتی/اپراتور
 * که WebSocket را می‌بندند ولی HTTPS معمولی را رد می‌کنند)
 *
 * هر دو مسیر همان پروتکل JSON را منتقل می‌کنند، بنابراین بقیه‌ی برنامه
 * تفاوتی بین آن‌ها نمی‌بیند.
 */

export class SignalClient {
  constructor({ cid, onMessage, onState }) {
    this.cid = cid;
    this.onMessage = onMessage || (() => {});
    this.onState = onState || (() => {});
    this.mode = null;          // 'ws' | 'sse'
    this.ws = null;
    this.es = null;
    this.open = false;
    this.manual = false;
    this.retry = 0;
    this.wsFailures = 0;
    this.timer = null;
    this.pingTimer = null;
    this.state = 'idle';
  }

  connect() {
    this.manual = false;
    if (this.state === 'connecting' || this.state === 'open') return;
    if (this.mode === 'sse') return this.connectSSE();
    return this.connectWS();
  }

  setState(s) {
    if (this.state === s) return;
    this.state = s;
    this.onState(s);
  }

  scheduleRetry(fn, delay) {
    clearTimeout(this.timer);
    this.timer = setTimeout(fn, delay);
  }

  /* ── WebSocket ── */
  connectWS() {
    this.setState('connecting');
    let ws;
    try {
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      ws = new WebSocket(`${proto}//${location.host}/ws`);
    } catch {
      return this.fallbackToSSE();
    }
    this.ws = ws;

    const bail = setTimeout(() => {
      if (ws.readyState !== 1) {
        try { ws.close(); } catch { /* noop */ }
      }
    }, 5000);

    ws.onopen = () => {
      clearTimeout(bail);
      this.mode = 'ws';
      this.open = true;
      this.wsFailures = 0;
      this.retry = 0;
      this.setState('open');
      this.startPing();
    };

    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      this.onMessage(msg);
    };

    ws.onerror = () => { /* close هوشمندتر است */ };

    ws.onclose = () => {
      clearTimeout(bail);
      this.open = false;
      this.stopPing();
      if (this.manual) return this.setState('closed');
      this.wsFailures += 1;
      // اگر WebSocket پشت این شبکه کار نمی‌کند، به SSE سوییچ می‌کنیم
      if (this.wsFailures >= 2 || this.mode === null) return this.fallbackToSSE();
      this.setState('closed');
      const delay = Math.min(8000, 700 * 2 ** this.retry++);
      this.scheduleRetry(() => this.connectWS(), delay);
    };
  }

  fallbackToSSE() {
    this.mode = 'sse';
    this.connectSSE();
  }

  /* ── SSE + POST ── */
  connectSSE() {
    this.setState('connecting');
    try { this.es?.close(); } catch { /* noop */ }
    const es = new EventSource(`/api/events?cid=${encodeURIComponent(this.cid)}`);
    this.es = es;

    es.onopen = () => {
      this.open = true;
      this.retry = 0;
      this.setState('open');
      this.startPing();
    };
    es.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      this.onMessage(msg);
    };
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) {
        this.open = false;
        this.stopPing();
        if (this.manual) return this.setState('closed');
        this.setState('closed');
        const delay = Math.min(8000, 900 * 2 ** this.retry++);
        this.scheduleRetry(() => this.connectSSE(), delay);
      } else {
        this.setState('closed');
      }
    };
  }

  startPing() {
    this.stopPing();
    this.pingTimer = setInterval(() => this.send({ t: 'ping' }), 25_000);
  }
  stopPing() {
    clearInterval(this.pingTimer);
    this.pingTimer = null;
  }

  send(msg) {
    if (this.mode === 'sse') {
      fetch('/api/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cid: this.cid, msg }),
        keepalive: true,
      }).catch(() => {});
      return true;
    }
    if (this.ws && this.ws.readyState === 1) {
      try { this.ws.send(JSON.stringify(msg)); return true; } catch { return false; }
    }
    return false;
  }

  close() {
    this.manual = true;
    this.stopPing();
    clearTimeout(this.timer);
    this.open = false;
    try { this.ws?.close(); } catch { /* noop */ }
    try { this.es?.close(); } catch { /* noop */ }
    this.setState('closed');
  }
}
