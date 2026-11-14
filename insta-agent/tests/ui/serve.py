"""Starts the agent in this process and runs one browser script against it.

    python3 serve.py flows.mjs demo      the fake page, no login (what `--demo` shows)
    python3 serve.py connect.mjs sim     an empty agent with login, talking to the built-in simulator

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


def main():
    script, mode = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "demo")
    tmp = tempfile.mkdtemp(prefix="ia-ui-")
    gradient_png(os.path.join(tmp, "wide.png"), 1200, 900)
    gradient_png(os.path.join(tmp, "tall.png"), 600, 2400)
    with open(os.path.join(tmp, "clip.mp4"), "wb") as f:
        f.write(b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00isommp42" + b"\x00" * 50000)
    env = {"AGENT_QUIET": "1", "HOME": tmp, "AGENT_TICK_SEC": "0.5"}
    argv = ["--port", "0", "--no-browser", "--data", os.path.join(tmp, "data")]
    if mode == "demo":
        argv += ["--demo", "--no-auth"]
    else:
        env["AGENT_SIM"] = "1"
    app = ia.App(argv, env)
    app.start()
    sim = app.agent.sim
    sim.video_seconds = 2
    sim.lively = False
    evil = '<img src=x onerror="window.__xss=1"><script>window.__xss=2</script> سلام'
    sim.add_comment(evil, 'x"><svg/onload=window.__xss=3>', 0)
    sim.add_dm(evil, "evil.user")
    sim.media[0]["caption"] += '\n<b onmouseover="window.__xss=4">bold?</b>'
    scratch = os.environ.get("IA_UI_SCRATCH", "/tmp/ia-ui")
    child = dict(os.environ, BASE="http://127.0.0.1:%d" % app.port, KEY=app.web.key, TOKEN=ia.SIM_TOKEN, ASSETS=tmp,
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
