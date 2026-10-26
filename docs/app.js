// 🐠 Diana App — منطق کامل رابط کاربری سیستم چندعامله دیانا
// چت زنده + صدا (TTS/STT) + مغز ابری رایگان از مرورگر + رویدادهای زنده ارکستراتور (SSE)
'use strict';

const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const Fish = {
  say: (...a) => window.DianaFish?.say?.(...a),
  setMood: (...a) => window.DianaFish?.setMood?.(...a),
  setSpeaking: (...a) => window.DianaFish?.setSpeaking?.(...a),
  pulseDept: (...a) => window.DianaFish?.pulseDept?.(...a),
  feed: (...a) => window.DianaFish?.feed?.(...a),
};
const FA_DIGITS = '۰۱۲۳۴۵۶۷۸۹';
const faNum = n => String(n).replace(/\d/g, d => FA_DIGITS[d]);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const nowTime = () => new Date().toLocaleTimeString('fa-IR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

const api = {
  async get(u) { const r = await fetch(u); return r.json(); },
  async post(u, body) { const r = await fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); return r.json(); },
  async del(u) { const r = await fetch(u, { method: 'DELETE' }); return r.json(); },
};

// ---------- رندر امن Markdown ساده ----------
function md(text) {
  const blocks = [];
  let t = String(text ?? '').replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    blocks.push(`<pre><code>${esc(code.replace(/\n$/, ''))}</code></pre>`);
    return `\u0001${blocks.length - 1}\u0001`;
  });
  t = esc(t);
  t = t.replace(/!\[([^\]]*)\]\((https?:[^)\s]+)\)/g, '<img class="gen-img" alt="$1" src="$2" loading="lazy">');
  t = t.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  t = t.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  t = t.replace(/(^|\s)\*([^*\n]+)\*/g, '$1<i>$2</i>');
  t = t.replace(/`([^`\n]+)`/g, '<code>$1</code>');
  const lines = t.split('\n').map(line => {
    if (/^\s*-{3,}\s*$/.test(line)) return '<hr>';
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) return `<h${h[1].length}>${h[2]}</h${h[1].length}>`;
    if (/^\s*[•\-☐☑️✔️]/.test(line) || /^\s*\d+[.)\-]\s/.test(line)) return `<div>${line}</div>`;
    return line === '' ? '<div class="md-sp"></div>' : `<div>${line}</div>`;
  });
  t = lines.join('');
  t = t.replace(/\u0001(\d+)\u0001/g, (_, i) => blocks[+i]);
  return t;
}
function stripForSpeech(text) {
  return String(text ?? '')
    .replace(/```[\s\S]*?```/g, ' (کد ضمیمه شده) ')
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, 'تصویر ساخته شد')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[#*_>`☐☑️\-•]/g, ' ')
    .replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE0F}]/gu, '')
    .replace(/\s+/g, ' ').trim();
}

// ---------- وضعیت سراسری ----------
let settings = { voice: true, cloud_brain: true };
let userName = '';
let memoryFacts = [];
let chatHistory = [];           // {role:'user'|'assistant', content}
let agentsRegistry = null;
let agentRuns = {};
let currentMission = null;      // {id, goal, plan, cards:Map, done, total}
let activeAgents = 0;
let greetedWithVoice = false;

function toast(msg, ms = 3400) {
  const el = $('#toast'); el.textContent = msg; el.hidden = false;
  clearTimeout(el._t); el._t = setTimeout(() => el.hidden = true, ms);
}

// ---------- صدای دیانا ----------
let voices = [];
function refreshVoices() { try { voices = speechSynthesis.getVoices(); } catch (e) {} }
if ('speechSynthesis' in window) { refreshVoices(); speechSynthesis.onvoiceschanged = refreshVoices; }
function pickVoice(text) {
  if (!voices.length) refreshVoices();
  const latin = (text.match(/[A-Za-z]/g) || []).length > text.length * 0.4;
  if (!latin) {
    const fa = voices.find(v => /^fa/i.test(v.lang));
    if (fa) return fa;
    const ar = voices.find(v => /^ar/i.test(v.lang));
    if (ar) return ar;
  }
  return voices.find(v => /female|zira|samantha|google us english/i.test(v.name)) || voices.find(v => /^en/i.test(v.lang)) || voices[0];
}
function speak(text) {
  if (!settings.voice || !('speechSynthesis' in window)) return;
  const clean = stripForSpeech(text);
  if (!clean) return;
  try {
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(clean.slice(0, 650));
    const v = pickVoice(clean);
    if (v) { u.voice = v; u.lang = v.lang; } else u.lang = 'fa-IR';
    u.rate = 1.03; u.pitch = 1.18;
    u.onstart = () => Fish.setSpeaking(true);
    u.onend = u.onerror = () => Fish.setSpeaking(false);
    speechSynthesis.speak(u);
  } catch (e) { Fish.setSpeaking(false); }
}
let bubbleTimer = null;
function showSpeechBubble(text) {
  const el = $('#speechBubble');
  const clean = stripForSpeech(text);
  if (!clean) return;
  el.textContent = clean.length > 170 ? clean.slice(0, 170) + '…' : clean;
  el.hidden = false;
  clearTimeout(bubbleTimer);
  bubbleTimer = setTimeout(() => el.hidden = true, Math.min(14000, Math.max(3600, clean.length * 95)));
}
function dianaSay(text, { speakIt = true } = {}) {
  showSpeechBubble(text);
  Fish.say();
  if (speakIt) speak(text);
}

