/**
 * بیشماره (BiShomare) — سرور تماس بدون سیمکارت
 * ------------------------------------------------------------------
 * این سرور دو کار انجام میدهد:
 *   ۱) سیگنالینگ WebRTC  (فقط پیامهای کوچک JSON — صدا/تصویر هرگز از سرور عبور نمیکند)
 *   ۲) سرو کردن رابط کاربری (PWA)
 *
 * صدا و تصویر به صورت رمزنگاریشده (DTLS-SRTP) مستقیم بین دو مرورگر رد و بدل میشود؛
 * بنابراین هزینهی پهنای باند سرور تقریباً صفر است و کیفیت تماس به مسیر اینترنت دو طرف بستگی دارد.
 *
 * اجرا:  node server.js         (پیشفرض روی پورت 8080)
 */

import express from 'express';
import http from 'http';
import path from 'path';
import fs from 'fs';
import os from 'os';
import https from 'https';
import crypto from 'crypto';
import { fileURLToPath } from 'url';
import { WebSocketServer } from 'ws';
import { generateVAPIDKeys, setVapidDetails, sendNotification } from 'web-push';
import selfsigned from 'selfsigned';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/* ───────────────────────── تنظیمات ───────────────────────── */

const PORT = Number(process.env.PORT || 8080);
const HOST = process.env.HOST || '0.0.0.0';

// اگر این را تنظیم کنی، فقط کسانی که کد دسترسی دارند میتوانند وارد شوند
const ACCESS_CODE = (process.env.CALL_CODE || '').trim();

/**
 * حالت «بدون اینترنت» (شبکه‌ی محلی / LAN)
 * با `npm run lan` یا LAN=1 روشن می‌شود: سرور روی HTTPS با گواهی خودامضا بالا می‌آید،
 * STUN لازم نیست (تماس مستقیم روی همان وای‌فای انجام می‌شود) و هیچ بسته‌ای
 * از دستگاه خارج نمی‌شود. برای همین بدون اینترنت هم کار می‌کند.
 */
const LAN = process.argv.includes('--lan') || /^(1|true|yes|on)$/i.test(process.env.LAN || '');
const HTTPS_PORT = Number(process.env.LAN_PORT || 8443);

// سرورهای STUN برای پیدا کردن مسیر بین دو طرف
const DEFAULT_STUN = 'stun:stun.l.google.com:19302,stun:stun1.l.google.com:19302';
const STUN_URLS = (process.env.STUN_URLS !== undefined ? process.env.STUN_URLS : LAN ? '' : DEFAULT_STUN)
  .split(',').map((s) => s.trim()).filter(Boolean);

// سرور TURN اختیاری — برای شبکههایی که NAT سخت دارند (شبکهی اداری/همراه)
const TURN_URL = (process.env.TURN_URL || '').trim();
const TURN_USER = (process.env.TURN_USER || '').trim();
const TURN_PASS = (process.env.TURN_PASS || '').trim();

const RING_TIMEOUT_MS = 50_000;   // چقدر زنگ بخورد تا خودکار قطع شود
const ROOM_TTL_MS = 3 * 60 * 60_000;
const MAX_ROOMS = 2000;
const MAX_PEERS = 5000;
const MAX_ROOM_MEMBERS = 2;       // تماس یکبهیک
const MAX_MSG_PER_SEC = 90;
const MAX_FRAME_BYTES = 64 * 1024;
const PUSH_RING_TIMEOUT = 90_000;  // چقدر منتظر بمانیم تا طرف مقابل اعلان را باز کند
const MAX_PUSH_SUBS = 20_000;

function iceServers() {
  const list = STUN_URLS.map((urls) => ({ urls }));
  if (TURN_URL) {
    list.push({
      urls: TURN_URL.split(',').map((s) => s.trim()).filter(Boolean),
      username: TURN_USER,
      credential: TURN_PASS,
    });
  }
  return list;
}

/* ───────────── Web Push — زنگ خوردن وقتی برنامه بسته است ─────────────
 * برای این کار به یک جفت کلید VAPID نیاز است. اگر در متغیرهای محیطی نبود،
 * یک جفت می‌سازیم و در data/vapid.json نگه می‌داریم (روی هاست دائمی امن است).
 * اگر هاست فایل‌سیستم موقت دارد، کلیدها با هر ری‌استارت عوض می‌شوند و
 * کاربر باید یک بار دیگر اشتراک اعلان بسازد.
 */

