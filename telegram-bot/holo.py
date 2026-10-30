"""Provider integrations for Holo Agent (Groq, DuckDuckGo and Pollinations)."""
from __future__ import annotations

import base64
import json
import logging
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

LOGGER = logging.getLogger("najib_agent")
GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GEMINI_API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models/"
POLLINATIONS_URL = "https://image.pollinations.ai/prompt/"


class HoloError(Exception):
    """An integration error safe to summarize to the bot owner."""


def chat_completion(
    *, api_key: str, model: str, messages: list[dict[str, str]], timeout: float = 45,
    endpoint: str = GROQ_CHAT_URL, max_tokens: int = 1200,
) -> str:
    if not api_key:
        raise HoloError("کلید هوش مصنوعی تنظیم نشده است؛ GROQ_API_KEY را در تنظیمات سرور اضافه کن.")
    payload = {"model": model, "messages": messages, "temperature": 0.7, "max_tokens": max_tokens}
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise HoloError("کلید سرویس هوش مصنوعی معتبر نیست.") from None
        if exc.code == 429:
            raise HoloError("محدودیت درخواست سرویس هوش مصنوعی؛ کمی بعد دوباره امتحان کن.") from None
        LOGGER.warning("LLM provider returned HTTP %s", exc.code)
        raise HoloError(f"سرویس هوش مصنوعی درخواست را نپذیرفت (خطای {exc.code}).") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise HoloError("ارتباط با سرویس هوش مصنوعی برقرار نشد یا زمان درخواست تمام شد.") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HoloError("پاسخ سرویس هوش مصنوعی قابل خواندن نبود.") from None
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise HoloError("سرویس هوش مصنوعی پاسخ متنی برنگرداند.") from None
    if not isinstance(content, str) or not content.strip():
        raise HoloError("سرویس هوش مصنوعی پاسخ متنی برنگرداند.")
    return content.strip()


def _pollinations_text(raw: str) -> str:
    try:
        data = json.loads(raw)
        content = data["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        content = raw.strip()
    return content.strip() if isinstance(content, str) else ""


def pollinations_completion(
    *, messages: list[dict[str, str]], timeout: float = 60, max_tokens: int = 1200,
) -> str:
    """No-key public text fallback; availability and limits are controlled by the provider."""
    endpoint = "https://text.pollinations.ai/openai"
    payload = {
        "model": "openai",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": max_tokens,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "HoloAgent/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content = _pollinations_text(response.read(2_000_000).decode("utf-8", "replace"))
        if content:
            return content
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        LOGGER.warning("Public text POST fallback failed: %s", type(exc).__name__)

    # Older Pollinations deployments also accept a prompt in the URL path.
    flat_prompt = "\n".join(f"{item['role']}: {item['content']}" for item in messages)
    get_url = "https://text.pollinations.ai/" + urllib.parse.quote(flat_prompt[:6000]) + "?model=openai"
    get_request = urllib.request.Request(get_url, headers={"User-Agent": "HoloAgent/1.0"})
    try:
        with urllib.request.urlopen(get_request, timeout=min(timeout, 35)) as response:
            content = _pollinations_text(response.read(2_000_000).decode("utf-8", "replace"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        LOGGER.warning("Public text GET fallback failed: %s", type(exc).__name__)
        raise HoloError("مدل عمومیِ بدون کلید فعلاً در دسترس نیست.") from None
    if not content:
        raise HoloError("مدل عمومی پاسخ متنی برنگرداند.")
    return content


def _gemini_request(api_key: str, model: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    if not api_key:
        raise HoloError("کلید Gemini تنظیم نشده است؛ GEMINI_API_KEY را وارد کن.")
    endpoint = GEMINI_API_ROOT + urllib.parse.quote(model, safe="") + ":generateContent"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise HoloError("کلید Gemini معتبر نیست یا دسترسی API برای آن فعال نیست.") from None
        if exc.code == 404:
            raise HoloError("مدل Gemini پیدا نشد؛ مقدار GEMINI_MODEL را بررسی کن.") from None
        if exc.code == 429:
            raise HoloError("سهمیهٔ Gemini فعلاً تمام شده؛ کمی بعد دوباره امتحان کن.") from None
        LOGGER.warning("Gemini returned HTTP %s", exc.code)
        raise HoloError(f"Gemini درخواست را نپذیرفت (خطای {exc.code}).") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise HoloError("ارتباط با Gemini برقرار نشد یا زمان درخواست تمام شد.") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HoloError("پاسخ Gemini قابل خواندن نبود.") from None
    return result


def gemini_completion(
    *, api_key: str, model: str, messages: list[dict[str, str]], timeout: float = 45,
    max_tokens: int = 1200,
) -> str:
    system_parts = [item["content"] for item in messages if item.get("role") == "system"]
    contents = [
        {
            "role": "model" if item.get("role") == "assistant" else "user",
            "parts": [{"text": item.get("content", "")}],
        }
        for item in messages
        if item.get("role") != "system" and item.get("content")
    ]
    if not contents:
        raise HoloError("پیام خالی است.")
    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": max_tokens},
    }
    if system_parts:
        payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
    result = _gemini_request(api_key, model, payload, timeout)
    try:
        parts = result["candidates"][0]["content"]["parts"]
        text = "\n".join(part["text"] for part in parts if isinstance(part.get("text"), str))
    except (KeyError, IndexError, TypeError):
        feedback = result.get("prompt_feedback", {}) if isinstance(result, dict) else {}
        if feedback:
            raise HoloError("Gemini نتوانست به این درخواست پاسخ دهد؛ متن را ساده‌تر کن.") from None
        raise HoloError("Gemini پاسخ متنی برنگرداند.") from None
    if not text.strip():
        raise HoloError("Gemini پاسخ متنی برنگرداند.")
    return text.strip()


def gemini_transcribe(api_key: str, model: str, audio: bytes, timeout: float = 60) -> str:
    if len(audio) > 14_000_000:
        raise HoloError("ویس برای تبدیل با Gemini خیلی بزرگ است؛ یک ویس کوتاه‌تر بفرست.")
    instruction = "این فایل صوتی شامل گفتار است. گفتار را دقیقاً به زبان گفته‌شده پیاده‌سازی کن و فقط متن پیاده‌سازی‌شده را برگردان."
    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": instruction},
                {"inlineData": {"mimeType": "audio/ogg", "data": base64.b64encode(audio).decode("ascii")}},
            ],
        }],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1200},
    }
    result = _gemini_request(api_key, model, payload, timeout)
    try:
        text = "\n".join(
            part["text"] for part in result["candidates"][0]["content"]["parts"]
            if isinstance(part.get("text"), str)
        )
    except (KeyError, IndexError, TypeError):
        raise HoloError("Gemini نتوانست گفتار را از ویس استخراج کند.") from None
    if not text.strip():
        raise HoloError("گفتار واضحی در ویس پیدا نشد.")
    return text.strip()


