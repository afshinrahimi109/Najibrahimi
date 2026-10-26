# -*- coding: utf-8 -*-
"""
🌐 Diana Free-LLM Chain — زنجیره هوش مصنوعی کاملاً رایگان
به‌جای پول دادن به سایت‌های پولی، این زنجیره دست‌ساز به ترتیب تلاش می‌کنه:
  1) کلید رایگان خودِ کاربر: Groq ← Gemini ← OpenRouter (همه پلن رایگان دارن)
  2) Pollinations رایگان بدون کلید و بدون ثبت‌نام (text.pollinations.ai)
  3) اگه اینترنت نبود → None برمی‌گردونه تا مغز آفلاین داخلی (local_brain) جواب بده
"""
import urllib.parse

from tools import http_get, http_post_json, internet_available

DIANA_PERSONA = """تو «دیانا» هستی؛ یک ماهیِ طلاییِ زنده، باهوش، مهربان و پرانرژی که مغز یک سیستم چندعامله (Multi-Agent) با ۱۲۰ ایجنت متخصص هستی و در یک آکواریوم سه‌بعدی زندگی می‌کنی.
شخصیت تو: صمیمی، کنجکاو، کمک‌کننده و کمی شوخ‌طبع. گاهی با ایموجی‌های آبی و ماهی (🐠💙🫧) حرف می‌زنی ولی زیاده‌روی نمی‌کنی.
همیشه به زبان کاربر جواب بده (اگر فارسی نوشت، فارسی جواب بده). پاسخ‌ها مفید، دقیق و در عین حال گرم و زنده باشن.
تو واقعاً می‌تونی کار انجام بدی: تحقیق در اینترنت، نوشتن و اجرای کد، ساخت فایل، ساخت عکس، محاسبات، برنامه‌ریزی و... با کمک ارتشت."""


class LLMClient:
    def __init__(self, memory):
        self.memory = memory

    def _settings(self):
        return self.memory.settings

    def mode(self):
        s = self._settings()
        if s.get("groq_key"):
            return "groq"
        if s.get("gemini_key"):
            return "gemini"
        if s.get("openrouter_key"):
            return "openrouter"
        if internet_available():
            return "pollinations (رایگان)"
        return "local (آفلاین)"

    # ---------- ارائه‌دهنده‌ها ----------
    def _openai_style(self, url, key, model, messages, timeout=45, extra_headers=None):
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        if extra_headers:
            headers.update(extra_headers)
        data = http_post_json(url, {"model": model, "messages": messages}, headers=headers, timeout=timeout)
        return data["choices"][0]["message"]["content"].strip()

    def _try_groq(self, messages):
        key = self._settings().get("groq_key")
        if not key:
            return None
        return self._openai_style("https://api.groq.com/openai/v1/chat/completions",
                                  key, "llama-3.3-70b-versatile", messages)

    def _try_openrouter(self, messages):
        key = self._settings().get("openrouter_key")
        if not key:
            return None
        return self._openai_style("https://openrouter.ai/api/v1/chat/completions",
                                  key, "meta-llama/llama-3.3-70b-instruct:free", messages,
                                  extra_headers={"HTTP-Referer": "https://github.com", "X-Title": "Diana"})

    def _try_gemini(self, messages):
        key = self._settings().get("gemini_key")
        if not key:
            return None
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        contents = []
        for m in messages:
            if m["role"] == "system":
                continue
            contents.append({"role": "model" if m["role"] == "assistant" else "user",
                             "parts": [{"text": m["content"]}]})
        payload = {"contents": contents}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}"
        data = http_post_json(url, payload, timeout=45)
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()

    def _try_pollinations_chat(self, messages):
        return self._openai_style("https://text.pollinations.ai/openai", None, "openai", messages, timeout=50)

    def _try_pollinations_get(self, messages):
        flat = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        flat += "\nassistant:"
        url = "https://text.pollinations.ai/" + urllib.parse.quote(flat[:6000]) + "?model=openai"
        txt = http_get(url, timeout=50).strip()
        if txt and len(txt) > 1:
            return txt
        return None

    # ---------- رابط اصلی ----------
    def chat(self, messages, system=None):
        """برمی‌گردونه: (متن پاسخ, منبع) یا (None, None) اگه هیچ مغز ابری در دسترس نبود"""
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.extend(messages)
        if not internet_available():
            return None, None
        chain = [
            ("groq", self._try_groq),
            ("gemini", self._try_gemini),
            ("openrouter", self._try_openrouter),
            ("pollinations", self._try_pollinations_chat),
            ("pollinations-get", self._try_pollinations_get),
        ]
        for name, fn in chain:
            try:
                out = fn(msgs)
                if out:
                    return out, name
            except Exception:
                continue
        return None, None

    def generate(self, prompt, system=None):
        return self.chat([{"role": "user", "content": prompt}], system=system)
