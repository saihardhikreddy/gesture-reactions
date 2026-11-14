# Changelog

## Unreleased

Fixes since 2026-11-09:

- A webcam that drops a frame no longer stops the program. Reads are retried for up to 2 seconds, and if the camera is really gone the app says so before it quits. A video file still stops when it ends.
- A gesture shown just before you fired a reaction with the 1-8 keys no longer fires again the moment that effect ends. Hold the gesture afresh to trigger it.
- Pressing the same reaction key again while its effect is playing no longer stacks another copy (five stacked fireworks dropped 720p video below 30 fps). A different reaction can still start.
- With no internet on the first run, the app now says it could not download the hand model and where to save it by hand, instead of opening the camera and then crashing with a traceback.

## 2026-11-09

Fixes and checks since the October release (from the commit history):

- Reactions now fire on slow laptops too. At about 3 fps or less, the hold check used to throw away the frames it needed, so nothing ever fired.
- Pausing with `g` and resuming no longer fires a reaction straight away for a gesture you were holding when you paused. The hold starts over.
- Settings that can't work are refused at startup with a clear message: a zero or negative `--hold`, `--cooldown`, `--fps`, `--width` or `--height`, and `--no-virtual-cam --no-preview` without `--whatsapp` (no output, and no window to quit from).
- The hand model downloads to a temporary file first, so an interrupted download no longer leaves a broken model that fails on every start.
- New tests: two-hand reactions ignore which hand is which, where they are and any extra hands. CI also lints every push with ruff.

## 2026-10-09

- All eight reactions redrawn to look like Apple's: glossy 3D hearts, balloons and thumbs, springy pop-in motion, soft shadows, glow and bloom, and a colour grade on the room for fireworks, lasers, hearts and rain.
- Thumbs up/down now sit in a frosted-glass bubble beside your face, drawn from Twemoji artwork, so they look the same on every PC (no emoji font needed).
- Confetti flips in 3D as it falls; balloons sway on strings; fireworks launch rockets and leave sparkle trails; lasers sweep through haze; rain brings a storm cloud and splashes.
- Sprites are built once at startup ("Preparing effects..."), so each effect costs only a few milliseconds per 720p frame.
- New `scripts/render_demo.py` and `scripts/bench_effects.py`; effect tests run in CI.

## 2026-10-08

- WhatsApp now goes through OBS Window Capture and **DroidCam Video**. WhatsApp calls only list Media Foundation cameras, so OBS Virtual Camera never shows up in a call.
- `--whatsapp` prints the OBS + DroidCam steps when it starts.
- New `update.bat` pulls the latest version and refreshes the packages.
- README: one-time and per-call WhatsApp steps, an Updating section and more troubleshooting.

## 2026-10-07

- Webcam fix: try Media Foundation first, then DirectShow, and skip a backend that only gives black frames.
- New `--backend` and `--list-cameras` options.
- README: step-by-step Windows setup and camera picking.
- First release: eight macOS-style reactions, OBS Virtual Camera output, `--whatsapp` output window, one-click `.bat` files, tests on Windows and Ubuntu.
