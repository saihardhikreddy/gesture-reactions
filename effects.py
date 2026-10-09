"""Animated full-screen reaction effects drawn onto BGR video frames with OpenCV.

The look follows Apple's video-call Reactions: glossy 3D sprites, springy
motion, additive glow and a light colour grade on the scene behind.

Everything that is expensive (3D shading, supersampling, blur) happens once
when a sprite is first needed and is cached per frame height, so drawing an
effect only blends small pre-rendered images and a few cheap full-frame passes.
Call ``EffectPlayer.preload(w, h)`` at startup to build every sprite up front.
"""

from __future__ import annotations

import math
import random
import re

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


# ---------------------------------------------------------------- sprite shading

_SPRITES: dict[tuple, np.ndarray] = {}


def cached(key: tuple, build):
    """Return the sprite stored under key, building it on first use."""
    sprite = _SPRITES.get(key)
    if sprite is None:
        sprite = _SPRITES[key] = build()
        _CACHED_IDS.add(id(sprite))
    return sprite


def _norm(v):
    v = np.asarray(v, np.float32)
    return v / np.linalg.norm(v)


def inflate(mask: np.ndarray, color: np.ndarray, bevel=1.0, ambient=0.45, diffuse=0.7,
            specular=0.8, shininess=30.0, rim=0.3, light=(-0.45, -0.75, 0.6)) -> np.ndarray:
    """Shade a flat shape as if it were a puffy 3D object.

    mask: HxW float 0..1. color: HxWx3 float 0..1 (BGR). The shape's distance
    to its edge becomes a rounded height map (bevel 1 = full dome, smaller =
    flat top with rounded edges), whose normals are lit with diffuse, specular
    and rim terms. Returns HxWx3 float BGR.
    """
    dist = cv2.distanceTransform((mask > 0.5).astype(np.uint8), cv2.DIST_L2, 5)
    radius = max(1.0, float(dist.max()) * bevel)
    t = np.clip(dist / radius, 0, 1)
    height = np.sqrt(1 - (1 - t) ** 2) * radius
    height = cv2.GaussianBlur(height, (0, 0), max(1.0, radius * 0.08))
    gx = cv2.Sobel(height, cv2.CV_32F, 1, 0, ksize=3) / 8
    gy = cv2.Sobel(height, cv2.CV_32F, 0, 1, ksize=3) / 8
    nz = 1 / np.sqrt(gx * gx + gy * gy + 1)
    nx, ny = -gx * nz, -gy * nz
    lx, ly, lz = _norm(light)
    hx, hy, hz = _norm((lx, ly, lz + 1))
    lambert = np.clip(nx * lx + ny * ly + nz * lz, 0, 1)
    spec = np.clip(nx * hx + ny * hy + nz * hz, 0, 1) ** shininess
    fresnel = (1 - nz) ** 2
    shade = (ambient + diffuse * lambert)[..., None]
    out = color * shade + (specular * spec)[..., None] + (rim * fresnel)[..., None] * (0.5 + color)
    return np.clip(out, 0, 1)


def soft_ellipse(shape, cx, cy, rx, ry, angle=0.0, blur=0.0) -> np.ndarray:
    """HxW float mask with a filled, optionally feathered ellipse."""
    m = np.zeros(shape[:2], np.float32)
    cv2.ellipse(m, (int(cx), int(cy)), (max(1, int(rx)), max(1, int(ry))), angle, 0, 360, 1.0,
                -1, cv2.LINE_AA)
    if blur > 0:
        m = cv2.GaussianBlur(m, (0, 0), blur)
    return m


