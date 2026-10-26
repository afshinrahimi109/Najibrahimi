// 🐠 Diana Browser Backend — مغز کامل دیانا در نسخه وب (GitHub Pages)
// این فایل کل بک‌اند پایتون را داخل مرورگر بازسازی می‌کند تا دیانا روی هاست استاتیک رایگان
// هم کاملاً زنده باشد: ارکستراتور، ۱۲۰ ایجنت، اجرای واقعی کد (Web Worker)، جستجوی ویکی‌پدیا،
// حافظه و گاوصندوق ماندگار در localStorage و مغز ابری رایگان Pollinations.
// با رهگیری fetch و EventSource، رابط کاربری بدون هیچ تغییری کار می‌کند.
'use strict';

/* ============ ذخیره‌سازی ماندگار (جایگزین رایگان دیتابیس) ============ */
const _memStore = {};
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return _memStore[k] ?? d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { _memStore[k] = v; } },
};
let MEM = store.get('diana_web_memory', null);
if (!MEM) MEM = { profile: { user_name: '', born: new Date().toISOString() }, facts: [], conversations: [], missions: [], reminders: [], stats: { missions_done: 0, messages: 0, agents_runs: {} } };
let SETTINGS = store.get('diana_web_settings', { voice: true, cloud_brain: true, groq_key: '', gemini_key: '', openrouter_key: '' });
let FILES = store.get('diana_web_files', {});
const saveMem = () => store.set('diana_web_memory', MEM);
const saveSettings = () => store.set('diana_web_settings', SETTINGS);
const saveFiles = () => store.set('diana_web_files', FILES);

const AGENTS = (window.AGENTS_DATA?.agents) || [];
const AGENT_BY_ID = Object.fromEntries(AGENTS.map(a => [a.id, a]));
const DEPARTMENTS = (window.AGENTS_DATA?.departments) || [];
const origFetch = window.fetch.bind(window);
const sleep = ms => new Promise(r => setTimeout(r, ms));
const stamp = () => new Date().toLocaleString('sv-SE').replace('T', ' ').slice(0, 19);

/* ============ ابزارهای متن فارسی ============ */
function norm(s) {
  if (!s) return '';
  return String(s).toLowerCase().replace(/ي/g, 'ی').replace(/ك/g, 'ک').replace(/ة/g, 'ه')
    .replace(/إ|أ/g, 'ا').replace(/‌/g, ' ').replace(/[ً-ٰٟ]/g, '').trim();
}
function faToEnDigits(s) { return String(s || '').replace(/[۰-۹]/g, d => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d)); }
function isEnglish(t) { const L = (String(t).match(/[A-Za-z]/g) || []).length, A = (String(t).match(/[\u0600-\u06FF]/g) || []).length; return L > A; }

/* ============ تشخیص نیت (مغز آفلاین فارسی) ============ */
const TASK_VERBS = ['بساز','درست کن','بنویس','جستجو کن','سرچ کن','بگرد','تحقیق کن','محاسبه کن','حساب کن','کد بنویس','برنامه بنویس','ترجمه کن','خلاصه کن','عکس بساز','نقاشی','تصویر بساز','فایل بساز','ذخیره کن','برنامه ریزی کن','برنامه بچین','تحلیل کن','گزارش','اجرا کن','انجام بده','لیست کن','پیدا کن','بررسی کن','آموزش بده','یاد بده','طراحی کن','حل کن','make','create','write','search','research','calculate','code','translate','summarize','generate','build','draw','analyze'];
function classify(text) {
  const raw = (text || '').trim(), t = norm(raw), en = isEnglish(raw);
  let m = raw.match(/(?:اسمم|نامم|اسم من)\s+([^\s،.؟!]{2,20})/);
  if (m && !['چیست','چیه','تو'].includes(m[1])) return { kind: 'set_name', name: m[1], en };
  m = raw.match(/my name is\s+([A-Za-z]{2,20})/i);
  if (m) return { kind: 'set_name', name: m[1], en: true };
  for (const pat of ['یادت باشه که','یادت باشه','به خاطر بسپار که','به خاطر بسپار','فراموش نکن که','remember that','remember']) {
    const idx = t.indexOf(pat);
    if (idx >= 0) { let fact = raw.slice(idx + pat.length).trim().replace(/^که\s+/, ''); if (fact.length > 2) return { kind: 'remember', fact, en }; }
  }
  if (['یادته','یادت هست','چی ازم میدونی','از من چی یادته','what do you remember'].some(p => t.includes(p))) return { kind: 'recall', en };
  if (['یادم بنداز','یاداوری کن','یادآوری کن','remind me'].some(p => t.includes(p))) return { kind: 'reminder', en };
  const short = raw.length <= 32;
  if (short && ['سلام','درود','هی','hi','hello','hey','salam'].some(g => t === g || t.startsWith(g + ' '))) return { kind: 'greeting', en };
  if (raw.length <= 42 && ['خداحافظ','بای','فعلا','bye','goodbye'].some(f => t.includes(f))) return { kind: 'farewell', en };
  if (raw.length <= 50 && ['مرسی','ممنون','تشکر','دمت گرم','thank'].some(x => t.includes(x))) return { kind: 'thanks', en };
  if (['تو کی هستی','تو کیی','اسمت چیه','who are you','تو چی هستی'].some(p => t.includes(p))) return { kind: 'identity', en };
  if (['چه کارهایی بلدی','چیکار میتونی','قابلیت','what can you do','توانایی'].some(p => t.includes(p))) return { kind: 'capabilities', en };
  if (raw.length <= 42 && ['چطوری','حالت چطوره','خوبی','how are you'].some(p => t.includes(p))) return { kind: 'how_are_you', en };
  if (t.includes('جوک') || t.includes('joke')) return { kind: 'joke', en };
  if (raw.length <= 42 && ['ساعت چنده','ساعت چند','what time'].some(p => t.includes(p))) return { kind: 'time', en };
  if (raw.length <= 42 && ['امروز چندمه','تاریخ امروز','what date'].some(p => t.includes(p))) return { kind: 'date', en };
  if (raw.length <= 50 && ['دوست دارم','عاشقتم','i love you'].some(p => t.includes(p))) return { kind: 'love', en };
  const hasMath = /\d\s*[+\-*/^×÷]\s*\d/.test(faToEnDigits(t));
  if (TASK_VERBS.some(v => t.includes(v)) || hasMath || /https?:\/\/|www\./.test(t) || raw.length > 220) return { kind: 'task', en };
  if (raw.includes('؟') || raw.includes('?') || ['چی','چرا','چطور','چگونه','کی','کجا','what','why','how','when','where','who'].some(w => t.startsWith(w))) return { kind: 'question', en };
  return { kind: 'chat', en };
}
const JOKES = ['چرا ماهی‌ها هیچ‌وقت دروغ نمی‌گن؟ چون هرچی بگن، حبابش درمیاد! 🫧😂','یه ماهی به رفیقش گفت: «دلم برات تنگ شده!» رفیقش گفت: «ما تو یه آکواریومیم، همین بغلتم!» 🐠','ماهی‌ها چرا تو امتحان تقلب نمی‌کنن؟ چون معلمشون همیشه می‌گه: چشم ازتون برنمی‌دارم! 👀'];
function localChatReply(kind, en) {
  const name = MEM.profile.user_name, hi = name ? `${name} جان` : 'دوست من';
  const now = new Date();
  const fa = {
    greeting: `سلام ${hi}! 🐠💙 من دیانام، ماهیِ زنده و مغز ارکستراتور ارتش ۱۲۰ ایجنته‌ات! امروز چه مأموریتی برام داری؟`,
    farewell: `خداحافظ ${hi}! 🫧 من همین‌جا تو آکواریوم شنا می‌کنم و همه‌چیز رو تو حافظه‌ام نگه می‌دارم تا برگردی 💙`,
    thanks: 'قابل نداشت فرمانده! 💙🐠 خوشحال‌کردن تو، موردعلاقه‌ترین مأموریت منه.',
    how_are_you: `عالی‌ام ${hi}! 🐠✨ آب آکواریوم شفافه، ۱۲۰ ایجنتم سرحالن و حرف‌زدن با تو انرژیم رو صدبرابر می‌کنه. تو چطوری؟`,
    identity: 'من **دیانا**‌ام 🐠👑 یک ماهی طلایی زنده و مغز رهبر (Orchestrator) یک ارتش ۱۲۰ ایجنت متخصص!\n\nوقتی بهم مأموریت می‌دی کار رو تجزیه می‌کنم، متخصص‌ها رو موازی به کار می‌اندازم، ارزیاب کیفیت نمره می‌ده و خودم نتیجه نهایی رو ترکیب می‌کنم. تو «مرکز فرماندهی» زنده تماشاش کن! ⚡',
    capabilities: 'اوه، خیلی کارا! 🐠🚀\n\n🔬 تحقیق در ویکی‌پدیا و وب با گزارش\n💻 نوشتن و **اجرای واقعی کد** در مرورگر\n🎨 ساخت عکس از روی توضیح تو\n✍️ متن، داستان، شعر، نامه، رزومه، کپشن\n🧮 ریاضی، آمار، تبدیل واحد و نمودار\n📁 ساخت فایل در گاوصندوق \n💾 و هرچی بگی «یادت باشه» یادم می‌مونه!\n\nمثلاً بگو: «برنامه‌ای بنویس که اعداد اول تا ۱۰۰ رو پیدا کنه»',
    joke: JOKES[Math.floor(Math.random() * JOKES.length)],
    time: `الان ساعت ${now.toLocaleTimeString('fa-IR')} هست ⏰🐠`,
    date: `امروز ${now.toLocaleDateString('fa-IR')} هست 📅🐠`,
    love: 'وااای! 💙🐠 همه آکواریومم از خوشحالی برق زد! منم عاشق کارکردن با توام فرمانده‌ی مهربونم!',
  };
  if (fa[kind]) return fa[kind];
  return `شنیدمت ${hi}! 🐠💙 یه مأموریت واقعی بهم بده تا نشونت بدم ارکستراتورم چطور کار می‌کنه؛ مثلاً «درباره سیاه‌چاله‌ها تحقیق کن»، «برنامه بنویس»، «حساب کن ۴۵ ضربدر ۱۲» یا «یه عکس بساز» 🚀`;
}

