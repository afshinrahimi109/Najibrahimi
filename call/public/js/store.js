/* ذخیره‌سازی محلی — همه‌چیز روی دستگاه خودِ کاربر می‌ماند */

const KEY = 'bishomare.v1';

const DEFAULTS = {
  name: '',
  myId: '',        // شماره‌ی ثابت روی این دستگاه
  cid: '',         // شناسه‌ی اتصال (برای انتقال پشتیبان SSE)
  code: '',        // کد دسترسی سرور (اگر خصوصی باشد)
  ring: true,
  sticky: true,
  micId: '',
  camId: '',
  video: false,
  recents: [],
  friends: [],
};

function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

function read() {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || '{}');
    return { ...DEFAULTS, ...raw };
  } catch {
    return { ...DEFAULTS };
  }
}

export const store = read();
if (!store.cid) store.cid = uuid();
if (!Array.isArray(store.recents)) store.recents = [];
persist();

export function persist() {
  try { localStorage.setItem(KEY, JSON.stringify(store)); } catch { /* حالت ناشناس */ }
}

export function save(patch = {}) {
  Object.assign(store, patch);
  persist();
  return store;
}

export function addRecent(entry) {
  const list = store.recents.filter((r) => !(r.id === entry.id && Date.now() - r.at < 5000));
  list.unshift(entry);
  store.recents = list.slice(0, 12);
  persist();
}

export function clearAll() {
  try { localStorage.removeItem(KEY); } catch { /* noop */ }
}
