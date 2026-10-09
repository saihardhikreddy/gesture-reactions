"""Animated full-screen reaction effects drawn onto BGR video frames with OpenCV."""

from __future__ import annotations

import math
import os
import random

import cv2
import numpy as np

from gestures import (
    REACTION_BALLOONS,
    REACTION_CONFETTI,
    REACTION_FIREWORKS,
    REACTION_HEARTS,
    REACTION_LASERS,
    REACTION_RAIN,
    REACTION_THUMBS_DOWN,
    REACTION_THUMBS_UP,
)

BRIGHT = [
    (60, 60, 255), (40, 200, 255), (60, 230, 90), (255, 160, 40),
    (230, 80, 220), (255, 230, 60), (90, 255, 255), (160, 100, 255),
]

# ---------------------------------------------------------------- easing


def clamp01(x: float) -> float:
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def lerp(a, b, t):
    return a + (b - a) * t


def smoothstep(x: float) -> float:
    x = clamp01(x)
    return x * x * (3 - 2 * x)


def ease_out_cubic(x: float) -> float:
    return 1 - (1 - clamp01(x)) ** 3


def ease_in_cubic(x: float) -> float:
    return clamp01(x) ** 3


def ease_in_out_sine(x: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * clamp01(x))


def ease_out_back(x: float, overshoot: float = 1.70158) -> float:
    """Ease out that shoots past 1 and settles back."""
    x = clamp01(x) - 1
    return 1 + (overshoot + 1) * x ** 3 + overshoot * x ** 2


def spring(t: float, frequency: float = 2.0, damping: float = 6.0) -> float:
    """Damped spring going from 0 to 1 over time t (seconds): overshoots, wobbles, settles."""
    if t <= 0:
        return 0.0
    return 1 - math.exp(-damping * t) * math.cos(2 * math.pi * frequency * t)


def fade(t: float, duration: float, fade_in: float, fade_out: float) -> float:
    """0..1 intensity that eases in at the start and out at the end."""
    a = smoothstep(t / fade_in) if fade_in > 0 else 1.0
    b = smoothstep((duration - t) / fade_out) if fade_out > 0 else 1.0
    return min(a, b) if t < duration else 0.0


# ---------------------------------------------------------------- compositing


def _region(shape, x0: int, y0: int, w: int, h: int):
    """Frame and sprite slices for a w*h sprite placed at (x0, y0), or None if off-screen."""
    fh, fw = shape[:2]
    fx0, fy0 = max(x0, 0), max(y0, 0)
    fx1, fy1 = min(x0 + w, fw), min(y0 + h, fh)
    if fx0 >= fx1 or fy0 >= fy1:
        return None
    return ((slice(fy0, fy1), slice(fx0, fx1)),
            (slice(fy0 - y0, fy1 - y0), slice(fx0 - x0, fx1 - x0)))


def transform(sprite: np.ndarray, scale=1.0, angle=0.0, sx=1.0):
    """Resize (sx squashes horizontally) and rotate (degrees, counter-clockwise) a
    sprite in a single warp."""
    h, w = sprite.shape[:2]
    if w * scale * sx < 1 or h * scale < 1:
        return None
    if abs(angle) <= 0.3:
        if abs(scale - 1) < 1e-3 and abs(sx - 1) < 1e-3:
            return sprite
        interp = cv2.INTER_AREA if scale < 0.5 else cv2.INTER_LINEAR
        return cv2.resize(sprite, (max(1, round(w * scale * sx)), max(1, round(h * scale))),
                          interpolation=interp)
    r = math.radians(angle)
    c, s = math.cos(r), math.sin(r)
    a, b = scale * sx, scale
    # Forward map: scale about the centre, then rotate (y points down, so negate the sine).
    m = np.array([[a * c, b * s, 0.0], [-a * s, b * c, 0.0]], np.float32)
    nw = int(abs(a * c) * w + abs(b * s) * h) + 2
    nh = int(abs(a * s) * w + abs(b * c) * h) + 2
    m[:, 2] = (nw / 2, nh / 2) - m[:, :2] @ np.array([w / 2, h / 2], np.float32)
    return cv2.warpAffine(sprite, m, (nw, nh), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_CONSTANT, borderValue=0)


