"""Hand-sign classification from MediaPipe hand landmarks.

Works on the 21 landmarks MediaPipe returns per hand (x, y in 0..1 image
coordinates, y pointing down). Everything is measured relative to the size of
the hand, so it does not matter how far you sit from the camera.

Landmark indices (MediaPipe convention):
    0 wrist
    1-4   thumb  (CMC, MCP, IP, TIP)
    5-8   index  (MCP, PIP, DIP, TIP)
    9-12  middle
    13-16 ring
    17-20 pinky
"""

from __future__ import annotations

import math
from collections import Counter, deque
from dataclasses import dataclass, field

WRIST = 0
THUMB_MCP, THUMB_IP, THUMB_TIP = 2, 3, 4
INDEX_MCP, INDEX_PIP, INDEX_TIP = 5, 6, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP = 9, 10, 12
RING_MCP, RING_PIP, RING_TIP = 13, 14, 16
PINKY_MCP, PINKY_PIP, PINKY_TIP = 17, 18, 20

FINGERS = {
    "index": (INDEX_MCP, INDEX_PIP, INDEX_TIP),
    "middle": (MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP),
    "ring": (RING_MCP, RING_PIP, RING_TIP),
    "pinky": (PINKY_MCP, PINKY_PIP, PINKY_TIP),
}

# Per-hand gestures
THUMBS_UP = "thumbs_up"
THUMBS_DOWN = "thumbs_down"
PEACE = "peace"
ROCK = "rock"

# Reactions (what gets shown), matching macOS
REACTION_THUMBS_UP = "thumbs_up"
REACTION_THUMBS_DOWN = "thumbs_down"
REACTION_FIREWORKS = "fireworks"
REACTION_RAIN = "rain"
REACTION_BALLOONS = "balloons"
REACTION_CONFETTI = "confetti"
REACTION_LASERS = "lasers"
REACTION_HEARTS = "hearts"

ALL_REACTIONS = [
    REACTION_THUMBS_UP,
    REACTION_THUMBS_DOWN,
    REACTION_FIREWORKS,
    REACTION_RAIN,
    REACTION_BALLOONS,
    REACTION_CONFETTI,
    REACTION_LASERS,
    REACTION_HEARTS,
]


def _xy(p):
    """Accept MediaPipe landmark objects or plain (x, y[, z]) tuples."""
    if hasattr(p, "x"):
        return p.x, p.y
    return p[0], p[1]


def _dist(a, b):
    ax, ay = _xy(a)
    bx, by = _xy(b)
    return math.hypot(ax - bx, ay - by)


def hand_size(lm) -> float:
    """Wrist to middle-finger knuckle: a stable scale for the hand."""
    return max(_dist(lm[WRIST], lm[MIDDLE_MCP]), 1e-6)


def finger_extended(lm, finger: str) -> bool:
    """A finger is straight when its tip is clearly farther from the wrist
    than its middle joint, and well away from the palm."""
    mcp, pip, tip = FINGERS[finger]
    s = hand_size(lm)
    tip_d = _dist(lm[tip], lm[WRIST])
    pip_d = _dist(lm[pip], lm[WRIST])
    return tip_d > pip_d * 1.12 and _dist(lm[tip], lm[mcp]) > 0.55 * s


def finger_folded(lm, finger: str) -> bool:
    """A finger is curled when its tip is no farther from the wrist than its
    middle joint (tip tucked into the palm)."""
    mcp, pip, tip = FINGERS[finger]
    return _dist(lm[tip], lm[WRIST]) < _dist(lm[pip], lm[WRIST]) * 1.05


def thumb_extended(lm) -> bool:
    """Thumb sticks out: tip far from the index knuckle and from its own base.
    The second limit is loose because a thumb pointing at the camera looks short."""
    s = hand_size(lm)
    return (
        _dist(lm[THUMB_TIP], lm[INDEX_MCP]) > 0.6 * s
        and _dist(lm[THUMB_TIP], lm[THUMB_MCP]) > 0.35 * s
    )


