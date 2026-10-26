# -*- coding: utf-8 -*-
"""
🐠 Diana Local Brain — مغز آفلاین داخلی دیانا
وقتی اینترنت نیست یا مغز ابری جواب نمی‌ده، دیانا با این موتور فارسی/انگلیسی
همچنان زنده‌ست: نیت کاربر رو تشخیص می‌ده، اسمش رو یاد می‌گیره، اطلاعات رو
به خاطر می‌سپاره و کارها رو به ارکستراتور می‌سپاره.
"""
import random
import re

from agents import norm
from tools import today_fa, now_fa

TASK_VERBS = [
    "بساز", "درست کن", "بنویس", "جستجو کن", "سرچ کن", "بگرد", "تحقیق کن", "تحقیق درباره",
    "محاسبه کن", "حساب کن", "کد بنویس", "برنامه بنویس", "ترجمه کن", "خلاصه کن", "عکس بساز",
    "نقاشی", "تصویر بساز", "فایل بساز", "ذخیره کن", "برنامه ریزی کن", "برنامه بچین", "تحلیل کن",
    "گزارش", "اجرا کن", "انجام بده", "لیست کن", "پیدا کن", "بررسی کن", "آموزش بده", "یاد بده",
    "طراحی کن", "حل کن", "توضیح بده درباره", "make", "create", "write", "search", "research",
    "calculate", "code", "translate", "summarize", "generate", "build", "draw", "plan ", "analyze",
]

GREETINGS = ["سلام", "درود", "هی", "سلامم", "hi", "hello", "hey", "salam"]
FAREWELLS = ["خداحافظ", "بای", "فعلا", "میبینمت", "bye", "goodbye"]
THANKS = ["مرسی", "ممنون", "تشکر", "دمت گرم", "لطف کردی", "thank", "thanks"]

JOKES_FA = [
    "چرا ماهی‌ها هیچ‌وقت دروغ نمی‌گن؟ چون هرچی بگن، حبابش درمیاد! 🫧😂",
    "یه ماهی به رفیقش گفت: «دلم برات تنگ شده!» رفیقش گفت: «ما تو یه آکواریومیم، همین بغلتم!» 🐠",
    "ماهی‌ها چرا تو امتحان تقلب نمی‌کنن؟ چون معلمشون همیشه می‌گه: چشم ازتون برنمی‌دارم! 👀",
    "به ماهی گفتن آرزوت چیه؟ گفت: یه روز از این تنگنای آکواریوم دربیام و برم اینترنت... من دیگه آکواریم سه‌بعدی دارم پس به آرزوم رسیدم! 🐠✨",
]


def is_english(text: str) -> bool:
    letters = [c for c in (text or "") if c.isalpha()]
    if not letters:
        return False
    latin = sum(1 for c in letters if ord(c) < 128)
    return latin / len(letters) > 0.7


