#!/data/data/com.termux/files/usr/bin/bash
# 📸 شروع خودکار ایجنت اینستاگرام بعد از روشن شدن گوشی (اپ Termux:Boot لازم است)
# کپی کن به:  ~/.termux/boot/insta-agent.sh
#   mkdir -p ~/.termux/boot && cp insta-agent/termux-boot.sh ~/.termux/boot/insta-agent.sh
AGENT_DIR="${AGENT_DIR:-$HOME/Najibrahimi/insta-agent}"
if [ ! -f "$AGENT_DIR/insta_agent.py" ]; then
  for d in "$HOME/storage/downloads/NajibRahimi/insta-agent" "$HOME/Najibrahimi/insta-agent" "$HOME/insta-agent" "$HOME"; do
    if [ -f "$d/insta_agent.py" ]; then AGENT_DIR="$d"; break; fi
  done
fi
if [ ! -f "$AGENT_DIR/insta_agent.py" ]; then
  echo "insta_agent.py not found. Set AGENT_DIR in this script." >&2
  exit 1
fi
cd "$AGENT_DIR" || exit 1
LOG_DIR="${AGENT_DATA_DIR:-$HOME/.insta_agent}"
mkdir -p "$LOG_DIR"
# جلوگیری از خواب رفتن پردازنده (وگرنه زمان‌بندی و پاسخ خودکار می‌ایستد)
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock
# گزارش قبلی را نگه می‌دارد تا فایل بی‌نهایت بزرگ نشود
[ -f "$LOG_DIR/agent.log" ] && mv -f "$LOG_DIR/agent.log" "$LOG_DIR/agent.log.1"
exec python3 insta_agent.py --no-browser >> "$LOG_DIR/agent.log" 2>&1