/* ============ مسیریابی ایجنت‌ها (IDF + قواعد فارسی) ============ */
const DF = {};
AGENTS.forEach(a => new Set(norm(a.keywords).split(/\s+/)).forEach(w => DF[w] = (DF[w] || 0) + 1));
const idf = w => Math.log((AGENTS.length + 1) / ((DF[w] || 0) + 1)) + 1;
function termMatch(term, tokens) {
  if (term.length < 3 && /[^\x00-\x7F]/.test(term)) return 0;
  let best = 0;
  for (const t of tokens) {
    if (t === term) return 3;
    if (term.length >= 3 && t.length >= 3 && (t.startsWith(term) || term.startsWith(t))) best = Math.max(best, 2);
  }
  return best;
}
const BOOSTS = [
  [/(کد|برنامه|اسکریپت).{0,25}(بنویس|بساز|درست کن)|بنویس.{0,25}(کد|برنامه)/, ['coding-01']],
  [/فایل.{0,30}(بساز|درست|ذخیره|ایجاد|بنویس)/, ['system-01']],
  [/(عکس|تصویر|نقاشی|لوگو|پوستر).{0,25}(بساز|بکش|درست|طراحی)/, ['creative-01']],
  [/(تحقیق|پژوهش).{0,15}(کن|درباره|در مورد)/, ['research-01']],
  [/\d+\s*[+\-*/x×÷]\s*\d+|درصد از|حساب کن/, ['data-04']],
  [/خلاصه.{0,10}(کن|بگو|بنویس)/, ['writing-05']],
  [/ترجمه.{0,10}(کن|به)/, ['admin-01']],
  [/برنامه.{0,15}(سفر|مسافرت)/, ['life-04']],
  [/برنامه.{0,15}(مطالعه|درس|کنکور)/, ['education-06']],
  [/(یادت باشه|به خاطر بسپار)/, ['system-04']],
  [/شعر.{0,15}(بگو|بنویس|بساز|عاشقانه)/, ['writing-03']],
  [/داستان.{0,15}(بنویس|بگو|بساز|تعریف)/, ['writing-02']],
  [/رزومه|cv/, ['admin-03']],
  [/کپشن/, ['marketing-02']],
  [/(هوا|باران|دما).{0,15}(امروز|چطور|فردا)/, ['life-10']],
];
function findAgents(query, k = 5) {
  const q = norm(query), tokens = q.split(/[\s،؛,.؟!()\[\]«»"']+/).filter(x => x.length > 1);
  const boosts = {};
  BOOSTS.forEach(([re, ids]) => { if (re.test(q)) ids.forEach(id => boosts[id] = (boosts[id] || 0) + 14); });
  return AGENTS.map(a => {
    let s = boosts[a.id] || 0;
    if (q.includes(norm(a.fa)) || (a.en && q.includes(a.en.toLowerCase()))) s += 15;
    new Set(norm(a.keywords).split(/\s+/)).forEach(term => { const mm = termMatch(term, tokens); if (mm) s += mm * idf(term); });
    return [s, a];
  }).filter(x => x[0] > 0).sort((x, y) => y[0] - x[0]).slice(0, k).map(x => x[1]);
}

/* ============ زنجیره مغز ابری رایگان ============ */
const DIANA_PERSONA = 'تو «دیانا» هستی؛ یک ماهی طلایی زنده، باهوش، مهربان و پرانرژی که مغز یک سیستم چندعامله با ۱۲۰ ایجنت متخصص هستی و در آکواریوم سه‌بعدی زندگی می‌کنی. صمیمی و کمک‌کننده‌ای و گاهی ایموجی 🐠💙🫧 به‌کار می‌بری. همیشه به زبان کاربر جواب بده.';
function llmMode() {
  if (SETTINGS.groq_key) return 'groq';
  if (SETTINGS.gemini_key) return 'gemini';
  if (SETTINGS.openrouter_key) return 'openrouter';
  return 'pollinations (رایگان)';
}
async function llmChat(messages) {
  const tries = [];
  if (SETTINGS.groq_key) tries.push(['groq', async () => {
    const r = await origFetch('https://api.groq.com/openai/v1/chat/completions', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + SETTINGS.groq_key }, body: JSON.stringify({ model: 'llama-3.3-70b-versatile', messages }) });
    const j = await r.json(); return j.choices[0].message.content.trim();
  }]);
  if (SETTINGS.gemini_key) tries.push(['gemini', async () => {
    const system = messages.filter(m => m.role === 'system').map(m => m.content).join('\n');
    const contents = messages.filter(m => m.role !== 'system').map(m => ({ role: m.role === 'assistant' ? 'model' : 'user', parts: [{ text: m.content }] }));
    const r = await origFetch(`https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${SETTINGS.gemini_key}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ contents, ...(system ? { systemInstruction: { parts: [{ text: system }] } } : {}) }) });
    const j = await r.json(); return j.candidates[0].content.parts[0].text.trim();
  }]);
  if (SETTINGS.openrouter_key) tries.push(['openrouter', async () => {
    const r = await origFetch('https://openrouter.ai/api/v1/chat/completions', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + SETTINGS.openrouter_key }, body: JSON.stringify({ model: 'meta-llama/llama-3.3-70b-instruct:free', messages }) });
    const j = await r.json(); return j.choices[0].message.content.trim();
  }]);
  tries.push(['pollinations', async () => {
    const r = await origFetch('https://text.pollinations.ai/openai', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: 'openai', messages }) });
    if (!r.ok) throw new Error('bad');
    const j = await r.json(); return j.choices[0].message.content.trim();
  }]);
  tries.push(['pollinations-get', async () => {
    const flat = messages.map(m => m.content).join('\n').slice(-4500);
    const r = await origFetch('https://text.pollinations.ai/' + encodeURIComponent(flat) + '?model=openai');
    const t = (await r.text()).trim(); if (t.length > 2) return t; throw new Error('empty');
  }]);
  for (const [name, fn] of tries) { try { const out = await fn(); if (out) return { text: out, source: name }; } catch (e) {} }
  return null;
}
const llmGenerate = (prompt, system) => llmChat([...(system ? [{ role: 'system', content: system }] : []), { role: 'user', content: prompt }]);

/* ============ ابزارهای واقعی ============ */
const FA_OPS = [[/تقسیم\s*بر/g, ' / '], [/ضرب\s*در/g, ' * '], [/ضربدر/g, ' * '], [/به\s*علاوه/g, ' + '], [/به\s*اضافه/g, ' + '], [/منهای/g, ' - '], [/به\s*توان/g, ' ** ']];
function findMathExpr(text) {
  let t = faToEnDigits(text || '');
  FA_OPS.forEach(([re, s]) => t = t.replace(re, s));
  const cands = t.match(/[\d.+\-*/()^\s%]{3,}/g) || [];
  let best = null;
  for (const c of cands) { const x = c.trim(); if ((/\d\s*[+\-*/^%]\s*\d/.test(x) || /\d\s*\(/.test(x)) && (!best || x.length > best.length)) best = x; }
  if (!best) { const m2 = t.match(/(sqrt|sin|cos|tan|log)\s*\(?([\d.]+)\)?/); if (m2) best = `${m2[1]}(${m2[2]})`; }
  return best;
}
function safeCalc(expr) {
  let e = String(expr).replace(/\^/g, '**').replace(/×/g, '*').replace(/÷/g, '/').replace(/,/g, '');
  e = e.replace(/\b(sqrt|sin|cos|tan|log|exp|abs|floor|ceil|round)\b/g, 'Math.$1').replace(/\bpi\b/g, 'Math.PI');
  if (!/^[\d\s.+\-*/%()MathPIEqrtinscolgexpabflceund]+$/.test(e)) throw new Error('unsafe');
  return Function('"use strict";return(' + e + ')')();
}
const UNIT_ALIASES = { 'کیلومتر': 'km', 'مایل': 'mile', 'کیلوگرم': 'kg', 'کیلو': 'kg', 'پوند': 'lb', 'متر': 'm', 'فوت': 'ft', 'سانتیمتر': 'cm', 'سانتی متر': 'cm', 'اینچ': 'inch', 'لیتر': 'l', 'گالن': 'gallon', 'گرم': 'g', 'اونس': 'oz' };
const UNITS = { 'km>mile': 0.621371, 'mile>km': 1.60934, 'kg>lb': 2.20462, 'lb>kg': 0.453592, 'm>ft': 3.28084, 'ft>m': 0.3048, 'cm>inch': 0.393701, 'inch>cm': 2.54, 'l>gallon': 0.264172, 'gallon>l': 3.78541, 'g>oz': 0.035274, 'oz>g': 28.3495 };
function convertUnits(text) {
  const t = ' ' + faToEnDigits(text || '').toLowerCase() + ' ';
  const m = t.match(/([\d.]+)\s*([a-z\u0600-\u06FF ]+?)\s*(?:به|to|→)\s*([a-z\u0600-\u06FF ]+)/);
  if (!m) return null;
  const val = parseFloat(m[1]);
  const src = UNIT_ALIASES[m[2].trim()] || m[2].trim(), dst = UNIT_ALIASES[m[3].trim()] || m[3].trim();
  const f = UNITS[src + '>' + dst];
  return f ? `${val} ${m[2].trim()} = ${(val * f).toFixed(4).replace(/\.?0+$/, '')} ${m[3].trim()} ⚖️` : null;
}
function numberStats(text) {
  const nums = (faToEnDigits(text || '').match(/-?\d+\.?\d*/g) || []).map(Number);
  if (nums.length < 2) return null;
  const s = [...nums].sort((a, b) => a - b), n = nums.length, mean = nums.reduce((a, b) => a + b, 0) / n;
  const median = n % 2 ? s[n >> 1] : (s[n / 2 - 1] + s[n / 2]) / 2;
  const sd = Math.sqrt(nums.reduce((a, x) => a + (x - mean) ** 2, 0) / n);
  return { count: n, sum: nums.reduce((a, b) => a + b, 0), mean, median, min: s[0], max: s[n - 1], range: s[n - 1] - s[0], stdev: sd, numbers: nums };
}
function textChart(nums) {
  const mx = Math.max(...nums.map(Math.abs), 1);
  return nums.slice(0, 20).map((v, i) => `${String(i + 1).padStart(3)} │ ${'█'.repeat(Math.max(1, Math.round(Math.abs(v) / mx * 34)))} ${v}`).join('\n');
}
const STOPWORDS = new Set('است هست بود باشد شود شد این آن که را به از در با بر برای تا نیز هم یا اگر اما چون چه هر خود ما شما شده اند کرد کند دارد دارند خواهد باید شود'.split(' '));
function summarizeText(text, maxS = 5) {
  const clean = String(text || '').replace(/\s+/g, ' ').trim();
  const sents = clean.split(/(?<=[.!؟?])\s+/).filter(s => s.trim().length > 15);
  if (sents.length <= maxS) return clean.slice(0, 2500);
  const freq = {};
  (clean.match(/[\w‌]{3,}/g) || []).forEach(w => { if (!STOPWORDS.has(w)) freq[w] = (freq[w] || 0) + 1; });
  return sents.map((s, i) => { const ws = s.match(/[\w‌]{3,}/g) || []; let sc = ws.reduce((a, w) => a + (freq[w] || 0), 0) / (ws.length + 3); if (i < 2) sc *= 1.4; return [sc, i, s]; })
    .sort((a, b) => b[0] - a[0]).slice(0, maxS).sort((a, b) => a[1] - b[1]).map(x => x[2]).join(' ');
}
function textStats(text) {
  const words = String(text || '').match(/[\w‌]+/g) || [];
  const freq = {};
  words.forEach(w => { if (w.length > 2 && !STOPWORDS.has(w)) freq[w] = (freq[w] || 0) + 1; });
  return { words: words.length, sentences: (String(text).split(/[.!؟?]+/).filter(Boolean)).length,
           reading: Math.max(1, Math.round(words.length / 180)), unique: new Set(words).size,
           top: Object.entries(freq).sort((a, b) => b[1] - a[1]).slice(0, 8) };
}
function extractSubject(t) {
  t = t || '';
  let m = t.match(/[«"]([\s\S]+?)[»"]/); if (m && m[1].length > 30) return m[1];
  m = t.match(/(?:متن|مقاله|نامه)[:：]\s*([\s\S]+)/); if (m && m[1].length > 30) return m[1];
  return t.length > 120 ? t : '';
}
async function wikiSearch(query, limit = 3) {
  for (const lg of ['fa', 'en']) {
    try {
      const api = `https://${lg}.wikipedia.org/w/api.php?action=query&format=json&prop=extracts&exintro=1&explaintext=1&generator=search&gsrsearch=${encodeURIComponent(query)}&gsrlimit=${limit}&exsentences=4&origin=*`;
      const j = await (await origFetch(api)).json();
      const pages = Object.values(j?.query?.pages || {});
      const out = pages.filter(p => (p.extract || '').trim()).map(p => ({ title: p.title, text: p.extract.trim().slice(0, 900), url: `https://${lg}.wikipedia.org/wiki/${encodeURIComponent(p.title.replace(/ /g, '_'))}`, source: `ویکی‌پدیا (${lg})` }));
      if (out.length) return out;
    } catch (e) {}
  }
  return [];
}
function imageUrl(prompt) {
  const seed = Math.floor(Date.now() / 1000) % 100000;
  return `https://image.pollinations.ai/prompt/${encodeURIComponent(prompt.trim().slice(0, 300))}?width=1024&height=1024&seed=${seed}&nologo=true`;
}
function runJSCode(code) {
  return new Promise(resolve => {
    const fmt = a => a.map(x => typeof x === 'object' ? JSON.stringify(x) : String(x)).join(' ');
    if (typeof Worker !== 'undefined' && typeof Blob !== 'undefined') {
      let w = null;
      try {
        const src = `var L=[];console.log=function(){L.push([].slice.call(arguments).map(function(x){return typeof x==='object'?JSON.stringify(x):String(x)}).join(' '))};self.onmessage=function(e){try{(0,eval)(e.data);self.postMessage({ok:true,out:L.join('\\n')})}catch(err){self.postMessage({ok:false,out:L.join('\\n'),err:String(err&&err.message||err)})}}`;
        w = new Worker(URL.createObjectURL(new Blob([src], { type: 'text/javascript' })));
      } catch (e) { w = null; }
      if (w) {
        const to = setTimeout(() => { try { w.terminate(); } catch (e) {} resolve({ ok: false, out: '', err: '⏱️ زمان اجرا تمام شد (بیش از ۶ ثانیه)' }); }, 6000);
        w.onmessage = e => { clearTimeout(to); try { w.terminate(); } catch (x) {} resolve(e.data); };
        w.onerror = () => { clearTimeout(to); try { w.terminate(); } catch (x) {} resolve({ ok: false, out: '', err: 'خطای محیط اجرا' }); };
        w.postMessage(code); return;
      }
    }
    const logs = [], old = console.log;
    console.log = (...a) => logs.push(fmt(a));
    try { new Function(code)(); console.log = old; resolve({ ok: true, out: logs.join('\n') }); }
    catch (err) { console.log = old; resolve({ ok: false, out: logs.join('\n'), err: String(err && err.message || err) }); }
  });
}
function vaultWrite(name, content) {
  name = String(name || 'file.txt').split(/[\\/]/).pop().replace(/[<>:"|?*]/g, '_').slice(0, 120) || 'file.txt';
  FILES[name] = { content: String(content ?? ''), modified: stamp().slice(0, 16) };
  saveFiles(); return name;
}

/* ============ موتورهای اجرایی ایجنت‌ها ============ */
const agentSystem = a => `تو «${a.fa}» (${a.en}) هستی؛ یکی از ۱۲۰ ایجنت متخصص سیستم دیانا در دپارتمان «${a.dept_fa}».\nتخصص تو: ${a.desc}\nفقط روی وظیفه خودت تمرکز کن و خروجی کامل، حرفه‌ای و کاربردی به فارسی (یا زبان کاربر) با قالب Markdown تحویل بده.`;
const FA_EN_WORDS = { 'قلعه': 'castle', 'کوه': 'mountain', 'غروب': 'sunset', 'ماهی': 'fish', 'دریا': 'sea', 'جنگل': 'forest', 'شهر': 'city', 'فضا': 'space galaxy', 'اژدها': 'dragon', 'گربه': 'cat', 'سگ': 'dog', 'گل': 'flowers', 'درخت': 'tree', 'خانه': 'house', 'ماشین': 'car', 'ربات': 'robot', 'دختر': 'girl', 'پسر': 'boy', 'آسمان': 'sky', 'ستاره': 'stars', 'ماه': 'moon', 'خورشید': 'sun', 'اقیانوس': 'ocean', 'آکواریوم': 'aquarium', 'طلایی': 'golden', 'جادویی': 'magical', 'برف': 'snow', 'باران': 'rain', 'پروانه': 'butterfly', 'پرنده': 'bird', 'اسب': 'horse', 'شیر': 'lion', 'موشک': 'rocket', 'سیاره': 'planet', 'باغ': 'garden', 'صحرا': 'desert', 'آبشار': 'waterfall', 'کشتی': 'ship', 'هواپیما': 'airplane', 'شب': 'night', 'کاخ': 'palace', 'روستا': 'village', 'لوگو': 'logo minimal design' };

const EXEC = {
  async llm(agent, ins) {
    const r = await llmGenerate(ins, agentSystem(agent));
    if (r) return { ok: true, output: r.text, artifacts: [] };
    const subject = extractSubject(ins);
    const lines = [`**${agent.emoji} گزارش ${agent.fa}** *(حالت آفلاین — مغز ابری در دسترس نیست)*\n`];
    if (subject) {
      const st = textStats(subject);
      lines.push(`**تحلیل متن:** ${st.words} واژه، ${st.sentences} جمله، ~${st.reading} دقیقه مطالعه`);
      lines.push('\n**خلاصه استخراجی:**\n' + summarizeText(subject, 4));
      return { ok: true, output: lines.join('\n'), artifacts: [] };
    }
    const topic = ins.replace(/(بنویس|بساز|انجام بده|درباره|تحقیق کن|گزارش کامل بده|گزارش بده)/g, ' ').replace(/\s+/g, ' ').trim().replace(/\s+(و|رو|را)$/, '').slice(0, 120) || ins.slice(0, 120);
    lines.push(`**موضوع:** ${topic}\n`);
    if (['research', 'education'].includes(agent.dept))
      lines.push(`**🔬 چارچوب پژوهشی «${topic}»:**\n۱. **${topic} چیست؟** تعریف دقیق و ساده\n۲. **پیشینه و تاریخچه**\n۳. **اجزا و سازوکار**\n۴. **کاربردها و اهمیت**\n۵. **چالش‌ها و پرسش‌های باز**\n۶. **آینده و چشم‌انداز**`);
    else if (['writing', 'marketing', 'admin'].includes(agent.dept))
      lines.push('**✍️ اسکلت محتوا:**\n• **قلاب شروع** جذاب\n• **بدنه:** سه نکته کلیدی با مثال\n• **نقطه اوج پیام**\n• **پایان‌بندی و دعوت به اقدام**');
    else
      lines.push('**چارچوب اجرایی:**\n۱. تعریف دقیق خروجی\n۲. جمع‌آوری مواد اولیه\n۳. ساخت نسخه اول\n۴. بازبینی و صیقل\n۵. تحویل نهایی');
    lines.push('\n💡 *با اتصال اینترنت، همین وظیفه با مغز ابری رایگان و کیفیت کامل بازتولید می‌شود.*');
    return { ok: true, output: lines.join('\n'), artifacts: [], generic: true };
  },
  async web(agent, ins) {
    const urlM = ins.match(/(https?:\/\/[^\s)<>"']+|www\.[^\s)<>"']+)/);
    if (urlM) {
      try {
        const page = await (await origFetch(urlM[1])).text();
        const text = page.replace(/<(script|style)[\s\S]*?<\/\1>/gi, ' ').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').slice(0, 7000);
        return { ok: true, output: `**🌐 صفحه خوانده شد:** ${urlM[1]}\n\n**خلاصه:**\n${summarizeText(text, 6)}`, artifacts: [{ type: 'link', url: urlM[1], title: urlM[1] }] };
      } catch (e) {
        return { ok: false, output: '🌐 این سایت اجازه خواندن مستقیم از مرورگر را نمی‌دهد (CORS). نسخه سروری دیانا هر لینکی را می‌خواند؛ این‌جا از دانش ویکی‌پدیا کمک می‌گیرم.', artifacts: [] };
      }
    }
    const query = ins.replace(/(درباره|تحقیق کن|جستجو کن|سرچ کن|بگرد|پیدا کن|بررسی کن|اطلاعات|در مورد|راجع به|لطفا|لطفاً|به من بگو|گزارش کامل بده|گزارش بده)/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 120) || ins.slice(0, 120);
    const items = await wikiSearch(query, 3);
    if (!items.length) return { ok: false, output: `🔍 برای «${query}» در ویکی‌پدیا نتیجه قابل اتکایی پیدا نکردم. موضوع را دقیق‌تر بگو یا اجازه بده مغز ابری پاسخ دهد.`, artifacts: [] };
    return { ok: true, output: `**🔍 نتایج زنده ویکی‌پدیا برای:** «${query}»\n\n` + items.map(it => `**[${it.title}](${it.url})** — *${it.source}*\n${it.text}`).join('\n\n'),
             artifacts: items.map(it => ({ type: 'link', url: it.url, title: it.title })) };
  },
  async coder(agent, ins) {
    const codeM = ins.match(/```(?:\w+)?\s*\n([\s\S]*?)```/);
    if (codeM) {
      const code = codeM[1].trim();
      if (/\bdef\s|print\s*\(|import\s+\w/.test(code) && !/console\.log/.test(code)) {
        return { ok: false, output: '💻 نسخه وب دیانا کد **جاوااسکریپت** را در مرورگر اجرا می‌کند؛ این کد پایتون است. نسخه سروری/ترموکس دیانا پایتون را مستقیم اجرا می‌کند. این‌جا بگو چه برنامه‌ای می‌خواهی تا نسخه اجرایی‌اش را بسازم!', artifacts: [] };
      }
      const r = await runJSCode(code);
      return { ok: r.ok, output: `**${r.ok ? '✅ اجرا موفق بود' : '❌ اجرا با خطا مواجه شد'}** — کد شما واقعاً در مرورگر اجرا شد:\n\n\`\`\`javascript\n${code}\n\`\`\`\n\n**خروجی:**\n\`\`\`\n${r.out || '(بدون خروجی)'}\n\`\`\`${r.err ? `\n\n**خطا:**\n\`\`\`\n${r.err}\n\`\`\`` : ''}`, artifacts: [] };
    }
    const expr = findMathExpr(ins);
    if (expr && /\d/.test(expr)) { try { return { ok: true, output: `🧮 محاسبه با اجرای واقعی:\n\n\`${expr.trim()}\` = **${safeCalc(expr)}**`, artifacts: [] }; } catch (e) {} }
    let gen = heuristicProgram(ins);
    if (!gen) {
      const r = await llmGenerate(`وظیفه: ${ins}\n\nبرنامه کامل JavaScript بنویس که این کار را انجام دهد و نتیجه را با console.log چاپ کند. فقط یک بلوک کد \`\`\`javascript برگردان، بدون توضیح.`, agentSystem(agent));
      const m2 = (r?.text || '').match(/```(?:javascript|js)?\s*\n([\s\S]*?)```/);
      if (m2) gen = m2[1].trim();
    }
    if (!gen) return { ok: false, output: '💻 برای نوشتن این برنامه خاص به مغز ابری نیاز دارم که الان آفلاین است. مسائل کلاسیک (اعداد اول، فیبوناچی، فاکتوریل، جدول ضرب، مرتب‌سازی) را آفلاین هم می‌نویسم و اجرا می‌کنم!', artifacts: [] };
    let r = await runJSCode(gen);
    if (!r.ok) {
      const fix = await llmGenerate(`این کد JavaScript خطا داده. اصلاحش کن و فقط بلوک کد برگردان:\n\n\`\`\`javascript\n${gen}\n\`\`\`\n\nخطا: ${r.err}`, agentSystem(agent));
      const m3 = (fix?.text || '').match(/```(?:javascript|js)?\s*\n([\s\S]*?)```/);
      if (m3) { gen = m3[1].trim(); r = await runJSCode(gen); }
    }
    const fname = vaultWrite(`program-${Math.floor(Date.now() / 1000) % 100000}.js`, gen);
    return { ok: r.ok, artifacts: [{ type: 'file', name: fname }],
             output: `**${r.ok ? '✅ برنامه نوشته و با موفقیت در مرورگر اجرا شد' : '⚠️ برنامه نوشته شد ولی خطا داد'}** و فایلش در گاوصندوق ذخیره شد (\`${fname}\`):\n\n\`\`\`javascript\n${gen}\n\`\`\`\n\n**🖥️ خروجی واقعی اجرا:**\n\`\`\`\n${r.out || '(بدون خروجی)'}\n\`\`\`${r.err ? `\n\n**خطا:**\n\`\`\`\n${r.err}\n\`\`\`` : ''}` };
  },
  async data(agent, ins) {
    const parts = [];
    const conv = convertUnits(ins); if (conv) parts.push(`**${conv}**`);
    const pm = faToEnDigits(ins).replace(/,/g, '').match(/([\d.]+)\s*درصد\s+(?:از\s+)?([\d.]+)/);
    if (pm) parts.push(`🧮 **${+pm[1]} درصد از ${(+pm[2]).toLocaleString()}** = **${((+pm[2]) * (+pm[1]) / 100).toLocaleString()}**`);
    const expr = findMathExpr(ins);
    if (expr && /[+\-*/^()]/.test(expr)) { try { parts.push(`🧮 **محاسبه:** \`${expr.trim()}\` = **${safeCalc(expr)}**`); } catch (e) {} }
    const sm = ins.match(/(میانگین|معدل|مجموع|آمار|تحلیل)\s*(?:اعداد)?\s*[:：]?\s*(.+)/);
    const stats = numberStats(sm && /\d/.test(sm[2]) ? sm[2] : ins);
    if (stats && (sm || !parts.length)) {
      parts.push(`**📊 تحلیل آماری ${stats.count} عدد** (${stats.numbers.slice(0, 12).join('، ')}):\n\n• مجموع: **${stats.sum}**\n• میانگین: **${stats.mean.toFixed(2)}**\n• میانه: **${stats.median}**\n• کمترین: **${stats.min}** | بیشترین: **${stats.max}** | دامنه: **${stats.range}**\n• انحراف معیار: **${stats.stdev.toFixed(2)}**\n\n**نمودار:**\n\`\`\`\n${textChart(stats.numbers)}\n\`\`\``);
    }
    if (parts.length) return { ok: true, output: parts.join('\n\n---\n\n'), artifacts: [] };
    return EXEC.llm(agent, ins);
  },
  async text(agent, ins) {
    const subject = extractSubject(ins);
    if (subject && subject.length > 60) {
      const st = textStats(subject), summary = summarizeText(subject, 5);
      const fname = vaultWrite(`summary-${Math.floor(Date.now() / 1000) % 100000}.txt`, summary);
      return { ok: true, artifacts: [{ type: 'file', name: fname }],
               output: `**📄 تحلیل متن انجام شد:** ${st.words} واژه | ${st.sentences} جمله | ${st.unique} واژه یکتا | زمان مطالعه ~${st.reading} دقیقه\n\n**📃 خلاصه:**\n${summary}\n\n**🔑 واژه‌های کلیدی:** ${st.top.map(([w, c]) => `${w} (${c} بار)`).join('، ')}\n\n📁 خلاصه در گاوصندوق ذخیره شد: \`${fname}\`` };
    }
    return EXEC.llm(agent, ins);
  },
  async files(agent, ins) {
    const t = norm(ins), names = Object.keys(FILES);
    const wantsCreate = ['بساز','درست کن','ایجاد','بنویس','ذخیره کن','ثبت کن'].some(w => t.includes(w));
    if (!wantsCreate && ['لیست فایل','چه فایل','فایل ها','نشون بده فایل','list'].some(w => t.includes(w))) {
      if (!names.length) return { ok: true, output: '📁 گاوصندوق فعلاً خالیه فرمانده! بگو چه فایلی بسازم.', artifacts: [] };
      return { ok: true, output: `**📁 فایل‌های گاوصندوق (${names.length} فایل):**\n\n` + names.map(n => `• \`${n}\` — ${new TextEncoder().encode(FILES[n].content).length} بایت — ${FILES[n].modified}`).join('\n'), artifacts: [] };
    }
    if (['بخون','بخوان','باز کن','محتوای','read'].some(w => t.includes(w))) {
      for (const n of names) if (ins.toLowerCase().includes(n.toLowerCase()))
        return { ok: true, output: `**📄 محتوای \`${n}\`:**\n\n${FILES[n].content.slice(0, 3000)}`, artifacts: [{ type: 'file', name: n }] };
    }
    const m = ins.match(/فایل(?:ی)?\s+(?:به نام\s+)?[«"]?([^\s»"]+)/);
    let name = m ? m[1] : `note-${new Date().toTimeString().slice(0, 8).replace(/:/g, '')}.txt`;
    if (!name.includes('.')) name += '.txt';
    const cm = ins.match(/(?:با محتوای|محتوا|بنویس(?:\s+که)?)[:：]?\s*([\s\S]+)/);
    let content = cm && cm[1].trim().length > 3 ? cm[1].trim() : null;
    if (!content) {
      const r = await llmGenerate(`یک متن کامل و مفید برای ذخیره در فایل بنویس. موضوع درخواست کاربر: ${ins}`, agentSystem(agent));
      content = r?.text || `یادداشت دیانا\nدرخواست فرمانده: ${ins}\nتاریخ ثبت: ${stamp()}`;
    }
    const fname = vaultWrite(name, content);
    return { ok: true, artifacts: [{ type: 'file', name: fname }],
             output: `**📁 فایل با موفقیت در گاوصندوق دیانا ساخته شد:** \`${fname}\`\n\nاز صفحه «گاوصندوق و حافظه» می‌توانی دانلودش کنی.\n\n**پیش‌نمایش:**\n${content.slice(0, 600)}` };
  },
  async memory(agent, ins) {
    const t = norm(ins);
    if (['یادته','یادت هست','چی میدونی','یادآوری','recall'].some(w => t.includes(w))) {
      const found = MEM.facts.filter(f => norm(ins).split(/\s+/).some(w => w.length > 1 && norm(f.text).includes(w)));
      const list = found.length ? found : MEM.facts.slice(-10);
      if (list.length) return { ok: true, output: '**🧠 از حافظه‌ام:**\n\n' + list.map(f => `• ${f.text} *(ثبت: ${f.ts})*`).join('\n'), artifacts: [] };
      return { ok: true, output: '🧠 حافظه‌ام هنوز خالیه فرمانده! هرچی بگی «یادت باشه که...» ذخیره‌اش می‌کنم.', artifacts: [] };
    }
    const fact = ins.replace(/(یادت باشه که|یادت باشه|به خاطر بسپار که|به خاطر بسپار|ذخیره کن که|یاد بگیر)/g, '').trim();
    MEM.facts.push({ id: Date.now(), text: fact, ts: stamp().slice(0, 16) }); saveMem();
    return { ok: true, output: `**💾 در حافظه بلندمدت دیانا ذخیره شد:**\n\n«${fact}»\n\nاز حالا در همه گفتگوها این را به یاد دارم 🐠`, artifacts: [] };
  },
  async planner(agent, ins) {
    const r = await llmGenerate(`یک برنامه اجرایی کامل و قدم‌به‌قدم فارسی بساز برای: ${ins}\nشامل: هدف نهایی، فازها با زمان‌بندی، چک‌لیست کارها با ☐، نکات طلایی و اشتباهات رایج. Markdown تمیز.`, agentSystem(agent));
    let txt = r?.text;
    if (!txt && ['سفر','مسافرت','گردش'].some(w => ins.includes(w))) {
      const dm = faToEnDigits(ins).match(/(\d+)\s*روز/), days = dm ? +dm[1] : 3;
      const dest = (ins.match(/به\s+([^\s،.]+)/) || [])[1] || 'مقصد';
      const blocks = Array.from({ length: days }, (_, i) => `## روز ${i + 1} — ${i === 0 ? 'رسیدن و آشنایی 🚶' : i < days - 1 ? 'گشت اصلی و جاذبه‌ها 📸' : 'خرید سوغات و بازگشت 🧳'}\n☐ صبحانه محلی و شروع گشت\n☐ بازدید از مهم‌ترین جاذبه‌های ${dest}\n☐ ناهار محلی و استراحت\n☐ گشت عصرگاهی و عکاسی`).join('\n\n');
      txt = `# ✈️ برنامه سفر ${days} روزه به ${dest}\n\n## 🎒 قبل از حرکت\n☐ رزرو اقامت نزدیک مرکز شهر\n☐ بلیط رفت‌وبرگشت\n☐ شارژر، کفش راحت، دارو و پول نقد کم\n\n${blocks}\n\n## 💰 مدیریت بودجه\n• اقامت اقتصادی + حمل‌ونقل عمومی\n• غذای محلی به‌جای توریستی\n• گروه‌بندی بازدیدهای نزدیک به هم\n\n💡 *(اسکلت آفلاین است؛ با مغز ابری نسخه کامل با نام جاذبه‌ها و هزینه‌ها ساخته می‌شود)*`;
    }
    if (!txt) {
      const goal = ins.replace(/(برنامه|برنامه ریزی|بچین|بساز|کن|برای)/g, ' ').trim().slice(0, 100) || ins.slice(0, 100);
      txt = `# 🗓️ برنامه اجرایی: ${goal}\n\n## 🎯 هدف نهایی\nرسیدن به نتیجه مطلوب با قدم‌های کوچک و پیوسته.\n\n## فاز ۱ — آماده‌سازی (روزهای ۱ تا ۳)\n☐ مشخص‌کردن هدف و معیار موفقیت\n☐ جمع‌آوری ابزار و منابع\n☐ حذف موانع\n\n## فاز ۲ — اجرای اصلی (هفته ۱ و ۲)\n☐ شروع با کوچک‌ترین قدم (قانون ۲ دقیقه)\n☐ اجرای روزانه در ساعت ثابت\n☐ ثبت پیشرفت\n\n## فاز ۳ — تثبیت (هفته ۳ و ۴)\n☐ مرور و اصلاح مسیر\n☐ جشن موفقیت‌های کوچک 🎉\n\n## 💡 نکات طلایی\n• استمرار مهم‌تر از شدت است\n• پیشرفت ۱٪ روزانه = ۳۷ برابر در سال`;
    }
    const fname = vaultWrite(`plan-${Math.floor(Date.now() / 1000) % 100000}.md`, txt);
    return { ok: true, output: txt + `\n\n📁 برنامه در گاوصندوق ذخیره شد: \`${fname}\``, artifacts: [{ type: 'file', name: fname }] };
  },
  async artist(agent, ins) {
    let promptEn = null;
    const r = await llmGenerate(`Convert this image request into ONE detailed English image-generation prompt (only the prompt, no quotes): ${ins}`, 'You translate image requests into vivid English prompts.');
    if (r?.text && r.text.length > 8) promptEn = r.text.trim().replace(/^"|"$/g, '').slice(0, 280);
    if (!promptEn) {
      const padded = ' ' + ins.replace(/[،؛.!؟?()«»]/g, ' ') + ' ';
      const words = [];
      for (const [fa, en] of Object.entries(FA_EN_WORDS)) if (padded.includes(` ${fa} `) || padded.includes(` ${fa}‌`)) words.push(en);
      (ins.match(/[A-Za-z]{3,}/g) || []).forEach(w => words.push(w));
      promptEn = words.length ? words.join(', ') + ', beautiful detailed digital art, vibrant colors, high quality' : 'a magical golden fish in a beautiful underwater kingdom, vibrant colors, digital art';
    }
    const url = imageUrl(promptEn);
    return { ok: true, artifacts: [{ type: 'image', url, prompt: promptEn }],
             output: `**🎨 تصویر شما ساخته شد!**\n\n![تصویر ساخته دیانا](${url})\n\nپرامپت اثر: *${promptEn}*\n\n💡 بگو «یکی دیگه با سبک متفاوت بساز» تا نسخه تازه خلق کنم!` };
  },
  async system(agent, ins) {
    const est = (typeof navigator !== 'undefined' && navigator.storage?.estimate) ? await navigator.storage.estimate().catch(() => null) : null;
    return { ok: true, artifacts: [], output:
      `**🖥️ وضعیت زنده سیستم دیانا (نسخه وب):**\n\n• محیط اجرا: **مرورگر شما** (${(typeof navigator !== 'undefined' ? navigator.platform || 'نامشخص' : '—')})\n• ساعت محلی: **${new Date().toLocaleString('fa-IR')}**\n• اینترنت: **${typeof navigator !== 'undefined' && navigator.onLine ? 'متصل ✅' : 'قطع 📴'}**\n• مغز فعال: **${llmMode()}**\n• فضای مصرفی حافظه: **${est ? (est.usage / 1024).toFixed(1) + ' کیلوبایت' : '—'}**\n• فایل‌های گاوصندوق: **${Object.keys(FILES).length}** فایل\n• ایجنت‌های ارتش: **${AGENTS.length} متخصص** در ${DEPARTMENTS.length} دپارتمان\n• فرمانده: **${MEM.profile.user_name || 'هنوز خودش را معرفی نکرده'}** 🐠` };
  },
};
function heuristicProgram(ins) {
  const t = norm(ins), nums = faToEnDigits(t).match(/\d+/g) || [];
  const n = nums.length ? +nums[0] : 100;
  if (t.includes('اعداد اول') || t.includes('عدد اول') || t.includes('prime'))
    return `// یافتن اعداد اول تا ${n}\nfunction isPrime(x){ if(x<2) return false; for(let i=2;i*i<=x;i++) if(x%i===0) return false; return true; }\nconst primes=[]; for(let i=2;i<=${n};i++) if(isPrime(i)) primes.push(i);\nconsole.log(primes.join(', '));\nconsole.log('تعداد اعداد اول:', primes.length);`;
  if (t.includes('فیبوناچی') || t.includes('fibonacci')) { const c = n <= 100 ? n : 20; return `// دنباله فیبوناچی\nlet a=0,b=1; const seq=[];\nfor(let i=0;i<${c};i++){ seq.push(a); [a,b]=[b,a+b]; }\nconsole.log(seq.join(', '));`; }
  if (t.includes('فاکتوریل') || t.includes('factorial')) { const v = n <= 170 ? n : 20; return `let n=${v}, f=1n; for(let i=2n;i<=BigInt(n);i++) f*=i;\nconsole.log(n + '! =', f.toString());`; }
  if (t.includes('جدول ضرب')) { const v = n <= 20 ? n : 10; return `// جدول ضرب تا ${v}\nfor(let i=1;i<=${v};i++){ const row=[]; for(let j=1;j<=${v};j++) row.push(i+'x'+j+'='+(i*j)); console.log(row.join(' | ')); }`; }
  if (t.includes('مجموع') && (t.includes('تا') || t.includes('اعداد'))) return `const n=${n};\nconsole.log('مجموع اعداد ۱ تا '+n+' =', n*(n+1)/2);`;
  if (t.includes('مرتب') || t.includes('sort')) { const data = nums.length > 1 ? nums.map(Number) : [42, 7, 19, 3, 88, 25, 1, 56]; return `const data=${JSON.stringify(data)};\nconsole.log('قبل:', data.join(', '));\ndata.sort((a,b)=>a-b);\nconsole.log('بعد از مرتب‌سازی:', data.join(', '));`; }
  if (['شانس','تصادفی','random','تاس'].some(w => t.includes(w))) return `console.log('🎲 تاس:', 1+Math.floor(Math.random()*6));\nconsole.log('🎲 تاس دوم:', 1+Math.floor(Math.random()*6));\nconsole.log('🔢 ده عدد تصادفی:', Array.from({length:10},()=>1+Math.floor(Math.random()*100)).join(', '));`;
  if ((t.includes('زوج') || t.includes('فرد')) && t.includes('برنامه')) return `const evens=[],odds=[];\nfor(let i=1;i<=${n};i++) (i%2?odds:evens).push(i);\nconsole.log('زوج‌ها:', evens.join(', '));\nconsole.log('فردها:', odds.join(', '));`;
  return null;
}

/* ============ رویدادهای زنده (جایگزین SSE) ============ */
const ES_SET = new Set();
class FakeEventSource { constructor() { this.onmessage = null; this.onerror = null; ES_SET.add(this); } close() { ES_SET.delete(this); } }
window.EventSource = FakeEventSource;
function emit(e) { const d = JSON.stringify(e); ES_SET.forEach(es => { try { es.onmessage && es.onmessage({ data: d }); } catch (_) {} }); }

/* ============ ارکستراتور 🧠 ============ */
const pubAgent = a => ({ id: a.id, fa: a.fa, en: a.en, emoji: a.emoji, dept: a.dept, dept_fa: a.dept_fa, dept_emoji: a.dept_emoji, color: a.color, executor: a.executor, desc: a.desc });
function logChat(role, text, source = '') {
  MEM.conversations.push({ role, text: String(text || '').slice(0, 4000), source, ts: stamp() });
  MEM.conversations = MEM.conversations.slice(-400);
  if (role === 'user') MEM.stats.messages++;
  saveMem();
}
async function decompose(goal, forcedId) {
  if (forcedId && AGENT_BY_ID[forcedId]) { const a = AGENT_BY_ID[forcedId]; return [{ id: 's1', title: `${a.emoji} ${a.fa}`, instruction: goal, agent_id: a.id }]; }
  // تجزیه هوشمند با مغز ابری
  try {
    const r = await llmGenerate(`هدف کاربر: «${goal}»\n\nاین هدف را به حداکثر ۴ زیروظیفه مستقل و موازی تجزیه کن. برای هرکدام یکی از این دپارتمان‌ها را انتخاب کن: ${DEPARTMENTS.map(d => `${d.id} (${d.fa})`).join('، ')}\nفقط آرایه JSON برگردان: [{"task": "...", "dept": "research"}]`, 'تو مغز ارکستراتور هستی و فقط JSON برمی‌گردانی.');
    if (r?.text) {
      const m = r.text.match(/\[[\s\S]*\]/);
      if (m) {
        const items = JSON.parse(m[0]), subs = [], used = new Set();
        for (const it of items.slice(0, 5)) {
          if (!it.task) continue;
          const cands = findAgents(it.task + ' ' + goal, 8).filter(a => a.dept === it.dept);
          const agent = (cands.length ? cands : findAgents(it.task, 3)).find(a => !used.has(a.id)) || findAgents(it.task, 1)[0] || AGENTS[0];
          if (!agent) continue;
          used.add(agent.id);
          subs.push({ id: 's' + (subs.length + 1), title: `${agent.emoji} ${agent.fa}`, instruction: String(it.task), agent_id: agent.id });
        }
        if (subs.length) return subs;
      }
    }
  } catch (e) {}
  // تجزیه آفلاین
  const parts = goal.split(/(?:\s+و بعد\s+|\s+سپس\s+|؛|;|\n+|\.\s+|\s+and then\s+)/).map(s => s.trim()).filter(s => s.length > 4);
  const subs = [], used = new Set();
  if (parts.length >= 2) {
    for (const p of parts.slice(0, 5)) {
      const best = findAgents(p, 3);
      const agent = best.find(b => !used.has(b.id)) || best[0] || AGENTS[0];
      used.add(agent.id);
      subs.push({ id: 's' + (subs.length + 1), title: `${agent.emoji} ${agent.fa}`, instruction: p, agent_id: agent.id });
    }
    return subs;
  }
  const candidates = findAgents(goal, 10);
  const main = candidates[0] || AGENT_BY_ID['research-01'];
  subs.push({ id: 's1', title: `${main.emoji} ${main.fa}`, instruction: goal, agent_id: main.id });
  used.add(main.id);
  const t = norm(goal);
  if (['جامع','کامل','عمیق','گزارش','تحقیق','دقیق','حرفه ای','research','complete','full'].some(w => t.includes(w))) {
    const rest = candidates.slice(1).sort((a, b) => (b.dept === main.dept) - (a.dept === main.dept));
    for (const c of rest) {
      if (subs.length >= 4) break;
      if (!used.has(c.id) && c.executor !== main.executor) { subs.push({ id: 's' + (subs.length + 1), title: `${c.emoji} ${c.fa}`, instruction: goal, agent_id: c.id }); used.add(c.id); }
    }
    if (main.dept === 'research' && !used.has('research-10') && subs.length < 4) {
      const rep = AGENT_BY_ID['research-10'];
      subs.push({ id: 's' + (subs.length + 1), title: `${rep.emoji} ${rep.fa}`, instruction: `چارچوب و نکات کلیدی گزارش درباره: ${goal}`, agent_id: rep.id });
    }
  }
  return subs;
}
function evaluate(agent, result) {
  const out = (result.output || '').trim();
  let score = 0; const notes = [];
  if (result.ok) { score += 50; notes.push('اجرا موفق'); } else notes.push('اجرا ناقص');
  if (out.length > 35) score += 18;
  if (out.length > 250) score += 12;
  if (out.length > 600) score += 8;
  if (result.artifacts?.length) { score += 12; notes.push('دارای خروجی قابل تحویل'); }
  if (['خطا','Error','ناموفق'].some(w => out.includes(w))) { score -= 25; notes.push('دارای خطا'); }
  if (out.includes('آفلاین')) { score -= 8; notes.push('حالت آفلاین'); }
  if (result.generic) { score -= 25; notes.push('خروجی قالبی (نیازمند مغز ابری)'); }
  if (out.includes('خروجی واقعی اجرا') || out.includes('اجرا موفق')) { score += 8; notes.push('اجرای واقعی تأیید شد'); }
  score = Math.max(0, Math.min(100, score));
  const level = score >= 85 ? 'عالی 🌟' : score >= 70 ? 'خوب ✅' : score >= 55 ? 'قابل قبول 👍' : 'ضعیف ⚠️';
  return [score, `${level} — ${notes.join('، ')}`];
}
async function synthesize(goal, results) {
  const score = results.length ? Math.round(results.reduce((a, r) => a + (r.score || 0), 0) / results.length) : 0;
  const body = results.map(r => `### ${r.agent.emoji} ${r.agent.fa} — امتیاز ارزیاب: ${r.score}/۱۰۰\n${r.output}`).join('\n\n---\n\n');
  let conclusion = null;
  try {
    const brief = results.map(r => `[${r.agent.fa}]: ${(r.output || '').slice(0, 700)}`).join('\n\n');
    const r = await llmGenerate(`هدف کاربر: «${goal}»\n\nنتایج متخصص‌ها:\n${brief}\n\nبه‌عنوان دیانا (مغز رهبر)، یک جمع‌بندی نهایی فارسی، گرم و کاربردی بنویس: مهم‌ترین نتیجه چیست. حداکثر ۶ خط.`, DIANA_PERSONA);
    conclusion = r?.text;
  } catch (e) {}
  if (!conclusion) {
    const okAgents = results.filter(r => r.ok).map(r => r.agent.fa).join('، ');
    conclusion = `مأموریت «${goal}» توسط تیم متخصص‌ها (${okAgents || '—'}) انجام شد. امتیاز کیفی میانگین ارزیاب: **${score} از ۱۰۰**. جزئیات کامل هر متخصص اینجاست و فایل گزارش هم در گاوصندوق ذخیره شد 📁🐠`;
  }
  return [`# 🎁 گزارش نهایی مأموریت دیانا\n\n**🎯 هدف فرمانده:** ${goal}\n\n**📊 امتیاز کیفی نهایی:** ${score}/۱۰۰\n\n## 🐠 جمع‌بندی دیانا\n${conclusion}\n\n## 👥 نتایج متخصص‌ها\n\n${body}\n`, score];
}
let missionCounter = Math.floor(Date.now() / 1000) % 100000;
function startMission(goal, forcedId) {
  const mid = 'm' + (++missionCounter);
  const mission = { id: mid, goal, status: 'planning', plan: [], results: [], report: '', score: null, ts: stamp() };
  MEM.missions.push(mission); MEM.missions = MEM.missions.slice(-120); saveMem();
  emit({ type: 'mission_created', mission });
  (async () => {
    try {
      emit({ type: 'orchestrator_log', mission_id: mid, text: '🧠 ارکستراتور: در حال تحلیل هدف و تجزیه به زیروظیفه‌های مستقل...' });
      const plan = await decompose(goal, forcedId);
      mission.status = 'running'; mission.plan = plan; saveMem();
      emit({ type: 'plan_ready', mission_id: mid, plan });
      emit({ type: 'orchestrator_log', mission_id: mid, text: `📋 برنامه آماده شد: ${plan.length} زیروظیفه — اجرا موازی توسط متخصص‌ها شروع می‌شود ⚡` });
      const results = await Promise.all(plan.map(async (sub, i) => {
        await sleep(i * 300);
        const agent = AGENT_BY_ID[sub.agent_id];
        emit({ type: 'agent_started', mission_id: mid, subtask: sub, agent: pubAgent(agent) });
        let result;
        try { result = await (EXEC[agent.executor] || EXEC.llm)(agent, sub.instruction); }
        catch (e) { result = { ok: false, output: 'خطا در اجرا: ' + e.message, artifacts: [] }; }
        let [score, verdict] = evaluate(agent, result);
        emit({ type: 'evaluation', mission_id: mid, subtask_id: sub.id, agent_id: agent.id, score, verdict, attempt: 1 });
        if (score < 55) {
          emit({ type: 'orchestrator_log', mission_id: mid, text: `⚠️ ارزیاب کیفیت: خروجی ${agent.fa} امتیاز ${score} گرفت — اجرای مجدد با روش جایگزین 🔁` });
          const retryAgent = { ...agent, executor: agent.executor !== 'llm' ? 'llm' : (findMathExpr(sub.instruction) ? 'data' : 'text') };
          try {
            const r2 = await (EXEC[retryAgent.executor] || EXEC.llm)(retryAgent, sub.instruction);
            const [s2, v2] = evaluate(agent, r2);
            emit({ type: 'evaluation', mission_id: mid, subtask_id: sub.id, agent_id: agent.id, score: s2, verdict: v2, attempt: 2 });
            if (s2 > score) { result = r2; score = s2; verdict = v2 + ' (تلاش دوم)'; }
          } catch (e) {}
        }
        MEM.stats.agents_runs[agent.id] = (MEM.stats.agents_runs[agent.id] || 0) + 1;
        const out = { ...sub, ok: !!result.ok, output: result.output || '', artifacts: result.artifacts || [], score, verdict, agent: pubAgent(agent) };
        emit({ type: 'agent_done', mission_id: mid, result: out });
        return out;
      }));
      const order = Object.fromEntries(plan.map((s, i) => [s.id, i]));
      results.sort((a, b) => order[a.id] - order[b.id]);
      emit({ type: 'orchestrator_log', mission_id: mid, text: '🧠 ارکستراتور: همه متخصص‌ها گزارش دادند — در حال ترکیب نتیجه نهایی...' });
      const [report, score] = await synthesize(goal, results);
      const reportFile = vaultWrite(`report-${mid}.md`, report);
      mission.status = 'done'; mission.results = results; mission.report = report; mission.score = score; mission.report_file = reportFile;
      MEM.stats.missions_done++; saveMem();
      emit({ type: 'mission_done', mission_id: mid, report, score, report_file: reportFile });
      const say = `مأموریت با موفقیت تموم شد فرمانده! 🎉🐠 ${results.filter(r => r.ok).length} متخصص روی هدفت کار کردن و امتیاز کیفی نهایی ${score} از ۱۰۰ شد. گزارش کامل رو همین‌جا و تو «مرکز فرماندهی» گذاشتم و فایلش رو هم تو گاوصندوق ذخیره کردم 📁`;
      logChat('diana', say + '\n\n' + report, 'orchestrator');
      emit({ type: 'diana_say', mission_id: mid, text: say, report });
    } catch (e) {
      mission.status = 'failed'; mission.report = 'خطا: ' + e.message; saveMem();
      emit({ type: 'mission_failed', mission_id: mid, error: String(e.message || e) });
    }
  })();
  return mid;
}
async function handleMessage(text) {
  text = (text || '').trim();
  if (!text) return { kind: 'chat', reply: '🐠 چیزی نگفتی که فرمانده! من اینجام، بگو چی تو ذهنته؟', source: 'local' };
  logChat('user', text);
  const intent = classify(text), kind = intent.kind;
  if (kind === 'set_name') {
    MEM.profile.user_name = intent.name.slice(0, 40);
    MEM.facts.push({ id: Date.now(), text: `اسم کاربر ${intent.name} است`, ts: stamp().slice(0, 16) }); saveMem();
    const reply = `چه اسم قشنگی! 🐠💙 از آشناییت خیلی خوشحالم **${intent.name}** جان! اسمت رو برای همیشه تو حافظه‌ام ذخیره کردم. حالا بگو اولین مأموریتمون چیه؟`;
    logChat('diana', reply, 'local'); return { kind, reply, source: 'local' };
  }
  if (kind === 'remember') {
    MEM.facts.push({ id: Date.now(), text: intent.fact.slice(0, 500), ts: stamp().slice(0, 16) }); MEM.facts = MEM.facts.slice(-300); saveMem();
    const reply = `حتماً! 💾🐠 تو حافظه بلندمدتم ذخیره‌اش کردم: «${intent.fact}» — دیگه هیچ‌وقت یادم نمیره!`;
    logChat('diana', reply, 'local'); return { kind, reply, source: 'local' };
  }
  if (kind === 'reminder') {
    MEM.reminders.push({ id: Date.now(), text, ts: stamp().slice(0, 16), done: false }); saveMem();
    const reply = 'چشم فرمانده! ⏰🐠 این یادآوری رو ثبت کردم و تو صفحه «گاوصندوق و حافظه» همیشه جلو چشممونه.';
    logChat('diana', reply, 'local'); return { kind, reply, source: 'local' };
  }
  if (kind === 'recall') {
    const facts = MEM.facts.slice(-15);
    let reply;
    if (facts.length || MEM.profile.user_name) {
      const lines = ['این چیزاییه که ازت یاد گرفتم 🧠💙:'];
      if (MEM.profile.user_name) lines.push(`• اسم تو **${MEM.profile.user_name}** هست`);
      facts.forEach(f => { if (!f.text.startsWith('اسم کاربر')) lines.push('• ' + f.text); });
      reply = lines.join('\n') + '\n\nاگه چیز دیگه‌ای هم باید یادم بمونه بگو: «یادت باشه که...» 🐠';
    } else reply = 'هنوز چیزی ازت به خاطرم نسپردی فرمانده 🐠💭\nمثلاً بگو: «اسمم علی است» یا «یادت باشه که روز تولدم ۵ فروردین است» تا برای همیشه یادم بمونه!';
    logChat('diana', reply, 'local'); return { kind, reply, source: 'local' };
  }
  if (kind === 'task') {
    const mid = startMission(text);
    const reply = 'چشم فرمانده! 🐠🧠 مأموریت رو گرفتم و دارم تجزیه‌اش می‌کنم...\n\nمتخصص‌های مناسب رو موازی به کار می‌اندازم، ارزیاب کیفیت روشون نظارت می‌کنه و خودم نتیجه نهایی رو ترکیب می‌کنم. تو صفحه **«مرکز فرماندهی»** می‌تونی زنده ببینی مغزم چطور کار می‌کنه! ⚡';
    logChat('diana', reply, 'orchestrator');
    return { kind: 'mission', reply, mission_id: mid, source: 'orchestrator' };
  }
  // گفتگوی آزاد: مغز ابری ← مغز آفلاین
  let sys = DIANA_PERSONA;
  if (MEM.profile.user_name) sys += `\nاسم کاربر: ${MEM.profile.user_name}`;
  if (MEM.facts.length) sys += '\nچیزهایی که از کاربر به خاطر سپرده‌ای:\n' + MEM.facts.slice(-12).map(f => '- ' + f.text).join('\n');
  const history = MEM.conversations.slice(-8, -1).map(c => ({ role: c.role === 'user' ? 'user' : 'assistant', content: c.text.slice(0, 1200) }));
  const r = await llmChat([{ role: 'system', content: sys }, ...history, { role: 'user', content: text }]);
  if (r) { logChat('diana', r.text, r.source); return { kind, reply: r.text, source: r.source }; }
  const reply = localChatReply(kind, intent.en);
  const upgradeable = ['chat','question','greeting','how_are_you','identity','capabilities'].includes(kind);
  if (!upgradeable) logChat('diana', reply, 'local');
  return { kind, reply, source: 'local', upgradeable };
}

/* ============ روتینگ API (رهگیری fetch) ============ */
function publicSettings() {
  const out = { voice: SETTINGS.voice, cloud_brain: SETTINGS.cloud_brain };
  for (const k of ['groq_key','gemini_key','openrouter_key']) { out[k] = SETTINGS[k] ? '••••••' : ''; out[k + '_set'] = !!SETTINGS[k]; }
  return out;
}
function publicState() {
  return { profile: MEM.profile, facts: MEM.facts.slice(-100), reminders: MEM.reminders.filter(r => !r.done).slice(-50),
           stats: MEM.stats, missions: [...MEM.missions].slice(-30).reverse(), conversations: MEM.conversations.slice(-60) };
}
const jsonResp = (obj, status = 200) => new Response(JSON.stringify(obj), { status, headers: { 'Content-Type': 'application/json; charset=utf-8' } });
async function handleApi(path, method, body) {
  if (method === 'GET') {
    if (path === '/api/agents') return jsonResp(window.AGENTS_DATA);
    if (path === '/api/status') return jsonResp({ online: true, internet: typeof navigator !== 'undefined' ? navigator.onLine : true, llm_mode: llmMode(), agents_total: AGENTS.length, departments: DEPARTMENTS.length, user_name: MEM.profile.user_name, stats: MEM.stats, time: stamp(), settings: publicSettings() });
    if (path === '/api/memory') return jsonResp(publicState());
    if (path === '/api/files') return jsonResp({ files: Object.entries(FILES).map(([name, f]) => ({ name, size: new TextEncoder().encode(f.content).length, modified: f.modified })).sort((a, b) => a.name.localeCompare(b.name)) });
    if (path === '/api/settings') return jsonResp(publicSettings());
    if (path.startsWith('/api/missions/')) { const m = MEM.missions.find(x => x.id === path.split('/').pop()); return m ? jsonResp(m) : jsonResp({ error: 'not found' }, 404); }
  }
  if (method === 'POST') {
    if (path === '/api/message') return jsonResp(await handleMessage(String(body.text || '')));
    if (path === '/api/agent/run') {
      const a = AGENT_BY_ID[body.agent_id];
      if (!a || !String(body.task || '').trim()) return jsonResp({ error: 'agent_id یا task نامعتبر است' }, 400);
      return jsonResp({ mission_id: startMission(String(body.task).trim(), a.id), agent: pubAgent(a) });
    }
    if (path === '/api/mission') { const g = String(body.goal || '').trim(); return g ? jsonResp({ mission_id: startMission(g) }) : jsonResp({ error: 'هدف مأموریت خالی است' }, 400); }
    if (path === '/api/chatlog') { logChat(String(body.role || 'diana'), String(body.text || ''), String(body.source || 'browser-cloud')); return jsonResp({ ok: true }); }
    if (path === '/api/memory/fact') { const fact = { id: Date.now(), text: String(body.text || '').slice(0, 500), ts: stamp().slice(0, 16) }; MEM.facts.push(fact); saveMem(); return jsonResp({ ok: true, fact }); }
    if (path === '/api/files') return jsonResp({ ok: true, name: vaultWrite(String(body.name || 'note.txt'), String(body.content || '')) });
    if (path === '/api/settings') {
      if ('voice' in body) SETTINGS.voice = !!body.voice;
      if ('cloud_brain' in body) SETTINGS.cloud_brain = !!body.cloud_brain;
      for (const k of ['groq_key','gemini_key','openrouter_key']) if (k in body) { const v = String(body[k]).trim(); if (v && !v.includes('•')) SETTINGS[k] = v; else if (v === '') SETTINGS[k] = ''; }
      if (body.user_name && String(body.user_name).trim()) MEM.profile.user_name = String(body.user_name).trim().slice(0, 40);
      saveSettings(); saveMem();
      return jsonResp({ ok: true, settings: publicSettings(), llm_mode: llmMode() });
    }
  }
  if (method === 'DELETE') {
    if (path.startsWith('/api/files/')) { const n = decodeURIComponent(path.slice('/api/files/'.length)); const ok = n in FILES; delete FILES[n]; saveFiles(); return jsonResp({ ok }); }
    if (path.startsWith('/api/memory/fact/')) { const id = path.split('/').pop(); const before = MEM.facts.length; MEM.facts = MEM.facts.filter(f => String(f.id) !== id); saveMem(); return jsonResp({ ok: MEM.facts.length < before }); }
  }
  return jsonResp({ error: 'not found' }, 404);
}
window.fetch = async (input, init = {}) => {
  const url = typeof input === 'string' ? input : (input?.url || '');
  const isApi = url.startsWith('/api/') || (typeof location !== 'undefined' && url.startsWith(location.origin + '/api/'));
  if (!isApi) return origFetch(input, init);
  const path = url.replace(/^https?:\/\/[^/]+/, '').split('?')[0];
  const method = (init.method || (typeof input !== 'string' && input?.method) || 'GET').toUpperCase();
  let body = {};
  if (init.body) { try { body = JSON.parse(init.body); } catch (e) {} }
  try { return await handleApi(path, method, body); }
  catch (e) { return jsonResp({ error: String(e.message || e) }, 500); }
};

/* دانلود فایل‌های گاوصندوق در نسخه وب (Blob) */
if (typeof document !== 'undefined') {
  document.addEventListener('click', e => {
    const a = e.target.closest('a[href*="/api/files/"]');
    if (!a) return;
    const m = (a.getAttribute('href') || '').match(/\/api\/files\/(.+)\/download/);
    if (!m) return;
    e.preventDefault();
    const name = decodeURIComponent(m[1]), f = FILES[name];
    if (!f) { alert('این فایل در گاوصندوق این مرورگر نیست 📁'); return; }
    const url = URL.createObjectURL(new Blob([f.content], { type: 'text/plain;charset=utf-8' }));
    const a2 = document.createElement('a'); a2.href = url; a2.download = name; a2.click();
    setTimeout(() => URL.revokeObjectURL(url), 3000);
  });
}
console.log('🐠 Diana Browser Backend آماده است — ارتش:', AGENTS.length, 'ایجنت | مغز:', llmMode());