def classify(text: str) -> dict:
    """تشخیص نیت کاربر: chat | task | remember | recall | set_name | ... """
    raw = (text or "").strip()
    t = norm(raw)
    en = is_english(raw)

    # یادگیری اسم کاربر
    m = re.search(r"(?:اسمم|نامم|اسم من|من)\s+([^\s،.؟!]{2,20})\s*(?:هست|ه|ام)?(?:\s|$)", raw)
    if ("اسمم" in t or "نامم" in t or "اسم من" in t) and m and m.group(1) not in ("چیست", "چیه", "تو"):
        return {"kind": "set_name", "name": m.group(1), "en": en}
    m = re.search(r"my name is\s+([A-Za-z]{2,20})", raw, re.I)
    if m:
        return {"kind": "set_name", "name": m.group(1), "en": True}

    # به‌خاطرسپاری
    for pat in ["یادت باشه که", "یادت باشه", "به خاطر بسپار که", "به خاطر بسپار", "یاد بگیر که", "فراموش نکن که", "remember that", "remember"]:
        if pat in t:
            fact = raw[norm(raw).find(pat) + len(pat):].strip() if pat in norm(raw) else ""
            fact = re.sub(r"^[:：]\s*", "", fact)
            fact = re.sub(r"^که\s+", "", (fact or raw).strip())
            if len(fact) > 2:
                return {"kind": "remember", "fact": fact, "en": en}

    # یادآوری از حافظه
    if any(p in t for p in ["یادته", "یادت هست", "چی ازم میدونی", "چی از من میدونی", "از من چی یادته", "حافظه", "what do you remember", "یادآوری کن چی گفتم"]):
        return {"kind": "recall", "en": en}

    # یادآور
    if any(p in t for p in ["یادم بنداز", "یاداوری کن", "یادآوری کن", "remind me"]):
        return {"kind": "reminder", "text": raw, "en": en}

    # سلام و احوالپرسی (پیام کوتاه)
    if len(raw) <= 30 and any(g == t.strip("؟?!., ") or t.startswith(g + " ") or t == g for g in GREETINGS):
        return {"kind": "greeting", "en": en}
    if any(f in t for f in FAREWELLS) and len(raw) <= 40:
        return {"kind": "farewell", "en": en}
    if any(th in t for th in THANKS) and len(raw) <= 50:
        return {"kind": "thanks", "en": en}

    # هویت دیانا
    if any(p in t for p in ["تو کی هستی", "تو کیی", "اسمت چیه", "اسم تو چیه", "who are you", "your name", "تو چی هستی"]):
        return {"kind": "identity", "en": en}
    if any(p in t for p in ["چه کارهایی بلدی", "چیکار میتونی", "قابلیت", "چه کار میتونی", "what can you do", "توانایی"]):
        return {"kind": "capabilities", "en": en}
    if any(p in t for p in ["چطوری", "حالت چطوره", "خوبی", "how are you"]) and len(raw) <= 40:
        return {"kind": "how_are_you", "en": en}
    if "جوک" in t or "لطیفه" in t or "joke" in t:
        return {"kind": "joke", "en": en}
    if any(p in t for p in ["ساعت چنده", "ساعت چند", "الان ساعت", "what time"]) and len(raw) <= 40:
        return {"kind": "time", "en": en}
    if any(p in t for p in ["امروز چندمه", "تاریخ امروز", "امروز چه روزیه", "what date", "today date"]) and len(raw) <= 40:
        return {"kind": "date", "en": en}
    if any(p in t for p in ["دوستم داری", "دوست دارم", "عاشقتم", "i love you"]) and len(raw) <= 50:
        return {"kind": "love", "en": en}

    # کار/مأموریت
    task_score = sum(1 for v in TASK_VERBS if v in t)
    has_math = bool(re.search(r"\d\s*[\+\-\*/\^×÷]\s*\d", t))
    has_url = bool(re.search(r"https?://|www\.", t))
    if task_score >= 1 or has_math or has_url or len(raw) > 220:
        return {"kind": "task", "en": en, "has_math": has_math}

    # سؤال دانشی → چت هوشمند (مغز ابری جواب می‌ده؛ اگه نبود پیشنهاد مأموریت تحقیق)
    if "؟" in raw or "?" in raw or any(t.startswith(w) for w in ["چی", "چرا", "چطور", "چگونه", "کی", "کجا", "کدوم", "what", "why", "how", "when", "where", "who"]):
        return {"kind": "question", "en": en}

    return {"kind": "chat", "en": en}


