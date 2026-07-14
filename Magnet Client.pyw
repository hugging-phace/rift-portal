"""
Magnet Client
==============
A modern PySide6 client for the Magnet remote support platform.

Same backend powers as the original Python Portal, rebuilt with the
Presence visual design language: calm intelligence, soft volumetric light,
and a living field of intelligent orbs.
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

from magnet_vision import VisionStreamer, VisionConfig
from magnet_orb import OrbWidget

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
    "bg": "#0A0A0C",
    "panel": "#101115",
    "panel_light": "#161820",
    "panel_lighter": "#1E212B",
    "text": "#E8E9F0",
    "muted": "#8A8D99",
    "accent": "#7367FF",
    "accent_bright": "#A18CFF",
    "active": "#61D9FF",
    "success": "#22c55e",
    "error": "#ef4444",
    "warning": "#f59e0b",
    "chat_bg": "#0A0A0C",
    "bubble_atlas": "#14151A",
    "bubble_user": "#1E2030",
    "bubble_border": "#2A2D3A",
    "input_bg": "#101115",
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
    """Premium smoked-glass panel for the AI Presence UI."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        radius = 22

        # Deep, layered neutral fill — depth from gradients, not alpha alone
        fill_grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        fill_grad.setColorAt(0, QColor(16, 17, 23, 252))
        fill_grad.setColorAt(0.5, QColor(12, 13, 18, 253))
        fill_grad.setColorAt(1, QColor(10, 10, 12, 254))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(fill_grad))
        painter.drawRoundedRect(rect, radius, radius)

        # Soft top sheen
        sheen_grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.top() + rect.height() * 0.30)
        sheen_grad.setColorAt(0, QColor(255, 255, 255, 18))
        sheen_grad.setColorAt(0.6, QColor(255, 255, 255, 5))
        sheen_grad.setColorAt(1, QColor(255, 255, 255, 0))
        sheen_rect = rect.adjusted(2, 2, -2, 0)
        sheen_rect.setHeight(int(rect.height() * 0.30))
        painter.setBrush(QBrush(sheen_grad))
        painter.drawRoundedRect(sheen_rect, radius, radius)

        # Subtle volumetric border: soft, not glowing
        border_grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        border_grad.setColorAt(0, QColor(120, 120, 140, 45))
        border_grad.setColorAt(0.5, QColor(80, 82, 100, 28))
        border_grad.setColorAt(1, QColor(50, 52, 68, 20))
        pen = QPen(QBrush(border_grad), 1.2)
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
# AI Presence state colors — subtle, professional, no neon
_STATE_COLORS = {
    "awaiting":        None,                 # dark field, no accent
    "portal_opening":  QColor(115, 103, 255), # primary violet
    "portal_closing":  QColor(115, 103, 255),
    "idle":            QColor(115, 103, 255),
    "command":         QColor(97, 217, 255),  # cyan
    "terminal":        QColor(138, 107, 255), # secondary violet
    "screenshot":      QColor(210, 205, 255), # soft white flash
    "test_pulse":      QColor(235, 90, 80),   # warm red
    "paused":          QColor(255, 180, 70),  # amber
    "feedme":          QColor(120, 220, 160), # green
    "vision":          QColor(180, 140, 255), # violet-pink
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
    """Quiet circular bed for the AI presence field — recessed, smoky, no ring."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self._border_alpha = 25

    def set_border_alpha(self, alpha):
        self._border_alpha = alpha
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        side = min(w, h)
        cx, cy = w / 2, h / 2
        r = side / 2 - 4

        # Recessed dark disc
        disc = QRadialGradient(cx, cy, r)
        disc.setColorAt(0, QColor(10, 10, 12, 250))
        disc.setColorAt(0.7, QColor(13, 14, 19, 245))
        disc.setColorAt(1, QColor(16, 17, 23, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(disc))
        painter.drawEllipse(QPointF(cx, cy), r, r)

        # Feathered edge illumination — subtle, not a hard ring
        if self._border_alpha > 0:
            edge = QRadialGradient(cx, cy, r * 1.02)
            edge.setColorAt(0, QColor(120, 120, 140, 0))
            edge.setColorAt(0.80, QColor(120, 120, 140, 0))
            edge.setColorAt(0.90, QColor(120, 120, 140, self._border_alpha))
            edge.setColorAt(1, QColor(120, 120, 140, 0))
            painter.setBrush(QBrush(edge))
            painter.drawEllipse(QPointF(cx, cy), r * 1.02, r * 1.02)

        painter.end()


# ------------------------------------------------------------------
# UI: dimensional tear orb widget (legacy — replaced by magnet_orb.OrbWidget)
# ------------------------------------------------------------------
class _OldOrbWidget(QWidget):
    """A living AI presence field — volumetric, magnetic, and quietly intelligent.

    Replaces the fantasy portal with a premium computational organism:
    soft smoked glass, intelligent light nodes, fluid particles, and
    state-driven volumetric lighting. No rings, no holes, no magic.
    """

    state_changed = Signal(str)
    clicked = Signal()

    class _Node:
        __slots__ = ("x", "y", "vx", "vy", "size", "alpha", "target_alpha",
                     "phase", "focus", "focus_timer", "color", "index",
                     "orbit_r", "orbit_speed", "trail", "pulse")

        def __init__(self, owner, index):
            self.index = index
            w, h = owner.width(), owner.height()
            cx, cy = w / 2, h / 2
            base_r = min(w, h) / 2 * 0.80 if min(w, h) > 0 else 60
            self.orbit_r = base_r * (0.28 + random.random() * 0.28)
            self.orbit_speed = (0.08 + random.random() * 0.15) * (1 if random.random() > 0.5 else -1)
            angle = random.random() * math.pi * 2
            self.x = cx + math.cos(angle) * self.orbit_r
            self.y = cy + math.sin(angle) * self.orbit_r
            self.vx = 0.0
            self.vy = 0.0
            self.size = base_r * (0.09 + random.random() * 0.07)
            self.alpha = 0.0
            self.target_alpha = 0.0
            self.phase = random.random() * 100
            self.focus = index % 4
            self.focus_timer = 2.0 + random.random() * 5.0
            self.color = QColor(115, 103, 255)
            self.trail = []
            self.pulse = 0.0

        def update(self, dt, owner, foci, center, base_r, speed, mouse):
            self.focus_timer -= dt
            if self.focus_timer <= 0:
                self.focus_timer = 4.0 + random.random() * 6.0
                if len(foci) > 1:
                    new_focus = self.focus
                    while new_focus == self.focus:
                        new_focus = random.randrange(len(foci))
                    self.focus = new_focus

            # Target is the focus point plus a gentle orbit around it
            target = foci[self.focus] if self.focus < len(foci) else center
            tx = target[0] + math.cos(self.phase + owner._time * self.orbit_speed) * self.orbit_r * 0.7
            ty = target[1] + math.sin(self.phase + owner._time * self.orbit_speed) * self.orbit_r * 0.7

            # Mouse gravity: subtle pull when cursor is inside the field
            mx, my, mprox = mouse
            if mprox > 0:
                tx += (mx - tx) * mprox * 0.25
                ty += (my - ty) * mprox * 0.25

            ax = (tx - self.x) * 2.0
            ay = (ty - self.y) * 2.0

            # Soft repulsion from other nodes
            for other in owner._nodes:
                if other is self:
                    continue
                dx = self.x - other.x
                dy = self.y - other.y
                d2 = dx * dx + dy * dy + 0.1
                if d2 < (base_r * 0.25) ** 2:
                    rep = 8.0 / d2
                    ax += dx * rep
                    ay += dy * rep

            # Noise wander
            angle = _flow_angle(self.x * 0.5, self.y * 0.5, owner._time * 0.2 + self.index)
            ax += math.cos(angle) * base_r * 0.4
            ay += math.sin(angle) * base_r * 0.4

            self.vx += ax * dt * speed
            self.vy += ay * dt * speed
            self.vx *= 0.94
            self.vy *= 0.94
            self.x += self.vx * dt
            self.y += self.vy * dt

            # Alpha fade
            self.alpha += (self.target_alpha - self.alpha) * (1.0 - math.exp(-dt * 4.0))
            self.phase += dt * (0.3 + speed * 0.2)

            # Trail history: keep last few positions for a soft light streak
            self.trail.insert(0, (self.x, self.y))
            if len(self.trail) > 5:
                self.trail = self.trail[:5]

            # Occasional gentle brightness pulse
            self.pulse += dt * 0.8

        def draw(self, painter, accent, glow):
            if self.alpha <= 0.01:
                return
            # Occasional brightening before returning to equilibrium
            pulse = 0.08 * math.sin(self.pulse) + 0.04 * math.sin(self.pulse * 1.7)
            a = int(self.alpha * (1.0 + pulse))
            base = self.color

            # Soft light trail: small gradient echoes behind the moving orb
            speed = math.hypot(self.vx, self.vy)
            trail_len = min(5, max(0, int(speed * 0.25)))
            if trail_len > 1 and len(self.trail) > 1:
                tail_r = self.size * (1.3 + glow * 0.8)
                for i in range(1, trail_len + 1):
                    if i >= len(self.trail):
                        break
                    t = i / (trail_len + 1)
                    tx, ty = self.trail[i]
                    ta = int(a * (1.0 - t) * 0.35)
                    tail_grad = QRadialGradient(tx, ty, tail_r * (1.0 - t * 0.4))
                    tail_grad.setColorAt(0, QColor(base.red(), base.green(), base.blue(), ta))
                    tail_grad.setColorAt(0.6, QColor(base.red(), base.green(), base.blue(), int(ta * 0.25)))
                    tail_grad.setColorAt(1, QColor(base.red(), base.green(), base.blue(), 0))
                    painter.setBrush(QBrush(tail_grad))
                    painter.drawEllipse(QPointF(tx, ty), tail_r * (1.0 - t * 0.4), tail_r * (1.0 - t * 0.4))

            # Soft volumetric glow
            r = self.size * (2.6 + glow * 1.2)
            grad = QRadialGradient(self.x, self.y, r)
            grad.setColorAt(0, QColor(base.red(), base.green(), base.blue(), int(a * (0.8 + glow * 0.2))))
            grad.setColorAt(0.35, QColor(base.red(), base.green(), base.blue(), int(a * 0.35)))
            grad.setColorAt(0.75, QColor(base.red(), base.green(), base.blue(), int(a * 0.10)))
            grad.setColorAt(1, QColor(base.red(), base.green(), base.blue(), 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(grad))
            painter.drawEllipse(QPointF(self.x, self.y), r, r)

            # Bright core
            core = QColor(235, 236, 245, int(a * 0.9))
            painter.setBrush(QBrush(core))
            painter.drawEllipse(QPointF(self.x, self.y), self.size * 0.35, self.size * 0.35)


    class _Particle:
        __slots__ = ("x", "y", "vx", "vy", "size", "alpha", "target_alpha",
                     "life", "max_life", "noise_offset", "orbit", "orbit_speed")

        def __init__(self, owner):
            w, h = owner.width(), owner.height()
            cx, cy = w / 2, h / 2
            base_r = min(w, h) / 2 * 0.80 if min(w, h) > 0 else 60
            self.orbit = random.random() * math.pi * 2
            self.orbit_speed = (0.1 + random.random() * 0.3) * (1 if random.random() > 0.5 else -1)
            r = (random.random() ** 0.5) * base_r * 0.9
            self.x = cx + math.cos(self.orbit) * r
            self.y = cy + math.sin(self.orbit) * r
            self.vx = 0.0
            self.vy = 0.0
            self.size = base_r * (0.015 + random.random() * 0.02)
            self.alpha = 0.0
            self.target_alpha = random.randint(30, 90)
            self.life = random.random() * 5.0
            self.max_life = 5.0 + random.random() * 8.0
            self.noise_offset = random.random() * 100

        def update(self, dt, owner, nodes, center, base_r, speed, converge, state):
            self.life += dt
            if self.life > self.max_life or math.hypot(self.x - center[0], self.y - center[1]) > base_r * 1.1:
                self._respawn(owner, center, base_r, state)

            # Flow field noise
            angle = _flow_angle(self.x * 0.6, self.y * 0.6, owner._time * 0.15 + self.noise_offset)
            self.vx += math.cos(angle) * base_r * 0.15 * speed * dt
            self.vy += math.sin(angle) * base_r * 0.15 * speed * dt

            # Magnetic attraction to nearest node
            nearest = None
            nearest_d2 = float("inf")
            for n in nodes:
                dx = n.x - self.x
                dy = n.y - self.y
                d2 = dx * dx + dy * dy
                if d2 < nearest_d2:
                    nearest_d2 = d2
                    nearest = n

            if nearest is not None:
                strength = 8.0 if converge else 2.5
                d = math.sqrt(nearest_d2) + 0.1
                self.vx += (nearest.x - self.x) / d * strength * speed * dt
                self.vy += (nearest.y - self.y) / d * strength * speed * dt

            # Converge to center for feed_me
            if converge:
                dx = center[0] - self.x
                dy = center[1] - self.y
                d = math.hypot(dx, dy) + 0.1
                self.vx += dx / d * base_r * 0.8 * dt
                self.vy += dy / d * base_r * 0.8 * dt

            self.vx *= 0.96
            self.vy *= 0.96
            self.x += self.vx * dt
            self.y += self.vy * dt

            # Alpha breathe
            self.alpha += (self.target_alpha - self.alpha) * (1.0 - math.exp(-dt * 2.0))
            self.orbit += dt * self.orbit_speed * speed

        def _respawn(self, owner, center, base_r, state):
            angle = random.random() * math.pi * 2
            r = (random.random() ** 0.5) * base_r * 0.95
            if state == "feedme":
                r = base_r * (0.7 + random.random() * 0.25)
            self.x = center[0] + math.cos(angle) * r
            self.y = center[1] + math.sin(angle) * r
            self.vx = 0.0
            self.vy = 0.0
            self.life = 0.0
            self.max_life = 4.0 + random.random() * 8.0
            self.target_alpha = random.randint(25, 80)

        def draw(self, painter, base_alpha):
            if self.alpha <= 0.01:
                return
            a = int(self.alpha * base_alpha)
            painter.setBrush(QBrush(QColor(180, 185, 210, a)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(self.x, self.y), self.size, self.size)


    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(160, 160)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        self._state = "awaiting"
        self._previous_state = "idle"
        self._nodes = []
        self._particles = []
        self._initialized = False

        self._time = 0.0
        self._breath = 0.0
        self._phase = random.random() * math.pi * 2
        self._flash = 0.0
        self._ripple = []

        # Mouse
        self._mouse_x = 0.0
        self._mouse_y = 0.0
        self._target_proximity = 0.0
        self._proximity = 0.0
        self._lean_x = 0.0
        self._lean_y = 0.0

        # State targets
        self._node_target = 0
        self._particle_target = 0
        self._speed_target = 0.3
        self._scale_target = 0.15
        self._tint_target = None
        self._glow_target = 0.0
        self._converge_target = False

        # Current values
        self._node_count = 0.0
        self._particle_count = 0.0
        self._speed = 0.3
        self._scale = 0.15
        self._tint = None
        self._tint_blend = 0.0
        self._glow = 0.0
        self._converge = False

        self._portal_progress = 0.0

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
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        dx = self._mouse_x - cx
        dy = self._mouse_y - cy
        dist = math.hypot(dx, dy)
        side = min(w, h)
        max_dist = side * 0.7
        self._target_proximity = max(0, 1.0 - dist / max_dist)
        if dist > 0.1:
            self._lean_x = (dx / dist) * self._target_proximity * 0.06
            self._lean_y = (dy / dist) * self._target_proximity * 0.06

    def leaveEvent(self, event):
        self._target_proximity = 0.0
        self._lean_x = 0.0
        self._lean_y = 0.0

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            self._ripple.append({"x": pos.x(), "y": pos.y(), "age": 0.0, "max_age": 2.0})
            if self._state == "vision":
                self.clicked.emit()

    def _ensure_init(self):
        if self._initialized:
            return
        w, h = self.width(), self.height()
        if w == 0 or h == 0:
            return
        for i in range(6):
            n = _OldOrbWidget._Node(self, i)
            self._nodes.append(n)
        for i in range(80):
            p = _OldOrbWidget._Particle(self)
            self._particles.append(p)
        self._initialized = True

    def _tick(self):
        now = self._elapsed.elapsed()
        dt = min((now - self._last_ms) / 1000.0, 0.1)
        self._last_ms = now
        self._time += dt

        self._ensure_init()

        ease = 1.0 - math.exp(-dt * 5.0)
        self._speed = self._lerp(self._speed, self._speed_target, ease)
        self._scale = self._lerp(self._scale, self._scale_target, ease)
        self._glow = self._lerp(self._glow, self._glow_target, ease)
        self._tint = self._tint_target
        self._converge = self._converge_target

        # Portal transition progress
        if self._state == "portal_opening":
            self._portal_progress = min(1.0, self._portal_progress + dt * 0.6)
            if self._portal_progress >= 1.0:
                self.set_state("idle")
        elif self._state == "portal_closing":
            self._portal_progress = max(0.0, self._portal_progress - dt * 0.6)
            if self._portal_progress <= 0.0:
                self.set_state("awaiting")
        else:
            self._portal_progress = self._lerp(self._portal_progress, 1.0, ease) if self._state != "awaiting" else 0.0

        # Flash decay
        if self._flash > 0:
            self._flash = max(0, self._flash - dt * 6.0)

        # Breathing
        self._breath = 0.5 + 0.5 * math.sin(self._time * 0.4)

        # Mouse proximity
        prox_ease = 1.0 - math.exp(-dt * 3.0)
        self._proximity = self._lerp(self._proximity, self._target_proximity, prox_ease)

        # Particle / node counts interpolation
        self._node_count = self._lerp(self._node_count, self._node_target, ease)
        self._particle_count = self._lerp(self._particle_count, self._particle_target, ease)

        # Ripples
        for r in self._ripple:
            r["age"] += dt
        self._ripple = [r for r in self._ripple if r["age"] < r["max_age"]]

        # Update nodes and particles
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        side = min(w, h)
        base_r = side / 2 * 0.82 * self._scale
        if self._state == "awaiting":
            base_r = side / 2 * 0.12 * self._breath

        # Dynamic foci
        foci_count = max(1, int(round(self._node_count)) if self._node_count < 0.5 else max(1, int(round(self._node_count))))
        foci = []
        for i in range(foci_count):
            angle = self._time * (0.08 + i * 0.03) + i * (2 * math.pi / max(1, foci_count))
            r = base_r * (0.32 + 0.20 * math.sin(self._time * 0.12 + i))
            fx = cx + math.cos(angle) * r + self._lean_x * base_r
            fy = cy + math.sin(angle) * r + self._lean_y * base_r
            foci.append((fx, fy))

        center = (cx + self._lean_x * base_r, cy + self._lean_y * base_r)
        mouse = (self._mouse_x, self._mouse_y, self._proximity)

        active_nodes = int(round(self._node_count))
        for i, n in enumerate(self._nodes):
            if i < active_nodes:
                n.target_alpha = 180 + int(self._glow * 60)
            else:
                n.target_alpha = 0
            n.color = self._tint if self._tint else QColor(115, 103, 255)
            n.update(dt, self, foci, center, base_r, self._speed, mouse)

        active_particles = int(round(self._particle_count))
        for i, p in enumerate(self._particles):
            if i < active_particles:
                p.target_alpha = p.target_alpha  # leave as-is
            else:
                p.target_alpha = 0
            p.update(dt, self, [n for n in self._nodes if n.alpha > 10], center, base_r,
                     self._speed, self._converge, self._state)

        self.update()

    def set_state(self, state):
        self._previous_state = self._state
        self._state = state
        self.state_changed.emit(state)
        # Vision Mode gets a brief emphasis flash when it is first entered.
        if state == "vision" and self._previous_state != "vision":
            self._vision_flash_time = getattr(self, "_time", 0.0)

        color = _STATE_COLORS.get(state)
        if state == "awaiting":
            self._node_target = 0
            self._particle_target = 0
            self._speed_target = 0.1
            self._scale_target = 0.15
            self._tint_target = None
            self._glow_target = 0.0
            self._converge_target = False
        elif state in ("portal_opening", "portal_closing"):
            self._node_target = 2
            self._particle_target = 30
            self._speed_target = 0.8
            self._scale_target = 1.0
            self._tint_target = QColor(115, 103, 255)
            self._glow_target = 0.3
            self._converge_target = False
        elif state == "idle":
            self._node_target = 1
            self._particle_target = 30
            self._speed_target = 0.4
            self._scale_target = 1.0
            self._tint_target = color
            self._glow_target = 0.25
            self._converge_target = False
        elif state in ("command", "terminal"):
            self._node_target = 4
            self._particle_target = 60
            self._speed_target = 1.6 if state == "command" else 1.8
            self._scale_target = 1.05
            self._tint_target = color
            self._glow_target = 0.55
            self._converge_target = False
        elif state == "test_pulse":
            self._node_target = 2
            self._particle_target = 40
            self._speed_target = 0.8
            self._scale_target = 1.0
            self._tint_target = color
            self._glow_target = 0.6
            self._converge_target = False
        elif state == "paused":
            self._node_target = 1
            self._particle_target = 12
            self._speed_target = 0.12
            self._scale_target = 0.35
            self._tint_target = color
            self._glow_target = 0.08
            self._converge_target = False
        elif state == "feedme":
            self._node_target = 5
            self._particle_target = 75
            self._speed_target = 1.8
            self._scale_target = 1.0
            self._tint_target = color
            self._glow_target = 0.55
            self._converge_target = True
        elif state == "vision":
            self._node_target = 1
            self._particle_target = 35
            self._speed_target = 0.5
            self._scale_target = 1.0
            self._tint_target = color
            self._glow_target = 0.4
            self._converge_target = False

    def flash_command(self):
        previous = self._state
        self.set_state("command")
        def _restore():
            if self._state == "command":
                self.set_state(previous if previous != "command" else "idle")
        QTimer.singleShot(1200, _restore)

    def flash_terminal(self):
        previous = self._state
        self.set_state("terminal")
        def _restore():
            if self._state == "terminal":
                self.set_state(previous if previous != "terminal" else "idle")
        QTimer.singleShot(1500, _restore)

    def flash_alert(self):
        self._flash = 1.0

    def start_portal_opening(self):
        self._portal_progress = 0.0
        self.set_state("portal_opening")

    def start_portal_closing(self):
        self._portal_progress = 1.0
        self.set_state("portal_closing")

    def set_paused(self, paused):
        self.set_state("paused" if paused else "idle")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        w, h = self.width(), self.height()
        side = min(w, h)
        cx, cy = w / 2, h / 2
        clip_r = side / 2 - 2

        # Soft circular clip — the field lives inside a quiet sphere
        clip = QPainterPath()
        clip.addEllipse(QPointF(cx, cy), clip_r, clip_r)
        painter.setClipPath(clip)

        if not self._initialized and w > 0 and h > 0:
            self._ensure_init()

        base_r = clip_r * 0.85 * self._scale
        if self._state == "awaiting":
            base_r = clip_r * 0.18 * (0.7 + 0.3 * self._breath)

        cx += self._lean_x * base_r
        cy += self._lean_y * base_r

        accent = self._tint if self._tint else QColor(115, 103, 255)

        # ---- 1. Volumetric smoked-glass base ----
        # Deep solid center, softening into layered gradients
        grad_center = QRadialGradient(cx, cy, base_r * 0.6)
        grad_center.setColorAt(0, QColor(10, 10, 12, 255))
        grad_center.setColorAt(0.6, QColor(14, 15, 19, 230))
        grad_center.setColorAt(1, QColor(10, 10, 12, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(grad_center))
        painter.drawEllipse(QPointF(cx, cy), base_r * 0.62, base_r * 0.62)

        grad_mid = QRadialGradient(cx, cy, base_r * 0.92)
        grad_mid.setColorAt(0, QColor(16, 17, 23, 140))
        grad_mid.setColorAt(0.5, QColor(20, 22, 30, 90))
        grad_mid.setColorAt(0.85, QColor(22, 24, 33, 40))
        grad_mid.setColorAt(1, QColor(22, 24, 33, 0))
        painter.setBrush(QBrush(grad_mid))
        painter.drawEllipse(QPointF(cx, cy), base_r, base_r)

        # Edge illumination — not a ring, just a soft rim of light
        edge_alpha = int(12 + self._glow * 28 + self._proximity * 16)
        if edge_alpha > 0:
            edge_grad = QRadialGradient(cx, cy, base_r * 1.02)
            edge_grad.setColorAt(0, QColor(accent.red(), accent.green(), accent.blue(), 0))
            edge_grad.setColorAt(0.78, QColor(accent.red(), accent.green(), accent.blue(), 0))
            edge_grad.setColorAt(0.88, QColor(accent.red(), accent.green(), accent.blue(), edge_alpha))
            edge_grad.setColorAt(0.95, QColor(accent.red(), accent.green(), accent.blue(), edge_alpha // 2))
            edge_grad.setColorAt(1, QColor(accent.red(), accent.green(), accent.blue(), 0))
            painter.setBrush(QBrush(edge_grad))
            painter.drawEllipse(QPointF(cx, cy), base_r * 1.02, base_r * 1.02)

        # Soft top sheen
        sheen = QLinearGradient(cx - base_r * 0.5, cy - base_r * 0.6,
                                cx + base_r * 0.3, cy + base_r * 0.2)
        sheen.setColorAt(0, QColor(255, 255, 255, 5))
        sheen.setColorAt(0.6, QColor(255, 255, 255, 2))
        sheen.setColorAt(1, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(sheen))
        painter.drawEllipse(QPointF(cx, cy), base_r, base_r)

        # ---- 2. Field particles ----
        # Use additive blending so overlapping lights feel like real glow
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        for p in self._particles:
            p.draw(painter, 1.0)

        # ---- 3. Intelligent nodes ----
        for n in self._nodes:
            n.draw(painter, accent, self._glow)

        # ---- 4. State flash / alert ----
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        if self._flash > 0.01:
            f = self._flash
            flash_r = base_r * (0.2 + 0.8 * (1.0 - f))
            flash_grad = QRadialGradient(cx, cy, flash_r)
            flash_grad.setColorAt(0, QColor(230, 230, 245, int(80 * f)))
            flash_grad.setColorAt(0.4, QColor(accent.red(), accent.green(), accent.blue(), int(60 * f)))
            flash_grad.setColorAt(0.8, QColor(accent.red(), accent.green(), accent.blue(), int(20 * f)))
            flash_grad.setColorAt(1, QColor(accent.red(), accent.green(), accent.blue(), 0))
            painter.setBrush(QBrush(flash_grad))
            painter.drawEllipse(QPointF(cx, cy), flash_r, flash_r)

        # ---- 5. Vision Mode emphasis flash ----
        if self._state == "vision" and self._time - getattr(self, "_vision_flash_time", -1) < 0.25:
            flash_r = base_r * (0.2 + 0.8 * (1.0 - (self._time - self._vision_flash_time) / 0.25))
            shot_grad = QRadialGradient(cx, cy, flash_r)
            shot_grad.setColorAt(0, QColor(230, 230, 245, 120))
            shot_grad.setColorAt(0.5, QColor(230, 230, 245, 30))
            shot_grad.setColorAt(1, QColor(230, 230, 245, 0))
            painter.setBrush(QBrush(shot_grad))
            painter.drawEllipse(QPointF(cx, cy), flash_r, flash_r)

        # ---- 6. Click ripples ----
        for r in self._ripple:
            t = r["age"] / r["max_age"]
            if t >= 1.0:
                continue
            rr = t * base_r * 1.2
            alpha = int(50 * (1.0 - t) ** 2)
            if alpha <= 0:
                continue
            ripple_pen = QPen(QColor(accent.red(), accent.green(), accent.blue(), alpha))
            ripple_pen.setWidthF(1.5 * (1.0 - t))
            painter.setPen(ripple_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(r["x"], r["y"]), rr, rr)

        # ---- 7. Subtle field distortion during vision ----
        if self._state == "vision":
            dist_alpha = int(8 + self._proximity * 15)
            dist_grad = QRadialGradient(cx, cy, base_r)
            dist_grad.setColorAt(0, QColor(accent.red(), accent.green(), accent.blue(), 0))
            dist_grad.setColorAt(0.7, QColor(accent.red(), accent.green(), accent.blue(), 0))
            dist_grad.setColorAt(0.85, QColor(accent.red(), accent.green(), accent.blue(), dist_alpha))
            dist_grad.setColorAt(1, QColor(accent.red(), accent.green(), accent.blue(), 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(dist_grad))
            painter.drawEllipse(QPointF(cx, cy), base_r, base_r)

        painter.end()



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
                background-color: rgba(10, 10, 12, 245);
                border-radius: 20px;
                border: 1px solid rgba(120, 120, 140, 28);
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
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
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

        close_btn = QPushButton("×")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {PALETTE['muted']}; border-radius: 12px; font-size: 14px; border: none; }}
            QPushButton:hover {{ background: rgba(239, 68, 68, 80); color: {PALETTE['text']}; }}
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

        title = QLabel("Close this connection?")
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {PALETTE['text']}; background: transparent; border: none;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        msg = QLabel("Closing will break the connection for the current session. Are you sure?")
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
            self._parent_window._send_user_message("I'm not sure if I should close this yet. Can you confirm?")
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

        msg = QLabel("Atlas closed this session. You can close the window now, or leave it open if you believe they might reconnect later.")
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

        title = QLabel("Reconnect?")
        title.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {PALETTE['text']}; background: transparent; border: none;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        msg = QLabel("Are you sure you want to reconnect? If Atlas is finished, you can close instead.")
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


class StatusLabel(QLabel):
    """Single-line status label that elides long text and shows the full message in a tooltip."""

    def setText(self, text):
        self._full_text = text or ""
        width = self.width() if self.width() > 0 else 220
        metrics = QFontMetrics(self.font())
        elided = metrics.elidedText(self._full_text, Qt.TextElideMode.ElideRight, width)
        super().setText(elided)
        self.setToolTip(self._full_text)


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
        self.setFixedSize(260, 286)
        self.setAcceptDrops(True)  # Allow file drag-and-drop

        # Outer rounded-rect frosted glass container
        self.container = FrostedContainer(self)
        self.container.setGeometry(8, 8, 244, 270)
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

        title = QLabel("Magnet")
        title.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none; letter-spacing: 1px;")

        min_btn = QPushButton("−")
        min_btn.setFixedSize(22, 22)
        min_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {PALETTE['muted']}; border-radius: 11px; font-size: 13px; border: none; }}
            QPushButton:hover {{ background: {PALETTE['panel_lighter']}; color: {PALETTE['text']}; }}
        """)
        min_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        min_btn.clicked.connect(self.showMinimized)

        close_btn = QPushButton("×")
        close_btn.setFixedSize(22, 22)
        close_btn.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {PALETTE['muted']}; border-radius: 11px; font-size: 13px; border: none; }}
            QPushButton:hover {{ background: rgba(239, 68, 68, 80); color: {PALETTE['text']}; }}
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
        orb_area.setFixedSize(160, 160)
        orb_area.set_border_alpha(22)
        orb_layout = QVBoxLayout(orb_area)
        orb_layout.setContentsMargins(8, 8, 8, 8)
        orb_layout.setSpacing(2)

        self.orb = OrbWidget(orb_area)
        self.orb.setFixedSize(140, 140)
        self.orb.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.orb.state_changed.connect(self._on_orb_state_changed)
        self.orb.clicked.connect(self._on_vision_click)
        orb_layout.addWidget(self.orb, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addSpacing(6)
        layout.addWidget(orb_area, alignment=Qt.AlignmentFlag.AlignCenter)

        self.status_label = StatusLabel("Awaiting connection")
        self.status_label.setFont(QFont("Segoe UI", 9))
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(False)
        self.status_label.setFixedSize(220, 24)
        self.status_label.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none;")
        layout.addWidget(self.status_label)

        # Footer with chat button
        footer = QWidget()
        footer.setFixedHeight(30)
        footer.setStyleSheet("background: transparent; border: none;")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 4, 0, 0)
        footer_layout.setSpacing(0)

        self.chat_btn = QPushButton("Chat")
        self.chat_btn.setFont(QFont("Segoe UI", 9))
        self.chat_btn.setFixedHeight(24)
        self.chat_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {PALETTE['panel_light']};
                color: {PALETTE['text']};
                border-radius: 12px;
                padding: 0 14px;
                border: 1px solid rgba(255, 255, 255, 25);
            }}
            QPushButton:hover {{ background-color: {PALETTE['accent']}; color: #ffffff; border: 1px solid rgba(255, 255, 255, 45); }}
        """)
        self.chat_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.chat_btn.clicked.connect(self._toggle_chat)

        self.reopen_btn = QPushButton("Reconnect")
        self.reopen_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self.reopen_btn.setFixedHeight(24)
        accent_col = QColor(PALETTE['accent'])
        accent_r = accent_col.red()
        accent_g = accent_col.green()
        accent_b = accent_col.blue()
        self.reopen_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba({accent_r}, {accent_g}, {accent_b}, 40);
                color: {PALETTE['accent_bright']};
                border-radius: 12px;
                padding: 0 14px;
                border: 1px solid rgba({accent_r}, {accent_g}, {accent_b}, 75);
            }}
            QPushButton:hover {{ background-color: rgba({accent_r}, {accent_g}, {accent_b}, 65); }}
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
        self._set_status("Awaiting connection", PALETTE["muted"])
        self._position_chat()

        # Vision streaming worker (screen capture -> Agent console)
        self._vision_streamer = VisionStreamer(self)
        self._vision_streamer.state_changed.connect(self._on_vision_state_changed)
        self._vision_streamer.error.connect(lambda msg: _portal_log(f"[Vision] {msg}"))

    def _on_vision_state_changed(self, state):
        _portal_log(f"Vision streamer state: {state}")

    def _on_new_command(self, cmd):
        cmd_type = cmd.get("type", "")
        cmd_id = cmd.get("id", "")
        _portal_log(f"_on_new_command: id={cmd_id} type={cmd_type}")
        # Screenshot is an instant action with no orb animation.
        if cmd_type != "screenshot":
            self.orb.flash_alert()
        # Trigger the right orb animation for each command type
        if cmd_type == "terminal":
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
            self._set_status("Opening...", PALETTE["active"])
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
        color = PALETTE["success"] if ok else PALETTE["error"]
        self._set_status(result[:60], color)
        # Persistent modes (paused, feedme, test_pulse, vision) should keep their
        # status text instead of flipping back to "Presence idle" after a few seconds.
        # The check is done when the timer fires, not when it is scheduled, so a
        # brief flash_command that restores to a persistent state is respected.
        def _maybe_reset_idle():
            if not self.paused and self.orb._state not in ("paused", "feedme", "test_pulse", "vision"):
                self._set_status("Presence idle", self._idle_color)
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
            if getattr(self, "_vision_streamer", None):
                self._vision_streamer.stop_stream()
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
                self._set_status("Resumed", PALETTE["success"])
            else:
                self.paused = True
                self.orb.set_paused(True)
                self._set_status("Paused", PALETTE["warning"])
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
            self._set_status("Opening", PALETTE["active"])
        elif key == Qt.Key.Key_S:
            ok, result = self._execute_command({"type": "screenshot"})
            self._set_status(result[:60] if isinstance(result, str) else "Screenshot sent",
                             PALETTE["success"] if ok else PALETTE["error"])
        elif key == Qt.Key.Key_Escape:
            self.paused = False
            self.orb.set_state("idle")
            self._set_status("Presence idle", self._idle_color)
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
        doesn't get spammed. Screenshot is an instant action, so the Vision
        state remains active and no orb animation is triggered.
        """
        now = time.time()
        if now - self._vision_last_click < 0.5:
            return
        self._vision_last_click = now

        self._set_status("Capturing vision snapshot...", self._active_color)
        cmd_id = uuid.uuid4().hex
        ok, result = self._execute_command({"type": "screenshot", "id": cmd_id})
        if ok:
            _write_command_result(cmd_id, "screenshot", True, result)
            self._set_status("Vision snapshot sent", PALETTE["success"])
            return

        # If capture failed and we're on macOS, show a platform notice.
        if platform.system() == "Darwin":
            self._set_status("Not compatible with mac", PALETTE["error"])
            _post_to_discord("[Vision] Desktop capture not supported on macOS.")
        else:
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
            QTimer.singleShot(2000, lambda: self._set_status("Presence idle", self._idle_color))

    def _execute_command(self, cmd):
        cmd_type = cmd.get("type", "")
        user = _get_user()
        host = platform.node() or "unknown"

        if cmd_type == "pause_portal":
            self.paused = True
            self.orb.set_paused(True)
            self._poll_worker.set_paused(True)
            self._set_status("Paused", PALETTE["warning"])
            return True, "Paused"

        if cmd_type == "resume_portal":
            self.paused = False
            self.orb.set_paused(False)
            self._poll_worker.set_paused(False)
            self._set_status("Resumed", PALETTE["success"])
            return True, "Resumed"

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
            return True, "Connected"

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
                return True, "Already closing"
            self._force_close()
            return True, "Closing"

        if cmd_type == "start_vision":
            endpoint = cmd.get("endpoint", {})
            host = endpoint.get("host", "127.0.0.1")
            port = int(endpoint.get("port", 0))
            if not host or not port:
                return False, "No Vision endpoint provided"
            try:
                self._vision_streamer.stop_stream()
                self._vision_streamer.start_stream(host, port, SESSION_ID)
                self.orb.set_state("vision")
                return True, f"Vision stream started to {host}:{port}"
            except Exception as e:
                return False, f"Vision start failed: {e}"

        if cmd_type == "stop_vision":
            try:
                self._vision_streamer.stop_stream()
                if self.orb._state == "vision":
                    self.orb.set_state("idle")
                return True, "Vision stream stopped"
            except Exception as e:
                return False, f"Vision stop failed: {e}"

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
            folder = Path(self.portal_folder) / arg if arg else Path(self.portal_folder)
            try:
                files = []
                for p in folder.rglob("*"):
                    if p.is_file() and not str(p).startswith(str(folder / ".git")):
                        rel = p.relative_to(folder)
                        files.append(f"{rel} ({p.stat().st_size} bytes)")
                return True, "Files:\n" + "\n".join(files[:200])
            except Exception as e:
                return False, f"Scan failed: {e}"

        # .view — read a file's contents
        if cmd_name == ".view":
            if not arg:
                return False, "Need a file path to view"
            path = Path(self.portal_folder) / arg
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    return True, f.read()[:4000]
            except Exception as e:
                return False, f"View failed: {e}"

        # .delete — delete a file
        if cmd_name == ".delete":
            if not arg:
                return False, "Need a file path to delete"
            path = Path(self.portal_folder) / arg
            try:
                _backup_file(path, "delete")
                path.unlink()
                return True, f"Deleted {path}"
            except Exception as e:
                return False, f"Delete failed: {e}"

        # .fetch — fetch a single file (return its contents as base64)
        if cmd_name == ".fetch":
            if not arg:
                return False, "Need a file path to fetch"
            path = Path(self.portal_folder) / arg
            try:
                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                return True, {"file": str(path), "data": b64}
            except Exception as e:
                return False, f"Fetch failed: {e}"

        # .fetchall — fetch all files in the portal folder
        if cmd_name == ".fetchall":
            try:
                folder = Path(self.portal_folder) / arg if arg else Path(self.portal_folder)
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

        # .screenshot — take a screenshot instantly, no orb animation
        if cmd_name == ".screenshot":
            return self._execute_command({"type": "screenshot", "id": cmd.get("id", "")})

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
        self._set_status("Closing...", PALETTE["muted"])
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
        self._force_close_pending = False
        self._reconnect_timer.stop()
        self.orb.set_state("awaiting")
        self._set_status("Dormant — click Reconnect to resume", PALETTE["muted"])
        if self.chat_visible:
            self._hide_chat()
        self.chat_btn.setVisible(False)
        self.reopen_btn.setVisible(True)

    def _start_reconnect_window(self):
        """User clicked Reopen Rift: poll for 5 minutes, once per minute, for an admin Open Rift."""
        self._dormant = True
        self._reconnect_window = True
        self._force_close_pending = False
        self._poll_now = True
        self._reconnect_timer.start(5 * 60 * 1000)  # 5 minutes
        self.orb.set_state("portal_opening")
        self._set_status("Reconnecting...", PALETTE["active"])
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
        self._force_close_pending = False
        self._reconnect_timer.stop()
        self.chat_btn.setVisible(True)
        self.reopen_btn.setVisible(False)

    def _acknowledge_agent_close(self):
        """User chose to close their Rift after the agent ended the session."""
        self.user_closed_once = True
        self._force_close_pending = False
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
