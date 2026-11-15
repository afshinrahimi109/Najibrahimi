"""Lets the studio work against the REAL text and picture services, exactly as it does on the owner's phone.

This is NOT part of the normal test run: those tests never leave the machine. GitHub Actions runs this file only on
request (see the workflow), and every finding is written as an annotation so it can be read from the run's summary
page or the API. Pictures come back as very small previews inside those annotations.

    python live_check.py reel|picture|voice|pack
"""
import base64
import io
import json
import os
import shutil
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
    """The narrator against the real speech service. It needs a Pollinations key (environment POLLINATIONS_KEY);
    without one, only the fact the panel tells the owner is checked: no key, no speech."""
    a, key = agent(), os.environ.get("POLLINATIONS_KEY", "").strip()
    if not key:
        try:
            status, _, raw = a.graph.http("POST", a.cfg.gen_api + "/v1/audio/speech", json.dumps({"model": "openai/tts-1", "input": "سلام", "voice": "nova"}).encode("utf-8"),
                                          {"Content-Type": "application/json"}, 60)
        except ia.GraphError as e:
            status, raw = 0, str(e).encode("utf-8")
        refused = status in (401, 403) and not ia.sniff_audio(raw[:64])
        note("notice" if refused else "warning", "speech without a key", "status=%s sound=%s (expected: refused) %s" % (
            status, bool(ia.sniff_audio(raw[:64])), raw[:200].decode("utf-8", "replace")))
        note("notice", "narrated reel", "skipped: no POLLINATIONS_KEY given, so real speech was not tried")
        return
    a.settings.patch({"studio": {"pollen": key}})
    try:
        note("notice", "key", json.dumps(a.studio.check_key(), ensure_ascii=False))
    except ia.UserError as e:
        note("error", "key", str(e))
    job = run(a, {"idea": "تخفیف ۲۰ درصدی لاتهٔ پاییزی تا آخر هفته", "kind": "reel", "scenes": 3, "style": "photo", "voice": True}, "narrated reel")
    for i, v in enumerate(job.get("voices") or []):
        f = a.store.get(v["file"]) if v["file"] else None
        note("notice" if f else "error", "narrated reel voice %d" % (i + 1), "%s | %s" % (
            ("%s %s bytes from %s" % (f["mime"], f["size"], v["source"])) if f else v["why"], v["text"]))


def check_pack():
    """The narrator on the device: does every address the agent knows still hand out the very files it expects?
    Each address is asked by itself, for all the files it should bring; every file is checked against its SHA-256."""
    a, works = agent(), {}
    for base, archive, inside, names in ia.VOICE_SOURCES:
        pack = ia.VoicePack(a)
        pack.dir = tempfile.mkdtemp(prefix="ia-pack-")
        pack.files = {n: ia.VOICE_FILES[n] for n in names}
        pack.sources = [(base, archive, inside, names)]
        t0 = time.time()
        pack.run()
        view, mb = pack.view(), (archive or sum(ia.VOICE_FILES[n][0] for n in names)) / 1e6
        ok = view["state"] == "ready"
        for n in names:
            works[n] = works.get(n, 0) + (1 if ok else 0)
        note("notice" if ok else "warning", "narrator files from " + urlhost(base), "%s: %s, %.1f MB in %.0f s (%s) %s" % (
            base, "every file is the original" if ok else "FAILED", mb, time.time() - t0, ", ".join(names), view["why"]))
        shutil.rmtree(pack.dir, ignore_errors=True)
    first = {}
    for base, archive, inside, names in ia.VOICE_SOURCES:                # what a phone fetches when every first address answers
        if not any(n in first for n in names):
            for n in names:
                first[n] = archive / float(len(names)) if archive else ia.VOICE_FILES[n][0]
    note("notice" if all(works.get(n) for n in ia.VOICE_FILES) else "error", "narrator files",
         "addresses that work, per file: %s; a phone fetches %.1f MB, the files take %.1f MB" % (
             json.dumps(works), sum(first.values()) / 1e6, sum(v[0] for v in ia.VOICE_FILES.values()) / 1e6))
    if not all(works.get(n) for n in ia.VOICE_FILES):
        sys.exit(1)


def urlhost(url):
    return url.split("/")[2]


if __name__ == "__main__":
    {"reel": check_reel, "picture": check_picture, "voice": check_voice, "pack": check_pack}[sys.argv[1] if len(sys.argv) > 1 else "reel"]()
