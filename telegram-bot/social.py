"""Small official Meta Graph API publishers for a Facebook Page and Instagram professional account."""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


class SocialPublishError(Exception):
    """Safe-to-display error raised by a social publishing integration."""


def _version(config: Any) -> str:
    version = str(getattr(config, "meta_graph_api_version", "v26.0"))
    if not re.fullmatch(r"v\d+\.\d+", version):
        raise SocialPublishError("META_GRAPH_API_VERSION باید مثل v26.0 باشد.")
    return version


def _identifier(value: str, label: str) -> str:
    value = str(value).strip()
    if not value or not re.fullmatch(r"[0-9]+", value):
        raise SocialPublishError(f"شناسهٔ {label} تنظیم نشده یا معتبر نیست.")
    return value


def _https_url(value: str) -> str:
    value = value.strip()
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        raise SocialPublishError("لینک رسانه معتبر نیست؛ لینک عمومی HTTPS بده.") from None
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise SocialPublishError("برای انتشار عکس، لینک مستقیم و عمومی HTTPS لازم است.")
    return value


def _request_json(
    *, url: str, access_token: str, method: str, payload: dict[str, str] | None = None,
    timeout: float = 30,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            message = body.get("error", {}).get("message", "")
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            message = ""
        detail = f": {message[:300]}" if message else ""
        raise SocialPublishError(f"Meta API درخواست را نپذیرفت (HTTP {exc.code}){detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise SocialPublishError("ارتباط با Meta برقرار نشد؛ اینترنت و دسترسی API را بررسی کن.") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise SocialPublishError("پاسخ Meta قابل خواندن نبود.") from None
    if not isinstance(result, dict):
        raise SocialPublishError("پاسخ Meta قالب نامعتبر داشت.")
    if result.get("error"):
        error = result["error"]
        message = error.get("message", "") if isinstance(error, dict) else ""
        detail = f": {str(message)[:300]}" if message else ""
        raise SocialPublishError(f"Meta API خطا برگرداند{detail}")
    return result


def publish_facebook_page_post(
    config: Any, message: str, *, image_url: str = ""
) -> str:
    """Publish text or a publicly hosted image and caption to a Facebook Page."""
    page_id = _identifier(getattr(config, "facebook_page_id", ""), "Facebook Page")
    access_token = str(getattr(config, "facebook_page_access_token", "")).strip()
    if not access_token:
        raise SocialPublishError("FACEBOOK_PAGE_ACCESS_TOKEN را در تنظیمات محلی وارد کن.")
    message = message.strip()
    if not message:
        raise SocialPublishError("متن پست خالی است.")
    if len(message) > 60_000:
        raise SocialPublishError("متن پست Facebook بیش از حد طولانی است.")
    version = _version(config)
    if image_url:
        url = f"https://graph.facebook.com/{version}/{page_id}/photos"
        payload = {"url": _https_url(image_url), "caption": message}
    else:
        url = f"https://graph.facebook.com/{version}/{page_id}/feed"
        payload = {"message": message}
    result = _request_json(url=url, access_token=access_token, method="POST", payload=payload)
    post_id = result.get("id") or result.get("post_id")
    if not post_id:
        raise SocialPublishError("Meta پست را تأیید کرد اما شناسهٔ انتشار را نفرستاد.")
    return str(post_id)


def publish_instagram_image(
    config: Any, image_url: str, caption: str, *, poll_interval: float = 2.0,
    max_polls: int = 10,
) -> str:
    """Publish a public JPEG URL to an Instagram professional account via Instagram Login."""
    instagram_id = _identifier(getattr(config, "instagram_account_id", ""), "Instagram")
    access_token = str(getattr(config, "instagram_access_token", "")).strip()
    if not access_token:
        raise SocialPublishError("INSTAGRAM_ACCESS_TOKEN را در تنظیمات محلی وارد کن.")
    image_url = _https_url(image_url)
    caption = caption.strip()
    if len(caption) > 2200:
        raise SocialPublishError("کپشن Instagram نباید بیشتر از ۲۲۰۰ نویسه باشد.")
    version = _version(config)
    root = f"https://graph.instagram.com/{version}"
    container = _request_json(
        url=f"{root}/{instagram_id}/media", access_token=access_token,
        method="POST", payload={"image_url": image_url, "caption": caption},
    )
    container_id = container.get("id")
    if not container_id:
        raise SocialPublishError("Instagram شناسهٔ آماده‌سازی رسانه را نفرستاد.")

    status_url = f"{root}/{urllib.parse.quote(str(container_id), safe='')}?fields=status_code"
    poll_count = max(1, min(max_polls, 20))
    for attempt in range(poll_count):
        status = _request_json(url=status_url, access_token=access_token, method="GET")
        status_code = str(status.get("status_code", "")).upper()
        if status_code in ("FINISHED", "PUBLISHED"):
            break
        if status_code in ("ERROR", "EXPIRED"):
            raise SocialPublishError("Instagram آماده‌سازی عکس را ناموفق دانست؛ لینک JPEG را بررسی کن.")
        if attempt + 1 < poll_count:
            time.sleep(max(0, min(poll_interval, 5)))
    else:
        raise SocialPublishError("آماده‌سازی عکس Instagram طول کشید؛ دوباره کمی بعد تلاش کن.")

    published = _request_json(
        url=f"{root}/{instagram_id}/media_publish", access_token=access_token,
        method="POST", payload={"creation_id": str(container_id)},
    )
    media_id = published.get("id")
    if not media_id:
        raise SocialPublishError("Instagram شناسهٔ پست منتشرشده را نفرستاد.")
    return str(media_id)
