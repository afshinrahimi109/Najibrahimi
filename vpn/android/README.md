# 📱 اپ اندرویدی FreeVPN (ساختهشده از صفر)

این یه **اپ VPN واقعی اندروید** است که از صفر نوشته شده — بدون هیچ کتابخانهای،
بدون v2rayNG، بدون Hiddify، بدون نیاز به ترموکس:

- `VpnService` اندروید → یه رابط TUN میسازد و کل ترافیک گوشی را میگیرد.
- `Tun2Socks.java` → یه پردازشگر بسته IPv4/TCP/UDP مینیمال که خودمان نوشتیم.
- `RelaySocket.java` → هندشیک WebSocket (RFC 6455) + هدر باینری VLESS را خودش میسازد
  و مستقیم به سرور `vpn/server.py` وصل میشود.
- `IpUtils.java` → ساخت بسته IP/TCP/UDP و محاسبه checksum از صفر.
- `MainActivity.java` → لینک `vless://` را میخواند و فیلدها را پر میکند.

> ⚠️ **محدودیت مهم:** فقط IPv4 و TCP پشتیبانی میشود. یعنی QUIC/HTTP3 و بقیه ترافیک
> UDP کار نمیکند (DNS هم از طریق یه سوکت محافظتشده مستقیم به 1.1.1.1 میرود).
> این یه پروژهٔ شخصی/آزمایشی است، نه یه کلاینت حرفهای مثل Hiddify. اگه دنبال
> پایداری حداکثری هستی، همان Hiddify/v2rayNG را با لینک `vless://` استفاده کن
> (آموزشش تو [`vpn/README.md`](../README.md) هست).

---

## ۱. گرفتن APK — مستقیم از داخل خود گیتھاب (رایگان، بدون کامپیوتر)

**سادهترین راه 👈 لینک مستقیم دانلود:**

🔽 **https://github.com/afshinrahimi109/Najibrahimi/releases/download/v1.0.0/FreeVPN.apk**

یا برو تو مخزن ← سمت راست صفحه **Releases** ← نسخه `v1.0.0` ← فایل `FreeVPN.apk`.
دیگه لازم نیست دنبال Artifact بگردی؛ workflow هربار که کد تغییر کنه خودش APK رو
میسازه و تو همون صفحهٔ Releases آپدیت میکنه.

> چرا قبلاً تو گیتھاب نبود؟ چون workflow فقط روی برنچ قدیمی
> `arena/f21d825b-najibrahimi` اجرا میشد و بعد از مرج شدن PR دیگه تریگر نمیشد.
> الان `main` و همهٔ برنچهای `arena/**` هم بیلد میشوند و نتیجه داخل **Releases** میرود.

راه جایگزین (آرتیفکت): تب **Actions** ← آخرین اجرای
[Build FreeVPN Android APK](https://github.com/afshinrahimi109/Najibrahimi/actions/workflows/build-apk.yml)
← بخش **Artifacts** ← `freevpn-debug-apk` (ZIP) ← `FreeVPN.apk`.

بعد از دانلود: فایل APK را باز کن و نصب کن
(لازمه گزینه «نصب از منابع ناشناخته / Install unknown apps» را برای مرورگرت روشن کنی).

## ۲. استفاده

1. اول سرور را بالا بیار (آموزش [`vpn/README.md`](../README.md) — مسیر ب، قدم ۱ تا ۳).
2. لینک `vless://...` را از `gen_config.py` یا صفحه `https://host/<TOKEN>/` کپی کن.
3. اپ FreeVPN را باز کن → لینک را تو کادر اول بچسبان → **خواندن لینک**.
4. **وصل شو ✅** → اندروید یه صفحه اجازه VPN نشان میدهد → تأیید کن.
5. تست: مرورگر را باز کن و یه سایت خارجی ببین.

> نکته: پلن رایگان Render بعد ۱۵ دقیقه بیکاری میخوابد؛ بار اول حدود ۱ دقیقه
> طول میکشد سرور بیدار شود. صبور باش 🙂

## ۳. ساخت با کامپیوتر (اختیاری)

```bash
# نیاز: JDK 17 + Android SDK (platform android-34, build-tools 34.0.0)
cd vpn/android
gradle assembleDebug
# خروجی: app/build/outputs/apk/debug/app-debug.apk
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## ۴. عیبیابی

| علامت | راهحل |
|---|---|
| **سایتها (مثلاً گیتھاب) باز نمیشوند** | دکمهٔ **🔍 تست اتصال** را بزن. شماره ۱ = DNS هاست، ۲ = TCP/TLS/WebSocket/VLESS، ۳ = ترافیک واقعی. هرجا ایستاد، مشکل همانجاست. اگه هر ۳ تا ✅ شد ولی سایت باز نشد → **تنظیمات اندروید → Private DNS → `dns.google`** بگذار (DNS گوشی فیلتر/مسموم شده). |
| APK توی Releases نیست | لینک بالا را مستقیم باز کن؛ اگه 404 داد، تب Actions را ببین که بیلد قرمز نشده باشه. |
| «اجازه VPN داده نشد» | دوباره «وصل شو» را بزن و تو پنجره اندروید تأیید کن. |
| شماره ۱ تست قرمز شد (UnknownHost) | هاست اشتباه است یا DNS گوشی نمیتواند `*.onrender.com` را حل کند. Private DNS را روی `dns.google` بگذار. |
| شماره ۲ تست قرمز شد | TOKEN/UUID اشتباه، سرور خوابیده (۶۰ث صبر کن)، پورت/اشتباهی TLS، یا ISP آدرس Render را بسته. لاگ Render را چک کن. |
| وصل میشود ولی سایتها باز نمیشوند | سرور خوابیده (صبر کن)، یا TOKEN/UUID اشتباه است، یا فیلترینگ ISP جلوی `*.onrender.com` را گرفته. |
| بعضی اپها کار نمیکنند | آن اپ از UDP/QUIC استفاده میکند؛ این اپ فقط TCP را پشتیبانی میکند. از Hiddify استفاده کن. |
| باتری زود تمام میشود | طبیعی است؛ TUN + TLS مداوم مصرف دارد. |

## ۵. ساختار

```
vpn/android/
├── settings.gradle, build.gradle, gradle.properties
└── app/
    ├── build.gradle
    └── src/main/
        ├── AndroidManifest.xml
        └── java/com/najibrahimi/freevpn/
            ├── MainActivity.java     # رابط کاربری + خواندن لینک vless://
            ├── FreeVpnService.java   # VpnService + TUN + نوتیفیکیشن
            ├── Tun2Socks.java        # پردازش بستهها + پل TCP/DNS
            ├── RelaySocket.java      # WebSocket + VLESS (از صفر)
            └── IpUtils.java          # IP/TCP/UDP + checksum
```
