#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
تست انتها به انتهای رله VPN — بدون هیچ وابستگی خارجی.

    cd vpn && python3 tests/test_relay.py

چه چیزهایی تست میشود:
  1. /health و صفحه کانفیگ و لینک سابسکریپشن
  2. WebSocket خام + هدر VLESS -> اکو (TCP)
  3. early data (0-RTT) از طریق Sec-WebSocket-Protocol
  4. رد شدن UUID اشتباه
  5. جلوگیری از SSRF (اتصال به IP خصوصی ممنوع است مگر حالت تست)
  6. مسیر کامل: SOCKS5 -> client.py -> WebSocket -> server.py -> مقصد
"""
from __future__ import annotations

import base64
import os
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from wsproto import ByteReader, read_frame, send_frame  # noqa: E402

UUID = str(uuid.uuid4())
TOKEN = "test-token-" + uuid.uuid4().hex[:10]
PASS = []


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start_echo(port: int):
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(16)

    def handle(c):
        with c:
            c.settimeout(10)
            while True:
                try:
                    data = c.recv(4096)
                except OSError:
                    return
                if not data:
                    return
                c.sendall(data)

    def loop():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=handle, args=(c,), daemon=True).start()

    threading.Thread(target=loop, daemon=True).start()
    return srv


def wait_port(port: int, timeout=15) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            s = socket.create_connection(("127.0.0.1", port), 0.3)
            s.close()
            return True
        except OSError:
            time.sleep(0.15)
    return False


def vless_request(uuid_bytes: bytes, host: str, port: int, payload: bytes) -> bytes:
    return (b"\x00" + uuid_bytes + b"\x00\x01" + struct.pack("!H", port) +
            b"\x01" + socket.inet_aton(host) + payload)


def ws_open(port: int, token: str, early: bytes | None = None):
    s = socket.create_connection(("127.0.0.1", port), 5)
    s.settimeout(6)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    lines = [f"GET /{token} HTTP/1.1", f"Host: 127.0.0.1:{port}",
             "Upgrade: websocket", "Connection: Upgrade",
             f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"]
    if early is not None:
        lines.append("Sec-WebSocket-Protocol: " +
                     base64.urlsafe_b64encode(early).decode("ascii").rstrip("="))
    s.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("ascii"))
    reader = ByteReader(s)
    head = bytearray()
    while b"\r\n\r\n" not in head:
        head.extend(reader.read(1))
    if b" 101 " not in bytes(head).split(b"\r\n")[0]:
        raise AssertionError("WS handshake failed: " + bytes(head).decode("latin-1")[:200])
    return s, reader


def collect(reader: ByteReader, want: int, timeout=6) -> bytes:
    out = bytearray()
    end = time.time() + timeout
    while len(out) < want and time.time() < end:
        try:
            opcode, payload = read_frame(reader)
        except (socket.timeout, OSError, ValueError):
            break
        if opcode == 0x8:
            break
        if opcode in (0x1, 0x2, 0x0):
            out.extend(payload)
    return bytes(out)


def main():
    relay_port, echo_port, socks_port = free_port(), free_port(), free_port()
    echo = start_echo(echo_port)
    env = os.environ.copy()
    env.update({
        "PORT": str(relay_port), "VPN_UUID": UUID, "VPN_TOKEN": TOKEN,
        "PUBLIC_HOST": "127.0.0.1", "VPN_PUBLIC_SCHEME": "http",
        "VPN_PUBLIC_PORT": str(relay_port), "VPN_ALLOW_PRIVATE": "1",
        "VPN_IDLE_TIMEOUT": "30", "PYTHONUNBUFFERED": "1",
    })
    server = subprocess.Popen([sys.executable, str(BASE / "server.py")],
                              cwd=str(BASE), env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    client = None
    try:
        assert wait_port(relay_port), "relay server did not start"
        base = f"http://127.0.0.1:{relay_port}"

        # 1) HTTP routes
        with urllib.request.urlopen(base + "/health", timeout=5) as r:
            assert r.status == 200 and b'"ok": true' in r.read()
        with urllib.request.urlopen(base + f"/{TOKEN}/", timeout=5) as r:
            page = r.read().decode("utf-8")
            assert "vless://" in page and UUID in page
        with urllib.request.urlopen(base + f"/{TOKEN}/sub", timeout=5) as r:
            sub = base64.b64decode(r.read()).decode()
            assert sub.startswith("vless://") and UUID in sub and TOKEN in sub
        PASS.append("1. /health + صفحه کانفیگ + سابسکریپشن")

        # 2) WebSocket خام + VLESS (TCP) -> اکو
        s, reader = ws_open(relay_port, TOKEN)
        lock = threading.Lock()
        req = vless_request(uuid.UUID(UUID).bytes, "127.0.0.1", echo_port, b"hello-vpn")
        send_frame(s, lock, 0x2, req, mask=True)
        data = collect(reader, 2 + len(b"hello-vpn"))
        assert data.startswith(b"\x00\x00"), f"bad VLESS response: {data[:20]!r}"
        assert b"hello-vpn" in data, f"echo missing: {data[:80]!r}"
        s.close()
        PASS.append("2. WebSocket + هدر VLESS + رله TCP (اکو)")

        # 3) early data (0-RTT)
        s2, reader2 = ws_open(relay_port, TOKEN, early=req)
        data2 = collect(reader2, 2 + len(b"hello-vpn"))
        assert data2.startswith(b"\x00\x00") and b"hello-vpn" in data2, repr(data2[:80])
        s2.close()
        PASS.append("3. early data (Sec-WebSocket-Protocol / 0-RTT)")

        # 4) UUID اشتباه نباید رله شود
        s3, reader3 = ws_open(relay_port, TOKEN)
        bad = vless_request(uuid.uuid4().bytes, "127.0.0.1", echo_port, b"hello-vpn")
        send_frame(s3, threading.Lock(), 0x2, bad, mask=True)
        data3 = collect(reader3, 999, timeout=3)
        assert b"hello-vpn" not in data3, "wrong UUID was relayed!"
        s3.close()
        PASS.append("4. رد شدن UUID نامعتبر")

        # 5) SSRF guard (با ماژول جداگانه، ALLOW_PRIVATE=0)
        os.environ.update({"VPN_UUID": UUID, "VPN_TOKEN": TOKEN, "VPN_ALLOW_PRIVATE": "0"})
        import server as relay_module  # noqa: E402
        try:
            relay_module.safe_connect("127.0.0.1", echo_port)
            raise AssertionError("SSRF guard did not block private IP")
        except ConnectionError:
            pass
        PASS.append("5. جلوگیری از SSRF (IP خصوصی بلاک شد)")

        # 6) مسیر کامل SOCKS5 -> client.py -> WS -> server.py -> اکو
        client = subprocess.Popen([sys.executable, str(BASE / "client.py"),
                                   "--host", "127.0.0.1", "--port", str(relay_port),
                                   "--token", TOKEN, "--uuid", UUID, "--no-tls",
                                   "--socks-port", str(socks_port)],
                                  cwd=str(BASE), env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        assert wait_port(socks_port, 12), "SOCKS5 client did not start"
        c = socket.create_connection(("127.0.0.1", socks_port), 5)
        c.settimeout(8)
        c.sendall(b"\x05\x01\x00")
        assert c.recv(2) == b"\x05\x00", "SOCKS5 greeting failed"
        c.sendall(b"\x05\x01\x00\x01" + socket.inet_aton("127.0.0.1") +
                  struct.pack("!H", echo_port))
        reply = c.recv(10)
        assert reply[:2] == b"\x05\x00", f"SOCKS5 CONNECT failed: {reply!r}"
        c.sendall(b"salam")
        assert c.recv(1024) == b"salam", "end-to-end SOCKS5 echo failed"
        c.close()
        PASS.append("6. مسیر کامل SOCKS5 → client.py → WebSocket → server → مقصد")

        print("\n" + "=" * 62)
        for line in PASS:
            print("✅ " + line)
        print("=" * 62 + "\nهمه تستها پاس شدند 🎉\n")
        return 0
    except Exception as exc:
        import traceback; traceback.print_exc()
        print("\n❌ TEST FAILED:", type(exc).__name__, exc, file=sys.stderr)
        for proc, name in ((server, "server"), (client, "client")):
            if proc and proc.poll() is None:
                proc.terminate()
            if proc:
                try:
                    out = proc.communicate(timeout=3)[0] or ""
                    print(f"--- {name} log ---\n{out[-3000:]}", file=sys.stderr)
                except subprocess.TimeoutExpired:
                    proc.kill()
        return 1
    finally:
        echo.close()
        if client and client.poll() is None:
            client.terminate()
        if server.poll() is None:
            server.terminate()


if __name__ == "__main__":
    sys.exit(main())
