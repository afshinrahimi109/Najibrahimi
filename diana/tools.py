# -*- coding: utf-8 -*-
"""
🛠️ Diana Tools — ابزارهای واقعی اجرایی دیانا
این‌ها «دست‌های» ایجنت‌ها هستن: کد واقعاً اجرا می‌شه، فایل واقعاً ساخته می‌شه،
وب واقعاً جستجو می‌شه و محاسبات واقعاً انجام می‌شن. هیچ‌کدوم نمایشی نیستن.
فقط با کتابخانه استاندارد پایتون — بدون نیاز به نصب هیچ‌چیز، روی هر هاست رایگان و ترموکس اجرا می‌شه.
"""
import ast
import html
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
VAULT_DIR = os.path.join(DATA_DIR, "vault")
SANDBOX_DIR = os.path.join(DATA_DIR, "sandbox")
os.makedirs(VAULT_DIR, exist_ok=True)
os.makedirs(SANDBOX_DIR, exist_ok=True)

UA = {"User-Agent": "DianaAgent/1.0 (Multi-Agent System; +https://github.com) Python-urllib"}

# ---------------- اینترنت ----------------
_net_cache = {"ok": None, "ts": 0}

def internet_available() -> bool:
    """بررسی سریع دسترسی سرور به اینترنت (کش ۳ دقیقه‌ای)"""
    now = time.time()
    if _net_cache["ok"] is not None and now - _net_cache["ts"] < 180:
        return _net_cache["ok"]
    try:
        req = urllib.request.Request("https://fa.wikipedia.org/w/api.php?action=query&format=json&meta=siteinfo", headers=UA)
        with urllib.request.urlopen(req, timeout=4) as r:
            ok = r.status == 200
    except Exception:
        ok = False
    _net_cache.update(ok=ok, ts=now)
    return ok

def http_get(url: str, timeout: int = 12) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    try:
        return raw.decode("utf-8", "replace")
    except Exception:
        return raw.decode("latin-1", "replace")

def http_post_json(url: str, payload: dict, headers: dict = None, timeout: int = 30) -> dict:
    data = json.dumps(payload).encode("utf-8")
    h = {"Content-Type": "application/json", **UA, **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def strip_html(page: str, limit: int = 6000) -> str:
    page = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"(?s)<!--.*?-->", " ", page)
    text = re.sub(r"(?s)<[^>]+>", " ", page)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]

# ---------------- جستجوی وب و ویکی‌پدیا ----------------
def wiki_search(query: str, lang: str = "fa", limit: int = 4) -> list:
    """جستجوی واقعی در ویکی‌پدیا و برگرداندن خلاصه مقالات"""
    results = []
    for lg in ([lang, "en"] if lang != "en" else ["en"]):
        try:
            api = (f"https://{lg}.wikipedia.org/w/api.php?action=query&format=json&prop=extracts"
                   f"&exintro=1&explaintext=1&generator=search&gsrsearch={urllib.parse.quote(query)}"
                   f"&gsrlimit={limit}&exsentences=4")
            data = json.loads(http_get(api, timeout=10))
            pages = (data.get("query") or {}).get("pages") or {}
            for p in pages.values():
                title = p.get("title", "")
                extract = (p.get("extract") or "").strip()
                if extract:
                    results.append({
                        "title": title,
                        "text": extract[:900],
                        "url": f"https://{lg}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
                        "source": f"ویکی‌پدیا ({lg})",
                    })
            if results:
                break
        except Exception:
            continue
    return results

