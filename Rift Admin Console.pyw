"""
Rift Admin Console — IT remote support control panel.
Controls portal instances, sends commands, views screenshots, chats.

Aesthetic: dark glass sidebar + black glass main area with techny accents.
"""

import io
import json
import math
import os
import random
import sys
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    Qt, QTimer, QPoint, QPointF, QSize, QRectF, Signal, QElapsedTimer, QEvent
)
from PySide6.QtGui import (
    QPainter, QColor, QRadialGradient, QLinearGradient, QFont,
    QCursor, QPixmap, QPen, QBrush, QPainterPath, QFontMetrics
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QTextEdit, QLineEdit, QFrame, QSizePolicy,
    QGraphicsDropShadowEffect, QStackedWidget, QDialog, QFileDialog
)

import uuid as _uuid
import base64 as _b64
import threading as _threading

from PySide6.QtCore import QThread, QObject as _QObj

# ------------------------------------------------------------------
# Shared components (standalone — no dependency on portal file)
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

FIREBASE_URL = "https://mbe-portal-default-rtdb.firebaseio.com"

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
                                      headers={"User-Agent": "RiftAdminConsole/1.0"})
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

        # Frosted glass fill: semi-transparent dark gradient
        fill_grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        fill_grad.setColorAt(0, QColor(26, 24, 42, 238))
        fill_grad.setColorAt(0.5, QColor(20, 19, 34, 245))
        fill_grad.setColorAt(1, QColor(14, 13, 26, 250))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(fill_grad))
        painter.drawRoundedRect(rect, radius, radius)

        # Soft top highlight (glass sheen)
        sheen_grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.top() + rect.height() * 0.35)
        sheen_grad.setColorAt(0, QColor(255, 255, 255, 20))
        sheen_grad.setColorAt(1, QColor(255, 255, 255, 0))
        sheen_rect = rect.adjusted(2, 2, -2, 0)
        sheen_rect.setHeight(int(rect.height() * 0.35))
        painter.setBrush(QBrush(sheen_grad))
        painter.drawRoundedRect(sheen_rect, radius, radius)

        # Thin purple border
        pen = QPen(QColor(154, 89, 182, 45))
        pen.setWidthF(1.5)
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
        # Faster in active states, slower in dormant. Dormant ("awaiting") stays calm,
        # everything else gets a touch more motion so the portal feels alive once open.
        if self._state == "awaiting":
            morph_rate = 0.08
        elif self._state == "idle":
            morph_rate = 0.20
        else:
            morph_rate = 0.32
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
        # Active states get a modest motion boost so the open portal feels alive;
        # dormant/awaiting keeps its slow, calm drift (speed_mul is already low there).
        active_boost = 1.0 if self._state == "awaiting" else 1.25
        if self._state == "feedme":
            field_speed = 0.30 * self._speed_mul * (0.6 + breath * 0.4) * prox_boost * active_boost
            edge_speed = 0.60 * self._speed_mul * (0.6 + breath * 0.4) * prox_boost * active_boost
        elif self._state == "test_pulse":
            field_speed = 0.20 * self._speed_mul * prox_boost
            edge_speed = 0.25 * self._speed_mul * prox_boost
        else:
            field_speed = 0.40 * self._speed_mul * (0.6 + breath * 0.4) * prox_boost * active_boost
            edge_speed = 0.52 * self._speed_mul * (0.6 + breath * 0.4) * prox_boost * active_boost
        self._field_phase -= dt * field_speed  # counter-clockwise
        self._edge_phase += dt * edge_speed    # clockwise
        # Inner rift: clear but controlled rotation at the opening
        inner_speed = 0.45 * self._speed_mul * (0.6 + breath * 0.4) * prox_boost * active_boost
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

    def flash_command(self):
        """Brief blue energy flash for regular commands."""
        previous = self._state
        self.set_state("command")
        QTimer.singleShot(1200, lambda: self.set_state(previous if previous != "command" else "idle"))

    def flash_terminal(self):
        """Brief purple energy flash for terminal commands."""
        previous = self._state
        self.set_state("terminal")
        QTimer.singleShot(1500, lambda: self.set_state(previous if previous != "terminal" else "idle"))

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

        painter.end()


# ------------------------------------------------------------------
# Firebase worker — polls for sessions and results in background
# ------------------------------------------------------------------
class FirebaseWorker(_QObj):
    """Background worker that polls Firebase for session list and results."""

    sessions_updated = Signal(list)   # list of session dicts from Firebase
    result_received = Signal(str, dict)  # (session_id, result_data)
    portal_opened = Signal(str)  # session_id — client confirmed portal opened
    chat_received = Signal(str, dict)  # (session_id, chat_msg) — incoming chat from portal
    poll_status = Signal(str)  # human-readable status/error for debugging

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True
        self._poll_sessions = True
        self._watching_results = {}  # session_id -> set of seen result cmd_ids
        self._watching_opened = set()  # session_ids we're waiting for portal_opened
        self._opened_seen = set()      # session_ids we've already seen opened
        self._watching_chat = {}       # session_id -> set of seen chat msg ids
        self._last_poll_error = None

    def stop(self):
        self._running = False

    def watch_results(self, session_id):
        """Start watching results for a specific session."""
        if session_id not in self._watching_results:
            self._watching_results[session_id] = set()

    def unwatch_results(self, session_id):
        """Stop watching results for a session."""
        self._watching_results.pop(session_id, None)

    def watch_chat(self, session_id):
        """Start watching for incoming chat messages from the portal."""
        if session_id not in self._watching_chat:
            self._watching_chat[session_id] = set()

    def unwatch_chat(self, session_id):
        """Stop watching chat for a session."""
        self._watching_chat.pop(session_id, None)

    def watch_for_opened(self, session_id):
        """Start watching for portal_opened confirmation from client."""
        # Always watch — remove from _opened_seen so a re-open can be detected
        self._opened_seen.discard(session_id)
        self._watching_opened.add(session_id)

    def unwatch_for_opened(self, session_id):
        self._watching_opened.discard(session_id)

    def run(self):
        session_tick = 0
        while self._running:
            # Each poll category is isolated so one failure doesn't suppress the others
            # (e.g. a results poll error must not stop chat from being received).
            try:
                if session_tick % 30 == 0:
                    self._poll_all_sessions()
                session_tick += 1
            except Exception as e:
                self._last_poll_error = str(e)
                self.poll_status.emit(f"Session poll error: {e}")

            for sid in list(self._watching_results.keys()):
                try:
                    self._poll_results(sid)
                except Exception as e:
                    self._last_poll_error = str(e)
                    self.poll_status.emit(f"Result poll error: {e}")

            for sid in list(self._watching_opened):
                try:
                    self._poll_opened(sid)
                except Exception as e:
                    self._last_poll_error = str(e)
                    self.poll_status.emit(f"Opened poll error: {e}")

            for sid in list(self._watching_chat.keys()):
                try:
                    self._poll_chat(sid)
                except Exception as e:
                    self._last_poll_error = str(e)
                    self.poll_status.emit(f"Chat poll error: {e}")

            _threading.Event().wait(0.1)  # 100ms tick

    def _poll_all_sessions(self):
        data = _firebase_get("sessions")
        if not data:
            self.sessions_updated.emit([])
            self.poll_status.emit("Firebase poll: 0 sessions")
            return
        self.poll_status.emit(f"Firebase poll: {len(data)} sessions")
        sessions = []
        for sid, info in data.items():
            if not isinstance(info, dict):
                continue
            status = info.get("status", "unknown")
            opened_at = info.get("opened_at", "")
            last_seen = info.get("last_seen", "")
            # Treat anything not explicitly "open" as inactive
            is_open = (status == "open")
            session_status = "active" if is_open else "inactive"
            # Determine card state:
            #   stale = open but no heartbeat recently
            #   waiting = open but admin hasn't opened portal yet
            #   connected = open and admin has opened portal
            card_state = "inactive"
            if is_open:
                if _is_stale(last_seen, minutes=5):
                    card_state = "stale"
                elif info.get("portal_opened", {}).get("opened"):
                    card_state = "connected"
                    # If we're waiting for this session and it's already opened, emit the signal
                    if sid in self._watching_opened and sid not in self._opened_seen:
                        self._opened_seen.add(sid)
                        self._watching_opened.discard(sid)
                        self.portal_opened.emit(sid)
                else:
                    card_state = "waiting"
            sessions.append({
                "id": sid,
                "name": f"{info.get('user', 'unknown')}@{info.get('host', 'unknown')}",
                "user": info.get("user", "unknown"),
                "host": info.get("host", "unknown"),
                "status": session_status,
                "portal_connected": card_state == "connected",
                "orb_state": "idle",
                "opened_at": opened_at,
                "last_seen": last_seen,
                "card_state": card_state,
            })
        self.sessions_updated.emit(sessions)

    def _poll_results(self, session_id):
        data = _firebase_get(f"sessions/{session_id}/results")
        if not data:
            return
        seen = self._watching_results.setdefault(session_id, set())
        for cmd_id, result in data.items():
            if not isinstance(result, dict) or cmd_id in seen:
                continue
            seen.add(cmd_id)
            self.result_received.emit(session_id, result)

    def _poll_opened(self, session_id):
        data = _firebase_get(f"sessions/{session_id}")
        if not isinstance(data, dict):
            return
        status = data.get("status", "")
        portal_opened = data.get("portal_opened", {})
        if status == "opened" or (isinstance(portal_opened, dict) and portal_opened.get("opened")):
            if session_id not in self._opened_seen:
                self._opened_seen.add(session_id)
                self._watching_opened.discard(session_id)
                self.portal_opened.emit(session_id)

    def _poll_chat(self, session_id):
        """Poll for incoming chat messages from the portal client."""
        data = _firebase_get(f"sessions/{session_id}/chat")
        if not isinstance(data, dict):
            return
        seen = self._watching_chat.setdefault(session_id, set())
        for msg_id, msg in data.items():
            if not isinstance(msg, dict):
                continue
            # Use the message's own id if present, else fall back to the Firebase child key
            mid = msg.get("id", msg_id)
            if mid in seen:
                continue
            seen.add(mid)
            # Only emit messages from the portal (not our own admin messages)
            sender = msg.get("sender", "")
            if sender == "admin":
                continue
            self.chat_received.emit(session_id, msg)


def _is_stale(last_seen, minutes=5):
    """Return True if last_seen is older than the given minutes."""
    if not last_seen:
        return True
    try:
        seen_dt = datetime.fromisoformat(last_seen)
        return (datetime.now() - seen_dt).total_seconds() > minutes * 60
    except Exception:
        return True


# ------------------------------------------------------------------
# Firebase command sender
# ------------------------------------------------------------------
def send_command_to_session(session_id, cmd_type, **extra):
    """Send a command to a portal session via Firebase."""
    cmd = {
        "id": _uuid.uuid4().hex,
        "type": cmd_type,
        "timestamp": datetime.now().isoformat(),
    }
    cmd.update(extra)
    ok = _firebase_put(f"sessions/{session_id}/commands/{cmd['id']}", cmd)
    return cmd["id"] if ok else None

def send_chat_to_session(session_id, text, sender="admin"):
    """Send a chat message to a portal session via Firebase.

    Returns the message id on success, or None if the Firebase write failed.
    """
    msg = {
        "id": _uuid.uuid4().hex,
        "sender": sender,
        "text": text,
        "timestamp": datetime.now().isoformat(),
    }
    ok = _firebase_put(f"sessions/{session_id}/chat/{msg['id']}", msg)
    return msg["id"] if ok else None


def cleanup_stale_sessions(max_age_hours=24):
    """Mark all sessions older than max_age_hours as closed so they stop showing active."""
    data = _firebase_get("sessions")
    if not data:
        return 0
    cutoff = datetime.now().timestamp() - max_age_hours * 3600
    cleaned = 0
    for sid, info in data.items():
        if not isinstance(info, dict):
            continue
        status = info.get("status", "")
        opened_at = info.get("opened_at", "")
        if status != "open" or not opened_at:
            continue
        try:
            opened_ts = datetime.strptime(opened_at, "%Y-%m-%d %H:%M").timestamp()
            if opened_ts < cutoff:
                _firebase_put(f"sessions/{sid}/status", "closed")
                cleaned += 1
        except Exception:
            pass
    return cleaned


def purge_all_closed_sessions():
    """Delete ALL sessions that are not 'open' from Firebase. Returns count deleted."""
    data = _firebase_get("sessions")
    if not data:
        return 0
    deleted = 0
    for sid, info in data.items():
        if not isinstance(info, dict):
            continue
        status = info.get("status", "")
        if status != "open":
            try:
                _firebase_delete(f"sessions/{sid}")
                deleted += 1
            except Exception:
                pass
    return deleted

# ------------------------------------------------------------------
# Admin palette extensions
# ------------------------------------------------------------------
ADMIN_BG = "#06060c"          # near-black background
ADMIN_PANEL = "#0a0a14"       # black glass panels
ADMIN_PANEL_LIGHT = "#101020" # slightly lighter
ADMIN_GRID = "#141428"        # grid line color
ADMIN_HUD = "#00d4ff"         # cyan HUD accent
ADMIN_HUD_DIM = "#006080"     # dim cyan
ADMIN_MONO = "Consolas"       # monospace font for data

# ------------------------------------------------------------------
# Theme system
# ------------------------------------------------------------------
THEMES = {
    "Sonic Wave - Dark Mode (Default)": {
        "is_dark": True,
        "bg": "#06060c",
        "panel_grad_top": (12, 10, 24, 252),
        "panel_grad_mid": (8, 7, 18, 254),
        "panel_grad_bot": (5, 4, 12, 255),
        "sidebar_grad_top": (14, 12, 26, 252),
        "sidebar_grad_mid": (10, 9, 20, 254),
        "sidebar_grad_bot": (7, 6, 14, 255),
        "grid_minor": (20, 20, 40, 40),
        "grid_major": (30, 30, 60, 25),
        "border": (80, 40, 120, 30),
        "sidebar_border": (154, 89, 182, 50),
        "main_border": (80, 40, 120, 35),
        "text": "#f0f0f5",
        "muted": "#8b8b9a",
        "accent": "#9b59b6",
        "accent_bright": "#c084fc",
        "hud": "#00d4ff",
        "hud_dim": "#006080",
        "success": "#22c55e",
        "error": "#ef4444",
        "input_bg": "#16162b",
        "chat_bg": "#0f0f1a",
        "bubble_user": "#2e1a47",
        "bubble_atlas": "#1a1a2e",
        "bubble_border": "#4a2a6e",
        "nav_active_bg": "rgba(155, 89, 182, 30)",
        "nav_hover_bg": "rgba(255, 255, 255, 8)",
        "sheen": (255, 255, 255, 8),
    },
    "Pretty Skies - Night": {
        "is_dark": True,
        "bg": "#080c18",
        "panel_grad_top": (14, 20, 38, 252),
        "panel_grad_mid": (10, 14, 28, 254),
        "panel_grad_bot": (6, 10, 22, 255),
        "sidebar_grad_top": (16, 24, 42, 253),
        "sidebar_grad_mid": (12, 18, 34, 254),
        "sidebar_grad_bot": (8, 14, 28, 255),
        "grid_minor": (30, 50, 80, 35),
        "grid_major": (40, 70, 110, 20),
        "border": (60, 100, 160, 35),
        "sidebar_border": (80, 130, 200, 55),
        "main_border": (60, 100, 160, 40),
        "text": "#d0e0f0",
        "muted": "#6080a0",
        "accent": "#4090d0",
        "accent_bright": "#60b0f0",
        "hud": "#40b0e0",
        "hud_dim": "#205080",
        "success": "#30c070",
        "error": "#f05050",
        "input_bg": "#101830",
        "chat_bg": "#0a1020",
        "bubble_user": "#1a2a48",
        "bubble_atlas": "#101830",
        "bubble_border": "#2a4a70",
        "nav_active_bg": "rgba(64, 144, 208, 30)",
        "nav_hover_bg": "rgba(255, 255, 255, 8)",
        "sheen": (255, 255, 255, 10),
    },
}

_current_theme_name = "Sonic Wave - Dark Mode (Default)"
THEME = THEMES[_current_theme_name]


def apply_theme(name):
    """Switch the global theme and return the new theme dict."""
    global _current_theme_name, THEME, PALETTE
    if name in THEMES:
        _current_theme_name = name
        THEME = THEMES[name]
        # Update PALETTE references for stylesheet-based widgets
        PALETTE["text"] = THEME["text"]
        PALETTE["muted"] = THEME["muted"]
        PALETTE["accent"] = THEME["accent"]
        PALETTE["accent_bright"] = THEME["accent_bright"]
        PALETTE["input_bg"] = THEME["input_bg"]
        PALETTE["chat_bg"] = THEME["chat_bg"]
        PALETTE["bubble_user"] = THEME["bubble_user"]
        PALETTE["bubble_atlas"] = THEME["bubble_atlas"]
        PALETTE["bubble_border"] = THEME["bubble_border"]
        PALETTE["success"] = THEME["success"]
        PALETTE["error"] = THEME["error"]
        return THEME
    return THEME


def current_theme_name():
    return _current_theme_name

# State display info
STATE_INFO = {
    "idle":       ("IDLE",       PALETTE["muted"]),
    "command":    ("COMMAND",    "#2878dc"),
    "terminal":   ("TERMINAL",   "#8c3cdc"),
    "screenshot": ("SCREENSHOT", "#dcc828"),
    "test_pulse": ("PULSE",      "#dc1e28"),
    "paused":     ("PAUSED",     "#ffb432"),
    "feedme":     ("FEEDME",     "#28dc64"),
}


# ------------------------------------------------------------------
# Black glass panel — less transparent than FrostedContainer
# ------------------------------------------------------------------
class BlackGlassPanel(QFrame):
    """Near-opaque black glass panel with subtle border."""

    def __init__(self, parent=None, radius=16, border_color=(80, 40, 120, 30)):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._radius = radius
        self._border_color = border_color

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()

        # Near-opaque glass fill from theme
        t = THEME
        fill_grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        fill_grad.setColorAt(0, QColor(*t["panel_grad_top"]))
        fill_grad.setColorAt(0.5, QColor(*t["panel_grad_mid"]))
        fill_grad.setColorAt(1, QColor(*t["panel_grad_bot"]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(fill_grad))
        painter.drawRoundedRect(rect, self._radius, self._radius)

        # Subtle top sheen
        sheen = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.top() + rect.height() * 0.25)
        sheen.setColorAt(0, QColor(*t["sheen"]))
        sheen.setColorAt(1, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(sheen))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), self._radius, self._radius)

        # Thin border
        pen = QPen(QColor(*self._border_color))
        pen.setWidthF(1.2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), self._radius, self._radius)

        painter.end()