class _SearchParser(HTMLParser):
    """Extract result title/link/snippet from DuckDuckGo's lightweight HTML page."""
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._capture_title = False
        self._capture_snippet = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        classes = attrs_dict.get("class", "") or ""
        if tag == "div" and "result" in classes.split():
            self._current = {"title": "", "url": "", "snippet": ""}
            self.results.append(self._current)
        elif self._current is not None and tag == "a" and "result__a" in classes.split():
            href = attrs_dict.get("href", "") or ""
            if "duckduckgo.com/l/" in href:
                href = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [href])[0]
            self._current["url"] = href
            self._capture_title = True
        elif self._current is not None and "result__snippet" in classes.split():
            self._capture_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._capture_title = False
        if tag in ("a", "td", "div"):
            self._capture_snippet = False

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        value = data.strip()
        if not value:
            return
        if self._capture_title:
            self._current["title"] = re.sub(r"\s+([,.;:!?])", r"\1", f"{self._current['title']} {value}".strip())
        elif self._capture_snippet:
            self._current["snippet"] = re.sub(r"\s+([,.;:!?])", r"\1", f"{self._current['snippet']} {value}".strip())


def search_web(query: str, limit: int = 5, timeout: float = 15) -> list[dict[str, str]]:
    query = query.strip()
    if not query:
        return []
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 HoloAgent/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            page = response.read(2_000_000).decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        raise HoloError("جستجوی وب در دسترس نیست؛ کمی بعد دوباره امتحان کن.") from None
    parser = _SearchParser()
    parser.feed(page)
    results = []
    for item in parser.results:
        if item["title"] and item["url"]:
            results.append({key: value.strip() for key, value in item.items()})
        if len(results) >= limit:
            break
    return results


