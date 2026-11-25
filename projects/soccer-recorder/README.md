# Soccer Stream Recorder

Python/macOS application for scheduling, monitoring and recording authorized soccer broadcasts. Includes Excel/Google Sheets schedule import, Hudl/BlueFrame, FloCollege and BoxCast adapters, concurrent recording, MP4 validation, recovery parts, optional email status updates and a Tkinter interface.

## Run

Requires Python 3.11+, Tkinter, FFmpeg and ffprobe. macOS Keychain and background-worker functionality require macOS. No credentials or real team schedules are included.

```sh
python3 portable_app.py
python3 record_games.py --workbook /path/to/schedule.xlsx list
python3 -m unittest discover -s tests -q
```

The schedule needs Date, Home Team, Away Team, Kick Off Time and Livestream Link columns. Green-filled rows select games. Use the GUI to schedule manually or import a sheet. Provider access must be authorized; the app does not bypass paywalls or DRM. Opening email setup is optional.

## Architecture

- `soccer_recorder/providers.py`, `hudl.py`, `flo.py`, `boxcast.py`: provider adapters.
- `recorder.py`: recording lifecycle, finalization and validation.
- `portable.py`: job persistence and background worker.
- `xlsx_schedule.py`: schedule parsing.
- `keychain.py`, `notifications.py`, `readiness.py`: credentials, notifications and macOS readiness.
- `tests/`: isolated fixtures for parsing, recording, provider behavior and UI configuration.

This is a source distribution; the original packaged app, recordings and operational schedules are intentionally excluded. Tests use a synthetic workbook.
