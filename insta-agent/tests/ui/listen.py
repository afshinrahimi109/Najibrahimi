"""Does the narrator on the device say what it was given? A speech recogniser (Whisper, through faster-whisper)
listens to the reel that `serve.py realvoice.mjs real` made and writes down what it hears; that is compared with
the lines the narrator was asked to read.

    pip install faster-whisper imageio-ffmpeg
    python check_made.py --real        (also writes the reel's sound next to it as a WAV)
    python listen.py [folder]          (default: ./shots)

Not part of the normal checks: the recogniser's model is a download of several gigabytes. GitHub Actions runs this
on request only. A recogniser is not a person: a high score says the words can be made out, not that the voice is
pleasant.
"""
import difflib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
import insta_agent as ia  # noqa: E402

SAME = {"ي": "ی", "ى": "ی", "ئ": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه", "ؤ": "و", "أ": "ا", "إ": "ا", "آ": "ا", "ء": ""}


def plain(text):
    """The letters alone, the way a listener would write them: numbers and signs in words, one spelling per letter,
    no marks, no spaces (so "می‌شود", "می شود" and "میشود" are the same)."""
    text = ia.spoken(str(text))
    text = "".join(SAME.get(c, c) for c in text)
    text = re.sub(r"[\u064b-\u065f\u0670\u0640\u200c\u200d\u200e\u200f]", "", text)
    return re.sub(r"[^0-9A-Za-z\u0621-\u063a\u0641-\u064a\u067e\u0686\u0698\u06a9\u06af\u06cc]", "", text).lower()


def note(ok, title, text):
    print(("PASS " if ok else "FAIL ") + title + "  " + text)
    if os.environ.get("GITHUB_ACTIONS"):
        print("::%s title=%s::%s" % ("notice" if ok else "error", title, str(text).replace("%", "%25").replace("\n", "%0A")))
    return ok


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "shots")
    with open(os.path.join(folder, "made-real.json"), encoding="utf-8") as fh:
        made = json.load(fh)
    from faster_whisper import WhisperModel
    model = WhisperModel(os.environ.get("WHISPER_MODEL", "large-v3"), device="cpu", compute_type="int8")
    good = True
    for name, m in sorted(made.items()):
        wav = os.path.join(folder, name + ".wav")
        if not os.path.exists(wav):
            good &= note(False, name, "no sound file; run check_made.py --real first")
            continue
        segments, _ = model.transcribe(wav, language="fa", beam_size=5)
        parts = [(s.start, s.end, s.text.strip()) for s in segments]
        heard, asked = " ".join(p[2] for p in parts), " ".join(m["says"])
        a, b = plain(asked), plain(heard)
        score = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
        lines = []
        for line in m["says"]:                         # how much of each line turns up in what was heard
            want = plain(line)
            blocks = difflib.SequenceMatcher(None, want, b, autojunk=False).get_matching_blocks()
            lines.append(sum(x.size for x in blocks) / float(max(1, len(want))))
        good &= note(score >= 0.6, "what the recogniser heard in " + name, "%d%% of the letters match (line by line: %s)\nasked: %s\nheard: %s\n%s" % (
            round(score * 100), ", ".join("%d%%" % round(x * 100) for x in lines), asked, heard,
            "\n".join("%5.1f–%5.1f s  %s" % p for p in parts)))
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