// ---------- ناوبری صفحات ----------
function goPage(name) {
  $$('.nav-btn').forEach(b => b.classList.toggle('active', b.dataset.page === name));
  $$('.page').forEach(p => p.classList.toggle('active', p.id === 'page-' + name));
  if (name === 'agents') loadAgentsPage();
  if (name === 'missions') loadMissionsPage();
  if (name === 'vault') loadVaultPage();
  if (name === 'settings') loadSettingsPage();
  if (name === 'home') refreshHomeStats();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
$('#mainNav').addEventListener('click', e => {
  const b = e.target.closest('.nav-btn'); if (b) goPage(b.dataset.page);
});

// ---------- چت ----------
const chatBox = $('#chatMessages');
function scrollChat() { chatBox.scrollTop = chatBox.scrollHeight; }
function srcBadge(source) {
  const map = {
    local: '🧠 مغز داخلی', orchestrator: '⚡ ارکستراتور',
    pollinations: '☁️ مغز ابری رایگان', 'pollinations-get': '☁️ مغز ابری رایگان',
    'pollinations-browser': '☁️ مغز ابری رایگان', groq: '☁️ Groq', gemini: '☁️ Gemini', openrouter: '☁️ OpenRouter',
  };
  return source && map[source] ? `<span class="src-badge">${map[source]}</span><br>` : '';
}
function addBubble(role, text, source = '', extraHtml = '') {
  const wrap = document.createElement('div');
  wrap.className = 'msg ' + (role === 'user' ? 'user' : 'diana');
  wrap.innerHTML = `<div class="avatar">${role === 'user' ? '🧑' : '🐠'}</div>
    <div class="bubble">${role === 'diana' ? srcBadge(source) : ''}<span class="bubble-text markdown">${role === 'user' ? esc(text).replace(/\n/g, '<br>') : md(text)}</span>${extraHtml}</div>`;
  chatBox.appendChild(wrap);
  scrollChat();
  return wrap;
}
function addTyping() {
  const wrap = document.createElement('div');
  wrap.className = 'msg diana'; wrap.id = 'typingMsg';
  wrap.innerHTML = `<div class="avatar">🐠</div><div class="bubble"><span class="typing"><i></i><i></i><i></i></span></div>`;
  chatBox.appendChild(wrap); scrollChat();
}
function removeTyping() { $('#typingMsg')?.remove(); }

const DIANA_SYSTEM_BROWSER = `تو «دیانا» هستی؛ یک ماهی طلایی زنده، باهوش، مهربان و پرانرژی که مغز یک سیستم چندعامله با ۱۲۰ ایجنت متخصص هستی و در آکواریوم سه‌بعدی زندگی می‌کنی. صمیمی و کمک‌کننده‌ای، گاهی ایموجی 🐠💙🫧 به‌کار می‌بری ولی کم. همیشه به زبان کاربر جواب بده (فارسی نوشت، فارسی). پاسخ مفید، دقیق، گرم و نه‌چندان طولانی بده.`;

async function pollinationsChat(msgs, timeoutMs = 45000) {
  // مغز ابری رایگان از سمت مرورگر — Pollinations بدون کلید و ثبت‌نام
  const ctrl = new AbortController();
  const to = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch('https://text.pollinations.ai/openai', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: 'openai', messages: msgs }), signal: ctrl.signal,
    });
    clearTimeout(to);
    if (!r.ok) throw new Error('bad');
    const j = await r.json();
    const out = j?.choices?.[0]?.message?.content?.trim();
    if (out) return out;
    throw new Error('empty');
  } catch (e) {
    clearTimeout(to);
    try {
      const flat = msgs.map(m => m.content).join('\n').slice(-4500);
      const r2 = await fetch('https://text.pollinations.ai/' + encodeURIComponent(flat) + '?model=openai');
      if (r2.ok) { const t = (await r2.text()).trim(); if (t.length > 2) return t; }
    } catch (_) {}
    return null;
  }
}

async function browserCloudReply(userText) {
  let sys = DIANA_SYSTEM_BROWSER;
  if (userName) sys += `\nاسم کاربر (فرمانده): ${userName}`;
  if (memoryFacts.length) sys += `\nچیزهایی که از کاربر به خاطر سپرده‌ای:\n` + memoryFacts.slice(-10).map(f => '- ' + f.text).join('\n');
  const msgs = [{ role: 'system', content: sys },
    ...chatHistory.slice(-8), { role: 'user', content: userText }];
  return pollinationsChat(msgs, 35000);
}

