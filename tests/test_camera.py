"""Checks the black-frame test used to skip webcams that only send black.

Needs OpenCV and numpy (pip install -r requirements.txt); skipped without them.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from gesture_reactions import backend_order, is_black, warm_up  # noqa: E402


def frame(value, h=72, w=128):
    return np.full((h, w, 3), value, dtype=np.uint8)


def test_black_and_missing_frames_are_black():
    assert is_black(frame(0))
    assert is_black(frame(2))
    assert is_black(None)
    assert is_black(np.zeros((0, 0, 3), dtype=np.uint8))


def test_dark_but_real_picture_is_not_black():
    assert not is_black(frame(10))
    img = frame(0)
    img[:20, :40] = 200  # a bright patch in an otherwise black frame
    assert not is_black(img)


def test_noise_on_black_still_counts_as_black():
    rng = np.random.default_rng(0)
    assert is_black(rng.integers(0, 4, (72, 128, 3), dtype=np.uint8))


class FakeCap:
    def __init__(self, frames):
        self.frames = list(frames)

    def read(self):
        if not self.frames:
            return False, None
        return True, self.frames.pop(0)


def test_warm_up_waits_for_first_real_frame():
    cap = FakeCap([frame(0), frame(0), frame(120), frame(0)])
    assert not is_black(warm_up(cap, seconds=1.0))
    assert len(cap.frames) == 1  # stopped as soon as the picture arrived


def test_warm_up_gives_up_on_black_camera():
    cap = FakeCap([frame(0)] * 3)
    assert is_black(warm_up(cap, seconds=0.2))
    assert warm_up(FakeCap([]), seconds=0.1) is None


def test_backend_order():
    assert [n for n, _ in backend_order("dshow")] == ["dshow"]
    assert [n for n, _ in backend_order("msmf")] == ["msmf"]
    expected = ["msmf", "dshow"] if sys.platform == "win32" else ["any"]
    assert [n for n, _ in backend_order("auto")] == expected


class FakeVideoCapture(FakeCap):
    """Stands in for cv2.VideoCapture; `feeds` maps backend id -> frames it sends."""

    feeds = {}
    opened = []

    def __init__(self, index, api):
        super().__init__(self.feeds.get(api, []))
        self.api = api
        FakeVideoCapture.opened.append(api)

    def isOpened(self):
        return self.api in self.feeds

    def set(self, prop, value):
        return True

    def release(self):
        pass


@pytest.fixture
def fake_windows_camera(monkeypatch):
    import gesture_reactions

    monkeypatch.setattr(gesture_reactions.sys, "platform", "win32")
    monkeypatch.setattr(gesture_reactions.cv2, "VideoCapture", FakeVideoCapture)
    monkeypatch.setattr(gesture_reactions, "WARMUP_SECONDS", 0.2)
    FakeVideoCapture.opened = []
    return gesture_reactions


def test_open_camera_skips_black_backend(fake_windows_camera, capsys):
    g = fake_windows_camera
    FakeVideoCapture.feeds = {g.cv2.CAP_MSMF: [frame(0)] * 50, g.cv2.CAP_DSHOW: [frame(100)] * 5}
    cap, first = g.open_camera("0", 1280, 720, 30)
    assert cap.api == g.cv2.CAP_DSHOW and not is_black(first)
    assert "using dshow" in capsys.readouterr().out


def test_open_camera_prefers_msmf(fake_windows_camera):
    g = fake_windows_camera
    FakeVideoCapture.feeds = {g.cv2.CAP_MSMF: [frame(100)] * 5, g.cv2.CAP_DSHOW: [frame(100)] * 5}
    cap, _ = g.open_camera("0", 1280, 720, 30)
    assert FakeVideoCapture.opened == [g.cv2.CAP_MSMF]


def test_open_camera_all_black_still_runs_with_warning(fake_windows_camera, capsys):
    g = fake_windows_camera
    FakeVideoCapture.feeds = {g.cv2.CAP_DSHOW: [frame(0)] * 50}  # msmf can't open
    cap, first = g.open_camera("0", 1280, 720, 30)
    assert cap.api == g.cv2.CAP_DSHOW and is_black(first)
    assert "BLACK" in capsys.readouterr().out


def test_open_camera_nothing_opens_exits(fake_windows_camera):
    FakeVideoCapture.feeds = {}
    with pytest.raises(SystemExit):
        fake_windows_camera.open_camera("0", 1280, 720, 30)
