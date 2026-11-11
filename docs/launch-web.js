// 🚀 Diana Launch Web — کارخانهٔ راه‌اندازی کسب‌وکار در نسخهٔ وب (GitHub Pages)
// همان موتور پایتون (launch.py) را در مرورگر بازسازی می‌کند تا دیانا روی هاست استاتیک رایگان هم
// ۷ مرحلهٔ راه‌اندازی، حساب‌وکتاب قیف فروش، ۱۲ قاعدهٔ اتوماسیون و بستهٔ کامل فارسی بسازد.
// داده‌های ثابت (مراحل، کتاب راهنما، قواعد اتوماسیون، متخصص‌ها) از static/launch-data.js می‌آید
// که خودکار از launch.py تولید می‌شود؛ پس منطق در دو نسخه یکسان است.
'use strict';

(function () {
  const D = window.DIANA_LAUNCH_DATA || null;
  if (!D) { console.warn('launch-data.js بارگذاری نشد — موتور راه‌اندازی غیرفعال است'); return; }

  const FA = '۰۱۲۳۴۵۶۷۸۹';
  const fa = n => String(n).replace(/\./g, '٫').replace(/[0-9]/g, d => FA[+d]);
  const num = (v, d = 0) => { const x = parseFloat(String(v ?? '').replace(/٫/g, '.').replace(/[۰-۹]/g, c => FA.indexOf(c)).replace(/[^\d.\-]/g, '')); return isNaN(x) ? d : x; };
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const now = () => { const d = new Date(); const p = n => String(n).padStart(2, '0'); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`; };
  const nowFriendly = () => new Date().toLocaleString('fa-IR');

  // حافظه/گاوصندوق نسخهٔ وب در browser-backend.js است؛ از API همان‌ها استفاده می‌کنیم
  const MEM = () => (window.DIANA_MEM || window.MEM || null);
  const persist = () => { if (window.DianaSaveMem) window.DianaSaveMem(); };
  const broadcast = e => { if (window.DianaEmit) window.DianaEmit(e); };
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} },
  };
  const vaultWrite = (name, content) => (window.vaultWrite ? window.vaultWrite(name, content) : name);

  // ---------- نرمال‌سازی ورودی‌ها (هم‌ارز launch.normalize_fields) ----------
  function guessName(idea) {
    const stop = new Set(D.stop);
    const words = String(idea || '').split(/[\s،.؛:!?]+/).map(w => w.replace(/[»«"']/g, ''))
      .filter(w => w.length > 2 && !stop.has(w));
    return words.length ? words.slice(0, 2).join(' ') : 'کسب‌وکار من';
  }
  function domainName(idea) {
    const t = String(idea || '');
    let best = null;
    for (const [key, name] of D.domainNames) {
      const pos = t.indexOf(key);
      if (pos >= 0 && (best === null || pos < best[0])) best = [pos, name];
    }
    if (best) return best[1];
    const g = guessName(idea);
    return g === 'کسب‌وکار من' ? 'کسب‌وکار جدید' : g;
  }
  function normalizeFields(input) {
    const out = { ...D.defaults, ...(input || {}) };
    ['idea', 'business_name', 'target', 'city', 'goal'].forEach(k => { out[k] = String(out[k] || '').trim(); });
    out.ticket = num(out.ticket, 5) || 5;
    out.customers = Math.max(1, Math.round(num(out.customers, 20)));
    out.capacity = Math.max(1, Math.round(num(out.capacity, 30)));
    out.conversion = Math.min(90, Math.max(1, num(out.conversion, 5)));
    out.cac = Math.max(0, num(out.cac, 0.4));
    out.suppliers = String(out.suppliers || '').split(/[،,\n;]+/).map(s => s.trim()).filter(Boolean).slice(0, 12);
    out.need_suppliers = out.need_suppliers !== false;
    if (!out.currency) out.currency = 'تومان';
    if (!out.channel) out.channel = 'اینستاگرام و واتساپ';
    if (!out.business_name) out.business_name = domainName(out.idea);
    if (!out.goal) out.goal = `راه‌اندازی «${out.business_name}» در ${out.city || 'شهر خودم'} و رسیدن به ${fa(out.customers)} قرارداد در ماه`;
    return out;
  }
  function parseLaunchText(text) {
    const raw = String(text || '').trim();
    const f = { ...D.defaults, idea: raw.slice(0, 600) };
    let m = raw.match(/در\s+([آ-یA-Za-z]{3,20})/); if (m) f.city = m[1];
    m = raw.match(/اسم(?:ش|‌ش)?\s*(?:رو|را)?\s*[«"]?([^»"،.\s]{3,25})/); if (m) f.business_name = m[1];
    m = raw.match(/(\d+)\s*(?:تا|الی)\s*(\d+)\s*مشتری/); if (m) f.customers = m[2];
    m = raw.match(/(\d+)\s*مشتری/); if (m) f.customers = m[1];
    m = raw.match(/(\d+(?:[.,]\d+)?)\s*(?:میلیون|هزار)/); if (m) f.ticket = m[1];
    return normalizeFields(f);
  }

  // ---------- حساب‌وکتاب ----------
  function numbers(L) {
    const ticket = num(L.ticket, 5) || 5;
    const customers = Math.max(1, Math.round(num(L.customers, 20)));
    const cap = Math.max(1, Math.round(num(L.capacity, 30)));
    const conv = Math.min(90, Math.max(1, num(L.conversion, 5)));
    const cac = Math.max(0, num(L.cac, 0.4));
    const revenue = ticket * customers;
    const leads = Math.ceil(customers / (conv / 100));
    const meetings = Math.max(1, Math.ceil(leads * 0.15));
    const marketing = cac * customers;
    return { ticket, customers, cap, conv, cac, revenue, leads, meetings, marketing,
             profit: revenue - marketing, capPct: (customers / cap) * 100,
             perDay: Math.ceil(leads / 22), cur: L.currency || 'تومان' };
  }
  const money = (x, cur) => Math.abs(x - Math.round(x)) < 0.05
    ? `${fa(Math.round(x))} میلیون ${cur}` : `${fa(Math.round(x * 100) / 100)} میلیون ${cur}`;
  const capacityNote = n => n.capPct <= 80
    ? `✅ ظرفیت اجرا کافی است: ${fa(n.customers)} سفارش از ${fa(n.cap)} ظرفیت (${fa(Math.round(n.capPct))}٪ اشغال).`
    : n.capPct <= 100
      ? `⚠️ ظرفیت تقریباً پر است (${fa(Math.round(n.capPct))}٪). یک تأمین‌کنندهٔ پشتیبان اضافه کن یا قیمت را بالا ببر.`
      : `🛑 هدف از ظرفیت بیشتر است (${fa(Math.round(n.capPct))}٪). قبل از فروش ظرفیت را با تأمین‌کنندهٔ دوم بالا ببر.`;

  // ---------- کتاب راهنما ----------
  function ctx(L) {
    const n = numbers(L);
    return {
      city: L.city || 'شهر خودت', idea: L.idea || 'این نیاز',
      channel: L.channel || 'اینستاگرام و واتساپ', ticket: money(n.ticket, n.cur),
      sup: (L.suppliers && L.suppliers.length) ? L.suppliers.slice(0, 5).join('، ') : 'تأمین‌کنندهٔ فعلی ثبت نشده',
      leads: fa(n.leads), perday: fa(n.perDay), meetings: fa(n.meetings),
      conv: fa(Math.round(n.conv * 10) / 10), profitpct: fa(Math.round(n.revenue ? n.profit / n.revenue * 100 : 0)),
      name: L.business_name,
    };
  }
  const fmt = (t, c) => String(t).replace(/\{(\w+)\}/g, (_, k) => (k in c ? c[k] : `{${k}}`));
  function stagePlaybook(stageId, L) {
    const tm = D.playbook[stageId] || { tasks: [], kpis: [], risks: [], tools: [] };
    const c = ctx(L);
    const out = {};
    for (const k of Object.keys(tm)) out[k] = tm[k].map(t => fmt(t, c));
    return out;
  }
  function stageMarkdown(stage, L, agent) {
    const n = numbers(L), c = ctx(L);
    const pb = stagePlaybook(stage.id, L);
    const tasks = pb.tasks.map((t, i) => `${fa(i + 1)}. ${t}`).join('\n');
    return `## ${stage.icon} مرحلهٔ ${fa(D.stages.indexOf(stage) + 1)}: ${stage.step}

**🎯 خروجی این مرحله:** ${stage.deliverable}
**❓ چرا مهم است:** ${stage.why}
**👤 متخصص مسئول:** ${agent.emoji} ${agent.fa} (${agent.en}) — ${agent.desc}

### ✅ کارهای این مرحله (به ترتیب اجرا)
${tasks}

### 📊 معیار موفقیت (KPI)
${pb.kpis.map(k => '- ' + k).join('\n')}

### ⚠️ ریسک‌های این مرحله و پادزهر
${pb.risks.map(r => '- ' + r).join('\n')}

### 🧰 ابزار پیشنهادی
${pb.tools.map(t => '- ' + t).join('\n')}

### 💰 عدد‌های همین مرحله
- درآمد ماهانه هدف: **${money(n.revenue, n.cur)}** | سرنخ لازم: **${fa(n.leads)}** در ماه (روزی **${fa(n.perDay)}**)
- ظرفیت: ${capacityNote(n)}
`;
  }


  // ---------- اسناد آمادهٔ استفاده: پیش‌نویس قرارداد و قالب RFQ ----------
  function contractMarkdown(L) {
    const n = numbers(L), cur = n.cur;
    const d = new Date(); const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    return `# 📜 پیش‌نویس قرارداد ارائهٔ خدمات — «${L.business_name}»

> ⚠️ این یک قالب تجاری برای شروع مذاکره است، نه مشاورهٔ حقوقی. قبل از امضای قرارداد بزرگ، یک مشاور حقوقی آن را ببیند.

**تاریخ:** ${today} | **شمارهٔ قرارداد:** [شماره]

## ۱. طرفین
- **ارائه‌دهنده:** «${L.business_name}» به نمایندگی [نام و سمت]، نشانی [نشانی]، تلفن [تلفن].
- **کارفرما:** [نام شرکت/شخص] به نمایندگی [نام و سمت]، نشانی [نشانی].

## ۲. موضوع و دامنهٔ کار
[شرح دقیق خدمت — همان چیزی که در پیشنهاد تأیید شد].
**خارج از دامنه:** [موارد خارج از تعهد] — هر مورد اضافه فقط با «برگهٔ تغییر دامنه» (بند ۹).

## ۳. زمان‌بندی
- شروع کار: [تاریخ] (مشروط به دریافت پیش‌پرداخت)
- تحویل مرحله‌ای: مرحلهٔ ۱ [تاریخ] | مرحلهٔ ۲ [تاریخ] | تحویل نهایی [تاریخ]

## ۴. مبلغ و شرایط پرداخت
- **مبلغ کل:** ${money(n.ticket, cur)}
- **پیش‌پرداخت ۵۰٪ هم‌زمان با امضا:** ${money(n.ticket * 0.5, cur)}
- **مانده ۵۰٪ پس از تحویل و تأیید نهایی:** ${money(n.ticket * 0.5, cur)}
- پرداخت به حساب [شماره حساب/شبا] به نام [نام صاحب حساب].

## ۵. کیفیت و پذیرش
- استاندارد: [مشخصات قابل سنجش]. مهلت اعلام ایراد: ۵ روز کاری. حداکثر ۲ دور اصلاح رایگان.

## ۶. جریمهٔ تأخیر (دو طرفه)
- تأخیر ارائه‌دهنده: ۰٫۵٪ مبلغ به‌ازای هر روز (حداکثر ۱۰٪). تأخیر پرداخت: ۰٫۵٪ روزانه.

## ۷. مالکیت نتیجه
- پس از تسویهٔ کامل، مالکیت خروجی به کارفرما منتقل می‌شود. حق نمایش نمونه‌کار محفوظ است.

## ۸. محرمانگی
اطلاعات تجاری و داده‌های کارفرما محرمانه است و فقط برای اجرای این قرارداد استفاده می‌شود.

## ۹. تغییر دامنه (Change Order)
هر تغییر باید کتبی باشد و اثر آن بر قیمت و زمان روشن شود. کار اضافه بدون تأیید کتبی تعهدی ایجاد نمی‌کند.

## ۱۰. فسخ
هر طرف با ۱۵ روز اطلاع کتبی؛ کار انجام‌شده تسویه می‌شود.

## ۱۱. حل اختلاف
مذاکرهٔ مستقیم (۱۴ روز) → میانجیگری [مرجع] → مرجع قانونی صالح [شهر].

## ۱۲. فورس ماژور
رویدادهای خارج از کنترل، تعهدات را تا رفع رویداد معلق می‌کند.

## ۱۳. اعلامیه‌ها
[ایمیل ارائه‌دهنده] / [ایمیل کارفرما]

## ۱۴. کل توافق
این قرارداد همراه پیوست پیشنهاد قیمت، کل توافق طرفین است.

## ۱۵. امضا
| ارائه‌دهنده | کارفرما |
|---|---|
| نام / سمت / تاریخ / امضا | نام / سمت / تاریخ / امضا |
`;
  }

  function rfqMarkdown(L) {
    const n = numbers(L), cur = n.cur;
    const sup = (L.suppliers && L.suppliers.length) ? L.suppliers.slice(0, 5).join('، ') : '—';
    return `# 📨 درخواست قیمت (RFQ) — ${L.business_name}

**به:** [نام تأمین‌کننده] | **از:** ${L.business_name} | **تاریخ:** ${now().slice(0, 10)}
**مهلت پاسخ:** ۴۸ ساعت | **تأمین‌کنندگان فعلی:** ${sup}

برای پروژه‌ای در حوزهٔ «${L.idea || 'خدمات ما'}» در ${L.city || 'شهر ما'} لطفاً قیمت و شرایط زیر را اعلام کنید:

| # | شرح | مقدار | مشخصات | مهلت تحویل |
|---|---|---|---|---|
| ۱ | [قلم اول] | [مقدار] | [استاندارد] | [تاریخ] |
| ۲ | [قلم دوم] | [مقدار] | [استاندارد] | [تاریخ] |

**شرایط درخواستی:** قیمت واحد و کل به ${cur}، حداقل سفارش، زمان تأمین تا ${L.city || '[محل]'}،
شرایط پرداخت (ترجیح: ۳۰٪ پیش‌پرداخت)، استاندارد کیفیت، جریمهٔ تأخیر.

**معیار انتخاب:** ۴۰٪ تحویل به‌موقع، ۳۰٪ کیفیت، ۲۰٪ قیمت، ۱۰٪ انعطاف — ارزان‌ترین اولویت اول نیست.

با سپاس — [نام]، ${L.business_name}
`;
  }

  // ---------- برنامهٔ مادر ----------
  function planMarkdown(L) {
    const n = numbers(L), cur = n.cur;
    const rows = D.stages.map((s, i) => `| ${fa(i + 1)} | ${s.icon} ${s.step} | ${s.deliverable} |`).join('\n');
    return `# 🚀 برنامهٔ راه‌اندازی «${L.business_name}»

**🎯 هدف فرمانده:** ${L.goal}
**💡 ایده:** ${L.idea || '—'}
**📍 بازار:** ${L.city || 'شهر خودم'} | **کانال اصلی:** ${L.channel}
**📅 تاریخ تدوین:** ${now()} | **تدوین:** دیانا 🐠 (دپارتمان راه‌اندازی)

## 💰 حساب‌وکتاب اولیه (میلیون ${cur})
| شاخص | مقدار |
|---|---|
| میانگین مبلغ هر قرارداد | **${money(n.ticket, cur)}** |
| هدف قرارداد در ماه | **${fa(n.customers)} قرارداد** |
| درآمد ماهانه هدف | **${money(n.revenue, cur)}** |
| نرخ تبدیل سرنخ → قرارداد | **${fa(Math.round(n.conv * 10) / 10)}٪** |
| سرنخ لازم در ماه | **${fa(n.leads)} سرنخ** (روزی ~${fa(n.perDay)}) |
| جلسهٔ لازم در ماه | **${fa(n.meetings)} جلسه** |
| بودجهٔ بازاریابی ماهانه | **${money(n.marketing, cur)}** |
| سود بعد از هزینهٔ جذب | **${money(n.profit, cur)}** |

**🧯 بررسی ظرفیت:** ${capacityNote(n)}

## 🗺️ نقشهٔ ۷ مرحله
| # | مرحله | خروجی نهایی |
|---|---|---|
${rows}

## 🏭 تأمین‌کنندگان فعلی
${(L.suppliers && L.suppliers.length) ? L.suppliers.join('، ') : 'هنوز ثبت نشده — مرحلهٔ ۳ آن را می‌سازد'}

## ⏱️ تقویم ۹۰ روزه
- **هفتهٔ ۱:** اعتبارسنجی بازار + پیشنهاد و قیمت (۲۰ پیام آزمون تقاضا)
- **هفتهٔ ۲:** توافق با ۲ تأمین‌کننده + آماده‌سازی اسکریپت‌ها و قالب قرارداد
- **هفتهٔ ۳–۴:** کمپین اول (۱۰۰ سرنخ) + بستن ۳ قرارداد اول با ۵۰٪ پیش‌پرداخت
- **ماه ۲:** تثبیت اتوماسیون و رسیدن به ۵۰٪ هدف درآمد
- **ماه ۳:** کانال دوم، ۵ نظر مشتری، رسیدن به ۱۰۰٪ هدف

## 📊 داشبورد هفتگی
۱. سرنخ جدید  ۲. گفتگوی واقعی  ۳. پیشنهاد ارسال‌شده  ۴. قرارداد امضاشده + مبلغ
۵. درصد تحویل به‌موقع  ۶. درآمد وصول‌شده

## ⚠️ سه ریسکی که همه را می‌بلعد
۱. **فروش قبل از تأمین** ۲. **قیمت‌گذاری از ترس** (حاشیهٔ زیر ۳۰٪) ۳. **تک‌کانالی بودن جذب مشتری**

> 🐠 این سند مادر است؛ ۷ سند اجرایی مرحله‌به‌مرحله و نقشهٔ اتوماسیون هم ساخته می‌شوند.
`;
  }

  // ---------- اتوماسیون ----------
  function automationSpecs(L) {
    const n = numbers(L), cur = n.cur, cn = L.channel || 'اینستاگرام و واتساپ';
    const ideas = (L.idea || L.business_name || '').slice(0, 70);
    const map = {
      a01: `جستجوی وب/ویکی‌پدیا برای «${ideas}» + ثبت تغییرات قیمت رقبا در گاوصندوق`,
      a02: 'ثبت نام/منبع/نیاز + امتیاز ۰-۱۰۰ بر اساس بودجه، فوریت، تناسب + تعیین پیگیری بعدی',
      a03: 'ارسال پیام خوش‌آمد + یک نمونه‌کار مناسب + یک سؤال کشف نیاز',
      a04: 'پیگیری ۱ با نمونه‌کار → پیگیری ۲ با سؤال کوتاه → بایگانی و یادآوری ماه بعد',
      a05: `ساخت پیشنهاد از قالب (سه بسته، مبلغ پایه ${money(n.ticket, cur)}) + ارسال PDF و ثبت در جدول`,
      a06: 'ارسال RFQ به ۳ تأمین‌کننده فعال + مقایسهٔ پاسخ‌ها در ۲۴ ساعت + پیشنهاد بهترین گزینه',
      a07: 'پر کردن قالب قرارداد با متغیرهای مشتری + ارسال برای امضای الکترونیک + آرشیو PDF',
      a08: 'صدور فاکتور ۵۰٪ پیش‌پرداخت + یادآوری سررسید + پیام تشکر و شروع کار',
      a09: 'ساخت پروژهٔ ۵ مرحله‌ای در Linear + درخواست تأمین + پیام «سفارش ثبت شد» با زمان تحویل',
      a10: 'پیام وضعیت به مشتری + اجرای چک‌لیست ۵ موردی کیفیت + ثبت مدرک تحویل',
      a11: 'پیام رضایت + درخواست معرفی دو نفر + ثبت نظر در پوشهٔ اثبات اجتماعی',
      a12: 'سرنخ، نرخ تبدیل، قرارداد، درآمد وصول‌شده، گلوگاه هفته + سه اقدام هفتهٔ بعد',
    };
    return D.automation.map(a => ({ ...a, trigger: a.id === 'a02' ? `📥 پیام/فرم جدید در ${cn}` : a.trigger, action: map[a.id] || a.action }));
  }
  function automationMarkdown(L) {
    const rows = automationSpecs(L).map(s => `| ${s.id} | ${s.trigger} | **${s.title}** | ${s.action} | ${s.systems.join('، ')} |`).join('\n');
    return `# ⚙️ شبکهٔ اتوماسیون پشت صحنه — «${L.business_name}»

| # | رویداد | قاعده | اقدام خودکار | سیستم‌ها |
|---|---|---|---|---|
${rows}

## 🔌 نقش سیستم‌ها
- **Supabase** — پایگاه دادهٔ سرنخ، قرارداد، سفارش و درآمد.
- **Gmail** — پیام اول، پیگیری، RFQ، فاکتور و اعلان‌ها.
- **Google Calendar** — جلسه‌ها، ددلاین تحویل و یادآوری سررسید.
- **Google Docs / Drive** — پیشنهاد، قرارداد، نمونه‌کار و آرشیو.
- **Dropbox / Dropbox Sign** — امضای الکترونیک و نسخهٔ امن قرارداد.
- **Linear** — پروژهٔ اجرای هر سفارش.
- **دیانا 🐠** — مغز ارکسترATOR: تشخیص مرحله، تولید متن و اجرای ابزارها.

> 🔐 هیچ سفارشی بدون پیش‌پرداخت وارد مرحلهٔ اجرا نمی‌شود.
`;
  }

  function runbookMarkdown(L, results) {
    const n = numbers(L), cur = n.cur;
    const body = results.map(r => `### ${r.stage.icon} ${r.stage.step} — امتیاز ارزیاب: ${fa(r.score)}/۱۰۰\n${String(r.output || '').slice(0, 2600)}`).join('\n\n---\n\n');
    const avg = Math.round(results.reduce((s, r) => s + r.score, 0) / Math.max(1, results.length));
    return `# 🎁 بستهٔ کامل راه‌اندازی «${L.business_name}»

**🎯 هدف:** ${L.goal}
**📊 امتیاز کیفی کل:** ${fa(avg)}/۱۰۰
**📅 ${now()}** | تهیه‌شده توسط دیانا و ${fa(results.length)} متخصص راه‌اندازی

## ⚡ خلاصهٔ یک‌نگاهی
- **پول:** هر قرارداد ${money(n.ticket, cur)} × ${fa(n.customers)} قرارداد = **${money(n.revenue, cur)} در ماه**
- **قیف:** ${fa(n.leads)} سرنخ → ${fa(n.meetings)} جلسه → ${fa(n.customers)} قرارداد (${fa(Math.round(n.conv * 10) / 10)}٪ تبدیل)
- **ظرفیت:** ${capacityNote(n)}
- **اتوماسیون:** ${fa(automationSpecs(L).length)} قاعدهٔ خودکار از سرنخ تا رضایت‌سنجی

## 🚦 پنج قدم بعدی (همین امروز)
۱. **۲ ساعت:** ۲۰ پیام آزمون تقاضا با اسکریپت مرحلهٔ ۴ بفرست.
۲. **۴ ساعت:** سه بستهٔ قیمتی را نهایی کن و سقف تخفیف را بنویس.
۳. **فردا:** با ۳ تأمین‌کننده تماس بگیر و RFQ بفرست.
۴. **این هفته:** قالب قرارداد را با یک مشتری واقعی پر کن و پیش‌پرداخت بگیر.
۵. **جمعه:** شش عدد داشبورد را ثبت کن.

---

${body}

---

## ⚙️ شبکهٔ اتوماسیون پشت صحنه
${automationMarkdown(L)}
`;
  }

  // ---------- اجرای ۷ مرحله ----------
  const pubAgent = a => ({ id: a.id, fa: a.fa, en: a.en, emoji: a.emoji, dept: a.dept, dept_fa: a.dept_fa, color: a.color, executor: a.executor, desc: a.desc });
  function evaluate(output, source) {
    let score = 55; const notes = ['کتاب راهنمای اجرایی'];
    if (output.length > 900) score += 12;
    if (output.length > 2000) score += 8;
    if (output.includes('KPI') && output.includes('ریسک')) { score += 10; notes.push('دارای اقدام/KPI/ریسک'); }
    if (output.includes('«')) { score += 5; notes.push('متن آمادهٔ استفاده'); }
    if (source !== 'playbook') { score += 8; notes.push('تحلیل زندهٔ مغز ابری'); }
    score = Math.max(0, Math.min(100, score));
    return [score, `${score >= 88 ? 'عالی 🌟' : score >= 75 ? 'خوب ✅' : 'قابل قبول 👍'} — ${notes.join('، ')}`];
  }

  function newRec(L, id) {
    return {
      id: id || ('W' + String(Date.now()).slice(-9)), fields: L, status: 'planning', score: null,
      ts: now(), stages: D.stages.map(s => ({ id: s.id, step: s.step, icon: s.icon, owner: s.owner,
        deliverable: s.deliverable, status: 'pending' })),
      results: [], plan: planMarkdown(L), automation: automationSpecs(L),
    };
  }

  /** یک کسب‌وکار را ثبت می‌کند و پیش از اجرای پس‌زمینه برمی‌گرداند (برای پاسخ سریع چت/API) */
  function prepare(fields) {
    const mem = MEM(); if (!mem) return null;
    const L = normalizeFields(fields);
    const rec = newRec(L);
    rec.plan_file = vaultWrite(`launch-${rec.id}-00-plan.md`, rec.plan);
    rec.contract_file = vaultWrite(`launch-${rec.id}-contract-draft.md`, contractMarkdown(L));
    rec.rfq_file = vaultWrite(`launch-${rec.id}-rfq-template.md`, rfqMarkdown(L));
    mem.launches = mem.launches || [];
    mem.launches.push(rec);
    mem.launches = mem.launches.slice(-20);
    persist();
    broadcast({ type: 'launch_created', launch: publicRec(rec) });
    return rec;
  }

  async function runLaunch(L, mode, forcedId) {
    const mem = MEM(); if (!mem) return null;
    L = normalizeFields(L);
    mem.launches = mem.launches || [];
    let rec = forcedId ? mem.launches.find(r => r.id === forcedId) : null;
    if (!rec) {
      rec = newRec(L);
      mem.launches.push(rec);
      mem.launches = mem.launches.slice(-20);
      broadcast({ type: 'launch_created', launch: publicRec(rec) });
    }
    const lid = rec.id;
    rec.fields = L; rec.status = 'running'; rec.mode = mode || 'auto'; rec.score = null;
    rec.results = []; rec.plan = planMarkdown(L); rec.automation = automationSpecs(L);
    rec.stages = D.stages.map(s => ({ id: s.id, step: s.step, icon: s.icon, owner: s.owner, deliverable: s.deliverable, status: 'pending' }));
    // اسناد آمادهٔ استفاده (هم‌ارز launch.py)
    rec.plan_file = vaultWrite(`launch-${lid}-00-plan.md`, rec.plan);
    rec.contract_file = vaultWrite(`launch-${lid}-contract-draft.md`, contractMarkdown(L));
    rec.rfq_file = vaultWrite(`launch-${lid}-rfq-template.md`, rfqMarkdown(L));
    persist();
    broadcast({ type: 'launch_created', launch: { ...rec, results: [] } });

    // تحلیل زنده با مغز ابری (اگر در دسترس بود) — همان رفتار نسخهٔ پایتون
    const live = (mode !== 'offline') && typeof window.llmGenerate === 'function';

    for (let i = 0; i < D.stages.length; i++) {
      const stage = D.stages[i];
      const agent = (D.agents.find(a => a.id === stage.owner) || D.agents[0]);
      rec.stages[i].status = 'running';
      persist();
      broadcast({ type: 'launch_stage_started', launch_id: lid, index: i, total: D.stages.length,
        stage: { id: stage.id, step: stage.step, icon: stage.icon, deliverable: stage.deliverable }, agent: pubAgent(agent) });
      let output = stageMarkdown(stage, L, agent);
      let source = 'playbook';
      if (live) {
        try {
          const pb = stagePlaybook(stage.id, L);
          const r = await window.llmGenerate(
            `کسب‌وکار: «${L.business_name}» — ${L.idea}\nبازار: ${L.city || 'شهر مشتری'} | کانال: ${L.channel}\nمرحله: ${stage.step} | خروجی: ${stage.deliverable}\nچارچوب داخلی: ${pb.tasks.slice(0, 3).join('; ')}\n` +
            'یک سند اجرایی فارسی Markdown حداکثر ۶۰۰ کلمه بنویس: اقدام‌های مشخص با عدد و مهلت، اسکریپت آماده، KPI و دو ریسک با پادزهر.',
            `تو ${agent.fa} (${agent.en}) هستی؛ تخصصت: ${agent.desc}. فقط خروجی کاربردی بده.`);
          if (r && r.text && r.text.length > 120) {
            output += '\n\n### 🧠 تحلیل زندهٔ متخصص\n\n' + r.text;
            source = 'cloud';
          }
        } catch (e) {}
      }
      const [score, verdict] = evaluate(output, source);
      const fname = vaultWrite(`launch-${lid}-${String(i + 1).padStart(2, '0')}-${stage.id}.md`,
        `# ${stage.icon} ${stage.step} — ${L.business_name}\n\n*مرحلهٔ ${fa(i + 1)} از ${fa(D.stages.length)} | متخصص: ${agent.emoji} ${agent.fa} | امتیاز: ${fa(score)}/۱۰۰ (${verdict})*\n\n${output}\n`);
      rec.stages[i] = { ...rec.stages[i], status: 'done', score, verdict, source, preview: output.slice(0, 4000), artifact: fname };
      rec.results.push({ index: i, stage: { id: stage.id, step: stage.step, icon: stage.icon, deliverable: stage.deliverable },
        agent: pubAgent(agent), output, score, verdict, source, artifact: { name: fname, type: 'file' } });
      persist();
      broadcast({ type: 'launch_stage_done', launch_id: lid, index: i, total: D.stages.length,
        stage: rec.stages[i], agent: pubAgent(agent), score, verdict, source, artifact: { name: fname }, preview: output.slice(0, 1400) });
      await new Promise(r => setTimeout(r, 300));
    }

    const runbook = runbookMarkdown(L, rec.results);
    const reportFile = vaultWrite(`launch-${lid}-runbook.md`, runbook);
    const autoFile = vaultWrite(`launch-${lid}-automation.md`, automationMarkdown(L));
    rec.status = 'done';
    rec.score = Math.round(rec.results.reduce((s, r) => s + r.score, 0) / rec.results.length);
    rec.report = runbook; rec.report_file = reportFile; rec.automation_file = autoFile;
    persist();
    broadcast({ type: 'launch_ready', launch_id: lid, score: rec.score, report_file: reportFile,
      automation_file: autoFile, automation: rec.automation, stages: D.stages.length, report: runbook.slice(0, 5000) });
    return rec;
  }

  function publicRec(rec) {
    if (!rec) return null;
    const { results, ...rest } = rec;
    return { ...rest, results: (results || []).map(r => ({ ...r, output: String(r.output || '').slice(0, 1600) })) };
  }

  // ---------- ثبت در روتر fetch (هم‌ارز API پایتون) ----------
  function install() {
    if (window.__dianaLaunchInstalled) return;
    window.__dianaLaunchInstalled = true;
    window.DianaLaunch = {
      stages: D.stages, normalizeFields, parseLaunchText, numbers, money, planMarkdown,
      stageMarkdown, stagePlaybook, automationSpecs, automationMarkdown, runbookMarkdown,
      runLaunch, publicRec, fa, prepare, newRec, contractMarkdown, rfqMarkdown,
    };
    const origFetch = window.fetch.bind(window);
    window.fetch = async (input, init = {}) => {
      const url = typeof input === 'string' ? input : (input?.url || '');
      const isLocal = url.includes('/api/launch') || url.includes('/api/ping') || url.includes('/api/events/poll');
      if (!isLocal) return origFetch(input, init);
      const path = url.replace(/^https?:\/\/[^/]+/, '').split('?')[0];
      const method = (init.method || 'GET').toUpperCase();
      let body = {};
      try { if (init.body) body = JSON.parse(init.body); } catch (e) {}
      const json = (o, s = 200) => (typeof Response !== 'undefined')
        ? new Response(JSON.stringify(o), { status: s, headers: { 'Content-Type': 'application/json; charset=utf-8' } })
        : { ok: s < 300, status: s, json: async () => o };  // محیط‌های بدون fetch بومی
      const mem = MEM() || {};
      try {
        // 🔗 سلامت اتصال در نسخهٔ وب (هم‌ارز /api/ping سرور پایتون)
        if (path === '/api/ping' && method === 'GET') {
          return json({ ok: true, diana: true, version: 'web-2.1-launch', mode: 'browser', stream: 'local' });
        }
        if (path === '/api/events/poll' && method === 'GET') {
          return json({ events: [], last: 0, stream: 'local' });
        }
        if (path === '/api/launch' && method === 'GET') {
          const list = [...(mem.launches || [])].reverse().map(r => {
            const { results, plan, report, ...rest } = r;
            return rest;
          });
          return json({ launches: list, stages: D.stages, defaults: D.defaults });
        }
        if (path === '/api/launch/quote' && method === 'POST') {
          const f = normalizeFields(body);
          return json({ fields: f, numbers: numbers(f), plan: planMarkdown(f) });
        }
        if (path === '/api/launch/parse' && method === 'POST') {
          return json({ fields: parseLaunchText(body.text || '') });
        }
        if (path === '/api/launch' && method === 'POST') {
          const f = normalizeFields(body);
          const rec = prepare(f);
          // اجرا در پس‌زمینه؛ پاسخ فوری مثل نسخهٔ پایتون
          runLaunch(f, body.mode || 'auto', rec.id).catch(e => console.warn('launch failed', e));
          return json({ ok: true, launch: publicRec(rec) });
        }
        const m = path.match(/^\/api\/launch\/([^/]+)(?:\/(full))?$/);
        if (m && method === 'GET') {
          const rec = (mem.launches || []).find(r => r.id === m[1]);
          if (!rec) return json({ error: 'not found' }, 404);
          if (m[2] === 'full') return json(rec);
          return json(publicRec(rec));
        }
      } catch (e) { return json({ error: String(e.message || e) }, 500); }
      return json({ error: 'not found' }, 404);
    };
    console.log('🚀 Diana Launch Web آماده است — ۷ مرحله، ' + D.automation.length + ' قاعدهٔ اتوماسیون، ' + D.agents.length + ' متخصص');
  }

  install();
})();
