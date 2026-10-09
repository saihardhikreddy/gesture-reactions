"""Times every effect per frame, the way the app runs it, without a webcam.

    python scripts/bench_effects.py [--width 1280 --height 720]

Sprites are built first (as the app does at startup), then each effect is
played start to finish on a sample frame and its update + draw time recorded.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from effects import EffectPlayer, make_effect  # noqa: E402
from gestures import ALL_REACTIONS  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--runs", type=int, default=3)
    args = ap.parse_args()
    w, h = args.width, args.height

    t0 = time.perf_counter()
    EffectPlayer().preload(w, h)
    print(f"preload: {(time.perf_counter() - t0) * 1000:.0f} ms at {w}x{h}\n")

    rng = np.random.default_rng(0)
    base = rng.integers(40, 200, (h, w, 3), dtype=np.uint8)
    print(f"{'effect':<12} {'avg ms':>7} {'p95 ms':>7} {'max ms':>7} {'frames':>7}")
    for name in ALL_REACTIONS:
        times = []
        for run in range(args.runs):
            fx = make_effect(name, w, h, seed=run)
            while fx.alive:
                frame = base.copy()
                t = time.perf_counter()
                fx.update(1 / 30)
                fx.draw(frame)
                times.append((time.perf_counter() - t) * 1000)
        a = np.array(times)
        print(f"{name:<12} {a.mean():7.2f} {np.percentile(a, 95):7.2f} {a.max():7.2f} {len(a) // args.runs:7d}")


if __name__ == "__main__":
    main()
