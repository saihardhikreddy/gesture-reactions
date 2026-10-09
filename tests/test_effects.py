"""Runs every reaction effect on blank frames, without a webcam.

Needs OpenCV and numpy (pip install -r requirements.txt); skipped without them.
"""

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

import effects  # noqa: E402
from effects import EffectPlayer, make_effect  # noqa: E402
from gestures import ALL_REACTIONS  # noqa: E402

W, H = 320, 180
FPS = 30


def play(name, w=W, h=H, seed=1):
    """Run an effect to the end; return (frames drawn, frame at the midpoint)."""
    fx = make_effect(name, w, h, seed=seed)
    limit = int(fx.duration * FPS) + 5
    frame = mid = None
    n = 0
    while fx.alive:
        assert n < limit, f"{name} did not finish"
        frame = np.zeros((h, w, 3), np.uint8)
        fx.update(1 / FPS)
        fx.draw(frame)
        assert frame.shape == (h, w, 3) and frame.dtype == np.uint8
        n += 1
        if n == int(fx.duration * FPS / 2):
            mid = frame.copy()
    return n, mid


@pytest.mark.parametrize("name", ALL_REACTIONS)
def test_effect_runs_to_the_end(name):
    n, mid = play(name)
    assert n > FPS  # lasts more than a second
    assert mid is not None and mid.any(), f"{name} drew nothing halfway through"


@pytest.mark.parametrize("name", ALL_REACTIONS)
def test_effect_handles_odd_and_tiny_frame_sizes(name):
    play(name, 333, 177)
    play(name, 64, 36)


@pytest.mark.parametrize("name", ALL_REACTIONS)
def test_effect_is_repeatable_with_a_seed(name):
    _, a = play(name, seed=7)
    _, b = play(name, seed=7)
    assert np.array_equal(a, b)


def test_player_triggers_and_clears():
    player = EffectPlayer()
    player.preload(W, H)
    assert not player.busy
    player.trigger("hearts", W, H)
    player.trigger("thumbs_up", W, H)
    assert player.busy
    for _ in range(10 * FPS):
        player.render(np.zeros((H, W, 3), np.uint8), 1 / FPS)
        if not player.busy:
            break
    assert not player.busy


def test_blit_clips_at_every_edge():
    sprite = effects.heart_sprite(60)
    for cx, cy in [(-20, -20), (W + 20, H + 20), (-500, 50), (W / 2, H + 500), (W / 2, H / 2)]:
        frame = np.zeros((H, W, 3), np.uint8)
        effects.blit(frame, sprite, cx, cy, scale=1.3, alpha=0.7, angle=25)
        assert frame.shape == (H, W, 3)
    effects.add_light(frame, effects.glow_dot(40), -10, H + 5, 0.5)


def test_sprites_are_premultiplied_bgra_and_cached():
    a = effects.heart_sprite(48)
    assert a.ndim == 3 and a.shape[2] == 4 and a.dtype == np.uint8
    assert (a[:, :, :3].max(axis=2) <= a[:, :, 3].astype(int) + 1).all()
    assert effects.heart_sprite(48) is a
    for sprite in (effects.thumb_sprite(64), effects.balloon_sprite(40, (60, 50, 235))):
        assert sprite[:, :, 3].max() > 200  # solid in the middle
        assert sprite[-1, 0, 3] < 30 and sprite[0, -1, 3] < 30  # see-through corners
    cloud = effects.cloud_sprite(200, 80)
    assert cloud[2, 100, 3] > 150 and cloud[-1, 100, 3] < 30  # solid top, open underside


def test_easing_curves():
    assert effects.spring(0) == 0
    assert abs(effects.spring(5.0) - 1) < 1e-3
    assert max(effects.spring(t / 100) for t in range(100)) > 1.05  # overshoots
    assert max(effects.ease_out_back(t / 100) for t in range(101)) > 1.0
    assert effects.ease_out_back(1.0) == pytest.approx(1.0)
    assert effects.ease_out_cubic(0) == 0 and effects.ease_out_cubic(1) == 1
    assert effects.fade(0, 3, 0.5, 0.5) == 0
    assert effects.fade(1.5, 3, 0.5, 0.5) == 1
    assert effects.fade(3, 3, 0.5, 0.5) == 0


def test_grade_fades_with_amount():
    frame = np.full((H, W, 3), 128, np.uint8)
    untouched = frame.copy()
    effects.grade(frame, 0.0, gain=(0.5, 0.5, 0.5), vignette=1.0)
    assert np.array_equal(frame, untouched)
    effects.grade(frame, 1.0, gain=(0.5, 0.5, 0.5), vignette=1.0)
    assert frame[H // 2, W // 2, 0] == 64  # centre: gain only
    assert frame[0, 0, 0] < 10  # corner: vignette too


def test_svg_path_flattening():
    polys = effects.svg_path_polygons(effects._THUMB_PATHS[0][1])
    assert polys
    pts = np.vstack(polys)
    assert pts.min() >= -0.5 and pts.max() <= 36.5  # inside the 36x36 viewBox
    square = effects.svg_path_polygons("M1 1h2v2H1z")
    assert np.allclose(square[0], [(1, 1), (3, 1), (3, 3), (1, 3)])
    assert math.isclose(effects.svg_path_polygons("m0 0l1 1")[0][-1][0], 1.0)