# ------------------------------------------------------------------
# HUD stat card — monospace data display with label
# ------------------------------------------------------------------
class StatCard(BlackGlassPanel):
    """A small HUD card showing a label + value in monospace."""

    def __init__(self, label, value="---", parent=None, accent=ADMIN_HUD):
        super().__init__(parent, radius=12, border_color=(0, 100, 130, 25))
        self._accent = accent
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)

        self._label = QLabel(label.upper())
        self._label.setFont(QFont(ADMIN_MONO, 7))
        self._label.setStyleSheet(f"color: {ADMIN_HUD_DIM}; background: transparent; border: none; letter-spacing: 2px;")
        layout.addWidget(self._label)

        self._value = QLabel(value)
        self._value.setFont(QFont(ADMIN_MONO, 16, QFont.Weight.Bold))
        self._value.setStyleSheet(f"color: {self._accent}; background: transparent; border: none;")
        layout.addWidget(self._value)

    def set_value(self, value, color=None):
        self._value.setText(value)
        if color:
            self._value.setStyleSheet(f"color: {color}; background: transparent; border: none;")


# ------------------------------------------------------------------
# Grid background — subtle techny grid lines
# ------------------------------------------------------------------
class GridBackground(QWidget):
    """Paints a subtle grid pattern behind the main area, with rounded corners."""

    def __init__(self, parent=None, radius=22):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._grid_size = 40
        self._radius = radius

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()

        # Rounded clip path for the entire main area
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        painter.setClipPath(path)

        # Base fill
        painter.fillRect(rect, QColor(THEME["bg"]))

        # Grid lines
        pen = QPen(QColor(*THEME["grid_minor"]))
        pen.setWidthF(0.5)
        painter.setPen(pen)

        for x in range(0, rect.width(), self._grid_size):
            painter.drawLine(x, 0, x, rect.height())
        for y in range(0, rect.height(), self._grid_size):
            painter.drawLine(0, y, rect.width(), y)

        # Brighter grid every 5 cells
        pen = QPen(QColor(*THEME["grid_major"]))
        pen.setWidthF(0.5)
        painter.setPen(pen)
        for x in range(0, rect.width(), self._grid_size * 5):
            painter.drawLine(x, 0, x, rect.height())
        for y in range(0, rect.height(), self._grid_size * 5):
            painter.drawLine(0, y, rect.width(), y)

        # Thin border
        pen = QPen(QColor(*THEME["main_border"]))
        pen.setWidthF(1.2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), self._radius, self._radius)

        painter.end()


# ------------------------------------------------------------------
# Sidebar container — darker, more opaque than FrostedContainer
# ------------------------------------------------------------------
class DarkSidebar(QFrame):
    """Near-opaque dark glass sidebar — less transparent than FrostedContainer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        radius = 22

        # Near-opaque fill from theme — sidebar is slightly lighter
        t = THEME
        fill_grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        fill_grad.setColorAt(0, QColor(*t["sidebar_grad_top"]))
        fill_grad.setColorAt(0.5, QColor(*t["sidebar_grad_mid"]))
        fill_grad.setColorAt(1, QColor(*t["sidebar_grad_bot"]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(fill_grad))
        painter.drawRoundedRect(rect, radius, radius)

        # Subtle top sheen
        sheen_grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.top() + rect.height() * 0.3)
        sheen_grad.setColorAt(0, QColor(*t["sheen"]))
        sheen_grad.setColorAt(1, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(sheen_grad))
        painter.drawRoundedRect(rect.adjusted(2, 2, -2, 0), radius, radius)

        # Thin border from theme
        pen = QPen(QColor(*t["sidebar_border"]))
        pen.setWidthF(1.5)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius, radius)

        painter.end()


# ------------------------------------------------------------------
# Sidebar navigation button
# ------------------------------------------------------------------
class NavButton(QPushButton):
    """Sidebar navigation button with HUD-style indicator."""

    def __init__(self, label, parent=None):
        super().__init__(label, parent)
        self._active = False
        self.setFixedHeight(38)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(QFont("Segoe UI", 9))
        self._update_style()

    def set_active(self, active):
        self._active = active
        self._update_style()

    def refresh_theme(self):
        self._update_style()

    def _update_style(self):
        t = THEME
        if self._active:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: {t['nav_active_bg']};
                    color: {t['accent_bright']};
                    border: none;
                    border-left: 3px solid {t['accent_bright']};
                    text-align: left;
                    padding-left: 16px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {t['muted']};
                    border: none;
                    border-left: 3px solid transparent;
                    text-align: left;
                    padding-left: 16px;
                }}
                QPushButton:hover {{
                    color: {t['text']};
                    background: {t['nav_hover_bg']};
                }}
            """)


# ------------------------------------------------------------------
# Control button — mode trigger
# ------------------------------------------------------------------
class ControlButton(QPushButton):
    """A mode trigger button with colored accent."""

    def __init__(self, label, color, parent=None):
        super().__init__(label, parent)
        self._color = color
        self.setFixedHeight(34)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
        self.setStyleSheet(f"""
            QPushButton {{
                background: rgba({color}, 20);
                color: rgb({color});
                border: 1px solid rgba({color}, 60);
                border-radius: 6px;
                padding: 0 14px;
            }}
            QPushButton:hover {{
                background: rgba({color}, 40);
                border: 1px solid rgba({color}, 120);
            }}
            QPushButton:pressed {{
                background: rgba({color}, 60);
            }}
        """)


# ------------------------------------------------------------------
# Log entry widget
# ------------------------------------------------------------------
class LogEntry(QFrame):
    """A single command log entry with timestamp and type."""

    def __init__(self, timestamp, entry_type, message, color=PALETTE["text"], parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent; border: none;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(12)

        time_label = QLabel(timestamp)
        time_label.setFont(QFont(ADMIN_MONO, 8))
        time_label.setStyleSheet(f"color: {ADMIN_HUD_DIM}; background: transparent; border: none;")
        time_label.setFixedWidth(70)

        type_label = QLabel(entry_type.upper())
        type_label.setFont(QFont(ADMIN_MONO, 8, QFont.Weight.Bold))
        type_label.setStyleSheet(f"color: {color}; background: transparent; border: none;")
        type_label.setFixedWidth(80)

        msg_label = QLabel(message)
        msg_label.setFont(QFont(ADMIN_MONO, 8))
        msg_label.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none;")
        msg_label.setWordWrap(True)
        msg_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)

        layout.addWidget(time_label)
        layout.addWidget(type_label)
        layout.addWidget(msg_label, 1)


# ------------------------------------------------------------------
# Session data model
# ------------------------------------------------------------------
import uuid as _uuid

