# Rift Portal

A PySide6 remote-support suite for MBE:

- **Python Portal for Atlas v2.pyw** — the client-side remote-support portal (modern Qt UI, orb widget, glassmorphism styling). Talks to Firebase for sessions/results and posts to a Discord webhook.
- **Rift Admin Console.pyw** — the IT-side control panel. Controls portal instances, sends commands, views screenshots, and chats. It is **fully standalone** — the shared UI components (`OrbWidget`, `CircularGlassFrame`, `FrostedContainer`, `PALETTE`, Firebase helpers, etc.) are embedded directly, so it no longer requires the portal file to be present on the same machine.

## Requirements

- Python 3.9+
- Dependencies in `requirements.txt` (currently just `PySide6`)

```bash
pip install -r requirements.txt
```

## Running

Both files are `.pyw` (Windows windowed scripts). Run them with Python:

```bash
python "Python Portal for Atlas v2.pyw"
python "Rift Admin Console.pyw"
```

## Configuration

Runtime config (Firebase URL, Discord webhook, poll interval, portal version) lives near the top of `Python Portal for Atlas v2.pyw`.
