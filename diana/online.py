#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🐠 online.py — «آدرس ثابت رایگان» + اتصال همیشگی دیانا
================================================================
بدون هیچ کتابخانه‌ی اضافی (فقط stdlib پایتون) و روی ترموکس، لینوکس،
مک و ویندوز اجرا می‌شود.

کاری که می‌کند:
  1. سرور دیانا (server.py) را بالا می‌آورد و اگر خوابید دوباره بیدارش می‌کند.
  2. یک تونل رایگان (ngrok / Cloudflare / Tailscale) روی آن می‌سازد و در صورت
     قطع شدن اینترنت، خودکار دوباره وصل می‌شود.
  3. آدرس عمومی را چاپ می‌کند و در data/public-url.txt ذخیره می‌کند.
  4. به صورت خودکار یک رمز تصادفی (DIANA_TOKEN) می‌سازد تا وقتی دیانا
     در اینترنت باز است، هر کسی نتواند از ۱۲۰ ایجنت و ابزارهایش استفاده کند.

استفاده:
    python3 online.py                # شروع (همه چیز خودکار)
    python3 online.py --setup        # ساخت .env + نصب پیشنیازها روی ترموکس
    python3 online.py --show         # نمایش آدرس و رمز فعلی
    python3 online.py --provider ngrok
    python3 online.py --no-server    # اگر سرور را جای دیگری اجرا کرده‌ای

راهنمای کامل: STATIC-IP.md
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
ENV_FILE = BASE / ".env"
ENV_EXAMPLE = BASE / ".env.example"
DATA_DIR = BASE / "data"
URL_FILE = DATA_DIR / "public-url.txt"
TUNNEL_LOG = DATA_DIR / "tunnel.log"

PROVIDERS = ("auto", "ngrok", "cloudflared", "cloudflare-named", "tailscale", "none")
NGROK_HOST = re.compile(r"https://[A-Za-z0-9._-]+\.ngrok(?:-free)?\.(?:app|dev|io|pizza)")
CLOUDFLARE_HOST = re.compile(r"https://[A-Za-z0-9-]+\.trycloudflare\.com")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ------------------------------------------------------------------ پیکربندی
def read_env_file(path: Path) -> dict:
    cfg = {}
    if not path.exists():
        return cfg
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        cfg[key.strip()] = value
    return cfg


def load_config(args) -> dict:
    cfg = read_env_file(ENV_FILE)
    # متغیرهای محیطی همیشه بر فایل .env اولویت دارند (مناسب Render/Docker)
    for key in ("TUNNEL", "PORT", "DIANA_USER", "DIANA_TOKEN", "NGROK_DOMAIN",
                "NGROK_AUTHTOKEN", "CF_TUNNEL_TOKEN", "CF_ALLOWED_MAIL", "PUBLIC_URL"):
        if key in os.environ:
            cfg[key] = os.environ[key]
    cfg.setdefault("PORT", "8000")
    cfg.setdefault("TUNNEL", "auto")
    cfg.setdefault("DIANA_USER", "diana")
    if args.provider:
        cfg["TUNNEL"] = args.provider
    if args.port:
        cfg["PORT"] = str(args.port)
    # فاصله اضافی اطراف مقادیر (مخصوصاً رمز) باعث 401 شدن نمیشود
    return {k: v.strip() if isinstance(v, str) else v for k, v in cfg.items()}


ENV_TEMPLATE = """# 🔒 تنظیمات خصوصی دیانا — این فایل در گیت ذخیره نمی‌شود (.gitignore)
# ساخته‌شده توسط online.py. راهنما: STATIC-IP.md

# کدام تونل؟ auto | ngrok | cloudflared | cloudflare-named | tailscale | none
TUNNEL={tunnel}
PORT={port}

# رمز دسترسی به دیانا در حالت آنلاین (HTTP Basic Auth)
DIANA_USER={user}
DIANA_TOKEN={token}

# --- ngrok (پیشنهادی: دامنه‌ی ثابت رایگان) ---
# توکن را از dashboard.ngrok.com → Your Authtoken بگیر
NGROK_AUTHTOKEN=
# دامنه‌ی ثابت رایگان حسابت، مثلاً abc123.ngrok-free.dev
# اگر خالی بگذاری، ngrok به طور خودکار همان دامنه‌ی ثابت را استفاده می‌کند
NGROK_DOMAIN=

# --- Cloudflare Tunnel نامدار (اگر دامنه داری) ---
CF_TUNNEL_TOKEN=
PUBLIC_URL=

# --- Quick Tunnel موقت ایمیل مجاز (اختیاری) ---
CF_ALLOWED_MAIL=
"""


