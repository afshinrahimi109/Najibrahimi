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
        stamp = now()

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
