#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ایجنت اینستاگرام  —  insta_agent.py
====================================
یک فایل، بدون نصب هیچ کتابخانه‌ای (فقط پایتون ۳٫۸ به بالا).

    python insta_agent.py              اجرا و باز شدن پنل فارسی (گوشی یا کامپیوتر)
    python insta_agent.py --demo       حالت نمایشی با یک پیج ساختگی (بدون توکن و بدون اینترنت)
    python insta_agent.py --show-key   نمایش دوبارهٔ کد ورود پنل

کارها: انتشار و زمان‌بندی پست / چندتایی / ریل / استوری، صندوق کامنت و دایرکت، پاسخ خودکار با
قانون، مخفی‌کردن اسپم، آمار، و دستیار کپشن و هشتگ.
فقط از API رسمی اینستاگرام (Meta) استفاده می‌کند و رمز پیج را هیچ‌وقت نمی‌خواهد.
راهنمای کامل: README.md کنار همین فایل.
"""
import argparse
import base64
import copy
import hashlib
import hmac
import http.client
import json
import os
import random
import re
import secrets
import shlex
import shutil
import signal
import socket
import sqlite3
import ssl
import struct
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zlib
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "1.0.0"
DEFAULT_PORT = 8787
API_VERSIONS = ["v26.0", "v27.0", "v25.0", ""]
KINDS = ("image", "carousel", "reel", "story")
IMAGE_MODES = ("auto", "pollinations", "horde", "custom", "off")       # where the studio gets its pictures from
FREE_GAP = 46                   # Pollinations without a key: one picture and one text every 45 seconds per address
KIND_FA = {"image": "پست", "carousel": "پست چندتایی", "reel": "ریل", "story": "استوری"}
IMAGE_MAX = 8 * 1024 * 1024
VIDEO_MAX = 300 * 1024 * 1024
STORY_VIDEO_MAX = 100 * 1024 * 1024
MAX_HASHTAGS = 30               # the most a caption may carry according to Meta's API reference
GOOD_HASHTAGS = 5               # what Instagram itself advises since December 2025: more only gets a warning here
FRESH_SEC = 3 * 86400          # older comments/messages are imported as "already handled"
AUTO_MAX_AGE = 86400           # the agent never auto-answers anything older than this
QUIET = False


# ───────────────────────────── helpers ─────────────────────────────

def now():
    return time.time()


def jdump(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def jload(text, default=None):
    try:
        return json.loads(text) if text not in (None, "", b"") else default
    except (TypeError, ValueError):
        return default


def clamp(value, low, high):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = low
    return max(low, min(high, value))


def truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def parse_ts(value):
    """Graph timestamps (2026-11-11T10:20:30+0000) → epoch seconds."""
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        v = float(value)
        return v / 1000.0 if v > 1e11 else v
    s = str(value).strip()
    if re.fullmatch(r"\d{9,13}", s):
        v = float(s)
        return v / 1000.0 if v > 1e11 else v
    s = re.sub(r"Z$", "+0000", s)
    s = re.sub(r"\.\d+", "", s)
    s = re.sub(r"([+-]\d\d):(\d\d)$", r"\1\2", s)
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue
    return 0.0


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime(ts))


_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_TO_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
_NORM = str.maketrans({"ي": "ی", "ى": "ی", "ئ": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه", "أ": "ا", "إ": "ا", "آ": "ا",
                       "ؤ": "و", "\u200c": "", "\u200d": "", "\u200e": "", "\u200f": "", "ـ": ""})


def norm(text):
    """Lower-cased, punctuation-free form used to compare Persian/English text."""
    s = str(text or "").translate(_NORM).translate(_FA_DIGITS).lower()
    s = re.sub(r"[\u064b-\u065f\u0670]", "", s)
    s = re.sub(r"[^\w\s@#]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def fa(n):
    """Number → Persian digits with thousands separators."""
    if isinstance(n, float):
        n = int(round(n))
    s = "{:,}".format(n).replace(",", "٬") if isinstance(n, int) else str(n)
    return s.translate(_TO_FA)


_SECRETS = [re.compile(r"(access_token=|Bearer\s+|/bot)([A-Za-z0-9_\-:.|%]{12,})"),
            re.compile(r"\b(IGAA|IGQ|EAA)([A-Za-z0-9_\-]{16,})")]


def redact(text):
    s = str(text)
    for rx in _SECRETS:
        s = rx.sub(lambda m: m.group(1) + "***", s)
    return s


def log(*parts):
    if not QUIET:
        sys.stderr.write("[%s] %s\n" % (time.strftime("%H:%M:%S"), redact(" ".join(str(p) for p in parts))))
        sys.stderr.flush()


class UserError(Exception):
    """A problem the person can fix; the message is shown in the panel as is."""

    def __init__(self, message, status=400, code=""):
        super().__init__(message)
        self.message, self.status, self.code = message, status, code


class NotReady(Exception):
    """Something is still warming up (e.g. the public link); try again shortly."""

    def __init__(self, message, wait=4):
        super().__init__(message)
        self.message, self.wait = message, wait


class Permanent(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


# ───────────────────────────── config ─────────────────────────────

def read_env_file(path):
    out = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key, value = key.strip(), value.strip()
                if key.startswith("export "):
                    key = key[7:].strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                    value = value[1:-1]
                out[key] = value
    except OSError:
        pass
    return out


class Config:
    def __init__(self, argv=None, env=None):
        global QUIET
        isolated = env is not None
        env = dict(os.environ if env is None else env)
        if not isolated:
            for k, v in read_env_file(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")).items():
                env.setdefault(k, v)
        p = argparse.ArgumentParser(prog="insta_agent.py", description="ایجنت مدیریت پیج اینستاگرام (پنل فارسی)")
        p.add_argument("--host", help="نشانی شنود (پیش‌فرض 127.0.0.1)")
        p.add_argument("--port", type=int, help="پورت پنل (پیش‌فرض %d)" % DEFAULT_PORT)
        p.add_argument("--data", help="پوشهٔ داده‌ها (پیش‌فرض ~/.insta_agent)")
        p.add_argument("--demo", action="store_true", help="حالت نمایشی با پیج ساختگی")
        p.add_argument("--no-browser", action="store_true", help="مرورگر را خودکار باز نکن")
        p.add_argument("--no-auth", action="store_true", help="بدون کد ورود (فقط روی خود دستگاه یا حالت نمایشی)")
        p.add_argument("--show-key", action="store_true", help="کد ورود را نشان بده و خارج شو")
        p.add_argument("--version", action="version", version="insta_agent " + VERSION)
        a = p.parse_args(sys.argv[1:] if argv is None else list(argv))
        self.env = env
        self.demo = a.demo or truthy(env.get("AGENT_DEMO"))
        self.sim = self.demo or truthy(env.get("AGENT_SIM"))
        self.host = a.host or env.get("AGENT_HOST") or "127.0.0.1"
        port = a.port if a.port is not None else (env.get("AGENT_PORT") or env.get("PORT"))
        self.port = int(port) if port not in (None, "") else DEFAULT_PORT
        home = env.get("HOME") or os.path.expanduser("~")
        default_dir = os.path.join(home, ".insta_agent_demo" if self.demo else ".insta_agent")
        self.data_dir = os.path.abspath(a.data or env.get("AGENT_DATA_DIR") or default_dir)
        self.loopback = self.host in ("127.0.0.1", "localhost", "::1")
        self.no_browser = a.no_browser or truthy(env.get("AGENT_NO_BROWSER"))
        self.no_auth = a.no_auth or truthy(env.get("AGENT_NO_AUTH"))
        self.show_key = a.show_key
        self.password = env.get("AGENT_PASSWORD") or ""
        self.public_url = (env.get("AGENT_PUBLIC_URL") or "").rstrip("/")
        self.proxy = env.get("AGENT_PROXY") or ""
        self.tick = float(env.get("AGENT_TICK_SEC") or 5)
        self.no_loop = truthy(env.get("AGENT_NO_LOOP"))
        self.tunnel_cmd = env.get("AGENT_TUNNEL_CMD") or ""
        self.ai_url = env.get("AGENT_AI_URL") or ""
        self.temp_host = env.get("AGENT_TEMP_HOST") or "https://litterbox.catbox.moe/resources/internals/api.php"
        self.image_api = (env.get("AGENT_IMAGE_URL") or "https://image.pollinations.ai").rstrip("/")
        self.gen_api = (env.get("AGENT_GEN_URL") or "https://gen.pollinations.ai").rstrip("/")
        self.horde_api = (env.get("AGENT_HORDE_URL") or "https://aihorde.net/api/v2").rstrip("/")
        self.free_gap = float(env.get("AGENT_FREE_GAP") or (8 if self.demo else FREE_GAP))
        self.api_version = env.get("IG_API_VERSION") or API_VERSIONS[0]
        self.ig_graph = (env.get("IG_GRAPH_URL") or "https://graph.instagram.com").rstrip("/")
        self.fb_graph = (env.get("FB_GRAPH_URL") or "https://graph.facebook.com").rstrip("/")
        self.telegram_api = (env.get("TELEGRAM_API_URL") or "https://api.telegram.org").rstrip("/")
        self.env_token = env.get("IG_ACCESS_TOKEN") or ""
        self.embed_ok = self.demo or truthy(env.get("AGENT_ALLOW_EMBED"))
        QUIET = truthy(env.get("AGENT_QUIET"))
        if self.no_auth and not (self.loopback or self.demo):
            p.error("--no-auth فقط وقتی مجاز است که پنل روی خود دستگاه (127.0.0.1) باشد یا در حالت نمایشی.")


# ───────────────────────────── storage ─────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS posts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, caption TEXT NOT NULL DEFAULT '',
  media TEXT NOT NULL DEFAULT '[]', opts TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'draft',
  scheduled_at REAL NOT NULL DEFAULT 0, manual INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT '{}',
  error TEXT NOT NULL DEFAULT '', progress TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 0,
  next_try_at REAL NOT NULL DEFAULT 0, ig_media_id TEXT NOT NULL DEFAULT '', permalink TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL DEFAULT 0, updated_at REAL NOT NULL DEFAULT 0, published_at REAL NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS posts_due ON posts(status, scheduled_at);
CREATE TABLE IF NOT EXISTS files (
  id TEXT PRIMARY KEY, ext TEXT, mime TEXT, kind TEXT, size INTEGER DEFAULT 0, width INTEGER DEFAULT 0,
  height INTEGER DEFAULT 0, name TEXT DEFAULT '', created_at REAL DEFAULT 0, temp_url TEXT DEFAULT '',
  temp_until REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS media (
  id TEXT PRIMARY KEY, data TEXT NOT NULL, ts REAL DEFAULT 0, pos INTEGER DEFAULT 999,
  seen_count INTEGER DEFAULT -1, synced_at REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS comments (
  id TEXT PRIMARY KEY, media_id TEXT NOT NULL, parent_id TEXT NOT NULL DEFAULT '', user_id TEXT DEFAULT '',
  username TEXT DEFAULT '', text TEXT DEFAULT '', ts REAL DEFAULT 0, hidden INTEGER DEFAULT 0,
  mine INTEGER DEFAULT 0, state TEXT DEFAULT 'open', auto INTEGER DEFAULT 0, deleted INTEGER DEFAULT 0,
  suggest TEXT DEFAULT '', dm_sent INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS comments_media ON comments(media_id);
CREATE INDEX IF NOT EXISTS comments_open ON comments(state, mine, deleted);
CREATE TABLE IF NOT EXISTS convs (
  id TEXT PRIMARY KEY, user_id TEXT DEFAULT '', username TEXT DEFAULT '', updated REAL DEFAULT 0,
  last_text TEXT DEFAULT '', last_id TEXT DEFAULT '', last_ts REAL DEFAULT 0, last_from_me INTEGER DEFAULT 0,
  last_user_ts REAL DEFAULT 0, handled_id TEXT DEFAULT '', auto_id TEXT DEFAULT '', suggest TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS msgs (
  id TEXT PRIMARY KEY, conv_id TEXT NOT NULL, from_me INTEGER DEFAULT 0, text TEXT DEFAULT '', ts REAL DEFAULT 0);
CREATE INDEX IF NOT EXISTS msgs_conv ON msgs(conv_id, ts);
CREATE TABLE IF NOT EXISTS rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT NOT NULL, name TEXT DEFAULT '', keywords TEXT DEFAULT '[]',
  mode TEXT DEFAULT 'any', replies TEXT DEFAULT '[]', private TEXT DEFAULT '', hide INTEGER DEFAULT 0,
  enabled INTEGER DEFAULT 1, hits INTEGER DEFAULT 0, created_at REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS actions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, target TEXT DEFAULT '', ukey TEXT DEFAULT '',
  actor TEXT DEFAULT 'user', rule_id INTEGER DEFAULT 0, detail TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS actions_ts ON actions(ts);
CREATE TABLE IF NOT EXISTS log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, level TEXT DEFAULT 'info', kind TEXT DEFAULT '', text TEXT,
  seen INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS snapshots (day TEXT PRIMARY KEY, ts REAL, followers INTEGER, follows INTEGER, media_count INTEGER);
"""


class DB:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None, timeout=30)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA secure_delete=ON")       # a removed token is overwritten, not just unlinked
            self.conn.executescript(SCHEMA)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def val(self, sql, args=(), default=0):
        with self.lock:
            row = self.conn.execute(sql, args).fetchone()
        return default if row is None or row[0] is None else row[0]

    def x(self, sql, args=()):
        with self.lock:
            return self.conn.execute(sql, args).lastrowid

    def get(self, key, default=None):
        row = self.one("SELECT v FROM kv WHERE k=?", (key,))
        return jload(row["v"], default) if row else default

    def set(self, key, value):
        self.x("INSERT INTO kv (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, jdump(value)))

    def drop(self, key):
        self.x("DELETE FROM kv WHERE k=?", (key,))

    def scrub(self):
        """Fold the write-ahead log into the main file, so a secret that was just removed is gone from disk too."""
        with self.lock:
            try:
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
            except sqlite3.Error:
                pass

    def close(self):
        with self.lock:
            try:
                self.conn.close()
            except sqlite3.Error:
                pass


DEFAULT_SETTINGS = {
    "autopilot": True,
    "manual": False,                                   # no page connected: the agent prepares, the owner posts by hand
    "auto": {"comment_reply": False, "spam_hide": False, "dm_reply": False, "ai_suggest": False, "ai_send": False,
             "daily_report": False},
    "since": {"comment_reply": 0.0, "spam_hide": 0.0, "dm_reply": 0.0, "ai_suggest": 0.0, "ai_send": 0.0,
              "daily_report": 0.0},
    "limits": {"per_hour": 30, "cooldown_min": 30, "daily_posts": 25, "quiet_from": "", "quiet_to": ""},
    "brand": {"about": "", "tone": "صمیمی و محترمانه", "hashtags": "", "handle": ""},
    "ai": {"mode": "free", "url": "", "model": "", "key": ""},
    "studio": {"image": "auto", "pollen": "", "url": "", "key": "", "model": ""},
    "media": {"method": "auto", "public_url": "", "temp_ok": False},
    "network": {"proxy": ""},
    "telegram": {"token": "", "chat_id": ""},
}
SECRET_FIELDS = (("ai", "key"), ("studio", "pollen"), ("studio", "key"), ("telegram", "token"))


def deep_merge(base, extra):
    out = {}
    for k, v in base.items():
        e = extra.get(k) if isinstance(extra, dict) else None
        if isinstance(v, dict):
            out[k] = deep_merge(v, e if isinstance(e, dict) else {})
        elif e is not None and (isinstance(e, type(v)) or (isinstance(v, float) and isinstance(e, (int, float)))) \
                and not (isinstance(e, bool) and not isinstance(v, bool)):
            out[k] = e
        else:
            out[k] = copy.deepcopy(v)
    return out


class Settings:
    def __init__(self, db):
        self.db = db
        self._cache = None
        self._lock = threading.Lock()

    def all(self):
        with self._lock:
            if self._cache is None:
                self._cache = deep_merge(DEFAULT_SETTINGS, self.db.get("settings") or {})
            return copy.deepcopy(self._cache)

    def get(self, path, default=None):
        node = self.all()
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def public(self):
        s = self.all()
        for section, key in SECRET_FIELDS:
            s[section][key + "_set"] = bool(s[section][key])
            s[section][key] = ""
        return s

    def patch(self, data):
        if not isinstance(data, dict):
            raise UserError("قالب تنظیمات نادرست است.")
        cur = self.all()
        stamp = float(int(now()))

        def walk(dst, src, ref, path):
            for k, v in src.items():
                if k not in ref or (path == "" and k == "since"):
                    continue
                r = ref[k]
                if isinstance(r, dict):
                    if isinstance(v, dict):
                        walk(dst[k], v, r, path + k + ".")
                elif isinstance(r, bool):
                    if isinstance(v, bool):
                        if path == "auto." and v and not dst[k]:
                            cur["since"][k] = stamp
                        dst[k] = v
                elif isinstance(r, int):
                    dst[k] = clamp(v, -10 ** 9, 10 ** 9)
                elif isinstance(v, str):
                    v = v.strip()[:4000]
                    if (path.rstrip("."), k) in SECRET_FIELDS and not v:
                        continue                       # an empty secret means "keep what you have"
                    dst[k] = v

        was_on = cur["autopilot"]
        walk(cur, data, DEFAULT_SETTINGS, "")
        for section, key in SECRET_FIELDS:
            if isinstance(data.get(section), dict) and data[section].get(key + "_clear") is True:
                cur[section][key] = ""
        if cur["autopilot"] and not was_on:            # resuming: never touch what arrived during the pause
            for k in cur["since"]:
                cur["since"][k] = stamp
        self.check(cur)
        with self._lock:
            self.db.set("settings", cur)
            self._cache = cur
        if any(isinstance(data.get(sec), dict) and (data[sec].get(key + "_clear") is True or data[sec].get(key))
               for sec, key in SECRET_FIELDS):
            self.db.scrub()                            # a replaced or removed key does not linger in the journal
        return self.public()

    @staticmethod
    def check(s):
        lim = s["limits"]
        lim["per_hour"] = clamp(lim["per_hour"], 1, 200)
        lim["cooldown_min"] = clamp(lim["cooldown_min"], 0, 1440)
        lim["daily_posts"] = clamp(lim["daily_posts"], 1, 50)
        for k in ("quiet_from", "quiet_to"):
            lim[k] = lim[k].translate(_FA_DIGITS).strip()
            if lim[k] and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", lim[k]):
                raise UserError("ساعت سکوت را به شکل 23:00 بنویس.")
        if bool(lim["quiet_from"]) != bool(lim["quiet_to"]):
            raise UserError("برای ساعت سکوت، هم شروع و هم پایان را بنویس (یا هر دو را خالی بگذار).")
        if s["ai"]["mode"] not in ("free", "custom", "off"):
            s["ai"]["mode"] = "free"
        if s["media"]["method"] not in ("auto", "public", "tunnel", "temp"):
            s["media"]["method"] = "auto"
        if s["studio"]["image"] not in IMAGE_MODES:
            s["studio"]["image"] = "auto"
        handle = s["brand"]["handle"].strip().lstrip("@").strip()
        if handle and not re.fullmatch(r"[A-Za-z0-9._]{1,30}", handle):
            raise UserError("نام کاربری پیج فقط حروف انگلیسی، عدد، نقطه و زیرخط دارد (مثلاً my.page).")
        s["brand"]["handle"] = handle
        for section, key, label in (("ai", "url", "نشانی سرویس هوش مصنوعی"), ("media", "public_url", "نشانی عمومی"),
                                    ("studio", "url", "نشانی سرویس تصویر")):
            v = s[section][key]
            if v and not re.fullmatch(r"https?://[\x21-\x7e]+", v):
                raise UserError(label + " باید با http:// یا https:// شروع شود.")
            s[section][key] = v.rstrip("/")
        proxy = s["network"]["proxy"]
        if proxy:
            if "://" not in proxy:
                proxy = "http://" + proxy
            if not re.fullmatch(r"https?://[^\s/]+/?", proxy):
                raise UserError("پروکسی را به شکل http://127.0.0.1:10809 بنویس (فقط پروکسی HTTP پشتیبانی می‌شود).")
            s["network"]["proxy"] = proxy.rstrip("/")


# ───────────────────────────── Graph API client ─────────────────────────────

class GraphError(Exception):
    def __init__(self, message, code=0, subcode=0, status=0, kind="", user_msg=""):
        self.message = redact(message)
        super().__init__(self.message)
        self.code, self.subcode, self.status = int(code or 0), int(subcode or 0), int(status or 0)
        self.user_msg = redact(user_msg or "")
        self.kind = kind or self.classify()

    def classify(self):
        c, s = self.code, self.subcode
        if s in (2534022, 2018278, 2018108):
            return "window"
        if s == 2207027 or c == 9007:
            return "not_ready"
        if s in (2207006, 2207008, 2207020) or c == 24:
            return "expired"
        if s == 2207042 or c == 9:
            return "quota"
        if s in (2207050, 2207051) or c in (25, 368):
            return "blocked"
        if s in (2207003, 2207052) or c == 9004:
            return "fetch"
        if s in (2207001, 2207032, 2207053):
            return "transient"
        if s in (2207004, 2207005, 2207009, 2207010, 2207023, 2207026, 2207028, 2207035, 2207036, 2207037) \
                or 36000 <= c <= 36010:
            return "media"
        if c in (190, 102):
            return "auth"
        if c in (4, 17, 32, 613) or 80000 <= c <= 80014 or self.status == 429:
            return "throttle"
        if c in (3, 10) or 200 <= c <= 299:
            return "permission"
        if c == 100:
            return "param"
        if c in (1, 2) or self.status >= 500:
            return "transient"
        return "other"

    @property
    def transient(self):
        return self.kind in ("network", "transient", "throttle", "fetch", "not_ready", "quota")

    @property
    def fa(self):
        k, detail = self.kind, (self.user_msg or self.message)
        if k == "auth":
            why = {460: "رمز پیج عوض شده", 463: "مهلت توکن تمام شده", 467: "توکن باطل شده",
                   458: "دسترسی برنامه از پیج برداشته شده"}.get(self.subcode, "توکن معتبر نیست")
            return "اینستاگرام این توکن را نپذیرفت (%s). یک توکن تازه بساز و دوباره وصل شو." % why
        if k == "permission":
            return ("توکن اجازهٔ این کار را ندارد. هنگام ساختن توکن باید همهٔ دسترسی‌ها (انتشار، کامنت، پیام، آمار) "
                    "فعال باشد. برای دایرکت با عموم مردم، متا «Advanced Access» می‌خواهد.")
        if k == "window":
            return ("اینستاگرام اجازهٔ این پیام را نداد: از آخرین پیام این کاربر بیش از ۲۴ ساعت گذشته است "
                    "(یا برای این کامنت قبلاً یک پیام خصوصی فرستاده شده).")
        if k == "throttle":
            return "اینستاگرام موقتاً سقف درخواست‌ها را بسته است؛ ایجنت کمی بعد خودش دوباره تلاش می‌کند."
        if k == "blocked":
            return "اینستاگرام این کار را موقتاً برای پیج محدود کرده است. چند ساعت صبر کن."
        if k == "quota":
            return "سقف انتشار روزانهٔ اینستاگرام برای این پیج پر شده است."
        if k == "not_ready":
            return "فایل هنوز در اینستاگرام آماده نشده است."
        if k == "expired":
            return "مهلت این بارگذاری در اینستاگرام تمام شد."
        if k == "fetch":
            return "اینستاگرام نتوانست فایل را از لینک بردارد. لینک باید عمومی، مستقیم و در دسترس باشد."
        if "hashtag" in detail.lower() and k in ("media", "param", "other"):
            return ("اینستاگرام این تعداد هشتگ را نپذیرفت. چندتا را بردار (%s تا یا کمتر مطمئن است) و دوباره بفرست."
                    % fa(GOOD_HASHTAGS))
        if k == "media":
            return {2207004: "حجم فایل بیشتر از حد مجاز اینستاگرام است.",
                    2207005: "فرمت فایل پذیرفته نیست (عکس باید JPEG و ویدیو MP4 باشد).",
                    2207009: "نسبت تصویر مجاز نیست (باید بین ۴:۵ و ۱٫۹۱:۱ باشد).",
                    2207010: "کپشن بیش از حد بلند است یا هشتگ/منشن زیادی دارد.",
                    2207026: "فرمت ویدیو پذیرفته نیست (MP4 با کدک H.264 و صدای AAC)."
                    }.get(self.subcode, "اینستاگرام این فایل را نپذیرفت: " + detail)
        if k == "network":
            return "ارتباط با اینستاگرام برقرار نشد. اینترنت (و در صورت نیاز فیلترشکن/پروکسی) را بررسی کن."
        if k == "transient":
            return "سرور اینستاگرام موقتاً پاسخ نداد."
        return "اینستاگرام درخواست را نپذیرفت: " + detail


class Graph:
    """Small HTTP client for Meta's Graph API (and the few other services the agent talks to)."""

    def __init__(self, cfg, settings):
        self.cfg, self.settings = cfg, settings
        self.version = cfg.api_version
        self.token = ""
        self.calls = 0
        self.usage, self.usage_at = 0, 0.0
        self._opener, self._opener_key = None, None
        self._lock = threading.Lock()

    def opener(self):
        proxy = (self.settings.get("network.proxy") or self.cfg.proxy or "").strip()
        with self._lock:
            if self._opener is None or self._opener_key != proxy:
                if proxy:
                    handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy})]
                elif self.cfg.sim:
                    handlers = [urllib.request.ProxyHandler({})]
                else:
                    handlers = []
                self._opener = urllib.request.build_opener(*handlers)
                self._opener.addheaders = [("User-Agent", "insta-agent/" + VERSION)]
                self._opener_key = proxy
            return self._opener

    def http(self, method, url, data=None, headers=None, timeout=30):
        req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
        try:
            with self.opener().open(req, timeout=timeout) as res:
                return res.status, {k.lower(): v for k, v in res.headers.items()}, res.read()
        except urllib.error.HTTPError as e:
            try:
                body = e.read()
            except Exception:
                body = b""
            return e.code, {k.lower(): v for k, v in (e.headers.items() if e.headers else [])}, body
        except (urllib.error.URLError, socket.timeout, ssl.SSLError, http.client.HTTPException, OSError) as e:
            raise GraphError("network: %s" % e, kind="network")

    def track_usage(self, headers):
        top = 0

        def walk(node):
            nonlocal top
            if isinstance(node, dict):
                for k, v in node.items():
                    if k in ("call_count", "total_cputime", "total_time") and isinstance(v, (int, float)):
                        top = max(top, int(v))
                    else:
                        walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        for name in ("x-business-use-case-usage", "x-app-usage"):
            walk(jload(headers.get(name), None))
        if top:
            self.usage, self.usage_at = top, now()

    def busy(self):
        return self.usage >= 85 and now() - self.usage_at < 900

    def call(self, method, path, params=None, base=None, token=None, body=None, timeout=30, version=None, _again=False):
        root = (base or self.cfg.ig_graph).rstrip("/")
        ver = self.version if version is None else version
        url = root + ("/" + ver if ver else "") + "/" + str(path).lstrip("/")
        used = token or self.token
        q = {}
        for k, v in (params or {}).items():
            if v is None:
                continue
            q[k] = jdump(v) if isinstance(v, (dict, list)) else ("true" if v is True else "false" if v is False else str(v))
        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            headers["Authorization"] = "Bearer " + used
            data = jdump(body).encode("utf-8")
            if q:
                url += "?" + urllib.parse.urlencode(q)
        else:
            q["access_token"] = used
            if method in ("GET", "DELETE"):
                url += "?" + urllib.parse.urlencode(q)
            else:
                data = urllib.parse.urlencode(q).encode("utf-8")
                headers["Content-Type"] = "application/x-www-form-urlencoded"
        self.calls += 1
        status, hdrs, raw = self.http(method, url, data, headers, timeout)
        self.track_usage(hdrs)
        parsed = jload(raw.decode("utf-8", "replace"), None)
        if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
            e = parsed["error"]
            err = GraphError(e.get("message") or "error", e.get("code"), e.get("error_subcode"), status,
                             user_msg=e.get("error_user_msg") or "")
            if err.kind == "auth" and not token and not _again and self.token and self.token != used:
                return self.call(method, path, params, base, None, body, timeout, version, True)   # token was renewed meanwhile
            raise err
        if status >= 400 or not isinstance(parsed, (dict, list)):
            soft = status < 400 or status >= 500 or status in (408, 429)
            raise GraphError("HTTP %s" % status, status=status, kind="transient" if soft else "other")
        return parsed


PROFILE_FIELDS = ["user_id,username,name,account_type,profile_picture_url,followers_count,follows_count,media_count,"
                  "biography,website", "user_id,username,name,account_type,media_count", "id,username"]
FB_PROFILE_FIELDS = "id,username,name,profile_picture_url,followers_count,follows_count,media_count,biography,website"
MEDIA_FIELDS = ["id,caption,media_type,media_product_type,media_url,thumbnail_url,permalink,timestamp,like_count,"
                "comments_count", "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp"]
COMMENT_FIELDS = ["id,text,timestamp,username,from,hidden,parent_id,like_count", "id,text,timestamp,username,hidden,parent_id",
                  "id,text,timestamp,username"]
MESSAGE_FIELDS = ["id,created_time,from,to,message,attachments", "id,created_time,from,to,message", "id,created_time,from,message"]
CONV_FIELDS = ["id,updated_time,participants", "id,updated_time"]
ACCOUNT_METRICS = ["reach", "views", "accounts_engaged", "total_interactions", "likes", "comments", "shares", "saves",
                   "replies", "profile_links_taps"]
MEDIA_METRICS = {"FEED": ["reach", "views", "likes", "comments", "saved", "shares", "total_interactions"],
                 "REELS": ["reach", "views", "likes", "comments", "saved", "shares", "total_interactions"],
                 "STORY": ["reach", "views", "shares", "replies", "total_interactions"]}


def insight_value(row):
    total = row.get("total_value")
    if isinstance(total, dict) and isinstance(total.get("value"), (int, float)):
        return int(total["value"])
    out = 0
    for v in row.get("values") or []:
        if isinstance(v, dict) and isinstance(v.get("value"), (int, float)):
            out += int(v["value"])
    return out


class Instagram:
    """Everything the agent asks from Instagram, as plain methods."""

    def __init__(self, cfg, db, graph):
        self.cfg, self.db, self.graph = cfg, db, graph
        self.good = {}                                 # which field list worked last time, per kind of call

    # ── account ──
    @property
    def acct(self):
        return self.db.get("account") or {}

    def save_acct(self, **changes):
        a = self.acct
        a.update(changes)
        self.db.set("account", a)
        return a

    @property
    def connected(self):
        return bool(self.acct.get("ig_id")) and bool(self.graph.token)

    def base(self):
        return self.cfg.fb_graph if self.acct.get("login") == "fb" else self.cfg.ig_graph

    def me(self):
        return self.acct.get("ig_id") or "me"

    def inbox_owner(self):
        a = self.acct
        return a.get("page_id") if a.get("login") == "fb" else a.get("ig_id")

    def call(self, method, path, params=None, body=None, timeout=30):
        return self.graph.call(method, path, params, base=self.base(), body=body, timeout=timeout)

    def versions(self):
        seen, out = set(), []
        for v in [self.cfg.api_version] + API_VERSIONS:
            if v not in seen:
                seen.add(v)
                out.append(v)
        return out

    def connect(self, token):
        """Checks a pasted token and returns (account, token to store). Nothing is saved here."""
        token = re.sub(r"\s+", "", str(token or "")).strip("\"'")
        if len(token) < 30 or not re.fullmatch(r"[A-Za-z0-9_\-|.]+", token):
            raise UserError("این متن شبیه توکن نیست. توکن یک رشتهٔ بلند انگلیسی است که معمولاً با IGAA شروع می‌شود.")
        fb = token.startswith("EAA")
        last = None
        for ver in self.versions():
            for fields in ([FB_PROFILE_FIELDS] if fb else PROFILE_FIELDS):
                try:
                    return self._connect_fb(token, ver) if fb else self._connect_ig(token, ver, fields)
                except GraphError as e:
                    last = e
                    if e.kind in ("auth", "permission", "network", "throttle", "transient"):
                        raise
                    if e.kind != "param":
                        break                          # this API version is not available → next one
        raise last

    def _connect_ig(self, token, ver, fields):
        d = self.graph.call("GET", "me", {"fields": fields}, base=self.cfg.ig_graph, token=token, version=ver)
        ig_id = str(d.get("user_id") or d.get("id") or "")
        if not ig_id:
            raise GraphError("profile without id", kind="other")
        acct = {"login": "ig", "ig_id": ig_id, "scoped_id": str(d.get("id") or ""), "page_id": "", "version": ver,
                "fields": fields}
        acct.update(self._profile(d))
        return acct, token

    def _connect_fb(self, token, ver):
        d = self.graph.call("GET", "me/accounts", {"fields": "id,name,access_token,instagram_business_account{id,username}",
                                                   "limit": 100}, base=self.cfg.fb_graph, token=token, version=ver)
        pages = [p for p in d.get("data") or [] if p.get("instagram_business_account") and p.get("access_token")]
        if not pages:
            raise UserError("با این توکن فیسبوکی صفحه‌ای که به یک پیج اینستاگرام وصل باشد پیدا نشد. "
                            "ساده‌تر است از توکن «Instagram Login» (که با IGAA شروع می‌شود) استفاده کنی.")
        page = pages[0]
        ig_id, page_token = str(page["instagram_business_account"]["id"]), page["access_token"]
        prof = self.graph.call("GET", ig_id, {"fields": FB_PROFILE_FIELDS}, base=self.cfg.fb_graph, token=page_token,
                               version=ver)
        acct = {"login": "fb", "ig_id": ig_id, "scoped_id": "", "page_id": str(page["id"]), "version": ver,
                "fields": FB_PROFILE_FIELDS}
        acct.update(self._profile(prof))
        return acct, page_token

    @staticmethod
    def _profile(d):
        out = {"username": d.get("username") or "", "name": d.get("name") or "",
               "account_type": d.get("account_type") or "", "picture": d.get("profile_picture_url") or "",
               "bio": d.get("biography") or "", "website": d.get("website") or ""}
        for src, dst in (("followers_count", "followers"), ("follows_count", "follows"), ("media_count", "media_count")):
            if d.get(src) is not None:
                out[dst] = int(d.get(src) or 0)
        return out

    def refresh_profile(self):
        a = self.acct
        if a.get("login") == "fb":
            d = self.call("GET", a["ig_id"], {"fields": FB_PROFILE_FIELDS})
        else:
            d = self.call("GET", "me", {"fields": a.get("fields") or PROFILE_FIELDS[0]})
        return self.save_acct(**{k: v for k, v in self._profile(d).items() if v not in ("", None)})

    def refresh_token(self):
        if self.acct.get("login") != "ig":
            raise UserError("توکن فیسبوکی تمدید خودکار ندارد؛ هر وقت باطل شد توکن تازه بده.")
        d = self.graph.call("GET", "refresh_access_token", {"grant_type": "ig_refresh_token"}, base=self.cfg.ig_graph,
                            version="")
        token = d.get("access_token")
        if not token:
            raise GraphError("refresh answer without a token", kind="other")
        self.graph.token = token
        self.db.set("secret.token", token)
        return self.save_acct(token_at=now(), token_expires=now() + int(d.get("expires_in") or 5184000))

    # ── content ──
    def _fields_call(self, path, field_sets, extra, key, make=None):
        """One field the token may not read fails the whole call, so the request steps down to a shorter list
        (and remembers which one worked)."""
        last = None
        for i in range(min(self.good.get(key, 0), len(field_sets) - 1), len(field_sets)):
            try:
                params = dict(extra)
                params["fields"] = make(field_sets[i]) if make else field_sets[i]
                out = self.call("GET", path, params)
                self.good[key] = i
                return out
            except GraphError as e:
                last = e
                if e.kind != "param":
                    raise
        raise last

    def media(self, limit=30):
        return self._fields_call("%s/media" % self.me(), MEDIA_FIELDS, {"limit": limit}, "media").get("data") or []

    def stories(self):
        return self._fields_call("%s/stories" % self.me(), MEDIA_FIELDS[1:], {}, "stories").get("data") or []

    def media_info(self, media_id):
        return self._fields_call(media_id, MEDIA_FIELDS, {}, "media")

    def create_container(self, params):
        return str(self.call("POST", "%s/media" % self.me(), params, timeout=90)["id"])

    def container_status(self, container_id):
        d = self.call("GET", container_id, {"fields": "status_code,status"})
        return str(d.get("status_code") or "").upper(), str(d.get("status") or "")

    def publish(self, container_id):
        """Returns (media id, config_issue). The second is set when Instagram published the post but left a part out."""
        d = self.call("POST", "%s/media_publish" % self.me(), {"creation_id": container_id}, timeout=90)
        return str(d["id"]), str(d.get("config_issue") or "")

    def quota(self):
        d = self.call("GET", "%s/content_publishing_limit" % self.me(), {"fields": "quota_usage,config"})
        row = (d.get("data") or [{}])[0]
        return int(row.get("quota_usage") or 0), int((row.get("config") or {}).get("quota_total") or 50)

    # ── comments ──
    def comments(self, media_id, limit=50):
        d = self._fields_call("%s/comments" % media_id, COMMENT_FIELDS, {"limit": limit}, "comments",
                              lambda f: "%s,replies.limit(25){%s}" % (f, f))
        return d.get("data") or [], bool((d.get("paging") or {}).get("next"))

    def reply(self, comment_id, text):
        return str(self.call("POST", "%s/replies" % comment_id, {"message": text}).get("id") or "")

    def comment_on(self, media_id, text):
        return str(self.call("POST", "%s/comments" % media_id, {"message": text}).get("id") or "")

    def hide(self, comment_id, hide=True):
        self.call("POST", comment_id, {"hide": bool(hide)})

    def delete_comment(self, comment_id):
        self.call("DELETE", comment_id)

    def set_comments(self, media_id, enabled):
        self.call("POST", media_id, {"comment_enabled": bool(enabled)})

    # ── direct messages ──
    def conversations(self, limit=25):
        d = self._fields_call("%s/conversations" % self.inbox_owner(), CONV_FIELDS, {"platform": "instagram", "limit": limit},
                              "convs")
        return d.get("data") or []

    def messages(self, conv_id, limit=20, known=()):
        """The newest messages of one chat, newest first. They are asked for in a single call; if Instagram refuses
        that form, the longer way from Meta's guide is used from then on: the list of message ids first, then each
        message that is not stored yet (`known`) on its own. Only the 20 newest can be read that way."""
        if not self.good.get("messages_one_by_one"):
            try:
                d = self._fields_call(conv_id, MESSAGE_FIELDS, {}, "messages",
                                      lambda f: "messages.limit(%d){%s}" % (limit, f))
                return (d.get("messages") or {}).get("data") or []
            except GraphError as e:
                if e.kind != "param":
                    raise
        d = self.call("GET", conv_id, {"fields": "messages"})        # (fails too when the chat itself is the problem)
        self.good["messages_one_by_one"] = 1
        out = []
        for row in ((d.get("messages") or {}).get("data") or [])[:min(limit, 20)]:
            mid = str(row.get("id") or "")
            if not mid or mid in known:
                continue
            try:
                out.append(self._fields_call(mid, MESSAGE_FIELDS, {}, "message"))
            except GraphError as e:
                if e.kind != "param":
                    raise                              # (a single unreadable message is skipped)
        return out

    def send(self, recipient, text):
        return self.call("POST", "%s/messages" % self.inbox_owner(), body={"recipient": recipient, "message": {"text": text}})

    # ── insights ──
    def _metrics(self, path, metrics, extra):
        out = {}

        def fetch(names):
            params = dict(extra)
            params["metric"] = ",".join(names)
            for row in self.call("GET", path, params).get("data") or []:
                out[row.get("name")] = insight_value(row)

        try:
            fetch(metrics)
        except GraphError as e:
            if e.kind != "param":
                raise
            for name in metrics:                       # one unsupported metric fails the whole call → ask one by one
                try:
                    fetch([name])
                except GraphError as e2:
                    if e2.kind not in ("param", "permission"):
                        raise
        return out

    def account_insights(self, since, until):
        return self._metrics("%s/insights" % self.me(), ACCOUNT_METRICS,
                             {"period": "day", "metric_type": "total_value", "since": int(since), "until": int(until)})

    def media_insights(self, media_id, product="FEED"):
        return self._metrics("%s/insights" % media_id, MEDIA_METRICS.get(product, MEDIA_METRICS["FEED"]), {})

    def demographics(self, breakdown):
        d = self.call("GET", "%s/insights" % self.me(), {"metric": "follower_demographics", "period": "lifetime",
                                                          "metric_type": "total_value", "timeframe": "this_month",
                                                          "breakdown": breakdown})
        rows = []
        for row in d.get("data") or []:
            for b in (row.get("total_value") or {}).get("breakdowns") or []:
                for r in b.get("results") or []:
                    rows.append({"name": " ".join(str(x) for x in r.get("dimension_values") or []),
                                 "value": int(r.get("value") or 0)})
        return sorted(rows, key=lambda r: -r["value"])


# ───────────────────────────── media files & public links ─────────────────────────────

def sniff(head):
    """(kind, extension, mime) from the first bytes of a file, or None."""
    if head[:3] == b"\xff\xd8\xff":
        return "image", "jpg", "image/jpeg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image", "png", "image/png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image", "webp", "image/webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "image", "gif", "image/gif"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"mif1", b"msf1", b"heif", b"avif"):
            return "image", "heic", "image/heic"
        if brand[:2] == b"qt":
            return "video", "mov", "video/quicktime"
        return "video", "mp4", "video/mp4"
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return "video", "webm", "video/webm"          # what some browsers record; fine for the gallery, not for the API
    return None


def image_size(path):
    try:
        with open(path, "rb") as fh:
            head = fh.read(30)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", head[16:24])
                return int(w), int(h)
            if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                form = head[12:16]
                if form == b"VP8X":
                    return 1 + int.from_bytes(head[24:27], "little"), 1 + int.from_bytes(head[27:30], "little")
                if form == b"VP8L":
                    bits = int.from_bytes(head[21:25], "little")
                    return 1 + (bits & 0x3FFF), 1 + ((bits >> 14) & 0x3FFF)
                if form == b"VP8 ":
                    return int.from_bytes(head[26:28], "little") & 0x3FFF, int.from_bytes(head[28:30], "little") & 0x3FFF
                return 0, 0
            if head[:2] != b"\xff\xd8":
                return 0, 0
            fh.seek(2)
            while True:
                byte = fh.read(1)
                if not byte:
                    return 0, 0
                if byte != b"\xff":
                    continue
                marker = fh.read(1)
                while marker == b"\xff":
                    marker = fh.read(1)
                if not marker:
                    return 0, 0
                m = marker[0]
                if m in (0x00, 0x01, 0xD8) or 0xD0 <= m <= 0xD7:
                    continue
                if m in (0xD9, 0xDA):
                    return 0, 0
                size = struct.unpack(">H", fh.read(2))[0]
                if m in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    data = fh.read(5)
                    h, w = struct.unpack(">HH", data[1:5])
                    return int(w), int(h)
                fh.seek(size - 2, 1)
    except (OSError, struct.error, IndexError):
        return 0, 0


class Tunnel:
    """Runs `cloudflared` so Instagram can fetch a file straight from this device (media port only)."""
    URL_RE = re.compile(r"https://[A-Za-z0-9-]+\.trycloudflare\.com")

    def __init__(self, cfg, graph):
        self.cfg, self.graph = cfg, graph
        self.proc, self.url, self.ready = None, "", False
        self.started = self.used = 0.0
        self.lock = threading.Lock()

    def command(self, port):
        if self.cfg.tunnel_cmd:
            cmd = self.cfg.tunnel_cmd.replace("{port}", str(port))
            if os.name == "nt":                        # keep the backslashes of Windows paths
                return [part.strip('"') for part in shlex.split(cmd, posix=False)]
            return shlex.split(cmd)
        exe = shutil.which("cloudflared")
        return [exe, "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:%d" % port] if exe else None

    def available(self):
        return bool(self.cfg.tunnel_cmd or shutil.which("cloudflared"))

    def ensure(self, port):
        with self.lock:
            self.used = now()
            if self.proc is not None and self.proc.poll() is not None:
                self.proc, self.url, self.ready = None, "", False
            if self.proc is None:
                cmd = self.command(port)
                if not cmd:
                    raise UserError("برنامهٔ cloudflared نصب نیست. در ترموکس بزن: pkg install cloudflared")
                try:
                    self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                                 stdin=subprocess.DEVNULL)
                except OSError as e:
                    raise UserError("اجرای cloudflared ممکن نشد: %s" % e)
                self.started, self.url, self.ready = now(), "", False
                threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
            if self.ready:
                return self.url
            url, age = self.url, now() - self.started
        if url:
            try:
                status, _, body = self.graph.http("GET", url + "/healthz", timeout=8)
                if status == 200 and body.strip() == b"ok":
                    self.ready = True
                    return url
            except GraphError:
                pass
        if age > 120:
            self.stop()
            raise UserError("تونل cloudflared بالا نیامد (اینترنت یا فیلترشکن را بررسی کن).")
        raise NotReady("در حال ساختن لینک عمومی برای فایل…")

    def _read(self, proc):
        try:
            for raw in iter(proc.stdout.readline, b""):
                m = self.URL_RE.search(raw.decode("utf-8", "replace"))
                if m and not self.url:
                    self.url = m.group(0)
        except (OSError, ValueError):
            pass

    def stop(self):
        with self.lock:
            proc, self.proc, self.url, self.ready = self.proc, None, "", False
        if proc is None:
            return
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass
        try:
            proc.stdout.close()
        except Exception:
            pass

    def idle_check(self):
        if self.proc is not None and now() - self.used > 900:
            self.stop()


class MediaStore:
    def __init__(self, cfg, db, settings, graph):
        self.cfg, self.db, self.settings, self.graph = cfg, db, settings, graph
        self.dir = os.path.join(cfg.data_dir, "media")
        os.makedirs(self.dir, exist_ok=True)
        self.tunnel = Tunnel(cfg, graph)
        self.media_port = 0

    def get(self, fid):
        return self.db.one("SELECT * FROM files WHERE id=?", (str(fid),))

    def path(self, f):
        return os.path.join(self.dir, "%s.%s" % (f["id"], f["ext"]))

    @staticmethod
    def view(f):
        return {"id": f["id"], "type": f["kind"], "width": f["width"], "height": f["height"], "size": f["size"],
                "preview": "/api/file/" + f["id"]}

    def add(self, tmp_path, name=""):
        """Takes a finished upload (a temp file inside the media folder) and registers it."""
        try:
            with open(tmp_path, "rb") as fh:
                found = sniff(fh.read(64))
            size = os.path.getsize(tmp_path)
            if not found:
                raise UserError("این فایل عکس یا ویدیوی قابل‌قبول نیست (عکس JPEG یا ویدیو MP4/MOV).")
            kind, ext, mime = found
            if kind == "image" and ext != "jpg":
                raise UserError("اینستاگرام فقط عکس JPEG می‌پذیرد. پنل خودش تبدیل می‌کند؛ صفحه را تازه کن و دوباره انتخاب کن.")
            if kind == "image" and size > IMAGE_MAX:
                raise UserError("حجم عکس بیش از ۸ مگابایت است.")
            if size > VIDEO_MAX:
                raise UserError("حجم ویدیو بیش از ۳۰۰ مگابایت است.")
            fid = secrets.token_hex(12)
            final = os.path.join(self.dir, "%s.%s" % (fid, ext))
            os.replace(tmp_path, final)
        except UserError:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise
        w, h = image_size(final) if kind == "image" else (0, 0)
        self.db.x("INSERT INTO files (id, ext, mime, kind, size, width, height, name, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                  (fid, ext, mime, kind, size, w, h, str(name or "")[:200], now()))
        return self.get(fid)

    def add_asset(self, raw, name=""):
        """A picture the studio fetched, in whatever format it came. The panel draws the final image from it;
        it is never published as it is and, like every unused file, it is removed after a day."""
        found = sniff(raw[:64])
        if not found or found[0] != "image":
            raise UserError("این فایل عکس نیست.")
        fid = secrets.token_hex(12)
        final = os.path.join(self.dir, "%s.%s" % (fid, found[1]))
        with open(final, "wb") as fh:
            fh.write(raw)
        w, h = image_size(final)
        self.db.x("INSERT INTO files (id, ext, mime, kind, size, width, height, name, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                  (fid, found[1], found[2], "asset", len(raw), w, h, str(name or "")[:200], now()))
        return self.get(fid)

    def methods(self):
        m = self.settings.all()["media"]
        public = (m["public_url"] or self.cfg.public_url).rstrip("/")
        out = {"method": m["method"], "public": bool(public), "tunnel": self.tunnel.available(), "temp": bool(m["temp_ok"]),
               "tunnel_up": self.tunnel.ready}
        out["ready"] = bool(self.cfg.sim or out["public"] or out["tunnel"] or out["temp"] or m["method"] == "temp")
        return out

    def public_url(self, f):
        """A link Instagram's servers can download the file from."""
        name = "%s.%s" % (f["id"], f["ext"])
        m = self.settings.all()["media"]
        method = m["method"]
        public = (m["public_url"] or self.cfg.public_url).rstrip("/")
        if not public and self.cfg.sim and method == "auto":
            public = "http://127.0.0.1:%d" % self.media_port
        if method in ("auto", "public") and public:
            return public + "/m/" + name
        if method in ("auto", "tunnel") and self.tunnel.available():
            return self.tunnel.ensure(self.media_port) + "/m/" + name
        if method == "temp" or (method == "auto" and m["temp_ok"]):
            return self.temp_url(f)
        raise UserError("اینستاگرام فایل را خودش از اینترنت برمی‌دارد و هنوز راهی برای لینک عمومی تنظیم نشده. "
                        "ساده‌ترین راه در ترموکس: pkg install cloudflared — یا در «ایجنت ← تنظیمات ← لینک عمومی» "
                        "میزبان موقت را روشن کن.")

    def temp_url(self, f):
        if f["temp_url"] and f["temp_until"] > now() + 300:
            return f["temp_url"]
        boundary = "----ia" + secrets.token_hex(12)
        with open(self.path(f), "rb") as fh:
            blob = fh.read()

        def field(name, value):
            return ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, name, value)).encode()

        body = b"".join([field("reqtype", "fileupload"), field("time", "1h"),
                         ("--%s\r\nContent-Disposition: form-data; name=\"fileToUpload\"; filename=\"%s.%s\"\r\n"
                          "Content-Type: %s\r\n\r\n" % (boundary, f["id"][:12], f["ext"], f["mime"])).encode(),
                         blob, ("\r\n--%s--\r\n" % boundary).encode()])
        status, _, raw = self.graph.http("POST", self.cfg.temp_host, body,
                                         {"Content-Type": "multipart/form-data; boundary=" + boundary}, timeout=300)
        url = raw.decode("utf-8", "replace").strip()
        local = url.startswith("http://127.0.0.1:") and self.cfg.sim
        if status != 200 or not (re.fullmatch(r"https://[\x21-\x7e]+", url) or local):
            raise GraphError("temp host answered HTTP %s" % status, status=status, kind="transient")
        self.db.x("UPDATE files SET temp_url=?, temp_until=? WHERE id=?", (url, now() + 3300, f["id"]))
        return url

    def cleanup(self):
        used = set()
        for r in self.db.q("SELECT media, status, published_at FROM posts"):
            if r["status"] == "published" and r["published_at"] < now() - 7 * 86400:
                continue
            for m in jload(r["media"], []):
                if m.get("file"):
                    used.add(m["file"])
        for f in self.db.q("SELECT * FROM files WHERE created_at<?", (now() - 86400,)):
            if f["id"] not in used:
                try:
                    os.remove(self.path(f))
                except OSError:
                    pass
                self.db.x("DELETE FROM files WHERE id=?", (f["id"],))
        try:
            for name in os.listdir(self.dir):
                full = os.path.join(self.dir, name)
                if name.endswith(".part") and os.path.getmtime(full) < now() - 3600:
                    os.remove(full)
        except OSError:
            pass
        self.tunnel.idle_check()


# ───────────────────────────── writing assistant ─────────────────────────────

class AIDown(Exception):
    """The text service gave no usable answer. wait > 0: it asked to come back after that many seconds."""

    def __init__(self, why="", wait=0.0):
        super().__init__(why)
        self.wait = max(0.0, float(wait or 0))


class AI:
    FREE_URL = "https://text.pollinations.ai/openai"

    def __init__(self, cfg, settings, graph, ig):
        self.cfg, self.settings, self.graph, self.ig = cfg, settings, graph, ig
        self.free_at = 0.0                             # when the free service takes the next question from this address

    def endpoint(self):
        """(address, key, model, kind) of the text service in use, or None when it is switched off."""
        s = self.settings.all()
        ai, pollen = s["ai"], s["studio"]["pollen"]
        if ai["mode"] == "off":
            return None
        if ai["mode"] == "custom" and ai["url"]:
            return ai["url"], ai["key"], ai["model"] or "gpt-4o-mini", "custom"
        if self.cfg.ai_url:                            # AGENT_AI_URL: an own service that needs no key
            return self.cfg.ai_url, "", ai["model"] or "openai", "custom"
        if pollen:                                     # the owner's Pollinations key: better models, no waiting
            return self.cfg.gen_api + "/v1/chat/completions", pollen, ai["model"], "pollen"
        if self.cfg.sim and self.FREE_URL == AI.FREE_URL:
            return None                                # demo and tests never call out
        return self.FREE_URL, "", "openai-fast", "free"

    def mode(self):
        ep = self.endpoint()
        return ep[3] if ep else "off"

    def ask(self, system, user, history=None, max_tokens=700):
        ep = self.endpoint()
        if not ep:
            raise AIDown("off")
        url, key, model, kind = ep
        if kind == "free" and now() < self.free_at:
            raise AIDown("limit", self.free_at - now())
        if not url.rstrip("/").endswith(("/chat/completions", "/openai")):
            url = url.rstrip("/") + "/chat/completions"
        messages = [{"role": "system", "content": system}] + list(history or []) + [{"role": "user", "content": user}]
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        payload = {"messages": messages, "max_tokens": max_tokens}
        if model:
            payload["model"] = model
        if kind != "pollen":                           # its default model takes no temperature
            payload["temperature"] = 0.8
        if kind == "free":
            payload["seed"] = random.randint(1, 2 ** 31 - 1)      # the same question must not come back from a shared cache
        try:
            status, hdrs, body = self.graph.http("POST", url, jdump(payload).encode("utf-8"), headers, timeout=45)
        except GraphError as e:
            raise AIDown(str(e))
        raw = body.decode("utf-8", "replace")
        data = jload(raw, None)
        if status in (402, 429, 503) and kind == "free":
            m = re.search(r"(?:retry after|wait)\s+(\d+)\s*s", raw, re.I)
            after = str(hdrs.get("retry-after") or "")
            wait = int(m.group(1)) if m else int(after) if after.isdigit() else self.cfg.free_gap
            self.free_at = now() + wait
            raise AIDown("limit", wait)
        try:
            if status >= 400:
                raise KeyError(status)
            text = data["choices"][0]["message"]["content"]
        except (TypeError, KeyError, IndexError):
            raise AIDown("HTTP %s" % status)
        text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
        if not text:
            raise AIDown("empty answer")
        if kind == "free":
            self.free_at = now() + self.cfg.free_gap
        return text

    @staticmethod
    def offline(e, **extra):
        """What the panel is told when templates stand in for the assistant (and how long the free service asks to wait)."""
        wait = int(getattr(e, "wait", 0) + 0.999)
        return dict(extra, source="offline", **({"wait": wait} if wait else {}))

    def persona(self):
        b, a = self.settings.all()["brand"], self.ig.acct
        return ("تو دستیار مدیریت یک پیج اینستاگرام هستی. نام پیج: @%s (%s). دربارهٔ پیج: %s. لحن نوشتن: %s. "
                "فارسی روان و طبیعی بنویس؛ کوتاه و بدون مقدمه و توضیح اضافه. چیزی را که نمی‌دانی از خودت نساز."
                % (a.get("username") or b["handle"] or "page", a.get("name") or "", b["about"] or a.get("bio") or "نامشخص", b["tone"]))

    def brand_tags(self):
        out = []
        for raw in re.split(r"[\s,،]+", self.settings.all()["brand"]["hashtags"]):
            raw = raw.strip().lstrip("#")
            if raw:
                out.append("#" + raw)
        return out

    def offline_hashtags(self, topic):
        words = [w for w in re.findall(r"[\w\u200c]+", topic or "", flags=re.UNICODE) if len(w) >= 3][:6]
        out = list(self.brand_tags())
        if len(words) >= 2:
            out.append("#" + "_".join(words[:3]).replace("\u200c", "_"))
        out += ["#" + w.replace("\u200c", "_") for w in words]
        out += ["#پیشنهاد_ویژه", "#روزمرگی", "#معرفی", "#ایده", "#اینستاگرام"]
        seen, uniq = set(), []
        for tag in out:
            if norm(tag) not in seen:
                seen.add(norm(tag))
                uniq.append(tag)
        return uniq[:15]

    def captions(self, topic, kind="image"):
        topic = str(topic or "").strip()[:500]
        if not topic:
            raise UserError("بنویس پست دربارهٔ چیست.")
        try:
            text = self.ask(self.persona(),
                            "برای یک %s اینستاگرام با موضوع «%s» سه کپشن متفاوت بنویس: کوتاه، معمولی، و داستانی. "
                            "هر کپشن با ۳ تا ۵ هشتگ مرتبط تمام شود (نه بیشتر). بین کپشن‌ها فقط یک خط شامل === بگذار و هیچ "
                            "توضیح، شماره یا عنوانی ننویس." % (KIND_FA.get(kind, "پست"), topic))
            items = [re.sub(r"^\s*(کپشن\s*)?[\d۰-۹]+\s*[\.\):\-]\s*", "", p.strip()) for p in re.split(r"\n\s*={3,}\s*\n?", text)]
            items = [limit_tags(i) for i in items if i][:5]
            if items:
                return {"items": items, "source": "ai"}
            down = None
        except AIDown as e:
            down = e
        tail = " ".join(self.offline_hashtags(topic)[:5])
        return self.offline(down, items=[
            "%s ✨\n\n%s" % (topic, tail),
            "%s\n\nنظر شما چیه؟ توی کامنت‌ها برامون بنویسید 👇\n\n%s" % (topic, tail),
            "یه خبر خوب: %s 🌿\nاگه دوست داشتید برای دوستاتون هم بفرستید.\n\n%s" % (topic, tail)])

    def hashtags(self, topic):
        topic = str(topic or "").strip()[:500]
        try:
            text = self.ask(self.persona(), "برای پستی با موضوع «%s» ده هشتگ فارسی و انگلیسی دقیق و مرتبط پیشنهاد بده "
                                            "(نه هشتگ‌های کلی مثل #explore). فقط هشتگ‌ها را با فاصله بنویس."
                            % (topic or "معرفی پیج"), max_tokens=300)
            tags = []
            for t in re.findall(r"#[^\s#،,]+", text):
                if norm(t) not in [norm(x) for x in tags]:
                    tags.append(t)
            if len(tags) >= 3:
                return {"items": tags[:12], "source": "ai"}
            down = None
        except AIDown as e:
            down = e
        return self.offline(down, items=self.offline_hashtags(topic)[:12])

    def ideas(self, count=6):
        about = self.settings.all()["brand"]["about"] or "پیج"
        try:
            text = self.ask(self.persona(), "%d ایدهٔ کوتاه و عملی برای پست یا ریل این پیج بده. هر ایده در یک خط، "
                                            "بدون شماره." % count, max_tokens=500)
            items = [re.sub(r"^\s*[\-\*•\d۰-۹\.\)]+\s*", "", ln).strip() for ln in text.splitlines()]
            items = [i for i in items if len(i) > 8][:count]
            if items:
                return {"items": items, "source": "ai"}
            down = None
        except AIDown as e:
            down = e
        base = ["پشت‌صحنهٔ یک روز کاری: از صبح تا شب در چند عکس", "معرفی پرطرفدارترین محصول یا خدمت و دلیل محبوبیتش",
                "پاسخ به سه سؤال پرتکرار مشتری‌ها در یک پست چندتایی", "قبل و بعد: نتیجهٔ یک کار واقعی را نشان بده",
                "یک نکتهٔ آموزشی کوتاه که مخاطب همین امروز به کارش بیاید", "نظر یک مشتری راضی (با اجازهٔ خودش)",
                "نظرسنجی در استوری: از مخاطب بپرس چه چیزی دوست دارد ببیند", "داستان شروع کار: %s چطور راه افتاد؟" % about]
        random.shuffle(base)
        return self.offline(down, items=base[:count])

    @staticmethod
    def offline_reply(text):
        n = norm(text)
        if any(w in n for w in ("قیمت", "چنده", "هزینه", "چند تومن", "چقدر")):
            return "سلام 🌹 ممنون از توجه‌تون. برای قیمت لطفاً دایرکت پیام بدید تا کامل راهنمایی کنیم."
        if any(w in n for w in ("ادرس", "کجاست", "کجایید", "لوکیشن")):
            return "سلام 🌹 آدرس و راه‌های ارتباطی در بیوی پیج هست."
        if any(w in n for w in ("ممنون", "مرسی", "عالی", "قشنگ", "دمتون", "عاشق")):
            return "ممنون از محبت‌تون 🙏🌹"
        if "؟" in str(text) or "?" in str(text):
            return "سلام 🌹 ممنون از پیام‌تون؛ به‌زودی کامل پاسخ می‌دیم."
        return "ممنون که همراه ما هستید 🌹"

    def reply(self, text, context="", kind="comment"):
        try:
            out = self.ask(self.persona() + " فقط متن پاسخ را بنویس: حداکثر دو جمله، بدون نقل‌قول.",
                           "%s زیر را یک کاربر نوشته است:\n«%s»\n%sیک پاسخ مؤدبانه و مفید بنویس. اگر اطلاعات لازم "
                           "(مثل قیمت دقیق یا موجودی) را نداری حدس نزن؛ بگو در دایرکت راهنمایی می‌کنیم."
                           % ("کامنت" if kind == "comment" else "پیام", str(text)[:600],
                              ("متن پست: «%s»\n" % context[:400]) if context else ""), max_tokens=220)
            return {"text": out.strip().strip("«»\"'")[:900], "source": "ai"}
        except AIDown as e:
            return self.offline(e, text=self.offline_reply(text))

    def chat(self, history, facts):
        history = [{"role": "assistant" if m.get("role") == "assistant" else "user", "content": str(m.get("content") or "")[:2000]}
                   for m in (history if isinstance(history, list) else []) if isinstance(m, dict) and m.get("content")][-12:]
        if not history or history[-1]["role"] != "user":
            raise UserError("پیامی نوشته نشده است.")
        try:
            text = self.ask(self.persona() + "\nوضعیت فعلی پیج:\n" + facts, history[-1]["content"], history[:-1], 800)
            return {"text": text, "source": "ai"}
        except AIDown as e:
            if e.wait:
                return self.offline(e, text="سرویس رایگان هوش مصنوعی هر ۴۵ ثانیه یک پاسخ می‌دهد؛ %s ثانیهٔ دیگر دوباره بپرس."
                                    % fa(int(e.wait + 0.999)))
            return self.offline(e, text="الان به سرویس هوش مصنوعی دسترسی ندارم، ولی این وضعیت فعلی پیج است:\n\n" + facts
                                + "\n\nبرای ایدهٔ پست و کپشن می‌توانی از دکمه‌های «کپشن پیشنهادی» و «ایده» هم استفاده کنی.")


# ───────────────────────────── studio: a post or a reel out of one idea ─────────────────────────────
# The agent writes the words itself (caption, hashtags, a headline, a line for each scene) and asks a picture
# service for the pictures. The panel then draws the final image or renders the reel on the phone itself, so the
# result exists even when no picture service can be reached.

PICTURE_SIZES = {"post": (768, 960), "reel": (720, 1280), "square": (896, 896)}
HORDE_SIZES = {"post": (512, 640), "reel": (384, 704), "square": (576, 576)}     # the most it gives without an account
PICTURE_STYLES = {
    "photo": "professional photograph, natural light, shallow depth of field, highly detailed",
    "art": "digital illustration, soft colors, clean shapes",
    "minimal": "minimalist composition, plain background, a lot of empty space, soft light",
    "3d": "3D render, soft studio lighting, pastel colors",
}
NO_TEXT = "no text, no letters, no watermark"
HORDE_MODELS = {"photo": ["ICBINP - I Can't Believe It's Not Photography", "AbsoluteReality", "Deliberate", "stable_diffusion"],
                "art": ["Dreamshaper", "Deliberate", "stable_diffusion"]}
HORDE_AVOID = re.compile(r"nsfw|pony|anime|furry|hentai|illustrious|noob|waifu|anything|XL|flux", re.I)
HORDE_AGENT = "insta-agent:%s:github.com/afshinrahimi109/Najibrahimi" % VERSION
HORDE_POLL = 3.0                # seconds between two looks at a queued picture
HORDE_WAIT = 150                # how long a picture may sit in the volunteers' queue
PATIENCE = 60                   # the longest the studio waits for a service that says "come back in N seconds"
GRACE = 1.0                     # ...plus this much, so the service's clock has surely moved on
PICTURE_MAX = 15 * 1024 * 1024
SCENE_LINES = ["جزئیات بیشتر در کپشن 👇", "همین حالا پیام بده", "برای دوستانت هم بفرست", "ما را دنبال کن"]


class PictureError(Exception):
    """A picture service could not deliver. wait > 0: it asked to come back after that many seconds.
    tell=True: the owner should hear about it even when another service delivers (a refused key, for example)."""

    def __init__(self, message, wait=0.0, tell=False):
        super().__init__(message)
        self.message, self.wait, self.tell = message, max(0.0, float(wait or 0)), tell


def shorten(text, limit):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit + 1]
    return (cut[:cut.rfind(" ")] if " " in cut[limit // 2:] else text[:limit]).rstrip(" ،,.؛:-") + "…"


def loose_json(text):
    """The first JSON object inside an answer that may carry a code fence or a few words around it."""
    text = str(text or "")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    data = jload(text[start:end + 1], None)
    return data if isinstance(data, dict) else None


class Studio:
    def __init__(self, agent):
        self.agent, self.cfg, self.graph = agent, agent.cfg, agent.graph
        self.jobs, self.lock = {}, threading.Lock()
        self.free_at = 0.0                             # when the free picture service takes the next request from here
        self.models, self.models_at = None, 0.0

    def conf(self):
        return self.agent.settings.all()["studio"]

    def state(self):
        c = self.conf()
        return {"image": c["image"], "pollen": bool(c["pollen"]), "custom": bool(c["url"]),
                "free_wait": max(0, int(self.free_at - now())), "text": self.agent.ai.mode()}

    # ── words ──
    def question(self, idea, kind, n):
        """(what the assistant is, what it is asked) for one post."""
        ai, reel = self.agent.ai, kind == "reel"
        ask = ("ایده: «%s»\nبرای %s اینستاگرام فقط یک شیء JSON معتبر بده (بدون هیچ توضیح یا متن دیگری) با این کلیدها:\n"
               "\"caption\": کپشن فارسی ۲ تا ۴ جمله با یکی دو ایموجی؛ بدون هشتگ.\n"
               "\"hashtags\": آرایهٔ ۳ تا ۵ هشتگ دقیق و مرتبط.\n"
               "\"headline\": تیتر فارسی خیلی کوتاه برای نوشتن روی تصویر (حداکثر ۶ کلمه).\n"
               "\"sub\": یک جملهٔ کوتاه تکمیلی یا دعوت به اقدام (حداکثر ۸ کلمه) یا رشتهٔ خالی.\n"
               "\"image\": توصیف انگلیسی دقیق یک تصویر برای مدل تصویرساز (سوژه، محیط، نور، زاویه)، بدون هیچ نوشته‌ای در تصویر.\n"
               % (idea, ("یک ریل %d صحنه‌ای" % n) if reel else "یک پست تصویری"))
        if reel:
            ask += ("\"scenes\": آرایهٔ دقیقاً %d صحنه؛ هر صحنه یک شیء با \"text\" (جملهٔ فارسی خیلی کوتاه برای روی تصویر، حداکثر ۷ کلمه) "
                    "و \"image\" (توصیف انگلیسی تصویر همان صحنه). صحنهٔ اول توجه را جلب کند و صحنهٔ آخر دعوت به اقدام باشد.\n" % n)
        return ai.persona() + " هر چه می‌نویسی فقط یک شیء JSON معتبر باشد.", ask

    def plan(self, idea, kind, n, job=None):
        """Caption, hashtags, headline and one picture description per scene: from the assistant, or from templates."""
        ai, text, why = self.agent.ai, "", ""
        reel = kind == "reel"
        system, ask = self.question(idea, kind, n)
        for attempt in (0, 1):
            try:
                text = ai.ask(system, ask, max_tokens=1100)
                break
            except AIDown as e:
                wait = e.wait
                why = "limit" if wait else ("off" if str(e) == "off" else "down")
                if attempt or not 0 < wait <= PATIENCE or job is None:
                    break
                job["step"] = "سرویس رایگان متن هر ۴۵ ثانیه یک پاسخ می‌دهد؛ %s ثانیهٔ دیگر…" % fa(int(wait + GRACE))
                if job["cancel"].wait(wait + GRACE):
                    break
        base = self.offline_plan(idea, kind, n)
        data = loose_json(text)
        if not data:
            base["why"] = why or ("down" if not text else "format")
            return base

        def s(value, limit):
            return shorten(value, limit) if isinstance(value, str) else ""

        out = dict(base, source="ai", why="")
        caption = str(data.get("caption") or "").strip() if isinstance(data.get("caption"), str) else ""
        caption = re.sub(r"\s*#[^\s#]+", "", caption).strip()[:1800]       # hashtags travel on their own
        tags = []
        for t in (data.get("hashtags") if isinstance(data.get("hashtags"), list) else []):
            t = "#" + re.sub(r"[\s#]+", "_", str(t).strip().lstrip("#")).strip("_")
            if len(t) > 1 and norm(t) not in [norm(x) for x in tags]:
                tags.append(t[:60])
        out.update(caption=caption or base["caption"], hashtags=tags[:GOOD_HASHTAGS] or base["hashtags"],
                   headline=s(data.get("headline"), 70) or base["headline"], sub=s(data.get("sub"), 90),
                   image=s(data.get("image"), 500) or base["image"])
        if reel:
            scenes = []
            for i, sc in enumerate(data.get("scenes") if isinstance(data.get("scenes"), list) else []):
                if isinstance(sc, dict) and len(scenes) < n:
                    scenes.append({"text": s(sc.get("text"), 80) or base["scenes"][i]["text"], "image": s(sc.get("image"), 500) or out["image"]})
            out["scenes"] = scenes + base["scenes"][len(scenes):]
        return out

    def offline_plan(self, idea, kind, n):
        ai = self.agent.ai
        tags = ai.offline_hashtags(idea)[:GOOD_HASHTAGS]
        parts = [p.strip() for p in re.split(r"[\n.!؟?؛،:\-–—]+", idea) if len(p.strip()) >= 3]
        headline = shorten(parts[0] if parts else idea, 60)
        lines = [shorten(p, 70) for p in parts][:max(1, n - 1)]
        handle = self.agent.ig.acct.get("username") or self.agent.settings.get("brand.handle") or ""
        extra = ([("@" + handle)] if handle else []) + SCENE_LINES
        while len(lines) < n:
            lines.append(extra[(len(lines) - 1) % len(extra)] if lines else headline)
        return {"source": "offline", "why": "", "caption": "%s ✨\n\nنظر شما چیه؟ توی کامنت‌ها برامون بنویسید 👇" % idea, "hashtags": tags,
                "headline": headline, "sub": "", "image": idea,
                "scenes": [{"text": t, "image": idea} for t in lines[:n]] if kind == "reel" else []}

    # ── pictures ──
    def fetch(self, method, url, data=None, headers=None, timeout=120):
        try:
            return self.graph.http(method, url, data, headers, timeout)
        except GraphError:
            raise PictureError("ارتباط با سرویس تصویر برقرار نشد (اینترنت یا فیلترشکن را بررسی کن).")

    @staticmethod
    def is_picture(raw):
        found = sniff(raw[:64])
        return bool(found and found[0] == "image" and found[1] in ("jpg", "png", "webp") and len(raw) <= PICTURE_MAX)

    @staticmethod
    def refusal(headers, raw):
        """(what the service said, how many seconds it wants us to wait) out of a "not now" answer."""
        text = raw[:2000].decode("utf-8", "replace")
        data, msg = jload(text, None), ""
        if isinstance(data, dict):
            err = data.get("error")
            msg = (err.get("message") if isinstance(err, dict) else err) or data.get("message") or ""
        msg = str(msg or text)[:300]
        m = re.search(r"(?:retry after|wait)\s+(\d+)\s*s", msg, re.I)
        if m:
            return msg, int(m.group(1))
        after = str(headers.get("retry-after") or "")
        return msg, int(after) if after.isdigit() else 0

    def from_key(self, prompt, shape, seed, style, job):
        """Pollinations with the owner's own key: full size, no waiting, no logo."""
        c = self.conf()
        if not c["pollen"]:
            raise PictureError("")
        w, h = PICTURE_SIZES[shape]
        q = {"width": w, "height": h, "seed": seed, "safe": "true"}
        url = "%s/image/%s?%s" % (self.cfg.gen_api, urllib.parse.quote(prompt[:900], safe=""), urllib.parse.urlencode(q))
        status, headers, raw = self.fetch("GET", url, headers={"Authorization": "Bearer " + c["pollen"]})
        if status == 200 and self.is_picture(raw):
            return raw
        if status == 401:
            raise PictureError("کلید Pollinations پذیرفته نشد؛ در تنظیمات دوباره واردش کن.", tell=True)
        if status == 402:
            raise PictureError("اعتبار (Pollen) کلید Pollinations تمام شده است.", tell=True)
        _, wait = self.refusal(headers, raw)
        if status in (429, 503):
            raise PictureError("Pollinations فعلاً شلوغ است.", wait or 10)
        raise PictureError("Pollinations جواب نداد (HTTP %s)." % status)

    def from_free(self, prompt, shape, seed, style, job):
        """Pollinations without a key: one picture every 45 seconds per address, with its small logo in a corner."""
        left = self.free_at - now()
        if left > 0:
            raise PictureError("سرویس رایگان هر ۴۵ ثانیه یک تصویر می‌دهد.", left)
        w, h = PICTURE_SIZES[shape]
        q = urllib.parse.urlencode({"width": w, "height": h, "seed": seed, "private": "true", "safe": "true"})
        url = "%s/prompt/%s?%s" % (self.cfg.image_api, urllib.parse.quote(prompt[:700], safe=""), q)
        status, headers, raw = self.fetch("GET", url)
        if status == 200 and self.is_picture(raw):
            self.free_at = now() + self.cfg.free_gap
            return raw
        _, wait = self.refusal(headers, raw)
        if status in (402, 429, 503):
            wait = wait or (10 if status == 503 else self.cfg.free_gap)
            self.free_at = max(self.free_at, now() + wait)
            raise PictureError("سرویس رایگان فعلاً نوبت نمی‌دهد.", wait)
        raise PictureError("سرویس رایگان تصویر جواب نداد (HTTP %s)." % status)

    def horde_headers(self, json_body=False):
        h = {"apikey": "0000000000", "Client-Agent": HORDE_AGENT, "Accept": "application/json"}
        if json_body:
            h["Content-Type"] = "application/json"
        return h

    def horde_models(self, style):
        """Which general-purpose models the volunteers serve right now (most of that network draws anime)."""
        if self.models is None or now() - self.models_at > 1800:
            self.models, self.models_at = [], now()
            try:
                status, _, raw = self.fetch("GET", self.cfg.horde_api + "/status/models?type=image", headers=self.horde_headers(), timeout=20)
                rows = jload(raw.decode("utf-8", "replace"), None) if status == 200 else None
                for m in (rows if isinstance(rows, list) else []):
                    if isinstance(m, dict) and int(m.get("count") or 0) > 0:
                        self.models.append((str(m.get("name")), int(m.get("count") or 0)))
            except (PictureError, ValueError, TypeError):
                pass
        known = HORDE_MODELS["art" if style in ("art", "3d") else "photo"]
        if not self.models:
            return list(known)
        live = dict(self.models)
        want = [name for name in known if name in live]
        if not want:
            want = [name for name, _ in sorted(self.models, key=lambda x: -x[1]) if not HORDE_AVOID.search(name)][:4]
        return want

    def from_horde(self, prompt, shape, seed, style, job):
        """AI Horde, a network of volunteers: free and without an account, but small pictures and sometimes a queue."""
        base = self.cfg.horde_api
        w, h = HORDE_SIZES[shape]
        body = {"prompt": prompt[:900] + " ### text, letters, watermark, logo, blurry, deformed, low quality",
                "params": {"width": w, "height": h, "steps": 24, "n": 1, "sampler_name": "k_euler_a", "cfg_scale": 6.5,
                           "karras": True, "seed": str(seed)},
                "nsfw": False, "censor_nsfw": True, "r2": False, "shared": False, "slow_workers": True, "trusted_workers": False}
        models = self.horde_models(style)
        if models:
            body["models"] = models
        status, headers, raw = self.fetch("POST", base + "/generate/async", jdump(body).encode("utf-8"), self.horde_headers(True), 30)
        data = jload(raw.decode("utf-8", "replace"), None)
        rid = data.get("id") if isinstance(data, dict) else None
        if status not in (200, 202) or not rid:
            rc = data.get("rc") if isinstance(data, dict) else ""
            if status == 429 or rc == "TooManyPrompts":
                raise PictureError("شبکهٔ داوطلبانه فعلاً درخواست تازه نمی‌پذیرد.", 20)
            raise PictureError("شبکهٔ داوطلبانه (AI Horde) درخواست را نپذیرفت (%s)." % (rc or "HTTP %s" % status))
        deadline = now() + HORDE_WAIT
        try:
            while True:
                if job is not None and job["cancel"].wait(HORDE_POLL):
                    raise PictureError("لغو شد.")
                if job is None:
                    time.sleep(HORDE_POLL)
                status, _, raw = self.fetch("GET", base + "/generate/check/" + rid, headers=self.horde_headers(), timeout=20)
                st = jload(raw.decode("utf-8", "replace"), None)
                st = st if isinstance(st, dict) else {}
                if st.get("done"):
                    break
                if st.get("faulted") or st.get("is_possible") is False:
                    raise PictureError("شبکهٔ داوطلبانه نتوانست این تصویر را بسازد.")
                if now() > deadline:
                    raise PictureError("صف شبکهٔ داوطلبانه طولانی بود.")
                if job is not None and st.get("queue_position"):
                    job["step"] = "در صف شبکهٔ داوطلبانه (نفر %s)…" % fa(st["queue_position"])
        except PictureError:
            try:
                self.fetch("DELETE", base + "/generate/status/" + rid, headers=self.horde_headers(), timeout=15)
            except PictureError:
                pass
            raise
        status, _, raw = self.fetch("GET", base + "/generate/status/" + rid, headers=self.horde_headers(), timeout=60)
        data = jload(raw.decode("utf-8", "replace"), None)
        gens = data.get("generations") if isinstance(data, dict) else None
        if not gens or not isinstance(gens[0], dict):
            raise PictureError("شبکهٔ داوطلبانه تصویری برنگرداند.")
        if gens[0].get("censored"):
            raise PictureError("شبکهٔ داوطلبانه این تصویر را نپذیرفت؛ توصیف دیگری امتحان کن.")
        return self.unwrap(gens[0].get("img"))

    def unwrap(self, value):
        """A picture that came inside JSON: either a link or the file itself as base64."""
        value = str(value or "")
        if value.startswith(("http://", "https://")):
            status, _, blob = self.fetch("GET", value)
            if status != 200:
                blob = b""
        else:
            try:
                blob = base64.b64decode(value.split(",", 1)[-1], validate=False)
            except ValueError:
                blob = b""
        if not self.is_picture(blob):
            raise PictureError("فایلی که سرویس تصویر فرستاد عکس نبود.")
        return blob

    def from_custom(self, prompt, shape, seed, style, job):
        """Any service that speaks OpenAI's "images/generations" (the owner's own address, key and model)."""
        c = self.conf()
        if not c["url"]:
            raise PictureError("" if c["image"] != "custom" else "نشانی سرویس تصویر خودت را در تنظیمات ننوشته‌ای.")
        url = c["url"] if c["url"].endswith("/images/generations") else c["url"] + "/images/generations"
        body = {"model": c["model"] or "gpt-image-1", "prompt": prompt[:1500], "n": 1, "size": "1024x1024" if shape == "square" else "1024x1536"}
        headers = {"Content-Type": "application/json"}
        if c["key"]:
            headers["Authorization"] = "Bearer " + c["key"]
        status, _, raw = self.fetch("POST", url, jdump(body).encode("utf-8"), headers, 180)
        data = jload(raw.decode("utf-8", "replace"), None)
        try:
            item = data["data"][0]
            value = item.get("b64_json") or item.get("url")
        except (TypeError, KeyError, IndexError, AttributeError):
            value = None
        if status >= 400 or not value:
            raise PictureError("سرویس تصویر خودت جواب قابل‌استفاده‌ای نداد (HTTP %s)." % status, tell=True)
        return self.unwrap(value)

    SOURCES = {"key": "Pollinations (با کلید)", "free": "Pollinations (رایگان)", "horde": "AI Horde", "custom": "سرویس خودت"}
    ORDER = {"auto": ("custom", "key", "free", "horde"), "pollinations": ("key", "free"), "horde": ("horde",), "custom": ("custom",)}

    def picture(self, prompt, shape="post", style="photo", job=None):
        """One picture from the first service that delivers. Returns (file row, name of the service)."""
        mode = self.conf()["image"]
        if mode == "off":
            raise PictureError("ساخت تصویر با هوش مصنوعی در تنظیمات خاموش است.")
        shape = shape if shape in PICTURE_SIZES else "post"
        full = ", ".join(x for x in (shorten(prompt, 600), PICTURE_STYLES.get(style, PICTURE_STYLES["photo"]), NO_TEXT) if x)
        seed = random.randint(1, 2 ** 31 - 1)
        said = []
        for attempt in (0, 1):
            soonest = None
            for name in self.ORDER[mode]:
                if job is not None and job["cancel"].is_set():
                    raise PictureError("لغو شد.")
                try:
                    raw = getattr(self, "from_" + name)(full, shape, seed, style, job)
                    return self.agent.store.add_asset(raw, "studio:" + name), name
                except PictureError as e:
                    if e.message:
                        said.append("%s: %s" % (self.SOURCES[name], e.message))
                    if e.tell and job is not None and said[-1] not in job["notes"]:
                        job["notes"].append(said[-1])
                    if e.wait and (soonest is None or e.wait < soonest):
                        soonest = e.wait
            if attempt or soonest is None or soonest > PATIENCE:
                break
            if job is not None:
                job["step"] = "سرویس تصویر نوبت نداد؛ %s ثانیهٔ دیگر دوباره می‌پرسم…" % fa(int(soonest + GRACE))
                if job["cancel"].wait(soonest + GRACE):
                    raise PictureError("لغو شد.")
            else:
                time.sleep(soonest + GRACE)
            said = []
        raise PictureError(" | ".join(said[-3:]) or "هیچ سرویس تصویری در دسترس نبود.")

    # ── jobs: making takes a while, so the panel starts a job and asks how it is going ──
    @staticmethod
    def view(job):
        return {k: job[k] for k in ("id", "kind", "status", "step", "plan", "pictures", "notes", "error")}

    def job(self, jid):
        with self.lock:
            job = self.jobs.get(str(jid))
        if not job:
            raise UserError("این کار پیدا نشد (شاید ایجنت دوباره اجرا شده باشد). دوباره «بساز» را بزن.", 404)
        return self.view(job)

    def cancel(self, jid):
        with self.lock:
            job = self.jobs.get(str(jid))
        if job:
            job["cancel"].set()
        return {"ok": True}

    def start(self, kind, fn, *args):
        with self.lock:
            for old in [k for k, v in self.jobs.items() if v["created"] < now() - 3600]:
                del self.jobs[old]
            if sum(1 for v in self.jobs.values() if v["status"] == "running") >= 2:
                raise UserError("ایجنت همین حالا مشغول ساختن است؛ صبر کن تمام شود.", 429)
            job = {"id": secrets.token_hex(8), "kind": kind, "status": "running", "step": "", "plan": None, "pictures": [],
                   "notes": [], "error": "", "created": now(), "cancel": threading.Event()}
            self.jobs[job["id"]] = job
        threading.Thread(target=self.run, args=(job, fn) + args, name="studio", daemon=True).start()
        return self.view(job)

    def run(self, job, fn, *args):
        try:
            fn(job, *args)
            job["status"] = "canceled" if job["cancel"].is_set() else "done"
        except UserError as e:
            job["status"], job["error"] = "failed", e.message
        except Exception:
            log("studio:", traceback.format_exc())
            job["status"], job["error"] = "failed", "خطای داخلی برنامه؛ جزئیات در ترمینال نوشته شد."
        job["step"] = ""

    def make(self, data):
        idea = re.sub(r"[ \t]+", " ", str(data.get("idea") or "")).strip()[:600]
        if len(idea) < 3:
            raise UserError("ایده‌ات را در یک جمله بنویس.")
        kind = "reel" if data.get("kind") == "reel" else "image"
        n = clamp(data.get("scenes") or 4, 2, 6) if kind == "reel" else 1
        style = data.get("style") if data.get("style") in PICTURE_STYLES else "photo"
        return self.start("make", self.do_make, idea, kind, n, style, data.get("pictures") is not False)

    def do_make(self, job, idea, kind, n, style, want):
        job["step"] = "در حال نوشتن کپشن و چیدن صحنه‌ها…"
        plan = self.plan(idea, kind, n, job)
        plan.update(idea=idea, kind=kind, style=style)
        prompts = [sc["image"] for sc in plan["scenes"]] if kind == "reel" else [plan["image"]]
        job["pictures"] = [{"prompt": p, "file": "", "preview": "", "source": "", "why": ""} for p in prompts]
        job["plan"] = plan
        if not want:
            return
        letters = re.findall(r"[^\W\d_]", idea)
        if plan["source"] != "ai" and sum(1 for ch in letters if ch.isascii()) < 0.6 * max(1, len(letters)):
            # The picture services only understand English; without the assistant's description the picture would
            # show something else than the idea, so a drawn background is the honest choice.
            for pic in job["pictures"]:
                pic["why"] = "دستیار در دسترس نبود تا ایده را برای تصویرساز توصیف کند؛ برای همین تصویر هوش مصنوعی ساخته نشد."
            return
        self.draw(job, "reel" if kind == "reel" else "post", style)

    def redo(self, data):
        prompt = str(data.get("prompt") or "").strip()[:600]
        if len(prompt) < 3:
            raise UserError("بنویس تصویر چه چیزی را نشان بدهد.")
        shape = data.get("shape") if data.get("shape") in PICTURE_SIZES else "post"
        style = data.get("style") if data.get("style") in PICTURE_STYLES else "photo"
        return self.start("picture", self.do_redo, prompt, shape, style)

    def do_redo(self, job, prompt, shape, style):
        job["pictures"] = [{"prompt": prompt, "file": "", "preview": "", "source": "", "why": ""}]
        self.draw(job, shape, style)

    def draw(self, job, shape, style):
        failed, total = 0, len(job["pictures"])
        for i, pic in enumerate(job["pictures"]):
            if job["cancel"].is_set():
                return
            job["step"] = "در حال کشیدن تصویر…" if total == 1 else "در حال کشیدن تصویر %s از %s…" % (fa(i + 1), fa(total))
            try:
                f, source = self.picture(pic["prompt"], shape, style, job)
                pic.update(file=f["id"], preview="/api/file/" + f["id"], source=source, width=f["width"], height=f["height"])
                failed = 0
            except PictureError as e:
                pic["why"] = e.message
                failed += 1
                if failed >= 2:                        # nothing answers: the remaining scenes get a drawn background at once
                    for rest in job["pictures"][i + 1:]:
                        rest["why"] = e.message
                    return


# ───────────────────────────── auto-reply rules ─────────────────────────────

def rule_matches(rule, text):
    if rule["mode"] == "every":
        return True
    n = norm(text)
    keys = [k for k in (norm(k) for k in rule["keywords"]) if k]
    if not n or not keys:
        return False
    words = n.split()

    def has(k):
        return k in words if len(k) <= 2 else k in n

    if rule["mode"] == "all":
        return all(has(k) for k in keys)
    if rule["mode"] == "exact":
        return n in keys
    return any(has(k) for k in keys)


SPAM_WORDS = [norm(w) for w in (
    "فالوور ارزان", "خرید فالوور", "فالوور واقعی", "افزایش فالوور", "فالوور رایگان", "درآمد دلاری", "کسب درآمد از خانه",
    "سود تضمینی", "شرط بندی", "سایت شرطبندی", "follow for follow", "f4f", "free followers", "buy followers",
    "check my bio", "link in my bio", "dm me for", "promote it on", "crypto signal", "onlyfans")]
LINK_RE = re.compile(r"(https?://|www\.|t\.me/|wa\.me/|\b[\w-]{2,}\.(com|ir|xyz|net|org|info|link|io|shop|site|online|top|click|club|vip)\b)", re.I)


def looks_spam(text):
    n = norm(text)
    return bool(LINK_RE.search(str(text or ""))) or any(w in n for w in SPAM_WORDS)


DEFAULT_RULES = [
    {"scope": "comment", "name": "قیمت", "keywords": ["قیمت", "چنده", "هزینه"], "mode": "any",
     "replies": ["سلام {username} 🌹 قیمت رو براتون دایرکت کردیم.", "سلام {username} 🌹 جزئیات قیمت رو دایرکت فرستادیم."],
     "private": "سلام 🌹 ممنون از توجه‌تون. بگید کدوم مورد مدنظرتونه تا قیمت دقیق رو بفرستیم."},
    {"scope": "comment", "name": "تشکر", "keywords": ["قشنگ", "عالی", "عاشق", "مرسی", "ممنون", "دمتون گرم"], "mode": "any",
     "replies": ["ممنون از محبت‌تون 🙏🌹", "لطف دارید {username} 🌹", "خوشحالیم که دوست داشتید 😍"]},
    {"scope": "dm", "name": "ساعت کاری و آدرس", "keywords": ["ساعت کاری", "تا ساعت چند", "آدرس", "کجایید", "لوکیشن"],
     "mode": "any", "replies": ["سلام 🌹 ممنون از پیام‌تون. ساعت کاری و آدرس در بیوی پیج هست؛ اگر سؤال دیگه‌ای بود در خدمتیم."]},
]


class Rules:
    def __init__(self, db):
        self.db = db

    @staticmethod
    def view(r):
        return {"id": r["id"], "scope": r["scope"], "name": r["name"], "keywords": jload(r["keywords"], []),
                "mode": r["mode"], "replies": jload(r["replies"], []), "private": r["private"], "hide": bool(r["hide"]),
                "enabled": bool(r["enabled"]), "hits": r["hits"]}

    def list(self, scope=None):
        if scope:
            return [self.view(r) for r in self.db.q("SELECT * FROM rules WHERE scope=? ORDER BY id", (scope,))]
        return [self.view(r) for r in self.db.q("SELECT * FROM rules ORDER BY id")]

    def save(self, data, rid=None):
        scope = data.get("scope")
        if scope not in ("comment", "dm"):
            raise UserError("نوع قانون نامعتبر است.")
        mode = data.get("mode") if data.get("mode") in ("any", "all", "exact", "every") else "any"
        keys = data.get("keywords")
        if isinstance(keys, str):
            keys = re.split(r"[,،\n]+", keys)
        keys = [str(k).strip()[:60] for k in (keys or []) if str(k).strip()][:40]
        replies = data.get("replies")
        if isinstance(replies, str):
            replies = [replies]
        replies = [str(t).strip()[:900] for t in (replies or []) if str(t).strip()][:10]
        private = str(data.get("private") or "").strip()[:900] if scope == "comment" else ""
        hide = bool(data.get("hide")) if scope == "comment" else False
        if mode != "every" and not keys:
            raise UserError("دست‌کم یک کلمهٔ کلیدی بنویس.")
        if not replies and not private and not hide:
            raise UserError("بگو ایجنت چه کار کند: دست‌کم یک متن پاسخ بنویس.")
        if scope == "dm" and not replies:
            raise UserError("برای دایرکت یک متن پاسخ لازم است.")
        if any(len(t.encode("utf-8")) > 1000 for t in ([private] + (replies if scope == "dm" else []))):
            raise UserError("متن پیام دایرکت بلند است (اینستاگرام حداکثر ۱۰۰۰ بایت می‌پذیرد؛ حدود ۵۰۰ حرف فارسی).")
        name = str(data.get("name") or "").strip()[:60] or (keys[0] if keys else "قانون")
        args = (scope, name, jdump(keys), mode, jdump(replies), private, int(hide), int(bool(data.get("enabled", True))))
        if rid:
            if not self.db.one("SELECT id FROM rules WHERE id=?", (rid,)):
                raise UserError("این قانون پیدا نشد.", 404)
            self.db.x("UPDATE rules SET scope=?, name=?, keywords=?, mode=?, replies=?, private=?, hide=?, enabled=? "
                      "WHERE id=?", args + (rid,))
        else:
            rid = self.db.x("INSERT INTO rules (scope, name, keywords, mode, replies, private, hide, enabled, created_at) "
                            "VALUES (?,?,?,?,?,?,?,?,?)", args + (now(),))
        return self.view(self.db.one("SELECT * FROM rules WHERE id=?", (rid,)))

    def delete(self, rid):
        self.db.x("DELETE FROM rules WHERE id=?", (rid,))

    def match(self, scope, text):
        for r in self.list(scope):
            if r["enabled"] and rule_matches(r, text):
                return r
        return None

    def hit(self, rid):
        self.db.x("UPDATE rules SET hits=hits+1 WHERE id=?", (rid,))

    @staticmethod
    def render(text, username):
        out = str(text).replace("{username}", ("@" + username) if username else "")
        return re.sub(r"[ \t]{2,}", " ", out).strip()

    def seed(self, enabled):
        if self.db.get("rules.seeded"):
            return
        for r in DEFAULT_RULES:
            data = dict(r)
            data["enabled"] = enabled
            self.save(data)
        self.db.set("rules.seeded", 1)


# ───────────────────────────── publishing ─────────────────────────────

RETRY_BACKOFF = [30, 120, 300, 900, 1800]
PUBLISH_RECHECK_SEC = 20
CONTAINER_POLL_SEC = 4
QUOTA_RETRY_SEC = 3600
MISSED_AFTER_SEC = 6 * 3600
LINK_WAIT_SEC = 600
VIDEO_WAIT_SEC = 1500
RESTART_SEC = 1
POST_COLS = ("id", "kind", "caption", "status", "scheduled_at", "error", "progress", "attempts", "next_try_at",
             "ig_media_id", "permalink", "created_at", "updated_at", "published_at")


def count_tags(caption):
    return len(re.findall(r"#[^\s#]+", caption)), len(re.findall(r"(?<![\w.])@[\w.]+", caption))


def limit_tags(text, most=GOOD_HASHTAGS):
    """Drops every hashtag after the advised number from a text the assistant wrote (the owner may add more by hand)."""
    seen = [0]

    def keep(m):
        seen[0] += 1
        return m.group(0) if seen[0] <= most else ""

    out = re.sub(r"#[^\s#]+", keep, text)
    if seen[0] <= most:
        return text
    return re.sub(r"[ \t]+(?=\n|$)", "", re.sub(r"[ \t]{2,}", " ", out)).strip()


class Publisher:
    """Scheduled posts as a resumable state machine: a post is never published twice."""

    def __init__(self, agent):
        self.agent, self.db = agent, agent.db
        self.lock = threading.RLock()                  # the panel and the background loop never touch a post at once

    # ── reading ──
    def raw(self, pid):
        r = self.db.one("SELECT * FROM posts WHERE id=?", (pid,))
        if not r:
            raise UserError("این پست پیدا نشد.", 404)
        return r

    def view(self, r):
        store, media = self.agent.store, []
        for m in jload(r["media"], []):
            if m.get("file"):
                f = store.get(m["file"])
                item = store.view(f) if f else {"id": m["file"], "type": "image", "width": 0, "height": 0, "size": 0,
                                                "preview": ""}
                item.update(file=m["file"], missing=not f)
                media.append(item)
            else:
                media.append({"url": m.get("url"), "type": m.get("type") or "image", "preview": m.get("url")})
        out = {k: r[k] for k in POST_COLS}
        out.update(media=media, opts=jload(r["opts"], {}), manual=bool(r["manual"]),
                   by_hand=(jload(r["state"], {}) or {}).get("by") == "hand")
        return out

    def get(self, pid):
        return self.view(self.raw(pid))

    def list(self, group="all"):
        where, order = {
            "queue": ("status IN ('due','scheduled','publishing','failed','missed')", "status!='due', scheduled_at"),
            "drafts": ("status IN ('draft','canceled')", "updated_at DESC"),
            "published": ("status='published'", "published_at DESC"),
        }.get(group, ("1=1", "updated_at DESC"))
        return [self.view(r) for r in self.db.q("SELECT * FROM posts WHERE %s ORDER BY %s LIMIT 100" % (where, order))]

    # ── writing ──
    def media_kind(self, m):
        if m.get("file"):
            f = self.agent.store.get(m["file"])
            return f["kind"] if f else "image"
        return m.get("type") or "image"

    def validate(self, kind, caption, media, opts):
        hand = self.agent.hand()
        if not self.agent.ig.connected and not hand:
            raise UserError("اول پیج را وصل کن.")
        kinds = [self.media_kind(m) for m in media]
        n = len(media)
        if hand and not n:
            pass                                       # a reminder may be just a caption: the owner picks the file in Instagram
        elif kind == "image" and not (n == 1 and kinds[0] == "image"):
            raise UserError("پست تکی یک عکس می‌خواهد. (برای ویدیو «ریل» و برای چند عکس «چندتایی» را انتخاب کن.)")
        if kind == "reel" and not (n == 1 and kinds[0] == "video"):
            raise UserError("ریل یک ویدیو می‌خواهد.")
        if kind == "story" and n != 1:
            raise UserError("استوری یک عکس یا یک ویدیو می‌خواهد.")
        if kind == "carousel" and not 2 <= n <= 20:
            raise UserError("پست چندتایی بین ۲ تا ۲۰ عکس/ویدیو می‌خواهد.")
        if len(caption) > 2200:
            raise UserError("کپشن بلندتر از ۲۲۰۰ نویسه است.")
        tags, mentions = count_tags(caption)
        if tags > MAX_HASHTAGS:                        # (above GOOD_HASHTAGS the panel warns, but the choice is the owner's)
            raise UserError("کپشن %s هشتگ دارد؛ اینستاگرام حداکثر %s هشتگ می‌پذیرد. چندتا را بردار."
                            % (fa(tags), fa(MAX_HASHTAGS)))
        if mentions > 20:
            raise UserError("کپشن بیش از ۲۰ منشن دارد.")
        for m in media:
            if not m.get("file"):
                continue
            f = self.agent.store.get(m["file"])
            if not f or not os.path.exists(self.agent.store.path(f)):
                raise UserError("یکی از فایل‌ها دیگر روی دستگاه نیست؛ دوباره انتخابش کن.")
            if hand:
                continue                               # posted by hand: the Instagram app crops and converts by itself
            if f["ext"] == "webm":
                raise UserError("اینستاگرام ویدیوی WebM نمی‌پذیرد. ویدیو را دوباره (با مرورگر Chrome) بساز تا MP4 شود.")
            if kind == "story" and f["kind"] == "video" and f["size"] > STORY_VIDEO_MAX:
                raise UserError("ویدیوی استوری باید کمتر از ۱۰۰ مگابایت (و حداکثر ۶۰ ثانیه) باشد.")
            if f["kind"] == "image" and kind != "story" and f["width"] and f["height"]:
                ratio = f["width"] / float(f["height"])
                if not 0.79 <= ratio <= 1.92:
                    raise UserError("نسبت تصویر باید بین ۴:۵ (عمودی) و ۱٫۹۱:۱ (افقی) باشد.")

    def save(self, data, pid=None):
        kind = data.get("kind")
        if kind not in KINDS:
            raise UserError("نوع پست نامعتبر است.")
        caption = str(data.get("caption") or "").replace("\r\n", "\n").strip()[:6000]
        media = []
        items = data.get("media") if isinstance(data.get("media"), list) else []
        if len(items) > 20:
            raise UserError("هر پست حداکثر ۲۰ عکس/ویدیو می‌پذیرد.")
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("file"):
                f = self.agent.store.get(item["file"])
                if not f:
                    raise UserError("یکی از فایل‌ها پیدا نشد؛ دوباره انتخابش کن.")
                media.append({"file": f["id"]})
            elif item.get("url"):
                url = str(item["url"]).strip()
                ok = re.fullmatch(r"https://[\x21-\x7e]+", url) or (self.agent.cfg.sim and url.startswith("http://127.0.0.1"))
                if not ok or len(url) > 2000:
                    raise UserError("لینک فایل باید مستقیم، عمومی و با https:// باشد (فقط حروف انگلیسی).")
                media.append({"url": url, "type": "video" if item.get("type") == "video" else "image"})
        src = data.get("opts") if isinstance(data.get("opts"), dict) else {}
        opts = {"alt_text": str(src.get("alt_text") or "").strip()[:1000],
                "first_comment": str(src.get("first_comment") or "").strip()[:2200],
                "share_to_feed": src.get("share_to_feed") is not False, "comments_off": src.get("comments_off") is True}
        action = data.get("action") or "draft"
        try:
            when = float(data.get("scheduled_at") or 0)
        except (TypeError, ValueError):
            raise UserError("زمان انتشار نامعتبر است.")
        with self.lock:
            return self._save(pid, kind, caption, media, opts, action, when)

    def _save(self, pid, kind, caption, media, opts, action, when):
        state = {}
        if pid:
            old = self.raw(pid)
            if old["status"] == "published":
                raise UserError("این پست منتشر شده و دیگر قابل ویرایش نیست.")
            if old["status"] == "publishing":
                raise UserError("این پست در حال انتشار است؛ اول «توقف» را بزن، بعد ویرایش کن.")
            state = self.carry_state(jload(old["state"], {}), dirty=True)
        status, manual = "draft", 0
        if action in ("schedule", "now"):
            self.validate(kind, caption, media, opts)
            status = "scheduled"
            if action == "now":
                when, manual = now(), 1
                if self.agent.hand():
                    status, manual = "due", 0          # nothing is sent anywhere: the owner posts it by hand now
            elif when < now() + 30:
                raise UserError("زمان انتشار باید در آینده باشد.")
        elif action != "draft":
            raise UserError("درخواست نامعتبر است.")
        args = (kind, caption, jdump(media), jdump(opts), status, when, manual, jdump(state), now())
        if pid:
            self.db.x("UPDATE posts SET kind=?, caption=?, media=?, opts=?, status=?, scheduled_at=?, manual=?, state=?, "
                      "updated_at=?, error='', progress='', attempts=0, next_try_at=0 WHERE id=?", args + (pid,))
        else:
            pid = self.db.x("INSERT INTO posts (kind, caption, media, opts, status, scheduled_at, manual, state, updated_at, "
                            "created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", args + (now(),))
        self.agent.wake.set()
        return self.get(pid)

    @staticmethod
    def carry_state(old, dirty=False):
        """A post whose publish request was already sent must be double-checked before anything is sent again."""
        if old.get("sent") and old.get("container"):
            keep = {"stage": "verify", "container": old["container"], "sent": old["sent"], "verify_at": 0, "checks": 0,
                    "started": now(), "caption": old.get("caption", "")}
            if dirty or old.get("dirty"):
                keep["dirty"] = True
            return keep
        return {}

    def publish_now(self, pid):
        with self.lock:
            r = self.raw(pid)
            if r["status"] == "published":
                raise UserError("این پست قبلاً منتشر شده است.")
            if r["status"] == "publishing":
                raise UserError("این پست همین حالا در حال انتشار است.")
            self.validate(r["kind"], r["caption"], jload(r["media"], []), jload(r["opts"], {}))
            state = self.carry_state(jload(r["state"], {}))
            if self.agent.hand():
                self.db.x("UPDATE posts SET status='due', manual=0, scheduled_at=?, attempts=0, next_try_at=0, error='', "
                          "progress='', updated_at=? WHERE id=?", (now(), now(), pid))
                return self.get(pid)
            self.db.x("UPDATE posts SET status='scheduled', manual=1, scheduled_at=?, attempts=0, next_try_at=0, error='', "
                      "progress='', state=?, updated_at=? WHERE id=?", (now(), jdump(state), now(), pid))
        self.agent.wake.set()
        return self.get(pid)

    def done_by_hand(self, pid):
        """The owner says: I have posted this one myself in the Instagram app."""
        with self.lock:
            r = self.raw(pid)
            if r["status"] == "published":
                raise UserError("این پست قبلاً منتشرشده علامت خورده است.")
            if r["status"] == "publishing" or (jload(r["state"], {}) or {}).get("sent"):
                raise UserError("ایجنت همین حالا مشغول انتشار این پست است؛ چند لحظه صبر کن.")
            self.db.x("UPDATE posts SET status='published', published_at=?, updated_at=?, error='', progress='', manual=0, "
                      "attempts=0, next_try_at=0, state=? WHERE id=?", (now(), now(), jdump({"stage": "done", "by": "hand"}), pid))
        self.agent.note("%s را خودت منتشر کردی ✓" % KIND_FA[r["kind"]], "ok", "publish")
        return self.get(pid)

    def stoppable(self, r):
        """Once the publish request has left, the post may already be live: it cannot be pulled back any more."""
        if r["status"] == "published":
            raise UserError("این پست منتشر شده است.")
        if r["status"] == "publishing" and (jload(r["state"], {}) or {}).get("sent"):
            raise UserError("درخواست انتشار این پست به اینستاگرام رفته و ایجنت در حال بررسی نتیجه است؛ چند لحظه صبر کن.")

    def cancel(self, pid):
        with self.lock:
            r = self.raw(pid)
            self.stoppable(r)
            state = self.carry_state(jload(r["state"], {}))
            self.db.x("UPDATE posts SET status='draft', manual=0, error='', progress='', attempts=0, next_try_at=0, state=?, "
                      "updated_at=? WHERE id=?", (jdump(state), now(), pid))
        return self.get(pid)

    def duplicate(self, pid):
        r = self.raw(pid)
        new = self.db.x("INSERT INTO posts (kind, caption, media, opts, status, created_at, updated_at) VALUES (?,?,?,?,'draft',?,?)",
                        (r["kind"], r["caption"], r["media"], r["opts"], now(), now()))
        return self.get(new)

    def delete(self, pid):
        with self.lock:
            r = self.raw(pid)
            if r["status"] != "published":
                self.stoppable(r)
            self.db.x("DELETE FROM posts WHERE id=?", (pid,))

    def published_last_day(self):
        return self.db.val("SELECT COUNT(*) FROM posts WHERE status='published' AND published_at>?", (now() - 86400,))

    def slots(self, count=6):
        """Suggested publishing times: the page's best hours, skipping ones that are already taken."""
        hours = self.agent.analytics.best_hours()
        taken = [r["scheduled_at"] for r in self.db.q("SELECT scheduled_at FROM posts WHERE status='scheduled'")]
        out, day = [], time.localtime()
        base = time.mktime((day.tm_year, day.tm_mon, day.tm_mday, 0, 0, 0, 0, 0, -1))
        for d in range(0, 14):
            for hr in sorted(hours):
                ts = base + d * 86400 + hr * 3600
                if ts > now() + 900 and all(abs(ts - t) > 1800 for t in taken):
                    out.append(ts)
                if len(out) >= count:
                    return out
        return out

    # ── engine ──
    def put(self, pid, st, progress=None):
        if progress is None:
            self.db.x("UPDATE posts SET state=? WHERE id=?", (jdump(st), pid))
        else:
            self.db.x("UPDATE posts SET state=?, progress=? WHERE id=?", (jdump(st), progress, pid))

    def later(self, pid, seconds, progress=None):
        if progress is None:
            self.db.x("UPDATE posts SET next_try_at=? WHERE id=?", (now() + seconds, pid))
        else:
            self.db.x("UPDATE posts SET next_try_at=?, progress=? WHERE id=?", (now() + seconds, progress, pid))

    def fail(self, pid, why):
        r = self.raw(pid)
        self.db.x("UPDATE posts SET status='failed', error=?, progress='', manual=0, updated_at=? WHERE id=?", (why, now(), pid))
        self.agent.note("انتشار %s ناموفق ماند: %s" % (KIND_FA[r["kind"]], why), "alert", "publish")

    def retry(self, r, why, wait=None):
        n = r["attempts"] + 1
        if n > len(RETRY_BACKOFF):
            return self.fail(r["id"], why)
        delay = wait if wait is not None else RETRY_BACKOFF[n - 1]
        self.db.x("UPDATE posts SET attempts=?, next_try_at=?, error=?, progress=? WHERE id=?",
                  (n, now() + delay, why, "تلاش دوباره تا %s دقیقهٔ دیگر" % fa(max(1, int(round(delay / 60.0)))), r["id"]))

    def to_telegram(self, pid):
        """A post's files, then its caption as a message of its own (one tap copies it), to the owner's Telegram chat:
        from there the owner passes them on to the Instagram app."""
        r, agent = self.raw(pid), self.agent
        if not agent.has_telegram():
            raise UserError("اول در «تنظیمات ← اعلان در تلگرام» ربات خودت را وصل کن.")
        files = []
        for m in jload(r["media"], []):
            f = agent.store.get(m["file"]) if m.get("file") else None
            if f and os.path.exists(agent.store.path(f)):
                files.append(f)
        if not files and not r["caption"]:
            raise UserError("این پست نه فایل دارد نه کپشن.")
        for i, f in enumerate(files):
            agent.telegram_file(f, "insta-%d%s.%s" % (pid, ("-%d" % (i + 1)) if len(files) > 1 else "", f["ext"]))
        if r["caption"]:
            agent.telegram(r["caption"])
        return {"ok": True, "files": len(files)}

    def tick_hand(self):
        """Posting by hand: at its time a post only becomes "due" and the owner is told (panel and Telegram)."""
        t = now()
        for row in self.db.q("SELECT id FROM posts WHERE status='scheduled' AND scheduled_at<=? ORDER BY scheduled_at LIMIT 10", (t,)):
            with self.lock:
                r = self.db.one("SELECT * FROM posts WHERE id=?", (row["id"],))
                if not r or r["status"] != "scheduled" or r["scheduled_at"] > t:
                    continue                           # changed from the panel a moment ago
                self.db.x("UPDATE posts SET status='due', manual=0, error='', progress='', updated_at=? WHERE id=?", (t, r["id"]))
            first, sent = (r["caption"] or "").strip().split("\n")[0][:60], False
            if self.agent.has_telegram():              # the file and the caption travel ahead of the reminder itself
                try:
                    self.to_telegram(r["id"])
                    sent = True
                except UserError as e:
                    log("telegram:", e.message)
            self.agent.note("وقت انتشار %s رسید%s. %s" % (
                KIND_FA[r["kind"]], (": «%s»" % first) if first else "",
                "فایل و کپشن را در تلگرام برایت فرستادم؛ از همان‌جا به اینستاگرام بده." if sent
                else "پنل را باز کن، فایل را ذخیره و کپشن را کپی کن و در اینستاگرام بگذار."), "alert", "due")

    def tick(self):
        t = now()
        s = self.agent.settings.all()
        rows = self.db.q("SELECT id FROM posts WHERE (status='publishing' OR (status='scheduled' AND scheduled_at<=?)) "
                         "AND next_try_at<=? ORDER BY scheduled_at LIMIT 6", (t, t))
        for row in rows:
            with self.lock:
                self.tick_one(row["id"], s, t)

    def tick_one(self, pid, s, t):
        r = self.db.one("SELECT * FROM posts WHERE id=?", (pid,))
        if not r or r["next_try_at"] > t:
            return
        if r["status"] == "scheduled":
            if r["scheduled_at"] > t:
                return
            if not r["manual"]:
                if not s["autopilot"]:
                    return
                if t - r["scheduled_at"] > MISSED_AFTER_SEC:
                    self.db.x("UPDATE posts SET status='missed', updated_at=?, error=? WHERE id=?",
                              (t, "ایجنت در زمان این پست روشن نبود. اگر هنوز می‌خواهی، دستی منتشرش کن.", pid))
                    self.agent.note("یک %s زمان‌بندی‌شده جا ماند چون ایجنت در آن ساعت روشن نبود." % KIND_FA[r["kind"]],
                                    "warn", "publish")
                    return
                if self.published_last_day() >= s["limits"]["daily_posts"]:
                    self.later(pid, 1800, "سقف روزانه‌ای که خودت گذاشته‌ای پر است؛ بعداً دوباره بررسی می‌شود.")
                    return
            self.db.x("UPDATE posts SET status='publishing', error='', progress='در حال آماده‌سازی…', updated_at=? WHERE id=?",
                      (t, pid))
            r = self.raw(pid)
        elif r["status"] != "publishing":
            return                                     # changed from the panel a moment ago
        self.step(r)

    def step(self, r):
        pid, st = r["id"], (jload(r["state"], {}) or {})
        try:
            self.advance(r, st)
        except NotReady as e:
            if now() - st.get("started", now()) > LINK_WAIT_SEC:
                self.fail(pid, "لینک عمومی برای فایل آماده نشد. اینترنت و cloudflared را بررسی کن.")
            else:
                self.later(pid, e.wait, e.message)
        except (Permanent, UserError) as e:
            self.fail(pid, e.message)
        except GraphError as e:
            if e.kind == "auth":
                self.agent.problem(e, "publish")
                self.fail(pid, e.fa)
            elif e.transient:
                if e.kind == "throttle":
                    self.agent.problem(e, "publish")
                self.retry(r, e.fa, QUOTA_RETRY_SEC if e.kind == "quota" else None)
            else:
                self.fail(pid, e.fa)
        except Exception as e:
            log("publisher:", traceback.format_exc())
            self.retry(r, "خطای داخلی برنامه: %s" % e)

    def media_url(self, m):
        if m.get("url"):
            return m["url"], m.get("type") or "image"
        f = self.agent.store.get(m.get("file") or "")
        if not f or not os.path.exists(self.agent.store.path(f)):
            raise Permanent("فایل این پست دیگر روی دستگاه نیست؛ پست را ویرایش و فایل را دوباره انتخاب کن.")
        return self.agent.store.public_url(f), f["kind"]

    def restart(self, r, st, count=True):
        n = st.get("restarts", 0) + (1 if count else 0)
        if n > 2:
            raise Permanent("اینستاگرام چند بار بارگذاری را ناتمام گذاشت. کمی بعد دوباره تلاش کن.")
        self.put(r["id"], {"restarts": n}, "شروع دوباره…")
        self.later(r["id"], RESTART_SEC)

    EXTRAS = {"alt_text": "«متن جایگزین عکس»", "share_to_feed": "«نمایش ریل در صفحهٔ اصلی»"}

    def create(self, p):
        """Sends one file to Instagram. When the request is refused and it carried an optional extra, it is tried
        once more without the extras: a post without alt text is better than no post."""
        ig = self.agent.ig
        extras = [k for k in self.EXTRAS if k in p]
        try:
            return ig.create_container(p)
        except GraphError as e:
            if e.kind != "param" or not extras:
                raise
            first = e
        try:
            cid = ig.create_container({k: v for k, v in p.items() if k not in extras})
        except GraphError:
            raise first
        self.agent.note("اینستاگرام گزینهٔ %s را نپذیرفت؛ پست بدون آن فرستاده شد." % " و ".join(self.EXTRAS[k] for k in extras),
                        "warn", "publish")
        return cid

    def advance(self, r, st):
        pid, ig, kind = r["id"], self.agent.ig, r["kind"]
        media, opts = jload(r["media"], []), jload(r["opts"], {})
        if not st.get("stage"):
            st.update(stage="create", started=now(), caption=r["caption"])
            self.put(pid, st, "در حال فرستادن فایل به اینستاگرام…")
        if st["stage"] == "create":
            if kind == "carousel":
                kids = st.setdefault("kids", [None] * len(media))
                for i, m in enumerate(media):
                    if kids[i]:
                        continue
                    url, mk = self.media_url(m)
                    p = {"is_carousel_item": True}
                    if mk == "video":
                        p.update(media_type="VIDEO", video_url=url)
                    else:
                        p["image_url"] = url
                    kids[i] = ig.create_container(p)
                    self.put(pid, st, "فایل %s از %s فرستاده شد" % (fa(i + 1), fa(len(media))))
                st["stage"] = "kids"
            else:
                url, mk = self.media_url(media[0])
                p = {}
                if kind == "reel":
                    p.update(media_type="REELS", video_url=url, share_to_feed=bool(opts.get("share_to_feed", True)))
                elif kind == "story":
                    p["media_type"] = "STORIES"
                    p["video_url" if mk == "video" else "image_url"] = url
                else:
                    p["image_url"] = url
                    if opts.get("alt_text"):
                        p["alt_text"] = opts["alt_text"]
                if kind != "story" and r["caption"]:
                    p["caption"] = r["caption"]
                st["container"] = self.create(p)
                st["stage"] = "wait"
            st["wait_from"] = now()
            self.put(pid, st, "اینستاگرام در حال پردازش فایل است…")
        if st["stage"] == "kids":
            for cid in st["kids"]:
                code, text = ig.container_status(cid)
                if code == "ERROR":
                    raise Permanent("اینستاگرام یکی از فایل‌ها را نپذیرفت. " + text)
                if code == "EXPIRED":
                    return self.restart(r, st)
                if code != "FINISHED":
                    if now() - st.get("wait_from", now()) > VIDEO_WAIT_SEC:
                        raise Permanent("پردازش فایل در اینستاگرام بیش از حد طول کشید.")
                    return self.later(pid, CONTAINER_POLL_SEC)
            p = {"media_type": "CAROUSEL", "children": ",".join(st["kids"])}
            if r["caption"]:
                p["caption"] = r["caption"]
            st["container"] = ig.create_container(p)
            st["stage"], st["wait_from"] = "wait", now()
            self.put(pid, st)
        if st["stage"] == "wait":
            code, text = ig.container_status(st["container"])
            if code == "FINISHED":
                st["stage"] = "publish"
                self.put(pid, st, "در حال انتشار…")
            elif code == "PUBLISHED":
                return self.finish(r, st, self.find_published(r, st))
            elif code == "ERROR":
                raise Permanent("اینستاگرام این فایل را نپذیرفت. " + text)
            elif code == "EXPIRED":
                return self.restart(r, st)
            else:
                if now() - st.get("wait_from", now()) > VIDEO_WAIT_SEC:
                    raise Permanent("پردازش فایل در اینستاگرام بیش از حد طول کشید.")
                return self.later(pid, CONTAINER_POLL_SEC)
        if st["stage"] == "publish":
            # Written down BEFORE the request: if the answer is lost (or the app dies here), the post
            # continues from "verify" and asks Instagram what happened instead of publishing again.
            st.update(stage="verify", sent=now(), verify_at=now() + PUBLISH_RECHECK_SEC, checks=0)
            self.put(pid, st)
            try:
                mid, issue = ig.publish(st["container"])
            except GraphError as e:
                if e.kind in ("network", "transient"):
                    return self.later(pid, PUBLISH_RECHECK_SEC, "پاسخ اینستاگرام نرسید؛ در حال بررسی نتیجه…")
                st.pop("sent", None)                   # a clear "no": nothing was published
                if e.kind == "expired":
                    return self.restart(r, st)
                st["stage"] = "wait" if e.kind == "not_ready" else "publish"
                self.put(pid, st)
                if e.kind == "not_ready":
                    return self.later(pid, CONTAINER_POLL_SEC)
                raise
            return self.finish(r, st, mid, issue)
        if st["stage"] == "verify":
            if now() < st.get("verify_at", 0):
                return self.later(pid, max(1, st["verify_at"] - now()))
            code, text = ig.container_status(st["container"])
            found = self.find_published(r, st)
            if code == "PUBLISHED" or found:
                return self.finish(r, st, found)
            if code == "FINISHED":
                st["checks"] = st.get("checks", 0) + 1
                if st["checks"] >= 2:                  # Instagram says twice that nothing was published
                    if st.get("dirty"):                # …and the post was edited meanwhile → build it again
                        return self.restart(r, st, count=False)
                    st["stage"] = "publish"
                    st.pop("sent", None)
                    self.put(pid, st)
                    return self.later(pid, 0)
                st["verify_at"] = now() + PUBLISH_RECHECK_SEC
                self.put(pid, st)
                return self.later(pid, PUBLISH_RECHECK_SEC)
            if code == "ERROR":
                raise Permanent("اینستاگرام این فایل را نپذیرفت. " + text)
            if code == "EXPIRED":
                return self.restart(r, st)
            return self.later(pid, CONTAINER_POLL_SEC)

    def find_published(self, r, st):
        """Looks for this post on the page itself (used when a publish answer was lost)."""
        since = st.get("sent", now()) - 120
        want = (st.get("caption", r["caption"]) or "").strip()
        ours = {x["ig_media_id"] for x in self.db.q("SELECT ig_media_id FROM posts WHERE ig_media_id!='' AND id!=?", (r["id"],))}
        try:
            if r["kind"] == "story":
                for m in self.agent.ig.stories():
                    if parse_ts(m.get("timestamp")) >= since and str(m.get("id")) not in ours:
                        return str(m.get("id"))
                return ""
            for m in self.agent.ig.media(limit=8):
                if str(m.get("id")) in ours:
                    continue                           # that one belongs to another post of this panel
                if parse_ts(m.get("timestamp")) >= since and (m.get("caption") or "").strip() == want:
                    return str(m.get("id"))
        except GraphError:
            pass
        return ""

    def finish(self, r, st, media_id, issue=""):
        pid, ig, opts = r["id"], self.agent.ig, jload(r["opts"], {})
        permalink = ""
        if media_id:
            try:
                permalink = ig.media_info(media_id).get("permalink") or ""
            except GraphError:
                pass
        self.db.x("UPDATE posts SET status='published', ig_media_id=?, permalink=?, published_at=?, updated_at=?, error='', "
                  "progress='', manual=0, state=? WHERE id=?", (media_id or "", permalink, now(), now(), jdump({"stage": "done"}), pid))
        self.agent.note("%s منتشر شد ✓" % KIND_FA[r["kind"]], "ok", "publish")
        if issue:
            what = {"CAPTION_NOT_ATTACHED": "کپشن را روی آن نگذاشت (معمولاً به‌خاطر هشتگ یا متنی که نمی‌پسندد). "
                                            "کپشن را از خود اپ اینستاگرام اضافه کن.",
                    "USER_TAGGING_FAILURE": "تگ‌کردن افراد را انجام نداد."}.get(issue, "بخشی از آن را اعمال نکرد (%s)." % issue)
            self.agent.note("%s منتشر شد، ولی اینستاگرام %s" % (KIND_FA[r["kind"]], what), "alert", "publish")
        if media_id and r["kind"] != "story":
            try:
                if opts.get("first_comment"):
                    ig.comment_on(media_id, opts["first_comment"])
                if opts.get("comments_off"):
                    ig.set_comments(media_id, False)
            except GraphError as e:
                self.agent.note("پست منتشر شد ولی تنظیم کامنت آن انجام نشد: " + e.fa, "warn", "publish")
        self.agent.media_at = 0
        self.agent.due.pop("quota", None)


# ───────────────────────────── comments inbox ─────────────────────────────

THREAD_ID = "CASE WHEN parent_id='' THEN id ELSE parent_id END"


class Inbox:
    def __init__(self, agent):
        self.agent, self.db = agent, agent.db

    def is_me(self, uid, username):
        a = self.agent.ig.acct
        if uid and str(uid) in (a.get("ig_id"), a.get("scoped_id"), a.get("page_id")):
            return True
        return bool(username) and str(username).lower() == (a.get("username") or "").lower()

    # ── reading from Instagram ──
    def sync(self, force=False):
        done = 0
        for i, m in enumerate(self.agent.media_list(refresh=True)[:25]):
            row = self.db.one("SELECT seen_count, synced_at FROM media WHERE id=?", (str(m.get("id")),))
            if row is None:
                continue
            count = m.get("comments_count")
            age = now() - row["synced_at"]
            if count is None:
                need = i < 10 and age > 600            # this token cannot read the counter → look on a timer
            else:
                count = int(count)
                need = row["synced_at"] == 0 or row["seen_count"] != count or (i < 3 and age > 600)
                if need and count == 0 and row["seen_count"] <= 0 and not force:
                    self.db.x("UPDATE media SET seen_count=0, synced_at=? WHERE id=?", (now(), str(m["id"])))
                    continue
            if not (need or force):
                continue
            self.sync_media(str(m["id"]), count)
            done += 1
            if done >= 8 and not force:
                break

    def sync_media(self, media_id, count=None):
        data, more = self.agent.ig.comments(media_id)
        seen, mine_new, complete = set(), [], set()

        def upsert(c, parent=""):
            cid = str(c.get("id") or "")
            if not cid:
                return
            seen.add(cid)
            frm = c.get("from") or {}
            username = frm.get("username") or c.get("username") or ""
            uid = str(frm.get("id") or "")
            mine = 1 if self.is_me(uid, username) else 0
            ts = parse_ts(c.get("timestamp")) or now()
            hidden = 1 if c.get("hidden") else 0
            known = self.db.one("SELECT hidden FROM comments WHERE id=?", (cid,))
            if known is not None and "hidden" not in c:
                hidden = known["hidden"]               # this token cannot read the flag → keep what we know
            if known is None:
                state = "done" if (mine or hidden or ts < now() - FRESH_SEC) else "open"
                self.db.x("INSERT INTO comments (id, media_id, parent_id, user_id, username, text, ts, hidden, mine, state) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (cid, media_id, parent, uid, username, c.get("text") or "", ts, hidden, mine, state))
                if mine:
                    mine_new.append((parent or cid, ts))
            else:
                self.db.x("UPDATE comments SET text=?, hidden=?, deleted=0, username=? WHERE id=?",
                          (c.get("text") or "", hidden, username, cid))

        for c in data:
            upsert(c)
            replies = (c.get("replies") or {}).get("data") or []
            if len(replies) < 25:
                complete.add(str(c.get("id")))
            for r in replies:
                upsert(r, str(c.get("id")))
        for parent, ts in mine_new:                    # answered from the Instagram app itself → nothing left to do
            self.db.x("UPDATE comments SET state='done' WHERE (id=? OR parent_id=?) AND mine=0 AND ts<=?", (parent, parent, ts))
        if not more:
            grace = now() - 120
            for row in self.db.q("SELECT id, parent_id, mine, hidden, ts FROM comments WHERE media_id=? AND deleted=0", (media_id,)):
                if row["id"] in seen or row["hidden"] or (row["mine"] and row["ts"] > grace):
                    continue
                if row["parent_id"] and row["parent_id"] in seen and row["parent_id"] not in complete:
                    continue                           # a reply beyond the first 25 we asked for
                self.db.x("UPDATE comments SET deleted=1, state='done' WHERE id=?", (row["id"],))
        self.db.x("UPDATE media SET seen_count=?, synced_at=? WHERE id=?", (-1 if count is None else count, now(), media_id))

    # ── lists for the panel ──
    def media_brief(self, media_id):
        row = self.db.one("SELECT data FROM media WHERE id=?", (media_id,))
        m = jload(row["data"], {}) if row else {}
        return {"id": media_id, "caption": (m.get("caption") or "")[:140], "permalink": m.get("permalink") or "",
                "thumb": m.get("thumbnail_url") or m.get("media_url") or "", "type": m.get("media_type") or ""}

    @staticmethod
    def cview(c):
        return {"id": c["id"], "username": c["username"], "text": c["text"], "ts": c["ts"], "mine": bool(c["mine"]),
                "hidden": bool(c["hidden"]), "open": c["state"] == "open" and not c["mine"] and not c["hidden"],
                "dm_sent": bool(c["dm_sent"])}

    def thread(self, tid):
        top = self.db.one("SELECT * FROM comments WHERE id=? AND deleted=0", (str(tid),))
        if not top:
            return None
        if top["parent_id"]:
            return self.thread(top["parent_id"])
        replies = self.db.q("SELECT * FROM comments WHERE parent_id=? AND deleted=0 ORDER BY ts, id", (top["id"],))
        rows = [top] + replies
        opens = [c for c in rows if c["state"] == "open" and not c["mine"] and not c["hidden"]]
        return {"id": top["id"], "media": self.media_brief(top["media_id"]), "top": self.cview(top),
                "replies": [self.cview(c) for c in replies], "open": bool(opens), "suggest": top["suggest"],
                "last_ts": max(c["ts"] for c in (opens or rows))}

    def threads(self, flt="open", media_id=None):
        if media_id:
            ids = self.db.q("SELECT id AS tid FROM comments WHERE media_id=? AND parent_id='' AND deleted=0 ORDER BY ts DESC LIMIT 60",
                            (str(media_id),))
        elif flt == "open":
            ids = self.db.q("SELECT DISTINCT %s AS tid FROM comments WHERE state='open' AND mine=0 AND deleted=0 AND hidden=0 LIMIT 200" % THREAD_ID)
        elif flt == "hidden":
            ids = self.db.q("SELECT DISTINCT %s AS tid FROM comments WHERE hidden=1 AND deleted=0 LIMIT 200" % THREAD_ID)
        else:
            ids = self.db.q("SELECT id AS tid FROM comments WHERE parent_id='' AND deleted=0 ORDER BY ts DESC LIMIT 60")
        out = [t for t in (self.thread(r["tid"]) for r in ids) if t]
        out.sort(key=lambda t: -t["last_ts"])
        return out[:80]

    def open_count(self):
        return self.db.val("SELECT COUNT(DISTINCT %s) FROM comments WHERE state='open' AND mine=0 AND deleted=0 AND hidden=0" % THREAD_ID)

    # ── actions ──
    def row(self, cid):
        c = self.db.one("SELECT * FROM comments WHERE id=? AND deleted=0", (str(cid),))
        if not c:
            raise UserError("این کامنت دیگر وجود ندارد.", 404)
        return c

    @staticmethod
    def ukey(c):
        return "c:" + (c["user_id"] or c["username"])

    def reply(self, cid, text, actor="user", rule_id=0):
        text = str(text or "").strip()
        if not text:
            raise UserError("متن پاسخ خالی است.")
        if len(text) > 2200:
            raise UserError("پاسخ خیلی بلند است.")
        c = self.row(cid)
        top = c["parent_id"] or c["id"]                # Instagram only takes replies on the top comment of a thread
        new_id = self.agent.ig.reply(top, text) or ("local-" + secrets.token_hex(6))
        a = self.agent.ig.acct
        self.db.x("INSERT OR REPLACE INTO comments (id, media_id, parent_id, user_id, username, text, ts, mine, state) "
                  "VALUES (?,?,?,?,?,?,?,1,'done')",
                  (new_id, c["media_id"], top, a.get("ig_id") or "", a.get("username") or "", text, now()))
        self.db.x("UPDATE comments SET state='done', suggest='' WHERE (id=? OR parent_id=?) AND mine=0", (top, top))
        self.db.x("UPDATE media SET seen_count=seen_count+1 WHERE id=? AND seen_count>=0", (c["media_id"],))
        self.agent.acted("reply", c["id"], self.ukey(c), actor, rule_id, text)
        return new_id

    def private(self, cid, text, actor="user", rule_id=0):
        text = str(text or "").strip()
        if not text:
            raise UserError("متن پیام خالی است.")
        if len(text.encode("utf-8")) > 1000:
            raise UserError("پیام بلند است (اینستاگرام حداکثر ۱۰۰۰ بایت می‌پذیرد؛ حدود ۵۰۰ حرف فارسی).")
        c = self.row(cid)
        if c["mine"]:
            raise UserError("این کامنت را خود پیج نوشته است.")
        if c["dm_sent"]:
            raise UserError("برای این کامنت قبلاً یک پیام خصوصی فرستاده شده است (اینستاگرام فقط یک بار اجازه می‌دهد).")
        if now() - c["ts"] > 7 * 86400:
            raise UserError("از این کامنت بیش از ۷ روز گذشته و اینستاگرام دیگر اجازهٔ پیام خصوصی نمی‌دهد.")
        self.agent.ig.send({"comment_id": c["id"]}, text)
        self.db.x("UPDATE comments SET dm_sent=1 WHERE id=?", (c["id"],))
        self.agent.acted("private", c["id"], self.ukey(c), actor, rule_id, text)
        self.agent.due.pop("dms", None)

    def hide(self, cid, hide=True, actor="user", rule_id=0):
        c = self.row(cid)
        self.agent.ig.hide(c["id"], hide)
        if hide:
            self.db.x("UPDATE comments SET hidden=1, state='done' WHERE id=?", (c["id"],))
        else:
            self.db.x("UPDATE comments SET hidden=0 WHERE id=?", (c["id"],))
        self.agent.acted("hide" if hide else "unhide", c["id"], "", actor, rule_id, c["text"])

    def delete(self, cid):
        c = self.row(cid)
        self.agent.ig.delete_comment(c["id"])
        self.db.x("UPDATE comments SET deleted=1, state='done' WHERE id=? OR parent_id=?", (c["id"], c["id"]))
        self.db.x("UPDATE media SET seen_count=-1 WHERE id=?", (c["media_id"],))
        self.agent.acted("delete", c["id"], "", "user", 0, c["text"])

    def dismiss(self, cid):
        c = self.row(cid)
        top = c["parent_id"] or c["id"]
        self.db.x("UPDATE comments SET state='done' WHERE id=? OR parent_id=?", (top, top))

    def dismiss_all(self):
        self.db.x("UPDATE comments SET state='done' WHERE state='open'")

    def suggest(self, cid):
        c = self.row(cid)
        top = c["parent_id"] or c["id"]
        target = self.db.one("SELECT * FROM comments WHERE (id=? OR parent_id=?) AND mine=0 AND deleted=0 "
                             "ORDER BY (state='open') DESC, ts DESC LIMIT 1", (top, top)) or c
        out = self.agent.ai.reply(target["text"], self.media_brief(c["media_id"])["caption"])
        self.db.x("UPDATE comments SET suggest=? WHERE id=?", (out["text"], top))
        return out

    # ── automation ──
    def automate(self):
        s = self.agent.settings.all()
        auto, since = s["auto"], s["since"]
        if not s["autopilot"] or not (auto["comment_reply"] or auto["spam_hide"] or auto["ai_suggest"]):
            return
        rows = self.db.q("SELECT * FROM comments WHERE state='open' AND mine=0 AND deleted=0 AND hidden=0 AND auto=0 "
                         "AND ts>=? ORDER BY ts, id LIMIT 200", (now() - AUTO_MAX_AGE,))
        ai_calls, quiet = 0, self.agent.quiet()
        for c in rows:
            mark = "UPDATE comments SET auto=1 WHERE id=?"     # always written BEFORE acting: never answer twice
            if auto["spam_hide"] and c["ts"] >= since["spam_hide"] and looks_spam(c["text"]):
                if not self.agent.may_act():
                    return
                self.db.x(mark, (c["id"],))
                try:
                    self.hide(c["id"], True, actor="auto")
                    self.agent.note("کامنت تبلیغاتی @%s مخفی شد: «%s»" % (c["username"], c["text"][:70]), "info", "auto")
                except GraphError as e:
                    self.agent.problem(e, "comments")
                continue
            if auto["comment_reply"] and c["ts"] >= since["comment_reply"]:
                rule = self.agent.rules.match("comment", c["text"])
                if rule:
                    if quiet:
                        continue                       # waits for the end of the quiet hours
                    if not self.agent.may_act():
                        return
                    self.db.x(mark, (c["id"],))
                    if not self.agent.cooling(self.ukey(c)):
                        self.apply(rule, c)
                    continue
            if auto["ai_suggest"] and c["ts"] >= since["ai_suggest"]:
                if ai_calls >= 3:
                    continue                           # the next round takes the rest
                ai_calls += 1
                self.db.x(mark, (c["id"],))
                out = self.agent.ai.reply(c["text"], self.media_brief(c["media_id"])["caption"])
                send = (auto["ai_send"] and out["source"] == "ai" and c["ts"] >= since["ai_send"] and not quiet
                        and not looks_spam(out["text"]) and "@" not in out["text"]      # plain words only go out unseen
                        and not self.agent.cooling(self.ukey(c)) and self.agent.may_act())
                try:
                    if send:
                        self.reply(c["id"], out["text"], actor="ai")
                        self.agent.note("دستیار به کامنت @%s پاسخ داد: «%s»" % (c["username"], out["text"][:70]), "info", "auto")
                    else:
                        self.db.x("UPDATE comments SET suggest=? WHERE id=?", (out["text"], c["parent_id"] or c["id"]))
                except GraphError as e:
                    self.agent.problem(e, "comments")
                continue
            self.db.x(mark, (c["id"],))                # nothing applies → it stays for the human and is not looked at again

    def apply(self, rule, c):
        rules = self.agent.rules
        try:
            if rule["replies"]:
                self.reply(c["id"], rules.render(random.choice(rule["replies"]), c["username"]), "rule", rule["id"])
            if rule["hide"]:
                self.hide(c["id"], True, "rule", rule["id"])
        except GraphError as e:
            self.agent.problem(e, "comments")
            self.agent.note("پاسخ خودکار به @%s فرستاده نشد: %s" % (c["username"], e.fa), "warn", "auto-fail", 600)
            return
        if rule["private"]:
            try:
                self.private(c["id"], rules.render(rule["private"], ""), "rule", rule["id"])
            except (GraphError, UserError) as e:
                why = e.fa if isinstance(e, GraphError) else e.message
                self.agent.note("پیام خصوصی خودکار فرستاده نشد: " + why, "warn", "auto-private", 3600)
        self.db.x("UPDATE comments SET state='done' WHERE id=?", (c["id"],))
        rules.hit(rule["id"])
        self.agent.note("به کامنت @%s طبق قانون «%s» رسیدگی شد." % (c["username"], rule["name"]), "info", "auto")


# ───────────────────────────── direct messages ─────────────────────────────

class Direct:
    OPEN = "last_from_me=0 AND last_id!='' AND last_id!=handled_id"

    def __init__(self, agent):
        self.agent, self.db = agent, agent.db

    def is_me(self, p):
        return self.agent.inbox.is_me((p or {}).get("id"), (p or {}).get("username") or "")

    def sync(self, force=False):
        for c in self.agent.ig.conversations():
            cid = str(c.get("id") or "")
            if not cid:
                continue
            updated = parse_ts(c.get("updated_time"))
            row = self.db.one("SELECT * FROM convs WHERE id=?", (cid,))
            if row and row["updated"] >= updated and not force and now() - updated > 120:
                continue                               # (a chat changed in the last 2 minutes is read again: same-second messages)
            other = None
            for p in (c.get("participants") or {}).get("data") or []:
                if not self.is_me(p):
                    other = p
            self.load(cid, updated, other, row)

    def load(self, cid, updated, other, row):
        items = []
        known = set(r["id"] for r in self.db.q("SELECT id FROM msgs WHERE conv_id=?", (cid,)))
        for m in reversed(self.agent.ig.messages(cid, known=known)):       # Instagram lists newest first
            mid = str(m.get("id") or "")
            if not mid:
                continue
            frm = m.get("from") or {}
            text = m.get("message") or ("📎 پیوست" if m.get("attachments") else "")
            item = {"id": mid, "mine": self.is_me(frm), "text": text, "ts": parse_ts(m.get("created_time")) or now(), "from": frm}
            items.append(item)
            self.db.x("INSERT OR IGNORE INTO msgs (id, conv_id, from_me, text, ts) VALUES (?,?,?,?,?)",
                      (mid, cid, 1 if item["mine"] else 0, text, item["ts"]))
        if not items:
            return
        items.sort(key=lambda i: i["ts"])
        last = items[-1]
        self.db.x("DELETE FROM msgs WHERE conv_id=? AND id LIKE 'local-%' AND ts<=?", (cid, last["ts"] + 5))
        if other is None:
            other = next((i["from"] for i in items if not i["mine"]), None)
        user_ts = max([i["ts"] for i in items if not i["mine"]] or [0])
        uid = str((other or {}).get("id") or (row["user_id"] if row else ""))
        name = (other or {}).get("username") or (row["username"] if row else "") or "کاربر"
        if row is None:
            handled = last["id"] if (last["mine"] or last["ts"] < now() - FRESH_SEC) else ""
            self.db.x("INSERT INTO convs (id, user_id, username, updated, last_text, last_id, last_ts, last_from_me, last_user_ts, "
                      "handled_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (cid, uid, name, updated, last["text"], last["id"], last["ts"], 1 if last["mine"] else 0, user_ts, handled))
        else:
            self.db.x("UPDATE convs SET user_id=?, username=?, updated=?, last_text=?, last_id=?, last_ts=?, last_from_me=?, "
                      "last_user_ts=? WHERE id=?",
                      (uid, name, updated, last["text"], last["id"], last["ts"], 1 if last["mine"] else 0,
                       max(user_ts, row["last_user_ts"]), cid))

    def view(self, c):
        return {"id": c["id"], "username": c["username"], "last_text": c["last_text"], "last_ts": c["last_ts"],
                "last_from_me": bool(c["last_from_me"]), "suggest": c["suggest"],
                "open": (not c["last_from_me"]) and c["last_id"] != "" and c["last_id"] != c["handled_id"],
                "can_reply": now() - c["last_user_ts"] < 86400, "window_until": c["last_user_ts"] + 86400}

    def list(self):
        return [self.view(c) for c in self.db.q("SELECT * FROM convs ORDER BY last_ts DESC LIMIT 100")]

    def open_count(self):
        return self.db.val("SELECT COUNT(*) FROM convs WHERE " + self.OPEN)

    def row(self, cid):
        c = self.db.one("SELECT * FROM convs WHERE id=?", (str(cid),))
        if not c:
            raise UserError("این گفتگو پیدا نشد.", 404)
        return c

    def get(self, cid):
        c = self.row(cid)
        msgs = self.db.q("SELECT id, from_me, text, ts FROM msgs WHERE conv_id=? ORDER BY ts DESC, rowid DESC LIMIT 60", (c["id"],))
        return {"conv": self.view(c), "messages": [{"id": m["id"], "mine": bool(m["from_me"]), "text": m["text"], "ts": m["ts"]}
                                                   for m in reversed(msgs)]}

    def send(self, cid, text, actor="user", rule_id=0):
        text = str(text or "").strip()
        if not text:
            raise UserError("متن پیام خالی است.")
        if len(text.encode("utf-8")) > 1000:
            raise UserError("پیام بلند است (اینستاگرام حداکثر ۱۰۰۰ بایت می‌پذیرد؛ حدود ۵۰۰ حرف فارسی).")
        c = self.row(cid)
        if not c["user_id"]:
            raise UserError("شناسهٔ این کاربر مشخص نیست؛ از خود اینستاگرام پاسخ بده.")
        if now() - c["last_user_ts"] > 86400:
            raise UserError("از آخرین پیام این کاربر بیش از ۲۴ ساعت گذشته است و اینستاگرام اجازهٔ پاسخ از این راه را "
                            "نمی‌دهد. از خود اپ اینستاگرام جواب بده.")
        self.agent.ig.send({"id": c["user_id"]}, text)
        mid = "local-" + secrets.token_hex(8)
        self.db.x("INSERT INTO msgs (id, conv_id, from_me, text, ts) VALUES (?,?,1,?,?)", (mid, c["id"], text, now()))
        self.db.x("UPDATE convs SET last_text=?, last_id=?, last_ts=?, last_from_me=1, suggest='' WHERE id=?",
                  (text, mid, now(), c["id"]))
        self.agent.acted("dm", c["id"], "d:" + c["id"], actor, rule_id, text)

    def dismiss(self, cid):
        self.db.x("UPDATE convs SET handled_id=last_id WHERE id=?", (self.row(cid)["id"],))

    def suggest(self, cid):
        c = self.row(cid)
        last = self.db.one("SELECT text FROM msgs WHERE conv_id=? AND from_me=0 ORDER BY ts DESC LIMIT 1", (c["id"],))
        out = self.agent.ai.reply(last["text"] if last else c["last_text"], kind="dm")
        self.db.x("UPDATE convs SET suggest=? WHERE id=?", (out["text"], c["id"]))
        return out

    def automate(self):
        s = self.agent.settings.all()
        if not (s["autopilot"] and s["auto"]["dm_reply"]):
            return
        floor = max(s["since"]["dm_reply"], now() - AUTO_MAX_AGE)
        rows = self.db.q("SELECT * FROM convs WHERE %s AND last_id!=auto_id AND last_user_ts>=? ORDER BY last_user_ts LIMIT 100"
                         % self.OPEN, (floor,))
        for c in rows:
            rule = self.agent.rules.match("dm", c["last_text"])
            if not rule:
                self.db.x("UPDATE convs SET auto_id=last_id WHERE id=?", (c["id"],))
                continue
            if self.agent.quiet():
                continue
            if not self.agent.may_act():
                return
            self.db.x("UPDATE convs SET auto_id=last_id WHERE id=?", (c["id"],))      # before sending: never twice
            if self.agent.cooling("d:" + c["id"]):
                continue
            try:
                self.send(c["id"], self.agent.rules.render(random.choice(rule["replies"]), c["username"]), "rule", rule["id"])
                self.agent.rules.hit(rule["id"])
                self.agent.note("به دایرکت @%s طبق قانون «%s» پاسخ داده شد." % (c["username"], rule["name"]), "info", "auto")
            except GraphError as e:
                self.agent.problem(e, "dms")
                self.agent.note("پاسخ خودکار دایرکت به @%s فرستاده نشد: %s" % (c["username"], e.fa), "warn", "auto-fail", 600)
            except UserError as e:
                self.agent.note("پاسخ خودکار دایرکت فرستاده نشد: " + e.message, "warn", "auto-fail", 600)


# ───────────────────────────── insights ─────────────────────────────

METRIC_FA = [("reach", "ریچ (حساب‌های دیده)"), ("views", "بازدید"), ("accounts_engaged", "حساب‌های تعامل‌کرده"),
             ("total_interactions", "کل تعامل‌ها"), ("likes", "لایک"), ("comments", "کامنت"), ("shares", "اشتراک‌گذاری"),
             ("saves", "ذخیره"), ("saved", "ذخیره"), ("replies", "پاسخ به استوری"), ("profile_links_taps", "لمس لینک‌های پروفایل")]


class Analytics:
    def __init__(self, agent):
        self.agent, self.db = agent, agent.db
        self.detail_cache = {}

    def media_rows(self):
        return [jload(r["data"], {}) for r in self.db.q("SELECT data FROM media ORDER BY ts DESC LIMIT 200")]

    def best_hours(self):
        buckets = {}
        for m in self.media_rows():
            ts = parse_ts(m.get("timestamp"))
            if not ts or ts < now() - 120 * 86400 or m.get("like_count") is None:
                continue
            hour = time.localtime(ts).tm_hour
            buckets.setdefault(hour, []).append(int(m.get("like_count") or 0) + 2 * int(m.get("comments_count") or 0))
        if sum(len(v) for v in buckets.values()) < 6:
            return [12, 18, 21]
        ranked = sorted(buckets, key=lambda h: -sum(buckets[h]) / float(len(buckets[h])))
        return sorted(ranked[:3])

    def top_posts(self, days):
        rows = [m for m in self.media_rows() if parse_ts(m.get("timestamp")) >= now() - days * 86400]
        rows.sort(key=lambda m: -(int(m.get("like_count") or 0) + 2 * int(m.get("comments_count") or 0)))
        return [{"id": str(m.get("id")), "caption": (m.get("caption") or "")[:90], "type": m.get("media_type") or "",
                 "thumb": m.get("thumbnail_url") or m.get("media_url") or "", "likes": m.get("like_count"),
                 "comments": m.get("comments_count"), "ts": parse_ts(m.get("timestamp"))} for m in rows[:5]]

    def overview(self, days=7, refresh=False):
        days = 28 if str(days) == "28" else 7
        key = "insights.%d" % days
        data = self.db.get(key)
        if refresh or not data or now() - data.get("fetched_at", 0) > 1800:
            t = now()
            try:
                cur = self.agent.ig.account_insights(t - days * 86400, t)
                prev = self.agent.ig.account_insights(t - 2 * days * 86400, t - days * 86400)
                metrics = []
                for name, label in METRIC_FA:
                    if name in cur:
                        p = prev.get(name)
                        metrics.append({"key": name, "label": label, "value": cur[name],
                                        "change": int(round((cur[name] - p) * 100.0 / p)) if p else None})
                data = {"days": days, "metrics": metrics, "fetched_at": t, "error": ""}
                self.db.set(key, data)
            except GraphError as e:
                self.agent.problem(e, "insights")
                data = dict(data or {"days": days, "metrics": [], "fetched_at": 0})
                data["error"] = e.fa
        out = dict(data)
        snaps = self.db.q("SELECT day, followers FROM snapshots ORDER BY day DESC LIMIT 60")[::-1]
        inside = snaps[-(days + 1):]
        out["followers"] = {"now": self.agent.ig.acct.get("followers"), "series": snaps,
                            "delta": inside[-1]["followers"] - inside[0]["followers"] if len(inside) > 1 else None}
        out["top"] = self.top_posts(days)
        out["best_hours"] = self.best_hours()
        return out

    def media_detail(self, media_id):
        media_id = str(media_id)
        row = self.db.one("SELECT data FROM media WHERE id=?", (media_id,))
        m = jload(row["data"], {}) if row else {}
        if not m:
            m = self.agent.ig.media_info(media_id)
        hit = self.detail_cache.get(media_id)
        if hit and now() - hit[0] < 600:
            metrics, error = hit[1], ""
        else:
            product = (m.get("media_product_type") or "FEED").upper()
            metrics, error, labels = [], "", dict(METRIC_FA)
            try:
                got = self.agent.ig.media_insights(media_id, product if product in MEDIA_METRICS else "FEED")
                metrics = [{"key": k, "label": labels.get(k, k).replace(" (حساب‌های دیده)", ""), "value": v} for k, v in got.items()]
                self.detail_cache[media_id] = (now(), metrics)
                if len(self.detail_cache) > 200:
                    self.detail_cache.clear()
            except GraphError as e:
                self.agent.problem(e, "insights")
                error = e.fa
        return {"media": m, "metrics": metrics, "error": error,
                "open_comments": len([t for t in self.agent.inbox.threads(media_id=media_id) if t["open"]])}

    def audience(self):
        out, error = {}, ""
        for name in ("gender", "age", "city", "country"):
            try:
                out[name] = self.agent.ig.demographics(name)[:8]
            except GraphError as e:
                if e.kind in ("auth", "network", "throttle"):
                    self.agent.problem(e, "insights")
                    raise
                error = "اینستاگرام آمار مخاطبان را نداد (معمولاً پیج باید دست‌کم ۱۰۰ دنبال‌کننده داشته باشد)."
        return {"groups": out, "error": error if not any(out.values()) else ""}


# ───────────────────────────── the agent ─────────────────────────────

INBOX_SEC = 60
DM_SEC = 60


class Agent:
    """Owns all parts and runs the background loop that keeps the page going."""

    def __init__(self, cfg):
        self.cfg = cfg
        os.makedirs(cfg.data_dir, exist_ok=True)
        try:
            os.chmod(cfg.data_dir, 0o700)
        except OSError:
            pass
        self.db = DB(os.path.join(cfg.data_dir, "agent.db"))
        self.settings = Settings(self.db)
        self.graph = Graph(cfg, self.settings)
        self.graph.token = self.db.get("secret.token") or ""
        self.ig = Instagram(cfg, self.db, self.graph)
        if "version" in self.ig.acct:
            self.graph.version = self.ig.acct["version"]
        self.store = MediaStore(cfg, self.db, self.settings, self.graph)
        self.ai = AI(cfg, self.settings, self.graph, self.ig)
        self.rules = Rules(self.db)
        self.publisher, self.inbox, self.direct, self.analytics = Publisher(self), Inbox(self), Direct(self), Analytics(self)
        self.studio = Studio(self)
        self.sim = None
        self.wake, self.stop_flag = threading.Event(), threading.Event()
        self.thread = None
        self.tick_lock = threading.RLock()
        self.due = {}
        self.cool_until = self.media_at = 0.0
        self.net_fails = 0
        self.rules.seed(enabled=cfg.demo)

    # ── life cycle ──
    def start(self):
        if self.thread is None:
            self.stop_flag.clear()
            self.thread = threading.Thread(target=self.loop, name="agent", daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_flag.set()
        self.wake.set()
        if self.thread is not None:
            self.thread.join(timeout=15)
            self.thread = None
        self.store.tunnel.stop()

    def loop(self):
        while not self.stop_flag.is_set():
            try:
                self.tick()
            except Exception:
                log("agent:", traceback.format_exc())
            self.wake.wait(self.cfg.tick)
            self.wake.clear()

    def tick(self, force=False):
        with self.tick_lock:
            if force:
                self.due.clear()
            if self.sim is not None and self.cfg.demo:
                self.sim.live_tick()
            if not self.ig.connected or self.ig.acct.get("invalid"):
                if self.hand():
                    self.job("remind", 0, self.publisher.tick_hand)
                    self.job("house", 3600, self.store.cleanup)
                return
            self.job("publish", 0, self.publisher.tick)
            if now() < self.cool_until:
                return
            if not self.graph.busy():
                self.job("comments", INBOX_SEC, self.inbox.sync)
                self.job("dms", DM_SEC, self.sync_dms)
            self.job("auto", 0, self.automate)
            self.job("profile", 1800, self.profile_job)
            self.job("quota", 1800, self.quota_job)
            self.job("token", 3600, self.token_job)
            self.job("daily", 300, self.daily_job)
            self.job("house", 3600, self.store.cleanup)

    def job(self, name, every, fn):
        if now() < self.due.get(name, 0):
            return
        self.due[name] = now() + every
        try:
            fn()
            if name == "comments":
                self.net_fails = 0
        except GraphError as e:
            self.problem(e, name)
        except UserError as e:
            log(name + ":", e.message)
        except Exception:
            log(name + ":", traceback.format_exc())

    def problem(self, e, where=""):
        """One place that decides what an Instagram error means for the agent as a whole."""
        if e.kind == "auth":
            if self.ig.acct.get("ig_id") and not self.ig.acct.get("invalid"):
                self.ig.save_acct(invalid=e.fa)
                self.note("اتصال پیج قطع شد. " + e.fa, "alert", "auth")
        elif e.kind == "throttle":
            self.cool_until = now() + 900
            self.note(e.fa, "warn", "throttle", 3600)
        elif e.kind == "network":
            self.net_fails += 1
            if self.net_fails >= 5:
                self.note(e.fa, "warn", "network", 3600)
        elif e.kind == "permission":
            if where == "dms":
                self.db.set("dm.blocked", e.fa)
                self.due["dms"] = now() + 6 * 3600
            label = {"dms": "دایرکت", "comments": "کامنت‌ها", "insights": "آمار", "publish": "انتشار"}.get(where, "اینستاگرام")
            self.note("%s: %s" % (label, e.fa), "warn", "perm-" + where, 86400)
        elif e.kind not in ("transient", "not_ready", "window"):
            self.note(e.fa, "warn", "graph-" + where, 3600)

    # ── jobs ──
    def sync_dms(self):
        self.direct.sync()
        if self.db.get("dm.blocked"):
            self.db.drop("dm.blocked")

    def automate(self):
        self.inbox.automate()
        self.direct.automate()

    def profile_job(self):
        self.ig.refresh_profile()
        self.snapshot()

    def snapshot(self):
        a = self.ig.acct
        if a.get("followers") is None:
            return
        self.db.x("INSERT INTO snapshots (day, ts, followers, follows, media_count) VALUES (?,?,?,?,?) ON CONFLICT(day) DO UPDATE "
                  "SET ts=excluded.ts, followers=excluded.followers, follows=excluded.follows, media_count=excluded.media_count",
                  (time.strftime("%Y-%m-%d"), now(), a.get("followers") or 0, a.get("follows") or 0, a.get("media_count") or 0))

    def quota_job(self):
        try:
            used, total = self.ig.quota()
            self.db.set("quota", {"used": used, "total": total, "at": now()})
        except GraphError as e:
            if e.kind in ("auth", "throttle", "network"):
                raise

    def token_job(self):
        a = self.ig.acct
        if a.get("login") != "ig":
            return
        if now() >= (a.get("token_next") or 0):
            try:
                self.ig.refresh_token()
                self.ig.save_acct(token_next=now() + 7 * 86400)
                self.note("توکن پیج خودکار تمدید شد (۶۰ روز دیگر اعتبار دارد).", "info", "token")
            except GraphError as e:
                # A refused renewal alone does not prove the token is dead (it must be 24h old); normal calls decide that.
                self.ig.save_acct(token_next=now() + 86400)
                log("token renewal failed:", e.message)
        left = (self.ig.acct.get("token_expires") or 0) - now()
        if self.ig.acct.get("token_expires") and left < 7 * 86400:
            self.note("اعتبار توکن پیج تا %s روز دیگر تمام می‌شود و تمدید خودکار انجام نشد. از بخش «ایجنت» توکن تازه بده."
                      % fa(max(0, int(left / 86400))), "alert", "token-exp", 86400)

    def daily_job(self):
        if not self.settings.get("auto.daily_report"):
            return
        lt = time.localtime()
        day = time.strftime("%Y-%m-%d", lt)
        if lt.tm_hour < 21 or self.db.get("report.day") == day:
            return
        self.db.set("report.day", day)
        text = self.report()
        self.note(text, "info", "report")
        self.push(text)

    def report(self):
        a, since = self.ig.acct, now() - 86400
        snaps = self.db.q("SELECT followers FROM snapshots ORDER BY day DESC LIMIT 2")
        delta = snaps[0]["followers"] - snaps[1]["followers"] if len(snaps) == 2 else 0
        return ("گزارش امروز @%s\nدنبال‌کننده: %s (%s%s)\nپست منتشرشده: %s\nکارهای خودکار ایجنت: %s\nمنتظر پاسخ: %s کامنت و %s دایرکت"
                % (a.get("username"), fa(a.get("followers") or 0), "+" if delta >= 0 else "−", fa(abs(delta)),
                   fa(self.db.val("SELECT COUNT(*) FROM posts WHERE status='published' AND published_at>?", (since,))),
                   fa(self.db.val("SELECT COUNT(*) FROM actions WHERE actor!='user' AND ts>?", (since,))),
                   fa(self.inbox.open_count()), fa(self.direct.open_count())))

    def hand(self):
        """No page is connected and the owner chose to post by hand: the agent prepares everything, the owner publishes."""
        return not self.ig.connected and bool(self.settings.get("manual"))

    def facts(self):
        a = self.ig.acct
        if not self.ig.connected:
            count = self.db.val
            return ("پیج به ایجنت وصل نیست؛ صاحب پیج خودش در اپ اینستاگرام پست می‌گذارد و ایجنت محتوا را آماده و یادآوری می‌کند.\n"
                    "آمادهٔ انتشار: %s | یادآوری‌های پیش رو: %s | پیش‌نویس: %s"
                    % (fa(count("SELECT COUNT(*) FROM posts WHERE status='due'")),
                       fa(count("SELECT COUNT(*) FROM posts WHERE status='scheduled'")),
                       fa(count("SELECT COUNT(*) FROM posts WHERE status IN ('draft','canceled')"))))
        return ("دنبال‌کننده: %s | دنبال‌شونده: %s | تعداد پست: %s\nکامنت منتظر پاسخ: %s | دایرکت منتظر پاسخ: %s\n"
                "پست در صف انتشار: %s | پیش‌نویس: %s\nبهترین ساعت‌های انتشار: %s"
                % (fa(a.get("followers") or 0), fa(a.get("follows") or 0), fa(a.get("media_count") or 0),
                   fa(self.inbox.open_count()), fa(self.direct.open_count()),
                   fa(self.db.val("SELECT COUNT(*) FROM posts WHERE status='scheduled'")),
                   fa(self.db.val("SELECT COUNT(*) FROM posts WHERE status IN ('draft','canceled')")),
                   "، ".join("%s:۰۰" % fa(h) for h in self.analytics.best_hours())))

    # ── notes, limits, brakes ──
    def note(self, text, level="info", kind="", dedupe=0):
        if dedupe and kind and self.db.one("SELECT id FROM log WHERE kind=? AND ts>? LIMIT 1", (kind, now() - dedupe)):
            return
        self.db.x("INSERT INTO log (ts, level, kind, text) VALUES (?,?,?,?)", (now(), level, kind, text))
        self.db.x("DELETE FROM log WHERE id<(SELECT MAX(id) FROM log)-400")
        if level == "alert":
            self.push(text)

    def push(self, text):
        try:
            self.telegram("🤖 ایجنت اینستاگرام\n" + text)
        except Exception as e:
            log("telegram:", e)

    def telegram(self, text):
        t = self.settings.all()["telegram"]
        if not (t["token"] and t["chat_id"]):
            return False
        url = "%s/bot%s/sendMessage" % (self.cfg.telegram_api, t["token"])
        data = urllib.parse.urlencode({"chat_id": t["chat_id"], "text": text[:3900]}).encode("utf-8")
        try:
            status, _, body = self.graph.http("POST", url, data, {"Content-Type": "application/x-www-form-urlencoded"}, 15)
        except GraphError:
            raise UserError("به تلگرام وصل نشد (اینترنت یا پروکسی را بررسی کن).")
        if status != 200 or not (jload(body.decode("utf-8", "replace"), {}) or {}).get("ok"):
            raise UserError("تلگرام پیام را نپذیرفت؛ توکن ربات و شناسهٔ چت را بررسی کن.")
        return True

    def has_telegram(self):
        t = self.settings.all()["telegram"]
        return bool(t["token"] and t["chat_id"])

    def telegram_file(self, f, name):
        """Sends one of the agent's files to the owner's own chat. A picture goes as a document, so that Telegram does
        not shrink it; a video stays playable."""
        t = self.settings.all()["telegram"]
        if not (t["token"] and t["chat_id"]):
            return False
        if f["size"] > 50 * 1024 * 1024:
            raise UserError("این فایل برای ربات تلگرام بزرگ است (بیش از ۵۰ مگابایت)؛ «ذخیره در گوشی» را بزن.")
        method, field = ("sendVideo", "video") if f["kind"] == "video" and f["ext"] in ("mp4", "mov") else ("sendDocument", "document")
        boundary = "----ia" + secrets.token_hex(12)
        with open(self.store.path(f), "rb") as fh:
            blob = fh.read()
        parts = [("--%s\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n%s\r\n" % (boundary, t["chat_id"])).encode("utf-8")]
        if method == "sendVideo":
            parts.append(("--%s\r\nContent-Disposition: form-data; name=\"supports_streaming\"\r\n\r\ntrue\r\n" % boundary).encode("utf-8"))
        parts += [("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\nContent-Type: %s\r\n\r\n"
                   % (boundary, field, name, f["mime"])).encode("utf-8"), blob, ("\r\n--%s--\r\n" % boundary).encode("utf-8")]
        url = "%s/bot%s/%s" % (self.cfg.telegram_api, t["token"], method)
        try:
            status, _, body = self.graph.http("POST", url, b"".join(parts), {"Content-Type": "multipart/form-data; boundary=" + boundary}, 300)
        except GraphError:
            raise UserError("به تلگرام وصل نشد (اینترنت یا پروکسی را بررسی کن).")
        if status != 200 or not (jload(body.decode("utf-8", "replace"), {}) or {}).get("ok"):
            raise UserError("تلگرام فایل را نپذیرفت؛ توکن ربات و شناسهٔ چت را بررسی کن.")
        return True

    def acted(self, kind, target, ukey, actor, rule_id, detail):
        self.db.x("INSERT INTO actions (ts, kind, target, ukey, actor, rule_id, detail) VALUES (?,?,?,?,?,?,?)",
                  (now(), kind, str(target), ukey, actor, int(rule_id or 0), str(detail)[:300]))
        self.db.x("DELETE FROM actions WHERE ts<?", (now() - 30 * 86400,))

    def may_act(self):
        done = self.db.val("SELECT COUNT(*) FROM actions WHERE actor!='user' AND ts>?", (now() - 3600,))
        if done >= self.settings.get("limits.per_hour"):
            self.note("ایجنت به سقف کارهای خودکار در یک ساعت رسید و بقیه را کمی بعد انجام می‌دهد.", "warn", "cap", 3600)
            return False
        return True

    def cooling(self, ukey):
        minutes = self.settings.get("limits.cooldown_min")
        if not minutes:
            return False
        return bool(self.db.one("SELECT id FROM actions WHERE ukey=? AND actor!='user' AND kind IN ('reply','dm','private') "
                                "AND ts>? LIMIT 1", (ukey, now() - minutes * 60)))

    def quiet(self):
        lim = self.settings.all()["limits"]
        a, b = lim["quiet_from"], lim["quiet_to"]
        if not a or not b or a == b:
            return False
        t = time.strftime("%H:%M")
        return (a <= t < b) if a < b else (t >= a or t < b)

    # ── page ──
    def media_list(self, refresh=False):
        if self.ig.connected and (refresh or now() - self.media_at > 600):
            items = self.ig.media(30)
            with self.db.lock:
                self.db.x("UPDATE media SET pos=999")
                for i, m in enumerate(items):
                    self.db.x("INSERT INTO media (id, data, ts, pos) VALUES (?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                              "data=excluded.data, ts=excluded.ts, pos=excluded.pos",
                              (str(m.get("id")), jdump(m), parse_ts(m.get("timestamp")), i))
                self.db.x("DELETE FROM media WHERE pos=999 AND ts<?", (now() - 180 * 86400,))
            self.media_at = now()
        return [jload(r["data"], {}) for r in self.db.q("SELECT data FROM media WHERE pos<999 ORDER BY pos")]

    def connect(self, token):
        with self.tick_lock:
            before = self.ig.acct
            old = before.get("ig_id") or before.get("last_ig_id")
            acct, stored = self.ig.connect(token)
            if old and old != acct["ig_id"]:
                self.wipe_page()
            acct.update(connected_at=now(), token_at=now(), token_expires=0, token_next=now() + 25 * 3600, invalid="")
            self.graph.token, self.graph.version = stored, acct["version"]
            self.ig.good.clear()
            self.db.set("secret.token", stored)
            self.db.set("account", acct)
            self.db.drop("dm.blocked")
            self.due.clear()
            self.cool_until = self.media_at = 0.0
            self.snapshot()
            self.note("پیج @%s وصل شد ✓" % acct["username"], "ok", "connect")
        self.wake.set()
        return acct

    def wipe_page(self):
        """A different page was connected: nothing of the old page may leak into (or be published on) the new one."""
        for table in ("comments", "convs", "msgs", "media", "snapshots", "actions"):
            self.db.x("DELETE FROM " + table)
        self.db.x("UPDATE posts SET status='draft', state='{}', manual=0, error='', progress='' "
                  "WHERE status IN ('scheduled','publishing','failed','missed')")
        for key in ("insights.7", "insights.28", "quota", "report.day"):
            self.db.drop(key)

    def disconnect(self):
        with self.tick_lock:
            a = self.ig.acct
            self.graph.token = ""
            self.db.drop("secret.token")
            self.db.set("account", {"last_username": a.get("username") or "", "last_ig_id": a.get("ig_id") or ""})
            self.note("اتصال پیج برداشته شد.", "info", "connect")
            self.db.scrub()

    def status(self):
        a, s, t = self.ig.acct, self.settings.all(), now()
        day = time.mktime(tuple(time.localtime()[:3]) + (0, 0, 0, 0, 0, -1))
        count = self.db.val
        nxt = self.db.one("SELECT * FROM posts WHERE status='scheduled' ORDER BY scheduled_at LIMIT 1")
        return {
            "version": VERSION, "demo": self.cfg.demo, "connected": self.ig.connected, "manual": self.hand(), "now": t,
            "handle": s["brand"]["handle"],
            "account": {k: a.get(k) for k in ("username", "name", "picture", "followers", "follows", "media_count", "bio",
                                              "login", "invalid", "token_expires", "connected_at", "last_username")},
            "autopilot": s["autopilot"], "auto": s["auto"], "quiet": self.quiet(),
            "counts": {
                "open_comments": self.inbox.open_count(), "open_dms": self.direct.open_count(),
                "scheduled": count("SELECT COUNT(*) FROM posts WHERE status='scheduled'"),
                "publishing": count("SELECT COUNT(*) FROM posts WHERE status='publishing'"),
                "failed": count("SELECT COUNT(*) FROM posts WHERE status IN ('failed','missed')"),
                "due": count("SELECT COUNT(*) FROM posts WHERE status='due'"),
                "drafts": count("SELECT COUNT(*) FROM posts WHERE status IN ('draft','canceled')"),
                "published_today": count("SELECT COUNT(*) FROM posts WHERE status='published' AND published_at>=?", (day,)),
                "auto_today": count("SELECT COUNT(*) FROM actions WHERE actor!='user' AND ts>=?", (day,)),
                "unseen": count("SELECT COUNT(*) FROM log WHERE seen=0"),
            },
            "next_post": self.publisher.view(nxt) if nxt else None, "quota": self.db.get("quota"),
            "daily_cap": s["limits"]["daily_posts"], "media": self.store.methods(), "ai": self.ai.mode(),
            "dm_blocked": self.db.get("dm.blocked") or "", "busy": self.graph.busy() or t < self.cool_until,
            "studio": self.studio.state(), "telegram": self.has_telegram(),
        }


# ───────────────────────────── built-in simulator (demo mode and tests) ─────────────────────────────
# A small in-memory stand-in for Meta's Graph API, served by this same program under /_sim/.
# It lets the whole agent be tried (and tested) with a fake page and no internet.

SIM_TOKEN = "IGAAsim0demo0token0000000000000000000000000000"
SIM_FB_TOKEN = "EAAsim0demo0facebook0token00000000000000000000"
SIM_PAGE_TOKEN = "EAAsim0demo0page0token0000000000000000000000000"
PALETTE = [("#f97316", "#db2777"), ("#f59e0b", "#c2410c"), ("#0ea5e9", "#4338ca"), ("#10b981", "#047857"),
           ("#8b5cf6", "#5b21b6"), ("#ef4444", "#991b1b"), ("#14b8a6", "#115e59"), ("#ec4899", "#9d174d")]


class Sim:
    LIVE = [("c", "maryam.k", "قیمت این لاته چنده؟"), ("c", "amir_h72", "خیلی قشنگه 😍"),
            ("d", "sina.photo", "سلام، ساعت کاری‌تون چطوره؟"),
            ("c", "best.followers.shop", "خرید فالوور ارزان و واقعی 👉 www.cheap-follow.xyz"),
            ("c", "narges_r", "تا ساعت چند بازید؟"), ("c", "hamid.coffee", "عالی بود، دمتون گرم 👌"),
            ("d", "kiana.m", "آدرس دقیق‌تون رو می‌فرستید؟"), ("c", "parisa.d", "هزینهٔ ارسال چقدره؟")]

    def __init__(self):
        self.lock = threading.RLock()
        self.token, self.fb_token, self.page_token = SIM_TOKEN, SIM_FB_TOKEN, SIM_PAGE_TOKEN
        self.page_id = "100200300400500"
        self.user = {"id": "9000000000000001", "user_id": "17841400000000001", "username": "demo.cafe", "name": "کافه دمو",
                     "account_type": "BUSINESS", "followers_count": 1840, "follows_count": 312,
                     "biography": "قهوهٔ تازه، هر روز ☕️ | سفارش: دایرکت", "website": "https://example.com"}
        self.seq = 1000
        self.media, self.stories, self.comments, self.convs, self.containers = [], [], {}, {}, {}
        self.calls, self.faults, self.fetched, self.telegram, self.telegram_files = [], [], [], [], []
        self.unknown_fields, self.bad_versions = set(), set()
        self.config_issue, self.versions = "", set()
        self.flat_messages = False                     # True: chats only give message ids; each message is read on its own
        self.refused_params = set()                    # parameter names that POST /media answers with an error
        self.hashtag_cap = MAX_HASHTAGS                # captions with more hashtags are refused
        self.video_seconds = 3
        self.lively = True
        self.quota_used, self.quota_total = 0, 50
        self.next_live, self.live_i = now() + 20, 0
        # stand-ins for the text and picture services the studio talks to
        self.ai_calls, self.ai_script, self.horde_jobs = [], {}, {}
        self.ai_key = "sk_sim_demo_key"
        self.ai_text = None                            # the text service's answer: a string, or a function of the request
        self.ai_delay = 0.0                            # seconds every picture takes
        self.free_gap, self.free_next = {"image": 0.0, "text": 0.0}, {"image": 0.0, "text": 0.0}
        self.horde_polls = 1                           # looks at a queued picture until it is ready
        self.horde_names = ["stable_diffusion", "Deliberate", "Dreamshaper", "AbsoluteReality", "WAI-NSFW-illustrious-SDXL"]
        self.seed()

    def nid(self, prefix):
        self.seq += 1
        return "%s%012d" % (prefix, self.seq)

    # ── content for the fake page ──
    def seed(self):
        t = now()
        posts = [("لاتهٔ پاییزی با دارچین 🍂 امروز تا ساعت ۲۳ منتظرتونیم.\n#کافه #لاته #پاییز", "IMAGE", 0, 18, 214),
                 ("صبح‌ها با بوی قهوهٔ تازه شروع می‌شه ☕️", "IMAGE", 1, 21, 162),
                 ("پشت‌صحنهٔ دم‌کردن V60 🎬", "VIDEO", 2, 12, 530),
                 ("منوی کیک‌های این هفته 🍰 ورق بزنید", "CAROUSEL_ALBUM", 3, 18, 389),
                 ("دانهٔ تازه‌رسیدهٔ اتیوپی رسید!", "IMAGE", 5, 9, 121),
                 ("لاته‌آرت امروز از باریستای خوبمون 🎬", "VIDEO", 7, 21, 742),
                 ("صبحانهٔ دونفره، فقط جمعه‌ها", "IMAGE", 9, 12, 88),
                 ("فضای دنج طبقهٔ بالا 🌿", "CAROUSEL_ALBUM", 12, 18, 276),
                 ("موسیقی زنده پنجشنبه‌شب‌ها 🎶", "IMAGE", 15, 21, 305),
                 ("چای ماسالا برای روزهای سرد", "IMAGE", 19, 15, 97)]
        for i, (caption, mtype, days, hour, likes) in enumerate(posts):
            day = time.localtime(t - days * 86400)
            ts = time.mktime(tuple(day[:3]) + (hour, 7, 0, 0, 0, -1)) if days else t - 5 * 3600
            self.media.append(self.make_media(caption, mtype, min(ts, t - 5 * 3600), likes, i))
        h = 3600
        first = self.add_comment("چه قشنگ شده 😍", "ali_rz", 0, ts=t - 3 * h)
        self.add_comment("ممنون از لطف‌تون 🌹", self.user["username"], 0, parent=first, ts=t - 2.9 * h)
        self.add_comment("قیمت لاته چنده؟", "sara.mohammadi", 0, ts=t - 2 * h)
        self.add_comment("فالوور ارزان و واقعی فقط با ما 👉 www.follow-shop.xyz", "promo_fast_follow", 0, ts=t - 0.8 * h)
        self.add_comment("تا ساعت چند بازید؟", "niloofar.art", 0, ts=t - 0.5 * h)
        self.add_comment("آدرس دقیق‌تون کجاست؟", "mehdi.k", 1, ts=t - 5 * h)
        self.add_comment("دفعهٔ قبل عالی بود 👌", "zahra_bn", 1, ts=t - 20 * h)
        self.add_comment("این آهنگ چیه؟", "omid.t", 2, ts=t - 6 * 86400)
        self.add_comment("کیک هویج هم دارید؟", "shirin_gh", 3, ts=t - 8 * 86400)
        self.add_dm("سلام، ساعت کاری‌تون چطوره؟", "elham.gh", ts=t - 0.3 * h)
        self.add_dm("سلام، برای همکاری تبلیغاتی پیام دادم.", "reza.dev", ts=t - 3 * h)
        old = self.add_dm("سفارش عمده هم قبول می‌کنید؟", "bahar.s", ts=t - 5 * 86400)
        self.convs[old]["messages"].append({"id": self.nid("m_"), "from_me": True, "text": "سلام، بله 🌹 جزئیات را بفرمایید.",
                                            "ts": t - 5 * 86400 + 900})
        self.convs[old]["updated"] = t - 5 * 86400 + 900

    def make_media(self, caption, mtype, ts, likes, n, product=None, blob=None):
        mid = self.nid("180")
        return {"id": mid, "caption": caption, "media_type": mtype, "ts": ts, "like_count": likes, "n": n, "blob": blob,
                "media_product_type": product or ("REELS" if mtype == "VIDEO" else "FEED"), "comment_enabled": True,
                "code": "D" + hashlib.md5(mid.encode()).hexdigest()[:10]}

    @staticmethod
    def uid(username):
        return str(6000000000 + zlib.crc32(username.encode("utf-8")) % 1000000000)

    def add_comment(self, text, username="someone", media_index=0, parent="", ts=None, media_id=None):
        with self.lock:
            cid = self.nid("179")
            mine = username == self.user["username"]
            self.comments[cid] = {"id": cid, "media_id": media_id or self.media[media_index]["id"], "parent_id": parent or "",
                                  "text": text, "ts": now() if ts is None else ts, "username": username,
                                  "user_id": self.user["user_id"] if mine else self.uid(username), "hidden": False,
                                  "dm_done": False}
            return cid

    def conv_for(self, username):
        uid = self.uid(username)
        for c in self.convs.values():
            if c["user_id"] == uid:
                return c
        cid = "t_" + self.nid("")
        self.convs[cid] = {"id": cid, "user_id": uid, "username": username, "updated": 0.0, "messages": []}
        return self.convs[cid]

    def add_dm(self, text, username="someone", ts=None):
        with self.lock:
            conv = self.conv_for(username)
            ts = now() if ts is None else ts
            conv["messages"].append({"id": self.nid("m_"), "from_me": False, "text": text, "ts": ts})
            conv["updated"] = max(ts, conv["updated"] + 1)
            return conv["id"]

    def live_tick(self):
        """Demo only: every now and then somebody comments or writes, so the agent can be watched working."""
        if not self.lively or now() < self.next_live:
            return
        with self.lock:
            kind, user, text = self.LIVE[self.live_i % len(self.LIVE)]
            cycle = self.live_i // len(self.LIVE)
            self.live_i += 1
            self.next_live = now() + random.randint(35, 70)
            user = user if cycle == 0 else "%s%d" % (user, cycle + 1)
            if kind == "c":
                self.add_comment(text, user, self.live_i % 3)
            else:
                self.add_dm(text, user)
            if self.live_i % 3 == 0:
                self.user["followers_count"] += 1

    # ── test hooks ──
    def fail(self, pattern, code=2, sub=0, message="simulated failure", status=400, times=1, method=None, drop=False):
        """Next matching call(s) fail. drop=True: the action happens but the answer is lost."""
        self.faults.append({"pattern": pattern, "method": method, "times": times, "drop": drop, "status": status,
                            "error": {"message": message, "type": "OAuthException", "code": code, "error_subcode": sub}})

    def demo_plan(self, body):
        """Demo only: the studio's question gets a made-up but sensible answer. Every other question gets none, so
        the assistant falls back to its templates, exactly as it does without internet."""
        ask = str((((body or {}).get("messages") or [{}])[-1]).get("content") or "")
        m = re.match(r"ایده: «(.*?)»\n", ask, re.S)
        if not m or "JSON" not in ask:
            return None
        idea, n = m.group(1).strip(), re.search(r"ریل (\d+) صحنه", ask)
        head = shorten(idea, 44)
        lines = [head, "همین هفته", "با بهترین کیفیت", "منتظرتان هستیم", "همین حالا پیام بده", "جزئیات در کپشن"]
        scenes = [{"text": lines[i % len(lines)], "image": "scene %d of a short video about a small business offer, warm light" % (i + 1)}
                  for i in range(int(n.group(1)) if n else 0)]
        return jdump({"caption": "%s ✨\nهمین امروز سر بزنید؛ منتظرتان هستیم 🌿" % idea, "hashtags": ["#پیشنهاد_ویژه", "#کسب_و_کار", "#اینستاگرام"],
                      "headline": head, "sub": "همین حالا پیام بده", "image": "a warm, inviting photo that shows the offer", "scenes": scenes})

    def script(self, service, status, obj=None, headers=None, times=1):
        """The next call(s) to one of the AI stand-ins ("pimg", "pgen", "horde", "oimg", "ptxt") get this answer."""
        self.ai_script.setdefault(service, []).extend([(status, obj if obj is not None else {}, headers or {})] * times)

    def free_turn(self, what):
        """The free service serves one request every so often per address; the others are told how long to wait."""
        with self.lock:
            left = self.free_next[what] - now()
            if left > 0:
                return int(left + 0.999)
            self.free_next[what] = now() + self.free_gap[what]
            return 0

    def ai(self, method, path, q, raw, headers):
        """(status, content type, body, extra headers) of the simulated text and picture services."""
        service, _, tail = path.partition("/")
        body = jload(raw.decode("utf-8", "replace"), None) if raw else None

        def answer(status, obj, extra=None):
            return status, "application/json; charset=utf-8", jdump(obj).encode("utf-8"), extra or {}

        def picture(text, width, height):
            if self.ai_delay:
                time.sleep(self.ai_delay)
            return 200, "image/png", fake_picture(text, width, height), {"x-model-used": "sim"}

        with self.lock:
            self.ai_calls.append((service, method, tail, dict(q), body, {k.lower(): v for k, v in headers.items()}))
            if len(self.ai_calls) > 2000:
                del self.ai_calls[:1000]
            queue = self.ai_script.get(service)
            if queue:
                status, obj, extra = queue.pop(0)
                return answer(status, obj, extra)
        limit = lambda what, left: answer(402, {"status": 402, "success": False, "error": {"code": "FREE_LIMIT", "message": (
            "Free limit reached: 1 %s every 45 seconds per IP. Retry after %ds, or get unlimited %ss with a pollen key" % (what, left, what))}})
        bearer = headers.get("Authorization") or ""
        width, height = clamp(q.get("width") or 768, 64, 2048), clamp(q.get("height") or 960, 64, 2048)
        if service == "pimg" and tail.startswith("prompt/"):
            left = self.free_turn("image")
            return limit("image", left) if left else picture(tail + str(q.get("seed")), width * 5 // 8, height * 5 // 8)
        if service == "pgen":
            if bearer != "Bearer " + self.ai_key:
                return answer(401, {"success": False, "error": {"message": "A valid API key is required.", "code": "UNAUTHORIZED"}, "status": 401})
            if tail.startswith("image/"):
                return picture(tail + str(q.get("seed")), width, height)
            if tail == "v1/chat/completions" and method == "POST":
                said = self.ai_text(body or {}) if callable(self.ai_text) else self.ai_text
                if said is None:
                    return answer(500, {"error": {"message": "the simulated text service has nothing to say"}})
                return answer(200, {"choices": [{"index": 0, "message": {"role": "assistant", "content": said}, "finish_reason": "stop"}],
                                    "model": "openai/gpt-5.4-nano"})
        if service == "oimg" and tail == "images/generations" and method == "POST":
            if bearer != "Bearer " + self.ai_key:
                return answer(401, {"error": {"message": "Incorrect API key provided", "type": "invalid_request_error"}})
            w, _, h = str((body or {}).get("size") or "1024x1024").partition("x")
            blob = picture(str((body or {}).get("prompt")), clamp(w, 64, 2048), clamp(h, 64, 2048))[2]
            return answer(200, {"created": int(now()), "data": [{"b64_json": base64.b64encode(blob).decode("ascii")}]})
        if service == "ptxt":
            left = self.free_turn("text")
            if left:
                return limit("reply", left)
            said = self.ai_text(body or dict(q, prompt=urllib.parse.unquote(tail))) if callable(self.ai_text) else self.ai_text
            if said is None:
                return answer(500, {"error": "the simulated text service has nothing to say"})
            if method == "POST" and tail == "openai":
                return answer(200, {"choices": [{"index": 0, "message": {"role": "assistant", "content": said}, "finish_reason": "stop"}]})
            return 200, "text/plain; charset=utf-8", str(said).encode("utf-8"), {}
        if service == "horde":
            if headers.get("apikey") != "0000000000":
                return answer(401, {"message": "No user matching sent API Key. Have you remembered to register at https://aihorde.net/register ?", "rc": "InvalidAPIKey"})
            if tail == "status/models":
                return answer(200, [{"name": n, "count": 3, "queued": 0, "eta": 5, "type": "image"} for n in self.horde_names])
            if tail == "generate/async" and method == "POST":
                params = (body or {}).get("params") or {}
                if clamp(params.get("width") or 0, 0, 9999) * clamp(params.get("height") or 0, 0, 9999) > 576 * 576:
                    return answer(403, {"message": "Due to heavy demand, for requests over 576x576 or over the applicable first-order-equivalent "
                                                   "sampler work budget the client needs to already have the required kudos.", "rc": "KudosUpfront"})
                rid = "%s-%s" % (secrets.token_hex(4), secrets.token_hex(6))
                with self.lock:
                    self.horde_jobs[rid] = {"left": self.horde_polls, "body": body or {}, "canceled": False}
                return answer(202, {"id": rid, "kudos": 6.0})
            m = re.fullmatch(r"generate/(check|status)/([\w-]+)", tail)
            job = self.horde_jobs.get(m.group(2)) if m else None
            if not job:
                return answer(404, {"message": "Request not found", "rc": "RequestNotFound"})
            if method == "DELETE":
                job["canceled"] = True
                return answer(200, {"done": False, "generations": []})
            if m.group(1) == "check":
                with self.lock:
                    job["left"] -= 1
                    done = job["left"] <= 0
                return answer(200, {"done": done, "faulted": False, "is_possible": True, "wait_time": 0 if done else 8,
                                    "queue_position": 0 if done else job["left"], "finished": int(done), "waiting": int(not done)})
            params = job["body"].get("params") or {}
            blob = picture(str(job["body"].get("prompt")) + str(params.get("seed")), clamp(params.get("width") or 512, 64, 1024),
                           clamp(params.get("height") or 512, 64, 1024))[2]
            return answer(200, {"done": True, "generations": [{"img": base64.b64encode(blob).decode("ascii"), "censored": False, "state": "ok",
                                                               "model": (job["body"].get("models") or ["stable_diffusion"])[0],
                                                               "seed": str(params.get("seed"))}]})
        return answer(404, {"error": "not found"})

    @staticmethod
    def err(code, message, sub=0, status=400):
        e = {"message": message, "type": "OAuthException", "code": code}
        if sub:
            e["error_subcode"] = sub
        return status, {"error": e}

    def fetch(self, url):
        self.fetched.append(url)
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            req = urllib.request.Request(url, headers={"User-Agent": "facebookexternalhit/1.1"})
            with opener.open(req, timeout=10) as res:
                return res.status == 200, res.read(3 * 1024 * 1024 + 1)
        except Exception:
            return False, b""

    # ── the API ──
    def handle(self, method, host, path, params, body=None, bearer=""):
        parts = [p for p in path.split("/") if p]
        if parts and re.fullmatch(r"v\d+\.\d+", parts[0]):
            self.versions.add(parts[0])
            if parts.pop(0) in self.bad_versions:
                return self.err(2635, "You are calling a version of the API that is not available")
        key = "/".join(parts)
        fetched = None
        if method == "POST" and key.endswith("/media") and (params.get("video_url") or params.get("image_url")):
            fetched = self.fetch(params.get("video_url") or params.get("image_url"))     # outside the lock
        with self.lock:
            self.calls.append((method, key, dict(params)))
            if len(self.calls) > 4000:
                del self.calls[:2000]
            for f in self.faults:
                if f["times"] > 0 and f["method"] in (None, method) and re.search(f["pattern"], key):
                    f["times"] -= 1
                    if f["drop"]:
                        self.route(method, host, parts, params, body, bearer, fetched)
                        return 502, None
                    return f["status"], {"error": f["error"]}
            return self.route(method, host, parts, params, body, bearer, fetched)

    def route(self, method, host, parts, params, body, bearer, fetched):
        token = params.get("access_token") or bearer or ""
        if token not in ((self.token,) if host == "ig" else (self.fb_token, self.page_token)):
            return self.err(190, "Invalid OAuth access token - Cannot parse access token")
        me, n = self.user["user_id"], len(parts)
        head = parts[0] if parts else ""
        bad = [f for f in re.split(r"[,{}]", params.get("fields") or "") if f in self.unknown_fields]
        if bad:
            return self.err(100, "Tried accessing nonexisting field (%s)" % bad[0])
        if host == "fb" and parts == ["me", "accounts"]:
            return 200, {"data": [{"id": self.page_id, "name": "Demo Cafe", "access_token": self.page_token,
                                   "instagram_business_account": {"id": me, "username": self.user["username"]}}]}
        if parts == ["refresh_access_token"]:
            self.token = "IGAA" + secrets.token_hex(24)
            return 200, {"access_token": self.token, "token_type": "bearer", "expires_in": 5183944}
        if head in ("me", me, self.user["id"], self.page_id):
            if n == 1 and method == "GET":
                return self.profile(params.get("fields") or "id", host)
            edge = parts[1] if n == 2 else ""
            if edge == "media":
                if method == "POST":
                    return self.create_container(params, fetched)
                limit = clamp(params.get("limit") or 25, 1, 100)
                return 200, {"data": [self.media_out(m, params) for m in self.media[:limit]]}
            if edge == "media_publish" and method == "POST":
                return self.publish(params)
            if edge == "content_publishing_limit":
                return 200, {"data": [{"quota_usage": self.quota_used, "config": {"quota_total": self.quota_total,
                                                                               "quota_duration": 86400}}]}
            if edge == "stories":
                return 200, {"data": [self.media_out(m, params) for m in self.stories if m["ts"] > now() - 86400]}
            if edge == "tags":
                return 200, {"data": []}
            if edge == "insights":
                return self.account_insights(params)
            if edge == "conversations":
                return 200, {"data": [self.conv_out(c, params.get("fields") or "id,updated_time")
                                      for c in sorted(self.convs.values(), key=lambda c: -c["updated"])]}
            if edge == "messages" and method == "POST":
                return self.send_message(body if isinstance(body, dict) else params)
        if head in self.containers and n == 1 and method == "GET":
            return 200, self.container_out(self.containers[head])
        m = next((x for x in self.media + self.stories if x["id"] == head), None)
        if m is not None:
            if n == 1 and method == "GET":
                return 200, self.media_out(m, params)
            if n == 1 and method == "POST":
                if "comment_enabled" in params:
                    m["comment_enabled"] = params["comment_enabled"] == "true"
                return 200, {"success": True}
            if n == 2 and parts[1] == "comments":
                if method == "POST":
                    return self.page_comment(m["id"], "", params.get("message"))
                return self.comments_out(m, params)
            if n == 2 and parts[1] == "insights":
                return self.media_insights(m, params)
        c = self.comments.get(head)
        if c is not None:
            if n == 1 and method == "DELETE":
                for cid in [k for k, v in self.comments.items() if k == head or v["parent_id"] == head]:
                    del self.comments[cid]
                return 200, {"success": True}
            if n == 1 and method == "POST":
                if "hide" in params:
                    c["hidden"] = params["hide"] == "true"
                return 200, {"success": True}
            if n == 1:
                return 200, self.comment_out(c)
            if n == 2 and parts[1] == "replies" and method == "POST":
                if c["parent_id"]:
                    return self.err(100, "Replies can only be created on top-level comments")
                return self.page_comment(c["media_id"], c["id"], params.get("message"))
        conv = self.convs.get(head)
        if conv is not None and n == 1 and method == "GET":
            fields = params.get("fields") or ""
            if "messages" not in fields:
                return 200, {"id": conv["id"], "updated_time": iso(conv["updated"])}
            if re.search(r"messages\s*[.{]", fields):
                if self.flat_messages:
                    return self.err(100, "Syntax error: field expansion is not supported on this edge")
                rows = [self.msg_out(conv, x) for x in reversed(conv["messages"][-30:])]
            else:
                rows = [{"id": x["id"], "created_time": iso(x["ts"])} for x in reversed(conv["messages"])]
            return 200, {"id": conv["id"], "messages": {"data": rows}}
        for conv in self.convs.values():
            for i, x in enumerate(reversed(conv["messages"])):
                if x["id"] == head and n == 1 and method == "GET":
                    if i >= 20:
                        return self.err(100, "This message has been deleted")
                    want = set((params.get("fields") or "id,created_time").split(","))
                    return 200, {k: v for k, v in self.msg_out(conv, x).items() if k in want or k == "id"}
        return self.err(100, "Unsupported request - object with ID '%s' does not exist" % head, sub=33)

    def profile(self, fields, host):
        full = dict(self.user, media_count=len(self.media), profile_picture_url="/_sim/img/avatar.svg")
        if host == "fb":
            full["id"] = full.pop("user_id")
            full.pop("account_type")
        out = {}
        for f in [x for x in fields.split(",") if x]:
            if f not in full:
                return self.err(100, "Tried accessing nonexisting field (%s)" % f)
            out[f] = full[f]
        return 200, out

    def media_out(self, m, params=None):
        thumb = "/_sim/pub/%s.jpg" % m["id"] if m["blob"] else "/_sim/img/%d.svg" % m["n"]
        out = {"id": m["id"], "caption": m["caption"], "media_type": m["media_type"], "timestamp": iso(m["ts"]),
               "media_product_type": m["media_product_type"], "permalink": "https://www.instagram.com/p/%s/" % m["code"],
               "like_count": m["like_count"], "is_comment_enabled": m["comment_enabled"],
               "comments_count": len([1 for c in self.comments.values() if c["media_id"] == m["id"]])}
        if m["media_type"] == "VIDEO":
            out["thumbnail_url"] = thumb
        else:
            out["media_url"] = thumb
        asked = [f for f in ((params or {}).get("fields") or "").split(",") if f]
        return {k: v for k, v in out.items() if k == "id" or k in asked} if asked else out

    def create_container(self, p, fetched):
        for name in sorted(self.refused_params):
            if name in p:
                return self.err(100, "Unsupported parameter: %s is not available for this API" % name)
        mtype = (p.get("media_type") or "IMAGE").upper()
        caption = p.get("caption") or ""
        if len(caption) > 2200:
            return self.err(36004, "The caption was too long", sub=2207010)
        if count_tags(caption)[0] > self.hashtag_cap:
            return self.err(100, "The caption contains too many hashtags")
        c = {"id": self.nid("178"), "type": mtype, "caption": caption, "ready_at": now(), "published": False, "error": "",
             "expired": False, "kids": [], "video": False, "blob": None, "item": p.get("is_carousel_item") == "true"}
        if mtype == "CAROUSEL":
            kids = [k for k in (p.get("children") or "").split(",") if k]
            if not 2 <= len(kids) <= 20 or any(k not in self.containers or not self.containers[k]["item"] for k in kids):
                return self.err(100, "Invalid parameter: children")
            c["kids"] = kids
        else:
            if not (p.get("video_url") or p.get("image_url")):
                return self.err(100, "The parameter image_url or video_url is required")
            ok, data = fetched or (False, b"")
            if not ok:
                return self.err(9004, "Media download has failed. The media URI doesn't meet our requirements.", sub=2207052)
            kind = sniff(data[:64])
            if p.get("video_url"):
                c["video"], c["ready_at"] = True, now() + self.video_seconds
                if not kind or kind[0] != "video":
                    c["error"] = "Unsupported video format"
            elif not kind or kind[1] != "jpg":
                return self.err(36001, "The image format is not supported. Supported formats are: JPEG.", sub=2207005)
            else:
                c["blob"] = data if len(data) <= 3 * 1024 * 1024 else None
        self.containers[c["id"]] = c
        return 200, {"id": c["id"]}

    def container_out(self, c):
        code = ("PUBLISHED" if c["published"] else "EXPIRED" if c["expired"] else "ERROR" if c["error"]
                else "IN_PROGRESS" if now() < c["ready_at"] else "FINISHED")
        return {"id": c["id"], "status_code": code, "status": c["error"] or code.title()}

    def publish(self, p):
        c = self.containers.get(p.get("creation_id") or "")
        if c is None:
            return self.err(100, "Invalid parameter: creation_id")
        code = self.container_out(c)["status_code"]
        if code == "PUBLISHED" or c["item"]:
            return self.err(100, "This container cannot be published")
        if code != "FINISHED":
            return self.err(9007, "Media ID is not available", sub=2207027)
        if self.quota_used >= self.quota_total:
            return self.err(9, "Content publishing limit reached", sub=2207042)
        c["published"] = True
        self.quota_used += 1
        issue = self.config_issue if c["caption"] else ""
        src = self.containers[c["kids"][0]] if c["type"] == "CAROUSEL" else c
        if c["type"] == "CAROUSEL":
            mtype, product = "CAROUSEL_ALBUM", "FEED"
        elif c["type"] == "STORIES":
            mtype, product = ("VIDEO" if c["video"] else "IMAGE"), "STORY"
        elif c["video"]:
            mtype, product = "VIDEO", "REELS"
        else:
            mtype, product = "IMAGE", "FEED"
        m = self.make_media("" if issue == "CAPTION_NOT_ATTACHED" else c["caption"], mtype, now(), 0,
                            self.seq % len(PALETTE), product, src["blob"])
        (self.stories if product == "STORY" else self.media).insert(0, m)
        return 200, ({"id": m["id"], "config_issue": issue} if issue else {"id": m["id"]})

    def comment_out(self, c):
        out = {"id": c["id"], "text": c["text"], "timestamp": iso(c["ts"]), "username": c["username"],
               "from": {"id": c["user_id"], "username": c["username"]}, "hidden": c["hidden"], "like_count": 0}
        if c["parent_id"]:
            out["parent_id"] = c["parent_id"]
        return out

    def comments_out(self, m, p):
        tops = sorted([c for c in self.comments.values() if c["media_id"] == m["id"] and not c["parent_id"]],
                      key=lambda c: (-c["ts"], c["id"]))
        limit = clamp(p.get("limit") or 50, 1, 100)
        data = []
        for c in tops[:limit]:
            out = self.comment_out(c)
            kids = sorted([r for r in self.comments.values() if r["parent_id"] == c["id"]], key=lambda r: (r["ts"], r["id"]))
            if kids:
                out["replies"] = {"data": [self.comment_out(r) for r in kids[:25]]}
            data.append(out)
        res = {"data": data}
        if len(tops) > limit:
            res["paging"] = {"cursors": {"after": "next"}, "next": "https://graph.invalid/next"}
        return 200, res

    def page_comment(self, media_id, parent, message):
        if not message:
            return self.err(100, "The parameter message is required")
        return 200, {"id": self.add_comment(message, self.user["username"], parent=parent, media_id=media_id)}

    def conv_out(self, c, fields="id,updated_time,participants"):
        out = {"id": c["id"], "updated_time": iso(c["updated"])}
        if "participants" in fields.split(","):
            out["participants"] = {"data": [{"id": self.user["user_id"], "username": self.user["username"]},
                                            {"id": c["user_id"], "username": c["username"]}]}
        return out

    def msg_out(self, conv, m):
        page = {"id": self.user["user_id"], "username": self.user["username"]}
        other = {"id": conv["user_id"], "username": conv["username"]}
        return {"id": m["id"], "created_time": iso(m["ts"]), "message": m["text"], "from": page if m["from_me"] else other,
                "to": {"data": [other if m["from_me"] else page]}}

    def send_message(self, b):
        rec, msg = b.get("recipient"), b.get("message")
        rec = jload(rec, {}) if isinstance(rec, str) else (rec or {})
        msg = jload(msg, {}) if isinstance(msg, str) else (msg or {})
        text = msg.get("text") or ""
        if not rec or not text:
            return self.err(100, "Invalid parameter")
        if len(text.encode("utf-8")) > 1000:
            return self.err(100, "Length of param message[text] must be less than or equal to 1000")
        if rec.get("comment_id"):
            c = self.comments.get(str(rec["comment_id"]))
            if c is None:
                return self.err(100, "Invalid parameter: comment_id")
            if c["dm_done"] or now() - c["ts"] > 7 * 86400:
                return self.err(10, "This message is sent outside of allowed window.", sub=2534022)
            c["dm_done"] = True
            conv = self.conv_for(c["username"])
        else:
            conv = next((x for x in self.convs.values() if x["user_id"] == str(rec.get("id"))), None)
            if conv is None:
                return self.err(100, "No matching user found", sub=2018001)
            if now() - max([x["ts"] for x in conv["messages"] if not x["from_me"]] or [0]) > 86400:
                return self.err(10, "This message is sent outside of allowed window.", sub=2534022)
        mid = self.nid("m_")
        conv["messages"].append({"id": mid, "from_me": True, "text": text, "ts": now()})
        conv["updated"] = max(now(), conv["updated"] + 1)
        return 200, {"recipient_id": conv["user_id"], "message_id": mid}

    @staticmethod
    def metric(name, since, until):
        base = {"reach": 370, "views": 1010, "accounts_engaged": 57, "total_interactions": 127, "likes": 91, "comments": 13,
                "shares": 9, "saves": 13, "replies": 7, "profile_links_taps": 5}[name]
        days = max(1, int(round((until - since) / 86400.0)))
        wobble = zlib.crc32(("%s:%d" % (name, int(since) // 86400)).encode()) % 50
        return int(base * days * (0.75 + wobble / 100.0))

    def account_insights(self, p):
        names = [x for x in (p.get("metric") or "").split(",") if x]
        if names == ["follower_demographics"]:
            table = {"gender": [("F", 1012), ("M", 736), ("U", 92)],
                     "age": [("25-34", 810), ("18-24", 520), ("35-44", 330), ("45-54", 120), ("13-17", 60)],
                     "city": [("Tehran, Tehran Province", 640), ("Mashhad, Razavi Khorasan", 210), ("Isfahan", 190),
                              ("Shiraz, Fars", 150), ("Kabul", 90)],
                     "country": [("IR", 1500), ("AF", 140), ("DE", 80), ("TR", 60), ("NL", 30)]}.get(p.get("breakdown"))
            if table is None:
                return self.err(100, "Invalid parameter: breakdown")
            results = [{"dimension_values": [k], "value": v} for k, v in table]
            return 200, {"data": [{"name": "follower_demographics", "period": "lifetime",
                                   "total_value": {"breakdowns": [{"dimension_keys": [p["breakdown"]], "results": results}]}}]}
        bad = [x for x in names if x not in ACCOUNT_METRICS]
        if bad or not names:
            return self.err(100, "metric[0] must be one of the following values: " + ", ".join(ACCOUNT_METRICS))
        since, until = float(p.get("since") or now() - 86400), float(p.get("until") or now())
        if until - since > 30 * 86400 + 60:
            return self.err(100, "There cannot be more than 30 days (2592000 s) between since and until")
        return 200, {"data": [{"name": x, "period": "day", "title": x, "total_value": {"value": self.metric(x, since, until)}}
                              for x in names]}

    def media_insights(self, m, p):
        names = [x for x in (p.get("metric") or "").split(",") if x]
        allowed = MEDIA_METRICS["STORY" if m["media_product_type"] == "STORY" else "FEED"]
        if not names or any(x not in allowed for x in names):
            return self.err(100, "The Media Insights API does not support the requested metric for this media type")
        likes = m["like_count"]
        comments = len([1 for c in self.comments.values() if c["media_id"] == m["id"]])
        vals = {"reach": likes * 3 + 40, "views": likes * 7 + 90, "likes": likes, "comments": comments, "saved": likes // 7,
                "shares": likes // 10, "replies": likes // 20}
        vals["total_interactions"] = likes + comments + vals["saved"] + vals["shares"]
        return 200, {"data": [{"name": x, "period": "lifetime", "values": [{"value": vals[x]}]} for x in names]}

    # ── pictures of the fake page ──
    def asset(self, name):
        m = re.fullmatch(r"pub/(\d+)\.jpg", name)
        if m:
            item = next((x for x in self.media + self.stories if x["id"] == m.group(1) and x["blob"]), None)
            return ("image/jpeg", item["blob"]) if item else None
        m = re.fullmatch(r"img/(\d+|avatar)\.svg", name)
        if not m:
            return None
        a, b = PALETTE[1] if m.group(1) == "avatar" else PALETTE[int(m.group(1)) % len(PALETTE)]
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400"><defs><linearGradient id="g" x1="0" y1="0" '
               'x2="1" y2="1"><stop offset="0" stop-color="%s"/><stop offset="1" stop-color="%s"/></linearGradient></defs>'
               '<rect width="400" height="400" fill="url(#g)"/><circle cx="310" cy="90" r="120" fill="#fff" opacity=".14"/>'
               '<circle cx="70" cy="350" r="140" fill="#000" opacity=".12"/></svg>' % (a, b))
        return "image/svg+xml", svg.encode("utf-8")


# ───────────────────────────── web panel (server side) ─────────────────────────────

KEY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
SESSION_COOKIE = "ia_session"
ICON_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><defs><linearGradient id="g" x1="0" y1="1" x2="1" y2="0">'
            '<stop offset="0" stop-color="#f59e0b"/><stop offset=".5" stop-color="#ec4899"/><stop offset="1" stop-color="#8b5cf6"/>'
            '</linearGradient></defs><rect width="64" height="64" rx="16" fill="url(#g)"/><rect x="16" y="16" width="32" height="32" '
            'rx="10" fill="none" stroke="#fff" stroke-width="4"/><circle cx="32" cy="32" r="7.5" fill="none" stroke="#fff" '
            'stroke-width="4"/><circle cx="42" cy="22" r="2.6" fill="#fff"/></svg>')
MANIFEST = {"name": "ایجنت اینستاگرام", "short_name": "ایجنت پیج", "start_url": "/", "display": "standalone", "dir": "rtl",
            "lang": "fa", "background_color": "#0b0f1a", "theme_color": "#0b0f1a",
            "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
                      {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"}]}


def png_file(width, height, rows):
    """A PNG out of raw RGB rows (each row starts with a zero byte), so that no image library is needed."""
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(rows), 6)) + chunk(b"IEND", b""))


def fake_picture(text, width, height):
    """What the simulated picture services send (demo and tests): a sky, a sun and a table, coloured after the request."""
    width, height = clamp(width, 64, 640), clamp(height, 64, 1136)
    seed = zlib.crc32(str(text).encode("utf-8"))
    top, bottom = [tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in PALETTE[seed % len(PALETTE)]]
    sun_x, sun_y, sun_r = int(width * (0.22 + (seed >> 8) % 56 / 100.0)), height * 0.3, width * 0.17
    table = int(height * (0.68 + (seed >> 16) % 10 / 100.0))
    rows = bytearray()
    for y in range(height):
        t = y / float(height - 1)
        row = bytearray(bytes(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)) * width)
        dy = y - sun_y
        if abs(dy) < sun_r:
            half = int((sun_r * sun_r - dy * dy) ** 0.5)
            x0, x1 = max(0, sun_x - half), min(width, sun_x + half)
            row[x0 * 3:x1 * 3] = bytes((255, 240, 205)) * (x1 - x0)
        if y >= table:
            shade = 0.55 - 0.25 * (y - table) / float(max(1, height - table))
            row[:] = bytes(int(bottom[i] * shade) for i in range(3)) * width
            edge = min(width, max(0, int(width * 0.18 + (y - table) * 0.9)))
            row[:edge * 3] = bytes(int(top[i] * shade * 0.9) for i in range(3)) * edge
        rows.append(0)
        rows.extend(row)
    return png_file(width, height, rows)


def make_icon_png(size):
    """The home-screen icon, drawn by hand so that no image library is needed."""
    rows = bytearray()
    mid, ring_out, ring_in, dot = (size - 1) / 2.0, size * 0.30, size * 0.23, size * 0.08
    for y in range(size):
        rows.append(0)
        for x in range(size):
            t = (x + (size - y)) / (2.0 * size)
            col = (int(245 + (139 - 245) * t), int(158 + (92 - 158) * t), int(11 + (246 - 11) * t))
            d = ((x - mid) ** 2 + (y - mid) ** 2) ** 0.5
            if ring_in <= d <= ring_out or d <= dot:
                col = (255, 255, 255)
            rows.extend(col)
    return png_file(size, size, rows)


class Web:
    """Login key, session cookie and brute-force lock-out for the panel."""

    def __init__(self, cfg, agent):
        self.cfg, self.agent = cfg, agent
        self.key = cfg.password or self.load("key.txt", lambda: "-".join(
            "".join(secrets.choice(KEY_ALPHABET) for _ in range(5)) for _ in range(2)))
        self.secret = self.load("secret.txt", lambda: secrets.token_hex(32))
        self.fails, self.icons = {}, {}
        self.lock = threading.Lock()

    def load(self, name, make):
        path = os.path.join(self.cfg.data_dir, name)
        try:
            with open(path, encoding="utf-8") as fh:
                value = fh.read().strip()
            if value:
                return value
        except OSError:
            pass
        value = make()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(value + "\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return value

    def session(self):
        return hmac.new(self.secret.encode("utf-8"), ("session:" + self.key).encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def norm_key(value):
        return re.sub(r"[^A-Z0-9]", "", str(value or "").translate(_FA_DIGITS).upper())

    def key_ok(self, value, ip):
        with self.lock:
            recent = [t for t in self.fails.get(ip, []) if t > now() - 600]
            self.fails[ip] = recent
            if len(recent) >= 8:
                raise UserError("تلاش‌های ناموفق زیاد بود؛ ده دقیقهٔ دیگر دوباره امتحان کن.", 429)
        given = str(value or "")
        if self.cfg.password:
            ok = hmac.compare_digest(given.strip().encode("utf-8"), self.key.encode("utf-8"))
        else:
            ok = hmac.compare_digest(self.norm_key(given).encode("utf-8"), self.norm_key(self.key).encode("utf-8"))
        if not ok:
            with self.lock:
                self.fails.setdefault(ip, []).append(now())
        return ok

    def authed(self, headers):
        if self.cfg.no_auth:
            return True
        want = self.session()
        for part in (headers.get("Cookie") or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == SESSION_COOKIE and hmac.compare_digest(value.strip(), want):
                return True
        return False

    def icon(self, size):
        if size not in self.icons:
            self.icons[size] = make_icon_png(size)
        return self.icons[size]

    def font(self):
        if "font" not in self.icons:
            self.icons["font"] = base64.b64decode(FONT_WOFF2)
        return self.icons["font"]


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != "nt"              # on Windows "reuse" would let two agents share one port
    request_queue_size = 64

    def handle_error(self, request, client_address):
        if not isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, socket.timeout)):
            log("http:", traceback.format_exc())


def make_handler(app, media_only=False):
    cfg, agent, web = app.cfg, app.agent, app.web

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "InstaAgent"
        sys_version = ""
        timeout = 120

        def log_message(self, fmt, *args):
            pass

        def do_GET(self):
            self.dispatch("GET")

        def do_HEAD(self):
            self.dispatch("HEAD")

        def do_POST(self):
            self.dispatch("POST")

        def do_DELETE(self):
            self.dispatch("DELETE")

        # ── plumbing ──
        def dispatch(self, method):
            self.body_read = method != "POST"
            try:
                self.route(method)
            except UserError as e:
                self.send_json(e.status, {"error": e.message, "code": e.code})
            except GraphError as e:
                agent.problem(e, "panel")
                self.send_json(502, {"error": e.fa, "kind": e.kind})
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                self.close_connection = True
            except Exception:
                log("panel:", traceback.format_exc())
                try:
                    self.send_json(500, {"error": "خطای داخلی برنامه؛ جزئیات در ترمینال نوشته شد."})
                except Exception:
                    self.close_connection = True
            if not self.body_read:
                self.close_connection = True           # an unread request body would corrupt the next request

        def send_bytes(self, status, body, ctype, extra=None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            if not cfg.embed_ok:
                self.send_header("X-Frame-Options", "DENY")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def send_json(self, status, obj, extra=None):
            headers = {"Cache-Control": "no-store"}
            headers.update(extra or {})
            self.send_bytes(status, jdump(obj).encode("utf-8"), "application/json; charset=utf-8", headers)

        def send_text(self, status, text):
            self.send_bytes(status, text.encode("utf-8"), "text/plain; charset=utf-8", {"Cache-Control": "no-store"})

        def read_body(self, limit=2 * 1024 * 1024):
            n = int(self.headers.get("Content-Length") or 0)
            if n > limit:
                raise UserError("درخواست بیش از حد بزرگ است.", 413)
            raw = self.rfile.read(n) if n > 0 else b""
            self.body_read = True
            return raw

        def read_json(self):
            raw = self.read_body()
            if not raw:
                return {}
            data = jload(raw.decode("utf-8", "replace"), None)
            if not isinstance(data, dict):
                raise UserError("قالب درخواست نادرست است.")
            return data

        def cookie(self):
            secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
            return "%s=%s; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000%s" % (SESSION_COOKIE, web.session(), secure)

        def host_ok(self):
            if not cfg.loopback:
                return True
            host = (self.headers.get("Host") or "").lower()
            name = host[:host.rfind(":")] if ":" in host and not host.endswith("]") else host
            return name in ("127.0.0.1", "localhost", "[::1]")

        def send_file(self, path, mime):
            try:
                size = os.path.getsize(path)
            except OSError:
                return self.send_text(404, "not found")
            start, end, status = 0, size - 1, 200
            rng = re.fullmatch(r"bytes=(\d*)-(\d*)", (self.headers.get("Range") or "").strip())
            if rng and (rng.group(1) or rng.group(2)) and size:
                if rng.group(1):
                    start = int(rng.group(1))
                    end = min(int(rng.group(2)), size - 1) if rng.group(2) else size - 1
                else:
                    start = max(0, size - int(rng.group(2)))
                if start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", "bytes */%d" % size)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return None
                status = 206
            length = end - start + 1
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "private, max-age=3600")
            if status == 206:
                self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, size))
            self.end_headers()
            if self.command == "HEAD":
                return None
            with open(path, "rb") as fh:
                fh.seek(start)
                while length > 0:
                    chunk = fh.read(min(65536, length))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    length -= len(chunk)
            return None

        def send_media(self, name):
            m = re.fullmatch(r"([0-9a-f]{24})\.(jpg|mp4|mov)", name)
            f = agent.store.get(m.group(1)) if m else None
            if not f or f["ext"] != m.group(2):
                return self.send_text(404, "not found")
            return self.send_file(agent.store.path(f), f["mime"])

        # ── routes ──
        def route(self, method):
            u = urllib.parse.urlsplit(self.path)
            path, q = urllib.parse.unquote(u.path), dict(urllib.parse.parse_qsl(u.query))
            if path == "/healthz":
                return self.send_text(200, "ok")
            if path.startswith("/m/") and method in ("GET", "HEAD"):
                return self.send_media(path[3:])
            if media_only:
                return self.send_text(404, "not found")
            if not self.host_ok():
                return self.send_text(403, "forbidden host")
            if path.startswith("/_sim/") and agent.sim is not None:
                return self.sim_route(method, path[6:], q)
            if method in ("GET", "HEAD"):
                if path in ("/", "/index.html"):
                    return self.page(q)
                if path == "/manifest.webmanifest":
                    return self.send_bytes(200, jdump(MANIFEST).encode("utf-8"), "application/manifest+json")
                if path == "/icon.svg":
                    return self.send_bytes(200, ICON_SVG.encode("utf-8"), "image/svg+xml", {"Cache-Control": "max-age=86400"})
                if path == "/font/vazirmatn.woff2":
                    return self.send_bytes(200, web.font(), "font/woff2", {"Cache-Control": "max-age=31536000, immutable"})
                m = re.fullmatch(r"/icon-(192|512)\.png", path)
                if m:
                    return self.send_bytes(200, web.icon(int(m.group(1))), "image/png", {"Cache-Control": "max-age=86400"})
            if path.startswith("/api/"):
                return self.api(method, path[5:].strip("/"), q)
            return self.send_text(404, "not found")

        def page(self, q):
            if "k" in q:                               # the link printed in the terminal: log in, then drop the key from the address
                try:
                    ok = web.key_ok(q.get("k"), self.client_address[0])
                except UserError:
                    ok = False
                self.send_response(303)
                self.send_header("Location", "/")
                if ok:
                    self.send_header("Set-Cookie", self.cookie())
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            nonce = secrets.token_urlsafe(16)
            html = UI_HTML.replace("__NONCE__", nonce).replace("__VERSION__", VERSION)
            csp = ("default-src 'self'; script-src 'nonce-%s'; style-src 'nonce-%s'; img-src 'self' https: data: blob:; "
                   "media-src 'self' https: blob:; connect-src 'self'; base-uri 'none'; form-action 'self'; object-src 'none'"
                   % (nonce, nonce)) + ("" if cfg.embed_ok else "; frame-ancestors 'none'")
            return self.send_bytes(200, html.encode("utf-8"), "text/html; charset=utf-8",
                                   {"Content-Security-Policy": csp, "Cache-Control": "no-store"})

        def sim_route(self, method, rest, q):
            sim = agent.sim
            if rest.startswith(("img/", "pub/")):
                found = sim.asset(rest)
                if not found:
                    return self.send_text(404, "not found")
                return self.send_bytes(200, found[1], found[0], {"Cache-Control": "max-age=3600",
                                                               "Content-Security-Policy": "default-src 'none'"})
            raw = self.read_body(8 * 1024 * 1024) if method == "POST" else b""
            if rest.startswith("ai/"):
                status, ctype, blob, extra = sim.ai(method, rest[3:], q, raw, self.headers)
                return self.send_bytes(status, blob, ctype, dict(extra, **{"Cache-Control": "no-store"}))
            ctype = self.headers.get("Content-Type") or ""
            if rest.startswith("tg/") and ctype.startswith("multipart/form-data"):
                got = {"method": rest.rsplit("/", 1)[-1]}
                for part in raw.split(b"--" + ctype.split("boundary=", 1)[-1].encode("ascii")):
                    head, sep, data = part.partition(b"\r\n\r\n")
                    name = re.search(br'name="([^"]*)"', head)
                    if not sep or not name:
                        continue
                    data = data[:-2] if data.endswith(b"\r\n") else data
                    fname = re.search(br'filename="([^"]*)"', head)
                    if fname:
                        got.update(field=name.group(1).decode(), filename=fname.group(1).decode(), size=len(data), head=data[:16])
                    else:
                        got[name.group(1).decode()] = data.decode("utf-8", "replace")
                sim.telegram_files.append(got)
                return self.send_json(200, {"ok": True})
            form = dict(urllib.parse.parse_qsl(raw.decode("utf-8", "replace"))) if raw else {}
            if rest.startswith("tg/"):
                sim.telegram.append(form)
                return self.send_json(200, {"ok": True})
            host, _, tail = rest.partition("/")
            if host not in ("ig", "fb"):
                return self.send_text(404, "not found")
            params, body = dict(q), None
            if "json" in (self.headers.get("Content-Type") or ""):
                body = jload(raw.decode("utf-8", "replace"), {})
            else:
                params.update(form)
            auth = self.headers.get("Authorization") or ""
            status, obj = sim.handle(method, host, tail, params, body, auth[7:] if auth.startswith("Bearer ") else "")
            if obj is None:
                return self.send_bytes(status, b"<html><body>Bad Gateway</body></html>", "text/html")
            return self.send_json(status, obj)

        def api(self, method, path, q):
            if method not in ("GET", "HEAD"):
                if self.headers.get("X-IA") != "1":    # a plain form or a foreign page cannot add this header
                    raise UserError("درخواست نامعتبر است.", 403)
                origin = self.headers.get("Origin")
                if origin and not cfg.demo:
                    host = urllib.parse.urlsplit(origin).netloc
                    if host not in (self.headers.get("Host"), self.headers.get("X-Forwarded-Host")):
                        raise UserError("درخواست از مبدأ ناشناس رد شد.", 403)
            if path == "upload" and method == "POST":
                if not web.authed(self.headers):
                    raise UserError("ابتدا با کد ورود وارد شو.", 401, "auth")
                return self.send_json(200, self.upload(q))
            body = self.read_json() if method == "POST" else {}
            if path == "login" and method == "POST":
                if web.key_ok(body.get("key"), self.client_address[0]):
                    return self.send_json(200, {"ok": True}, {"Set-Cookie": self.cookie()})
                raise UserError("کد ورود درست نیست.", 401)
            if not web.authed(self.headers):
                raise UserError("ابتدا با کد ورود وارد شو.", 401, "auth")
            if path == "logout" and method == "POST":
                return self.send_json(200, {"ok": True}, {"Set-Cookie": SESSION_COOKIE + "=; Path=/; Max-Age=0"})
            m = re.fullmatch(r"file/([0-9a-f]{24})", path)
            if m and method in ("GET", "HEAD"):
                f = agent.store.get(m.group(1))
                if not f:
                    return self.send_text(404, "not found")
                return self.send_file(agent.store.path(f), f["mime"])
            out = api_call(app, method, path, q, body)
            return self.send_json(200, out)

        def upload(self, q):
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0:
                raise UserError("فایلی نرسید.")
            if n > VIDEO_MAX:
                raise UserError("فایل خیلی بزرگ است (حداکثر ۳۰۰ مگابایت).", 413)
            tmp = os.path.join(agent.store.dir, "up-%s.part" % secrets.token_hex(8))
            left = n
            with open(tmp, "wb") as fh:
                while left > 0:
                    chunk = self.rfile.read(min(left, 65536))
                    if not chunk:
                        break
                    fh.write(chunk)
                    left -= len(chunk)
            if left:
                os.remove(tmp)
                raise UserError("بارگذاری ناقص ماند؛ دوباره تلاش کن.")
            self.body_read = True
            return agent.store.view(agent.store.add(tmp, q.get("name") or ""))

    return Handler


def api_call(app, method, path, q, body):
    """All JSON routes of the panel. Returns a JSON-able object or raises UserError / GraphError."""
    agent = app.agent
    ig, pub, inbox, dm = agent.ig, agent.publisher, agent.inbox, agent.direct
    G, P, D = method in ("GET", "HEAD"), method == "POST", method == "DELETE"

    def online():
        if not ig.connected:
            raise UserError("اول پیج را وصل کن.", 409)

    if path == "status" and G:
        return agent.status()
    if path == "connect" and P:
        agent.connect(body.get("token"))
        return agent.status()
    if path == "disconnect" and P:
        agent.disconnect()
        return agent.status()
    if path == "token/refresh" and P:
        online()
        ig.refresh_token()
        ig.save_acct(token_next=now() + 7 * 86400)
        return {"ok": True, "token_expires": ig.acct.get("token_expires")}
    if path == "settings":
        if P:
            agent.settings.patch(body)
            agent.wake.set()
        return agent.settings.public()
    if path == "telegram/test" and P:
        if not agent.telegram("✅ ایجنت اینستاگرام به تلگرام وصل است."):
            raise UserError("اول توکن ربات و شناسهٔ چت را ذخیره کن.")
        return {"ok": True}
    if path == "log" and G:
        rows = agent.db.q("SELECT id, ts, level, kind, text, seen FROM log ORDER BY id DESC LIMIT ?", (clamp(q.get("limit") or 60, 1, 200),))
        return {"items": rows}
    if path == "log/seen" and P:
        agent.db.x("UPDATE log SET seen=1 WHERE seen=0")
        return {"ok": True}

    # posts
    if path == "posts":
        if P:
            return pub.save(body)
        return {"items": pub.list(q.get("group") or "all")}
    m = re.fullmatch(r"posts/(\d+)(?:/(publish|cancel|duplicate|done|telegram))?", path)
    if m:
        pid, action = int(m.group(1)), m.group(2)
        if action and P:
            return getattr(pub, {"publish": "publish_now", "cancel": "cancel", "duplicate": "duplicate", "done": "done_by_hand",
                                 "telegram": "to_telegram"}[action])(pid)
        if not action and G:
            return pub.get(pid)
        if not action and P:
            return pub.save(body, pid)
        if not action and D:
            pub.delete(pid)
            return {"ok": True}
    if path == "slots" and G:
        return {"items": pub.slots(), "best_hours": agent.analytics.best_hours()}

    # the page itself
    if path == "media" and G:
        online()
        return {"items": agent.media_list(refresh=q.get("refresh") == "1" or now() - agent.media_at > 60)}
    m = re.fullmatch(r"media/(\d+)", path)
    if m and G:
        online()
        return agent.analytics.media_detail(m.group(1))

    # comments
    if path == "comments" and G:
        return {"items": inbox.threads(q.get("filter") or "open", q.get("media")), "open": inbox.open_count()}
    if path == "comments/sync" and P:
        online()
        inbox.sync()
        return {"ok": True, "open": inbox.open_count()}
    if path == "comments/dismiss_all" and P:
        inbox.dismiss_all()
        return {"ok": True}
    m = re.fullmatch(r"comments/([\w.\-]+)/(reply|private|hide|unhide|delete|dismiss|suggest)", path)
    if m and P:
        cid, action = m.group(1), m.group(2)
        if action == "suggest":
            return inbox.suggest(cid)
        if action == "dismiss":
            inbox.dismiss(cid)
            return {"ok": True}
        online()
        thread_id = inbox.row(cid)["parent_id"] or cid
        if action == "reply":
            inbox.reply(cid, body.get("text"))
        elif action == "private":
            inbox.private(cid, body.get("text"))
        elif action == "delete":
            inbox.delete(cid)
        else:
            inbox.hide(cid, action == "hide")
        return {"ok": True, "thread": inbox.thread(thread_id)}

    # direct messages
    if path == "dm" and G:
        return {"items": dm.list(), "open": dm.open_count(), "blocked": agent.db.get("dm.blocked") or ""}
    if path == "dm/sync" and P:
        online()
        agent.sync_dms()
        return {"ok": True, "open": dm.open_count()}
    m = re.fullmatch(r"dm/([^/]+)(?:/(send|dismiss|suggest))?", path)
    if m:
        cid, action = m.group(1), m.group(2)
        if not action and G:
            return dm.get(cid)
        if action == "send" and P:
            online()
            dm.send(cid, body.get("text"))
            return dm.get(cid)
        if action == "dismiss" and P:
            dm.dismiss(cid)
            return {"ok": True}
        if action == "suggest" and P:
            return dm.suggest(cid)

    # rules
    if path == "rules":
        if P:
            return agent.rules.save(body)
        return {"items": agent.rules.list()}
    if path == "rules/test" and P:
        rule = agent.rules.match(body.get("scope") or "comment", body.get("text") or "")
        return {"rule": rule, "spam": looks_spam(body.get("text") or "")}
    m = re.fullmatch(r"rules/(\d+)", path)
    if m and P:
        return agent.rules.save(body, int(m.group(1)))
    if m and D:
        agent.rules.delete(int(m.group(1)))
        return {"ok": True}

    # numbers
    if path == "insights" and G:
        online()
        return agent.analytics.overview(q.get("days") or 7, q.get("refresh") == "1")
    if path == "insights/audience" and G:
        online()
        return agent.analytics.audience()

    # assistant
    if path == "ai/captions" and P:
        return agent.ai.captions(body.get("topic"), body.get("kind") or "image")
    if path == "ai/hashtags" and P:
        return agent.ai.hashtags(body.get("topic"))
    if path == "ai/ideas" and P:
        return agent.ai.ideas(clamp(body.get("count") or 6, 1, 10))
    if path == "ai/plan" and P:
        ideas = agent.ai.ideas(clamp(body.get("count") or 5, 1, 10))
        made = []
        for idea in ideas["items"]:
            caption = limit_tags("%s\n\n%s" % (idea, " ".join(agent.ai.offline_hashtags(idea)[:GOOD_HASHTAGS])))
            made.append(pub.save({"kind": "image", "caption": caption, "media": [], "action": "draft"}))
        return {"items": made, "source": ideas["source"]}
    if path == "chat" and P:
        return agent.ai.chat(body.get("messages"), agent.facts())

    # studio
    if path == "studio" and G:
        return agent.studio.state()
    if path == "studio/make" and P:
        return agent.studio.make(body)
    if path == "studio/picture" and P:
        return agent.studio.redo(body)
    m = re.fullmatch(r"studio/job/([0-9a-f]{16})(/cancel)?", path)
    if m and m.group(2) and P:
        return agent.studio.cancel(m.group(1))
    if m and not m.group(2) and G:
        return agent.studio.job(m.group(1))
    raise UserError("چنین نشانی‌ای در برنامه نیست.", 404)


# ───────────────────────────── application ─────────────────────────────

class App:
    def __init__(self, argv=None, env=None):
        self.cfg = Config(argv, env)
        self.agent = Agent(self.cfg)
        self.web = Web(self.cfg, self.agent)
        self.httpd = self.media_httpd = self.lock_fh = None
        self.port = self.media_port = 0

    def acquire_lock(self):
        """Two agents on one data folder would publish everything twice, so only one may run."""
        fh = open(os.path.join(self.cfg.data_dir, "agent.lock"), "a")
        try:
            try:
                import fcntl
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except ImportError:                        # Windows
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except ImportError:
            pass
        except OSError:
            fh.close()
            raise UserError("ایجنت همین حالا روی این دستگاه در حال اجراست (شاید در یک پنجرهٔ دیگر). اول آن را ببند.")
        self.lock_fh = fh

    def start(self):
        cfg = self.cfg
        self.acquire_lock()
        try:
            self.httpd = Server((cfg.host, cfg.port), make_handler(self))
        except OSError as e:
            raise UserError("پورت %d آزاد نیست (%s). با --port یک پورت دیگر بده." % (cfg.port, e))
        self.port = self.httpd.server_address[1]
        for candidate in ([self.port + 1, self.port + 2, 0] if cfg.port else [0]):
            try:
                self.media_httpd = Server(("127.0.0.1", candidate), make_handler(self, media_only=True))
                break
            except OSError:
                continue
        self.media_port = self.agent.store.media_port = self.media_httpd.server_address[1]
        if cfg.sim:
            self.agent.sim = Sim()
            base = "http://127.0.0.1:%d/_sim" % self.port
            cfg.ig_graph, cfg.fb_graph, cfg.telegram_api = base + "/ig", base + "/fb", base + "/tg"
            cfg.image_api, cfg.gen_api, cfg.horde_api = base + "/ai/pimg", base + "/ai/pgen", base + "/ai/horde"
        for srv in (self.httpd, self.media_httpd):     # the servers answer first: the simulator is reached over HTTP
            threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True).start()
        if cfg.demo:
            self.demo_setup()
        elif cfg.env_token and not self.agent.ig.connected:
            try:
                self.agent.connect(cfg.env_token)
            except (UserError, GraphError) as e:
                log("IG_ACCESS_TOKEN:", e.fa if isinstance(e, GraphError) else e.message)
        if not cfg.no_loop:
            self.agent.start()

    def demo_setup(self):
        """Demo data lives in memory, so every demo start begins with a freshly connected fake page."""
        agent = self.agent
        agent.wipe_page()
        agent.connect(SIM_TOKEN)
        agent.ai.FREE_URL = "http://127.0.0.1:%d/_sim/ai/ptxt/openai" % self.port
        agent.sim.ai_text, agent.sim.ai_delay = agent.sim.demo_plan, 0.8
        agent.sim.free_gap.update(image=self.cfg.free_gap - 1, text=self.cfg.free_gap - 1)
        if not agent.db.get("demo.ready"):
            agent.settings.patch({"auto": {"comment_reply": True, "spam_hide": True, "dm_reply": True},
                                  "brand": {"about": "کافهٔ کوچک محلی با قهوهٔ تازه و کیک خانگی"}})
            agent.db.set("demo.ready", 1)
        else:                                          # only what arrives from now on is handled automatically
            s = agent.settings.all()
            agent.settings.patch({"autopilot": False})
            agent.settings.patch({"autopilot": s["autopilot"]})

    def stop(self):
        self.agent.stop()
        for srv in (self.httpd, self.media_httpd):
            if srv is not None:
                srv.shutdown()
                srv.server_close()
        self.agent.db.close()
        if self.lock_fh is not None:
            self.lock_fh.close()
            self.lock_fh = None


def open_browser(url):
    try:
        exe = shutil.which("termux-open-url")
        if exe:
            subprocess.Popen([exe, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif "com.termux" not in os.environ.get("PREFIX", ""):
            webbrowser.open(url)
    except Exception:
        pass


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):            # a terminal that cannot show Persian must not stop the agent
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    try:
        app = App(argv)
        if app.cfg.show_key:
            print(app.web.key)
            return 0
        app.start()
    except UserError as e:
        sys.stderr.write("✗ %s\n" % e.message)
        return 2
    cfg = app.cfg
    url = "http://%s:%d/" % ("127.0.0.1" if cfg.host in ("0.0.0.0", "") else cfg.host, app.port)
    link = url if cfg.no_auth else url + "?k=" + app.web.key
    line = "=" * 58
    print("\n".join(["", line, "  Insta Agent %s%s" % (VERSION, "   [DEMO - fake page]" if cfg.demo else ""),
                     "  Panel : " + link, "  Key   : " + ("(not needed)" if cfg.no_auth else app.web.key),
                     "  Data  : " + cfg.data_dir, "  Stop  : Ctrl+C", line,
                     "  پنل را در مرورگر گوشی باز کن. تا وقتی این پنجره باز است ایجنت کار می‌کند.",
                     "  در ترموکس برای بیدار ماندن گوشی:  termux-wake-lock", ""]))
    sys.stdout.flush()
    if not cfg.no_browser:
        open_browser(link)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda *_: stop.set())
        except (ValueError, OSError):
            pass
    try:
        while not stop.wait(1):
            pass
    except KeyboardInterrupt:
        pass
    print("\nدر حال بستن ایجنت…")
    app.stop()
    return 0


# ───────────────────────────── web panel (the page itself) ─────────────────────────────
# One self-contained Persian, right-to-left, phone-first page. No outside files or scripts; its font is embedded below.

UI_HTML = r'''<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0b0f1a">
<title>ایجنت اینستاگرام</title>
<link rel="manifest" href="/manifest.webmanifest">
<link rel="icon" href="/icon.svg">
<link rel="apple-touch-icon" href="/icon-192.png">
<style nonce="__NONCE__">
@font-face{font-family:Vazirmatn;src:url(/font/vazirmatn.woff2) format("woff2");font-weight:100 900;font-display:swap}
:root{--bg:#f3f5fa;--card:#fff;--ink:#111827;--mut:#6b7280;--line:#e2e6ee;--soft:#eef1f6;--pri:#ec4899;--ok:#10b981;--warn:#d97706;--bad:#ef4444;--info:#3b82f6;--grad:linear-gradient(135deg,#f59e0b,#ec4899 55%,#8b5cf6)}
@media (prefers-color-scheme:dark){:root{--bg:#0b0f1a;--card:#141a29;--ink:#f1f5f9;--mut:#94a3b8;--line:#263044;--soft:#1b2335}}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.75 Vazirmatn,Vazir,IRANSans,Tahoma,system-ui,sans-serif}
body{padding-bottom:calc(78px + env(safe-area-inset-bottom))}
body.hasfab{padding-bottom:calc(152px + env(safe-area-inset-bottom))}
button,input,textarea,select{font:inherit;color:inherit}
button{cursor:pointer;border:0;background:none;padding:0}
a{color:var(--info)}
p{margin:0}
.ic{width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;flex:none;vertical-align:middle}
.hide{display:none!important}
.ltr{direction:ltr;unicode-bidi:isolate}
input.ltr,textarea.ltr{text-align:left}
.muted{color:var(--mut)}.sm{font-size:.86rem}.center{text-align:center}
.row{display:flex;align-items:center;gap:10px}.grow{flex:1;min-width:0}.wrap{flex-wrap:wrap}.fix{flex:none;width:128px}
.when .in{padding-inline:8px;font-size:.92rem}
.col{display:flex;flex-direction:column;gap:10px}
.up{color:var(--ok)}.down{color:var(--bad)}.amber{color:var(--warn)}
#top{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 14px;display:flex;align-items:center;gap:10px}
#top>img{width:36px;height:36px;border-radius:11px}
#top h1{margin:0;font-size:1.05rem;line-height:1.3;direction:ltr;text-align:right}
#top .sub{font-size:.8rem;color:var(--mut);display:flex;align-items:center;gap:6px}
.dot{width:9px;height:9px;border-radius:50%;background:var(--ok);display:inline-block;flex:none}
.dot.off{background:var(--mut)}.dot.bad{background:var(--bad)}.dot.warn{background:var(--warn)}
main{padding:14px;max-width:640px;margin:0 auto;display:flex;flex-direction:column;gap:12px}
#nav{position:fixed;bottom:0;left:0;right:0;z-index:6;background:var(--card);border-top:1px solid var(--line);display:flex;padding:6px 4px calc(6px + env(safe-area-inset-bottom))}
#nav button{flex:1;display:flex;flex-direction:column;align-items:center;gap:1px;font-size:.74rem;color:var(--mut);padding:4px 0;position:relative}
#nav button.on{color:var(--pri)}
.badge{background:var(--pri);color:#fff;border-radius:99px;font-size:.7rem;min-width:19px;height:19px;padding:0 5px;display:inline-flex;align-items:center;justify-content:center;line-height:1;font-weight:700}
#nav .badge,.iconbtn .badge{position:absolute;top:-2px;inset-inline-start:calc(50% + 2px)}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:14px}
button.card,.tap{width:100%;text-align:start}
.card.ok{border-color:var(--ok)}.card.bad{border-color:var(--bad)}.card.off{opacity:.6}
h2{font-size:1.05rem;margin:0}
h3{font-size:.9rem;margin:6px 4px -4px;color:var(--mut)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:9px 16px;border-radius:14px;background:var(--soft);border:1px solid var(--line);font-weight:600;min-height:44px;text-decoration:none;color:var(--ink)}
.btn.pri{background:var(--grad);color:#fff;border:0}
.btn.danger{color:var(--bad)}
.btn.sm{padding:5px 12px;min-height:36px;font-size:.88rem}
.btn.block{width:100%}
button:disabled{opacity:.5}
.iconbtn{width:40px;height:40px;border-radius:12px;display:inline-flex;align-items:center;justify-content:center;position:relative;flex:none}
.in{width:100%;min-width:0;padding:9px 12px;border-radius:12px;border:1px solid var(--line);background:var(--soft);outline:0;min-height:44px}
.in:focus{border-color:var(--pri)}
textarea.in{resize:vertical;display:block}
label.f{font-size:.85rem;color:var(--mut);display:block;margin:6px 2px -4px}
.pill{display:inline-flex;align-items:center;gap:5px;border:1px solid var(--line);border-radius:99px;padding:1px 10px;font-size:.8rem;color:var(--mut);white-space:nowrap}
.pill .ic{width:14px;height:14px}
.pill.ok{color:var(--ok);border-color:var(--ok)}.pill.warn{color:var(--warn);border-color:var(--warn)}.pill.bad{color:var(--bad);border-color:var(--bad)}.pill.info{color:var(--info);border-color:var(--info)}.pill.pri{background:var(--pri);color:#fff;border-color:var(--pri)}
.seg{display:flex;background:var(--soft);border:1px solid var(--line);border-radius:14px;padding:4px;gap:4px}
.seg button{flex:1;padding:7px 4px;border-radius:10px;font-weight:600;font-size:.92rem;white-space:nowrap;color:var(--mut);display:flex;gap:6px;align-items:center;justify-content:center}
.seg button.on{background:var(--card);color:var(--ink);box-shadow:0 1px 3px rgba(0,0,0,.18)}
.chips{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.chip{border:1px solid var(--line);border-radius:99px;padding:5px 12px;font-size:.86rem;background:var(--card)}
.chip.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.sw{width:52px;height:30px;border-radius:99px;background:var(--line);position:relative;flex:none;transition:background .15s}
.sw::after{content:"";position:absolute;top:3px;inset-inline-start:3px;width:24px;height:24px;border-radius:50%;background:#fff;transition:transform .15s;box-shadow:0 1px 3px rgba(0,0,0,.3)}
.sw.on{background:var(--ok)}.sw.on::after{transform:translateX(-22px)}
.line{padding:8px 0;border-bottom:1px solid var(--line)}.line:last-child{border-bottom:0;padding-bottom:0}
.avatar{width:54px;height:54px;border-radius:50%;object-fit:cover;background:var(--grad);flex:none;display:inline-flex;align-items:center;justify-content:center;color:#fff;font-weight:700}
.avatar.s{width:42px;height:42px}
.stats{display:grid;grid-template-columns:repeat(3,1fr);text-align:center;margin-top:12px}
.stats b{display:block;font-size:1.15rem}.stats span{font-size:.8rem;color:var(--mut)}
.thumb{width:58px;height:58px;border-radius:12px;background:var(--soft);flex:none;display:flex;align-items:center;justify-content:center;color:var(--mut);overflow:hidden}
.thumb.s{width:42px;height:42px;border-radius:10px}
.thumb img,.thumb video,.mitem img,.mitem video{width:100%;height:100%;object-fit:cover;display:block}
.clamp{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere}
.pre{white-space:pre-wrap;overflow-wrap:anywhere}
.empty{text-align:center;color:var(--mut);padding:30px 10px;display:flex;flex-direction:column;align-items:center;gap:10px}
.empty>.ic{width:40px;height:40px;opacity:.6}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:4px}
.tile{aspect-ratio:1;border-radius:10px;overflow:hidden;position:relative;background:var(--soft);display:block}
.tile img{width:100%;height:100%;object-fit:cover;display:block}
.tile .meta{position:absolute;inset:auto 0 0 0;padding:16px 6px 3px;background:linear-gradient(transparent,rgba(0,0,0,.7));color:#fff;font-size:.74rem;display:flex;gap:6px;justify-content:center;align-items:center}
.tile .meta .ic{width:13px;height:13px}
.tile .kind{position:absolute;top:6px;inset-inline-start:6px;color:#fff;filter:drop-shadow(0 1px 2px rgba(0,0,0,.6))}
.kpis{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:10px 12px}
.kpi b{font-size:1.2rem}
.chat{display:flex;flex-direction:column;gap:6px}
.bubble{max-width:86%;padding:7px 12px;border-radius:16px;background:var(--soft);align-self:flex-start;white-space:pre-wrap;overflow-wrap:anywhere}
.bubble.me{align-self:flex-end;background:var(--pri);color:#fff}
.bubble small{display:block;opacity:.75;font-size:.72rem;direction:rtl}
.bubble span[dir]{display:block;text-align:start}
.sheet{position:fixed;inset:0;z-index:20;background:rgba(0,0,0,.5);display:flex;align-items:flex-end;justify-content:center}
.panel{background:var(--bg);width:100%;max-width:640px;max-height:92vh;max-height:92dvh;border-radius:22px 22px 0 0;display:flex;flex-direction:column}
.panel .head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 16px;border-bottom:1px solid var(--line)}
.panel .body{padding:14px;overflow:auto;display:flex;flex-direction:column;gap:12px;flex:1}
.panel .body>*{flex:none}
.panel .foot{padding:10px 14px calc(10px + env(safe-area-inset-bottom));border-top:1px solid var(--line);display:flex;gap:8px;align-items:center}
.panel .foot .btn{flex:1;padding-inline:8px;font-size:.92rem}
#toasts{position:fixed;top:12px;left:0;right:0;z-index:40;display:flex;flex-direction:column;align-items:center;gap:8px;pointer-events:none}
.toast{background:var(--card);border:1px solid var(--ok);border-radius:14px;padding:8px 14px;box-shadow:0 6px 20px rgba(0,0,0,.25);max-width:90%;pointer-events:auto}
.toast.bad{border-color:var(--bad)}
#fab{position:fixed;bottom:calc(88px + env(safe-area-inset-bottom));inset-inline-end:16px;z-index:7;width:54px;height:54px;border-radius:18px;background:var(--grad);color:#fff;display:flex;align-items:center;justify-content:center;box-shadow:0 8px 22px rgba(236,72,153,.4)}
.kinds{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.kinds button{border:1px solid var(--line);background:var(--card);border-radius:14px;padding:9px 4px;display:flex;flex-direction:column;align-items:center;gap:2px;font-size:.85rem;color:var(--mut)}
.kinds button.on{border-color:var(--pri);color:var(--ink);box-shadow:inset 0 0 0 1px var(--pri)}
.strip{display:flex;gap:8px;overflow-x:auto;padding-bottom:4px}
.mitem{width:92px;height:116px;border-radius:12px;overflow:hidden;position:relative;flex:none;background:var(--soft);display:flex;align-items:center;justify-content:center;color:var(--mut);font-size:.78rem;text-align:center}
.mitem .fit{width:100%;height:100%;display:flex;align-items:center;justify-content:center}
.mitem .rm{position:absolute;top:4px;inset-inline-end:4px;width:26px;height:26px;border-radius:50%;background:rgba(0,0,0,.6);color:#fff;display:flex;align-items:center;justify-content:center}
.mitem .rm .ic{width:14px;height:14px}
.mitem .tag{position:absolute;bottom:4px;inset-inline-start:4px;background:rgba(0,0,0,.6);color:#fff;border-radius:6px;padding:0 6px;font-size:.7rem}
.mitem.add{border:2px dashed var(--line);flex-direction:column;gap:4px;background:none}
.big{width:100%;border-radius:16px;max-height:46vh;object-fit:cover;display:block;background:var(--soft)}
.hero{text-align:center;padding:14px 6px;display:flex;flex-direction:column;align-items:center;gap:6px}
.hero img{width:72px;height:72px;border-radius:20px}
ol.steps{padding-inline-start:22px;margin:0;display:flex;flex-direction:column;gap:8px}
code{background:var(--soft);border:1px solid var(--line);border-radius:6px;padding:0 6px;direction:ltr;unicode-bidi:isolate;font-size:.86em;display:inline-block}
details.box{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:12px 14px}
details.box summary{font-weight:700;cursor:pointer;list-style:none;display:flex;gap:8px;align-items:center}
details.box summary::-webkit-details-marker{display:none}
details.box[open] summary{margin-bottom:10px}
details.box>.col{gap:8px}
.logline{display:flex;gap:10px;align-items:flex-start;padding:8px 0;border-bottom:1px solid var(--line)}
.logline:last-child{border-bottom:0}
.logline .dot{margin-top:10px}
.bar{height:8px;border-radius:99px;background:var(--soft);overflow:hidden}
.bar i{display:block;height:100%;background:var(--grad);border-radius:99px}
.stage{width:100%;height:auto;border-radius:16px;display:block;background:var(--soft)}
.stage.tall{width:auto;max-width:100%;max-height:56vh;margin:0 auto}
.spin{width:30px;height:30px;border:3px solid var(--line);border-top-color:var(--pri);border-radius:50%;display:inline-block;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.empty .bar{width:100%}
.spark{width:100%;height:70px;direction:ltr}
.spark polyline{fill:none;stroke:var(--pri);stroke-width:2.5;stroke-linejoin:round;stroke-linecap:round}
</style>
</head>
<body>
<header id="top" class="hide"></header>
<main id="view"><div class="empty">در حال اتصال به ایجنت…</div></main>
<nav id="nav" class="hide"></nav>
<button id="fab" class="hide" aria-label="پست جدید"></button>
<div id="sheets"></div>
<div id="toasts"></div>
<script nonce="__NONCE__">
'use strict';
const D = document, $ = (s, r) => (r || D).querySelector(s);
const S = {st: null, authed: true, tab: 'home', sub: {content: 'queue', inbox: 'comments'}, filter: 'open', days: 7, seq: 0, refresh: false, typed: {}};
const VIEWS = {};
const ICONS = {
  home: 'M3 10l9-7 9 7v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z M9 22V12h6v10', grid: 'M3 3h7v7H3z M14 3h7v7h-7z M14 14h7v7h-7z M3 14h7v7H3z',
  chat: 'M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z',
  bars: 'M18 20V10 M12 20V4 M6 20v-6', bot: 'M12 8V4 M5 8h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z M9 13v2 M15 13v2',
  plus: 'M12 5v14 M5 12h14', x: 'M18 6L6 18 M6 6l12 12', send: 'M22 2L11 13 M22 2l-7 20-4-9-9-4 20-7z',
  bell: 'M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9 M13.73 21a2 2 0 0 1-3.46 0', clock: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z M12 6v6l4 2',
  check: 'M20 6L9 17l-5-5', image: 'M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z M8.5 10a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z M21 15l-5-5L5 21',
  layers: 'M12 2L2 7l10 5 10-5-10-5z M2 17l10 5 10-5 M2 12l10 5 10-5', film: 'M4 2h16a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2z M7 2v20 M17 2v20 M2 12h20 M2 7h5 M2 17h5 M17 17h5 M17 7h5',
  story: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z M12 8v8 M8 12h8', refresh: 'M23 4v6h-6 M1 20v-6h6 M3.51 9a9 9 0 0 1 14.85-3.36L23 10 M1 14l4.64 4.36A9 9 0 0 0 20.49 15',
  more: 'M12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z M19 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z M5 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2z',
  trash: 'M3 6h18 M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6 M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2',
  eyeoff: 'M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94 M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19 M1 1l22 22',
  eye: 'M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z', edit: 'M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z',
  zap: 'M13 2L3 14h9l-1 8 10-12h-9l1-8z', settings: 'M4 21v-7 M4 10V3 M12 21v-9 M12 8V3 M20 21v-5 M20 12V3 M1 14h6 M9 8h6 M17 16h6',
  heart: 'M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z',
  chev: 'M15 18l-6-6 6-6', upload: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4 M17 8l-5-5-5 5 M12 3v12',
  lock: 'M5 11h14a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2z M7 11V7a5 5 0 0 1 10 0v4',
  hash: 'M4 9h16 M4 15h16 M10 3L8 21 M16 3l-2 18', external: 'M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6 M15 3h6v6 M10 14L21 3',
  alert: 'M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z M12 9v4 M12 17h.01',
  spark: 'M12 3l1.8 5.6L19.5 10l-5.7 1.6L12 17l-1.8-5.4L4.5 10l5.7-1.4z M19 16v4 M17 18h4', link: 'M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71 M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71',
  help: 'M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3 M12 17h.01', calendar: 'M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z M16 2v4 M8 2v4 M3 10h18'
};
const KIND = {image: ['پست', 'image'], carousel: ['چندتایی', 'layers'], reel: ['ریل', 'film'], story: ['استوری', 'story']};
const STATUS = {draft: ['پیش‌نویس', ''], scheduled: ['زمان‌بندی‌شده', 'info'], publishing: ['در حال انتشار', 'warn'], published: ['منتشرشده', 'ok'], failed: ['ناموفق', 'bad'], missed: ['جامانده', 'warn'], canceled: ['لغوشده', ''], due: ['وقت انتشار', 'pri']};
/* without a connected page the owner posts by hand: a scheduled post is a reminder, a published one was posted by the owner */
const statusOf = p => (p.status === 'scheduled' && !S.st.connected ? ['یادآوری', 'info'] : p.status === 'published' && p.by_hand ? ['منتشرشده (خودت)', 'ok'] : STATUS[p.status]);
const live = () => S.st.connected || S.st.manual;

/* ───── tiny DOM helpers: every piece of text goes in as a text node, never as HTML ───── */
function svg(tag) { return D.createElementNS('http://www.w3.org/2000/svg', tag); }
function icon(n, cls) {
  const s = svg('svg'), p = svg('path');
  s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('class', 'ic' + (cls ? ' ' + cls : '')); s.setAttribute('aria-hidden', 'true');
  p.setAttribute('d', ICONS[n] || ''); s.appendChild(p);
  return s;
}
function add(el, ...kids) {
  for (const k of kids.flat(9)) { if (k == null || k === false || k === '') continue; el.appendChild(k.nodeType ? k : D.createTextNode(String(k))); }
  return el;
}
function h(tag, a, ...kids) {
  const el = D.createElement(tag);
  for (const k in (a || {})) {
    const v = a[k];
    if (v == null || v === false) continue;
    if (k.slice(0, 2) === 'on') el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className = v;
    else if (k === 'value') el.value = v;
    else if (['checked', 'disabled', 'open', 'muted', 'multiple'].includes(k)) el[k] = !!v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  return add(el, kids);
}
function fill(el, ...kids) { el.textContent = ''; return add(el, ...kids); }
const fa = n => (n == null || n === '' ? '—' : Number(n).toLocaleString('fa-IR'));
const two = n => String(n).padStart(2, '0');
function ago(ts) {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return 'همین حالا';
  if (s < 3600) return fa(Math.floor(s / 60)) + ' دقیقه پیش';
  if (s < 86400) return fa(Math.floor(s / 3600)) + ' ساعت پیش';
  if (s < 86400 * 30) return fa(Math.floor(s / 86400)) + ' روز پیش';
  return new Date(ts * 1000).toLocaleDateString('fa-IR');
}
function day(d) { return d.toLocaleDateString('fa-IR', {weekday: 'long', day: 'numeric', month: 'long'}); }
function when(ts) { const d = new Date(ts * 1000); return day(d) + '، ساعت ' + d.toLocaleTimeString('fa-IR', {hour: '2-digit', minute: '2-digit'}); }
function igts(s) { return Date.parse(String(s || '').replace(/([+-]\d\d)(\d\d)$/, '$1:$2')) / 1000; }

/* ───── talking to the agent ───── */
function Err(message, status, silent) { this.message = message; this.status = status; this.silent = !!silent; }
async function api(method, path, body, raw) {
  const opt = {method, headers: {'X-IA': '1'}, credentials: 'same-origin'};
  if (raw) { opt.body = body; opt.headers['Content-Type'] = 'application/octet-stream'; }
  else if (body !== undefined) { opt.body = JSON.stringify(body); opt.headers['Content-Type'] = 'application/json'; }
  let res;
  try { res = await fetch(path, opt); }
  catch (e) { throw new Err('ارتباط با ایجنت قطع است. برنامه (ترموکس) هنوز باز است؟', 0); }
  let data = {};
  try { data = await res.json(); } catch (e) { /* not JSON */ }
  if (res.status === 401 && data.code === 'auth') { S.authed = false; render(true); throw new Err(data.error, 401, true); }
  if (!res.ok) throw new Err(data.error || ('خطای ' + res.status), res.status);
  return data;
}
const GET = p => api('GET', p), POST = (p, b) => api('POST', p, b || {}), DEL = p => api('DELETE', p);
function toast(msg, kind) {
  const t = h('div', {class: 'toast ' + (kind || ''), role: 'status', onclick: () => t.remove()}, msg);
  $('#toasts').textContent = '';                       /* the newest message is the one that matters */
  $('#toasts').appendChild(t);
  setTimeout(() => t.remove(), kind === 'bad' ? 6500 : 3000);
}
/* run an action from a button: the button is disabled meanwhile and errors become toasts */
async function run(btn, fn) {
  if (btn) btn.disabled = true;
  try { return await fn(); }
  catch (e) { if (!e || !e.silent) toast((e && e.message) || 'خطا', 'bad'); }
  finally { if (btn) btn.disabled = false; }
}
/* The newest answer wins: a slow background poll must not undo what a later request has already shown. */
let stAsked = 0, stShown = 0;
function putStatus(st) { stShown = ++stAsked; S.st = st; }
async function loadStatus() {
  const n = ++stAsked, st = await GET('/api/status');
  if (n < stShown) return false;
  stShown = n; S.st = st;
  return true;
}
async function refresh() { if (await loadStatus() && live()) { paintTop(); paintNav(); } }

/* ───── bottom sheets ───── */
function sheet(title, o) {
  o = o || {};
  const body = h('div', {class: 'body'}), foot = h('div', {class: 'foot hide'}), ttl = h('h2', null, title);
  const s = {body, foot, title: ttl, onclose: o.onclose,
    close() { if (!el.isConnected) return; el.remove(); if (s.onclose) s.onclose(); },
    setFoot(...k) { foot.classList.remove('hide'); fill(foot, ...k); }};
  const el = h('div', {class: 'sheet'}, h('div', {class: 'panel', role: 'dialog', 'aria-modal': 'true'},
    h('div', {class: 'head'}, ttl, h('button', {class: 'iconbtn', 'aria-label': 'بستن', onclick: () => s.close()}, icon('x'))), body, foot));
  el.addEventListener('click', e => { if (e.target === el) s.close(); });
  $('#sheets').appendChild(el);
  return s;
}
function ask(msg, ok, danger) {
  return new Promise(res => {
    const s = sheet('مطمئنی؟', {onclose: () => res(false)});
    add(s.body, h('p', null, msg));
    s.setFoot(h('button', {class: 'btn', onclick: () => s.close()}, 'نه'), h('button', {class: 'btn ' + (danger ? 'danger' : 'pri'), onclick: () => { res(true); s.close(); }}, ok || 'بله'));
  });
}
function field(label, input, hint) { return [h('label', {class: 'f'}, label), input, hint ? h('div', {class: 'muted sm'}, hint) : null]; }
function segment(items, cur, fn) {
  return h('div', {class: 'seg'}, items.map(i => h('button', {class: cur === i[0] ? 'on' : '', 'data-seg': i[0], onclick: () => fn(i[0])}, i[1], i[2] ? h('span', {class: 'badge'}, fa(i[2])) : null)));
}
function empty(ic, text, extra) { return h('div', {class: 'empty'}, icon(ic), h('div', null, text), extra); }
function toggle(on, fn, label) {
  const b = h('button', {class: 'sw' + (on ? ' on' : ''), role: 'switch', 'aria-checked': String(!!on), 'aria-label': label || ''});
  b.addEventListener('click', () => run(b, async () => { const v = !b.classList.contains('on'); await fn(v); b.classList.toggle('on', v); b.setAttribute('aria-checked', String(v)); }));
  return b;
}
function thumb(src, type, cls) {
  const box = h('span', {class: cls || 'thumb'}), ph = () => fill(box, icon(type === 'video' ? 'film' : 'image'));
  if (!src) { ph(); return box; }
  const el = type === 'video' && !/\.(svg|jpe?g|png)$/i.test(src) ? h('video', {src: src + '#t=0.1', muted: true, playsinline: '', preload: 'metadata'}) : h('img', {src, alt: '', loading: 'lazy'});
  el.addEventListener('error', ph);
  return add(box, el);
}
async function saveSettings(patch, msg) { await POST('/api/settings', patch); await refresh(); if (msg !== false) toast(msg || 'ذخیره شد'); }

/* ───── frame: header, tabs, polling ───── */
const TABS = [['home', 'خانه', 'home'], ['content', 'محتوا', 'grid'], ['inbox', 'گفتگوها', 'chat'], ['stats', 'آمار', 'bars'], ['agent', 'ایجنت', 'bot']];
function paintTop() {
  const st = S.st, a = st.account;
  const state = !st.connected ? ['', 'بدون اتصال؛ انتشار با خودت'] : a.invalid ? ['bad', 'اتصال پیج قطع است'] : !st.autopilot ? ['off', 'ایجنت متوقف است'] : st.busy ? ['warn', 'اینستاگرام موقتاً محدود کرده؛ کمی صبر'] : ['', 'ایجنت روشن است'];
  fill($('#top'), h('img', {src: '/icon.svg', alt: ''}),
    h('div', {class: 'grow'}, h('h1', null, st.connected ? '@' + a.username : st.handle ? '@' + st.handle : 'ایجنت پیج'), h('div', {class: 'sub'}, h('i', {class: 'dot ' + state[0]}), (st.demo ? 'حالت نمایشی — ' : '') + state[1])),
    h('button', {class: 'iconbtn', 'aria-label': 'اعلان‌ها', onclick: notesSheet}, icon('bell'), st.counts.unseen ? h('span', {class: 'badge'}, fa(st.counts.unseen)) : null));
}
function paintNav() {
  const c = S.st.counts, n = {inbox: c.open_comments + c.open_dms, content: c.due};
  const tabs = TABS.filter(t => S.st.connected || !['inbox', 'stats'].includes(t[0]));      /* no page: nothing to read from Instagram */
  if (!tabs.some(t => t[0] === S.tab)) S.tab = 'home';
  fill($('#nav'), tabs.map(t => h('button', {class: S.tab === t[0] ? 'on' : '', 'data-tab': t[0], onclick: () => go(t[0])}, icon(t[2]), t[1], n[t[0]] ? h('span', {class: 'badge'}, fa(n[t[0]])) : null)));
  $('#fab').classList.toggle('hide', S.tab !== 'content' || !!S.st.account.invalid);
  document.body.classList.toggle('hasfab', !$('#fab').classList.contains('hide'));
}
function go(tab, sub) { S.tab = tab; if (sub) S.sub[tab] = sub; window.scrollTo(0, 0); render(true); }
async function render(fresh) {
  const view = $('#view'), st = S.st;
  const chrome = on => { $('#top').classList.toggle('hide', !on); $('#nav').classList.toggle('hide', !on); if (!on) { $('#fab').classList.add('hide'); document.body.classList.remove('hasfab'); } };
  S.seq++;
  if (!S.authed) { chrome(false); return fill(view, loginView()); }
  if (!st) { chrome(false); return fill(view, h('div', {class: 'empty'}, 'در حال اتصال به ایجنت…')); }
  if (!live()) { chrome(false); return fill(view, connectView()); }
  chrome(true); paintNav(); paintTop();
  const my = S.seq;
  if (fresh) fill(view, h('div', {class: 'empty'}, 'در حال بارگذاری…'));
  try { const kids = await VIEWS[S.tab](); if (my === S.seq) fill(view, kids); }
  catch (e) { if (my === S.seq && !(e && e.silent)) fill(view, h('div', {class: 'card bad'}, (e && e.message) || 'خطا'), h('button', {class: 'btn', onclick: () => render(true)}, icon('refresh'), 'تلاش دوباره')); }
}
async function poll() {
  if (D.hidden || !S.authed) return;
  const prev = S.st;
  try { if (!await loadStatus()) return; } catch (e) { return; }
  if (!prev || prev.connected !== S.st.connected || prev.manual !== S.st.manual) return render(true);
  if (!live()) return;
  paintTop(); paintNav();
  const sig = s => JSON.stringify([s.counts, s.autopilot, s.auto, s.account.invalid, s.account.followers, s.next_post && s.next_post.id]);
  const typing = /INPUT|TEXTAREA|SELECT/.test((D.activeElement || {}).tagName || '');
  if (sig(prev) !== sig(S.st) && !typing && !$('#sheets').childElementCount) render(false);
}

/* ───── login & connect ───── */
function loginView() {
  const inp = h('input', {class: 'in ltr center', placeholder: 'ABCDE-FGHJK', autocomplete: 'off', autocapitalize: 'characters', spellcheck: 'false', 'aria-label': 'کد ورود'});
  const btn = h('button', {class: 'btn pri block', type: 'submit'}, icon('lock'), 'ورود');
  const submit = e => { e.preventDefault(); run(btn, async () => { await POST('/api/login', {key: inp.value}); $('#toasts').textContent = ''; S.authed = true; await loadStatus(); render(true); }); };
  return [h('div', {class: 'hero'}, h('img', {src: '/icon.svg', alt: ''}), h('h2', null, 'ایجنت اینستاگرام'), h('p', {class: 'muted'}, 'کدی را که هنگام اجرای برنامه در ترمینال نشان داده شد وارد کن.')),
    h('form', {class: 'card col', onsubmit: submit}, h('label', {class: 'f'}, 'کد ورود (Key)'), inp, btn,
      h('p', {class: 'muted sm'}, 'کد را گم کرده‌ای؟ در ترمینال بزن: ', h('code', null, 'python insta_agent.py --show-key')))];
}
function guide() {
  const li = (...k) => h('li', null, k);
  return h('ol', {class: 'steps'},
    li('پیج باید «حرفه‌ای» (Business یا Creator) و عمومی (نه خصوصی) باشد: در اینستاگرام ← تنظیمات ← نوع حساب ← «تغییر به حساب حرفه‌ای» (رایگان است).'),
    li('در سایت ', h('a', {href: 'https://developers.facebook.com/apps/', target: '_blank', rel: 'noopener'}, 'developers.facebook.com'), ' وارد شو و «Create App» را بزن. اگر «Use case» پرسید گزینهٔ اینستاگرام (Manage messaging & content on Instagram) را بردار؛ در فرم قدیمی‌تر: Other ← Business.'),
    li('در برنامه‌ای که ساختی محصول «Instagram» را اضافه کن و به بخش «API setup with Instagram login» برو.'),
    li('در قسمت «Generate access tokens» پیج خودت را اضافه کن، همهٔ دسترسی‌ها را تأیید کن و «Generate token» را بزن.'),
    li('توکن (رشتهٔ بلندی که با IGAA شروع می‌شود) را کپی کن و همین‌جا بچسبان.'));
}
function tokenBox(done) {
  const ta = h('textarea', {class: 'in ltr', rows: 3, placeholder: 'IGAA…', 'aria-label': 'توکن', spellcheck: 'false', autocomplete: 'off'});
  const btn = h('button', {class: 'btn pri block', onclick: () => run(btn, async () => { putStatus(await POST('/api/connect', {token: ta.value})); toast('پیج وصل شد ✓'); done(); })}, icon('link'), 'اتصال به پیج');
  return [field('توکن دسترسی (Access Token)', ta), btn];
}
function connectView() {
  const a = (S.st.account || {}), proxy = h('input', {class: 'in ltr', placeholder: 'http://127.0.0.1:10809', 'aria-label': 'پروکسی'});
  GET('/api/settings').then(s => { proxy.value = s.network.proxy; }).catch(() => {});
  const byHand = h('button', {class: 'btn pri block', 'data-manual': '1', onclick: e => run(e.currentTarget, async () => { await POST('/api/settings', {manual: true}); await loadStatus(); S.tab = 'home'; render(true); })}, icon('spark'), 'بدون اتصال شروع کن');
  return [h('div', {class: 'hero'}, h('img', {src: '/icon.svg', alt: ''}), h('h2', null, 'ایجنت اینستاگرام'),
      h('p', {class: 'muted'}, 'دو راه برای شروع هست؛ بعداً هم می‌توانی عوضش کنی.')),
    h('div', {class: 'card col'}, h('b', null, '۱. بدون اتصال: خودم پست می‌کنم'),
      h('p', {class: 'muted sm'}, 'ایده‌ات را می‌نویسی؛ ایجنت عکس یا ویدیوی کوتاه، کپشن و هشتگ می‌سازد و سر وقت یادآوری می‌کند. انتشار را خودت در اپ اینستاگرام انجام می‌دهی. نه توکن می‌خواهد، نه سایت متا.'), byHand),
    h('div', {class: 'card col'}, h('b', null, '۲. اتصال با توکن متا: انتشار و پاسخ خودکار'),
      h('p', {class: 'muted sm'}, 'ایجنت خودش منتشر می‌کند، کامنت و دایرکت را می‌خواند و آمار می‌دهد. فقط از راه رسمی اینستاگرام (توکن) وصل می‌شود و هیچ‌وقت رمز پیج را نمی‌خواهد. سایت توسعه‌دهندگان متا در بعضی کشورها (از جمله ایران) باز نمی‌شود.'),
      a.last_username ? h('div', {class: 'sm'}, 'آخرین پیج وصل‌شده: ', h('b', {class: 'ltr'}, '@' + a.last_username)) : null,
      tokenBox(() => { S.tab = 'home'; render(true); })),
    h('details', {class: 'box'}, h('summary', null, icon('help'), 'توکن را از کجا بیاورم؟ (حدود ۵ دقیقه، فقط یک بار)'), guide(),
      h('p', {class: 'muted sm'}, 'توکن ۶۰ روز اعتبار دارد و ایجنت خودش تمدیدش می‌کند. توکن فقط روی همین دستگاه نگه داشته می‌شود.')),
    h('details', {class: 'box'}, h('summary', null, icon('settings'), 'اینستاگرام بدون فیلترشکن باز نمی‌شود؟'),
      h('div', {class: 'col'}, h('p', {class: 'muted sm'}, 'نشانی پروکسی HTTP فیلترشکن را بنویس (در v2rayNG معمولاً http://127.0.0.1:10809).'),
        h('div', {class: 'row'}, proxy, h('button', {class: 'btn sm', onclick: e => run(e.currentTarget, async () => { await POST('/api/settings', {network: {proxy: proxy.value}}); toast('ذخیره شد'); })}, 'ذخیره'))))];
}
function tokenSheet() {
  const s = sheet('توکن تازه');
  add(s.body, h('p', {class: 'muted sm'}, 'اگر توکن باطل شده یا می‌خواهی پیج دیگری وصل کنی، توکن تازه را اینجا بچسبان.'), tokenBox(() => { s.close(); render(true); }),
    h('details', {class: 'box'}, h('summary', null, icon('help'), 'راهنمای ساختن توکن'), guide()));
}

/* ───── home ───── */
function stat(n, label) { return h('div', null, h('b', null, fa(n)), h('span', null, label)); }
function navRow(ic, text, fn) { return h('button', {class: 'card row', onclick: fn}, icon(ic), h('b', {class: 'grow'}, text), icon('chev')); }
function logLine(l) {
  return h('div', {class: 'logline'}, h('i', {class: 'dot ' + ({alert: 'bad', warn: 'warn', ok: ''}[l.level] != null ? {alert: 'bad', warn: 'warn', ok: ''}[l.level] : 'off')}),
    h('div', {class: 'grow'}, h('div', {class: 'pre'}, l.text), h('small', {class: 'muted'}, ago(l.ts))));
}
async function homeByHand() {
  const c = S.st.counts, idea = h('textarea', {class: 'in', rows: 2, placeholder: 'مثلاً: تخفیف ۲۰٪ لاتهٔ پاییزی تا آخر هفته', 'aria-label': 'ایده', value: S.typed.idea || ''});
  idea.addEventListener('input', () => { S.typed.idea = idea.value; });
  const make = kind => studio({idea: idea.value, kind}, r => { delete S.typed.idea; composer(null, r); });
  const out = [h('div', {class: 'card col'}, h('h2', null, 'چه چیزی بسازم؟'),
    h('p', {class: 'muted sm'}, 'ایده‌ات را در یک جمله بنویس؛ ایجنت تصویر یا ویدیوی کوتاه، کپشن و هشتگ را آماده می‌کند.'), idea,
    h('div', {class: 'row'}, h('button', {class: 'btn pri grow', 'data-make': 'image', onclick: () => make('image')}, icon('image'), 'عکس بساز'),
      h('button', {class: 'btn pri grow', 'data-make': 'reel', onclick: () => make('reel')}, icon('film'), 'ویدیو بساز')))];
  const [queue, log] = await Promise.all([GET('/api/posts?group=queue'), GET('/api/log?limit=4')]);
  const due = queue.items.filter(p => p.status === 'due'), soon = queue.items.filter(p => p.status === 'scheduled');
  if (due.length) out.push(h('h3', null, 'وقت انتشار این‌ها رسیده'), due.map(postCard));
  if (soon.length) out.push(h('h3', null, 'یادآوری‌های پیش رو'), soon.slice(0, 3).map(postCard));
  out.push(h('div', {class: 'card col'}, h('div', {class: 'chips'}, h('span', {class: 'pill info'}, icon('clock'), fa(c.scheduled) + ' یادآوری'), h('span', {class: 'pill'}, icon('edit'), fa(c.drafts) + ' پیش‌نویس'),
      h('span', {class: 'pill ok'}, icon('check'), fa(c.published_today) + ' انتشار امروز')),
    h('button', {class: 'btn', onclick: () => composer()}, icon('upload'), 'پست با عکس یا ویدیوی خودم')));
  out.push(h('div', {class: 'card col'}, h('b', null, 'پیج وصل نیست'), h('div', {class: 'muted sm'}, 'ایجنت محتوا را آماده و یادآوری می‌کند؛ انتشار، کامنت‌ها و آمار در اپ اینستاگرام با خودت است.'),
    h('button', {class: 'btn sm', onclick: tokenSheet}, icon('link'), 'اتصال با توکن متا')));
  if (log.items.length) out.push(h('h3', null, 'آخرین رویدادها'), h('div', {class: 'card'}, log.items.map(logLine)));
  return out;
}
VIEWS.home = async () => {
  if (!S.st.connected) return homeByHand();
  const st = S.st, a = st.account, c = st.counts, au = st.auto, out = [];
  if (a.invalid) out.push(h('div', {class: 'card bad col'}, h('b', null, 'اتصال پیج قطع شده است'), h('div', {class: 'sm'}, a.invalid), h('button', {class: 'btn pri', onclick: tokenSheet}, 'دادن توکن تازه')));
  out.push(h('div', {class: 'card'}, h('div', {class: 'row'}, a.picture ? h('img', {class: 'avatar', src: a.picture, alt: ''}) : h('span', {class: 'avatar'}),
      h('div', {class: 'grow'}, h('b', null, a.name || a.username), h('div', {class: 'muted sm ltr'}, '@' + a.username)), st.demo ? h('span', {class: 'pill warn'}, 'نمایشی') : null),
    h('div', {class: 'stats'}, stat(a.followers, 'دنبال‌کننده'), stat(a.follows, 'دنبال‌شونده'), stat(a.media_count, 'پست'))));
  out.push(h('div', {class: 'card row' + (st.autopilot ? ' ok' : '')}, h('div', {class: 'grow'}, h('b', null, st.autopilot ? 'ایجنت روشن است' : 'ایجنت متوقف است'),
      h('div', {class: 'muted sm'}, st.autopilot ? 'انتشار زمان‌بندی‌شده و کارهای خودکار فعال‌اند.' : 'تا دوباره روشنش نکنی هیچ کار خودکاری انجام نمی‌شود.')),
    toggle(st.autopilot, async v => { await saveSettings({autopilot: v}, v ? 'ایجنت روشن شد' : 'ایجنت متوقف شد'); render(false); }, 'روشن یا متوقف کردن ایجنت')));
  const todo = [];
  if (c.open_comments) todo.push(navRow('chat', fa(c.open_comments) + ' کامنت منتظر پاسخ', () => go('inbox', 'comments')));
  if (c.open_dms) todo.push(navRow('send', fa(c.open_dms) + ' دایرکت منتظر پاسخ', () => go('inbox', 'dm')));
  if (c.failed) todo.push(navRow('alert', fa(c.failed) + ' پست منتشرنشده', () => go('content', 'queue')));
  if (c.due) todo.push(navRow('send', fa(c.due) + ' پست منتظر انتشار به دست خودت', () => go('content', 'queue')));
  out.push(h('h3', null, 'کارهای منتظر تو'), todo.length ? todo : h('div', {class: 'card muted'}, icon('check'), ' همه‌چیز رسیدگی شده است.'));
  out.push(h('h3', null, 'انتشار'), st.next_post ? postCard(st.next_post) : null,
    h('div', {class: 'card col'}, h('div', {class: 'chips'}, h('span', {class: 'pill info'}, icon('clock'), fa(c.scheduled) + ' در صف'), h('span', {class: 'pill'}, icon('edit'), fa(c.drafts) + ' پیش‌نویس'),
        h('span', {class: 'pill ok'}, icon('check'), fa(c.published_today) + ' انتشار امروز'), st.quota ? h('span', {class: 'pill'}, 'سقف اینستاگرام: ' + fa(st.quota.used) + ' از ' + fa(st.quota.total)) : null),
      st.media.ready ? null : h('div', {class: 'sm down'}, 'برای انتشار از گالری هنوز «لینک عمومی» تنظیم نشده است (ایجنت ← تنظیمات).'),
      h('button', {class: 'btn pri', onclick: () => composer()}, icon('plus'), 'پست جدید')));
  const pill = (on, t) => h('span', {class: 'pill ' + (on ? 'ok' : '')}, t + ': ' + (on ? 'روشن' : 'خاموش'));
  out.push(h('h3', null, 'ایجنت امروز'), h('div', {class: 'card col'}, h('div', {class: 'chips'}, h('span', {class: 'pill'}, icon('zap'), fa(c.auto_today) + ' کار خودکار'),
      pill(au.comment_reply, 'پاسخ کامنت'), pill(au.spam_hide, 'ضد اسپم'), pill(au.dm_reply, 'پاسخ دایرکت')),
    st.quiet ? h('div', {class: 'muted sm'}, 'الان ساعت سکوت است؛ پاسخ‌های خودکار بعد از آن فرستاده می‌شوند.') : null,
    h('button', {class: 'btn sm', onclick: () => go('agent')}, icon('settings'), 'تنظیم کارهای خودکار')));
  const log = await GET('/api/log?limit=4');
  if (log.items.length) out.push(h('h3', null, 'آخرین رویدادها'), h('div', {class: 'card'}, log.items.map(logLine)));
  return out;
};
async function notesSheet() {
  const s = sheet('اعلان‌ها');
  try {
    const d = await GET('/api/log?limit=80');
    fill(s.body, d.items.length ? h('div', {class: 'card'}, d.items.map(logLine)) : empty('bell', 'هنوز رویدادی ثبت نشده است.'));
    await POST('/api/log/seen'); await refresh();
  } catch (e) { fill(s.body, h('div', {class: 'card bad'}, e.message)); }
}

/* ───── content: queue, drafts, page ───── */
function postCard(p) {
  const m = p.media[0], st = statusOf(p);
  const sub = p.status === 'scheduled' ? when(p.scheduled_at) : p.status === 'publishing' ? (p.progress || 'در حال انتشار…') : p.status === 'published' ? ago(p.published_at)
    : p.status === 'due' ? 'آماده است؛ بازش کن و در اینستاگرام بگذار' : (p.status === 'failed' || p.status === 'missed') ? p.error : 'آخرین تغییر: ' + ago(p.updated_at);
  return h('button', {class: 'card row', 'data-post': p.id, onclick: () => postSheet(p.id)}, thumb(m && !m.missing ? m.preview : '', m ? m.type : 'image'),
    h('div', {class: 'grow'}, h('div', {class: 'chips'}, h('span', {class: 'pill ' + st[1]}, st[0]), h('span', {class: 'pill'}, icon(KIND[p.kind][1]), KIND[p.kind][0])),
      h('div', {class: 'clamp'}, p.caption || '— بدون کپشن —'), h('div', {class: 'muted sm clamp'}, sub)));
}
function tile(m) {
  const src = m.thumbnail_url || m.media_url, k = m.media_type === 'VIDEO' ? 'film' : m.media_type === 'CAROUSEL_ALBUM' ? 'layers' : '';
  const t = h('button', {class: 'tile', 'aria-label': 'پست', onclick: () => mediaSheet(m.id)});
  if (src) { const img = h('img', {src, alt: '', loading: 'lazy'}); img.addEventListener('error', () => img.remove()); t.appendChild(img); }
  return add(t, k ? h('span', {class: 'kind'}, icon(k)) : null, h('span', {class: 'meta'}, icon('heart'), fa(m.like_count), icon('chat'), fa(m.comments_count)));
}
VIEWS.content = async () => {
  const c = S.st.counts, hand = !S.st.connected;
  if (hand && S.sub.content === 'page') S.sub.content = 'queue';
  const sub = S.sub.content;
  const seg = segment([['queue', hand ? 'برنامه' : 'صف انتشار', c.due + c.scheduled + c.publishing + c.failed], ['drafts', 'پیش‌نویس‌ها']].concat(hand ? [] : [['page', 'صفحهٔ من']]), sub, v => { S.sub.content = v; render(true); });
  if (sub === 'page') {
    const d = await GET('/api/media');
    return [seg, d.items.length ? h('div', {class: 'grid'}, d.items.map(tile)) : empty('grid', 'هنوز پستی در پیج نیست.')];
  }
  const [d, done] = await Promise.all([GET('/api/posts?group=' + sub), sub === 'queue' ? GET('/api/posts?group=published') : {items: []}]);
  const fresh = h('div', {class: 'row'}, h('button', {class: 'btn pri', 'data-studio': '1', onclick: () => studio({}, r => composer(null, r))}, icon('spark'), 'بساز'),
    h('button', {class: 'btn', onclick: () => composer()}, icon('plus'), 'پست جدید'));
  return [seg, sub === 'drafts' ? h('button', {class: 'btn', onclick: planSheet}, icon('spark'), 'چیدن برنامهٔ محتوایی') : null,
    d.items.length ? d.items.map(postCard) : empty('calendar', sub === 'queue' ? (hand ? 'چیزی در برنامه نیست.' : 'چیزی در صف انتشار نیست.') : 'پیش‌نویسی نداری.', fresh),
    done.items.length ? [h('h3', null, hand ? 'منتشرشده' : 'منتشرشده از همین پنل'), done.items.slice(0, 6).map(postCard)] : null];
};
async function mediaSheet(id) {
  const s = sheet('پست پیج');
  fill(s.body, h('div', {class: 'empty'}, 'در حال بارگذاری…'));
  try {
    const d = await GET('/api/media/' + id), m = d.media, src = m.thumbnail_url || m.media_url;
    fill(s.body, src ? h('img', {class: 'big', src, alt: ''}) : null, h('div', {class: 'pre'}, m.caption || ''), h('div', {class: 'muted sm'}, when(igts(m.timestamp))),
      d.error ? h('div', {class: 'card bad sm'}, d.error) : h('div', {class: 'kpis'}, d.metrics.map(x => h('div', {class: 'kpi'}, h('b', null, fa(x.value)), h('div', {class: 'muted sm'}, x.label)))));
    s.setFoot(m.permalink ? h('a', {class: 'btn', href: m.permalink, target: '_blank', rel: 'noopener'}, icon('external'), 'اینستاگرام') : null,
      h('button', {class: 'btn', onclick: () => threadsSheet(id)}, icon('chat'), 'کامنت‌ها' + (d.open_comments ? ' (' + fa(d.open_comments) + ' منتظر)' : '')));
  } catch (e) { fill(s.body, h('div', {class: 'card bad'}, e.message)); }
}
async function threadsSheet(mediaId) {
  const s = sheet('کامنت‌های این پست', {onclose: () => render(false)});
  try {
    const d = await GET('/api/comments?filter=all&media=' + mediaId);
    fill(s.body, d.items.length ? d.items.map(t => threadCard(t, true)) : empty('chat', 'کامنتی برای این پست ثبت نشده است.'));
  } catch (e) { fill(s.body, h('div', {class: 'card bad'}, e.message)); }
}
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return; } catch (e) { /* not allowed here: the old way */ }
  const ta = h('textarea', {class: 'in', value: text});
  ta.style.position = 'fixed'; ta.style.opacity = '0';
  D.body.appendChild(ta); ta.select();
  const ok = D.execCommand('copy');
  ta.remove();
  if (!ok) throw new Err('کپی نشد؛ متن را خودت انتخاب و کپی کن.');
}
function saveFile(file) {
  const url = URL.createObjectURL(file), a = h('a', {href: url, download: file.name, class: 'hide'});
  D.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}
/* Posting by hand: the file goes to the Instagram app (or to the gallery), the caption to the clipboard. */
function handKit(p, again) {
  const files = p.media.filter(m => m.file && !m.missing), links = p.media.filter(m => m.url);
  let ready = null;                                    /* fetched ahead, so that "share" still happens right on the tap */
  const load = () => ready || (ready = Promise.all(files.map(async (m, i) => {
    const res = await fetch(m.preview, {credentials: 'same-origin'});
    if (!res.ok) throw new Err('فایل این پست خوانده نشد.');
    const blob = await res.blob(), ext = {'video/mp4': 'mp4', 'video/webm': 'webm', 'video/quicktime': 'mov', 'image/jpeg': 'jpg'}[blob.type] || 'bin';
    return new File([blob], 'insta-' + p.id + (files.length > 1 ? '-' + (i + 1) : '') + '.' + ext, {type: blob.type});
  })));
  if (files.length) load().catch(() => { ready = null; });
  const canShare = !!(navigator.share && navigator.canShare) && files.length > 0;
  const save = async () => { for (const f of await load()) saveFile(f); toast('در پوشهٔ Download گوشی ذخیره شد'); };
  const share = async () => {
    const list = await load();
    if (!navigator.canShare({files: list})) return save();
    let copied = false;
    if (p.caption) { try { await copyText(p.caption); copied = true; } catch (e) { /* the caption can still be copied by its own button */ } }
    try { await navigator.share({files: list}); }
    catch (e) { if (e && e.name === 'AbortError') return; throw new Err('این مرورگر نتوانست فایل را به اپ دیگری بدهد؛ «ذخیره» را بزن و از گالری انتخابش کن.'); }
    if (copied) toast('کپشن کپی شده است؛ در اینستاگرام بچسبانش');
  };
  const btn = (label, ic, fn, cls, mark) => h('button', {class: 'btn ' + (cls || ''), 'data-kit': mark, onclick: e => run(e.currentTarget, fn)}, icon(ic), label);
  return h('div', {class: 'card col', 'data-kit': 'box'}, h('b', null, 'انتشار با خودت'),
    h('div', {class: 'muted sm'}, !files.length ? (links.length ? 'فایل این پست یک لینک است؛ بازش کن و ذخیره کن.' : 'این یادآوری فایل ندارد؛ عکس یا ویدیو را در خود اینستاگرام انتخاب کن.')
      : canShare ? 'با «ارسال به اینستاگرام» فایل مستقیم به اپ می‌رود و کپشن کپی می‌شود؛ آنجا بچسبانش.' : 'فایل را ذخیره کن، کپشن را کپی کن و در اپ اینستاگرام بگذار.'),
    canShare ? btn('ارسال به اینستاگرام', 'send', share, 'pri block', 'share') : null,
    h('div', {class: 'row'}, files.length ? btn('ذخیره در گوشی', 'upload', save, 'grow', 'save') : null,
      links.map(m => h('a', {class: 'btn grow', href: m.url, target: '_blank', rel: 'noopener'}, icon('external'), 'باز کردن فایل')),
      p.caption ? btn('کپی کپشن', 'layers', async () => { await copyText(p.caption); toast('کپشن کپی شد ✓'); }, 'grow', 'copy') : null),
    S.st.telegram && (files.length || p.caption) ? btn('بفرست به تلگرام خودم', 'send', async () => { await POST('/api/posts/' + p.id + '/telegram'); toast('فایل و کپشن در تلگرام توست ✓'); }, 'block', 'telegram') : null,
    btn('منتشر کردم', 'check', async () => { await POST('/api/posts/' + p.id + '/done'); toast('ثبت شد ✓'); await again(); }, 'block', 'done'));
}
function postSheet(id) {
  let timer = 0, last = '';
  const s = sheet('پست', {onclose: () => clearTimeout(timer)});
  const load = async () => {
    let p;
    try { p = await GET('/api/posts/' + id); } catch (e) { s.close(); return; }
    if (last && last !== p.status) render(false);
    last = p.status;
    const st = statusOf(p), again = async () => { await refresh(); render(false); await load(); };
    const one = p.media.length === 1 && p.media[0].file && !p.media[0].missing ? p.media[0] : null;
    const byHand = !['published', 'publishing'].includes(p.status) && (!S.st.connected || p.status === 'due');
    fill(s.body, one ? (one.type === 'video' ? h('video', {class: 'big', src: one.preview, controls: true, playsinline: true, preload: 'metadata'}) : h('img', {class: 'big', src: one.preview, alt: ''}))
        : p.media.length ? h('div', {class: 'strip'}, p.media.map(m => thumb(m.missing ? '' : m.preview, m.type, 'mitem'))) : null,
      h('div', {class: 'chips'}, h('span', {class: 'pill ' + st[1]}, st[0]), h('span', {class: 'pill'}, icon(KIND[p.kind][1]), KIND[p.kind][0])),
      p.status === 'scheduled' ? h('div', {class: 'row'}, icon('clock'), when(p.scheduled_at)) : null,
      p.status === 'publishing' ? h('div', {class: 'card'}, p.progress || 'در حال انتشار…', p.error ? h('div', {class: 'muted sm'}, 'آخرین مشکل: ' + p.error) : null) : null,
      (p.status === 'failed' || p.status === 'missed') && p.error ? h('div', {class: 'card bad'}, p.error) : null,
      p.status === 'published' ? h('div', {class: 'card ok'}, (p.by_hand ? 'خودت منتشرش کردی ✓ — ' : 'منتشر شد ✓ — ') + ago(p.published_at)) : null,
      byHand ? handKit(p, again) : null, h('div', {class: 'pre', dir: 'auto'}, p.caption || '— بدون کپشن —'));
    const act = (label, fn, cls, ic) => h('button', {class: 'btn ' + (cls || ''), onclick: e => run(e.currentTarget, fn)}, ic ? icon(ic) : null, label);
    const kids = [];
    if (p.status === 'publishing') {
      timer = setTimeout(load, 1500);
      if (p.attempts || p.next_try_at > S.st.now + 20) kids.push(act('توقف و برگشت به پیش‌نویس', async () => { clearTimeout(timer); await POST('/api/posts/' + id + '/cancel'); toast('به پیش‌نویس‌ها برگشت'); await again(); }, '', 'x'));
    } else if (p.status === 'published') {
      if (p.permalink) kids.push(h('a', {class: 'btn', href: p.permalink, target: '_blank', rel: 'noopener'}, icon('external'), 'اینستاگرام'));
      kids.push(act('کپی به پیش‌نویس', async () => { await POST('/api/posts/' + id + '/duplicate'); toast('در پیش‌نویس‌ها کپی شد'); s.close(); go('content', 'drafts'); }, '', 'layers'));
    } else {
      kids.push(act('حذف', async () => { if (await ask('این پست حذف شود؟', 'حذف', true)) { await DEL('/api/posts/' + id); s.close(); await refresh(); render(false); } }, 'danger', 'trash'));
      kids.push(act('ویرایش', async () => { s.close(); composer(p); }, '', 'edit'));
      if (p.status === 'scheduled' || p.status === 'due') kids.push(act(p.status === 'due' ? 'به پیش‌نویس' : S.st.connected ? 'لغو زمان' : 'لغو یادآوری', async () => { await POST('/api/posts/' + id + '/cancel'); toast('به پیش‌نویس‌ها برگشت'); await again(); }));
      if (S.st.connected) kids.push(act(p.status === 'failed' ? 'تلاش دوباره' : 'انتشار الان', async () => { await POST('/api/posts/' + id + '/publish'); await again(); }, 'pri', 'send'));
    }
    if (kids.length) s.setFoot(kids); else s.foot.classList.add('hide');
  };
  load();
}
async function planSheet() {
  const s = sheet('برنامهٔ محتوایی'), n = h('select', {class: 'in', 'aria-label': 'تعداد'}, [3, 5, 7].map(x => h('option', {value: x}, fa(x) + ' ایده')));
  n.value = '5';
  const btn = h('button', {class: 'btn pri', onclick: () => run(btn, async () => {
    const r = await POST('/api/ai/plan', {count: Number(n.value)});
    toast(fa(r.items.length) + ' پیش‌نویس با کپشن ساخته شد'); s.close(); await refresh(); go('content', 'drafts');
  })}, icon('spark'), 'بچین');
  add(s.body, h('p', {class: 'muted'}, 'دستیار چند ایدهٔ پست می‌سازد و هر کدام را با کپشن و هشتگ در پیش‌نویس‌ها می‌گذارد. بعد عکس یا ویدیو را اضافه و زمان‌بندی کن.'), h('div', {class: 'row'}, n, btn));
}

/* ───── composer ───── */
function loadImage(file) {
  return new Promise((res, rej) => {
    const url = URL.createObjectURL(file), img = new Image();
    img.onload = () => { URL.revokeObjectURL(url); res(img); };
    img.onerror = () => { URL.revokeObjectURL(url); rej(new Error('مرورگر نتوانست این عکس را باز کند.')); };
    img.src = url;
  });
}
/* Instagram only takes JPEG, at most 8 MB, between 4:5 and 1.91:1 → convert (and crop the middle) on the phone itself */
async function prepImage(file, kind) {
  const img = await loadImage(file);
  let sw = img.naturalWidth, sh = img.naturalHeight, sx = 0, sy = 0, cropped = false;
  if (kind !== 'story') {
    const r = sw / sh;
    if (r < 0.8) { const nh = Math.round(sw / 0.8); sy = Math.round((sh - nh) / 2); sh = nh; cropped = true; }
    else if (r > 1.91) { const nw = Math.round(sh * 1.91); sx = Math.round((sw - nw) / 2); sw = nw; cropped = true; }
  }
  const scale = Math.min(1, 1440 / sw), cv = h('canvas', {width: Math.round(sw * scale), height: Math.round(sh * scale)}), ctx = cv.getContext('2d');
  ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, cv.width, cv.height); ctx.drawImage(img, sx, sy, sw, sh, 0, 0, cv.width, cv.height);
  let q = 0.9, blob = null;
  do { blob = await new Promise(r => cv.toBlob(r, 'image/jpeg', q)); q -= 0.12; } while (blob && blob.size > 7.5e6 && q > 0.4);
  if (!blob) throw new Error('تبدیل عکس انجام نشد.');
  return {blob, cropped};
}
function composer(post, seed) {
  const hand = !S.st.connected;
  const p = post ? {id: post.id, kind: post.kind, caption: post.caption, opts: Object.assign({}, post.opts), mode: post.status === 'scheduled' ? 'later' : 'now', at: post.status === 'scheduled' ? post.scheduled_at : 0,
      media: post.media.filter(m => !m.missing).map(m => m.file ? {file: m.file, type: m.type, preview: m.preview} : {url: m.url, type: m.type, preview: m.url})}
    : Object.assign({kind: 'image', caption: '', media: [], opts: {share_to_feed: true}, mode: 'now', at: 0}, seed || {});
  const s = sheet(post ? 'ویرایش پست' : 'پست جدید');
  const file = h('input', {type: 'file', class: 'hide'}), cap = h('textarea', {class: 'in', rows: 5, placeholder: 'کپشن…', 'aria-label': 'کپشن', value: p.caption});
  const counter = h('div', {class: 'muted sm row'}), strip = h('div', {class: 'strip'}), kinds = h('div', {class: 'kinds'}), hint = h('div', {class: 'muted sm'}), timing = h('div', {class: 'card col'});
  const optBox = h('div', {class: 'col'}), capBox = h('div', {class: 'col'});
  const max = () => (p.kind === 'carousel' ? 20 : 1);
  /* Hashtags: Instagram advises five at most (more only gets a warning here); the API refuses more than thirty. */
  const TAG_GOOD = 5, TAG_MAX = 30, tagList = () => cap.value.match(/#[^\s#]+/g) || [];
  const tagNote = h('div', {class: 'sm amber hide', 'data-tagnote': '1'}, 'بیشتر از ' + fa(TAG_GOOD) + ' هشتگ: منتشر می‌شود، ولی اینستاگرام ممکن است اضافه‌ها را نادیده بگیرد یا کپشن را نگذارد.');
  const count = () => {
    const tags = tagList().length, many = tags > TAG_GOOD && tags <= TAG_MAX;
    fill(counter, h('span', {class: 'grow' + (cap.value.length > 2200 ? ' down' : '')}, fa(cap.value.length) + ' از ۲٬۲۰۰ نویسه'),
      h('span', {class: tags > TAG_MAX ? 'down' : many ? 'amber' : ''}, fa(tags) + ' هشتگ' + (tags > TAG_MAX ? ' (حداکثر ' + fa(TAG_MAX) + ')' : many ? ' (توصیه: تا ' + fa(TAG_GOOD) + ')' : '')));
    tagNote.classList.toggle('hide', !many);
  };
  cap.addEventListener('input', count);
  const addUrl = () => {
    const u = sheet('افزودن با لینک'), inp = h('input', {class: 'in ltr', placeholder: 'https://…/photo.jpg', 'aria-label': 'لینک'}), typ = h('select', {class: 'in'}, h('option', {value: 'image'}, 'عکس (JPEG)'), h('option', {value: 'video'}, 'ویدیو (MP4)'));
    if (p.kind === 'reel') typ.value = 'video';
    add(u.body, h('p', {class: 'muted sm'}, 'لینک باید مستقیم و عمومی باشد (اینستاگرام خودش فایل را از این نشانی برمی‌دارد).'), field('لینک فایل', inp), field('نوع فایل', typ));
    u.setFoot(h('button', {class: 'btn pri', onclick: () => { const v = inp.value.trim(); if (!/^https:\/\/\S+$/.test(v)) return toast('لینک باید با https:// شروع شود', 'bad'); p.media.push({url: v, type: typ.value, preview: v}); u.close(); paint(); }}, 'افزودن'));
  };
  /* the studio makes the picture or the reel from an idea; what it made lands here */
  const fromStudio = () => studio({kind: p.kind === 'reel' ? 'reel' : 'image', idea: cap.value.split('\n')[0].replace(/#\S+/g, '').trim()}, r => {
    if (p.kind === 'carousel' && r.kind === 'image') p.media.push(r.media[0]);
    else { p.kind = r.kind; p.media = r.media.slice(); }
    if (!cap.value.trim()) cap.value = r.caption;
    count(); paint();
  });
  const paintOpts = () => {
    const txt = (key, label, ph, rows) => { const el = h(rows ? 'textarea' : 'input', {class: 'in', placeholder: ph, rows, value: p.opts[key] || ''}); el.addEventListener('input', () => { p.opts[key] = el.value; }); return field(label, el); };
    const sw = (key, label, def) => h('div', {class: 'row'}, h('span', {class: 'grow'}, label), toggle(p.opts[key] == null ? def : p.opts[key], async v => { p.opts[key] = v; }, label));
    fill(optBox, p.kind === 'image' ? txt('alt_text', 'متن جایگزین عکس (برای نابینایان)', 'توضیح کوتاه عکس') : null,
      p.kind !== 'story' ? txt('first_comment', 'اولین کامنت (اختیاری)', 'بعد از انتشار، خود پیج این را زیر پست می‌نویسد', 2) : null,
      p.kind === 'reel' ? sw('share_to_feed', 'نمایش ریل در صفحهٔ اصلی پیج', true) : null,
      p.kind !== 'story' ? sw('comments_off', 'بستن کامنت‌های این پست', false) : h('div', {class: 'muted sm'}, 'استوری گزینهٔ دیگری ندارد.'));
  };
  const paintTiming = () => {
    fill(timing, h('b', null, hand ? 'کی می‌خواهی پستش کنی؟' : 'چه زمانی منتشر شود؟'), segment([['now', 'همین حالا'], ['later', hand ? 'یادآوری کن' : 'زمان‌بندی']], p.mode, v => {
      p.mode = v; if (v === 'later' && !p.at) p.at = Math.ceil((Date.now() / 1000 + 3600) / 900) * 900; paintTiming(); paintFoot(); }));
    if (p.mode !== 'later') return;
    const d = new Date(p.at * 1000), t0 = new Date(), dsel = h('select', {class: 'in', 'aria-label': 'روز'}), time = h('input', {class: 'in ltr', type: 'time', 'aria-label': 'ساعت', value: two(d.getHours()) + ':' + two(d.getMinutes())});
    let pick = 0;
    for (let i = 0; i < 75; i++) {
      const x = new Date(t0.getFullYear(), t0.getMonth(), t0.getDate() + i);
      if (x.toDateString() === d.toDateString()) pick = i;
      dsel.appendChild(h('option', {value: i}, (i === 0 ? 'امروز، ' : i === 1 ? 'فردا، ' : '') + day(x)));
    }
    dsel.value = String(pick);
    const label = h('div', {class: 'muted sm'}, when(p.at)), chips = h('div', {class: 'chips'});
    const sync = () => { const t = (time.value || '12:00').split(':'), x = new Date(t0.getFullYear(), t0.getMonth(), t0.getDate() + Number(dsel.value), Number(t[0]), Number(t[1])); p.at = x.getTime() / 1000; fill(label, when(p.at)); };
    dsel.addEventListener('change', sync); time.addEventListener('change', sync);
    GET('/api/slots').then(r => fill(chips, r.items.map(ts => h('button', {class: 'chip', onclick: () => { p.at = ts; paintTiming(); }}, when(ts))))).catch(() => {});
    add(timing, h('div', {class: 'row when'}, h('div', {class: 'grow'}, dsel), h('div', {class: 'fix'}, time)), label, h('div', {class: 'muted sm'}, hand ? 'ساعت‌های پیشنهادی:' : 'پیشنهاد ایجنت (ساعت‌هایی که پست‌هایت بهتر دیده شده):'), chips);
  };
  const paint = () => {
    fill(kinds, Object.keys(KIND).map(k => h('button', {class: p.kind === k ? 'on' : '', 'data-kind': k, onclick: () => { p.kind = k; p.media = p.media.slice(0, max()); paint(); }}, icon(KIND[k][1]), KIND[k][0])));
    file.accept = p.kind === 'reel' ? 'video/*' : p.kind === 'image' ? 'image/*' : 'image/*,video/*';
    file.multiple = p.kind === 'carousel';
    const more = p.media.length < max();
    fill(strip, p.media.map((m, i) => h('div', {class: 'mitem'}, thumb(m.preview, m.type, 'fit'), h('span', {class: 'tag'}, m.type === 'video' ? 'ویدیو' : 'عکس'),
        h('button', {class: 'rm', 'aria-label': 'برداشتن', onclick: () => { p.media.splice(i, 1); paint(); }}, icon('x')))),
      more ? h('button', {class: 'mitem add', 'data-add': 'file', onclick: () => file.click()}, icon('upload'), 'از گالری') : null,
      more && p.kind !== 'story' ? h('button', {class: 'mitem add', 'data-add': 'ai', onclick: fromStudio}, icon('spark'), 'بساز') : null,
      more && !hand ? h('button', {class: 'mitem add', 'data-add': 'url', onclick: addUrl}, icon('link'), 'با لینک') : null);
    fill(hint, {image: 'یک عکس. خودکار به JPEG تبدیل و اگر لازم باشد به نسبت مجاز (۴:۵ تا ۱٫۹۱:۱) بریده می‌شود.', carousel: '۲ تا ۲۰ عکس یا ویدیو؛ مخاطب ورق می‌زند.',
      reel: 'یک ویدیوی MP4 (عمودی ۹:۱۶ بهتر دیده می‌شود)؛ از ۳ ثانیه تا ۱۵ دقیقه و حداکثر ۳۰۰ مگابایت.', story: 'یک عکس یا ویدیو (۹:۱۶)؛ ویدیو حداکثر ۶۰ ثانیه و ۱۰۰ مگابایت. بدون کپشن فرستاده می‌شود و بعد از ۲۴ ساعت پاک می‌شود.'}[p.kind]);
    capBox.classList.toggle('hide', p.kind === 'story');
    paintOpts(); paintTiming(); paintFoot();
  };
  file.addEventListener('change', async () => {
    const files = Array.from(file.files).slice(0, max() - p.media.length);
    file.value = '';
    for (const f of files) {
      const ph = h('div', {class: 'mitem'}, 'در حال آماده‌سازی…');
      strip.prepend(ph);
      try {
        let blob = f, cropped = false;
        if (/^image\//.test(f.type) || /\.(jpe?g|png|webp|heic|heif)$/i.test(f.name)) { const r = await prepImage(f, p.kind); blob = r.blob; cropped = r.cropped; }
        else if (f.size > 300 * 1024 * 1024) throw new Error('حجم ویدیو بیش از ۳۰۰ مگابایت است.');
        const up = await api('POST', '/api/upload?name=' + encodeURIComponent(f.name), blob, true);
        p.media.push({file: up.id, type: up.type, preview: up.preview});
        if (cropped) toast('عکس به نسبت مجاز اینستاگرام برش خورد.');
      } catch (e) { toast((e && e.message) || 'این فایل خوانده نشد', 'bad'); }
      paint();
    }
  });
  const helper = (title, label, path, single) => {
    const a = sheet(title), topic = h('input', {class: 'in', placeholder: 'مثلاً: معرفی لاتهٔ پاییزی', 'aria-label': 'موضوع'}), list = h('div', {class: 'col'});
    const go_ = h('button', {class: 'btn pri', onclick: () => run(go_, async () => {
      fill(list, h('div', {class: 'muted'}, 'در حال نوشتن…'));
      let r;
      try { r = await POST(path, {topic: topic.value, kind: p.kind}); } catch (e) { fill(list); throw e; }
      const note = r.source === 'offline' ? h('div', {class: 'muted sm'}, 'سرویس هوش مصنوعی در دسترس نبود؛ این‌ها الگوهای آماده‌اند.') : null;
      if (single) fill(list, note, r.items.map(t => h('button', {class: 'card pre', 'data-pick': '1', onclick: () => { cap.value = t; count(); a.close(); }}, t)));
      else {
        const fillUp = () => {
          const got = tagList(), pick = r.items.filter(t => !got.includes(t)).slice(0, Math.max(0, TAG_GOOD - got.length));
          if (!pick.length) return toast('کپشن همین حالا ' + fa(got.length) + ' هشتگ دارد؛ اگر بیشتر می‌خواهی روی تک‌تک‌شان بزن.');
          cap.value = (cap.value.trim() + '\n\n' + pick.join(' ')).trim(); count(); a.close();
        };
        fill(list, note, h('div', {class: 'muted sm'}, 'روی هر هشتگ بزن تا به کپشن اضافه شود. اینستاگرام ۳ تا ' + fa(TAG_GOOD) + ' هشتگ دقیق را توصیه می‌کند.'),
          h('div', {class: 'chips'}, r.items.map(t => h('button', {class: 'chip', dir: 'auto', onclick: e => { cap.value = (cap.value.trim() + ' ' + t).trim(); count(); e.currentTarget.remove(); }}, t))),
          h('button', {class: 'btn', 'data-fill': '1', onclick: fillUp}, 'تکمیل تا ' + fa(TAG_GOOD) + ' هشتگ'));
      }
    })}, icon('spark'), 'بنویس');
    add(a.body, field(label, h('div', {class: 'row'}, topic, go_)), list);
  };
  const paintFoot = () => s.setFoot(h('button', {class: 'btn', onclick: e => save(e.currentTarget, 'draft')}, 'پیش‌نویس'),
    h('button', {class: 'btn pri', 'data-go': '1', onclick: e => save(e.currentTarget, p.mode === 'later' ? 'schedule' : 'now')}, icon(p.mode === 'later' ? 'clock' : 'send'),
      p.mode === 'later' ? (hand ? 'یادآوری' : 'زمان‌بندی') : (hand ? 'آماده کن' : 'انتشار')));
  const save = (btn, action) => run(btn, async () => {
    const body = {kind: p.kind, caption: p.kind === 'story' ? '' : cap.value, media: p.media.map(m => (m.file ? {file: m.file} : {url: m.url, type: m.type})), opts: p.opts, action, scheduled_at: p.at};
    const r = await POST(p.id ? '/api/posts/' + p.id : '/api/posts', body);
    s.close();
    toast(action === 'draft' ? 'در پیش‌نویس‌ها ذخیره شد' : action === 'schedule' ? (hand ? 'یادآوری تنظیم شد ✓' : 'زمان‌بندی شد ✓') : hand ? 'آماده است ✓' : 'انتشار شروع شد…');
    await refresh(); S.tab = 'content'; S.sub.content = action === 'draft' ? 'drafts' : 'queue'; render(true);
    if (action === 'now') postSheet(r.id);
  });
  add(capBox, field('کپشن', cap), counter, tagNote, h('div', {class: 'row'}, h('button', {class: 'btn sm grow', onclick: () => helper('کپشن پیشنهادی', 'این پست دربارهٔ چیست؟', '/api/ai/captions', true)}, icon('spark'), 'کپشن پیشنهادی'),
    h('button', {class: 'btn sm grow', onclick: () => helper('هشتگ پیشنهادی', 'موضوع پست', '/api/ai/hashtags', false)}, icon('hash'), 'هشتگ پیشنهادی')));
  add(s.body, kinds, strip, hint, file, capBox, hand ? null : h('details', {class: 'box'}, h('summary', null, icon('settings'), 'گزینه‌های بیشتر'), optBox), timing);
  count(); paint();
}

/* ───── studio: a picture or a reel out of one idea ─────
   The agent writes the words and fetches the pictures; everything is then drawn here, on the phone, so a result
   exists even when no picture service answered. */
const FACE = '"Vazirmatn", "Vazir", Tahoma, system-ui, sans-serif';
const LOOKS = [['#f97316', '#db2777'], ['#0ea5e9', '#4338ca'], ['#10b981', '#065f46'], ['#111827', '#4b5563'], ['#8b5cf6', '#4c1d95'], ['#fde68a', '#fca5a5'], ['#f59e0b', '#b45309'], ['#e0f2fe', '#a5b4fc']];
const SCENE_SEC = 3.2, FADE_SEC = 0.5, REEL_FPS = 30;
const PIC_FROM = {key: 'Pollinations', free: 'Pollinations رایگان', horde: 'AI Horde', custom: 'سرویس خودت'};
const NO_PLAN = {off: 'دستیار در تنظیمات خاموش است', limit: 'سرویس رایگان متن نوبت نداد', down: 'به سرویس متن دسترسی نبود', format: 'پاسخ سرویس متن قابل‌استفاده نبود'};
const blank = (w, ht) => Object.assign(D.createElement('canvas'), {width: w, height: ht});
const pause = ms => new Promise(r => setTimeout(r, ms || 0));
function loadPic(src) {
  return new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Err('تصویر باز نشد.')); i.src = src; });
}
async function faceReady() {
  if (!D.fonts || !D.fonts.load) return;
  try { await Promise.all([D.fonts.load('800 80px Vazirmatn'), D.fonts.load('500 40px Vazirmatn')]); } catch (e) { /* the phone's own font is used */ }
}
function cover(ctx, img, w, ht, zoom, cx, cy) {
  const iw = img.naturalWidth || img.width, ih = img.naturalHeight || img.height, s = Math.max(w / iw, ht / ih) * (zoom || 1), dw = iw * s, dh = ih * s;
  ctx.drawImage(img, (w - dw) * (cx == null ? 0.5 : cx), (ht - dh) * (cy == null ? 0.5 : cy), dw, dh);
}
function wrapText(ctx, text, maxW) {
  const out = [];
  for (const para of String(text || '').split('\n')) {
    let line = '';
    for (const word of para.split(/\s+/).filter(Boolean)) {
      const next = line ? line + ' ' + word : word;
      if (line && ctx.measureText(next).width > maxW) { out.push(line); line = word; } else line = next;
    }
    if (line) out.push(line);
  }
  return out;
}
/* the largest size at which the text fits its box */
function fitText(ctx, text, o) {
  let size = o.max, lines = [];
  const set = () => { ctx.font = o.weight + ' ' + Math.round(size) + 'px ' + FACE; lines = wrapText(ctx, text, o.w); };
  for (set(); size > o.min && (lines.length > o.lines || lines.some(l => ctx.measureText(l).width > o.w)); set()) size -= Math.max(2, size * 0.06);
  if (lines.length > o.lines) { lines = lines.slice(0, o.lines); lines[o.lines - 1] = lines[o.lines - 1].replace(/\s*\S*$/, '') + '…'; }
  return {size, lines};
}
function paintLines(ctx, lines, cx, top, size, o) {
  ctx.save();
  ctx.font = o.weight + ' ' + Math.round(size) + 'px ' + FACE; ctx.direction = 'rtl'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillStyle = o.ink;
  if (o.glow) { ctx.shadowColor = 'rgba(0,0,0,.6)'; ctx.shadowBlur = size * 0.22; ctx.shadowOffsetY = size * 0.04; }
  lines.forEach((l, i) => ctx.fillText(l, cx, top + size * 1.5 * (i + 0.5)));
  ctx.restore();
  return top + size * 1.5 * lines.length;
}
/* a drawn background for when there is no picture; returns true when it is a light one (dark words then) */
function backdrop(ctx, w, ht, look, t) {
  const pair = LOOKS[look % LOOKS.length], g = ctx.createLinearGradient(0, 0, w, ht), m = Math.min(w, ht), d = Math.sin((t || 0) * 0.7) * m * 0.025;
  const tone = c => { const n = parseInt(c.slice(1), 16); return (0.2126 * (n >> 16 & 255) + 0.7152 * (n >> 8 & 255) + 0.0722 * (n & 255)) / 255; };
  const light = tone(pair[0]) + tone(pair[1]) > 1.3, disc = (x, y, r) => { ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill(); };
  g.addColorStop(0, pair[0]); g.addColorStop(1, pair[1]);
  ctx.fillStyle = g; ctx.fillRect(0, 0, w, ht);
  ctx.fillStyle = light ? 'rgba(255,255,255,.35)' : 'rgba(255,255,255,.10)';
  disc(w * 0.86 + d, ht * 0.11, m * 0.34); disc(w * 0.08 - d, ht * 0.93, m * 0.42);
  ctx.fillStyle = light ? 'rgba(0,0,0,.05)' : 'rgba(0,0,0,.12)';
  disc(w * 0.5, ht * 1.08 + d, m * 0.62);
  return light;
}
/* a dark veil, so that words stay readable on any picture */
function veil(ctx, w, ht, place) {
  if (place === 'middle') { ctx.fillStyle = 'rgba(0,0,0,.42)'; ctx.fillRect(0, 0, w, ht); return; }
  const g = place === 'top' ? ctx.createLinearGradient(0, 0, 0, ht * 0.58) : ctx.createLinearGradient(0, ht, 0, ht * 0.38);
  g.addColorStop(0, 'rgba(0,0,0,.8)'); g.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = g; ctx.fillRect(0, 0, w, ht);
}
/* the words of one picture or one scene: a big line, an optional small one, and the name of the page */
function words(ctx, w, ht, o) {
  const u = w / 1080, gap = 20 * u;
  const head = o.head ? fitText(ctx, o.head, {w: w * 0.84, lines: o.lines, max: o.big * u, min: 50 * u, weight: 800}) : null;
  const sub = o.sub ? fitText(ctx, o.sub, {w: w * 0.8, lines: 2, max: 54 * u, min: 36 * u, weight: 500}) : null;
  const all = (head ? head.lines.length * head.size * 1.5 : 0) + (sub ? sub.lines.length * sub.size * 1.5 + gap : 0);
  let y = o.place === 'top' ? ht * 0.085 : o.place === 'middle' ? (ht - all) / 2 : ht * o.floor - all;
  const a = o.rise == null ? 1 : o.rise;
  ctx.save(); ctx.globalAlpha *= a; ctx.translate(0, (1 - a) * 40 * u);
  if (head) y = paintLines(ctx, head.lines, w / 2, y, head.size, {ink: o.ink, glow: o.glow, weight: 800});
  if (sub) paintLines(ctx, sub.lines, w / 2, y + gap, sub.size, {ink: o.ink, glow: o.glow, weight: 500});
  ctx.restore();
  if (!o.handle) return;
  ctx.save();
  ctx.font = '600 ' + Math.round(34 * u) + 'px ' + FACE; ctx.direction = 'ltr'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillStyle = o.ink; ctx.globalAlpha *= 0.85 * a;
  if (o.glow) { ctx.shadowColor = 'rgba(0,0,0,.6)'; ctx.shadowBlur = 8 * u; }
  ctx.fillText('@' + o.handle, w / 2, ht * o.tag);
  ctx.restore();
}
/* a feed picture. m: {img, head, sub, handle, look, words} */
function paintPost(cv, m) {
  const ctx = cv.getContext('2d'), w = cv.width, ht = cv.height;
  ctx.imageSmoothingQuality = 'high';
  let ink = '#fff', glow = true, place = ['bottom', 'top', 'middle'][m.look % 3];
  if (m.img) { cover(ctx, m.img, w, ht); if (m.words && (m.head || m.sub)) veil(ctx, w, ht, place); }
  else { const light = backdrop(ctx, w, ht, m.look, 0); ink = light ? '#111827' : '#fff'; glow = !light; place = 'middle'; }
  const show = m.words || !m.img;
  words(ctx, w, ht, {head: show ? m.head : '', sub: show ? m.sub : '', handle: m.handle, place, floor: 0.9, tag: place === 'bottom' || !m.img ? 0.95 : 0.955, ink, glow, big: m.img ? 104 : 128, lines: m.img ? 3 : 4});
}
/* one frame of a reel at second t. m: {scenes: [{img, text}], sub, handle, look} */
function paintReel(cv, m, t) {
  const ctx = cv.getContext('2d'), w = cv.width, ht = cv.height, n = m.scenes.length, at = Math.min(n - 1, Math.floor(t / SCENE_SEC));
  ctx.imageSmoothingQuality = 'medium';
  const one = (k, alpha) => {
    const sc = m.scenes[k], since = t - k * SCENE_SEC + FADE_SEC, p = Math.max(0, Math.min(1, since / (SCENE_SEC + FADE_SEC)));
    let ink = '#fff', glow = true;
    ctx.save(); ctx.globalAlpha = alpha;
    if (sc.img) { cover(ctx, sc.img, w, ht, k % 2 ? 1.16 - 0.1 * p : 1.05 + 0.1 * p, 0.5 + (k % 2 ? 0.08 : -0.08) * (p - 0.5), 0.5); veil(ctx, w, ht, 'bottom'); }
    else { const light = backdrop(ctx, w, ht, m.look + k, since); ink = light ? '#111827' : '#fff'; glow = !light; }
    const rise = Math.max(0, Math.min(1, (since - FADE_SEC - 0.1) / 0.45));
    words(ctx, w, ht, {head: sc.text, sub: k === n - 1 ? m.sub : '', handle: k === n - 1 ? m.handle : '', place: sc.img ? 'bottom' : 'middle', floor: 0.74, tag: 0.79,
      ink, glow, big: sc.img ? 92 : 112, lines: 3, rise: 1 - Math.pow(1 - rise, 3)});
    ctx.restore();
  };
  one(at, 1);
  const into = t - ((at + 1) * SCENE_SEC - FADE_SEC);
  if (at < n - 1 && into > 0) one(at + 1, Math.min(1, into / FADE_SEC));
}
const reelSeconds = m => m.scenes.length * SCENE_SEC + 0.2;

/* A plain MP4 (video only) out of H.264 samples. The index comes first, so the file plays while it still loads.
   turned: the frames lie on their side, the way phone cameras store upright video; the track says "turn me back". */
function mp4File(samples, avcC, w, ht, fps, turned, space) {
  const be = (v, n) => { const a = new Uint8Array(n); for (let i = n - 1; i >= 0; i--) { a[i] = v % 256; v = Math.floor(v / 256); } return a; };
  const u16 = v => be(v, 2), u32 = v => be(v, 4), txt = s => Uint8Array.from(s, c => c.charCodeAt(0)), zero = n => new Uint8Array(n);
  const join = parts => { const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0)); let o = 0; for (const p of parts) { out.set(p, o); o += p.length; } return out; };
  const box = (type, ...parts) => { const body = join(parts); return join([u32(body.length + 8), txt(type), body]); };
  const full = (type, flags, ...parts) => box(type, u32(flags), ...parts);
  const n = samples.length, tick = 1000, ms = Math.round(n * 1000 / fps);
  /* B-frames are shown later than they are decoded. Offsets may not be negative, so all shift and an edit list takes it back. */
  const shown = samples.map(s => Math.round(s.ts * fps / 1e6));
  let lead = 0;
  shown.forEach((p, i) => { lead = Math.max(lead, i - p); });
  const late = shown.map((p, i) => (p + lead - i) * tick), mixed = lead > 0 || late.some(v => v !== 0);
  const runs = []; for (const v of late) { if (runs.length && runs[runs.length - 1][1] === v) runs[runs.length - 1][0]++; else runs.push([1, v]); }
  const keys = []; samples.forEach((s, i) => { if (s.key) keys.push(i + 1); });
  const chunks = []; for (let i = 0; i < n; i += fps) chunks.push(Math.min(fps, n - i));
  const stsc = [[1, chunks[0]]]; if (chunks.length > 1 && chunks[chunks.length - 1] !== chunks[0]) stsc.push([chunks.length, chunks[chunks.length - 1]]);
  const flat = [u32(0x10000), u32(0), u32(0), u32(0), u32(0x10000), u32(0), u32(0), u32(0), u32(0x40000000)];
  const side = [u32(0), u32(0x10000), u32(0), u32(0xffff0000), u32(0), u32(0), u32(ht * 0x10000), u32(0), u32(0x40000000)];
  const colr = space && space.matrix ? box('colr', txt('nclx'), u16({bt709: 1, bt470bg: 5, smpte170m: 6}[space.primaries] || 1),
    u16({bt709: 1, smpte170m: 6, 'iec61966-2-1': 13}[space.transfer] || 1), u16({bt709: 1, bt470bg: 5, smpte170m: 6}[space.matrix] || 1), Uint8Array.of(space.fullRange ? 0x80 : 0)) : zero(0);
  const avc1 = box('avc1', zero(6), u16(1), zero(16), u16(w), u16(ht), u32(0x480000), u32(0x480000), u32(0), u16(1), zero(32), u16(24), u16(0xffff), box('avcC', avcC), colr);
  const moov = offsets => box('moov',
    full('mvhd', 0, u32(0), u32(0), u32(1000), u32(ms), u32(0x10000), u16(0x100), zero(10), ...flat, zero(24), u32(2)),
    box('trak',
      full('tkhd', 3, u32(0), u32(0), u32(1), u32(0), u32(ms), zero(8), u16(0), u16(0), u16(0), u16(0), ...(turned ? side : flat), u32(w * 0x10000), u32(ht * 0x10000)),
      mixed ? box('edts', full('elst', 0, u32(1), u32(ms), u32(lead * tick), u16(1), u16(0))) : zero(0),
      box('mdia',
        full('mdhd', 0, u32(0), u32(0), u32(fps * tick), u32(n * tick), u16(0x55c4), u16(0)),
        full('hdlr', 0, u32(0), txt('vide'), zero(12), txt('VideoHandler\0')),
        box('minf', full('vmhd', 1, zero(8)), box('dinf', full('dref', 0, u32(1), full('url ', 1))),
          box('stbl', full('stsd', 0, u32(1), avc1),
            full('stts', 0, u32(1), u32(n), u32(tick)),
            mixed ? full('ctts', 0, u32(runs.length), join(runs.map(r => join([u32(r[0]), u32(r[1])])))) : zero(0),
            keys.length < n ? full('stss', 0, u32(keys.length), join(keys.map(u32))) : zero(0),
            full('stsc', 0, u32(stsc.length), join(stsc.map(r => join([u32(r[0]), u32(r[1]), u32(1)])))),
            full('stsz', 0, u32(0), u32(n), join(samples.map(s => u32(s.data.length)))),
            full('stco', 0, u32(chunks.length), join(offsets.map(u32))))))));
  const ftyp = box('ftyp', txt('isom'), u32(512), txt('isomiso2avc1mp41'));
  const lay = start => { const out = []; let at = start, i = 0; for (const c of chunks) { out.push(at); for (let k = 0; k < c; k++) at += samples[i++].data.length; } return out; };
  const head = ftyp.length + moov(lay(0)).length + 8, total = samples.reduce((sum, x) => sum + x.data.length, 0);
  return new Blob([ftyp, moov(lay(head)), u32(total + 8), txt('mdat')].concat(samples.map(x => x.data)), {type: 'video/mp4'});
}
async function avcConfig(w, ht, fps) {
  if (typeof VideoEncoder === 'undefined' || typeof VideoFrame === 'undefined') return null;
  for (const codec of ['avc1.640028', 'avc1.4d0028', 'avc1.42e028', 'avc1.42001f']) {
    const cfg = {codec, width: w, height: ht, bitrate: Math.round(w * ht * fps * 0.1), framerate: fps, avc: {format: 'avc'}};
    try { if ((await VideoEncoder.isConfigSupported(cfg)).supported) return cfg; } catch (e) { /* try the next profile */ }
  }
  return null;
}
/* Frame by frame through the device's own H.264 encoder; null when this browser has none for that size. */
async function encodeFrames(stage, paint, seconds, fps, turned, onStep, stop) {
  const cw = turned ? stage.height : stage.width, ch = turned ? stage.width : stage.height, cfg = await avcConfig(cw, ch, fps);
  if (!cfg) return null;
  const lay = turned ? blank(cw, ch) : stage, lctx = turned ? lay.getContext('2d') : null, samples = [], frames = Math.round(seconds * fps);
  let desc = null, space = null, failed = null;
  const enc = new VideoEncoder({error: e => { failed = e; }, output: (chunk, meta) => {
    const dc = meta && meta.decoderConfig;
    if (dc && dc.description) { desc = new Uint8Array(dc.description.buffer ? dc.description.buffer.slice(dc.description.byteOffset, dc.description.byteOffset + dc.description.byteLength) : dc.description); space = dc.colorSpace || null; }
    const data = new Uint8Array(chunk.byteLength);
    chunk.copyTo(data);
    samples.push({data, key: chunk.type === 'key', ts: chunk.timestamp});
  }});
  enc.configure(cfg);
  try {
    for (let i = 0; i < frames; i++) {
      if (stop.on) throw new Err('لغو شد.', 0, true);
      if (failed) throw failed;
      paint(i / fps);
      if (turned) { lctx.setTransform(0, -1, 1, 0, 0, ch); lctx.drawImage(stage, 0, 0); }
      const frame = new VideoFrame(lay, {timestamp: Math.round(i * 1e6 / fps), duration: Math.round(1e6 / fps)});
      enc.encode(frame, {keyFrame: i % (fps * 2) === 0});
      frame.close();
      while (enc.encodeQueueSize > 4 && !failed) await pause();
      if (i % 6 === 0) { onStep(i / frames); await pause(); }
    }
    await enc.flush();
    if (failed) throw failed;
  } finally { try { enc.close(); } catch (e) { /* closed already */ } }
  if (!desc || samples.length !== frames) throw new Error('the encoder returned ' + samples.length + ' of ' + frames + ' frames');
  return mp4File(samples, desc, cw, ch, fps, turned, space);
}
/* The fallback: play the reel once on a canvas and let the browser record it (takes as long as the reel itself). */
function recordLive(stage, paint, seconds, fps, onStep, stop) {
  return new Promise((res, rej) => {
    const kinds = ['video/mp4;codecs=avc1.640028', 'video/mp4;codecs=avc1.4d0028', 'video/mp4;codecs=avc1', 'video/mp4', 'video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'];
    const type = typeof MediaRecorder === 'undefined' || !stage.captureStream ? '' : kinds.find(k => MediaRecorder.isTypeSupported(k));
    if (!type) return rej(new Err('این مرورگر نمی‌تواند ویدیو بسازد؛ با Chrome امتحان کن.'));
    paint(0);
    const stream = stage.captureStream(fps), rec = new MediaRecorder(stream, {mimeType: type, videoBitsPerSecond: Math.round(stage.width * stage.height * fps * 0.1)}), parts = [], t0 = performance.now();
    let broke = null;
    rec.ondataavailable = e => { if (e.data && e.data.size) parts.push(e.data); };
    rec.onerror = () => { broke = new Err('ضبط ویدیو متوقف شد.'); };
    rec.onstop = () => { stream.getTracks().forEach(tr => tr.stop()); if (broke) rej(broke); else res(new Blob(parts, {type: type.split(';')[0]})); };
    const tick = () => {
      const t = (performance.now() - t0) / 1000;
      if (stop.on || D.hidden) broke = stop.on ? new Err('لغو شد.', 0, true) : new Err('صفحه بسته شد و ضبط ناتمام ماند. دوباره بساز و تا پایان، همین صفحه را باز نگه دار.');
      if (broke || t >= seconds + 0.15) return rec.stop();
      paint(Math.min(t, seconds)); onStep(Math.min(1, t / seconds));
      requestAnimationFrame(tick);
    };
    rec.start();
    requestAnimationFrame(tick);
  });
}
/* Full size first; then the same lying on its side (older phones only encode wide pictures); then smaller; then recording. */
async function renderReel(m, onStep, stop) {
  const seconds = reelSeconds(m), ways = S.video ? [S.video] : [[1080, false], [1080, true], [720, false], [720, true], 'live'];
  let last = null;
  for (const way of ways) {
    const width = way === 'live' ? 720 : way[0], stage = blank(width, width * 16 / 9), paint = t => paintReel(stage, m, t);
    try {
      const blob = way === 'live' ? await recordLive(stage, paint, seconds, REEL_FPS, onStep, stop) : await encodeFrames(stage, paint, seconds, REEL_FPS, way[1], onStep, stop);
      if (blob) return {blob, way: way === 'live' ? 'live' : width + (way[1] ? ' turned' : ''), seconds};
    } catch (e) { if (e && e.silent) throw e; last = e; }
  }
  throw last instanceof Err ? last : new Err('ساخت ویدیو روی این دستگاه انجام نشد' + (last && last.message ? ' (' + last.message + ')' : '') + '.');
}

function studio(init, done) {
  init = init || {};
  const m = {kind: init.kind === 'reel' ? 'reel' : 'image', style: 'photo', scenes: 4, pics: S.st.studio.image !== 'off', look: Math.floor(Math.random() * LOOKS.length), words: true, shots: []};
  const stop = {on: false}, handle = () => (S.st.connected ? S.st.account.username : S.st.handle) || '';
  let timer = 0, anim = 0, jobId = '';
  const quit = () => { clearTimeout(timer); cancelAnimationFrame(anim); if (jobId) { POST('/api/studio/job/' + jobId + '/cancel').catch(() => {}); jobId = ''; } };
  const s = sheet('بساز', {onclose: () => { stop.on = true; quit(); }});
  const idea = h('textarea', {class: 'in', rows: 3, placeholder: 'مثلاً: تخفیف ۲۰٪ لاتهٔ پاییزی تا آخر هفته', 'aria-label': 'ایدهٔ پست', value: init.idea || ''});
  const demo = () => (S.st.demo ? h('div', {class: 'muted sm'}, 'حالت نمایشی: متن‌ها و تصویرها ساختگی‌اند؛ در اجرای واقعی از سرویس‌های هوش مصنوعی می‌آیند.') : null);

  const form = () => {
    quit();
    const styles = [['photo', 'عکس واقعی'], ['art', 'تصویرسازی'], ['minimal', 'مینیمال'], ['3d', 'سه‌بعدی']];
    const off = S.st.studio.image === 'off';
    fill(s.body, field('ایده‌ات را بنویس', idea),
      segment([['image', 'عکس'], ['reel', 'ویدیو (ریل)']], m.kind, v => { m.kind = v; form(); }),
      m.kind === 'reel' ? [h('label', {class: 'f'}, 'چند صحنه؟'), segment([[3, '۳'], [4, '۴'], [5, '۵']], m.scenes, v => { m.scenes = v; form(); })] : null,
      h('label', {class: 'f'}, 'سبک تصویر'), h('div', {class: 'chips'}, styles.map(x => h('button', {class: 'chip' + (m.style === x[0] ? ' on' : ''), 'data-style': x[0], onclick: () => { m.style = x[0]; form(); }}, x[1]))),
      h('div', {class: 'row'}, h('div', {class: 'grow'}, h('b', null, 'تصویر با هوش مصنوعی'),
          h('div', {class: 'muted sm'}, off ? 'در تنظیمات خاموش است؛ طرح‌های خود برنامه استفاده می‌شود.' : S.st.studio.pollen || S.st.studio.custom ? 'با کلید خودت ساخته می‌شود.'
            : m.kind === 'reel' ? 'سرویس‌های رایگان کند و کوچک‌اند؛ برای ریل یکی دو دقیقه صبر لازم است.' : 'از سرویس رایگان می‌آید؛ چند ثانیه تا یک دقیقه طول می‌کشد.')),
        off ? null : toggle(m.pics, async v => { m.pics = v; }, 'تصویر با هوش مصنوعی')), demo());
    s.setFoot(h('button', {class: 'btn pri', 'data-studio-go': '1', onclick: e => run(e.currentTarget, start)}, icon('spark'), m.kind === 'reel' ? 'ویدیو را بساز' : 'عکس را بساز'));
  };
  const working = job => {
    const got = job.pictures.filter(p => p.file).length;
    fill(s.body, h('div', {class: 'empty'}, h('i', {class: 'spin'}), h('b', null, job.step || 'در حال ساختن…'),
      job.pictures.length > 1 ? h('div', {class: 'muted sm'}, fa(got) + ' از ' + fa(job.pictures.length) + ' تصویر آماده است') : null,
      h('div', {class: 'muted sm'}, 'همین صفحه را باز نگه دار.')),
      got ? h('div', {class: 'strip'}, job.pictures.filter(p => p.file).map(p => thumb(p.preview, 'image', 'mitem'))) : null);
    s.setFoot(h('button', {class: 'btn', onclick: form}, icon('x'), 'لغو'));
  };
  const watch = (job, then) => {
    jobId = job.id; working(job);
    const look = async () => {
      if (stop.on || jobId !== job.id) return;
      try { job = await GET('/api/studio/job/' + job.id); } catch (e) { jobId = ''; toast(e.message, 'bad'); return form(); }
      if (stop.on || jobId !== job.id) return;
      if (job.status === 'running') { working(job); timer = setTimeout(look, 900); return; }
      jobId = '';
      if (job.status !== 'done') { if (job.status === 'failed') toast(job.error || 'ساخته نشد', 'bad'); return form(); }
      try { await then(job); } catch (e) { toast((e && e.message) || 'خطا', 'bad'); form(); }
    };
    timer = setTimeout(look, 500);
  };
  const start = async () => {
    const text = idea.value.trim();
    if (text.length < 3) { toast('ایده‌ات را در یک جمله بنویس', 'bad'); return; }
    watch(await POST('/api/studio/make', {idea: text, kind: m.kind, scenes: m.scenes, style: m.style, pictures: m.pics}), async job => {
      const plan = job.plan;
      Object.assign(m, {plan, notes: job.notes, head: plan.headline, sub: plan.sub, caption: (plan.caption + '\n\n' + plan.hashtags.join(' ')).trim()});
      m.shots = job.pictures.map((p, i) => ({prompt: p.prompt, src: p.preview, from: p.source, why: p.why, img: null, text: plan.scenes[i] ? plan.scenes[i].text : ''}));
      await Promise.all(m.shots.map(async sh => { if (sh.src) { try { sh.img = await loadPic(sh.src); } catch (e) { sh.src = ''; sh.why = 'تصویر باز نشد.'; } } }));
      await faceReady();
      result();
    });
  };
  /* one more picture for shot i, from the description as it stands now */
  const redo = (i, prompt) => run(null, async () => {
    watch(await POST('/api/studio/picture', {prompt, shape: m.kind === 'reel' ? 'reel' : 'post', style: m.style}), async job => {
      const p = job.pictures[0], sh = m.shots[i];
      sh.prompt = prompt;
      if (p.file) Object.assign(sh, {src: p.preview, from: p.source, why: '', img: await loadPic(p.preview)});
      else toast(p.why || 'تصویر ساخته نشد', 'bad');
      m.notes = (m.notes || []).concat(job.notes.filter(x => !(m.notes || []).includes(x)));
      result();
    });
  });
  const facts = () => {
    const drawn = m.shots.filter(x => x.img).length, why = (m.shots.find(x => !x.img && x.why) || {}).why;
    return [m.plan.source === 'offline' ? h('div', {class: 'sm amber'}, 'متن‌ها الگوی آماده‌اند (' + (NO_PLAN[m.plan.why] || 'دستیار جواب نداد') + '). می‌توانی خودت عوضشان کنی.') : null,
      h('div', {class: 'muted sm', 'data-pics': drawn}, m.shots.length === 1 ? (drawn ? 'تصویر: هوش مصنوعی (' + (PIC_FROM[m.shots[0].from] || '') + ')' : 'تصویر: طرح خود برنامه')
        : drawn === m.shots.length ? 'هر ' + fa(drawn) + ' تصویر را هوش مصنوعی ساخته است.' : !drawn ? 'زمینه‌ها طرح خود برنامه‌اند.'
        : fa(drawn) + ' از ' + fa(m.shots.length) + ' تصویر را هوش مصنوعی ساخته؛ بقیه طرح خود برنامه‌اند.'),
      !drawn || drawn < m.shots.length ? (why ? h('div', {class: 'muted sm'}, why) : null) : null,
      (m.notes || []).map(x => h('div', {class: 'sm amber'}, x)), demo()];
  };
  const describe = i => {
    const sh = m.shots[i], ta = h('textarea', {class: 'in ltr', rows: 3, 'aria-label': 'توصیف تصویر', value: sh.prompt});
    return h('details', {class: 'box'}, h('summary', null, icon('image'), m.shots.length > 1 ? 'تصویر صحنهٔ ' + fa(i + 1) : 'تصویر دیگر'),
      h('div', {class: 'col'}, h('div', {class: 'muted sm'}, 'تصویرساز انگلیسی را بهتر می‌فهمد. بنویس تصویر چه چیزی را نشان بدهد.'), ta,
        h('button', {class: 'btn', 'data-redo': i, onclick: () => redo(i, ta.value.trim())}, icon('refresh'), 'تصویر تازه بساز')));
  };
  const result = () => {
    cancelAnimationFrame(anim);
    const text = (label, key, obj) => { const el = h('input', {class: 'in', 'aria-label': label, value: obj[key] || ''}); el.addEventListener('input', () => { obj[key] = el.value; paint(); }); return field(label, el); };
    const stage = m.kind === 'reel' ? blank(540, 960) : blank(1080, 1350), t0 = performance.now();
    stage.className = 'stage' + (m.kind === 'reel' ? ' tall' : '');
    const reel = () => ({scenes: m.shots.map(x => ({img: x.img, text: x.text})), sub: m.sub, handle: handle(), look: m.look});
    const paint = () => { if (m.kind === 'image') paintPost(stage, {img: m.shots[0].img, head: m.head, sub: m.sub, handle: handle(), look: m.look, words: m.words}); };
    const loop = () => { if (!stage.isConnected) return; paintReel(stage, reel(), ((performance.now() - t0) / 1000) % reelSeconds(reel())); anim = requestAnimationFrame(loop); };
    const next = h('button', {class: 'btn sm', 'data-look': '1', onclick: () => { m.look++; paint(); }}, icon('refresh'), m.kind === 'reel' || m.shots[0].img ? 'چیدمان دیگر' : 'رنگ دیگر');
    fill(s.body, stage, facts(),
      m.kind === 'image' ? [text('نوشتهٔ روی تصویر', 'head', m), text('خط دوم (اختیاری)', 'sub', m),
          h('div', {class: 'row'}, m.shots[0].img ? [h('span', {class: 'grow'}, 'نوشته روی تصویر باشد'), toggle(m.words, async v => { m.words = v; paint(); }, 'نوشته روی تصویر')] : h('span', {class: 'grow'}), next), describe(0)]
        : [m.shots.map((sh, i) => text('نوشتهٔ صحنهٔ ' + fa(i + 1), 'text', sh)), text('خط آخر (اختیاری)', 'sub', m), h('div', {class: 'row'}, h('span', {class: 'grow muted sm'}, 'ویدیو بی‌صداست؛ آهنگ را موقع انتشار در اینستاگرام اضافه کن.'), next),
          m.shots.map((sh, i) => describe(i))],
      h('label', {class: 'f'}, 'کپشن (در مرحلهٔ بعد می‌توانی عوضش کنی)'), h('div', {class: 'card pre sm', dir: 'auto', 'data-caption': '1'}, m.caption));
    s.setFoot(h('button', {class: 'btn', onclick: form}, 'از نو'), h('button', {class: 'btn pri', 'data-studio-done': '1', onclick: e => run(e.currentTarget, m.kind === 'reel' ? () => film(reel()) : finish)}, icon('check'), m.kind === 'reel' ? 'ساخت ویدیو' : 'ادامه'));
    if (m.kind === 'reel') loop(); else paint();
  };
  const finish = async () => {
    const cv = $('canvas.stage', s.body), blob = await new Promise(r => cv.toBlob(r, 'image/jpeg', 0.92));
    if (!blob) throw new Err('تصویر ساخته نشد.');
    const up = await api('POST', '/api/upload?name=studio.jpg', blob, true);
    s.close();
    done({kind: 'image', caption: m.caption, media: [{file: up.id, type: up.type, preview: up.preview}]});
  };
  const film = async model => {
    cancelAnimationFrame(anim);
    const bar = h('i'), pct = h('b', null, '۰٪'), halt = {on: false};
    fill(s.body, h('div', {class: 'empty'}, h('i', {class: 'spin'}), h('div', null, 'در حال ساخت ویدیو… ', pct), h('div', {class: 'bar grow'}, bar), h('div', {class: 'muted sm'}, 'همین صفحه را باز و روشن نگه دار.')));
    s.setFoot(h('button', {class: 'btn', onclick: () => { halt.on = true; }}, icon('x'), 'لغو'));
    let made;
    try { made = await renderReel(model, p => { bar.style.width = Math.round(p * 100) + '%'; fill(pct, fa(Math.round(p * 100)) + '٪'); }, {get on() { return halt.on || stop.on; }}); }
    catch (e) { if (!stop.on) result(); if (e && e.silent) return; throw e; }
    fill(pct, '۱۰۰٪');
    const mp4 = made.blob.type === 'video/mp4', up = await api('POST', '/api/upload?name=studio.' + (mp4 ? 'mp4' : 'webm'), made.blob, true);
    S.made = {way: made.way, type: made.blob.type, size: made.blob.size, seconds: made.seconds, file: up.id};
    s.close();
    if (!mp4) toast('این مرورگر ویدیو را به شکل WebM ساخت و اینستاگرام شاید آن را نپذیرد؛ با Chrome دوباره بساز.', 'bad');
    done({kind: 'reel', caption: m.caption, media: [{file: up.id, type: up.type, preview: up.preview}]});
  };
  form();
  if (idea.value.trim().length >= 3 && init.kind) run(null, start);
}

/* ───── comments & direct ───── */
function threadCard(t, keep) {
  const card = h('div', {class: 'card col thread'});
  const gone = () => { card.remove(); if (!keep && !$('#view .thread')) render(false); };
  const paint = t => {
    /* a half-written reply survives the list being redrawn when new comments arrive */
    const ta = h('textarea', {class: 'in', rows: 1, placeholder: 'پاسخ بده…', 'aria-label': 'پاسخ', value: t.id in S.typed ? S.typed[t.id] : (t.suggest || '')});
    ta.addEventListener('input', () => { S.typed[t.id] = ta.value; });
    const act = (btn, action, body, msg, id) => run(btn, async () => {
      const r = await POST('/api/comments/' + (id || t.id) + '/' + action, body);
      if (action === 'reply' || action === 'delete') delete S.typed[t.id];
      toast(msg); await refresh();
      if (r.thread && (keep || S.filter !== 'open' || r.thread.open)) paint(r.thread); else gone();
    });
    const send = h('button', {class: 'btn pri', 'aria-label': 'فرستادن پاسخ', onclick: () => act(send, 'reply', {text: ta.value}, 'پاسخ فرستاده شد ✓')}, icon('send'));
    const bubble = c => h('div', {class: 'bubble' + (c.mine ? ' me' : '')}, h('small', null, h('b', {class: 'ltr'}, '@' + c.username), ' · ' + ago(c.ts) + (c.hidden ? ' · مخفی‌شده' : '') + (c.dm_sent ? ' · پیام خصوصی رفت' : '')), h('span', {dir: 'auto'}, c.text));
    fill(card, h('div', {class: 'row'}, thumb(t.media.thumb, 'image', 'thumb s'), h('div', {class: 'grow muted sm clamp'}, t.media.caption || 'پست'),
        t.open ? h('span', {class: 'pill pri'}, 'منتظر پاسخ') : null, h('button', {class: 'iconbtn', 'aria-label': 'بیشتر', onclick: () => menu(t, act, paint)}, icon('more'))),
      h('div', {class: 'chat'}, bubble(t.top), t.replies.map(bubble)),
      t.suggest ? h('div', {class: 'muted sm'}, icon('spark'), ' پیشنهاد دستیار در کادر پایین است؛ اگر خوب بود بفرست.') : null,
      h('div', {class: 'row replybar'}, ta, send),
      t.open ? h('button', {class: 'btn sm', onclick: e => run(e.currentTarget, async () => { await POST('/api/comments/' + t.id + '/dismiss'); await refresh(); if (keep || S.filter !== 'open') { t.open = false; paint(t); } else gone(); })}, icon('check'), 'نیازی به پاسخ نیست') : null);
  };
  paint(t);
  return card;
}
function menu(t, act, paint) {
  const s = sheet('کامنت @' + t.top.username), target = [t.top].concat(t.replies).filter(c => !c.mine).pop() || t.top;
  const item = (ic, label, fn, cls) => h('button', {class: 'btn block ' + (cls || ''), onclick: e => fn(e.currentTarget)}, icon(ic), label);
  add(s.body,
    item('spark', 'پیشنهاد پاسخ از دستیار', b => run(b, async () => { const r = await POST('/api/comments/' + t.id + '/suggest'); t.suggest = r.text; delete S.typed[t.id]; s.close(); paint(t); })),
    item('send', 'پیام خصوصی (دایرکت) به این کاربر', () => {
      s.close();
      const d = sheet('پیام خصوصی به @' + target.username), ta = h('textarea', {class: 'in', rows: 3, placeholder: 'متن پیام…', 'aria-label': 'پیام خصوصی'});
      add(d.body, h('p', {class: 'muted sm'}, 'اینستاگرام برای هر کامنت فقط یک پیام خصوصی و تا ۷ روز بعد از آن را اجازه می‌دهد.'), ta);
      d.setFoot(h('button', {class: 'btn pri', onclick: e => act(e.currentTarget, 'private', {text: ta.value}, 'پیام خصوصی فرستاده شد ✓', target.id).then(() => d.close())}, icon('send'), 'فرستادن'));
    }),
    t.top.hidden ? item('eye', 'نمایش دوبارهٔ کامنت', b => { s.close(); act(b, 'unhide', {}, 'کامنت دوباره دیده می‌شود'); })
      : item('eyeoff', 'مخفی‌کردن کامنت', b => { s.close(); act(b, 'hide', {}, 'کامنت مخفی شد'); }),
    item('trash', 'حذف کامنت', async b => { if (await ask('این کامنت برای همیشه از اینستاگرام حذف شود؟', 'حذف', true)) { s.close(); act(b, 'delete', {}, 'کامنت حذف شد'); } }, 'danger'),
    t.media.permalink ? h('a', {class: 'btn block', href: t.media.permalink, target: '_blank', rel: 'noopener'}, icon('external'), 'دیدن پست در اینستاگرام') : null);
}
function syncBtn(path) {
  return h('button', {class: 'iconbtn', 'aria-label': 'تازه‌سازی', onclick: e => run(e.currentTarget, async () => { await POST(path); await refresh(); render(false); toast('تازه شد'); })}, icon('refresh'));
}
function convRow(c) {
  return h('button', {class: 'card row', 'data-conv': c.id, onclick: () => chatSheet(c.id)}, h('span', {class: 'avatar s'}, (c.username || '?').charAt(0).toUpperCase()),
    h('div', {class: 'grow'}, h('div', {class: 'row'}, h('b', {class: 'ltr grow'}, '@' + c.username), h('small', {class: 'muted'}, ago(c.last_ts))), h('div', {class: 'muted sm clamp', dir: 'auto'}, (c.last_from_me ? 'شما: ' : '') + c.last_text)),
    c.open ? h('span', {class: 'pill pri'}, 'تازه') : null);
}
async function chatSheet(id) {
  let timer = 0, seen = '';
  const url = '/api/dm/' + encodeURIComponent(id), s = sheet('گفتگو', {onclose: () => { clearInterval(timer); render(false); }});
  const box = h('div', {class: 'chat'}), note = h('div', {class: 'muted sm'}), ta = h('textarea', {class: 'in', rows: 1, placeholder: 'پیام…', 'aria-label': 'پیام'});
  const send = h('button', {class: 'btn pri', 'aria-label': 'فرستادن پیام', onclick: () => run(send, async () => { const d = await POST(url + '/send', {text: ta.value}); ta.value = ''; paint(d); refresh(); })}, icon('send'));
  const paint = d => {
    const c = d.conv, sig = d.messages.map(m => m.id).join();
    fill(s.title, h('span', {class: 'ltr'}, '@' + c.username));
    if (sig !== seen) { seen = sig; fill(box, d.messages.map(m => h('div', {class: 'bubble' + (m.mine ? ' me' : '')}, h('span', {dir: 'auto'}, m.text), h('small', null, ago(m.ts))))); s.body.scrollTop = s.body.scrollHeight; }
    fill(note, c.can_reply ? (c.open ? h('button', {class: 'btn sm', onclick: e => run(e.currentTarget, async () => { await POST(url + '/dismiss'); await refresh(); s.close(); })}, icon('check'), 'نیازی به پاسخ نیست') : null)
      : 'از آخرین پیام این کاربر بیش از ۲۴ ساعت گذشته است؛ اینستاگرام اجازهٔ پاسخ از اینجا را نمی‌دهد. از خود اپ اینستاگرام جواب بده.');
    ta.disabled = !c.can_reply;
  };
  add(s.body, box, note);
  s.setFoot(h('button', {class: 'iconbtn', 'aria-label': 'پیشنهاد دستیار', onclick: e => run(e.currentTarget, async () => { ta.value = (await POST(url + '/suggest')).text; })}, icon('spark')), ta, send);
  const load = async () => { try { paint(await GET(url)); } catch (e) { /* keep what is shown */ } };
  await load();
  timer = setInterval(load, 5000);
}
VIEWS.inbox = async () => {
  const c = S.st.counts, sub = S.sub.inbox;
  const seg = segment([['comments', 'کامنت‌ها', c.open_comments], ['dm', 'دایرکت', c.open_dms]], sub, v => { S.sub.inbox = v; render(true); });
  if (sub === 'dm') {
    const d = await GET('/api/dm');
    return [h('div', {class: 'row'}, h('div', {class: 'grow'}, seg), syncBtn('/api/dm/sync')), d.blocked ? h('div', {class: 'card bad sm'}, d.blocked) : null,
      d.items.length ? d.items.map(convRow) : empty('send', 'هنوز گفتگویی نیست.'),
      h('p', {class: 'muted sm'}, 'اینستاگرام فقط تا ۲۴ ساعت بعد از آخرین پیام هر نفر اجازهٔ پاسخ از این راه را می‌دهد. برای دایرکت با عموم مردم، برنامه‌ات در متا باید «Advanced Access» داشته باشد.')];
  }
  const d = await GET('/api/comments?filter=' + S.filter);
  const chips = h('div', {class: 'chips grow'}, [['open', 'پاسخ‌نداده'], ['all', 'همه'], ['hidden', 'مخفی‌شده']].map(f => h('button', {class: 'chip' + (S.filter === f[0] ? ' on' : ''), onclick: () => { S.filter = f[0]; render(true); }}, f[1])));
  return [seg, h('div', {class: 'row'}, chips, syncBtn('/api/comments/sync')),
    S.filter === 'open' && d.items.length > 1 ? h('button', {class: 'btn sm', onclick: async e => { const b = e.currentTarget; if (await ask('همهٔ کامنت‌های منتظر «رسیدگی‌شده» علامت بخورند؟ (در اینستاگرام چیزی تغییر نمی‌کند.)', 'بله')) run(b, async () => { await POST('/api/comments/dismiss_all'); await refresh(); render(false); }); }}, icon('check'), 'همه را رسیدگی‌شده علامت بزن') : null,
    d.items.length ? d.items.map(t => threadCard(t)) : empty('chat', S.filter === 'open' ? 'کامنتی منتظر پاسخ نیست ✓' : 'چیزی برای نمایش نیست.')];
};

/* ───── numbers ───── */
function spark(v) {
  const lo = Math.min(...v), hi = Math.max(...v), w = 300, ht = 70, s = svg('svg'), p = svg('polyline');
  s.setAttribute('viewBox', '0 0 ' + w + ' ' + ht); s.setAttribute('class', 'spark'); s.setAttribute('preserveAspectRatio', 'none');
  p.setAttribute('points', v.map((y, i) => (i * w / (v.length - 1)).toFixed(1) + ',' + (ht - 6 - (hi === lo ? 0.5 : (y - lo) / (hi - lo)) * (ht - 12)).toFixed(1)).join(' '));
  s.appendChild(p);
  return s;
}
function bar(frac) { const i = h('i'); i.style.width = Math.max(2, Math.round(frac * 100)) + '%'; return h('div', {class: 'bar'}, i); }
const AUD = {gender: 'جنسیت', age: 'سن', city: 'شهر', country: 'کشور'}, GENDER = {F: 'زن', M: 'مرد', U: 'نامشخص'};
const region = (() => { try { const d = new Intl.DisplayNames(['fa'], {type: 'region'}); return c => { try { return d.of(c) || c; } catch (e) { return c; } }; } catch (e) { return c => c; } })();
VIEWS.stats = async () => {
  const d = await GET('/api/insights?days=' + S.days + (S.refresh ? '&refresh=1' : ''));
  S.refresh = false;
  const f = d.followers, sign = n => (n >= 0 ? 'up' : 'down');
  const kpi = m => h('div', {class: 'kpi'}, h('div', {class: 'row'}, h('b', null, fa(m.value)), m.change == null ? null : h('small', {class: sign(m.change)}, (m.change >= 0 ? '▲ ' : '▼ ') + fa(Math.abs(m.change)) + '٪')), h('div', {class: 'muted sm'}, m.label));
  const aud = h('div', {class: 'col'});
  const audBtn = h('button', {class: 'btn sm', onclick: () => run(audBtn, async () => {
    const r = await GET('/api/insights/audience');
    audBtn.remove();
    if (r.error) return fill(aud, h('div', {class: 'muted sm'}, r.error));
    fill(aud, Object.keys(AUD).filter(k => (r.groups[k] || []).length).map(k => {
      const rows = r.groups[k].slice(0, 5), total = r.groups[k].reduce((a, x) => a + x.value, 0) || 1;
      return h('div', {class: 'col'}, h('b', {class: 'sm'}, AUD[k]), rows.map(x => h('div', null, h('div', {class: 'row sm'}, h('span', {class: 'grow'}, k === 'gender' ? (GENDER[x.name] || x.name) : k === 'country' ? region(x.name) : x.name), h('span', {class: 'muted'}, fa(Math.round(x.value * 100 / total)) + '٪')), bar(x.value / total))));
    }));
  })}, 'نمایش سن، جنسیت و شهر');
  return [h('div', {class: 'row'}, h('div', {class: 'grow'}, segment([[7, '۷ روز اخیر'], [28, '۲۸ روز اخیر']], S.days, v => { S.days = v; render(true); })),
      h('button', {class: 'iconbtn', 'aria-label': 'تازه‌سازی آمار', onclick: () => { S.refresh = true; render(true); }}, icon('refresh'))),
    d.error ? h('div', {class: 'card bad sm'}, d.error) : null,
    d.metrics.length ? [h('div', {class: 'kpis'}, d.metrics.map(kpi)), h('p', {class: 'muted sm'}, 'درصدها نسبت به ' + fa(d.days) + ' روز قبل از آن است. آمار اینستاگرام گاهی تا ۴۸ ساعت دیرتر کامل می‌شود.')] : null,
    h('div', {class: 'card col'}, h('div', {class: 'row'}, h('b', {class: 'grow'}, 'دنبال‌کننده‌ها'), f.delta == null ? null : h('small', {class: sign(f.delta)}, (f.delta >= 0 ? '+' : '−') + fa(Math.abs(f.delta))), h('b', null, fa(f.now))),
      f.series.length > 1 ? spark(f.series.map(x => x.followers)) : h('div', {class: 'muted sm'}, 'ایجنت هر روز تعداد دنبال‌کننده‌ها را یادداشت می‌کند؛ نمودار رشد از فردا شکل می‌گیرد.')),
    h('div', {class: 'card col'}, h('b', null, 'بهترین ساعت‌های انتشار'), h('div', {class: 'chips'}, d.best_hours.map(x => h('span', {class: 'pill info'}, fa(x) + ':۰۰'))),
      h('div', {class: 'muted sm'}, 'بر اساس لایک و کامنت پست‌های قبلی خودت (اگر پست کم باشد، ساعت‌های پیش‌فرض).')),
    d.top.length ? h('div', {class: 'card col'}, h('b', null, 'بهترین پست‌های این بازه'), d.top.map(m => h('button', {class: 'row tap', onclick: () => mediaSheet(m.id)}, thumb(m.thumb, 'image', 'thumb s'),
      h('div', {class: 'grow clamp sm'}, m.caption || '—'), h('small', {class: 'muted row'}, icon('heart'), fa(m.likes), icon('chat'), fa(m.comments))))) : null,
    h('div', {class: 'card col'}, h('b', null, 'مخاطبان'), aud, audBtn)];
};

/* ───── agent tab: switches, rules, settings ───── */
function ruleSheet(r) {
  const s = sheet(r.id ? 'ویرایش قانون' : 'قانون تازه'), dm = r.scope === 'dm';
  const name = h('input', {class: 'in', value: r.name, placeholder: 'مثلاً: قیمت', 'aria-label': 'نام قانون'}), keys = h('textarea', {class: 'in', rows: 2, placeholder: 'قیمت، چنده، هزینه', 'aria-label': 'کلمه‌ها', value: r.keywords.join('، ')});
  const mode = h('select', {class: 'in', 'aria-label': 'شرط'}, [['any', 'اگر یکی از این کلمه‌ها را داشت'], ['all', 'اگر همهٔ این کلمه‌ها را داشت'], ['exact', 'اگر دقیقاً همین بود'], ['every', dm ? 'برای هر پیامی (بدون کلمه)' : 'برای هر کامنتی (بدون کلمه)']].map(m => h('option', {value: m[0]}, m[1])));
  mode.value = r.mode;
  const replies = h('textarea', {class: 'in', rows: 4, 'aria-label': 'پاسخ‌ها', placeholder: 'سلام {username} 🌹 …', value: r.replies.join('\n')});
  const priv = h('textarea', {class: 'in', rows: 2, 'aria-label': 'پیام خصوصی', placeholder: 'اختیاری', value: r.private || ''});
  let hide = !!r.hide, enabled = r.enabled !== false;
  add(s.body, field('نام قانون', name), field('شرط', mode), field('کلمه‌های کلیدی', keys, 'با ویرگول از هم جدا کن. «ي/ی»، نیم‌فاصله و بزرگی حروف فرقی نمی‌کند.'),
    field(dm ? 'متن پاسخ' : 'پاسخ زیر کامنت', replies, 'هر خط یک پاسخ جداست و ایجنت هر بار یکی را تصادفی می‌فرستد. {username} جای نام کاربر می‌نشیند.'),
    dm ? null : field('پیام خصوصی به نویسندهٔ کامنت', priv, 'اختیاری. برای هر کامنت فقط یک بار ممکن است.'),
    dm ? null : h('div', {class: 'row'}, h('span', {class: 'grow'}, 'کامنت را مخفی هم بکن'), toggle(hide, async v => { hide = v; }, 'مخفی‌کردن')),
    h('div', {class: 'row'}, h('span', {class: 'grow'}, 'این قانون فعال باشد'), toggle(enabled, async v => { enabled = v; }, 'فعال')));
  const save = h('button', {class: 'btn pri', onclick: () => run(save, async () => {
    const body = {scope: r.scope, name: name.value, mode: mode.value, keywords: keys.value, replies: replies.value.split('\n'), private: priv.value, hide, enabled};
    await POST(r.id ? '/api/rules/' + r.id : '/api/rules', body);
    toast('قانون ذخیره شد'); s.close(); render(false);
  })}, 'ذخیره');
  s.setFoot(r.id ? h('button', {class: 'btn danger', onclick: async e => { const b = e.currentTarget; if (await ask('این قانون حذف شود؟', 'حذف', true)) run(b, async () => { await DEL('/api/rules/' + r.id); s.close(); render(false); }); }}, icon('trash'), 'حذف') : null, save);
}
VIEWS.agent = async () => {
  if (!S.st.connected) return [
    h('div', {class: 'card col'}, h('b', null, 'بدون اتصال به پیج'), h('div', {class: 'muted sm'}, 'ایجنت عکس، ویدیو و کپشن را می‌سازد و سر وقت یادآوری می‌کند؛ انتشار با خودت است. خواندن کامنت و دایرکت، پاسخ خودکار و آمار به اتصال پیج (توکن متا) نیاز دارد.'),
      h('div', {class: 'row wrap'}, h('button', {class: 'btn sm', onclick: tokenSheet}, icon('link'), 'اتصال با توکن متا'))),
    h('div', {class: 'row'}, h('button', {class: 'btn grow', onclick: assistantSheet}, icon('spark'), 'دستیار'), h('button', {class: 'btn grow', id: 'open-settings', onclick: settingsSheet}, icon('settings'), 'تنظیمات'),
      h('button', {class: 'btn grow', onclick: helpSheet}, icon('help'), 'راهنما')),
    h('p', {class: 'muted sm center'}, 'ایجنت اینستاگرام — نسخهٔ __VERSION__')];
  const [set, rules] = await Promise.all([GET('/api/settings'), GET('/api/rules')]), st = S.st, au = set.auto, lim = set.limits;
  const sw = (key, title, desc) => h('div', {class: 'row line'}, h('div', {class: 'grow'}, h('b', null, title), h('div', {class: 'muted sm'}, desc)), toggle(au[key], v => saveSettings({auto: {[key]: v}}, false), title));
  const ruleCard = r => h('button', {class: 'card row' + (r.enabled ? '' : ' off'), 'data-rule': r.id, onclick: () => ruleSheet(r)}, h('div', {class: 'grow'}, h('b', null, r.name),
      h('div', {class: 'muted sm clamp'}, r.mode === 'every' ? 'برای همه' : 'اگر شامل: ' + r.keywords.join('، ')),
      h('div', {class: 'sm up clamp'}, '← ' + [r.replies.length ? 'پاسخ' : '', r.private ? 'پیام خصوصی' : '', r.hide ? 'مخفی‌کردن' : ''].filter(Boolean).join(' + '))),
    h('span', {class: 'pill'}, r.enabled ? fa(r.hits) + ' بار' : 'خاموش'));
  const group = (scope, title) => h('div', {class: 'col'}, h('div', {class: 'row'}, h('h3', {class: 'grow'}, title),
      h('button', {class: 'btn sm', 'data-newrule': scope, onclick: () => ruleSheet({scope, name: '', keywords: [], mode: 'any', replies: [], private: '', hide: false, enabled: true})}, icon('plus'), 'قانون تازه')),
    rules.items.filter(r => r.scope === scope).map(ruleCard));
  const num = (key, label) => { const el = h('input', {class: 'in ltr', type: 'number', inputmode: 'numeric', value: lim[key], 'aria-label': label}); return [field(label, el), el]; };
  const perHour = num('per_hour', 'حداکثر کار خودکار در هر ساعت'), cool = num('cooldown_min', 'فاصلهٔ دو پاسخ خودکار به یک نفر (دقیقه)'), daily = num('daily_posts', 'حداکثر انتشار در ۲۴ ساعت');
  const qf = h('input', {class: 'in ltr', type: 'time', value: lim.quiet_from, 'aria-label': 'شروع سکوت'}), qt = h('input', {class: 'in ltr', type: 'time', value: lim.quiet_to, 'aria-label': 'پایان سکوت'});
  const exp = st.account.token_expires ? ' — اعتبار توکن تا ' + new Date(st.account.token_expires * 1000).toLocaleDateString('fa-IR') : '';
  return [
    h('div', {class: 'card'}, h('b', null, 'کارهای خودکار'),
      sw('comment_reply', 'پاسخ خودکار به کامنت‌ها', 'طبق قانون‌های پایین؛ فقط برای کامنت‌هایی که از این لحظه به بعد می‌آیند.'),
      sw('spam_hide', 'مخفی‌کردن خودکار اسپم', 'کامنت‌های تبلیغاتی و لینک‌دار مخفی می‌شوند (حذف نمی‌شوند؛ می‌توانی برگردانی).'),
      sw('dm_reply', 'پاسخ خودکار به دایرکت', 'طبق قانون‌های دایرکت و فقط در پنجرهٔ ۲۴ ساعته.'),
      sw('ai_suggest', 'پیشنهاد پاسخ با هوش مصنوعی', 'برای کامنت‌هایی که قانونی ندارند پاسخ پیشنهادی می‌نویسد؛ فرستادنش با تأیید توست.'),
      sw('ai_send', 'فرستادن خودکار پاسخ هوش مصنوعی', 'پیشنهاد هوش مصنوعی بدون تأیید تو فرستاده می‌شود. با احتیاط روشن کن.'),
      sw('daily_report', 'گزارش روزانه', 'هر شب ساعت ۲۱ خلاصهٔ کار پیج در اعلان‌ها (و تلگرام، اگر وصل باشد).')),
    group('comment', 'قانون‌های کامنت'), group('dm', 'قانون‌های دایرکت'),
    h('details', {class: 'box'}, h('summary', null, icon('lock'), 'ترمزهای ایمنی'), h('div', {class: 'col'},
      h('p', {class: 'muted sm'}, 'برای اینکه پیج شبیه ربات اسپم نشود، ایجنت این سقف‌ها را رعایت می‌کند.'), perHour[0], cool[0], daily[0],
      h('label', {class: 'f'}, 'ساعت سکوت (در این بازه پاسخ خودکار فرستاده نمی‌شود)'), h('div', {class: 'row'}, 'از', qf, 'تا', qt),
      h('button', {class: 'btn', onclick: e => run(e.currentTarget, () => saveSettings({limits: {per_hour: Number(perHour[1].value), cooldown_min: Number(cool[1].value), daily_posts: Number(daily[1].value), quiet_from: qf.value, quiet_to: qt.value}}))}, 'ذخیرهٔ ترمزها'))),
    h('div', {class: 'row'}, h('button', {class: 'btn grow', onclick: assistantSheet}, icon('spark'), 'دستیار'), h('button', {class: 'btn grow', id: 'open-settings', onclick: settingsSheet}, icon('settings'), 'تنظیمات'),
      h('button', {class: 'btn grow', onclick: helpSheet}, icon('help'), 'راهنما')),
    h('div', {class: 'card col'}, h('b', null, 'اتصال پیج'), h('div', {class: 'muted sm'}, h('span', {class: 'ltr'}, '@' + st.account.username), exp),
      h('div', {class: 'row wrap'}, h('button', {class: 'btn sm', onclick: tokenSheet}, 'توکن تازه'),
        st.account.login === 'ig' ? h('button', {class: 'btn sm', onclick: e => run(e.currentTarget, async () => { await POST('/api/token/refresh'); toast('توکن تمدید شد ✓'); await refresh(); render(false); })}, 'تمدید توکن') : null,
        h('button', {class: 'btn sm danger', onclick: async () => { if (await ask('اتصال پیج برداشته شود؟ تا اتصال دوباره هیچ پستی منتشر نمی‌شود.', 'قطع اتصال', true)) run(null, async () => { putStatus(await POST('/api/disconnect')); render(true); }); }}, 'قطع اتصال'))),
    h('p', {class: 'muted sm center'}, 'ایجنت اینستاگرام — نسخهٔ __VERSION__')];
};
async function settingsSheet() {
  const s = sheet('تنظیمات');
  let set;
  try { set = await GET('/api/settings'); } catch (e) { return fill(s.body, h('div', {class: 'card bad'}, e.message)); }
  const m = S.st.media, inp = (v, a) => h('input', Object.assign({class: 'in', value: v == null ? '' : v}, a || {}));
  const sel = (v, opts) => { const el = h('select', {class: 'in'}, opts.map(o => h('option', {value: o[0]}, o[1]))); el.value = v; return el; };
  const box = (key, ic, title, kids, collect, extra) => h('details', {class: 'box', 'data-sec': key}, h('summary', null, icon(ic), title), h('div', {class: 'col'}, kids,
    h('div', {class: 'row'}, h('button', {class: 'btn pri grow', onclick: e => run(e.currentTarget, async () => { await saveSettings(collect()); })}, 'ذخیره'), extra)));
  const about = h('textarea', {class: 'in', rows: 3, value: set.brand.about, placeholder: 'مثلاً: کافهٔ کوچک محلی در شیراز با قهوهٔ تازه و کیک خانگی', 'aria-label': 'دربارهٔ پیج'}), tone = inp(set.brand.tone), tags = inp(set.brand.hashtags, {placeholder: '#کافه #قهوه'});
  const aiMode = sel(set.ai.mode, [['free', 'رایگان (سرویس عمومی Pollinations)'], ['custom', 'سرویس خودم (سازگار با OpenAI)'], ['off', 'خاموش (فقط الگوهای آماده)']]);
  const aiUrl = inp(set.ai.url, {class: 'in ltr', placeholder: 'https://api.openai.com/v1'}), aiModel = inp(set.ai.model, {class: 'in ltr', placeholder: 'gpt-4o-mini'}), aiKey = inp('', {class: 'in ltr', type: 'password', autocomplete: 'off', placeholder: set.ai.key_set ? '•••••• (ذخیره شده)' : 'کلید API'});
  const method = sel(set.media.method, [['auto', 'خودکار (هر کدام آماده بود)'], ['tunnel', 'فقط تونل cloudflared'], ['temp', 'فقط میزبان موقت'], ['public', 'فقط نشانی عمومی خودم']]), pub = inp(set.media.public_url, {class: 'in ltr', placeholder: 'https://my-agent.example.com'});
  let tempOk = set.media.temp_ok;
  const tgToken = inp('', {class: 'in ltr', type: 'password', autocomplete: 'off', placeholder: set.telegram.token_set ? '•••••• (ذخیره شده)' : '123456:ABC…'}), tgChat = inp(set.telegram.chat_id, {class: 'in ltr', placeholder: '123456789'});
  const proxy = inp(set.network.proxy, {class: 'in ltr', placeholder: 'http://127.0.0.1:10809'});
  const handle = inp(set.brand.handle, {class: 'in ltr', placeholder: 'my.page', 'aria-label': 'نام کاربری پیج'});
  const picMode = sel(set.studio.image, [['auto', 'خودکار (رایگان‌ها به نوبت)'], ['pollinations', 'فقط Pollinations'], ['horde', 'فقط AI Horde'], ['custom', 'فقط سرویس خودم'], ['off', 'خاموش (طرح‌های خود برنامه)']]);
  const pollen = inp('', {class: 'in ltr', type: 'password', autocomplete: 'off', 'aria-label': 'کلید Pollinations', placeholder: set.studio.pollen_set ? '•••••• (ذخیره شده)' : 'sk_…'});
  const picUrl = inp(set.studio.url, {class: 'in ltr', placeholder: 'https://…/v1'}), picModel = inp(set.studio.model, {class: 'in ltr', placeholder: 'gpt-image-1'});
  const picKey = inp('', {class: 'in ltr', type: 'password', autocomplete: 'off', placeholder: set.studio.key_set ? '•••••• (ذخیره شده)' : 'کلید API'});
  const state = (on, text) => h('div', {class: 'row sm'}, h('i', {class: 'dot ' + (on ? '' : 'off')}), h('span', {class: 'grow'}, text));
  add(s.body,
    box('brand', 'home', 'معرفی پیج (برای کپشن‌ها و پاسخ‌ها)', [field('پیج دربارهٔ چیست؟', about), field('لحن نوشتن', tone), field('هشتگ‌های همیشگی پیج', tags),
        field('نام کاربری پیج (اختیاری)', handle, 'بدون @. زیر عکس‌ها و در پایان ویدیوهایی که ایجنت می‌سازد نوشته می‌شود.')],
      () => ({brand: {about: about.value, tone: tone.value, hashtags: tags.value, handle: handle.value}})),
    box('studio', 'image', 'ساخت عکس و ویدیو', [h('p', {class: 'muted sm'}, 'ایجنت تصویر را از سرویس‌های هوش مصنوعی می‌گیرد و عکس نهایی و ویدیو را روی همین دستگاه می‌سازد. بدون ثبت‌نام از دو سرویس رایگان استفاده می‌کند: Pollinations (هر ۴۵ ثانیه یک تصویر، با نشان کوچک خودش در گوشه) و AI Horde (تصویر کوچک‌تر، گاهی با صف). اگر هیچ‌کدام جواب ندهند، طرح خود برنامه کشیده می‌شود.'),
        field('سرویس تصویر', picMode),
        field('کلید Pollinations (اختیاری)', pollen, 'با کلید خودت (از enter.pollinations.ai) تصویرها بزرگ‌تر، بدون انتظار و بدون نشان می‌شوند و متن‌ها را هم مدل بهتری می‌نویسد.'),
        h('details', {class: 'box'}, h('summary', null, icon('link'), 'سرویس تصویر خودم (سازگار با OpenAI)'), h('div', {class: 'col'}, field('نشانی', picUrl), field('نام مدل', picModel), field('کلید', picKey)))],
      () => ({studio: {image: picMode.value, pollen: pollen.value, url: picUrl.value, model: picModel.value, key: picKey.value}}),
      set.studio.pollen_set ? h('button', {class: 'btn danger', onclick: e => run(e.currentTarget, async () => { await saveSettings({studio: {pollen_clear: true}}, 'کلید برداشته شد'); pollen.placeholder = 'sk_…'; e.target.remove(); })}, 'حذف کلید') : null),
    box('ai', 'spark', 'هوش مصنوعی (متن)', [field('سرویس', aiMode, 'در حالت رایگان، متن کامنت/موضوع برای نوشتن پاسخ به یک سرویس عمومی فرستاده می‌شود و هر ۴۵ ثانیه یک پاسخ می‌دهد (با کلید Pollinations در بخش «ساخت عکس و ویدیو» این محدودیت نیست).'), field('نشانی سرویس خودم', aiUrl), field('نام مدل', aiModel), field('کلید', aiKey)],
      () => ({ai: {mode: aiMode.value, url: aiUrl.value, model: aiModel.value, key: aiKey.value}})),
    box('media', 'upload', 'انتشار از گالری (لینک عمومی)', [h('p', {class: 'muted sm'}, 'اینستاگرام فایل را خودش از یک نشانی اینترنتی برمی‌دارد. برای عکس و ویدیویی که از گالری انتخاب می‌کنی، ایجنت باید چند دقیقه یک لینک عمومی برایش بسازد:'),
        state(m.tunnel, m.tunnel ? 'تونل cloudflared: آماده است (فایل از خود گوشی و فقط در لحظهٔ انتشار در دسترس قرار می‌گیرد؛ پنل هیچ‌وقت بیرون نمی‌آید).' : 'تونل cloudflared: نصب نیست. در ترموکس یک بار بزن: pkg install cloudflared و ایجنت را دوباره اجرا کن.'),
        h('div', {class: 'row sm'}, h('i', {class: 'dot ' + (tempOk ? '' : 'off')}), h('span', {class: 'grow'}, 'میزبان موقت: فایل یک ساعت روی سرویس عمومی litterbox.catbox.moe گذاشته می‌شود (بدون نصب چیزی).'), toggle(tempOk, async v => { tempOk = v; }, 'میزبان موقت')),
        state(m.public, 'نشانی عمومی خودم: اگر ایجنت روی سرور یا پشت دامنهٔ خودت است.'), field('روش', method), field('نشانی عمومی (اختیاری)', pub)],
      () => ({media: {method: method.value, public_url: pub.value, temp_ok: tempOk}})),
    box('telegram', 'send', 'اعلان در تلگرام', [h('p', {class: 'muted sm'}, 'با @BotFather یک ربات بساز، توکنش را اینجا بگذار و شناسهٔ عددی خودت را (مثلاً از @userinfobot) بنویس. هشدارها و گزارش روزانه برایت فرستاده می‌شود؛ در انتشار دستی، سر وقتِ هر یادآوری فایل و کپشن هم به همین گفتگو می‌آید.'), field('توکن ربات', tgToken), field('شناسهٔ چت', tgChat)],
      () => ({telegram: {token: tgToken.value, chat_id: tgChat.value}}), h('button', {class: 'btn', onclick: e => run(e.currentTarget, async () => { await POST('/api/telegram/test'); toast('پیام آزمایشی فرستاده شد ✓'); })}, 'آزمایش')),
    box('network', 'link', 'پروکسی (فیلترشکن)', [h('p', {class: 'muted sm'}, 'اگر اینستاگرام فقط با فیلترشکن باز می‌شود، نشانی پروکسی HTTP آن را بنویس. خالی یعنی اتصال مستقیم.'), field('پروکسی HTTP', proxy)], () => ({network: {proxy: proxy.value}})));
}
function assistantSheet() {
  const s = sheet('دستیار'), box = h('div', {class: 'chat'}), ta = h('textarea', {class: 'in', rows: 1, placeholder: 'بپرس…', 'aria-label': 'پیام به دستیار'}), hist = [];
  const say = (text, me) => { box.appendChild(h('div', {class: 'bubble' + (me ? ' me' : '')}, text)); s.body.scrollTop = s.body.scrollHeight; };
  const send = h('button', {class: 'btn pri', 'aria-label': 'فرستادن', onclick: () => ask_(ta.value)}, icon('send'));
  const ask_ = text => run(send, async () => {
    text = (text || '').trim(); if (!text) return;
    ta.value = ''; say(text, true); hist.push({role: 'user', content: text});
    const wait = h('div', {class: 'bubble muted'}, 'در حال فکر کردن…'); box.appendChild(wait);
    try { const r = await POST('/api/chat', {messages: hist}); hist.push({role: 'assistant', content: r.text}); wait.remove(); say(r.text); }
    catch (e) { wait.remove(); hist.pop(); throw e; }
  });
  add(s.body, h('p', {class: 'muted sm'}, 'دربارهٔ پیج، ایدهٔ پست، کپشن یا پاسخ به مشتری بپرس. دستیار وضعیت فعلی پیج را می‌داند.'),
    h('div', {class: 'chips'}, ['وضعیت پیج چطور است؟', 'برای این هفته چه پست‌هایی بگذارم؟', 'یک کپشن برای معرفی محصول جدید بنویس'].map(q => h('button', {class: 'chip', onclick: () => ask_(q)}, q))), box);
  s.setFoot(ta, send);
}
function helpSheet() {
  const s = sheet('راهنما'), sec = (title, ...lines) => h('div', {class: 'card col'}, h('b', null, title), lines.map(l => h('div', {class: 'sm'}, l)));
  add(s.body,
    sec('ساختن پست از روی یک ایده', 'در «بساز» ایده‌ات را بنویس: ایجنت کپشن و هشتگ می‌نویسد، تصویر را از سرویس هوش مصنوعی می‌گیرد و عکس نهایی یا ریل را روی همین دستگاه می‌سازد.',
      'سرویس‌های رایگان تصویر کند و کوچک‌اند و گاهی جواب نمی‌دهند؛ آن وقت ایجنت طرح خودش را می‌کشد. با کلید Pollinations (در تنظیمات) نتیجه بهتر و سریع‌تر است.',
      'ریل از چند تصویر با حرکت و نوشته ساخته می‌شود و صدا ندارد؛ آهنگ را موقع انتشار در اینستاگرام اضافه کن. فیلم‌سازی کامل با هوش مصنوعی فقط در سرویس‌های پولی هست.'),
    sec('انتشار با خودت (بدون اتصال پیج)', 'پست آماده را باز کن: «ارسال به اینستاگرام» فایل را به اپ می‌دهد و کپشن را کپی می‌کند؛ آنجا بچسبانش. اگر این دکمه نبود، «ذخیره در گوشی» و «کپی کپشن» را بزن.',
      'برای هر پست می‌توانی یادآوری بگذاری؛ سر وقت در پنل (و در تلگرام، اگر وصلش کرده باشی) خبر می‌دهد. بعد از انتشار «منتشر کردم» را بزن.'),
    sec('ایجنت چه کارهایی می‌کند؟', 'با اتصال پیج: پست، پست چندتایی، ریل و استوری را همین حالا یا در زمان دلخواه منتشر می‌کند.', 'کامنت‌ها و دایرکت‌ها را در یک صندوق نشان می‌دهد و می‌توانی از همین‌جا جواب بدهی، مخفی یا حذف کنی.',
      'طبق قانون‌هایی که می‌نویسی خودش جواب می‌دهد و کامنت‌های تبلیغاتی را مخفی می‌کند.', 'آمار پیج و بهترین ساعت انتشار را نشان می‌دهد و در نوشتن کپشن و هشتگ کمک می‌کند.'),
    sec('چه چیزهایی شدنی نیست؟', 'اینستاگرام از راه رسمی اجازهٔ فالو/آنفالو، دیدن فهرست دنبال‌کننده‌ها، ویرایش کپشن یا بیو و گذاشتن استیکر و لینک روی استوری را نمی‌دهد؛ ایجنت هم سراغ راه‌های غیررسمی (که پیج را در خطر بسته‌شدن می‌گذارد) نمی‌رود.',
      'لایک‌کردن و حذف پست هم در این ایجنت نیست (متا برای این دو مجوز جداگانه می‌خواهد)؛ این دو را از خود اپ اینستاگرام انجام بده.',
      'دایرکت با عموم مردم فقط وقتی کار می‌کند که برنامه‌ات در متا «Advanced Access» گرفته باشد؛ تا آن موقع فقط با حساب‌هایی که در برنامه نقش دارند.'),
    sec('ایجنت باید روشن بماند', 'زمان‌بندی و پاسخ خودکار فقط تا وقتی کار می‌کند که برنامه در ترموکس باز باشد. در ترموکس بزن: termux-wake-lock و بهینه‌سازی باتری را برای ترموکس خاموش کن.',
      'اگر ایجنت در زمان یک پست خاموش باشد و بیش از ۶ ساعت بگذرد، آن پست «جامانده» می‌شود و خودکار منتشر نمی‌شود.'),
    sec('امنیت', 'رمز پیج هیچ‌وقت خواسته نمی‌شود. توکن فقط روی همین دستگاه می‌ماند و هر وقت بخواهی می‌توانی از تنظیمات اینستاگرام دسترسی برنامه را برداری.', 'پنل فقط روی همین دستگاه باز است و با کد ورود قفل می‌شود.'));
}

/* ───── start ───── */
fill($('#fab'), icon('plus'));
$('#fab').addEventListener('click', () => composer());
(async () => {
  try { await loadStatus(); } catch (e) { if (e.status !== 401) S.st = null; }
  render(true);
  setInterval(poll, 4000);
  D.addEventListener('visibilitychange', () => { if (!D.hidden) poll(); });
})();
</script>
</body>
</html>
'''


# ───────────────────────────── the typeface ─────────────────────────────
# Vazirmatn 33.0.3, the Persian typeface of the panel and of the pictures and reels it draws: the variable-weight
# (100-900) Persian/Arabic subset as WOFF2, embedded unchanged.
# Copyright 2015 The Vazirmatn Project Authors (https://github.com/rastikerdar/vazirmatn).
# Licensed under the SIL Open Font License, Version 1.1 (see OFL-Vazirmatn.txt next to this file, or
# https://openfontlicense.org); the font file itself also carries this notice.
FONT_WOFF2 = (
    "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"
)


if __name__ == "__main__":
    sys.exit(main())
