"""
magnet_orb.py
Shared Presence orb for Magnet Client and Magnet Agent.

A living concentration of energy: three luminous orbs that orbit, breathe,
occasionally merge, and occasionally divide into smaller orbs before reforming.
No particles, no stars, no dust, no glitter.
"""

import math
import random

from PySide6.QtCore import Qt, QTimer, QElapsedTimer, QPointF, Signal
from PySide6.QtGui import QColor, QPainter, QRadialGradient, QLinearGradient, QBrush, QPen, QPainterPath
from PySide6.QtWidgets import QWidget

# ------------------------------------------------------------------
# State colour overrides — kept subtle and professional
# ------------------------------------------------------------------
_STATE_COLORS = {
    "awaiting":        None,
    "portal_opening":  QColor(115, 103, 255),
    "portal_closing":  QColor(115, 103, 255),
    "idle":            QColor(115, 103, 255),
    "command":         QColor(97, 217, 255),
    "terminal":        QColor(138, 107, 255),
    "test_pulse":      QColor(235, 90, 80),
    "paused":          QColor(255, 180, 70),
    "feedme":          QColor(120, 220, 160),
    "vision":          QColor(180, 140, 255),
}


def _lerp(a, b, t):
    return a + (b - a) * t


def _blend_color(a: QColor, b: QColor, t: float = 0.5) -> QColor:
    return QColor(
        int(_lerp(a.red(), b.red(), t)),
        int(_lerp(a.green(), b.green(), t)),
        int(_lerp(a.blue(), b.blue(), t)),
    )


