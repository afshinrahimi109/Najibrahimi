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
    n = random.randint(10000, 99999)
    base = "https://text.pollinations.ai/"
    show("legacy text GET", *http("GET", base + urllib.parse.quote("Write the number %d and nothing else" % n), timeout=60), want=str(n))
    status, headers, raw, took = http("GET", base + "models", timeout=60)
    try:
        names = [(m.get("name"), m.get("tier"), m.get("community")) for m in json.loads(raw.decode("utf-8"))]
    except Exception:
        names = raw[:600].decode("utf-8", "replace")
    note("notice", "legacy text models", "status=%s %s" % (status, json.dumps(names)[:3500]))
    q = urllib.parse.urlencode({"model": "openai", "system": PLAN_SYSTEM, "private": "true", "seed": n})
    show("legacy text GET: Persian plan with system", *http("GET", base + urllib.parse.quote(PLAN_ASK) + "?" + q, timeout=90))
    q = urllib.parse.urlencode({"system": PLAN_SYSTEM, "private": "true", "seed": n + 1, "json": "true"})
    show("legacy text GET: Persian plan with json=true and no model", *http("GET", base + urllib.parse.quote(PLAN_ASK) + "?" + q, timeout=90))


def check_text_post():
    n = random.randint(10000, 99999)
    msgs = [{"role": "system", "content": PLAN_SYSTEM}, {"role": "user", "content": "برای پستی با موضوع «لاتهٔ پاییزی، شمارهٔ %d» یک کپشن دو جمله‌ای بنویس." % n}]
    show("legacy POST /openai minimal", *http("POST", "https://text.pollinations.ai/openai", {"model": "openai", "messages": msgs}, timeout=60))
    show("legacy POST /openai no model", *http("POST", "https://text.pollinations.ai/openai", {"messages": msgs}, timeout=60))
    show("legacy POST / (plain)", *http("POST", "https://text.pollinations.ai/", {"model": "openai", "messages": msgs, "seed": n}, timeout=60))
    show("legacy POST /openai with max_tokens and temperature", *http(
        "POST", "https://text.pollinations.ai/openai", {"model": "openai", "messages": msgs, "max_tokens": 400, "temperature": 0.8}, timeout=60))


def legacy_image(name, prompt, **params):
    q = {"width": 768, "height": 960, "seed": random.randint(1, 2 ** 31 - 1), "nologo": "true", "private": "true", "safe": "true"}
    q.update(params)
    status, headers, raw, took = http("GET", "https://image.pollinations.ai/prompt/%s?%s" % (urllib.parse.quote(prompt), urllib.parse.urlencode(q)), timeout=240)
    ok = report_image(name, status, headers, raw, took)
    note("notice", name + " headers", json.dumps({k: v for k, v in headers.items() if k.startswith(("x-", "retry", "content-type"))})[:1200])
    return ok


def check_image():
    en = "a cup of autumn latte with cinnamon on a wooden cafe table, warm light, food photography, no text"
    legacy_image("legacy image (no key)", en)
    time.sleep(47)
    legacy_image("legacy image, Persian prompt", "یک فنجان لاتهٔ پاییزی با دارچین روی میز چوبی کافه، نور گرم")
    time.sleep(47)
    legacy_image("legacy image 9:16 with model=flux", "a barista pouring milk into a latte, cozy cafe, autumn, cinematic", width=720, height=1280, model="flux")


def horde_one(base, h, name, body, wait=300):
    status, _, raw, took = http("POST", base + "/generate/async", body, h)
    note("notice" if status in (200, 202) else "error", name + " submit", "status=%s seconds=%.1f body=%s" % (status, took, raw[:500].decode("utf-8", "replace")))
    try:
        rid = json.loads(raw.decode("utf-8"))["id"]
    except Exception:
        return None
    t0, last = time.time(), {}
    while time.time() - t0 < wait:
        time.sleep(5)
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
        return note("error", name + " wait", "seconds=%.0f last=%s" % (took, json.dumps(last)[:400]))
    status, _, raw, _ = http("GET", base + "/generate/status/" + rid, headers=h)
    try:
        gen = json.loads(raw.decode("utf-8"))["generations"][0]
    except Exception:
        return note("error", name + " result", "status=%s body=%s" % (status, raw[:400].decode("utf-8", "replace")))
    img = str(gen.get("img") or "")
    status, headers, raw, _ = http("GET", img) if img.startswith("http") else (200, {"content-type": "base64"}, base64.b64decode(img), 0.0)
    headers = dict(headers, **{"content-type": "%s model=%s wait=%.0fs" % (headers.get("content-type"), gen.get("model"), took)})
    return report_image(name, status, headers, raw, 0.0)


def check_horde():
    base = "https://aihorde.net/api/v2"
    h = {"apikey": "0000000000", "Client-Agent": "insta-agent:1.1:github.com/afshinrahimi109/Najibrahimi"}
    status, _, raw, _ = http("GET", base + "/status/models?type=image", headers=h)
    try:
        models = sorted(json.loads(raw.decode("utf-8")), key=lambda m: -int(m.get("count") or 0))
    except Exception:
        models = []
    note("notice", "horde models by workers", json.dumps([(m.get("name"), m.get("count"), m.get("queued"), m.get("eta")) for m in models[:28]])[:3600])
    prompt = "a cup of autumn latte with cinnamon on a wooden cafe table, warm light, food photography"
    params = {"width": 768, "height": 960, "steps": 20, "n": 1, "sampler_name": "k_euler_a", "cfg_scale": 6}
    common = {"nsfw": False, "censor_nsfw": True, "r2": True, "shared": False, "slow_workers": True, "trusted_workers": False}
    horde_one(base, h, "horde 768x960 any model", dict(common, prompt=prompt, params=params))
    xl = [m["name"] for m in models if any(w in str(m.get("name")) for w in ("XL", "Flux", "flux")) and int(m.get("count") or 0) >= 1][:6]
    note("notice", "horde better models asked", json.dumps(xl))
    if xl:
        horde_one(base, h, "horde 768x960 XL or Flux", dict(common, prompt=prompt, params=dict(params, steps=20), models=xl))
    horde_one(base, h, "horde 576x1024 any model", dict(common, prompt="a barista pouring milk into a latte, cozy cafe, autumn, cinematic",
                                                         params=dict(params, width=576, height=1024)), wait=200)


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "text"
    {"text": check_text, "post": check_text_post, "image": check_image, "horde": check_horde}[what]()
