# -*- coding: utf-8 -*-
"""
🧠 Diana Memory — حافظه بلندمدت دیانا
همه چیز روی هاست شما ذخیره می‌شه: اسم و اطلاعات کاربر، حقایق به‌خاطرسپرده‌شده،
تاریخچه گفتگو، مأموریت‌ها و تنظیمات. ذخیره‌سازی JSON اتمیک و thread-safe —
جایگزین دست‌ساز و رایگانِ دیتابیس‌های پولی.
"""
import json
import os
import re
import threading
import time
from datetime import datetime

from agents import norm
from tools import DATA_DIR

MEMORY_FILE = os.path.join(DATA_DIR, "memory.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

DEFAULT_MEMORY = {
    "profile": {"user_name": "", "born": None},
    "facts": [],
    "conversations": [],
    "missions": [],
    "reminders": [],
    "stats": {"missions_done": 0, "messages": 0, "agents_runs": {}},
}
DEFAULT_SETTINGS = {
    "voice": True,
    "cloud_brain": True,   # استفاده از مغز ابری رایگان از سمت مرورگر
    "groq_key": "",
    "gemini_key": "",
    "openrouter_key": "",
}


class Memory:
    def __init__(self):
        self.lock = threading.RLock()
        self.data = self._load(MEMORY_FILE, dict(DEFAULT_MEMORY))
        self.settings = self._load(SETTINGS_FILE, dict(DEFAULT_SETTINGS))
        if not self.data["profile"].get("born"):
            self.data["profile"]["born"] = datetime.now().isoformat(timespec="seconds")
            self.save()

    def _load(self, path, default):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            merged = dict(default)
            merged.update(d)
            return merged
        except Exception:
            return dict(default)

    def _atomic_save(self, path, payload):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)

    def save(self):
        with self.lock:
            self._atomic_save(MEMORY_FILE, self.data)

    def save_settings(self):
        with self.lock:
            self._atomic_save(SETTINGS_FILE, self.settings)

    # ---------- پروفایل و حقایق ----------
    def set_user_name(self, name):
        with self.lock:
            self.data["profile"]["user_name"] = name.strip()[:40]
            self.save()

    def user_name(self):
        return self.data["profile"].get("user_name", "")

    def add_fact(self, text):
        with self.lock:
            fact = {"id": int(time.time() * 1000), "text": text.strip()[:500],
                    "ts": datetime.now().strftime("%Y-%m-%d %H:%M")}
            self.data["facts"].append(fact)
            self.data["facts"] = self.data["facts"][-300:]
            self.save()
            return fact

    def delete_fact(self, fid):
        with self.lock:
            before = len(self.data["facts"])
            self.data["facts"] = [f for f in self.data["facts"] if str(f["id"]) != str(fid)]
            self.save()
            return len(self.data["facts"]) < before

    def recall(self, query, k=5):
        q = norm(query)
        tokens = [t for t in re.split(r"\s+", q) if len(t) > 1]
        scored = []
        for f in self.data["facts"]:
            s = sum(1 for t in tokens if t in norm(f["text"]))
            if s:
                scored.append((s, f))
        scored.sort(key=lambda x: -x[0])
        return [f for _, f in scored[:k]]

    # ---------- گفتگو ----------
    def log_chat(self, role, text, source=""):
        with self.lock:
            self.data["conversations"].append({
                "role": role, "text": (text or "")[:4000], "source": source,
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })
            self.data["conversations"] = self.data["conversations"][-400:]
            if role == "user":
                self.data["stats"]["messages"] += 1
            self.save()

    def recent_chat(self, k=10):
        return self.data["conversations"][-k:]

    # ---------- مأموریت‌ها ----------
    def add_mission(self, mission):
        with self.lock:
            self.data["missions"].append(mission)
            self.data["missions"] = self.data["missions"][-120:]
            self.save()

    def update_mission(self, mission_id, **fields):
        with self.lock:
            for m in self.data["missions"]:
                if m["id"] == mission_id:
                    m.update(fields)
                    break
            self.save()

    def get_mission(self, mission_id):
        for m in self.data["missions"]:
            if m["id"] == mission_id:
                return m
        return None

    def bump_agent_stat(self, agent_id):
        with self.lock:
            st = self.data["stats"].setdefault("agents_runs", {})
            st[agent_id] = st.get(agent_id, 0) + 1
            self.save()

    def mission_done_inc(self):
        with self.lock:
            self.data["stats"]["missions_done"] += 1
            self.save()

    # ---------- یادآوری ----------
    def add_reminder(self, text):
        with self.lock:
            r = {"id": int(time.time() * 1000), "text": text.strip()[:300],
                 "ts": datetime.now().strftime("%Y-%m-%d %H:%M"), "done": False}
            self.data["reminders"].append(r)
            self.save()
            return r

    # ---------- خروجی عمومی ----------
    def public_state(self):
        return {
            "profile": self.data["profile"],
            "facts": self.data["facts"][-100:],
            "reminders": [r for r in self.data["reminders"] if not r["done"]][-50:],
            "stats": self.data["stats"],
            "missions": list(reversed(self.data["missions"][-30:])),
            "conversations": self.data["conversations"][-60:],
        }

    def public_settings(self):
        s = dict(self.settings)
        for k in ("groq_key", "gemini_key", "openrouter_key"):
            s[k] = "••••••" if s.get(k) else ""
            s[k + "_set"] = bool(self.settings.get(k))
        return s

    def context_for_llm(self):
        """خلاصه حافظه برای تزریق به پرامپت مغز"""
        parts = []
        name = self.user_name()
        if name:
            parts.append(f"اسم کاربر: {name}")
        facts = self.data["facts"][-12:]
        if facts:
            parts.append("چیزهایی که از کاربر به خاطر سپرده‌ای:\n" + "\n".join("- " + f["text"] for f in facts))
        return "\n".join(parts)