const VAPID_SUBJECT = process.env.VAPID_SUBJECT || 'mailto:admin@bishomare.local';
const DATA_DIR = path.join(__dirname, 'data');
const VAPID_FILE = path.join(DATA_DIR, 'vapid.json');

function loadVapid() {
  const pub = (process.env.VAPID_PUBLIC_KEY || '').trim();
  const priv = (process.env.VAPID_PRIVATE_KEY || '').trim();
  if (pub && priv) return { publicKey: pub, privateKey: priv };
  try {
    const raw = JSON.parse(fs.readFileSync(VAPID_FILE, 'utf8'));
    if (raw.publicKey && raw.privateKey) return raw;
  } catch { /* فایل نیست */ }
  const keys = generateVAPIDKeys();
  try {
    fs.mkdirSync(DATA_DIR, { recursive: true });
    fs.writeFileSync(VAPID_FILE, JSON.stringify(keys, null, 2), { mode: 0o600 });
  } catch { /* فایل‌سیستم فقط‌خواندنی */ }
  return keys;
}

const vapid = loadVapid();
let pushReady = true;
try {
  setVapidDetails(VAPID_SUBJECT, vapid.publicKey, vapid.privateKey);
} catch (err) {
  pushReady = false;
  console.warn('  ⚠️  Web Push غیرفعال شد:', err.message);
}

/** @type {Map<string, {subscription: object, name: string, updatedAt: number}>} */
const pushSubs = new Map();

/* ───────────────────────── وضعیت در حافظه ─────────────────────────
 * برای یک ابزار تماس، نگهداشتن وضعیت در حافظه کافی و سریع است.
 * اگر چند نسخه از سرور را همزمان اجرا میکنی، باید سیگنالینگ را
 * با Redis pub/sub بین آنها به اشتراک بگذاری.
 */

/** @type {Map<string, Peer>} */
const peers = new Map();
/** @type {Map<string, Room>} */
const rooms = new Map();
/** @type {Map<string, Call>} */
const calls = new Map();

class Peer {
  constructor(id) {
    this.id = id;
    this.name = 'مهمان';
    this.transport = null;   // 'ws' | 'sse'
    this.ws = null;
    this.res = null;         // پاسخ SSE
    this.room = null;        // کد اتاق فعلی
    this.dialing = null;     // callId
    this.alive = Date.now();
    this.authed = false;
    this.cid = null;         // شناسهی پایدار دستگاه (برای اتصال دوباره)
    this.msgWindow = { at: Date.now(), count: 0 };
  }
}

/* ───────────────────────── ابزارها ───────────────────────── */

const randId = (digits = 6) => {
  let s = '';
  for (let i = 0; i < digits; i++) s += crypto.randomInt(0, 10);
  return s;
};

function freshPeerId() {
  for (let i = 0; i < 200; i++) {
    const id = randId(6);
    if (!peers.has(id) && !(id.startsWith('0') && id.length < 6)) return id;
  }
  return randId(7);
}

const roomCode = () => crypto.randomBytes(5).toString('hex'); // 10 کاراکتر

