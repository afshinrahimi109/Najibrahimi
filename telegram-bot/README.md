# بات تلگرام Najib Agent

بات خصوصیِ ساخت پیش‌نویس ریل به فارسی: با `/reel <موضوع>` ابتدا زاویهٔ محتوا را انتخاب می‌کند، سپس سناریو/کپشن می‌سازد و نتیجه را در SQLite ذخیره می‌کند. بات فقط به شناسهٔ کاربریِ تنظیم‌شده پاسخ می‌دهد و فقط در گفت‌وگوی خصوصی کار می‌کند.

> توکن تلگرام و کلید OpenRouter را در مخزن، کد، چت یا تلگرام قرار نده. فایل `.env` محلی نادیده گرفته می‌شود؛ در Railway از **Variables** استفاده کن. حتی مخزن Private هم جای نگهداری secret نیست.

## فرمان‌ها

- `/start` و `/help` — شروع و راهنما
- `/reel چهار مسیر شغلی در هوش مصنوعی برای افراد مبتدی` — ساخت پیش‌نویس در دو مرحله
- `/status` — وضعیت بات، پیکربندی OpenRouter، تعداد پیش‌نویس‌ها و وضعیت اتصال اینستاگرام
- `/drafts` — فهرست ۱۰ پیش‌نویس اخیر
- `/draft 12` — نمایش پیش‌نویس با شناسهٔ ۱۲

بات در این نسخه **هیچ چیزی در اینستاگرام منتشر نمی‌کند**. متن ذخیره‌شده پیش‌نویس است؛ بازبینی و تأیید نهایی با صاحب بات می‌ماند. `/status` عمداً نشان می‌دهد: «اتصال رسمی اینستاگرام: انجام نشده».

## اجرای محلی

پیش‌نیاز: Python 3.10 یا جدیدتر.

```bash
cd telegram-bot
cp .env.example .env
# مقادیر .env را فقط روی دستگاه خودت وارد کن.
python -m venv .venv
# لینوکس / macOS / Termux:
. .venv/bin/activate
# ویندوز PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

برای Docker Compose:

```bash
cd telegram-bot
cp .env.example .env
# .env را ویرایش کن، سپس:
docker compose up --build -d
docker compose logs -f telegram-bot
```

داده‌ها در volume محلی Docker با نام `drafts` نگه‌داری می‌شوند. برای توقف: `docker compose down`؛ برای پاک‌کردن دیتابیس هم باید volume را جداگانه حذف کنی.

## راه‌اندازی روی Railway

این پوشه داخل مخزن اصلی قرار دارد. دو راه داری:

### استفاده از همین مخزن

1. مخزن را در Railway به‌عنوان سرویس Docker متصل کن.
2. در تنظیمات سرویس، **Root Directory** را روی `/telegram-bot` بگذار تا Railway همین `Dockerfile` را پیدا کند. این بات long polling دارد و به دامنهٔ عمومی یا پورت وب نیاز ندارد.
3. در **Variables** این مقادیر را اضافه کن:

   | Variable | مقدار |
   |---|---|
   | `TELEGRAM_BOT_TOKEN` | توکن ساخته‌شده در BotFather |
   | `TELEGRAM_OWNER_ID` | شناسهٔ عددی حساب تلگرام خودت |
   | `OPENROUTER_API_KEY` | کلید API در OpenRouter |
   | `OPENROUTER_MODEL` | `openai/gpt-4o-mini` |
   | `OPENROUTER_TIMEOUT_SECONDS` | `45` (اختیاری) |
   | `DATABASE_PATH` | `/app/data/drafts.sqlite3` (اختیاری؛ همین پیش‌فرض Docker است) |

4. برای ماندگاری پیش‌نویس‌ها بین deployها، به سرویس یک Railway **Volume** وصل و آن را روی `/app/data` mount کن. بدون volume ممکن است SQLite با جایگزینی container از دست برود.
5. Deploy کن؛ سپس در تلگرام `/start`، `/status` و دستور نمونهٔ `/reel چهار مسیر شغلی در هوش مصنوعی برای افراد مبتدی` را امتحان کن.

### مخزن جداگانهٔ Private با نام `najib-agent`

اگر می‌خواهی دقیقاً مخزن جداگانه بسازی، **محتویات همین پوشه** را در ریشهٔ مخزن Private آپلود کن (فایل `.env` را هرگز آپلود نکن). در آن حالت Root Directory سرویس Railway همان ریشهٔ مخزن است و به `/telegram-bot` نیاز ندارد. برای ماندگاری، Volume را همچنان روی `/app/data` وصل کن.

> مخزن Private انتخاب خوبی برای محدودکردن دسترسی به کد است؛ اما امنیت secret به این وابسته است که توکن‌ها فقط در Variables باشند و هرگز commit نشوند. اگر توکنی قبلاً افشا شده، آن را در BotFather باطل و جایگزین کن.

## اجرای آزمون‌ها

```bash
cd telegram-bot
python -m unittest discover -s tests -v
```
