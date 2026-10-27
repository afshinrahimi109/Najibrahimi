#!/data/data/com.termux/files/usr/bin/bash
# 🐠 شروع خودکار دیانا بعد از روشن شدن گوشی (Termux:Boot)
# کپی کن به:  ~/.termux/boot/diana.sh
#   mkdir -p ~/.termux/boot && cp diana/termux-boot.sh ~/.termux/boot/diana.sh
DIANA_DIR="${DIANA_DIR:-$HOME/Najibrahimi/diana}"
if [ ! -f "$DIANA_DIR/online.py" ]; then
  for d in "$HOME/storage/downloads/NajibRahimi/diana" "$HOME/Najibrahimi/diana" "$HOME/diana"; do
    if [ -f "$d/online.py" ]; then DIANA_DIR="$d"; break; fi
  done
fi
if [ ! -f "$DIANA_DIR/online.py" ]; then
  echo "diana/online.py not found. Set DIANA_DIR in this script." >&2
  exit 1
fi
cd "$DIANA_DIR" || exit 1
mkdir -p data
# جلوگیری از خواب رفتن پردازنده و قطع شدن تونل
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock
exec python3 online.py >> data/online.log 2>&1
