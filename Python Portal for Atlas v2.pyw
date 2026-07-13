"""
Python Portal for Atlas v2
============================
A modern PySide6 remote-support portal.

Same powers as the original tkinter portal, rebuilt with:
  - hardware-accelerated Qt rendering
  - smooth 60 fps animations
  - crisp high-DPI text
  - modern glassmorphism-inspired UI

The portal lives in the folder the user chose. When done, the user can
close it; a second close permanently deletes the portal file.
"""

import base64
import ctypes
import io
import json
import math
import os
import random
import platform
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
import zlib
import struct
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, QPointF, QSize,
    Property, Signal, QThread, QObject, QElapsedTimer, QByteArray, QBuffer, QIODevice
)
from PySide6.QtGui import (
    QPainter, QColor, QRadialGradient, QLinearGradient, QFont,
    QFontDatabase, QFontMetrics, QCursor, QIcon, QPixmap, QPen,
    QBrush, QRegion, QPainterPath
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QTextEdit, QLineEdit, QFrame, QSizePolicy, QGraphicsDropShadowEffect,
    QDialog
)

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
PORTAL_VERSION = "2.1.0"
# Set to True for grainy pointillist texture, False for smooth gradients.
# Backup of the smooth version: "Python Portal for Atlas v2 BACKUP.pyw"
GRAINY_RENDER = True
WEBHOOK_URL = (
    "https://discord.com/api/webhooks/1525590266634043392/"
    "Ew5A0Pr6w9fwtgMQP1IsYY4KOiieGW9rSGLlEl8dQSVI5FWjeQDZFCLgo973Ie0qD1no"
)
FIREBASE_URL = "https://mbe-portal-default-rtdb.firebaseio.com"
POLL_INTERVAL = 1.5
CHAT_POLL_INTERVAL = 1
REMINDER_INTERVAL = 25 * 60
CREATE_NO_WINDOW = (
    subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
)

SESSION_ID = f"portal-{uuid.uuid4().hex[:12]}"

_active_webhook_url = WEBHOOK_URL

# ------------------------------------------------------------------
# Theme
# ------------------------------------------------------------------
PALETTE = {
    "bg": "#0b0b14",
    "panel": "#12121f",
    "panel_light": "#1c1c2e",
    "text": "#f0f0f5",
    "muted": "#8b8b9a",
    "accent": "#9b59b6",
    "accent_bright": "#c084fc",
    "active": "#00d4ff",
    "success": "#22c55e",
    "error": "#ef4444",
    "warning": "#f59e0b",
    "chat_bg": "#0f0f1a",
    "bubble_atlas": "#1a1a2e",
    "bubble_user": "#2e1a47",
    "bubble_border": "#4a2a6e",
    "input_bg": "#16162b",
}


def _get_user():
    try:
        return os.getlogin()
    except Exception:
        return "unknown"


# ------------------------------------------------------------------
# Backend: Discord + Firebase
# ------------------------------------------------------------------
def _set_webhook_url(url):
    global _active_webhook_url
    _active_webhook_url = url or WEBHOOK_URL


