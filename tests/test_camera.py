"""Checks the black-frame test used to skip webcams that only send black.

Needs OpenCV and numpy (pip install -r requirements.txt); skipped without them.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from gesture_reactions import (  # noqa: E402
    FramePacer, file_frame_period,
    backend_order, ensure_model, require_model, is_black, next_reaction, parse_args, read_frame, warm_up,
    window_closed,
)
from gestures import ReactionTrigger  # noqa: E402


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


class FlakyCap:
    """Fails the reads listed in drop (by read number), returns a frame otherwise."""
    def __init__(self, drop=(), stop_after=None):
        self.n, self.drop, self.stop_after = 0, set(drop), stop_after

    def read(self):
        self.n += 1
        if self.n in self.drop or (self.stop_after is not None and self.n > self.stop_after):
            return False, None
        return True, frame(100)


def test_read_frame_rides_out_dropped_frames():
    cap = FlakyCap(drop={1, 2, 3})
    assert read_frame(cap, seconds=1.0) is not None
    assert cap.n == 4


def test_read_frame_gives_up_on_a_dead_camera():
    import time
    cap = FlakyCap(stop_after=0)
    t0 = time.monotonic()
    assert read_frame(cap, seconds=0.15) is None
    assert 0.15 <= time.monotonic() - t0 < 1.0 and cap.n > 1


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


def test_model_download_is_atomic(tmp_path, monkeypatch):
    import gesture_reactions

    path = str(tmp_path / "hand_landmarker.task")

    def cut_off(url, dest):
        with open(dest, "wb") as f:
            f.write(b"half a model")
        raise OSError("connection reset")

    monkeypatch.setattr(gesture_reactions, "download", cut_off)
    with pytest.raises(OSError):
        ensure_model(path, "https://example.invalid/model")
    assert os.listdir(tmp_path) == []  # nothing half-written left behind

    def ok(url, dest):
        with open(dest, "wb") as f:
            f.write(b"model")

    monkeypatch.setattr(gesture_reactions, "download", ok)
    assert ensure_model(path, "https://example.invalid/model") == path
    assert open(path, "rb").read() == b"model"
    assert os.listdir(tmp_path) == ["hand_landmarker.task"]


def test_model_download_has_a_timeout(tmp_path, monkeypatch):
    import io

    import gesture_reactions

    seen = {}

    def fake_urlopen(url, timeout=None):
        seen["timeout"] = timeout
        return io.BytesIO(b"model bytes")

    monkeypatch.setattr(gesture_reactions.urllib.request, "urlopen", fake_urlopen)
    dest = str(tmp_path / "m.part")
    gesture_reactions.download("https://example.invalid/model", dest)
    assert seen["timeout"] == gesture_reactions.DOWNLOAD_TIMEOUT
    assert open(dest, "rb").read() == b"model bytes"


def test_stalled_model_download_explains_what_to_do(tmp_path, monkeypatch):
    import gesture_reactions

    path = str(tmp_path / "hand_landmarker.task")

    def stalled(url, timeout=None):
        raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(gesture_reactions.urllib.request, "urlopen", stalled)
    with pytest.raises(SystemExit) as exit_info:
        require_model(path, "https://example.invalid/model")
    assert "Could not download the hand tracking model" in str(exit_info.value.code)
    assert os.listdir(tmp_path) == []


def test_failed_model_download_explains_what_to_do(tmp_path, monkeypatch):
    import urllib.error

    import gesture_reactions

    path = str(tmp_path / "hand_landmarker.task")

    def offline(url, dest):
        raise urllib.error.URLError("getaddrinfo failed")

    monkeypatch.setattr(gesture_reactions, "download", offline)
    with pytest.raises(SystemExit) as exit_info:
        require_model(path, "https://example.invalid/model")
    message = str(exit_info.value.code)
    assert "Could not download the hand tracking model" in message
    assert "https://example.invalid/model" in message and path in message
    assert os.listdir(tmp_path) == []

    with open(path, "wb") as f:  # already downloaded: no network needed
        f.write(b"model")
    assert require_model(path, "https://example.invalid/model") == path


def test_args_reject_nonsense_values():
    assert parse_args(["--hold", "0.3"]).hold == 0.3
    for bad in (["--hold", "0"], ["--cooldown", "-1"], ["--fps", "0"], ["--no-virtual-cam", "--no-preview"],
                ["--cooldown", "nan"], ["--hold", "inf"], ["--hold", "-inf"]):
        with pytest.raises(SystemExit):
            parse_args(bad)
    # still fine: WhatsApp mode has its own output window
    assert parse_args(["--whatsapp", "--no-preview"]).no_virtual_cam


def test_gesture_shown_before_an_effect_needs_a_fresh_hold_after_it():
    trig = ReactionTrigger(hold_seconds=0.45, cooldown_seconds=3.0)
    # Peace held for 0.3 s (not long enough), then a reaction is fired with a key.
    assert all(next_reaction(trig, "peace", False, t / 30) is None for t in range(10))
    # The key-fired effect plays for 2.8 s while the hand stays up.
    assert all(next_reaction(trig, "peace", True, 0.33 + t / 30) is None for t in range(84))
    # Screen clear again: the first frame back must not fire on the old frames.
    fired = [next_reaction(trig, "peace", False, 3.2 + t / 30) for t in range(30)]
    assert fired[0] is None
    assert fired.count("peace") == 1
    assert fired.index("peace") >= 10


def test_nothing_fires_while_the_screen_is_busy():
    trig = ReactionTrigger(hold_seconds=0.45, cooldown_seconds=0.1)
    assert all(next_reaction(trig, "thumbs_up", True, t / 30) is None for t in range(60))


def test_window_closed_follows_the_window_visibility(monkeypatch):
    import cv2
    import gesture_reactions

    visible = {"w": 1.0}
    monkeypatch.setattr(gesture_reactions.cv2, "getWindowProperty", lambda name, prop: visible.get(name, 0.0))
    assert not window_closed("w")
    visible["w"] = 0.0  # the user clicked X
    assert window_closed("w")

    def gone(name, prop):
        raise cv2.error("NULL window")
    monkeypatch.setattr(gesture_reactions.cv2, "getWindowProperty", gone)
    assert window_closed("w")


def test_video_files_play_at_their_own_frame_rate():
    class Cap:
        def __init__(self, fps):
            self.fps = fps

        def get(self, prop):
            return self.fps

    assert file_frame_period(Cap(25.0), 30) == pytest.approx(0.04)
    for bad in (0.0, float("nan"), 1000.0):          # missing or nonsense metadata
        assert file_frame_period(Cap(bad), 30) == pytest.approx(1 / 30)

    t, slept = [0.0], []
    pacer = FramePacer(0.04, clock=lambda: t[0], sleep=lambda d: (slept.append(d), t.__setitem__(0, t[0] + d)))
    t[0] += 0.01                                     # a fast frame waits out the rest of its slot
    pacer.wait()
    assert slept == [pytest.approx(0.03)] and t[0] == pytest.approx(0.04)
    t[0] += 0.1                                      # a slow one doesn't make the next ones rush
    pacer.wait()
    assert len(slept) == 1
    t[0] += 0.01
    pacer.wait()
    assert slept[-1] == pytest.approx(0.03)