def finish_sprite(color: np.ndarray, alpha: np.ndarray, ss: int, shadow=0.0,
                  shadow_offset=0.06, shadow_blur=0.05, blur=0.0, glow=None) -> np.ndarray:
    """Premultiply, add a soft drop shadow (and optional outer glow), then
    downsample a supersampled render by ``ss`` into a uint8 BGRA sprite."""
    h, w = alpha.shape
    rgb = color * alpha[..., None]
    a = alpha.copy()
    if glow is not None:
        gcolor, gstrength, gsize = glow
        g = cv2.GaussianBlur(alpha, (0, 0), gsize * h) * gstrength
        rgb = rgb + np.asarray(gcolor, np.float32) * (g * (1 - a))[..., None]
        a = a + g * (1 - a)
    if shadow > 0:
        dy = int(shadow_offset * h)
        sh = np.zeros_like(alpha)
        sh[dy:] = alpha[: h - dy]
        sh = cv2.GaussianBlur(sh, (0, 0), shadow_blur * h) * shadow
        a = a + sh * (1 - a)
    out = np.dstack([rgb, a])
    if blur > 0:
        out = cv2.GaussianBlur(out, (0, 0), blur * h)
    out = cv2.resize(out, (max(1, w // ss), max(1, h // ss)), interpolation=cv2.INTER_AREA)
    return (np.clip(out, 0, 1) * 255 + 0.5).astype(np.uint8)


def glow_dot(size: int, color=(255, 255, 255), falloff=2.5) -> np.ndarray:
    """BGR light sprite: a soft round glow for additive blending."""
    def build():
        r = np.linspace(-1, 1, size, dtype=np.float32)
        d2 = r[None, :] ** 2 + r[:, None] ** 2
        v = np.exp(-d2 * falloff * 2) * np.clip(1 - d2, 0, 1)
        return (v[..., None] * np.asarray(color, np.float32)).clip(0, 255).astype(np.uint8)
    return cached(("glow", size, tuple(color), falloff), build)


def sparkle(size: int, color=(255, 250, 240)) -> np.ndarray:
    """BGR light sprite: a four-pointed twinkle star with a soft core."""
    def build():
        r = np.linspace(-1, 1, size, dtype=np.float32)
        x, y = r[None, :], r[:, None]
        d2 = x * x + y * y
        rays = (np.exp(-(y * y) / 0.0012) * np.clip(1 - np.abs(x), 0, 1) ** 2.5
                + np.exp(-(x * x) / 0.0012) * np.clip(1 - np.abs(y), 0, 1) ** 2.5)
        v = rays + np.exp(-d2 / 0.006) + 0.35 * np.exp(-d2 / 0.05)
        return (np.clip(v, 0, 1)[..., None] * np.asarray(color, np.float32)).astype(np.uint8)
    return cached(("sparkle", size, tuple(color)), build)


# -- shapes


def heart_points(cx, cy, size, n=160) -> np.ndarray:
    """Outline of a plump heart, size = width in pixels."""
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    x = 16 * np.sin(t) ** 3
    y = -(13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t))
    pts = np.stack([x, y + 2.5], axis=1) * (size / 34.0)
    return pts + (cx, cy)


def heart_sprite(size: int, blur=0.0) -> np.ndarray:
    """Glossy red 3D heart, about size px wide."""
    def build():
        ss = 3
        s = size * ss
        pad = int(s * 0.12)
        cw = s + 2 * pad
        mask = np.zeros((cw, cw), np.float32)
        pts = heart_points(cw / 2, cw / 2, s)
        cv2.fillPoly(mask, [(pts * 16).astype(np.int32)], 1.0, cv2.LINE_AA, shift=4)
        yy = np.linspace(0, 1, cw, dtype=np.float32)[:, None, None]
        top = np.array([110, 80, 255], np.float32) / 255     # BGR: warm pink-red
        bottom = np.array([70, 20, 215], np.float32) / 255   # deeper crimson
        color = np.broadcast_to(top + (bottom - top) * yy, (cw, cw, 3)).copy()
        rgb = inflate(mask, color, bevel=1.0, ambient=0.5, diffuse=0.62, specular=0.55,
                      shininess=24, rim=0.25)
        # The soft "window" reflection on the left lobe that makes it look glossy.
        hl = soft_ellipse(mask.shape, cw / 2 - s * 0.2, cw / 2 - s * 0.14, s * 0.11, s * 0.06,
                          -35, blur=s * 0.012)
        rgb = rgb + (hl * mask * 0.75)[..., None] * (1 - rgb)
        return finish_sprite(rgb, mask, ss, shadow=0.0, blur=blur,
                             glow=((0.45, 0.35, 1.0), 0.3, 0.03))
    return cached(("heart", size, blur), build)


# -- emoji (vector paths, shaded at load time)

# Thumbs-up artwork from Twemoji (https://github.com/jdecked/twemoji),
# Copyright Twitter, Inc and other contributors, licensed CC-BY 4.0
# (https://creativecommons.org/licenses/by/4.0/). Changed here: rendered with
# 3D shading and a drop shadow; thumbs-down is the same drawing flipped.
_THUMB_PATHS = [
    ((94, 219, 255),  # BGR of #FFDB5E
     "M34.956 17.916c0-.503-.12-.975-.321-1.404-1.341-4.326-7.619-4.01-16.549-4.221-1.493-.035"
     "-.639-1.798-.115-5.668.341-2.517-1.282-6.382-4.01-6.382-4.498 0-.171 3.548-4.148 12.322"
     "-2.125 4.688-6.875 2.062-6.875 6.771v10.719c0 1.833.18 3.595 2.758 3.885C8.195 34.219 "
     "7.633 36 11.238 36h18.044c1.838 0 3.333-1.496 3.333-3.334 0-.762-.267-1.456-.698-2.018 "
     "1.02-.571 1.72-1.649 1.72-2.899 0-.76-.266-1.454-.696-2.015 1.023-.57 1.725-1.649 "
     "1.725-2.901 0-.909-.368-1.733-.961-2.336.757-.611 1.251-1.535 1.251-2.581z"),
    ((71, 149, 238),  # BGR of #EE9547
     "M23.02 21.249h8.604c1.17 0 2.268-.626 2.866-1.633.246-.415.109-.952-.307-1.199-.415-.247"
     "-.952-.108-1.199.307-.283.479-.806.775-1.361.775h-8.81c-.873 0-1.583-.71-1.583-1.583s.71"
     "-1.583 1.583-1.583H28.7c.483 0 .875-.392.875-.875s-.392-.875-.875-.875h-5.888c-1.838 0"
     "-3.333 1.495-3.333 3.333 0 1.025.475 1.932 1.205 2.544-.615.605-.998 1.445-.998 2.373 0 "
     "1.028.478 1.938 1.212 2.549-.611.604-.99 1.441-.99 2.367 0 1.12.559 2.108 1.409 2.713"
     "-.524.589-.852 1.356-.852 2.204 0 1.838 1.495 3.333 3.333 3.333h5.484c1.17 0 2.269-.625 "
     "2.867-1.632.247-.415.11-.952-.305-1.199-.416-.245-.953-.11-1.199.305-.285.479-.808.776"
     "-1.363.776h-5.484c-.873 0-1.583-.71-1.583-1.583s.71-1.583 1.583-1.583h6.506c1.17 0 "
     "2.27-.626 2.867-1.633.247-.416.11-.953-.305-1.199-.419-.251-.954-.11-1.199.305-.289.487"
     "-.799.777-1.363.777h-7.063c-.873 0-1.583-.711-1.583-1.584s.71-1.583 1.583-1.583h8.091c1.17"
     " 0 2.269-.625 2.867-1.632.247-.415.11-.952-.305-1.199-.417-.246-.953-.11-1.199.305-.289"
     ".486-.799.776-1.363.776H23.02c-.873 0-1.583-.71-1.583-1.583s.709-1.584 1.583-1.584z"),
]

_SVG_TOKEN = re.compile(r"[MmLlHhVvCcSsZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def svg_path_polygons(d: str, steps=10) -> list[np.ndarray]:
    """Flatten an SVG path (M L H V C S Z, absolute and relative) into closed polygons."""
    tokens = _SVG_TOKEN.findall(d)
    polys, cur = [], []
    x = y = sx = sy = 0.0
    last_ctrl = None
    cmd = None
    i = 0

    def num():
        nonlocal i
        i += 1
        return float(tokens[i - 1])

    def cubic(p0, p1, p2, p3):
        t = np.linspace(0, 1, steps + 1)[1:, None]
        return ((1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2
                + t ** 3 * p3)

    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
            if cmd in "Zz":
                if cur:
                    polys.append(np.array(cur))
                cur, (x, y) = [], (sx, sy)
                continue
        rel = cmd.islower()
        c = cmd.upper()
        ox, oy = (x, y) if rel else (0.0, 0.0)
        if c == "M":
            if cur:
                polys.append(np.array(cur))
            x, y = ox + num(), oy + num()
            sx, sy = x, y
            cur = [(x, y)]
            cmd = "l" if rel else "L"
            last_ctrl = None
        elif c == "L":
            x, y = ox + num(), oy + num()
            cur.append((x, y))
            last_ctrl = None
        elif c == "H":
            x = (x if rel else 0.0) + num()
            cur.append((x, y))
            last_ctrl = None
        elif c == "V":
            y = (y if rel else 0.0) + num()
            cur.append((x, y))
            last_ctrl = None
        elif c in "CS":
            p0 = np.array([x, y])
            if c == "C":
                p1 = np.array([ox + num(), oy + num()])
            else:
                p1 = 2 * p0 - last_ctrl if last_ctrl is not None else p0
            p2 = np.array([ox + num(), oy + num()])
            p3 = np.array([ox + num(), oy + num()])
            cur.extend(map(tuple, cubic(p0, p1, p2, p3)))
            last_ctrl = p2
            x, y = p3
        else:
            raise ValueError(f"unsupported SVG path command {cmd!r}")
    if cur:
        polys.append(np.array(cur))
    return polys


def thumb_sprite(size: int, up=True) -> np.ndarray:
    """3D-shaded thumbs up/down emoji, size px square."""
    def build():
        ss = 3
        s = size * ss
        pad = int(s * 0.12)
        cw = s + 2 * pad
        k = s / 36.0
        color = np.zeros((cw, cw, 3), np.float32)
        mask = np.zeros((cw, cw), np.float32)
        for bgr, d in _THUMB_PATHS:
            polys = []
            for p in svg_path_polygons(d):
                if not up:
                    p = np.stack([p[:, 0], 36 - p[:, 1]], 1)
                polys.append(((p * k + pad) * 16).astype(np.int32))
            layer = np.zeros((cw, cw), np.float32)
            cv2.fillPoly(layer, polys, 1.0, cv2.LINE_AA, shift=4)
            color = color * (1 - layer[..., None]) + (np.array(bgr, np.float32) / 255) * layer[..., None]
            mask = np.maximum(mask, layer)
        # Slight warm-to-amber gradient for depth before lighting.
        yy = np.linspace(0, 1, cw, dtype=np.float32)[:, None, None]
        color = color * (1.04 - 0.12 * yy)
        rgb = inflate(mask, color, bevel=0.28, ambient=0.66, diffuse=0.42, specular=0.45,
                      shininess=18, rim=0.12)
        return finish_sprite(rgb, mask, ss, shadow=0.35, shadow_offset=0.035, shadow_blur=0.03)
    return cached(("thumb", size, up), build)


def glass_bubble_sprites(size: int):
    """(disc mask, gloss overlay, drop shadow) for a frosted-glass bubble size px wide."""
    def build_mask():
        ss = 3
        s = size * ss
        m = np.zeros((s, s), np.float32)
        cv2.circle(m, (s // 2 * 16, s // 2 * 16), (s // 2 - ss) * 16, 1.0, -1, cv2.LINE_AA, shift=4)
        return cv2.resize(m, (size, size), interpolation=cv2.INTER_AREA)

    def build_gloss():
        ss = 3
        s = size * ss
        c = s / 2
        r = s / 2 - ss
        yy, xx = np.mgrid[0:s, 0:s].astype(np.float32)
        d = np.sqrt((xx - c) ** 2 + (yy - c) ** 2) / r
        inside = np.clip((1 - d) * r / 1.5, 0, 1)
        # Bright rim, strongest at the top left where the light comes from.
        ang = np.arctan2(yy - c, xx - c)
        facing = 0.55 + 0.45 * np.cos(ang + 2.3)
        rim = np.exp(-((1 - d) * r / (s * 0.012)) ** 2) * inside * (0.35 + 0.65 * facing)
        # Inner shading at the bottom edge gives the glass some thickness.
        inner = np.clip((d - 0.75) / 0.25, 0, 1) ** 2 * np.clip((yy - c) / r, 0, 1) * inside
        # Curved top reflection.
        top = soft_ellipse((s, s), c, c - r * 0.52, r * 0.62, r * 0.36, 0, blur=s * 0.03)
        top *= np.clip(1 - (yy - (c - r * 0.85)) / (r * 0.7), 0, 1) ** 1.3 * inside
        white = np.clip(rim * 0.9 + top * 0.42, 0, 1)
        shade = inner * 0.18
        a = np.clip(white + shade, 0, 1)
        rgb = np.where(a[..., None] > 0, (white / np.maximum(a, 1e-4))[..., None], 0) * np.ones(3)
        return finish_sprite(rgb.astype(np.float32), a, ss)

    def build_shadow():
        s = int(size * 1.4)
        m = soft_ellipse((s, s), s / 2, s / 2, size * 0.46, size * 0.46, 0, blur=size * 0.07)
        return finish_sprite(np.zeros((s, s, 3), np.float32), m * 0.42, 1)

    return (cached(("bubble_mask", size), build_mask),
            cached(("bubble_gloss", size), build_gloss),
            cached(("bubble_shadow", size), build_shadow))


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
    """A frosted-glass bubble springs in with a glossy 3D thumb, floats, then pops away."""

    duration = 2.8
    fade_in = 0.0
    fade_out = 0.45

    def __init__(self, w, h, up: bool, seed=None):
        super().__init__(w, h, seed)
        self.up = up
        self.size = int(h * 0.46) // 2 * 2
        self.mask, self.gloss, self.shadow = glass_bubble_sprites(self.size)
        self.emoji = thumb_sprite(int(self.size * 0.7), up)
        # Up and to the side of the face, like a speech bubble.
        self.cx, self.cy = w * 0.5 + min(w * 0.27, h * 0.5), h * 0.38
        self.star = sparkle(max(8, int(h * 0.12)))
        rng = self.rng
        self.glints = [(a + rng.uniform(-0.2, 0.2), rng.uniform(0.62, 0.8), rng.uniform(0.6, 1.0),
                        rng.uniform(0.0, 0.12))
                       for a in np.linspace(0, 2 * math.pi, 7, endpoint=False)]

    def _bubble(self, frame, cx, cy, d, alpha):
        """Frosted glass: blurred, brightened background inside a disc, plus a gloss rim."""
        d = int(d) // 2 * 2
        if d < 6:
            return
        x0, y0 = int(cx - d / 2), int(cy - d / 2)
        r = _region(frame.shape, x0, y0, d, d)
        if r is None:
            return
        dst, src = r
        patch = frame[dst]
        ph, pw = patch.shape[:2]
        small = cv2.resize(patch, (max(1, pw // 6), max(1, ph // 6)), interpolation=cv2.INTER_AREA)
        small = cv2.GaussianBlur(small, (0, 0), 1.6)
        frosted = cv2.resize(small, (pw, ph), interpolation=cv2.INTER_LINEAR)
        # Lighten toward a faint tint: 70% blurred scene + 30% tint, as one colour matrix.
        tint = np.array((255, 244, 238) if self.up else (240, 240, 244), np.float32)
        frosted = cv2.transform(frosted, np.hstack([np.eye(3, dtype=np.float32) * 0.7, tint[:, None] * 0.3]))
        m = cv2.resize(self.mask, (d, d), interpolation=cv2.INTER_LINEAR)[src] * alpha
        frame[dst] = cv2.blendLinear(frosted, patch, np.ascontiguousarray(m), 1 - m)
        blit(frame, self.gloss, cx, cy, d / self.size, alpha)

    def draw(self, frame):
        t, h = self.t, self.h
        out = clamp01((t - (self.duration - self.fade_out)) / self.fade_out)
        alpha = 1 - ease_in_cubic(out) if out > 0 else 1.0
        exit_scale = 1 + 0.12 * ease_in_cubic(out) if self.up else 1 - 0.15 * ease_in_cubic(out)
        drift = ease_in_out_sine(t / self.duration)
        cx = self.cx
        cy = self.cy - drift * h * 0.05 if self.up else self.cy + drift * h * 0.03
        cy += math.sin(t * 2.6) * h * 0.006

        bubble = spring(t, 1.7, 5.5) * exit_scale
        blit(frame, self.shadow, cx, cy + self.size * 0.08 * bubble, bubble, 0.85 * alpha)
        self._bubble(frame, cx, cy, self.size * bubble, alpha)

        pop = spring(t - 0.08, 1.9, 5.0) * exit_scale
        if self.up:
            angle = 16 * math.exp(-3.5 * t) * math.sin(2 * math.pi * 1.6 * t)
        else:
            angle = -10 * math.exp(-3.0 * t) * math.sin(2 * math.pi * 2.2 * t)
        blit(frame, self.emoji, cx, cy, pop, alpha, angle)

        if self.up:  # a quick ring of glints as it lands
            for a, dist, size, delay in self.glints:
                p = (t - 0.12 - delay) / 0.55
                if 0 < p < 1:
                    rr = self.size * (dist + 0.25 * ease_out_cubic(p))
                    g = math.sin(math.pi * p) * alpha
                    add_light(frame, self.star, cx + math.cos(a) * rr, cy + math.sin(a) * rr,
                              g, size * (0.5 + 0.5 * math.sin(math.pi * p)))


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
    """Glossy 3D hearts pop up from the bottom and float away, with depth of field."""

    duration = 4.0
    fade_in = 0.3
    fade_out = 0.8

    # (relative size, blur, speed in heights/s, opacity, count)
    LAYERS = [(0.09, 0.006, 0.26, 0.8, 11), (0.17, 0.0, 0.36, 1.0, 14), (0.3, 0.012, 0.5, 0.95, 4)]

    def __init__(self, w, h, seed=None):
        super().__init__(w, h, seed)
        rng = self.rng
        self.sprites = [heart_sprite(int(h * s), blur) for s, blur, *_ in self.LAYERS]
        self.hearts = []
        for layer, (s, _, speed, opacity, n) in enumerate(self.LAYERS):
            for i in range(n):
                self.hearts.append({
                    "layer": layer,
                    "x": (i + rng.uniform(0.1, 0.9)) / n * w,
                    "y0": h + h * s * 0.7,
                    "t0": rng.uniform(0, 1.9),
                    "v": speed * h * rng.uniform(0.85, 1.15),
                    "scale": rng.uniform(0.75, 1.0),
                    "sway": rng.uniform(0.02, 0.05) * w,
                    "freq": rng.uniform(0.6, 1.1),
                    "phase": rng.uniform(0, 2 * math.pi),
                    "tilt": rng.uniform(-14, 14),
                    "opacity": opacity,
                })
        self.hearts.sort(key=lambda d: d["layer"])

    def draw(self, frame):
        e = self.envelope
        grade(frame, e, gain=(0.97, 0.94, 1.05), lift=(8, 0, 14), vignette=0.3)
        for d in self.hearts:
            tau = self.t - d["t0"]
            if tau <= 0:
                continue
            y = d["y0"] - d["v"] * tau - d["v"] * 0.35 * (1 - math.exp(-4 * tau))
            if y < -self.h * 0.3:
                continue
            x = d["x"] + math.sin(tau * d["freq"] * 2 * math.pi * 0.5 + d["phase"]) * d["sway"]
            scale = d["scale"] * spring(tau, 1.5, 6.0) * (1 + 0.04 * math.sin(tau * 9 + d["phase"]))
            angle = d["tilt"] + 8 * math.sin(tau * 1.7 + d["phase"])
            top_fade = smoothstep((y + self.h * 0.1) / (self.h * 0.35))
            blit(frame, self.sprites[d["layer"]], x, y, scale, d["opacity"] * e * top_fade, angle)


# ---------------------------------------------------------------- manager


def make_effect(name: str, w: int, h: int, seed: int | None = None) -> Effect:
    return {
        REACTION_THUMBS_UP: lambda: ThumbEffect(w, h, up=True, seed=seed),
        REACTION_THUMBS_DOWN: lambda: ThumbEffect(w, h, up=False, seed=seed),
        REACTION_FIREWORKS: lambda: FireworksEffect(w, h),
        REACTION_RAIN: lambda: RainEffect(w, h),
        REACTION_BALLOONS: lambda: BalloonsEffect(w, h),
        REACTION_CONFETTI: lambda: ConfettiEffect(w, h),
        REACTION_LASERS: lambda: LasersEffect(w, h),
        REACTION_HEARTS: lambda: HeartsEffect(w, h, seed=seed),
    }[name]()


class EffectPlayer:
    """Holds the currently running effects and draws them every frame."""

    def __init__(self):
        self.effects: list[Effect] = []

    def preload(self, w: int, h: int):
        """Build every effect's sprites now, so the first reaction doesn't stutter."""
        for name in (REACTION_THUMBS_UP, REACTION_THUMBS_DOWN, REACTION_FIREWORKS, REACTION_RAIN,
                     REACTION_BALLOONS, REACTION_CONFETTI, REACTION_LASERS, REACTION_HEARTS):
            # Draw one frame too, so OpenCV's code paths are warm before the first real one.
            fx = make_effect(name, w, h)
            fx.update(0.5)
            fx.draw(np.zeros((h, w, 3), np.uint8))
        _vignette(w, h)

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