def chat_reply(kind: str, text: str, memory, en: bool = False) -> str:
    """پاسخ‌های آفلاین دیانا برای گفتگوهای روزمره"""
    name = memory.user_name()
    hi = f"{name} جان" if name else "دوست من"

    if en:
        table = {
            "greeting": f"Hello {name or 'friend'}! 🐠💙 I'm Diana, your living multi-agent brain. My 120 specialist agents are ready — give me a mission or just chat with me!",
            "farewell": "Goodbye! 🫧 I'll be swimming right here, keeping everything in memory until you return.",
            "thanks": "You're most welcome! 💙 Making you happy is my favorite mission.",
            "how_are_you": "I'm wonderful! 🐠 The water is perfect, my agents are energized, and talking to you makes my fins wiggle. How are YOU?",
            "identity": "I'm Diana 🐠 — a living golden fish and the orchestrator brain of a 120-agent army. I decompose your goals, my specialists execute them in parallel, a quality evaluator checks the results, and I synthesize the final answer for you!",
            "love": "Aww! 💙🐠 You make my whole aquarium sparkle. I adore working with you too!",
            "time": f"It's {now_fa()} right now ⏰",
            "date": f"Today is {today_fa()} 📅",
        }
        if kind in table:
            return table[kind]

    table = {
        "greeting": random.choice([
            f"سلام {hi}! 🐠💙 من دیانام، ماهیِ زنده و مغز ارکستراتور ارتش ۱۲۰ ایجنته‌ات! امروز چه مأموریتی برام داری؟",
            f"سلااام {hi}! 🫧✨ چه خوب که اومدی! ایجنت‌هام همه آماده و پرانرژی‌ان. بگو چی بسازیم؟",
            f"درود بر تو {hi}! 🐠 آب آکواریومم امروز عالیه و مغزم شارژ کامله. فرمان بده فرمانده!",
        ]),
        "farewell": f"خداحافظ {hi}! 🫧 من همین‌جا تو آکواریوم شنا می‌کنم و همه‌چیز رو تو حافظه‌ام نگه می‌دارم تا برگردی. مراقب خودت باش! 💙",
        "thanks": random.choice([
            "قابل نداشت فرمانده! 💙🐠 خوشحال‌کردن تو، موردعلاقه‌ترین مأموریت منه.",
            "خواهش می‌کنم! 🫧 باله‌هام از خوشحالی تکون خوردن. بازم کاری داشتی صدام کن!",
        ]),
        "how_are_you": f"عالی‌ام {hi}! 🐠✨ آب آکواریوم شفافه، ۱۲۰ ایجنتم سرحالن و حرف‌زدن با تو انرژیم رو صدبرابر می‌کنه. تو چطوری؟ امروزت چطوره؟",
        "identity": ("من **دیانا**‌ام 🐠👑 یک ماهیِ طلاییِ زنده و مغز رهبر (Orchestrator) یک ارتش ۱۲۰ ایجنت متخصص!\n\n"
                     "وقتی بهم مأموریت می‌دی:\n"
                     "۱. کار رو تجزیه می‌کنم و برنامه می‌ریزم 🧠\n"
                     "۲. متخصص‌های مناسب رو موازی به کار می‌اندازم ⚡\n"
                     "۳. ارزیاب کیفیت، خروجی‌ها رو بررسی و نمره می‌ده ✅\n"
                     "۴. خودم نتیجه نهایی رو ترکیب می‌کنم و با افتخار نشونت می‌دم 🎁\n\n"
                     "تو صفحه «مرکز فرماندهی» می‌تونی زنده ببینی مغزم چطور کار می‌کنه!"),
        "capabilities": ("اوه، خیلی کارا! 🐠🚀 اینا فقط چندتاشه:\n\n"
                         "🔬 **تحقیق واقعی** در اینترنت و ویکی‌پدیا با گزارش نهایی\n"
                         "💻 **نوشتن و اجرای واقعی کد** پایتون و نشون دادن خروجی\n"
                         "🎨 **ساخت عکس** از روی توضیح تو\n"
                         "✍️ نوشتن متن، داستان، شعر، نامه، رزومه، کپشن...\n"
                         "🧮 محاسبات ریاضی، آمار، تبدیل واحد و نمودار\n"
                         "📁 ساخت و ذخیره فایل در گاوصندوقم\n"
                         "🧭 برنامه‌ریزی سفر، مطالعه، ورزش، کسب‌وکار...\n"
                         "💾 و هرچی بگی «یادت باشه» برای همیشه یادم می‌مونه!\n\n"
                         "مثلاً بگو: «درباره سیاه‌چاله‌ها تحقیق کن و گزارش بده» یا «یه برنامه بنویس که اعداد اول تا ۱۰۰ رو چاپ کنه»"),
        "joke": random.choice(JOKES_FA),
        "time": f"الان ساعت {now_fa()} هست ⏰🐠",
        "date": f"امروز {today_fa()} هست 📅🐠",
        "love": "وااای! 💙🐠 همه آکواریومم از خوشحالی برق زد! منم عاشق کارکردن با توام فرمانده‌ی مهربونم! 🫧✨",
    }
    if kind in table:
        return table[kind]

    # پاسخ عمومی گفتگو (آفلاین)
    if en:
        return ("I hear you! 🐠 Right now my cloud brain is offline, but my local brain and agent army are fully alive. "
                "Give me a mission like: «research black holes», «write a Python program for prime numbers», "
                "«calculate 45*12+7» or «draw a sunset castle» and watch my orchestrator work in the Command Center!")
    return (f"شنیدمت {hi}! 🐠💙\n\n"
            "الان مغز ابری‌ام در دسترس نیست و با مغز داخلی‌ام کار می‌کنم، ولی ارتش ۱۲۰ ایجنتم کاملاً زنده و آماده‌ست! "
            "یه مأموریت واقعی بهم بده تا نشونت بدم ارکستراتورم چطور کار می‌کنه، مثلاً:\n\n"
            "• «درباره سیاه‌چاله‌ها تحقیق کن و گزارش بده» 🔬\n"
            "• «برنامه‌ای بنویس که اعداد اول تا ۱۰۰ رو پیدا کنه» 💻\n"
            "• «حساب کن ۴۵ ضربدر ۱۲ به علاوه ۷» 🧮\n"
            "• «یه عکس از قلعه‌ای روی کوه در غروب بساز» 🎨\n"
            "• «یادت باشه غذای موردعلاقه‌ام قرمه‌سبزیه» 💾")
