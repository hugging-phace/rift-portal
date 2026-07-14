"""
Magnet Agent — AI command center for the Magnet remote support platform.
Controls client instances, sends commands, views screenshots, chats.

Aesthetic: Presence design language — calm graphite glass, soft volumetric light,
and a living field of intelligent orbs.
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

from magnet_vision import VisionServer, get_default_ip

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

def _log(msg):
    """Minimal debug log for the Agent console."""
    print(msg, flush=True)

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
                                      headers={"User-Agent": "MagnetAgent/1.0"})
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
# UI: dimensional tear orb widget
# ------------------------------------------------------------------
class OrbWidget(QWidget):
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
            n = OrbWidget._Node(self, i)
            self._nodes.append(n)
        for i in range(80):
            p = OrbWidget._Particle(self)
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
        elif state == "screenshot":
            self._node_target = 3
            self._particle_target = 50
            self._speed_target = 1.0
            self._scale_target = 1.05
            self._tint_target = color
            self._glow_target = 0.7
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

    def start_screenshot(self):
        self._previous_state = self._state if self._state != "screenshot" else self._previous_state
        self.set_state("screenshot")

    def end_screenshot(self):
        self.set_state(self._previous_state if self._previous_state not in ("screenshot", "") else "idle")

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

        # ---- 5. Screenshot quick flash ----
        if self._state == "screenshot" and self._time - getattr(self, "_screenshot_time", 0) < 0.25:
            shot_grad = QRadialGradient(cx, cy, base_r * 0.5)
            shot_grad.setColorAt(0, QColor(230, 230, 245, 120))
            shot_grad.setColorAt(0.5, QColor(230, 230, 245, 30))
            shot_grad.setColorAt(1, QColor(230, 230, 245, 0))
            painter.setBrush(QBrush(shot_grad))
            painter.drawEllipse(QPointF(cx, cy), base_r * 0.5, base_r * 0.5)

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



class FirebaseWorker(_QObj):
    """Background worker that polls Firebase for session list and results."""

    sessions_updated = Signal(list)   # list of session dicts from Firebase
    result_received = Signal(str, dict)  # (session_id, result_data)
    portal_opened = Signal(str)  # session_id — client confirmed portal opened
    chat_received = Signal(str, dict)  # (session_id, chat_msg) — incoming chat from portal
    poll_status = Signal(str)  # human-readable status/error for debugging
    refresh = Signal()  # request an immediate session poll in the worker thread

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
            # Treat anything not explicitly "open" as inactive, but keep the
            # original status (e.g. "user-closed", "closed") so the admin UI can
            # show the close alert and zip-download option.
            is_open = (status == "open")
            session_status = "active" if is_open else status
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
ADMIN_BG = "#0A0A0C"          # near-black background
ADMIN_PANEL = "#101115"       # black glass panels
ADMIN_PANEL_LIGHT = "#161820" # slightly lighter
ADMIN_GRID = "#1E212B"        # grid line color
ADMIN_HUD = "#61D9FF"         # cyan HUD accent
ADMIN_HUD_DIM = "#8A8D99"     # dim neutral
ADMIN_MONO = "Consolas"       # monospace font for data

# ------------------------------------------------------------------
# Theme system
# ------------------------------------------------------------------
THEMES = {
    "Presence": {
        "is_dark": True,
        "bg": "#0A0A0C",
        "panel_grad_top": (16, 17, 23, 252),
        "panel_grad_mid": (12, 13, 18, 253),
        "panel_grad_bot": (10, 10, 12, 254),
        "sidebar_grad_top": (18, 19, 25, 252),
        "sidebar_grad_mid": (14, 15, 20, 253),
        "sidebar_grad_bot": (10, 11, 15, 254),
        "grid_minor": (30, 31, 38, 30),
        "grid_major": (45, 47, 58, 22),
        "border": (120, 120, 140, 28),
        "sidebar_border": (120, 120, 140, 35),
        "main_border": (100, 102, 120, 30),
        "text": "#E8E9F0",
        "muted": "#8A8D99",
        "accent": "#7367FF",
        "accent_bright": "#A18CFF",
        "hud": "#61D9FF",
        "hud_dim": "#4A5A7A",
        "success": "#22c55e",
        "error": "#ef4444",
        "input_bg": "#101115",
        "chat_bg": "#0A0A0C",
        "bubble_user": "#1E2030",
        "bubble_atlas": "#14151A",
        "bubble_border": "#2A2D3A",
        "nav_active_bg": "rgba(115, 103, 255, 30)",
        "nav_hover_bg": "rgba(255, 255, 255, 8)",
        "sheen": (255, 255, 255, 8),
    },
    "Sonic Wave - Dark Mode": {
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

_current_theme_name = "Presence"
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

# Sync PALETTE with the default Presence theme so hardcoded references below match
apply_theme(_current_theme_name)

# State display info
STATE_INFO = {
    "idle":       ("IDLE",       PALETTE["muted"]),
    "command":    ("COMMAND",    PALETTE["active"]),
    "terminal":   ("TERMINAL",   PALETTE["accent_bright"]),
    "screenshot": ("SCREENSHOT", "#E8E9F0"),
    "test_pulse": ("PULSE",      PALETTE["error"]),
    "paused":     ("PAUSED",     PALETTE["warning"]),
    "feedme":     ("FEEDME",     PALETTE["success"]),
    "vision":     ("VISION",     PALETTE["accent_bright"]),
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


def download_session_zip(session, parent=None):
    """Collect files/screenshots from a session and prompt to save a zip."""
    try:
        files = []  # list of (filename, bytes)
        screenshot_idx = 0
        for r in session.results:
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

        default_name = f"rift_{session.id}_files.zip"
        path, _ = QFileDialog.getSaveFileName(parent, "Save Zip", default_name, "Zip files (*.zip)")
        if not path:
            return

        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for name, data in files:
                zf.writestr(name, data)
    except Exception:
        pass


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
        download_btn.clicked.connect(lambda: download_session_zip(self._session, self))
        layout.addWidget(download_btn)

    def _download_zip(self):
        download_session_zip(self._session, self)


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
        self._session = session
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

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        info_row = QWidget(self)
        info_row.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        info_row.setFixedHeight(64)
        info_layout = QHBoxLayout(info_row)
        info_layout.setContentsMargins(14, 8, 14, 8)
        info_layout.setSpacing(12)

        self._dot = QLabel()
        self._dot.setFixedSize(10, 10)
        self._dot.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        info_layout.addWidget(self._dot)

        # Name + host info
        name_host_layout = QVBoxLayout()
        name_host_layout.setSpacing(2)

        self._name_label = QLabel()
        self._name_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        self._name_label.setStyleSheet(f"color: {PALETTE['text']}; background: transparent; border: none;")
        self._name_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        name_host_layout.addWidget(self._name_label)

        self._host_label = QLabel()
        self._host_label.setFont(QFont(ADMIN_MONO, 7))
        self._host_label.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none;")
        self._host_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        name_host_layout.addWidget(self._host_label)

        info_layout.addLayout(name_host_layout, 1)

        self._state_label = QLabel()
        self._state_label.setFont(QFont(ADMIN_MONO, 7, QFont.Weight.Bold))
        self._state_label.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none; letter-spacing: 1px;")
        self._state_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        info_layout.addWidget(self._state_label)

        main_layout.addWidget(info_row)

        self._zip_alert = None

        self._apply_session(session)

    def _apply_session(self, session):
        """Apply session data to child widgets and colors."""
        card_state = getattr(session, "card_state", "inactive")
        border_color, glow_color = self.STATE_COLORS.get(card_state, self.STATE_COLORS["inactive"])

        self._session_id = session.id
        self._session = session
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

        # If the user has closed this session, show the zip-download alert inline on the card.
        is_closed = session.status in ("user-closed", "closed")
        if is_closed:
            if self._zip_alert is None:
                self._zip_alert = QFrame(self)
                self._zip_alert.setAutoFillBackground(True)
                self._zip_alert.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
                self._zip_alert.setStyleSheet("background-color: rgba(120, 40, 40, 180); border: 1px solid rgba(220, 80, 80, 120); border-radius: 6px;")
                zl = QVBoxLayout(self._zip_alert)
                zl.setContentsMargins(8, 6, 8, 6)
                zl.setSpacing(4)
                zh = QLabel("User closed this Rift")
                zh.setStyleSheet(f"color: {PALETTE['error']}; background: transparent; font-weight: bold;")
                zh.setFont(QFont(ADMIN_MONO, 8, QFont.Weight.Bold))
                zh.setWordWrap(True)
                zm = QLabel("Save important documents before the session is purged.")
                zm.setStyleSheet(f"color: {PALETTE['text']}; background: transparent;")
                zm.setFont(QFont(ADMIN_MONO, 7))
                zm.setWordWrap(True)
                self._zip_alert._download_btn = QPushButton("Download Zip")
                self._zip_alert._download_btn.setFixedHeight(30)
                self._zip_alert._download_btn.setFont(QFont(ADMIN_MONO, 8, QFont.Weight.Bold))
                self._zip_alert._download_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                self._zip_alert._download_btn.setStyleSheet(f"""
                    QPushButton {{
                        background: rgba(220, 60, 60, 25);
                        color: {PALETTE['error']};
                        border: 1px solid rgba(220, 60, 60, 60);
                        border-radius: 4px;
                        padding: 0 14px;
                    }}
                    QPushButton:hover {{ background: rgba(220, 60, 60, 45); }}
                """)
                self._zip_alert._download_btn.clicked.connect(self._download_zip)
                zl.addWidget(zh)
                zl.addWidget(zm)
                zl.addWidget(self._zip_alert._download_btn)
                self.layout().addWidget(self._zip_alert)
            self._zip_alert.setVisible(True)
            self._zip_alert.setFixedHeight(116)
            self.setFixedHeight(180)
            self._border_color = (220, 60, 60, 80)
            self._glow_color = (255, 80, 80)
            self.layout().activate()
            self._zip_alert.update()
            self.update()
        else:
            if self._zip_alert is not None:
                self._zip_alert.setVisible(False)
            self.setFixedHeight(64)
            # Reset border/glow to default inactive colors
            self._border_color = (60, 60, 80, 30)
            self._glow_color = (90, 90, 110)

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

    def _download_zip(self):
        """Download a zip of all shared files/screenshots for this session."""
        download_session_zip(self._session, self)

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
        layout.addWidget(self._active_scroll, 2)

        # Fallback click detector on the scroll viewport — catches clicks that
        # the card itself may miss due to refresh/reparent timing.
        self._active_scroll.viewport().installEventFilter(self)

        # Inactive sessions (collapsed)
        self._inactive_toggle = QPushButton(">  INACTIVE / EXPIRED")
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
        self._inactive_collapsed = True
        self._inactive_toggle.clicked.connect(self._toggle_inactive)
        layout.addWidget(self._inactive_toggle)

        self._inactive_scroll = QScrollArea()
        self._inactive_scroll.setMinimumHeight(200)
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
        layout.addWidget(self._inactive_scroll, 1)

        # Fallback click detector for inactive list too
        self._inactive_scroll.viewport().installEventFilter(self)

        # Poll status footer
        self._poll_status_label = QLabel("Firebase: waiting for first poll...")
        self._poll_status_label.setFont(QFont(ADMIN_MONO, 7))
        self._poll_status_label.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none; padding: 4px 0;")
        layout.addWidget(self._poll_status_label)

    def _toggle_inactive(self):
        self._inactive_collapsed = not self._inactive_collapsed
        self._inactive_scroll.setVisible(not self._inactive_collapsed)
        prefix = ">" if self._inactive_collapsed else "v"
        self._inactive_toggle.setText(f"{prefix}  INACTIVE / EXPIRED")

    def eventFilter(self, watched, event):
        """Fallback: route clicks on the scroll viewport to the card beneath.

        Clicks on interactive children (buttons) are left alone so their own
        signals fire. Clicks on the card itself or non-interactive children
        open the session detail view.
        """
        if event.type() == QEvent.Type.MouseButtonPress:
            mouse_event = event
            if mouse_event.button() == Qt.MouseButton.LeftButton:
                viewport = watched
                pos = viewport.mapTo(self._active_container if viewport == self._active_scroll.viewport() else self._inactive_container, mouse_event.pos())
                target = self._active_container.childAt(pos) if viewport == self._active_scroll.viewport() else self._inactive_container.childAt(pos)
                # Let buttons and other interactive children handle their own clicks.
                if isinstance(target, QPushButton):
                    return False
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
        # Show user-closed sessions at the top of the inactive list so the close alert
        # and zip-download button are immediately visible without scrolling.
        inactive = sorted(inactive, key=lambda s: (0 if s.status in ("user-closed", "closed") else 1, s.last_seen or ""))

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
        ".vision": "vision",
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

        # Quick actions — Screenshot, Feed, Pause, Pulse, Vision
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
        self.btn_vision = ControlButton("Vision", "220,80,180")
        actions_row.addWidget(self.btn_screenshot)
        actions_row.addWidget(self.btn_feed)
        actions_row.addWidget(self.btn_pause)
        actions_row.addWidget(self.btn_pulse)
        actions_row.addWidget(self.btn_vision)
        left_layout.addLayout(actions_row)

        # Vision feed panel (shown when a Vision stream is active)
        self._vision_feed = QLabel()
        self._vision_feed.setFixedHeight(260)
        self._vision_feed.setStyleSheet(f"""
            QLabel {{
                background: {PALETTE['bg']};
                border: 1px solid rgba(255, 255, 255, 20);
                border-radius: 8px;
            }}
        """)
        self._vision_feed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._vision_feed.setScaledContents(True)
        self._vision_feed.setVisible(False)
        left_layout.addWidget(self._vision_feed)

        self._vision_status = QLabel("Vision inactive")
        self._vision_status.setFont(QFont(ADMIN_MONO, 7, QFont.Weight.Bold))
        self._vision_status.setStyleSheet(f"color: {PALETTE['muted']}; background: transparent; border: none; letter-spacing: 1px;")
        self._vision_status.setVisible(False)
        left_layout.addWidget(self._vision_status)

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
        self.btn_vision.clicked.connect(lambda: self._quick("vision"))

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

        # Hand the command to the admin console so it sends a single rift_command
        # (and updates local orb state) without duplicating typed/rift commands.
        self.command_sent.emit(self._session.id, text)

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

    def set_vision_active(self, active: bool, status: str = ""):
        """Show or hide the Vision feed panel and update its status text."""
        self._vision_feed.setVisible(active)
        self._vision_status.setVisible(active)
        if status:
            self._vision_status.setText(status)

    def set_vision_frame(self, pixmap: QPixmap):
        """Display a new Vision frame, scaling it to the feed area."""
        if not pixmap or pixmap.isNull():
            return
        scaled = pixmap.scaled(
            self._vision_feed.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._vision_feed.setPixmap(scaled)
        self._vision_status.setText("Live")

    def clear_vision_frame(self):
        self._vision_feed.clear()


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
class MagnetAgent(QWidget):
    """Magnet Agent window — AI command center with session-based content."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Magnet Agent")
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

        title = QLabel("Magnet")
        title.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {PALETTE['text']}; background: transparent; border: none; letter-spacing: 0px;")
        title_layout.addWidget(title)
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
            ("Commands", 1),
            ("Terminal", 2),
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
        # Force refresh requests to run in the worker thread, not the UI thread
        self._firebase_worker.refresh.connect(self._firebase_worker._poll_all_sessions)
        self._firebase_thread.started.connect(self._firebase_worker.run)
        self._firebase_thread.start()

        # ---- Vision server (receives screen stream from clients) ----
        self._vision_server = VisionServer(self)
        self._vision_server.server_started.connect(self._on_vision_server_started)
        self._vision_server.client_connected.connect(self._on_vision_client_connected)
        self._vision_server.client_disconnected.connect(self._on_vision_client_disconnected)
        self._vision_server.frame_received.connect(self._on_vision_frame)
        self._vision_server.error.connect(lambda msg: _log(f"[Vision] {msg}"))
        self._vision_session_id = None
        self._vision_target_session_id = None

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
        # Send force_close command to the portal and mark the session as closed
        # in Firebase so the admin UI immediately shows the close alert.
        send_command_to_session(session_id, "force_close")
        try:
            _firebase_put(f"sessions/{session_id}/status", "closed")
        except Exception:
            pass
        # Stop watching results
        self._firebase_worker.unwatch_results(session_id)
        for s in self._sessions:
            if s.id == session_id:
                s.status = "closed"
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
        """Manually refresh the session list from Firebase in the worker thread."""
        self._firebase_worker.refresh.emit()

    def _cleanup_stale_sessions(self, hours=1):
        """Mark stale open sessions as closed so they disappear from the active list."""
        cleaned = cleanup_stale_sessions(max_age_hours=hours)
        # Force a session refresh immediately in the worker thread
        self._firebase_worker.refresh.emit()

    def _purge_closed_sessions(self):
        """Delete all non-open sessions from Firebase to clean up history."""
        deleted = purge_all_closed_sessions()
        # Force a session refresh immediately in the worker thread
        self._firebase_worker.refresh.emit()

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
        """Send a typed command to the portal client via Firebase.

        All commands starting with '.' are sent as a single rift_command so the
        portal interprets them directly. This avoids sending both a rift_command
        and a separate typed command (which produced "command errors" even though
        the action succeeded)."
        """
        text = text.strip()
        if not text:
            return

        cmd_word = text.split(None, 1)[0].lower()
        if cmd_word == ".help":
            return

        # Determine orb state for local visual feedback
        orb_state_map = {
            ".scan": "command",
            ".view": "command",
            ".fetch": "command",
            ".fetchall": "command",
            ".delete": "command",
            ".terminal": "terminal",
            ".screenshot": "screenshot",
            ".pause": "paused",
            ".feed": "feedme",
            ".pulse": "test_pulse",
            ".reset": "idle",
            ".vision": "vision",
        }

        if cmd_word.startswith("."):
            # Send the raw .rift command to the portal interpreter
            send_command_to_session(session_id, "rift_command", command=text)
            orb_state = orb_state_map.get(cmd_word, "command")
        else:
            # Plain text — send as a message command
            send_command_to_session(session_id, "message", text=text)
            orb_state = "command"

        self._trigger_orb(orb_state)

        if self._current_session and self._current_session.id == session_id:
            self._session_detail.update_state(orb_state)
            self._session_detail.add_result("output", f"$ {text}", "Command sent to portal...\nWaiting for response...")

    def _on_quick_action(self, session_id, action):
        """Send a quick action command to the portal via Firebase.

        Quick action buttons toggle their mode on the second press. Instead of
        sending a separate typed command and a rift_command, we send a single
        rift_command (e.g. '.feed') and let the portal toggle the state itself.
        """
        # Map the action name to the rift_command text
        action_cmd_map = {
            "screenshot": ".screenshot",
            "feedme": ".feed",
            "paused": ".pause",
            "test_pulse": ".pulse",
            "vision": ".vision",
        }
        # Vision streaming is handled locally by the Agent server + start_vision command.
        if action == "vision":
            self._toggle_vision_stream(session_id)
            return

        cmd_text = action_cmd_map.get(action, action)
        send_command_to_session(session_id, "rift_command", command=cmd_text)

        # Toggle the local orb state for Feed/Pause/Pulse; Screenshot is one-shot
        toggle_actions = {"feedme", "paused", "test_pulse"}
        target_state = action
        for s in self._sessions:
            if s.id == session_id:
                if action in toggle_actions and s.orb_state == action:
                    target_state = "idle"
                s.orb_state = target_state
                if self._current_session and self._current_session.id == session_id:
                    self._session_detail.update_state(target_state)
                break

        self._trigger_orb(target_state)

    def _trigger_orb(self, state):
        """Trigger the sidebar orb to show a state."""
        if state == "screenshot":
            self.orb.flash_command()
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
        elif state == "vision":
            self.orb.set_state("vision")
        elif state == "idle":
            self.orb.set_state("idle")
            self.orb.set_paused(False)
        self._update_orb_state(state)

    # ------------------------------------------------------------------
    # Vision streaming controls
    # ------------------------------------------------------------------
    def _toggle_vision_stream(self, session_id):
        """Start or stop the Vision screen stream for a session."""
        if self._vision_session_id == session_id or self._vision_target_session_id == session_id:
            self._stop_vision_stream()
            return
        # Stop any existing stream first
        self._stop_vision_stream()
        self._vision_target_session_id = session_id
        # Start the TCP server; once it is listening we send the start_vision command.
        self._vision_server.start_server(port=0)

    def _stop_vision_stream(self):
        """Stop the Vision server and tell the client to stop streaming."""
        if self._vision_session_id:
            send_command_to_session(self._vision_session_id, "stop_vision")
        elif self._vision_target_session_id:
            send_command_to_session(self._vision_target_session_id, "stop_vision")
        self._vision_server.stop_server()
        self._vision_session_id = None
        self._vision_target_session_id = None
        if self._current_session:
            self._session_detail.set_vision_active(False)
        self._trigger_orb("idle")

    def _on_vision_server_started(self, host, port):
        """Server is listening — send the client the endpoint and update UI."""
        session_id = self._vision_target_session_id
        if not session_id:
            return
        endpoint = {"host": host, "port": port}
        send_command_to_session(session_id, "start_vision", endpoint=endpoint)
        if self._current_session and self._current_session.id == session_id:
            self._session_detail.set_vision_active(True, "Waiting for client...")

    def _on_vision_client_connected(self, session_id):
        """Client connected to the Vision server."""
        self._vision_session_id = session_id
        self._vision_target_session_id = session_id
        if self._current_session and self._current_session.id == session_id:
            self._session_detail.set_vision_active(True, "Live")
            self._session_detail.update_state("vision")
        self._trigger_orb("vision")

    def _on_vision_client_disconnected(self, session_id):
        """Client disconnected — clear the feed and reset state."""
        if self._vision_session_id == session_id:
            self._vision_session_id = None
            self._vision_target_session_id = None
            if self._current_session:
                self._session_detail.set_vision_active(False)
            self._trigger_orb("idle")

    def _on_vision_frame(self, session_id, jpeg_bytes):
        """Decode an incoming Vision frame and display it in the session detail."""
        try:
            img = QImage.fromData(jpeg_bytes)
            if img.isNull():
                return
            pixmap = QPixmap.fromImage(img)
            if self._current_session and self._current_session.id == session_id:
                self._session_detail.set_vision_frame(pixmap)
        except Exception as e:
            _log(f"Vision frame decode error: {e}")

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
        try:
            if getattr(self, "_vision_server", None):
                self._vision_server.stop_server()
                self._vision_server.wait(2000)
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

    window = MagnetAgent()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