// تکمیل واقعی مأموریت با مغز ابری مرورگر، وقتی سرور آفلاین بوده و خروجی‌ها اسکلتی شدن
let missionGoal = '', missionHadOffline = false, missionEnhancing = false;
async function enhanceMissionWithCloud(e) {
  if (missionEnhancing || !settings.cloud_brain) return;
  missionEnhancing = true;
  cmdLog('☁️ مغز ابری مرورگر: سرور آفلاین بود — در حال تکمیل واقعی مأموریت با هوش مصنوعی رایگان...');
  setFishMood('☁️ دیانا در حال تکمیل گزارش با مغز ابری...');
  Fish.setMood('thinking');
  const prompt = `هدف مأموریت کاربر: «${missionGoal}»\n\nمتخصص‌های آفلاین من این اسکلت اولیه را ساخته‌اند:\n${(e.report || '').slice(0, 3200)}\n\nحالا تو به‌عنوان مغز ابری دیانا، این مأموریت را کاملاً واقعی و کامل انجام بده: یک گزارش نهایی فارسیِ غنی، دقیق و کاربردی با قالب Markdown بنویس که مستقیم و کامل به هدف کاربر پاسخ دهد (خودِ محتوای کامل را بنویس، نه اسکلت و چارچوب). اگر موضوع نیاز به دانش دارد، دانش دقیق خودت را با جزئیات و مثال بنویس. در پایان یک جمع‌بندی کوتاه و گرم از زبان دیانا 🐠 اضافه کن.`;
  const out = await pollinationsChat([
    { role: 'system', content: DIANA_SYSTEM_BROWSER },
    { role: 'user', content: prompt },
  ], 60000);
  if (out) {
    const fname = `report-${e.mission_id}-cloud.md`;
    await api.post('/api/files', { name: fname, content: out });
    $('#cmdReport').innerHTML = `<div style="background:rgba(52,211,153,.08);border:1px solid rgba(52,211,153,.35);border-radius:12px;padding:12px;margin-bottom:12px"><b>☁️ نسخه کامل ابری گزارش</b> — با مغز رایگان Pollinations تکمیل شد و در گاوصندوق ذخیره شد (<a href="/api/files/${encodeURIComponent(fname)}/download">⬇️ دانلود</a>)</div>` + md(out) + '<hr><h3>📋 نسخه اسکلت آفلاین سرور:</h3>' + $('#cmdReport').innerHTML;
    addBubble('diana', '☁️ فرمانده! چون سرورم آفلاین بود، گزارش رو با **مغز ابری رایگان** کامل و واقعی کردم و تو گاوصندوق ذخیره‌اش کردم. اینم نسخه کامل👇', 'pollinations-browser',
      `<details open style="margin-top:8px"><summary style="cursor:pointer;color:#6ee7b7;font-size:12px">☁️ گزارش کامل ابری مأموریت</summary><div class="markdown" style="margin-top:8px">${md(out)}</div></details>`);
    api.post('/api/chatlog', { role: 'diana', text: '☁️ نسخه کامل ابری گزارش آماده شد:\n\n' + out.slice(0, 3500), source: 'pollinations-browser' });
    cmdLog('☁️✅ نسخه کامل ابری گزارش ساخته و در گاوصندوق ذخیره شد: ' + fname);
    dianaSay('فرمانده! گزارش رو با مغز ابری رایگان کاملش کردم! تو چت و مرکز فرماندهی گذاشتمش 🐠☁️');
    refreshHomeStats();
  } else {
    cmdLog('☁️⚠️ مغز ابری مرورگر هم در دسترس نبود — نسخه آفلاین سرور تحویل داده شد');
  }
  setFishMood('🎉 مأموریت با موفقیت انجام شد!');
  Fish.setMood('celebrate');
  missionEnhancing = false;
}

let sending = false;
async function sendMessage(rawText) {
  const text = (rawText ?? $('#chatInput').value).trim();
  if (!text || sending) return;
  sending = true;
  $('#chatInput').value = ''; autoGrow($('#chatInput'));
  addBubble('user', text);
  chatHistory.push({ role: 'user', content: text });
  addTyping();
  Fish.setMood('thinking'); setFishMood('🧠 دیانا داره فکر می‌کنه...');
  try {
    const res = await api.post('/api/message', { text });
    removeTyping();
    if (res.kind === 'mission') {
      currentMissionId = res.mission_id;
      addBubble('diana', res.reply, 'orchestrator',
        `<br><button class="go-cmd" onclick="goPage('command')">🧠 مشاهده زنده در مرکز فرماندهی</button>`);
      dianaSay('چشم فرمانده! مأموریت رو گرفتم و متخصص‌هام رو به کار انداختم. تو مرکز فرماندهی زنده تماشاش کن!');
      chatHistory.push({ role: 'assistant', content: res.reply });
      $('#cmdLiveDot').hidden = false;
    } else if (res.upgradeable && settings.cloud_brain) {
      const bubble = addBubble('diana', res.reply, 'local');
      setFishMood('☁️ در حال اتصال به مغز ابری رایگان...');
      const cloud = await browserCloudReply(text);
      if (cloud) {
        bubble.querySelector('.bubble').innerHTML = srcBadge('pollinations-browser') + `<span class="bubble-text markdown">${md(cloud)}</span>`;
        scrollChat();
        api.post('/api/chatlog', { role: 'diana', text: cloud, source: 'pollinations-browser' });
        chatHistory.push({ role: 'assistant', content: cloud });
        dianaSay(cloud);
      } else {
        api.post('/api/chatlog', { role: 'diana', text: res.reply, source: 'local' });
        chatHistory.push({ role: 'assistant', content: res.reply });
        dianaSay(res.reply);
      }
      setFishMood('🐠 دیانا سرحاله');
    } else {
      addBubble('diana', res.reply, res.source || 'local');
      chatHistory.push({ role: 'assistant', content: res.reply });
      dianaSay(res.reply);
      setFishMood('🐠 دیانا سرحاله');
    }
    if (res.kind === 'set_name') refreshHomeStats();
  } catch (e) {
    removeTyping();
    addBubble('diana', 'اوه! 🌊 یه موج ارتباطم با سرور رو قطع کرد. مطمئن شو سرور دیانا روشنه و دوباره تلاش کن فرمانده!', 'local');
    setFishMood('🐠 دیانا سرحاله');
  }
  Fish.setMood('idle');
  sending = false;
}
function setFishMood(t) { $('#fishMood').textContent = t; }
function setActiveAgents(n) { activeAgents = Math.max(0, n); $('#activeAgentsChip').textContent = `⚡ ایجنت فعال: ${faNum(activeAgents)}`; }

