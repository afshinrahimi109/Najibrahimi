"""Checks the files the studio made during `serve.py byhand.mjs hand`: are the reels MP4 files that a normal
player decodes from the first frame to the last, upright and of the right length?

    pip install imageio-ffmpeg        (brings an ffmpeg; one on the PATH is used as well)
    python check_made.py [folder]     (default: ./shots)
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import insta_agent as ia  # noqa: E402

# file → (width, height, frames, how the frames are stored)
WANTED = {"made-reel.mp4": (1080, 1920, 390, "1080x1920"), "made-reel-turned.mp4": (1080, 1920, 294, "1920x1080"),
          "made-reel-small.mp4": (720, 1280, 294, "720x1280")}


def ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return None


def say(ok, title, text):
    print(("PASS " if ok else "FAIL ") + title + "  " + text)
    if os.environ.get("GITHUB_ACTIONS"):
        print("::%s title=%s::%s" % ("notice" if ok else "error", title, text))
    return ok


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "shots")
    good = True
    pic = os.path.join(folder, "made-picture.jpg")
    size = ia.image_size(pic) if os.path.exists(pic) else (0, 0)
    good &= say(size == (1080, 1350), "made-picture.jpg", "JPEG %dx%d, %d bytes" % (size + (os.path.getsize(pic) if os.path.exists(pic) else 0,)))
    exe = ffmpeg()
    if not exe:
        return say(False, "ffmpeg", "no ffmpeg found (pip install imageio-ffmpeg)") or 1
    for name, (w, h, frames, stored) in WANTED.items():
        path = os.path.join(folder, name)
        if not os.path.exists(path):
            good &= say(False, name, "the file was not made")
            continue
        with open(path, "rb") as fh:
            head = fh.read(262144)
        first = head[4:8] == b"ftyp" and 0 < head.find(b"moov") < head.find(b"mdat")      # the index before the pictures
        info = subprocess.run([exe, "-hide_banner", "-i", path], stderr=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True).stderr
        # decode everything; "-v error" prints only what a player would stumble over
        errors = subprocess.run([exe, "-hide_banner", "-v", "error", "-i", path, "-map", "0:v:0", "-f", "null", "-"],
                                stderr=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True).stderr.strip()
        shown = subprocess.run([exe, "-hide_banner", "-i", path, "-map", "0:v:0", "-vf", "showinfo", "-f", "null", "-"],
                               stderr=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True).stderr
        sizes = set(re.findall(r" s:(\d+x\d+) ", shown))                  # after the player has turned the picture upright
        count = len(re.findall(r"\] n: *\d+ ", shown))
        duration = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info)
        seconds = (int(duration.group(1)) * 3600 + int(duration.group(2)) * 60 + float(duration.group(3))) if duration else 0
        codec = re.search(r"Video: (\w+) \((\w+)\)", info)
        ok = (not errors and sizes == {"%dx%d" % (w, h)} and count == frames and abs(seconds - frames / 30.0) < 0.05
              and bool(codec) and codec.group(1) == "h264" and (", %s" % stored) in info and first)
        good &= say(ok, name, "%s %s, stored %s, shown %s, %d frames, %.2f s, %d bytes, index first: %s%s" % (
            codec.group(1) if codec else "?", codec.group(2) if codec else "?", stored if (", %s" % stored) in info else "?",
            ",".join(sorted(sizes)) or "?", count, seconds, os.path.getsize(path), first, ("; decoder said: " + errors[:300]) if errors else ""))
    for name in sorted(os.listdir(folder)):
        if name.startswith("made-reel-live."):
            path = os.path.join(folder, name)
            info = subprocess.run([exe, "-hide_banner", "-i", path], stderr=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True).stderr
            stream = re.search(r"Video: [^\n]+", info)
            good &= say(bool(stream) and "720x1280" in stream.group(0), name, (stream.group(0)[:160] if stream else "no video stream") + ", %d bytes" % os.path.getsize(path))
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
