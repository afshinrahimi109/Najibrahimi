"""Private Telegram bot that creates and stores Persian Instagram Reel drafts."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatType
from telegram.ext import Application, CommandHandler, ContextTypes

from database import DraftStore

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
        "سلام! 👋\n"
        "من پیش‌نویس ریل فارسی می‌سازم و آن را برایت ذخیره می‌کنم.\n\n"
        "برای شروع:\n/reel چهار مسیر شغلی در هوش مصنوعی برای افراد مبتدی\n\n"
        "برای راهنما: /help"
    )


async def help_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not await _require_owner(update, context):
        return
    await update.effective_message.reply_text(
        "دستورها:\n"
        "/reel <موضوع> — ساخت و ذخیرهٔ پیش‌نویس ریل\n"
        "/status — وضعیت بات، مدل و اتصال اینستاگرام\n"
        "/drafts — نمایش پیش‌نویس‌های اخیر\n"
        "/draft <شناسه> — دیدن یک پیش‌نویس ذخیره‌شده\n"
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
        f"کلید تنظیم شده — {config.openrouter_model}"
        if config.openrouter_api_key
        else "کلید تنظیم نشده"
    )
    count = store.count_drafts(owner_id=config.owner_id)
    await update.effective_message.reply_text(
        "📊 وضعیت بات\n"
        "🤖 بات تلگرام: فعال\n"
        f"🧠 OpenRouter: {llm_status}\n"
        f"🗃 پیش‌نویس‌های ذخیره‌شده: {count}\n"
        "📸 اتصال رسمی اینستاگرام: انجام نشده"
    )


async def reel_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    if not await _require_owner(update, context):
        return

    message = update.effective_message
    config = _get_config(context)
    topic = " ".join(context.args).strip()
    if not topic:
        await message.reply_text(
            "موضوع را بعد از دستور بنویس؛ مثلاً:\n"
            "/reel چهار مسیر شغلی در هوش مصنوعی برای افراد مبتدی"
        )
        return
    if len(topic) > MAX_TOPIC_LENGTH:
        await message.reply_text(
            f"موضوع خیلی طولانی است؛ لطفاً آن را به کمتر از {MAX_TOPIC_LENGTH} نویسه برسان."
        )
        return
    if not config.openrouter_api_key:
        await message.reply_text(
            "⛔ کلید OPENROUTER_API_KEY تنظیم نشده است؛ آن را در Variables سرویس Railway اضافه کن."
        )
        return

    await message.reply_text("🧠 مغز سیستم شروع کرد…")
    await message.reply_text("🧭 مغز سیستم: در حال انتخاب زاویهٔ محتوا…")
    try:
        angle = await asyncio.to_thread(
            _openrouter_chat,
            config,
            STRATEGY_SYSTEM_PROMPT,
            f"موضوع ریل: {topic}",
            max_tokens=180,
        )
        await message.reply_text("✍️ نویسنده: در حال ساخت پیش‌نویس…")
        content = await asyncio.to_thread(
            _openrouter_chat,
            config,
            WRITER_SYSTEM_PROMPT,
            f"موضوع: {topic}\nزاویهٔ انتخاب‌شده: {angle}\n\n" "لطفاً پیش‌نویس کامل را طبق قالب تعیین‌شده بنویس.",
            max_tokens=1100,
        )
        draft = await asyncio.to_thread(
            _get_store(context).save_draft,
            owner_id=config.owner_id,
            topic=topic,
            angle=angle,
            content=content,
            model=config.openrouter_model,
        )
    except GenerationError as exc:
        LOGGER.warning("Draft generation failed: %s", exc)
        await message.reply_text(f"⛔ ساخت پیش‌نویس کامل نشد: {exc}")
        return
    except Exception:
        LOGGER.exception("Unexpected error while creating a draft")
        await message.reply_text(
            "⛔ هنگام ساخت یا ذخیرهٔ پیش‌نویس خطایی رخ داد. کمی بعد دوباره امتحان کن."
        )
        return

    response = (
        f"🎯 موضوع: {topic}\n"
        f"🧭 زاویهٔ محتوا: {angle}\n\n"
        f"{content}\n\n"
        "✅ متن تأیید شد و ذخیره شد (به‌عنوان پیش‌نویس).\n"
        f"🗃 شناسهٔ پیش‌نویس: {draft['id']} — دیدن دوباره: /draft {draft['id']}\n"
        "📌 این تأیید، تأیید نهایی انتشار نیست؛ انتشار انجام نشده و بازبینی تو لازم است."
    )
    await _reply_long(message, response)


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
