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
            break
    except ImportError:
        pass
    _sprite_cache[key] = sprite
    return sprite


def blit(frame: np.ndarray, sprite: np.ndarray, cx: float, cy: float, scale=1.0, alpha=1.0):
    """Alpha-blend a BGRA sprite centred at (cx, cy)."""
    if scale != 1.0:
        s = max(2, int(sprite.shape[0] * scale))
        sprite = cv2.resize(sprite, (s, s), interpolation=cv2.INTER_LINEAR)
    h, w = sprite.shape[:2]
    x0, y0 = int(cx - w / 2), int(cy - h / 2)
    fx0, fy0 = max(x0, 0), max(y0, 0)
    fx1, fy1 = min(x0 + w, frame.shape[1]), min(y0 + h, frame.shape[0])
    if fx0 >= fx1 or fy0 >= fy1:
        return
    sp = sprite[fy0 - y0 : fy1 - y0, fx0 - x0 : fx1 - x0]
    a = (sp[:, :, 3:4].astype(np.float32) / 255.0) * alpha
    roi = frame[fy0:fy1, fx0:fx1].astype(np.float32)
    frame[fy0:fy1, fx0:fx1] = (sp[:, :, :3] * a + roi * (1 - a)).astype(np.uint8)


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

    def __init__(self, w: int, h: int):
        self.w, self.h = w, h
        self.t = 0.0

    @property
    def alive(self) -> bool:
        return self.t < self.duration

    @property
    def envelope(self) -> float:
        """0..1 intensity: fades in at the start and out at the end."""
        a = min(1.0, self.t / self.fade_in) if self.fade_in else 1.0
        b = min(1.0, (self.duration - self.t) / self.fade_out) if self.fade_out else 1.0
        return max(0.0, min(a, b))

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


def make_effect(name: str, w: int, h: int) -> Effect:
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
