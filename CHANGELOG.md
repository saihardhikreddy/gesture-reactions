# Changelog

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
