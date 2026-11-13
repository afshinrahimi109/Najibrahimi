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
API_VERSIONS = ["v27.0", "v26.0", "v25.0", ""]
KINDS = ("image", "carousel", "reel", "story")
KIND_FA = {"image": "پست", "carousel": "پست چندتایی", "reel": "ریل", "story": "استوری"}
IMAGE_MAX = 8 * 1024 * 1024
VIDEO_MAX = 300 * 1024 * 1024
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

    def close(self):
        with self.lock:
            try:
                self.conn.close()
            except sqlite3.Error:
                pass


DEFAULT_SETTINGS = {
    "autopilot": True,
    "auto": {"comment_reply": False, "spam_hide": False, "dm_reply": False, "ai_suggest": False, "ai_send": False,
             "daily_report": False},
    "since": {"comment_reply": 0.0, "spam_hide": 0.0, "dm_reply": 0.0, "ai_suggest": 0.0, "ai_send": 0.0,
              "daily_report": 0.0},
    "limits": {"per_hour": 30, "cooldown_min": 30, "daily_posts": 25, "quiet_from": "", "quiet_to": ""},
    "brand": {"about": "", "tone": "صمیمی و محترمانه", "hashtags": ""},
    "ai": {"mode": "free", "url": "", "model": "", "key": ""},
    "media": {"method": "auto", "public_url": "", "temp_ok": False},
    "network": {"proxy": ""},
    "telegram": {"token": "", "chat_id": ""},
}
SECRET_FIELDS = (("ai", "key"), ("telegram", "token"))


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
        for section, key, label in (("ai", "url", "نشانی سرویس هوش مصنوعی"), ("media", "public_url", "نشانی عمومی")):
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
        if s == 2207008 or c == 24:
            return "expired"
        if s == 2207042 or c == 9:
            return "quota"
        if s in (2207050, 2207051) or c in (25, 368):
            return "blocked"
        if s == 2207052 or c == 9004:
            return "fetch"
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
COMMENT_FIELDS = "id,text,timestamp,username,from,hidden,parent_id,like_count"
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
    def _fields_call(self, path, field_sets, extra):
        last = None
        for fields in field_sets:
            try:
                params = dict(extra)
                params["fields"] = fields
                return self.call("GET", path, params)
            except GraphError as e:
                last = e
                if e.kind != "param":
                    raise
        raise last

    def media(self, limit=30):
        return self._fields_call("%s/media" % self.me(), MEDIA_FIELDS, {"limit": limit}).get("data") or []

    def stories(self):
        return self._fields_call("%s/stories" % self.me(), MEDIA_FIELDS[1:], {}).get("data") or []

    def media_info(self, media_id):
        return self._fields_call(media_id, MEDIA_FIELDS, {})

    def create_container(self, params):
        return str(self.call("POST", "%s/media" % self.me(), params, timeout=90)["id"])

    def container_status(self, container_id):
        d = self.call("GET", container_id, {"fields": "status_code,status"})
        return str(d.get("status_code") or "").upper(), str(d.get("status") or "")

    def publish(self, container_id):
        return str(self.call("POST", "%s/media_publish" % self.me(), {"creation_id": container_id}, timeout=90)["id"])

    def quota(self):
        d = self.call("GET", "%s/content_publishing_limit" % self.me(), {"fields": "quota_usage,config"})
        row = (d.get("data") or [{}])[0]
        return int(row.get("quota_usage") or 0), int((row.get("config") or {}).get("quota_total") or 50)

    # ── comments ──
    def comments(self, media_id, limit=50):
        fields = "%s,replies.limit(25){%s}" % (COMMENT_FIELDS, COMMENT_FIELDS)
        d = self.call("GET", "%s/comments" % media_id, {"fields": fields, "limit": limit})
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
        d = self.call("GET", "%s/conversations" % self.inbox_owner(),
                      {"platform": "instagram", "fields": "id,updated_time,participants", "limit": limit})
        return d.get("data") or []

    def messages(self, conv_id, limit=20):
        d = self.call("GET", conv_id, {"fields": "messages.limit(%d){id,created_time,from,to,message,attachments}" % limit})
        return (d.get("messages") or {}).get("data") or []

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
    return None


def image_size(path):
    try:
        with open(path, "rb") as fh:
            head = fh.read(26)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", head[16:24])
                return int(w), int(h)
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
            return shlex.split(self.cfg.tunnel_cmd.replace("{port}", str(port)))
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
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
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
    pass


