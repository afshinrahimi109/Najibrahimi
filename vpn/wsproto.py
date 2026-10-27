#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wsproto.py — پیادهسازی مینیمال WebSocket (RFC 6455) فقط با stdlib پایتون.
هم سرور و هم کلاینت داخل این پوشه از همین فایل استفاده میکنند.
هیچ وابستگی خارجی لازم نیست: نه pip، نه websockets، نه aiohttp.
"""
from __future__ import annotations

import base64
import hashlib
import os
import struct

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_FRAME = 1 << 20  # ۱ مگابایت برای هر فریم؛ جلوگیری از مصرف بیهوده RAM


class ByteReader:
    """خواندن دقیق n بایت از سوکت، با بافر اولیه (برای early data / pipelining)."""

    def __init__(self, sock, initial: bytes = b""):
        self.sock = sock
        self.buf = bytearray(initial)

    def prepend(self, data: bytes) -> None:
        if data:
            self.buf[:0] = bytearray(data)

    def read(self, n: int) -> bytes:
        if n < 0:
            raise ValueError("negative read")
        while len(self.buf) < n:
            chunk = self.sock.recv(max(4096, n - len(self.buf)))
            if not chunk:
                raise ConnectionError("connection closed")
            self.buf.extend(chunk)
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out


def accept_key(key: str) -> str:
    """Sec-WebSocket-Accept برای Handshake سرور."""
    digest = hashlib.sha1((key + WS_GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def frame_bytes(opcode: int, data: bytes = b"", mask: bool = False) -> bytes:
    """بایتهای یک فریم کامل (بدون ارسال) — بهدرد early data و تستها میخورد."""
    first = 0x80 | (opcode & 0x0F)
    length = len(data)
    if length < 126:
        header = bytes((first, length | (0x80 if mask else 0)))
    elif length < 65536:
        header = bytes((first, 126 | (0x80 if mask else 0))) + struct.pack("!H", length)
    else:
        header = bytes((first, 127 | (0x80 if mask else 0))) + struct.pack("!Q", length)
    payload = data
    if mask:
        key = os.urandom(4)
        payload = bytes(b ^ key[i % 4] for i, b in enumerate(data))
        header += key
    return header + payload


def send_frame(sock, lock, opcode: int, data: bytes = b"", mask: bool = False) -> None:
    """ارسال یک فریم. فریمهای کلاینت حتماً باید mask شوند (RFC 6455)."""
    with lock:
        sock.sendall(frame_bytes(opcode, data, mask))


def read_frame(reader: ByteReader):
    """-> (opcode, payload). ممکن است socket.timeout بدهد؛ تصمیمش با فراخواننده است."""
    b0, b1 = reader.read(2)
    _fin = b0 & 0x80  # فریمهای چندتکهای: opcode 0 همان ادامه پیام است
    opcode = b0 & 0x0F
    masked = b1 & 0x80
    length = b1 & 0x7F
    if length == 126:
        length = struct.unpack("!H", reader.read(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", reader.read(8))[0]
    if length > MAX_FRAME:
        raise ValueError("websocket frame too large")
    key = reader.read(4) if masked else b""
    payload = reader.read(length) if length else b""
    if masked:
        payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
    return opcode, payload
