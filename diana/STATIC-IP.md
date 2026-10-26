# 🌐 آدرس ثابت رایگان برای دیانا (همیشه متصل)

> خلاصه: «IP ثابت عمومی رایگان» عملاً وجود ندارد، ولی **حتماً هم لازم نیست**.
> چیزی که میخواهی یک **آدرس ثابت** است که هر بار وصل شدی همان بماند.
> توی این مخزن آن را با `online.py` ساختهایم: سرور دیانا + یک تونل رایگان +
> وصل مجدد خودکار + رمز عبور. فقط کافی است یکی از مسیرهای زیر را انتخاب کنی.

---

## ۱. واقعیت (۳۰ ثانیه بخوان)

| پرسش | جواب |
|---|---|
| IP ثابت عمومی رایگان میشود گرفت؟ | نه. IPv4 کمیاب است و اپراتورها بابتش پول میگیرند. |
| چرا IP خانه/موبایل من درست کار نمیکند؟ | اکثر خطوط ایران **CGNAT** هستند؛ یعنی IP عمومی نداری و پورت ورودی بسته است. حتی IP هم هر بار عوض میشود. |
| پس چهکار کنم؟ | بهجای IP، یک **نام/دامنه ثابت** بگیر که تونلی آن را به سرورت وصل کند. نیازی به IP عمومی، پورت فورواردینگ یا روت شدن گوشی نیست. |
| یعنی همیشه آنلاین است؟ | تا وقتی گوشی/کامپیوترت **روشن** و `online.py` در حال اجرا باشد، بله (حتی اگر اینترنت قطع و وصل شود، خودکار برمیگردد). برای ۲۴/۷ واقعی بدون گوشی، از هاست رایگان Render استفاده کن (بخش ۵). |

---

## ۲. کدام راه را انتخاب کنم؟ (مقایسه)

| روش | چی گیر میآوری | آدرس ثابت؟ | دامنه لازم؟ | رویدادهای زنده (SSE) دیانا | محدودیت رایگان |
|---|---|---|---|---|---|
| **ngrok** ⭐ پیشنهادی | `https://abc123.ngrok-free.dev` | ✅ دائمی (مال حسابت میماند) | ❌ | ✅ | ۱ گیگابایت ترافیک + ۲۰٫۰۰۰ درخواست در ماه؛ یک صفحه هشدار قبل از سایت |
| **Cloudflare Quick Tunnel** | `https://xyz.trycloudflare.com` | ❌ هر بار عوض میشود | ❌ | ❌ پشتیبانی نمیکند | بدون تضمین؛ فقط تست |
| **Cloudflare Tunnel نامدار** | `https://diana.example.com` | ✅ دائمی | ✅ یک دامنه روی Cloudflare | ✅ | پلن رایگان Cloudflare کافی است |
| **Tailscale** | IP ثابت `100.x.y.z` | ✅ دائمی | ❌ | ✅ | فقط دستگاههایی میبینند که وارد همان اکانت شدهاند |
| **Render (هاست ابری)** | `https://diana-assistant.onrender.com` | ✅ دائمی | ❌ | ✅ | بعد از ۱۵ دقیقه بیکاری میخوابد؛ استارت سرد حدود ۳۰–۶۰ ثانیه |
| **DuckDNS / No-IP** | `you.duckdns.org` | ✅ اگر IP عمومی داشته باشی | ❌ | ✅ | روی CGNAT و پورت بسته تقریباً بیکار است |

**نتیجه:** برای دیانا (که SSE و اجرای کد دارد) → **ngrok** سادهترین راه است.
اگر فقط دستگاههای خودت باید وصل شوند → **Tailscale** امنترین راه است.

---

## ۳. شروع سریع: ngrok روی ترموکس (۵ دقیقه)

### قدم ۱ — آمادهسازی

```bash
pkg update -y && pkg upgrade -y
pkg install python git wget tar -y
cd ~/Najibrahimi          # یا هرجایی که مخزن را کلون کردهای
git pull
cd diana
```

### قدم ۲ — نصب ngrok (نسخه ARM64 موبایل)

```bash
wget -O /tmp/ngrok.tgz https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm64.tgz
tar -xzf /tmp/ngrok.tgz -C $PREFIX/bin ngrok
chmod +x $PREFIX/bin/ngrok
ngrok version
```

