"""Checks the files the studio made during `serve.py byhand.mjs hand`: are the reels MP4 files that a normal
player decodes from the first frame to the last, upright and of the right length? And the narrated ones: is there
a sound track that decodes, lasts as long as the picture, and has speech where the scenes are?

    pip install imageio-ffmpeg        (brings an ffmpeg; one on the PATH is used as well)
    python check_made.py [folder]     (default: ./shots)
    python check_made.py --real       only the reel of `serve.py realvoice.mjs real` (the real Persian narrator);
                                      its sound is also written next to it as a WAV, for listen.py
"""
import array
import json
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


def heard(exe, path):
    """The sound of a file as the decoder gives it: (seconds, loudest sample, stretches of sound, what the decoder complained about)."""
    run = subprocess.run([exe, "-hide_banner", "-v", "error", "-i", path, "-map", "0:a:0", "-f", "s16le", "-ac", "1", "-ar", "48000", "-"],
                         stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    pcm = array.array("h")
    pcm.frombytes(run.stdout[:len(run.stdout) // 2 * 2])
    if sys.byteorder == "big":
        pcm.byteswap()
    step, loud = 2400, []                               # 50 ms windows
    for i in range(0, len(pcm) - step + 1, step):
        loud.append(max(abs(x) for x in pcm[i:i + step]) > 1200)
    stretches, quiet = 0, 99
    for on in loud:                                    # sound after at least 0.4 s of quiet begins a new stretch
        if on:
            stretches += quiet >= 8
            quiet = 0
        else:
            quiet += 1
    return len(pcm) / 48000.0, max([abs(x) for x in pcm] or [0]), stretches, run.stderr.decode("utf-8", "replace").strip()


def narrated(exe, folder, listing="made.json", least=4):
    """The reels with sound; what the panel said about each is in made.json."""
    listing = os.path.join(folder, listing)
    if not os.path.exists(listing):
        return say(False, os.path.basename(listing), "the narrated reels were not made")
    with open(listing, encoding="utf-8") as fh:
        made = json.load(fh)
    good = len(made) >= least
    for name, m in sorted(made.items()):
        path = os.path.join(folder, name)
        if not os.path.exists(path):
            good &= say(False, name, "the file was not made")
            continue
        info = subprocess.run([exe, "-hide_banner", "-i", path], stderr=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True).stderr
        video, audio = re.search(r"Video: (\w+)[^\n]*?, (\d+x\d+)", info), re.search(r"Audio: (\w+)[^\n]*?(\d+) Hz, (\w+)", info)
        errors = subprocess.run([exe, "-hide_banner", "-v", "error", "-i", path, "-map", "0:v:0", "-f", "null", "-"],
                                stderr=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True).stderr.strip()
        shown = subprocess.run([exe, "-hide_banner", "-i", path, "-map", "0:v:0", "-vf", "showinfo", "-f", "null", "-"],
                               stderr=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True).stderr
        frames = len(re.findall(r"\] n: *\d+ ", shown))
        seconds, peak, stretches, complaint = heard(exe, path) if audio else (0, 0, 0, "no sound track")
        loose = bool(m.get("loose"))                   # recorded by the browser while it played: lengths are near, not exact
        ok = (bool(video) and video.group(1) == "h264" and video.group(2) == "%dx%d" % (m["w"], m["h"]) and bool(audio)
              and audio.group(1) in ("aac", "opus") and audio.group(2) == "48000" and not complaint and peak > 3000
              and (m["sound"] != "aac" or "mp4a" in info)
              and abs(seconds - m["seconds"]) < (1.0 if loose else 0.08)
              and (loose or (not errors and frames == int(round(m["seconds"] * 30))))
              and ("speech" not in m or (stretches >= m["speech"] if m.get("real") else stretches == m["speech"]))   # a real voice pauses inside a line too
              and (loose or audio.group(1) == m["sound"]))
        if m.get("real") and audio:                    # for the speech recogniser
            subprocess.run([exe, "-hide_banner", "-v", "error", "-y", "-i", path, "-map", "0:a:0", "-ac", "1", "-ar", "16000", path + ".wav"])
        good &= say(ok, name, "%s %s, %d frames; sound: %s %s Hz %s, %.2f s (the reel: %.2f s), loudest %d of 32767, %d stretches of sound%s%s" % (
            video.group(1) if video else "?", video.group(2) if video else "?", frames, audio.group(1) if audio else "none",
            audio.group(2) if audio else "?", audio.group(3) if audio else "?", seconds, m["seconds"], peak, stretches,
            ("; decoder said: " + (complaint or errors)[:300]) if (complaint or (errors and not loose)) else "",
            "; made by: " + str(m.get("voice"))))
    return good


def main():
    args = [a for a in sys.argv[1:] if a != "--real"]
    folder = args[0] if args else os.path.join(HERE, "shots")
    if "--real" in sys.argv[1:]:
        exe = ffmpeg()
        if not exe:
            return say(False, "ffmpeg", "no ffmpeg found (pip install imageio-ffmpeg)") or 1
        return 0 if narrated(exe, folder, "made-real.json", 1) else 1
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
    good &= narrated(exe, folder)
    for name in sorted(os.listdir(folder)):
        if name.startswith("made-reel-live."):
            path = os.path.join(folder, name)
            info = subprocess.run([exe, "-hide_banner", "-i", path], stderr=subprocess.PIPE, stdout=subprocess.PIPE, universal_newlines=True).stderr
            stream = re.search(r"Video: [^\n]+", info)
            good &= say(bool(stream) and "720x1280" in stream.group(0), name, (stream.group(0)[:160] if stream else "no video stream") + ", %d bytes" % os.path.getsize(path))
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