def ensure_env(cfg: dict) -> None:
    if ENV_FILE.exists():
        return
    token = secrets.token_urlsafe(18)
    ENV_FILE.write_text(ENV_TEMPLATE.format(
        tunnel=cfg.get("TUNNEL", "auto"),
        port=cfg.get("PORT", "8000"),
        user=cfg.get("DIANA_USER", "diana"),
        token=token,
    ), encoding="utf-8")
    try:
        os.chmod(ENV_FILE, 0o600)
    except OSError:
        pass
    cfg["DIANA_TOKEN"] = token
    log(f"فایل .env ساخته شد و یک رمز تصادفی در آن ذخیره شد: {ENV_FILE}")


def choose_provider(cfg: dict) -> str:
    provider = (cfg.get("TUNNEL") or "auto").strip().lower()
    if provider != "auto":
        return provider if provider in PROVIDERS else "none"
    if cfg.get("CF_TUNNEL_TOKEN") and shutil.which("cloudflared"):
        return "cloudflare-named"
    if shutil.which("ngrok"):
        return "ngrok"
    if shutil.which("cloudflared"):
        return "cloudflared"
    log("⚠️ نه ngrok و نه cloudflared پیدا نشد. فعلاً فقط محلی در دسترس است.")
    log("   python3 online.py --setup  را اجرا کن تا پیشنیازها نصب شوند.")
    return "none"


def is_termux() -> bool:
    return "com.termux" in os.environ.get("PREFIX", "")


# ------------------------------------------------------------------ ابزارها
def popen_kwargs() -> dict:
    if os.name == "posix":
        return {"start_new_session": True}
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {}


def stop_proc(proc) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=6)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def auth_header(cfg: dict) -> str:
    raw = f"{cfg.get('DIANA_USER', 'diana')}:{cfg.get('DIANA_TOKEN', '')}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def local_ok(cfg: dict, timeout: float = 2.0) -> bool:
    url = f"http://127.0.0.1:{cfg['PORT']}/api/status"
    req = urllib.request.Request(url, headers={"Authorization": auth_header(cfg)})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def start_server(cfg: dict):
    env = os.environ.copy()
    env["PORT"] = str(cfg["PORT"])
    env["PYTHONUNBUFFERED"] = "1"
    env["DIANA_USER"] = cfg.get("DIANA_USER", "diana")
    env["DIANA_TOKEN"] = cfg.get("DIANA_TOKEN", "")
    log("🐠 در حال اجرای سرور دیانا...")
    return subprocess.Popen([sys.executable, str(BASE / "server.py")],
                            cwd=str(BASE), env=env, **popen_kwargs())


def wait_for_server(cfg: dict, seconds: int = 20) -> bool:
    for _ in range(seconds * 2):
        if local_ok(cfg):
            return True
        time.sleep(0.5)
    return False