_PLANES: dict[int, tuple] = {}
_CACHED_IDS: set[int] = set()  # long-lived sprites, whose split planes are worth keeping


def _planes(sprite: np.ndarray):
    """Colour and 3-channel alpha of a BGRA sprite; kept for cached (untransformed) sprites."""
    hit = _PLANES.get(id(sprite))
    if hit is not None and hit[0] is sprite:
        return hit[1], hit[2]
    b, g, r, a = cv2.split(sprite)
    planes = cv2.merge([b, g, r]), cv2.merge([a, a, a])
    if id(sprite) in _CACHED_IDS:
        _PLANES[id(sprite)] = (sprite, *planes)
    return planes


def blit(frame: np.ndarray, sprite: np.ndarray, cx: float, cy: float,
         scale=1.0, alpha=1.0, angle=0.0, sx=1.0):
    """Alpha-composite a premultiplied BGRA sprite centred at (cx, cy)."""
    if alpha <= 0.004:
        return
    sp = transform(sprite, scale, angle, sx)
    if sp is None:
        return
    h, w = sp.shape[:2]
    r = _region(frame.shape, int(round(cx - w / 2)), int(round(cy - h / 2)), w, h)
    if r is None:
        return
    dst, src = r
    rgb, a3 = _planes(sp)
    rgb, a3 = rgb[src], a3[src]
    roi = frame[dst]
    covered = cv2.multiply(roi, a3, scale=alpha / 255)
    if alpha < 0.996:
        rgb = cv2.convertScaleAbs(rgb, alpha=alpha)
    frame[dst] = cv2.add(cv2.subtract(roi, covered), rgb)


def add_light(frame: np.ndarray, sprite: np.ndarray, cx: float, cy: float, gain=1.0, scale=1.0):
    """Additively blend a BGR light sprite (black = no light) centred at (cx, cy)."""
    if gain <= 0.004:
        return
    sp = transform(sprite, scale)
    if sp is None:
        return
    h, w = sp.shape[:2]
    r = _region(frame.shape, int(round(cx - w / 2)), int(round(cy - h / 2)), w, h)
    if r is None:
        return
    dst, src = r
    frame[dst] = cv2.addWeighted(frame[dst], 1.0, sp[src], gain, 0)


