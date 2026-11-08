/*
 * Service Worker — فقط برای «نصب‌پذیر شدن» و باز شدن پوسته‌ی برنامه در حالت آفلاین.
 * استراتژی: شبکه اول، کش پشتیبان. بنابراین نسخه‌ی تازه همیشه اولویت دارد
 * و بعد از هر deploy، تغییرات فوراً دیده می‌شوند.
 */

const CACHE = 'bishomare-v1';
const SHELL = [
  './',
  './index.html',
  './style.css',
  './js/app.js',
  './js/call.js',
  './js/signal.js',
  './js/store.js',
  './js/ring.js',
  './manifest.webmanifest',
  './icons/icon-192.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname === '/ws') return;

  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        }
        return res;
      })
      .catch(() => caches.match(req).then((hit) => hit || caches.match('./index.html')))
  );
});

/* ─────────────────────────────────────────────
   اعلان تماس (Web Push)
   وقتی برنامه بسته است، این بخش نوتیفیکیشن «تماس ورودی» را نشان می‌دهد
   و با زدن روی آن، برنامه را با لینک همان تماس باز می‌کند.
   ───────────────────────────────────────────── */

self.addEventListener('push', (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data ? event.data.text() : '' };
  }

  const room = data.room || '';
  const target = new URL(room ? `./?c=${room}` : './', self.registration.scope).href;

  event.waitUntil(
    self.registration.showNotification(data.title || '📞 تماس ورودی — بی‌شماره', {
      body: data.body || 'یک تماس ورودی داری',
      icon: './icons/icon-192.png',
      badge: './icons/icon-192.png',
      tag: 'bishomare-call',
      renotify: true,
      requireInteraction: true,
      vibrate: [420, 180, 420, 700, 420, 180, 420],
      data: { url: target, room },
      actions: [
        { action: 'open', title: 'پاسخ' },
        { action: 'close', title: 'رد' },
      ],
    }).catch(() => {})
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  if (event.action === 'close') return;

  const raw = event.notification.data?.url || self.registration.scope;
  const target = new URL(raw, self.registration.scope).href;

  event.waitUntil((async () => {
    const list = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    const sameOrigin = list.filter((c) => c.url.startsWith(self.location.origin));
    // اگر برنامه از قبل باز است، همان را جلو می‌آوریم و به لینک تماس می‌بریم
    if (sameOrigin.length) {
      const client = sameOrigin[0];
      try {
        if (client.navigate && client.url !== target) await client.navigate(target);
        await client.focus();
        return;
      } catch { /* برو سراغ باز کردن پنجره‌ی تازه */ }
    }
    await self.clients.openWindow(target);
  })());
});