function cleanName(raw) {
  const s = String(raw ?? '')
    .replace(/[\u0000-\u001f\u007f]/g, '')
    .replace(/[<>"`]/g, '')
    .trim()
    .slice(0, 24);
  return s || 'مهمان';
}

const publicPeer = (p) => ({ id: p.id, name: p.name });

function send(peer, msg) {
  if (!peer) return;
  const data = JSON.stringify(msg);
  try {
    if (peer.transport === 'ws' && peer.ws && peer.ws.readyState === 1) {
      peer.ws.send(data);
    } else if (peer.transport === 'sse' && peer.res && !peer.res.writableEnded) {
      peer.res.write(`data: ${data}\n\n`);
    }
  } catch {
    /* اتصال مرده — با heartbeat پاک میشود */
  }
}

function sendError(peer, code, message, extra = {}) {
  send(peer, { t: 'error', code, message, ...extra });
}

function rateLimited(peer) {
  const now = Date.now();
  if (now - peer.msgWindow.at > 1000) {
    peer.msgWindow = { at: now, count: 0 };
  }
  peer.msgWindow.count += 1;
  return peer.msgWindow.count > MAX_MSG_PER_SEC;
}

/* ───────────────────────── حضور آنلاین ───────────────────────── */

let presenceTimer = null;
function broadcastPresence(force = false) {
  if (presenceTimer && !force) return;
  presenceTimer = setTimeout(() => {
    presenceTimer = null;
    const list = [];
    for (const p of peers.values()) {
      if (!p.authed) continue;
      list.push({ ...publicPeer(p), busy: !!(p.room || p.dialing) });
      if (list.length >= 60) break;
    }
    let count = 0;
    for (const p of peers.values()) if (p.authed) count++;
    const msg = { t: 'presence', peers: list, count };
    for (const p of peers.values()) if (p.authed) send(p, msg);
  }, 250);
}

/* ───────────────────────── اتاقها ───────────────────────── */

function getRoom(code) {
  let room = rooms.get(code);
  if (!room) {
    if (rooms.size >= MAX_ROOMS) return null;
    room = { code, members: new Set(), createdAt: Date.now(), video: null };
    rooms.set(code, room);
  }
  return room;
}

function leaveRoom(peer, notify = true) {
  if (!peer.room) return;
  const room = rooms.get(peer.room);
  peer.room = null;
  if (!room) return;
  room.members.delete(peer.id);

  if (notify) {
    // اتاق‌ها یک‌به‌یک‌اند: با رفتن یک نفر، تماس برای همه تمام می‌شود.
    // این کار جلوی «مشغول ماندن» طرف مقابل را می‌گیرد.
    for (const id of [...room.members]) {
      const other = peers.get(id);
      room.members.delete(id);
      if (!other) continue;
      other.room = null;
      send(other, { t: 'peer-left', peer: publicPeer(peer) });
      send(other, { t: 'call-ended', reason: 'peer-left' });
    }
  }

  if (room.members.size === 0) {
    // اتاق خالی را مدتی نگه می‌داریم تا لینک دوباره هم کار کند
    setTimeout(() => {
      const r = rooms.get(room.code);
      if (r && r.members.size === 0) rooms.delete(room.code);
    }, 10 * 60_000).unref?.();
  }
}

function otherMembers(room, selfId) {
  return [...room.members].filter((id) => id !== selfId).map((id) => peers.get(id)).filter(Boolean);
}

/* ───────────────────────── تماسها ───────────────────────── */

function dropCall(call, reason) {
  if (!call) return;
  clearTimeout(call.timer);
  calls.delete(call.id);
  const from = peers.get(call.from);
  const to = peers.get(call.to);
  if (from) from.dialing = null;
  if (to) to.dialing = null;
  if (reason) {
    send(from, { t: 'call-ended', callId: call.id, reason });
    send(to, { t: 'call-ended', callId: call.id, reason });
  }
}

/* ───────────────────── اعلان پوش (زنگ روی اپ بسته) ───────────────────── */

function onPushSubscribe(peer, msg) {
  if (!peer.authed) return sendError(peer, 'auth', 'ابتدا وارد شو.');
  const sub = msg.subscription;
  if (!sub || typeof sub !== 'object' || typeof sub.endpoint !== 'string') {
    return sendError(peer, 'bad-push', 'اشتراک اعلان معتبر نیست.');
  }
  if (pushSubs.size >= MAX_PUSH_SUBS && !pushSubs.has(peer.id)) {
    return sendError(peer, 'busy', 'ظرفیت اعلان‌ها پر است.');
  }
  pushSubs.set(peer.id, {
    subscription: {
      endpoint: sub.endpoint.slice(0, 500),
      keys: { p256dh: String(sub.keys?.p256dh || ''), auth: String(sub.keys?.auth || '') },
    },
    name: peer.name,
    updatedAt: Date.now(),
  });
  send(peer, { t: 'push-ok', id: peer.id });
}

/**
 * «زنگ با اعلان»: طرف مقابل آنلاین نیست ولی اشتراک اعلان دارد.
 * یک اتاق برای تماس می‌سازیم، تماس‌گیرنده را داخلش می‌نشانیم و برای طرف
 * مقابل نوتیفیکیشنی با لینک همان اتاق می‌فرستیم. به‌محض باز کردن لینک،
 * همان مسیر معمولی «تماس با لینک» تماس را وصل می‌کند.
 */
function pushRing(caller, toId, video) {
  const rec = pushSubs.get(toId);
  if (!rec) return sendError(caller, 'offline', 'این شماره آنلاین نیست.');

  const room = getRoom(roomCode());
  if (!room) return sendError(caller, 'busy', 'سرور شلوغ است؛ کمی بعد تلاش کن.');

  room.members.add(caller.id);
  caller.room = room.code;

  const callId = crypto.randomBytes(6).toString('hex');
  const name = rec.name || 'کاربر بی‌شماره';

  send(caller, { t: 'push-ringing', callId, room: room.code, to: { id: toId, name } });
  send(caller, { t: 'joined', room: room.code, peer: null, initiator: false, video: Boolean(video) });

  const payload = JSON.stringify({
    type: 'incoming',
    title: '📞 تماس ورودی — بی‌شماره',
    body: `${caller.name} دارد زنگ می‌زند — برای پاسخ بزن`,
    from: publicPeer(caller),
    room: room.code,
    video: Boolean(video),
    callId,
  });

  Promise.resolve()
    .then(() => sendNotification(rec.subscription, payload, { TTL: 90, urgency: 'high', timeout: 5000 }))
    .catch((err) => {
      // اشتراک منقضی شده است
      if (err && (err.statusCode === 404 || err.statusCode === 410)) pushSubs.delete(toId);
    });

  // اگر تا این مدت کسی به اتاق نیامد، تماس را تمام می‌کنیم
  room.ringTimer = setTimeout(() => {
    room.ringTimer = null;
    const r = rooms.get(room.code);
    if (!r || r.members.size >= 2) return;
    const c = peers.get(caller.id);
    if (c) {
      send(c, { t: 'call-ended', reason: 'no-answer' });
      leaveRoom(c, false);
    }
  }, PUSH_RING_TIMEOUT);
  room.ringTimer.unref?.();

  broadcastPresence();
  return true;
}


/* ───────────────────────── منطق پیامها ───────────────────────── */

function onHello(peer, msg) {
  if (ACCESS_CODE && String(msg.code || '') !== ACCESS_CODE) {
    sendError(peer, 'auth', 'کد دسترسی نادرست است.', { needCode: true });
    return;
  }
  peer.authed = true;
  peer.name = cleanName(msg.name);
  if (msg.cid && typeof msg.cid === 'string') peer.cid = msg.cid.slice(0, 64);
  peer.alive = Date.now();

  // اگر دستگاه همان دستگاه قبلی است (بازگشت از پسزمینه/قطعی موبایل)
  // همان شناسهی قبلی را پس بده تا دوستانت با همان شماره پیدایت کنند
  const wanted = String(msg.id || '').trim();
  if (wanted && /^\d{5,8}$/.test(wanted) && !peers.has(wanted)) {
    const old = peers.get(peer.id);
    if (old === peer) {
      peers.delete(peer.id);
      peer.id = wanted;
      peers.set(wanted, peer);
    }
  }

  send(peer, {
    t: 'welcome',
    id: peer.id,
    name: peer.name,
    iceServers: iceServers(),
    hasTurn: Boolean(TURN_URL),
    lan: LAN,
    vapidPublicKey: pushReady ? vapid.publicKey : '',
    ringTimeout: RING_TIMEOUT_MS,
    peers: [...peers.values()].filter((p) => p.authed && p !== peer).slice(0, 60)
      .map((p) => ({ ...publicPeer(p), busy: !!(p.room || p.dialing) })),
  });
  broadcastPresence(true);
}

function onDial(peer, msg) {
  if (!peer.authed) return sendError(peer, 'auth', 'ابتدا وارد شو.');
  if (peer.room || peer.dialing) return sendError(peer, 'busy', 'خودت در یک تماس هستی.');

  const toId = String(msg.to || '').replace(/[^0-9]/g, '');
  const target = peers.get(toId);
  if (!target || !target.authed) {
    // طرف مقابل آنلاین نیست؛ اگر اعلان پوش دارد با نوتیفیکیشن زنگ می‌زنیم
    if (pushReady && pushSubs.has(toId)) return pushRing(peer, toId, Boolean(msg.video));
    return sendError(peer, 'offline', 'این شماره آنلاین نیست.');
  }
  if (target.id === peer.id) return sendError(peer, 'self', 'نمیتوانی به خودت زنگ بزنی!');
  if (target.room || target.dialing) return sendError(peer, 'busy', 'این شماره مشغول است.');

  const call = {
    id: crypto.randomBytes(6).toString('hex'),
    from: peer.id,
    to: target.id,
    video: Boolean(msg.video),
    startedAt: Date.now(),
    timer: null,
  };
  call.timer = setTimeout(() => {
    if (calls.has(call.id)) {
      send(peers.get(call.from), { t: 'timeout', callId: call.id });
      send(peers.get(call.to), { t: 'timeout', callId: call.id });
      dropCall(call, null);
    }
  }, RING_TIMEOUT_MS);
  call.timer.unref?.();

  calls.set(call.id, call);
  peer.dialing = call.id;
  target.dialing = call.id;

  send(peer, { t: 'dialing', callId: call.id, to: publicPeer(target) });
  send(target, {
    t: 'incoming',
    callId: call.id,
    from: publicPeer(peer),
    video: call.video,
    ringTimeout: RING_TIMEOUT_MS,
  });
}

function startCall(call) {
  const caller = peers.get(call.from);
  const callee = peers.get(call.to);
  if (!caller || !callee) {
    dropCall(call, 'peer-gone');
    return;
  }
  clearTimeout(call.timer);
  calls.delete(call.id);
  caller.dialing = null;
  callee.dialing = null;

  const room = getRoom(roomCode());
  if (!room) {
    dropCall(call, 'server-busy');
    return;
  }
  room.members.add(caller.id);
  room.members.add(callee.id);
  caller.room = room.code;
  callee.room = room.code;

  send(caller, {
    t: 'start',
    callId: call.id,
    room: room.code,
    peer: publicPeer(callee),
    initiator: true,
    video: call.video,
    outgoing: true,
  });
  send(callee, {
    t: 'start',
    callId: call.id,
    room: room.code,
    peer: publicPeer(caller),
    initiator: false,
    video: call.video,
    outgoing: false,
  });
  broadcastPresence();
}

function onAccept(peer, msg) {
  const call = calls.get(String(msg.callId || ''));
  if (!call || call.to !== peer.id) return sendError(peer, 'gone', 'این تماس دیگر در دسترس نیست.');
  startCall(call);
}

function onReject(peer, msg) {
  const call = calls.get(String(msg.callId || ''));
  if (!call || call.to !== peer.id) return;
  send(peers.get(call.from), { t: 'rejected', callId: call.id });
  dropCall(call, null);
  broadcastPresence();
}

function onCancel(peer, msg) {
  const call = calls.get(String(msg.callId || ''));
  if (!call || call.from !== peer.id) return;
  send(peers.get(call.to), { t: 'cancelled', callId: call.id });
  dropCall(call, null);
  broadcastPresence();
}

function onJoin(peer, msg) {
  if (!peer.authed) return sendError(peer, 'auth', 'ابتدا وارد شو.');
  let code = String(msg.room || '').toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, 24);
  if (code.length < 6) return sendError(peer, 'bad-room', 'کد اتاق معتبر نیست.');
  if (peer.room === code) return; // همین حالا داخلش هست

  if (peer.room) leaveRoom(peer);
  if (peer.dialing) dropCall(calls.get(peer.dialing), 'left');

  const room = getRoom(code);
  if (!room) return sendError(peer, 'server-busy', 'سرور شلوغ است، کمی بعد تلاش کن.');
  if (room.members.size >= MAX_ROOM_MEMBERS) {
    return sendError(peer, 'full', 'این تماس در حال حاضر دو نفر دارد.', { room: code });
  }

  const others = otherMembers(room, peer.id);
  room.members.add(peer.id);
  peer.room = code;
  if (room.video === null) room.video = Boolean(msg.video);

  const initiator = room.members.size === 2; // نفر دوم پیشنهاد (offer) را میسازد
  const other = others[0] || null;

  send(peer, {
    t: 'joined',
    room: code,
    peer: other ? publicPeer(other) : null,
    initiator,
    video: Boolean(room.video),
  });
  if (other) {
    send(other, { t: 'peer-joined', peer: publicPeer(peer), video: Boolean(room.video) });
  }
  broadcastPresence();
}

function onSignal(peer, msg) {
  if (!peer.room) return;
  const room = rooms.get(peer.room);
  if (!room) return;
  const data = msg.data;
  if (!data || typeof data !== 'object') return;
  const payload = JSON.stringify(data);
  if (payload.length > MAX_FRAME_BYTES) return;
  for (const id of room.members) {
    if (id === peer.id) continue;
    send(peers.get(id), { t: 'signal', from: peer.id, data });
  }
}

function onHangup(peer, msg) {
  if (peer.dialing) {
    const call = calls.get(peer.dialing);
    if (call && call.from === peer.id) {
      send(peers.get(call.to), { t: 'cancelled', callId: call.id });
    }
    dropCall(call, null);
  }
  if (peer.room) leaveRoom(peer, true);
  broadcastPresence();
}

function onSetName(peer, msg) {
  peer.name = cleanName(msg.name);
  send(peer, { t: 'me', id: peer.id, name: peer.name });
  broadcastPresence(true);
}

function dispatch(peer, raw) {
  if (!peer || typeof raw !== 'object' || raw === null) return;
  if (rateLimited(peer)) return;
  peer.alive = Date.now();
  switch (raw.t) {
    case 'hello': return onHello(peer, raw);
    case 'ping': return send(peer, { t: 'pong', at: Date.now() });
    case 'dial': return onDial(peer, raw);
    case 'accept': return onAccept(peer, raw);
    case 'reject': return onReject(peer, raw);
    case 'cancel': return onCancel(peer, raw);
    case 'join': return onJoin(peer, raw);
    case 'signal': return onSignal(peer, raw);
    case 'hangup': return onHangup(peer, raw);
    case 'setName': return onSetName(peer, raw);
    case 'push': return onPushSubscribe(peer, raw);
    default: return;
  }
}

function removePeer(peer) {
  if (!peer) return;
  if (peer.id && peers.get(peer.id) !== peer) return; // قبلاً جایگزین شده
  if (peer.dialing) {
    const call = calls.get(peer.dialing);
    if (call) {
      const otherId = call.from === peer.id ? call.to : call.from;
      send(peers.get(otherId), { t: 'call-ended', callId: call.id, reason: 'peer-gone' });
      dropCall(call, null);
    }
  }
  leaveRoom(peer, true);
  peers.delete(peer.id);
  broadcastPresence(true);
}

/* ───────────────────────── وبسرور ───────────────────────── */

const app = express();
app.disable('x-powered-by');
app.set('trust proxy', true);
app.use(express.json({ limit: '80kb' }));

app.get('/api/health', (_req, res) => {
  res.json({
    ok: true,
    peers: [...peers.values()].filter((p) => p.authed).length,
    rooms: rooms.size,
    calls: calls.size,
    turn: Boolean(TURN_URL),
    lan: LAN,
    push: pushReady,
    pushSubs: pushSubs.size,
    uptime: Math.round(process.uptime()),
  });
});

app.get('/api/config', (_req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  res.json({
    iceServers: iceServers(),
    hasTurn: Boolean(TURN_URL),
    lan: LAN,
    needCode: Boolean(ACCESS_CODE),
    ringTimeout: RING_TIMEOUT_MS,
    vapidPublicKey: pushReady ? vapid.publicKey : '',
    push: pushReady,
    serverTime: Date.now(),
  });
});

/* ── انتقال پشتیبان برای شبکههایی که WebSocket را میبندند: SSE + POST ── */
const ssePeers = new Map(); // cid -> Peer

app.get('/api/events', (req, res) => {
  const cid = String(req.query.cid || '').slice(0, 64);
  if (!cid) return res.status(400).end('cid required');
  if (peers.size > MAX_PEERS) return res.status(503).end('busy');

  res.writeHead(200, {
    'Content-Type': 'text/event-stream; charset=utf-8',
    'Cache-Control': 'no-cache, no-transform',
    Connection: 'keep-alive',
    'X-Accel-Buffering': 'no',
  });
  res.write(`retry: 1500\n\n`);

  let peer = ssePeers.get(cid);
  if (!peer || peer.transport !== 'sse') {
    peer = new Peer(freshPeerId());
    peer.cid = cid;
    peers.set(peer.id, peer);
    ssePeers.set(cid, peer);
  }
  peer.transport = 'sse';
  peer.res = res;
  peer.ws = null;
  peer.alive = Date.now();

  const keep = setInterval(() => {
    try {
      res.write(`: keep-alive\n\n`);
    } catch { /* noop */ }
  }, 20_000);
  keep.unref?.();

  req.on('close', () => {
    clearInterval(keep);
    if (peer.res === res) {
      peer.res = null;
      if (ssePeers.get(cid) === peer) {
        ssePeers.delete(cid);
        removePeer(peer);
      }
    }
  });
});

app.post('/api/send', (req, res) => {
  const cid = String(req.body?.cid || '').slice(0, 64);
  const peer = ssePeers.get(cid);
  if (!peer) return res.status(409).json({ ok: false, code: 'no-session' });
  dispatch(peer, req.body?.msg);
  res.json({ ok: true });
});

/* ── فایلهای ثابت ── */
/* ── دانلود گواهی حالت محلی (برای نصب روی گوشی و رفع هشدار) ── */
app.get('/cert', (_req, res) => {
  const certFile = path.join(__dirname, 'data', 'tls', 'cert.pem');
  try {
    const pem = fs.readFileSync(certFile);
    res.setHeader('Content-Type', 'application/x-x509-ca-cert');
    res.setHeader('Content-Disposition', 'attachment; filename="bishomare-lan.crt"');
    res.setHeader('Cache-Control', 'no-store');
    res.end(pem);
  } catch {
    res.status(404).type('text/plain; charset=utf-8').send('سرور در حالت محلی اجرا نشده است.');
  }
});


app.use(
  express.static(path.join(__dirname, 'public'), {
    etag: true,
    maxAge: '1h',
    setHeaders(res, filePath) {
      if (filePath.endsWith('.html') || filePath.endsWith('sw.js') || filePath.endsWith('manifest.webmanifest')) {
        res.setHeader('Cache-Control', 'no-cache');
      }
    },
  })
);

app.get(/^\/(?!api|ws).*/, (_req, res) => {
  res.setHeader('Cache-Control', 'no-cache');
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

const server = http.createServer(app);

/* ── WebSocket: مسیر اصلی سیگنالینگ ── */
const wssList = [];

function attachWs(serverInstance) {
  const wss = new WebSocketServer({ server: serverInstance, path: '/ws', maxPayload: MAX_FRAME_BYTES });
  wssList.push(wss);

  wss.on('connection', (ws, req) => {
    if (peers.size > MAX_PEERS) {
      ws.close(1013, 'busy');
      return;
    }
    const peer = new Peer(freshPeerId());
    peer.transport = 'ws';
    peer.ws = ws;
    peers.set(peer.id, peer);

    ws.isAlive = true;
    ws.on('pong', () => { ws.isAlive = true; peer.alive = Date.now(); });

    // برای اینکه کلاینت بتواند در صورت قطعی همان شناسه را بگیرد
    send(peer, { t: 'hello-ack', provisionalId: peer.id });

    ws.on('message', (buf) => {
      let msg;
      try { msg = JSON.parse(buf.toString()); } catch { return; }
      dispatch(peer, msg);
    });

    ws.on('close', () => {
      if (peer.ws === ws) removePeer(peer);
    });
    ws.on('error', () => {
      if (peer.ws === ws) removePeer(peer);
    });

    const ip = (req.headers['x-forwarded-for'] || req.socket.remoteAddress || '').toString().split(',')[0];
    if (ip) peer.ip = ip;
  });

  return wss;
}

const heartbeat = setInterval(() => {
  for (const wss of wssList) {
    for (const ws of wss.clients) {
      if (ws.isAlive === false) { ws.terminate(); continue; }
      ws.isAlive = false;
      try { ws.ping(); } catch { /* noop */ }
    }
  }
  // پاکسازی اتاق‌های قدیمی و همتای بدون اتصال
  const now = Date.now();
  for (const [code, room] of rooms) {
    if (room.members.size === 0 && now - room.createdAt > ROOM_TTL_MS) rooms.delete(code);
  }
  for (const p of peers.values()) {
    if (p.transport === 'sse' && !p.res && now - p.alive > 120_000) removePeer(p);
  }
  // اشتراک‌های اعلانِ خیلی قدیمی را پاک می‌کنیم
  const pushCutoff = now - 60 * 24 * 60 * 60_000;
  for (const [id, rec] of pushSubs) {
    if (rec.updatedAt < pushCutoff) pushSubs.delete(id);
  }
}, 30_000);
heartbeat.unref?.();

/* ── گواهی خودامضا برای حالت محلی ── */

function localIPv4() {
  const out = new Set(['127.0.0.1']);
  for (const list of Object.values(os.networkInterfaces())) {
    for (const ni of list || []) {
      if (ni.family === 'IPv4' && !ni.internal) out.add(ni.address);
    }
  }
  return [...out];
}

async function ensureCert() {
  const dir = path.join(__dirname, 'data', 'tls');
  const keyFile = path.join(dir, 'key.pem');
  const certFile = path.join(dir, 'cert.pem');
  const metaFile = path.join(dir, 'hosts.json');
  const ips = localIPv4();

  try {
    const meta = JSON.parse(fs.readFileSync(metaFile, 'utf8'));
    const same = meta.ips.length === ips.length && meta.ips.every((ip) => ips.includes(ip));
    const key = fs.readFileSync(keyFile, 'utf8');
    const cert = fs.readFileSync(certFile, 'utf8');
    if (same && key && cert) return { key, cert };
  } catch { /* بسازیم */ }

  const altNames = [
    { type: 2, value: 'localhost' },
    { type: 2, value: 'bishomare.local' },
    ...ips.map((ip) => ({ type: 7, ip })),
  ];
  const pems = await selfsigned.generate([{ name: 'commonName', value: 'bishomare.local' }], {
    days: 3650,
    keySize: 2048,
    algorithm: 'sha256',
    extensions: [
      { name: 'subjectAltName', altNames },
      { name: 'basicConstraints', cA: true },
    ],
  });
  try {
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(keyFile, pems.private, { mode: 0o600 });
    fs.writeFileSync(certFile, pems.cert, { mode: 0o600 });
    fs.writeFileSync(metaFile, JSON.stringify({ ips, created: Date.now() }), { mode: 0o600 });
  } catch { /* فایل‌سیستم فقط‌خواندنی */ }
  return { key: pems.private, cert: pems.cert };
}

/* ── اجرا ── */

const servers = [];

function printInfo() {
  console.log(`     STUN: ${STUN_URLS.length ? STUN_URLS.join(', ') : 'ندارد (تماس مستقیم روی شبکه)'}`);
  console.log(`     TURN: ${TURN_URL || 'تنظیم نشده'}`);
  console.log(`     کد دسترسی: ${ACCESS_CODE ? 'فعال' : 'غیرفعال'}`);
  console.log(`     اعلان پوش: ${pushReady ? 'فعال' : 'غیرفعال'}`);
}

async function main() {
  if (LAN) {
    const { key, cert } = await ensureCert();
    const httpsServer = https.createServer({ key, cert }, app);
    attachWs(httpsServer);
    await new Promise((resolve, reject) => {
      httpsServer.once('error', reject);
      httpsServer.listen(HTTPS_PORT, HOST, resolve);
    });
    servers.push(httpsServer);

    // آدرس HTTP فقط برای هدایت به HTTPS (راحت‌تر تایپ شود)
    const redirectServer = http.createServer((req, res) => {
      const host = String(req.headers.host || '').split(':')[0] || 'localhost';
      res.writeHead(302, { Location: `https://${host}:${HTTPS_PORT}${req.url || '/'}` });
      res.end('بی‌شماره در حالت محلی روی HTTPS اجرا می‌شود.');
    });
    redirectServer.on('error', () => {});
    try { redirectServer.listen(PORT, HOST); servers.push(redirectServer); } catch { /* پورت مشغول */ }

    const urls = localIPv4().filter((ip) => ip !== '127.0.0.1').map((ip) => `https://${ip}:${HTTPS_PORT}`);
    console.log('\n  📴 بی‌شماره — حالت محلی (بدون سیم‌کارت، بدون اینترنت)');
    console.log(`     سرور روی HTTPS:${HTTPS_PORT} بالا آمد`);
    if (urls.length) {
      console.log('     از گوشی روی همین وای‌فای باز کن:');
      for (const u of urls) console.log(`        ${u}`);
      console.log('     بار اول مرورگر هشدار گواهی می‌دهد → «پیشرفته» → «ادامه/Proceed»');
      console.log('     آیفون: گواهی باید اعتماد شود (راهنما در README).');
    } else {
      console.log('     ⚠️ هیچ آدرس شبکه‌ی محلی پیدا نشد — وای‌فای/هات‌اسپات را روشن کن.');
    }
    printInfo();
    console.log('');
  } else {
    const server = http.createServer(app);
    attachWs(server);
    await new Promise((resolve, reject) => {
      server.once('error', reject);
      server.listen(PORT, HOST, resolve);
    });
    servers.push(server);
    console.log(`\n  📞 بیشماره روی http://${HOST}:${PORT} بالا آمد`);
    printInfo();
    console.log('');
  }
}

main().catch((err) => {
  console.error('  ❌ سرور بالا نیامد:', err.message);
  process.exit(1);
});

process.on('SIGTERM', () => {
  for (const p of peers.values()) send(p, { t: 'error', code: 'shutdown', message: 'سرور راه‌اندازی مجدد می‌شود.' });
  for (const s of servers) { try { s.close(); } catch { /* noop */ } }
  setTimeout(() => process.exit(0), 1500).unref();
});
