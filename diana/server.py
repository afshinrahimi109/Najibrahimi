# -*- coding: utf-8 -*-
"""
🐠 Diana Server — سرور اصلی سیستم چندعامله دیانا
فقط کتابخانه استاندارد پایتون: بدون pip install، روی هر هاست رایگان، کامپیوتر و ترموکس اجرا می‌شه.
اجرا:  python3 server.py   →   http://localhost:8000
"""
import json
import mimetypes
import os
import queue
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import agents as agent_registry
import tools
from brain import Orchestrator
from memory import Memory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
PORT = int(os.environ.get("PORT", "8000"))

memory = Memory()

# ---------- گذرگاه رویدادهای زنده (SSE) ----------
_subscribers = set()
_sub_lock = threading.Lock()

def emit(event: dict):
    data = json.dumps(event, ensure_ascii=False)
    with _sub_lock:
        dead = []
        for q in _subscribers:
            try:
                q.put_nowait(data)
            except Exception:
                dead.append(q)
        for q in dead:
            _subscribers.discard(q)

brain = Orchestrator(memory, emit)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write(f"🐠 {self.address_string()} {fmt % args}\n")

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
        path = unquote(urlparse(self.path).path)
        try:
            if path == "/api/events":
                return self._sse()
            if path == "/api/agents":
                return self._json(agent_registry.public_registry())
            if path == "/api/status":
                info = tools.system_info()
                return self._json({
                    "online": True, "internet": info["internet"], "llm_mode": brain.llm.mode(),
                    "agents_total": len(agent_registry.AGENTS),
                    "departments": len(agent_registry.DEPARTMENTS),
                    "user_name": memory.user_name(),
                    "stats": memory.data["stats"],
                    "time": info["time"],
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

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.daemon_threads = True
    print("=" * 58)
    print("🐠 دیانا بیدار شد! سیستم چندعامله با ۱۲۰ ایجنت متخصص آماده‌ست")
    print(f"🌐 آکواریوم دیانا: http://localhost:{PORT}")
    print(f"🧠 مغز ابری: {brain.llm.mode()} | اینترنت سرور: {'✅ وصل' if tools.internet_available() else '📴 قطع — حالت آفلاین فعاله'}")
    print("=" * 58)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🐠 دیانا رفت بخوابه... خداحافظ فرمانده!")


if __name__ == "__main__":
    main()
