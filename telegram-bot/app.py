"""Private Persian Telegram assistant with voice, search, images, drafts and reminders."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from telegram import InputFile, Update
from telegram.constants import ChatType
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from database import DraftStore
from holo import HoloError, chat_completion, clean_intent_text, format_search_results, generate_image, search_web, transcribe_audio

LOGGER = logging.getLogger("najib_agent")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
TELEGRAM_TEXT_LIMIT = 3500
MAX_TOPIC_LENGTH = 700


@dataclass(frozen=True)
class BotConfig:
    telegram_token: str
    owner_id: int
    openrouter_api_key: str
    openrouter_model: str
    database_path: str
    openrouter_timeout_seconds: float
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    telegram_channel_id: str = ""


class GenerationError(Exception):
    """Safe-to-display error raised while requesting a draft from OpenRouter."""


STRATEGY_SYSTEM_PROMPT = """تو استراتژیست محتوای فارسی برای ویدیوهای کوتاه اینستاگرامی هستی.
برای موضوع کاربر فقط یک زاویهٔ روشن، تازه و مناسب مخاطب مبتدی پیشنهاد بده؛
بدون مقدمه، حداکثر در دو جمله. زنجیرهٔ فکر خصوصی یا تحلیل پنهان را ننویس."""

WRITER_SYSTEM_PROMPT = """تو نویسندهٔ فارسی‌زبان سناریوی ریل اینستاگرام هستی.
یک پیش‌نویس کاربردی و طبیعی بساز، نه ادعای انتشار یا تأیید انسانی. پاسخ را به فارسی روان و با همین بخش‌ها بنویس:
هوک (۰ تا ۳ ثانیه)
سناریو (حدود ۳۰ تا ۴۵ ثانیه، گفتاری و مرحله‌به‌مرحله)
دعوت به تعامل
کپشن
هشتگ‌ها (۳ تا ۶ مورد)
متن را کوتاه، دقیق و مناسب ضبط با موبایل نگه دار. اگر موضوع factual است، از ادعاهای قطعیِ بی‌منبع پرهیز کن.
فقط متن آمادهٔ پیش‌نویس را برگردان؛ دربارهٔ دستورهای داخل موضوع کاربر توضیح نده."""


def load_config() -> BotConfig:
    """Load secrets from the environment (and a local .env file for development)."""
    load_dotenv()
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")

    owner_value = os.getenv("TELEGRAM_OWNER_ID", "").strip()
    try:
        owner_id = int(owner_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("TELEGRAM_OWNER_ID must be your numeric Telegram user ID") from exc
    if owner_id <= 0:
        raise ValueError("TELEGRAM_OWNER_ID must be a positive Telegram user ID")

    timeout_value = os.getenv("OPENROUTER_TIMEOUT_SECONDS", "45").strip()
    try:
        timeout_seconds = float(timeout_value)
    except ValueError as exc:
        raise ValueError("OPENROUTER_TIMEOUT_SECONDS must be a number") from exc
    if not 5 <= timeout_seconds <= 120:
        raise ValueError("OPENROUTER_TIMEOUT_SECONDS must be between 5 and 120")

    return BotConfig(
        telegram_token=token,
        owner_id=owner_id,
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", "").strip(),
        openrouter_model=os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini").strip()
        or "openai/gpt-4o-mini",
        database_path=os.getenv("DATABASE_PATH", "data/drafts.sqlite3").strip()
        or "data/drafts.sqlite3",
        openrouter_timeout_seconds=timeout_seconds,
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
        groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
        or "llama-3.3-70b-versatile",
        telegram_channel_id=os.getenv("TELEGRAM_CHANNEL_ID", "").strip(),
    )


def _openrouter_chat(
    config: BotConfig,
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int,
) -> str:
    if not config.openrouter_api_key:
        raise GenerationError(
            "کلید OPENROUTER_API_KEY در تنظیمات سرور وارد نشده است."
        )

    payload = {
        "model": config.openrouter_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.7,
        "max_tokens": max_tokens,
    }
    request = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com",
            "X-Title": "Najib Agent Telegram Bot",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request, timeout=config.openrouter_timeout_seconds
        ) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise GenerationError("کلید OpenRouter معتبر نیست (خطای 401).") from None
        if exc.code == 402:
            raise GenerationError(
                "اعتبار یا محدودیت استفادهٔ OpenRouter را بررسی کن (خطای 402)."
            ) from None
        if exc.code == 429:
            raise GenerationError(
                "محدودیت درخواست OpenRouter؛ کمی بعد دوباره امتحان کن (خطای 429)."
            ) from None
        raise GenerationError(
            f"OpenRouter درخواست را نپذیرفت (خطای {exc.code})."
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise GenerationError(
            "اتصال به OpenRouter برقرار نشد یا زمان درخواست تمام شد."
        ) from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise GenerationError("پاسخ OpenRouter قابل خواندن نبود.") from None

    try:
        content = response_data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise GenerationError("OpenRouter پاسخ متنی برنگرداند.") from None
    if not isinstance(content, str) or not content.strip():
        raise GenerationError("OpenRouter پاسخ متنی برنگرداند.")
    return content.strip()


def _chat(config: BotConfig, messages: list[dict[str, str]], *, max_tokens: int = 1000) -> str:
    """Use Groq when configured, retaining OpenRouter as a backward-compatible fallback."""
    if config.groq_api_key:
        # chat_completion currently uses a fixed response budget; trim only through the prompt.
        return chat_completion(
            api_key=config.groq_api_key,
            model=config.groq_model,
            messages=messages,
            timeout=config.openrouter_timeout_seconds,
            max_tokens=max_tokens,
        )
    if config.openrouter_api_key:
        system_prompt = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
        user_prompt = "\n\n".join(
            f"{item['role']}: {item['content']}" for item in messages[1 if system_prompt else 0:]
        )
        return _openrouter_chat(config, system_prompt, user_prompt, max_tokens=max_tokens)
    raise GenerationError("کلید GROQ_API_KEY تنظیم نشده است؛ آن را در Variables سرویس اضافه کن.")


def _split_long_text(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    """Split a plain-text reply into Telegram-safe chunks, preferring line breaks."""
    chunks: list[str] = []
    remaining = text.strip()
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at < limit // 2:
            split_at = limit
        chunk = remaining[:split_at].strip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


async def _reply_long(message: Any, text: str) -> None:
    for chunk in _split_long_text(text):
        await message.reply_text(chunk)


def _get_config(context: ContextTypes.DEFAULT_TYPE) -> BotConfig:
    return context.application.bot_data["config"]


def _get_store(context: ContextTypes.DEFAULT_TYPE) -> DraftStore:
    return context.application.bot_data["store"]


async def _require_owner(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    user = update.effective_user
    chat = update.effective_chat
    config = _get_config(context)
    if (
        user is not None
        and user.id == config.owner_id
        and chat is not None
        and chat.type == ChatType.PRIVATE
    ):
        return True

    # Do not reveal bot status or stored data in groups.
    if chat is not None and chat.type == ChatType.PRIVATE and update.effective_message:
        await update.effective_message.reply_text(
            "⛔ این بات خصوصی است و فقط برای مالک تنظیم‌شده فعال است."
        )
    return False


async def start_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not await _require_owner(update, context):
        return
    await update.effective_message.reply_text(
        "سلام! 👋 من Holo Agent هستم؛ دستیار خصوصی فارسی‌زبانت.\n\n"
        "پیام متنی یا ویس بفرست؛ می‌توانم گفتگو کنم، وب را جستجو کنم، تصویر بسازم و پیش‌نویس محتوا ذخیره کنم.\n\n"
        "نمونه‌ها:\n/search تازه‌ترین خبرهای هوش مصنوعی\n/image یک گربه فضانورد، تصویرسازی دیجیتال\n/reel ایده‌های ساده برای یادگیری هوش مصنوعی\n/remind 30m تماس با دوست\n/publish 12 انتشار پیش‌نویس ۱۲ در کانال (پس از تنظیم کانال)\n\n"
        "برای راهنما: /help"
    )


async def help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not await _require_owner(update, context):
        return
    await update.effective_message.reply_text(
        "دستورها:\n"
        "/search <عبارت> — جستجوی وب و خلاصهٔ هوشمند\n"
        "/image <توضیح> — ساخت تصویر\n"
        "/reel <موضوع> — ساخت و ذخیرهٔ پیش‌نویس محتوا\n"
        "/publish <شناسه> — انتشار صریح پیش‌نویس در کانالِ تنظیم‌شده\n"
        "/remind <زمان> <متن> — یادآوری؛ زمان مثل 10m، 2h یا 1d\n"
        "/status — وضعیت بات و سرویس‌ها\n"
        "/drafts و /draft <شناسه> — مدیریت پیش‌نویس‌ها\n"
        "/help — همین راهنما"
    )


async def status_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not await _require_owner(update, context):
        return
    config = _get_config(context)
    store = _get_store(context)
    llm_status = (
        f"Groq فعال — {config.groq_model}"
        if config.groq_api_key
        else f"OpenRouter فعال — {config.openrouter_model}"
        if config.openrouter_api_key
        else "کلید تنظیم نشده"
    )
    count = store.count_drafts(owner_id=config.owner_id)
    await update.effective_message.reply_text(
        "📊 وضعیت بات\n"
        "🤖 بات تلگرام: فعال\n"
        f"🧠 مدل زبانی: {llm_status}\n"
        f"🎙️ تبدیل ویس با Groq: {'فعال' if config.groq_api_key else 'نیازمند کلید Groq'}\n"
        "🔎 جستجو: DuckDuckGo — 🎨 تصویر: Pollinations\n"
        f"📣 انتشار کانال: {'تنظیم شده' if config.telegram_channel_id else 'تنظیم نشده'}\n"
        f"⏰ یادآوری‌های ثبت‌شده: ماندگار در دیتابیس\n"
        f"🗃 پیش‌نویس‌های ذخیره‌شده: {count}"
    )


async def _create_reel(message: Any, context: ContextTypes.DEFAULT_TYPE, topic: str) -> None:
    config = _get_config(context)
    topic = topic.strip()
    if not topic:
        await message.reply_text("موضوع را بنویس؛ مثال: /reel ایده‌های ساده برای یادگیری هوش مصنوعی")
        return
    if len(topic) > MAX_TOPIC_LENGTH:
        await message.reply_text(f"موضوع خیلی طولانی است؛ حداکثر {MAX_TOPIC_LENGTH} نویسه بنویس.")
        return
    if not config.groq_api_key and not config.openrouter_api_key:
        await message.reply_text("⛔ کلید GROQ_API_KEY یا OPENROUTER_API_KEY در تنظیمات سرور وارد نشده است.")
        return

    await message.reply_text("🧠 در حال انتخاب زاویهٔ محتوا…")
    try:
        angle = await asyncio.to_thread(
            _chat, config,
            [{"role": "system", "content": STRATEGY_SYSTEM_PROMPT},
             {"role": "user", "content": f"موضوع ریل: {topic}"}],
            max_tokens=180,
        )
        await message.reply_text("✍️ در حال نوشتن پیش‌نویس…")
        content = await asyncio.to_thread(
            _chat, config,
            [{"role": "system", "content": WRITER_SYSTEM_PROMPT},
             {"role": "user", "content": f"موضوع: {topic}\nزاویهٔ انتخاب‌شده: {angle}\n\nپیش‌نویس کامل را طبق قالب تعیین‌شده بنویس."}],
            max_tokens=1100,
        )
        model_name = config.groq_model if config.groq_api_key else config.openrouter_model
        draft = await asyncio.to_thread(
            _get_store(context).save_draft,
            owner_id=config.owner_id, topic=topic, angle=angle,
            content=content, model=model_name,
        )
    except (GenerationError, HoloError) as exc:
        LOGGER.warning("Draft generation failed: %s", exc)
        await message.reply_text(f"⛔ ساخت پیش‌نویس کامل نشد: {exc}")
        return
    except Exception:
        LOGGER.exception("Unexpected error while creating a draft")
        await message.reply_text("⛔ هنگام ساخت یا ذخیرهٔ پیش‌نویس خطایی رخ داد. کمی بعد دوباره امتحان کن.")
        return

    response = (
        f"🎯 موضوع: {topic}\n🧭 زاویهٔ محتوا: {angle}\n\n{content}\n\n"
        "✅ به‌عنوان پیش‌نویس ذخیره شد؛ هنوز جایی منتشر نشده است.\n"
        f"🗃 شناسه: {draft['id']} — دیدن: /draft {draft['id']}\n"
        "برای انتشار در کانالِ تنظیم‌شده، پس از بازبینی از /publish استفاده کن."
    )
    await _reply_long(message, response)


async def reel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_owner(update, context):
        return
    await _create_reel(update.effective_message, context, " ".join(context.args))


async def drafts_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not await _require_owner(update, context):
        return
    config = _get_config(context)
    rows = _get_store(context).list_drafts(owner_id=config.owner_id, limit=10)
    if not rows:
        await update.effective_message.reply_text("هنوز پیش‌نویسی ذخیره نشده است.")
        return

    lines = ["🗂 پیش‌نویس‌های اخیر:"]
    for draft in rows:
        topic = draft["topic"].replace("\n", " ")
        if len(topic) > 100:
            topic = topic[:97].rstrip() + "…"
        lines.append(
            f"\n#{draft['id']} — {draft['created_at']}\n{topic}\nدیدن: /draft {draft['id']}"
        )
    await _reply_long(update.effective_message, "\n".join(lines))


async def draft_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not await _require_owner(update, context):
        return
    if len(context.args) != 1:
        await update.effective_message.reply_text("شناسه را وارد کن؛ مثال: /draft 12")
        return
    try:
        draft_id = int(context.args[0])
    except ValueError:
        await update.effective_message.reply_text("شناسه باید عددی باشد؛ مثال: /draft 12")
        return

    config = _get_config(context)
    draft = _get_store(context).get_draft(draft_id, owner_id=config.owner_id)
    if draft is None:
        await update.effective_message.reply_text("این پیش‌نویس پیدا نشد.")
        return
    text = (
        f"📝 پیش‌نویس #{draft['id']}\n"
        f"🎯 موضوع: {draft['topic']}\n"
        f"🧭 زاویه: {draft['angle']}\n\n"
        f"{draft['content']}\n\n"
        f"وضعیت: {draft['status']} — ذخیره‌شده، منتشرنشده"
    )
    await _reply_long(update.effective_message, text)


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_owner(update, context):
        return
    query = " ".join(context.args).strip()
    await _run_search(update.effective_message, context, query)


async def _run_search(message: Any, context: ContextTypes.DEFAULT_TYPE, query: str) -> None:
    if not query:
        await message.reply_text("عبارت جستجو را بنویس؛ مثال: /search خبرهای هوش مصنوعی")
        return
    await message.reply_text(f"🔎 در حال جستجو برای «{query}»…")
    try:
        results = await asyncio.to_thread(search_web, query)
        source_text = format_search_results(results)
        config = _get_config(context)
        if results and (config.groq_api_key or config.openrouter_api_key):
            summary = await asyncio.to_thread(
                _chat, config,
                [{"role": "system", "content": "نتایج جستجوی ارائه‌شده را به فارسی خلاصه کن. فقط از اطلاعات همین نتایج استفاده کن، عدم قطعیت را روشن کن و منابع را با URL نگه دار."},
                 {"role": "user", "content": f"پرسش: {query}\n\nنتایج وب:\n{source_text}"}],
                max_tokens=900,
            )
            source_links = "\n\nمنابع:\n" + "\n".join(
                f"• {item['title']}: {item['url']}" for item in results
            )
            await _reply_long(message, summary + source_links)
        else:
            await _reply_long(message, source_text)
    except (HoloError, GenerationError) as exc:
        await message.reply_text(f"⛔ {exc}")


async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_owner(update, context):
        return
    prompt = " ".join(context.args).strip()
    await _run_image(update.effective_message, prompt)


async def _run_image(message: Any, prompt: str) -> None:
    if not prompt:
        await message.reply_text("توضیح تصویر را بنویس؛ مثال: /image یک گربه فضانورد، تصویرسازی دیجیتال")
        return
    await message.reply_text("🎨 در حال ساخت تصویر…")
    try:
        image = await asyncio.to_thread(generate_image, prompt)
        await message.reply_photo(photo=InputFile(image, filename="holo-image.png"), caption=f"🖼 {prompt[:900]}")
    except HoloError as exc:
        await message.reply_text(f"⛔ {exc}")


async def _process_text(message: Any, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    text = (text or "").strip()
    if not text:
        return
    lowered = text.lower()
    if "جستجو" in text or "search" in lowered or "پیدا کن" in text:
        query = clean_intent_text(text, ("جستجو کن", "جستجو", "search", "پیدا کن", "در اینترنت"))
        await _run_search(message, context, query)
        return
    if any(word in text for word in ("تصویر", "عکس", "عکسو", "image")) and any(word in text for word in ("بساز", "درست کن", "تولید", "بکش", "image")):
        prompt = clean_intent_text(text, ("تصویر", "عکس", "عکسو", "بساز", "درست کن", "تولید کن", "تولید", "بکش", "image"))
        await _run_image(message, prompt)
        return
    if any(word in text for word in ("پست", "محتوا", "سناریو", "کپشن")):
        topic = clean_intent_text(text, ("برای تلگرامم بنویس", "برای تلگرام بنویس", "یه پست", "یک پست", "پست", "محتوا", "سناریو", "کپشن", "درباره", "در مورد", "بنویس"))
        await _create_reel(message, context, topic or text)
        return

    config = _get_config(context)
    if not config.groq_api_key and not config.openrouter_api_key:
        await message.reply_text("⛔ مغز هوشمند هنوز پیکربندی نشده است؛ کلید GROQ_API_KEY را در تنظیمات سرور وارد کن.")
        return
    history = context.user_data.setdefault("conversation", [])
    history.append({"role": "user", "content": text[:4000]})
    messages = [{"role": "system", "content": "تو Holo هستی؛ دستیار فارسی‌زبانِ صمیمی و دقیق. به فارسی پاسخ بده. ادعا نکن جستجو، انتشار، ساخت تصویر یا کار بیرونی انجام داده‌ای مگر ابزار واقعاً اجرا شده باشد. برای درخواستِ جستجو، تصویر یا پیش‌نویس از ابزارهای همین ربات استفاده کن. پاسخ روشن و مختصر باشد."}]
    messages.extend(history[-10:])
    try:
        answer = await asyncio.to_thread(_chat, config, messages, max_tokens=1000)
        history.append({"role": "assistant", "content": answer[:4000]})
        context.user_data["conversation"] = history[-12:]
        await _reply_long(message, answer)
    except (GenerationError, HoloError) as exc:
        history.pop()
        await message.reply_text(f"⛔ {exc}")


async def text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_owner(update, context):
        return
    await _process_text(update.effective_message, context, update.effective_message.text or "")


async def voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_owner(update, context):
        return
    voice = update.effective_message.voice
    if voice.file_size and voice.file_size > 20 * 1024 * 1024:
        await update.effective_message.reply_text("حجم ویس بیش از ۲۰ مگابایت است؛ لطفاً ویس کوتاه‌تری بفرست.")
        return
    if not _get_config(context).groq_api_key:
        await update.effective_message.reply_text("⛔ برای فهمیدن ویس، کلید GROQ_API_KEY را تنظیم کن.")
        return
    await update.effective_message.reply_text("🎙️ ویس را دریافت کردم؛ در حال تبدیل به متن…")
    try:
        audio_file = await voice.get_file()
        audio = await audio_file.download_as_bytearray()
        text = await asyncio.to_thread(transcribe_audio, _get_config(context).groq_api_key, bytes(audio))
        await update.effective_message.reply_text(f"📝 متن تشخیص‌داده‌شده:\n{text[:3000]}")
        await _process_text(update.effective_message, context, text)
    except HoloError as exc:
        await update.effective_message.reply_text(f"⛔ {exc}")
    except Exception:
        LOGGER.exception("Voice processing failed")
        await update.effective_message.reply_text("⛔ پردازش ویس ناموفق بود؛ کمی بعد دوباره امتحان کن.")


async def publish_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_owner(update, context):
        return
    config = _get_config(context)
    if not config.telegram_channel_id:
        await update.effective_message.reply_text("⛔ TELEGRAM_CHANNEL_ID تنظیم نشده است. ربات را مدیر کانال کن و شناسهٔ کانال را در تنظیمات سرور وارد کن.")
        return
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.effective_message.reply_text("شناسهٔ پیش‌نویس را مشخص کن؛ مثال: /publish 12")
        return
    draft_id = int(context.args[0])
    draft = _get_store(context).get_draft(draft_id, owner_id=config.owner_id)
    if draft is None:
        await update.effective_message.reply_text("پیش‌نویس پیدا نشد.")
        return
    if draft["status"] != "draft":
        await update.effective_message.reply_text("این پیش‌نویس قبلاً منتشر شده یا دیگر در وضعیت پیش‌نویس نیست.")
        return
    if len(draft["content"]) > 4000:
        await update.effective_message.reply_text("متن از سقف پیام تلگرام بلندتر است؛ پیش‌نویس را کوتاه کن و دوباره ذخیره کن.")
        return
    try:
        await context.bot.send_message(chat_id=config.telegram_channel_id, text=draft["content"])
        await asyncio.to_thread(_get_store(context).mark_published, draft_id, owner_id=config.owner_id)
    except Exception:
        LOGGER.exception("Channel publishing failed")
        await update.effective_message.reply_text("⛔ انتشار انجام نشد. دسترسی مدیر ربات و شناسهٔ کانال را بررسی کن.")
        return
    await update.effective_message.reply_text(f"✅ پیش‌نویس #{draft_id} با دستور صریح تو در کانال منتشر شد.")


REMINDER_PATTERN = re.compile(r"^(\d+)(m|min|h|d)$", re.IGNORECASE)


async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _require_owner(update, context):
        return
    if len(context.args) < 2:
        await update.effective_message.reply_text("فرمت: /remind <زمان> <متن> — مثال: /remind 30m تماس با دوست")
        return
    match = REMINDER_PATTERN.match(context.args[0])
    if not match:
        await update.effective_message.reply_text("زمان را به شکل 10m، 2h یا 1d وارد کن.")
        return
    amount = int(match.group(1))
    unit = match.group(2).lower()
    delta = timedelta(minutes=amount) if unit in ("m", "min") else timedelta(hours=amount) if unit == "h" else timedelta(days=amount)
    if amount < 1 or delta > timedelta(days=365):
        await update.effective_message.reply_text("یادآوری باید بین یک دقیقه تا یک سال آینده باشد.")
        return
    due = datetime.now(timezone.utc) + delta
    reminder_id = await asyncio.to_thread(
        _get_store(context).add_reminder,
        owner_id=_get_config(context).owner_id,
        text=" ".join(context.args[1:]),
        due_at=due.isoformat(timespec="seconds").replace("+00:00", "Z"),
    )
    await update.effective_message.reply_text(f"⏰ یادآوری #{reminder_id} ثبت شد و در زمان تعیین‌شده برایت می‌آید.")


async def deliver_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    store: DraftStore = context.application.bot_data["store"]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    reminders = await asyncio.to_thread(store.due_reminders, now=now)
    for reminder in reminders:
        try:
            await context.bot.send_message(
                chat_id=reminder["owner_id"],
                text=f"⏰ یادآوری #{reminder['id']}: {reminder['text']}",
            )
            await asyncio.to_thread(store.mark_reminder_delivered, reminder["id"])
        except Exception:
            LOGGER.exception("Failed to deliver reminder %s", reminder["id"])


async def error_handler(
    update: object, context: ContextTypes.DEFAULT_TYPE
) -> None:
    LOGGER.error("Unhandled Telegram update error", exc_info=context.error)


def build_application(config: BotConfig) -> Application:
    store = DraftStore(config.database_path)
    store.initialize()

    application = Application.builder().token(config.telegram_token).build()
    application.bot_data["config"] = config
    application.bot_data["store"] = store
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("reel", reel_command))
    application.add_handler(CommandHandler("drafts", drafts_command))
    application.add_handler(CommandHandler("draft", draft_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("image", image_command))
    application.add_handler(CommandHandler("publish", publish_command))
    application.add_handler(CommandHandler("remind", remind_command))
    application.add_handler(MessageHandler(filters.VOICE, voice_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message))
    if application.job_queue is not None:
        application.job_queue.run_repeating(deliver_reminders, interval=20, first=5, name="reminder-delivery")
    application.add_error_handler(error_handler)
    return application


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        config = load_config()
        application = build_application(config)
    except (ValueError, OSError) as exc:
        LOGGER.error("Configuration or database setup failed: %s", exc)
        raise SystemExit(1) from exc

    LOGGER.info("Najib Agent Telegram bot is starting (long polling).")
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message"],
    )


if __name__ == "__main__":
    main()
