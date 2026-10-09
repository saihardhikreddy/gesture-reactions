"""Renders the README demo GIFs from the real effect code, no webcam needed.

    python scripts/render_demo.py                    # docs/demo.gif + docs/reactions/*.gif
    python scripts/render_demo.py --only hearts      # just one or a few reactions
    python scripts/render_demo.py --stills frames/   # also full-size PNGs to inspect

Writes:
    docs/demo.gif               every reaction in turn, with a caption
    docs/reactions/<name>.gif   one GIF per reaction
"""

from __future__ import annotations

import argparse
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from effects import make_effect  # noqa: E402

W, H = 1280, 720      # render at a real webcam size, then scale the GIFs down
FPS = 30              # simulation rate
CLIP_STEP = 2         # per-reaction GIFs keep every 2nd frame: 15 fps
DEMO_STEP = 3         # the combined demo keeps every 3rd: 10 fps, to stay a sensible size
CLIP_SIZE = (400, 225)
DEMO_SIZE = (432, 243)
SCENES = [            # (reaction, hand sign, caption)
    ("thumbs_up", "One thumbs up", "Thumbs up"),
    ("thumbs_down", "One thumbs down", "Thumbs down"),
    ("hearts", "Heart hands", "Hearts"),
    ("balloons", "One peace sign", "Balloons"),
    ("confetti", "Two peace signs", "Confetti"),
    ("fireworks", "Two thumbs up", "Fireworks"),
    ("lasers", "Two rock-on hands", "Lasers"),
    ("rain", "Two thumbs down", "Rain"),
]


def font(size):
    for name in ("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"):
        for d in ("/usr/share/fonts/truetype/dejavu", r"C:\Windows\Fonts", "/Library/Fonts", ""):
            try:
                return ImageFont.truetype(os.path.join(d, name), size)
            except OSError:
                continue
    return ImageFont.load_default()


def backdrop(w=W, h=H) -> np.ndarray:
    """A stand-in for a webcam frame: someone at a desk in a softly lit room."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    u, v = xx / w, yy / h
    # Warm wall, lit from a window on the left.
    light = np.exp(-((u - 0.12) ** 2) / 0.18) * 0.55 + 0.45
    wall = np.array([150, 170, 190], np.float32) * (0.75 + 0.35 * (1 - v))[..., None]
    img = wall * light[..., None]
    # Window with daylight.
    win = ((u > 0.05) & (u < 0.27) & (v > 0.08) & (v < 0.62)).astype(np.float32)
    sky = np.array([250, 235, 215], np.float32)
    img = img * (1 - win[..., None]) + sky * win[..., None]
    for x in (0.16,):
        img[:, int(x * w) - 4:int(x * w) + 4][(v[:, 0] > 0.08) & (v[:, 0] < 0.62)] = (120, 135, 150)
    img[int(0.35 * h) - 3:int(0.35 * h) + 3, int(0.05 * w):int(0.27 * w)] = (120, 135, 150)
    # Shelf with books and a plant on the right.
    cv2.rectangle(img, (int(0.72 * w), int(0.46 * h)), (int(0.97 * w), int(0.48 * h)), (70, 90, 115), -1)
    book_cols = [(60, 70, 160), (140, 100, 50), (80, 140, 190), (90, 60, 60), (70, 130, 90)]
    x = int(0.74 * w)
    for i, c in enumerate(book_cols * 2):
        bw = int(w * (0.012 + 0.006 * (i % 3)))
        bh = int(h * (0.1 + 0.03 * ((i * 7) % 4)))
        cv2.rectangle(img, (x, int(0.46 * h) - bh), (x + bw, int(0.46 * h)), c, -1)
        x += bw + 2
        if x > 0.95 * w:
            break
    cv2.ellipse(img, (int(0.85 * w), int(0.3 * h)), (int(0.05 * w), int(0.09 * h)), 0, 0, 360, (70, 120, 60), -1)
    cv2.rectangle(img, (int(0.83 * w), int(0.36 * h)), (int(0.87 * w), int(0.46 * h)), (90, 110, 170), -1)
    # Lamp glow.
    img += (np.exp(-(((u - 0.62) / 0.06) ** 2 + ((v - 0.18) / 0.1) ** 2)) * 70)[..., None] * \
        np.array([0.6, 0.85, 1.0], np.float32)
    img = cv2.GaussianBlur(img, (0, 0), h * 0.012)  # the room is out of focus

    # The person, in focus.
    person = np.zeros((h, w), np.float32)
    cv2.ellipse(person, (int(0.5 * w), int(1.12 * h)), (int(0.27 * w), int(0.42 * h)), 0, 180, 360, 1.0, -1,
                cv2.LINE_AA)
    cv2.rectangle(person, (int(0.465 * w), int(0.55 * h)), (int(0.535 * w), int(0.75 * h)), 1.0, -1)
    sweater = np.array([95, 80, 55], np.float32) * (1.15 - 0.4 * v)[..., None] * \
        (0.85 + 0.25 * np.exp(-((u - 0.42) ** 2) / 0.02))[..., None]
    neck = ((u > 0.465) & (u < 0.535) & (v < 0.72)).astype(np.float32)
    skin = np.array([135, 165, 215], np.float32) * (0.85 + 0.2 * np.exp(-((u - 0.47) ** 2) / 0.004))[..., None]
    body = sweater * (1 - neck[..., None]) + skin * 0.8 * neck[..., None]
    img = img * (1 - person[..., None]) + body * person[..., None]
    head = np.zeros((h, w), np.float32)
    cv2.ellipse(head, (int(0.5 * w), int(0.42 * h)), (int(0.085 * w), int(0.2 * h)), 0, 0, 360, 1.0, -1,
                cv2.LINE_AA)
    shade = 0.8 + 0.3 * np.clip(1 - np.hypot((u - 0.47) / 0.1, (v - 0.38) / 0.25), 0, 1)
    img = img * (1 - head[..., None]) + (skin * shade[..., None]) * head[..., None]
    hair = np.zeros((h, w), np.float32)
    cv2.ellipse(hair, (int(0.5 * w), int(0.33 * h)), (int(0.092 * w), int(0.14 * h)), 0, 180, 360, 1.0, -1,
                cv2.LINE_AA)
    cv2.ellipse(hair, (int(0.5 * w), int(0.33 * h)), (int(0.092 * w), int(0.05 * h)), 0, 0, 180, 1.0, -1,
                cv2.LINE_AA)
    img = img * (1 - hair[..., None]) + np.array([35, 45, 60], np.float32) * hair[..., None]
    return np.clip(img, 0, 255).astype(np.uint8)


def caption(frame_rgb: Image.Image, text: str, scale: float) -> Image.Image:
    img = frame_rgb.convert("RGBA")
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    f = font(int(20 * scale))
    tw = d.textlength(text, font=f)
    pad, bh = 18 * scale, 36 * scale
    x0, y0 = (img.width - tw) / 2 - pad, img.height - bh - 16 * scale
    d.rounded_rectangle((x0, y0, x0 + tw + 2 * pad, y0 + bh), radius=bh / 2, fill=(20, 20, 24, 150))
    d.text((x0 + pad, y0 + 7 * scale), text, font=f, fill=(255, 255, 255, 255))
    return Image.alpha_composite(img, over).convert("RGB")


# 8x8 Bayer matrix: ordered dithering keeps still areas identical from frame to
# frame (unlike error diffusion), so the GIF only stores what moves.
_BAYER = np.array([
    [0, 32, 8, 40, 2, 34, 10, 42], [48, 16, 56, 24, 50, 18, 58, 26],
    [12, 44, 4, 36, 14, 46, 6, 38], [60, 28, 52, 20, 62, 30, 54, 22],
    [3, 35, 11, 43, 1, 33, 9, 41], [51, 19, 59, 27, 49, 17, 57, 25],
    [15, 47, 7, 39, 13, 45, 5, 37], [63, 31, 55, 23, 61, 29, 53, 21]], np.float32) / 64 - 0.5


def to_gif_frames(frames: list[Image.Image], dither=14.0) -> list[Image.Image]:
    """Quantize a clip to one palette (sampled from a few of its frames) with ordered dithering."""
    w, h = frames[0].size
    picks = np.linspace(0, len(frames) - 1, min(8, len(frames))).astype(int)
    strip = Image.new("RGB", (w, h * len(picks)))
    for i, k in enumerate(picks):
        strip.paste(frames[k], (0, h * i))
    palette = strip.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    threshold = np.tile(_BAYER, (h // 8 + 1, w // 8 + 1))[:h, :w, None] * dither
    out = []
    for f in frames:
        img = np.clip(np.asarray(f, np.float32) + threshold, 0, 255).astype(np.uint8)
        out.append(Image.fromarray(img).quantize(palette=palette, dither=Image.Dither.NONE))
    return out


def save_gif(path, clips, fps):
    """Write clips (lists of RGB frames, each clip with its own palette) as one looping GIF."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    gif = [f for clip in clips for f in to_gif_frames(clip)]
    gif[0].save(path, save_all=True, append_images=gif[1:], duration=round(1000 / fps), loop=0,
                optimize=True, disposal=1)
    print(f"wrote {os.path.relpath(path, ROOT)} ({len(gif)} frames, {os.path.getsize(path) // 1024} KB)")


