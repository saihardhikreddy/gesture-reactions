"""Checks the gesture rules against synthetic hand skeletons.

Run from the repo root:  python -m pytest
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gestures import (
    PEACE, ROCK, THUMBS_DOWN, THUMBS_UP,
    REACTION_BALLOONS, REACTION_CONFETTI, REACTION_FIREWORKS, REACTION_HEARTS,
    REACTION_LASERS, REACTION_RAIN, REACTION_THUMBS_DOWN, REACTION_THUMBS_UP,
    ReactionTrigger, classify_frame, classify_hand,
)


def make_hand(fingers="", thumb=False, angle=0.0, cx=0.5, cy=0.6, scale=0.1, mirror=False):
    """Build 21 landmarks in a local frame where the fingers point up (-y) and
    the thumb sticks out to +x, then rotate (radians, clockwise on screen),
    scale and move it. `fingers` lists extended ones: i, m, r, p."""
    pts = [(0.0, 0.0)] * 21
    pts[0] = (0.0, 0.0)
    mcp_x = {"i": 0.35, "m": 0.1, "r": -0.15, "p": -0.38}
    base = {"i": 5, "m": 9, "r": 13, "p": 17}
    for f, i0 in base.items():
        x = mcp_x[f]
        mcp = (x, -1.0 if f != "p" else -0.9)
        if f in fingers:
            seg = [0.45, 0.3, 0.25]
            spread = {"i": 0.15, "m": -0.05, "r": -0.1, "p": -0.2}[f]
            if f == "i" and "m" in fingers and "r" not in fingers:
                spread = 0.25  # V sign
            if f == "m" and "i" in fingers and "r" not in fingers:
                spread = -0.25
            d = (math.sin(spread), -math.cos(spread))
            p = mcp
            out = [mcp]
            for s in seg:
                p = (p[0] + d[0] * s, p[1] + d[1] * s)
                out.append(p)
        else:  # curled into the palm
            out = [mcp, (x, mcp[1] - 0.35), (x, mcp[1] - 0.2), (x, mcp[1] + 0.25)]
        for k, q in enumerate(out):
            pts[i0 + k] = q
    if thumb:
        thumb_pts = [(0.3, -0.2), (0.55, -0.35), (0.85, -0.45), (1.1, -0.5)]
    else:
        thumb_pts = [(0.3, -0.2), (0.45, -0.45), (0.35, -0.65), (0.2, -0.75)]
    for k, q in enumerate(thumb_pts):
        pts[1 + k] = q

    out = []
    c, s = math.cos(angle), math.sin(angle)
    for x, y in pts:
        if mirror:
            x = -x
        rx, ry = x * c - y * s, x * s + y * c
        out.append((cx + rx * scale, cy + ry * scale, 0.0))
    return out


UP = math.radians(-90)   # rotates thumb (+x) to point up
DOWN = math.radians(90)  # rotates thumb (+x) to point down


def test_single_hand_gestures():
    assert classify_hand(make_hand(thumb=True, angle=UP)) == THUMBS_UP
    assert classify_hand(make_hand(thumb=True, angle=DOWN)) == THUMBS_DOWN
    assert classify_hand(make_hand("im")) == PEACE
    assert classify_hand(make_hand("im", thumb=False, angle=math.radians(15))) == PEACE
    assert classify_hand(make_hand("ip")) == ROCK
    assert classify_hand(make_hand("ip", thumb=True)) == ROCK


def test_mirrored_thumbs():
    # Left hand: mirror the local frame, so the thumb points to -x; rotate the other way.
    assert classify_hand(make_hand(thumb=True, angle=DOWN, mirror=True)) == THUMBS_UP
    assert classify_hand(make_hand(thumb=True, angle=UP, mirror=True)) == THUMBS_DOWN


def test_scale_invariance():
    for scale in (0.05, 0.1, 0.2):
        assert classify_hand(make_hand("im", scale=scale)) == PEACE
        assert classify_hand(make_hand(thumb=True, angle=UP, scale=scale)) == THUMBS_UP


def test_non_gestures():
    assert classify_hand(make_hand("imrp", thumb=True)) is None   # open palm
    assert classify_hand(make_hand("")) is None                  # fist
    assert classify_hand(make_hand("i")) is None                 # pointing
    assert classify_hand(make_hand("imr")) is None               # three fingers
    assert classify_hand(make_hand(thumb=True)) is None          # thumb sideways


def test_two_hand_reactions():
    L, R = dict(cx=0.3), dict(cx=0.7)
    up_r, up_l = make_hand(thumb=True, angle=UP, **R), make_hand(thumb=True, angle=DOWN, mirror=True, **L)
    dn_r, dn_l = make_hand(thumb=True, angle=DOWN, **R), make_hand(thumb=True, angle=UP, mirror=True, **L)
    assert classify_frame([up_r]) == REACTION_THUMBS_UP
    assert classify_frame([dn_r]) == REACTION_THUMBS_DOWN
    assert classify_frame([up_l, up_r]) == REACTION_FIREWORKS
    assert classify_frame([dn_l, dn_r]) == REACTION_RAIN
    assert classify_frame([make_hand("im", **R)]) == REACTION_BALLOONS
    assert classify_frame([make_hand("im", **L), make_hand("im", **R)]) == REACTION_CONFETTI
    assert classify_frame([make_hand("ip", **L), make_hand("ip", **R)]) == REACTION_LASERS
    assert classify_frame([make_hand("ip", **R)]) is None   # one rock-on hand: nothing, like macOS
    assert classify_frame([up_l, dn_r]) is None             # mixed signals
    assert classify_frame([]) is None


def heart_hands():
    """Two hands meeting: index tips touching above, thumb tips touching below."""
    def hand(sign):
        cx = 0.5 + sign * 0.12
        lm = [(cx, 0.7, 0.0)] * 21
        lm = [list(p) for p in lm]
        lm[0] = [cx + sign * 0.02, 0.75, 0]
        # fingers curve over the top toward the centre line
        for i0, dy in ((5, 0.0), (9, 0.02), (13, 0.04), (17, 0.06)):
            lm[i0] = [cx + sign * 0.02, 0.62 + dy, 0]
            lm[i0 + 1] = [cx, 0.52 + dy, 0]
            lm[i0 + 2] = [0.5 + sign * 0.05, 0.47 + dy, 0]
            lm[i0 + 3] = [0.5 + sign * 0.01, 0.49 + dy, 0]
        lm[1] = [cx, 0.72, 0]
        lm[2] = [cx - sign * 0.04, 0.76, 0]
        lm[3] = [0.5 + sign * 0.04, 0.8, 0]
        lm[4] = [0.5 + sign * 0.01, 0.82, 0]
        return lm

    return [hand(-1), hand(1)]


def test_heart():
    assert classify_frame(heart_hands()) == REACTION_HEARTS
    # Same hands pulled apart: no heart.
    a, b = heart_hands()
    b = [[x + 0.3, y, z] for x, y, z in b]
    assert classify_frame([a, b]) != REACTION_HEARTS


def test_trigger_needs_hold_and_cooldown():
    trig = ReactionTrigger(hold_seconds=0.5, cooldown_seconds=3.0)
    fired = [trig.update("hearts", t / 30) for t in range(0, 30)]
    assert fired.count("hearts") == 1
    assert fired.index("hearts") >= 12            # ~0.4 s+ of holding first
    # Still holding during cooldown: nothing more.
    assert all(trig.update("hearts", 1 + t / 30) is None for t in range(60))
    # A one-frame flicker doesn't fire.
    trig2 = ReactionTrigger()
    assert trig2.update("confetti", 0.0) is None
    assert all(trig2.update(None, t / 30) is None for t in range(1, 30))


if __name__ == "__main__":
    import sys
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print("PASS", name)
            except AssertionError as e:
                failed += 1
                print("FAIL", name, e)
    sys.exit(1 if failed else 0)
