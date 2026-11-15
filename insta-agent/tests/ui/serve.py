"""Starts the agent in this process and runs one browser script against it.

    python3 serve.py flows.mjs demo      the fake page, no login (what `--demo` shows)
    python3 serve.py connect.mjs sim     an empty agent with login, talking to the built-in simulator
    python3 serve.py byhand.mjs hand     no page and no login; simulated text and picture services for the studio
    python3 serve.py realvoice.mjs real  like "hand", but the narrator on the device is the real one: its files are
                                         downloaded (about 85 MB; AGENT_VOICE_MIRROR=<address>/ names an own copy)

Hostile text is planted in a comment, a message and a caption; the scripts check that none of it runs.
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import insta_agent as ia  # noqa: E402


def gradient_png(path, w, h):
    rows = []
    for y in range(h):
        row = bytearray([0])
        for x in range(w):
            row += bytes((int(255 * x / w), int(255 * y / h), 160))
        rows.append(bytes(row))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(b"".join(rows), 6)) + chunk(b"IEND", b""))


def aac_tone(path):
    """Three beeps as AAC, made by ffmpeg when there is one: phones encode the sound of a reel as AAC, the browsers
    these checks run in cannot, so the panel's MP4 writer gets its AAC from here (see byhand.mjs, step 11b)."""
    exe = shutil.which("ffmpeg")
    if not exe:
        try:
            import imageio_ffmpeg
            exe = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return
    subprocess.call([exe, "-hide_banner", "-v", "error", "-y", "-f", "lavfi", "-i",
                     "aevalsrc=0.5*sin(2*PI*440*t)*lt(mod(t\\,1)\\,0.5):d=3:s=48000", "-ac", "1", "-c:a", "aac", "-b:a", "96k", "-f", "adts", path])


def main():
    script, mode = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "demo")
    tmp = tempfile.mkdtemp(prefix="ia-ui-")
    gradient_png(os.path.join(tmp, "wide.png"), 1200, 900)
    gradient_png(os.path.join(tmp, "tall.png"), 600, 2400)
    with open(os.path.join(tmp, "clip.mp4"), "wb") as f:
        f.write(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00isommp42" + b"\x00" * 50000)
    if mode == "hand":
        aac_tone(os.path.join(tmp, "tone.aac"))
    env = {"AGENT_QUIET": "1", "HOME": tmp, "AGENT_TICK_SEC": "0.5"}
    argv = ["--port", "0", "--no-browser", "--data", os.path.join(tmp, "data")]
    if mode == "demo":
        argv += ["--demo", "--no-auth"]
    else:
        env["AGENT_SIM"] = "1"
    if mode in ("hand", "real"):
        argv += ["--no-auth"]
        env["AGENT_FREE_GAP"] = "2"
    app = ia.App(argv, env)
    app.start()
    sim = app.agent.sim
    if mode == "real":                                 # the narrator's files come from where a phone gets them
        app.agent.pack.files, app.agent.pack.sources = dict(ia.VOICE_FILES), list(ia.VOICE_SOURCES)
        app.cfg.voice_mirror = os.environ.get("AGENT_VOICE_MIRROR", "")
        keep = os.environ.get("AGENT_VOICE_DIR")       # a folder that outlives this run, so the files are fetched once
        if keep:
            app.agent.pack.dir = keep
    if mode in ("hand", "real"):                       # the studio gets made-up words and drawn stand-in pictures
        app.agent.ai.FREE_URL = "http://127.0.0.1:%d/_sim/ai/ptxt/openai" % app.port
        sim.ai_text, sim.ai_delay = sim.demo_plan, 0.3
        sim.free_gap.update(image=1.5, text=1.5)
    sim.video_seconds = 2
    sim.lively = False
    evil = '<img src=x onerror="window.__xss=1"><script>window.__xss=2</script> سلام'
    sim.add_comment(evil, 'x"><svg/onload=window.__xss=3>', 0)
    sim.add_dm(evil, "evil.user")
    sim.media[0]["caption"] += '\n<b onmouseover="window.__xss=4">bold?</b>'
    scratch = os.environ.get("IA_UI_SCRATCH", "/tmp/ia-ui")
    child = dict(os.environ, BASE="http://127.0.0.1:%d" % app.port, KEY=app.web.key, TOKEN=ia.SIM_TOKEN, AI_KEY=sim.ai_key, ASSETS=tmp,
                 SHOTS=os.environ.get("SHOTS", os.path.join(HERE, "shots")),
                 LD_LIBRARY_PATH=os.pathsep.join([os.path.join(scratch, "al2023", "lib"), os.path.join(scratch, "swiftshader"),
                                                  os.environ.get("LD_LIBRARY_PATH", "")]))
    code = 1
    try:
        code = subprocess.call(["node", os.path.join(HERE, script)], env=child, cwd=HERE)
        print("page now has %d posts and %d stories" % (len(sim.media), len(sim.stories)))
    finally:
        app.stop()
        shutil.rmtree(tmp, ignore_errors=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