class Session:
    """Represents a remote portal client session."""
    def __init__(self, name=None, host="unknown", user="unknown"):
        self.id = _uuid.uuid4().hex[:12]
        self.name = name or f"Session-{self.id[:6]}"
        self.host = host
        self.user = user
        self.status = "active"  # active, inactive, expired
        self.portal_connected = False  # True once the portal handshake completes
        self.created = datetime.now()
        self.last_active = datetime.now()
        self.orb_state = "idle"
        self.chat = []              # list of (sender, text, timestamp)
        self.results = []           # list of dicts: {type, title, content, timestamp, collapsed}
        self._seen_chat_ids = set()
        self._seen_result_ids = set()
        self._close_alert_added = False
        self.opened_at = ""
        self.last_seen = ""
        self.card_state = "inactive"

    def uptime_str(self):
        delta = datetime.now() - self.created
        h = int(delta.total_seconds() // 3600)
        m = int((delta.total_seconds() % 3600) // 60)
        s = int(delta.total_seconds() % 60)
        return f"{h:02d}:{m:02d}:{s:02d}"


# ------------------------------------------------------------------
# Portal opening animation widget — small blue glow growing
# ------------------------------------------------------------------
class PortalOpeningWidget(QWidget):
    """Animated portal opening — small blue glow grows from center."""

    admin_animation_done = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._progress = 0.0  # 0..1
        self._animation_done = False
        self._client_confirmed = False
        self._pulse_phase = 0.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        self._last_ms = 0

    def start(self):
        self._progress = 0.0
        self._animation_done = False
        self._client_confirmed = False
        self._pulse_phase = 0.0
        self._last_ms = self._elapsed.elapsed()
        self._timer.start(16)

    def confirm_client_open(self):
        """Called when the client has confirmed the portal is open."""
        self._client_confirmed = True
        self._timer.stop()
        self.update()

    def _tick(self):
        now = self._elapsed.elapsed()
        dt = min((now - self._last_ms) / 1000.0, 0.1)
        self._last_ms = now

        if not self._animation_done:
            # Grow over ~1.5 seconds — fast enough to not feel sluggish
            self._progress = min(1.0, self._progress + dt * 0.7)
            if self._progress >= 1.0:
                self._animation_done = True
                self.admin_animation_done.emit()
        else:
            # Keep a slow pulse while waiting for client confirmation
            self._pulse_phase = (self._pulse_phase + dt * 2.0) % (2 * math.pi)

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        max_r = min(w, h) * 0.35

        # Blue glow grows from center, then pulses while waiting
        if not self._animation_done:
            r = max_r * self._progress
        else:
            pulse = 1.0 + 0.05 * math.sin(self._pulse_phase)
            r = max_r * pulse

        if r > 1:
            # Outer glow
            glow_grad = QRadialGradient(cx, cy, r * 1.8)
            glow_grad.setColorAt(0, QColor(40, 120, 220, int(110)))
            glow_grad.setColorAt(0.4, QColor(30, 80, 180, int(50)))
            glow_grad.setColorAt(1, QColor(10, 25, 60, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(glow_grad))
            painter.drawEllipse(QPointF(cx, cy), r * 1.8, r * 1.8)

            # Core glow
            core_grad = QRadialGradient(cx, cy, r)
            core_grad.setColorAt(0, QColor(80, 160, 240, int(170)))
            core_grad.setColorAt(0.5, QColor(40, 100, 200, int(70)))
            core_grad.setColorAt(1, QColor(20, 50, 120, 0))
            painter.setBrush(QBrush(core_grad))
            painter.drawEllipse(QPointF(cx, cy), r, r)

        # Status text
        if not self._animation_done:
            status_text = "PORTAL OPENING..."
            status_color = QColor(80, 160, 240)
        elif not self._client_confirmed:
            status_text = "WAITING FOR PORTAL TO CONNECT..."
            status_color = QColor(80, 160, 240)
        else:
            status_text = "PORTAL NOW OPEN"
            status_color = QColor(40, 220, 100)
        painter.setPen(status_color)
        painter.setFont(QFont(ADMIN_MONO, 10, QFont.Weight.Bold))
        painter.drawText(QPointF(cx - 80, cy + max_r + 30), status_text)

        painter.end()


# ------------------------------------------------------------------
# Collapsible output box — for long text results
# ------------------------------------------------------------------
class ResultPopoutDialog(QDialog):
    """Simple read-only popout window for long command output."""

    def __init__(self, title, content, parent=None):
        super().__init__(parent, Qt.WindowType.WindowCloseButtonHint)
        self.setWindowTitle(title)
        self.resize(720, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        text = QTextEdit()
        text.setPlainText(content)
        text.setReadOnly(True)
        text.setFont(QFont(ADMIN_MONO, 9))
        text.setStyleSheet(f"""
            QTextEdit {{
                background: {PALETTE['chat_bg']};
                color: {PALETTE['text']};
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 6px;
                padding: 6px;
            }}
        """)
        layout.addWidget(text)


class ZoomImageViewer(QWidget):
    """Image viewer: fit-to-window, click toggles zoom, click-and-drag pans."""

    def __init__(self, pixmap, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self._scale = 1.0
        self._offset = QPointF(0, 0)
        self._zoomed = False
        self._dragging = False
        self._may_be_click = False
        self._drag_start = QPointF()
        self._offset_at_drag_start = QPointF()
        self.setMinimumSize(300, 200)
        self.setMouseTracking(True)
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        self.setStyleSheet("background: #0b0b14;")

    def showEvent(self, event):
        super().showEvent(event)
        # Defer fitting until the widget has its final geometry.
        QTimer.singleShot(0, self._fit_to_window)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._zoomed:
            self._fit_to_window()

    def _fit_to_window(self):
        if self._pixmap.isNull() or self._pixmap.width() == 0 or self._pixmap.height() == 0:
            self._scale = 1.0
            self._offset = QPointF(0, 0)
            self._zoomed = False
            self.update()
            return
        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return
        sw = w / self._pixmap.width()
        sh = h / self._pixmap.height()
        self._scale = min(sw, sh, 1.0)
        self._offset = QPointF(0, 0)
        self._zoomed = False
        self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        self.update()

    def _zoom_step(self, factor):
        """Zoom by a factor around the center of the view, keeping the image centered."""
        if self._pixmap.isNull() or self._pixmap.width() == 0 or self._pixmap.height() == 0:
            return
        old_scale = self._scale
        new_scale = max(0.1, min(10.0, old_scale * factor))
        # Scale the existing offset so the image stays where it is relative to center
        ratio = new_scale / old_scale
        self._offset = self._offset * ratio
        self._scale = new_scale
        self._zoomed = (abs(new_scale - self._fit_scale()) > 0.01)
        self.update()

    def _fit_scale(self):
        if self._pixmap.isNull() or self._pixmap.width() == 0 or self._pixmap.height() == 0:
            return 1.0
        return min(1.0, self.width() / self._pixmap.width(), self.height() / self._pixmap.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#0b0b14"))
        if self._pixmap.isNull():
            return
        w = self._pixmap.width() * self._scale
        h = self._pixmap.height() * self._scale
        x = (self.width() - w) / 2 + self._offset.x()
        y = (self.height() - h) / 2 + self._offset.y()
        painter.drawPixmap(QRectF(x, y, w, h), self._pixmap,
                           QRectF(0, 0, self._pixmap.width(), self._pixmap.height()))

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.15 if delta > 0 else 1 / 1.15
        self._zoom_step(factor)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position()
            self._offset_at_drag_start = QPointF(self._offset)
            self._may_be_click = True
            self._dragging = False
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            pos = event.position()
            if self._may_be_click and (pos - self._drag_start).manhattanLength() > 4:
                self._may_be_click = False
                self._dragging = True
                self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
            if self._dragging:
                self._offset = self._offset_at_drag_start + (pos - self._drag_start)
                self.update()
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False
            self._may_be_click = False
            self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            event.accept()

    def mouseDoubleClickEvent(self, event):
        self._fit_to_window()
        event.accept()


class ImagePopoutDialog(QDialog):
    """Enlarged popout window for screenshots with zoom/pan support."""

    MAX_W = 1000
    MAX_H = 700
    MIN_W = 500
    MIN_H = 350
    PAD = 40

    def __init__(self, pixmap, title, parent=None):
        super().__init__(parent, Qt.WindowType.WindowCloseButtonHint)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        viewer = ZoomImageViewer(pixmap)
        layout.addWidget(viewer)
        self._size_to_image(pixmap)

    def _size_to_image(self, pixmap):
        if pixmap.isNull() or pixmap.width() == 0 or pixmap.height() == 0:
            self.resize(self.MIN_W, self.MIN_H)
            return
        img_w = pixmap.width()
        img_h = pixmap.height()
        scale = min(1.0, (self.MAX_W - self.PAD) / img_w, (self.MAX_H - self.PAD) / img_h)
        w = max(self.MIN_W, int(img_w * scale) + self.PAD)
        h = max(self.MIN_H, int(img_h * scale) + self.PAD)
        self.resize(w, h)


class ZipDownloadBox(BlackGlassPanel):
    """Alert box shown when a session is closed, offering a zip of all shared files/screenshots."""

    def __init__(self, session, parent=None):
        super().__init__(parent, radius=8, border_color=(220, 60, 60, 50))
        self._session = session

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)

        header = QLabel("  !  User closed this Rift")
        header.setFont(QFont(ADMIN_MONO, 9, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {PALETTE['error']}; background: transparent; border: none;")
        layout.addWidget(header)

        msg = QLabel("Save any important documents before closing this session or exiting.")
        msg.setFont(QFont(ADMIN_MONO, 8))
        msg.setStyleSheet(f"color: {PALETTE['text']}; background: transparent; border: none;")
        msg.setWordWrap(True)
        layout.addWidget(msg)

        download_btn = QPushButton("Download Zip")
        download_btn.setFixedHeight(30)
        download_btn.setFont(QFont(ADMIN_MONO, 8, QFont.Weight.Bold))
        download_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        download_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(220, 60, 60, 25);
                color: {PALETTE['error']};
                border: 1px solid rgba(220, 60, 60, 60);
                border-radius: 4px;
                padding: 0 14px;
            }}
            QPushButton:hover {{ background: rgba(220, 60, 60, 45); }}
        """)
        download_btn.clicked.connect(self._download_zip)
        layout.addWidget(download_btn)

    def _download_zip(self):
        try:
            files = []  # list of (filename, bytes)
            screenshot_idx = 0
            for r in self._session.results:
                if r["type"] in ("file", "file_drop"):
                    payload = r.get("content", {})
                    if isinstance(payload, dict):
                        path = payload.get("file", "")
                        data = payload.get("data", "")
                        if data:
                            name = Path(path).name or f"file_{len(files) + 1}"
                            files.append((name, _b64.b64decode(data)))
                elif r["type"] == "files":
                    payload = r.get("content", {})
                    if isinstance(payload, dict):
                        for rel, b64_data in payload.get("files", {}).items():
                            if b64_data:
                                files.append((rel, _b64.b64decode(b64_data)))
                elif r["type"] == "screenshot" and isinstance(r.get("content"), str) and r["content"] != "Received":
                    screenshot_idx += 1
                    files.append((f"screenshot_{screenshot_idx}.png", _b64.b64decode(r["content"])))

            if not files:
                return

            default_name = f"rift_{self._session.id}_files.zip"
            path, _ = QFileDialog.getSaveFileName(self, "Save Zip", default_name, "Zip files (*.zip)")
            if not path:
                return

            with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for name, data in files:
                    zf.writestr(name, data)
        except Exception:
            pass


class RiftConfirmDialog(QDialog):
    """On-theme confirmation dialog with a title, message, and two buttons."""

    def __init__(self, title, message, confirm_text="Yes", cancel_text="Cancel", danger=False, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(420, 200)
        self._confirmed = False

        container = QFrame(self)
        container.setGeometry(0, 0, 420, 200)
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

        title_lbl = QLabel(title)
        title_lbl.setFont(QFont(ADMIN_MONO, 11, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {PALETTE['text']}; background: transparent; border: none;")
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_lbl)

        msg_lbl = QLabel(message)
        msg_lbl.setFont(QFont(ADMIN_MONO, 9))
        msg_lbl.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none;")
        msg_lbl.setWordWrap(True)
        msg_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(msg_lbl, 1)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        cancel_btn = QPushButton(cancel_text)
        cancel_btn.setFixedHeight(32)
        cancel_btn.setFont(QFont(ADMIN_MONO, 8, QFont.Weight.Bold))
        cancel_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 12);
                color: {PALETTE['muted']};
                border: 1px solid rgba(255, 255, 255, 25);
                border-radius: 6px;
            }}
            QPushButton:hover {{ background: rgba(255, 255, 255, 22); color: {PALETTE['text']}; }}
        """)
        cancel_btn.clicked.connect(self.reject)

        confirm_btn = QPushButton(confirm_text)
        confirm_btn.setFixedHeight(32)
        confirm_btn.setFont(QFont(ADMIN_MONO, 8, QFont.Weight.Bold))
        confirm_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        if danger:
            confirm_btn.setStyleSheet("""
                QPushButton {
                    background: rgba(220, 60, 60, 35);
                    color: #ff8a8a;
                    border: 1px solid rgba(220, 60, 60, 60);
                    border-radius: 6px;
                }
                QPushButton:hover { background: rgba(220, 60, 60, 55); }
            """)
        else:
            confirm_btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(154, 89, 182, 35);
                    color: {PALETTE['accent_bright']};
                    border: 1px solid rgba(154, 89, 182, 60);
                    border-radius: 6px;
                }}
                QPushButton:hover {{ background: rgba(154, 89, 182, 55); }}
            """)
        confirm_btn.clicked.connect(self.accept)

        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(confirm_btn)
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


class FileResultBox(BlackGlassPanel):
    """Box showing a downloadable file result."""

    def __init__(self, title, file_name, file_data_b64, parent=None):
        super().__init__(parent, radius=8, border_color=(40, 220, 100, 40))
        self._file_name = file_name
        self._file_data_b64 = file_data_b64

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        header = QLabel(f"  v  {title}")
        header.setFont(QFont(ADMIN_MONO, 8, QFont.Weight.Bold))
        header.setStyleSheet(f"color: #28dc64; background: transparent; border: none;")
        layout.addWidget(header)

        file_row = QHBoxLayout()
        file_row.setSpacing(8)
        name_label = QLabel(file_name)
        name_label.setFont(QFont(ADMIN_MONO, 8))
        name_label.setStyleSheet(f"color: {PALETTE['text']}; background: transparent; border: none;")
        name_label.setWordWrap(True)
        file_row.addWidget(name_label, 1)

        download_btn = QPushButton("Download")
        download_btn.setFixedHeight(26)
        download_btn.setFont(QFont(ADMIN_MONO, 8, QFont.Weight.Bold))
        download_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        download_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(40, 220, 100, 25);
                color: #28dc64;
                border: 1px solid rgba(40, 220, 100, 60);
                border-radius: 4px;
                padding: 0 10px;
            }}
            QPushButton:hover {{ background: rgba(40, 220, 100, 45); }}
        """)
        download_btn.clicked.connect(self._download)
        file_row.addWidget(download_btn)
        layout.addLayout(file_row)

    def _download(self):
        try:
            path, _ = QFileDialog.getSaveFileName(self, "Save File", self._file_name)
            if not path:
                return
            data = _b64.b64decode(self._file_data_b64)
            Path(path).write_bytes(data)
        except Exception as e:
            pass


class FilesResultBox(BlackGlassPanel):
    """Box showing multiple downloadable file results."""

    def __init__(self, title, files_dict, parent=None):
        super().__init__(parent, radius=8, border_color=(40, 220, 100, 40))
        self._files_dict = files_dict

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        header = QLabel(f"  v  {title}")
        header.setFont(QFont(ADMIN_MONO, 8, QFont.Weight.Bold))
        header.setStyleSheet(f"color: #28dc64; background: transparent; border: none;")
        layout.addWidget(header)

        for file_name, file_data_b64 in files_dict.items():
            file_row = QHBoxLayout()
            file_row.setSpacing(8)
            name_label = QLabel(file_name)
            name_label.setFont(QFont(ADMIN_MONO, 8))
            name_label.setStyleSheet(f"color: {PALETTE['text']}; background: transparent; border: none;")
            name_label.setWordWrap(True)
            file_row.addWidget(name_label, 1)

            download_btn = QPushButton("Download")
            download_btn.setFixedHeight(24)
            download_btn.setFont(QFont(ADMIN_MONO, 7, QFont.Weight.Bold))
            download_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            download_btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(40, 220, 100, 25);
                    color: #28dc64;
                    border: 1px solid rgba(40, 220, 100, 60);
                    border-radius: 4px;
                    padding: 0 8px;
                }}
                QPushButton:hover {{ background: rgba(40, 220, 100, 45); }}
            """)
            download_btn.clicked.connect(lambda checked, fn=file_name, fd=file_data_b64: self._download(fn, fd))
            file_row.addWidget(download_btn)
            layout.addLayout(file_row)

    def _download(self, file_name, file_data_b64):
        try:
            path, _ = QFileDialog.getSaveFileName(self, "Save File", file_name)
            if not path:
                return
            data = _b64.b64decode(file_data_b64)
            Path(path).write_bytes(data)
        except Exception:
            pass


class CollapsibleBox(BlackGlassPanel):
    """A collapsible box for command outputs, file contents, etc."""

    def __init__(self, title, content, result_type="output", parent=None):
        color_map = {
            "output": PALETTE["text"],
            "screenshot": "#dcc828",
            "file": "#28dc64",
            "error": PALETTE["error"],
            "terminal": "#8c3cdc",
        }
        color = color_map.get(result_type, PALETTE["text"])
        super().__init__(parent, radius=8, border_color=(80, 40, 120, 25))
        self._collapsed = True
        self._content = content
        self._title = title
        self._color = color

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        # Header row — toggle arrow + title + popout button
        header = QWidget()
        header.setStyleSheet("background: transparent; border: none;")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)

        title_btn = QPushButton(f"  >  {title}")
        title_btn.setFont(QFont(ADMIN_MONO, 8, QFont.Weight.Bold))
        title_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {color};
                border: none;
                text-align: left;
                padding: 2px 0px;
            }}
            QPushButton:hover {{ color: {PALETTE['accent_bright']}; }}
        """)
        title_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        title_btn.clicked.connect(self._toggle)
        self._header = title_btn
        header_layout.addWidget(title_btn, 1)

        popout_btn = QPushButton("↗")
        popout_btn.setFixedSize(20, 20)
        popout_btn.setFont(QFont(ADMIN_MONO, 8, QFont.Weight.Bold))
        popout_btn.setToolTip("Open in popout")
        popout_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {PALETTE['muted']};
                border: 1px solid rgba(255, 255, 255, 25);
                border-radius: 4px;
            }}
            QPushButton:hover {{ color: {PALETTE['accent_bright']}; border: 1px solid rgba(255, 255, 255, 55); }}
        """)
        popout_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        popout_btn.clicked.connect(self._popout)
        header_layout.addWidget(popout_btn)

        layout.addWidget(header)

        # Content area (hidden when collapsed)
        self._content_label = QLabel(content)
        self._content_label.setFont(QFont(ADMIN_MONO, 8))
        self._content_label.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none;")
        self._content_label.setWordWrap(True)
        self._content_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        self._content_label.setVisible(False)
        layout.addWidget(self._content_label)

    def _toggle(self):
        self._collapsed = not self._collapsed
        self._content_label.setVisible(not self._collapsed)
        arrow = "v" if not self._collapsed else ">"
        self._header.setText(f"  {arrow}  {self._title}")

    def _popout(self):
        dialog = ResultPopoutDialog(self._title, self._content, self)
        dialog.exec()

    def mouseDoubleClickEvent(self, event):
        # Double-clicking the whole box opens the popout
        self._popout()
        event.accept()


# ------------------------------------------------------------------
# Session card — shown in the session list
# ------------------------------------------------------------------
class SessionCard(QFrame):
    """A clickable card representing a session in the list, with animated edge glow."""

    card_clicked = Signal(str)  # emits session id

    STATE_COLORS = {
        "waiting":    ((140, 60, 220), (200, 120, 255)),  # border, glow
        "connected":  ((40, 200, 90), (80, 255, 140)),
        "stale":      ((200, 60, 60), (255, 100, 100)),
        "inactive":   ((60, 60, 80), (90, 90, 110)),
    }

    def __init__(self, session, parent=None):
        card_state = getattr(session, "card_state", "inactive")
        border_color, glow_color = self.STATE_COLORS.get(card_state, self.STATE_COLORS["inactive"])
        super().__init__(parent)
        self._radius = 10
        self._border_color = (*border_color, 30)
        self._session_id = session.id
        self._card_state = card_state
        self._glow_color = glow_color
        self._border_color_rgb = border_color
        self.setFixedHeight(64)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

        # Edge animation only for waiting state
        self._anim_phase = 0.0
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._anim_tick)
        if card_state == "waiting":
            self._anim_timer.start(16)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(12)

        self._dot = QLabel()
        self._dot.setFixedSize(10, 10)
        self._dot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self._dot)

        # Name + host info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        self._name_label = QLabel()
        self._name_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        self._name_label.setStyleSheet(f"color: {PALETTE['text']}; background: transparent; border: none;")
        self._name_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        info_layout.addWidget(self._name_label)

        self._host_label = QLabel()
        self._host_label.setFont(QFont(ADMIN_MONO, 7))
        self._host_label.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none;")
        self._host_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        info_layout.addWidget(self._host_label)

        layout.addLayout(info_layout, 1)

        self._state_label = QLabel()
        self._state_label.setFont(QFont(ADMIN_MONO, 7, QFont.Weight.Bold))
        self._state_label.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none; letter-spacing: 1px;")
        self._state_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self._state_label)

        self._apply_session(session)

    def _apply_session(self, session):
        """Apply session data to child widgets and colors."""
        card_state = getattr(session, "card_state", "inactive")
        border_color, glow_color = self.STATE_COLORS.get(card_state, self.STATE_COLORS["inactive"])

        self._session_id = session.id
        self._card_state = card_state
        self._glow_color = glow_color
        self._border_color_rgb = border_color
        self._border_color = (*border_color, 30)

        dot_map = {
            "waiting": PALETTE["accent_bright"],
            "connected": PALETTE["success"],
            "stale": PALETTE["error"],
            "inactive": PALETTE["muted"],
        }
        self._dot.setStyleSheet(f"background: {dot_map.get(card_state, PALETTE['muted'])}; border-radius: 5px; border: none;")

        self._name_label.setText(session.name)

        ts_parts = []
        if session.opened_at:
            ts_parts.append(f"opened {session.opened_at}")
        if session.last_seen:
            try:
                seen_dt = datetime.fromisoformat(session.last_seen)
                delta = datetime.now() - seen_dt
                if delta.total_seconds() < 60:
                    ts_parts.append("last seen just now")
                elif delta.total_seconds() < 3600:
                    ts_parts.append(f"last seen {int(delta.total_seconds() // 60)}m ago")
                else:
                    ts_parts.append(f"last seen {int(delta.total_seconds() // 3600)}h ago")
            except Exception:
                pass
        timestamp_text = "  -  ".join(ts_parts) if ts_parts else ""
        self._host_label.setText(f"{session.user}@{session.host}{('  -  ' + timestamp_text) if timestamp_text else ''}")

        state_info, state_color = STATE_INFO.get(session.orb_state, ("UNKNOWN", PALETTE["muted"]))
        self._state_label.setText(state_info)
        self._state_label.setStyleSheet(f"color: {state_color}; background: transparent; border: none; letter-spacing: 1px;")

        # Start/stop animation based on state
        if card_state == "waiting" and not self._anim_timer.isActive():
            self._anim_timer.start(16)
        elif card_state != "waiting" and self._anim_timer.isActive():
            self._anim_timer.stop()
            self.update()

    def update_session(self, session):
        """Update the card in-place with new session data."""
        old_state = self._card_state
        self._apply_session(session)
        if old_state != self._card_state:
            self.update()

    def _anim_tick(self):
        self._anim_phase += 0.0025  # slow travel
        if self._anim_phase >= 1.0:
            self._anim_phase = 0.0
        self.update()

    def mousePressEvent(self, event):
        """Emit click on press — works even if a refresh reparents the card."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.card_clicked.emit(self._session_id)
            event.accept()
        else:
            super().mousePressEvent(event)

    def paintEvent(self, event):
        # Draw the black glass panel background ourselves (since we no longer inherit it)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        radius = self._radius

        t = THEME
        fill_grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        fill_grad.setColorAt(0, QColor(*t["panel_grad_top"]))
        fill_grad.setColorAt(0.5, QColor(*t["panel_grad_mid"]))
        fill_grad.setColorAt(1, QColor(*t["panel_grad_bot"]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(fill_grad))
        painter.drawRoundedRect(rect, radius, radius)

        sheen_grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.top() + rect.height() * 0.25)
        sheen_grad.setColorAt(0, QColor(*t["sheen"]))
        sheen_grad.setColorAt(1, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(sheen_grad))
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius, radius)

        pen = QPen(QColor(*self._border_color))
        pen.setWidthF(1.2)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius, radius)

        painter.end()

        # Only waiting state gets the animated traveling glow
        if self._card_state == "waiting":
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            rect = self.rect().adjusted(2, 2, -2, -2)
            radius = self._radius - 2

            path = QPainterPath()
            path.addRoundedRect(rect, radius, radius)

            total_len = path.length()
            if total_len > 0:
                seg_percent = 0.20
                start_t = self._anim_phase
                end_t = start_t + seg_percent
                r, g, b = self._glow_color

                steps = 60
                prev_pt = None
                for i in range(steps + 1):
                    t = start_t + (end_t - start_t) * (i / steps)
                    if t > 1.0:
                        t -= 1.0
                    pt = path.pointAtPercent(t)

                    if prev_pt is not None:
                        fade = 1.0 - (i / steps)
                        glow_color = QColor(r, g, b, int(35 * fade))
                        painter.setPen(QPen(glow_color, 3))
                        painter.drawLine(prev_pt, pt)
                        core_color = QColor(min(r + 40, 255), min(g + 40, 255), min(b + 40, 255), int(120 * fade))
                        painter.setPen(QPen(core_color, 1))
                        painter.drawLine(prev_pt, pt)

                    prev_pt = pt

            painter.end()