> گوشی ۳۲ بیتی داری؟ بهجای `arm64` بنویس `arm`.
> لینک عوض شد؟ از <https://ngrok.com/download> نسخه Linux (ARM64) را بردار.
> اصلاً ngrok نخواستی؟ `python3 online.py --setup` روی ترموکس `cloudflared` را خودکار نصب میکند (ولی ببین بخش ۲: آدرسش ثابت نیست و SSE ندارد).

### قدم ۳ — یک بار ثبتنام (رایگان)

1. برو <https://dashboard.ngrok.com/signup> و با ایمیل/گوگل وارد شو.
2. از **Your Authtoken** توکن را کپی کن.
3. از **Cloud Edge → Domains** دامنهای ثابت رایگانت را ببین؛ شبیه `abc123.ngrok-free.dev`.
   (همان دامنهای است که `ngrok http 8000` هم به طور خودکار استفاده میکند.)

### قدم ۴ — تنظیمات

```bash
python3 online.py --setup       # فایل .env را میسازد + یک رمز تصادفی قوی
nano .env                       # یا: termux-setup-storage و ویرایش با ادیتور
```

داخل `.env` این سه خط را پر کن:

```dotenv
TUNNEL=ngrok
NGROK_AUTHTOKEN=2abc...توکن-اینجا
NGROK_DOMAIN=abc123.ngrok-free.dev
```

> ⚠️ `.env` داخل `.gitignore` است؛ هیچوقت توکن یا رمز را توی گیت، چت یا اسکرینشات نفرست.

### قدم ۵ — اجرا

```bash
python3 online.py
```

خروجی شبیه این است:

```
==============================================================
🌐 آدرس ثابت دیانا:  https://abc123.ngrok-free.dev
🔒 نام کاربری: diana
🔑 رمز:        xY7_...
📄 ذخیره شد در: data/public-url.txt
==============================================================
```

همان آدرس را در مرورگر هر دستگاهی باز کن. پلن رایگان ngrok یک صفحه هشدار
نشان میدهد → یک بار **Visit Site** را بزن؛ بعد مرورگر نام کاربری و رمز را میپرسد.

**از این به بعد همان آدرس است** — حتی اگر گوشی ریاستارت شود، اینترنت برود،
یا تونل قطع شود؛ `online.py` خودکار دوباره وصل میکند.

دستورهای مفید:

```bash
python3 online.py --show            # آدرس و رمز فعلی
python3 online.py --provider ngrok # انتخاب دستی تونل
python3 online.py --no-server      # اگر server.py را جای دیگری اجرا کردهای
cat data/tunnel.log                # لاگ تونل برای عیبیابی
```

---

## ۴. «همیشه متصل» یعنی چه؟

`online.py` اینکارها را خودکار انجام میدهد:

- ✅ سرور `server.py` را اجرا میکند و اگر کرش کرد دوباره بالا میآورد.
- ✅ تونل را نگه میدارد؛ با قطع اینترنت، با فاصله ۲ ← ۴ ← ۸ ← … ← ۳۰ ثانیه دوباره وصل میشود.
- ✅ سلامت سرور را هر ۱۲ ثانیه چک میکند.
- ✅ آدرس تازه را چاپ و در `data/public-url.txt` ذخیره میکند.
- ✅ یک رمز تصادفی (`DIANA_TOKEN`) میسازد و به سرور میدهد (HTTP Basic Auth).

### روشن شدن خودکار بعد از ریاستارت گوشی (Termux:Boot)

```bash
pkg install termux-api -y          # اختیاری، برای wake-lock
mkdir -p ~/.termux/boot
cp ~/Najibrahimi/diana/termux-boot.sh ~/.termux/boot/diana.sh
chmod +x ~/.termux/boot/diana.sh
```

اپ **Termux:Boot** را هم نصب و یک بار باز کن. از این بعد با هر ریاستارت،
دیانا و تونلش خودکار بالا میآیند (لاگ در `diana/data/online.log`).

> همچنین بهینهسازی باتری اندروید را برای Termux خاموش کن و گوشی را به شارژ بزن؛
> در غیر این صورت اندروید وسط کار پردازش را میخواباند.

### لینوکس (systemd)

`/etc/systemd/system/diana.service`:

