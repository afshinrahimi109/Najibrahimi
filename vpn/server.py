#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🐠 vpn/server.py — «ویپیان از صفر»
================================================================
یک رله VLESS روی WebSocket که از صفر و فقط با کتابخانه استاندارد پایتون
نوشته شده است. هیچ pip install، هیچ پنل، هیچ باینری خارجی لازم نیست.

روی هر هاست رایگانی که پورت HTTP و WebSocket بدهد اجرا میشود
(پیشنهاد: Render پلن Free — بدون کارت بانکی، آدرس ثابت *.onrender.com).

متغیرهای محیطی:
  PORT              پورت (پیشفرض 8000)
  VPN_UUID          UUID مشتری (اجباری؛ با gen_config.py بساز)
  VPN_TOKEN         راز مسیر WebSocket (اجباری؛ با gen_config.py بساز)
  PUBLIC_HOST       هاست عمومی اختیاری (مثلاً my-vpn.onrender.com)
  VPN_PUBLIC_SCHEME http | https   (پیشفرض https)
  VPN_PUBLIC_PORT   پورت لینک کانفیگ (پیشفرض 443 برای https)
  VPN_ALLOW_PRIVATE 1 = اجازه اتصال به IP خصوصی (فقط برای تست محلی!)
  VPN_IDLE_TIMEOUT  ثانیه تا پینگ نگهدارنده (پیشفرض 60)
  VPN_MAX_CONN      حداکثر اتصال همزمان (پیشفرض 32)