def render(name, base, seed=5, lead=0.25, tail=0.2):
    """All frames (BGR, full size) of one reaction, with a moment of plain video around it."""
    fx = make_effect(name, W, H, seed=seed)
    frames = [base.copy() for _ in range(int(lead * FPS))]
    while fx.alive:
        f = base.copy()
        fx.update(1 / FPS)
        fx.draw(f)
        frames.append(f)
    return frames + [base.copy() for _ in range(int(tail * FPS))]


def rgb(bgr, size):
    return Image.fromarray(cv2.cvtColor(cv2.resize(bgr, size, interpolation=cv2.INTER_AREA),
                                        cv2.COLOR_BGR2RGB))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "docs"))
    ap.add_argument("--only", help="comma-separated reactions to render (skips demo.gif)")
    ap.add_argument("--stills", metavar="DIR", help="also save every 6th frame as a PNG here")
    args = ap.parse_args()

    base = backdrop()
    combined = []
    for name, sign, effect in SCENES:
        if args.only and name not in args.only.split(","):
            continue
        frames = render(name, base)
        save_gif(os.path.join(args.out, "reactions", f"{name}.gif"),
                 [[rgb(f, CLIP_SIZE) for f in frames[::CLIP_STEP]]], FPS / CLIP_STEP)
        text = f"{sign}  \u2192  {effect}"
        combined.append([caption(rgb(f, DEMO_SIZE), text, DEMO_SIZE[0] / 640) for f in frames[::DEMO_STEP]])
        if args.stills:
            os.makedirs(os.path.join(args.stills, name), exist_ok=True)
            for i in range(0, len(frames), 6):
                cv2.imwrite(os.path.join(args.stills, name, f"{i:03d}.png"), frames[i])
    if not args.only:
        save_gif(os.path.join(args.out, "demo.gif"), combined, FPS / DEMO_STEP)


if __name__ == "__main__":
    main()
