"""Gesture Reactions: macOS-style video-call reactions for Windows.

Reads your webcam, watches for hand signs with MediaPipe, plays a full-screen
effect when it sees one, and sends the result to a virtual camera that Zoom,
Teams, Meet, Discord etc. can select as "OBS Virtual Camera".

WhatsApp calls only list Media Foundation cameras, which OBS Virtual Camera
isn't, so for WhatsApp use --whatsapp: it opens a clean output window that OBS
captures and passes on as "DroidCam Video" (see README.md).

    python gesture_reactions.py               # webcam 0 -> virtual camera + preview
    python gesture_reactions.py --camera 1    # pick a different webcam
    python gesture_reactions.py --no-virtual-cam   # preview window only
    python gesture_reactions.py --whatsapp    # clean output window for OBS + DroidCam
    python gesture_reactions.py --list-cameras     # which camera index is which

Keys in the preview window:
    1-8   fire a reaction by hand (see REACTION_KEYS)
    g     pause / resume gesture detection
    l     show / hide hand landmarks in the preview
    q/Esc quit
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.request

# Media Foundation otherwise takes several seconds to open some webcams.
os.environ.setdefault("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "0")

import cv2  # noqa: E402
import numpy as np

from effects import EffectPlayer
from gestures import ALL_REACTIONS, ReactionTrigger, classify_frame

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/latest/hand_landmarker.task"
)
HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(HERE, "hand_landmarker.task")

OUTPUT_WINDOW = "Gesture Reactions Output"
BACKENDS = {"msmf": cv2.CAP_MSMF, "dshow": cv2.CAP_DSHOW}
BLACK_MEAN = 3.0       # a frame darker than this on average counts as black
WARMUP_SECONDS = 1.5   # how long a camera gets to deliver a non-black frame
WHATSAPP_STEPS = """\
WhatsApp mode: the "Gesture Reactions Output" window is what the other person sees.
  1. Keep that window open (not minimised).
  2. In OBS: Window Capture of '[python.exe]: Gesture Reactions Output', then Ctrl+F.
  3. In OBS: Tools > DroidCam Virtual Output (on). Not 'Start Virtual Camera'.
  4. Quit WhatsApp from the tray, reopen it, and pick 'DroidCam Video' as the camera.
  5. Press 1 in the Output window to test."""
REACTION_KEYS = {ord(str(i + 1)): name for i, name in enumerate(ALL_REACTIONS)}

HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20), (0, 17),
]


def ensure_model() -> str:
    if not os.path.exists(MODEL_PATH):
        print("Downloading hand tracking model (~8 MB)...")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    return MODEL_PATH


def make_detector():
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision

    options = vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=ensure_model()),
        running_mode=vision.RunningMode.VIDEO,
        num_hands=2,
        min_hand_detection_confidence=0.6,
        min_hand_presence_confidence=0.6,
        min_tracking_confidence=0.5,
    )
    detector = vision.HandLandmarker.create_from_options(options)

    def detect(frame_bgr: np.ndarray, ts_ms: int):
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        return detector.detect_for_video(image, ts_ms).hand_landmarks

    detect.close = detector.close
    return detect


def is_black(frame, threshold: float = BLACK_MEAN) -> bool:
    """True for a missing/empty frame or one that is (almost) pure black."""
    return frame is None or frame.size == 0 or float(frame.mean()) < threshold


def backend_order(choice: str = "auto") -> list[tuple[str, int]]:
    if choice != "auto":
        return [(choice, BACKENDS[choice])]
    if sys.platform == "win32":
        # DirectShow can open a webcam that another app (e.g. OBS) holds and
        # then deliver only black frames, so try Media Foundation first.
        return [("msmf", cv2.CAP_MSMF), ("dshow", cv2.CAP_DSHOW)]
    return [("any", cv2.CAP_ANY)]


def warm_up(cap, seconds: float | None = None):
    """Read frames until one isn't black or time runs out. Returns the last frame read."""
    frame = None
    deadline = time.monotonic() + (WARMUP_SECONDS if seconds is None else seconds)
    while time.monotonic() < deadline:
        ok, f = cap.read()
        if ok and f is not None:
            frame = f
            if not is_black(frame):
                break
        else:
            time.sleep(0.05)
    return frame


