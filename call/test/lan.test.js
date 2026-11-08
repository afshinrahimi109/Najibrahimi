/*
 * تست «حالت محلی» — تماس بدون سیم‌کارت و بدون اینترنت
 * ─────────────────────────────────────────────────────────────
 * سرور را با LAN=1 بالا می‌آورد و بررسی می‌کند:
 *   • روی HTTPS با گواهی خودامضا سرو می‌شود (برای اجازه‌ی میکروفون لازم است)
 *   • هیچ سرور STUN/TURN بیرونی لازم نیست  (iceServers خالی)
 *   • HTTP به HTTPS هدایت می‌شود
 *   • سیگنالینگ WebSocket روی TLS کار می‌کند
 *   • رابط کاربری و QR در دسترس‌اند
 *
 *   node test/lan.test.js
 */

import { spawn } from 'node:child_process';
import https from 'node:https';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';
import { WebSocket } from 'ws';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const PORT = 8096;
const HTTPS_PORT = 8452;

let passed = 0;
const ok = (m) => { passed++; console.log(`  ✓ ${m}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function getJson(url) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, { rejectUnauthorized: false, timeout: 4000 }, (res) => {
      let body = '';
      res.setEncoding('utf8');
      res.on('data', (d) => { body += d; });
      res.on('end', () => {
        try { resolve({ status: res.statusCode, headers: res.headers, json: JSON.parse(body) }); }
        catch { resolve({ status: res.statusCode, headers: res.headers, text: body }); }
      });
    });
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.on('error', reject);
  });
}

const server = spawn(process.execPath, ['server.js', '--lan'], {
  cwd: ROOT,
  env: { ...process.env, PORT: String(PORT), LAN_PORT: String(HTTPS_PORT), LAN: '1', CALL_CODE: '' },
  stdio: ['ignore', 'pipe', 'pipe'],
});
let log = '';
server.stdout.on('data', (d) => { log += d; });
server.stderr.on('data', (d) => { log += d; });
const cleanup = () => { try { server.kill('SIGKILL'); } catch { /* noop */ } };
process.on('exit', cleanup);

try {
  let up = false;
  for (let i = 0; i < 100; i++) {
    try {
      const r = await getJson(`https://127.0.0.1:${HTTPS_PORT}/api/health`);
      if (r.status === 200) { up = true; break; }
    } catch { /* هنوز بالا نیامده */ }
    await sleep(120);
  }
  assert.ok(up, 'سرور HTTPS بالا نیامد');
  ok('سرور روی HTTPS با گواهی خودامضا بالا آمد');

  const health = await getJson(`https://127.0.0.1:${HTTPS_PORT}/api/health`);
  assert.equal(health.json.lan, true);
  ok('سرور خودش را در «حالت محلی» اعلام می‌کند');

  const cfg = (await getJson(`https://127.0.0.1:${HTTPS_PORT}/api/config`)).json;
  assert.deepEqual(cfg.iceServers, []);
  ok('برای تماس محلی هیچ STUN/TURN بیرونی لازم نیست (بدون اینترنت)');

  // هدایت HTTP → HTTPS
  const redirect = await new Promise((resolve, reject) => {
    const req = https.request ? null : null;
    import('node:http').then(({ default: http }) => {
      const r = http.get(`http://127.0.0.1:${PORT}/`, { timeout: 3000 }, (res) => {
        resolve({ status: res.statusCode, location: res.headers.location });
        res.resume();
      });
      r.on('error', reject);
      r.on('timeout', () => r.destroy(new Error('timeout')));
    }).catch(reject);
  });
  assert.equal(redirect.status, 302);
  assert.match(redirect.location || '', /^https:\/\/.+\/\s*$|^https:\/\/.+/);
  ok('آدرس HTTP خودکار به HTTPS هدایت می‌شود');

  // سیگنالینگ روی WSS
  const ws = new WebSocket(`wss://127.0.0.1:${HTTPS_PORT}/ws`, { rejectUnauthorized: false });
  const welcome = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('تایم‌اوت WSS')), 5000);
    ws.on('open', () => ws.send(JSON.stringify({ t: 'hello', name: 'گوشی محلی' })));
    ws.on('message', (buf) => {
      const msg = JSON.parse(buf.toString());
      if (msg.t === 'welcome') {
        clearTimeout(timer);
        resolve(msg);
      }
    });
    ws.on('error', (e) => { clearTimeout(timer); reject(e); });
  });
  assert.match(welcome.id, /^\d{5,8}$/);
  assert.equal(welcome.lan, true);
  assert.deepEqual(welcome.iceServers, []);
  ok('سیگنالینگ WebSocket روی TLS در حالت محلی کار می‌کند');
  ws.close();

  // رابط کاربری و QR
  const page = await new Promise((resolve, reject) => {
    https.get(`https://127.0.0.1:${HTTPS_PORT}/`, { rejectUnauthorized: false }, (res) => {
      let b = '';
      res.setEncoding('utf8');
      res.on('data', (d) => { b += d; });
      res.on('end', () => resolve(b));
    }).on('error', reject);
  });
  assert.ok(page.includes('بی‌شماره') && page.includes('qrBox') && page.includes('lanChip'));
  ok('رابط کاربری، محل QR و نشان «حالت محلی» سرو می‌شوند');

  const qrModule = await new Promise((resolve, reject) => {
    https.get(`https://127.0.0.1:${HTTPS_PORT}/js/vendor/qrcode.mjs`, { rejectUnauthorized: false }, (res) => {
      assert.equal(res.statusCode, 200);
      res.resume();
      resolve(true);
    }).on('error', reject);
  });
  assert.ok(qrModule);
  ok('کتابخانه‌ی QR از خود سرور (بدون CDN) در دسترس است');

  // گواهی قابل نصب
  const cert = await new Promise((resolve, reject) => {
    https.get(`https://127.0.0.1:${HTTPS_PORT}/cert`, { rejectUnauthorized: false }, (res) => {
      let b = '';
      res.setEncoding('utf8');
      res.on('data', (d) => { b += d; });
      res.on('end', () => resolve({ status: res.statusCode, type: res.headers['content-type'], body: b }));
    }).on('error', reject);
  });
  assert.equal(cert.status, 200);
  assert.match(cert.type || '', /x509/);
  assert.match(cert.body, /BEGIN CERTIFICATE/);
  ok('گواهی برای نصب روی گوشی (رفع هشدار) قابل دانلود است');

  // خروجی راهنما آدرس شبکه‌ی محلی را نشان می‌دهد
  assert.ok(/https:\/\/\d+\.\d+\.\d+\.\d+:\d+|هیچ آدرس شبکه/.test(log));
  ok('سرور آدرس شبکه‌ی محلی را برای باز کردن روی گوشی چاپ می‌کند');

  console.log(`\n  ✅ همه‌ی ${passed} تست حالت محلی موفق بود\n`);
  cleanup();
  process.exit(0);
} catch (err) {
  console.error('\n  ❌ تست حالت محلی شکست خورد:', err.message);
  if (log) console.error('\n  --- سرور ---\n' + log.slice(-1500));
  cleanup();
  process.exit(1);
}