$('#sendBtn').addEventListener('click', () => sendMessage());
$('#chatInput').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});
function autoGrow(el) { el.style.height = 'auto'; el.style.height = Math.min(110, el.scrollHeight) + 'px'; }
$('#chatInput').addEventListener('input', e => autoGrow(e.target));
$('#quickChips').addEventListener('click', e => {
  const c = e.target.closest('.chip'); if (!c) return;
  if (c.textContent.includes('اسمم رو یاد بگیر')) {
    $('#chatInput').value = 'سلام دیانا! اسمم ... هست';
    $('#chatInput').focus();
    toast('✏️ اسمت رو جای سه‌نقطه بنویس و ارسال کن تا دیانا یاد بگیره!');
    return;
  }
  sendMessage(c.textContent.replace(/\s*[🔬💻🎨🧮✈️📚]\s*$/u, '').trim());
});
$('#clearChatBtn').addEventListener('click', () => { chatBox.innerHTML = ''; toast('🧹 نمای گفتگو پاک شد (حافظه دیانا سر جاشه)'); });
$('#voiceQuickToggle').addEventListener('click', async () => {
  settings.voice = !settings.voice;
  $('#voiceQuickToggle').textContent = settings.voice ? '🔊' : '🔇';
  $('#voiceQuickToggle').classList.toggle('off', !settings.voice);
  if (!settings.voice && 'speechSynthesis' in window) speechSynthesis.cancel();
  await api.post('/api/settings', { voice: settings.voice });
  toast(settings.voice ? '🔊 صدای دیانا روشن شد' : '🔇 صدای دیانا خاموش شد');
  if (settings.voice) dianaSay('صدام برگشت! سلام فرمانده 🐠');
});

// تشخیص صدا (صحبت با دیانا)
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
if (SR) {
  const rec = new SR(); rec.lang = 'fa-IR'; rec.interimResults = false;
  rec.onresult = e => { const tx = e.results[0][0].transcript; $('#chatInput').value = tx; sendMessage(tx); };
  rec.onend = () => $('#micBtn').classList.remove('recording');
  rec.onerror = () => { $('#micBtn').classList.remove('recording'); toast('🎤 میکروفون در دسترس نیست یا اجازه داده نشد'); };
  $('#micBtn').addEventListener('click', () => {
    try { $('#micBtn').classList.add('recording'); rec.start(); toast('🎤 دارم گوش می‌دم فرمانده...'); } catch (e) {}
  });
} else {
  $('#micBtn').addEventListener('click', () => toast('🎤 این مرورگر تشخیص صدا نداره؛ کروم رو امتحان کن'));
}

// ---------- رویدادهای زنده ارکستراتور (SSE) ----------
let currentMissionId = null;
function cmdLog(text) {
  const log = $('#cmdLog');
  const line = document.createElement('div');
  line.className = 'log-line';
  line.innerHTML = `<span class="log-time">${nowTime()}</span>${esc(text)}`;
  log.appendChild(line); log.scrollTop = log.scrollHeight;
}
function resetCommandUI(goal) {
  missionGoal = goal; missionHadOffline = false;
  $('#cmdAgents').innerHTML = '';
  $('#cmdReport').innerHTML = '<div class="empty-box">⏳ متخصص‌ها در حال کارن... گزارش نهایی اینجا میاد</div>';
  $('#cmdProgress').style.width = '4%';
  $('#brainOrb').classList.add('thinking');
  $('#brainState').textContent = '🧠 ارکستراتور در حال برنامه‌ریزی...';
  $('#cmdMeta').innerHTML = `🎯 <b>هدف مأموریت:</b> ${esc(goal)}`;
  $('#cmdLiveDot').hidden = false;
  currentMission = { plan: [], done: 0, total: 0 };
  Fish.setMood('thinking'); setFishMood('🧠 دیانا و ارتشش در حال اجرای مأموریتن...');
}
function renderPlanCards(plan) {
  const box = $('#cmdAgents'); box.innerHTML = '';
  plan.forEach(sub => {
    const card = document.createElement('div');
    card.className = 'live-agent'; card.id = 'sub-' + sub.id;
    card.innerHTML = `<div class="la-head"><span class="la-emoji">⏳</span>
      <div><div class="la-name">${esc(sub.title)}</div><div class="la-dept">در انتظار شروع</div></div></div>
      <div class="la-task">${esc(sub.instruction)}</div>
      <div class="la-status">⏸️ در صف اجرا</div>`;
    box.appendChild(card);
  });
}
function updateProgress() {
  if (!currentMission || !currentMission.total) return;
  $('#cmdProgress').style.width = Math.round((currentMission.done / currentMission.total) * 100) + '%';
}

