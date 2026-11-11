#!/usr/bin/env python3
"""
ساخت تیزر تبلیغاتی عمودی (1080x1920) برای بازی «کی‌کرافت کره».
تصاویر استاتیک با حرکات دوربین (Ken Burns) + پارالاکس، متن فارسی متحرک،
اورلی وُکسل/اسکن‌لاین و نریشن صوتی ترکیب می‌شود و خروجی MP4 می‌دهد.

اجرا:  python3 build_video.py
نیاز:  pip install pillow imageio-ffmpeg arabic-reshaper python-bidi
"""
import math
import os
import subprocess
import wave

import arabic_reshaper
import imageio_ffmpeg
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(BASE, "assets")
AUDIO = os.path.join(BASE, "audio")
FONTS = os.path.join(BASE, "fonts")
OUT = os.path.join(BASE, "k-craft-korea-teaser.mp4")

W, H = 1080, 1920
FPS = 30
FF = imageio_ffmpeg.get_ffmpeg_exe()

F_BLACK = os.path.join(FONTS, "Vazirmatn-FD-Black.ttf")
F_BOLD = os.path.join(FONTS, "Vazirmatn-FD-Bold.ttf")
F_MED = os.path.join(FONTS, "Vazirmatn-FD-Medium.ttf")

GOLD = (255, 214, 138)
WHITE = (255, 255, 255)
PINK = (255, 156, 196)


def fa(text: str) -> str:
    """شکل‌دهی و ترتیب راست‌به‌چپ فارسی برای ترسیم با Pillow."""
    return get_display(arabic_reshaper.reshape(text))


def font(path, size):
    return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.BASIC)


# ---------------------------------------------------------------- timeline
# هر سکانس: تصویر، مدت (ثانیه)، زوم، جملات متحرک
SCENES = [
    dict(img="01_village.png", dur=10.5, zoom=0.11, pan=(0.35, -0.25), pos="top",
         kicker="وُکسل + کره", title="کی‌کرافت کره", en="K-CRAFT KOREA",
         lines=["شبیه‌ساز ماین‌کرفت", "با روح کره‌ای"]),
    dict(img="02_character.png", dur=10.2, zoom=0.14, pan=(-0.2, 0.2), pos="bottom",
         kicker="چهره‌های اصیل", title="چهره کره‌ای", en="KOREAN FACES",
         lines=["چشم تک‌پلک و ابروی صاف", "کلاه گات و هانبوک قرمز"]),
    dict(img="06_selfie.png", dur=7.0, zoom=0.10, pan=(0.25, 0.15), pos="bottom",
         kicker="استودیو شخصی‌سازی", title="خودت را بساز", en="CHARACTER STUDIO",
         lines=["کلید C : طراحی چهره", "مو، چهره و پوشش کره‌ای"]),
    dict(img="03_mining.png", dur=8.1, zoom=0.13, pan=(-0.3, -0.15), pos="top",
         kicker="جهان وکسل", title="معدن الماس", en="VOXEL WORLD",
         lines=["زغال، آهن، طلا، الماس", "۶۰ فریم بر ثانیه"]),
    dict(img="04_food.png", dur=8.0, zoom=0.12, pan=(0.2, -0.2), pos="top",
         kicker="حالت بقا", title="کیمباب و توکبوکی", en="SURVIVAL & FOOD",
         lines=["غذا، ساخت‌وساز، معامله", "با اهالی دهکده"]),
    dict(img="05_night.png", dur=8.7, zoom=0.12, pan=(-0.25, 0.2), pos="top",
         kicker="جشن فانوس", title="شب دهکده چوسان", en="LANTERN NIGHT",
         lines=["فانوس ابریشمی و آتش‌بازی", "چرخه روز و شب"]),
]

END_CARD_DUR = 12.5
TOTAL = sum(s["dur"] for s in SCENES) + END_CARD_DUR


