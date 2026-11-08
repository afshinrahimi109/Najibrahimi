/*
 * تست رابط کاربری در محیط شبیه‌سازی‌شده‌ی مرورگر (jsdom)
 * ──────────────────────────────────────────────────────────────
 * دو «مرورگر» مستقل ساخته می‌شود، هر دو به سرور واقعی وصل می‌شوند،
 * WebRTC و میکروفون شبیه‌سازی می‌شوند و کل مسیر کاربر تست می‌شود:
 *   ساخت لینک → باز کردن لینک توسط نفر دوم → پیوستن → تماس برقرار
 *   و همچنین تماس با شماره‌ی ۶ رقمی → پاسخ → قطع
 *
 *   node test/browser.test.js
 */

import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';
import * as esbuild from 'esbuild';
import { JSDOM, VirtualConsole } from 'jsdom';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PORT = 8097;
const BASE = `http://127.0.0.1:${PORT}`;

let passed = 0;
const ok = (m) => { passed++; console.log(`  ✓ ${m}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitFor(fn, label, timeout = 8000) {
  const t0 = Date.now();
  for (;;) {
    try {
      const v = await fn();
      if (v) return v;
    } catch { /* هنوز آماده نیست */ }
    if (Date.now() - t0 > timeout) throw new Error(`تایم‌اوت: ${label}`);
    await sleep(50);
  }
}

/* ───────── شبیه‌سازی WebRTC و رسانه ───────── */

class FakeTrack {
  constructor(kind) {
    this.kind = kind;
    this.enabled = true;
    this.readyState = 'live';
    this.muted = false;
    this.id = Math.random().toString(36).slice(2);
    this.listeners = {};
  }
  stop() { this.readyState = 'ended'; }
  addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
  removeEventListener() {}
  dispatch(name) { (this.listeners[name] || []).forEach((f) => f()); }
}

class FakeStream {
  constructor() { this.tracks = []; }
  addTrack(t) { if (!this.tracks.includes(t)) this.tracks.push(t); }
  removeTrack(t) { this.tracks = this.tracks.filter((x) => x !== t); }
  getTracks() { return [...this.tracks]; }
  getAudioTracks() { return this.tracks.filter((t) => t.kind === 'audio'); }
  getVideoTracks() { return this.tracks.filter((t) => t.kind === 'video'); }
}

let sdpCounter = 0;

class FakePeerConnection {
  constructor(cfg = {}) {
    this.cfg = cfg;
    this.transceivers = [];
    this.connectionState = 'new';
    this.iceConnectionState = 'new';
    this.signalingState = 'stable';
    this.remoteDescription = null;
    this.localDescription = null;
  }
  addTransceiver(kindOrTrack, init = {}) {
    const kind = typeof kindOrTrack === 'string' ? kindOrTrack : kindOrTrack.kind;
    const tx = {
      kind,
      direction: init.direction || 'sendrecv',
      stopped: false,
      mid: null,
      sender: { track: typeof kindOrTrack === 'string' ? null : kindOrTrack, replaceTrack: async (t) => { tx.sender.track = t; } },
      receiver: { track: new FakeTrack(kind) },
    };
    this.transceivers.push(tx);
    return tx;
  }
  async createOffer() {
    sdpCounter += 1;
    return { type: 'offer', sdp: `v=0\r\no=- ${sdpCounter} 1 IN IP4 0.0.0.0\r\ns=-\r\nt=0 0\r\n` };
  }
  async createAnswer() {
    sdpCounter += 1;
    return { type: 'answer', sdp: `v=0\r\no=- ${sdpCounter} 1 IN IP4 0.0.0.0\r\ns=-\r\nt=0 0\r\n` };
  }
  async setLocalDescription(desc) {
    this.localDescription = desc;
    this.signalingState = desc.type === 'offer' ? 'have-local-offer' : 'stable';
    if (desc.type === 'answer') setTimeout(() => this.setConnectionState('connected'), 30);
  }
  async setRemoteDescription(desc) {
    this.remoteDescription = desc;
    if (desc.type === 'offer') {
      this.signalingState = 'have-remote-offer';
      if (!this.transceivers.length) {
        this.addTransceiver('audio', { direction: 'sendrecv' });
        this.addTransceiver('video', { direction: 'sendrecv' });
      }
      setTimeout(() => {
        for (const tx of this.transceivers) this.ontrack?.({ track: tx.receiver.track, streams: [] });
      }, 5);
    } else {
      this.signalingState = 'stable';
      setTimeout(() => this.setConnectionState('connected'), 30);
    }
  }
  setConnectionState(state) {
    if (this.connectionState === state) return;
    this.connectionState = state;
    this.iceConnectionState = state === 'connected' ? 'connected' : 'failed';
    this.onconnectionstatechange?.();
    this.oniceconnectionstatechange?.();
  }
  getTransceivers() { return this.transceivers; }
  getSenders() { return this.transceivers.map((t) => t.sender); }
  addIceCandidate() { return Promise.resolve(); }
  restartIce() {}
  close() { this.connectionState = 'closed'; }
  async getStats() {
    const m = new Map();
    m.set('pair', { type: 'candidate-pair', selected: true, state: 'succeeded', currentRoundTripTime: 0.042, localCandidateId: 'l', remoteCandidateId: 'r' });
    m.set('l', { type: 'local-candidate', candidateType: 'srflx' });
    m.set('r', { type: 'remote-candidate', candidateType: 'srflx' });
    m.set('in', { id: 'in', type: 'inbound-rtp', kind: 'audio', bytesReceived: 4000, packetsReceived: 120, packetsLost: 1, jitter: 0.012, codecId: 'c1' });
    m.set('out', { id: 'out', type: 'outbound-rtp', kind: 'audio', bytesSent: 3800 });
    m.set('c1', { id: 'c1', type: 'codec', mimeType: 'audio/opus' });
    return m;
  }
}

class FakeAudioContext {
  constructor() {
    this.state = 'running';
    this.currentTime = 0;
    this.destination = {};
    this.sampleRate = 48000;
  }
  resume() { this.state = 'running'; return Promise.resolve(); }
  close() { return Promise.resolve(); }
  createAnalyser() {
    return { fftSize: 512, getByteTimeDomainData: (arr) => arr.fill(128) };
  }
  createMediaStreamSource() { return { connect() {} }; }
  createGain() { return { gain: { value: 0, setValueAtTime() {}, linearRampToValueAtTime() {} }, connect() {} }; }
  createOscillator() { return { type: 'sine', frequency: { value: 440 }, connect() {}, start() {}, stop() {} }; }
}

/* ───────── ساخت یک «مرورگر» ───────── */

const bundle = await esbuild.build({
  entryPoints: [path.join(ROOT, 'public/js/app.js')],
  bundle: true,
  format: 'iife',
  write: false,
  target: 'es2020',
  logLevel: 'silent',
});
const appCode = bundle.outputFiles[0].text;
const html = readFileSync(path.join(ROOT, 'public/index.html'), 'utf8');

function makeBrowser({ url, name }) {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on('jsdomError', (e) => errors.push(e.message));

  const dom = new JSDOM(html, { url, runScripts: 'outside-only', pretendToBeVisual: true, virtualConsole: vc });
  const win = dom.window;
  win.addEventListener('error', (e) => errors.push(e.message || String(e.error)));
  win.addEventListener('unhandledrejection', (e) => errors.push(String(e.reason)));

  // رسانه و WebRTC شبیه‌سازی‌شده
  win.MediaStream = FakeStream;
  win.RTCPeerConnection = FakePeerConnection;
  win.AudioContext = FakeAudioContext;
  win.webkitAudioContext = FakeAudioContext;
  win.isSecureContext = true;
  Object.defineProperty(win.HTMLMediaElement.prototype, 'srcObject', {
    configurable: true,
    get() { return this._srcObject || null; },
    set(v) { this._srcObject = v; },
  });
  win.HTMLMediaElement.prototype.play = function play() { return Promise.resolve(); };
  win.HTMLMediaElement.prototype.pause = function pause() {};

  Object.defineProperty(win.navigator, 'mediaDevices', {
    configurable: true,
    value: {
      async getUserMedia(constraints = {}) {
        const stream = new FakeStream();
        if (constraints.audio) stream.addTrack(new FakeTrack('audio'));
        if (constraints.video) stream.addTrack(new FakeTrack('video'));
        return stream;
      },
      async enumerateDevices() {
        return [
          { kind: 'audioinput', deviceId: 'mic1', label: 'میکروفون تست' },
          { kind: 'videoinput', deviceId: 'cam1', label: 'دوربین تست' },
        ];
      },
    },
  });
  Object.defineProperty(win.navigator, 'vibrate', { configurable: true, value: () => true });
  win.fetch = (input, init) => fetch(new URL(input, BASE).toString(), init);

  win.eval(appCode);

  return {
    win,
    errors,
    name,
    q: (sel) => win.document.querySelector(sel),
    click: (sel) => {
      const node = typeof sel === 'string' ? win.document.querySelector(sel) : sel;
      assert.ok(node, `دکمه پیدا نشد: ${sel}`);
      node.dispatchEvent(new win.MouseEvent('click', { bubbles: true }));
      return node;
    },
    text: (sel) => (win.document.querySelector(sel)?.textContent || '').trim(),
    visible: (sel) => {
      const n = win.document.querySelector(sel);
      return Boolean(n && !n.hidden);
    },
    callState: () => win.document.querySelector('#callScreen').dataset.state,
    tray: () => win.document.querySelector('#toast').textContent,
  };
}

/* ───────── اجرای سرور ───────── */

const server = spawn(process.execPath, ['server.js'], {
  cwd: ROOT,
  env: { ...process.env, PORT: String(PORT), CALL_CODE: '' },
  stdio: ['ignore', 'pipe', 'pipe'],
});
let serverLog = '';
server.stdout.on('data', (d) => { serverLog += d; });
server.stderr.on('data', (d) => { serverLog += d; });
const cleanup = () => { try { server.kill('SIGKILL'); } catch { /* noop */ } };
process.on('exit', cleanup);

try {
  for (let i = 0; i < 80; i++) {
    try { if ((await fetch(`${BASE}/api/health`)).ok) break; } catch { /* صبر */ }
    await sleep(100);
  }

  /* ── مرورگر اول ── */
  const A = makeBrowser({ url: `${BASE}/`, name: 'A' });
  const idA = await waitFor(() => (/^[۰-۹]{3}/.test(A.text('#myId')) ? A.text('#myId') : null), 'شماره‌ی الف');
  ok(`مرورگر اول وصل شد و شماره گرفت (${idA})`);
  await waitFor(() => A.q('#connPill').className.includes('pill-ok'), 'سبز شدن نشانگر اتصال');
  ok('نشانگر اتصال «آنلاین» شد');

  /* ── شماره‌گیر: نمایش زنده‌ی شماره ── */
  ['5', '5', '5', '1', '2', '3'].forEach((k) => {
    A.click(A.q(`#dialpad [data-k="${k}"]`));
  });
  assert.ok(A.text('#dialDigits').length >= 6);
  ok('شماره‌گیر رقم‌ها را نشان می‌دهد');

  /* ── ساخت لینک تماس ── */
  A.click('#btnNewLink');
  await waitFor(() => A.q('#linkBox') && !A.q('#linkBox').hidden, 'نمایش لینک');
  const link = A.q('#linkInput').value;
  assert.match(link, /\?c=[a-z0-9]{6,}/);
  ok('لینک تماس ساخته شد');

  /* ── نفر دوم لینک را باز می‌کند ── */
  const B = makeBrowser({ url: link, name: 'B' });
  await waitFor(() => B.callState() === 'incoming', 'صفحه‌ی دعوت در مرورگر دوم');
  assert.ok(B.text('#callName').includes('دعوت'));
  ok('مرورگر دوم صفحه‌ی «دعوت به تماس» را دید');

  B.click('[data-act="accept"]');
  await waitFor(() => A.callState() === 'active' && B.callState() === 'active', 'اتصال هر دو طرف', 12000);
  ok('تماس لینکی برقرار شد و هر دو طرف «در حال گفتگو» شدند');

  await waitFor(() => A.q('#callTimer').textContent !== '00:00', 'شمارنده‌ی زمان', 4000);
  ok('شمارنده‌ی مدت تماس کار می‌کند');

  assert.ok(A.text('#callName').length > 0 && B.text('#callName').length > 0);
  ok(`نام طرف مقابل نمایش داده شد (${B.text('#callName')})`);

  /* ── بی‌صدا و دوربین ── */
  A.click('[data-act="mute"]');
  assert.ok(A.q('[data-act="mute"]').classList.contains('off'));
  A.click('[data-act="mute"]');
  assert.ok(!A.q('[data-act="mute"]').classList.contains('off'));
  ok('دکمه‌ی بی‌صدا درست کار می‌کند');

  A.click('[data-act="camera"]');
  await waitFor(() => !A.q('#localVideo').hidden, 'روشن شدن دوربین');
  ok('دوربین در میانه‌ی تماس روشن شد (بدون قطع تماس)');

  /* ── جزئیات فنی ── */
  A.click('[data-act="stats"]');
  await waitFor(() => A.q('#statsPanel').textContent.includes('opus'), 'آمار کدک');
  ok('پنل جزئیات، کدک و کیفیت را نشان می‌دهد');

  /* ── قطع تماس ── */
  A.click('[data-act="hangup"]');
  await waitFor(() => A.callState() === 'idle' && B.callState() === 'idle', 'پایان تماس');
  ok('قطع تماس هر دو طرف را به حالت اول برگرداند');

  await waitFor(() => B.q('#recentCard') && !B.q('#recentCard').hidden, 'تاریخچه');
  ok('تماس در «تماس‌های اخیر» ثبت شد');

  /* ── تماس با شماره‌ی ۶ رقمی ── */
  const idB = B.text('#myId').replace(/\s/g, '');
  await waitFor(() => A.q('#onlineList').children.length > 0, 'لیست آنلاین‌ها');
  const dialA = makeBrowser({ url: `${BASE}/`, name: 'C' });
  await waitFor(() => /^[۰-۹]{3}/.test(dialA.text('#myId')), 'شماره‌ی C');

  // C شماره‌ی B را می‌گیرد (ارقام فارسی → لاتین)
  const latinB = idB.replace(/[۰-۹]/g, (d) => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d)));
  for (const ch of latinB) dialA.click(dialA.q(`#dialpad [data-k="${ch}"]`));
  await waitFor(() => dialA.text('#dialHint').includes('آنلاین'), 'تشخیص آنلاین بودن در شماره‌گیر');
  ok('شماره‌گیر تشخیص می‌دهد طرف مقابل آنلاین است');

  dialA.click('#btnDial');
  await waitFor(() => B.callState() === 'incoming', 'زنگ در مرورگر B');
  ok('تماس با شماره باعث زنگ خوردن طرف مقابل شد');

  B.click('[data-act="accept"]');
  await waitFor(() => dialA.callState() === 'active' && B.callState() === 'active', 'اتصال تماس شماره‌ای', 12000);
  ok('تماس شماره‌ای (۶ رقمی) برقرار شد');

  dialA.click('[data-act="hangup"]');
  await waitFor(() => dialA.callState() === 'idle' && B.callState() === 'idle', 'پایان تماس شماره‌ای');
  ok('تماس شماره‌ای درست قطع شد');

  /* ── بدون خطای جاوااسکریپت ── */
  for (const b of [A, B, dialA]) {
    const real = b.errors.filter((e) => e && !/Not implemented|Could not parse CSS/.test(e));
    assert.equal(real.length, 0, `خطای جاوااسکریپت در ${b.name}: ${real.join(' | ')}`);
  }
  ok('هیچ خطای جاوااسکریپتی در طول کل جریان ثبت نشد');

  console.log(`\n  ✅ همه‌ی ${passed} تست مرورگری موفق بود\n`);
  cleanup();
  process.exit(0);
} catch (err) {
  console.error('\n  ❌ تست مرورگری شکست خورد:', err.message);
  if (serverLog) console.error('\n  --- سرور ---\n' + serverLog.slice(-1500));
  cleanup();
  process.exit(1);
}
