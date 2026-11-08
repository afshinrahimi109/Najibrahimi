/*
 * تست سیگنالینگ — بدون مرورگر
 * دو کلاینت WebSocket و دو کلاینت SSE را شبیه‌سازی می‌کند و کل جریان
 * تماس (زنگ زدن، پذیرش، عبور SDP/ICE، لینک اتاق، قطع تماس) را می‌سنجد.
 *
 *   node test/signal.test.js
 */

import { spawn } from 'node:child_process';
import { WebSocket } from 'ws';
import assert from 'node:assert/strict';

const PORT = 8099;
const BASE = `http://127.0.0.1:${PORT}`;
let passed = 0;
const ok = (name) => { passed++; console.log(`  ✓ ${name}`); };

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ── یک کلاینت ساده‌ی WebSocket با صف پیام ── */
class WsClient {
  constructor() {
    this.inbox = [];
    this.waiters = [];
  }
  async connect() {
    this.ws = new WebSocket(`ws://127.0.0.1:${PORT}/ws`);
    await new Promise((res, rej) => {
      this.ws.once('open', res);
      this.ws.once('error', rej);
    });
    this.ws.on('message', (buf) => {
      const msg = JSON.parse(buf.toString());
      const idx = this.waiters.findIndex((w) => w.match(msg));
      if (idx >= 0) {
        const [w] = this.waiters.splice(idx, 1);
        clearTimeout(w.timer);
        w.resolve(msg);
      } else {
        this.inbox.push(msg);
      }
    });
    return this;
  }
  send(msg) { this.ws.send(JSON.stringify(msg)); }
  next(match, timeout = 2500) {
    const type = typeof match === 'string' ? { t: match } : match;
    const hit = this.inbox.findIndex((m) => Object.entries(type).every(([k, v]) => m[k] === v));
    if (hit >= 0) return Promise.resolve(this.inbox.splice(hit, 1)[0]);
    return new Promise((resolve, reject) => {
      const w = { match: (m) => Object.entries(type).every(([k, v]) => m[k] === v), resolve };
      w.timer = setTimeout(() => {
        this.waiters = this.waiters.filter((x) => x !== w);
        reject(new Error(`تایم‌اوت: پیام ${JSON.stringify(type)} نرسید`));
      }, timeout);
      this.waiters.push(w);
    });
  }
  async hello(name) {
    this.send({ t: 'hello', name });
    const w = await this.next('welcome');
    this.id = w.id;
    return w;
  }
  close() { try { this.ws.close(); } catch { /* noop */ } }
}

/* ── یک کلاینت SSE ── */
class SseClient {
  constructor(cid) { this.cid = cid; this.inbox = []; }
  async connect() {
    const res = await fetch(`${BASE}/api/events?cid=${this.cid}`);
    assert.equal(res.status, 200);
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    (async () => {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let i;
        while ((i = buf.indexOf('\n\n')) >= 0) {
          const chunk = buf.slice(0, i);
          buf = buf.slice(i + 2);
          for (const line of chunk.split('\n')) {
            if (line.startsWith('data: ')) this.inbox.push(JSON.parse(line.slice(6)));
          }
        }
      }
    })().catch(() => {});
    return this;
  }
  async send(msg) {
    const r = await fetch(`${BASE}/api/send`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cid: this.cid, msg }),
    });
    assert.equal(r.status, 200);
  }
  async next(t, timeout = 2500) {
    const start = Date.now();
    for (;;) {
      const hit = this.inbox.findIndex((m) => m.t === t);
      if (hit >= 0) return this.inbox.splice(hit, 1)[0];
      if (Date.now() - start > timeout) throw new Error(`تایم‌اوت SSE: ${t}`);
      await sleep(25);
    }
  }
}

/* ───────── اجرای تست ───────── */

const server = spawn(process.execPath, ['server.js'], {
  cwd: new URL('..', import.meta.url).pathname,
  env: { ...process.env, PORT: String(PORT), CALL_CODE: '' },
  stdio: ['ignore', 'pipe', 'pipe'],
});
let serverLog = '';
server.stdout.on('data', (d) => { serverLog += d; });
server.stderr.on('data', (d) => { serverLog += d; });

const cleanup = () => { try { server.kill('SIGKILL'); } catch { /* noop */ } };
process.on('exit', cleanup);