function connectSSE() {
  const es = new EventSource('/api/events');
  es.onmessage = ev => {
    let e; try { e = JSON.parse(ev.data); } catch (_) { return; }
    switch (e.type) {
      case 'mission_created':
        currentMissionId = e.mission.id;
        resetCommandUI(e.mission.goal);
        cmdLog(`🚀 مأموریت جدید ساخته شد: ${e.mission.goal}`);
        break;
      case 'plan_ready':
        if (currentMission) { currentMission.plan = e.plan; currentMission.total = e.plan.length; }
        renderPlanCards(e.plan);
        $('#brainState').textContent = `⚡ ${faNum(e.plan.length)} متخصص موازی در حال اجرا...`;
        cmdLog(`📋 برنامه ارکستراتور: ${e.plan.map(p => p.title).join(' + ')}`);
        break;
      case 'orchestrator_log':
        cmdLog(e.text);
        break;
      case 'agent_started': {
        setActiveAgents(activeAgents + 1);
        Fish.pulseDept(e.agent.color);
        const card = $('#sub-' + e.subtask.id);
        if (card) {
          card.classList.add('working');
          card.style.setProperty('--dept', e.agent.color);
          card.querySelector('.la-emoji').textContent = e.agent.emoji;
          card.querySelector('.la-dept').textContent = `${e.agent.dept_emoji} ${e.agent.dept_fa} • ${e.agent.en}`;
          card.querySelector('.la-status').innerHTML = '<span class="spinner"></span> در حال اجرا با ابزار واقعی...';
        }
        cmdLog(`▶️ ${e.agent.emoji} ${e.agent.fa} شروع کرد`);
        break;
      }
      case 'evaluation':
        cmdLog(`🔍 ارزیاب کیفیت: امتیاز ${faNum(e.score)}/۱۰۰ (تلاش ${faNum(e.attempt)}) — ${e.verdict}`);
        break;
      case 'agent_done': {
        if ((e.result.output || '').includes('حالت آفلاین')) missionHadOffline = true;
        setActiveAgents(activeAgents - 1);
        if (currentMission) { currentMission.done++; updateProgress(); }
        const card = $('#sub-' + e.result.id);
        if (card) {
          card.classList.remove('working'); card.classList.add('done');
          card.querySelector('.la-status').innerHTML = e.result.ok ? '✅ انجام شد' : '⚠️ ناقص انجام شد';
          const badge = document.createElement('span');
          badge.className = 'score-badge'; badge.title = e.result.verdict;
          badge.textContent = `${faNum(e.result.score)} امتیاز`;
          card.appendChild(badge);
          const det = document.createElement('details');
          det.innerHTML = `<summary style="cursor:pointer;font-size:11.5px;color:#67e8f9;margin-top:7px">📄 مشاهده خروجی متخصص</summary><div class="markdown" style="margin-top:7px">${md(e.result.output)}</div>`;
          card.appendChild(det);
        }
        cmdLog(`✅ ${e.result.agent.emoji} ${e.result.agent.fa} تحویل داد — نظر ارزیاب: ${e.result.verdict}`);
        break;
      }
      case 'mission_done': {
        $('#cmdProgress').style.width = '100%';
        $('#brainOrb').classList.remove('thinking');
        $('#brainState').textContent = `🏆 مأموریت کامل شد! امتیاز کیفی نهایی: ${faNum(e.score)}/۱۰۰`;
        $('#cmdLiveDot').hidden = true;
        $('#cmdReport').innerHTML = md(e.report) +
          (e.report_file ? `<br><a class="mini-btn" href="/api/files/${encodeURIComponent(e.report_file)}/download">⬇️ دانلود فایل گزارش (${esc(e.report_file)})</a>` : '');
        cmdLog(`🎁 گزارش نهایی ترکیب و در گاوصندوق ذخیره شد (${e.report_file || ''})`);
        Fish.setMood('celebrate'); setFishMood('🎉 مأموریت با موفقیت انجام شد!');
        setActiveAgents(0); refreshHomeStats();
        if (!$('#page-command').classList.contains('active') && !$('#page-home').classList.contains('active'))
          toast('🎉 دیانا مأموریت رو تموم کرد! گزارش در مرکز فرماندهیه');
        if (missionHadOffline) enhanceMissionWithCloud(e);
        break;
      }
      case 'diana_say': {
        addBubble('diana', e.text, 'orchestrator',
          `<details style="margin-top:8px"><summary style="cursor:pointer;color:#fde68a;font-size:12px">📄 مشاهده گزارش کامل مأموریت</summary><div class="markdown" style="margin-top:8px">${md(e.report)}</div></details>`);
        chatHistory.push({ role: 'assistant', content: e.text });
        dianaSay(e.text);
        break;
      }
      case 'mission_failed':
        $('#brainOrb').classList.remove('thinking');
        $('#cmdLiveDot').hidden = true; setActiveAgents(0);
        cmdLog('❌ مأموریت با خطا متوقف شد: ' + e.error);
        toast('❌ مأموریت ناموفق بود؛ جزئیات در مرکز فرماندهی');
        break;
    }
  };
  es.onerror = () => { /* EventSource خودش وصل می‌شه */ };
}
$('#cmdStartBtn').addEventListener('click', startMissionFromCmd);
$('#cmdGoalInput').addEventListener('keydown', e => { if (e.key === 'Enter') startMissionFromCmd(); });
async function startMissionFromCmd() {
  const goal = $('#cmdGoalInput').value.trim();
  if (!goal) { toast('🎯 اول هدف مأموریت رو بنویس فرمانده!'); return; }
  $('#cmdGoalInput').value = '';
  await api.post('/api/mission', { goal });
  toast('🚀 مأموریت شروع شد! ارکستراتور در حال برنامه‌ریزیه...');
  dianaSay('مأموریت جدید رو از مرکز فرماندهی گرفتم! دارم ارتشم رو به خط می‌کنم 🧠⚡');
}