# ------------------------------------------------------------------ تونل‌ها
def ngrok_add_token(cfg: dict) -> None:
    token = (cfg.get("NGROK_AUTHTOKEN") or "").strip()
    if not token or not shutil.which("ngrok"):
        return
    result = subprocess.run(["ngrok", "config", "add-authtoken", token],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode == 0:
        log("🔑 توکن ngrok تنظیم شد.")
    else:
        log("⚠️ تنظیم توکن ngrok ناموفق بود. دستی اجرا کن: ngrok config add-authtoken <TOKEN>")


def tunnel_command(provider: str, cfg: dict):
    port = str(cfg["PORT"])
    if provider == "ngrok":
        cmd = ["ngrok", "http", port]
        domain = (cfg.get("NGROK_DOMAIN") or "").strip()
        if domain:
            if not domain.startswith("http://") and not domain.startswith("https://"):
                domain = "https://" + domain
            cmd += ["--url", domain]
        return cmd
    if provider == "cloudflared":
        cmd = ["cloudflared", "tunnel", "--no-autoupdate",
               "--url", f"http://localhost:{port}"]
        mail = (cfg.get("CF_ALLOWED_MAIL") or "").strip()
        if mail:
            cmd += ["--allowed-mail", mail]
        return cmd
    if provider == "cloudflare-named":
        token = (cfg.get("CF_TUNNEL_TOKEN") or "").strip()
        if not token:
            log("❌ برای cloudflare-named باید CF_TUNNEL_TOKEN را در .env بگذاری.")
            return None
        return ["cloudflared", "tunnel", "--no-autoupdate", "run", "--token", token]
    return None  # tailscale / none تونل جداگانه‌ای ندارند


def start_tunnel(provider: str, cfg: dict):
    cmd = tunnel_command(provider, cfg)
    if cmd is None:
        return None
    binary = cmd[0]
    if not shutil.which(binary):
        log(f"⚠️ برنامه‌ی {binary} پیدا نشد. تونل اجرا نمی‌شود.")
        log("   python3 online.py --setup  را اجرا کن.")
        return None
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log(f"🌐 اجرای تونل: {binary}")
    # لاگ تازه برای هر بار وصل شدن تا آدرس قدیمی دوباره اعلام نشود
    logfile = open(TUNNEL_LOG, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(cmd, cwd=str(BASE), stdout=logfile,
                            stderr=subprocess.STDOUT, **popen_kwargs())
    proc._logfile = logfile  # جلوگیری از بسته شدن زودهنگام فایل لاگ
    return proc


def log_tail(n: int = 120) -> str:
    try:
        lines = TUNNEL_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except OSError:
        return ""


def tailscale_url(cfg: dict) -> str:
    if shutil.which("tailscale"):
        try:
            out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True,
                                 text=True, timeout=8)
            ip = (out.stdout or "").strip().splitlines()
            if ip and re.match(r"^100\.\d+\.\d+\.\d+$", ip[0].strip()):
                return f"http://{ip[0].strip()}:{cfg['PORT']}"
        except Exception:
            pass
    return (cfg.get("PUBLIC_URL") or "").strip()


def discover_url(provider: str, cfg: dict) -> str:
    fixed = (cfg.get("PUBLIC_URL") or "").strip()
    if provider == "ngrok":
        # رابط محلی ngrok معتبرترین منبع آدرس است
        try:
            with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=2) as resp:
                data = json.load(resp)
            for tunnel in data.get("tunnels", []):
                url = tunnel.get("public_url", "")
                if url.startswith("https://"):
                    return url
        except Exception:
            pass
        found = NGROK_HOST.findall(log_tail())
        if found:
            return found[-1]
        domain = (cfg.get("NGROK_DOMAIN") or "").strip()
        if domain:
            return domain if domain.startswith("http") else "https://" + domain
        return ""
    if provider == "cloudflared":
        found = CLOUDFLARE_HOST.findall(log_tail())
        return found[-1] if found else ""
    if provider == "cloudflare-named":
        return fixed
    if provider == "tailscale":
        return tailscale_url(cfg)
    return f"http://127.0.0.1:{cfg['PORT']}"


