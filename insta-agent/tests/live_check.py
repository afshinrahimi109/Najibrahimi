"""Asks the real AI services for text and pictures, to see what they answer today.

This is NOT part of the normal test run: those tests never leave the machine. GitHub Actions runs this file only
when the workflow is started by hand, and every finding is written as an annotation so it can be read from the
run's summary page (or the API).

    python live_check.py text|post|image|horde
"""
import base64
import io
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "insta-agent-live-check/1 (+https://github.com/afshinrahimi109/Najibrahimi)"


def http(method, url, data=None, headers=None, timeout=180):
    h = {"User-Agent": UA}
    h.update(headers or {})
    if isinstance(data, (dict, list)):
        data = json.dumps(data).encode("utf-8")
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            return res.status, dict((k.lower(), v) for k, v in res.headers.items()), res.read(), time.time() - t0
    except urllib.error.HTTPError as e:
        return e.code, dict((k.lower(), v) for k, v in (e.headers.items() if e.headers else [])), e.read(), time.time() - t0
    except Exception as e:                                         # network trouble is a finding too
        return 0, {}, ("%s: %s" % (type(e).__name__, e)).encode("utf-8"), time.time() - t0


def note(level, title, text):
    text = str(text).strip().replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    print("::%s title=%s::%s" % (level, title.replace(",", " ").replace("::", " "), text), flush=True)


