# 🔐 VPN رایگان از صفر — آدرس ثابت، بدون کارت بانکی، روی اندروید

> **چی ساختم:** یه سرور/رله VPN کامل (پروتکل VLESS روی WebSocket) که **از صفر و فقط با
> کتابخانه استاندارد پایتون** نوشته شده — نه کپی یه پنل آماده، نه نیاز به pip، نه VPS پولی.
> روی یه هاست رایگان (Render) دیپلو میشه و یه **آدرس ثابت** مثل
> `https://free-vpn-relay-xxxx.onrender.com` میگیره که همیشه همان میماند.
> سمت گوشی هم یا با یه اپ اپنسورس رایگان (Hiddify / v2rayNG) وصل میشی، یا کاملاً از صفر
> با `client.py` داخل ترموکس + یه اپ VpnService مثل SocksDroid.

---

## ۰. اول یه حقیقت صادقانه (مهمتر از کده)

| پرسش | جواب |
|---|---|
| IP ثابت عمومی رایگان و بدون کارت هست؟ | **نه.** اون فقط تو پلن رایگان Oracle Cloud / Google Cloud هست که ثبتنامشان کارت بانکی بینالمللی میخواهد [1](https://www.xda-developers.com/bypassed-cgnat-oracle-free-cloud-tier/) [4](https://findstack.com/resources/free-vps-no-credit-card). |
| پس «آدرس ثابت» یعنی چی؟ | یه **hostname ثابت** (`*.onrender.com`) که عوض نمی‌شود، هرچند IP پشتش عوض شود. برای کانفیگ VPN دقیقاً همین لازم است. |
| همیشه وصل میماند؟ | سرور رایگان Render بعد از ۱۵ دقیقه بیکاری میخوابد و حدود ۱ دقیقه طول می‌کشد بیدار شود؛ ۷۵۰ ساعت و حدود ۵ گیگابایت ترافیک در ماه دارد [10](https://render.com/docs/free). من توی سرور پینگ نگهدارنده گذاشتم تا وقتی وصلی نخوابد. |
| تو ایران حتماً کار می‌کند؟ | **تضمین نمیکنم.** فیلترینگ ۲۰۲۶ پروتکلهای VLESS/WS و WireGuard را با DPI میگیرد و گاهی IPهای ابری را مسدود می‌کند [9](https://lowendtalk.com/discussion/206643/iran-internet-update-for-hosting-providers-and-users-june-2025) [5](https://github.com/net4people/bbs/issues/628). واسه همین «مسیر الف» (اپهای رایگان) را هم پایین گذاشتم — آن را به عنوان پشتیبان همیشه داشته باش. |
| چرا Cloudflare Workers نساختی؟ | چون ToS Cloudflare از دسامبر ۲۰۲۴ صراحتاً پروکسی/VPN روی شبکهاش را ممنوع کرده و اکانتهای VLESS-Worker بن میشوند [8](https://community.cloudflare.com/t/blocking-xray-and-v2ray-traffic/748125) [1](https://laither.com/posts/2026/05/cf-workers-%E9%83%A8%E7%BD%B2%E4%BB%A3%E7%90%86%E8%A2%AB%E5%B0%81%E5%8F%B7%E4%B8%80%E4%B8%AA%E8%B4%A6%E5%8F%B7%E7%9A%84%E6%95%99%E8%AE%AD/)؛ تازه `workers.dev` هم در ایران فیلتر است [2](https://community.cloudflare.com/t/worker-dev-filtered-in-iran/474197). |
| اپ اندرویدی رو هم از صفر مینویسی؟ | یه اپ VPN سیستمعامل نیاز به Android SDK + موتور بومی tun2socks دارد. من بکاند و یه کلاینت کامل پایتونی (`client.py`) را از صفر نوشتم؛ سمت گوشی از اپ اپنسورس رایگان استفاده میکنیم. اگه خواستی بعداً یه workflow بسازم که APK اختصاصیتو بسازه. |

---

## ۱. سه تا راه — کدوم رو انتخاب کنی؟

| | مسیر الف: اپ رایگان | **مسیر ب: این مخزن (از صفر)** | مسیر ج: IP ثابت واقعی |
|---|---|---|---|
| چی میگیری | یه VPN آماده | یه سرور شخصی + آدرس ثابت | یه IPv4 عمومی ثابت |
| کارت بانکی | ❌ نمیخواد | ❌ نمیخواد | ✅ حتماً میخواد |
| IP/آدرس ثابت | ❌ (سرورها عوض میشوند) | ✅ `*.onrender.com` | ✅ واقعاً IP ثابت |
| نصب | ۲ دقیقه | ۱۰ دقیقه | ۳۰ دقیقه |
| پایداری تو ایران | معمولاً بهتر (پروتکل Stealth) | بستگی به ISP داره | بهتر، ولی باز DPI هست |
| هزینه | ۰ | ۰ | ۰ (پلن Always Free) |

**مسیر الف — اگه فقط میخوای «همیشه وصل باشی»، همین رو نصب کن:**

- **Proton VPN Free** — ترافیک نامحدود، ۱ دستگاه، پروتکل Stealth، نیازی به کارت ندارد [1](https://www.tomsguide.com/best-picks/best-free-vpn).
- **hide.me Free** — ترافیک نامحدود، ۱ دستگاه، ۸ موقعیت، WireGuard/OpenVPN/IKEv2 [3](https://whatismylocation.org/blog/best-free-vpn-2026).
- **Windscribe Free** — ۱۰ گیگابایت در ماه با تأیید ایمیل، دستگاه نامحدود [6](https://toolradar.com/blog/best-free-vpns).
- **Cloudflare WARP (اپ 1.1.1.1)** — رایگان و نامحدود؛ گاهی تنها چیزیه که تو ایران وصل میشه.
- **Psiphon / Lantern** — مخصوص کشورهای فیلترشده ساخته شدن.

> نکته: **هیچ سرویس رایگانی IP اختصاصی ثابت نمیدهد**؛ IP ثابت/اختصاصی آپشن پولی
> Proton/Nord/Surfshark و شرکته [14](https://www.top10vpn.com/guides/dedicated-ip-vpn/).
> (سرورهای رایگان ProtonIP ثابت دارند ولی بین همه کاربران مشترکند [19](https://www.reddit.com/r/ProtonVPN/wiki/faq/).)

**مسیر ج — اگه یه روز کارت گرفتی:** Oracle Cloud Always Free بهت یه VM دائمی و
**IP عمومی قابل رزرو (Reserved Public IP)** میدهد [13](https://www.rackupit.com/blog/assign-reserved-static-ip-oracle-cloud-vps)،
با ۱۰ ترابایت ترافیک در ماه [4](https://findstack.com/resources/free-vps-no-credit-card).
Google Cloud هم یه `e2-micro` دائمی میدهد ولی فقط ۱ گیگابایت خروجی در ماه دارد
(برای VPN تقریباً هیچی) [8](https://devshot.co/blog/cloud-free-tiers-compared).

---

## ۲. مسیر ب — راهاندازی (۱۰ دقیقه)

### قدم ۱ — ساخت رمزها

روی کامپیوتر یا ترموکس:

```bash
cd ~/Najibrahimi/vpn
python3 gen_config.py --write-env
```

خروجی شبیه این است — **همینجا کپی کن یه جای امن** (فایل `vpn/.env` ساخته شد و تو گیت نمیرود):

```
VPN_UUID=3f2b...-....-....
VPN_TOKEN=xY7_abcdef...
```

### قدم ۲ — دیپلوی رایگان (بدون کارت)

1. تغییرات رو پوش کن به گیت‌هاب (همین مخزن).
2. برو <https://render.com> و با اکانت گیت‌هابت وارد شو — **کارت بانکی نمیخواهد** [2](https://render.com/articles/platforms-with-a-real-free-tier-for-developers-in-2026).
3. **New → Blueprint** ← مخزن `Najibrahimi` را انتخاب کن، مسیر Blueprint را بگذار `vpn/render.yaml`.
4. پلن **Free** را انتخاب کن. وقتی متغیرها را پرسید:
   - `VPN_UUID` = همان UUID قدم ۱
   - `VPN_TOKEN` = همان TOKEN قدم ۱
5. دیپلو تمام شد → آدرسی مثل `https://free-vpn-relay.onrender.com` میگیری.
   **این همان «IP ثابت» توست** — تا وقتی سرویس پاک نشود عوض نمی‌شود.
6. تست: `https://free-vpn-relay.onrender.com/health` باید `{"ok":true}` بدهد.

> اگه خواستی دستی بسازی: New → Web Service، `Root Directory = vpn`، `Runtime = Python 3`،
> `Build Command = echo ok`، `Start Command = python3 server.py`، پلن Free،
> و همان دو متغیر محیطی. `Health Check Path = /health`.

### قدم ۳ — گرفتن لینک کانفیگ

```bash
python3 gen_config.py --host free-vpn-relay.onrender.com \
  --uuid 3f2b... --token xY7_abcdef...
```

خروجی یه لینک `vless://...` میدهد. یا سادهتر، تو مرورگر برو:

```
https://free-vpn-relay.onrender.com/<TOKEN>/
```

صفحهای فارسی میبینی که لینک کانفیگ، لینک سابسکریپشن و آموزش گوشی را نشان میدهد.
⚠️ این آدرس رمز توست؛ برای کسی نفرست.

### قدم ۴ — وصل شدن با اندروید (سادهترین)

1. اپ **Hiddify Next** یا **v2rayNG** را نصب کن (از GitHub Releases یا F-Droid؛ نیازی به Play Store نیست).
2. لینک `vless://...` را کپی کن.
3. توی اپ: **+ → Import from clipboard / وارد کردن از کلیپبورد**.
4. وصل شو. اگه بار اول جواب نداد، ۶۰ ثانیه صبر کن (بیدار شدن سرور رایگان).
5. توی تنظیمات اپ، DNS را روی **DoH** بگذار (مثلاً `https://1.1.1.1/dns-query`) چون
   سرور ما فعلاً فقط TCP را پشتیبانی می‌کند، نه UDP/DNS روی پورت ۵۳.

### قدم ۵ (اختیاری) — کلاینت «کاملاً از صفر» روی خود گوشی

اگه دوست داری سمت گوشی هم کد خودمون باشه (به‌جای v2rayNG)، تو ترموکس:

```bash
pkg install python -y
cd ~/Najibrahimi/vpn
python3 client.py --host free-vpn-relay.onrender.com \
  --token xY7_abcdef... --uuid 3f2b...
```

این اسکریپت یه پروکسی SOCKS5 روی `127.0.0.1:1080` باز می‌کند و ترافیک را داخل
WebSocket TLS میفرستد سرور. بعد اپ **SocksDroid** (یا هر اپ VpnService مشابه) را نصب کن،
آدرس سرورش را بگذار `127.0.0.1` و پورت `1080` (بدون نام کاربری/رمز) و وصل شو —
حالا کل ترافیک گوشی از تونل تو میرود. ترموکس را باز نگه دار (میتوانی با `tmux` یا
Termux:Boot دائمیش کنی).

---

## ۳. تست محلی قبل از دیپلو

همهچیز را روی کامپیوترت بدون اینترنت و بدون هاست می‌شود تست کرد:

```bash
cd vpn
python3 tests/test_relay.py
```

این تست سرور را بالا میآورد، یه سرور اکو میسازد، با یه کلاینت WebSocket خام
هدر VLESS میفرستد، UUID غلط را رد می‌کند، و در نهایت از مسیر کامل
**SOCKS5 → client.py → WebSocket → server.py → مقصد** رد می‌کند و اکو را چک مینماید.

دستوری هم اگر خواستی سرور را تنهایی ببینی:

```bash
VPN_UUID=$(python3 -c 'import uuid;print(uuid.uuid4())') \
VPN_TOKEN=testtoken VPN_ALLOW_PRIVATE=1 VPN_PUBLIC_SCHEME=http \
PORT=8000 python3 server.py
# ترمینال دیگر:
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/testtoken/
```

---

## ۴. محدودیتهای فنی (رو راست باشیم)

- **فقط TCP.** دستور UDP/MUX در VLESS رد می‌شود. یعنی QUIC/HTTP3 و DNS UDP از تونل رد نمیشوند؛
  توی کلاینت DNS را DoH بگذار و اگه سایتی کند بود، مرورگر را مجبور به TCP کن.
- **رمزگذاری بیرونی = TLS هاست.** VLESS خودش رمزگذاری نمی‌کند؛ ترافیک بین گوشی و Render
  با TLS رمز می‌شود و سایتهای HTTPS هم رمز دارند. برای کارهای خیلی حساس ازش استفاده نکن.
- **لاگ.** سرور آدرس مقصد (`host:port`) و حجم ترافیک را لاگ می‌کند، نه محتوا. هاست (Render)
  هم متادیتای خودش را دارد. این یه ابزار دور زدن محدودیت شبکه است، نه ناشناسساز حرفهای.
- **ترافیک رایگان محدود است** (حدود ۵ گیگابایت در ماه، ۷۵۰ ساعت روشن بودن).
  فیلم و دانلود سنگین نکن؛ برای وب و پیامرسان مناسب است.
- **فیلترینگ.** ممکن است ISPات آدرس `*.onrender.com` را مسدود کند یا VLESS/WS را تشخیص دهد.
  اون موقع مسیر الف (اپهای رایگان) را استفاده کن. من عمداً هیچ تکنیک DPI-evasion
  (fragment / clean-IP scanner / REALITY) توش نگذاشتم — هم پیچیده است هم دائم تغییر می‌کند.
- **ToS.** فقط مصرف شخصی؛ سرور را تبدیل به پروکسی عمومی نکن و لینک را پخش نکن
  (Render ارائه سرویس به شخص ثالث را ممنوع کرده) [1](https://convika.com/compare/render-free-tier-production/).

---

## ۵. امنیت و عیبیابی

| علامت | علت / راهحل |
|---|---|
| `404 Not Found` | TOKEN اشتباه است. مسیر دقیقاً `/<VPN_TOKEN>` است. |
| `curl /health` وصل نمی‌شود | سرور خوابیده؛ ۶۰ ثانیه صبر کن، یا یه درخواست دیگر بزن تا بیدار شود. |
| کلاینت وصل می‌شود ولی صفحها باز نمی‌شود | UUID اشتباه، یا DNS روی UDP است → DoH بگذار. |
| `reject: invalid UUID` تو لاگ Render | UUID توی لینک با `VPN_UUID` سرور فرق دارد. |
| `connect failed: cannot reach ...` | مقصد از سمت هاست قابل دسترس نیست، یا SSRF-guard جلوی IP خصوصی را گرفته. |
| سرور بعد از ۱۵ دقیقه قطع شد | طبیعی پلن رایگان است؛ پینگ نگهدارنده فقط وقتی کلاینت وصل است کمک می‌کند. |
| خواستی رمزها را عوض کنی | `VPN_UUID` / `VPN_TOKEN` را تو Render عوض کن، سرویس را ریستارت کن و لینک تازه بساز. |

**چکلیست امنیتی:**
- ✅ `vpn/.env` داخل `.gitignore` است؛ هیچوقت کامیتش نکن.
- ✅ TOKEN حداقل ۲۴ کاراکتر تصادفی باشد (`gen_config.py` میسازد).
- ✅ `VPN_ALLOW_PRIVATE=1` را **فقط** برای تست محلی بگذار (باعث می‌شود سرور بتواند به IPهای داخلی هاست وصل شود).
- ✅ لینک `vless://` و صفحه `/<TOKEN>/` را جایی پابلیک نکن.
- ✅ رمزها را توی چت/اسکرینشات/گیت نفرست.

---

## ۶. ساختار فایلها

```
vpn/
├── README.md          # این راهنما
├── server.py          # رله VLESS/WebSocket (stdlib، بدون وابستگی)
├── client.py          # کلاینت SOCKS5 -> VLESS/WS (stdlib، مخصوص ترموکس)
├── wsproto.py         # پیادهسازی مینیمال RFC 6455 WebSocket
├── gen_config.py      # ساخت UUID/TOKEN و لینک vless://
├── render.yaml        # دیپلوی یککلیک روی پلن رایگان Render
└── tests/
    └── test_relay.py  # تست انتها به انتها (بدون وابستگی)
```

---

## ۷. منابع (بررسیشده، مهر ۱۴۰۵ / اکتبر ۲۰۲۶)

- Render پلن رایگان بدون کارت: <https://render.com/docs/free> · <https://render.com/articles/platforms-with-a-real-free-tier-for-developers-in-2026>
- مستندات پروتکل VLESS: <https://xtls.github.io/en/development/protocols/vless.html>
- WebSocket RFC 6455: <https://www.rfc-editor.org/rfc/rfc6455.html>
- Oracle Cloud IP ثابت رزروشده: <https://www.rackupit.com/blog/assign-reserved-static-ip-oracle-cloud-vps>
- ممنوعیت پروکسی در ToS کلودفلر: <https://community.cloudflare.com/t/blocking-xray-and-v2ray-traffic/748125>
- اپهای VPN رایگان ۲۰۲۶: <https://www.tomsguide.com/best-picks/best-free-vpn> · <https://toolradar.com/blog/best-free-vpns>
- وضعیت فیلترینگ ایران و پروتکلها: <https://github.com/net4people/bbs/issues/628>
