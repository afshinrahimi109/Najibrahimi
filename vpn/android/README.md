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

## ۱. گرفتن APK (رایگان، بدون کامپیوتر)

وقتی این پوشه پوش بشه، workflow [`build-apk.yml`](../../../.github/workflows/build-apk.yml)
روی GitHub Actions اجرا میشه و یه APK میسازد:

1. برو تو مخزن گیتھابت ← تب **Actions**.
2. روی آخرین اجرای **Build FreeVPN Android APK** کلیک کن.
3. پایین صفحه، تو بخش **Artifacts**، روی `freevpn-debug-apk` کلیک کن → یه فایل ZIP میگیری.
4. ZIP را تو گوشی باز کن → `app-debug.apk` را نصب کن
   (لازمه گزینه «نصب از منابع ناشناخته / Install unknown apps» را برای مرورگرت روشن کنی).

اگه خواستی دستی اجرا کنی: Actions ← همون workflow ← **Run workflow**.

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
| APK توی Artifacts نیست | تب Actions را باز کن؛ اگه قرمز شد، لاگش را بفرست تا درستش کنیم. |
| «اجازه VPN داده نشد» | دوباره «وصل شو» را بزن و تو پنجره اندروید تأیید کن. |
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