// ---------- صفحه ارتش ایجنت‌ها ----------
let activeDept = 'all', selectedAgent = null;
const EXEC_LABELS = { llm: '🧠 مغز هوشمند', web: '🌐 وب زنده', coder: '💻 اجرای کد', data: '🧮 محاسبات', text: '📄 پردازش متن', files: '📁 فایل واقعی', memory: '💾 حافظه', planner: '🗓️ برنامه‌ساز', artist: '🎨 تصویرساز', system: '🖥️ سیستم' };
async function loadAgentsPage() {
  if (!agentsRegistry) agentsRegistry = await api.get('/api/agents');
  const st = await api.get('/api/status'); agentRuns = st.stats?.agents_runs || {};
  const filters = $('#deptFilters');
  if (!filters.children.length) {
    const all = document.createElement('button');
    all.className = 'dept-chip active'; all.dataset.dept = 'all'; all.textContent = '🌟 همه ارتش';
    filters.appendChild(all);
    agentsRegistry.departments.forEach(d => {
      const b = document.createElement('button');
      b.className = 'dept-chip'; b.dataset.dept = d.id; b.style.setProperty('--chip', d.color);
      b.textContent = `${d.emoji} ${d.fa}`; filters.appendChild(b);
    });
    filters.addEventListener('click', e => {
      const b = e.target.closest('.dept-chip'); if (!b) return;
      activeDept = b.dataset.dept;
      $$('.dept-chip').forEach(x => x.classList.toggle('active', x === b));
      renderAgents();
    });
  }
  renderAgents();
}
function renderAgents() {
  const q = ($('#agentSearch').value || '').trim();
  const list = agentsRegistry.agents.filter(a =>
    (activeDept === 'all' || a.dept === activeDept) &&
    (!q || (a.fa + a.en + a.desc + a.keywords + a.dept_fa).includes(q)));
  $('#agentsCount').textContent = `نمایش ${faNum(list.length)} متخصص از ${faNum(agentsRegistry.total)} ایجنت ارتش دیانا`;
  $('#agentsGrid').innerHTML = list.map(a => `
    <div class="agent-card" data-id="${a.id}" style="--dept:${a.color}" title="کلیک کن و به این متخصص مأموریت بده">
      <div class="ac-emoji">${a.emoji}</div>
      <div class="ac-fa">${esc(a.fa)}</div><div class="ac-en">${esc(a.en)}</div>
      <div class="ac-desc">${esc(a.desc)}</div>
      <div class="ac-meta"><span class="ac-dept">${a.dept_emoji} ${esc(a.dept_fa)}</span>
      <span class="ac-runs">${agentRuns[a.id] ? `🏅 ${faNum(agentRuns[a.id])} مأموریت` : ''}</span>
      <span class="ac-exec">${EXEC_LABELS[a.executor] || a.executor}</span></div>
    </div>`).join('') || '<div class="empty-box">متخصصی با این مشخصات پیدا نشد 🔍</div>';
}
$('#agentSearch').addEventListener('input', () => agentsRegistry && renderAgents());
$('#agentsGrid').addEventListener('click', e => {
  const card = e.target.closest('.agent-card'); if (!card) return;
  selectedAgent = agentsRegistry.agents.find(a => a.id === card.dataset.id);
  $('#modalAgentInfo').innerHTML = `
    <div class="modal-agent-head"><div class="ma-emoji">${selectedAgent.emoji}</div>
    <div><div class="ma-fa">${esc(selectedAgent.fa)}</div>
    <div class="ma-desc">${selectedAgent.dept_emoji} دپارتمان ${esc(selectedAgent.dept_fa)} • ${EXEC_LABELS[selectedAgent.executor]}<br>${esc(selectedAgent.desc)}</div></div></div>`;
  $('#modalTask').value = '';
  $('#agentModal').hidden = false;
  $('#modalTask').focus();
});
$('#modalClose').addEventListener('click', () => $('#agentModal').hidden = true);
$('#agentModal').addEventListener('click', e => { if (e.target.id === 'agentModal') e.target.hidden = true; });
$('#modalRun').addEventListener('click', async () => {
  const task = $('#modalTask').value.trim();
  if (!task || !selectedAgent) { toast('📝 مأموریت رو بنویس فرمانده!'); return; }
  $('#agentModal').hidden = true;
  await api.post('/api/agent/run', { agent_id: selectedAgent.id, task });
  goPage('command');
  toast(`🚀 ${selectedAgent.emoji} ${selectedAgent.fa} مأموریت رو گرفت و شروع کرد!`);
  dianaSay(`${selectedAgent.fa} رو مستقیم مأمور کردی! دارم روش نظارت می‌کنم و نتیجه رو اعلام می‌کنم 🐠`);
});

