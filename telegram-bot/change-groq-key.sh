#!/usr/bin/env bash
# Rotate the Groq key without displaying it or replacing the other local settings.
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
if [[ ! -f .env ]]; then
  echo "فایل .env پیدا نشد؛ اول bash setup.sh را اجرا کن." >&2
  exit 1
fi

read -r -s -p "کلید جدید Groq را پیست کن (روی صفحه دیده نمی‌شود): " GROQ_API_KEY
echo
if [[ -z "$GROQ_API_KEY" ]]; then
  echo "کلید خالی است؛ چیزی تغییر نکرد." >&2
  exit 1
fi
umask 077
printf '%s' "$GROQ_API_KEY" | python -c '
from pathlib import Path
import sys
path = Path(".env")
key = sys.stdin.read().strip()
if not key or "\n" in key or "\r" in key:
    raise SystemExit("کلید نامعتبر است؛ چیزی تغییر نکرد.")
lines = path.read_text(encoding="utf-8").splitlines()
updated = False
for index, line in enumerate(lines):
    if line.startswith("GROQ_API_KEY="):
        lines[index] = "GROQ_API_KEY=" + key
        updated = True
        break
if not updated:
    lines.append("GROQ_API_KEY=" + key)
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
path.chmod(0o600)
'
unset GROQ_API_KEY
echo "کلید Groq در فایل محلی به‌روزرسانی شد. بات با تنظیم جدید در حال اجراست."
exec .venv/bin/python app.py
