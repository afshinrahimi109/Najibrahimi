#!/bin/bash
# 🐠 اجرای دیانا در لینوکس / مک / ترموکس (Termux)
cd "$(dirname "$0")"
echo "🐠 در حال بیدار کردن دیانا..."
echo "🌐 بعد از اجرا، مرورگر را باز کن: http://localhost:8000"
python3 server.py