// ---------- صفحه مأموریت‌ها ----------
async function loadMissionsPage() {
  const mem = await api.get('/api/memory');
  const list = $('#missionsList');
  if (!mem.missions.length) { list.innerHTML = '<div class="empty-box">هنوز مأموریتی انجام نشده. اولین فرمان رو از آکواریوم بده! 🐠</div>'; return; }
  list.innerHTML = mem.missions.map(m => `
    <div class="mission-item" data-id="${m.id}">
      <div class="mi-goal">🎯 ${esc(m.goal)}</div>
      <div class="mi-meta"><span>${m.status === 'done' ? '✅ انجام‌شده' : m.status === 'running' ? '⚡ در حال اجرا' : m.status}</span>
      ${m.score != null ? `<span class="mi-score">⭐ ${faNum(m.score)}/۱۰۰</span>` : ''}<span>${esc(m.ts || '')}</span></div>
    </div>`).join('');
}
$('#missionsList').addEventListener('click', async e => {
  const item = e.target.closest('.mission-item'); if (!item) return;
  const m = await api.get('/api/missions/' + item.dataset.id);
  $('#missionDetail').innerHTML = (m.report ? md(m.report) : '<div class="empty-box">این مأموریت هنوز گزارشی نداره</div>') +
    (m.report_file ? `<br><a class="mini-btn" href="/api/files/${encodeURIComponent(m.report_file)}/download">⬇️ دانلود گزارش</a>` : '');
});

// ---------- صفحه گاوصندوق و حافظه ----------
async function loadVaultPage() {
  const [filesRes, mem] = await Promise.all([api.get('/api/files'), api.get('/api/memory')]);
  memoryFacts = mem.facts || [];
  $('#filesList').innerHTML = filesRes.files.length ? filesRes.files.map(f => `
    <div class="file-row"><span>📄</span><span class="fname">${esc(f.name)}</span>
    <span class="fmeta">${faNum(f.size)} بایت • ${esc(f.modified)}</span>
    <a class="mini-btn" href="/api/files/${encodeURIComponent(f.name)}/download">⬇️ دانلود</a>
    <button class="mini-btn danger" data-del-file="${esc(f.name)}">🗑️</button></div>`).join('')
    : '<div class="empty-box">گاوصندوق خالیه — به دیانا بگو فایل بسازه یا خودت از پایین بساز 📁</div>';
  $('#factsList').innerHTML = memoryFacts.length ? [...memoryFacts].reverse().map(f => `
    <div class="fact-row"><span>💾</span><span class="fact-text">${esc(f.text)}</span>
    <span class="fmeta">${esc(f.ts)}</span><button class="mini-btn danger" data-del-fact="${f.id}">🗑️</button></div>`).join('')
    : '<div class="empty-box">دیانا هنوز چیزی ازت به خاطر نسپرده. بهش بگو: «یادت باشه که...» 🧠</div>';
  $('#remindersList').innerHTML = mem.reminders.length ? mem.reminders.map(r => `
    <div class="rem-row"><span>⏰</span><span class="fact-text">${esc(r.text)}</span><span class="fmeta">${esc(r.ts)}</span></div>`).join('')
    : '<div class="empty-box">یادآوری‌ای ثبت نشده</div>';
}
$('#filesList').addEventListener('click', async e => {
  const b = e.target.closest('[data-del-file]'); if (!b) return;
  await api.del('/api/files/' + encodeURIComponent(b.dataset.delFile));
  toast('🗑️ فایل حذف شد'); loadVaultPage(); refreshHomeStats();
});
$('#factsList').addEventListener('click', async e => {
  const b = e.target.closest('[data-del-fact]'); if (!b) return;
  await api.del('/api/memory/fact/' + b.dataset.delFact);
  toast('🧠 از حافظه دیانا پاک شد'); loadVaultPage();
});
$('#createFileBtn').addEventListener('click', async () => {
  const name = $('#newFileName').value.trim() || 'note.txt';
  const content = $('#newFileContent').value;
  await api.post('/api/files', { name, content });
  $('#newFileName').value = ''; $('#newFileContent').value = '';
  toast('📁 فایل در گاوصندوق ساخته شد'); loadVaultPage(); refreshHomeStats();
});
$('#addFactBtn').addEventListener('click', async () => {
  const text = $('#newFactInput').value.trim(); if (!text) return;
  await api.post('/api/memory/fact', { text });
  $('#newFactInput').value = '';
  toast('💾 دیانا به خاطر سپردش!'); dianaSay('به خاطر سپردمش فرمانده! دیگه هیچ‌وقت یادم نمیره 💾🐠');
  loadVaultPage(); refreshHomeStats();
});

