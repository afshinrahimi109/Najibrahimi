"""Asks the real AI services for text and pictures, to see what they answer today.

This is NOT part of the normal test run: those tests never leave the machine. GitHub Actions runs this file only
when the workflow is started by hand, and every finding is written as an annotation so it can be read from the
run's summary page (or the API).

    python live_check.py text|image|horde|limits
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


def check_text():
    n = random.randint(10000, 99999)
    status, _, raw, took = http("GET", "https://text.pollinations.ai/" + urllib.parse.quote("Write the number %d and nothing else" % n))
    note("notice" if status == 200 and str(n).encode() in raw else "error", "legacy text GET (no key)",
         "status=%s seconds=%.1f body=%s" % (status, took, raw[:200].decode("utf-8", "replace")))
    body = {"model": "openai", "temperature": 0.8, "max_tokens": 400, "messages": [
        {"role": "system", "content": "تو دستیار یک پیج اینستاگرام هستی. فارسی روان بنویس."},
        {"role": "user", "content": "برای پستی با موضوع «لاتهٔ پاییزی با دارچین، شمارهٔ %d» یک کپشن دو جمله‌ای بنویس." % n}]}
    status, headers, raw, took = http("POST", "https://text.pollinations.ai/openai", body)
    try:
        text = json.loads(raw.decode("utf-8"))["choices"][0]["message"]["content"]
    except Exception:
        text = ""
    note("notice" if status == 200 and text else "error", "legacy text POST /openai (no key)",
         "status=%s type=%s seconds=%.1f answer=%s raw=%s" % (status, headers.get("content-type"), took, text[:500],
                                                          "" if text else raw[:400].decode("utf-8", "replace")))
    status, _, raw, took = http("GET", "https://gen.pollinations.ai/text/" + urllib.parse.quote("Write the number %d and nothing else" % n))
    note("notice", "new text GET (no key)", "status=%s seconds=%.1f body=%s" % (status, took, raw[:300].decode("utf-8", "replace")))


def check_image():
    seed = random.randint(1, 2 ** 31 - 1)
    prompt = "a cup of autumn latte with cinnamon on a wooden cafe table, warm light, food photography"
    q = urllib.parse.urlencode({"width": 768, "height": 960, "seed": seed, "nologo": "true", "private": "true", "safe": "true"})
    status, headers, raw, took = http("GET", "https://image.pollinations.ai/prompt/%s?%s" % (urllib.parse.quote(prompt), q), timeout=240)
    report_image("legacy image GET (no key)", status, headers, raw, took)
    note("notice", "legacy image headers", json.dumps({k: v for k, v in headers.items() if k.startswith(("x-", "content-", "cache", "retry"))})[:1500])
    fa = "یک فنجان لاتهٔ پاییزی با دارچین روی میز چوبی کافه"
    q = urllib.parse.urlencode({"width": 768, "height": 960, "seed": seed + 1, "nologo": "true", "private": "true", "safe": "true"})
    status, headers, raw, took = http("GET", "https://image.pollinations.ai/prompt/%s?%s" % (urllib.parse.quote(fa), q), timeout=240)
    report_image("legacy image GET with a Persian prompt", status, headers, raw, took)
    status, headers, raw, took = http("GET", "https://gen.pollinations.ai/image/%s?width=768&height=960&seed=%d" % (urllib.parse.quote(prompt), seed))
    note("notice", "new image GET (no key)", "status=%s type=%s seconds=%.1f body=%s" % (
        status, headers.get("content-type"), took, raw[:300].decode("utf-8", "replace") if kind_of(raw).startswith("other") else kind_of(raw)))


def check_horde():
    base = "https://aihorde.net/api/v2"
    h = {"apikey": "0000000000", "Client-Agent": "insta-agent:1.1:github.com/afshinrahimi109/Najibrahimi"}
    status, _, raw, took = http("GET", base + "/status/heartbeat", headers=h)
    note("notice", "horde heartbeat", "status=%s seconds=%.1f body=%s" % (status, took, raw[:200].decode("utf-8", "replace")))
    status, _, raw, took = http("GET", base + "/status/performance", headers=h)
    note("notice", "horde performance", "status=%s body=%s" % (status, raw[:600].decode("utf-8", "replace")))
    body = {"prompt": "a cup of autumn latte with cinnamon on a wooden cafe table, warm light, food photography",
            "params": {"width": 512, "height": 640, "steps": 20, "n": 1, "sampler_name": "k_euler_a", "cfg_scale": 7},
            "nsfw": False, "censor_nsfw": True, "r2": True, "shared": False, "slow_workers": True, "trusted_workers": False}
    status, _, raw, took = http("POST", base + "/generate/async", body, h)
    note("notice" if status in (200, 202) else "error", "horde submit (anonymous key)", "status=%s seconds=%.1f body=%s" % (status, took, raw[:600].decode("utf-8", "replace")))
    try:
        rid = json.loads(raw.decode("utf-8"))["id"]
    except Exception:
        return
    t0, last = time.time(), {}
    while time.time() - t0 < 420:
        time.sleep(6)
        status, _, raw, _ = http("GET", base + "/generate/check/" + rid, headers=h)
        try:
            last = json.loads(raw.decode("utf-8"))
        except Exception:
            last = {"raw": raw[:200].decode("utf-8", "replace")}
        if last.get("done") or last.get("faulted") or last.get("is_possible") is False:
            break
    note("notice" if last.get("done") else "error", "horde wait", "seconds=%.0f last=%s" % (time.time() - t0, json.dumps(last)[:500]))
    if not last.get("done"):
        http("DELETE", base + "/generate/status/" + rid, headers=h)
        return
    status, _, raw, _ = http("GET", base + "/generate/status/" + rid, headers=h)
    try:
        gen = json.loads(raw.decode("utf-8"))["generations"][0]
    except Exception:
        return note("error", "horde result", "status=%s body=%s" % (status, raw[:500].decode("utf-8", "replace")))
    note("notice", "horde result", json.dumps({k: (v if k != "img" else str(v)[:120]) for k, v in gen.items()})[:900])
    img = str(gen.get("img") or "")
    if img.startswith("http"):
        status, headers, raw, took = http("GET", img)
    else:
        status, headers, raw, took = 200, {"content-type": "base64"}, base64.b64decode(img), 0.0
    report_image("horde image", status, headers, raw, took)


def check_limits():
    for size in (500, 2000, 6000, 12000, 30000):
        note("notice", "annotation of %d characters" % size, ("0123456789" * (size // 10))[:size - 4] + "-END")


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "text"
    {"text": check_text, "image": check_image, "horde": check_horde, "limits": check_limits}[what]()
