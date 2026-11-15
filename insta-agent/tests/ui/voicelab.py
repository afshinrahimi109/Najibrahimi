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
            scores, words, seconds, heard_all, t0 = [], [], 0.0, [], time.time()
            for line in LINES:
                wav = os.path.join(folder, "line.wav")
                with wave.open(wav, "wb") as fh:
                    voice.synthesize_wav(line, fh, syn_config=conf)
                with wave.open(wav, "rb") as fh:
                    rate, raw = fh.getframerate(), fh.readframes(fh.getnframes())
                pcm = numpy.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
                seconds += len(pcm) / float(rate)
                at = numpy.linspace(0, len(pcm), int(len(pcm) * 16000 / rate), endpoint=False)      # to the recogniser's 16 kHz
                segments, _ = model.transcribe(numpy.interp(at, numpy.arange(len(pcm)), pcm).astype("float32"), language="fa", beam_size=5)
                heard = " ".join(s.text.strip() for s in segments)
                heard_all.append(heard)
                a, b = listen.plain(line), listen.plain(heard)
                scores.append(difflib.SequenceMatcher(None, a, b, autojunk=False).ratio())
                want, got = [listen.plain(w) for w in line.split()], set(listen.plain(w) for w in heard.split())
                want = [w for w in want if w]
                words.append(sum(1 for w in want if w in got) / float(max(1, len(want))))
            row = {"voice": name, "settings": label, "letters": round(100 * sum(scores) / len(scores), 1), "words": round(100 * sum(words) / len(words), 1),
                   "worst": round(100 * min(scores)), "seconds": round(seconds, 1), "took": round(time.time() - t0)}
            table.append(row)
            say("notice", "voice lab %s, %s" % (name, label), "%s\n%s" % (json.dumps(row, ensure_ascii=False), "\n".join(
                "%3d%%  %s  ←  %s" % (round(100 * s), h, line) for s, h, line in zip(scores, heard_all, LINES))))
    table.sort(key=lambda r: (-r["letters"], -r["words"]))
    say("notice", "voice lab result (recogniser: Whisper %s)" % model_name, "\n".join(
        "%-13s %-40s letters %5.1f%%  whole words %5.1f%%  worst line %3d%%  %5.1f s of speech" % (
            r["voice"], r["settings"], r["letters"], r["words"], r["worst"], r["seconds"]) for r in table) + "\n\n" + "\n".join(facts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