class AI:
    FREE_URL = "https://text.pollinations.ai/openai"

    def __init__(self, cfg, settings, graph, ig):
        self.cfg, self.settings, self.graph, self.ig = cfg, settings, graph, ig

    def endpoint(self):
        s = self.settings.all()["ai"]
        if s["mode"] == "off":
            return None
        if s["mode"] == "custom" and s["url"]:
            return s["url"], s["key"], s["model"] or "gpt-4o-mini"
        if self.cfg.ai_url:
            return self.cfg.ai_url, "", s["model"] or "openai"
        if self.cfg.sim:
            return None                                # demo and tests never call out
        return self.FREE_URL, "", "openai"

    def mode(self):
        ep = self.endpoint()
        return "off" if not ep else ("custom" if ep[0] != self.FREE_URL else "free")

    def ask(self, system, user, history=None, max_tokens=700):
        ep = self.endpoint()
        if not ep:
            raise AIDown("off")
        url, key, model = ep
        if not url.rstrip("/").endswith(("/chat/completions", "/openai")):
            url = url.rstrip("/") + "/chat/completions"
        messages = [{"role": "system", "content": system}] + list(history or []) + [{"role": "user", "content": user}]
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        payload = jdump({"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.8})
        try:
            status, _, body = self.graph.http("POST", url, payload.encode("utf-8"), headers, timeout=45)
        except GraphError as e:
            raise AIDown(str(e))
        data = jload(body.decode("utf-8", "replace"), None)
        try:
            text = data["choices"][0]["message"]["content"]
        except (TypeError, KeyError, IndexError):
            raise AIDown("HTTP %s" % status)
        text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
        if not text:
            raise AIDown("empty answer")
        return text

    def persona(self):
        b, a = self.settings.all()["brand"], self.ig.acct
        return ("تو دستیار مدیریت یک پیج اینستاگرام هستی. نام پیج: @%s (%s). دربارهٔ پیج: %s. لحن نوشتن: %s. "
                "فارسی روان و طبیعی بنویس؛ کوتاه و بدون مقدمه و توضیح اضافه. چیزی را که نمی‌دانی از خودت نساز."
                % (a.get("username") or "page", a.get("name") or "", b["about"] or a.get("bio") or "نامشخص", b["tone"]))

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
                            "هر کپشن با ۳ تا ۶ هشتگ مرتبط تمام شود. بین کپشن‌ها فقط یک خط شامل === بگذار و هیچ "
                            "توضیح، شماره یا عنوانی ننویس." % (KIND_FA.get(kind, "پست"), topic))
            items = [re.sub(r"^\s*(کپشن\s*)?[\d۰-۹]+\s*[\.\):\-]\s*", "", p.strip()) for p in re.split(r"\n\s*={3,}\s*\n?", text)]
            items = [i for i in items if i][:5]
            if items:
                return {"items": items, "source": "ai"}
        except AIDown:
            pass
        tail = " ".join(self.offline_hashtags(topic)[:5])
        return {"source": "offline", "items": [
            "%s ✨\n\n%s" % (topic, tail),
            "%s\n\nنظر شما چیه؟ توی کامنت‌ها برامون بنویسید 👇\n\n%s" % (topic, tail),
            "یه خبر خوب: %s 🌿\nاگه دوست داشتید برای دوستاتون هم بفرستید.\n\n%s" % (topic, tail)]}

    def hashtags(self, topic):
        topic = str(topic or "").strip()[:500]
        try:
            text = self.ask(self.persona(), "برای پستی با موضوع «%s» پانزده هشتگ فارسی و انگلیسی مرتبط پیشنهاد بده. "
                                            "فقط هشتگ‌ها را با فاصله بنویس." % (topic or "معرفی پیج"), max_tokens=300)
            tags = []
            for t in re.findall(r"#[^\s#،,]+", text):
                if norm(t) not in [norm(x) for x in tags]:
                    tags.append(t)
            if len(tags) >= 3:
                return {"items": tags[:30], "source": "ai"}
        except AIDown:
            pass
        return {"items": self.offline_hashtags(topic), "source": "offline"}

    def ideas(self, count=6):
        about = self.settings.all()["brand"]["about"] or "پیج"
        try:
            text = self.ask(self.persona(), "%d ایدهٔ کوتاه و عملی برای پست یا ریل این پیج بده. هر ایده در یک خط، "
                                            "بدون شماره." % count, max_tokens=500)
            items = [re.sub(r"^\s*[\-\*•\d۰-۹\.\)]+\s*", "", ln).strip() for ln in text.splitlines()]
            items = [i for i in items if len(i) > 8][:count]
            if items:
                return {"items": items, "source": "ai"}
        except AIDown:
            pass
        base = ["پشت‌صحنهٔ یک روز کاری: از صبح تا شب در چند عکس", "معرفی پرطرفدارترین محصول یا خدمت و دلیل محبوبیتش",
                "پاسخ به سه سؤال پرتکرار مشتری‌ها در یک پست چندتایی", "قبل و بعد: نتیجهٔ یک کار واقعی را نشان بده",
                "یک نکتهٔ آموزشی کوتاه که مخاطب همین امروز به کارش بیاید", "نظر یک مشتری راضی (با اجازهٔ خودش)",
                "نظرسنجی در استوری: از مخاطب بپرس چه چیزی دوست دارد ببیند", "داستان شروع کار: %s چطور راه افتاد؟" % about]
        random.shuffle(base)
        return {"items": base[:count], "source": "offline"}

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
        except AIDown:
            return {"text": self.offline_reply(text), "source": "offline"}

    def chat(self, history, facts):
        history = [{"role": "assistant" if m.get("role") == "assistant" else "user", "content": str(m.get("content") or "")[:2000]}
                   for m in (history or []) if m.get("content")][-12:]
        if not history or history[-1]["role"] != "user":
            raise UserError("پیامی نوشته نشده است.")
        try:
            text = self.ask(self.persona() + "\nوضعیت فعلی پیج:\n" + facts, history[-1]["content"], history[:-1], 800)
            return {"text": text, "source": "ai"}
        except AIDown:
            return {"source": "offline", "text": "الان به سرویس هوش مصنوعی دسترسی ندارم، ولی این وضعیت فعلی پیج است:\n\n"
                    + facts + "\n\nبرای ایدهٔ پست و کپشن می‌توانی از دکمه‌های «کپشن پیشنهادی» و «ایده» هم استفاده کنی."}


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
POST_COLS = ("id", "kind", "caption", "status", "scheduled_at", "error", "progress", "attempts", "next_try_at",
             "ig_media_id", "permalink", "created_at", "updated_at", "published_at")


def count_tags(caption):
    return len(re.findall(r"#[^\s#]+", caption)), len(re.findall(r"(?<![\w.])@[\w.]+", caption))


class Publisher:
    """Scheduled posts as a resumable state machine: a post is never published twice."""

    def __init__(self, agent):
        self.agent, self.db = agent, agent.db

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
        out.update(media=media, opts=jload(r["opts"], {}), manual=bool(r["manual"]))
        return out

    def get(self, pid):
        return self.view(self.raw(pid))

    def list(self, group="all"):
        where, order = {
            "queue": ("status IN ('scheduled','publishing','failed','missed')", "scheduled_at"),
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
        if not self.agent.ig.connected:
            raise UserError("اول پیج را وصل کن.")
        kinds = [self.media_kind(m) for m in media]
        n = len(media)
        if kind == "image" and not (n == 1 and kinds[0] == "image"):
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
        if tags > 30:
            raise UserError("کپشن بیش از ۳۰ هشتگ دارد.")
        if mentions > 20:
            raise UserError("کپشن بیش از ۲۰ منشن دارد.")
        for m in media:
            if not m.get("file"):
                continue
            f = self.agent.store.get(m["file"])
            if not f or not os.path.exists(self.agent.store.path(f)):
                raise UserError("یکی از فایل‌ها دیگر روی دستگاه نیست؛ دوباره انتخابش کن.")
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
        for item in (data.get("media") or [])[:20]:
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
        when = float(data.get("scheduled_at") or 0)
        state = {}
        if pid:
            old = self.raw(pid)
            if old["status"] in ("publishing", "published"):
                raise UserError("این پست دیگر قابل ویرایش نیست.")
            state = self.carry_state(jload(old["state"], {}), dirty=True)
        status, manual = "draft", 0
        if action in ("schedule", "now"):
            self.validate(kind, caption, media, opts)
            status = "scheduled"
            if action == "now":
                when, manual = now(), 1
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
        r = self.raw(pid)
        if r["status"] == "published":
            raise UserError("این پست قبلاً منتشر شده است.")
        if r["status"] == "publishing":
            raise UserError("این پست همین حالا در حال انتشار است.")
        self.validate(r["kind"], r["caption"], jload(r["media"], []), jload(r["opts"], {}))
        state = self.carry_state(jload(r["state"], {}))
        self.db.x("UPDATE posts SET status='scheduled', manual=1, scheduled_at=?, attempts=0, next_try_at=0, error='', "
                  "progress='', state=?, updated_at=? WHERE id=?", (now(), jdump(state), now(), pid))
        self.agent.wake.set()
        return self.get(pid)

    def cancel(self, pid):
        r = self.raw(pid)
        if r["status"] == "publishing":
            raise UserError("این پست در حال انتشار است و دیگر نمی‌شود جلویش را گرفت.")
        if r["status"] == "published":
            raise UserError("این پست منتشر شده است.")
        self.db.x("UPDATE posts SET status='draft', manual=0, error='', progress='', updated_at=? WHERE id=?", (now(), pid))
        return self.get(pid)

    def duplicate(self, pid):
        r = self.raw(pid)
        new = self.db.x("INSERT INTO posts (kind, caption, media, opts, status, created_at, updated_at) VALUES (?,?,?,?,'draft',?,?)",
                        (r["kind"], r["caption"], r["media"], r["opts"], now(), now()))
        return self.get(new)

    def delete(self, pid):
        r = self.raw(pid)
        if r["status"] == "publishing":
            raise UserError("این پست در حال انتشار است؛ چند لحظه صبر کن.")
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

    def tick(self):
        t = now()
        s = self.agent.settings.all()
        rows = self.db.q("SELECT * FROM posts WHERE (status='publishing' OR (status='scheduled' AND scheduled_at<=?)) "
                         "AND next_try_at<=? ORDER BY scheduled_at LIMIT 6", (t, t))
        for r in rows:
            if r["status"] == "scheduled":
                if not r["manual"]:
                    if not s["autopilot"]:
                        continue
                    if t - r["scheduled_at"] > MISSED_AFTER_SEC:
                        self.db.x("UPDATE posts SET status='missed', updated_at=?, error=? WHERE id=?",
                                  (t, "ایجنت در زمان این پست روشن نبود. اگر هنوز می‌خواهی، دستی منتشرش کن.", r["id"]))
                        self.agent.note("یک %s زمان‌بندی‌شده جا ماند چون ایجنت در آن ساعت روشن نبود." % KIND_FA[r["kind"]],
                                        "warn", "publish")
                        continue
                    if self.published_last_day() >= s["limits"]["daily_posts"]:
                        self.later(r["id"], 1800, "سقف روزانه‌ای که خودت گذاشته‌ای پر است؛ بعداً دوباره بررسی می‌شود.")
                        continue
                self.db.x("UPDATE posts SET status='publishing', error='', progress='در حال آماده‌سازی…', updated_at=? WHERE id=?",
                          (t, r["id"]))
                r = self.raw(r["id"])
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

    def restart(self, r, st):
        n = st.get("restarts", 0) + 1
        if n > 2:
            raise Permanent("اینستاگرام چند بار بارگذاری را ناتمام گذاشت. کمی بعد دوباره تلاش کن.")
        self.put(r["id"], {"restarts": n}, "شروع دوباره…")
        self.later(r["id"], 1)

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
                st["container"] = ig.create_container(p)
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
                mid = ig.publish(st["container"])
            except GraphError as e:
                if e.kind in ("network", "transient"):
                    return self.later(pid, PUBLISH_RECHECK_SEC, "پاسخ اینستاگرام نرسید؛ در حال بررسی نتیجه…")
                st["stage"] = "wait" if e.kind == "not_ready" else "publish"      # a clear "no": nothing was published
                st.pop("sent", None)
                self.put(pid, st)
                if e.kind == "not_ready":
                    return self.later(pid, CONTAINER_POLL_SEC)
                raise
            return self.finish(r, st, mid)
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
                    if st.get("dirty"):
                        return self.restart(r, {})
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
                return self.restart(r, {})
            return self.later(pid, CONTAINER_POLL_SEC)

    def find_published(self, r, st):
        """Looks for this post on the page itself (used when a publish answer was lost)."""
        since = st.get("sent", now()) - 120
        want = (st.get("caption", r["caption"]) or "").strip()
        try:
            if r["kind"] == "story":
                for m in self.agent.ig.stories():
                    if parse_ts(m.get("timestamp")) >= since:
                        return str(m.get("id"))
                return ""
            for m in self.agent.ig.media(limit=8):
                if parse_ts(m.get("timestamp")) >= since and (m.get("caption") or "").strip() == want:
                    return str(m.get("id"))
        except GraphError:
            pass
        return ""

    def finish(self, r, st, media_id):
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
            if self.db.one("SELECT id FROM comments WHERE id=?", (cid,)) is None:
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
                         "AND ts>=? ORDER BY ts LIMIT 25", (now() - AUTO_MAX_AGE,))
        ai_calls = 0
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
                    if self.agent.quiet():
                        continue
                    if not self.agent.may_act():
                        return
                    self.db.x(mark, (c["id"],))
                    if not self.agent.cooling(self.ukey(c)):
                        self.apply(rule, c)
                    continue
            if auto["ai_suggest"] and c["ts"] >= since["ai_suggest"] and ai_calls < 3:
                ai_calls += 1
                self.db.x(mark, (c["id"],))
                out = self.agent.ai.reply(c["text"], self.media_brief(c["media_id"])["caption"])
                send = (auto["ai_send"] and out["source"] == "ai" and c["ts"] >= since["ai_send"] and not self.agent.quiet()
                        and not self.agent.cooling(self.ukey(c)) and self.agent.may_act())
                try:
                    if send:
                        self.reply(c["id"], out["text"], actor="ai")
                        self.agent.note("دستیار به کامنت @%s پاسخ داد: «%s»" % (c["username"], out["text"][:70]), "info", "auto")
                    else:
                        self.db.x("UPDATE comments SET suggest=? WHERE id=?", (out["text"], c["parent_id"] or c["id"]))
                except GraphError as e:
                    self.agent.problem(e, "comments")

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
        for m in reversed(self.agent.ig.messages(cid)):       # Instagram lists newest first
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
        rows = self.db.q("SELECT * FROM convs WHERE %s AND last_id!=auto_id AND last_user_ts>=? ORDER BY last_user_ts LIMIT 20"
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

    def facts(self):
        a = self.ig.acct
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

    def status(self):
        a, s, t = self.ig.acct, self.settings.all(), now()
        day = time.mktime(tuple(time.localtime()[:3]) + (0, 0, 0, 0, 0, -1))
        count = self.db.val
        nxt = self.db.one("SELECT * FROM posts WHERE status='scheduled' ORDER BY scheduled_at LIMIT 1")
        return {
            "version": VERSION, "demo": self.cfg.demo, "connected": self.ig.connected, "now": t,
            "account": {k: a.get(k) for k in ("username", "name", "picture", "followers", "follows", "media_count", "bio",
                                              "login", "invalid", "token_expires", "connected_at", "last_username")},
            "autopilot": s["autopilot"], "auto": s["auto"], "quiet": self.quiet(),
            "counts": {
                "open_comments": self.inbox.open_count(), "open_dms": self.direct.open_count(),
                "scheduled": count("SELECT COUNT(*) FROM posts WHERE status='scheduled'"),
                "publishing": count("SELECT COUNT(*) FROM posts WHERE status='publishing'"),
                "failed": count("SELECT COUNT(*) FROM posts WHERE status IN ('failed','missed')"),
                "drafts": count("SELECT COUNT(*) FROM posts WHERE status IN ('draft','canceled')"),
                "published_today": count("SELECT COUNT(*) FROM posts WHERE status='published' AND published_at>=?", (day,)),
                "auto_today": count("SELECT COUNT(*) FROM actions WHERE actor!='user' AND ts>=?", (day,)),
                "unseen": count("SELECT COUNT(*) FROM log WHERE seen=0"),
            },
            "next_post": self.publisher.view(nxt) if nxt else None, "quota": self.db.get("quota"),
            "daily_cap": s["limits"]["daily_posts"], "media": self.store.methods(), "ai": self.ai.mode(),
            "dm_blocked": self.db.get("dm.blocked") or "", "busy": self.graph.busy() or t < self.cool_until,
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
        self.calls, self.faults, self.fetched, self.telegram = [], [], [], []
        self.unknown_fields = set()
        self.video_seconds = 3
        self.lively = True
        self.quota_used, self.quota_total = 0, 50
        self.next_live, self.live_i = now() + 20, 0
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
            parts.pop(0)
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
                return 200, {"data": [self.media_out(m) for m in self.media[:limit]]}
            if edge == "media_publish" and method == "POST":
                return self.publish(params)
            if edge == "content_publishing_limit":
                return 200, {"data": [{"quota_usage": self.quota_used, "config": {"quota_total": self.quota_total,
                                                                               "quota_duration": 86400}}]}
            if edge == "stories":
                return 200, {"data": [self.media_out(m) for m in self.stories if m["ts"] > now() - 86400]}
            if edge == "tags":
                return 200, {"data": []}
            if edge == "insights":
                return self.account_insights(params)
            if edge == "conversations":
                return 200, {"data": [self.conv_out(c) for c in sorted(self.convs.values(), key=lambda c: -c["updated"])]}
            if edge == "messages" and method == "POST":
                return self.send_message(body if isinstance(body, dict) else params)
        if head in self.containers and n == 1 and method == "GET":
            return 200, self.container_out(self.containers[head])
        m = next((x for x in self.media + self.stories if x["id"] == head), None)
        if m is not None:
            if n == 1 and method == "GET":
                return 200, self.media_out(m)
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
            return 200, {"id": conv["id"], "messages": {"data": [self.msg_out(conv, x) for x in reversed(conv["messages"][-30:])]}}
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

    def media_out(self, m):
        thumb = "/_sim/pub/%s.jpg" % m["id"] if m["blob"] else "/_sim/img/%d.svg" % m["n"]
        out = {"id": m["id"], "caption": m["caption"], "media_type": m["media_type"], "timestamp": iso(m["ts"]),
               "media_product_type": m["media_product_type"], "permalink": "https://www.instagram.com/p/%s/" % m["code"],
               "like_count": m["like_count"], "is_comment_enabled": m["comment_enabled"],
               "comments_count": len([1 for c in self.comments.values() if c["media_id"] == m["id"]])}
        if m["media_type"] == "VIDEO":
            out["thumbnail_url"] = thumb
        else:
            out["media_url"] = thumb
        return out

    def create_container(self, p, fetched):
        mtype = (p.get("media_type") or "IMAGE").upper()
        caption = p.get("caption") or ""
        if len(caption) > 2200:
            return self.err(36004, "The caption was too long", sub=2207010)
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
        src = self.containers[c["kids"][0]] if c["type"] == "CAROUSEL" else c
        if c["type"] == "CAROUSEL":
            mtype, product = "CAROUSEL_ALBUM", "FEED"
        elif c["type"] == "STORIES":
            mtype, product = ("VIDEO" if c["video"] else "IMAGE"), "STORY"
        elif c["video"]:
            mtype, product = "VIDEO", "REELS"
        else:
            mtype, product = "IMAGE", "FEED"
        m = self.make_media(c["caption"], mtype, now(), 0, self.seq % len(PALETTE), product, src["blob"])
        (self.stories if product == "STORY" else self.media).insert(0, m)
        return 200, {"id": m["id"]}

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

    def conv_out(self, c):
        return {"id": c["id"], "updated_time": iso(c["updated"]),
                "participants": {"data": [{"id": self.user["user_id"], "username": self.user["username"]},
                                          {"id": c["user_id"], "username": c["username"]}]}}

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

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b""))


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


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
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
    m = re.fullmatch(r"posts/(\d+)(?:/(publish|cancel|duplicate))?", path)
    if m:
        pid, action = int(m.group(1)), m.group(2)
        if action and P:
            return getattr(pub, {"publish": "publish_now", "cancel": "cancel", "duplicate": "duplicate"}[action])(pid)
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
            caption = "%s\n\n%s" % (idea, " ".join(agent.ai.offline_hashtags(idea)[:5]))
            made.append(pub.save({"kind": "image", "caption": caption, "media": [], "action": "draft"}))
        return {"items": made, "source": ideas["source"]}
    if path == "chat" and P:
        return agent.ai.chat(body.get("messages"), agent.facts())
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
        try:
            import fcntl
        except ImportError:
            return
        fh = open(os.path.join(self.cfg.data_dir, "agent.lock"), "w")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
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
# One self-contained Persian, right-to-left, phone-first page. No outside files, fonts or scripts.

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
:root{--bg:#f3f5fa;--card:#fff;--ink:#111827;--mut:#6b7280;--line:#e2e6ee;--soft:#eef1f6;--pri:#ec4899;--ok:#10b981;--warn:#d97706;--bad:#ef4444;--info:#3b82f6;--grad:linear-gradient(135deg,#f59e0b,#ec4899 55%,#8b5cf6)}
@media (prefers-color-scheme:dark){:root{--bg:#0b0f1a;--card:#141a29;--ink:#f1f5f9;--mut:#94a3b8;--line:#263044;--soft:#1b2335}}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.75 Vazirmatn,Vazir,IRANSans,Tahoma,system-ui,sans-serif}
body{padding-bottom:calc(78px + env(safe-area-inset-bottom))}
button,input,textarea,select{font:inherit;color:inherit}
button{cursor:pointer;border:0;background:none;padding:0}
a{color:var(--info)}
p{margin:0}
.ic{width:22px;height:22px;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;flex:none;vertical-align:middle}
.hide{display:none!important}
.ltr{direction:ltr;unicode-bidi:isolate}
input.ltr,textarea.ltr{text-align:left}
.muted{color:var(--mut)}.sm{font-size:.86rem}.center{text-align:center}
.row{display:flex;align-items:center;gap:10px}.grow{flex:1;min-width:0}.wrap{flex-wrap:wrap}
.col{display:flex;flex-direction:column;gap:10px}
.up{color:var(--ok)}.down{color:var(--bad)}
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
.in{width:100%;padding:9px 12px;border-radius:12px;border:1px solid var(--line);background:var(--soft);outline:0;min-height:44px}
.in:focus{border-color:var(--pri)}
textarea.in{resize:vertical;display:block}
label.f{font-size:.85rem;color:var(--mut);display:block;margin:6px 2px -4px}
.pill{display:inline-flex;align-items:center;gap:5px;border:1px solid var(--line);border-radius:99px;padding:1px 10px;font-size:.8rem;color:var(--mut);white-space:nowrap}
.pill .ic{width:14px;height:14px}
.pill.ok{color:var(--ok);border-color:var(--ok)}.pill.warn{color:var(--warn);border-color:var(--warn)}.pill.bad{color:var(--bad);border-color:var(--bad)}.pill.info{color:var(--info);border-color:var(--info)}.pill.pri{background:var(--pri);color:#fff;border-color:var(--pri)}
.seg{display:flex;background:var(--soft);border:1px solid var(--line);border-radius:14px;padding:4px;gap:4px}
.seg button{flex:1;padding:7px 4px;border-radius:10px;font-weight:600;color:var(--mut);display:flex;gap:6px;align-items:center;justify-content:center}
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
.sheet{position:fixed;inset:0;z-index:20;background:rgba(0,0,0,.5);display:flex;align-items:flex-end;justify-content:center}
.panel{background:var(--bg);width:100%;max-width:640px;max-height:92vh;max-height:92dvh;border-radius:22px 22px 0 0;display:flex;flex-direction:column}
.panel .head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 16px;border-bottom:1px solid var(--line)}
.panel .body{padding:14px;overflow:auto;display:flex;flex-direction:column;gap:12px;flex:1}
.panel .foot{padding:10px 14px calc(10px + env(safe-area-inset-bottom));border-top:1px solid var(--line);display:flex;gap:8px;align-items:center}
.panel .foot .btn{flex:1}
#toasts{position:fixed;top:12px;left:0;right:0;z-index:40;display:flex;flex-direction:column;align-items:center;gap:8px;pointer-events:none}
.toast{background:var(--card);border:1px solid var(--ok);border-radius:14px;padding:8px 14px;box-shadow:0 6px 20px rgba(0,0,0,.25);max-width:90%}
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
const S = {st: null, authed: true, tab: 'home', sub: {content: 'queue', inbox: 'comments'}, filter: 'open', days: 7, seq: 0, refresh: false};
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
const STATUS = {draft: ['پیش‌نویس', ''], scheduled: ['زمان‌بندی‌شده', 'info'], publishing: ['در حال انتشار', 'warn'], published: ['منتشرشده', 'ok'], failed: ['ناموفق', 'bad'], missed: ['جامانده', 'warn'], canceled: ['لغوشده', '']};

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
  const t = h('div', {class: 'toast ' + (kind || ''), role: 'status'}, msg);
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
async function refresh() { S.st = await GET('/api/status'); if (S.st.connected) { paintTop(); paintNav(); } }

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
  const state = a.invalid ? ['bad', 'اتصال پیج قطع است'] : !st.autopilot ? ['off', 'ایجنت متوقف است'] : st.busy ? ['warn', 'اینستاگرام موقتاً محدود کرده؛ کمی صبر'] : ['', 'ایجنت روشن است'];
  fill($('#top'), h('img', {src: '/icon.svg', alt: ''}),
    h('div', {class: 'grow'}, h('h1', null, '@' + a.username), h('div', {class: 'sub'}, h('i', {class: 'dot ' + state[0]}), (st.demo ? 'حالت نمایشی — ' : '') + state[1])),
    h('button', {class: 'iconbtn', 'aria-label': 'اعلان‌ها', onclick: notesSheet}, icon('bell'), st.counts.unseen ? h('span', {class: 'badge'}, fa(st.counts.unseen)) : null));
}
function paintNav() {
  const c = S.st.counts, n = c.open_comments + c.open_dms;
  fill($('#nav'), TABS.map(t => h('button', {class: S.tab === t[0] ? 'on' : '', 'data-tab': t[0], onclick: () => go(t[0])}, icon(t[2]), t[1], t[0] === 'inbox' && n ? h('span', {class: 'badge'}, fa(n)) : null)));
  $('#fab').classList.toggle('hide', S.tab !== 'content' || !!S.st.account.invalid);
}
function go(tab, sub) { S.tab = tab; if (sub) S.sub[tab] = sub; window.scrollTo(0, 0); render(true); }
async function render(fresh) {
  const view = $('#view'), st = S.st;
  const chrome = on => { $('#top').classList.toggle('hide', !on); $('#nav').classList.toggle('hide', !on); if (!on) $('#fab').classList.add('hide'); };
  S.seq++;
  if (!S.authed) { chrome(false); return fill(view, loginView()); }
  if (!st) { chrome(false); return fill(view, h('div', {class: 'empty'}, 'در حال اتصال به ایجنت…')); }
  if (!st.connected) { chrome(false); return fill(view, connectView()); }
  chrome(true); paintTop(); paintNav();
  const my = S.seq;
  if (fresh) fill(view, h('div', {class: 'empty'}, 'در حال بارگذاری…'));
  try { const kids = await VIEWS[S.tab](); if (my === S.seq) fill(view, kids); }
  catch (e) { if (my === S.seq && !(e && e.silent)) fill(view, h('div', {class: 'card bad'}, (e && e.message) || 'خطا'), h('button', {class: 'btn', onclick: () => render(true)}, icon('refresh'), 'تلاش دوباره')); }
}
async function poll() {
  if (D.hidden || !S.authed) return;
  const prev = S.st;
  try { S.st = await GET('/api/status'); } catch (e) { return; }
  if (!prev || prev.connected !== S.st.connected) return render(true);
  if (!S.st.connected) return;
  paintTop(); paintNav();
  const sig = s => JSON.stringify([s.counts, s.autopilot, s.auto, s.account.invalid, s.account.followers, s.next_post && s.next_post.id]);
  const typing = /INPUT|TEXTAREA|SELECT/.test((D.activeElement || {}).tagName || '');
  if (sig(prev) !== sig(S.st) && !typing && !$('#sheets').childElementCount) render(false);
}

/* ───── login & connect ───── */
function loginView() {
  const inp = h('input', {class: 'in ltr center', placeholder: 'ABCDE-FGHJK', autocomplete: 'off', autocapitalize: 'characters', spellcheck: 'false', 'aria-label': 'کد ورود'});
  const btn = h('button', {class: 'btn pri block', type: 'submit'}, icon('lock'), 'ورود');
  const submit = e => { e.preventDefault(); run(btn, async () => { await POST('/api/login', {key: inp.value}); S.authed = true; S.st = await GET('/api/status'); render(true); }); };
  return [h('div', {class: 'hero'}, h('img', {src: '/icon.svg', alt: ''}), h('h2', null, 'ایجنت اینستاگرام'), h('p', {class: 'muted'}, 'کدی را که هنگام اجرای برنامه در ترمینال نشان داده شد وارد کن.')),
    h('form', {class: 'card col', onsubmit: submit}, h('label', {class: 'f'}, 'کد ورود (Key)'), inp, btn,
      h('p', {class: 'muted sm'}, 'کد را گم کرده‌ای؟ در ترمینال بزن: ', h('code', null, 'python insta_agent.py --show-key')))];
}
function guide() {
  const li = (...k) => h('li', null, k);
  return h('ol', {class: 'steps'},
    li('پیج باید «حرفه‌ای» (Business یا Creator) باشد: در اینستاگرام ← تنظیمات ← نوع حساب ← «تغییر به حساب حرفه‌ای» (رایگان است).'),
    li('در سایت ', h('a', {href: 'https://developers.facebook.com/apps/', target: '_blank', rel: 'noopener'}, 'developers.facebook.com'), ' وارد شو، «Create App» را بزن و نوع «Business» را انتخاب کن.'),
    li('در برنامه‌ای که ساختی محصول «Instagram» را اضافه کن و به بخش «API setup with Instagram login» برو.'),
    li('در قسمت «Generate access tokens» پیج خودت را اضافه کن، همهٔ دسترسی‌ها را تأیید کن و «Generate token» را بزن.'),
    li('توکن (رشتهٔ بلندی که با IGAA شروع می‌شود) را کپی کن و همین‌جا بچسبان.'));
}
function tokenBox(done) {
  const ta = h('textarea', {class: 'in ltr', rows: 3, placeholder: 'IGAA…', 'aria-label': 'توکن', spellcheck: 'false', autocomplete: 'off'});
  const btn = h('button', {class: 'btn pri block', onclick: () => run(btn, async () => { S.st = await POST('/api/connect', {token: ta.value}); toast('پیج وصل شد ✓'); done(); })}, icon('link'), 'اتصال به پیج');
  return [field('توکن دسترسی (Access Token)', ta), btn];
}
function connectView() {
  const a = (S.st.account || {}), proxy = h('input', {class: 'in ltr', placeholder: 'http://127.0.0.1:10809', 'aria-label': 'پروکسی'});
  GET('/api/settings').then(s => { proxy.value = s.network.proxy; }).catch(() => {});
  return [h('div', {class: 'hero'}, h('img', {src: '/icon.svg', alt: ''}), h('h2', null, 'پیج را یک بار وصل کن'),
      h('p', {class: 'muted'}, 'ایجنت فقط از راه رسمی اینستاگرام (توکن) وصل می‌شود و هیچ‌وقت رمز پیج را نمی‌خواهد.')),
    a.last_username ? h('div', {class: 'card sm'}, 'آخرین پیج وصل‌شده: ', h('b', {class: 'ltr'}, '@' + a.last_username)) : null,
    h('div', {class: 'card col'}, tokenBox(() => { S.tab = 'home'; render(true); })),
    h('details', {class: 'box', open: true}, h('summary', null, icon('help'), 'توکن را از کجا بیاورم؟ (حدود ۵ دقیقه، فقط یک بار)'), guide(),
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
VIEWS.home = async () => {
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
  const m = p.media[0], st = STATUS[p.status];
  const sub = p.status === 'scheduled' ? when(p.scheduled_at) : p.status === 'publishing' ? (p.progress || 'در حال انتشار…') : p.status === 'published' ? ago(p.published_at)
    : (p.status === 'failed' || p.status === 'missed') ? p.error : 'آخرین تغییر: ' + ago(p.updated_at);
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
  const c = S.st.counts, sub = S.sub.content;
  const seg = segment([['queue', 'صف انتشار', c.scheduled + c.publishing + c.failed], ['drafts', 'پیش‌نویس‌ها'], ['page', 'صفحهٔ من']], sub, v => { S.sub.content = v; render(true); });
  if (sub === 'page') {
    const d = await GET('/api/media');
    return [seg, d.items.length ? h('div', {class: 'grid'}, d.items.map(tile)) : empty('grid', 'هنوز پستی در پیج نیست.')];
  }
  const [d, done] = await Promise.all([GET('/api/posts?group=' + sub), sub === 'queue' ? GET('/api/posts?group=published') : {items: []}]);
  const fresh = h('button', {class: 'btn pri', onclick: () => composer()}, icon('plus'), 'پست جدید');
  return [seg, sub === 'drafts' ? h('button', {class: 'btn', onclick: planSheet}, icon('spark'), 'چیدن برنامهٔ محتوایی') : null,
    d.items.length ? d.items.map(postCard) : empty('calendar', sub === 'queue' ? 'چیزی در صف انتشار نیست.' : 'پیش‌نویسی نداری.', fresh),
    done.items.length ? [h('h3', null, 'منتشرشده از همین پنل'), done.items.slice(0, 6).map(postCard)] : null];
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
function postSheet(id) {
  let timer = 0, last = '';
  const s = sheet('پست', {onclose: () => clearTimeout(timer)});
  const load = async () => {
    let p;
    try { p = await GET('/api/posts/' + id); } catch (e) { s.close(); return; }
    if (last && last !== p.status) render(false);
    last = p.status;
    const st = STATUS[p.status], again = async () => { await refresh(); render(false); await load(); };
    fill(s.body, p.media.length ? h('div', {class: 'strip'}, p.media.map(m => thumb(m.missing ? '' : m.preview, m.type, 'mitem'))) : null,
      h('div', {class: 'chips'}, h('span', {class: 'pill ' + st[1]}, st[0]), h('span', {class: 'pill'}, icon(KIND[p.kind][1]), KIND[p.kind][0])),
      p.status === 'scheduled' ? h('div', {class: 'row'}, icon('clock'), when(p.scheduled_at)) : null,
      p.status === 'publishing' ? h('div', {class: 'card'}, p.progress || 'در حال انتشار…', p.error ? h('div', {class: 'muted sm'}, 'آخرین مشکل: ' + p.error) : null) : null,
      (p.status === 'failed' || p.status === 'missed') && p.error ? h('div', {class: 'card bad'}, p.error) : null,
      p.status === 'published' ? h('div', {class: 'card ok'}, 'منتشر شد ✓ — ' + ago(p.published_at)) : null,
      h('div', {class: 'pre'}, p.caption || '— بدون کپشن —'));
    const act = (label, fn, cls, ic) => h('button', {class: 'btn ' + (cls || ''), onclick: e => run(e.currentTarget, fn)}, ic ? icon(ic) : null, label);
    const kids = [];
    if (p.status === 'publishing') timer = setTimeout(load, 1500);
    else if (p.status === 'published') {
      if (p.permalink) kids.push(h('a', {class: 'btn', href: p.permalink, target: '_blank', rel: 'noopener'}, icon('external'), 'دیدن در اینستاگرام'));
      kids.push(act('کپی به پیش‌نویس', async () => { await POST('/api/posts/' + id + '/duplicate'); toast('در پیش‌نویس‌ها کپی شد'); s.close(); go('content', 'drafts'); }, '', 'layers'));
    } else {
      kids.push(act('حذف', async () => { if (await ask('این پست حذف شود؟', 'حذف', true)) { await DEL('/api/posts/' + id); s.close(); await refresh(); render(false); } }, 'danger', 'trash'));
      kids.push(act('ویرایش', async () => { s.close(); composer(p); }, '', 'edit'));
      if (p.status === 'scheduled') kids.push(act('لغو زمان', async () => { await POST('/api/posts/' + id + '/cancel'); toast('به پیش‌نویس‌ها برگشت'); await again(); }));
      kids.push(act(p.status === 'failed' ? 'تلاش دوباره' : 'انتشار الان', async () => { await POST('/api/posts/' + id + '/publish'); await again(); }, 'pri', 'send'));
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
function composer(post) {
  const p = post ? {id: post.id, kind: post.kind, caption: post.caption, opts: Object.assign({}, post.opts), mode: post.status === 'scheduled' ? 'later' : 'now', at: post.status === 'scheduled' ? post.scheduled_at : 0,
      media: post.media.filter(m => !m.missing).map(m => m.file ? {file: m.file, type: m.type, preview: m.preview} : {url: m.url, type: m.type, preview: m.url})}
    : {kind: 'image', caption: '', media: [], opts: {share_to_feed: true}, mode: 'now', at: 0};
  const s = sheet(post ? 'ویرایش پست' : 'پست جدید');
  const file = h('input', {type: 'file', class: 'hide'}), cap = h('textarea', {class: 'in', rows: 5, placeholder: 'کپشن…', 'aria-label': 'کپشن', value: p.caption});
  const counter = h('div', {class: 'muted sm row'}), strip = h('div', {class: 'strip'}), kinds = h('div', {class: 'kinds'}), hint = h('div', {class: 'muted sm'}), timing = h('div', {class: 'card col'});
  const optBox = h('div', {class: 'col'}), capBox = h('div', {class: 'col'});
  const max = () => (p.kind === 'carousel' ? 20 : 1);
  const count = () => {
    const tags = (cap.value.match(/#[^\s#]+/g) || []).length;
    fill(counter, h('span', {class: 'grow'}, fa(cap.value.length) + ' از ۲٬۲۰۰ نویسه'), h('span', null, fa(tags) + ' هشتگ (حداکثر ۳۰)'));
    counter.classList.toggle('down', cap.value.length > 2200 || tags > 30);
  };
  cap.addEventListener('input', count);
  const addUrl = () => {
    const u = sheet('افزودن با لینک'), inp = h('input', {class: 'in ltr', placeholder: 'https://…/photo.jpg', 'aria-label': 'لینک'}), typ = h('select', {class: 'in'}, h('option', {value: 'image'}, 'عکس (JPEG)'), h('option', {value: 'video'}, 'ویدیو (MP4)'));
    if (p.kind === 'reel') typ.value = 'video';
    add(u.body, h('p', {class: 'muted sm'}, 'لینک باید مستقیم و عمومی باشد (اینستاگرام خودش فایل را از این نشانی برمی‌دارد).'), field('لینک فایل', inp), field('نوع فایل', typ));
    u.setFoot(h('button', {class: 'btn pri', onclick: () => { const v = inp.value.trim(); if (!/^https:\/\/\S+$/.test(v)) return toast('لینک باید با https:// شروع شود', 'bad'); p.media.push({url: v, type: typ.value, preview: v}); u.close(); paint(); }}, 'افزودن'));
  };
  const paintOpts = () => {
    const txt = (key, label, ph, rows) => { const el = h(rows ? 'textarea' : 'input', {class: 'in', placeholder: ph, rows, value: p.opts[key] || ''}); el.addEventListener('input', () => { p.opts[key] = el.value; }); return field(label, el); };
    const sw = (key, label, def) => h('div', {class: 'row'}, h('span', {class: 'grow'}, label), toggle(p.opts[key] == null ? def : p.opts[key], async v => { p.opts[key] = v; }, label));
    fill(optBox, p.kind === 'image' ? txt('alt_text', 'متن جایگزین عکس (برای نابینایان)', 'توضیح کوتاه عکس') : null,
      p.kind !== 'story' ? txt('first_comment', 'اولین کامنت (مثلاً هشتگ‌ها)', 'بعد از انتشار، خود پیج این را زیر پست می‌نویسد', 2) : null,
      p.kind === 'reel' ? sw('share_to_feed', 'نمایش ریل در صفحهٔ اصلی پیج', true) : null,
      p.kind !== 'story' ? sw('comments_off', 'بستن کامنت‌های این پست', false) : h('div', {class: 'muted sm'}, 'استوری گزینهٔ دیگری ندارد.'));
  };
  const paintTiming = () => {
    fill(timing, h('b', null, 'چه زمانی منتشر شود؟'), segment([['now', 'همین حالا'], ['later', 'زمان‌بندی']], p.mode, v => {
      p.mode = v; if (v === 'later' && !p.at) p.at = Math.ceil((Date.now() / 1000 + 3600) / 900) * 900; paintTiming(); paintFoot(); }));
    if (p.mode !== 'later') return;
    const d = new Date(p.at * 1000), t0 = new Date(), dsel = h('select', {class: 'in', 'aria-label': 'روز'}), time = h('input', {class: 'in ltr', type: 'time', 'aria-label': 'ساعت', value: two(d.getHours()) + ':' + two(d.getMinutes())});
    let pick = 0;
    for (let i = 0; i < 75; i++) {
      const x = new Date(t0.getFullYear(), t0.getMonth(), t0.getDate() + i);
      if (x.toDateString() === d.toDateString()) pick = i;
      dsel.appendChild(h('option', {value: i}, (i === 0 ? 'امروز — ' : i === 1 ? 'فردا — ' : '') + day(x)));
    }
    dsel.value = String(pick);
    const label = h('div', {class: 'muted sm'}, when(p.at)), chips = h('div', {class: 'chips'});
    const sync = () => { const t = (time.value || '12:00').split(':'), x = new Date(t0.getFullYear(), t0.getMonth(), t0.getDate() + Number(dsel.value), Number(t[0]), Number(t[1])); p.at = x.getTime() / 1000; fill(label, when(p.at)); };
    dsel.addEventListener('change', sync); time.addEventListener('change', sync);
    GET('/api/slots').then(r => fill(chips, r.items.map(ts => h('button', {class: 'chip', onclick: () => { p.at = ts; paintTiming(); }}, when(ts))))).catch(() => {});
    add(timing, h('div', {class: 'row'}, h('div', {class: 'grow'}, dsel), time), label, h('div', {class: 'muted sm'}, 'پیشنهاد ایجنت (ساعت‌هایی که پست‌هایت بهتر دیده شده):'), chips);
  };
  const paint = () => {
    fill(kinds, Object.keys(KIND).map(k => h('button', {class: p.kind === k ? 'on' : '', 'data-kind': k, onclick: () => { p.kind = k; p.media = p.media.slice(0, max()); paint(); }}, icon(KIND[k][1]), KIND[k][0])));
    file.accept = p.kind === 'reel' ? 'video/*' : p.kind === 'image' ? 'image/*' : 'image/*,video/*';
    file.multiple = p.kind === 'carousel';
    const more = p.media.length < max();
    fill(strip, p.media.map((m, i) => h('div', {class: 'mitem'}, thumb(m.preview, m.type, 'fit'), h('span', {class: 'tag'}, m.type === 'video' ? 'ویدیو' : 'عکس'),
        h('button', {class: 'rm', 'aria-label': 'برداشتن', onclick: () => { p.media.splice(i, 1); paint(); }}, icon('x')))),
      more ? h('button', {class: 'mitem add', 'data-add': 'file', onclick: () => file.click()}, icon('upload'), 'از گالری') : null,
      more ? h('button', {class: 'mitem add', 'data-add': 'url', onclick: addUrl}, icon('link'), 'با لینک') : null);
    fill(hint, {image: 'یک عکس. خودکار به JPEG تبدیل و اگر لازم باشد به نسبت مجاز (۴:۵ تا ۱٫۹۱:۱) بریده می‌شود.', carousel: '۲ تا ۲۰ عکس یا ویدیو؛ مخاطب ورق می‌زند.',
      reel: 'یک ویدیوی MP4 (عمودی ۹:۱۶ بهتر دیده می‌شود).', story: 'یک عکس یا ویدیو (۹:۱۶). استوری کپشن ندارد و بعد از ۲۴ ساعت پاک می‌شود.'}[p.kind]);
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
      else fill(list, note, h('div', {class: 'chips'}, r.items.map(t => h('button', {class: 'chip ltr', onclick: e => { cap.value = (cap.value.trim() + ' ' + t).trim(); count(); e.currentTarget.remove(); }}, t))),
        h('button', {class: 'btn', onclick: () => { cap.value = (cap.value.trim() + '\n\n' + r.items.slice(0, 12).join(' ')).trim(); count(); a.close(); }}, 'افزودن همه به کپشن'));
    })}, icon('spark'), 'بنویس');
    add(a.body, field(label, h('div', {class: 'row'}, topic, go_)), list);
  };
  const paintFoot = () => s.setFoot(h('button', {class: 'btn', onclick: e => save(e.currentTarget, 'draft')}, 'پیش‌نویس'),
    h('button', {class: 'btn pri', 'data-go': '1', onclick: e => save(e.currentTarget, p.mode === 'later' ? 'schedule' : 'now')}, icon(p.mode === 'later' ? 'clock' : 'send'), p.mode === 'later' ? 'زمان‌بندی' : 'انتشار'));
  const save = (btn, action) => run(btn, async () => {
    const body = {kind: p.kind, caption: p.kind === 'story' ? '' : cap.value, media: p.media.map(m => (m.file ? {file: m.file} : {url: m.url, type: m.type})), opts: p.opts, action, scheduled_at: p.at};
    const r = await POST(p.id ? '/api/posts/' + p.id : '/api/posts', body);
    s.close();
    toast(action === 'draft' ? 'در پیش‌نویس‌ها ذخیره شد' : action === 'schedule' ? 'زمان‌بندی شد ✓' : 'انتشار شروع شد…');
    await refresh(); S.tab = 'content'; S.sub.content = action === 'draft' ? 'drafts' : 'queue'; render(true);
    if (action === 'now') postSheet(r.id);
  });
  add(capBox, field('کپشن', cap), counter, h('div', {class: 'row'}, h('button', {class: 'btn sm grow', onclick: () => helper('کپشن پیشنهادی', 'این پست دربارهٔ چیست؟', '/api/ai/captions', true)}, icon('spark'), 'کپشن پیشنهادی'),
    h('button', {class: 'btn sm grow', onclick: () => helper('هشتگ پیشنهادی', 'موضوع پست', '/api/ai/hashtags', false)}, icon('hash'), 'هشتگ پیشنهادی')));
  add(s.body, kinds, strip, hint, file, capBox, h('details', {class: 'box'}, h('summary', null, icon('settings'), 'گزینه‌های بیشتر'), optBox), timing);
  count(); paint();
}

/* ───── comments & direct ───── */
function threadCard(t, keep) {
  const card = h('div', {class: 'card col thread'});
  const gone = () => { card.remove(); if (!keep && !$('#view .thread')) render(false); };
  const paint = t => {
    const ta = h('textarea', {class: 'in', rows: 1, placeholder: 'پاسخ بده…', 'aria-label': 'پاسخ', value: t.suggest || ''});
    const act = (btn, action, body, msg, id) => run(btn, async () => {
      const r = await POST('/api/comments/' + (id || t.id) + '/' + action, body);
      toast(msg); await refresh();
      if (r.thread && (keep || S.filter !== 'open' || r.thread.open)) paint(r.thread); else gone();
    });
    const send = h('button', {class: 'btn pri', 'aria-label': 'فرستادن پاسخ', onclick: () => act(send, 'reply', {text: ta.value}, 'پاسخ فرستاده شد ✓')}, icon('send'));
    const bubble = c => h('div', {class: 'bubble' + (c.mine ? ' me' : '')}, h('small', null, h('b', {class: 'ltr'}, '@' + c.username), ' · ' + ago(c.ts) + (c.hidden ? ' · مخفی‌شده' : '') + (c.dm_sent ? ' · پیام خصوصی رفت' : '')), c.text);
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
    item('spark', 'پیشنهاد پاسخ از دستیار', b => run(b, async () => { const r = await POST('/api/comments/' + t.id + '/suggest'); t.suggest = r.text; s.close(); paint(t); })),
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
    h('div', {class: 'grow'}, h('div', {class: 'row'}, h('b', {class: 'ltr grow'}, '@' + c.username), h('small', {class: 'muted'}, ago(c.last_ts))), h('div', {class: 'muted sm clamp'}, (c.last_from_me ? 'شما: ' : '') + c.last_text)),
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
    if (sig !== seen) { seen = sig; fill(box, d.messages.map(m => h('div', {class: 'bubble' + (m.mine ? ' me' : '')}, m.text, h('small', null, ago(m.ts))))); s.body.scrollTop = s.body.scrollHeight; }
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
      return h('div', {class: 'col'}, h('b', {class: 'sm'}, AUD[k]), rows.map(x => h('div', null, h('div', {class: 'row sm'}, h('span', {class: 'grow'}, k === 'gender' ? (GENDER[x.name] || x.name) : x.name), h('span', {class: 'muted'}, fa(Math.round(x.value * 100 / total)) + '٪')), bar(x.value / total))));
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
        h('button', {class: 'btn sm danger', onclick: async () => { if (await ask('اتصال پیج برداشته شود؟ تا اتصال دوباره هیچ پستی منتشر نمی‌شود.', 'قطع اتصال', true)) run(null, async () => { S.st = await POST('/api/disconnect'); render(true); }); }}, 'قطع اتصال'))),
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
  const state = (on, text) => h('div', {class: 'row sm'}, h('i', {class: 'dot ' + (on ? '' : 'off')}), h('span', {class: 'grow'}, text));
  add(s.body,
    box('brand', 'home', 'معرفی پیج (برای کپشن‌ها و پاسخ‌ها)', [field('پیج دربارهٔ چیست؟', about), field('لحن نوشتن', tone), field('هشتگ‌های همیشگی پیج', tags)], () => ({brand: {about: about.value, tone: tone.value, hashtags: tags.value}})),
    box('ai', 'spark', 'هوش مصنوعی', [field('سرویس', aiMode, 'در حالت رایگان، متن کامنت/موضوع برای نوشتن پاسخ به یک سرویس عمومی فرستاده می‌شود.'), field('نشانی سرویس خودم', aiUrl), field('نام مدل', aiModel), field('کلید', aiKey)],
      () => ({ai: {mode: aiMode.value, url: aiUrl.value, model: aiModel.value, key: aiKey.value}})),
    box('media', 'upload', 'انتشار از گالری (لینک عمومی)', [h('p', {class: 'muted sm'}, 'اینستاگرام فایل را خودش از یک نشانی اینترنتی برمی‌دارد. برای عکس و ویدیویی که از گالری انتخاب می‌کنی، ایجنت باید چند دقیقه یک لینک عمومی برایش بسازد:'),
        state(m.tunnel, m.tunnel ? 'تونل cloudflared: آماده است (فایل از خود گوشی و فقط در لحظهٔ انتشار در دسترس قرار می‌گیرد؛ پنل هیچ‌وقت بیرون نمی‌آید).' : 'تونل cloudflared: نصب نیست. در ترموکس یک بار بزن: pkg install cloudflared و ایجنت را دوباره اجرا کن.'),
        h('div', {class: 'row sm'}, h('i', {class: 'dot ' + (tempOk ? '' : 'off')}), h('span', {class: 'grow'}, 'میزبان موقت: فایل یک ساعت روی سرویس عمومی litterbox.catbox.moe گذاشته می‌شود (بدون نصب چیزی).'), toggle(tempOk, async v => { tempOk = v; }, 'میزبان موقت')),
        state(m.public, 'نشانی عمومی خودم: اگر ایجنت روی سرور یا پشت دامنهٔ خودت است.'), field('روش', method), field('نشانی عمومی (اختیاری)', pub)],
      () => ({media: {method: method.value, public_url: pub.value, temp_ok: tempOk}})),
    box('telegram', 'send', 'اعلان در تلگرام', [h('p', {class: 'muted sm'}, 'با @BotFather یک ربات بساز، توکنش را اینجا بگذار و شناسهٔ عددی خودت را (مثلاً از @userinfobot) بنویس. هشدارها و گزارش روزانه برایت فرستاده می‌شود.'), field('توکن ربات', tgToken), field('شناسهٔ چت', tgChat)],
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
    sec('ایجنت چه کارهایی می‌کند؟', 'پست، پست چندتایی، ریل و استوری را همین حالا یا در زمان دلخواه منتشر می‌کند.', 'کامنت‌ها و دایرکت‌ها را در یک صندوق نشان می‌دهد و می‌توانی از همین‌جا جواب بدهی، مخفی یا حذف کنی.',
      'طبق قانون‌هایی که می‌نویسی خودش جواب می‌دهد و کامنت‌های تبلیغاتی را مخفی می‌کند.', 'آمار پیج و بهترین ساعت انتشار را نشان می‌دهد و در نوشتن کپشن و هشتگ کمک می‌کند.'),
    sec('چه چیزهایی شدنی نیست؟', 'اینستاگرام از راه رسمی اجازهٔ فالو/آنفالو، لایک‌کردن، دیدن فهرست دنبال‌کننده‌ها، ویرایش کپشن یا بیو و گذاشتن استیکر و لینک روی استوری را نمی‌دهد؛ ایجنت هم سراغ راه‌های غیررسمی (که پیج را در خطر بسته‌شدن می‌گذارد) نمی‌رود.',
      'دایرکت با عموم مردم فقط وقتی کار می‌کند که برنامه‌ات در متا «Advanced Access» گرفته باشد؛ تا آن موقع فقط با حساب‌هایی که در برنامه نقش دارند.'),
    sec('ایجنت باید روشن بماند', 'زمان‌بندی و پاسخ خودکار فقط تا وقتی کار می‌کند که برنامه در ترموکس باز باشد. در ترموکس بزن: termux-wake-lock و بهینه‌سازی باتری را برای ترموکس خاموش کن.',
      'اگر ایجنت در زمان یک پست خاموش باشد و بیش از ۶ ساعت بگذرد، آن پست «جامانده» می‌شود و خودکار منتشر نمی‌شود.'),
    sec('امنیت', 'رمز پیج هیچ‌وقت خواسته نمی‌شود. توکن فقط روی همین دستگاه می‌ماند و هر وقت بخواهی می‌توانی از تنظیمات اینستاگرام دسترسی برنامه را برداری.', 'پنل فقط روی همین دستگاه باز است و با کد ورود قفل می‌شود.'));
}

/* ───── start ───── */
fill($('#fab'), icon('plus'));
$('#fab').addEventListener('click', () => composer());
(async () => {
  try { S.st = await GET('/api/status'); } catch (e) { if (e.status !== 401) S.st = null; }
  render(true);
  setInterval(poll, 4000);
  D.addEventListener('visibilitychange', () => { if (!D.hidden) poll(); });
})();
</script>
</body>
</html>
'''


if __name__ == "__main__":
    sys.exit(main())
