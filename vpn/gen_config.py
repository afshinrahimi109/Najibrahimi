#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_config.py — ساخت رمزها و لینک کانفیگ VPN (فقط stdlib)

  python3 gen_config.py
  python3 gen_config.py --host my-vpn.onrender.com --write-env
  python3 gen_config.py --host 127.0.0.1 --port 8000 --http   # تست محلی
"""
from __future__ import annotations

import argparse
import os
import secrets
import uuid
from pathlib import Path
from urllib.parse import quote

BASE = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser(description="ساخت UUID/TOKEN و لینک vless://")
    p.add_argument("--host", default=os.environ.get("VPN_HOST", ""), help="هاست عمومی، مثلاً my-vpn.onrender.com")
    p.add_argument("--port", type=int, default=443)
    p.add_argument("--http", action="store_true", help="لینک بدون TLS (تست محلی)")
    p.add_argument("--write-env", action="store_true", help="ذخیره مقادیر در vpn/.env (گیت نمیشود)")
    p.add_argument("--uuid", default="", help="استفاده از UUID دلخواه")
    p.add_argument("--token", default="", help="استفاده از TOKEN دلخواه")
    args = p.parse_args()

    uid = args.uuid.strip() or str(uuid.uuid4())
    token = args.token.strip() or secrets.token_urlsafe(24)
    scheme = "http" if args.http else "https"
    port = args.port

    print("\n🔑 مقادیری که باید در تنظیمات هاست (Environment) بگذاری:")
    print("=" * 62)
    print(f"VPN_UUID={uid}")
    print(f"VPN_TOKEN={token}")
    print(f"PUBLIC_HOST={args.host}" if args.host else "# PUBLIC_HOST= (اختیاری)")
    if args.http:
        print("VPN_PUBLIC_SCHEME=http")
        print(f"VPN_PUBLIC_PORT={port}")
    print("=" * 62)

    if args.write_env:
        env = BASE / ".env"
        env.write_text(f"VPN_UUID={uid}\nVPN_TOKEN={token}\nVPN_HOST={args.host}\n",
                       encoding="utf-8")
        try:
            os.chmod(env, 0o600)
        except OSError:
            pass
        print(f"📝 ذخیره شد در {env} (داخل .gitignore است)")

    if args.host:
        path = "/" + token
        params = ["encryption=none", "type=ws", f"host={quote(args.host, safe='')}",
                  f"path={quote(path, safe='')}"]
        if not args.http:
            params += ["security=tls", f"sni={quote(args.host, safe='')}", "fp=chrome"]
        else:
            params.append("security=none")
        link = f"vless://{uid}@{args.host}:{port}?{'&'.join(params)}#FreeVPN"
        authority = args.host if port in (80, 443) else f"{args.host}:{port}"
        sub = f"{scheme}://{authority}{path}/sub"
        print("\n📋 لینک کانفیگ (کپی کن توی Hiddify / v2rayNG):")
        print(link)
        print("\n🔗 لینک سابسکریپشن:")
        print(sub)
        print("\n📄 صفحه کانفیگ:")
        print(f"{scheme}://{authority}{path}/")
        print("\n🧪 تست سریع:", f"curl {scheme}://{authority}/health")
    else:
        print("\nℹ️ بعد از دیپلو، دوباره اجرا کن با --host <آدرس سرورت> تا لینک کانفیگ بگیری.")
    print("\n⚠️ این مقادیر رمز تو هستند؛ توی گیت، چت یا اسکرینشات نذار.\n")


if __name__ == "__main__":
    main()
