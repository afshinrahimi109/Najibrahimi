# -*- coding: utf-8 -*-
"""
🐠 Diana Server — سرور اصلی سیستم چندعامله دیانا
فقط کتابخانه استاندارد پایتون: بدون pip install، روی هر هاست رایگان، کامپیوتر و ترموکس اجرا می‌شه.
اجرا:  python3 server.py   →   http://localhost:8000
"""
import asyncio
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import queue
import secrets
import socket
import sys
import threading
import time
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

try:  # پشتیبانی WebSocket روی همان پورت HTTP (بدون کتابخانهٔ بیرونی)
    from websockets.frames import Frame as _WSFrame, Opcode as _WSOpcode
    from websockets.exceptions import ConnectionClosed as _WSClosed
except Exception:  # pragma: no cover
    _WSFrame = None
    _WSOpcode = None
    _WSClosed = Exception

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import agents as agent_registry
import launch as launch_engine
import tools
from brain import Orchestrator
from memory import Memory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
PORT = int(os.environ.get("PORT", "8000"))
VERSION = "2.2-link"
WS_PORT = int(os.environ.get("DIANA_WS_PORT", str(PORT + 1)))

# 🔒 وقتی DIANA_TOKEN تنظیم شود (حالت آنلاین/تونل)، تمام درخواست‌ها نیاز به
# HTTP Basic Auth دارند. بدون آن سرور مثل قبل فقط محلی و بدون رمز است.
AUTH_USER = os.environ.get("DIANA_USER", "diana")
AUTH_TOKEN = os.environ.get("DIANA_TOKEN", "").strip()
# اگر روی هاست عمومی (Render/Railway/Fly/Heroku) بدون رمز اجرا شد،
# خودمان یک رمز تصادفی بسازیم تا دیانا بیحفاظ توی اینترنت باز نماند.
PUBLIC_HOST = any(os.environ.get(k) for k in ("RENDER", "RAILWAY_ENVIRONMENT", "FLY_APP_NAME", "DYNO"))
AUTO_TOKEN = False
if not AUTH_TOKEN and PUBLIC_HOST:
    AUTH_TOKEN = secrets.token_urlsafe(18)
    AUTO_TOKEN = True

memory = Memory()

# ---------- گذرگاه رویدادهای زنده (SSE + long-poll) ----------
# دو مسیر داریم تا اتصال در هر محیطی (پروکسی، iframe، تونل، شبکهٔ موبایل) کار کند:
#   ۱) SSE  →  GET /api/events           (رویدادها push می‌شوند)
#   ۲) Poll →  GET /api/events/poll?after=N  (اگر SSE بسته شد، مرورگر خودکار می‌چرخد)
_subscribers = set()
_sub_lock = threading.Lock()
_events = []            # [(id, json_text)] — پنجرهٔ آخرین رویدادها برای long-poll
_events_lock = threading.Lock()
_events_next = 1
EVENT_LOG_MAX = 400

def emit(event: dict):
    global _events_next
    data = json.dumps(event, ensure_ascii=False)
    with _events_lock:
        eid = _events_next
        _events_next += 1
        _events.append((eid, data))
        if len(_events) > EVENT_LOG_MAX:
            del _events[:len(_events) - EVENT_LOG_MAX]
    with _sub_lock:
        dead = []
        for q in _subscribers:
            try:
                q.put_nowait(data)
            except Exception:
                dead.append(q)
        for q in dead:
            _subscribers.discard(q)

def events_since(after: int, wait: float = 18.0):
    """رویدادهای بعد از شناسهٔ داده‌شده؛ اگر نبود تا `wait` ثانیه صبر می‌کند (long-poll)."""
    deadline = time.time() + max(0.0, min(wait, 25.0))
    while True:
        with _events_lock:
            if _events:
                latest = _events[-1][0]
                if after >= latest:          # هیچ رویداد تازه‌ای نیست
                    if time.time() >= deadline:
                        return [], latest
                    sleep_for = 0.4
                else:
                    batch = [(i, d) for (i, d) in _events if i > after]
                    if not batch:            # after قدیمی‌تر از پنجره است → آخرین‌ها را بده
                        batch = _events[-20:]
                    return batch, latest
            elif time.time() >= deadline:
                return [], 0
            else:
                sleep_for = 0.4
        time.sleep(sleep_for)