# ------------------------------------------------------------------
# Session list view (dashboard)
# ------------------------------------------------------------------
class SessionListView(QWidget):
    """Dashboard showing active and inactive sessions."""

    session_selected = Signal(str)
    new_session_requested = Signal()
    cleanup_stale = Signal()
    refresh_requested = Signal()
    purge_closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._sessions = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Header row
        header_row = QHBoxLayout()
        header_row.setSpacing(12)

        title = QLabel("ACTIVE SESSIONS")
        title.setFont(QFont(ADMIN_MONO, 10, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {ADMIN_HUD}; background: transparent; border: none; letter-spacing: 3px;")
        header_row.addWidget(title)
        header_row.addStretch()

        cleanup_btn = QPushButton("Clean Up Stale")
        cleanup_btn.setFixedHeight(32)
        cleanup_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
        cleanup_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cleanup_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {PALETTE['muted']};
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 6px;
                padding: 0 14px;
            }}
            QPushButton:hover {{
                color: {PALETTE['text']};
                border: 1px solid rgba(255, 255, 255, 40);
            }}
        """)
        cleanup_btn.clicked.connect(self.cleanup_stale.emit)
        header_row.addWidget(cleanup_btn)

        purge_btn = QPushButton("Purge Closed")
        purge_btn.setFixedHeight(32)
        purge_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
        purge_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        purge_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {PALETTE['error']};
                border: 1px solid rgba(239, 68, 68, 30);
                border-radius: 6px;
                padding: 0 14px;
            }}
            QPushButton:hover {{
                color: #ff5555;
                border: 1px solid rgba(239, 68, 68, 60);
            }}
        """)
        purge_btn.clicked.connect(self.purge_closed.emit)
        header_row.addWidget(purge_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedHeight(32)
        refresh_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
        refresh_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {PALETTE['muted']};
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 6px;
                padding: 0 14px;
            }}
            QPushButton:hover {{
                color: {PALETTE['text']};
                border: 1px solid rgba(255, 255, 255, 40);
            }}
        """)
        refresh_btn.clicked.connect(self.refresh_requested.emit)
        header_row.addWidget(refresh_btn)

        new_btn = QPushButton("+ New Session")
        new_btn.setFixedHeight(32)
        new_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
        new_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        new_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(155, 89, 182, 30);
                color: {PALETTE['accent_bright']};
                border: 1px solid rgba(155, 89, 182, 80);
                border-radius: 6px;
                padding: 0 16px;
            }}
            QPushButton:hover {{
                background: rgba(155, 89, 182, 50);
                border: 1px solid rgba(155, 89, 182, 120);
            }}
        """)
        new_btn.clicked.connect(self.new_session_requested.emit)
        header_row.addWidget(new_btn)
        layout.addLayout(header_row)

        # Stats row
        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)
        self.stat_active = StatCard("Active Sessions", "0", accent=PALETTE["success"])
        self.stat_total = StatCard("Total Sessions", "0")
        self.stat_uptime = StatCard("Console Uptime", "00:00:00")
        stats_row.addWidget(self.stat_active)
        stats_row.addWidget(self.stat_total)
        stats_row.addWidget(self.stat_uptime)
        layout.addLayout(stats_row)

        # Active sessions section
        self._active_label = QLabel("ACTIVE")
        self._active_label.setFont(QFont(ADMIN_MONO, 8, QFont.Weight.Bold))
        self._active_label.setStyleSheet(f"color: {PALETTE['success']}; background: transparent; border: none; letter-spacing: 2px;")
        layout.addWidget(self._active_label)

        self._active_scroll = QScrollArea()
        self._active_scroll.setWidgetResizable(True)
        self._active_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._active_container = QWidget()
        self._active_container.setStyleSheet("background: transparent;")
        self._active_layout = QVBoxLayout(self._active_container)
        self._active_layout.setContentsMargins(0, 0, 0, 0)
        self._active_layout.setSpacing(8)
        self._active_layout.addStretch()
        self._active_scroll.setWidget(self._active_container)
        layout.addWidget(self._active_scroll, 1)

        # Fallback click detector on the scroll viewport — catches clicks that
        # the card itself may miss due to refresh/reparent timing.
        self._active_scroll.viewport().installEventFilter(self)

        # Inactive sessions (collapsed)
        self._inactive_toggle = QPushButton("v  INACTIVE / EXPIRED")
        self._inactive_toggle.setFont(QFont(ADMIN_MONO, 8, QFont.Weight.Bold))
        self._inactive_toggle.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {PALETTE['muted']};
                border: none;
                text-align: left;
                padding: 4px 0;
                letter-spacing: 2px;
            }}
            QPushButton:hover {{ color: {PALETTE['text']}; }}
        """)
        self._inactive_toggle.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._inactive_collapsed = False
        self._inactive_toggle.clicked.connect(self._toggle_inactive)
        layout.addWidget(self._inactive_toggle)

        self._inactive_scroll = QScrollArea()
        self._inactive_scroll.setWidgetResizable(True)
        self._inactive_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._inactive_container = QWidget()
        self._inactive_container.setStyleSheet("background: transparent;")
        self._inactive_layout = QVBoxLayout(self._inactive_container)
        self._inactive_layout.setContentsMargins(0, 0, 0, 0)
        self._inactive_layout.setSpacing(8)
        self._inactive_layout.addStretch()
        self._inactive_scroll.setWidget(self._inactive_container)
        self._inactive_scroll.setVisible(False)
        layout.addWidget(self._inactive_scroll, 0)

        # Fallback click detector for inactive list too
        self._inactive_scroll.viewport().installEventFilter(self)

        # Poll status footer
        self._poll_status_label = QLabel("Firebase: waiting for first poll...")
        self._poll_status_label.setFont(QFont(ADMIN_MONO, 7))
        self._poll_status_label.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none; padding: 4px 0;")
        layout.addWidget(self._poll_status_label)

    def _toggle_inactive(self):
        self._inactive_collapsed = not self._inactive_collapsed
        self._inactive_scroll.setVisible(self._inactive_collapsed)
        prefix = "v" if self._inactive_collapsed else ">"
        self._inactive_toggle.setText(f"{prefix}  INACTIVE / EXPIRED")

    def eventFilter(self, watched, event):
        """Fallback: route clicks on the scroll viewport to the card beneath."""
        if event.type() == QEvent.Type.MouseButtonPress:
            mouse_event = event
            if mouse_event.button() == Qt.MouseButton.LeftButton:
                viewport = watched
                pos = viewport.mapTo(self._active_container if viewport == self._active_scroll.viewport() else self._inactive_container, mouse_event.pos())
                target = self._active_container.childAt(pos) if viewport == self._active_scroll.viewport() else self._inactive_container.childAt(pos)
                card = None
                w = target
                while w is not None:
                    if isinstance(w, SessionCard):
                        card = w
                        break
                    w = w.parent()
                if card is not None:
                    self.session_selected.emit(card._session_id)
                    return True
        return super().eventFilter(watched, event)

    def set_sessions(self, sessions):
        self._sessions = sessions
        self._refresh()

    def _refresh(self):
        active = [s for s in self._sessions if s.status == "active"]
        inactive = [s for s in self._sessions if s.status != "active"]

        self.stat_active.set_value(str(len(active)), PALETTE["success"])
        self.stat_total.set_value(str(len(self._sessions)))

        # Reuse existing cards where possible; this avoids destroying the card under a click.
        self._sync_cards(self._active_layout, active)
        self._sync_cards(self._inactive_layout, inactive)

    def _sync_cards(self, layout, sessions):
        """Update layout to match session list, preserving existing cards."""
        # Collect existing cards (skip the trailing stretch)
        existing_cards = []
        for i in range(layout.count() - 1):
            item = layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), SessionCard):
                existing_cards.append(item.widget())

        existing_by_id = {c._session_id: c for c in existing_cards}
        new_order = []

        for s in sessions:
            card = existing_by_id.pop(s.id, None)
            if card is None:
                card = SessionCard(s)
                card.card_clicked.connect(self.session_selected.emit)
                layout.insertWidget(layout.count() - 1, card)
            else:
                card.update_session(s)
            new_order.append(card)

        # Move cards to correct order
        for idx, card in enumerate(new_order):
            layout.removeWidget(card)
            layout.insertWidget(idx, card)

        # Remove any cards no longer in the list
        for card in existing_by_id.values():
            card.deleteLater()
            layout.removeWidget(card)

    def update_uptime(self, seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        self.stat_uptime.set_value(f"{h:02d}:{m:02d}:{s:02d}")

    def set_poll_status(self, text):
        self._poll_status_label.setText(text)


# ------------------------------------------------------------------
# Session detail view — three states: blank, portal opening, connected
# ------------------------------------------------------------------
class SessionDetailView(QWidget):
    """Detail view for a single session.

    Three states:
      1. Blank — no portal open, just an 'Open Portal' button
      2. Opening — portal animation playing
      3. Connected — commands, quick actions, results, chat
    """

    back_requested = Signal()
    command_sent = Signal(str, str)  # (session_id, command_text)
    quick_action = Signal(str, str)  # (session_id, action_type)
    portal_open_requested = Signal(str)  # (session_id) — admin clicked Open Portal
    close_session_requested = Signal(str)  # (session_id) — close/end session
    chat_sent = Signal(str, str)           # (session_id, text) — chat message

    # Command → orb state mapping
    COMMAND_MAP = {
        ".screenshot": "screenshot",
        ".terminal": "terminal",
        ".pause": "paused",
        ".feed": "feedme",
        ".scan": "command",
        ".delete": "command",
        ".view": "command",
        ".fetch": "command",
        ".fetchall": "command",
        ".reset": "idle",
        ".pulse": "test_pulse",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._session = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        # Top bar
        top_bar = QHBoxLayout()
        top_bar.setSpacing(12)

        back_btn = QPushButton("< Back")
        back_btn.setFixedHeight(30)
        back_btn.setFont(QFont("Segoe UI", 9))
        back_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        back_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {PALETTE['muted']};
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 6px;
                padding: 0 14px;
            }}
            QPushButton:hover {{ color: {PALETTE['text']}; border: 1px solid rgba(255, 255, 255, 40); }}
        """)
        back_btn.clicked.connect(self.back_requested.emit)
        top_bar.addWidget(back_btn)

        self._title_label = QLabel("Session")
        self._title_label.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self._title_label.setStyleSheet(f"color: {PALETTE['text']}; background: transparent; border: none;")
        top_bar.addWidget(self._title_label, 1)

        self._state_badge = QLabel("IDLE")
        self._state_badge.setFont(QFont(ADMIN_MONO, 8, QFont.Weight.Bold))
        self._state_badge.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none; letter-spacing: 2px;")
        top_bar.addWidget(self._state_badge)
        top_bar.addSpacing(12)

        # Close session button
        close_session_btn = QPushButton("Close Session")
        close_session_btn.setFixedHeight(30)
        close_session_btn.setFont(QFont("Segoe UI", 9))
        close_session_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_session_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(200, 60, 60, 30);
                color: #e07070;
                border: 1px solid rgba(200, 60, 60, 80);
                border-radius: 6px;
                padding: 0 14px;
            }}
            QPushButton:hover {{
                background: rgba(200, 60, 60, 60);
                border: 1px solid rgba(200, 60, 60, 140);
                color: #f09090;
            }}
        """)
        close_session_btn.clicked.connect(self._close_session)
        top_bar.addWidget(close_session_btn)
        layout.addLayout(top_bar)

        # Stacked content: blank / opening / connected
        self._content_stack = QStackedWidget()
        self._content_stack.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._waiting_for_client = False

        # ---- State 0: Blank (no portal open) ----
        blank_widget = QWidget()
        blank_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        blank_layout = QVBoxLayout(blank_widget)
        blank_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        blank_layout.setSpacing(20)

        blank_hint = QLabel("No portal open for this session.")
        blank_hint.setFont(QFont("Segoe UI", 12))
        blank_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        blank_hint.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none;")
        blank_layout.addWidget(blank_hint)

        self._open_portal_btn = QPushButton("Open Portal For This Session")
        self._open_portal_btn.setFixedSize(260, 44)
        self._open_portal_btn.setFont(QFont("Segoe UI", 11, QFont.Weight.Medium))
        self._open_portal_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._open_portal_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(40, 120, 220, 40);
                color: #5096e0;
                border: 1px solid rgba(40, 120, 220, 100);
                border-radius: 8px;
            }}
            QPushButton:hover {{
                background: rgba(40, 120, 220, 70);
                border: 1px solid rgba(40, 120, 220, 160);
                color: #80b0f0;
            }}
        """)
        self._open_portal_btn.clicked.connect(self._start_portal_open)
        blank_layout.addWidget(self._open_portal_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self._blank_widget = blank_widget
        self._content_stack.addWidget(blank_widget)

        # ---- State 1: Portal opening animation ----
        self._portal_anim = PortalOpeningWidget()
        self._portal_anim.admin_animation_done.connect(self._on_admin_animation_done_in_detail)
        self._content_stack.addWidget(self._portal_anim)

        # ---- State 2: Connected (commands + chat) ----
        connected_widget = QWidget()
        connected_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        conn_layout = QVBoxLayout(connected_widget)
        conn_layout.setContentsMargins(0, 0, 0, 0)
        conn_layout.setSpacing(10)

        # Portal open banner
        banner = QLabel("PORTAL NOW OPEN")
        banner.setFont(QFont(ADMIN_MONO, 9, QFont.Weight.Bold))
        banner.setStyleSheet(f"color: {PALETTE['success']}; background: transparent; border: none; letter-spacing: 3px;")
        conn_layout.addWidget(banner)

        # Main split: left (commands + results) | right (chat)
        split = QHBoxLayout()
        split.setSpacing(12)

        # Left panel
        left_panel = BlackGlassPanel(connected_widget, radius=12)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(14, 14, 14, 14)
        left_layout.setSpacing(10)

        # Quick actions — only Screenshot, Feed, Pause, Reset
        actions_label = QLabel("QUICK ACTIONS")
        actions_label.setFont(QFont(ADMIN_MONO, 7, QFont.Weight.Bold))
        actions_label.setStyleSheet(f"color: {ADMIN_HUD_DIM}; background: transparent; border: none; letter-spacing: 2px;")
        left_layout.addWidget(actions_label)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(6)
        self.btn_screenshot = ControlButton("Screenshot", "220,200,40")
        self.btn_feed = ControlButton("Feed", "40,220,100")
        self.btn_pause = ControlButton("Pause", "255,180,50")
        self.btn_pulse = ControlButton("Pulse", "220,30,40")
        self.btn_idle = ControlButton("Reset", "139,139,154")
        actions_row.addWidget(self.btn_screenshot)
        actions_row.addWidget(self.btn_feed)
        actions_row.addWidget(self.btn_pause)
        actions_row.addWidget(self.btn_pulse)
        actions_row.addWidget(self.btn_idle)
        left_layout.addLayout(actions_row)

        # Command input
        cmd_label = QLabel("COMMAND INPUT  (.help for list)")
        cmd_label.setFont(QFont(ADMIN_MONO, 7, QFont.Weight.Bold))
        cmd_label.setStyleSheet(f"color: {ADMIN_HUD_DIM}; background: transparent; border: none; letter-spacing: 2px;")
        left_layout.addWidget(cmd_label)

        self._cmd_input = QLineEdit()
        self._cmd_input.setPlaceholderText("Type a command (e.g. .scan, .screenshot, .terminal)...")
        self._cmd_input.setFixedHeight(34)
        self._cmd_input.setFont(QFont(ADMIN_MONO, 10))
        self._cmd_input.setStyleSheet(f"""
            QLineEdit {{
                background: {PALETTE['input_bg']};
                color: {PALETTE['text']};
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 6px;
                padding: 0 12px;
            }}
            QLineEdit:focus {{ border: 1px solid {PALETTE['accent']}; }}
        """)
        self._cmd_input.returnPressed.connect(self._send_command)
        left_layout.addWidget(self._cmd_input)

        # Results area
        results_label = QLabel("OUTPUT")
        results_label.setFont(QFont(ADMIN_MONO, 7, QFont.Weight.Bold))
        results_label.setStyleSheet(f"color: {ADMIN_HUD_DIM}; background: transparent; border: none; letter-spacing: 2px;")
        left_layout.addWidget(results_label)

        self._results_scroll = QScrollArea()
        self._results_scroll.setWidgetResizable(True)
        self._results_scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{ background: {ADMIN_PANEL}; width: 6px; border: none; }}
            QScrollBar::handle:vertical {{ background: {PALETTE['panel_light']}; border-radius: 3px; }}
        """)
        self._results_container = QWidget()
        self._results_container.setStyleSheet("background: transparent;")
        self._results_layout = QVBoxLayout(self._results_container)
        self._results_layout.setContentsMargins(0, 0, 0, 0)
        self._results_layout.setSpacing(6)
        self._results_layout.addStretch()
        self._results_scroll.setWidget(self._results_container)
        left_layout.addWidget(self._results_scroll, 1)

        split.addWidget(left_panel, 3)

        # Right: inline chat
        chat_panel = BlackGlassPanel(connected_widget, radius=12)
        chat_layout = QVBoxLayout(chat_panel)
        chat_layout.setContentsMargins(12, 12, 12, 12)
        chat_layout.setSpacing(8)

        chat_header = QLabel("CHAT")
        chat_header.setFont(QFont(ADMIN_MONO, 8, QFont.Weight.Bold))
        chat_header.setStyleSheet(f"color: {ADMIN_HUD_DIM}; background: transparent; border: none; letter-spacing: 2px;")
        chat_layout.addWidget(chat_header)

        self._chat_scroll = QScrollArea()
        self._chat_scroll.setWidgetResizable(True)
        self._chat_scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{ background: {ADMIN_PANEL}; width: 6px; border: none; }}
            QScrollBar::handle:vertical {{ background: {PALETTE['panel_light']}; border-radius: 3px; }}
        """)
        self._chat_container = QWidget()
        self._chat_container.setStyleSheet(f"background: {PALETTE['chat_bg']};")
        self._chat_layout = QVBoxLayout(self._chat_container)
        self._chat_layout.setContentsMargins(8, 8, 8, 8)
        self._chat_layout.setSpacing(6)
        self._chat_layout.addStretch()
        self._chat_scroll.setWidget(self._chat_container)
        chat_layout.addWidget(self._chat_scroll, 1)

        chat_input_row = QHBoxLayout()
        chat_input_row.setSpacing(6)
        self._chat_input = QLineEdit()
        self._chat_input.setPlaceholderText("Message...")
        self._chat_input.setFixedHeight(32)
        self._chat_input.setFont(QFont("Segoe UI", 9))
        self._chat_input.setStyleSheet(f"""
            QLineEdit {{
                background: {PALETTE['input_bg']};
                color: {PALETTE['text']};
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 6px;
                padding: 0 10px;
            }}
            QLineEdit:focus {{ border: 1px solid {PALETTE['accent']}; }}
        """)
        self._chat_input.returnPressed.connect(self._send_chat)

        self._chat_send = QPushButton("Send")
        self._chat_send.setFixedHeight(32)
        self._chat_send.setFont(QFont("Segoe UI", 9))
        self._chat_send.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._chat_send.setStyleSheet(f"""
            QPushButton {{
                background: {PALETTE['accent']};
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 0 14px;
            }}
            QPushButton:hover {{ background: {PALETTE['accent_bright']}; }}
        """)
        self._chat_send.clicked.connect(self._send_chat)

        chat_input_row.addWidget(self._chat_input, 1)
        chat_input_row.addWidget(self._chat_send)
        chat_layout.addLayout(chat_input_row)

        # Chat-disabled overlay message (shown until portal is opened)
        self._chat_disabled_label = QLabel("Chat will be available once the portal is open.")
        self._chat_disabled_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._chat_disabled_label.setFont(QFont("Segoe UI", 9))
        self._chat_disabled_label.setStyleSheet(f"color: {PALETTE['muted']}; background: rgba(0,0,0,80); border-radius: 6px; padding: 8px;")
        self._chat_disabled_label.setVisible(True)
        chat_layout.addWidget(self._chat_disabled_label)

        self._chat_input.setEnabled(False)
        self._chat_send.setEnabled(False)

        split.addWidget(chat_panel, 2)
        conn_layout.addLayout(split, 1)

        self._connected_widget = connected_widget
        self._content_stack.addWidget(connected_widget)

        layout.addWidget(self._content_stack, 1)

        # Wire quick actions
        self.btn_screenshot.clicked.connect(lambda: self._quick("screenshot"))
        self.btn_feed.clicked.connect(lambda: self._quick("feedme"))
        self.btn_pause.clicked.connect(lambda: self._quick("paused"))
        self.btn_pulse.clicked.connect(lambda: self._quick("test_pulse"))
        self.btn_idle.clicked.connect(lambda: self._quick("idle"))

    def _on_admin_animation_done_in_detail(self):
        """Local animation reached full size — nothing to do here, handled by widget."""
        pass

    def set_session(self, session):
        self._session = session
        self._title_label.setText(session.name)
        self._update_state_badge()
        self._refresh_chat()
        self._refresh_results()
        # Show appropriate state
        if session.portal_connected:
            self._content_stack.setCurrentWidget(self._connected_widget)
            # Make sure chat is enabled when re-entering a connected session
            self._chat_input.setEnabled(True)
            self._chat_input.setPlaceholderText("Message...")
            self._chat_send.setEnabled(True)
            self._chat_disabled_label.setVisible(False)
        else:
            self._content_stack.setCurrentWidget(self._blank_widget)

    def _start_portal_open(self):
        """Start the portal opening animation."""
        if not self._session:
            return
        self._content_stack.setCurrentWidget(self._portal_anim)
        self._portal_anim.start()
        self.portal_open_requested.emit(self._session.id)
        self._waiting_for_client = True
        # Check immediately if the portal is already confirmed — if so,
        # skip the waiting screen and go straight to connected
        data = _firebase_get(f"sessions/{self._session.id}")
        if isinstance(data, dict):
            po = data.get("portal_opened", {})
            if isinstance(po, dict) and po.get("opened"):
                # Portal already confirmed — go straight to connected view
                QTimer.singleShot(800, self._on_portal_opened)
                return

    def _on_portal_opened(self):
        """Portal handshake complete — switch to connected view and enable chat."""
        if not self._session:
            return
        # Don't bail if _waiting_for_client is False — the session refresh may
        # have detected the connection before the signal arrived
        if self._session.portal_connected and not self._waiting_for_client:
            # Already connected and not waiting — just make sure chat is enabled
            self._chat_input.setEnabled(True)
            self._chat_input.setPlaceholderText("Message...")
            self._chat_send.setEnabled(True)
            self._chat_disabled_label.setVisible(False)
            self._content_stack.setCurrentWidget(self._connected_widget)
            return
        self._waiting_for_client = False
        self._session.portal_connected = True
        self._session.chat.append(("portal", "Portal now open — ready for commands.", datetime.now()))
        self._refresh_chat()
        self._portal_anim.confirm_client_open()
        # Enable chat
        self._chat_input.setEnabled(True)
        self._chat_input.setPlaceholderText("Message...")
        self._chat_send.setEnabled(True)
        self._chat_disabled_label.setVisible(False)
        self._content_stack.setCurrentWidget(self._connected_widget)

    def _send_command(self):
        text = self._cmd_input.text().strip()
        if not text or not self._session:
            return
        self._cmd_input.clear()

        # .help shows command list
        if text == ".help":
            self.add_result("output", "Available Commands", "\n".join(sorted(self.COMMAND_MAP.keys())) + "\n.help")
            return

        # Map command to orb state for visual feedback (use just the command word,
        # so commands with arguments like ".scan C:\\path" still map correctly).
        cmd_word = text.split(None, 1)[0].lower()
        orb_state = self.COMMAND_MAP.get(cmd_word, "command")
        self.quick_action.emit(self._session.id, orb_state)

        # Send the raw .rift command to the portal so it can interpret it
        # The portal handles .rift commands directly
        send_command_to_session(self._session.id, "rift_command", command=text)

        # Add to results
        self.add_result("output", f"$ {text}", f"Command sent: {text}\nWaiting for response...")

    def _send_chat(self):
        text = self._chat_input.text().strip()
        if text and self._session:
            self._chat_input.clear()
            self._add_chat_bubble(text, is_admin=True)
            self._session.chat.append(("admin", text, datetime.now()))
            self.chat_sent.emit(self._session.id, text)

    def _quick(self, action):
        if self._session:
            self.quick_action.emit(self._session.id, action)

    def _close_session(self):
        if self._session:
            self.close_session_requested.emit(self._session.id)

    def add_result(self, result_type, title, content):
        if result_type in ("file", "file_drop"):
            file_path = content.get("file", "") if isinstance(content, dict) else ""
            file_name = Path(file_path).name or "file"
            box = FileResultBox(title, file_name, content.get("data", "") if isinstance(content, dict) else "", self._results_container)
        elif result_type == "files":
            files = content.get("files", {}) if isinstance(content, dict) else {}
            box = FilesResultBox(title, files, self._results_container)
        else:
            box = CollapsibleBox(title, content, result_type)
        self._results_layout.insertWidget(self._results_layout.count() - 1, box)
        QTimer.singleShot(10, lambda: self._results_scroll.verticalScrollBar().setValue(
            self._results_scroll.verticalScrollBar().maximum()))

    def add_close_alert(self, session):
        box = ZipDownloadBox(session, self._results_container)
        self._results_layout.insertWidget(self._results_layout.count() - 1, box)
        QTimer.singleShot(10, lambda: self._results_scroll.verticalScrollBar().setValue(
            self._results_scroll.verticalScrollBar().maximum()))

    def add_screenshot(self, pixmap, title="Screenshot"):
        shot_widget = BlackGlassPanel(self._results_container, radius=8, border_color=(220, 200, 40, 40))
        sl = QVBoxLayout(shot_widget)
        sl.setContentsMargins(8, 8, 8, 8)
        sl.setSpacing(4)
        header = QLabel(f"  v  {title}")
        header.setFont(QFont(ADMIN_MONO, 8, QFont.Weight.Bold))
        header.setStyleSheet(f"color: #dcc828; background: transparent; border: none;")
        sl.addWidget(header)
        img = QLabel()
        img.setPixmap(pixmap.scaled(400, 300, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        img.setStyleSheet("background: transparent; border: none;")
        img.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        img.setToolTip("Click to enlarge")

        def _open_image_popout():
            dialog = ImagePopoutDialog(pixmap, title, self)
            dialog.exec()

        img.mousePressEvent = lambda event: _open_image_popout()
        sl.addWidget(img)
        self._results_layout.insertWidget(self._results_layout.count() - 1, shot_widget)
        QTimer.singleShot(10, lambda: self._results_scroll.verticalScrollBar().setValue(
            self._results_scroll.verticalScrollBar().maximum()))

    def _add_chat_bubble(self, text, is_admin=False):
        bubble = QFrame()
        bubble.setMaximumWidth(280)
        if is_admin:
            bg = PALETTE["bubble_user"]
            color = PALETTE["accent_bright"]
            sender_text = "ADMIN"
        else:
            bg = PALETTE["bubble_atlas"]
            color = PALETTE["text"]
            sender_text = "PORTAL"
        bubble.setStyleSheet(f"""
            QFrame {{
                background: {bg};
                border: 1px solid {PALETTE['bubble_border']};
                border-radius: 8px;
            }}
        """)
        bl = QVBoxLayout(bubble)
        bl.setContentsMargins(10, 6, 10, 6)
        bl.setSpacing(2)
        sender = QLabel(sender_text)
        sender.setFont(QFont(ADMIN_MONO, 7))
        sender.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none;")
        msg = QLabel(text)
        msg.setFont(QFont("Segoe UI", 9))
        msg.setStyleSheet(f"color: {color}; background: transparent; border: none;")
        msg.setWordWrap(True)
        msg.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)
        bl.addWidget(sender)
        bl.addWidget(msg)
        self._chat_layout.insertWidget(self._chat_layout.count() - 1, bubble)
        QTimer.singleShot(10, lambda: self._chat_scroll.verticalScrollBar().setValue(
            self._chat_scroll.verticalScrollBar().maximum()))

    def _refresh_chat(self):
        while self._chat_layout.count() > 1:
            item = self._chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if self._session:
            for sender, text, ts in self._session.chat:
                self._add_chat_bubble(text, is_admin=(sender == "admin"))

    def _refresh_results(self):
        while self._results_layout.count() > 1:
            item = self._results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if self._session:
            for r in self._session.results:
                if r["type"] == "screenshot" and isinstance(r["content"], str) and r["content"] != "Received":
                    try:
                        pm = QPixmap()
                        pm.loadFromData(_b64.b64decode(r["content"]), "PNG")
                        self.add_screenshot(pm, r["title"])
                    except Exception:
                        self.add_result("error", f"Screenshot load failed: {r['title']}", "")
                elif r["type"] == "close_alert":
                    self.add_close_alert(r["content"])
                else:
                    self.add_result(r["type"], r["title"], r["content"])

    def update_state(self, state):
        if self._session:
            self._session.orb_state = state
            self._update_state_badge()

    def _update_state_badge(self):
        if not self._session:
            return
        info, color = STATE_INFO.get(self._session.orb_state, ("UNKNOWN", PALETTE["muted"]))
        self._state_badge.setText(info)
        self._state_badge.setStyleSheet(f"color: {color}; background: transparent; border: none; letter-spacing: 2px;")


# ------------------------------------------------------------------
# Rift Commands List view — "Know Your Superpowers (And Your Limits)"
# ------------------------------------------------------------------
RIFT_COMMANDS = [
    (".scan", "Scan", "Get an idea of the PC you're working on. Lists all mean folders and different paths — drives, user directories, app data locations, and key system paths. Use this first when connecting to a new client to understand the environment."),
    (".view", "View Files", "View file names in specific paths or folders. Usage: .view <path> — lists all files and subdirectories at the given path. Great for browsing what's on the client's machine without opening a terminal."),
    (".terminal", "Terminal", "Interact with the terminal on the client's PC. This requires some knowledge of terminal commands, but you can view the Terminal Commands menu for common commands we've short-coded/aliased for beginner use. Usage: .terminal <command>"),
    (".fetch", "Fetch File", "Fetch a single file from the client's PC. Usage: .fetch <path> — the file is sent back and appears in the output area. Useful for grabbing logs, configs, or specific documents."),
    (".fetchall", "Fetch All", "Fetch all files from a specific folder. Usage: .fetchall <path> — all files in the directory are packaged and sent back. Useful for grabbing entire log folders or config directories."),
    (".delete", "Delete File", "Delete a file on the client's PC. Usage: .delete <path> — permanently removes the file. Use with caution — this action cannot be undone."),
    (".screenshot", "Screenshot", "Request a screenshot from the client's PC. The screenshot is captured and sent back, appearing inline in the output area. The portal glows yellow while the screenshot is in transit."),
    (".pause", "Pause", "Pause the client's portal. The portal shrinks to a small amber dot on the client's side, indicating the connection is paused. Use this when you need the client to wait."),
    (".feed", "Feed Me", "Activate feed me mode on the client's portal. The portal opens a green-ringed black hole, indicating it's ready to receive files via drag-and-drop."),
    (".reset", "Reset", "Reset the client's portal back to idle. Clears any active state (pause, feed, etc.) and returns the portal to its default resting state."),
    (".pulse", "Pulse Test", "Send a red pulse through the client's portal. The portal flashes red, confirming the connection is alive and responsive. Use this as a heartbeat check or to verify the client is still connected."),
]

class CommandListEntry(BlackGlassPanel):
    """Expandable command entry — click to see explanation."""

    def __init__(self, cmd, name, description, parent=None):
        super().__init__(parent, radius=8, border_color=(80, 40, 120, 25))
        self._collapsed = True
        self._cmd = cmd
        self._name = name
        self._desc = description

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        # Header — command + name, click to expand
        header = QPushButton(f"  >  {cmd}  —  {name}")
        header.setFont(QFont(ADMIN_MONO, 9, QFont.Weight.Bold))
        header.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {PALETTE['accent_bright']};
                border: none;
                text-align: left;
                padding: 2px 0px;
            }}
            QPushButton:hover {{ color: {PALETTE['text']}; }}
        """)
        header.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        header.clicked.connect(self._toggle)
        self._header = header
        layout.addWidget(header)

        # Description (hidden when collapsed)
        desc_label = QLabel(description)
        desc_label.setFont(QFont("Segoe UI", 9))
        desc_label.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none;")
        desc_label.setWordWrap(True)
        desc_label.setVisible(False)
        self._desc_label = desc_label
        layout.addWidget(desc_label)

    def _toggle(self):
        self._collapsed = not self._collapsed
        self._desc_label.setVisible(not self._collapsed)
        arrow = "v" if not self._collapsed else ">"
        self._header.setText(f"  {arrow}  {self._cmd}  —  {self._name}")


class CommandListView(QWidget):
    """Rift Commands List — know your superpowers and your limits."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Title
        title = QLabel("RIFT COMMANDS LIST")
        title.setFont(QFont(ADMIN_MONO, 10, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {ADMIN_HUD}; background: transparent; border: none; letter-spacing: 3px;")
        layout.addWidget(title)

        subtitle = QLabel("Know Your Superpowers (And Your Limits)")
        subtitle.setFont(QFont("Segoe UI", 11, QFont.Weight.Medium))
        subtitle.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none;")
        layout.addWidget(subtitle)

        # Scrollable command list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{ background: {ADMIN_PANEL}; width: 6px; border: none; }}
            QScrollBar::handle:vertical {{ background: {PALETTE['panel_light']}; border-radius: 3px; }}
        """)
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        cmd_layout = QVBoxLayout(container)
        cmd_layout.setContentsMargins(0, 0, 0, 0)
        cmd_layout.setSpacing(8)
        cmd_layout.addStretch()

        for cmd, name, desc in RIFT_COMMANDS:
            entry = CommandListEntry(cmd, name, desc)
            cmd_layout.insertWidget(cmd_layout.count() - 1, entry)

        scroll.setWidget(container)
        layout.addWidget(scroll, 1)


# ------------------------------------------------------------------
# Terminal Commands view — editable short-coded aliases
# ------------------------------------------------------------------
DEFAULT_TERMINAL_COMMANDS = [
    (".terminal clearrecyc", "Clear Recycle Bin", "rd /s /q %systemdrive%\\$Recycle.Bin"),
    (".terminal flushdns", "Flush DNS Cache", "ipconfig /flushdns"),
    (".terminal sysinfo", "System Info", "systeminfo"),
    (".terminal ipconfig", "IP Configuration", "ipconfig /all"),
    (".terminal tasklist", "List Running Tasks", "tasklist"),
    (".terminal killtask", "Kill Task by PID", "taskkill /PID <pid> /F"),
    (".terminal diskcheck", "Check Disk", "chkdsk /f"),
    (".terminal sfcscan", "System File Checker", "sfc /scannow"),
    (".terminal dism", "DISM Repair", "DISM /Online /Cleanup-Image /RestoreHealth"),
    (".terminal netstat", "Network Statistics", "netstat -an"),
    (".terminal ping", "Ping Host", "ping <host>"),
    (".terminal traceroute", "Trace Route", "tracert <host>"),
    (".terminal whoami", "Current User", "whoami /all"),
    (".terminal env", "Environment Variables", "set"),
    (".terminal pythonver", "Python Version", "python --version"),
]

class TerminalCommandEntry(BlackGlassPanel):
    """Expandable terminal command — shows guts, editable, resettable."""

    reset_requested = Signal(str, str)  # (alias, default_guts)

    def __init__(self, alias, name, guts, parent=None):
        super().__init__(parent, radius=8, border_color=(140, 60, 220, 30))
        self._collapsed = True
        self._alias = alias
        self._name = name
        self._default_guts = guts

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        # Header
        header = QPushButton(f"  >  {alias}  —  {name}")
        header.setFont(QFont(ADMIN_MONO, 9, QFont.Weight.Bold))
        header.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: #c084fc;
                border: none;
                text-align: left;
                padding: 2px 0px;
            }}
            QPushButton:hover {{ color: {PALETTE['text']}; }}
        """)
        header.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        header.clicked.connect(self._toggle)
        self._header = header
        layout.addWidget(header)

        # Editable guts (hidden when collapsed)
        guts_layout = QVBoxLayout()
        guts_layout.setSpacing(6)

        guts_label = QLabel("Command:")
        guts_label.setFont(QFont(ADMIN_MONO, 7))
        guts_label.setStyleSheet(f"color: {ADMIN_HUD_DIM}; background: transparent; border: none;")
        guts_layout.addWidget(guts_label)

        self._guts_input = QLineEdit(guts)
        self._guts_input.setFont(QFont(ADMIN_MONO, 9))
        self._guts_input.setStyleSheet(f"""
            QLineEdit {{
                background: {PALETTE['input_bg']};
                color: {PALETTE['text']};
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 4px;
                padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {PALETTE['accent']}; }}
        """)
        guts_layout.addWidget(self._guts_input)

        # Reset button
        reset_btn = QPushButton("Reset to Default")
        reset_btn.setFixedHeight(26)
        reset_btn.setFont(QFont("Segoe UI", 8))
        reset_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        reset_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {PALETTE['muted']};
                border: 1px solid rgba(255, 255, 255, 15);
                border-radius: 4px;
                padding: 0 10px;
            }}
            QPushButton:hover {{ color: {PALETTE['text']}; border: 1px solid rgba(255, 255, 255, 30); }}
        """)
        reset_btn.clicked.connect(self._reset)
        guts_layout.addWidget(reset_btn)

        self._guts_widget = QWidget()
        self._guts_widget.setLayout(guts_layout)
        self._guts_widget.setVisible(False)
        layout.addWidget(self._guts_widget)

    def _toggle(self):
        self._collapsed = not self._collapsed
        self._guts_widget.setVisible(not self._collapsed)
        arrow = "v" if not self._collapsed else ">"
        self._header.setText(f"  {arrow}  {self._alias}  —  {self._name}")

    def _reset(self):
        self._guts_input.setText(self._default_guts)

    def get_guts(self):
        return self._guts_input.text()


class TerminalCommandsView(QWidget):
    """Terminal Commands — short-coded/aliased commands for beginner use."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        title = QLabel("TERMINAL COMMANDS")
        title.setFont(QFont(ADMIN_MONO, 10, QFont.Weight.Bold))
        title.setStyleSheet(f"color: #c084fc; background: transparent; border: none; letter-spacing: 3px;")
        layout.addWidget(title)

        subtitle = QLabel("Short-coded aliases for common terminal commands. Click to expand — you can edit the guts or reset to default.")
        subtitle.setFont(QFont("Segoe UI", 9))
        subtitle.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{ background: {ADMIN_PANEL}; width: 6px; border: none; }}
            QScrollBar::handle:vertical {{ background: {PALETTE['panel_light']}; border-radius: 3px; }}
        """)
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        cmd_layout = QVBoxLayout(container)
        cmd_layout.setContentsMargins(0, 0, 0, 0)
        cmd_layout.setSpacing(8)
        cmd_layout.addStretch()

        for alias, name, guts in DEFAULT_TERMINAL_COMMANDS:
            entry = TerminalCommandEntry(alias, name, guts)
            cmd_layout.insertWidget(cmd_layout.count() - 1, entry)

        scroll.setWidget(container)
        layout.addWidget(scroll, 1)


# ------------------------------------------------------------------
# Settings view — theme selection + placeholder settings
# ------------------------------------------------------------------
class SettingsView(QWidget):
    """Settings panel with theme selector and general settings."""

    theme_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Title
        title = QLabel("SETTINGS")
        title.setFont(QFont(ADMIN_MONO, 10, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {THEME['hud']}; background: transparent; border: none; letter-spacing: 3px;")
        layout.addWidget(title)

        # Scrollable settings
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{ background: {THEME['bg']}; width: 6px; border: none; }}
            QScrollBar::handle:vertical {{ background: {THEME['accent']}; border-radius: 3px; }}
        """)
        container = QWidget()
        container.setStyleSheet("background: transparent;")
        settings_layout = QVBoxLayout(container)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(16)

        # ---- Theme section ----
        theme_section = BlackGlassPanel(container, radius=12)
        theme_layout = QVBoxLayout(theme_section)
        theme_layout.setContentsMargins(16, 14, 16, 14)
        theme_layout.setSpacing(12)

        theme_header = QLabel("THEME")
        theme_header.setFont(QFont(ADMIN_MONO, 8, QFont.Weight.Bold))
        theme_header.setStyleSheet(f"color: {THEME['hud_dim']}; background: transparent; border: none; letter-spacing: 2px;")
        theme_layout.addWidget(theme_header)

        theme_desc = QLabel("Choose your console aesthetic. All themes keep the spacy galaxy milky way vibes.")
        theme_desc.setFont(QFont("Segoe UI", 9))
        theme_desc.setStyleSheet(f"color: {THEME['muted']}; background: transparent; border: none;")
        theme_desc.setWordWrap(True)
        theme_layout.addWidget(theme_desc)

        # Theme selector buttons
        self._theme_buttons = {}
        for name in THEMES:
            t = THEMES[name]
            btn = QPushButton(name)
            btn.setFixedHeight(40)
            btn.setFont(QFont("Segoe UI", 10))
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            is_current = (name == current_theme_name())
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {t['nav_active_bg'] if is_current else 'transparent'};
                    color: {t['accent_bright'] if is_current else t['muted']};
                    border: 1px solid {t['accent'] if is_current else 'rgba(255,255,255,15)'};
                    border-radius: 8px;
                    padding: 0 16px;
                    text-align: left;
                }}
                QPushButton:hover {{
                    border: 1px solid {t['accent']};
                    color: {t['text']};
                }}
            """)
            btn.clicked.connect(lambda checked, n=name: self._select_theme(n))
            theme_layout.addWidget(btn)
            self._theme_buttons[name] = btn

        # Theme preview swatches
        swatch_row = QHBoxLayout()
        swatch_row.setSpacing(6)
        for name in THEMES:
            t = THEMES[name]
            swatch = QFrame()
            swatch.setFixedSize(40, 40)
            swatch.setStyleSheet(f"""
                QFrame {{
                    background: {t['accent']};
                    border: 2px solid {'rgba(255,255,255,40)' if name == current_theme_name() else 'rgba(255,255,255,10)'};
                    border-radius: 6px;
                }}
            """)
            swatch.setToolTip(name)
            swatch_row.addWidget(swatch)
        swatch_row.addStretch()
        theme_layout.addLayout(swatch_row)

        settings_layout.addWidget(theme_section)

        # ---- General settings (placeholders) ----
        general_section = BlackGlassPanel(container, radius=12)
        gen_layout = QVBoxLayout(general_section)
        gen_layout.setContentsMargins(16, 14, 16, 14)
        gen_layout.setSpacing(12)

        gen_header = QLabel("GENERAL")
        gen_header.setFont(QFont(ADMIN_MONO, 8, QFont.Weight.Bold))
        gen_header.setStyleSheet(f"color: {THEME['hud_dim']}; background: transparent; border: none; letter-spacing: 2px;")
        gen_layout.addWidget(gen_header)

        # Placeholder toggle rows
        placeholders = [
            ("Auto-connect to last session", False),
            ("Sound effects", True),
            ("Minimize to tray on close", False),
            ("Show orb ripples on click", True),
            ("Confirm before closing sessions", True),
            ("Auto-scroll output on new results", True),
        ]
        self._placeholder_toggles = {}
        for label_text, default_val in placeholders:
            row = QHBoxLayout()
            row.setSpacing(8)
            label = QLabel(label_text)
            label.setFont(QFont("Segoe UI", 9))
            label.setStyleSheet(f"color: {THEME['text']}; background: transparent; border: none;")
            row.addWidget(label)
            row.addStretch()

            toggle = QPushButton("ON" if default_val else "OFF")
            toggle.setCheckable(True)
            toggle.setChecked(default_val)
            toggle.setFixedSize(50, 24)
            toggle.setFont(QFont(ADMIN_MONO, 7, QFont.Weight.Bold))
            toggle.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            toggle.setStyleSheet(self._toggle_style(default_val))
            toggle.toggled.connect(lambda checked, b=toggle: b.setText("ON" if checked else "OFF"))
            toggle.toggled.connect(lambda checked, b=toggle: b.setStyleSheet(self._toggle_style(checked)))
            row.addWidget(toggle)
            gen_layout.addLayout(row)
            self._placeholder_toggles[label_text] = toggle

        settings_layout.addWidget(general_section)

        # ---- Debug section ----
        debug_section = BlackGlassPanel(container, radius=12)
        debug_layout = QVBoxLayout(debug_section)
        debug_layout.setContentsMargins(16, 14, 16, 14)
        debug_layout.setSpacing(12)

        debug_header = QLabel("DEBUG")
        debug_header.setFont(QFont(ADMIN_MONO, 8, QFont.Weight.Bold))
        debug_header.setStyleSheet(f"color: {THEME['hud_dim']}; background: transparent; border: none; letter-spacing: 2px;")
        debug_layout.addWidget(debug_header)

        debug_url = QLabel(f"Firebase URL: {FIREBASE_URL}")
        debug_url.setFont(QFont(ADMIN_MONO, 7))
        debug_url.setStyleSheet(f"color: {THEME['muted']}; background: transparent; border: none;")
        debug_url.setWordWrap(True)
        debug_layout.addWidget(debug_url)

        dump_btn = QPushButton("Dump Raw Firebase Sessions")
        dump_btn.setFixedHeight(32)
        dump_btn.setFont(QFont("Segoe UI", 9))
        dump_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        dump_btn.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['input_bg']};
                color: {THEME['text']};
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 6px;
                padding: 0 14px;
            }}
            QPushButton:hover {{
                border: 1px solid {THEME['accent']};
            }}
        """)
        dump_btn.clicked.connect(self._dump_sessions)
        debug_layout.addWidget(dump_btn)

        test_btn = QPushButton("Test Connection (write + read)")
        test_btn.setFixedHeight(32)
        test_btn.setFont(QFont("Segoe UI", 9))
        test_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        test_btn.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['input_bg']};
                color: {THEME['text']};
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 6px;
                padding: 0 14px;
            }}
            QPushButton:hover {{
                border: 1px solid {THEME['accent']};
            }}
        """)
        test_btn.clicked.connect(self._test_connection)
        debug_layout.addWidget(test_btn)

        self._debug_text = QTextEdit()
        self._debug_text.setReadOnly(True)
        self._debug_text.setFont(QFont("Consolas", 8))
        self._debug_text.setStyleSheet(f"""
            QTextEdit {{
                background: {THEME['bg']};
                color: {THEME['text']};
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 6px;
                padding: 8px;
            }}
        """)
        self._debug_text.setPlaceholderText("Click 'Dump Raw Firebase Sessions' to see data...")
        self._debug_text.setMaximumHeight(200)
        debug_layout.addWidget(self._debug_text)
        settings_layout.addWidget(debug_section)

        # ---- About section ----
        about_section = BlackGlassPanel(container, radius=12)
        about_layout = QVBoxLayout(about_section)
        about_layout.setContentsMargins(16, 14, 16, 14)
        about_layout.setSpacing(6)

        about_header = QLabel("ABOUT")
        about_header.setFont(QFont(ADMIN_MONO, 8, QFont.Weight.Bold))
        about_header.setStyleSheet(f"color: {THEME['hud_dim']}; background: transparent; border: none; letter-spacing: 2px;")
        about_layout.addWidget(about_header)

        about_text = QLabel("Rift Admin Console v2.0\nPython Portal for Atlas\n\nA spacy remote support tool with portal aesthetics.")
        about_text.setFont(QFont("Segoe UI", 9))
        about_text.setStyleSheet(f"color: {THEME['muted']}; background: transparent; border: none;")
        about_text.setWordWrap(True)
        about_layout.addWidget(about_text)

        settings_layout.addWidget(about_section)
        settings_layout.addStretch()

        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

    def _toggle_style(self, on):
        if on:
            return f"""
                QPushButton {{
                    background: {THEME['success']};
                    color: #ffffff;
                    border: none;
                    border-radius: 12px;
                }}
            """
        else:
            return f"""
                QPushButton {{
                    background: {THEME['bg']};
                    color: {THEME['muted']};
                    border: 1px solid rgba(255, 255, 255, 20);
                    border-radius: 12px;
                }}
            """

    def _select_theme(self, name):
        self.theme_changed.emit(name)

    def refresh_theme(self):
        """Re-apply styles when theme changes."""
        self._refresh_theme_buttons()

    def _refresh_theme_buttons(self):
        for name, btn in self._theme_buttons.items():
            t = THEMES[name]
            is_current = (name == current_theme_name())
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {t['nav_active_bg'] if is_current else 'transparent'};
                    color: {t['accent_bright'] if is_current else t['muted']};
                    border: 1px solid {t['accent'] if is_current else 'rgba(255,255,255,15)'};
                    border-radius: 8px;
                    padding: 0 16px;
                    text-align: left;
                }}
                QPushButton:hover {{
                    border: 1px solid {t['accent']};
                    color: {t['text']};
                }}
            """)

    def _dump_sessions(self):
        """Fetch raw sessions from Firebase and display them for debugging."""
        try:
            data = _firebase_get("sessions")
            if not data:
                self._debug_text.setPlainText("No sessions found in Firebase.")
                return
            lines = [f"Firebase URL: {FIREBASE_URL}", f"Total sessions: {len(data)}", ""]
            for sid, info in data.items():
                if not isinstance(info, dict):
                    lines.append(f"{sid}: {info!r}")
                    continue
                status = info.get("status", "unknown")
                opened = info.get("opened_at", "")
                last_seen = info.get("last_seen", "")
                user = info.get("user", "unknown")
                host = info.get("host", "unknown")
                portal_opened = info.get("portal_opened", {})
                lines.append(f"{sid}")
                lines.append(f"  status: {status}")
                lines.append(f"  user@host: {user}@{host}")
                lines.append(f"  opened_at: {opened}")
                lines.append(f"  last_seen: {last_seen}")
                lines.append(f"  portal_opened: {portal_opened}")
                lines.append("")
            self._debug_text.setPlainText("\n".join(lines))
        except Exception as e:
            self._debug_text.setPlainText(f"Error fetching sessions: {e}")

    def _test_connection(self):
        """Write a test session to Firebase and read it back to verify connectivity."""
        try:
            test_id = f"test-{_uuid.uuid4().hex[:8]}"
            test_data = {
                "user": "admin-test",
                "host": "rift-console",
                "status": "test",
                "opened_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            write_ok = _firebase_put(f"sessions/{test_id}", test_data)
            if not write_ok:
                self._debug_text.setPlainText("Write to Firebase failed — check network/Firebase URL.")
                return
            read_data = _firebase_get(f"sessions/{test_id}")
            if not read_data:
                self._debug_text.setPlainText("Write succeeded, but read returned nothing. Possible delay or permission issue.")
                return
            # Clean up the test session
            _firebase_delete(f"sessions/{test_id}")
            self._debug_text.setPlainText(f"Connection OK.\n\nWrote test session: {test_id}\nRead back: {read_data}")
        except Exception as e:
            self._debug_text.setPlainText(f"Connection test error: {e}")


# ------------------------------------------------------------------
# New session dialog
# ------------------------------------------------------------------
class NewSessionDialog(BlackGlassPanel):
    """Simple inline dialog for starting a new session."""

    session_created = Signal(str, str)  # (name, host)
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, radius=16)
        self.setFixedSize(360, 200)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = QLabel("Start New Session")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {PALETTE['accent_bright']}; background: transparent; border: none;")
        layout.addWidget(title)

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Session name (e.g. John's Laptop)")
        self._name_input.setFixedHeight(34)
        self._name_input.setFont(QFont("Segoe UI", 10))
        self._name_input.setStyleSheet(f"""
            QLineEdit {{
                background: {PALETTE['input_bg']};
                color: {PALETTE['text']};
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 6px;
                padding: 0 12px;
            }}
            QLineEdit:focus {{ border: 1px solid {PALETTE['accent']}; }}
        """)
        layout.addWidget(self._name_input)

        self._host_input = QLineEdit()
        self._host_input.setPlaceholderText("Host / IP (optional)")
        self._host_input.setFixedHeight(34)
        self._host_input.setFont(QFont("Segoe UI", 10))
        self._host_input.setStyleSheet(f"""
            QLineEdit {{
                background: {PALETTE['input_bg']};
                color: {PALETTE['text']};
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 6px;
                padding: 0 12px;
            }}
            QLineEdit:focus {{ border: 1px solid {PALETTE['accent']}; }}
        """)
        layout.addWidget(self._host_input)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(32)
        cancel_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {PALETTE['muted']};
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 6px;
                padding: 0 16px;
            }}
            QPushButton:hover {{ color: {PALETTE['text']}; }}
        """)
        cancel_btn.clicked.connect(self.cancelled.emit)

        create_btn = QPushButton("Create")
        create_btn.setFixedHeight(32)
        create_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        create_btn.setStyleSheet(f"""
            QPushButton {{
                background: {PALETTE['accent']};
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 0 16px;
            }}
            QPushButton:hover {{ background: {PALETTE['accent_bright']}; }}
        """)
        create_btn.clicked.connect(self._create)

        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(create_btn)
        layout.addLayout(btn_row)

    def _create(self):
        name = self._name_input.text().strip() or None
        host = self._host_input.text().strip() or "pending"
        self.session_created.emit(name, host)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Return:
            self._create()
        elif event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()


# ------------------------------------------------------------------
# Main admin window
# ------------------------------------------------------------------
class DashboardView(QWidget):
    """Main dashboard with stats, controls, and command log."""

    command_triggered = Signal(str)  # emits command type string

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # ---- Stats row ----
        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)

        self.stat_state = StatCard("Portal State", "IDLE")
        self.stat_uptime = StatCard("Session Uptime", "00:00:00")
        self.stat_latency = StatCard("Latency", "---ms")
        self.stat_commands = StatCard("Commands Sent", "0")

        stats_row.addWidget(self.stat_state)
        stats_row.addWidget(self.stat_uptime)
        stats_row.addWidget(self.stat_latency)
        stats_row.addWidget(self.stat_commands)
        layout.addLayout(stats_row)

        # ---- Controls section ----
        controls_label = QLabel("PORTAL CONTROLS")
        controls_label.setFont(QFont(ADMIN_MONO, 8, QFont.Weight.Bold))
        controls_label.setStyleSheet(f"color: {ADMIN_HUD_DIM}; background: transparent; border: none; letter-spacing: 3px;")
        layout.addWidget(controls_label)

        controls_panel = BlackGlassPanel(self, radius=12)
        controls_layout = QVBoxLayout(controls_panel)
        controls_layout.setContentsMargins(16, 14, 16, 14)
        controls_layout.setSpacing(10)

        # Row 1: main mode triggers
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self.btn_command = ControlButton("Command", "40,120,220")
        self.btn_terminal = ControlButton("Terminal", "140,60,220")
        self.btn_screenshot = ControlButton("Screenshot", "220,200,40")
        self.btn_alert = ControlButton("Alert", "200,100,240")
        row1.addWidget(self.btn_command)
        row1.addWidget(self.btn_terminal)
        row1.addWidget(self.btn_screenshot)
        row1.addWidget(self.btn_alert)
        controls_layout.addLayout(row1)

        # Row 2: state controls
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        self.btn_pause = ControlButton("Pause", "255,180,50")
        self.btn_feed = ControlButton("Feed Me", "40,220,100")
        self.btn_pulse = ControlButton("Pulse Test", "220,30,40")
        self.btn_idle = ControlButton("Reset to Idle", "139,139,154")
        row2.addWidget(self.btn_pause)
        row2.addWidget(self.btn_feed)
        row2.addWidget(self.btn_pulse)
        row2.addWidget(self.btn_idle)
        controls_layout.addLayout(row2)

        layout.addWidget(controls_panel)

        # ---- Command log ----
        log_label = QLabel("COMMAND LOG")
        log_label.setFont(QFont(ADMIN_MONO, 8, QFont.Weight.Bold))
        log_label.setStyleSheet(f"color: {ADMIN_HUD_DIM}; background: transparent; border: none; letter-spacing: 3px;")
        layout.addWidget(log_label)

        log_panel = BlackGlassPanel(self, radius=12)
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(8, 8, 8, 8)
        log_layout.setSpacing(0)

        self._log_scroll = QScrollArea()
        self._log_scroll.setWidgetResizable(True)
        self._log_scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{ background: {ADMIN_PANEL}; width: 6px; border: none; }}
            QScrollBar::handle:vertical {{ background: {PALETTE['panel_light']}; border-radius: 3px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

        self._log_container = QWidget()
        self._log_container.setStyleSheet("background: transparent;")
        self._log_layout = QVBoxLayout(self._log_container)
        self._log_layout.setContentsMargins(4, 4, 4, 4)
        self._log_layout.setSpacing(0)
        self._log_layout.addStretch()
        self._log_scroll.setWidget(self._log_container)
        log_layout.addWidget(self._log_scroll)

        layout.addWidget(log_panel, 1)

        # ---- Wire up buttons ----
        self.btn_command.clicked.connect(lambda: self.command_triggered.emit("command"))
        self.btn_terminal.clicked.connect(lambda: self.command_triggered.emit("terminal"))
        self.btn_screenshot.clicked.connect(lambda: self.command_triggered.emit("screenshot"))
        self.btn_alert.clicked.connect(lambda: self.command_triggered.emit("alert"))
        self.btn_pause.clicked.connect(lambda: self.command_triggered.emit("paused"))
        self.btn_feed.clicked.connect(lambda: self.command_triggered.emit("feedme"))
        self.btn_pulse.clicked.connect(lambda: self.command_triggered.emit("test_pulse"))
        self.btn_idle.clicked.connect(lambda: self.command_triggered.emit("idle"))

        self._cmd_count = 0

    def update_state(self, state):
        info, color = STATE_INFO.get(state, ("UNKNOWN", PALETTE["muted"]))
        self.stat_state.set_value(info, color)

    def update_uptime(self, seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        self.stat_uptime.set_value(f"{h:02d}:{m:02d}:{s:02d}")

    def update_latency(self, ms):
        if ms is None:
            self.stat_latency.set_value("---ms")
        else:
            color = "#22c55e" if ms < 100 else "#f59e0b" if ms < 300 else "#ef4444"
            self.stat_latency.set_value(f"{ms}ms", color)

    def add_log_entry(self, entry_type, message, color=None):
        if color is None:
            color = STATE_INFO.get(entry_type, (None, PALETTE["text"]))[1]
        ts = datetime.now().strftime("%H:%M:%S")
        entry = LogEntry(ts, entry_type, message, color)
        # Insert before the stretch
        self._log_layout.insertWidget(self._log_layout.count() - 1, entry)

        # Keep log to last 100 entries
        while self._log_layout.count() > 102:
            item = self._log_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._cmd_count += 1
        self.stat_commands.set_value(str(self._cmd_count))

        # Auto-scroll to bottom
        QTimer.singleShot(10, lambda: self._log_scroll.verticalScrollBar().setValue(
            self._log_scroll.verticalScrollBar().maximum()))


# ------------------------------------------------------------------
# Chat view
# ------------------------------------------------------------------
class ChatView(QWidget):
    """Chat panel for messaging the portal user."""

    message_sent = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Header
        header = QLabel("CHAT")
        header.setFont(QFont(ADMIN_MONO, 8, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {ADMIN_HUD_DIM}; background: transparent; border: none; letter-spacing: 3px;")
        layout.addWidget(header)

        # Chat panel
        chat_panel = BlackGlassPanel(self, radius=12)
        chat_layout = QVBoxLayout(chat_panel)
        chat_layout.setContentsMargins(12, 12, 12, 12)
        chat_layout.setSpacing(8)

        # Messages scroll area
        self._msg_scroll = QScrollArea()
        self._msg_scroll.setWidgetResizable(True)
        self._msg_scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{ background: {ADMIN_PANEL}; width: 6px; border: none; }}
            QScrollBar::handle:vertical {{ background: {PALETTE['panel_light']}; border-radius: 3px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

        self._msg_container = QWidget()
        self._msg_container.setStyleSheet(f"background: {PALETTE['chat_bg']};")
        self._msg_layout = QVBoxLayout(self._msg_container)
        self._msg_layout.setContentsMargins(8, 8, 8, 8)
        self._msg_layout.setSpacing(6)
        self._msg_layout.addStretch()
        self._msg_scroll.setWidget(self._msg_container)
        chat_layout.addWidget(self._msg_scroll, 1)

        # Input row
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a message to send...")
        self._input.setFont(QFont("Segoe UI", 10))
        self._input.setFixedHeight(34)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: {PALETTE['input_bg']};
                color: {PALETTE['text']};
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 6px;
                padding: 0 12px;
            }}
            QLineEdit:focus {{
                border: 1px solid {PALETTE['accent']};
            }}
        """)
        self._input.returnPressed.connect(self._send)

        send_btn = QPushButton("Send")
        send_btn.setFixedHeight(34)
        send_btn.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
        send_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        send_btn.setStyleSheet(f"""
            QPushButton {{
                background: {PALETTE['accent']};
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 0 20px;
            }}
            QPushButton:hover {{ background: {PALETTE['accent_bright']}; }}
        """)
        send_btn.clicked.connect(self._send)

        input_row.addWidget(self._input, 1)
        input_row.addWidget(send_btn)
        chat_layout.addLayout(input_row)

        layout.addWidget(chat_panel, 1)

    def _send(self):
        text = self._input.text().strip()
        if text:
            self.message_sent.emit(text)
            self.add_message(text, is_admin=True)
            self._input.clear()

    def add_message(self, text, is_admin=False):
        """Add a chat message bubble to the view."""
        bubble = QFrame()
        bubble.setMaximumWidth(380)
        if is_admin:
            bg = PALETTE["bubble_user"]
            align = Qt.AlignmentFlag.AlignRight
            color = PALETTE["accent_bright"]
        else:
            bg = PALETTE["bubble_atlas"]
            align = Qt.AlignmentFlag.AlignLeft
            color = PALETTE["text"]

        bubble.setStyleSheet(f"""
            QFrame {{
                background: {bg};
                border: 1px solid {PALETTE['bubble_border']};
                border-radius: 10px;
            }}
        """)

        bl = QVBoxLayout(bubble)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(2)

        sender = QLabel("ADMIN" if is_admin else "PORTAL")
        sender.setFont(QFont(ADMIN_MONO, 7))
        sender.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none; letter-spacing: 1px;")

        msg = QLabel(text)
        msg.setFont(QFont("Segoe UI", 10))
        msg.setStyleSheet(f"color: {color}; background: transparent; border: none;")
        msg.setWordWrap(True)
        msg.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard)

        bl.addWidget(sender)
        bl.addWidget(msg)

        wrapper = QHBoxLayout()
        wrapper.addWidget(bubble, 0, align)
        wrapper.addStretch() if not is_admin else None

        self._msg_layout.insertWidget(self._msg_layout.count() - 1, bubble)
        QTimer.singleShot(10, lambda: self._msg_scroll.verticalScrollBar().setValue(
            self._msg_scroll.verticalScrollBar().maximum()))