def try_backend(index: int, api: int, width: int, height: int, fps: int, seconds: float | None = None):
    """Open one camera index with one backend. Returns (cap or None, last frame or None)."""
    cap = cv2.VideoCapture(index, api)
    if not cap.isOpened():
        cap.release()
        return None, None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    return cap, warm_up(cap, seconds)


def open_camera(source: str, width: int, height: int, fps: int, backend: str = "auto"):
    """Returns (cap, first frame). Numeric sources try each backend until one gives a picture."""
    if not source.isdigit():
        cap = cv2.VideoCapture(source)  # a video file, handy for testing
        if not cap.isOpened():
            sys.exit(f"Could not open video '{source}'.")
        ok, frame = cap.read()
        if not ok:
            sys.exit("Video opened but returned no frames.")
        return cap, frame

    black_backend = None
    for name, api in backend_order(backend):
        cap, frame = try_backend(int(source), api, width, height, fps)
        if cap is None:
            print(f"Camera {source} ({name}): could not open.")
            continue
        if frame is None:
            print(f"Camera {source} ({name}): opened but returned no frames.")
        elif is_black(frame):
            print(f"Camera {source} ({name}): frames are black.")
            black_backend = black_backend or (name, api)
        else:
            print(f"Camera {source}: using {name} backend.")
            return cap, frame
        cap.release()  # free the device before the next backend tries it

    if black_backend is None:
        sys.exit(f"Could not open camera {source}. Close other apps using it, "
                 "or run with --list-cameras to see which index is your webcam.")
    name, api = black_backend
    cap, frame = try_backend(int(source), api, width, height, fps, seconds=0.2)
    if cap is None or frame is None:
        sys.exit(f"Could not reopen camera {source}.")
    print(f"Camera {source}: using {name} backend, but it only gives BLACK frames.\n"
          "  - Another app may be holding the webcam: close OBS (or remove its webcam source),\n"
          "    Teams, Zoom, the Camera app and browser tabs using the camera.\n"
          "  - Check Windows Settings > Privacy & security > Camera (allow desktop apps).\n"
          "  - If that doesn't help, restart the PC.\n"
          "  - Run with --list-cameras to check the other camera numbers.")
    return cap, frame


def list_cameras(width: int, height: int, fps: int, backend: str = "auto", max_index: int = 5):
    try:  # hide OpenCV's "can't open index N" warnings, the table says it already
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)
    except AttributeError:
        pass
    print("index  backend  result")
    for index in range(max_index + 1):
        for name, api in backend_order(backend):
            cap, frame = try_backend(index, api, width, height, fps, seconds=1.0)
            if cap is None:
                result = "not found"
            elif frame is None:
                result = "opens, but no frames"
            else:
                h, w = frame.shape[:2]
                result = f"{w}x{h}, " + ("BLACK frames" if is_black(frame) else "picture OK")
            if cap is not None:
                cap.release()
            print(f"{index:>5}  {name:<7}  {result}")
    print("Use the index with 'picture OK', e.g. --camera 0 (add --backend msmf/dshow to force one).")


def draw_landmarks(frame, hands):
    h, w = frame.shape[:2]
    for lm in hands:
        pts = [(int(p.x * w), int(p.y * h)) for p in lm]
        for a, b in HAND_CONNECTIONS:
            cv2.line(frame, pts[a], pts[b], (0, 255, 0), 2, cv2.LINE_AA)
        for p in pts:
            cv2.circle(frame, p, 3, (0, 0, 255), -1, cv2.LINE_AA)


