#!/usr/bin/env bash
# Configure Gemini without exposing the key or changing Telegram/database settings.
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
if [[ ! -f .env ]]; then
  echo "فایل .env پیدا نشد؛ اول bash setup.sh را اجرا کن." >&2
  exit 1
fi

read -r -s -p "کلید Gemini را پیست کن (روی صفحه دیده نمی‌شود): " GEMINI_API_KEY
echo
if [[ -z "$GEMINI_API_KEY" ]]; then
  echo "کلید خالی است؛ چیزی تغییر نکرد." >&2
  exit 1
fi
umask 077
printf '%s' "$GEMINI_API_KEY" | python -c '
from pathlib import Path
import sys
path = Path(".env")
key = sys.stdin.read().strip()
if not key or "\n" in key or "\r" in key:
    raise SystemExit("کلید نامعتبر است؛ چیزی تغییر نکرد.")
lines = path.read_text(encoding="utf-8").splitlines()
values = {line.split("=", 1)[0]: i for i, line in enumerate(lines) if "=" in line and not line.lstrip().startswith("#")}
if "GEMINI_API_KEY" in values:
    lines[values["GEMINI_API_KEY"]] = "GEMINI_API_KEY=" + key
else:
    lines.append("GEMINI_API_KEY=" + key)
if "GEMINI_MODEL" not in values:
    lines.append("GEMINI_MODEL=gemini-2.5-flash")
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
path.chmod(0o600)
'
unset GEMINI_API_KEY
echo "Gemini تنظیم شد؛ بات با Gemini راه‌اندازی می‌شود."
exec .venv/bin/python app.py
