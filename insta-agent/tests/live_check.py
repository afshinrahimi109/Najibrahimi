"""Lets the studio work against the REAL text and picture services, exactly as it does on the owner's phone.

This is NOT part of the normal test run: those tests never leave the machine. GitHub Actions runs this file only on
request (see the workflow), and every finding is written as an annotation so it can be read from the run's summary
page or the API. Pictures come back as very small previews inside those annotations.

    python live_check.py reel|picture
"""
import base64
import io
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import insta_agent as ia  # noqa: E402


def note(level, title, text):
    text = str(text).strip().replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    print("::%s title=%s::%s" % (level, title.replace(",", " ").replace("::", " "), text), flush=True)


def thumb(path, width=96):
    """A very small copy of a picture as text, so a person can see that it shows what was asked for."""
    try:
        from PIL import Image
        im = Image.open(path).convert("RGB")
        im = im.resize((width, max(1, round(im.size[1] * width / im.size[0]))))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=36)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as e:
        return "no preview: %s" % e


def agent():
    tmp = tempfile.mkdtemp(prefix="ia-live-")
    cfg = ia.Config(["--data", os.path.join(tmp, "data"), "--no-browser"], {"HOME": tmp, "AGENT_QUIET": "1"})
    a = ia.Agent(cfg)
    a.settings.patch({"manual": True, "brand": {"about": "کافهٔ کوچک محلی با قهوهٔ تازه و کیک خانگی", "handle": "demo.cafe"}})
    return a


def run(a, body, title):
    """Starts a job the way the panel does and follows it; returns the finished job."""
    t0, steps, last = time.time(), [], None
    job = a.studio.make(body)
    while job["status"] == "running" and time.time() - t0 < 600:
        if job["step"] != last:
            last = job["step"]
            steps.append("%3.0fs %s" % (time.time() - t0, last))
        time.sleep(0.5)
        job = a.studio.job(job["id"])
    took = time.time() - t0
    plan = job.get("plan") or {}
    ok = job["status"] == "done" and plan.get("source") == "ai" and all(p["file"] for p in job["pictures"])
    note("notice" if ok else "error", title, "status=%s seconds=%.0f words=%s(%s) pictures=%s notes=%s\n%s" % (
        job["status"], took, plan.get("source"), plan.get("why"), [p["source"] or "-" for p in job["pictures"]], job["notes"], "\n".join(steps)))
    note("notice", title + " plan", json.dumps({k: plan.get(k) for k in ("caption", "hashtags", "headline", "sub", "image", "scenes")}, ensure_ascii=False)[:3800])
    for i, p in enumerate(job["pictures"]):
        if p["file"]:
            f = a.store.get(p["file"])
            note("notice", "%s picture %d from %s %sx%s %s bytes" % (title, i + 1, p["source"], f["width"], f["height"], f["size"]), thumb(a.store.path(f)))
        else:
            note("error", "%s picture %d missing" % (title, i + 1), p["why"])
    return job


def check_reel():
    run(agent(), {"idea": "تخفیف ۲۰ درصدی لاتهٔ پاییزی تا آخر هفته", "kind": "reel", "scenes": 3, "style": "photo"}, "reel")


def check_picture():
    a = agent()
    run(a, {"idea": "کیک هویج خانگی تازه از فر درآمد", "kind": "image", "style": "photo"}, "picture")
    out = a.ai.captions("کیک هویج خانگی")                 # right after the plan: the free service asks for patience
    note("notice", "captions right after", json.dumps(out, ensure_ascii=False)[:1500])
    run(a, {"idea": "ساعت کاری تازهٔ کافه: هر روز ۸ صبح تا ۱۱ شب", "kind": "image", "style": "art"}, "second picture")


def check_voice():
    """Is there any speech the free services give without a key? (With a key it is documented; without one it is not.)"""
    import urllib.parse
    a = agent()
    say = urllib.parse.quote("سلام! لاتهٔ پاییزی ما تا آخر هفته بیست درصد تخفیف دارد.", safe="")

    def go(title, method, url, body=None, headers=None):
        t0 = time.time()
        h = dict(headers or {})
        if body is not None:
            h["Content-Type"] = "application/json"
        try:
            status, hdrs, raw = a.graph.http(method, url, json.dumps(body).encode("utf-8") if body is not None else None, h, 90)
        except ia.GraphError as e:
            status, hdrs, raw = 0, {}, str(e).encode("utf-8")
        kind = "mp3" if raw[:3] == b"ID3" or raw[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2") else "wav" if raw[:4] == b"RIFF" else "ogg" if raw[:4] == b"OggS" else "other"
        note("notice" if status == 200 and kind != "other" else "warning", title, "status=%s type=%s kind=%s bytes=%d seconds=%.1f body=%s" % (
            status, hdrs.get("content-type"), kind, len(raw), time.time() - t0, "" if kind != "other" else raw[:400].decode("utf-8", "replace")))
        time.sleep(47)

    go("classic GET model=openai-audio", "GET", "https://text.pollinations.ai/%s?model=openai-audio&voice=nova" % say)
    go("classic POST /openai model=openai-audio", "POST", "https://text.pollinations.ai/openai",
       {"model": "openai-audio", "modalities": ["text", "audio"], "audio": {"voice": "nova", "format": "mp3"},
        "messages": [{"role": "user", "content": "این جمله را عیناً بخوان: سلام! لاتهٔ پاییزی ما بیست درصد تخفیف دارد."}]})
    go("new GET /audio without a key", "GET", "https://gen.pollinations.ai/audio/%s?voice=nova&model=openai/tts-1" % say)
    go("new POST /v1/audio/speech without a key", "POST", "https://gen.pollinations.ai/v1/audio/speech", {"model": "openai/tts-1", "input": "سلام", "voice": "nova"})
    go("classic models list", "GET", "https://text.pollinations.ai/models")
    go("classic image models list", "GET", "https://image.pollinations.ai/models")


if __name__ == "__main__":
    {"reel": check_reel, "picture": check_picture, "voice": check_voice}[sys.argv[1] if len(sys.argv) > 1 else "reel"]()