def transcribe_audio(api_key: str, audio: bytes, filename: str = "voice.ogg", timeout: float = 60) -> str:
    if not api_key:
        raise HoloError("برای تبدیل صدا، کلید GROQ_API_KEY را تنظیم کن.")
    boundary = "----HoloAgentBoundary7MA4YWxkTrZu0gW"
    fields = [
        ("model", "whisper-large-v3-turbo"),
        ("response_format", "json"),
        ("language", "fa"),
    ]
    body = bytearray()
    for name, value in fields:
        body.extend(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    safe_name = filename.replace('"', "")
    body.extend(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{safe_name}\"\r\n"
        "Content-Type: audio/ogg\r\n\r\n".encode()
    )
    body.extend(audio)
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        GROQ_TRANSCRIPTION_URL, data=bytes(body),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise HoloError("کلید Groq برای تبدیل صدا معتبر نیست.") from None
        if exc.code == 429:
            raise HoloError("محدودیت تبدیل صدا؛ کمی بعد دوباره امتحان کن.") from None
        LOGGER.warning("Speech transcription returned HTTP %s", exc.code)
        raise HoloError(f"تبدیل صدا انجام نشد (خطای {exc.code}).") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise HoloError("ارتباط تبدیل صدا برقرار نشد یا زمان درخواست تمام شد.") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HoloError("پاسخ تبدیل صدا قابل خواندن نبود.") from None
    text = result.get("text") if isinstance(result, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise HoloError("صدای واضحی برای تبدیل به متن پیدا نشد.")
    return text.strip()


def generate_image(prompt: str, timeout: float = 90) -> bytes:
    prompt = prompt.strip()
    if not prompt:
        raise HoloError("توضیح تصویر خالی است.")
    url = POLLINATIONS_URL + urllib.parse.quote(prompt[:500], safe="") + "?width=1024&height=1024&nologo=true"
    request = urllib.request.Request(url, headers={"User-Agent": "HoloAgent/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                raise HoloError(f"سرویس تصویر خطای {response.status} برگرداند.")
            content_type = response.headers.get("Content-Type", "")
            image = response.read(12_000_001)
    except HoloError:
        raise
    except urllib.error.HTTPError as exc:
        LOGGER.warning("Image provider returned HTTP %s", exc.code)
        raise HoloError("ساخت تصویر در دسترس نیست؛ کمی بعد دوباره امتحان کن.") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise HoloError("ارتباط با سرویس تصویر برقرار نشد یا زمان درخواست تمام شد.") from None
    if not content_type.startswith("image/") or not image.startswith(b"\x89PNG") and not image.startswith(b"\xff\xd8"):
        raise HoloError("سرویس تصویر فایل تصویری معتبر برنگرداند.")
    if len(image) > 12_000_000:
        raise HoloError("تصویر بزرگ‌تر از حد مجاز است.")
    return image


def animate_image_to_video(image: bytes, *, seconds: int = 6) -> bytes:
    """Create a short portrait MP4 with a gentle Ken Burns motion from a generated still."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HoloError("برای ساخت کلیپ متحرک، FFmpeg نصب نیست؛ در Termux اجرا کن: pkg install ffmpeg")
    if not image or len(image) > 12_000_000:
        raise HoloError("تصویر ورودی خالی یا بیش از حد بزرگ است.")
    seconds = max(3, min(int(seconds), 10))
    extension = ".jpg" if image.startswith(b"\xff\xd8") else ".png"
    with tempfile.TemporaryDirectory(prefix="holo-video-") as temp_dir:
        image_path = f"{temp_dir}/source{extension}"
        video_path = f"{temp_dir}/clip.mp4"
        with open(image_path, "wb") as image_file:
            image_file.write(image)
        filters = (
            "scale=720:1280:force_original_aspect_ratio=increase,"
            "crop=720:1280,"
            f"zoompan=z='min(zoom+0.0012,1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=720x1280:fps=30,"
            "format=yuv420p"
        )
        command = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-loop", "1",
            "-i", image_path, "-vf", filters, "-frames:v", str(seconds * 30),
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "27",
            "-movflags", "+faststart", video_path,
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=120)
            with open(video_path, "rb") as video_file:
                video = video_file.read(45_000_001)
        except FileNotFoundError:
            raise HoloError("FFmpeg پیدا نشد؛ در Termux اجرا کن: pkg install ffmpeg") from None
        except subprocess.TimeoutExpired:
            raise HoloError("ساخت کلیپ بیشتر از حد معمول طول کشید؛ یک تصویر ساده‌تر امتحان کن.") from None
        except subprocess.CalledProcessError as exc:
            LOGGER.warning("ffmpeg failed with return code %s", exc.returncode)
            raise HoloError("ساخت کلیپ ناموفق بود؛ FFmpeg را به‌روز کن و دوباره امتحان کن.") from None
        except OSError:
            raise HoloError("فایل کلیپ ساخته نشد؛ فضای ذخیره‌سازی گوشی را بررسی کن.") from None
    if len(video) < 12 or video[4:8] != b"ftyp" or len(video) > 45_000_000:
        raise HoloError("حجم کلیپ از سقف ارسال تلگرام بیشتر شد.")
    return video


def generate_motion_video(prompt: str, *, seconds: int = 6) -> bytes:
    """Generate a still image and render it as a short silent motion clip."""
    still = generate_image(prompt)
    return animate_image_to_video(still, seconds=seconds)


def format_search_results(results: list[dict[str, str]]) -> str:
    if not results:
        return "نتیجه‌ای پیدا نشد. عبارت جستجو را دقیق‌تر کن."
    return "\n\n".join(
        f"{index}. {item['title']}\n{item.get('snippet') or 'خلاصه‌ای در دسترس نیست.'}\n{item['url']}"
        for index, item in enumerate(results, 1)
    )


def clean_intent_text(text: str, words: tuple[str, ...]) -> str:
    cleaned = text.strip()
    for word in words:
        cleaned = re.sub(re.escape(word), " ", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip(" \t\n:،,؟?!")