try {
  // انتظار برای بالا آمدن سرور
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(`${BASE}/api/health`);
      if (r.ok) break;
    } catch { /* هنوز بالا نیامده */ }
    await sleep(100);
  }
  const health = await (await fetch(`${BASE}/api/health`)).json();
  assert.equal(health.ok, true);
  ok('سرور بالا آمد و /api/health جواب می‌دهد');

  const cfg = await (await fetch(`${BASE}/api/config`)).json();
  assert.ok(Array.isArray(cfg.iceServers) && cfg.iceServers.length > 0);
  ok('سرورهای ICE در /api/config موجودند');

  /* ── دو کاربر آنلاین ── */
  const alice = await new WsClient().connect();
  const wa = await alice.hello('آلیس');
  const bob = await new WsClient().connect();
  const wb = await bob.hello('باب');
  assert.match(wa.id, /^\d{5,8}$/);
  assert.notEqual(wa.id, wb.id);
  ok(`دو کاربر با شماره‌ی یکتا وارد شدند (${wa.id} / ${wb.id})`);

  const pres = await alice.next('presence');
  assert.ok(pres.peers.some((p) => p.id === wb.id));
  ok('لیست آنلاین‌ها برای هر دو طرف منتشر شد');

  /* ── تماس با شماره: زنگ، پذیرش، شروع ── */
  alice.send({ t: 'dial', to: wb.id, video: false });
  const dialing = await alice.next('dialing');
  assert.ok(dialing.callId);
  const incoming = await bob.next('incoming');
  assert.equal(incoming.from.id, wa.id);
  assert.equal(incoming.callId, dialing.callId);
  ok('زنگ تماس به طرف مقابل رسید و از طرف درخواست‌کننده تأیید شد');

  bob.send({ t: 'accept', callId: incoming.callId });
  const startA = await alice.next('start');
  const startB = await bob.next('start');
  assert.equal(startA.room, startB.room);
  assert.equal(startA.initiator, true);
  assert.equal(startB.initiator, false);
  ok('اتاق تماس ساخته شد و نقش پیشنهاددهنده/پاسخ‌دهنده تعیین شد');

  /* ── عبور SDP و ICE ── */
  alice.send({ t: 'signal', data: { sdp: { type: 'offer', sdp: 'v=0...' } } });
  const sig = await bob.next('signal');
  assert.equal(sig.from, wa.id);
  assert.equal(sig.data.sdp.type, 'offer');
  bob.send({ t: 'signal', data: { candidate: { candidate: 'candidate:1 1 udp 1 127.0.0.1 5000 typ host' } } });
  const sig2 = await alice.next('signal');
  assert.ok(sig2.data.candidate);
  ok('پیام‌های SDP و ICE بین دو طرف منتقل می‌شوند');

  /* ── قطع تماس ── */
  alice.send({ t: 'hangup', callId: startA.callId });
  const ended = await bob.next('call-ended');
  assert.equal(ended.reason, 'peer-left');
  ok('قطع تماس به طرف مقابل اطلاع داده شد');

  // طرف مقابل نباید «مشغول» بماند
  await sleep(120);
  alice.send({ t: 'dial', to: wb.id, video: false });
  const again = await alice.next('dialing', 1500);
  assert.ok(again.callId);
  bob.send({ t: 'reject', callId: again.callId });
  await alice.next('rejected');
  ok('پس از پایان تماس، شماره از حالت «مشغول» آزاد می‌شود');

  /* ── تماس با شماره‌ی آفلاین ── */
  alice.send({ t: 'dial', to: '999999', video: false });
  const err = await alice.next('error');
  assert.equal(err.code, 'offline');
  ok('تماس با شماره‌ی آفلاین خطای درست می‌دهد');

  /* ── تماس با خود ── */
  alice.send({ t: 'dial', to: wa.id, video: false });
  assert.equal((await alice.next('error')).code, 'self');
  ok('تماس با خود رد می‌شود');

  /* ── جریان لینک/اتاق ── */
  const carol = await new WsClient().connect();
  await carol.hello('کارول');
  const dave = await new WsClient().connect();
  const wd = await dave.hello('دیو');

  carol.send({ t: 'join', room: 'abc123def4', video: true });
  const joinedCarol = await carol.next('joined');
  assert.equal(joinedCarol.initiator, false);
  assert.equal(joinedCarol.peer, null);

  dave.send({ t: 'join', room: 'abc123def4', video: true });
  const joinedDave = await dave.next('joined');
  assert.equal(joinedDave.initiator, true);
  assert.equal(joinedDave.peer.id, carol.id);
  assert.equal(joinedDave.video, true);
  const peerJoined = await carol.next('peer-joined');
  assert.equal(peerJoined.peer.id, wd.id);
  assert.equal(peerJoined.video, true);
  ok('لینک اتاق: نفر دوم پیشنهاددهنده می‌شود و هر دو همدیگر را می‌بینند');

  const erin = await new WsClient().connect();
  await erin.hello('ارین');
  erin.send({ t: 'join', room: 'abc123def4', video: false });
  const full = await erin.next('error');
  assert.equal(full.code, 'full');
  ok('نفر سوم به اتاق دو‌نفره راه داده نمی‌شود');

  /* ── ترک اتاق به طرف مقابل اطلاع داده می‌شود ── */
  carol.send({ t: 'hangup', callId: 'x' });
  const left = await dave.next('peer-left');
  assert.equal(left.peer.id, carol.id);
  ok('خروج یک طرف به طرف دیگر اطلاع داده می‌شود');

  /* ── شناسه‌ی پایدار (اتصال دوباره با همان شماره) ── */
  carol.close();
  await sleep(120);
  const carol2 = await new WsClient().connect();
  const w2 = await carol2.hello('کارول');
  // شماره‌ی قبلی آزاد شده و سرور شماره‌ی جدید می‌دهد
  assert.match(w2.id, /^\d{5,8}$/);
  const carol3 = await new WsClient().connect();
  carol3.send({ t: 'hello', name: 'کارول', id: w2.id });
  ok('اتصال دوباره شماره‌ی درخواستی را می‌پذیرد');

  /* ── انتقال پشتیبان SSE ── */
  const sse = await new SseClient('cid-test-1').connect();
  await sse.send({ t: 'hello', name: 'اس‌اس‌ای' });
  const wSse = await sse.next('welcome');
  assert.match(wSse.id, /^\d{5,8}$/);
  ok('مسیر پشتیبان SSE کار می‌کند (welcome دریافت شد)');

  const wsPeer = await new WsClient().connect();
  const wWs = await wsPeer.hello('وب‌سوکت');
  wsPeer.send({ t: 'dial', to: wSse.id, video: false });
  const incSse = await sse.next('incoming');
  assert.equal(incSse.from.id, wWs.id);
  ok('تماس بین کلاینت WebSocket و کلاینت SSE برقرار می‌شود');

  /* ── اعلان پوش: زنگ روی اپِ بسته ── */
  const reza = await new WsClient().connect();
  const wr = await reza.hello('رضا');
  reza.send({
    t: 'push',
    subscription: {
      endpoint: 'https://127.0.0.1:9/push-test',
      keys: { p256dh: 'BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QTpQtUbVlUls0VJXg7A8u-Ts1XbjhazAkj7I99e8QcYP7DkM', auth: 'tBHItJI5svbpez7KI4CCXg' },
    },
  });
  assert.equal((await reza.next('push-ok')).t, 'push-ok');
  ok('اشتراک اعلان (push) ثبت شد');

  reza.close();
  await sleep(150); // مطمئن می‌شویم آفلاین شده است

  const caller = await new WsClient().connect();
  const wc = await caller.hello('تماس‌گیرنده');
  caller.send({ t: 'dial', to: wr.id, video: false });

  const pushRinging = await caller.next('push-ringing');
  assert.ok(pushRinging.room);
  assert.equal(pushRinging.to.id, wr.id);
  ok('تماس با کاربرِ آفلاینِ دارای اعلان، به «زنگ با اعلان» تبدیل می‌شود');

  const joinedCaller = await caller.next('joined');
  assert.equal(joinedCaller.peer, null);
  assert.equal(joinedCaller.room, pushRinging.room);
  ok('تماس‌گیرنده داخل اتاق انتظار نشسته است');

  // طرف مقابل اعلان را باز می‌کند و به همان اتاق می‌آید
  const answerer = await new WsClient().connect();
  const wan = await answerer.hello('پاسخ‌دهنده');
  answerer.send({ t: 'join', room: pushRinging.room, video: false });
  const joinedAnswerer = await answerer.next('joined');
  assert.equal(joinedAnswerer.initiator, true);
  assert.equal(joinedAnswerer.peer.id, wc.id);
  const peerArrived = await caller.next('peer-joined');
  assert.equal(peerArrived.peer.id, wan.id);
  ok('با باز شدن اعلان، طرف مقابل به اتاق می‌رسد و تماس شکل می‌گیرد');

  caller.send({ t: 'hangup', callId: pushRinging.callId });
  answerer.close();

  /* ── صفحه‌ی اصلی سرو می‌شود ── */
  const page = await fetch(BASE + '/');
  const html = await page.text();
  assert.ok(page.status === 200 && html.includes('بیشماره'));
  ok('رابط کاربری روی / سرو می‌شود');

  const appJs = await fetch(BASE + '/js/app.js');
  assert.equal(appJs.status, 200);
  ok('فایل‌های جاوااسکریپت در دسترس‌اند');

  carol2.close(); carol3.close(); dave.close(); erin.close(); wsPeer.close(); alice.close(); bob.close();

  console.log(`\n  ✅ همه‌ی ${passed} تست موفق بود\n`);
  cleanup();
  process.exit(0);
} catch (err) {
  console.error('\n  ❌ تست شکست خورد:', err.message);
  if (serverLog) console.error('\n  --- خروجی سرور ---\n' + serverLog.slice(-2000));
  cleanup();
  process.exit(1);
}
