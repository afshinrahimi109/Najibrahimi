#!/usr/bin/env bash
# Guided local setup for Linux, macOS, and Termux. Secrets are saved locally in .env only.
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

if [[ ! -f .env ]]; then
  echo "راه‌اندازی Holo Agent"
  echo "کلیدها فقط روی همین دستگاه در فایل محافظت‌شدهٔ .env ذخیره می‌شوند؛ آن‌ها را برای کسی نفرست."
  echo
  echo "۱) توکن ربات را از @BotFather بساز."
  read -r -s -p "توکن Telegram Bot: " TELEGRAM_BOT_TOKEN
  echo
  if [[ -z "$TELEGRAM_BOT_TOKEN" ]]; then echo "توکن خالی است؛ دوباره اجرا کن." >&2; exit 1; fi

  echo "۲) شناسهٔ عددی تلگرامت را از @userinfobot بگیر."
  read -r -p "شناسهٔ عددی مالک: " TELEGRAM_OWNER_ID
  if [[ ! "$TELEGRAM_OWNER_ID" =~ ^[0-9]+$ ]] || [[ "$TELEGRAM_OWNER_ID" == "0" ]]; then
    echo "شناسه باید عددی و بزرگ‌تر از صفر باشد." >&2
    exit 1
  fi

  echo "۳) یکی را انتخاب کن: Gemini، Groq، یا مدل عمومی بدون کلید."
  echo "   کلید Gemini را از aistudio.google.com/apikey یا کلید Groq را از console.groq.com/keys بگیر."
  read -r -p "انتخاب (1=Gemini، 2=Groq، 3=بدون کلید) [3]: " AI_PROVIDER
  AI_PROVIDER="${AI_PROVIDER:-3}"
  if [[ "$AI_PROVIDER" == "1" ]]; then
    read -r -s -p "کلید Gemini: " AI_API_KEY
    echo
    if [[ -z "$AI_API_KEY" ]]; then echo "کلید خالی است؛ دوباره اجرا کن." >&2; exit 1; fi
    PROVIDER_LINES=$'GEMINI_API_KEY='"$AI_API_KEY"$'\nGEMINI_MODEL=gemini-2.5-flash'
  elif [[ "$AI_PROVIDER" == "2" ]]; then
    read -r -s -p "کلید Groq: " AI_API_KEY
    echo
    if [[ -z "$AI_API_KEY" ]]; then echo "کلید خالی است؛ دوباره اجرا کن." >&2; exit 1; fi
    PROVIDER_LINES=$'GROQ_API_KEY='"$AI_API_KEY"$'\nGROQ_MODEL=llama-3.3-70b-versatile'
  elif [[ "$AI_PROVIDER" == "3" ]]; then
    PROVIDER_LINES=$'PUBLIC_FALLBACK=1'
  else
    echo "انتخاب معتبر نیست؛ دوباره اجرا کن." >&2
    exit 1
  fi

  umask 077
  {
    printf 'TELEGRAM_BOT_TOKEN=%s\n' "$TELEGRAM_BOT_TOKEN"
    printf 'TELEGRAM_OWNER_ID=%s\n' "$TELEGRAM_OWNER_ID"
    printf '%s\n' "$PROVIDER_LINES"
    printf 'DATABASE_PATH=./data/drafts.sqlite3\n'
  } > .env
  chmod 600 .env
  unset TELEGRAM_BOT_TOKEN TELEGRAM_OWNER_ID AI_API_KEY PROVIDER_LINES
  echo "تنظیمات محلی ذخیره شد."
else
  echo "فایل .env از قبل وجود دارد؛ تنظیمات فعلی را تغییر نمی‌دهم."
fi

if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then
  echo "Python پیدا نشد. در Termux اجرا کن: pkg install python" >&2
  exit 1
fi
PYTHON="$(command -v python3 || command -v python)"
if [[ ! -x .venv/bin/python ]]; then
  echo "در حال آماده‌کردن محیط Python…"
  "$PYTHON" -m venv .venv
fi

echo "در حال نصب کتابخانه‌های لازم…"
.venv/bin/python -m pip install -r requirements.txt

echo
printf "راه‌اندازی تمام شد. ربات در حال اجراست؛ برای توقف Ctrl+C را بزن.\n"
exec .venv/bin/python app.py
