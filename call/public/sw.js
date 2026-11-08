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
