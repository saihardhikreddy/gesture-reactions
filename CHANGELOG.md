# Changelog

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
