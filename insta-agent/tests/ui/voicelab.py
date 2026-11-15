"""Which Persian voice, and which settings, does a listener understand best? The agent's narrator is one of the
Persian Piper voices; nobody listens during the automatic checks, so a speech recogniser (Whisper) stands in for
the listener: every candidate voice reads the same sentences, the recogniser writes down what it hears, and the
score says how much of the sentences came through. The voice that is in insta_agent.py was chosen with this.

    pip install piper-tts faster-whisper
    python voicelab.py                 (downloads the voices, about 65 MB each, and a recogniser model)

Not part of the normal checks. A recogniser is not a person: the score compares voices, it does not say that a
voice is pleasant.
"""
import difflib
import hashlib
import json
import os
import sys
import tempfile
import time
import urllib.request
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import listen  # noqa: E402

REV = "6b9cfaacb4fb2e02a9621227e3c1a48bec9710c3"        # rhasspy/piper-voices at this commit
VOICES = ["amir", "ganji", "ganji_adabi", "reza_ibrahim", "gyro"]
SETTINGS = {"as the voice was published": None, "calmer (0.5 / 1.0 / 0.333)": (0.5, 1.0, 0.333), "calmer and slower (0.5 / 1.1 / 0.333)": (0.5, 1.1, 0.333)}
LINES = [
    "تخفیف بیست درصد لاتهٔ پاییزی تا آخر هفته؛ خبر خوب این هفتهٔ ماست.",
    "قهوهٔ ما هر روز صبح تازه دم می‌شود.",
    "از ساعت هشت صبح تا یازده شب منتظر شما هستیم.",
    "مثل همیشه با بهترین کیفیت آماده شده است.",
    "برای سفارش همین حالا به ما پیام بدهید.",
    "ارسال به سراسر کشور رایگان است.",
    "کیک هویج خانگی ما تازه از فر درآمده است.",
    "این ویدیو را برای دوستانتان هم بفرستید.",
    "جزئیات بیشتر را در کپشن بخوانید.",
    "ما را دنبال کنید تا خبرهای بعدی را از دست ندهید.",
    "فقط تا پایان این هفته فرصت دارید.",
    "قیمت‌ها از دویست و پنجاه هزار تومان شروع می‌شود.",
]


def say(level, title, text):
    print("%s: %s" % (title, text), flush=True)
    if os.environ.get("GITHUB_ACTIONS"):
        print("::%s title=%s::%s" % (level, title.replace(",", " "), str(text).replace("%", "%25").replace("\n", "%0A")), flush=True)


def fetch(url, path):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "insta-agent-voicelab"}), timeout=120) as res, open(path, "wb") as fh:
        digest, size = hashlib.sha256(), 0
        for chunk in iter(lambda: res.read(1 << 20), b""):
            fh.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def main():
    import numpy
    from piper import PiperVoice, SynthesisConfig
    folder = tempfile.mkdtemp(prefix="ia-voicelab-")
    model, model_name = listen.recogniser()
    if model is None:
        say("warning", "voice lab", "no recogniser model could be loaded")
        return 0
    table, facts = [], []
    for name in VOICES:
        base = "https://huggingface.co/rhasspy/piper-voices/resolve/%s/fa/fa_IR/%s/medium/fa_IR-%s-medium.onnx" % (REV, name, name)
        path = os.path.join(folder, name + ".onnx")
        try:
            size, sha = fetch(base, path)
            fetch(base + ".json", path + ".json")
            voice = PiperVoice.load(path)
        except Exception as e:
            say("warning", "voice lab", "%s could not be loaded: %s" % (name, str(e)[:300]))
            continue
        facts.append("%s: %d bytes, sha256 %s, sample rate %s, published settings %s / %s / %s" % (
            name, size, sha, voice.config.sample_rate, voice.config.noise_scale, voice.config.length_scale, voice.config.noise_w_scale))
        for label, knobs in SETTINGS.items():
            conf = SynthesisConfig(normalize_audio=False) if knobs is None else SynthesisConfig(
                noise_scale=knobs[0], length_scale=knobs[1], noise_w_scale=knobs[2], normalize_audio=False)
            # all lines in one piece of sound with pauses between them: the recogniser takes half a minute per piece, however short
            t0, pieces, seconds = time.time(), [], 0.0
            for line in LINES:
                wav = os.path.join(folder, "line.wav")
                with wave.open(wav, "wb") as fh:
                    voice.synthesize_wav(line, fh, syn_config=conf)
                with wave.open(wav, "rb") as fh:
                    rate, raw = fh.getframerate(), fh.readframes(fh.getnframes())
                pcm = numpy.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
                seconds += len(pcm) / float(rate)
                at = numpy.linspace(0, len(pcm), int(len(pcm) * 16000 / rate), endpoint=False)      # to the recogniser's 16 kHz
                pieces += [numpy.interp(at, numpy.arange(len(pcm)), pcm).astype("float32"), numpy.zeros(int(16000 * 0.8), dtype="float32")]
            segments, _ = model.transcribe(numpy.concatenate(pieces), language="fa", beam_size=5)
            heard = " ".join(seg.text.strip() for seg in segments)
            b_all = listen.plain(heard)
            score = difflib.SequenceMatcher(None, listen.plain(" ".join(LINES)), b_all, autojunk=False).ratio()
            got, per_line, found, total = set(listen.plain(w) for w in heard.split()), [], 0, 0
            for line in LINES:
                want = listen.plain(line)
                blocks = difflib.SequenceMatcher(None, want, b_all, autojunk=False).get_matching_blocks()
                per_line.append(sum(x.size for x in blocks) / float(max(1, len(want))))
                wanted = [w for w in (listen.plain(w) for w in line.split()) if w]
                found += sum(1 for w in wanted if w in got)
                total += len(wanted)
            row = {"voice": name, "settings": label, "letters": round(100 * score, 1), "words": round(100.0 * found / max(1, total), 1),
                   "worst": round(100 * min(per_line)), "seconds": round(seconds, 1), "took": round(time.time() - t0),
                   "heard": heard + "\n(line by line: %s)" % ", ".join("%d%%" % round(100 * x) for x in per_line)}
            table.append(row)
            print("%s, %s: %s\n%s" % (name, label, json.dumps({k: v for k, v in row.items() if k != "heard"}, ensure_ascii=False), row["heard"]), flush=True)
    table.sort(key=lambda r: (-r["letters"], -r["words"]))
    # GitHub keeps ten notes per step: the result first, then what was heard from the best setting of each voice
    say("notice", "voice lab result (recogniser: Whisper %s)" % model_name, "\n".join(
        "%-13s %-40s letters %5.1f%%  whole words %5.1f%%  worst line %3d%%  %5.1f s of speech" % (
            r["voice"], r["settings"], r["letters"], r["words"], r["worst"], r["seconds"]) for r in table) + "\n\n" + "\n".join(facts))
    seen = set()
    for r in table:
        if r["voice"] not in seen:
            seen.add(r["voice"])
            say("notice", "voice lab %s at its best (%s)" % (r["voice"], r["settings"]), r["heard"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
