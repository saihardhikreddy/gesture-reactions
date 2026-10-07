"""Renders assets/demo.gif and assets/effects.png from the real effect code.

    python scripts/make_demo.py
"""

import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from effects import EffectPlayer  # noqa: E402

W, H = 640, 360
FPS = 15
SCENES = [
    ("thumbs_up", "One thumbs up", "Thumbs up"),
    ("fireworks", "Two thumbs up", "Fireworks"),
    ("balloons", "One peace sign", "Balloons"),
    ("confetti", "Two peace signs", "Confetti"),
    ("lasers", "Two rock-on hands", "Lasers"),
    ("hearts", "Heart hands", "Hearts"),
    ("rain", "Two thumbs down", "Rain"),
    ("thumbs_down", "One thumbs down", "Thumbs down"),
]


def font(size, bold=True):
    names = ["DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", "arialbd.ttf", "arial.ttf"]
    for n in names:
        for d in ("/usr/share/fonts/truetype/dejavu", r"C:\Windows\Fonts", ""):
            try:
                return ImageFont.truetype(os.path.join(d, n), size)
            except OSError:
                continue
    return ImageFont.load_default()


def backdrop():
    """A stand-in for a webcam frame: soft gradient room and a person silhouette."""
    y = np.linspace(0, 1, H)[:, None]
    x = np.linspace(0, 1, W)[None, :]
    b = (70 + 40 * y + 10 * x)
    g = (60 + 30 * y + 20 * x)
    r = (55 + 20 * y + 35 * x)
    frame = np.dstack([b + 0 * x, g + 0 * x, r + 0 * y]).clip(0, 255).astype(np.uint8)
    cv2.ellipse(frame, (W // 2, H + 40), (170, 150), 0, 180, 360, (40, 38, 45), -1, cv2.LINE_AA)
    cv2.circle(frame, (W // 2, int(H * 0.47)), 62, (40, 38, 45), -1, cv2.LINE_AA)
    return frame


def label(frame, gesture, effect):
    img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert("RGBA")
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    text = f"{gesture}  \u2192  {effect}"
    f = font(20)
    tw = d.textlength(text, font=f)
    x0, y0 = (W - tw) / 2 - 18, H - 52
    d.rounded_rectangle((x0, y0, x0 + tw + 36, y0 + 36), radius=18, fill=(0, 0, 0, 150))
    d.text((x0 + 18, y0 + 7), text, font=f, fill=(255, 255, 255, 255))
    return Image.alpha_composite(img, over).convert("RGB")


def main():
    os.makedirs(os.path.join(ROOT, "assets"), exist_ok=True)
    base = backdrop()
    frames, stills = [], []
    for name, gesture, effect in SCENES:
        player = EffectPlayer()
        player.trigger(name, W, H)
        n = 0
        while player.busy and n < 3 * FPS:
            f = base.copy()
            player.render(f, 1 / FPS)
            n += 1
            if n % 2 == 0:  # 7.5 fps in the gif keeps the file small
                frames.append(label(f, gesture, effect))
            if n == int(1.3 * FPS):
                stills.append(label(f, gesture, effect))
    gif = [fr.resize((420, 236), Image.LANCZOS).quantize(colors=96, method=Image.MEDIANCUT) for fr in frames]
    gif[0].save(os.path.join(ROOT, "assets", "demo.gif"), save_all=True, append_images=gif[1:],
                duration=int(2000 / FPS), loop=0, optimize=True)

    tw, th = 320, 180
    sheet = Image.new("RGB", (tw * 4, th * 2))
    for i, s in enumerate(stills):
        sheet.paste(s.resize((tw, th), Image.LANCZOS), ((i % 4) * tw, (i // 4) * th))
    sheet.save(os.path.join(ROOT, "assets", "effects.png"), optimize=True)
    print(f"wrote demo.gif ({len(gif)} frames) and effects.png")


if __name__ == "__main__":
    main()