def ease(t):
    """easeInOutSine"""
    return 0.5 - 0.5 * math.cos(math.pi * min(max(t, 0.0), 1.0))


# ---------------------------------------------------------------- assets
_images = {}


def load_image(name):
    if name not in _images:
        im = Image.open(os.path.join(ASSETS, name)).convert("RGB")
        # پر کردن کامل کادر ۹:۱۶ با برش مرکزی
        tw, th = W, H
        s = max(tw / im.width, th / im.height)
        im = im.resize((max(tw, int(im.width * s + 0.5)), max(th, int(im.height * s + 0.5))),
                       Image.LANCZOS)
        left = (im.width - W) // 2
        top = (im.height - H) // 2
        _images[name] = im.crop((left, top, left + W, top + H))
    return _images[name]


def ken_burns(base, p, zoom, pan):
    """برش متحرک از تصویر پایه (p بین ۰ و ۱)."""
    z = 1.0 + zoom * ease(p)
    cw, ch = base.width / z, base.height / z
    ox = (1 - 1 / z) * W * (0.5 + pan[0] * (ease(p) - 0.5) * 2)
    oy = (1 - 1 / z) * H * (0.5 + pan[1] * (ease(p) - 0.5) * 2)
    ox = min(max(ox, 0), base.width - cw)
    oy = min(max(oy, 0), base.height - ch)
    return base.resize((W, H), Image.LANCZOS, box=(ox, oy, ox + cw, oy + ch))


# ---------------------------------------------------------------- overlay
SCAN = Image.new("RGBA", (W, H), (0, 0, 0, 0))
_d = ImageDraw.Draw(SCAN)
for y in range(0, H, 6):
    _d.line([(0, y), (W, y)], fill=(0, 0, 0, 24))
for x in range(0, W, 6):
    _d.line([(x, 0), (x, H)], fill=(0, 0, 0, 12))

VIGNETTE = Image.new("L", (W, H), 0)
_d = ImageDraw.Draw(VIGNETTE)
_d.ellipse([-W * 0.35, -H * 0.22, W * 1.35, H * 1.22], fill=255)
VIGNETTE = VIGNETTE.filter(ImageFilter.GaussianBlur(140))
DARK = Image.new("RGB", (W, H), (4, 2, 12))
VIGNETTE_RGB = Image.merge("RGB", (VIGNETTE, VIGNETTE, VIGNETTE))


def draw_center_text(canvas, txt, f, y, color, alpha=255, shadow=True):
    """متن وسط‌چین با سایه؛ ترسیم روی بوم کوچک برای سرعت بالا."""
    if alpha <= 0 or not txt:
        return
    bbox = f.getbbox(txt)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = 24
    cw, ch = int(tw + 2 * pad), int(th + 2 * pad)
    layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.text((pad - bbox[0], pad - bbox[1]), txt, font=f, fill=color + (alpha,))
    if shadow:
        sh = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        ds = ImageDraw.Draw(sh)
        ds.text((pad - bbox[0] + 3, pad - bbox[1] + 5), txt, font=f,
                fill=(0, 0, 0, int(alpha * 0.8)))
        layer = Image.alpha_composite(sh.filter(ImageFilter.GaussianBlur(4)), layer)
    x = int((W - tw) / 2 - pad)
    canvas.paste(layer, (x, int(y - pad)), layer)


def draw_pill(canvas, txt, f, y, alpha, fill=(255, 255, 255), fg=(18, 10, 30)):
    """برچسب گرد با گوشه‌های نرم."""
    if alpha <= 0 or not txt:
        return
    bbox = f.getbbox(txt)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    padx, pady = 34, 18
    cw, ch = int(tw + 2 * padx + 12), int(th + 2 * pady + 12)
    layer = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    r = (th + 2 * pady) / 2
    d.rounded_rectangle([6, 6, cw - 6, ch - 6], radius=r,
                        fill=fill + (int(alpha * 0.93),))
    d.text((6 + padx - bbox[0], 6 + pady - bbox[1]), txt, font=f, fill=fg + (alpha,))
    x = int((W - cw) / 2)
    canvas.paste(layer, (x, int(y - 6)), layer)