class OrbWidget(QWidget):
    """A living concentration of luminous energy.

    Three primary orbs drift in slow, non-repeating orbits. They breathe,
    occasionally move close enough to merge visually, and occasionally split
    into smaller orbs before reforming. The feeling is calm, intelligent and
    ethereal — not a particle system and not a magic spell.
    """

    state_changed = Signal(str)
    clicked = Signal()

    class _PrimaryOrb:
        __slots__ = (
            "angle", "radius", "radius_base", "target_radius", "radius_phase",
            "radius_speed", "orbit_speed", "orbit_phase", "x", "y", "size",
            "target_size", "alpha", "target_alpha", "color", "core_color",
            "pulse_phase", "merge_scale",
        )

        def __init__(self, owner, index):
            side = min(owner.width(), owner.height())
            base_r = side / 2 * 0.80 if side > 0 else 60

            # Three primary orbs live in distinct orbital bands so all are visible.
            bands = [0.22, 0.40, 0.58]
            self.radius_base = bands[index % len(bands)]
            self.angle = random.random() * math.pi * 2
            self.radius_phase = random.random() * math.pi * 2
            self.radius_speed = 0.08 + random.random() * 0.10
            self.orbit_speed = (0.06 + random.random() * 0.06) * (1 if random.random() > 0.5 else -1)
            self.orbit_phase = random.random() * math.pi * 2
            self.radius = base_r * self.radius_base
            self.target_radius = self.radius
            self.size = base_r * 0.11
            self.target_size = self.size
            self.alpha = 0.0
            self.target_alpha = 180
            self.color = QColor(115, 103, 255)
            self.core_color = QColor(235, 236, 245)
            self.pulse_phase = random.random() * math.pi * 2
            self.x = 0.0
            self.y = 0.0
            self.merge_scale = 1.0

    class _SubOrb:
        __slots__ = (
            "x", "y", "angle", "radius", "target_radius", "size", "alpha", "color",
            "core_color", "speed", "anchor", "pulse_phase",
        )

        def __init__(self, owner, anchor_index, index):
            side = min(owner.width(), owner.height())
            base_r = side / 2 * 0.80 if side > 0 else 60
            anchor = owner._orbs[anchor_index]

            self.anchor = anchor_index
            self.angle = anchor.angle + (index - 0.5) * 0.45 + random.random() * 0.1
            self.radius = base_r * 0.10
            self.target_radius = base_r * 0.30
            self.size = base_r * 0.035
            self.alpha = 0.0
            self.x = 0.0
            self.y = 0.0
            self.color = QColor(115, 103, 255)
            self.core_color = QColor(235, 236, 245)
            self.speed = (0.15 + random.random() * 0.15) * (1 if random.random() > 0.5 else -1)
            self.pulse_phase = random.random() * math.pi * 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(160, 160)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        self._state = "awaiting"
        self._previous_state = "idle"
        self._orbs = []
        self._sub_orbs = []
        self._initialized = False

        self._time = 0.0
        self._breath = 0.0
        self._phase = random.random() * math.pi * 2
        self._flash = 0.0
        self._ripple = []

        # Mouse / proximity
        self._mouse_x = 0.0
        self._mouse_y = 0.0
        self._target_proximity = 0.0
        self._proximity = 0.0
        self._lean_x = 0.0
        self._lean_y = 0.0

        # State targets
        self._speed_target = 0.1
        self._scale_target = 0.15
        self._glow_target = 0.0
        self._tint_target = None
        self._converge_target = False

        # Current values
        self._speed = 0.1
        self._scale = 0.15
        self._glow = 0.0
        self._tint = None
        self._converge = False

        self._portal_progress = 0.0
        self._vision_flash_time = -1.0

        # Split / merge events
        self._split_active = False
        self._split_phase = 0.0
        self._split_duration = 1.0
        self._next_event = 6.0 + random.random() * 10.0

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
        if self.width() == 0 or self.height() == 0:
            return
        for i in range(3):
            self._orbs.append(OrbWidget._PrimaryOrb(self, i))
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
            self._portal_progress = self._lerp(self._portal_progress, 1.0 if self._state != "awaiting" else 0.0, ease)

        # Flash decay
        if self._flash > 0:
            self._flash = max(0, self._flash - dt * 6.0)

        # Breathing
        self._breath = 0.5 + 0.5 * math.sin(self._time * 0.4)

        # Mouse proximity
        prox_ease = 1.0 - math.exp(-dt * 3.0)
        self._proximity = self._lerp(self._proximity, self._target_proximity, prox_ease)

        # Ripples
        for r in self._ripple:
            r["age"] += dt
        self._ripple = [r for r in self._ripple if r["age"] < r["max_age"]]

        # Update orbs
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        side = min(w, h)
        clip_r = side / 2 - 2
        base_r = clip_r * 0.85 * self._scale
        if self._state == "awaiting":
            base_r = clip_r * 0.18 * (0.7 + 0.3 * self._breath)

        cx += self._lean_x * base_r
        cy += self._lean_y * base_r

        self._update_orbs(dt, cx, cy, base_r, self._speed,
                          (self._mouse_x, self._mouse_y, self._proximity))

        self.update()

    def _state_alpha(self):
        """Target alpha for primary orbs based on current state."""
        if self._state == "awaiting":
            return 50
        if self._state == "paused":
            return 80
        if self._state in ("command", "terminal", "test_pulse"):
            return 230
        if self._state == "feedme":
            return 220
        if self._state == "vision":
            return 210
        return 190

    def _update_orbs(self, dt, cx, cy, base_r, speed, mouse):
        mx, my, mprox = mouse
        target_alpha = self._state_alpha()
        tint = self._tint if self._tint else QColor(115, 103, 255)

        # Schedule / advance split events
        if not self._split_active and self._time > self._next_event:
            self._start_split(base_r)

        if self._split_active:
            self._split_phase += dt / self._split_duration
            if self._split_phase >= 1.0:
                self._end_split(base_r)

        # Update primary orbs
        for orb in self._orbs:
            # Radius target: calm breathing orbit with a slow global drift
            if self._state == "feedme":
                r_target = base_r * 0.12
            elif self._state == "paused":
                r_target = base_r * 0.14
            elif self._state == "awaiting":
                r_target = base_r * 0.08
            else:
                r_target = base_r * (
                    orb.radius_base
                    + 0.12 * math.sin(self._time * orb.radius_speed + orb.radius_phase)
                    + 0.04 * math.sin(self._time * 0.025 + self._phase + orb.orbit_phase)
                )

            orb.target_radius = r_target
            orb.radius += (orb.target_radius - orb.radius) * dt * 0.35

            # Angle
            orb.angle += orb.orbit_speed * dt * speed

            # Position, with very subtle mouse lean
            lean_x = (mx - cx) * mprox * 0.12
            lean_y = (my - cy) * mprox * 0.12
            orb.x = cx + math.cos(orb.angle + orb.orbit_phase) * orb.radius + lean_x
            orb.y = cy + math.sin(orb.angle + orb.orbit_phase) * orb.radius + lean_y

            # Size: gentle pulse, with a merge boost
            orb.merge_scale = self._lerp(orb.merge_scale, 1.0, dt * 2.0)
            pulse = 1.0 + 0.08 * math.sin(self._time * 1.1 + orb.pulse_phase)
            sz = base_r * 0.085 * pulse
            if self._state == "awaiting":
                sz *= 0.6
            orb.target_size = sz * orb.merge_scale
            orb.size += (orb.target_size - orb.size) * dt * 2.0

            # Alpha
            if self._split_active:
                # Fade out during the split body, fade back near the end
                if self._split_phase < 0.25:
                    fade = 1.0 - self._split_phase / 0.25
                elif self._split_phase > 0.75:
                    fade = (self._split_phase - 0.75) / 0.25
                else:
                    fade = 0.0
                orb.target_alpha = int(target_alpha * fade)
            else:
                orb.target_alpha = target_alpha
            orb.alpha += (orb.target_alpha - orb.alpha) * dt * 1.5

            orb.color = tint
            orb.pulse_phase += dt * 0.5

        # Pairwise merge boost: when two orbs draw near, they each swell,
        # and a shared glow will be painted in paintEvent.
        if not self._split_active:
            for i in range(len(self._orbs)):
                for j in range(i + 1, len(self._orbs)):
                    a = self._orbs[i]
                    b = self._orbs[j]
                    d = math.hypot(a.x - b.x, a.y - b.y)
                    threshold = (a.size + b.size) * 1.45
                    if d < threshold:
                        merge = 1.0 + (threshold - d) / threshold * 0.18
                        a.merge_scale = max(a.merge_scale, merge)
                        b.merge_scale = max(b.merge_scale, merge)

        # Update sub-orbs during a split event
        if self._split_active:
            if self._split_phase < 0.2:
                alpha_target = 220
            elif self._split_phase > 0.7:
                alpha_target = int(220 * (1.0 - (self._split_phase - 0.7) / 0.3))
            else:
                alpha_target = 220

            converge = max(0.0, (self._split_phase - 0.5) * 2.0)
            for s in self._sub_orbs:
                anchor = self._orbs[s.anchor]

                # Orbit quickly at first, then drift toward the anchor
                s.angle += s.speed * dt * (1.0 + 2.0 * (1.0 - converge)) * speed

                base_target = base_r * (0.15 + 0.22 * math.sin(self._time * 0.25 + s.pulse_phase))
                anchor_target = anchor.radius
                s.target_radius = base_target * (1.0 - converge) + anchor_target * converge
                s.radius += (s.target_radius - s.radius) * dt * 0.6

                s.x = cx + math.cos(s.angle) * s.radius
                s.y = cy + math.sin(s.angle) * s.radius

                s.size += (base_r * 0.038 - s.size) * dt * 1.5
                s.alpha += (alpha_target - s.alpha) * dt * 2.0
                s.color = tint
                s.pulse_phase += dt * 0.7

    def _start_split(self, base_r):
        """Divide each primary orb into two smaller orbs for a brief dance."""
        self._split_active = True
        self._split_phase = 0.0
        self._split_duration = 4.0 + random.random() * 3.0
        self._sub_orbs = []
        for i, parent in enumerate(self._orbs):
            for k in range(2):
                sub = OrbWidget._SubOrb(self, i, k)
                sub.radius = base_r * 0.08
                sub.angle = parent.angle + (k - 0.5) * 0.5
                sub.size = base_r * 0.03
                self._sub_orbs.append(sub)

    def _end_split(self, base_r):
        """Reform the original three orbs."""
        self._split_active = False
        self._sub_orbs = []
        self._next_event = self._time + 10.0 + random.random() * 18.0

    def _draw_orb(self, painter, orb, core_bright=1.0):
        color = orb.color
        a = max(0, min(255, int(orb.alpha)))
        if a <= 0:
            return
        size = max(1.0, orb.size)
        center = QPointF(orb.x, orb.y)

        # Outer atmospheric halo — very soft and large
        r = size * 5.0
        grad = QRadialGradient(center, r)
        grad.setColorAt(0, QColor(color.red(), color.green(), color.blue(), int(a * 0.08)))
        grad.setColorAt(0.35, QColor(color.red(), color.green(), color.blue(), int(a * 0.04)))
        grad.setColorAt(0.75, QColor(color.red(), color.green(), color.blue(), int(a * 0.01)))
        grad.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, r, r)

        # Middle volumetric glow
        r = size * 2.4
        grad = QRadialGradient(center, r)
        grad.setColorAt(0, QColor(color.red(), color.green(), color.blue(), int(a * 0.35)))
        grad.setColorAt(0.5, QColor(color.red(), color.green(), color.blue(), int(a * 0.14)))
        grad.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
        painter.setBrush(QBrush(grad))
        painter.drawEllipse(center, r, r)

        # Inner bright body
        r = size * 1.15
        grad = QRadialGradient(center, r)
        grad.setColorAt(0, QColor(color.red(), color.green(), color.blue(), int(a * 0.75)))
        grad.setColorAt(0.55, QColor(color.red(), color.green(), color.blue(), int(a * 0.25)))
        grad.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
        painter.setBrush(QBrush(grad))
        painter.drawEllipse(center, r, r)

        # Soft white core
        r = size * 0.42
        core = orb.core_color
        ca = int(a * 0.95 * core_bright)
        grad = QRadialGradient(center, r)
        grad.setColorAt(0, QColor(core.red(), core.green(), core.blue(), ca))
        grad.setColorAt(1, QColor(core.red(), core.green(), core.blue(), 0))
        painter.setBrush(QBrush(grad))
        painter.drawEllipse(center, r, r)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        w, h = self.width(), self.height()
        side = min(w, h)
        cx, cy = w / 2, h / 2
        clip_r = side / 2 - 2

        # Soft circular clip
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

        # Edge illumination
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

        # ---- 2. Energy orbs ----
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)

        # Primary orbs
        for orb in self._orbs:
            self._draw_orb(painter, orb)

        # Sub-orbs during a split
        for sub in self._sub_orbs:
            self._draw_orb(painter, sub, core_bright=0.85)

        # Merge glows between close orbs
        if not self._split_active:
            for i in range(len(self._orbs)):
                for j in range(i + 1, len(self._orbs)):
                    a = self._orbs[i]
                    b = self._orbs[j]
                    d = math.hypot(a.x - b.x, a.y - b.y)
                    threshold = (a.size + b.size) * 1.5
                    if d < threshold:
                        mx = (a.x + b.x) / 2
                        my = (a.y + b.y) / 2
                        r = threshold * 1.35
                        merged = _blend_color(a.color, b.color, 0.5)
                        alpha = int(min(a.alpha, b.alpha) * 0.40 * (1.0 - d / threshold))
                        grad = QRadialGradient(QPointF(mx, my), r)
                        grad.setColorAt(0, QColor(merged.red(), merged.green(), merged.blue(), alpha))
                        grad.setColorAt(0.5, QColor(merged.red(), merged.green(), merged.blue(), alpha // 3))
                        grad.setColorAt(1, QColor(merged.red(), merged.green(), merged.blue(), 0))
                        painter.setBrush(QBrush(grad))
                        painter.drawEllipse(QPointF(mx, my), r, r)

        # ---- 3. State flash / alert ----
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

        # ---- 4. Vision Mode emphasis flash ----
        if self._state == "vision" and self._time - getattr(self, "_vision_flash_time", -1) < 0.25:
            t = (self._time - self._vision_flash_time) / 0.25
            flash_r = base_r * (0.2 + 0.8 * (1.0 - t))
            shot_grad = QRadialGradient(cx, cy, flash_r)
            shot_grad.setColorAt(0, QColor(230, 230, 245, 120))
            shot_grad.setColorAt(0.5, QColor(230, 230, 245, 30))
            shot_grad.setColorAt(1, QColor(230, 230, 245, 0))
            painter.setBrush(QBrush(shot_grad))
            painter.drawEllipse(QPointF(cx, cy), flash_r, flash_r)

        # ---- 5. Click ripples ----
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

        # ---- 6. Subtle field distortion during vision ----
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

    def set_state(self, state):
        self._previous_state = self._state
        self._state = state
        self.state_changed.emit(state)

        # Vision Mode gets a brief emphasis flash when it is first entered.
        if state == "vision" and self._previous_state != "vision":
            self._vision_flash_time = self._time

        color = _STATE_COLORS.get(state)
        self._tint_target = color

        if state == "awaiting":
            self._speed_target = 0.08
            self._scale_target = 0.15
            self._glow_target = 0.0
            self._converge_target = False
        elif state in ("portal_opening", "portal_closing"):
            self._speed_target = 0.8
            self._scale_target = 1.0
            self._glow_target = 0.3
            self._converge_target = False
        elif state == "idle":
            self._speed_target = 0.30
            self._scale_target = 1.0
            self._glow_target = 0.25
            self._converge_target = False
        elif state in ("command", "terminal"):
            self._speed_target = 1.5 if state == "command" else 1.6
            self._scale_target = 1.05
            self._glow_target = 0.55
            self._converge_target = False
        elif state == "test_pulse":
            self._speed_target = 1.0
            self._scale_target = 1.0
            self._glow_target = 0.6
            self._converge_target = False
        elif state == "paused":
            self._speed_target = 0.05
            self._scale_target = 0.35
            self._glow_target = 0.08
            self._converge_target = False
        elif state == "feedme":
            self._speed_target = 1.3
            self._scale_target = 1.0
            self._glow_target = 0.6
            self._converge_target = True
        elif state == "vision":
            self._speed_target = 0.45
            self._scale_target = 1.0
            self._glow_target = 0.45
            self._converge_target = False

    def _restore_state(self, previous, expected):
        if self._state == expected:
            self.set_state(previous if previous not in (expected, "") else "idle")

    def flash_command(self):
        previous = self._state
        self.set_state("command")
        QTimer.singleShot(1200, lambda: self._restore_state(previous, "command"))

    def flash_terminal(self):
        previous = self._state
        self.set_state("terminal")
        QTimer.singleShot(1500, lambda: self._restore_state(previous, "terminal"))

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