def announce(url: str, provider: str, cfg: dict) -> None:
    stable = provider in ("ngrok", "cloudflare-named", "tailscale")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    URL_FILE.write_text(url + "\n", encoding="utf-8")
    print("\n" + "=" * 62, flush=True)
    label = "ثابت" if stable else ("محلی" if provider == "none" else "موقت")
    print(f"🌐 آدرس {label} دیانا:  {url}", flush=True)
    print(f"🔒 نام کاربری: {cfg.get('DIANA_USER', 'diana')}", flush=True)
    print(f"🔑 رمز:        {cfg.get('DIANA_TOKEN', '(بدون رمز!)')}", flush=True)
    print(f"📄 ذخیره شد در: {URL_FILE.relative_to(BASE)}", flush=True)
    if provider == "ngrok":
        print("ℹ️ پلن رایگان ngrok یک صفحه‌ی هشدار نشان می‌دهد؛ یک بار «Visit Site» را بزن.", flush=True)
        print("ℹ️ محدودیت رایگان: ۱ گیگابایت ترافیک و ۲۰٬۰۰۰ درخواست در ماه.", flush=True)
    elif provider == "cloudflared":
        print("⚠️ Quick Tunnel موقتی است: با هر وصل مجدد آدرس عوض می‌شود و SSE پشتیبانی", flush=True)
        print("   نمی‌شود. برای آدرس واقعاً ثابت، ngrok یا Cloudflare نامدار را انتخاب کن.", flush=True)
    elif provider == "tailscale":
        print("ℹ️ فقط دستگاه‌هایی که با همان اکانت Tailscale وارد شده‌اند این IP را می‌بینند.", flush=True)
    elif provider == "cloudflare-named":
        print("ℹ️ آدرس ثابت است؛ PUBLIC_URL را در .env تنظیم کن تا اینجا نمایش داده شود.", flush=True)
    print("=" * 62 + "\n", flush=True)


# ------------------------------------------------------------------ حالت‌ها
def setup(cfg: dict, provider: str) -> None:
    ensure_env(cfg)
    cfg.update({k: v for k, v in read_env_file(ENV_FILE).items() if k not in cfg})
    print("\n✅ فایل تنظیمات:", ENV_FILE)
    print(f"   نام کاربری: {cfg.get('DIANA_USER', 'diana')}")
    print(f"   رمز:        {cfg.get('DIANA_TOKEN', '')}")
    print(f"   تونل:       {cfg.get('TUNNEL', 'auto')}")
    if is_termux() and not shutil.which("cloudflared") and not shutil.which("ngrok"):
        log("هیچ تونلی نصب نیست؛ cloudflared را از مخازن ترموکس نصب میکنم...")
        subprocess.run(["pkg", "install", "cloudflared", "-y"])
        log("برای آدرس واقعاً ثابت، طبق STATIC-IP.md نسخه ngrok را هم نصب کن.")
    print("\nقدم بعدی:")
    print("  • ngrok می‌خواهی؟  دستورهای نصبش هست: STATIC-IP.md (بخش «نگروک»)")
    print("  • بعد از نصب تونل:  python3 online.py")
    print("  • نمایش آدرس/رمز:  python3 online.py --show\n")


def show(cfg: dict) -> None:
    print("تنظیمات:", ENV_FILE if ENV_FILE.exists() else "(فایلی نیست — اول --setup را اجرا کن)")
    print(f"  تونل:       {cfg.get('TUNNEL', 'auto')}")
    print(f"  پورت:       {cfg.get('PORT', '8000')}")
    print(f"  نام کاربری: {cfg.get('DIANA_USER', 'diana')}")
    print(f"  رمز:        {cfg.get('DIANA_TOKEN', '(ندارد)')}")
    if URL_FILE.exists():
        print(f"  آخرین آدرس: {URL_FILE.read_text(encoding='utf-8').strip()}")
    if local_ok(cfg):
        print("  وضعیت سرور: ✅ در حال اجرا")
    else:
        print("  وضعیت سرور: ⏹ خاموش (python3 online.py)")