def draw_gradient_bar(canvas, y, p, color=GOLD):
    w = int(W * 0.18 * ease(min(p * 3, 1)))
    if w < 2:
        return
    d = ImageDraw.Draw(canvas)
    d.rounded_rectangle([W / 2 - w / 2, y, W / 2 + w / 2, y + 8], radius=4, fill=color)


def frame_caption(canvas, scene, local, dur):
    """متن‌های متحرک روی هر سکانس (بالا یا پایین کادر)."""
    fade_in = min(local / 0.6, 1.0)
    fade_out = min(max((dur - local) / 0.6, 0.0), 1.0)
    a = int(255 * ease(fade_in) * ease(fade_out))
    rise = int((1 - ease(fade_in)) * 46)

    bottom = scene.get("pos") == "bottom"
    top = (H - 660) if bottom else 300

    f_kick = font(F_BOLD, 40)
    f_title = font(F_BLACK, 100)
    f_en = font(F_BOLD, 30)
    f_line = font(F_MED, 46)

    draw_pill(canvas, fa(scene["kicker"]), f_kick, top - 96 + rise, a,
              fill=GOLD, fg=(30, 12, 40))
    draw_center_text(canvas, fa(scene["title"]), f_title, top + 30 + rise, WHITE, a)
    draw_gradient_bar(canvas, top + 174 + rise, min(local / 0.8, 1))
    if scene.get("en"):
        ea = int(a * ease(min(max((local - 0.3) / 0.5, 0), 1)))
        draw_center_text(canvas, scene["en"], f_en, top + 200 + rise, GOLD, ea)
    y = top + 262
    for i, ln in enumerate(scene["lines"]):
        la = int(a * ease(min(max((local - 0.45 - 0.18 * i) / 0.5, 0), 1)))
        draw_center_text(canvas, fa(ln), f_line, y + 70 * i + int((1 - la / 255) * 20),
                         (255, 240, 230), la)


def scene_shade(canvas, bottom):
    """سایه گرادیانی برای خوانایی متن، در جهت همان لبه."""
    grad = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    span = 900
    if bottom:
        for i in range(span):
            y = H - 1 - i
            gd.line([(0, y), (W, y)], fill=(6, 3, 18, int(175 * (1 - i / span) ** 1.5)))
    else:
        for y in range(span):
            gd.line([(0, y), (W, y)], fill=(6, 3, 18, int(175 * (1 - y / span) ** 1.5)))
    return Image.alpha_composite(canvas.convert("RGBA"), grad).convert("RGB")


_WM = None


def draw_hud(canvas, p_global):
    """نوار پیشرفت + واترمارک کوچک."""
    global _WM
    d = ImageDraw.Draw(canvas)
    d.rectangle([0, H - 8, int(W * p_global), H], fill=GOLD)
    if _WM is None:
        _WM = Image.new("RGBA", (420, 70), (0, 0, 0, 0))
        ImageDraw.Draw(_WM).text((0, 0), "K-CRAFT KOREA", font=font(F_BOLD, 30),
                                 fill=(255, 255, 255, 195))
    canvas.paste(_WM, (36, 34), _WM)


PETAL_COLORS = [(255, 176, 208), (255, 236, 244), (255, 210, 226)]
def _petal_sprite(size, color, alpha):
    key = (size, color, alpha)
    if key not in _PETAL_CACHE:
        im = Image.new("RGBA", (size, size), color + (alpha,))
        _PETAL_CACHE[key] = im
    return _PETAL_CACHE[key]


_PETAL_CACHE = {}