def web_search(query: str, limit: int = 5) -> list:
    """جستجوی وب با DuckDuckGo نسخه سبک (بدون نیاز به کلید API)"""
    results = []
    try:
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
        page = http_get(url, timeout=12)
        items = re.findall(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>', page, re.S)
        for href, title, snippet in items[:limit]:
            m = re.search(r"uddg=([^&]+)", href)
            real = urllib.parse.unquote(m.group(1)) if m else href
            results.append({
                "title": strip_html(title, 200),
                "text": strip_html(snippet, 400),
                "url": real,
                "source": "جستجوی وب (DuckDuckGo)",
            })
    except Exception:
        pass
    return results

def fetch_url(url: str) -> dict:
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    page = http_get(url, timeout=15)
    title_m = re.search(r"(?is)<title[^>]*>(.*?)</title>", page)
    return {"url": url, "title": strip_html(title_m.group(1), 200) if title_m else url, "text": strip_html(page)}

def extract_url(text: str):
    m = re.search(r"(https?://[^\s)<>\"']+|www\.[^\s)<>\"']+)", text or "")
    return m.group(1) if m else None

# ---------------- اجرای واقعی کد ----------------
def run_python(code: str, timeout: int = 12) -> dict:
    """اجرای کد پایتون در زیرپردازه جدا با محدودیت زمان، در پوشه سندباکس"""
    fname = os.path.join(SANDBOX_DIR, f"job_{int(time.time()*1000)}.py")
    with open(fname, "w", encoding="utf-8") as f:
        f.write(code)
    try:
        p = subprocess.run([sys.executable, fname], capture_output=True, text=True,
                           timeout=timeout, cwd=SANDBOX_DIR)
        return {"ok": p.returncode == 0, "stdout": (p.stdout or "")[:8000],
                "stderr": (p.stderr or "")[-3000:], "code": code}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"⏱️ زمان اجرا تمام شد (بیش از {timeout} ثانیه)", "code": code}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e), "code": code}
    finally:
        try: os.remove(fname)
        except Exception: pass

def extract_code(text: str):
    """استخراج بلوک کد پایتون از متن"""
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", text or "", re.S)
    return m.group(1).strip() if m else None

# ---------------- ریاضی و داده ----------------
SAFE_FUNCS = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
SAFE_FUNCS.update({"abs": abs, "round": round, "min": min, "max": max, "sum": sum})

def safe_calc(expr: str):
    """ماشین‌حساب امن با پیمایش AST — بدون eval خطرناک"""
    expr = (expr or "").strip().replace("^", "**").replace("×", "*").replace("÷", "/").replace("−", "-").replace(",", "")
    fa_digits = "۰۱۲۳۴۵۶۷۸۹"
    for i, d in enumerate(fa_digits):
        expr = expr.replace(d, str(i))
    tree = ast.parse(expr, mode="eval")

    def ev(node):
        if isinstance(node, ast.Expression): return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)): return node.value
        if isinstance(node, ast.BinOp):
            a, b = ev(node.left), ev(node.right)
            ops = {ast.Add: a + b, ast.Sub: a - b, ast.Mult: a * b, ast.Div: a / b,
                   ast.Pow: a ** b, ast.Mod: a % b, ast.FloorDiv: a // b}
            if type(node.op) in ops: return ops[type(node.op)]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub): return -ev(node.operand)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in SAFE_FUNCS:
            return SAFE_FUNCS[node.func.id](*[ev(a) for a in node.args])
        if isinstance(node, ast.Name) and node.id in ("pi", "e", "tau"): return getattr(math, node.id)
        raise ValueError("عبارت پشتیبانی نمی‌شه")
    return ev(tree)

FA_OPERATORS = [
    (r"تقسیم\s*بر", "/"), (r"ضرب\s*در", "*"), (r"ضربدر", "*"), (r"به\s*علاوه", "+"),
    (r"به\s*اضافه", "+"), (r"منهای", "-"), (r"به\s*توان", "**"), (r"جذر\s*(?=\d)", "sqrt"),
]

def find_math_expr(text: str):
    """یافتن عبارت ریاضی داخل متن کاربر (با پشتیبانی عملگرهای فارسی مثل «ضربدر» و «به علاوه»)"""
    t = text or ""
    fa_digits = "۰۱۲۳۴۵۶۷۸۹"
    for i, d in enumerate(fa_digits):
        t = t.replace(d, str(i))
    for pat, sym in FA_OPERATORS:
        t = re.sub(pat, f" {sym} ", t)
    cands = re.findall(r"[\d\.\+\-\*/\(\)\^\s%]{3,}", t)
    best = None
    for c in cands:
        c = c.strip()
        if re.search(r"\d\s*[\+\-\*/\^%]\s*\d", c) or re.search(r"\d\s*\(", c):
            if best is None or len(c) > len(best):
                best = c
    if not best:
        m = re.search(r"(sqrt|sin|cos|tan|log|ln)\s*\(?([\d\.]+)\)?", t)
        if m:
            fn = {"ln": "log"}.get(m.group(1), m.group(1))
            best = f"{fn}({m.group(2)})"
    return best