مسیرها:
  /health                 وضعیت سرویس
  /<TOKEN>/              صفحه کانفیگ (لینک vless:// را نشان میدهد)
  /<TOKEN>/sub           سابسکریپشن base64
  /<TOKEN>               WebSocket (مسیر VLESS)

امنیت: مسیر تصادفی + UUID + بررسی SSRF (جلوگیری از دسترسی به شبکه داخلی هاست).
"""
from __future__ import annotations

import base64
import hmac
import html
import ipaddress
import json
import os
import socket
import socketserver
import struct
import sys
import threading
import time
import uuid as uuidlib
from urllib.parse import urlsplit

from wsproto import ByteReader, accept_key, frame_bytes, read_frame, send_frame

# ------------------------------------------------------------------ پیکربندی
PORT = int(os.environ.get("PORT", "8000"))
TOKEN = os.environ.get("VPN_TOKEN", "").strip()
UUID_STR = os.environ.get("VPN_UUID", "").strip()
PUBLIC_HOST = os.environ.get("PUBLIC_HOST", "").strip()
PUBLIC_SCHEME = os.environ.get("VPN_PUBLIC_SCHEME", "https").strip().lower()
PUBLIC_PORT = int(os.environ.get("VPN_PUBLIC_PORT", "443" if PUBLIC_SCHEME == "https" else str(PORT)))
ALLOW_PRIVATE = os.environ.get("VPN_ALLOW_PRIVATE", "").strip() == "1"
IDLE_TIMEOUT = max(10, int(os.environ.get("VPN_IDLE_TIMEOUT", "60")))
MAX_CONN = max(1, int(os.environ.get("VPN_MAX_CONN", "32")))

if not TOKEN:
    sys.exit("❌ VPN_TOKEN تنظیم نشده. اول اجرا کن: python3 gen_config.py")
if not UUID_STR:
    UUID_STR = str(uuidlib.uuid4())
    print(f"⚠️ VPN_UUID تنظیم نشده؛ یکی موقت ساخته شد: {UUID_STR}", flush=True)
    print("   حتماً آن را در تنظیمات هاست ذخیره کن وگرنه با ریاستارت عوض میشود.", flush=True)
try:
    UUID_BYTES = uuidlib.UUID(UUID_STR).bytes
except ValueError:
    sys.exit("❌ VPN_UUID معتبر نیست (باید فرم 8-4-4-4-12 داشته باشد).")

WS_PATH = "/" + TOKEN
_active = 0
_active_lock = threading.Lock()


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ------------------------------------------------------------------ HTTP ساده
def http_reply(sock, status: int, body: bytes, ctype="text/plain; charset=utf-8") -> None:
    reason = {200: "OK", 400: "Bad Request", 404: "Not Found",
              429: "Too Many Requests", 500: "Internal Server Error"}.get(status, "OK")
    head = (f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: {ctype}\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Cache-Control: no-store\r\n"
            f"Connection: close\r\n\r\n")
    sock.sendall(head.encode("ascii") + body)


def host_of(headers: dict) -> str:
    if PUBLIC_HOST:
        return PUBLIC_HOST
    return headers.get("host", f"127.0.0.1:{PORT}").split(",")[0].strip()


def vless_link(host: str) -> str:
    """لینک استاندارد vless:// برای اپهای اندروید (v2rayNG / Hiddify / NekoBox)."""
    from urllib.parse import quote
    params = ["encryption=none", "type=ws", f"host={quote(host, safe='')}",
              f"path={quote(WS_PATH, safe='')}"]
    if PUBLIC_SCHEME == "https":
        params += ["security=tls", f"sni={quote(host, safe='')}", "fp=chrome"]
    else:
        params.append("security=none")
    query = "&".join(params)
    return f"vless://{UUID_STR}@{host}:{PUBLIC_PORT}?{query}#FreeVPN"


def config_page(host: str) -> bytes:
    link = vless_link(host)
    sub = f"{PUBLIC_SCHEME}://{host}/{TOKEN}/sub"
    safe_link = html.escape(link)
    return f"""<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>کانفیگ VPN</title>
<style>body{{font-family:Tahoma,Arial,sans-serif;max-width:760px;margin:40px auto;padding:0 18px;line-height:1.9;background:#0d1117;color:#e6edf3}}
pre{{background:#161b22;padding:14px;border-radius:10px;overflow-x:auto;direction:ltr;text-align:left;color:#7ee787}}
code{{background:#161b22;padding:2px 6px;border-radius:5px}} .w{{background:#3d2a12;padding:12px;border-radius:10px}}</style>
<h1>🔐 کانفیگ VPN شخصی تو</h1>
<p>این صفحه خصوصی است؛ لینک زیر را برای هیچکس نفرست (هم رمز مسیر و هم UUID داخلش است).</p>
<h3>۱) لینک کانفیگ (کپی کن)</h3><pre>{safe_link}</pre>
<h3>۲) لینک سابسکریپشن</h3><pre>{html.escape(sub)}</pre>
<h3>۳) روی اندروید</h3>
<p>اپ <b>Hiddify Next</b> یا <b>v2rayNG</b> را نصب کن ← دکمه <b>+</b> ←
«وارد کردن از کلیپبورد» / «Import from clipboard» ← لینک بالا را پیست کن ← وصل شو.</p>
<p class="w">⚠️ پلن رایگان هاست بعد از ۱۵ دقیقه بیکاری میخوابد؛ بار اول حدود ۱ دقیقه طول
میکشد بیدار شود. ترافیک رایگان هم محدود است — برای مصرف شخصی سبک مناسب است.</p>
</html>""".encode("utf-8")


# ------------------------------------------------------------------ VLESS
def parse_vless(data: bytes, expected: bytes):
    """پارس هدر VLESS. None یعنی داده کافی نیست؛ ValueError یعنی درخواست نامعتبر."""
    if len(data) < 18:
        return None
    version = data[0]
    if version != 0:
        raise ValueError("bad VLESS version")
    if not hmac.compare_digest(data[1:17], expected):
        raise ValueError("invalid UUID")
    addon_len = data[17]
    idx = 18 + addon_len
    if len(data) < idx + 4:
        return None
    command = data[idx]
    idx += 1
    port = struct.unpack("!H", data[idx:idx + 2])[0]
    idx += 2
    atype = data[idx]
    idx += 1
    if atype == 1:
        need = 4
    elif atype == 2:
        if len(data) < idx + 1:
            return None
        need = data[idx] + 1
    elif atype == 3:
        need = 16
    else:
        raise ValueError("bad address type")
    if len(data) < idx + need:
        return None
    if atype == 1:
        host = ".".join(str(b) for b in data[idx:idx + 4])
    elif atype == 2:
        n = data[idx]
        host = data[idx + 1:idx + 1 + n].decode("ascii", "replace")
    else:
        host = socket.inet_ntop(socket.AF_INET6, data[idx:idx + 16])
    idx += need
    return {"version": version, "command": command, "host": host,
            "port": port, "payload": data[idx:]}


def safe_connect(host: str, port: int):
    """اتصال TCP با جلوگیری از SSRF: فقط IP عمومی (مگر در حالت تست)."""
    if not (1 <= port <= 65535) or not host:
        raise ValueError("invalid target")
    infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    last = None
    for fam, typ, proto, _canon, addr in infos:
        try:
            ip = ipaddress.ip_address(addr[0])
        except ValueError:
            continue
        if not ALLOW_PRIVATE and not ip.is_global:
            continue  # loopback / private / link-local / multicast / reserved
        s = socket.socket(fam, typ, proto)
        s.settimeout(10)
        try:
            s.connect(addr)
            s.settimeout(None)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            return s
        except OSError as exc:
            last = exc
            s.close()
    raise ConnectionError(f"cannot reach {host}:{port} ({last})")


# ------------------------------------------------------------------ هندلر
class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        sock = self.request
        sock.settimeout(20)
        try:
            raw = b""
            while b"\r\n\r\n" not in raw and len(raw) < 65536:
                chunk = sock.recv(4096)
                if not chunk:
                    return
                raw += chunk
            head, _, rest = raw.partition(b"\r\n\r\n")
            lines = head.split(b"\r\n")
            parts = lines[0].decode("latin-1").split(" ")
            if len(parts) < 2:
                return
            method, target = parts[0], parts[1]
            headers = {}
            for line in lines[1:]:
                key, _, value = line.partition(b":")
                headers[key.strip().lower().decode("latin-1")] = value.strip().decode("latin-1")
            path = urlsplit(target).path.rstrip("/") or "/"
            host = host_of(headers)

            if path == "/health":
                return http_reply(sock, 200, json.dumps(
                    {"ok": True, "service": "vless-ws-relay", "time": int(time.time())}
                ).encode(), "application/json")
            if path == "/":
                return http_reply(sock, 200,
                                  b"Diana Free VPN relay - use /<TOKEN>/ for your config",
                                  "text/plain; charset=utf-8")
            if path == WS_PATH + "/sub":
                sub = base64.b64encode((vless_link(host) + "\n").encode()).decode()
                return http_reply(sock, 200, sub.encode("ascii"))
            if path != WS_PATH:
                return http_reply(sock, 404, b"Not found")

            if headers.get("upgrade", "").lower() != "websocket":
                return http_reply(sock, 200, config_page(host), "text/html; charset=utf-8")

            reader = ByteReader(sock, rest)
            self.handle_ws(reader, headers)
        except (socket.timeout, ConnectionError, OSError, ValueError) as exc:
            log(f"conn closed: {type(exc).__name__}: {exc}")
        except Exception as exc:  # یک اتصال خراب نباید سرور را بکشد
            log(f"unexpected error: {type(exc).__name__}: {exc}")

    def handle_ws(self, reader: ByteReader, headers: dict):
        global _active
        sock = self.request
        key = headers.get("sec-websocket-key", "").strip()
        subproto = headers.get("sec-websocket-protocol", "").split(",")[0].strip()
        if not key:
            return http_reply(sock, 400, b"missing Sec-WebSocket-Key")
        with _active_lock:
            if _active >= MAX_CONN:
                return http_reply(sock, 429, b"too many connections")
            _active += 1

        remote = None
        stop = threading.Event()
        send_lock = threading.Lock()
        buf = bytearray()
        stats = {"up": 0, "down": 0}
        try:
            lines = ["HTTP/1.1 101 Switching Protocols", "Upgrade: websocket",
                     "Connection: Upgrade", f"Sec-WebSocket-Accept: {accept_key(key)}"]
            if subproto:
                lines.append(f"Sec-WebSocket-Protocol: {subproto}")
            sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
            sock.settimeout(IDLE_TIMEOUT)

            # 0-RTT / Early data: بسته اول VLESS به صورت base64 در هدر Sec-WebSocket-Protocol
            # آمده است. آن را بهصورت یک فریم باینری مصنوعی جلوی جریان WS میگذاریم
            # تا حلقه اصلی همانطور که بقیه فریمها را پردازش میکند، آن را هم بگیرد.
            if subproto:
                try:
                    early = base64.urlsafe_b64decode(subproto + "=" * (-len(subproto) % 4))
                    if early and early[0] == 0 and len(early) >= 18:
                        reader.prepend(frame_bytes(0x2, early))
                except Exception:
                    pass

            def pump_remote():
                while not stop.is_set() and remote is not None:
                    try:
                        data = remote.recv(32768)
                    except OSError:
                        break
                    if not data:
                        break
                    try:
                        send_frame(sock, send_lock, 0x2, data)
                        stats["down"] += len(data)
                    except OSError:
                        break
                stop.set()

            while not stop.is_set():
                try:
                    opcode, payload = read_frame(reader)
                except socket.timeout:
                    # پینگ نگهدارنده: هم اتصال را زنده نگه میدارد هم هاست رایگان را بیدار
                    try:
                        send_frame(sock, send_lock, 0x9, b"")
                    except OSError:
                        break
                    continue
                if opcode == 0x8:
                    break
                if opcode == 0x9:
                    send_frame(sock, send_lock, 0xA, payload)
                    continue
                if opcode == 0xA:
                    continue
                if opcode not in (0x1, 0x2, 0x0):
                    continue
                buf.extend(payload)
                if remote is None:
                    try:
                        info = parse_vless(bytes(buf), UUID_BYTES)
                    except ValueError as exc:
                        log(f"reject: {exc}")
                        break
                    if info is None:
                        continue  # هدر ناقص است؛ فریم بعدی
                    if info["command"] != 1:
                        log(f"unsupported VLESS command: {info['command']} (only TCP)")
                        break
                    try:
                        remote = safe_connect(info["host"], info["port"])
                    except Exception as exc:
                        log(f"connect failed: {exc}")
                        break
                    log(f"connect -> {info['host']}:{info['port']}")
                    send_frame(sock, send_lock, 0x2, bytes((info["version"], 0)))
                    threading.Thread(target=pump_remote, daemon=True).start()
                    if info["payload"]:
                        remote.sendall(info["payload"])
                        stats["up"] += len(info["payload"])
                    buf.clear()
                else:
                    remote.sendall(payload)
                    stats["up"] += len(payload)
        finally:
            stop.set()
            if remote is not None:
                try:
                    remote.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                remote.close()
            try:
                send_frame(sock, send_lock, 0x8, b"")
            except OSError:
                pass
            with _active_lock:
                _active -= 1
            log(f"closed (up={stats['up']}B down={stats['down']}B)")


class RelayServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    server = RelayServer(("0.0.0.0", PORT), Handler)
    print("=" * 60, flush=True)
    print(f"🔐 رله VLESS/WebSocket | پورت {PORT} | مسیر {WS_PATH}", flush=True)
    print(f"🌐 هاست عمومی: {PUBLIC_HOST or '(از هدر Host خوانده میشود)'}", flush=True)
    print(f"🔒 جلوگیری از SSRF: {'غیرفعال (تست)' if ALLOW_PRIVATE else 'فعال'}", flush=True)
    print("=" * 60, flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
