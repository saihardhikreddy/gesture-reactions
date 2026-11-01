# Contributing to Gesture Reactions

Thanks for your interest in improving Gesture Reactions!

## Setup

1. Fork and clone the repository.
2. Install Python 3.10+ and the dependencies:

   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. Check your webcam works with `python test_camera.py`.
4. Run the gesture tests with `python -m pytest test_gestures.py`.

## Adding a new gesture or effect

- Gesture detection lives in `gestures.py`; add a detector function and a test in `test_gestures.py`.
- Visual effects live in `effects.py`; keep each effect self-contained so it can be previewed on its own.
- Map the gesture to the effect in `gesture_reactions.py`.
- Record a short GIF of the new effect for the README if you can.

## Reporting bugs

Open an issue with your Windows version, camera model, the command you ran, and the full error output.
