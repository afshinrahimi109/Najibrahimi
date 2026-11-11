# 🐠 لینک‌های دیانا (نسخهٔ ۲.۳ — تک‌پورت)

## ۱) اپ اصلی (سرور زنده)

https://8099-ixe6tfj23ie9obqucrdcg.e2b.app

## ۲) نسخهٔ بدون سرور (اگر بالایی باز نشد)

https://8099-ixe6tfj23ie9obqucrdcg.e2b.app/docs

## ۳) تست سلامت اتصال

https://8099-ixe6tfj23ie9obqucrdcg.e2b.app/api/ping

باید جواب بدهد: `{"ok": true, "diana": true, "version": "2.3-singleport", ...}`

---

### چطور مطمئن شوی لینک همان لینک درست است؟

در پنل **LIVE PREVIEW** کنار پروسهٔ «Diana — Business Launch War Room» لینکی نشان داده می‌شود؛
همان معتبر است. الگوی همیشگی: `https://{پورت}-{شناسهٔ سندباکس}.e2b.app`

شناسهٔ فعلی سندباکس: `ixe6tfj23ie9obqucrdcg` (با هر جلسهٔ تازه عوض می‌شود)

### اجرای دوباره روی سیستم خودت

```bash
cd diana
PORT=8099 DIANA_WS_PORT=8101 python3 server.py
# → http://localhost:8099  و  http://localhost:8099/docs
```

### لینک ثابت همیشگی (اختیاری)

```bash
cd diana
python3 online.py --setup     # ngrok / Cloudflare / Render + رمز
python3 online.py             # آدرس ثابت
```

جزئیات: `diana/STATIC-IP.md`