UNITS = {
    ("km", "mile"): 0.621371, ("mile", "km"): 1.60934, ("kg", "lb"): 2.20462, ("lb", "kg"): 0.453592,
    ("m", "ft"): 3.28084, ("ft", "m"): 0.3048, ("cm", "inch"): 0.393701, ("inch", "cm"): 2.54,
    ("l", "gallon"): 0.264172, ("gallon", "l"): 3.78541, ("kmh", "mph"): 0.621371, ("mph", "kmh"): 1.60934,
    ("g", "oz"): 0.035274, ("oz", "g"): 28.3495,
}
UNIT_ALIASES = {"کیلومتر": "km", "مایل": "mile", "کیلوگرم": "kg", "کیلو": "kg", "پوند": "lb",
                "متر": "m", "فوت": "ft", "سانتی متر": "cm", "سانتیمتر": "cm", "اینچ": "inch",
                "لیتر": "l", "گالن": "gallon", "گرم": "g", "اونس": "oz"}

def convert_units(text: str):
    t = " " + (text or "").lower() + " "
    fa_digits = "۰۱۲۳۴۵۶۷۸۹"
    for i, d in enumerate(fa_digits):
        t = t.replace(d, str(i))
    m = re.search(r"([\d\.]+)\s*([a-z\u0600-\u06FF ]+?)\s*(?:به|to|→)\s*([a-z\u0600-\u06FF ]+)", t)
    if not m:
        return None
    val = float(m.group(1))
    src = UNIT_ALIASES.get(m.group(2).strip(), m.group(2).strip())
    dst = UNIT_ALIASES.get(m.group(3).strip(), m.group(3).strip())
    if ("c" in (src, dst) or "سانتیگراد" in t or "فارنهایت" in t):
        if "فارنهایت" in m.group(3) or dst == "f":
            return f"{val:g} درجه سانتی‌گراد = {val*9/5+32:g} درجه فارنهایت 🌡️"
        if "سانتی" in m.group(3) or dst == "c":
            return f"{val:g} درجه فارنهایت = {(val-32)*5/9:g} درجه سانتی‌گراد 🌡️"
    factor = UNITS.get((src, dst))
    if factor:
        return f"{val:g} {m.group(2).strip()} = {val*factor:,.4f} {m.group(3).strip()} ⚖️".rstrip("0").rstrip(".") if "." in f"{val*factor:,.4f}" else f"{val:g} {src} = {val*factor:g} {dst}"
    return None

def number_stats(text: str):
    fa_digits = "۰۱۲۳۴۵۶۷۸۹"
    t = text or ""
    for i, d in enumerate(fa_digits):
        t = t.replace(d, str(i))
    nums = [float(x) for x in re.findall(r"-?\d+\.?\d*", t)]
    if len(nums) < 2:
        return None
    nums_sorted = sorted(nums)
    n = len(nums)
    mean = sum(nums) / n
    median = nums_sorted[n // 2] if n % 2 else (nums_sorted[n//2 - 1] + nums_sorted[n//2]) / 2
    var = sum((x - mean) ** 2 for x in nums) / n
    return {
        "count": n, "sum": sum(nums), "mean": mean, "median": median,
        "min": min(nums), "max": max(nums), "range": max(nums) - min(nums),
        "stdev": math.sqrt(var), "numbers": nums,
    }

def text_chart(nums, width=34):
    """نمودار میله‌ای متنی"""
    if not nums:
        return ""
    mx = max(abs(x) for x in nums) or 1
    lines = []
    for i, v in enumerate(nums[:20], 1):
        bar = "█" * max(1, int(abs(v) / mx * width))
        lines.append(f"{i:>3} │ {bar} {v:g}")
    return "\n".join(lines)

# ---------------- پردازش متن آفلاین ----------------
STOPWORDS = set("است هست بود باشد می شود شد این آن که را به از در با بر برای تا نیز هم یا و اگر اما چون چه هر یک دو سه خود ما شما او ایشان من تو شده است شده اند کرد کند کنند دارد دارند بود خواهد باید بین پس پیش روی زیر بالا شود می‌کند می‌شود".split())

def summarize_text(text: str, max_sentences: int = 5) -> str:
    """خلاصه‌سازی استخراجی: امتیازدهی به جمله‌ها بر اساس فراوانی واژه‌های کلیدی"""
    text = re.sub(r"\s+", " ", (text or "")).strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.!؟?۔])\s+", text) if len(s.strip()) > 15]
    if len(sentences) <= max_sentences:
        return text[:2500]
    freq = {}
    for w in re.findall(r"[\w‌]{3,}", text):
        if w not in STOPWORDS:
            freq[w] = freq.get(w, 0) + 1
    scored = []
    for i, s in enumerate(sentences):
        words = re.findall(r"[\w‌]{3,}", s)
        score = sum(freq.get(w, 0) for w in words) / (len(words) + 3)
        if i < 2:
            score *= 1.4
        scored.append((score, i, s))
    top = sorted(scored, key=lambda x: -x[0])[:max_sentences]
    return " ".join(s for _, _, s in sorted(top, key=lambda x: x[1]))