brain = Orchestrator(memory, emit)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write(f"🐠 {self.address_string()} {fmt % args}\n")

    # ---------- 🔒 محافظت در حالت آنلاین ----------
    def _authorized(self):
        if not AUTH_TOKEN:
            return True  # اجرای محلی بدون رمز (رفتار قبلی)
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            raw = base64.b64decode(header[6:].strip(), validate=True)
        except Exception:
            return False
        expected = f"{AUTH_USER}:{AUTH_TOKEN}".encode("utf-8")
        return hmac.compare_digest(raw, expected)

    def _require_auth(self):
        if self._authorized():
            return True
        body = b'{"error": "unauthorized"}'
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Diana", charset="UTF-8"')
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    # ---------- 🔌 WebSocket (همان پورت، پروکسی‌پسند) ----------
    def _ws_expected_key(self):
        """تأیید Origin/توکن برای اتصال WebSocket (اگر رمز تنظیم شده باشد)."""
        if not AUTH_TOKEN:
            return True
        token = (self.headers.get("X-Diana-Token") or "").strip()
        if token and hmac.compare_digest(token, AUTH_TOKEN):
            return True
        # مرورگر برای WebSocket نمی‌تواند هدر Basic بفرستد؛ رمز را از query می‌خوانیم
        qs = urllib.parse.parse_qs(urlparse(self.path).query)
        qtok = (qs.get("token") or [""])[0]
        return bool(qtok) and hmac.compare_digest(qtok, AUTH_TOKEN)

    def do_WEBSOCKET(self, ws):
        """جریان زندهٔ رویدادها روی WebSocket — در پیش‌نمایش/پروکسی همان پورت کار می‌کند."""
        if not self._ws_expected_key():
            ws.close(1008, "unauthorized")
            return
        qs = urllib.parse.parse_qs(urlparse(self.path).query)
        try:
            after = int((qs.get("after") or ["0"])[0] or 0)
        except Exception:
            after = 0
        # رویدادهای عقب‌مانده
        for i, d in events_since(after, wait=0)[0]:
            ws.send(json.dumps({"id": i, "data": json.loads(d)}, ensure_ascii=False))
        import select
        while True:
            batch, latest = events_since(after, wait=12)
            for i, d in batch:
                after = max(after, i)
                ws.send(json.dumps({"id": i, "data": json.loads(d)}, ensure_ascii=False))
            ws.ping(b"diana")
            # آیا کلاینت بسته است یا پیامی فرستاده؟ (پیام‌ها فقط برای keep-alive/درخواست تازه)
            try:
                r, _, _ = select.select([ws.socket], [], [], 0.05)
                if r:
                    op, data = ws.recv()
                    if op in ("close", None):
                        return
                    if op == "text" and data:
                        try:
                            msg = json.loads(data)
                        except Exception:
                            msg = {}
                        if str(msg.get("type")) == "sync":
                            after = int(msg.get("after") or after)
            except Exception:
                return

    # ---------- 🔌 WebSocket روی همان پورت HTTP ----------
    def _ws_bridge(self):
        """ارتقا به WebSocket و پل‌زدن رویدادها — بدون نیاز به پورت دوم (پروکسی‌پسند)."""
        if _WSFrame is None:
            return self._json({"error": "websockets not installed"}, 501)
        import socket as _socket
        key = (self.headers.get("Sec-WebSocket-Key") or "").strip()
        if not key:
            return self._json({"error": "bad handshake"}, 400)
        accept = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        self.wfile.write(
            ("HTTP/1.1 101 Switching Protocols\r\n"
             "Upgrade: websocket\r\n"
             "Connection: Upgrade\r\n"
             f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode())
        self.wfile.flush()
        self.close_connection = True
        sock = self.connection
        sock.settimeout(1.0)

        def send_text(txt):
            sock.sendall(_WSFrame(_WSOpcode.TEXT, txt.encode("utf-8")).serialize(mask=False))

        buf = b""
        try:  # رویدادهای عقب‌مانده
            qs = urllib.parse.parse_qs(urlparse(self.path).query)
            after = int((qs.get("after") or ["0"])[0] or 0)
        except Exception:
            after = 0
        try:
            for i, d in events_since(after, wait=0)[0]:
                after = max(after, i)
                send_text(json.dumps({"id": i, "data": json.loads(d)}, ensure_ascii=False))
        except Exception:
            return
        last_ping = time.time()
        while True:
            # ۱) رویدادهای تازه را بفرست
            try:
                batch, _latest = events_since(after, wait=0)
            except Exception:
                batch = []
            for i, d in batch:
                after = max(after, i)
                try:
                    send_text(json.dumps({"id": i, "data": json.loads(d)}, ensure_ascii=False))
                except Exception:
                    return
            # ۲) فریم‌های ورودی (close / ping / pong / sync)
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    return
                buf += chunk
                while len(buf) >= 2:
                    fin = bool(buf[0] & 0x80)
                    op = buf[0] & 0x0F
                    masked = bool(buf[1] & 0x80)
                    ln = buf[1] & 0x7F
                    off = 2
                    if ln == 126:
                        if len(buf) < 4:
                            break
                        ln = int.from_bytes(buf[2:4], "big"); off = 4
                    elif ln == 127:
                        if len(buf) < 10:
                            break
                        ln = int.from_bytes(buf[2:10], "big"); off = 10
                    mask = b""
                    if masked:
                        if len(buf) < off + 4:
                            break
                        mask = buf[off:off + 4]; off += 4
                    if len(buf) < off + ln:
                        break
                    payload = bytearray(buf[off:off + ln])
                    buf = buf[off + ln:]
                    if masked:
                        payload = bytearray(b ^ mask[i % 4] for i, b in enumerate(payload))
                    data = bytes(payload)
                    if op == 0x8:                       # close
                        try:
                            sock.sendall(_WSFrame(_WSOpcode.CLOSE, data[:2]).serialize(mask=False))
                        except Exception:
                            pass
                        return
                    if op == 0x9:                       # ping → pong
                        try:
                            sock.sendall(_WSFrame(_WSOpcode.PONG, data).serialize(mask=False))
                        except Exception:
                            return
                    elif op == 0xA:                     # pong
                        pass
                    elif op in (0x1, 0x2) and data:     # text/binary
                        try:
                            msg = json.loads(data.decode("utf-8", "ignore"))
                        except Exception:
                            msg = {}
                        if isinstance(msg, dict) and str(msg.get("type")) == "sync":
                            try:
                                after = int(msg.get("after") or after)
                            except Exception:
                                pass
                    if fin is False:
                        pass
            except (socket.timeout, TimeoutError):
                pass
            except OSError:
                return
            # ۳) ping هر ۲۵ ثانیه تا پروکسی اتصال را نبندد
            if time.time() - last_ping > 25:
                last_ping = time.time()
                try:
                    sock.sendall(_WSFrame(_WSOpcode.PING, b"diana").serialize(mask=False))
                except Exception:
                    return
            time.sleep(0.12)

    # ---------- ابزارها ----------
    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _body_json(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(n) if n else b"{}"
            return json.loads(raw.decode("utf-8", "replace") or "{}")
        except Exception:
            return {}

    def _static(self, path):
        if path in ("/", ""):
            path = "/index.html"
        fs_path = os.path.normpath(os.path.join(STATIC_DIR, path.lstrip("/")))
        if not fs_path.startswith(STATIC_DIR) or not os.path.isfile(fs_path):
            self._json({"error": "not found"}, 404)
            return
        ctype = mimetypes.guess_type(fs_path)[0] or "application/octet-stream"
        with open(fs_path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith(("text/", "application/javascript")) else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    # ---------- GET ----------
    def do_GET(self):
        # 🔓 این دو مسیر برای تست اتصال، بدون رمز و بدون لاگ سنگین
        raw_path = unquote(urlparse(self.path).path)
        if raw_path in ("/api/ping", "/healthz"):
            return self._json({"ok": True, "diana": True, "version": VERSION,
                               "ws_port": WS_PORT, "http_port": PORT,
                               "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        # 🔌 اگر مرورگر روی همین پورت ارتقا به WebSocket خواست: /stream
        if raw_path in ("/stream", "/ws") and self.headers.get("Upgrade", "").lower() == "websocket":
            return self._ws_bridge()
        if not self._require_auth():
            return
        path = raw_path
        try:
            if path == "/api/events":
                return self._sse()
            if path == "/api/events/poll":
                qs = urllib.parse.parse_qs(urlparse(self.path).query)
                after = int((qs.get("after") or ["0"])[0] or 0)
                wait = float((qs.get("wait") or ["18"])[0] or 18)
                batch, latest = events_since(after, wait)
                return self._json({"events": [{"id": i, "data": json.loads(d)} for i, d in batch],
                                   "last": latest})
            if path == "/favicon.ico":
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path == "/api/agents":
                return self._json(agent_registry.public_registry())
            if path == "/api/status":
                info = tools.system_info()
                return self._json({
                    "online": True, "internet": info["internet"], "llm_mode": brain.llm.mode(),
                    "agents_total": len(agent_registry.AGENTS),
                    "launches_total": len(memory.data.get("launches", [])),
                    "departments": len(agent_registry.DEPARTMENTS),
                    "user_name": memory.user_name(),
                    "stats": memory.data["stats"],
                    "time": info["time"],
                    "version": VERSION,
                    "stream": "ws+sse+poll",
                    "ws_port": WS_PORT,
                    "auth": bool(AUTH_TOKEN),
                    "settings": memory.public_settings(),
                })
            if path == "/api/memory":
                return self._json(memory.public_state())
            if path == "/api/files":
                return self._json({"files": tools.vault_list()})
            if path.startswith("/api/files/") and path.endswith("/download"):
                name = tools.safe_name(path[len("/api/files/"):-len("/download")])
                fs_path = os.path.join(tools.VAULT_DIR, name)
                if not os.path.isfile(fs_path):
                    return self._json({"error": "file not found"}, 404)
                with open(fs_path, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{name}")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path.startswith("/api/missions/"):
                m = memory.get_mission(path.split("/")[-1])
                return self._json(m or {"error": "not found"}, 200 if m else 404)
            # 🚀 راه‌اندازی کسب‌وکار
            if path == "/api/launch":
                return self._json({"launches": memory.public_state().get("launches", []),
                                   "stages": [{"id": s["id"], "step": s["step"], "icon": s["icon"],
                                               "owner": s["owner"], "deliverable": s["deliverable"],
                                               "why": s["why"]} for s in launch_engine.STAGES],
                                   "defaults": launch_engine.DEFAULTS})
            if path.startswith("/api/launch/"):
                parts = [p for p in path[len("/api/launch/"):].split("/") if p]
                lid = parts[0] if parts else ""
                full = len(parts) > 1 and parts[1] == "full"
                rec = brain.launch.detail(lid, full=full)
                if not rec:
                    return self._json({"error": "not found"}, 404)
                return self._json(rec)
            if path == "/api/settings":
                return self._json(memory.public_settings())
            return self._static(path)
        except BrokenPipeError:
            pass
        except Exception as e:
            try:
                self._json({"error": str(e)}, 500)
            except Exception:
                pass

    def _sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        q = queue.Queue(maxsize=200)
        with _sub_lock:
            _subscribers.add(q)
        try:
            self.wfile.write(b": diana-connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    data = q.get(timeout=20)
                    self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with _sub_lock:
                _subscribers.discard(q)

    # ---------- POST / DELETE ----------
    def do_POST(self):
        if not self._require_auth():
            return
        path = unquote(urlparse(self.path).path)
        body = self._body_json()
        try:
            if path == "/api/message":
                return self._json(brain.handle_message(str(body.get("text", ""))))
            if path == "/api/agent/run":
                agent_id = str(body.get("agent_id", ""))
                task = str(body.get("task", "")).strip()
                if agent_id not in agent_registry.AGENT_BY_ID or not task:
                    return self._json({"error": "agent_id یا task نامعتبر است"}, 400)
                mid = brain.start_mission(task, forced_agent_id=agent_id)
                return self._json({"mission_id": mid, "agent": brain._pub_agent(agent_registry.AGENT_BY_ID[agent_id])})
            if path == "/api/mission":
                goal = str(body.get("goal", "")).strip()
                if not goal:
                    return self._json({"error": "هدف مأموریت خالیه"}, 400)
                return self._json({"mission_id": brain.start_mission(goal)})
            # 🚀 راه‌اندازی کسب‌وکار (تحقیق → تأمین‌کننده → مشتری → قرارداد → اجرا)
            if path == "/api/launch":
                fields = body if isinstance(body, dict) else {}
                mode = str(body.get("mode", "auto")) if isinstance(body, dict) else "auto"
                rec = brain.launch.start(fields, mode=mode)
                return self._json({"ok": True, "launch": rec})
            if path == "/api/launch/parse":
                text = str(body.get("text", "")).strip()
                if not text:
                    return self._json({"error": "متن خالیه"}, 400)
                return self._json({"fields": launch_engine.normalize_fields(launch_engine.parse_launch_text(text))})
            if path == "/api/launch/quote":
                fields = launch_engine.normalize_fields(body if isinstance(body, dict) else {})
                return self._json({"fields": fields, "numbers": launch_engine.numbers(fields),
                                   "plan": launch_engine.plan_markdown(fields)})
            if path == "/api/chatlog":
                memory.log_chat(str(body.get("role", "diana")), str(body.get("text", "")), str(body.get("source", "browser-cloud")))
                return self._json({"ok": True})
            if path == "/api/memory/fact":
                fact = memory.add_fact(str(body.get("text", "")))
                return self._json({"ok": True, "fact": fact})
            if path == "/api/files":
                name = tools.vault_write(str(body.get("name", "note.txt")), str(body.get("content", "")))
                return self._json({"ok": True, "name": name})
            if path == "/api/settings":
                for k in ("voice", "cloud_brain"):
                    if k in body:
                        memory.settings[k] = bool(body[k])
                for k in ("groq_key", "gemini_key", "openrouter_key"):
                    if k in body and str(body[k]).strip() and "•" not in str(body[k]):
                        memory.settings[k] = str(body[k]).strip()
                    if k in body and str(body[k]).strip() == "":
                        memory.settings[k] = ""
                if "user_name" in body and str(body["user_name"]).strip():
                    memory.set_user_name(str(body["user_name"]))
                memory.save_settings()
                return self._json({"ok": True, "settings": memory.public_settings(), "llm_mode": brain.llm.mode()})
            return self._json({"error": "not found"}, 404)
        except Exception as e:
            return self._json({"error": str(e)}, 500)

    def do_DELETE(self):
        if not self._require_auth():
            return
        path = unquote(urlparse(self.path).path)
        try:
            if path.startswith("/api/files/"):
                ok = tools.vault_delete(path[len("/api/files/"):])
                return self._json({"ok": ok})
            if path.startswith("/api/memory/fact/"):
                ok = memory.delete_fact(path.split("/")[-1])
                return self._json({"ok": ok})
            return self._json({"error": "not found"}, 404)
        except Exception as e:
            return self._json({"error": str(e)}, 500)

    def do_HEAD(self):
        """بررسی سلامت اتصال: HEAD / → فقط هدرها (برای مانیتور و تست تونل)."""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("X-Diana-Version", VERSION)
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


class DianaServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


async def _serve_async(server):
    """سرور HTTP + WebSocket روی یک پورت؛ اگر websockets نصب نباشد، فقط HTTP."""
    try:
        import websockets
        from websockets.asyncio.server import serve as ws_serve
    except Exception:
        websockets = None
    http_srv = await asyncio.to_thread(
        lambda: server.serve_forever()) if False else None
    # HTTP را در نخ جدا اجرا می‌کنیم و WebSocket را در حلقهٔ asyncio
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    if websockets is None:
        print("ℹ️ بستهٔ websockets نصب نیست: جریان زنده از SSE/Polling استفاده می‌کند")
        print("   (نصب اختیاری: pip install websockets — برای WebSocket روی همان پورت)")
        while True:
            await asyncio.sleep(3600)
        return

    async def stream(ws):
        """پل: رویدادهای گذرگاه داخلی → WebSocket"""
        qs = urllib.parse.parse_qs(urlparse(ws.request.path).query)
        if AUTH_TOKEN:
            token = (qs.get("token") or [""])[0] or (ws.request.headers.get("X-Diana-Token") or "")
            if not (token and hmac.compare_digest(token, AUTH_TOKEN)):
                await ws.close(code=1008, reason="unauthorized")
                return
        try:
            after = int((qs.get("after") or ["0"])[0] or 0)
        except Exception:
            after = 0
        for i, d in events_since(after, wait=0)[0]:
            await ws.send(json.dumps({"id": i, "data": json.loads(d)}, ensure_ascii=False))
        while True:
            batch, latest = await asyncio.to_thread(events_since, after, 10)
            for i, d in batch:
                after = max(after, i)
                await ws.send(json.dumps({"id": i, "data": json.loads(d)}, ensure_ascii=False))
            if not batch:
                try:
                    await asyncio.wait_for(ws.ping(), timeout=5)
                except Exception:
                    return

    async with ws_serve(stream, "0.0.0.0", WS_PORT, ping_interval=None, max_size=2 ** 22):
        print(f"🔌 WebSocket زنده: ws://localhost:{WS_PORT}  (پیش‌نمایش: wss://{WS_PORT}-<sandbox>.e2b.app)")
        while True:
            await asyncio.sleep(3600)


def main():
    server = DianaServer(("0.0.0.0", PORT), Handler)
    server.daemon_threads = True
    print("=" * 58)
    print("🐠 دیانا بیدار شد! سیستم چندعامله با ۱۴۰ ایجنت متخصص آماده‌ست")
    print(f"🌐 آکواریوم دیانا: http://localhost:{PORT}")
    print(f"🧠 مغز ابری: {brain.llm.mode()} | اینترنت سرور: {'✅ وصل' if tools.internet_available() else '📴 قطع — حالت آفلاین فعاله'}")
    print(f"🔒 دسترسی: {'رمزدار (Basic Auth) — کاربر: ' + AUTH_USER if AUTH_TOKEN else 'بدون رمز (فقط محلی)'}")
    print(f"🔗 تست اتصال: http://localhost:{PORT}/api/ping  |  stream: sse + poll")
    sandbox = os.environ.get("E2B_SANDBOX_ID", "").strip()
    if sandbox:
        print(f"🌍 لینک عمومی (پیش‌نمایش): https://{PORT}-{sandbox}.e2b.app")
    if AUTO_TOKEN:
        print(f"⚠️ رمز خودکار ساخته شد — همین حالا از لاگ کپی کن: {AUTH_TOKEN}")
    print("=" * 58)
    try:
        asyncio.run(_serve_async(server))
    except KeyboardInterrupt:
        print("\n🐠 دیانا رفت بخوابه... خداحافظ فرمانده!")


if __name__ == "__main__":
    main()