def draw_petals(canvas, t, n=22, alpha=130):
    """گلبرگ‌های شکوفه گیلاس شناور (مربعی، وُکسل‌گونه)."""
    for i in range(n):
        seed = i * 97.13
        speed = 62 + (i % 7) * 24
        x = (seed * 7.31) % W + math.sin(t * 0.9 + i) * 46
        y = ((t * speed + seed * 11) % (H + 120)) - 60
        size = 8 + (i % 4) * 6
        color = PETAL_COLORS[0] if i % 3 else PETAL_COLORS[1]
        canvas.paste(_petal_sprite(size, color, alpha), (int(x), int(y)),
                     _petal_sprite(size, color, alpha))


def draw_voxel_burst(canvas, t, center=(W / 2, H / 2), radius=420, n=40, color=GOLD):
    """جرقه‌های مکعبی برای سکانس جشن."""
    if t < 0 or t > 2.4:
        return
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    k = ease(min(t / 1.2, 1))
    for i in range(n):
        ang = (i / n) * math.tau + 0.3
        r = radius * k * (0.55 + ((i * 37) % 100) / 140)
        x = center[0] + math.cos(ang) * r
        y = center[1] + math.sin(ang) * r * 0.85
        s = max(2, int(14 * (1 - k) + 3))
        a = int(230 * (1 - min(t / 2.4, 1)))
        c = color if i % 4 else (120, 220, 255)
        d.rectangle([x, y, x + s, y + s], fill=c + (a,))
    canvas.paste(layer, (0, 0), layer)


# ---------------------------------------------------------------- end card
END_BG = load_image("05_night.png").filter(ImageFilter.GaussianBlur(3))
END_BG = Image.blend(END_BG, Image.new("RGB", (W, H), (8, 6, 26)), 0.62)


def end_card_frame(local, dur):
    canvas = END_BG.copy()
    a_in = ease(min(local / 0.7, 1))
    f_logo = font(F_BLACK, 126)
    f_sub = font(F_BOLD, 44)
    f_info = font(F_MED, 42)
    f_badge = font(F_BOLD, 36)

    draw_center_text(canvas, fa("کی‌کرافت"), f_logo, 560 - int((1 - a_in) * 60), WHITE, int(255 * a_in))
    draw_center_text(canvas, fa("K-Craft Korea"), f_sub, 720, GOLD, int(255 * a_in))
    draw_gradient_bar(canvas, 800, min(local / 0.9, 1))

    rows = ["۱۰۰٪ آفلاین  •  اندروید و ویندوز", "فایل نصبی آماده  •  نسخه تک‌فایل", "وب‌اپلیکیشن PWA"]
    for i, r in enumerate(rows):
        la = ease(min(max((local - 0.8 - 0.22 * i) / 0.55, 0), 1))
        draw_pill(canvas, fa(r), f_badge, 880 + 96 * i, int(255 * la),
                  fill=(255, 255, 255) if i == 0 else (255, 255, 255), fg=(24, 12, 40))

    cta = ease(min(max((local - 1.9) / 0.6, 0), 1))
    if cta > 0:
        pulse = 1 + 0.03 * math.sin(local * 5)
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        txt = fa("همین حالا نصب کن")
        fl = font(F_BLACK, 58)
        bbox = d.textbbox((0, 0), txt, font=fl)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        padx, pady = 52, 26
        bw, bh = (tw + 2 * padx) * pulse, (th + 2 * pady) * pulse
        x0, y0 = (W - bw) / 2, 1330 + (th + 2 * pady - bh) / 2
        d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=bh / 2,
                            fill=(255, 92, 138, int(255 * cta)))
        d.text((x0 + bw / 2 - tw / 2 - bbox[0], y0 + bh / 2 - th / 2 - bbox[1]),
               txt, font=fl, fill=(255, 255, 255, int(255 * cta)))
        canvas.paste(layer, (0, 0), layer)

    draw_center_text(canvas, fa("Najibrahimi/K-Craft-Korea"), font(F_MED, 34), 1700, (200, 200, 220),
                     int(200 * cta))
    return canvas