```ini
[Unit]
Description=Diana online (static free address)
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/home/user/Najibrahimi/diana
ExecStart=/usr/bin/python3 online.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now diana
journalctl -u diana -f      # دیدن آدرس و رمز
```

### ویندوز

`python online.py` را در یک پنجره PowerShell باز نگه دار، یا با **Task Scheduler**
یک تسک «At log on» بساز که `python.exe <مسیر>\diana\online.py` را اجرا کند.

---

## ۵. ۲۴/۷ واقعی، بدون اینکه گوشی روشن باشد

تونل هرقدر هم خوب باشد، باز به دستگاهی وابسته است که پشتش روشن باشد.
اگر میخواهی حتی با گوشی خاموش هم دیانا جواب بدهد، از هاست رایگان استفاده کن
(فایل آمادهاش توی مخزن هست: `render.yaml`):

1. برو <https://render.com> ← **New → Blueprint** ← مخزن `Najibrahimi` را وصل کن.
2. `render.yaml` را انتخاب کن؛ پلن **Free**.
3. آدرس ثابت میشود: `https://diana-assistant.onrender.com` — نیازی به ngrok و IP ثابت نیست.
4. همان موقع ساخت سرویس، `render.yaml` خودش `DIANA_USER` را میگذارد و `DIANA_TOKEN` را از تو میخواهد (کافی است یک رمز بلند وارد کنی تا سایت محافظت شود).
5. اگر رمز را خالی بگذاری، `server.py` روی هاستهای عمومی خودش یک رمز تصادفی میسازد و توی لاگ چاپ میکند؛ حتماً از لاگ کپی کن.
6. برای ماندگار شدن حافظه، یک **Persistent Disk** روی `diana/data` وصل کن (پلن رایگان Render دیسک دائمی رایگان ندارد؛ میتوانی از حافظه JSON داخل مخزن یا یک سرویس رایگان دیتابیس استفاده کنی).

> GitHub Pages (همان لینکی که توی فایل TERMUX_COMMANDS هست) فقط فایلهای **استاتیک**
> `docs/` را نشان میدهد؛ چون دیانا پایتون است، بکاندش آنجا اجرا نمیشود.

**ترکیب پیشنهادی:** Render به عنوان آدرس اصلی ۲۴/۷ + تونل روی گوشی به عنوان پشتیبان
(دو آدرس ثابت رایگان، هیچکدام پولی نیستند).

---

## ۶. جایگزین امنتر: Tailscale (یک IP ثابت واقعی)

اگر فقط خودت از گوشی/لپتاپت قرار است به دیانا وصل شوی، نیازی به آدرس عمومی نیست:

- پلن **Personal** رایگان است (چند کاربر و دستگاههای نامحدود برای استفاده شخصی).
- به هر دستگاه یک IP ثابت از `100.x.y.z` میدهد که تا وقتی توی اکانتت هست عوض نمیشود.
- پشت CGNAT، وایفای، 4G و ... کار میکند؛ ترافیک رمزگذاری میشود؛ دیانا اصلاً توی اینترنت عمومی دیده نمیشود.
- نصب اپ Tailscale روی دستگاههایت ← لاگین با همان اکانت ← آدرس: `http://100.x.y.z:8000`.

روی ترموکس (ممکن است بسته به نسخه اندروید نیاز به حالت userspace-networking داشته باشد):

```bash
pkg install tailscale -y
tailscale up                  # لینکی میدهد؛ با همان اکانت لاگین کن
tailscale ip -4               # مثلاً 100.101.12.34  ← IP ثابت تو
```

سپس توی `.env`:

```dotenv
TUNNEL=tailscale
```

و `python3 online.py` آدرس `http://100.101.12.34:8000` را به تو نشان میدهد.
اگر نصب Tailscale روی ترموکس دردسر شد، همان ngrok را استفاده کن.

### Cloudflare Tunnel نامدار (اگر دامنه داری)

اگر یک دامنه (حتی ارزان) داری و DNSاش روی Cloudflare است، این بهترین گزینه است:

1. <https://one.dash.cloudflare.com> ← **Networks → Tunnels → Create a tunnel**.
2. نوع **Cloudflared** را انتخاب کن، مسیر `diana.example.com → http://localhost:8000` را بده.
3. توکن تونل را کپی کن و توی `.env` بگذار:

```dotenv
TUNNEL=cloudflare-named
CF_TUNNEL_TOKEN=eyJ...توکن
PUBLIC_URL=https://diana.example.com
```