def run(cfg: dict, args) -> None:
    provider = choose_provider(cfg)
    cfg["TUNNEL"] = provider
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if provider == "ngrok":
        ngrok_add_token(cfg)
    if provider == "tailscale" and not (cfg.get("PUBLIC_URL") or "").strip() and not shutil.which("tailscale"):
        log("⚠️ tailscale پیدا نشد. آدرس را در PUBLIC_URL داخل .env بنویس.")
    if provider == "cloudflare-named" and not (cfg.get("PUBLIC_URL") or "").strip():
        log("ℹ️ آدرس ثابتت را در PUBLIC_URL داخل .env بنویس تا اینجا نمایش داده شود.")

    print("\n" + "=" * 62, flush=True)
    print(f"🐠 دیانا آنلاین | تونل: {provider} | پورت: {cfg['PORT']}", flush=True)
    print("=" * 62 + "\n", flush=True)

    stopping = {"now": False}

    def on_signal(_sig, _frame):
        stopping["now"] = True

    signal.signal(signal.SIGINT, on_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, on_signal)

    server_proc = None
    tunnel_proc = None
    try:
        if not args.no_server:
            if local_ok(cfg):
                log("سرور دیانا از قبل در حال اجراست؛ از همان استفاده می‌شود.")
            else:
                server_proc = start_server(cfg)
                if not wait_for_server(cfg):
                    log("❌ سرور دیانا بالا نیامد. خروجی server.py را بررسی کن.")
        tunnel_proc = start_tunnel(provider, cfg)

        last_url = ""
        last_check = 0.0
        backoff = 2
        tunnel_started_at = time.time()
        while not stopping["now"]:
            time.sleep(2)
            if server_proc is not None and server_proc.poll() is not None:
                log("⚠️ سرور دیانا خوابید؛ راه‌اندازی مجدد...")
                server_proc = start_server(cfg)
                wait_for_server(cfg)
            if tunnel_proc is not None and tunnel_proc.poll() is not None:
                log(f"⚠️ تونل قطع شد؛ {backoff} ثانیه دیگر دوباره وصل می‌شویم...")
                for line in log_tail(5).splitlines():
                    if line.strip():
                        log("   ↳ " + line.strip()[:180])
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
                tunnel_proc = start_tunnel(provider, cfg)
                tunnel_started_at = time.time()
                last_url = ""  # آدرس تازه را دوباره اعلام کن
            now = time.time()
            if now - last_check >= 12:
                last_check = now
                if tunnel_proc is not None and tunnel_proc.poll() is None and now - tunnel_started_at > 30:
                    backoff = 2
                if not args.no_server and not local_ok(cfg):
                    log("⚠️ سرور محلی پاسخ نمی‌دهد؛ راه‌اندازی مجدد...")
                    stop_proc(server_proc)
                    server_proc = start_server(cfg)
                    wait_for_server(cfg)
                url = discover_url(provider, cfg)
                if url and url != last_url:
                    announce(url, provider, cfg)
                    last_url = url
                elif not url and not last_url and provider in ("ngrok", "cloudflared"):
                    log("⏳ منتظر گرفتن آدرس از تونل...")
    finally:
        log("در حال خاموش کردن تونل و سرور...")
        stop_proc(tunnel_proc)
        stop_proc(server_proc)
        log("خداحافظ 👋")


def main() -> None:
    parser = argparse.ArgumentParser(description="آدرس ثابت رایگان و اتصال همیشگی دیانا")
    parser.add_argument("--provider", choices=PROVIDERS, help="نوع تونل (پیشفرض: auto)")
    parser.add_argument("--port", type=int, help="پورت محلی دیانا (پیشفرض: 8000)")
    parser.add_argument("--no-server", action="store_true", help="سرور را خودم جای دیگری اجرا کردهام")
    parser.add_argument("--setup", action="store_true", help="ساخت .env و نصب پیشنیازها")
    parser.add_argument("--show", action="store_true", help="نمایش آدرس و رمز فعلی")
    args = parser.parse_args()

    cfg = load_config(args)
    if args.setup:
        setup(cfg, choose_provider(cfg))
        return
    if args.show:
        show(cfg)
        return
    ensure_env(cfg)
    # مقادیری که تازه‌ام ساخته شدند را وارد پیکربندی کن
    fresh = read_env_file(ENV_FILE)
    for key, value in fresh.items():
        cfg.setdefault(key, value)
    if not cfg.get("DIANA_TOKEN"):
        cfg["DIANA_TOKEN"] = secrets.token_urlsafe(18)
        log("⚠️ DIANA_TOKEN خالی است؛ یک رمز موقت ساخته شد (در .env ذخیره نشد).")
    run(cfg, args)


if __name__ == "__main__":
    main()