# ------------------------------------------------------------------
# Screenshot view
# ------------------------------------------------------------------
class ScreenshotView(QWidget):
    """Screenshot viewer panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        # Header
        header = QLabel("SCREENSHOTS")
        header.setFont(QFont(ADMIN_MONO, 8, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {ADMIN_HUD_DIM}; background: transparent; border: none; letter-spacing: 3px;")
        layout.addWidget(header)

        # Screenshot display panel
        self._shot_panel = BlackGlassPanel(self, radius=12)
        shot_layout = QVBoxLayout(self._shot_panel)
        shot_layout.setContentsMargins(16, 16, 16, 16)
        shot_layout.setSpacing(12)

        self._shot_label = QLabel("No screenshots received")
        self._shot_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._shot_label.setFont(QFont(ADMIN_MONO, 10))
        self._shot_label.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none;")
        self._shot_label.setMinimumHeight(300)
        shot_layout.addWidget(self._shot_label, 1)

        # Info bar
        self._shot_info = QLabel("")
        self._shot_info.setFont(QFont(ADMIN_MONO, 8))
        self._shot_info.setStyleSheet(f"color: {ADMIN_HUD_DIM}; background: transparent; border: none;")
        shot_layout.addWidget(self._shot_info)

        layout.addWidget(self._shot_panel, 1)

    def show_screenshot(self, pixmap, timestamp=None):
        """Display a received screenshot."""
        if pixmap is None:
            return

        # Scale to fit
        scaled = pixmap.scaled(
            self._shot_label.width(), self._shot_label.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        self._shot_label.setPixmap(scaled)

        ts = timestamp or datetime.now().strftime("%H:%M:%S")
        w, h = pixmap.width(), pixmap.height()
        self._shot_info.setText(f"  RECEIVED: {ts}  |  RESOLUTION: {w}x{h}  |  SIZE: {pixmap.width() * pixmap.height() * 4 // 1024}KB")


# ------------------------------------------------------------------
# Main admin window
# ------------------------------------------------------------------
class RiftAdminConsole(QWidget):
    """Main admin console window — sidebar + session-based content."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Rift Admin Console")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(1100, 700)
        self.setMinimumSize(720, 480)
        # Track mouse across the whole window so we can show resize cursors on the edges
        self.setMouseTracking(True)

        self._start_time = time.time()
        self._drag_pos = None
        self._sessions = []
        self._current_session = None
        self._new_session_dialog = None
        # Frameless-window resizing state
        self._resize_margin = 7
        self._resize_edge = None
        self._resize_start_geo = None
        self._resize_start_mouse = None
        self._normal_geometry = None  # remembered geometry for restore-from-maximized

        # ---- Main layout ----
        # The main content (black glass) fills the entire window. The sidebar is
        # positioned as a detached floating panel over the left edge.
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ---- Sidebar (floating panel) ----
        self._sidebar = DarkSidebar(self)
        self._sidebar.setFixedWidth(220)
        self._sidebar_layout = QVBoxLayout(self._sidebar)
        self._sidebar_layout.setContentsMargins(0, 0, 0, 0)
        self._sidebar_layout.setSpacing(0)

        # Drop shadow so it looks detached / floating
        shadow = QGraphicsDropShadowEffect(self._sidebar)
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(0, 0, 0, 160))
        shadow.setOffset(8, 8)
        self._sidebar.setGraphicsEffect(shadow)

        # Title
        title_area = QWidget()
        title_area.setFixedHeight(48)
        title_area.setStyleSheet("background: transparent; border: none;")
        title_layout = QHBoxLayout(title_area)
        title_layout.setContentsMargins(16, 0, 8, 0)
        title_layout.setSpacing(8)

        title = QLabel("RIFT")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {PALETTE['accent_bright']}; background: transparent; border: none; letter-spacing: 4px;")
        subtitle = QLabel("ADMIN")
        subtitle.setFont(QFont(ADMIN_MONO, 7))
        subtitle.setStyleSheet(f"color: #ffffff; background: transparent; border: none; letter-spacing: 2px;")
        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)
        title_layout.addStretch()

        min_btn = QPushButton("-")
        min_btn.setFixedSize(24, 24)
        min_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #8b8b9a; border-radius: 12px; font-size: 12px; border: none; }
            QPushButton:hover { background: #2a2a45; color: #f0f0f5; }
        """)
        min_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        min_btn.clicked.connect(self.showMinimized)
        title_layout.addWidget(min_btn)

        self._max_btn = QPushButton("□")
        self._max_btn.setFixedSize(24, 24)
        self._max_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #8b8b9a; border-radius: 12px; font-size: 11px; border: none; }
            QPushButton:hover { background: #2a2a45; color: #f0f0f5; }
        """)
        self._max_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._max_btn.clicked.connect(self._toggle_max_restore)
        title_layout.addWidget(self._max_btn)

        close_btn = QPushButton("x")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet("""
            QPushButton { background: transparent; color: #8b8b9a; border-radius: 12px; font-size: 12px; border: none; }
            QPushButton:hover { background: #8b3a3a; color: #f0f0f5; }
        """)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.clicked.connect(self.close)
        title_layout.addWidget(close_btn)
        self._sidebar_layout.addWidget(title_area)

        # Connection status
        status_area = QWidget()
        status_area.setFixedHeight(36)
        status_area.setStyleSheet("background: transparent; border: none;")
        status_layout = QHBoxLayout(status_area)
        status_layout.setContentsMargins(16, 0, 16, 0)
        status_layout.setSpacing(8)
        self._conn_dot = QLabel()
        self._conn_dot.setFixedSize(8, 8)
        self._conn_dot.setStyleSheet(f"background: {PALETTE['success']}; border-radius: 4px; border: none;")
        self._conn_text = QLabel("CONNECTED")
        self._conn_text.setFont(QFont(ADMIN_MONO, 7, QFont.Weight.Bold))
        self._conn_text.setStyleSheet(f"color: {PALETTE['success']}; background: transparent; border: none; letter-spacing: 1px;")
        status_layout.addWidget(self._conn_dot)
        status_layout.addWidget(self._conn_text)
        status_layout.addStretch()
        self._sidebar_layout.addWidget(status_area)

        # Nav
        nav_container = QWidget()
        nav_container.setStyleSheet("background: transparent; border: none;")
        nav_layout = QVBoxLayout(nav_container)
        nav_layout.setContentsMargins(0, 8, 0, 8)
        nav_layout.setSpacing(2)

        self._nav_buttons = []
        nav_items = [
            ("Sessions", 0),
            ("Rift Commands", 1),
            ("Terminal Commands", 2),
            ("Settings", 3),
        ]
        for label, idx in nav_items:
            btn = NavButton(label)
            btn.clicked.connect(lambda checked, i=idx: self._switch_view(i))
            nav_layout.addWidget(btn)
            self._nav_buttons.append(btn)
        nav_layout.addStretch()
        self._sidebar_layout.addWidget(nav_container, 1)

        # Orb at bottom
        orb_area = CircularGlassFrame()
        orb_area.setFixedSize(200, 200)
        orb_area.set_border_alpha(22)
        orb_layout = QVBoxLayout(orb_area)
        orb_layout.setContentsMargins(8, 8, 8, 8)
        orb_layout.setSpacing(0)
        self.orb = OrbWidget(orb_area)
        self.orb.setFixedSize(160, 160)
        # Start dormant — a black portal with a tiny needle point. It expands into
        # an active portal once a client connection is established (see _on_portal_opened
        # and _on_sessions_updated).
        self.orb.set_state("awaiting")
        self._orb_connected = False
        self.orb.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        orb_layout.addWidget(self.orb, alignment=Qt.AlignmentFlag.AlignCenter)
        self._sidebar_layout.addWidget(orb_area, alignment=Qt.AlignmentFlag.AlignCenter)

        # Ambient dormant rift animation — occasional open/close when no active sessions
        self._ambient_timer = QTimer(self)
        self._ambient_timer.timeout.connect(self._ambient_rift_tick)
        self._ambient_timer.setSingleShot(True)
        self._ambient_opening = False

        self._orb_status = QLabel("IDLE")
        self._orb_status.setFont(QFont(ADMIN_MONO, 7, QFont.Weight.Bold))
        self._orb_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._orb_status.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none; letter-spacing: 2px;")
        self._sidebar_layout.addWidget(self._orb_status)
        self._sidebar_layout.addSpacing(12)

        # ---- Main area ----
        content_wrapper = GridBackground()
        content_layout = QVBoxLayout(content_wrapper)
        # Leave room on the left for the floating sidebar + a gap
        content_layout.setContentsMargins(244, 12, 12, 12)
        content_layout.setSpacing(0)

        self._stack = QStackedWidget()
        self._stack.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # View 0: Session list
        self._session_list = SessionListView()
        self._session_list.session_selected.connect(self._open_session)
        self._session_list.new_session_requested.connect(self._show_new_session_dialog)
        self._session_list.cleanup_stale.connect(self._cleanup_stale_sessions)
        self._session_list.refresh_requested.connect(self._refresh_sessions)
        self._session_list.purge_closed.connect(self._purge_closed_sessions)
        self._stack.addWidget(self._session_list)

        # View 1: Rift Commands List
        self._command_list_view = CommandListView()
        self._stack.addWidget(self._command_list_view)

        # View 2: Terminal Commands
        self._terminal_commands_view = TerminalCommandsView()
        self._stack.addWidget(self._terminal_commands_view)

        # View 3: Settings
        self._settings_view = SettingsView()
        self._settings_view.theme_changed.connect(self._apply_theme)
        self._stack.addWidget(self._settings_view)

        # View 4: Session detail (not in nav — accessed by clicking a session)
        self._session_detail = SessionDetailView()
        self._session_detail.back_requested.connect(self._back_to_list)
        self._session_detail.command_sent.connect(self._on_command_sent)
        self._session_detail.quick_action.connect(self._on_quick_action)
        self._session_detail.portal_open_requested.connect(self._on_portal_open_requested)
        self._session_detail.close_session_requested.connect(self._close_session)
        self._session_detail.chat_sent.connect(self._on_chat_sent)
        self._stack.addWidget(self._session_detail)

        content_layout.addWidget(self._stack, 1)
        main_layout.addWidget(content_wrapper, 1)

        # Make sure the floating sidebar stays on top of the content
        self._sidebar.raise_()
        self._sidebar.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)

        # ---- Timer ----
        self._uptime_timer = QTimer(self)
        self._uptime_timer.timeout.connect(self._update_uptime)
        self._uptime_timer.start(1000)

        # ---- Firebase worker ----
        self._sessions = []
        self._firebase_worker = FirebaseWorker()
        self._firebase_thread = QThread(self)
        self._firebase_worker.moveToThread(self._firebase_thread)
        self._firebase_worker.sessions_updated.connect(self._on_sessions_updated)
        self._firebase_worker.result_received.connect(self._on_result_received)
        self._firebase_worker.portal_opened.connect(self._on_portal_opened)
        self._firebase_worker.chat_received.connect(self._on_chat_received)
        self._firebase_worker.poll_status.connect(self._on_poll_status)
        self._firebase_thread.started.connect(self._firebase_worker.run)
        self._firebase_thread.start()

        self._switch_view(0)

    def _on_poll_status(self, text):
        """Called when the Firebase worker reports poll status or errors."""
        self._session_list.set_poll_status(text)

    def _on_sessions_updated(self, fb_sessions):
        """Called when Firebase reports the current session list."""
        # Convert Firebase session dicts to Session objects
        new_sessions = []
        for fs in fb_sessions:
            # Try to find existing session to preserve chat/results
            existing = None
            for s in self._sessions:
                if s.id == fs["id"]:
                    existing = s
                    break
            if existing:
                existing.status = fs["status"]
                existing.portal_connected = fs["portal_connected"]
                existing.name = fs["name"]
                existing.user = fs["user"]
                existing.host = fs["host"]
                existing.opened_at = fs.get("opened_at", "")
                existing.last_seen = fs.get("last_seen", "")
                existing.card_state = fs.get("card_state", "inactive")
                new_sessions.append(existing)
            else:
                s = Session(name=fs["name"], host=fs["host"], user=fs["user"])
                s.id = fs["id"]
                s.status = fs["status"]
                s.portal_connected = fs["portal_connected"]
                s.opened_at = fs.get("opened_at", "")
                s.last_seen = fs.get("last_seen", "")
                s.card_state = fs.get("card_state", "inactive")
                new_sessions.append(s)
        self._sessions = new_sessions
        self._session_list.set_sessions(self._sessions)

        # Sidebar orb reflects overall session state: active if any session is
        # still active (open), even if stale or not yet connected. Only fall back
        # to dormant when there are no active sessions at all.
        has_active = any(s.status == "active" for s in new_sessions)
        self._set_orb_connected(has_active)

        # If a user closed their Rift, surface a persistent alert with a download-zip option
        for s in new_sessions:
            if s.status in ("user-closed", "closed") and not s._close_alert_added:
                s._close_alert_added = True
                self._add_session_close_alert(s)

        # When dormant, occasionally play an ambient rift opening/closing animation.
        if not has_active and not self._ambient_timer.isActive() and not self._ambient_opening:
            self._schedule_ambient_rift()

        # If the current session's portal_connected state changed, refresh the detail view
        if self._current_session:
            for s in new_sessions:
                if s.id == self._current_session.id:
                    # If the session is connected in Firebase, make sure we're showing
                    # the connected view — don't get stuck on waiting/blank
                    if s.portal_connected:
                        if not self._current_session.portal_connected:
                            self._current_session.portal_connected = True
                            self._session_detail._on_portal_opened()
                        # Also start watching chat if not already
                        self._firebase_worker.watch_chat(s.id)
                    elif s.portal_connected != self._current_session.portal_connected:
                        self._current_session.portal_connected = s.portal_connected
                    break

    def _add_session_close_alert(self, session):
        """Persist an alert when the user closes their Rift, with a download-zip option."""
        alert_text = "User closed this Rift. Save any important documents before closing this session or exiting."
        session.chat.append(("system", alert_text, datetime.now()))
        session.results.append({"type": "close_alert", "title": "Rift Closed", "content": session})
        if self._current_session and self._current_session.id == session.id:
            self._session_detail._refresh_chat()
            self._session_detail.add_close_alert(session)

    def _on_result_received(self, session_id, result):
        """Called when a command result comes back from a portal client."""
        # Find the session
        for s in self._sessions:
            if s.id == session_id:
                cmd_id = result.get("id", "")
                # Deduplicate results when a session is rewatched
                if cmd_id and cmd_id in s._seen_result_ids:
                    break
                if cmd_id:
                    s._seen_result_ids.add(cmd_id)
                cmd_type = result.get("type", "output")
                ok = result.get("ok", True)
                result_payload = result.get("result", "")
                is_current = bool(self._current_session and self._current_session.id == session_id)

                # A screenshot arrives as a dict payload {"image": <base64 png>}.
                # It can come back typed either "screenshot" (quick action) or
                # "rift_command" (.screenshot), so detect it by the payload shape.
                if isinstance(result_payload, dict) and "image" in result_payload:
                    b64_data = result_payload["image"]
                    try:
                        png_bytes = _b64.b64decode(b64_data)
                        pm = QPixmap()
                        pm.loadFromData(png_bytes, "PNG")
                        title = f"Screenshot - {datetime.now().strftime('%H:%M:%S')}"
                        if is_current:
                            self._session_detail.add_screenshot(pm, title)
                        s.results.append({"type": "screenshot", "title": title, "content": b64_data})
                    except Exception as e:
                        if is_current:
                            self._session_detail.add_result("error", "Screenshot decode failed", str(e))
                elif isinstance(result_payload, dict) and ("file" in result_payload or "data" in result_payload):
                    # Single file result (.fetch, drag-and-drop)
                    file_path = result_payload.get("file", "")
                    file_name = Path(file_path).name or "file"
                    title = f"File: {file_name}"
                    if is_current:
                        self._session_detail.add_result("file_drop", title, result_payload)
                    s.results.append({"type": "file_drop", "title": title, "content": result_payload})
                elif isinstance(result_payload, dict) and "files" in result_payload:
                    # Multiple file result (.fetchall)
                    files_dict = result_payload.get("files", {})
                    title = f"Files ({len(files_dict)})"
                    if is_current:
                        self._session_detail.add_result("files", title, result_payload)
                    s.results.append({"type": "files", "title": title, "content": result_payload})
                else:
                    # Non-image payloads: render dicts/lists as readable text
                    if isinstance(result_payload, (dict, list)):
                        try:
                            result_text = json.dumps(result_payload, indent=2)[:8000]
                        except Exception:
                            result_text = str(result_payload)
                    else:
                        result_text = str(result_payload)
                    title = f"Result: {cmd_type}" + ("" if ok else " (FAILED)")
                    if is_current:
                        self._session_detail.add_result("output" if ok else "error", title, result_text)
                    s.results.append({"type": "output", "title": title, "content": result_text})
                break

    def _on_chat_sent(self, session_id, text):
        """Send a chat message to the portal via Firebase."""
        if send_chat_to_session(session_id, text, sender="admin") is None:
            # Surface delivery failure so it isn't silently swallowed
            if self._current_session and self._current_session.id == session_id:
                self._session_detail._add_chat_bubble(
                    "⚠ Message failed to send (Firebase unreachable)", is_admin=False)

    def _switch_view(self, index):
        current = self._stack.currentIndex()
        # If we're leaving the session detail view, ask the admin to confirm first.
        if current == 4 and index != 4 and self._current_session is not None:
            if not self._confirm_leave_session():
                return
        self._stack.setCurrentIndex(index)
        # Only highlight nav buttons for nav views (0, 1, 2, 3)
        for i, btn in enumerate(self._nav_buttons):
            btn.set_active(i == index and index < len(self._nav_buttons))

    def _apply_theme(self, name):
        """Apply a new theme and refresh the entire UI."""
        apply_theme(name)
        # Refresh nav buttons
        for btn in self._nav_buttons:
            btn.refresh_theme()
        # Refresh settings view
        self._settings_view.refresh_theme()
        # Trigger a full repaint of all widgets
        self.update()
        for child in self.findChildren(QWidget):
            child.update()
            # Also refresh stylesheets that reference PALETTE
            if isinstance(child, QLabel):
                pass  # labels will get refreshed on next paint
        # Repaint the whole window
        self.repaint()

    def _open_session(self, session_id):
        for s in self._sessions:
            if s.id == session_id:
                self._current_session = s
                self._session_detail.set_session(s)
                self._stack.setCurrentIndex(4)  # session detail view
                for btn in self._nav_buttons:
                    btn.set_active(False)
                # Start watching results from this session
                self._firebase_worker.watch_results(session_id)
                # If already connected, start watching chat too
                if s.portal_connected:
                    self._firebase_worker.watch_chat(session_id)
                return

    def _confirm_leave_session(self):
        """Ask the admin if they're sure they want to leave the current session."""
        dialog = RiftConfirmDialog(
            "Leave Session?",
            "This session may contain unsaved files or screenshots. Leave without downloading?",
            confirm_text="Leave",
            cancel_text="Stay",
            parent=self
        )
        dialog.move(self.mapToGlobal(self.rect().center() - dialog.rect().center()))
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _confirm_close_session(self):
        """Ask the admin if they're sure they want to close/end the current session."""
        dialog = RiftConfirmDialog(
            "Close Session?",
            "This will permanently end the current session for the user. Any unsaved files or screenshots may be lost.",
            confirm_text="Close Session",
            cancel_text="Stay",
            danger=True,
            parent=self
        )
        dialog.move(self.mapToGlobal(self.rect().center() - dialog.rect().center()))
        return dialog.exec() == QDialog.DialogCode.Accepted

    def _back_to_list(self):
        if self._current_session and not self._confirm_leave_session():
            return
        if self._current_session:
            self._firebase_worker.unwatch_results(self._current_session.id)
            self._firebase_worker.unwatch_chat(self._current_session.id)
        self._current_session = None
        self._session_list.set_sessions(self._sessions)
        self._switch_view(0)

    def _close_session(self, session_id):
        """Close/end a session — sends force_close and returns to list."""
        if self._current_session and not self._confirm_close_session():
            return
        # Send force_close command to the portal
        send_command_to_session(session_id, "force_close")
        # Stop watching results
        self._firebase_worker.unwatch_results(session_id)
        for s in self._sessions:
            if s.id == session_id:
                s.status = "inactive"
                s.portal_connected = False
                break
        self._current_session = None
        self._session_list.set_sessions(self._sessions)
        self._switch_view(0)

    def _show_new_session_dialog(self):
        if self._new_session_dialog:
            return
        dialog = NewSessionDialog(self)
        dialog.session_created.connect(self._create_session)
        dialog.cancelled.connect(self._close_new_session_dialog)
        # Center over the window
        dialog.move(self.rect().center().x() - 180, self.rect().center().y() - 100)
        dialog.show()
        self._new_session_dialog = dialog

    def _refresh_sessions(self):
        """Manually refresh the session list from Firebase."""
        self._firebase_worker._poll_all_sessions()

    def _cleanup_stale_sessions(self, hours=1):
        """Mark stale open sessions as closed so they disappear from the active list."""
        cleaned = cleanup_stale_sessions(max_age_hours=hours)
        # Force a session refresh immediately
        self._firebase_worker._poll_all_sessions()

    def _purge_closed_sessions(self):
        """Delete all non-open sessions from Firebase to clean up history."""
        deleted = purge_all_closed_sessions()
        self._firebase_worker._poll_all_sessions()

    def _close_new_session_dialog(self):
        if self._new_session_dialog:
            self._new_session_dialog.deleteLater()
            self._new_session_dialog = None

    def _create_session(self, name, host):
        self._close_new_session_dialog()
        s = Session(name=name, host=host, user="pending")
        s.chat.append(("portal", "Session created — waiting for client to connect...", datetime.now()))
        self._sessions.append(s)
        self._session_list.set_sessions(self._sessions)

    def _on_command_sent(self, session_id, text):
        """Send a typed command to the portal client via Firebase."""
        # Parse . commands
        text = text.strip()
        if not text:
            return

        cmd_map = {
            ".scan": ("scan", {}),
            ".screenshot": ("screenshot", {}),
            ".pause": ("pause_portal", {}),
            ".feed": ("feedme", {}),
            ".reset": ("resume_portal", {}),
            ".pulse": ("test_pulse", {}),
            ".terminal": ("terminal", {}),
            ".view": ("scan_directory", {}),
            ".fetch": ("read_file", {}),
            ".fetchall": ("scan_directory", {}),
            ".delete": ("delete_file", {}),
        }

        parts = text.split(None, 1)
        cmd_key = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if cmd_key == ".help":
            return

        # Determine command type and extra params
        if cmd_key in cmd_map:
            cmd_type, _ = cmd_map[cmd_key]
            extra = {}
            if cmd_type == "scan" and arg:
                extra["path"] = arg
            elif cmd_type == "scan_directory" and arg:
                extra["path"] = arg
            elif cmd_type == "read_file" and arg:
                extra["path"] = arg
            elif cmd_type == "delete_file" and arg:
                extra["path"] = arg
            elif cmd_type == "terminal" and arg:
                extra["command"] = arg
        else:
            # Unknown command — send as message
            cmd_type = "message"
            extra = {"text": text}

        # Send via Firebase
        cmd_id = send_command_to_session(session_id, cmd_type, **extra)

        # Trigger orb
        orb_state_map = {
            "screenshot": "screenshot",
            "pause_portal": "paused",
            "feedme": "feedme",
            "resume_portal": "idle",
            "test_pulse": "test_pulse",
            "terminal": "terminal",
            "scan": "command",
            "scan_directory": "command",
            "read_file": "command",
            "delete_file": "command",
            "message": "command",
        }
        orb_state = orb_state_map.get(cmd_type, "command")
        self._trigger_orb(orb_state)

        if self._current_session and self._current_session.id == session_id:
            self._session_detail.add_result("output", f"$ {text}", f"Command sent to portal...\nType: {cmd_type}\nID: {cmd_id}")

    def _on_quick_action(self, session_id, action):
        """Send a quick action command to the portal via Firebase."""
        action_map = {
            "screenshot": "screenshot",
            "feedme": "feedme",
            "paused": "pause_portal",
            "test_pulse": "test_pulse",
            "idle": "resume_portal",
        }
        cmd_type = action_map.get(action, action)
        send_command_to_session(session_id, cmd_type)

        # Trigger orb locally
        orb_state_map = {
            "screenshot": "screenshot",
            "feedme": "feedme",
            "paused": "paused",
            "test_pulse": "test_pulse",
            "idle": "idle",
        }
        orb_state = orb_state_map.get(action, "command")
        self._trigger_orb(orb_state)

        # Update session state
        for s in self._sessions:
            if s.id == session_id:
                s.orb_state = orb_state
                if self._current_session and self._current_session.id == session_id:
                    self._session_detail.update_state(orb_state)
                break

    def _trigger_orb(self, state):
        """Trigger the sidebar orb to flash a state."""
        if state == "screenshot":
            self.orb.start_screenshot()
        elif state == "paused":
            self.orb.set_paused(True)
        elif state == "feedme":
            self.orb.set_state("feedme")
        elif state == "test_pulse":
            self.orb.set_state("test_pulse")
        elif state == "terminal":
            self.orb.flash_terminal()
        elif state == "command":
            self.orb.flash_command()
        elif state == "idle":
            self.orb.set_state("idle")
            self.orb.set_paused(False)
        self._update_orb_state(state)

    def _on_portal_open_requested(self, session_id):
        """Admin clicked Open Portal — send the command to the client."""
        # Send portal_open command to the client
        send_command_to_session(session_id, "portal_open")
        # Mark this session as pending-open so we know we're waiting for the client
        self._pending_open_session_id = session_id
        # Start watching for the client's portal_opened confirmation
        self._firebase_worker.watch_for_opened(session_id)
        # Also check immediately — the portal may have already confirmed
        # (e.g. from a previous open attempt that's still in Firebase)
        data = _firebase_get(f"sessions/{session_id}")
        if isinstance(data, dict):
            po = data.get("portal_opened", {})
            if isinstance(po, dict) and po.get("opened"):
                # Already opened — emit the signal directly
                QTimer.singleShot(500, lambda sid=session_id: self._on_portal_opened(sid))

    def _on_admin_animation_done(self):
        """Admin's local portal-opening animation has reached full size."""
        # The animation widget now shows 'Waiting for portal to connect...'
        pass

    def _on_portal_opened(self, session_id):
        """Client confirmed portal is open — switch to connected view."""
        if getattr(self, "_pending_open_session_id", None) == session_id:
            self._pending_open_session_id = None
        # Start watching for incoming chat from the portal
        self._firebase_worker.watch_chat(session_id)
        # Also start watching for command results
        self._firebase_worker.watch_results(session_id)
        if self._current_session and self._current_session.id == session_id:
            self._session_detail._on_portal_opened()
        # Portal is now connected — grow the dormant needle point into an active portal
        self._set_orb_connected(True)
        self._update_orb_state("idle")

    def _set_orb_connected(self, connected):
        """Drive the sidebar orb between dormant (awaiting) and active states.

        On the first connection we play the needle→expand opening animation;
        when the last connection drops we fall back to the dormant black portal.
        """
        if connected:
            self._ambient_timer.stop()
            self._ambient_opening = False
            if not self._orb_connected:
                self._orb_connected = True
                self.orb.start_portal_opening()
        else:
            if self._orb_connected:
                self._orb_connected = False
                self.orb.set_state("awaiting")

    def _ambient_rift_tick(self):
        """Dormant ambient effect: the rift occasionally opens and closes when no session is active."""
        if self._orb_connected or self._ambient_opening:
            return
        self._ambient_opening = True
        self._orb_status.setText("RIFT OPENING")
        self.orb.start_portal_opening()
        # Open animation (~2.5s), stay open (~2.5s), then reverse-close (~2.5s)
        QTimer.singleShot(6000, self._ambient_rift_close)

    def _ambient_rift_close(self):
        """Finish the ambient open/close cycle and schedule the next one."""
        if self._orb_connected:
            self._ambient_opening = False
            return
        self._orb_status.setText("RIFT CLOSING")
        self.orb.start_portal_closing()
        QTimer.singleShot(3200, lambda: (
            self._update_orb_state("awaiting"),
            self._schedule_ambient_rift()
        ))

    def _schedule_ambient_rift(self):
        """Schedule the next ambient open/close cycle if still dormant."""
        self._ambient_opening = False
        if self._orb_connected:
            return
        delay = random.randint(25000, 120000)  # 25s-2min of dormancy between displays
        self._ambient_timer.start(delay)

    def _on_chat_received(self, session_id, msg):
        """Incoming chat message from the portal client."""
        text = msg.get("text", "")
        sender = msg.get("sender", "portal")
        msg_type = msg.get("type", "")
        msg_id = msg.get("id", "")
        if not text:
            return
        # Find the session and add the message
        for s in self._sessions:
            if s.id == session_id:
                # Deduplicate messages when a session is rewatched
                if msg_id and msg_id in s._seen_chat_ids:
                    break
                if msg_id:
                    s._seen_chat_ids.add(msg_id)
                s.chat.append((sender, text, datetime.now()))
                # Fast pink flash on every incoming message
                self.orb.flash_alert()
                if self._current_session and self._current_session.id == session_id:
                    self._session_detail._add_chat_bubble(text, is_admin=False)
                break

    def _update_orb_state(self, state):
        info, color = STATE_INFO.get(state, ("UNKNOWN", PALETTE["muted"]))
        self._orb_status.setText(info)
        self._orb_status.setStyleSheet(f"color: {color}; background: transparent; border: none; letter-spacing: 2px;")

    def _update_uptime(self):
        elapsed = time.time() - self._start_time
        self._session_list.update_uptime(elapsed)

    def closeEvent(self, event):
        """Confirm before closing, then clean up background threads."""
        dialog = RiftConfirmDialog(
            "Close Rift Admin Console?",
            "Are you sure you want to close the admin console?",
            confirm_text="Close",
            cancel_text="Cancel",
            parent=self
        )
        dialog.move(self.mapToGlobal(self.rect().center() - dialog.rect().center()))
        if dialog.exec() != QDialog.DialogCode.Accepted:
            event.ignore()
            return
        try:
            self._firebase_worker.stop()
            self._firebase_thread.quit()
            self._firebase_thread.wait(2000)
        except Exception:
            pass
        super().closeEvent(event)

    def resizeEvent(self, event):
        """Keep the floating sidebar positioned over the left edge."""
        super().resizeEvent(event)
        if hasattr(self, "_sidebar"):
            margin = 12
            self._sidebar.setGeometry(margin, margin, self._sidebar.width(), self.height() - 2 * margin)

    # ---- Maximize / restore ----
    def _toggle_max_restore(self):
        if self.isMaximized():
            self.showNormal()
            self._max_btn.setText("□")
        else:
            # Remember the current geometry so a manual resize afterward feels natural
            self._normal_geometry = self.geometry()
            self.showMaximized()
            self._max_btn.setText("❐")

    def changeEvent(self, event):
        # Keep the maximize/restore glyph in sync with the actual window state
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "_max_btn"):
            self._max_btn.setText("❐" if self.isMaximized() else "□")
        super().changeEvent(event)

    # ---- Frameless window dragging + edge resizing ----
    def _edge_at(self, pos):
        """Return a set of edges ('left'/'right'/'top'/'bottom') near the given local pos."""
        m = self._resize_margin
        edges = set()
        if pos.x() <= m:
            edges.add("left")
        elif pos.x() >= self.width() - m:
            edges.add("right")
        if pos.y() <= m:
            edges.add("top")
        elif pos.y() >= self.height() - m:
            edges.add("bottom")
        return edges

    def _cursor_for_edges(self, edges):
        if ("left" in edges and "top" in edges) or ("right" in edges and "bottom" in edges):
            return Qt.CursorShape.SizeFDiagCursor
        if ("right" in edges and "top" in edges) or ("left" in edges and "bottom" in edges):
            return Qt.CursorShape.SizeBDiagCursor
        if "left" in edges or "right" in edges:
            return Qt.CursorShape.SizeHorCursor
        if "top" in edges or "bottom" in edges:
            return Qt.CursorShape.SizeVerCursor
        return Qt.CursorShape.ArrowCursor

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._edge_at(event.position().toPoint())
            if edges and not self.isMaximized():
                self._resize_edge = edges
                self._resize_start_geo = self.geometry()
                self._resize_start_mouse = event.globalPosition().toPoint()
            elif event.position().y() <= 60:
                # Only allow dragging from the top bar area (sidebar header / content top)
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        # Resizing takes priority when an edge grab is active
        if self._resize_edge and (event.buttons() & Qt.MouseButton.LeftButton):
            self._perform_resize(event.globalPosition().toPoint())
            event.accept()
            return
        if (event.buttons() & Qt.MouseButton.LeftButton) and self._drag_pos is not None:
            if self.isMaximized():
                # Dragging a maximized window restores it first
                self._toggle_max_restore()
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
            return
        # No button held — update the cursor to hint at resizable edges
        if not self.isMaximized():
            self.setCursor(self._cursor_for_edges(self._edge_at(event.position().toPoint())))
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def _perform_resize(self, global_pos):
        delta = global_pos - self._resize_start_mouse
        geo = self._resize_start_geo
        x, y, w, h = geo.x(), geo.y(), geo.width(), geo.height()
        min_w = self.minimumWidth()
        min_h = self.minimumHeight()
        if "left" in self._resize_edge:
            new_w = max(min_w, w - delta.x())
            x = x + (w - new_w)
            w = new_w
        elif "right" in self._resize_edge:
            w = max(min_w, w + delta.x())
        if "top" in self._resize_edge:
            new_h = max(min_h, h - delta.y())
            y = y + (h - new_h)
            h = new_h
        elif "bottom" in self._resize_edge:
            h = max(min_h, h + delta.y())
        self.setGeometry(x, y, w, h)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        self._resize_edge = None
        self._resize_start_geo = None
        self._resize_start_mouse = None

    def mouseDoubleClickEvent(self, event):
        # Double-click the title area toggles maximize (standard window behavior)
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() <= 48:
            self._toggle_max_restore()
            event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self._stack.currentIndex() == 4:
                self._back_to_list()
            elif self._new_session_dialog:
                self._close_new_session_dialog()
            else:
                self.close()
        elif event.key() == Qt.Key.Key_1:
            self._switch_view(0)
        elif event.key() == Qt.Key.Key_2:
            self._switch_view(1)
        elif event.key() == Qt.Key.Key_3:
            self._switch_view(2)
        elif event.key() == Qt.Key.Key_4:
            self._switch_view(3)
        else:
            super().keyPressEvent(event)


# ------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------
def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = RiftAdminConsole()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