def text_stats(text: str) -> dict:
    text = text or ""
    words = re.findall(r"[\w‌]+", text)
    sentences = [s for s in re.split(r"[.!؟?]+", text) if s.strip()]
    freq = {}
    for w in words:
        if len(w) > 2 and w not in STOPWORDS:
            freq[w] = freq.get(w, 0) + 1
    top = sorted(freq.items(), key=lambda x: -x[1])[:8]
    return {
        "chars": len(text), "words": len(words), "sentences": len(sentences),
        "reading_minutes": max(1, round(len(words) / 180)),
        "top_words": top,
        "unique_words": len(set(words)),
    }

def extract_subject_text(instruction: str) -> str:
    """استخراج متن اصلی از دستور کاربر (داخل نقل‌قول، بعد از «متن:» یا کل متن طولانی)"""
    t = instruction or ""
    m = re.search(r"[«\"](.+?)[»\"]", t, re.S)
    if m and len(m.group(1)) > 30:
        return m.group(1)
    m = re.search(r"(?:متن|مقاله|نامه)[:：]\s*(.+)", t, re.S)
    if m and len(m.group(1)) > 30:
        return m.group(1)
    return t if len(t) > 120 else ""

# ---------------- گاوصندوق فایل‌ها ----------------
def safe_name(name: str) -> str:
    name = os.path.basename((name or "file.txt").strip())
    name = re.sub(r"[\x00-\x1f<>:\\/|?*]", "_", name) or "file.txt"
    return name[:120]

def vault_write(name: str, content: str) -> str:
    name = safe_name(name)
    path = os.path.join(VAULT_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content or "")
    return name

def vault_read(name: str):
    path = os.path.join(VAULT_DIR, safe_name(name))
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()

def vault_list():
    items = []
    for fn in sorted(os.listdir(VAULT_DIR)):
        p = os.path.join(VAULT_DIR, fn)
        if os.path.isfile(p):
            items.append({"name": fn, "size": os.path.getsize(p),
                          "modified": datetime.fromtimestamp(os.path.getmtime(p)).strftime("%Y-%m-%d %H:%M")})
    return items

def vault_delete(name: str) -> bool:
    path = os.path.join(VAULT_DIR, safe_name(name))
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False

# ---------------- تصویر و سیستم ----------------
def image_url(prompt_en: str, seed: int = None) -> str:
    """ساخت تصویر رایگان با Pollinations — بدون کلید، بدون ثبت‌نام"""
    seed = seed if seed is not None else int(time.time()) % 100000
    q = urllib.parse.quote(prompt_en.strip()[:300])
    return f"https://image.pollinations.ai/prompt/{q}?width=1024&height=1024&seed={seed}&nologo=true"

def system_info() -> dict:
    import shutil
    du = shutil.disk_usage(DATA_DIR)
    return {
        "platform": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "machine": platform.machine(),
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "disk_free_gb": round(du.free / 1e9, 2),
        "disk_total_gb": round(du.total / 1e9, 2),
        "internet": internet_available(),
        "vault_files": len(vault_list()),
    }

def now_fa() -> str:
    return datetime.now().strftime("%H:%M:%S")

def today_fa() -> str:
    return datetime.now().strftime("%Y/%m/%d")