def kind_of(raw):
    if raw[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return "other(%r)" % raw[:60]


def thumb(raw, width=112):
    """A very small copy of the picture as text, so a person can check that it really shows what was asked."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw)).convert("RGB")
        size = im.size
        im = im.resize((width, max(1, round(im.size[1] * width / im.size[0]))))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=42)
        return size, base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as e:
        return None, "no thumbnail: %s" % e


def report_image(name, status, headers, raw, took):
    ok = status == 200 and kind_of(raw) in ("jpeg", "png", "webp")
    size, small = thumb(raw) if ok else (None, "")
    note("notice" if ok else "error", name,
         "status=%s type=%s kind=%s bytes=%s pixels=%s seconds=%.1f%s" % (
             status, headers.get("content-type"), kind_of(raw), len(raw), size, took,
             "" if ok else " body=" + raw[:300].decode("utf-8", "replace")))
    if ok:
        note("notice", name + " thumb", small)
    return ok


PLAN_SYSTEM = "تو دستیار یک پیج اینستاگرام هستی (کافهٔ کوچک محلی با قهوهٔ تازه). فارسی روان بنویس."
PLAN_ASK = ("ایده: «تخفیف ۲۰ درصدی لاتهٔ پاییزی تا آخر هفته». برای یک ریل ۳ صحنه‌ای اینستاگرام فقط یک شیء JSON بده با این کلیدها: "
            "caption (کپشن فارسی ۲ تا ۳ جمله، بدون هشتگ)، hashtags (آرایهٔ ۳ تا ۵ هشتگ)، headline (تیتر فارسی حداکثر ۶ کلمه)، "
            "image (توصیف انگلیسی یک عکس برای مدل تصویرساز، بدون نوشته در تصویر)، scenes (آرایهٔ ۳ صحنه، هر کدام text فارسی خیلی کوتاه "
            "و image انگلیسی). هیچ توضیحی بیرون از JSON ننویس.")


def show(name, status, headers, raw, took, want=None):
    text = raw.decode("utf-8", "replace")
    ok = status == 200 and bool(text.strip()) and (want is None or want in text)
    note("notice" if ok else "error", name, "status=%s type=%s seconds=%.1f chars=%d body=%s" % (
        status, headers.get("content-type"), took, len(text), text[:3300]))
    return ok


def check_text():
    """One free reply per 45 seconds and per address: every question here waits for its own turn."""
    n = random.randint(10000, 99999)
    base = "https://text.pollinations.ai/"
    q = urllib.parse.urlencode({"model": "openai-fast", "system": PLAN_SYSTEM, "private": "true", "seed": n})
    show("classic text GET: Persian plan with system", *http("GET", base + urllib.parse.quote(PLAN_ASK) + "?" + q, timeout=75))
    time.sleep(47)
    msgs = [{"role": "system", "content": PLAN_SYSTEM}, {"role": "user", "content": PLAN_ASK}]
    show("classic POST /openai (first in its window)", *http("POST", base + "openai", {"model": "openai-fast", "messages": msgs, "seed": n}, timeout=75))


def check_text_post():
    n = random.randint(10000, 99999)
    time.sleep(47)
    msgs = [{"role": "system", "content": PLAN_SYSTEM}, {"role": "user", "content": "برای پستی با موضوع «لاتهٔ پاییزی، شمارهٔ %d» یک کپشن دو جمله‌ای بنویس." % n}]
    show("classic POST / (plain, first in its window)", *http("POST", "https://text.pollinations.ai/", {"model": "openai-fast", "messages": msgs, "seed": n}, timeout=75))
    time.sleep(47)
    show("classic POST /openai as the assistant asks today", *http(
        "POST", "https://text.pollinations.ai/openai", {"model": "openai", "messages": msgs, "max_tokens": 400, "temperature": 0.8}, timeout=75))


def classic_image(name, prompt, tries=8, **params):
    q = {"width": 768, "height": 960, "seed": random.randint(1, 2 ** 31 - 1), "nologo": "true", "private": "true", "safe": "true"}
    q.update(params)
    url = "https://image.pollinations.ai/prompt/%s?%s" % (urllib.parse.quote(prompt), urllib.parse.urlencode(q))
    t0, seen = time.time(), []
    for _ in range(tries):
        status, headers, raw, took = http("GET", url, timeout=240)
        seen.append("%s:%s" % (status, headers.get("retry-after")))
        if status not in (402, 429, 503):
            break
        time.sleep(min(50, int(headers.get("retry-after") or 10)) + 1)
    headers = dict(headers, **{"content-type": "%s model=%s answers=%s total=%.0fs" % (headers.get("content-type"), headers.get("x-model-used"), ",".join(seen), time.time() - t0)})
    return report_image(name, status, headers, raw, took)


def check_image():
    classic_image("classic image", "a cup of autumn latte with cinnamon on a wooden cafe table, warm light, food photography, no text")
    time.sleep(47)
    classic_image("classic image, Persian prompt", "یک فنجان لاتهٔ پاییزی با دارچین روی میز چوبی کافه، نور گرم")
    time.sleep(47)
    classic_image("classic image 9:16", "a barista pouring milk into a latte, cozy cafe, autumn, cinematic", width=720, height=1280)


def horde_submit(base, h, name, body):
    status, _, raw, took = http("POST", base + "/generate/async", body, h)
    text = raw[:420].decode("utf-8", "replace")
    try:
        return json.loads(raw.decode("utf-8"))["id"], "submit=%s %s" % (status, text)
    except Exception:
        note("error", name, "submit status=%s body=%s" % (status, text))
        return None, ""


def horde_collect(base, h, name, rid, said, wait=240):
    t0, last = time.time(), {}
    while time.time() - t0 < wait:
        time.sleep(4)
        status, _, raw, _ = http("GET", base + "/generate/check/" + rid, headers=h)
        try:
            last = json.loads(raw.decode("utf-8"))
        except Exception:
            last = {"raw": raw[:200].decode("utf-8", "replace")}
        if last.get("done") or last.get("faulted") or last.get("is_possible") is False:
            break
    took = time.time() - t0
    if not last.get("done"):
        http("DELETE", base + "/generate/status/" + rid, headers=h)
        return note("error", name, "%s | not done after %.0fs last=%s" % (said, took, json.dumps(last)[:300]))
    status, _, raw, _ = http("GET", base + "/generate/status/" + rid, headers=h)
    try:
        gen = json.loads(raw.decode("utf-8"))["generations"][0]
    except Exception:
        return note("error", name, "%s | status=%s body=%s" % (said, status, raw[:300].decode("utf-8", "replace")))
    img = str(gen.get("img") or "")
    how = "link" if img.startswith("http") else "base64"
    status, headers, raw, _ = http("GET", img) if how == "link" else (200, {}, base64.b64decode(img), 0.0)
    headers = {"content-type": "%s model=%s wait=%.0fs censored=%s | %s" % (how, gen.get("model"), took, gen.get("censored"), said[:160])}
    return report_image(name, status, headers, raw, 0.0)


def check_horde():
    base = "https://aihorde.net/api/v2"
    h = {"apikey": "0000000000", "Client-Agent": "insta-agent:1.1:github.com/afshinrahimi109/Najibrahimi"}
    neg = " ### text, letters, watermark, logo, blurry, deformed, low quality"
    photo = ["ICBINP - I Can't Believe It's Not Photography", "AbsoluteReality", "Deliberate", "stable_diffusion"]
    art = ["Dreamshaper", "Deliberate", "stable_diffusion"]
    params = {"width": 512, "height": 640, "steps": 24, "n": 1, "sampler_name": "k_euler_a", "cfg_scale": 6.5, "karras": True}
    common = {"nsfw": False, "censor_nsfw": True, "r2": False, "shared": False, "slow_workers": True, "trusted_workers": False}
    a = "a cup of autumn latte with cinnamon on a wooden cafe table, warm light, food photography"
    b = "a barista pouring milk into a latte, cozy cafe, autumn, cinematic"
    c = "flat illustration of a small cafe storefront in autumn, falling leaves, soft colors"
    # two at once: is that allowed without an account?
    r1, s1 = horde_submit(base, h, "horde photo 512x640", dict(common, prompt=a + neg, params=params, models=photo))
    r2, s2 = horde_submit(base, h, "horde tall 384x704", dict(common, prompt=b + neg, params=dict(params, width=384, height=704), models=photo))
    if r1:
        horde_collect(base, h, "horde photo 512x640", r1, s1)
    if r2:
        horde_collect(base, h, "horde tall 384x704", r2, s2)
    r3, s3 = horde_submit(base, h, "horde art 512x640", dict(common, prompt=c + neg, params=params, models=art))
    if r3:
        horde_collect(base, h, "horde art 512x640", r3, s3)
    horde_submit(base, h, "horde 448x768 (just over the free size)", dict(common, prompt=b + neg, params=dict(params, width=448, height=768), models=photo))
    r5, s5 = horde_submit(base, h, "horde 576x576", dict(common, prompt=a + neg, params=dict(params, width=576, height=576), models=photo))
    if r5:
        horde_collect(base, h, "horde 576x576", r5, s5)


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "text"
    {"text": check_text, "post": check_text_post, "image": check_image, "horde": check_horde}[what]()
