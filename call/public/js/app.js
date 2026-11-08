/*
 * بیشماره — منطق برنامه
 * ──────────────────────────────────────────────────────────
 * دو جریان تماس:
 *   ۱) لینک: ساخت اتاق → فرستادن لینک → نفر دومی که وارد شود پیشنهاد (offer) می‌سازد
 *   ۲) شماره: شماره‌گیری ۶ رقمی → زنگ → پذیرش → اتصال
 */

import { store, save, addRecent, clearAll } from './store.js';
import { SignalClient } from './signal.js';
import { LiveCall, friendlyMediaError } from './call.js';
import { createRinger } from './ring.js';

/* ───────── ابزارها ───────── */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const FA = '۰۱۲۳۴۵۶۷۸۹';
const faDigits = (s) => String(s).replace(/\d/g, (d) => FA[+d]);
const enDigits = (s) => String(s).replace(/[۰-۹]/g, (d) => String(FA.indexOf(d)));
const fmtId = (id) => (id ? faDigits(String(id).replace(/(\d{3})(?=\d)/g, '$1 ')) : '··· ···');
const fmtTime = (ms) => {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`;
};
const initial = (name) => (name || '؟').trim().charAt(0) || '؟';
const rnd = (n) => {
  const bytes = crypto.getRandomValues(new Uint8Array(n));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('').slice(0, n);
};

const ringer = createRinger();

const el = {
  pill: $('#connPill'),
  banner: $('#banner'),
  myId: $('#myId'),
  myName: $('#myName'),
  btnSettings: $('#btnSettings'),
  btnIdMenu: $('#btnIdMenu'),
  btnNewLink: $('#btnNewLink'),
  linkBox: $('#linkBox'),
  linkInput: $('#linkInput'),
  btnCopyLink: $('#btnCopyLink'),
  btnShareLink: $('#btnShareLink'),
  btnOpenLink: $('#btnOpenLink'),
  dialDigits: $('#dialDigits'),
  dialHint: $('#dialHint'),
  dialpad: $('#dialpad'),
  btnDial: $('#btnDial'),
  btnVideoDial: $('#btnVideoDial'),
  onlineList: $('#onlineList'),
  onlineCount: $('#onlineCount'),
  onlineEmpty: $('#onlineEmpty'),
  recentCard: $('#recentCard'),
  recentList: $('#recentList'),
  callScreen: $('#callScreen'),
  remoteVideo: $('#remoteVideo'),
  localVideo: $('#localVideo'),
  callAvatar: $('#callAvatar'),
  bigAvatar: $('#bigAvatar'),
  callName: $('#callName'),
  callNumber: $('#callNumber'),
  callTimer: $('#callTimer'),
  callStatus: $('#callStatus'),
  callQuality: $('#callQuality'),
  qualityText: $('#qualityText'),
  wave: $('#wave'),
  statsPanel: $('#statsPanel'),
  btnPlayAudio: $('#btnPlayAudio'),
  sheet: $('#sheet'),
  setName: $('#setName'),
  setMic: $('#setMic'),
  setCam: $('#setCam'),
  setRing: $('#setRing'),
  setSticky: $('#setSticky'),
  setPush: $('#setPush'),
  sheetInfo: $('#sheetInfo'),
  btnReset: $('#btnReset'),
  myLink: $('#myLink'),
  btnInstall: $('#btnInstall'),
  iosInstallHint: $('#iosInstallHint'),
  btnCopyMyLink: $('#btnCopyMyLink'),
  codeGate: $('#codeGate'),
  codeInput: $('#codeInput'),
  btnCode: $('#btnCode'),
  toast: $('#toast'),
};

const state = {
  id: null,
  peer: null,
  callId: null,
  room: null,
  phase: 'idle',        // idle | waiting | outgoing | incoming | connecting | active
  dir: 'out',           // out | in | link
  video: false,
  invite: null,
  dialTarget: null,
  linkRoom: null,
  linkCreator: false,
  iceServers: [],
  hasTurn: false,
  vapidKey: '',
  call: null,
  startedAt: 0,
  lastStats: null,
  timers: { clock: null, level: null, stats: null, offer: null },
  typing: '',
  dialVideo: false,
  videoHidden: false,
  mediaLock: false,
  online: [],
};

/* ───────── سیگنالینگ ───────── */

const sig = new SignalClient({ cid: store.cid, onMessage: onMessage, onState: onConnState });

sig.connect();

function hello() {
  sig.send({
    t: 'hello',
    name: store.name || '',
    id: store.sticky ? (state.id || store.myId || '') : '',
    cid: store.cid,
    code: store.code || '',
  });
}

function onConnState(s) {
  setPill(s);
  if (s === 'open') {
    hello();
    updateSheetInfo();
  }
  if (s === 'closed' && state.phase !== 'idle') {
    toast('ارتباط با سرور قطع شد؛ در حال وصل شدن مجدد…', 'err');
  }
}

function setPill(s, customText) {
  const map = {
    open: ['pill-ok', 'آنلاین'],
    connecting: ['pill-wait', 'اتصال…'],
    closed: ['pill-bad', 'قطع'],
    idle: ['pill-wait', 'اتصال…'],
  };
  const [cls, txt] = map[s] || map.idle;
  el.pill.className = `pill ${cls}`;
  el.pill.querySelector('span').textContent = customText || txt;
}

/* ───────── پیام‌های سرور ───────── */

function onMessage(msg) {
  switch (msg.t) {
    case 'welcome': return onWelcome(msg);
    case 'presence': return renderOnline(msg);
    case 'me': save({ name: msg.name }); state.id = msg.id; renderMe(); return;
    case 'incoming': return onIncoming(msg);
    case 'dialing': return onDialing(msg);
    case 'start': return onStart(msg);
    case 'joined': return onJoined(msg);
    case 'peer-joined': return onPeerJoined(msg);
    case 'peer-left': return onPeerLeft();
    case 'signal': return onSignal(msg);
    case 'rejected': return endCall('طرف مقابل تماس را رد کرد.', true);
    case 'cancelled': return endCall('تماس لغو شد.', true);
    case 'timeout': return endCall('کسی پاسخ نداد.', true);
    case 'call-ended': {
      if (msg.reason === 'no-answer') return endCall('کسی پاسخ نداد.', true);
      return endCall(msg.reason === 'hungup' ? 'تماس پایان یافت.' : 'طرف مقابل قطع کرد.', true);
    }
    case 'push-ringing': return onPushRinging(msg);
    case 'push-ok': return refreshPushSwitch();
    case 'error': return onServerError(msg);
    default: return;
  }
}

function onWelcome(msg) {
  state.id = msg.id;
  state.iceServers = msg.iceServers || [];
  state.hasTurn = Boolean(msg.hasTurn);
  state.vapidKey = msg.vapidPublicKey || '';
  if (store.sticky || !store.myId) save({ myId: msg.id });
  if (!store.name) save({ name: msg.name || '' });
  renderMe();
  renderOnline({ peers: msg.peers || [], count: (msg.peers || []).length + 1 });
  updateSheetInfo();
  refreshPushSwitch();
  resendPushSubscription();
  maybeShowInvite();
}

function onServerError(msg) {
  if (msg.code === 'auth') return openGate();
  const map = {
    busy: 'این شماره در حال تماس است.',
    offline: 'این شماره آنلاین نیست.',
    self: 'به خودت که نمی‌شود زنگ زد 🙂',
    full: 'این لینک همین حالا در حال استفاده است.',
    gone: 'این تماس دیگر در دسترس نیست.',
    shutdown: 'سرور در حال به‌روزرسانی است.',
  };
  const text = map[msg.code] || msg.message || 'خطای سرور';
  if (['busy', 'offline', 'self', 'full', 'gone'].includes(msg.code)) return endCall(text, true);
  toast(text, 'err');
}

/* ───────── شماره و آنلاین‌ها ───────── */

function renderMe() {
  el.myId.textContent = fmtId(state.id);
  el.myName.textContent = store.name || 'مهمان';
  if (document.activeElement !== el.setName) el.setName.value = store.name || '';
}

function renderOnline(msg) {
  const list = (msg.peers || []).filter((p) => p.id !== state.id);
  state.online = list;
  el.onlineCount.textContent = faDigits(msg.count ?? list.length);
  el.onlineEmpty.hidden = list.length > 0;
  el.onlineList.innerHTML = '';

  for (const p of list.slice(0, 20)) {
    const li = document.createElement('li');
    li.innerHTML = `
      <span class="ava ${p.busy ? 'busy' : ''}">${initial(p.name)}</span>
      <span class="who"><b></b><span dir="ltr">${fmtId(p.id)}</span></span>
      <span class="act">${
        p.busy
          ? '<span class="tagbusy">مشغول</span>'
          : `<button class="audio" aria-label="تماس صوتی"><svg><use href="#i-phone"/></svg></button>
             <button class="vid" aria-label="تماس تصویری"><svg><use href="#i-video"/></svg></button>`
      }</span>`;
    $('.who b', li).textContent = p.name || 'مهمان';
    const a = $('.audio', li);
    const v = $('.vid', li);
    if (a) a.onclick = () => startOutgoing({ id: p.id, name: p.name }, false);
    if (v) v.onclick = () => startOutgoing({ id: p.id, name: p.name }, true);
    el.onlineList.appendChild(li);
  }
  if (state.typing) renderDial();
}

const presenceById = (id) => state.online.find((p) => p.id === id) || null;

/* ───────── لینک تماس ───────── */

const linkFor = (code) => `${location.origin}${location.pathname}?c=${code}`;

async function createLink() {
  if (state.phase === 'waiting') return cancelLink();
  if (state.phase !== 'idle' || state.mediaLock) return;

  let call;
  state.mediaLock = true;
  try {
    call = await prepareMedia(state.video);
  } catch (err) {
    state.mediaLock = false;
    return mediaFail(err);
  }
  state.mediaLock = false;

  const code = rnd(10);
  state.call = call;
  state.linkRoom = code;
  state.dir = 'link';
  state.linkCreator = true;
  state.phase = 'waiting';
  state.call.setMicEnabled(false);

  sig.send({ t: 'join', room: code, video: state.video });

  el.linkInput.value = linkFor(code);
  el.linkBox.hidden = false;
  el.btnNewLink.classList.remove('btn-primary');
  el.btnNewLink.classList.add('btn-soft');
  el.btnNewLink.innerHTML = '<svg><use href="#i-x"/></svg>لغو انتظار';
  setPill('open', 'در انتظار تماس…');
}

function cancelLink() {
  ringer.stop();
  sig.send({ t: 'hangup' });
  teardown();
  hideCallScreen();
  state.phase = 'idle';
  state.dir = 'out';
  resetLinkUi();
  setPill(sig.state);
  toast('انتظار لغو شد.');
}

function resetLinkUi() {
  el.linkBox.hidden = true;
  el.btnNewLink.classList.add('btn-primary');
  el.btnNewLink.classList.remove('btn-soft');
  el.btnNewLink.innerHTML = '<svg><use href="#i-link"/></svg>ساخت لینک تماس';
  state.linkRoom = null;
  state.linkCreator = false;
}

async function copyLink() {
  const text = el.linkInput.value;
  try {
    await navigator.clipboard.writeText(text);
    toast('لینک کپی شد ✓');
  } catch {
    el.linkInput.select();
    document.execCommand?.('copy');
    toast('لینک انتخاب شد — کپی کن.');
  }
}

async function shareLink() {
  const url = el.linkInput.value;
  if (navigator.share) {
    try {
      await navigator.share({ title: 'تماس با بیشماره', text: 'بیا با هم حرف بزنیم — روی این لینک بزن:', url });
      return;
    } catch { /* لغو شد */ }
  }
  copyLink();
}

/* ───────── دعوت با لینک ───────── */

function maybeShowInvite() {
  if (state.phase !== 'idle') return;
  const params = new URLSearchParams(location.search);

  // لینک شخصی: ‎/?to=123456‎  → با یک ضربه به آن شماره زنگ می‌زنیم
  const to = enDigits(params.get('to') || '').replace(/\D/g, '');
  if (to.length >= 5) {
    const known = presenceById(to);
    state.dialTarget = to;
    state.dir = 'out';
    state.phase = 'incoming';
    el.callName.textContent = known?.name || 'کاربر بی‌شماره';
    el.callNumber.textContent = fmtId(to);
    setAvatar(known ? initial(known.name) : '📞');
    showCallScreen('incoming');
    setStatus('برای شروع تماس، «تماس» را بزن');
    $('[data-act="accept"] span').textContent = 'تماس';
    return;
  }

  const code = (params.get('c') || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  if (!code || code.length < 6 || state.invite) return;
  state.invite = code;
  state.dir = 'link';
  state.phase = 'incoming';
  el.callName.textContent = 'دعوت به تماس';
  el.callNumber.textContent = 'یک لینک اشتراکی';
  setAvatar('📞');
  showCallScreen('incoming');
  setStatus('برای وصل شدن، «پیوستن» را بزن');
  ringer.incoming();
}

async function joinInvite() {
  const code = state.invite;
  state.invite = null;
  ringer.stop();

  if (state.mediaLock) return;
  let call;
  state.mediaLock = true;
  try {
    call = await prepareMedia(state.video);
  } catch (err) {
    state.mediaLock = false;
    hideCallScreen();
    return mediaFail(err);
  }
  state.mediaLock = false;
  state.call = call;
  state.dir = 'link';
  state.linkRoom = code;
  state.linkCreator = false;
  state.phase = 'connecting';
  showCallScreen('connecting');
  setStatus('در حال اتصال…');
  sig.send({ t: 'join', room: code, video: state.video });
}

/* ───────── رویدادهای اتاق لینک ───────── */

function onJoined(msg) {
  if (!['link', 'push'].includes(state.dir) || !state.call) return;
  state.room = msg.room;

  if (!msg.peer) {
    state.phase = 'waiting';
    if (state.linkCreator) return;                  // روی صفحه‌ی خانه منتظر می‌مانیم
    showCallScreen('connecting');
    setStatus(state.dir === 'push' ? 'اعلان فرستاده شد — منتظر پاسخ…' : 'در انتظار طرف مقابل…');
    return;
  }

  state.peer = msg.peer;
  state.phase = 'connecting';
  showCallScreen('connecting');
  paintPeer();
  setStatus('در حال اتصال…');

  maybeEnableVideo(msg);
  if (msg.initiator) {
    state.call.startAsCaller().catch(() => toast('برقراری تماس ناموفق بود.', 'err'));
  } else {
    armOfferTimeout();
  }
}

/** اگر اتاق تصویری است، دوربین این طرف را هم روشن کن */
function maybeEnableVideo(msg) {
  if (!msg?.video || !state.call || state.call.camTrack) return;
  state.call.openCamera()
    .then(() => { state.video = true; paintLocalVideo(); })
    .catch(() => toast('دوربین باز نشد؛ تماس صوتی ادامه دارد.', 'err'));
}

function onPeerJoined(msg) {
  if (!['link', 'push'].includes(state.dir) || !state.call || state.phase === 'active') return;
  state.peer = msg.peer;
  state.phase = 'connecting';
  showCallScreen('connecting');
  paintPeer();
  setStatus('در حال اتصال…');
  maybeEnableVideo(msg);
  armOfferTimeout();
}

function onPeerLeft() {
  if (state.phase === 'waiting' || state.phase === 'idle') return;
  endCall('طرف مقابل تماس را پایان داد.', true);
}

/* ───────── تماس با شماره ───────── */

async function startOutgoing(peer, video) {
  if (state.phase !== 'idle' || state.mediaLock) return;
  if (sig.state !== 'open') {
    toast('هنوز به سرور وصل نشده‌ایم…', 'err');
    sig.connect();
    return;
  }

  state.peer = { id: String(peer.id), name: peer.name || 'کاربر بیشماره' };
  state.dir = 'out';
  state.video = Boolean(video);

  let call;
  state.mediaLock = true;
  try {
    call = await prepareMedia(state.video);
  } catch (err) {
    state.mediaLock = false;
    return mediaFail(err);
  }
  state.mediaLock = false;
  state.call = call;
  state.phase = 'outgoing';
  ensureNotifyPermission();

  showCallScreen('outgoing');
  paintPeer();
  setStatus('در حال زنگ زدن…');
  ringer.outgoing();
  sig.send({ t: 'dial', to: state.peer.id, video: state.video });
}

function onDialing(msg) {
  state.callId = msg.callId;
  if (msg.to && !state.peer) state.peer = msg.to;
}

async function ensureNotifyPermission() {
  if (!('Notification' in window) || Notification.permission !== 'default') return;
  try { await Notification.requestPermission(); } catch { /* noop */ }
}

let incomingNote = null;
function notifyIncoming(name) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  if (!document.hidden) return;
  try {
    incomingNote = new Notification('📞 تماس ورودی — بیشماره', {
      body: `${name || 'یک کاربر'} دارد زنگ می‌زند`,
      tag: 'bishomare-call',
      requireInteraction: true,
      icon: 'icons/icon-192.png',
    });
    incomingNote.onclick = () => {
      window.focus();
      incomingNote?.close();
      incomingNote = null;
    };
  } catch { /* noop */ }
}

function clearIncomingNote() {
  try { incomingNote?.close(); } catch { /* noop */ }
  incomingNote = null;
}

function onIncoming(msg) {
  if (state.phase !== 'idle') {
    sig.send({ t: 'reject', callId: msg.callId });
    return;
  }
  state.callId = msg.callId;
  state.peer = msg.from;
  state.dir = 'in';
  state.video = Boolean(msg.video);
  state.phase = 'incoming';
  showCallScreen('incoming');
  paintPeer();
  setStatus('تماس ورودی…');
  ringer.incoming();
  document.title = `📞 تماس از ${msg.from?.name || 'ناشناس'}`;
  notifyIncoming(msg.from?.name);
}

async function acceptCall() {
  if (state.invite) return joinInvite();

  if (state.dialTarget) {
    const to = state.dialTarget;
    state.dialTarget = null;
    hideCallScreen();
    state.phase = 'idle';
    state.dir = 'out';
    return startOutgoing({ id: to, name: presenceById(to)?.name || 'کاربر بی‌شماره' }, false);
  }

  if (state.phase !== 'incoming') return;
  ringer.stop();

  if (state.mediaLock) return;
  let call;
  state.mediaLock = true;
  try {
    call = await prepareMedia(state.video);
  } catch (err) {
    state.mediaLock = false;
    sig.send({ t: 'reject', callId: state.callId });
    hideCallScreen();
    resetAll();
    return mediaFail(err);
  }
  state.mediaLock = false;
  state.call = call;
  state.phase = 'connecting';
  showCallScreen('connecting');
  setStatus('در حال اتصال…');
  sig.send({ t: 'accept', callId: state.callId });
  armOfferTimeout();
}

function onStart(msg) {
  state.callId = msg.callId;
  state.room = msg.room;
  state.video = Boolean(msg.video);
  if (msg.peer) state.peer = msg.peer;

  if (state.phase !== 'active') {
    state.phase = 'connecting';
    showCallScreen('connecting');
    paintPeer();
    setStatus('در حال اتصال…');
  }
  if (msg.initiator) {
    state.call?.startAsCaller().catch(() => toast('شروع تماس ناموفق بود.', 'err'));
  } else {
    armOfferTimeout();
  }
}

/** اگر بعد از چند ثانیه پیشنهادی نرسید، از طرف مقابل می‌خواهیم دوباره بفرستد */
function armOfferTimeout() {
  clearTimeout(state.timers.offer);
  state.timers.offer = setTimeout(() => {
    if (state.phase !== 'connecting' && state.phase !== 'active') return;
    if (state.call?.negotiated) return;
    state.call?.emitSignal({ request: 'renegotiate' });
  }, 7000);
}

function onSignal(msg) {
  state.call?.handleSignal(msg.data).catch(() => {});
}

/* ───────── رسانه ───────── */

async function prepareMedia(video) {
  const call = new LiveCall({
    iceServers: state.iceServers,
    settings: { micId: store.micId, camId: store.camId },
    callbacks: {
      onSignal: (data) => sig.send({ t: 'signal', data }),
      onConnectionState: onPcState,
      onRemoteStream: attachRemote,
      onPeerMedia: onPeerMedia,
      onTracksChanged: paintLocalVideo,
    },
  });
  await call.openMic();
  if (video) {
    try {
      await call.openCamera();
    } catch (err) {
      toast('دوربین باز نشد؛ تماس صوتی ادامه دارد.', 'err');
      state.video = false;
    }
  }
  state.video = Boolean(call.camTrack) && (state.video || Boolean(video));
  return call;
}

function mediaFail(err) {
  const text = friendlyMediaError(err);
  showBanner(`${text} — اگر این صفحه داخل قاب باز شده، در تب جدا بازش کن.`, true, () => window.open(location.href, '_blank'));
  toast(text, 'err');
  ringer.error();
  resetAll();
}

function onPcState(s) {
  if (s === 'connected') onConnected();
  else if (s === 'failed') {
    toast('اتصال ناپایدار شد؛ تلاش برای بازیابی…', 'err');
    state.call?.restartIce();
  } else if (s === 'disconnected') {
    setStatus('اتصال ضعیف…');
  }
}

function onConnected() {
  if (state.phase === 'active') return;
  clearTimeout(state.timers.offer);
  state.phase = 'active';
  state.startedAt = Date.now();
  el.callScreen.dataset.state = 'active';
  setStatus('در حال گفتگو');
  hideBanner();
  ringer.connected();
  state.call?.setMicEnabled(true);
  state.call?.announceMedia();
  startClock();
  startLevelMeter();
  startStats();
  paintLocalVideo();
  paintRemoteVideo();
  updateQualityBadge();
  requestWakeLock();
  document.title = 'در حال تماس — بیشماره';
}

function attachRemote(stream) {
  const count = stream.getTracks().length;
  if (el.remoteVideo.srcObject !== stream || el.remoteVideo._trackCount !== count) {
    el.remoteVideo.srcObject = null;
    el.remoteVideo.srcObject = stream;
    el.remoteVideo._trackCount = count;
    el.remoteVideo.muted = false;
    el.remoteVideo.volume = 1;
  }
  el.remoteVideo.play().catch(() => { el.btnPlayAudio.hidden = false; });
  paintRemoteVideo();
}

function paintRemoteVideo() {
  const stream = el.remoteVideo.srcObject;
  const track = stream ? stream.getVideoTracks()[0] : null;
  const live = Boolean(track && track.readyState === 'live' && !track.muted && !state.videoHidden);
  el.callScreen.classList.toggle('has-remote-video', live);
  if (track) {
    track.onunmute = paintRemoteVideo;
    track.onmute = paintRemoteVideo;
  }
}

function paintLocalVideo() {
  const camOn = Boolean(state.call?.camOn);
  if (camOn) {
    el.localVideo.hidden = false;
    if (el.localVideo.srcObject !== state.call.localStream) el.localVideo.srcObject = state.call.localStream;
    el.localVideo.play().catch(() => {});
  } else {
    el.localVideo.hidden = true;
  }
  const btn = $('[data-act="camera"]');
  if (btn) {
    btn.classList.toggle('off', !camOn);
    btn.querySelector('use').setAttribute('href', camOn ? '#i-video' : '#i-video-off');
    btn.querySelector('span').textContent = camOn ? 'دوربین روشن' : 'دوربین';
  }
  $('[data-act="flip"]').hidden = !camOn;
}

function onPeerMedia(m) {
  state.videoHidden = !m.cam;
  paintRemoteVideo();
  if (state.phase !== 'active') return;
  if (m.mic === false) setStatus('میکروفون طرف مقابل بسته است');
  else if (m.cam === false) setStatus('دوربین طرف مقابل خاموش است');
  else setStatus('در حال گفتگو');
}

function paintPeer() {
  const p = state.peer || {};
  el.callName.textContent = p.name || 'کاربر بیشماره';
  el.callNumber.textContent = p.id ? fmtId(p.id) : '';
  setAvatar(p.id ? initial(p.name) : '؟');
}

function setAvatar(text) {
  el.callAvatar.textContent = text;
  el.bigAvatar.textContent = text;
}

const setStatus = (text) => { el.callStatus.textContent = text; };

/* ───────── صفحه‌ی تماس ───────── */

function showCallScreen(phase) {
  el.callScreen.hidden = false;
  el.callScreen.dataset.state = phase;
  const isIncoming = phase === 'incoming';
  const showControls = !isIncoming;

  $('[data-act="accept"]').hidden = !isIncoming;
  $('[data-act="reject"]').hidden = !isIncoming;
  $('[data-act="hangup"]').hidden = isIncoming;
  $('[data-act="mute"]').hidden = !showControls;
  $('[data-act="camera"]').hidden = !showControls;
  $('[data-act="flip"]').hidden = true;
  $('[data-act="stats"]').hidden = phase === 'outgoing' || isIncoming;

  el.callTimer.textContent = '00:00';
  el.callQuality.hidden = true;
  el.statsPanel.hidden = true;
  el.btnPlayAudio.hidden = true;
  el.callScreen.classList.remove('has-remote-video');
  el.wave.classList.remove('live');
  el.wave.classList.add('on');
  el.localVideo.hidden = true;
  document.body.style.overflow = 'hidden';

  if (isIncoming) $('[data-act="accept"] span').textContent = state.invite ? 'پیوستن' : 'پاسخ';
  if (state.dialTarget) $('[data-act="accept"] span').textContent = 'تماس';

  const muteBtn = $('[data-act="mute"]');
  muteBtn.classList.remove('off');
  muteBtn.querySelector('use').setAttribute('href', '#i-mic');
  muteBtn.querySelector('span').textContent = 'بی‌صدا';
}

function hideCallScreen() {
  el.callScreen.hidden = true;
  el.callScreen.dataset.state = 'idle';
  el.wave.classList.remove('on', 'live');
  el.remoteVideo.srcObject = null;
  el.localVideo.srcObject = null;
  el.localVideo.hidden = true;
  el.statsPanel.hidden = true;
  el.btnPlayAudio.hidden = true;
  document.body.style.overflow = '';
  document.title = 'بیشماره — تماس بدون سیم‌کارت';
}

function startClock() {
  clearInterval(state.timers.clock);
  el.callTimer.textContent = '00:00';
  state.timers.clock = setInterval(() => {
    el.callTimer.textContent = fmtTime(Date.now() - state.startedAt);
  }, 1000);
}

function startLevelMeter() {
  clearInterval(state.timers.level);
  const live = Boolean(state.call?.analyser);
  el.wave.classList.toggle('live', live);
  const bars = $$('i', el.wave);
  state.timers.level = setInterval(() => {
    const lvl = state.call?.sampleLevel() || 0;
    if (!live) return;
    bars.forEach((b, i) => {
      const f = [0.5, 0.86, 0.68, 1, 0.78, 0.92, 0.56][i] || 0.7;
      b.style.height = `${Math.max(6, 6 + lvl * 30 * f).toFixed(1)}px`;
    });
  }, 90);
}

async function startStats() {
  clearInterval(state.timers.stats);
  const tick = async () => {
    if (state.phase !== 'active') return;
    const s = await state.call?.collectStats();
    if (!s) return;
    state.lastStats = s;
    updateQualityBadge();
    if (!el.statsPanel.hidden) renderStats(s);
  };
  state.timers.stats = setInterval(tick, 2000);
  tick();
}

function qualityOf(s) {
  if (!s) return { label: 'در حال سنجش', cls: '' };
  if (s.loss > 6 || (s.rtt !== null && s.rtt > 400)) return { label: 'ضعیف', cls: 'bad' };
  if (s.loss > 1.5 || (s.rtt !== null && s.rtt > 180)) return { label: 'متوسط', cls: 'warn' };
  return { label: 'عالی', cls: '' };
}

function updateQualityBadge() {
  const q = qualityOf(state.lastStats);
  el.callQuality.hidden = state.phase !== 'active';
  el.callQuality.className = `quality ${q.cls}`;
  el.qualityText.textContent = `کیفیت: ${q.label}`;
}

function pathLabel(s) {
  const t = s?.localType || s?.remoteType;
  if (t === 'relay') return 'رله (TURN)';
  if (t === 'srflx' || t === 'prflx') return 'مستقیم — از NAT عبور کرد';
  if (t === 'host') return 'مستقیم — شبکه‌ی محلی';
  return 'در حال تعیین';
}

function renderStats(s) {
  if (!s) {
    el.statsPanel.innerHTML = '<div class="stats-foot">در حال جمع‌آوری آمار…</div>';
    return;
  }
  el.statsPanel.innerHTML = `
    <div class="stats-grid">
      <div class="stat"><span>دریافت</span><b>${faDigits(s.kbpsIn)} kbps</b></div>
      <div class="stat"><span>ارسال</span><b>${faDigits(s.kbpsOut)} kbps</b></div>
      <div class="stat"><span>تأخیر (RTT)</span><b>${s.rtt === null ? '—' : faDigits(s.rtt) + ' ms'}</b></div>
      <div class="stat"><span>افت بسته</span><b>${faDigits(s.loss)}٪</b></div>
      <div class="stat"><span>لرزش</span><b>${faDigits(s.jitter)} ms</b></div>
      <div class="stat"><span>کدک</span><b dir="ltr">${s.codec || '—'}</b></div>
    </div>
    <div class="stats-foot">مسیر: ${pathLabel(s)}<br>${
      state.hasTurn
        ? 'سرور رله (TURN) روی این سرور فعال است.'
        : 'بدون TURN؛ اگر شبکه‌ی هر دو طرف سخت باشد ممکن است تماس وصل نشود.'
    }</div>`;
}

/* ───────── اعلان پوش: زنگ خوردن وقتی برنامه بسته است ───────── */

function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

function onPushRinging(msg) {
  state.callId = msg.callId;
  state.room = msg.room;
  state.dir = 'push';
  if (msg.to) state.peer = msg.to;
  state.phase = 'outgoing';
  if (!el.callScreen.hidden) {
    paintPeer();
    setStatus('زنگ زدیم و برای طرف مقابل اعلان فرستادیم…');
  }
}

async function getPushSubscription() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return null;
  try {
    const reg = await navigator.serviceWorker.getRegistration();
    if (!reg) return null;
    return await reg.pushManager.getSubscription();
  } catch { return null; }
}

async function refreshPushSwitch() {
  if (!el.setPush) return;
  const sub = await getPushSubscription();
  el.setPush.setAttribute('aria-checked', String(Boolean(sub)));
}

/** بعد از هر اتصال، اشتراک موجود را دوباره به سرور معرفی می‌کنیم (شماره عوض شده باشد) */
async function resendPushSubscription() {
  const sub = await getPushSubscription();
  if (sub) sig.send({ t: 'push', subscription: sub.toJSON() });
}

async function togglePush() {
  const isOn = el.setPush.getAttribute('aria-checked') === 'true';

  if (isOn) {
    try {
      const sub = await getPushSubscription();
      await sub?.unsubscribe();
    } catch { /* noop */ }
    el.setPush.setAttribute('aria-checked', 'false');
    toast('اعلان تماس خاموش شد.');
    return;
  }

  if (!('Notification' in window) || !('PushManager' in window) || !('serviceWorker' in navigator)) {
    toast('این مرورگر اعلان پوش را پشتیبانی نمی‌کند.', 'err');
    return;
  }
  if (!state.vapidKey) {
    toast('سرور اعلان پوش را فعال نکرده است.', 'err');
    return;
  }

  try {
    const perm = await Notification.requestPermission();
    if (perm !== 'granted') {
      toast('اجازه‌ی اعلان داده نشد.', 'err');
      return;
    }
    const reg = await navigator.serviceWorker.ready;
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(state.vapidKey),
      });
    }
    sig.send({ t: 'push', subscription: sub.toJSON() });
    el.setPush.setAttribute('aria-checked', 'true');
    toast('آماده شد ✓ از این به بعد حتی با بسته بودن برنامه هم زنگ می‌خورد.');
  } catch (err) {
    toast(`ساخت اشتراک اعلان ناموفق بود: ${err.message || ''}`, 'err');
  }
}

/* ───────── پایان تماس ───────── */


function endCall(reason, remote = false) {
  if (state.phase === 'idle' && !state.call) return;
  const wasActive = state.phase === 'active';
  const dur = wasActive ? Date.now() - state.startedAt : 0;

  ringer.stop();
  if (!remote) sig.send({ t: 'hangup', callId: state.callId });

  if (state.peer?.id) {
    addRecent({
      id: state.peer.id,
      name: state.peer.name || 'کاربر بیشماره',
      dir: state.dir === 'in' ? 'in' : 'out',
      at: Date.now(),
      dur,
      video: state.video,
    });
    renderRecents();
  }

  teardown();
  hideCallScreen();
  resetAll();
  if (reason) toast(reason);
  if (!remote) ringer.ended();
}

function teardown() {
  clearInterval(state.timers.clock);
  clearInterval(state.timers.level);
  clearInterval(state.timers.stats);
  clearTimeout(state.timers.offer);
  state.timers = { clock: null, level: null, stats: null, offer: null };
  try { state.call?.close(); } catch { /* noop */ }
  state.call = null;
  releaseWakeLock();
}

function resetAll() {
  state.phase = 'idle';
  state.peer = null;
  state.callId = null;
  state.room = null;
  state.invite = null;
  state.dialTarget = null;
  state.startedAt = 0;
  state.lastStats = null;
  state.videoHidden = false;
  state.mediaLock = false;
  state.dir = 'out';
  resetLinkUi();
  if (sig.state === 'open') setPill('open');
  else setPill(sig.state);
}

/* ───────── دکمه‌های تماس ───────── */

$('#callControls').addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-act]');
  if (!btn) return;
  const act = btn.dataset.act;

  if (act === 'accept') { clearIncomingNote(); return acceptCall(); }

  if (act === 'reject') {
    ringer.stop();
    clearIncomingNote();
    if (state.dialTarget) {
      state.dialTarget = null;
      hideCallScreen();
      resetAll();
      return;
    }
    if (state.dir === 'link' && state.invite) {
      state.invite = null;
      hideCallScreen();
      resetAll();
      toast('دعوت رد شد.');
      return;
    }
    sig.send({ t: 'reject', callId: state.callId });
    endCall('تماس رد شد.');
    return;
  }

  if (act === 'hangup') {
    clearIncomingNote();
    if (state.phase === 'waiting' && state.dir === 'link') return cancelLink();
    return endCall(state.phase === 'active' ? 'تماس پایان یافت.' : 'تماس لغو شد.');
  }

  if (!state.call) return;

  if (act === 'mute') {
    const next = !state.call.micOn;
    state.call.setMicEnabled(next);
    btn.classList.toggle('off', !next);
    btn.querySelector('use').setAttribute('href', next ? '#i-mic' : '#i-mic-off');
    btn.querySelector('span').textContent = next ? 'بی‌صدا' : 'صدا روشن';
    return;
  }

  if (act === 'camera') {
    try {
      const next = !state.call.camOn;
      await state.call.setCameraEnabled(next);
      if (next) state.video = true;
      paintLocalVideo();
      paintRemoteVideo();
    } catch (err) {
      toast(friendlyMediaError(err), 'err');
    }
    return;
  }

  if (act === 'flip') {
    try {
      const next = state.call.facing === 'user' ? 'environment' : 'user';
      await state.call.openCamera(next);
      state.call.facing = next;
      paintLocalVideo();
    } catch (err) { toast(friendlyMediaError(err), 'err'); }
    return;
  }

  if (act === 'stats') {
    el.statsPanel.hidden = !el.statsPanel.hidden;
    if (!el.statsPanel.hidden) renderStats(state.lastStats);
    return;
  }
});

el.btnPlayAudio.addEventListener('click', () => {
  el.remoteVideo.play().catch(() => {});
  el.btnPlayAudio.hidden = true;
});

/* ───────── تب‌ها و شماره‌گیر ───────── */

$$('.tab').forEach((tab) => {
  tab.onclick = () => {
    $$('.tab').forEach((t) => t.classList.toggle('active', t === tab));
    $$('.pane').forEach((p) => p.classList.toggle('active', p.dataset.pane === tab.dataset.tab));
  };
});

$$('.mode').forEach((m) => {
  m.onclick = () => {
    $$('.mode').forEach((x) => x.classList.toggle('active', x === m));
    state.video = m.dataset.video === '1';
  };
});

el.dialpad.addEventListener('click', (e) => {
  const b = e.target.closest('button');
  if (!b) return;
  const k = b.dataset.k;
  if (k === 'del') state.typing = state.typing.slice(0, -1);
  else if (k === '*') return;
  else if (state.typing.length < 8) state.typing += k;
  renderDial();
  try { navigator.vibrate?.(8); } catch { /* noop */ }
});

function renderDial() {
  el.dialDigits.textContent = state.typing ? faDigits(state.typing.replace(/(\d{3})(?=\d)/g, '$1 ')) : '';
  const known = presenceById(state.typing);
  if (state.typing.length >= 5 && known) {
    el.dialHint.textContent = `${known.name} آنلاین است`;
    el.dialHint.style.color = 'var(--accent)';
  } else if (state.typing.length >= 5) {
    el.dialHint.textContent = 'این شماره آنلاین نیست';
    el.dialHint.style.color = 'var(--muted-2)';
  } else {
    el.dialHint.textContent = 'شماره‌ی ۶ رقمی طرف مقابل';
    el.dialHint.style.color = '';
  }
}

function dialTyped() {
  const id = enDigits(state.typing).replace(/\D/g, '');
  if (id.length < 5) {
    toast('شماره باید حداقل ۵ رقم باشد.', 'err');
    return null;
  }
  state.typing = '';
  renderDial();
  return id;
}

el.btnDial.onclick = () => {
  const id = dialTyped();
  if (id) startOutgoing({ id, name: presenceById(id)?.name || 'کاربر بیشماره' }, false);
};

el.btnVideoDial.onclick = () => {
  el.btnVideoDial.classList.toggle('active');
  state.dialVideo = el.btnVideoDial.classList.contains('active');
  const id = dialTyped();
  if (id) startOutgoing({ id, name: presenceById(id)?.name || 'کاربر بیشماره' }, true);
  else toast('شماره را وارد کن، بعد دکمه‌ی دوربین را بزن.', 'err');
};

el.btnNewLink.onclick = () => { ensureNotifyPermission(); createLink(); };
el.btnCopyLink.onclick = copyLink;
el.btnShareLink.onclick = shareLink;
el.btnOpenLink.onclick = () => { if (state.linkRoom) window.open(linkFor(state.linkRoom), '_blank'); };

/* ───────── تماس‌های اخیر ───────── */

function renderRecents() {
  const list = (store.recents || []).slice(0, 8);
  el.recentCard.hidden = list.length === 0;
  el.recentList.innerHTML = '';
  for (const r of list) {
    const when = new Date(r.at);
    const stamp = `${faDigits(String(when.getHours()).padStart(2, '0'))}:${faDigits(String(when.getMinutes()).padStart(2, '0'))}`;
    const li = document.createElement('li');
    li.innerHTML = `
      <span class="ava">${initial(r.name)}</span>
      <span class="who">
        <b></b>
        <span>${r.dir === 'in' ? '↙' : '↗'} <span dir="ltr">${fmtId(r.id)}</span> · ${stamp}${r.dur ? ' · ' + faDigits(fmtTime(r.dur)) : ''}</span>
      </span>
      <span class="act"><button class="audio" aria-label="تماس"><svg><use href="#i-phone"/></svg></button></span>`;
    $('.who b', li).textContent = r.name;
    $('.audio', li).onclick = () => startOutgoing({ id: r.id, name: r.name }, Boolean(r.video));
    el.recentList.appendChild(li);
  }
}

/* ───────── تنظیمات ───────── */

const linkForId = (id) => `${location.origin}${location.pathname}?to=${id}`;

function openSheet() {
  el.sheet.hidden = false;
  el.setName.value = store.name || '';
  el.myLink.value = state.id ? linkForId(state.id) : '';
  if (el.btnInstall) el.btnInstall.hidden = !deferredPrompt;
  if (el.iosInstallHint) el.iosInstallHint.hidden = !(isIOSDevice && !navigator.standalone);
  syncSwitches();
  updateSheetInfo();
  fillDevices();
}

const closeSheet = () => { el.sheet.hidden = true; };

function syncSwitches() {
  el.setRing.setAttribute('aria-checked', String(Boolean(store.ring)));
  el.setSticky.setAttribute('aria-checked', String(Boolean(store.sticky)));
}

async function fillDevices() {
  try {
    const devices = await navigator.mediaDevices.enumerateDevices();
    const mics = devices.filter((d) => d.kind === 'audioinput');
    const cams = devices.filter((d) => d.kind === 'videoinput');
    el.setMic.innerHTML = '<option value="">پیش‌فرض دستگاه</option>' +
      mics.map((d, i) => `<option value="${d.deviceId}">${d.label || 'میکروفون ' + faDigits(i + 1)}</option>`).join('');
    el.setCam.innerHTML = '<option value="">پیش‌فرض دستگاه</option>' +
      cams.map((d, i) => `<option value="${d.deviceId}">${d.label || 'دوربین ' + faDigits(i + 1)}</option>`).join('');
    el.setMic.value = store.micId || '';
    el.setCam.value = store.camId || '';
  } catch { /* دسترسی نداریم */ }
}

function updateSheetInfo() {
  el.sheetInfo.innerHTML = `
    شماره‌ی تو: <b>${fmtId(state.id)}</b><br>
    سرور: <b dir="ltr">${location.host}</b><br>
    مسیر سیگنالینگ: <b>${sig.mode === 'sse' ? 'SSE (پشتیبان)' : 'WebSocket'}</b><br>
    سرور رله (TURN): <b>${state.hasTurn ? 'فعال' : 'غیرفعال'}</b><br>
    نسخه: <b>۱٫۰</b>`;
}

el.btnSettings.onclick = openSheet;
el.btnIdMenu.onclick = openSheet;
$$('[data-close]').forEach((b) => { b.onclick = closeSheet; });

el.setName.oninput = () => {
  save({ name: el.setName.value.trim().slice(0, 24) });
  renderMe();
  sig.send({ t: 'setName', name: store.name });
};

el.btnCopyMyLink.onclick = async () => {
  try {
    await navigator.clipboard.writeText(el.myLink.value);
    toast('لینک تماس مستقیم کپی شد ✓');
  } catch {
    el.myLink.select();
    document.execCommand?.('copy');
    toast('لینک انتخاب شد — کپی کن.');
  }
};

el.setPush.onclick = togglePush;
el.setMic.onchange = () => save({ micId: el.setMic.value });
el.setCam.onchange = () => save({ camId: el.setCam.value });

el.setRing.onclick = () => {
  save({ ring: !store.ring });
  ringer.setEnabled(store.ring);
  syncSwitches();
};

el.setSticky.onclick = () => {
  save({ sticky: !store.sticky, myId: store.sticky ? '' : state.id });
  syncSwitches();
  toast(store.sticky ? 'شماره روی این دستگاه ثابت شد.' : 'هر بار شماره‌ی تازه می‌گیری.');
};

el.btnReset.onclick = () => {
  clearAll();
  toast('پاک شد؛ صفحه بازخوانی می‌شود…');
  setTimeout(() => location.reload(), 700);
};

/* ───────── کد دسترسی ───────── */

function openGate() {
  el.codeGate.hidden = false;
  el.codeInput.value = store.code || '';
  el.codeInput.focus();
}

el.btnCode.onclick = () => {
  save({ code: el.codeInput.value.trim() });
  el.codeGate.hidden = true;
  hello();
  toast('در حال ورود…');
};
el.codeInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') el.btnCode.click(); });

/* ───────── بنر، توست، Wake Lock ───────── */

function showBanner(text, bad = false, onClick = null) {
  el.banner.hidden = false;
  el.banner.textContent = text;
  el.banner.className = `banner ${bad ? 'bad' : ''}`;
  el.banner.style.cursor = onClick ? 'pointer' : '';
  el.banner.onclick = onClick;
}
const hideBanner = () => { el.banner.hidden = true; };

let toastTimer = null;
function toast(text, kind = '') {
  el.toast.hidden = false;
  el.toast.textContent = text;
  el.toast.className = `toast show ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    el.toast.classList.remove('show');
    setTimeout(() => { el.toast.hidden = true; }, 320);
  }, 3400);
}