// ---------- صفحه تنظیمات ----------
function setToggle(el, on) { el.classList.toggle('on', on); el.textContent = on ? 'روشن' : 'خاموش'; }
async function loadSettingsPage() {
  const s = await api.get('/api/settings');
  const st = await api.get('/api/status');
  settings.voice = s.voice; settings.cloud_brain = s.cloud_brain;
  $('#setName').value = st.user_name || '';
  setToggle($('#setVoice'), !!s.voice); setToggle($('#setCloud'), !!s.cloud_brain);
  $('#keyGroq').value = s.groq_key_set ? '••••••' : '';
  $('#keyGemini').value = s.gemini_key_set ? '••••••' : '';
  $('#keyOpenrouter').value = s.openrouter_key_set ? '••••••' : '';
}
$('#setVoice').addEventListener('click', e => { settings.voice = !settings.voice; setToggle(e.target, settings.voice); });
$('#setCloud').addEventListener('click', e => { settings.cloud_brain = !settings.cloud_brain; setToggle(e.target, settings.cloud_brain); });
$('#saveSettingsBtn').addEventListener('click', async () => {
  const body = {
    user_name: $('#setName').value.trim(), voice: settings.voice, cloud_brain: settings.cloud_brain,
    groq_key: $('#keyGroq').value, gemini_key: $('#keyGemini').value, openrouter_key: $('#keyOpenrouter').value,
  };
  const res = await api.post('/api/settings', body);
  $('#settingsMsg').textContent = `✅ ذخیره شد! مغز فعال دیانا الان: ${res.llm_mode}`;
  $('#voiceQuickToggle').textContent = settings.voice ? '🔊' : '🔇';
  userName = body.user_name;
  updateBrainPill(res.llm_mode);
  dianaSay('تنظیمات مغزم به‌روز شد فرمانده! 🧠🐠');
});
function updateBrainPill(mode, internet) {
  let label = mode || 'local (آفلاین)';
  if ((mode || '').startsWith('local') && settings.cloud_brain) label = 'مغز داخلی + ☁️ ابری رایگان مرورگر';
  else if (!(mode || '').startsWith('local')) label = '☁️ مغز ابری: ' + mode;
  $('#brainModeText').textContent = `🧠 ${label}`;
  $('#statusPill').title = `اینترنت سرور: ${internet ? 'متصل ✅' : 'قطع 📴 (مرورگر تو مغز ابری رو تأمین می‌کنه)'} | حالت مغز سرور: ${mode}`;
}

// ---------- آمار خانه و راه‌اندازی ----------
async function refreshHomeStats() {
  try {
    const [st, filesRes] = await Promise.all([api.get('/api/status'), api.get('/api/files')]);
    settings.voice = st.settings.voice; settings.cloud_brain = st.settings.cloud_brain;
    userName = st.user_name || '';
    $('#statMissions').textContent = faNum(st.stats.missions_done || 0);
    $('#statFiles').textContent = faNum(filesRes.files.length);
    $('#voiceQuickToggle').textContent = settings.voice ? '🔊' : '🔇';
    updateBrainPill(st.llm_mode, st.internet);
  } catch (e) {}
  try {
    const mem = await api.get('/api/memory');
    memoryFacts = mem.facts || [];
    $('#statFacts').textContent = faNum(memoryFacts.length);
  } catch (e) {}
}

async function init() {
  connectSSE();
  await refreshHomeStats();
  // بارگذاری تاریخچه گفتگو از حافظه ماندگار
  let hasHistory = false;
  try {
    const mem = await api.get('/api/memory');
    const convs = mem.conversations || [];
    if (convs.length) {
      hasHistory = true;
      convs.slice(-24).forEach(c => {
        addBubble(c.role === 'user' ? 'user' : 'diana', c.text, c.source || '');
        chatHistory.push({ role: c.role === 'user' ? 'user' : 'assistant', content: c.text });
      });
    }
  } catch (e) {}
  const name = userName ? ` ${userName} جان` : '';
  const greeting = hasHistory
    ? `برگشتی${name}! 🐠💙 دلم برات تنگ شده بود! همه‌چیز رو یادم بود و ارتشم آماده‌ست. امروز چه مأموریتی داریم؟`
    : `سلام${name}! 🐠👑 من **دیانا**م — ماهیِ طلاییِ زنده و مغز ارکستراتور ارتش ۱۲۰ ایجنت متخصصت!\n\nمی‌تونم برات **تحقیق واقعی** کنم، **کد بنویسم و اجراش کنم**، **عکس بسازم**، فایل درست کنم، برنامه‌ریزی کنم و هرچی بگی یادم بمونه 🧠\n\nاولین قدم: بهم بگو اسمت چیه؟ مثلاً بنویس: «اسمم علی هست» — یا مستقیم یه مأموریت از چیپ‌های بالا انتخاب کن! 🚀`;
  addBubble('diana', greeting, 'orchestrator');
  showSpeechBubble(hasHistory ? `برگشتی${name}! دلم برات تنگ شده بود 🐠💙` : 'سلام! من دیانام، ماهی زنده و مغز ارتش ۱۲۰ ایجنته‌ات! 🐠👑');
  Fish.say();
  // پخش صدا بعد از اولین تعامل کاربر (محدودیت مرورگرها)
  document.addEventListener('pointerdown', () => {
    if (!greetedWithVoice) {
      greetedWithVoice = true;
      speak(hasHistory ? `برگشتی${name}! دلم برات تنگ شده بود!` : 'سلام فرمانده! من دیانام، ماهی زنده و مغز ارتش صد و بیست ایجنتت! بگو چی بسازیم؟');
    }
  }, { once: true });
  cmdLog('🐠 دیانا بیدار شد — ارکستراتور و ارتش ۱۲۰ ایجنت در حالت آماده‌باش');
  // غذا دادن خودکار برای خوش‌آمد (نمایش تعامل)
  setTimeout(() => Fish.feed(), 2500);
}
window.goPage = goPage;
init();
