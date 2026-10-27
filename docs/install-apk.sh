#!/usr/bin/env bash
# install-apk.sh — نصب FreeVPN.apk وقتی دانلود مستقیم از گیتھاب «معلق» میشود.
# اجرا در Termux:
#   curl -fsSL -o i.sh <raw-url>/docs/install-apk.sh && bash i.sh
# فقط از stdlib/ابزارهای معمولی ترموکس استفاده میکند.
set -u

REPO="afshinrahimi109/Najibrahimi"
BRANCH="arena/621700c4-najibrahimi"
RAW="https://raw.githubusercontent.com/$REPO/$BRANCH/docs"
RAW_MAIN="https://raw.githubusercontent.com/$REPO/main/docs"
RELEASE="https://github.com/$REPO/releases/download/v1.0.0/FreeVPN.apk"
PROXY1="https://gh-proxy.com/https://github.com/$REPO/releases/download/v1.0.0/FreeVPN.apk"
PROXY2="https://ghproxy.net/https://github.com/$REPO/releases/download/v1.0.0/FreeVPN.apk"
APK_NAME="FreeVPN.apk"
JSDEL="https://cdn.jsdelivr.net/gh/$REPO@arena%2F621700c4-najibrahimi/docs"
GHRAW="https://github.com/$REPO/raw/refs/heads/$BRANCH/docs/$APK_NAME"
PAGES="https://afshinrahimi109.github.io/Najibrahimi/$APK_NAME"

echo "======================================================"
echo " 🔐 نصب FreeVPN.apk — حالت مقاوم در برابر قطع دانلود"
echo "======================================================"
echo "[*] نصب ابزارهای لازم..."
pkg install -y curl coreutils >/dev/null 2>&1 || true

mkdir -p "$HOME"
OUT="$HOME/$APK_NAME"
rm -f "$OUT"

# اگه از داخل خود ریپو اجرا شده، همان فایل لوکالی را کپی کن (هیچ دانلودی لازم نیست)
LOCAL="$(cd "$(dirname "$0")" 2>/dev/null && pwd)/$APK_NAME"
if [ -s "$LOCAL" ]; then
  cp "$LOCAL" "$OUT"
  echo "✅ از فایل داخل ریپو استفاده شد (بدون دانلود): $LOCAL"
else
echo "[*] امتحان لینکها (هرکدوم کار کرد ادامه میدیم)..."
for u in "$GHRAW" "$JSDEL/$APK_NAME" "$PAGES" "$RAW/$APK_NAME" "$RAW_MAIN/$APK_NAME" \
         "$PROXY1" "$PROXY2" "$RELEASE"; do
  echo "    → $u"
  rm -f "$OUT"
  if curl -fL --connect-timeout 10 --max-time 120 --retry 3 --retry-delay 2 \
       -o "$OUT" "$u" 2>/dev/null && [ -s "$OUT" ]; then
    echo "    ✅ دانلود OK"
    break
  fi
  echo "    ❌ نشد، لینک بعدی"
done
fi

if [ ! -s "$OUT" ]; then
  echo "[*] هیچ لینک باینری کار نکرد؛ میریم سراغ نسخهٔ متنی base64..."
  for u in "$JSDEL/$APK_NAME.base64.txt" "$RAW/$APK_NAME.base64.txt" "$RAW_MAIN/$APK_NAME.base64.txt" \
           "https://afshinrahimi109.github.io/Najibrahimi/$APK_NAME.base64.txt"; do
    echo "    → $u"
    if curl -fL --connect-timeout 10 --max-time 120 --retry 3 --retry-delay 2 \
         -o "$HOME/fvpn.b64" "$u" 2>/dev/null && [ -s "$HOME/fvpn.b64" ]; then
      base64 -d "$HOME/fvpn.b64" > "$OUT" 2>/dev/null || true
      [ -s "$OUT" ] && echo "    ✅ از روی متن ساخته شد" && break
    fi
  done
fi

if [ ! -s "$OUT" ]; then
  echo "❌ نتونستم دانلود کنم. یه بار دیگه اجرا کن یا وایفای/دیتا رو عوض کن."
  exit 1
fi

echo "[*] حجم: $(wc -c < "$OUT") بایت"
EXP=""
for u in "$JSDEL/$APK_NAME.sha256" "$RAW/$APK_NAME.sha256" "$RAW_MAIN/$APK_NAME.sha256"; do
  EXP=$(curl -fsSL --connect-timeout 8 --max-time 20 "$u" 2>/dev/null | awk '{print $1}' | head -1)
  [ -n "$EXP" ] && break
done
ACT=$(sha256sum "$OUT" | awk '{print $1}')
if [ -n "$EXP" ]; then
  echo "[*] sha256 مورد انتظار: $EXP"
  echo "[*] sha256 فایل تو     : $ACT"
  [ "$EXP" = "$ACT" ] && echo "✅ امضا مطابقت کرد" || echo "⚠️ امضا فرق کرد! فایل رو پاک و دوباره دانلود کن."
else
  echo "[*] sha256 فایل: $ACT"
fi

# منتقل کردن به حافظه shared تا installer اندروید بتواند بخواندش
if [ -d "$HOME/storage/downloads" ]; then
  cp "$OUT" "$HOME/storage/downloads/$APK_NAME" && OUT="$HOME/storage/downloads/$APK_NAME"
else
  echo "[!] اگه نصب نشد: termux-setup-storage بزن و دوباره اجرا کن."
fi

echo "[*] باز کردن فایل برای نصب..."
if command -v termux-open >/dev/null 2>&1; then
  termux-open "$OUT"
elif command -v am >/dev/null 2>&1; then
  am start -a android.intent.action.VIEW -d "file://$OUT" \
    -t application/vnd.android.package-archive >/dev/null 2>&1 || true
fi
echo "✅ تمام. فایل: $OUT"