def add_layer(frame: np.ndarray, layer: np.ndarray, gain=1.0, bloom=0.0, bloom_size=0.012):
    """Additively blend a light layer (any resolution) onto the frame, with optional bloom.

    The bloom is blurred at 1/8 of the frame size, so it costs well under a millisecond.
    """
    if gain <= 0.004:
        return
    fh, fw = frame.shape[:2]
    if bloom > 0:
        sw, sh = max(1, fw // 8), max(1, fh // 8)
        small = cv2.resize(layer, (sw, sh), interpolation=cv2.INTER_AREA)
        sigma = max(0.8, bloom_size * fh / 8)
        near = cv2.GaussianBlur(small, (0, 0), sigma)
        far = cv2.GaussianBlur(small, (0, 0), sigma * 3.5)
        halo = cv2.addWeighted(near, bloom, far, bloom * 0.9, 0)
        lh, lw = layer.shape[:2]
        layer = cv2.add(layer, cv2.resize(halo, (lw, lh), interpolation=cv2.INTER_LINEAR))
    if layer.shape[:2] != (fh, fw):
        layer = cv2.resize(layer, (fw, fh), interpolation=cv2.INTER_LINEAR)
    cv2.addWeighted(frame, 1.0, layer, gain, 0, dst=frame)


_VIGNETTES: dict[tuple[int, int], np.ndarray] = {}


def _vignette(w: int, h: int) -> np.ndarray:
    """How much each pixel darkens at full vignette strength (0 centre .. 255 corners)."""
    key = (w, h)
    if key not in _VIGNETTES:
        y = np.linspace(-1, 1, h, dtype=np.float32)[:, None]
        x = np.linspace(-1, 1, w, dtype=np.float32)[None, :]
        d = np.sqrt(x * x * 0.8 + y * y) / math.sqrt(1.8)
        v = np.clip((d - 0.25) / 0.75, 0, 1) ** 1.5
        v8 = (v * 255).astype(np.uint8)
        _VIGNETTES[key] = cv2.merge([v8, v8, v8])
    return _VIGNETTES[key]


_LUMA = np.array([0.114, 0.587, 0.299], np.float32)  # BGR


def grade(frame: np.ndarray, amount: float, gain=(1.0, 1.0, 1.0), lift=(0, 0, 0),
          contrast=1.0, desaturate=0.0, vignette=0.0):
    """Colour-grade the whole frame in place: per-channel gain/lift (BGR), contrast,
    desaturation and a vignette, all scaled by ``amount`` (0..1) so it can fade.

    Gain, lift, contrast and desaturation are one 3x4 colour matrix, so the
    grade costs a single pass (plus one for the vignette)."""
    if amount <= 0.004:
        return
    mix = (1 - desaturate) * np.eye(3, dtype=np.float32) + desaturate * np.tile(_LUMA, (3, 1))
    g = np.asarray(gain, np.float32)
    m = g[:, None] * contrast * mix
    offset = g * 128 * (1 - contrast) + np.asarray(lift, np.float32)
    m = (1 - amount) * np.eye(3, dtype=np.float32) + amount * m
    cv2.transform(frame, np.hstack([m, (amount * offset)[:, None]]), dst=frame)
    if vignette > 0:
        dark = cv2.multiply(frame, _vignette(frame.shape[1], frame.shape[0]),
                            scale=vignette * amount / 255)
        cv2.subtract(frame, dark, dst=frame)


# ---------------------------------------------------------------- emoji sprites

_EMOJI_FONTS = [
    r"C:\Windows\Fonts\seguiemj.ttf",  # Windows (Segoe UI Emoji)
    "/System/Library/Fonts/Apple Color Emoji.ttc",
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/noto/NotoColorEmoji.ttf",
]
_sprite_cache: dict[str, np.ndarray | None] = {}


def emoji_sprite(char: str, size: int = 160) -> np.ndarray | None:
    """Render a colour emoji to a BGRA image, or None if no emoji font exists."""
    key = f"{char}:{size}"
    if key in _sprite_cache:
        return _sprite_cache[key]
    sprite = None
    try:
        from PIL import Image, ImageDraw, ImageFont

        for path in _EMOJI_FONTS:
            if not os.path.exists(path):
                continue
            # Noto Color Emoji only ships a 109px bitmap strike.
            font_px = 109 if "Noto" in path else size
            try:
                font = ImageFont.truetype(path, font_px)
            except OSError:
                continue
            canvas = Image.new("RGBA", (font_px * 2, font_px * 2), (0, 0, 0, 0))
            ImageDraw.Draw(canvas).text(
                (font_px // 2, font_px // 3), char, font=font, embedded_color=True
            )
            bbox = canvas.getbbox()
            if not bbox:
                continue
            canvas = canvas.crop(bbox).resize((size, size), Image.LANCZOS)
            rgba = np.array(canvas)
            sprite = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)
            sprite[:, :, :3] = (sprite[:, :, :3].astype(np.float32) * sprite[:, :, 3:4] / 255).astype(np.uint8)
            break
    except ImportError:
        pass
    _sprite_cache[key] = sprite
    return sprite


def tint(frame: np.ndarray, color, amount: float):
    """Blend the whole frame toward a colour (amount 0..1)."""
    if amount <= 0:
        return
    keep = 1 - amount
    cv2.multiply(frame, (keep, keep, keep, 0), dst=frame)
    cv2.add(frame, tuple(c * amount for c in color) + (0,), dst=frame)


def glow(layer: np.ndarray, sigma: float) -> np.ndarray:
    """Soft blur for light effects, done at quarter size so it stays cheap at 720p+."""
    h, w = layer.shape[:2]
    small = cv2.resize(layer, (w // 4, h // 4), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), max(sigma / 4, 0.8))
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)


def heart_polygon(cx, cy, size, angle=0.0):
    t = np.linspace(0, 2 * np.pi, 40)
    x = 16 * np.sin(t) ** 3
    y = -(13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t))
    pts = np.stack([x, y], axis=1) * (size / 32.0)
    if angle:
        c, s = math.cos(angle), math.sin(angle)
        pts = pts @ np.array([[c, s], [-s, c]])
    pts += (cx, cy)
    return pts.astype(np.int32)


# ---------------------------------------------------------------- base effect


class Effect:
    duration = 3.2
    fade_in = 0.25
    fade_out = 0.6

    def __init__(self, w: int, h: int, seed: int | None = None):
        self.w, self.h = w, h
        self.t = 0.0
        self.rng = random.Random(seed)

    @property
    def alive(self) -> bool:
        return self.t < self.duration

    @property
    def envelope(self) -> float:
        """0..1 intensity: eases in at the start and out at the end."""
        return fade(self.t, self.duration, self.fade_in, self.fade_out)

    def update(self, dt: float):
        self.t += dt

    def draw(self, frame: np.ndarray):
        raise NotImplementedError


# ---------------------------------------------------------------- thumbs


class ThumbEffect(Effect):
    duration = 2.4

    def __init__(self, w, h, up: bool):
        super().__init__(w, h)
        self.up = up
        self.char = "\U0001F44D" if up else "\U0001F44E"
        size = int(min(w, h) * 0.45)
        self.sprite = emoji_sprite(self.char, size)
        self.small = emoji_sprite(self.char, max(24, size // 3))
        self.size = size
        self.bubbles = [
            [random.uniform(0.1, 0.9) * w, h + random.uniform(0, h * 0.6),
             random.uniform(-40, 40), random.uniform(180, 320) * (h / 720)]
            for _ in range(10)
        ]

    def update(self, dt):
        super().update(dt)
        for b in self.bubbles:
            b[0] += b[2] * dt
            b[1] -= b[3] * dt

    def _icon(self, frame, cx, cy, scale, alpha, sprite, size):
        if sprite is not None:
            blit(frame, sprite, cx, cy, scale, alpha)
            return
        # Fallback when no emoji font: a coloured badge with +1 / -1.
        r = int(size * 0.45 * scale)
        overlay = frame.copy()
        color = (60, 190, 60) if self.up else (60, 60, 220)
        cv2.circle(overlay, (int(cx), int(cy)), r, color, -1, cv2.LINE_AA)
        label = "+1" if self.up else "-1"
        fs = r / 28
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_DUPLEX, fs, max(2, int(fs * 2)))
        cv2.putText(overlay, label, (int(cx - tw / 2), int(cy + th / 2)),
                    cv2.FONT_HERSHEY_DUPLEX, fs, (255, 255, 255), max(2, int(fs * 2)), cv2.LINE_AA)
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, dst=frame)

    def draw(self, frame):
        e = self.envelope
        for b in self.bubbles:
            self._icon(frame, b[0], b[1], 1.0, 0.85 * e, self.small, self.size / 3)
        # Pop in with a little overshoot, then gently bob.
        p = min(1.0, self.t / 0.35)
        pop = 1 + 0.25 * math.sin(p * math.pi) if p < 1 else 1.0
        bob = math.sin(self.t * 4) * self.h * 0.01
        self._icon(frame, self.w * 0.5, self.h * 0.45 + bob, pop * max(0.05, p), e,
                   self.sprite, self.size)


# ---------------------------------------------------------------- fireworks


class FireworksEffect(Effect):
    duration = 3.6

    def __init__(self, w, h):
        super().__init__(w, h)
        self.particles = []  # x, y, vx, vy, life, color
        self.next_burst = 0.0
        self.trail = np.zeros((h, w, 3), np.uint8)

    def _burst(self):
        cx = random.uniform(0.15, 0.85) * self.w
        cy = random.uniform(0.12, 0.5) * self.h
        color = random.choice(BRIGHT)
        speed = random.uniform(0.25, 0.4) * min(self.w, self.h)
        for i in range(70):
            a = random.uniform(0, 2 * math.pi)
            v = speed * random.uniform(0.4, 1.0)
            self.particles.append([cx, cy, math.cos(a) * v, math.sin(a) * v,
                                   random.uniform(0.9, 1.4), color])

    def update(self, dt):
        super().update(dt)
        if self.t >= self.next_burst and self.t < self.duration - 1.0:
            self._burst()
            self.next_burst = self.t + random.uniform(0.18, 0.4)
        g = 0.25 * self.h
        for p in self.particles:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[2] *= 0.97
            p[3] = p[3] * 0.97 + g * dt
            p[4] -= dt
        self.particles = [p for p in self.particles if p[4] > 0]

    def draw(self, frame):
        tint(frame, (20, 10, 0), 0.45 * self.envelope)
        cv2.multiply(self.trail, (0.82, 0.82, 0.82, 0), dst=self.trail)
        for x, y, _, _, life, color in self.particles:
            c = tuple(int(ch * min(1.0, life)) for ch in color)
            cv2.circle(self.trail, (int(x), int(y)), 3, c, -1, cv2.LINE_AA)
        cv2.add(frame, glow(self.trail, 4), dst=frame)
        cv2.add(frame, self.trail, dst=frame)


# ---------------------------------------------------------------- rain


class RainEffect(Effect):
    duration = 3.6

    def __init__(self, w, h):
        super().__init__(w, h)
        self.drops = [self._drop(random.uniform(-h, h)) for _ in range(int(w * 0.35))]
        self.clouds = [(random.uniform(-0.1, 1.1) * w, random.uniform(-0.05, 0.08) * h,
                        random.uniform(0.12, 0.22) * w) for _ in range(9)]

    def _drop(self, y):
        return [random.uniform(0, self.w), y, random.uniform(0.9, 1.6) * self.h,
                random.uniform(0.03, 0.06) * self.h]

    def update(self, dt):
        super().update(dt)
        for d in self.drops:
            d[1] += d[2] * dt
            if d[1] > self.h and self.t < self.duration - 0.8:
                d[:] = self._drop(random.uniform(-0.2 * self.h, 0))

    def draw(self, frame):
        e = self.envelope
        tint(frame, (90, 60, 40), 0.4 * e)
        overlay = frame.copy()
        for x, y, _, length in self.drops:
            cv2.line(overlay, (int(x), int(y)), (int(x - length * 0.12), int(y + length)),
                     (235, 215, 200), 2, cv2.LINE_AA)
        shift = -self.h * 0.25 * (1 - min(1.0, self.t / 0.5))
        for cx, cy, r in self.clouds:
            cv2.ellipse(overlay, (int(cx), int(cy + shift)), (int(r), int(r * 0.55)),
                        0, 0, 360, (95, 90, 90), -1, cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.85 * e, frame, 1 - 0.85 * e, 0, dst=frame)


# ---------------------------------------------------------------- balloons


class BalloonsEffect(Effect):
    duration = 4.0
    fade_out = 0.3

    def __init__(self, w, h):
        super().__init__(w, h)
        self.balloons = []
        for i in range(14):
            r = random.uniform(0.045, 0.075) * w
            self.balloons.append({
                "x": random.uniform(0.05, 0.95) * w,
                "y": h + r * 2 + random.uniform(0, h * 0.8),
                "r": r,
                "v": random.uniform(0.35, 0.55) * h,
                "phase": random.uniform(0, 6.28),
                "color": random.choice(BRIGHT),
            })

    def update(self, dt):
        super().update(dt)
        for b in self.balloons:
            b["y"] -= b["v"] * dt

    def draw(self, frame):
        overlay = frame.copy()
        for b in self.balloons:
            x = b["x"] + math.sin(self.t * 2 + b["phase"]) * b["r"] * 0.4
            y, r = b["y"], b["r"]
            # string
            pts = np.array([[x + math.sin(self.t * 3 + b["phase"] + k * 0.6) * r * 0.15,
                             y + r * 1.2 + k * r * 0.35] for k in range(8)], np.int32)
            cv2.polylines(overlay, [pts], False, (220, 220, 220), 2, cv2.LINE_AA)
            cv2.ellipse(overlay, (int(x), int(y)), (int(r), int(r * 1.2)), 0, 0, 360,
                        b["color"], -1, cv2.LINE_AA)
            knot = np.array([[x - r * 0.12, y + r * 1.3], [x + r * 0.12, y + r * 1.3],
                             [x, y + r * 1.15]], np.int32)
            cv2.fillPoly(overlay, [knot], b["color"], cv2.LINE_AA)
            cv2.ellipse(overlay, (int(x - r * 0.35), int(y - r * 0.45)),
                        (int(r * 0.18), int(r * 0.3)), 30, 0, 360, (255, 255, 255), -1, cv2.LINE_AA)
        a = 0.92 * self.envelope
        cv2.addWeighted(overlay, a, frame, 1 - a, 0, dst=frame)


# ---------------------------------------------------------------- confetti


class ConfettiEffect(Effect):
    duration = 4.0

    def __init__(self, w, h):
        super().__init__(w, h)
        self.pieces = []
        for _ in range(int(w * 0.25)):
            self.pieces.append([
                random.uniform(0, w), random.uniform(-h * 1.2, -10),       # x, y
                random.uniform(-60, 60), random.uniform(0.25, 0.5) * h,    # vx, vy
                random.uniform(0, 6.28), random.uniform(-8, 8),             # angle, spin
                random.uniform(0.008, 0.016) * w, random.choice(BRIGHT),    # size, colour
                random.uniform(0, 6.28),                                    # wobble phase
            ])

    def update(self, dt):
        super().update(dt)
        for p in self.pieces:
            p[0] += (p[2] + math.sin(self.t * 3 + p[8]) * 50) * dt
            p[1] += p[3] * dt
            p[4] += p[5] * dt

    def draw(self, frame):
        overlay = frame.copy()
        for x, y, _, _, ang, _, s, color, _ in self.pieces:
            if y < -s or y > self.h + s:
                continue
            flip = abs(math.cos(ang * 0.7))  # fake 3D tumble
            rect = ((float(x), float(y)), (float(s * 2), float(max(1.0, s * flip))), math.degrees(ang))
            box = cv2.boxPoints(rect).astype(np.int32)
            cv2.fillPoly(overlay, [box], color, cv2.LINE_AA)
        a = self.envelope
        cv2.addWeighted(overlay, a, frame, 1 - a, 0, dst=frame)


# ---------------------------------------------------------------- lasers


class LasersEffect(Effect):
    duration = 3.6

    def __init__(self, w, h):
        super().__init__(w, h)
        self.beams = []
        for i in range(8):
            side = i % 2
            self.beams.append({
                "origin": (int(w * (0.02 if side == 0 else 0.98)), int(h * random.uniform(0.85, 1.05))),
                "color": random.choice([(255, 60, 255), (80, 255, 80), (255, 255, 60),
                                        (60, 60, 255), (255, 160, 0)]),
                "speed": random.uniform(1.2, 2.6) * (1 if side else -1),
                "phase": random.uniform(0, 6.28),
                "base": -math.pi / 2 + (0.6 if side == 0 else -0.6),
            })

    def draw(self, frame):
        e = self.envelope
        tint(frame, (30, 0, 20), 0.55 * e)
        layer = np.zeros_like(frame)
        L = math.hypot(self.w, self.h) * 1.2
        for b in self.beams:
            ang = b["base"] + math.sin(self.t * b["speed"] + b["phase"]) * 0.7
            ox, oy = b["origin"]
            end = (int(ox + math.cos(ang) * L), int(oy + math.sin(ang) * L))
            cv2.line(layer, (ox, oy), end, b["color"], 10, cv2.LINE_AA)
            cv2.line(layer, (ox, oy), end, (255, 255, 255), 2, cv2.LINE_AA)
        layer = cv2.add(layer, glow(layer, 9))
        cv2.addWeighted(frame, 1.0, layer, e, 0, dst=frame)


# ---------------------------------------------------------------- hearts


class HeartsEffect(Effect):
    duration = 3.8

    def __init__(self, w, h):
        super().__init__(w, h)
        self.hearts = []
        for _ in range(26):
            self.hearts.append({
                "x": random.uniform(0.05, 0.95) * w,
                "y": h + random.uniform(0, h * 0.9),
                "s": random.uniform(0.04, 0.09) * min(w, h) * 1.6,
                "v": random.uniform(0.3, 0.55) * h,
                "phase": random.uniform(0, 6.28),
                "color": random.choice([(80, 40, 235), (140, 90, 255), (60, 20, 200),
                                        (180, 120, 255), (120, 60, 255)]),
            })

    def update(self, dt):
        super().update(dt)
        for hd in self.hearts:
            hd["y"] -= hd["v"] * dt

    def draw(self, frame):
        tint(frame, (120, 80, 255), 0.18 * self.envelope)
        overlay = frame.copy()
        for hd in self.hearts:
            beat = 1 + 0.08 * math.sin(self.t * 10 + hd["phase"])
            x = hd["x"] + math.sin(self.t * 2 + hd["phase"]) * hd["s"] * 0.5
            poly = heart_polygon(x, hd["y"], hd["s"] * beat, math.sin(self.t + hd["phase"]) * 0.25)
            cv2.fillPoly(overlay, [poly], hd["color"], cv2.LINE_AA)
        a = 0.9 * self.envelope
        cv2.addWeighted(overlay, a, frame, 1 - a, 0, dst=frame)


# ---------------------------------------------------------------- manager


def make_effect(name: str, w: int, h: int, seed: int | None = None) -> Effect:
    return {
        REACTION_THUMBS_UP: lambda: ThumbEffect(w, h, up=True),
        REACTION_THUMBS_DOWN: lambda: ThumbEffect(w, h, up=False),
        REACTION_FIREWORKS: lambda: FireworksEffect(w, h),
        REACTION_RAIN: lambda: RainEffect(w, h),
        REACTION_BALLOONS: lambda: BalloonsEffect(w, h),
        REACTION_CONFETTI: lambda: ConfettiEffect(w, h),
        REACTION_LASERS: lambda: LasersEffect(w, h),
        REACTION_HEARTS: lambda: HeartsEffect(w, h),
    }[name]()


class EffectPlayer:
    """Holds the currently running effects and draws them every frame."""

    def __init__(self):
        self.effects: list[Effect] = []

    def trigger(self, name: str, w: int, h: int):
        self.effects.append(make_effect(name, w, h))

    @property
    def busy(self) -> bool:
        return bool(self.effects)

    def render(self, frame: np.ndarray, dt: float):
        for fx in self.effects:
            fx.update(dt)
            fx.draw(frame)
        self.effects = [fx for fx in self.effects if fx.alive]