def _post_to_discord(content):
    try:
        payload = json.dumps({"content": content[:1900]}).encode("utf-8")
        req = urllib.request.Request(
            _active_webhook_url, data=payload,
            headers={"Content-Type": "application/json",
                     "User-Agent": f"PythonPortal/{PORTAL_VERSION}"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            ok = resp.status in (200, 204)
            _portal_log(f"_post_to_discord: status={resp.status}, ok={ok}")
            return ok
    except Exception as e:
        _portal_log(f"_post_to_discord error: {e}")
        return False


def _post_file_to_discord(content, file_path):
    try:
        with open(file_path, "rb") as f:
            file_data = f.read()
        boundary = f"----WebKitFormBoundary{os.urandom(8).hex()}"
        payload_json = json.dumps({"content": content[:1900]})
        from mimetypes import guess_type
        content_type = guess_type(file_path)[0] or "application/octet-stream"

        body = b""
        body += f"--{boundary}\r\n".encode()
        body += b'Content-Disposition: form-data; name="payload_json"\r\n'
        body += b"Content-Type: application/json\r\n\r\n"
        body += payload_json.encode() + b"\r\n"

        body += f"--{boundary}\r\n".encode()
        body += (f'Content-Disposition: form-data; name="files[0]"; '
                 f'filename="{Path(file_path).name}"\r\n').encode()
        body += f"Content-Type: {content_type}\r\n\r\n".encode()
        body += file_data + b"\r\n"
        body += f"--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            _active_webhook_url, data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                     "User-Agent": f"PythonPortal/{PORTAL_VERSION}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status in (200, 204)
    except Exception:
        return _post_to_discord(content + "\n\n[File attachment failed]")


def _firebase_put(path, data):
    try:
        url = f"{FIREBASE_URL}/{path}.json"
        payload = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=payload, method="PUT",
                                      headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status in (200, 204)
    except Exception:
        return False


def _firebase_get(path):
    try:
        url = f"{FIREBASE_URL}/{path}.json"
        req = urllib.request.Request(url,
                                      headers={"User-Agent": f"PythonPortal/{PORTAL_VERSION}"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def _firebase_delete(path):
    try:
        url = f"{FIREBASE_URL}/{path}.json"
        req = urllib.request.Request(url, method="DELETE")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status in (200, 204)
    except Exception:
        return False


def _register_session(user, host, folder):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    data = {
        "id": SESSION_ID,
        "name": f"{user}@{host}",
        "user": user,
        "host": host,
        "folder": folder,
        "status": "open",
        "opened_at": now,
        "last_seen": now,
        "portal_connected": False,
        "card_state": "waiting",
        "orb_state": "idle",
        "version": PORTAL_VERSION,
    }
    ok = _firebase_put(f"sessions/{SESSION_ID}", data)
    _portal_log(f"_register_session: sessions/{SESSION_ID} ok={ok}")
    return ok


def _update_last_seen():
    try:
        _firebase_put(f"sessions/{SESSION_ID}/last_seen", datetime.now().strftime("%Y-%m-%d %H:%M"))
    except Exception as e:
        _portal_log(f"_update_last_seen error: {e}")


def _mark_portal_opened():
    try:
        _firebase_put(f"sessions/{SESSION_ID}/portal_opened", {
            "opened": True,
            "opened_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
        _firebase_put(f"sessions/{SESSION_ID}/portal_connected", True)
        _firebase_put(f"sessions/{SESSION_ID}/status", "open")
        _firebase_put(f"sessions/{SESSION_ID}/card_state", "connected")
    except Exception as e:
        _portal_log(f"_mark_portal_opened error: {e}")


def _write_command_result(cmd_id, cmd_type, ok, result):
    try:
        data = {
            "id": cmd_id,
            "type": cmd_type,
            "ok": ok,
            "result": result,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        _firebase_put(f"sessions/{SESSION_ID}/results/{cmd_id}", data)
    except Exception as e:
        _portal_log(f"_write_command_result error: {e}")


def _wait_for_webhook(timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = _firebase_get(f"sessions/{SESSION_ID}")
        _portal_log(f"_wait_for_webhook poll: data={data}")
        if data and data.get("webhook_url"):
            _set_webhook_url(data["webhook_url"])
            _portal_log(f"_wait_for_webhook: assigned webhook {data['webhook_url']}")
            return True
        time.sleep(1)
    _portal_log("_wait_for_webhook: timed out, using default webhook")
    return False


def _mark_session_closed():
    _firebase_put(f"sessions/{SESSION_ID}/status", "closed")


def _portal_log(msg):
    """Write a debug line to the portal's log file."""
    try:
        log_path = Path(__file__).resolve().parent / ".portal_v2_debug.log"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    except Exception:
        pass


def _clear_chat_and_commands():
    try:
        _firebase_put(f"sessions/{SESSION_ID}/chat", {})
        _firebase_put(f"sessions/{SESSION_ID}/commands", {})
    except Exception:
        pass


# ------------------------------------------------------------------
# Backend: command execution helpers
# ------------------------------------------------------------------
def _scan_directory(path):
    lines = []
    p = Path(path)
    if not p.exists():
        return f"Path does not exist: {path}"

    lines.append(f"Scanned: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("")
    lines.append(f"Contents of: {p}")
    if p.parent.exists():
        lines.append(f"Parent: {p.parent}")
    lines.append("")

    subdirs = sorted([d for d in p.iterdir() if d.is_dir()])
    if subdirs:
        lines.append("Subfolders:")
        for sub in subdirs[:20]:
            lines.append(f"  {sub.name}/")
        if len(subdirs) > 20:
            lines.append(f"  ... and {len(subdirs) - 20} more")
        lines.append("")

    lines.append("Files in this folder:")
    files = sorted([f for f in p.iterdir() if f.is_file()])
    if not files:
        lines.append("  (no files)")
    for f in files:
        try:
            size = f.stat().st_size
            if size > 1024 * 1024:
                size_str = f"({size / 1024 / 1024:.1f} MB)"
            elif size > 1024:
                size_str = f"({size / 1024:.0f} KB)"
            else:
                size_str = f"({size} B)"
        except Exception:
            size_str = ""
        lines.append(f"  {f.name} {size_str}")

    lines.append("")
    lines.append("One level deeper:")
    for sub in subdirs[:10]:
        subfiles = sorted([f.name for f in sub.iterdir() if f.is_file()][:5])
        if subfiles:
            lines.append(f"  {sub.name}/ -> {', '.join(subfiles)}")
        else:
            lines.append(f"  {sub.name}/ -> (empty)")
    if len(subdirs) > 10:
        lines.append(f"  ... and {len(subdirs) - 10} more subfolders")

    if p.parent.exists():
        siblings = sorted([d for d in p.parent.iterdir() if d.is_dir()])
        if siblings:
            lines.append("")
            lines.append("Quick options (nearby folders):")
            for sib in siblings[:15]:
                lines.append(f"  {sib.resolve()}/")
            if len(siblings) > 15:
                lines.append(f"  ... and {len(siblings) - 15} more")

    return "\n".join(lines)


def _check_packages():
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format=columns"],
            capture_output=True, text=True, timeout=30,
            creationflags=CREATE_NO_WINDOW)
        return proc.stdout or proc.stderr
    except Exception as e:
        return f"Error: {e}"


def _read_file(path, max_bytes=50000):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = f.read(max_bytes)
        if len(data) == max_bytes:
            data += "\n... [truncated]"
        return data
    except Exception as e:
        return f"Error reading file: {e}"


def _backup_dir():
    return Path(__file__).parent / ".portal_backups"


def _backup_log_file():
    return _backup_dir() / "undo_log.json"


def _backup_file(path, operation, extra=None):
    p = Path(path)
    if not p.exists() or not p.is_file():
        return None
    try:
        backup_dir = _backup_dir()
        backup_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_name = f"{timestamp}_{p.name}"
        backup_path = backup_dir / backup_name
        shutil.copy2(p, backup_path)
        entry = {
            "original_path": str(p.resolve()),
            "backup_path": str(backup_path),
            "operation": operation,
            "timestamp": datetime.now().isoformat(),
        }
        if extra:
            entry.update(extra)
        logs = []
        log_file = _backup_log_file()
        if log_file.exists():
            try:
                logs = json.load(open(log_file, "r", encoding="utf-8"))
            except Exception:
                pass
        logs.append(entry)
        json.dump(logs, open(log_file, "w", encoding="utf-8"), indent=2)
        return entry
    except Exception:
        return None


def _undo_last():
    log_file = _backup_log_file()
    if not log_file.exists():
        return False, "No undo history available."
    try:
        logs = json.load(open(log_file, "r", encoding="utf-8"))
    except Exception:
        return False, "Could not read undo history."
    if not logs:
        return False, "No undo history available."

    entry = logs.pop()
    operation = entry.get("operation", "")
    original_path = entry.get("original_path", "")
    backup_path = entry.get("backup_path", "")

    try:
        if operation in ("delete", "replace", "add"):
            if not backup_path or not Path(backup_path).exists():
                return False, f"Backup missing for {operation} on {original_path}"
            Path(original_path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_path, original_path)
            json.dump(logs, open(log_file, "w", encoding="utf-8"), indent=2)
            return True, f"Undo {operation}: restored {original_path}"
        elif operation == "rename":
            old_path = entry.get("old_path", "")
            new_path = entry.get("new_path", "")
            if not old_path or not new_path:
                return False, "Rename undo missing path info"
            if not Path(backup_path).exists():
                return False, f"Backup missing for rename: {old_path}"
            if Path(new_path).exists():
                Path(new_path).unlink()
            Path(old_path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_path, old_path)
            json.dump(logs, open(log_file, "w", encoding="utf-8"), indent=2)
            return True, f"Undo rename: restored {old_path}"
        else:
            return False, f"Unknown operation: {operation}"
    except Exception as e:
        return False, f"Undo failed: {e}"


def _download_file(url, dest_path):
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": f"PythonPortal/{PORTAL_VERSION}"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as f:
            f.write(data)
        return True, f"Downloaded {len(data)} bytes to {dest_path}"
    except Exception as e:
        return False, f"Download failed: {e}"


def _write_png_rgb(output_path, rgb_bytes, width, height):
    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)
        raw.extend(rgb_bytes[y * stride:(y + 1) * stride])
    compressed = zlib.compress(bytes(raw))

    def _chunk(tag, data):
        chunk = struct.pack(">I", len(data)) + tag + data
        crc = zlib.crc32(chunk[4:]) & 0xffffffff
        return chunk + struct.pack(">I", crc)

    with open(output_path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
        f.write(_chunk(b"IDAT", compressed))
        f.write(_chunk(b"IEND", b""))


def _speak_text(text):
    try:
        if platform.system() == "Windows":
            try:
                import win32com.client as com
                voice = com.Dispatch("SAPI.SpVoice")
                voice.Speak(text)
                return
            except Exception:
                pass
            try:
                import pyttsx3
                engine = pyttsx3.init()
                engine.say(text)
                engine.runAndWait()
                return
            except Exception:
                pass
        elif platform.system() == "Darwin":
            subprocess.run(["say", text], check=False, timeout=30)
            return
        else:
            subprocess.run(["espeak", text], check=False, timeout=30)
            return
    except Exception:
        pass


def _play_message_sound():
    """Play the native system alert sound for incoming chat messages."""
    try:
        if platform.system() == "Windows":
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
                return
            except Exception:
                pass
        elif platform.system() == "Darwin":
            subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"], check=False, timeout=5)
            return
        # Fallback to Qt's built-in beep
        from PySide6.QtWidgets import QApplication
        QApplication.beep()
    except Exception:
        pass


# ------------------------------------------------------------------
# UI: frosted glass container
# ------------------------------------------------------------------
class FrostedContainer(QFrame):
    """A rounded, semi-transparent frosted-glass frame."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        radius = 22

        # Frosted glass fill: slightly darker and less transparent
        fill_grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        fill_grad.setColorAt(0, QColor(22, 21, 38, 245))
        fill_grad.setColorAt(0.5, QColor(16, 15, 30, 250))
        fill_grad.setColorAt(1, QColor(10, 9, 22, 252))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(fill_grad))
        painter.drawRoundedRect(rect, radius, radius)

        # Soft top highlight (glass sheen)
        sheen_grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.top() + rect.height() * 0.35)
        sheen_grad.setColorAt(0, QColor(255, 255, 255, 40))
        sheen_grad.setColorAt(0.6, QColor(255, 255, 255, 10))
        sheen_grad.setColorAt(1, QColor(255, 255, 255, 0))
        sheen_rect = rect.adjusted(2, 2, -2, 0)
        sheen_rect.setHeight(int(rect.height() * 0.35))
        painter.setBrush(QBrush(sheen_grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(sheen_rect, radius, radius)

        # Glass-like gradient border: brighter at the top, moodier at the bottom
        border_grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        border_grad.setColorAt(0, QColor(200, 160, 240, 100))
        border_grad.setColorAt(0.5, QColor(154, 89, 182, 60))
        border_grad.setColorAt(1, QColor(110, 60, 170, 45))
        pen = QPen(QBrush(border_grad), 1.5)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius, radius)

        painter.end()


# ------------------------------------------------------------------
# Dark matter particle system
# ------------------------------------------------------------------
# Violet color palette for the particle field — kept dark, no bright star vibes
_DM_COLORS = [
    (4, 2, 10),       # #04020A - darkest (most common)
    (18, 10, 34),     # #120A22 - dark
    (38, 20, 62),     # #26143E - mid-dark
    (72, 40, 105),    # #482869 - mid
    (110, 70, 155),   # #6E469B - lighter accent (~5% only)
]
# State color overrides (r, g, b) — particles tint toward these
_STATE_COLORS = {
    "awaiting":        None,              # pure black — no connection yet
    "portal_opening":  None,              # pink+blue needle growing to idle
    "portal_closing":  None,              # violet shrinking back to dormant needle
    "idle":            None,              # violet palette
    "command":         (40, 120, 220),    # blend of blues — deep sea blue
    "terminal":        (140, 60, 220),    # purple — terminal command
    "screenshot":      (220, 200, 40),    # yellow — screenshot in progress
    "test_pulse":      (220, 30, 40),     # intense red
    "paused":          (255, 180, 50),    # amber/yellow light
    "feedme":          (40, 220, 100),    # green
    "vision":          (220, 80, 180),    # purple-pink — Vision eye
}


def _flow_angle(x, y, t):
    """Pseudo-noise flow field angle using overlapping sine waves.
    This produces organic, non-repeating flow patterns similar to Perlin noise
    but much faster in pure Python."""
    n = (
        math.sin(x * 0.012 + t * 0.20) +
        math.cos(y * 0.010 + t * 0.15) +
        math.sin((x + y) * 0.007 + t * 0.10) +
        math.cos((x - y) * 0.009 + t * 0.08)
    )
    return n * math.pi


def _pick_color(brightness, tint=None):
    """Pick a color from the palette based on brightness (0-1).
    If tint is (r,g,b), blend toward it."""
    if brightness > 0.95:
        idx = 4  # bright lavender (~5%)
    elif brightness > 0.75:
        idx = 3
    elif brightness > 0.50:
        idx = 2
    elif brightness > 0.25:
        idx = 1
    else:
        idx = 0
    r, g, b = _DM_COLORS[idx]
    if tint:
        blend = 0.4
        r = int(r + (tint[0] - r) * blend)
        g = int(g + (tint[1] - g) * blend)
        b = int(b + (tint[2] - b) * blend)
    return r, g, b


class DarkMatterParticle:
    """A tiny near-black particle drifting inside the dimensional tear."""
    __slots__ = ("x", "y", "vx", "vy", "size", "base_alpha", "brightness",
                 "layer", "life", "max_life", "angle", "radius_frac",
                 "noise_offset")

    def __init__(self, cx, cy, base_r, layer):
        self.layer = layer
        self.angle = random.random() * math.pi * 2
        self.radius_frac = random.random() ** 0.5 * 0.5
        self.x = cx + math.cos(self.angle) * base_r * self.radius_frac
        self.y = cy + math.sin(self.angle) * base_r * self.radius_frac
        self.vx = 0.0
        self.vy = 0.0
        self.size = (0.4 + random.random() * 0.6) if layer == 0 else                     (0.6 + random.random() * 0.8) if layer == 1 else                     (0.8 + random.random() * 1.0)
        self.base_alpha = (3 + random.random() * 5) if layer == 0 else                           (5 + random.random() * 8) if layer == 1 else                           (8 + random.random() * 10)
        self.brightness = random.random()
        self.max_life = 4.0 + random.random() * 10.0
        self.life = random.random() * self.max_life
        self.noise_offset = random.random() * 100

    def update(self, dt, cx, cy, base_r, phase, speed_mul=1.0, tint=None):
        """Independent wandering drift — each particle moves on its own."""
        dx = self.x - cx
        dy = self.y - cy
        dist = math.sqrt(dx * dx + dy * dy) + 0.1
        frac = dist / base_r

        # Independent flow-field wander (no shared orbital direction)
        angle = _flow_angle(self.x * 0.3, self.y * 0.3, phase * 0.3 + self.noise_offset)
        flow_strength = (0.8 + self.layer * 0.3) * speed_mul
        self.vx += math.cos(angle) * flow_strength * dt
        self.vy += math.sin(angle) * flow_strength * dt

        # Very gentle inward pull if drifting too far
        if frac > 0.55:
            pull = (frac - 0.55) * 6.0
            self.vx -= (dx / dist) * pull * dt
            self.vy -= (dy / dist) * pull * dt

        # Damping
        self.vx *= 0.992
        self.vy *= 0.992

        # Move slowly
        self.x += self.vx * dt * 20
        self.y += self.vy * dt * 20

        # Life cycle
        self.life += dt
        if self.life > self.max_life:
            self._respawn(cx, cy, base_r)

        # Clamp to center area
        dist_from_center = math.sqrt((self.x - cx) ** 2 + (self.y - cy) ** 2)
        if dist_from_center > base_r * 0.6:
            self._respawn(cx, cy, base_r)

    def _respawn(self, cx, cy, base_r):
        self.angle = random.random() * math.pi * 2
        self.radius_frac = random.random() ** 0.5 * 0.45
        self.x = cx + math.cos(self.angle) * base_r * self.radius_frac
        self.y = cy + math.sin(self.angle) * base_r * self.radius_frac
        self.vx = 0.0
        self.vy = 0.0
        self.life = 0.0
        self.max_life = 4.0 + random.random() * 10.0
        self.brightness = random.random()

    @property
    def alpha(self):
        t = self.life / self.max_life
        if t < 0.2:
            return int(self.base_alpha * (t / 0.2))
        elif t > 0.8:
            return int(self.base_alpha * ((1.0 - t) / 0.2))
        return int(self.base_alpha)


# ------------------------------------------------------------------
# UI: fluid dark-matter container (atmospheric, not a disc)
# ------------------------------------------------------------------
class CircularGlassFrame(QFrame):
    """Atmospheric dark-matter backdrop — fluid, breathing, never a perfect circle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self._border_alpha = 35
        self._phase = random.random() * math.pi * 2
        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        self._last_ms = 0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def set_border_alpha(self, alpha):
        self._border_alpha = alpha
        self.update()

    def _blob_path(self, cx, cy, base_r, phase, detail=72, seed=0.0, intensity=0.10):
        """Generate an organic blob path. Uses its own phase for independent motion."""
        path = QPainterPath()
        pts = []
        for i in range(detail):
            angle = 2 * math.pi * i / detail
            wave = (
                math.sin(angle * 2 + phase + seed) * 0.45 +
                math.cos(angle * 3 - phase * 1.1 + seed) * 0.30 +
                math.sin(angle * 5 + phase * 0.6 + seed) * 0.22 +
                math.cos(angle * 8 - phase * 0.4 + seed * 1.7) * 0.14 +
                math.sin(angle * 13 + phase * 0.25 + seed) * 0.09 +
                math.cos(angle * 21 + phase * 0.15 + seed) * 0.05
            )
            r = base_r * (1 + wave * intensity)
            x = cx + math.cos(angle) * r
            y = cy + math.sin(angle) * r
            pts.append((x, y))

        mid = lambda a, b: ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        path.moveTo(*mid(pts[-1], pts[0]))
        for i in range(detail):
            p1 = pts[i]
            p2 = pts[(i + 1) % detail]
            m = mid(p1, p2)
            path.quadTo(*p1, *m)
        return path

    def _tick(self):
        now = self._elapsed.elapsed()
        dt = min((now - self._last_ms) / 1000.0, 0.1)
        self._last_ms = now
        # Slow breathing
        self._phase += dt * 0.35
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        side = min(w, h)
        cx, cy = w / 2, h / 2
        radius = side / 2 - 4

        # Multiple fluid dark layers — each breathes independently
        # Outermost is the largest, innermost is darkest
        for i in range(4):
            frac = 0.96 - i * 0.04
            r = radius * frac
            # Each layer rotates in alternating direction for opposing motion
            layer_phase = self._phase * (0.8 if i % 2 == 0 else -0.6) + i * 1.3
            intensity = 0.08 + i * 0.02
            blob = self._blob_path(cx, cy, r, layer_phase, intensity=intensity)

            # Very dark purple-black fill, getting darker toward center
            darkness = 6 + i * 2
            grad = QRadialGradient(cx, cy, r)
            grad.setColorAt(0, QColor(darkness, darkness - 2, darkness + 4, 225 - i * 20))
            grad.setColorAt(0.7, QColor(darkness - 2, darkness - 3, darkness, 235 - i * 15))
            grad.setColorAt(1, QColor(darkness - 4, darkness - 4, darkness - 2, 0))

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(grad))
            painter.drawPath(blob)

        painter.end()


# ------------------------------------------------------------------
# UI: dimensional tear orb widget
# ------------------------------------------------------------------
class OrbWidget(QWidget):
    """A dimensional tear in reality — dark center, fluid edge energy, state-driven.

    Rendering order:
      1. Black center
      2. Drifting dark particles
      3. Outer dark fluid field (breathing, morphing, never circular)
      4. Thin magical energy edge (multiple translucent wispy layers)
      5. Optional glow (state dependent)

    States:
      idle         - almost asleep, very slow, very dark
      command      - turquoise edge energy
      test_pulse   - red breathing heartbeat glow at edge
      paused       - solid amber eclipse, barely moving
      feedme       - portal waking up, faster, more layers, brighter
    """

    state_changed = Signal(str)  # emitted when the orb state changes
    clicked = Signal()            # emitted when the orb is clicked (Vision mode)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(260, 260)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

        # Three independent phases for layered motion
        self._field_phase = random.random() * math.pi * 2   # outer dark field (CCW)
        self._edge_phase = random.random() * math.pi * 2     # magical edge (CW)
        self._inner_phase = random.random() * math.pi * 2     # inner rift rotation
        self._state = "awaiting"  # starts with no connection

        # Smoothly interpolated state values
        self._scale = 1.0
        self._target_scale = 1.0
        self._speed_mul = 1.0
        self._target_speed_mul = 1.0
        self._glow = 0.0
        self._target_glow = 0.0
        self._edge_layers = 3
        self._target_edge_layers = 3
        self._edge_intensity = 0.08
        self._target_edge_intensity = 0.08
        self._tint = None
        self._target_tint = None
        self._tint_blend = 0.0
        self._target_tint_blend = 0.0

        self._pulse_phase = 0.0
        self._breath_phase = 0.0
        self._morph_phase = 0.0  # slow shape evolution — the portal breathes and shifts
        self._pause_breath = 1.0  # 0..1, size modulation for paused state
        self._pulse_breath = 1.0  # 0..1, size modulation for pulse state
        self._crack_morph = 0.0
        self._target_crack_morph = 0.0
        self._vortex_strength = 0.0
        self._target_vortex_strength = 0.0
        self._alert_flash = 0.0
        self._portal_opening_progress = 0.0  # 0..1, grows during portal_opening

        # Vision mode eye state
        self._vision_open = 1.0          # 0..1, eyelid openness (1 = open)
        self._vision_blink = 0.0         # blink timer

        # Mouse interaction state — all smoothly interpolated
        self._mouse_x = 0.0       # actual mouse position
        self._mouse_y = 0.0
        self._mouse_active = False
        self._proximity = 0.0      # 0..1, how close the mouse is (smoothed)
        self._target_proximity = 0.0
        self._lean_x = 0.0         # portal leans toward mouse (smoothed)
        self._target_lean_x = 0.0
        self._lean_y = 0.0
        self._target_lean_y = 0.0
        # Click ripples — list of {x, y, age, max_age}
        self._ripples = []
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        self._particles = []
        self._initialized = False

        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        self._last_ms = 0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def _lerp(self, a, b, t):
        return a + (b - a) * t

    def mouseMoveEvent(self, event):
        pos = event.position()
        self._mouse_x = pos.x()
        self._mouse_y = pos.y()
        self._mouse_active = True
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        dx = self._mouse_x - cx
        dy = self._mouse_y - cy
        dist = math.sqrt(dx * dx + dy * dy)
        side = min(w, h)
        max_dist = side * 0.7
        # Proximity: 1 when mouse is at center, 0 when far away
        self._target_proximity = max(0, 1.0 - dist / max_dist)
        # Lean: subtle shift toward mouse (normalized direction, scaled by proximity)
        if dist > 0.1:
            self._target_lean_x = (dx / dist) * self._target_proximity * 0.06
            self._target_lean_y = (dy / dist) * self._target_proximity * 0.06

    def leaveEvent(self, event):
        self._mouse_active = False
        self._target_proximity = 0.0
        self._target_lean_x = 0.0
        self._target_lean_y = 0.0

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            self._ripples.append({
                "x": pos.x(),
                "y": pos.y(),
                "age": 0.0,
                "max_age": 2.5,
            })
            # In Vision mode, clicking the eye captures a screenshot.
            if self._state == "vision":
                self.clicked.emit()

    def _init_particles(self):
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        side = min(w, h)
        base_r = side * 0.35

        # Sparse particles for the dark center
        counts = [60, 35, 15]
        self._particles = []
        for layer, count in enumerate(counts):
            for _ in range(count):
                p = DarkMatterParticle(cx, cy, base_r, layer=layer)
                p.size *= 0.5
                p.base_alpha = int(p.base_alpha * 0.3)
                self._particles.append(p)
        self._initialized = True

    def _tick(self):
        now = self._elapsed.elapsed()
        dt = min((now - self._last_ms) / 1000.0, 0.1)
        self._last_ms = now

        # Breathing — very slow
        self._breath_phase += dt * 0.4
        self._pulse_phase += dt * 1.5
        # Morph — very slow shape evolution, makes the portal feel alive without spinning fast
        # Faster in active states, slower in idle
        morph_rate = 0.12 if self._state == "idle" else 0.25
        self._morph_phase += dt * morph_rate
        breath = 0.5 + 0.5 * math.sin(self._breath_phase)  # 0..1

        # Smooth state transitions — faster so return-to-idle doesn't drag
        ease = 1.0 - math.exp(-dt * 6.0)

        # Paused: visible size breathing — shrinks to near needle-point and back
        # Proximity quickens the breath slightly
        if self._state == "paused":
            pause_rate = 0.7 * (1.0 + self._proximity * 0.4)
            # 0.08 at minimum (needle point), 1.0 at maximum (full pause size)
            self._pause_breath = 0.08 + 0.92 * (0.5 + 0.5 * math.sin(self._breath_phase * pause_rate))
        else:
            # Fast recovery when leaving paused — don't mess up other modes
            fast_ease = 1.0 - math.exp(-dt * 15.0)
            self._pause_breath = self._lerp(self._pause_breath, 1.0, fast_ease)

        # Pulse: size pulses between ~0.65 and ~1.15
        if self._state == "test_pulse":
            pulse_rate = 2.5 * (1.0 + self._proximity * 0.3)
            self._pulse_breath = 0.65 + 0.50 * (0.5 + 0.5 * math.sin(self._pulse_phase * pulse_rate))
        else:
            fast_ease = 1.0 - math.exp(-dt * 15.0)
            self._pulse_breath = self._lerp(self._pulse_breath, 1.0, fast_ease)

        # Vision mode: occasional blink and smooth eyelid movement
        if self._state == "vision":
            self._vision_blink += dt
            # Blink every ~2.5 to 4.5 seconds
            if self._vision_blink > 3.5 + math.sin(self._breath_phase * 0.5) * 0.5:
                self._vision_blink = 0.0
            # Eyelid opens quickly, closes quickly for the blink, then reopens
            if self._vision_blink < 0.15:
                target_open = 1.0
            elif self._vision_blink < 0.35:
                target_open = 0.15
            else:
                target_open = 1.0
            self._vision_open = self._lerp(self._vision_open, target_open, 1.0 - math.exp(-dt * 20.0))
        else:
            self._vision_open = self._lerp(self._vision_open, 1.0, 1.0 - math.exp(-dt * 10.0))

        # Crack morph: inert (always targets 0, kept for compatibility)
        self._crack_morph = self._lerp(self._crack_morph, self._target_crack_morph, ease)

        # Vortex strength: builds up in feedme, decays otherwise
        self._vortex_strength = self._lerp(self._vortex_strength, self._target_vortex_strength, ease)

        # Alert flash decays — fast, split-second flash that overpowers other glows
        if self._alert_flash > 0:
            self._alert_flash = max(0, self._alert_flash - dt * 8.0)

        # Portal opening/closing: progress grows/shrinks, then transitions
        if self._state == "portal_opening":
            self._portal_opening_progress = min(1.0, self._portal_opening_progress + dt * 0.4)
            if self._portal_opening_progress >= 1.0:
                self.set_state("idle")
        elif self._state == "portal_closing":
            self._portal_opening_progress = max(0.0, self._portal_opening_progress - dt * 0.4)
            if self._portal_opening_progress <= 0.0:
                self.set_state("awaiting")
        else:
            # Reset progress when not in portal_opening/closing (so it can replay)
            if self._state != "awaiting" and self._portal_opening_progress > 0:
                self._portal_opening_progress = max(0, self._portal_opening_progress - dt * 2.0)
            elif self._state == "awaiting":
                self._portal_opening_progress = 0.0

        self._scale = self._lerp(self._scale, self._target_scale, ease)
        self._speed_mul = self._lerp(self._speed_mul, self._target_speed_mul, ease)
        self._glow = self._lerp(self._glow, self._target_glow, ease)
        self._edge_layers = self._lerp(self._edge_layers, self._target_edge_layers, ease)
        self._edge_intensity = self._lerp(self._edge_intensity, self._target_edge_intensity, ease)
        self._tint_blend = self._lerp(self._tint_blend, self._target_tint_blend, ease)
        # Tint color: set immediately (no interpolation needed — the blend handles the fade)
        self._tint = self._target_tint

        # Mouse interaction — slower ease so it feels organic, not snappy
        mouse_ease = 1.0 - math.exp(-dt * 2.0)
        self._proximity = self._lerp(self._proximity, self._target_proximity, mouse_ease)
        self._lean_x = self._lerp(self._lean_x, self._target_lean_x, mouse_ease)
        self._lean_y = self._lerp(self._lean_y, self._target_lean_y, mouse_ease)

        # Age and remove ripples
        for r in self._ripples:
            r["age"] += dt
        self._ripples = [r for r in self._ripples if r["age"] < r["max_age"]]

        # Opposing motion: field goes CCW (negative), edge goes CW (positive)
        prox_boost = 1.0 + self._proximity * 0.6
        if self._state == "feedme":
            field_speed = 0.30 * self._speed_mul * (0.6 + breath * 0.4) * prox_boost
            edge_speed = 0.60 * self._speed_mul * (0.6 + breath * 0.4) * prox_boost
        elif self._state == "test_pulse":
            field_speed = 0.20 * self._speed_mul * prox_boost
            edge_speed = 0.25 * self._speed_mul * prox_boost
        else:
            field_speed = 0.40 * self._speed_mul * (0.6 + breath * 0.4) * prox_boost
            edge_speed = 0.52 * self._speed_mul * (0.6 + breath * 0.4) * prox_boost
        self._field_phase -= dt * field_speed  # counter-clockwise
        self._edge_phase += dt * edge_speed    # clockwise
        # Inner rift: clear but controlled rotation at the opening
        inner_speed = 0.45 * self._speed_mul * (0.6 + breath * 0.4) * prox_boost
        self._inner_phase += dt * inner_speed

        if self._initialized:
            w, h = self.width(), self.height()
            cx, cy = w / 2, h / 2
            base_r = min(w, h) * 0.35 * self._scale
            for p in self._particles:
                p.update(dt, cx, cy, base_r, self._field_phase, speed_mul=self._speed_mul)

        self.update()

    def set_state(self, state):
        self._state = state
        sc = _STATE_COLORS.get(state)
        # Default: no crack, no vortex
        self._target_crack_morph = 0.0
        self._target_vortex_strength = 0.0
        if state == "awaiting":
            # Pure black empty space — no particles, no edge energy
            self._target_scale = 1.0
            self._target_speed_mul = 0.3
            self._target_glow = 0.0
            self._target_edge_layers = 0
            self._target_edge_intensity = 0.0
            self._target_tint = None
            self._target_tint_blend = 0.0
            self._portal_opening_progress = 0.0
        elif state == "portal_opening":
            # Needle point that grows — pink+blue colors fading to violet
            self._target_scale = 1.0
            self._target_speed_mul = 0.8
            self._target_glow = 0.0
            self._target_edge_layers = 3
            self._target_edge_intensity = 0.08
            self._target_tint = None
            self._target_tint_blend = 0.0
            # Don't reset progress here — it grows in _tick
        elif state == "portal_closing":
            # Needle point that shrinks — violet fading back to pink+blue, then gone
            self._target_scale = 1.0
            self._target_speed_mul = 0.8
            self._target_glow = 0.0
            self._target_edge_layers = 3
            self._target_edge_intensity = 0.08
            self._target_tint = None
            self._target_tint_blend = 0.0
            # Don't reset progress here — it shrinks in _tick
        elif state == "idle":
            self._target_scale = 1.0
            self._target_speed_mul = 1.0
            self._target_glow = 0.0
            self._target_edge_layers = 3
            self._target_edge_intensity = 0.08
            self._target_tint = None
            self._target_tint_blend = 0.0
        elif state == "command":
            self._target_scale = 1.08
            self._target_speed_mul = 2.0
            self._target_glow = 0.0
            self._target_edge_layers = 6
            self._target_edge_intensity = 0.06
            self._target_tint = sc
            self._target_tint_blend = 0.6
        elif state == "terminal":
            self._target_scale = 1.08
            self._target_speed_mul = 2.5
            self._target_glow = 0.0
            self._target_edge_layers = 6
            self._target_edge_intensity = 0.06
            self._target_tint = sc
            self._target_tint_blend = 0.6
        elif state == "screenshot":
            self._target_scale = 1.08
            self._target_speed_mul = 1.5
            self._target_glow = 0.0
            self._target_edge_layers = 6
            self._target_edge_intensity = 0.06
            self._target_tint = sc
            self._target_tint_blend = 0.6
        elif state == "test_pulse":
            self._target_scale = 1.0
            self._target_speed_mul = 0.4
            self._target_glow = 0.0
            self._target_edge_layers = 4
            self._target_edge_intensity = 0.04
            self._target_tint = sc
            self._target_tint_blend = 0.8
        elif state == "paused":
            self._target_scale = 0.32
            self._target_speed_mul = 0.08
            self._target_glow = 0.0
            self._target_edge_layers = 2
            self._target_edge_intensity = 0.03
            self._target_tint = sc
            self._target_tint_blend = 0.95
        elif state == "feedme":
            self._target_scale = 1.0
            self._target_speed_mul = 2.0
            self._target_glow = 0.0
            self._target_edge_layers = 6
            self._target_edge_intensity = 0.06
            self._target_tint = sc
            self._target_tint_blend = 0.6
            self._target_vortex_strength = 1.0
        elif state == "vision":
            self._target_scale = 1.0
            self._target_speed_mul = 0.6
            self._target_glow = 0.4
            self._target_edge_layers = 4
            self._target_edge_intensity = 0.08
            self._target_tint = sc
            self._target_tint_blend = 0.85

        self.state_changed.emit(state)

    def flash_command(self):
        """Brief blue energy flash for regular commands.

        Only restore the previous state if the portal is still in the command
        flash state. This prevents the flash from overwriting a persistent mode
        (e.g. paused/feedme) that was set while the flash was running."""
        previous = self._state
        self.set_state("command")
        def _restore():
            if self._state == "command":
                self.set_state(previous if previous != "command" else "idle")
        QTimer.singleShot(1200, _restore)

    def flash_terminal(self):
        """Brief purple energy flash for terminal commands."""
        previous = self._state
        self.set_state("terminal")
        def _restore():
            if self._state == "terminal":
                self.set_state(previous if previous != "terminal" else "idle")
        QTimer.singleShot(1500, _restore)

    def start_screenshot(self):
        """Yellow glow lingers while a screenshot is being taken/sent."""
        self.set_state("screenshot")

    def end_screenshot(self):
        """Screenshot is done — fade back to idle."""
        self.set_state("idle")

    def flash_alert(self):
        """Quick pink ring flash — split-second burst on incoming messages."""
        self._alert_flash = 1.0

    def start_portal_opening(self):
        """Begin the portal opening animation — needle point grows to idle."""
        self._portal_opening_progress = 0.0
        self.set_state("portal_opening")

    def start_portal_closing(self):
        """Begin the portal closing animation — active portal shrinks back to dormant."""
        self._portal_opening_progress = 1.0
        self.set_state("portal_closing")

    def set_paused(self, paused):
        if paused:
            self.set_state("paused")
        else:
            self.set_state("idle")

    def _blob_path(self, cx, cy, base_r, phase, detail=72, seed=0.0, intensity=0.08, morph=0.0):
        """Organic blob with many harmonics for fluid, non-repeating motion.
        morph: a slow secondary phase that changes the waviness shape itself over time,
        so the blob doesn't just rotate — it actually morphs.
        The morph influence is bounded so the shape never spreads too wide."""
        path = QPainterPath()
        pts = []
        # Bound the morph influence to 0..1 — oscillates, never grows unboundedly
        # This keeps the shape in the subtle "teeth" range, never spreading into a flower
        morph_strength = 0.5 + 0.5 * math.sin(morph * 0.3)  # 0..1, slow oscillation
        for i in range(detail):
            angle = 2 * math.pi * i / detail
            # Primary harmonics — rotate with phase
            wave = (
                math.sin(angle * 2 + phase + seed) * 0.45 +
                math.cos(angle * 3 - phase * 1.1 + seed) * 0.30 +
                math.sin(angle * 5 + phase * 0.6 + seed) * 0.22 +
                math.cos(angle * 8 - phase * 0.4 + seed * 1.7) * 0.14 +
                math.sin(angle * 13 + phase * 0.25 + seed) * 0.09 +
                math.cos(angle * 21 + phase * 0.15 + seed) * 0.05
            )
            # Secondary morph — slowly shifts the harmonic weights so the shape evolves
            # Capped by morph_strength so it never spreads too wide
            if morph != 0.0:
                wave += (
                    math.sin(angle * 3 + morph * 0.7 + seed * 2.0) * 0.15 +
                    math.cos(angle * 7 + morph * 0.5 + seed * 1.3) * 0.10 +
                    math.sin(angle * 11 + morph * 0.3 + seed) * 0.06
                ) * morph_strength
            r = base_r * (1 + wave * intensity)
            x = cx + math.cos(angle) * r
            y = cy + math.sin(angle) * r
            pts.append((x, y))

        mid = lambda a, b: ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        path.moveTo(*mid(pts[-1], pts[0]))
        for i in range(detail):
            p1 = pts[i]
            p2 = pts[(i + 1) % detail]
            m = mid(p1, p2)
            path.quadTo(*p1, *m)
        return path

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        w, h = self.width(), self.height()
        side = min(w, h)
        cx, cy = w / 2, h / 2
        clip_r = side / 2

        # Clip to a circle (the widget bounds)
        clip = QPainterPath()
        clip.addEllipse(QPointF(cx, cy), clip_r, clip_r)
        painter.setClipPath(clip)

        if not self._initialized and w > 0 and h > 0:
            self._init_particles()

        base_r = side * 0.40 * self._scale
        if self._pause_breath < 0.999:
            base_r *= self._pause_breath
        if self._pulse_breath != 1.0 and self._state == "test_pulse":
            base_r *= self._pulse_breath
        # Awaiting: orb shrinks to near nothing — empty space
        if self._state == "awaiting":
            base_r *= 0.02
        # Portal opening/closing: needle point grows/shrinks between 0.02 and 1.0
        if self._state in ("portal_opening", "portal_closing"):
            prog = self._portal_opening_progress
            base_r *= 0.02 + 0.98 * prog
        # Gentle whole-portal breathing — very subtle, makes it feel alive
        # Only in idle and colored states (not paused/pulse which have their own size behavior)
        if self._state not in ("paused", "test_pulse", "awaiting", "portal_opening", "portal_closing"):
            breath_scale = 1.0 + 0.03 * math.sin(self._breath_phase * 0.6)
            base_r *= breath_scale

        # Apply lean — the portal subtly shifts toward the mouse
        cx += self._lean_x * base_r
        cy += self._lean_y * base_r

        # Proximity makes the edge subtly brighter — the portal is aware of you
        prox_glow = self._proximity * 0.15  # very subtle

        # State color
        tint = self._tint if self._tint_blend > 0.01 else None

        # ---- 1. Black center ----
        center_grad = QRadialGradient(cx, cy, base_r * 0.7)
        center_grad.setColorAt(0, QColor(0, 0, 0, 255))
        center_grad.setColorAt(0.6, QColor(2, 1, 4, 250))
        center_grad.setColorAt(1, QColor(4, 2, 8, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(center_grad))
        painter.drawEllipse(QPointF(cx, cy), base_r * 0.7, base_r * 0.7)

        # ---- 1b. Inner rift rotation — slow, visible arcs at the opening ----
        if self._state != "awaiting":
            num_inner_arcs = 4
            inner_base_r = base_r * 0.40
            for i in range(num_inner_arcs):
                arc_r = inner_base_r * (0.85 + 0.15 * math.sin(self._pulse_phase * 0.7 + i * 1.3))
                arc_phase = self._inner_phase + i * (2 * math.pi / num_inner_arcs)
                arc_path = QPainterPath()
                steps = 16
                for j in range(steps + 1):
                    t = j / steps
                    a = arc_phase + t * (math.pi * 0.6)
                    px = cx + math.cos(a) * arc_r
                    py = cy + math.sin(a) * arc_r
                    if j == 0:
                        arc_path.moveTo(px, py)
                    else:
                        arc_path.lineTo(px, py)
                if tint and self._tint_blend > 0.01:
                    tr, tg, tb = tint
                    blend = self._tint_blend * 0.45
                    ir = int(45 * (1 - blend) + tr * blend)
                    ig = int(22 * (1 - blend) + tg * blend)
                    ib = int(62 * (1 - blend) + tb * blend)
                else:
                    ir, ig, ib = 45, 22, 62
                arc_alpha = int(28 + 18 * math.sin(self._pulse_phase * 1.8 + i))
                pen = QPen(QColor(ir, ig, ib, arc_alpha))
                pen.setWidthF(1.1 + 0.35 * (i % 2))
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(arc_path)

        # ---- 2. Drifting dark particles (skip in awaiting state) ----
        if self._state != "awaiting":
            for p in self._particles:
                dist_from_center = math.sqrt((p.x - cx) ** 2 + (p.y - cy) ** 2)
                if dist_from_center > base_r * 0.55:
                    continue
                a = p.alpha
                if a <= 0:
                    continue
                # Near-black, barely visible
                shade = int(5 + p.brightness * 8)
                c = QColor(shade, shade, shade + 1, a)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(c))
                painter.drawEllipse(QPointF(p.x, p.y), p.size * 0.5, p.size * 0.5)

        # ---- 3. Outer dark fluid field (breathing, morphing) — the "intestines" ----
        # Multiple layers, each with its own phase for fluid smoke effect
        # Field rotates counter-clockwise (field_phase decreases)
        # In colored states, the intestines themselves glow with the state's tint
        num_field_layers = 4
        # Subtle pulse for active states — the intestines breathe a bit brighter
        state_pulse = 0.0
        if self._tint_blend > 0.1:
            state_pulse = 0.5 + 0.5 * math.sin(self._pulse_phase * 2.0)
        for i in range(num_field_layers):
            frac = 0.72 + i * 0.07
            r = base_r * frac
            # Each layer breathes independently, alternating direction slightly
            layer_phase = self._field_phase + i * 0.8
            layer_intensity = 0.06 + i * 0.015
            # Morph: each layer evolves its shape slowly, offset by index
            layer_morph = self._morph_phase + i * 1.3
            blob = self._blob_path(cx, cy, r, layer_phase, seed=i * 2.1,
                                   intensity=layer_intensity, morph=layer_morph)

            # Very dark, slightly purple — base color
            darkness = 8 + i * 3
            base_r_c = darkness
            base_g_c = darkness - 3
            base_b_c = darkness + 6

            # In colored states, blend the dark field toward the tint color
            # The intestines themselves light up — same structure, just color-coded
            if tint and self._tint_blend > 0.01:
                tr, tg, tb = tint
                blend = self._tint_blend * (0.45 + 0.15 * state_pulse)
                base_r_c = int(darkness * (1 - blend) + tr * blend)
                base_g_c = int((darkness - 3) * (1 - blend) + tg * blend)
                base_b_c = int((darkness + 6) * (1 - blend) + tb * blend)

            grad = QRadialGradient(cx, cy, r)
            grad.setColorAt(0, QColor(base_r_c, base_g_c, base_b_c, 180 - i * 25))
            grad.setColorAt(0.6, QColor(base_r_c - 2, base_g_c - 1, base_b_c - 4, 190 - i * 20))
            grad.setColorAt(1, QColor(base_r_c - 4, base_g_c - 2, base_b_c - 6, 0))

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(grad))
            painter.drawPath(blob)

        # ---- 4. Thin magical energy edge (wispy translucent layers) ----
        # Edge rotates clockwise (edge_phase increases) — opposing the field
        # Multiple translucent layers at slightly different radii = energy, not a stroke
        edge_base_r = base_r * 0.93
        num_edge = int(self._edge_layers + 0.5)
        for i in range(num_edge):
            offset = (i - num_edge / 2) * 0.015
            r = edge_base_r * (1 + offset)
            layer_seed = i * 1.7
            layer_intensity = self._edge_intensity * (1.0 + i * 0.1)
            edge_morph = self._morph_phase * 0.8 + i * 0.9
            blob = self._blob_path(cx, cy, r, self._edge_phase, seed=layer_seed,
                                   intensity=layer_intensity, morph=edge_morph)

            # Color: idle = faint dark purple, states = tinted
            if tint:
                base_r_c, base_g_c, base_b_c = tint
                blend = self._tint_blend
                # Command: alternate between deep blue and lighter blue per layer
                if self._state == "command":
                    if i % 2 == 0:
                        base_r_c, base_g_c, base_b_c = 30, 100, 220   # deep blue
                    else:
                        base_r_c, base_g_c, base_b_c = 60, 150, 240   # lighter blue
            else:
                base_r_c, base_g_c, base_b_c = 90, 45, 110
                blend = 1.0

            # Colored states: many extremely thin faint lines (premium, minimalist)
            # Idle: fewer, slightly thicker (unchanged)
            if self._tint_blend > 0.1:
                # Colored state — thin threads with a gentle pulse, visible but not cartoonish
                edge_pulse = 0.5 + 0.5 * math.sin(self._pulse_phase * 2.0 + i * 0.5)
                layer_alpha = int((14 + i * 4) * (0.5 + (self._glow + prox_glow) * 0.5 + 0.3 + edge_pulse * 0.2))
                layer_alpha = min(255, layer_alpha)
                wisp_width = 0.5 + (num_edge - i) * 0.10
            else:
                # Idle — keep original feel
                layer_alpha = int((18 + i * 5) * (0.5 + (self._glow + prox_glow) * 0.5 + 0.3))
                layer_alpha = min(255, layer_alpha)
                wisp_width = 1.2 + (num_edge - i) * 0.6

            pen = QPen(QColor(
                int(base_r_c * blend + 30 * (1 - blend)),
                int(base_g_c * blend + 15 * (1 - blend)),
                int(base_b_c * blend + 40 * (1 - blend)),
                layer_alpha
            ))
            pen.setWidthF(wisp_width)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(blob)

        # ---- 5. Portal opening/closing: needle point grows/shrinks, pink+blue fading to violet ----
        if self._state in ("portal_opening", "portal_closing"):
            prog = self._portal_opening_progress  # 0..1
            # Color shifts from pink+blue to violet as it grows
            # Pink (255, 80, 200) + Blue (40, 120, 220) → Violet (90, 45, 110)
            if prog < 0.5:
                # First half: mostly pink+blue
                t_color = prog * 2.0  # 0..1
                r = int(255 * (1 - t_color) + 90 * t_color)
                g = int(80 * (1 - t_color) + 45 * t_color)
                b = int(200 * (1 - t_color) + 110 * t_color)
            else:
                # Second half: transition to violet
                t_color = (prog - 0.5) * 2.0  # 0..1
                r = int(90 * (1 - t_color) + 90 * t_color)
                g = int(45 * (1 - t_color) + 45 * t_color)
                b = int(110 * (1 - t_color) + 110 * t_color)
            # Wavy blob that gets bigger and more wavy as it grows
            open_r = base_r * (0.5 + 0.4 * prog)
            wavy_intensity = 0.04 + 0.08 * prog  # more wavy as it grows
            open_blob = self._blob_path(cx, cy, open_r, self._edge_phase,
                                        seed=1.0, intensity=wavy_intensity)
            # Glow gradient — brighter at needle point, softer as it grows
            glow_alpha = int(120 * (1.0 - prog * 0.5))
            open_grad = QRadialGradient(cx, cy, open_r)
            open_grad.setColorAt(0, QColor(r, g, b, glow_alpha))
            open_grad.setColorAt(0.3, QColor(r, g, b, glow_alpha // 2))
            open_grad.setColorAt(0.7, QColor(r // 2, g // 2, b // 2, glow_alpha // 4))
            open_grad.setColorAt(1, QColor(0, 0, 0, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(open_grad))
            painter.drawPath(open_blob)

            # Secondary blue glow that fades as it grows
            if prog < 0.7:
                blue_alpha = int(80 * (1.0 - prog / 0.7))
                blue_r = base_r * (0.3 + 0.3 * prog)
                blue_blob = self._blob_path(cx, cy, blue_r, self._field_phase,
                                            seed=2.0, intensity=0.06 + 0.06 * prog)
                blue_grad = QRadialGradient(cx, cy, blue_r)
                blue_grad.setColorAt(0, QColor(40, 120, 220, blue_alpha))
                blue_grad.setColorAt(0.5, QColor(30, 80, 180, blue_alpha // 2))
                blue_grad.setColorAt(1, QColor(10, 30, 80, 0))
                painter.setBrush(QBrush(blue_grad))
                painter.drawPath(blue_blob)

        # ---- 6. State-specific overlays ----
        # Command, terminal, screenshot, feedme: NO separate overlay needed —
        # the intestines (field layers) and edge layers already glow with the state's tint.
        # The color-coded rings ARE the animation. Same structure as idle, just lit up.

        # ---- Paused: breathing amber light — the special case (needle point + amber) ----
        if self._state == "paused" and self._tint_blend > 0.5:
            prox_breath_boost = 1.0 + self._proximity * 0.6
            breath_paused = 0.5 + 0.5 * math.sin(self._breath_phase * 0.8 * prox_breath_boost)
            bright = 0.7 + 0.3 * breath_paused + self._proximity * 0.08

            # Core amber glow — contained at base_r * 0.75, wavy blob, soft falloff
            core_r = base_r * (0.65 + 0.10 * breath_paused)
            core_blob = self._blob_path(cx, cy, core_r, self._edge_phase,
                                        seed=1.0, intensity=0.12 + 0.04 * breath_paused)
            core_grad = QRadialGradient(cx, cy, core_r)
            core_grad.setColorAt(0, QColor(min(255, int(255 * bright)), min(255, int(190 * bright)), min(255, int(70 * bright)), 140))
            core_grad.setColorAt(0.25, QColor(min(255, int(220 * bright)), min(255, int(150 * bright)), min(255, int(45 * bright)), 80))
            core_grad.setColorAt(0.55, QColor(180, 110, 30, 35))
            core_grad.setColorAt(1, QColor(100, 60, 20, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(core_grad))
            painter.drawPath(core_blob)

            # Outer warm haze — contained at base_r * 0.95, wavy, always present
            haze_r = base_r * (0.90 + 0.05 * breath_paused + self._proximity * 0.03)
            haze_blob = self._blob_path(cx, cy, haze_r, self._field_phase,
                                        seed=2.0, intensity=0.10 + 0.04 * breath_paused)
            haze_alpha = int(12 + 15 * breath_paused + self._proximity * 10)
            haze_grad = QRadialGradient(cx, cy, haze_r)
            haze_grad.setColorAt(0, QColor(255, 180, 60, 0))
            haze_grad.setColorAt(0.4, QColor(200, 130, 40, haze_alpha // 3))
            haze_grad.setColorAt(0.75, QColor(180, 110, 30, haze_alpha))
            haze_grad.setColorAt(1, QColor(100, 60, 20, 0))
            painter.setBrush(QBrush(haze_grad))
            painter.drawPath(haze_blob)

        # ---- Pulse: red diffuse glow — contained, mirrors paused style ----
        if self._state == "test_pulse" and self._tint_blend > 0.5:
            pulse_rate = 2.5 * (1.0 + self._proximity * 0.3)
            pulse_val = 0.5 + 0.5 * math.sin(self._pulse_phase * pulse_rate)
            bright = 0.6 + 0.4 * pulse_val + self._proximity * 0.1

            # Core red glow — contained at base_r * 0.70, wavy blob
            core_r = base_r * (0.60 + 0.10 * pulse_val)
            core_blob = self._blob_path(cx, cy, core_r, self._edge_phase,
                                        seed=1.0, intensity=0.12 + 0.04 * pulse_val)
            core_grad = QRadialGradient(cx, cy, core_r)
            core_grad.setColorAt(0, QColor(min(255, int(220 * bright)), min(255, int(30 * bright)), min(255, int(35 * bright)), 130))
            core_grad.setColorAt(0.25, QColor(min(255, int(180 * bright)), min(255, int(25 * bright)), min(255, int(30 * bright)), 70))
            core_grad.setColorAt(0.55, QColor(140, 20, 25, 30))
            core_grad.setColorAt(1, QColor(80, 10, 15, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(core_grad))
            painter.drawPath(core_blob)

            # Outer red haze — contained at base_r * 0.92, wavy
            haze_r = base_r * (0.85 + 0.07 * pulse_val + self._proximity * 0.03)
            haze_blob = self._blob_path(cx, cy, haze_r, self._field_phase,
                                        seed=2.0, intensity=0.10 + 0.04 * pulse_val)
            haze_alpha = int(12 + 15 * pulse_val + self._proximity * 10)
            haze_grad = QRadialGradient(cx, cy, haze_r)
            haze_grad.setColorAt(0, QColor(220, 30, 35, 0))
            haze_grad.setColorAt(0.4, QColor(180, 25, 30, haze_alpha // 3))
            haze_grad.setColorAt(0.75, QColor(160, 20, 25, haze_alpha))
            haze_grad.setColorAt(1, QColor(80, 10, 15, 0))
            painter.setBrush(QBrush(haze_grad))
            painter.drawPath(haze_blob)

        # ---- Feedme: no separate overlay — the intestines glow green via the tint blend ----

        # ---- Alert flash: quick pink ring flash — split-second burst ----
        if self._alert_flash > 0.01:
            af = self._alert_flash  # 0..1, decays fast
            # Big ring flash — expands from center, contained within base_r
            # Ring radius grows quickly then fades
            ring_r = base_r * (0.25 + 0.65 * (1.0 - af))  # expands as it fades
            ring_blob = self._blob_path(cx, cy, ring_r, self._edge_phase,
                                        seed=7.0, intensity=0.10 + 0.08 * af)
            # Bright pink ring — feathered edges, overpowering other glows
            ring_grad = QRadialGradient(cx, cy, ring_r)
            ring_grad.setColorAt(0, QColor(255, 80, 200, 0))
            ring_grad.setColorAt(0.82, QColor(255, 80, 200, int(60 * af)))
            ring_grad.setColorAt(0.90, QColor(255, 100, 215, int(230 * af)))
            ring_grad.setColorAt(0.97, QColor(255, 90, 205, int(140 * af)))
            ring_grad.setColorAt(1, QColor(220, 60, 180, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(ring_grad))
            painter.drawPath(ring_blob)

            # Bright core flash — brief hot center burst
            core_flash_r = base_r * (0.45 + 0.25 * (1.0 - af))
            core_flash_blob = self._blob_path(cx, cy, core_flash_r, self._field_phase,
                                              seed=9.0, intensity=0.06 + 0.08 * af)
            core_flash_grad = QRadialGradient(cx, cy, core_flash_r)
            core_flash_grad.setColorAt(0, QColor(255, 120, 220, int(90 * af)))
            core_flash_grad.setColorAt(0.4, QColor(255, 80, 200, int(40 * af)))
            core_flash_grad.setColorAt(1, QColor(255, 60, 180, 0))
            painter.setBrush(QBrush(core_flash_grad))
            painter.drawPath(core_flash_blob)

            # Faded glow behind the ring
            glow_r = base_r * 0.75
            glow_blob = self._blob_path(cx, cy, glow_r, self._field_phase,
                                        seed=8.0, intensity=0.08)
            glow_grad = QRadialGradient(cx, cy, glow_r)
            glow_grad.setColorAt(0, QColor(255, 80, 200, int(45 * af)))
            glow_grad.setColorAt(0.5, QColor(220, 60, 180, int(25 * af)))
            glow_grad.setColorAt(1, QColor(180, 40, 140, 0))
            painter.setBrush(QBrush(glow_grad))
            painter.drawPath(glow_blob)

        # ---- Click ripples — disturbances in the dark matter ----
        for r in self._ripples:
            t = r["age"] / r["max_age"]  # 0..1
            if t >= 1.0:
                continue
            # Ripple expands outward from click point
            ripple_r = t * base_r * 1.2
            # Fade out as it expands
            ripple_alpha = int(60 * (1.0 - t) ** 2)
            if ripple_alpha <= 0:
                continue
            # The ripple is a faint purple disturbance
            ripple_color = QColor(80, 40, 100, ripple_alpha)
            pen = QPen(ripple_color)
            pen.setWidthF(2.0 * (1.0 - t * 0.5))
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(r["x"], r["y"]), ripple_r, ripple_r)

            # Second, fainter wider ripple
            ripple_alpha2 = int(30 * (1.0 - t) ** 2)
            if ripple_alpha2 > 0:
                pen2 = QPen(QColor(60, 30, 80, ripple_alpha2))
                pen2.setWidthF(4.0 * (1.0 - t * 0.5))
                painter.setPen(pen2)
                painter.drawEllipse(QPointF(r["x"], r["y"]), ripple_r * 1.3, ripple_r * 1.3)

        # ---- Vision mode: vertical cat/dragon eye that follows the mouse ----
        if self._state == "vision":
            eye_col = tint if tint else (220, 80, 180)
            er, eg, eb = eye_col
            # Eye dimensions: vertical almond, larger in the centre
            a = base_r * 0.55
            b = base_r * 0.80
            eye_path = QPainterPath()
            eye_path.moveTo(-a, 0)
            eye_path.cubicTo(-a, -b * 1.2, -a * 0.2, -b, 0, -b)
            eye_path.cubicTo(a * 0.2, -b, a, -b * 1.2, a, 0)
            eye_path.cubicTo(a, b * 1.2, a * 0.2, b, 0, b)
            eye_path.cubicTo(-a * 0.2, b, -a, b * 1.2, -a, 0)

            # The pupil/iris follows the mouse via the lean values
            pupil_x = self._lean_x * base_r * 4.0
            pupil_y = self._lean_y * base_r * 4.0

            painter.save()
            painter.translate(cx, cy)
            # Blink scales the whole eye vertically
            painter.scale(1.0, max(0.12, self._vision_open))

            # Sclera glow
            sclera_grad = QRadialGradient(0, 0, b)
            sclera_grad.setColorAt(0, QColor(er, eg, eb, 100))
            sclera_grad.setColorAt(0.5, QColor(er // 2, eg // 2, eb // 2, 60))
            sclera_grad.setColorAt(1, QColor(0, 0, 0, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(sclera_grad))
            painter.drawPath(eye_path)

            # Iris
            iris_r = base_r * 0.32
            iris_grad = QRadialGradient(pupil_x, pupil_y, iris_r)
            iris_grad.setColorAt(0, QColor(min(255, er + 35), min(255, eg + 35), min(255, eb + 35), 160))
            iris_grad.setColorAt(0.6, QColor(er, eg, eb, 100))
            iris_grad.setColorAt(1, QColor(0, 0, 0, 0))
            painter.setBrush(QBrush(iris_grad))
            painter.drawEllipse(QPointF(pupil_x, pupil_y), iris_r, iris_r)

            # Pupil (vertical slit)
            painter.setBrush(QBrush(QColor(10, 5, 15, 230)))
            painter.drawEllipse(QPointF(pupil_x, pupil_y), base_r * 0.12, base_r * 0.35)

            # Eye outline (soft purple-pink stroke)
            outline_pen = QPen(QColor(er, eg, eb, 90))
            outline_pen.setWidthF(2.0)
            painter.setPen(outline_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(eye_path)

            painter.restore()

        painter.end()


# ------------------------------------------------------------------
# UI: chat components
# ------------------------------------------------------------------
class ChatBubble(QFrame):
    def __init__(self, sender, text, is_atlas=True, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(2)

        sender_lbl = QLabel(sender)
        sender_lbl.setStyleSheet(f"color: {PALETTE['muted']}; font-size: 10px; background: transparent;")
        sender_lbl.setFont(QFont("Segoe UI", 8))

        bubble = QLabel(text)
        bubble.setWordWrap(True)
        bubble.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bubble.setFont(QFont("Segoe UI", 10))
        bg = PALETTE["bubble_atlas"] if is_atlas else PALETTE["bubble_user"]
        text_color = PALETTE["text"]
        bubble.setStyleSheet(f"""
            QLabel {{
                background-color: {bg};
                color: {text_color};
                border-radius: 14px;
                padding: 10px 12px;
                border: 1px solid rgba(255, 255, 255, 25);
            }}
        """)

        if is_atlas:
            layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
            layout.addWidget(sender_lbl, alignment=Qt.AlignmentFlag.AlignLeft)
            layout.addWidget(bubble, alignment=Qt.AlignmentFlag.AlignLeft)
            bubble.setMaximumWidth(280)
        else:
            layout.setAlignment(Qt.AlignmentFlag.AlignRight)
            layout.addWidget(sender_lbl, alignment=Qt.AlignmentFlag.AlignRight)
            layout.addWidget(bubble, alignment=Qt.AlignmentFlag.AlignRight)
            bubble.setMaximumWidth(280)


class ChatWindow(QWidget):
    message_sent = Signal(str)
    mute_toggled = Signal(bool)
    close_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(340, 420)

        container = QFrame(self)
        container.setGeometry(8, 8, 324, 404)
        container.setStyleSheet(f"""
            QFrame {{
                background-color: rgba(15, 15, 26, 245);
                border-radius: 20px;
                border: 1px solid rgba(154, 89, 182, 25);
            }}
        """)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setFixedHeight(46)
        header.setStyleSheet("background: transparent; border: none;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 0, 10, 0)

        title = QLabel("Atlas")
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {PALETTE['text']}; background: transparent; border: none;")

        self.mute_btn = QPushButton("Sound on")
        self.mute_btn.setCheckable(True)
        self.mute_btn.setChecked(False)
        self.mute_btn.setFixedSize(70, 26)
        self.mute_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {PALETTE['panel_light']};
                color: {PALETTE['text']};
                border-radius: 13px;
                font-size: 10px;
            }}
            QPushButton:checked {{
                background-color: {PALETTE['muted']};
                color: {PALETTE['bg']};
            }}
        """)
        self.mute_btn.toggled.connect(self._on_mute)

        close_btn = QPushButton("x")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #8b8b9a; border-radius: 12px; font-size: 12px; border: none; }
            QPushButton:hover { background: #8b3a3a; color: #f0f0f5; }
        """)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.clicked.connect(self._on_close)

        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(self.mute_btn)
        header_layout.addWidget(close_btn)
        layout.addWidget(header)

        # Messages
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("border: none; background: transparent;")
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.messages_container = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setContentsMargins(10, 10, 10, 10)
        self.messages_layout.setSpacing(6)
        self.messages_layout.addStretch()
        self.messages_container.setStyleSheet("background: transparent;")
        self.scroll.setWidget(self.messages_container)
        layout.addWidget(self.scroll, 1)

        # Input
        input_frame = QWidget()
        input_frame.setFixedHeight(58)
        input_frame.setStyleSheet("background: transparent; border: none;")
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(10, 8, 10, 8)
        input_layout.setSpacing(8)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Type here to message Atlas...")
        self.input.setFont(QFont("Segoe UI", 10))
        self.input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {PALETTE['input_bg']};
                color: {PALETTE['text']};
                border-radius: 16px;
                padding: 6px 12px;
                border: 1px solid {PALETTE['panel_light']};
            }}
            QLineEdit:focus {{ border: 1px solid {PALETTE['accent']}; }}
        """)
        self.input.returnPressed.connect(self._send)

        send_btn = QPushButton(">")
        send_btn.setFixedSize(32, 32)
        send_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {PALETTE['input_bg']};
                color: {PALETTE['accent_bright']};
                border-radius: 16px;
                font-size: 16px;
            }}
            QPushButton:hover {{ background-color: {PALETTE['panel_light']}; }}
        """)
        send_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        send_btn.clicked.connect(self._send)

        input_layout.addWidget(self.input, 1)
        input_layout.addWidget(send_btn)
        layout.addWidget(input_frame)

        self._muted = False

    def _on_mute(self, checked):
        self._muted = checked
        self.mute_btn.setText("Muted" if checked else "Sound on")
        self.mute_toggled.emit(checked)

    def is_muted(self):
        return self._muted

    def _send(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.add_message("You", text, is_atlas=False)
        self.message_sent.emit(text)

    def _on_close(self):
        self.close_requested.emit()

    def add_message(self, sender, text, is_atlas=True):
        stretch = self.messages_layout.takeAt(self.messages_layout.count() - 1)
        bubble = ChatBubble(sender, text, is_atlas=is_atlas)
        self.messages_layout.addWidget(bubble)
        self.messages_layout.addStretch()
        if stretch:
            stretch.invalidate()
        QTimer.singleShot(10, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))

    def add_system_message(self, text):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setFont(QFont("Segoe UI", 9))
        lbl.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; padding: 6px 0;")
        stretch = self.messages_layout.takeAt(self.messages_layout.count() - 1)
        self.messages_layout.addWidget(lbl)
        self.messages_layout.addStretch()
        if stretch:
            stretch.invalidate()
        QTimer.singleShot(10, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))


# ------------------------------------------------------------------
# Backend worker: polls Firebase in a background thread
# ------------------------------------------------------------------
class PortalWorker(QObject):
    new_command = Signal(dict)

    def __init__(self, owner):
        super().__init__()
        self._owner = owner
        self._running = True
        self._paused = False

    def set_paused(self, paused):
        self._paused = paused

    def stop(self):
        self._running = False

    def _get_interval(self):
        # Dormant after agent-close: no polling at all unless the user has
        # pressed Reopen Rift, in which case poll once per minute for 5 minutes.
        if self._owner._dormant:
            return 60 if self._owner._reconnect_window else None
        # While paused we still poll at the normal interval so a resume/.pause
        # toggle is picked up promptly; the _poll_commands skip handles ignoring
        # other commands while paused.
        return POLL_INTERVAL

    def run(self):
        last_poll = 0
        while self._running:
            now = time.time()
            interval = self._get_interval()
            if interval is None:
                # Fully dormant: just sleep until the state changes
                if self._owner._poll_now:
                    self._owner._poll_now = False
                time.sleep(1)
                continue
            if self._owner._poll_now or (now - last_poll >= interval):
                self._owner._poll_now = False
                try:
                    self._poll_commands()
                except Exception:
                    pass
                last_poll = time.time()
            time.sleep(1)

    def _poll_commands(self):
        data = _firebase_get(f"sessions/{SESSION_ID}/commands")
        _portal_log(f"_poll_commands: data={data!r}, paused={self._paused}")
        if not data:
            return
        commands = data if isinstance(data, list) else list(data.values())
        for cmd in sorted(commands, key=lambda c: c.get("timestamp", "")):
            cmd_id = cmd.get("id")
            if not cmd_id or cmd_id in self._owner._executed_ids:
                continue
            self._owner._executed_ids.add(cmd_id)
            self._owner._save_executed_ids()
            _portal_log(f"_poll_commands: new cmd id={cmd_id} type={cmd.get('type')}")
            if self._paused:
                # When paused, only allow explicit resume commands or the .pause
                # rift_command toggle to pass through.
                cmd_type = cmd.get("type", "")
                if cmd_type == "resume_portal":
                    pass
                elif cmd_type == "rift_command" and cmd.get("command", "").strip().lower() == ".pause":
                    pass
                else:
                    continue
            self.new_command.emit(cmd)


# ------------------------------------------------------------------
# Backend worker: polls Firebase chat in a background thread
# ------------------------------------------------------------------
class ChatWorker(QObject):
    chat_message = Signal(str, bool)  # text, speak

    def __init__(self, owner):
        super().__init__()
        self._owner = owner
        self._running = True

    def stop(self):
        self._running = False

    def _get_interval(self):
        if self._owner._dormant:
            return 60 if self._owner._reconnect_window else None
        return CHAT_POLL_INTERVAL

    def run(self):
        last_poll = 0
        while self._running:
            now = time.time()
            interval = self._get_interval()
            if interval is None:
                # Fully dormant: don't poll chat at all until the user reopens
                if self._owner._poll_now:
                    self._owner._poll_now = False
                time.sleep(1)
                continue
            if self._owner._poll_now or (now - last_poll >= interval):
                self._owner._poll_now = False
                try:
                    self._poll_chat()
                except Exception:
                    pass
                last_poll = time.time()
            time.sleep(1)

    def _poll_chat(self):
        data = _firebase_get(f"sessions/{SESSION_ID}/chat")
        _portal_log(f"_poll_chat: data={data is not None}")
        if not data:
            return
        # Iterate preserving the Firebase child key so we can fall back to it
        # when a message has no explicit "id" field.
        if isinstance(data, list):
            items = list(enumerate(data))
        else:
            items = list(data.items())
        for child_key, msg_data in items:
            if not isinstance(msg_data, dict):
                continue
            msg_id = msg_data.get("id", child_key)
            if msg_id in self._owner._seen_chat_ids:
                continue
            self._owner._seen_chat_ids.add(msg_id)
            sender = msg_data.get("sender", "")
            # Skip our own messages — we don't want to echo back what we sent
            if sender == "portal":
                continue
            text = msg_data.get("text", "")
            msg_type = msg_data.get("type", "msg")
            speak = (msg_type == "speak")
            _portal_log(f"_poll_chat: new msg id={msg_id}")
            if text:
                self.chat_message.emit(text, speak)


# ------------------------------------------------------------------
# UI: main window
# ------------------------------------------------------------------
class RiftCloseConfirmDialog(QDialog):
    """On-theme confirmation shown before the user closes their Rift."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(420, 220)

        container = QFrame(self)
        container.setGeometry(0, 0, 420, 220)
        container.setStyleSheet(f"""
            QFrame {{
                background-color: rgba(18, 17, 30, 245);
                border: 1px solid rgba(154, 89, 182, 50);
                border-radius: 16px;
            }}
        """)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        title = QLabel("Close this Rift?")
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {PALETTE['text']}; background: transparent; border: none;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        msg = QLabel("Closing this Rift will break the connection for the current session. Are you sure?")
        msg.setFont(QFont("Segoe UI", 10))
        msg.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none;")
        msg.setWordWrap(True)
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(msg, 1)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        ask_btn = QPushButton("Ask IT Support")
        ask_btn.setFixedHeight(32)
        ask_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        ask_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        ask_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 12);
                color: {PALETTE['muted']};
                border: 1px solid rgba(255, 255, 255, 25);
                border-radius: 6px;
            }}
            QPushButton:hover {{ background: rgba(255, 255, 255, 22); color: {PALETTE['text']}; }}
        """)
        ask_btn.clicked.connect(self._ask_it_support)

        close_btn = QPushButton("Yes - close it")
        close_btn.setFixedHeight(32)
        close_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(220, 60, 60, 35);
                color: #ff8a8a;
                border: 1px solid rgba(220, 60, 60, 60);
                border-radius: 6px;
            }}
            QPushButton:hover {{ background: rgba(220, 60, 60, 55); }}
        """)
        close_btn.clicked.connect(self.accept)

        btn_layout.addWidget(ask_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        self._parent_window = parent
        self._drag_pos = None

    def _ask_it_support(self):
        if self._parent_window:
            self._parent_window._send_user_message("I'm not sure if I should close this Rift yet. Can you confirm?")
        self.reject()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        event.accept()


class RiftAgentClosedDialog(QDialog):
    """Shown when the admin (Rift Agent) closes the session from the console."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(440, 220)

        container = QFrame(self)
        container.setGeometry(0, 0, 440, 220)
        container.setStyleSheet(f"""
            QFrame {{
                background-color: rgba(18, 17, 30, 245);
                border: 1px solid rgba(154, 89, 182, 50);
                border-radius: 16px;
            }}
        """)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        title = QLabel("Session Closed")
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {PALETTE['text']}; background: transparent; border: none;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        msg = QLabel("Rift Agent just closed this session. You can close your Rift now, or leave it open if you believe they might need to reconnect later.")
        msg.setFont(QFont("Segoe UI", 10))
        msg.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none;")
        msg.setWordWrap(True)
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(msg, 1)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        dormant_btn = QPushButton("Go Dormant")
        dormant_btn.setFixedHeight(32)
        dormant_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        dormant_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        dormant_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(154, 89, 182, 35);
                color: {PALETTE['accent_bright']};
                border: 1px solid rgba(154, 89, 182, 60);
                border-radius: 6px;
            }}
            QPushButton:hover {{ background: rgba(154, 89, 182, 55); }}
        """)
        dormant_btn.clicked.connect(self.reject)

        close_btn = QPushButton("Close Also")
        close_btn.setFixedHeight(32)
        close_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(220, 60, 60, 35);
                color: #ff8a8a;
                border: 1px solid rgba(220, 60, 60, 60);
                border-radius: 6px;
            }}
            QPushButton:hover {{ background: rgba(220, 60, 60, 55); }}
        """)
        close_btn.clicked.connect(self.accept)

        btn_layout.addWidget(dormant_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        self._drag_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        event.accept()


class RiftReopenConfirmDialog(QDialog):
    """Confirmation shown when the user presses the persistent Reopen Rift button."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(420, 220)

        container = QFrame(self)
        container.setGeometry(0, 0, 420, 220)
        container.setStyleSheet(f"""
            QFrame {{
                background-color: rgba(18, 17, 30, 245);
                border: 1px solid rgba(154, 89, 182, 50);
                border-radius: 16px;
            }}
        """)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        title = QLabel("Reopen this Rift?")
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {PALETTE['text']}; background: transparent; border: none;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        msg = QLabel("Are you sure you want to reopen this Rift? If the Agent is finished working this can be closed.")
        msg.setFont(QFont("Segoe UI", 10))
        msg.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none;")
        msg.setWordWrap(True)
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(msg, 1)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(32)
        close_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 12);
                color: {PALETTE['muted']};
                border: 1px solid rgba(255, 255, 255, 25);
                border-radius: 6px;
            }}
            QPushButton:hover {{ background: rgba(255, 255, 255, 22); color: {PALETTE['text']}; }}
        """)
        close_btn.clicked.connect(self.reject)

        reopen_btn = QPushButton("Yes Reopen")
        reopen_btn.setFixedHeight(32)
        reopen_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        reopen_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        reopen_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(154, 89, 182, 35);
                color: {PALETTE['accent_bright']};
                border: 1px solid rgba(154, 89, 182, 60);
                border-radius: 6px;
            }}
            QPushButton:hover {{ background: rgba(154, 89, 182, 55); }}
        """)
        reopen_btn.clicked.connect(self.accept)

        btn_layout.addWidget(close_btn)
        btn_layout.addWidget(reopen_btn)
        layout.addLayout(btn_layout)

        self._drag_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        event.accept()


class ModernPortalWindow(QWidget):
    def __init__(self, portal_folder, color_override=None):
        super().__init__()
        self.portal_folder = portal_folder
        self.executed_file = Path(__file__).resolve()
        self.user_closed_once = False

        # Frameless + translucent compact portal — shows in the taskbar
        # so it can be recovered if it slips behind other windows.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.Window
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(260, 360)
        self.setAcceptDrops(True)  # Allow file drag-and-drop

        # Outer rounded-rect frosted glass container
        self.container = FrostedContainer(self)
        self.container.setGeometry(8, 8, 244, 344)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(0)

        # Title bar
        title_bar = QWidget()
        title_bar.setFixedHeight(30)
        title_bar.setStyleSheet("background: transparent; border: none;")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(8)

        title = QLabel("Rift")
        title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none;")

        min_btn = QPushButton("-")
        min_btn.setFixedSize(22, 22)
        min_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #8b8b9a; border-radius: 11px; font-size: 13px; border: none; }
            QPushButton:hover { background: #2a2a45; color: #f0f0f5; }
        """)
        min_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        min_btn.clicked.connect(self.showMinimized)

        close_btn = QPushButton("x")
        close_btn.setFixedSize(22, 22)
        close_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #8b8b9a; border-radius: 11px; font-size: 13px; border: none; }
            QPushButton:hover { background: #8b3a3a; color: #f0f0f5; }
        """)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.clicked.connect(self._on_close_clicked)

        title_layout.addWidget(title)
        title_layout.addStretch()
        title_layout.addWidget(min_btn)
        title_layout.addWidget(close_btn)
        layout.addWidget(title_bar)

        # Orb area — circular dark glass backdrop for the portal
        # Sized to match the admin console sidebar orb exactly.
        orb_area = CircularGlassFrame()
        orb_area.setFixedSize(200, 200)
        orb_area.set_border_alpha(22)
        orb_layout = QVBoxLayout(orb_area)
        orb_layout.setContentsMargins(8, 8, 8, 8)
        orb_layout.setSpacing(2)

        self.orb = OrbWidget(orb_area)
        self.orb.setFixedSize(160, 160)
        self.orb.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.orb.state_changed.connect(self._on_orb_state_changed)
        self.orb.clicked.connect(self._on_vision_click)
        orb_layout.addWidget(self.orb, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(6)
        layout.addWidget(orb_area, alignment=Qt.AlignmentFlag.AlignCenter)

        self.status_label = QLabel("Awaiting Rift connection")
        self.status_label.setFont(QFont("Segoe UI", 9))
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setFixedWidth(220)
        self.status_label.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none;")
        layout.addWidget(self.status_label)

        # Footer with chat button
        footer = QWidget()
        footer.setFixedHeight(34)
        footer.setStyleSheet("background: transparent; border: none;")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 4, 0, 0)
        footer_layout.setSpacing(0)

        self.chat_btn = QPushButton("Open Chat")
        self.chat_btn.setFont(QFont("Segoe UI", 9))
        self.chat_btn.setFixedHeight(26)
        self.chat_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {PALETTE['panel_light']};
                color: {PALETTE['text']};
                border-radius: 13px;
                padding: 0 16px;
                border: 1px solid rgba(255, 255, 255, 30);
            }}
            QPushButton:hover {{ background-color: {PALETTE['accent']}; color: #ffffff; border: 1px solid rgba(255, 255, 255, 50); }}
        """)
        self.chat_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.chat_btn.clicked.connect(self._toggle_chat)

        self.reopen_btn = QPushButton("Reopen Rift")
        self.reopen_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.reopen_btn.setFixedHeight(26)
        self.reopen_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba(154, 89, 182, 35);
                color: {PALETTE['accent_bright']};
                border-radius: 13px;
                padding: 0 16px;
                border: 1px solid rgba(154, 89, 182, 60);
            }}
            QPushButton:hover {{ background-color: rgba(154, 89, 182, 55); }}
        """)
        self.reopen_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.reopen_btn.clicked.connect(self._on_reopen_rift)
        self.reopen_btn.setVisible(False)

        footer_layout.addStretch()
        footer_layout.addWidget(self.chat_btn)
        footer_layout.addWidget(self.reopen_btn)
        footer_layout.addStretch()
        layout.addWidget(footer)

        # Separate chat window to the right
        self.chat = ChatWindow(self)
        self.chat.message_sent.connect(self._send_user_message)
        self.chat.mute_toggled.connect(self._on_mute_toggled)
        self.chat.close_requested.connect(self._hide_chat)
        self.chat_visible = False

        # Window drag
        self._drag_pos = None
        title_bar.mousePressEvent = self._title_mouse_press
        title_bar.mouseMoveEvent = self._title_mouse_move

        # Dormant/reconnect state and flags must be initialized before the
        # background workers start, or the worker threads can race ahead of
        # __init__ and see missing attributes.
        self.paused = False
        self.muted = False
        self._running = True
        self._registered = False
        self._executed_file = Path(__file__).parent / ".portal_executed.json"
        self._executed_ids = self._load_executed_ids()
        self._seen_chat_ids = set()
        self._color_override = color_override
        self._idle_color = PALETTE["accent"]
        self._active_color = PALETTE["active"]
        self._dormant = False
        self._reconnect_window = False
        self._poll_now = False
        self._vision_last_click = 0  # used for double-click dedup in Vision mode
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._on_reconnect_timeout)

        # Background workers for Firebase polling (so the UI never freezes)
        self._poll_thread = QThread(self)
        self._poll_worker = PortalWorker(self)
        self._poll_worker.moveToThread(self._poll_thread)
        self._poll_worker.new_command.connect(self._on_new_command)
        self._poll_thread.started.connect(self._poll_worker.run)
        self._poll_thread.start()

        self._chat_thread = QThread(self)
        self._chat_worker = ChatWorker(self)
        self._chat_worker.moveToThread(self._chat_thread)
        self._chat_worker.chat_message.connect(self._receive_atlas_message)
        self._chat_thread.started.connect(self._chat_worker.run)
        self._chat_thread.start()

        self._reminder_timer = QTimer(self)
        self._reminder_timer.timeout.connect(self._send_reminder)
        self._reminder_timer.start(REMINDER_INTERVAL * 1000)

        self._center()
        self.show()
        self._set_status("Awaiting Rift connection", PALETTE["muted"])
        self._position_chat()

    def _on_new_command(self, cmd):
        cmd_type = cmd.get("type", "")
        cmd_id = cmd.get("id", "")
        _portal_log(f"_on_new_command: id={cmd_id} type={cmd_type}")
        # Pink lightning flash on every incoming command
        self.orb.flash_alert()
        # Trigger the right orb animation for each command type
        if cmd_type == "screenshot":
            self.orb.start_screenshot()
        elif cmd_type == "terminal":
            self.orb.flash_terminal()
        elif cmd_type == "feedme":
            self.orb.set_state("feedme")
        elif cmd_type == "pause_portal":
            self.orb.set_paused(True)
        elif cmd_type == "resume_portal":
            self.orb.set_paused(False)
        elif cmd_type == "test_pulse":
            self.orb.set_state("test_pulse")
        elif cmd_type == "portal_open":
            self._exit_dormant()
            self.orb.start_portal_opening()
            self._set_status("Rift opening...", PALETTE["active"])
        elif cmd_type == "rift_command":
            # _execute_rift_command handles its own orb state (toggle modes,
            # command flashes, etc.). Flashing here would overwrite the state
            # used for toggle decisions.
            pass
        else:
            self.orb.flash_command()
        ok, result = self._execute_command(cmd)
        _portal_log(f"_on_new_command: ok={ok}, result={result}")
        if cmd_id:
            _write_command_result(cmd_id, cmd_type, ok, result)
        # Screenshot yellow glow only lasts while the capture is in progress;
        # once we have a result the portal returns to idle automatically.
        if cmd_type == "screenshot" and ok:
            self.orb.end_screenshot()
        color = PALETTE["success"] if ok else PALETTE["error"]
        self._set_status(result[:60], color)
        # Persistent modes (paused, feedme, test_pulse, vision) should keep their
        # status text instead of flipping back to "Rift idle" after a few seconds.
        # The check is done when the timer fires, not when it is scheduled, so a
        # brief flash_command that restores to a persistent state is respected.
        def _maybe_reset_idle():
            if not self.paused and self.orb._state not in ("paused", "feedme", "test_pulse", "vision"):
                self._set_status("Rift idle", self._idle_color)
        QTimer.singleShot(2500, _maybe_reset_idle)

    def closeEvent(self, event):
        # Route the first close request through the same confirmation flow as
        # the X button, so window-manager closes also mark the session as
        # user-closed. Final close (second close) is handled normally.
        if not self.user_closed_once:
            event.ignore()
            self._on_close_clicked()
            return
        try:
            self._poll_worker.stop()
            self._chat_worker.stop()
            self._poll_thread.quit()
            self._chat_thread.quit()
            self._poll_thread.wait(1000)
            self._chat_thread.wait(1000)
        except Exception:
            pass
        super().closeEvent(event)

    def _load_executed_ids(self):
        try:
            if self._executed_file.exists():
                with open(self._executed_file, "r", encoding="utf-8") as f:
                    return set(json.load(f))
        except Exception:
            pass
        return set()

    def _save_executed_ids(self):
        try:
            with open(self._executed_file, "w", encoding="utf-8") as f:
                json.dump(list(self._executed_ids), f)
        except Exception:
            pass

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_T:
            if self.orb._state == "test_pulse":
                self.orb.set_state("idle" if not self.paused else "paused")
                self._set_status("Test pulse stopped", PALETTE["success"])
            else:
                self.orb.set_state("test_pulse")
                self._set_status("Test pulse running", PALETTE["error"])
        elif key == Qt.Key.Key_P:
            if self.paused:
                self.paused = False
                self.orb.set_paused(False)
                self._set_status("Rift resumed", PALETTE["success"])
            else:
                self.paused = True
                self.orb.set_paused(True)
                self._set_status("Rift paused", PALETTE["warning"])
            self._poll_worker.set_paused(self.paused)
        elif key == Qt.Key.Key_F:
            if self.orb._state == "feedme":
                self.orb.set_state("idle" if not self.paused else "paused")
                self._set_status("Feed-me mode ended", PALETTE["success"])
            else:
                self.orb.set_state("feedme")
                self._set_status("Drop files here", PALETTE["success"])
        elif key == Qt.Key.Key_C:
            self.orb.flash_command()
            self._set_status("Command flash", PALETTE["active"])
        elif key == Qt.Key.Key_V:
            self.orb.flash_terminal()
            self._set_status("Terminal flash", PALETTE["active"])
        elif key == Qt.Key.Key_A:
            self.orb.flash_alert()
            self._set_status("Alert flash", PALETTE["active"])
        elif key == Qt.Key.Key_O:
            self.orb.start_portal_opening()
            self._set_status("Rift opening", PALETTE["active"])
        elif key == Qt.Key.Key_S:
            self.orb.start_screenshot()
            self._set_status("Screenshot in progress", PALETTE["warning"])
            QTimer.singleShot(3000, lambda: (self.orb.end_screenshot(),
                                             self._set_status("Rift idle", self._idle_color)))
        elif key == Qt.Key.Key_Escape:
            self.paused = False
            self.orb.set_state("idle")
            self._set_status("Rift idle", self._idle_color)
            self._poll_worker.set_paused(False)
        elif key == Qt.Key.Key_K:
            # Inject a test command into Firebase to verify the portal can receive commands.
            import uuid as _uuid
            cmd = {"id": _uuid.uuid4().hex, "type": "test_pulse", "timestamp": datetime.now().isoformat()}
            ok = _firebase_put(f"sessions/{SESSION_ID}/commands/{cmd['id']}", cmd)
            _portal_log(f"injected test command: ok={ok}")
            self._set_status(f"Injected test cmd: {ok}", PALETTE["success"])
        else:
            super().keyPressEvent(event)

    def _title_mouse_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def _title_mouse_move(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            old_pos = self.pos()
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            if self.chat_visible:
                delta = self.pos() - old_pos
                self.chat.move(self.chat.pos() + delta)
            event.accept()

    def _center(self):
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)

    # ---- Drag and drop file support (feedme mode) ----
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            # Flash the orb to show it's accepting
            self.orb.flash_alert()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        event.acceptProposedAction()
        files = []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path:
                files.append(path)
        if not files:
            return
        # Process each dropped file
        for fpath in files:
            self._handle_dropped_file(fpath)

    def _handle_dropped_file(self, file_path):
        """Handle a file dropped onto the portal — upload the actual file to Firebase for admin download."""
        try:
            p = Path(file_path)
            if not p.exists():
                return
            size = p.stat().st_size
            _portal_log(f"File dropped: {file_path}")
            try:
                b64 = base64.b64encode(p.read_bytes()).decode("utf-8")
            except Exception as e:
                _portal_log(f"Drop read error: {e}")
                return
            drop_id = f"drop-{uuid.uuid4().hex[:12]}"
            # Write the actual file data as a command result so the admin can download it
            _write_command_result(
                drop_id, "file_drop", True,
                {"file": str(p), "data": b64}
            )
            # Brief chat note so the admin sees something happened
            chat_id = uuid.uuid4().hex
            _firebase_put(
                f"sessions/{SESSION_ID}/chat/{chat_id}",
                {
                    "id": chat_id,
                    "sender": "portal",
                    "text": f"File dropped: {p.name}",
                    "timestamp": datetime.now().isoformat(),
                    "type": "file_drop",
                    "file_name": p.name,
                    "file_size": size,
                },
            )
            self._set_status(f"File: {p.name}", PALETTE["active"])
            self.orb.flash_alert()
            # If in feedme mode, keep it; otherwise switch to feedme briefly
            if self.orb._state != "feedme":
                self.orb.flash_command()
        except Exception as e:
            _portal_log(f"Drop error: {e}")
            self._set_status(f"Drop failed: {e}", PALETTE["error"])

    def _position_chat(self):
        screen = QApplication.primaryScreen().geometry()
        chat_w = self.chat.width()
        right_x = self.x() + self.width() - 10
        left_x = self.x() - chat_w + 10
        if right_x + chat_w <= screen.right():
            self.chat.move(right_x, self.y() + 6)
        elif left_x >= screen.left():
            self.chat.move(left_x, self.y() + 6)
        else:
            self.chat.move(max(screen.left(), screen.right() - chat_w), self.y() + 6)

    def _set_status(self, text, color=None):
        self.status_label.setText(text)

    def _set_always_on_top(self, always_on_top):
        """Toggle the window's stay-on-top flag without losing frameless/taskbar behavior."""
        has_topmost = bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        if always_on_top == has_topmost:
            return
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
        if always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        # Hide, reconfigure, then re-show to avoid crashes on translucent frameless windows.
        was_visible = self.isVisible()
        pos = self.pos()
        self.hide()
        self.setWindowFlags(flags)
        if was_visible:
            self.show()
            self.move(pos)
            if always_on_top:
                self.raise_()
                self.activateWindow()

    def _on_orb_state_changed(self, state):
        """Keep the window always-on-top only while in feedme mode."""
        self._set_always_on_top(state == "feedme")

    def _on_vision_click(self):
        """Capture and send a screenshot when the Vision eye is clicked.

        Double-clicks within 500 ms are treated as a single click so the admin
        doesn't get spammed. On macOS, QScreen capture may not work for the
        desktop window; in that case we show a compatibility notice instead.
        """
        now = time.time()
        if now - self._vision_last_click < 0.5:
            return
        self._vision_last_click = now

        self._set_status("Capturing vision snapshot...", self._active_color)
        self.orb.start_screenshot()
        cmd_id = uuid.uuid4().hex
        ok, result = self._execute_command({"type": "screenshot", "id": cmd_id})
        if ok:
            _write_command_result(cmd_id, "screenshot", True, result)
            # Return to Vision state so the eye stays active after the snapshot.
            self.orb.set_state("vision")
            self._set_status("Vision snapshot sent", PALETTE["success"])
            return

        # If capture failed and we're on macOS, show a platform notice.
        if platform.system() == "Darwin":
            self.orb.set_state("vision")
            self._set_status("Not compatible with mac", PALETTE["error"])
            _post_to_discord("[Vision] Desktop capture not supported on macOS.")
        else:
            self.orb.set_state("vision")
            self._set_status("Vision snapshot failed", PALETTE["error"])

    def _toggle_chat(self):
        if self.chat_visible:
            self._hide_chat()
        else:
            self._show_chat()

    def _show_chat(self):
        self.chat_visible = True
        self._position_chat()
        self.chat.show()
        self.chat.raise_()
        self.chat.activateWindow()
        self.chat_btn.setText("Close Chat")

    def _hide_chat(self):
        self.chat_visible = False
        self.chat.hide()
        self.chat_btn.setText("Open Chat")

    def _on_mute_toggled(self, muted):
        self.muted = muted

    def _send_user_message(self, text):
        user = _get_user()
        host = platform.node() or "unknown"
        # Write to Firebase chat so the admin console can see it
        try:
            msg_id = uuid.uuid4().hex
            _firebase_put(
                f"sessions/{SESSION_ID}/chat/{msg_id}",
                {
                    "id": msg_id,
                    "sender": "portal",
                    "text": text,
                    "timestamp": datetime.now().isoformat(),
                },
            )
            # Mark our own message as seen so we don't echo it back
            self._seen_chat_ids.add(msg_id)
        except Exception as e:
            _portal_log(f"_send_user_message firebase error: {e}")
        threading.Thread(target=_post_to_discord, args=(
            f"**Reply from {user}@{host}**\n{text[:1500]}",), daemon=True).start()

    def _send_reminder(self):
        if self.paused or self.user_closed_once or self._dormant:
            return
        _post_to_discord(
            f"**Reminder**\nRift `{SESSION_ID}` is still open and listening.\n"
            f"Folder: `{self.portal_folder}`")

    def _receive_atlas_message(self, text, speak=False):
        if not self.paused:
            self._set_status("Message from Atlas...", self._active_color)
        # Fast pink flash and sound on every message received
        self.orb.flash_alert()
        if not self.muted:
            threading.Thread(target=_play_message_sound, daemon=True).start()
        self.chat.add_message("Atlas", text, is_atlas=True)
        if not self.chat_visible:
            self._show_chat()
        if speak and not self.muted:
            threading.Thread(target=_speak_text, args=(text,), daemon=True).start()
        if not self.paused:
            QTimer.singleShot(2000, lambda: self._set_status("Rift idle", self._idle_color))

    def _execute_command(self, cmd):
        cmd_type = cmd.get("type", "")
        user = _get_user()
        host = platform.node() or "unknown"

        if cmd_type == "pause_portal":
            self.paused = True
            self.orb.set_paused(True)
            self._poll_worker.set_paused(True)
            self._set_status("Rift paused", PALETTE["warning"])
            return True, "Rift paused"

        if cmd_type == "resume_portal":
            self.paused = False
            self.orb.set_paused(False)
            self._poll_worker.set_paused(False)
            self._set_status("Rift resumed", PALETTE["success"])
            return True, "Rift resumed"

        if cmd_type == "test_pulse":
            self.orb.set_state("test_pulse")
            self._set_status("Responsiveness test running", PALETTE["error"])
            _post_to_discord(f"[Rift @ {user}@{host}] Test pulse started.")
            return True, "Test pulse started"

        if cmd_type == "stop_test_pulse":
            self.orb.set_state("idle" if not self.paused else "paused")
            self._set_status("Test pulse stopped", PALETTE["success"])
            _post_to_discord(f"[Rift @ {user}@{host}] Test pulse stopped.")
            return True, "Test pulse stopped"

        if cmd_type == "feedme":
            self.orb.set_state("feedme")
            self._set_status("Drop files here", PALETTE["success"])
            _post_to_discord(f"[Rift @ {user}@{host}] Feed-me mode active.")
            return True, "Feed-me mode active"

        if cmd_type == "stop_feedme":
            self.orb.set_state("idle" if not self.paused else "paused")
            self._set_status("Drop mode ended", PALETTE["success"])
            _post_to_discord(f"[Rift @ {user}@{host}] Feed-me mode ended.")
            return True, "Feed-me mode ended"

        if cmd_type in ("message", "speak"):
            text = cmd.get("text", "")
            if text:
                self._receive_atlas_message(text, speak=(cmd_type == "speak"))
            return True, f"{cmd_type}: delivered"

        if cmd_type == "run_script":
            path = cmd.get("path", "")
            if not path or not Path(path).exists():
                return False, f"Script not found: {path}"
            try:
                proc = subprocess.Popen(
                    [sys.executable, path],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    creationflags=CREATE_NO_WINDOW,
                    cwd=str(Path(path).parent))
                threading.Thread(target=self._stream_script, args=(proc, cmd.get("id")), daemon=True).start()
                return True, f"Running script: {path}"
            except Exception as e:
                return False, f"Could not run script: {e}"

        if cmd_type == "scan_directory":
            path = cmd.get("path", self.portal_folder)
            return True, _scan_directory(path)

        if cmd_type == "check_packages":
            return True, _check_packages()

        if cmd_type == "read_file":
            path = cmd.get("path", "")
            if not path or not Path(path).exists():
                return False, f"File not found: {path}"
            return True, _read_file(path)

        if cmd_type == "write_file":
            path = cmd.get("path", "")
            content = cmd.get("content", "")
            if not path:
                return False, "No path given"
            try:
                p = Path(path)
                p.parent.mkdir(parents=True, exist_ok=True)
                _backup_file(path, "replace")
                with open(p, "w", encoding="utf-8") as f:
                    f.write(content)
                return True, f"Wrote {len(content)} bytes to {path}"
            except Exception as e:
                return False, f"Write failed: {e}"

        if cmd_type == "delete_file":
            path = cmd.get("path", "")
            if not path or not Path(path).exists():
                return False, f"File not found: {path}"
            try:
                _backup_file(path, "delete")
                Path(path).unlink()
                return True, f"Deleted {path}"
            except Exception as e:
                return False, f"Delete failed: {e}"

        if cmd_type == "replace_file":
            path = cmd.get("path", "")
            content = cmd.get("content", "")
            if not path:
                return False, "No path given"
            try:
                p = Path(path)
                p.parent.mkdir(parents=True, exist_ok=True)
                _backup_file(path, "replace")
                with open(p, "w", encoding="utf-8") as f:
                    f.write(content)
                return True, f"Replaced {path}"
            except Exception as e:
                return False, f"Replace failed: {e}"

        if cmd_type == "rename_file":
            old_path = cmd.get("old_path", "")
            new_path = cmd.get("new_path", "")
            if not old_path or not new_path:
                return False, "Need old_path and new_path"
            try:
                _backup_file(old_path, "rename", {"old_path": old_path, "new_path": new_path})
                shutil.move(old_path, new_path)
                return True, f"Renamed {old_path} -> {new_path}"
            except Exception as e:
                return False, f"Rename failed: {e}"

        if cmd_type == "undo":
            ok, msg = _undo_last()
            return ok, msg

        if cmd_type == "download_file":
            url = cmd.get("url", "")
            dest = cmd.get("dest", "")
            if not url or not dest:
                return False, "Need url and dest"
            return _download_file(url, dest)

        if cmd_type == "portal_open":
            # Don't override the portal opening animation — let it play
            _mark_portal_opened()
            return True, "Rift opened"

        if cmd_type == "screenshot":
            was_visible = self.isVisible()
            was_minimized = self.isMinimized()
            try:
                # Hide the portal briefly so it doesn't capture itself.
                # Visibility/minimized state is restored in finally, guaranteed.
                self.hide()
                QApplication.processEvents()
                # macOS: Qt's grabWindow often returns a black image for the desktop.
                # Use the native screencapture tool as the primary equivalent there.
                if platform.system() == "Darwin":
                    tmp_path = Path(__file__).parent / ".vision_tmp.png"
                    try:
                        subprocess.run(["screencapture", "-x", str(tmp_path)], check=True, timeout=10)
                        pixmap = QPixmap(str(tmp_path))
                    except Exception:
                        pixmap = QPixmap()
                    finally:
                        try:
                            if tmp_path.exists():
                                tmp_path.unlink()
                        except Exception:
                            pass
                    if pixmap.isNull():
                        screen = QApplication.primaryScreen()
                        pixmap = screen.grabWindow(0)
                else:
                    screen = QApplication.primaryScreen()
                    pixmap = screen.grabWindow(0)
                if pixmap.isNull():
                    return False, "Screenshot failed: could not capture screen"
                # QPixmap.save needs a QIODevice, not a Python BytesIO — use a QBuffer.
                ba = QByteArray()
                buf = QBuffer(ba)
                buf.open(QIODevice.OpenModeFlag.WriteOnly)
                pixmap.save(buf, "PNG")
                buf.close()
                b64 = base64.b64encode(bytes(ba)).decode("utf-8")
                return True, {"image": b64}
            except Exception as e:
                return False, f"Screenshot failed: {e}"
            finally:
                if was_visible:
                    self.show()
                    if was_minimized:
                        self.showMinimized()
                    self.raise_()
                    self.activateWindow()

        if cmd_type == "terminal":
            command_text = cmd.get("command", "").strip()
            if not command_text:
                return False, "No command given"
            try:
                output = subprocess.check_output(
                    command_text, shell=True, stderr=subprocess.STDOUT,
                    creationflags=CREATE_NO_WINDOW, timeout=30
                ).decode("utf-8", errors="replace")
                return True, output[:4000]
            except subprocess.CalledProcessError as e:
                return False, f"Exit {e.returncode}:\n{e.output.decode('utf-8', errors='replace')[:4000]}"
            except Exception as e:
                return False, f"Terminal error: {e}"

        if cmd_type == "force_close":
            # Only act on a genuine admin close. Ignore duplicates or stale
            # force_close commands that may arrive while the user is already
            # closing or the portal is already dormant.
            if self.user_closed_once or (self._dormant and not self._reconnect_window):
                return True, "Rift already closing"
            self._force_close()
            return True, "Closing Rift"

        # ---- .rift commands — interpreted directly by the portal ----
        if cmd_type == "rift_command":
            # Preserve original casing (paths are case-sensitive on some systems);
            # only the command name itself is lowercased inside _execute_rift_command.
            rift_cmd = cmd.get("command", "").strip()
            if not rift_cmd:
                return False, "No .rift command given"
            return self._execute_rift_command(rift_cmd, cmd)

        return False, f"Unknown command: {cmd_type}"

    def _execute_rift_command(self, rift_cmd, cmd):
        """Handle .rift commands sent from the admin console.

        rift_cmd is the full command string (e.g. '.scan /some/path').
        We split it into the command name and an optional argument.
        """
        parts = rift_cmd.split(None, 1)
        cmd_name = parts[0].lower() if parts else ""
        arg = parts[1].strip() if len(parts) > 1 else cmd.get("path", cmd.get("content", ""))

        # Transient rift commands (.scan, .view, .terminal, etc.) flash the orb.
        # Toggle/mode commands (.pause, .feed, .pulse, .vision, .reset, .screenshot)
        # manage their own state.
        if cmd_name not in (".pause", ".feed", ".pulse", ".vision", ".reset", ".screenshot"):
            if cmd_name == ".terminal":
                self.orb.flash_terminal()
            else:
                self.orb.flash_command()

        # .scan — scan the current directory (or a given path) for files
        if cmd_name == ".scan":
            folder = arg or self.portal_folder
            try:
                files = []
                for p in Path(folder).rglob("*"):
                    if p.is_file() and not str(p).startswith(str(Path(folder) / ".git")):
                        rel = p.relative_to(folder)
                        files.append(f"{rel} ({p.stat().st_size} bytes)")
                return True, "Files:\n" + "\n".join(files[:200])
            except Exception as e:
                return False, f"Scan failed: {e}"

        # .view — read a file's contents
        if cmd_name == ".view":
            path = arg
            if not path:
                return False, "Need a file path to view"
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    return True, f.read()[:4000]
            except Exception as e:
                return False, f"View failed: {e}"

        # .delete — delete a file
        if cmd_name == ".delete":
            path = arg
            if not path:
                return False, "Need a file path to delete"
            try:
                _backup_file(path, "delete")
                Path(path).unlink()
                return True, f"Deleted {path}"
            except Exception as e:
                return False, f"Delete failed: {e}"

        # .fetch — fetch a single file (return its contents as base64)
        if cmd_name == ".fetch":
            path = arg
            if not path:
                return False, "Need a file path to fetch"
            try:
                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                return True, {"file": path, "data": b64}
            except Exception as e:
                return False, f"Fetch failed: {e}"

        # .fetchall — fetch all files in the portal folder
        if cmd_name == ".fetchall":
            try:
                folder = Path(arg) if arg else Path(self.portal_folder)
                results = {}
                for p in folder.rglob("*"):
                    if p.is_file() and ".git" not in str(p):
                        rel = str(p.relative_to(folder))
                        try:
                            with open(p, "rb") as f:
                                results[rel] = base64.b64encode(f.read()).decode("utf-8")
                        except Exception:
                            pass
                return True, {"files": results}
            except Exception as e:
                return False, f"FetchAll failed: {e}"

        # .reset — return to idle
        if cmd_name == ".reset":
            return self._execute_command({"type": "resume_portal", "id": cmd.get("id", "")})

        # .screenshot — take a screenshot and return to idle when done
        if cmd_name == ".screenshot":
            self.orb.start_screenshot()
            ok, result = self._execute_command({"type": "screenshot", "id": cmd.get("id", "")})
            if ok:
                self.orb.end_screenshot()
            return ok, result

        # .terminal — run a terminal command
        if cmd_name == ".terminal":
            if not arg:
                return False, "Need a command to run (e.g. .terminal ipconfig)"
            return self._execute_command({"type": "terminal", "id": cmd.get("id", ""), "command": arg})

        # .pause — toggle pause state
        if cmd_name == ".pause":
            if self.paused:
                return self._execute_command({"type": "resume_portal", "id": cmd.get("id", "")})
            return self._execute_command({"type": "pause_portal", "id": cmd.get("id", "")})

        # .feed — toggle feed-me mode
        if cmd_name == ".feed":
            if self.orb._state == "feedme":
                return self._execute_command({"type": "stop_feedme", "id": cmd.get("id", "")})
            return self._execute_command({"type": "feedme", "id": cmd.get("id", "")})

        # .pulse — toggle test pulse
        if cmd_name == ".pulse":
            if self.orb._state == "test_pulse":
                return self._execute_command({"type": "stop_test_pulse", "id": cmd.get("id", "")})
            return self._execute_command({"type": "test_pulse", "id": cmd.get("id", "")})

        # .vision — toggle Vision mode (eye-shaped portal that follows the mouse)
        if cmd_name == ".vision":
            if self.orb._state == "vision":
                self.orb.set_state("idle")
                return True, "Vision deactivated"
            self.orb.set_state("vision")
            return True, "Vision active"

        # Unknown .rift command
        return False, f"Unknown .rift command: {cmd_name}"

    def _stream_script(self, proc, cmd_id):
        try:
            output = []
            for line in iter(proc.stdout.readline, b""):
                output.append(line.decode("utf-8", errors="replace"))
            proc.stdout.close()
            proc.wait()
            text = f"Script output (exit {proc.returncode}):\n{''.join(output)[:1800]}"
            _post_to_discord(text)
        except Exception as e:
            _post_to_discord(f"Script streaming failed: {e}")

    def _on_close_clicked(self):
        if not self.user_closed_once:
            dialog = RiftCloseConfirmDialog(self)
            dialog.move(self.mapToGlobal(self.rect().center() - dialog.rect().center()))
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self._user_close()
        else:
            self._final_user_close()

    def _user_close(self):
        self.user_closed_once = True
        try:
            _firebase_put(f"sessions/{SESSION_ID}/status", "user-closed")
        except Exception:
            pass
        self.chat.hide()
        user = _get_user()
        host = platform.node() or "unknown"
        _post_to_discord(
            f"**User closed the Rift (background mode)**\n"
            f"[Rift @ {user}@{host}]\n"
            f"Session: `{SESSION_ID}`\n"
            f"Atlas can use `/resurrect` to reopen it or `/close` to end the session.\n"
            f"Closing again will permanently delete the Rift.")
        self.hide()
        self._set_always_on_top(False)

    def _final_user_close(self):
        try:
            _mark_session_closed()
        except Exception:
            pass
        # Stop background workers so the process can exit cleanly.
        try:
            self._poll_worker.stop()
            self._chat_worker.stop()
            self._poll_thread.quit()
            self._chat_thread.quit()
            self._poll_thread.wait(1000)
            self._chat_thread.wait(1000)
        except Exception:
            pass
        user = _get_user()
        host = platform.node() or "unknown"
        _post_to_discord(
            f"**User permanently closed the Rift**\n"
            f"[Rift @ {user}@{host}]\n"
            f"Session: `{SESSION_ID}`")
        self.destroy()
        try:
            portal_path = Path(__file__).resolve()
            if self.executed_file.exists():
                self.executed_file.unlink()
            if portal_path.exists():
                portal_path.unlink()
            bdir = _backup_dir()
            if bdir.exists():
                shutil.rmtree(bdir)
        except Exception:
            pass

    def _force_close(self):
        """Handle the admin closing the session.

        The portal shows a dialog with 'Go Dormant' and 'Close Also'. Going
        dormant puts the portal to sleep with a persistent 'Reopen Rift' button.
        Reopening starts a 5-minute reconnect window where the portal polls Firebase
        once per minute, waiting for the admin to actually click Open Rift.
        This avoids burning Firebase quota while still allowing recovery.
        """
        # If the user already closed their Rift, just finalize the shutdown.
        if self.user_closed_once:
            self._final_user_close()
            return
        # Avoid showing the dialog more than once for a single admin close.
        if getattr(self, "_force_close_pending", False):
            return
        self._force_close_pending = True
        try:
            _mark_session_closed()
        except Exception:
            pass
        self._dormant = True
        self._reconnect_window = False
        self._reconnect_timer.stop()
        self._set_status("Rift closing...", PALETTE["muted"])
        self.orb.set_state("portal_closing")
        self.chat_btn.setVisible(False)
        self.reopen_btn.setVisible(False)
        if self.chat_visible:
            self._hide_chat()
        QTimer.singleShot(3000, self._show_agent_closed_dialog)

    def _enter_dormant(self):
        """Put the portal into a low-polling dormant state after agent close."""
        self._dormant = True
        self._reconnect_window = False
        self._reconnect_timer.stop()
        self.orb.set_state("awaiting")
        self._set_status("Rift dormant — click Reopen Rift to reconnect", PALETTE["muted"])
        if self.chat_visible:
            self._hide_chat()
        self.chat_btn.setVisible(False)
        self.reopen_btn.setVisible(True)

    def _start_reconnect_window(self):
        """User clicked Reopen Rift: poll for 5 minutes, once per minute, for an admin Open Rift."""
        self._dormant = True
        self._reconnect_window = True
        self._poll_now = True
        self._reconnect_timer.start(5 * 60 * 1000)  # 5 minutes
        self.orb.set_state("portal_opening")
        self._set_status("Reconnecting... waiting for Rift Agent", PALETTE["active"])
        self.reopen_btn.setVisible(False)

    def _on_reconnect_timeout(self):
        """5-minute reconnect window expired without the admin engaging."""
        self._enter_dormant()
        dialog = RiftReopenConfirmDialog(self)
        dialog.move(self.mapToGlobal(self.rect().center() - dialog.rect().center()))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._start_reconnect_window()
        else:
            self._acknowledge_agent_close()

    def _show_agent_closed_dialog(self):
        dialog = RiftAgentClosedDialog(self)
        dialog.move(self.mapToGlobal(self.rect().center() - dialog.rect().center()))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Close Also chosen
            self._acknowledge_agent_close()
        else:
            # Go Dormant chosen
            self._enter_dormant()

    def _on_reopen_rift(self):
        """Reopen Rift button clicked from the dormant UI."""
        dialog = RiftReopenConfirmDialog(self)
        dialog.move(self.mapToGlobal(self.rect().center() - dialog.rect().center()))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._start_reconnect_window()
        else:
            self._acknowledge_agent_close()

    def _exit_dormant(self):
        """Admin engaged (portal_open command) — resume normal operation."""
        self._dormant = False
        self._reconnect_window = False
        self._reconnect_timer.stop()
        self.chat_btn.setVisible(True)
        self.reopen_btn.setVisible(False)

    def _acknowledge_agent_close(self):
        """User chose to close their Rift after the agent ended the session."""
        self.user_closed_once = True
        try:
            _firebase_put(f"sessions/{SESSION_ID}/status", "user-closed")
        except Exception:
            pass
        self.chat.hide()
        self._set_always_on_top(False)
        self.hide()


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------
def main():
    # High-DPI must be set before QApplication is created.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    PORTAL_FOLDER = str(Path(__file__).parent)
    color_override = None
    for arg in sys.argv[1:]:
        if arg.startswith("--color="):
            color_override = arg.split("=", 1)[1]
        elif arg.startswith("--webhook="):
            _set_webhook_url(arg.split("=", 1)[1])

    # Allow a webhook_url.txt file in the portal folder to override the webhook
    webhook_file = Path(PORTAL_FOLDER) / "webhook_url.txt"
    if webhook_file.exists():
        try:
            url = webhook_file.read_text(encoding="utf-8").strip()
            if url:
                _set_webhook_url(url)
        except Exception:
            pass

    window = ModernPortalWindow(PORTAL_FOLDER, color_override=color_override)

    # Do backend registration in the background so the UI opens instantly.
    def _backend_init():
        try:
            _portal_log("_backend_init started")
            user = _get_user()
            host = platform.node() or "unknown"
            registered = _register_session(user, host, PORTAL_FOLDER)
            if registered:
                window._registered = True
                # Start heartbeat once registration succeeds
                threading.Thread(target=_heartbeat_loop, daemon=True).start()
            # Post the opening message to the default webhook first so the bot sees it,
            # then wait for a session-specific webhook assignment.
            _post_to_discord(
                f"**Rift Opened**\n"
                f"Session: `{SESSION_ID}`\n"
                f"User: {user}@{host}\n"
                f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"Python: {platform.python_version()}\n"
                f"Folder: {PORTAL_FOLDER}")
            _wait_for_webhook(timeout=30)
            _portal_log("_backend_init finished")
        except Exception as e:
            _portal_log(f"_backend_init error: {e}")
        # Clear old Firebase data for this session
        _clear_chat_and_commands()

    def _heartbeat_loop():
        while getattr(window, "_running", True):
            try:
                if getattr(window, "_registered", False) and not getattr(window, "_dormant", False):
                    _update_last_seen()
            except Exception as e:
                _portal_log(f"_heartbeat_loop error: {e}")
            time.sleep(30)

    threading.Thread(target=_backend_init, daemon=True).start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
