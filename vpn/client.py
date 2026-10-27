#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
vpn/client.py — کلاینت از صفر: SOCKS5 محلی -> تونل VLESS/WebSocket
================================================================
بدون هیچ کتابخانهای (فقط stdlib). روی ترموکس اندروید، لینوکس، مک و ویندوز
اجرا میشود. یک پروکسی SOCKS5 روی 127.0.0.1:1080 باز میکند؛
سپس با اپهایی مثل SocksDroid (که VpnService اندروید را میسازد) میتوانی
کل ترافیک گوشی را از تونل رد کنی — یعنی یک VPN کامل، ساختهشده از صفر.

نمونه:
  python3 client.py --host my-vpn.onrender.com --token TOKEN --uuid UUID
  # ترموکس: بگذار در پسزمینه بماند، بعد SocksDroid را به 127.0.0.1:1080 وصل کن

توجه: اگر اپ v2rayNG / Hiddify داری، اصلاً نیازی به این فایل نیست؛
      لینک vless:// صفحه /<TOKEN>/ را مستقیم ایمپورت کن.
"""
from __future__ import annotations

import argparse
import base64
import ipaddress
import os
import socket
import socketserver
import ssl
import struct
import sys
import threading
import uuid as uuidlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wsproto import ByteReader, read_frame, send_frame  # noqa: E402

UUID_BYTES = b""
CFG = {}


class WS:
    """یک اتصال WebSocket = یک جریان TCP داخل تونل."""

    def __init__(self, sock, reader):
        self.sock = sock
        self.reader = reader
        self.lock = threading.Lock()

    @classmethod
    def connect(cls, timeout=20):
        host, port = CFG["host"], CFG["port"]
        sock = socket.create_connection((host, port), timeout)
        if CFG["tls"]:
            ctx = ssl.create_default_context()
            sock = ctx.wrap_socket(sock, server_hostname=host)
        sock.settimeout(timeout)
        reader = ByteReader(sock)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        host_header = host if port in (80, 443) else f"{host}:{port}"
        request = (
            f"GET /{CFG['token']} HTTP/1.1\r\n"
            f"Host: {host_header}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(request.encode("ascii"))
        head = bytearray()
        while b"\r\n\r\n" not in head:
            head.extend(reader.read(1))
            if len(head) > 16384:
                raise ConnectionError("WS handshake response too large")
        first_line = bytes(head).split(b"\r\n")[0].decode("latin-1")
        if " 101 " not in first_line:
            raise ConnectionError(f"WS handshake failed: {first_line}")
        sock.settimeout(300)
        return cls(sock, reader)

    def send(self, data: bytes):
        send_frame(self.sock, self.lock, 0x2, data, mask=True)

    def recv(self) -> bytes:
        while True:
            opcode, payload = read_frame(self.reader)
            if opcode == 0x8:
                raise ConnectionError("websocket closed by server")
            if opcode == 0x9:
                send_frame(self.sock, self.lock, 0xA, payload, mask=True)
                continue
            if opcode == 0xA:
                continue
            if opcode in (0x1, 0x2, 0x0):
                return payload

    def close(self):
        try:
            send_frame(self.sock, self.lock, 0x8, b"", mask=True)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def vless_header(host: str, port: int, payload: bytes = b"") -> bytes:
    """ساخت هدر باینری VLESS (نسخه 0 + UUID + addon خالی + TCP)."""
    try:
        ip = ipaddress.ip_address(host)
        addr = (b"\x01" if ip.version == 4 else b"\x03") + ip.packed
    except ValueError:
        raw = host.encode("idna")
        if not raw or len(raw) > 255:
            raise ValueError("invalid domain")
        addr = b"\x02" + bytes((len(raw),)) + raw
    return (b"\x00" + UUID_BYTES + b"\x00\x01" +
            struct.pack("!H", port) + addr + payload)


def relay(local: socket.socket, ws: WS) -> None:
    stop = threading.Event()

    def local_to_ws():
        while not stop.is_set():
            try:
                data = local.recv(32768)
            except OSError:
                break
            if not data:
                break
            try:
                ws.send(data)
            except OSError:
                break
        stop.set()

    def ws_to_local():
        to_strip = 2  # هدر پاسخ VLESS: [version, addon_len]
        while not stop.is_set():
            try:
                data = ws.recv()
            except (OSError, ValueError):
                break
            if not data:
                break
            if to_strip:
                n = min(to_strip, len(data))
                data, to_strip = data[n:], to_strip - n
                if not data:
                    continue
            try:
                local.sendall(data)
            except OSError:
                break
        stop.set()

    threads = [threading.Thread(target=local_to_ws, daemon=True),
               threading.Thread(target=ws_to_local, daemon=True)]
    for t in threads:
        t.start()
    stop.wait()
    for s in (local, ws.sock):
        try:
            s.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
    ws.close()
    local.close()
    for t in threads:
        t.join(timeout=2)


def read_exact(sock, n: int) -> bytes:
    out = b""
    while len(out) < n:
        chunk = sock.recv(n - len(out))
        if not chunk:
            raise ConnectionError("socks client disconnected")
        out += chunk
    return out


class SocksHandler(socketserver.BaseRequestHandler):
    def handle(self):
        global UUID_BYTES
        c = self.request
        c.settimeout(60)
        try:
            ver, n = read_exact(c, 2)
            if ver != 5 or n == 0:
                return
            read_exact(c, n)  # متدها؛ ما بدون احراز هویت هستیم
            c.sendall(b"\x05\x00")
            ver, cmd, _rsv, atyp = read_exact(c, 4)
            if atyp == 1:
                host = socket.inet_ntoa(read_exact(c, 4))
            elif atyp == 3:
                ln = read_exact(c, 1)[0]
                host = read_exact(c, ln).decode("ascii", "replace")
            elif atyp == 4:
                host = socket.inet_ntop(socket.AF_INET6, read_exact(c, 16))
            else:
                c.sendall(b"\x05\x08\x00\x01\x00\x00\x00\x00\x00\x00")
                return
            port = struct.unpack("!H", read_exact(c, 2))[0]
            if cmd != 1:
                c.sendall(b"\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00")
                return
            ws = WS.connect()
            ws.send(vless_header(host, port))
            c.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            c.settimeout(None)
            relay(c, ws)
        except (ConnectionError, OSError, ValueError) as exc:
            print(f"[socks] {type(exc).__name__}: {exc}", flush=True)
            try:
                c.close()
            except OSError:
                pass


class SocksServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    global UUID_BYTES, CFG
    parser = argparse.ArgumentParser(description="SOCKS5 -> VLESS/WebSocket client (zero dependencies)")
    parser.add_argument("--host", default=os.environ.get("VPN_HOST", ""), help="هاست سرور (بدون https://)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("VPN_PORT", "443")))
    parser.add_argument("--token", default=os.environ.get("VPN_TOKEN", ""))
    parser.add_argument("--uuid", default=os.environ.get("VPN_UUID", ""))
    parser.add_argument("--listen", default="127.0.0.1")
    parser.add_argument("--socks-port", type=int, default=1080)
    parser.add_argument("--no-tls", action="store_true", help="بدون TLS (فقط تست محلی)")
    args = parser.parse_args()

    if not all((args.host, args.token, args.uuid)):
        parser.error("به --host و --token و --uuid نیاز دارم (یا متغیرهای VPN_*)")
    try:
        UUID_BYTES = uuidlib.UUID(args.uuid).bytes
    except ValueError:
        parser.error("UUID نامعتبر است")
    CFG = {"host": args.host, "port": args.port, "token": args.token,
           "tls": not args.no_tls}

    srv = SocksServer((args.listen, args.socks_port), SocksHandler)
    print("=" * 60, flush=True)
    print(f"🔐 SOCKS5 روی {args.listen}:{args.socks_port}", flush=True)
    print(f"🌐 تونل: {'wss' if CFG['tls'] else 'ws'}://{args.host}:{args.port}/{args.token}", flush=True)
    print("📱 در اندروید: SocksDroid را به 127.0.0.1:1080 وصل کن (بدون نام کاربری/رمز)", flush=True)
    print("=" * 60, flush=True)
    try:
        srv.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
