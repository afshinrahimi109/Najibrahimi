"""Shared test rig: one running agent wired to the built-in simulator, in a throw-away folder."""
import http.server
import json
import os
import shutil
import struct
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import insta_agent as ia  # noqa: E402

# make every waiting period tiny
ia.CONTAINER_POLL_SEC = 0.02
ia.PUBLISH_RECHECK_SEC = 0.05
ia.RETRY_BACKOFF = [0.05, 0.05, 0.05, 0.05, 0.05]
ia.QUOTA_RETRY_SEC = 0.05
ia.RESTART_SEC = 0.02


def jpeg(width=1080, height=1080, pad=0):
    """Smallest thing that looks like a JPEG of the given size (header only, not decodable)."""
    return (b"\xff\xd8\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            + b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 3) + b"\x01\x11\x00\x02\x11\x00"
            + b"\x00" * pad + b"\xff\xd9")


def mp4(size=4096):
    return b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00isommp42" + b"\x00" * max(0, size - 24)


def png():
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">IIBBBBB", 10, 10, 8, 2, 0, 0, 0) + b"\x00" * 20


class Rig:
    def __init__(self, connect=True, auth=False, env=None, loop=False, host=None, demo=False):
        self.tmp = tempfile.mkdtemp(prefix="ia-test-")
        e = {"AGENT_QUIET": "1", "HOME": self.tmp, "AGENT_TICK_SEC": "0.1"}
        if not demo:
            e["AGENT_SIM"] = "1"
        if not loop:
            e["AGENT_NO_LOOP"] = "1"
        e.update(env or {})
        argv = ["--port", "0", "--no-browser", "--data", os.path.join(self.tmp, "data")]
        argv += [] if auth else ["--no-auth"]
        argv += ["--host", host] if host else []
        argv += ["--demo"] if demo else []
        self.app = ia.App(argv, e)
        self.app.start()
        self.agent, self.sim = self.app.agent, self.app.agent.sim
        self.sim.video_seconds = 0.15
        self.sim.lively = False
        self.base = "http://127.0.0.1:%d" % self.app.port
        self.media_base = "http://127.0.0.1:%d" % self.app.media_port
        self.cookie = ""
        if connect and not demo:
            self.agent.connect(ia.SIM_TOKEN)

    def close(self):
        self.app.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ── HTTP ──
    def req(self, method, path, body=None, headers=None, raw=None, base=None):
        h = {"X-IA": "1"}
        if self.cookie:
            h["Cookie"] = self.cookie
        data = raw
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        h = {k: v for k, v in h.items() if v is not None}
        req = urllib.request.Request((base or self.base) + path, data=data, method=method, headers=h)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(req, timeout=30) as res:
                status, hdrs, payload = res.status, res.headers, res.read()
        except urllib.error.HTTPError as err:
            status, hdrs, payload = err.code, err.headers, err.read()
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            parsed = payload
        return status, parsed, hdrs

    def get(self, path, **kw):
        return self.req("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.req("POST", path, body if body is not None else {}, **kw)

    def ok(self, method, path, body=None, **kw):
        status, data, _ = self.req(method, path, body if (body is not None or method != "POST") else {}, **kw)
        assert status == 200, "%s %s → %s %s" % (method, path, status, data)
        return data

    def upload(self, data, name="file.jpg"):
        status, out, _ = self.req("POST", "/api/upload?name=" + urllib.parse.quote(name), raw=data, headers={"Content-Type": "application/octet-stream"})
        assert status == 200, out
        return out

    # ── driving the agent by hand (the background loop is off in tests) ──
    def tick(self, n=1, force=True):
        for _ in range(n):
            self.agent.tick(force=force)

    def post_status(self, pid):
        return self.agent.publisher.get(pid)

    def run_post(self, pid, timeout=8, until=("published", "failed", "missed")):
        end = time.time() + timeout
        while time.time() < end:
            self.agent.publisher.tick()
            p = self.post_status(pid)
            if p["status"] in until:
                return p
            time.sleep(0.02)
        return self.post_status(pid)

    def new_post(self, kind="image", action="now", media=None, caption="سلام دنیا", **extra):
        if media is None:
            media = [{"file": self.upload(mp4() if kind == "reel" else jpeg())["id"]}]
        body = dict(kind=kind, caption=caption, media=media, action=action)
        body.update(extra)
        return self.ok("POST", "/api/posts", body)

    def feed_count(self):
        return len(self.sim.media)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class FakeAI:
    """A stand-in for an OpenAI-compatible chat service: answers with `self.answer` and remembers what it was asked."""

    def __init__(self, answer="سلام 🌹 در دایرکت راهنمایی می‌کنیم."):
        self.answer, self.asked, self.status = answer, [], 200
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8"))
                outer.asked.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
                answer = outer.answer(body) if callable(outer.answer) else outer.answer
                out = json.dumps({"choices": [{"message": {"role": "assistant", "content": answer}}]}).encode("utf-8")
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d/v1" % self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()