def classify_hand(lm) -> str | None:
    """Return the gesture made by a single hand, or None."""
    s = hand_size(lm)
    ext = {f: finger_extended(lm, f) for f in FINGERS}
    fold = {f: finger_folded(lm, f) for f in FINGERS}

    # Thumbs up / down: fist with only the thumb out, pointing vertically.
    if all(fold.values()) and thumb_extended(lm):
        tx, ty = _xy(lm[THUMB_TIP])
        mx, my = _xy(lm[THUMB_MCP])
        dx, dy = tx - mx, ty - my
        if abs(dy) > abs(dx) * 1.2 and abs(dy) > 0.3 * s:
            # The thumb tip must also clear the curled fingers.
            knuckles_y = [_xy(lm[i])[1] for i in (INDEX_PIP, MIDDLE_PIP, RING_PIP, PINKY_PIP)]
            if dy < 0 and ty < min(knuckles_y):
                return THUMBS_UP
            if dy > 0 and ty > max(knuckles_y):
                return THUMBS_DOWN

    # Peace / victory: index + middle out and spread apart, ring + pinky curled.
    if ext["index"] and ext["middle"] and fold["ring"] and fold["pinky"]:
        if _dist(lm[INDEX_TIP], lm[MIDDLE_TIP]) > 0.3 * s:
            return PEACE

    # Rock on / horns: index + pinky out, middle + ring curled.
    if ext["index"] and ext["pinky"] and fold["middle"] and fold["ring"]:
        return ROCK

    return None


def is_heart(lm_a, lm_b) -> bool:
    """Two hands forming a heart: thumb tips touch at the bottom, index tips
    touch at the top, with an opening in between."""
    s = (hand_size(lm_a) + hand_size(lm_b)) / 2
    thumbs_close = _dist(lm_a[THUMB_TIP], lm_b[THUMB_TIP]) < 0.55 * s
    index_close = _dist(lm_a[INDEX_TIP], lm_b[INDEX_TIP]) < 0.55 * s
    if not (thumbs_close and index_close):
        return False
    # Index tips above thumb tips (heart's top lobes over its point), with a gap.
    ia = _xy(lm_a[INDEX_TIP])
    ib = _xy(lm_b[INDEX_TIP])
    ta = _xy(lm_a[THUMB_TIP])
    tb = _xy(lm_b[THUMB_TIP])
    index_y = (ia[1] + ib[1]) / 2
    thumb_y = (ta[1] + tb[1]) / 2
    return thumb_y - index_y > 0.5 * s


def classify_frame(hands: list) -> str | None:
    """Map the hands in one frame to a reaction name (or None)."""
    if len(hands) >= 2 and is_heart(hands[0], hands[1]):
        return REACTION_HEARTS

    gestures = [classify_hand(h) for h in hands[:2]]
    counts = Counter(g for g in gestures if g)

    if counts[THUMBS_UP] >= 2:
        return REACTION_FIREWORKS
    if counts[THUMBS_DOWN] >= 2:
        return REACTION_RAIN
    if counts[PEACE] >= 2:
        return REACTION_CONFETTI
    if counts[ROCK] >= 2:
        return REACTION_LASERS
    # Single-hand reactions only when the other hand isn't doing something else.
    if len(counts) == 1:
        if counts[THUMBS_UP] == 1:
            return REACTION_THUMBS_UP
        if counts[THUMBS_DOWN] == 1:
            return REACTION_THUMBS_DOWN
        if counts[PEACE] == 1:
            return REACTION_BALLOONS
    return None


@dataclass
class ReactionTrigger:
    """Debounces per-frame guesses so a reaction fires only when a gesture is
    held steadily, and not again until a cooldown has passed."""

    hold_seconds: float = 0.45
    cooldown_seconds: float = 3.0
    agreement: float = 0.75
    _history: deque = field(default_factory=deque)
    _last_fire: float = -1e9

    def update(self, reaction: str | None, now: float) -> str | None:
        self._history.append((now, reaction))
        while self._history and now - self._history[0][0] > self.hold_seconds:
            self._history.popleft()

        if reaction is None or now - self._last_fire < self.cooldown_seconds:
            return None
        # Need a full window of history before deciding.
        if now - self._history[0][0] < self.hold_seconds * 0.8:
            return None
        votes = sum(1 for _, r in self._history if r == reaction)
        if votes / len(self._history) >= self.agreement:
            self._last_fire = now
            self._history.clear()
            return reaction
        return None
