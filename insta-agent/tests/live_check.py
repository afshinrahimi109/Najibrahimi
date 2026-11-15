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


def check_probe():
    """Does the free text service think less (and answer sooner) when asked to?"""
    import random
    a = agent()
    system, ask = a.studio.question("تخفیف ۲۰ درصدی لاتهٔ پاییزی تا آخر هفته", "reel", 3)
    body = {"model": "openai-fast", "messages": [{"role": "system", "content": system}, {"role": "user", "content": ask}],
            "temperature": 0.8, "seed": random.randint(1, 2 ** 31 - 1), "reasoning_effort": "low"}
    t0 = time.time()
    try:
        status, headers, raw = a.graph.http("POST", "https://text.pollinations.ai/openai", json.dumps(body).encode("utf-8"), {"Content-Type": "application/json"}, 150)
        text = raw.decode("utf-8", "replace")
    except ia.GraphError as e:
        status, headers, text = 0, {}, str(e)
    note("notice" if status == 200 else "error", "POST /openai with reasoning_effort low", "status=%s seconds=%.1f chars=%d tokens=%s body=%s" % (
        status, time.time() - t0, len(text), headers.get("x-usage-completion-text-tokens"), text[:1200]))
    time.sleep(50)


if __name__ == "__main__":
    {"reel": check_reel, "picture": check_picture, "probe": check_probe}[sys.argv[1] if len(sys.argv) > 1 else "reel"]()