# ---------------------------------------------------------------- render
def render_frames():
    order = []
    for idx, s in enumerate(SCENES):
        order.append(("scene", idx))
    order.append(("end", 0))

    for kind, idx in order:
        if kind == "scene":
            s = SCENES[idx]
            base = load_image(s["img"])
            n = int(s["dur"] * FPS)
            for f in range(n):
                local = f / FPS
                p = local / s["dur"]
                canvas = ken_burns(base, p, s["zoom"], s["pan"])
                # گرمای رنگ ملایم + کنتراست
                canvas = Image.blend(canvas, Image.new("RGB", (W, H), (255, 170, 120)), 0.05)
                # وینیت (چند برابر کردن نقاب ۸بیتی)
                canvas = Image.composite(canvas, DARK, VIGNETTE)
                # سایه لبه برای خوانایی متن
                canvas = scene_shade(canvas, s.get("pos") == "bottom")
                canvas = Image.alpha_composite(canvas.convert("RGBA"), SCAN).convert("RGB")
                draw_petals(canvas, local + idx * 3.0, 22, 130)
                if s["img"] == "05_night.png":
                    draw_voxel_burst(canvas, local - 0.6)
                frame_caption(canvas, s, local, s["dur"])
                gp = 0.0
                for j in range(idx):
                    gp += SCENES[j]["dur"]
                draw_hud(canvas, (gp + local) / TOTAL)
                yield canvas
        else:
            n = int(END_CARD_DUR * FPS)
            for f in range(n):
                local = f / FPS
                canvas = end_card_frame(local, END_CARD_DUR)
                canvas = Image.alpha_composite(canvas.convert("RGBA"), SCAN).convert("RGB")
                draw_petals(canvas, local + 40, 18, 110)
                gp = sum(s["dur"] for s in SCENES)
                draw_hud(canvas, (gp + local) / TOTAL)
                yield canvas


def build_concat_audio(path):
    """نریشن‌ها را پشت سر هم با مکث کوچک بچسبان و یک WAV بساز."""
    files = ["n1.mp3", "n2.mp3", "n3.mp3", "n4.mp3"]
    listfile = os.path.join(AUDIO, "list.txt")
    with open(listfile, "w") as fh:
        for i, f in enumerate(files):
            fh.write(f"file '{os.path.join(AUDIO, f)}'\n")
            fh.write("duration 0.35\n" if i < len(files) - 1 else "")
    subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "concat", "-safe", "0", "-i", listfile,
                    "-ar", "44100", "-ac", "2", path], check=True)
    return path


def main():
    wav_path = os.path.join(BASE, "narration.wav")
    build_concat_audio(wav_path)

    # طول نریشن
    with wave.open(wav_path) as wf:
        voice_len = wf.getnframes() / wf.getframerate()
    print(f"narration: {voice_len:.2f}s | video: {TOTAL:.2f}s")

    dur = max(TOTAL, voice_len + 0.6)
    cmd = [FF, "-y", "-hide_banner", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", wav_path,
           "-filter_complex",
           f"[1:a]apad,atrim=0:{dur},afade=t=out:st={dur - 1.6}:d=1.6,"
           f"volume=1.0[a]",
           "-map", "0:v", "-map", "[a]",
           "-c:v", "libx264", "-preset", "medium", "-crf", "20",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart",
           "-c:a", "aac", "-b:a", "160k", "-shortest", OUT]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    total_frames = int(dur * FPS)
    for i, frame in enumerate(render_frames()):
        proc.stdin.write(frame.tobytes())
        if i % 60 == 0:
            print(f"  frame {i}/{total_frames}", flush=True)
    proc.stdin.close()
    proc.wait()
    if proc.returncode != 0:
        raise SystemExit("ffmpeg failed")
    size = os.path.getsize(OUT) / 1e6
    print(f"OK -> {OUT} ({size:.1f} MB)")


if __name__ == "__main__":
    main()