دیگر محدودیت ترافیک ngrok و صفحه هشدارش را هم نداری، و SSE هم کامل کار میکند.

---

## ۷. 🔒 امنیت (خیلی مهم)

دیانا ابزاری دارد که **کد پایتون اجرا میکند** و به حافظه و فایلهایت دسترسی دارد.
باز کردنش روی اینترنت بدون رمز یعنی هر کسی لینک را پیدا کند میتواند از آن استفاده کند.
برای همین:

- `online.py` به طور خودکار `DIANA_TOKEN` تصادفی میسازد و `server.py` همهٔ درخواستها
  (HTML، API، SSE، دانلود فایل، حذف) را با **HTTP Basic Auth** چک میکند.
- بدون `DIANA_TOKEN` (اجرای معمولی `python3 server.py`) رفتار مثل قبل است: فقط محلی، بدون رمز.
- استثنای امنیتی: روی هاستهای عمومی (Render/Railway/Fly/Heroku) اگر رمز نگذاری، `server.py` خودش رمز تصادفی میسازد و در لاگ چاپ میکند تا دیانا بیحفاظ آنلاین نماند.
- `.env`، `data/public-url.txt` و لاگها داخل `.gitignore` هستند.
- رمز را عوض کردن: خط `DIANA_TOKEN` توی `.env` را عوض کن و `online.py` را دوباره اجرا کن.
- امنترین حالت، **Tailscale** است: اصلاً آدرس عمومی وجود ندارد.
- پلن رایگان ngrok قبل از سایت یک صفحه هشدار فیشینگ نشان میدهد؛ یک بار کلیک «Visit Site» کافی است.

---

## ۸. عیبیابی

| علامت | دلیل / راهحل |
|---|---|
| آدرس هر بار عوض میشود | داری از Cloudflare Quick Tunnel استفاده میکنی. `TUNNEL=ngrok` بگذار و `NGROK_DOMAIN` را پر کن، یا `cloudflare-named`. |
| صفحه بالا میآید ولی رویدادها/مرکز فرماندهی زنده نیست | Quick Tunnel از SSE پشتیبانی نمیکند → ngrok / Tailscale / Cloudflare نامدار. |
| مرورگر مدام رمز میخواهد / 401 | کاربر `DIANA_USER` و رمز `DIANA_TOKEN` از `.env` را وارد کن. `python3 online.py --show`. |
| `ERR_NGROK_108` / توکن قبول نیست | `NGROK_AUTHTOKEN` اشتباه است، یا دستی اجرا کن: `ngrok config add-authtoken <TOKEN>`. |
| تونل هر چند ثانیه یکبار قطع میشود | لاگ `data/tunnel.log` را ببین؛ معمولاً توکن، دامنه اشتباه یا نسخه قدیمی ngrok است. |
| سرور بالا نمیآید | `PORT` توی `.env` را عوض کن یا `python3 server.py` را جدا اجرا کن تا خطا را ببینی. |
| گوشی خوابید و لینک مرد | بهینهسازی باتری Termux را خاموش کن + `termux-wake-lock` + اسکریپت بوت Termux:Boot (بخش ۴). |
| بعد از ریاستارت آدرس در دسترس نیست | `~/.termux/boot/diana.sh` را چک کن و `cat data/online.log`. |
| اصلاً نمیتوانم سایت را از ایران باز کنم | درگاه پرداخت/ثبتنام بعضی سرویسها ممکن است محدود باشد؛ Tailscale یا Render را امتحان کن. |

---

## ۹. خلاصه دستورها

```bash
cd ~/Najibrahimi/diana
python3 online.py --setup     # یک بار: ساخت .env و رمز
python3 online.py             # اجرا: آدرس ثابت + وصل مجدد خودکار
python3 online.py --show      # آدرس و رمز فراموش شد
```

منابع رسمی (برای چک کردن تغییرات پلنهای رایگان):

- ngrok — دامنه ثابت رایگان: <https://ngrok.com/blog/free-static-domains-ngrok-users> · محدودیتها: <https://ngrok.com/docs/pricing-limits/free-plan-limits>
- Cloudflare Quick Tunnels: <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/>
- Tailscale Personal: <https://tailscale.com/pricing>
- Render Blueprint پروژه: `diana/render.yaml`