def main():
    ap = argparse.ArgumentParser(description="macOS-style gesture reactions for any video call app.")
    ap.add_argument("--camera", default="0", help="webcam index (0, 1, ...) or a video file path")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--backend", choices=["auto", "msmf", "dshow"], default="auto",
                    help="camera API; auto tries Media Foundation, then DirectShow, skipping black ones")
    ap.add_argument("--list-cameras", action="store_true",
                    help="show which camera indexes 0-5 work with each backend, then exit")
    ap.add_argument("--no-virtual-cam", action="store_true", help="only show the preview window")
    ap.add_argument("--no-preview", action="store_true", help="don't open a preview window")
    ap.add_argument("--whatsapp", action="store_true",
                    help="skip the virtual camera and show an unmirrored output window for OBS to capture")
    ap.add_argument("--hold", type=float, default=0.45, help="seconds a gesture must be held")
    ap.add_argument("--cooldown", type=float, default=3.0, help="seconds between reactions")
    args = ap.parse_args()
    if args.whatsapp:
        args.no_virtual_cam = True
    if args.list_cameras:
        list_cameras(args.width, args.height, args.fps, args.backend)
        return

    cap, frame = open_camera(args.camera, args.width, args.height, args.fps, args.backend)
    h, w = frame.shape[:2]
    print(f"Camera: {w}x{h}")
    if args.whatsapp:
        print(WHATSAPP_STEPS)

    cam = None
    if not args.no_virtual_cam:
        try:
            import pyvirtualcam

            cam = pyvirtualcam.Camera(width=w, height=h, fps=args.fps,
                                      fmt=pyvirtualcam.PixelFormat.BGR)
            print(f"Virtual camera started: {cam.device}. Pick it as the camera in your call app.")
        except Exception as e:  # noqa: BLE001
            print(f"Virtual camera unavailable ({e}).\n"
                  "Install OBS Studio (it provides 'OBS Virtual Camera'), or run with --no-virtual-cam.")
            if args.no_preview:
                sys.exit(1)

    detect = make_detector()
    trigger = ReactionTrigger(hold_seconds=args.hold, cooldown_seconds=args.cooldown)
    player = EffectPlayer()
    print("Preparing effects...")
    player.preload(w, h)  # build the 3D sprites now, not on the first reaction
    detecting, show_landmarks = True, False
    start = last = time.monotonic()
    last_ts = -1
    banner, banner_until = "", 0.0

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            now = time.monotonic()
            dt, last = now - last, now

            hands = []
            if detecting:
                ts = max(int((now - start) * 1000), last_ts + 1)  # must strictly increase
                last_ts = ts
                hands = detect(frame, ts)
                # Don't stack reactions: only look for a new one when the screen is clear.
                reaction = trigger.update(classify_frame(hands), now) if not player.busy else None
                if reaction:
                    player.trigger(reaction, w, h)
                    banner, banner_until = reaction.replace("_", " "), now + 1.5
                    print("Reaction:", reaction)

            player.render(frame, dt)

            if cam is not None:
                cam.send(frame)
            if args.whatsapp:
                # Exactly what the other person should see: no mirroring, no text.
                cv2.imshow(OUTPUT_WINDOW, frame)

            if args.no_preview:
                key = cv2.waitKey(1) & 0xFF if args.whatsapp else 255
            else:
                preview = cv2.flip(frame, 1)  # mirror, like a call app's self-view
                if show_landmarks and hands:
                    overlay = frame.copy()
                    draw_landmarks(overlay, hands)
                    preview = cv2.flip(overlay, 1)
                status = "detecting" if detecting else "paused (g)"
                if now < banner_until:
                    status += f" | {banner}"
                cv2.putText(preview, status, (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                            (255, 255, 255), 2, cv2.LINE_AA)
                cv2.imshow("Gesture Reactions (preview, mirrored)", preview)
                key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord("g"):
                detecting = not detecting
            elif key == ord("l"):
                show_landmarks = not show_landmarks
            elif key in REACTION_KEYS:
                player.trigger(REACTION_KEYS[key], w, h)

            if cam is not None:
                cam.sleep_until_next_frame()
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        detect.close()
        if cam is not None:
            cam.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