let wakeLock = null;
async function requestWakeLock() {
  try { if ('wakeLock' in navigator) wakeLock = await navigator.wakeLock.request('screen'); } catch { /* noop */ }
}
function releaseWakeLock() {
  try { wakeLock?.release(); } catch { /* noop */ }
  wakeLock = null;
}

/* ───────── راه‌اندازی ───────── */

function checkEnvironment() {
  if (!window.isSecureContext) {
    showBanner('این صفحه روی HTTPS نیست. مرورگرها فقط در HTTPS اجازه‌ی میکروفون می‌دهند.', true);
  } else if (!navigator.mediaDevices?.getUserMedia) {
    showBanner('مرورگر تو از تماس صوتی پشتیبانی نمی‌کند. Chrome، Safari یا Firefox جدید را امتحان کن.', true);
  }
  if (window.self !== window.top) {
    showBanner('این صفحه داخل یک قاب باز شده. اگر میکروفون اجازه نگرفت، همین‌جا بزن تا در تب جدا باز شود.', false,
      () => window.open(location.href, '_blank'));
  }
}

window.addEventListener('beforeunload', () => {
  try { if (state.phase !== 'idle') sig.send({ t: 'hangup', callId: state.callId }); } catch { /* noop */ }
});

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') {
    if (sig.state === 'closed') sig.connect();
    if (state.phase === 'idle') document.title = 'بیشماره — تماس بدون سیم‌کارت';
  }
});

ringer.setEnabled(Boolean(store.ring));
document.addEventListener('pointerdown', () => ringer.prime(), { once: true });
renderMe();
renderRecents();
setPill('idle');
checkEnvironment();
updateSheetInfo();

/* ───────── نصب برنامه (PWA) ───────── */

let deferredPrompt = null;

window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredPrompt = e;
  if (el.btnInstall) el.btnInstall.hidden = false;
});

if (el.btnInstall) {
  el.btnInstall.onclick = async () => {
    if (!deferredPrompt) return;
    try {
      deferredPrompt.prompt();
      await deferredPrompt.userChoice;
    } catch { /* noop */ }
    deferredPrompt = null;
    el.btnInstall.hidden = true;
  };
}

const isIOSDevice = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
if (el.iosInstallHint && isIOSDevice && !navigator.standalone) el.iosInstallHint.hidden = false;

/* ثبت سرویس‌ورکر (نصب روی صفحه‌ی اصلی + باز شدن آفلاینِ پوسته) */
if ('serviceWorker' in navigator && window.isSecureContext) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('sw.js').catch(() => {});
  });
}
