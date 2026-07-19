"""
magnet_orb.py
Shared Presence orb for Magnet Client and Magnet Agent.

Presence is a living intelligence: three luminous energy nodes drifting in an
invisible magnetic field. They breathe, attract, repel, merge, divide, and
transition into a structured computational form when the system is working.
No particles, no stars, no dust, no glitter.
"""

import math
import random

from PySide6.QtCore import Qt, QTimer, QElapsedTimer, QPointF, Signal
from PySide6.QtGui import (
    QColor, QPainter, QRadialGradient, QLinearGradient, QConicalGradient,
    QBrush, QPen, QPainterPath,
)
from PySide6.QtWidgets import QWidget

# ------------------------------------------------------------------
# Base Presence palette
# ------------------------------------------------------------------
_PRESENCE_CORE = QColor(245, 243, 255)  # soft white with violet
_PRESENCE_GLOW = QColor(150, 140, 255)  # soft violet
_IRIS_WARM = QColor(195, 145, 90)       # warm golden brown
_IRIS_COOL = QColor(80, 145, 210)       # cool blue

_STATE_COLORS = {
    "awaiting":        None,
    "portal_opening":  QColor(115, 103, 255),
    "portal_closing":  QColor(115, 103, 255),
    "idle":            QColor(130, 120, 255),
    "command":         QColor(100, 200, 255),
    "terminal":        QColor(150, 120, 255),
    "test_pulse":      QColor(230, 100, 90),
    "paused":          QColor(255, 190, 90),
    "feedme":          QColor(130, 220, 170),
    "vision":          QColor(190, 150, 255),
}

_DEFAULT_TINT = QColor(130, 120, 255)


def _lerp(a, b, t):
    return a + (b - a) * t


def _clamp(v, lo=0.0, hi=1.0):
    return max(lo, min(hi, v))


def _smoothstep(edge0, edge1, x):
    t = _clamp((x - edge0) / (edge1 - edge0))
    return t * t * (3.0 - 2.0 * t)


def _blend_color(a, b, t):
    return QColor(
        int(_lerp(a.red(), b.red(), t)),
        int(_lerp(a.green(), b.green(), t)),
        int(_lerp(a.blue(), b.blue(), t)),
    )


def _flow_angle(x, y, t):
    """Pseudo-noise flow field angle using overlapping sine waves."""
    n = (
        math.sin(x * 0.012 + t * 0.20) +
        math.cos(y * 0.010 + t * 0.15) +
        math.sin((x + y) * 0.007 + t * 0.10) +
        math.cos((x - y) * 0.009 + t * 0.08)
    )
    return n * math.pi


# ------------------------------------------------------------------
# OrbWidget
# ------------------------------------------------------------------
class OrbWidget(QWidget):
    """A living intelligent Presence.

    Three luminous energy nodes drift through an invisible magnetic field.
    During meaningful work they coalesce into a calm computational formation
    of connected hexagonal forms, then dissolve back into free organic motion.
    """

    state_changed = Signal(str)
    clicked = Signal()

    class _EnergyOrb:
        __slots__ = (
            "index", "x", "y", "vx", "vy", "angle", "radius_base",
            "orbit_speed", "orbit_phase", "radius_phase", "radius_speed",
            "radius", "size", "target_size", "alpha", "target_alpha",
            "color", "core_color", "hex_rotation", "hex_rotation_speed",
            "pulse_phase", "merge_scale", "trail", "thought_timer",
            "thought_value", "info_offset",
        )

        def __init__(self, owner, index):
            self.index = index
            self.x = owner.width() / 2.0
            self.y = owner.height() / 2.0
            self.vx = 0.0
            self.vy = 0.0
            side = min(owner.width(), owner.height())
            base_r = side / 2.0 * 0.80 if side > 0 else 60.0

            bands = [0.22, 0.40, 0.58]
            self.radius_base = bands[index % len(bands)]
            self.angle = random.random() * math.pi * 2
            self.orbit_speed = (0.04 + random.random() * 0.05) * (1 if random.random() > 0.5 else -1)
            self.orbit_phase = random.random() * math.pi * 2
            self.radius_phase = random.random() * math.pi * 2
            self.radius_speed = 0.06 + random.random() * 0.08
            self.radius = base_r * self.radius_base

            self.size = base_r * 0.085
            self.target_size = self.size
            self.alpha = 0.0
            self.target_alpha = 190

            self.color = QColor(130, 120, 255)
            self.core_color = QColor(245, 243, 255)

            self.hex_rotation = random.random() * math.pi * 2
            self.hex_rotation_speed = (0.02 + random.random() * 0.03) * (1 if random.random() > 0.5 else -1)
            self.pulse_phase = random.random() * math.pi * 2
            self.merge_scale = 1.0
            self.trail = []
            self.thought_timer = 2.0 + random.random() * 5.0
            self.thought_value = 0.0
            self.info_offset = 0.0

    class _SubOrb:
        __slots__ = (
            "x", "y", "vx", "vy", "angle", "radius", "target_radius",
            "size", "alpha", "color", "core_color", "speed", "anchor",
            "pulse_phase", "merge_scale", "trail", "info_offset", "hex_rotation",
            "thought_value",
        )

        def __init__(self, owner, anchor_index, sub_index):
            side = min(owner.width(), owner.height())
            base_r = side / 2.0 * 0.80 if side > 0 else 60.0
            anchor = owner._orbs[anchor_index]

            self.anchor = anchor_index
            self.angle = anchor.angle + (sub_index - 0.5) * 0.45 + random.random() * 0.1
            self.radius = base_r * 0.10
            self.target_radius = base_r * 0.30
            self.size = base_r * 0.035
            self.alpha = 0.0
            self.x = anchor.x
            self.y = anchor.y
            self.vx = 0.0
            self.vy = 0.0
            self.color = QColor(anchor.color)
            self.core_color = QColor(anchor.core_color)
            self.speed = (0.12 + random.random() * 0.12) * (1 if random.random() > 0.5 else -1)
            self.pulse_phase = random.random() * math.pi * 2
            self.merge_scale = 1.0
            self.trail = []
            self.info_offset = 0.0
            self.hex_rotation = random.random() * math.pi * 2
            self.thought_value = 0.0

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

        self._mouse_x = 0.0
        self._mouse_y = 0.0
        self._target_proximity = 0.0
        self._proximity = 0.0
        self._lean_x = 0.0
        self._lean_y = 0.0

        self._speed = 0.1
        self._speed_target = 0.1
        self._scale = 0.15
        self._scale_target = 0.15
        self._glow = 0.0
        self._glow_target = 0.0
        self._tint = QColor(_DEFAULT_TINT)
        self._tint_target = None

        self._portal_progress = 0.0
        self._vision_flash_time = -1.0

        self._comp_progress = 0.0
        self._comp_target = 0.0
        self._formation_angle = 0.0
        self._formation_speed = 0.02
        self._formation_speed_target = 0.02

        self._split_active = False
        self._split_phase = 0.0
        self._split_duration = 1.0
        self._next_split = 5.0 + random.random() * 8.0

        self._info_exchange = None
        self._next_info = 8.0 + random.random() * 10.0

        self._data_flow = False
        self._data_flow_accum = 0.0
        self._data_pulses = []

        self._flash = 0.0
        self._ripples = []

        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        self._last_ms = 0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def _lerp(self, a, b, t):
        return a + (b - a) * t

    def _ensure_init(self):
        if self._initialized:
            return
        if self.width() == 0 or self.height() == 0:
            return
        for i in range(3):
            self._orbs.append(OrbWidget._EnergyOrb(self, i))
        self._initialized = True

    def mouseMoveEvent(self, event):
        pos = event.position()
        self._mouse_x = pos.x()
        self._mouse_y = pos.y()
        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        dx = self._mouse_x - cx
        dy = self._mouse_y - cy
        dist = math.hypot(dx, dy)
        side = min(w, h)
        max_dist = side * 0.7
        self._target_proximity = max(0.0, 1.0 - dist / max_dist)
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
            self._ripples.append({"x": pos.x(), "y": pos.y(), "age": 0.0, "max_age": 2.0})
            if self._state == "vision":
                self.clicked.emit()

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
        self._formation_speed = self._lerp(
            self._formation_speed, self._formation_speed_target, ease
        )

        comp_ease = 1.0 - math.exp(-dt * 1.5)
        self._comp_progress = self._lerp(self._comp_progress, self._comp_target, comp_ease)

        target_tint = self._tint_target if self._tint_target is not None else _DEFAULT_TINT
        self._tint = _blend_color(self._tint, target_tint, 1.0 - math.exp(-dt * 4.0))

        if self._state == "portal_opening":
            self._portal_progress = min(1.0, self._portal_progress + dt * 0.6)
            if self._portal_progress >= 1.0:
                self.set_state("idle")
        elif self._state == "portal_closing":
            self._portal_progress = max(0.0, self._portal_progress - dt * 0.6)
            if self._portal_progress <= 0.0:
                self.set_state("awaiting")
        else:
            self._portal_progress = self._lerp(
                self._portal_progress, 1.0 if self._state != "awaiting" else 0.0, ease
            )

        if self._flash > 0:
            self._flash = max(0.0, self._flash - dt * 6.0)

        self._breath = 0.5 + 0.5 * math.sin(self._time * 0.4)

        prox_ease = 1.0 - math.exp(-dt * 3.0)
        self._proximity = self._lerp(self._proximity, self._target_proximity, prox_ease)

        for r in self._ripples:
            r["age"] += dt
        self._ripples = [r for r in self._ripples if r["age"] < r["max_age"]]

        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        side = min(w, h)
        clip_r = side / 2.0 - 2
        base_r = clip_r * 0.85 * self._scale
        if self._state == "awaiting":
            base_r = clip_r * 0.18 * (0.7 + 0.3 * self._breath)

        cx += self._lean_x * base_r
        cy += self._lean_y * base_r

        self._update_orbs(dt, cx, cy, base_r, self._speed,
                          (self._mouse_x, self._mouse_y, self._proximity))

        self.update()

    def _state_alpha(self):
        base = {
            "awaiting": 50,
            "paused": 80,
            "command": 230,
            "terminal": 230,
            "test_pulse": 240,
            "feedme": 220,
            "vision": 210,
        }.get(self._state, 190)
        if self._state in ("portal_opening", "portal_closing"):
            return int(base * self._portal_progress)
        return base

    def _is_comp_state(self, state):
        return state in ("command", "terminal", "test_pulse", "feedme", "vision")

    def _start_split(self, base_r):
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
                sub.x = parent.x
                sub.y = parent.y
                self._sub_orbs.append(sub)

    def _end_split(self, base_r):
        self._split_active = False
        self._sub_orbs = []
        self._next_split = self._time + 10.0 + random.random() * 18.0

    def _start_info_exchange(self):
        i = random.randrange(3)
        j = random.randrange(3)
        while j == i:
            j = random.randrange(3)
        self._info_exchange = {
            "src": i,
            "dst": j,
            "phase": 0.0,
            "duration": 1.4 + random.random() * 1.2,
        }
        self._next_info = self._time + 4.0 + random.random() * 10.0

    def _update_orbs(self, dt, cx, cy, base_r, speed, mouse):
        mx, my, mprox = mouse
        target_alpha = self._state_alpha()
        comp = self._comp_progress

        form_factor = _smoothstep(0.0, 0.45, comp)
        conn_alpha = _smoothstep(0.25, 0.70, comp)
        hex_factor = _smoothstep(0.55, 1.0, comp)

        self._formation_angle += dt * self._formation_speed * (0.3 + 0.7 * comp)

        formation = []
        form_radius = base_r * 0.55
        for i in range(3):
            a = self._formation_angle + i * 2 * math.pi / 3
            fx = cx + math.cos(a) * form_radius
            fy = cy + math.sin(a) * form_radius
            formation.append((fx, fy))

        # Cancel organic split if we entered computational mode.
        if self._split_active and comp > 0.4:
            self._end_split(base_r)

        if comp < 0.3 and not self._split_active and self._time > self._next_split:
            self._start_split(base_r)
        if self._split_active:
            self._split_phase += dt / self._split_duration
            if self._split_phase >= 1.0:
                self._end_split(base_r)

        # Cancel information exchange if leaving computational mode.
        if self._info_exchange and comp < 0.4:
            self._info_exchange = None

        if comp > 0.5 and not self._info_exchange and not self._split_active and self._time > self._next_info:
            self._start_info_exchange()

        if self._info_exchange:
            exc = self._info_exchange
            exc["phase"] += dt / exc["duration"]
            if exc["phase"] >= 1.0:
                self._info_exchange = None

        # Data flow for file transfer / feedme
        self._data_flow = self._state == "feedme"
        if self._data_flow and comp > 0.5:
            self._data_flow_accum += dt
            if self._data_flow_accum > 0.45:
                self._data_flow_accum -= 0.45
                for pair in [(0, 1), (1, 2), (2, 0)]:
                    self._data_pulses.append({
                        "i": pair[0],
                        "j": pair[1],
                        "t": 0.0,
                        "speed": 0.6 + random.random() * 0.5,
                        "color": self._tint or QColor(210, 205, 255),
                    })
        else:
            self._data_flow_accum = 0.0

        new_pulses = []
        for p in self._data_pulses:
            p["t"] += dt * p["speed"]
            if p["t"] < 1.0:
                new_pulses.append(p)
        self._data_pulses = new_pulses

        # Primary orbs
        for idx, orb in enumerate(self._orbs):
            if self._state == "feedme" and comp < 0.5:
                r_target = base_r * 0.12
            elif self._state == "paused":
                r_target = base_r * 0.15
            elif self._state == "awaiting":
                r_target = base_r * 0.10
            else:
                r_target = base_r * (
                    orb.radius_base
                    + 0.12 * math.sin(self._time * orb.radius_speed + orb.radius_phase)
                    + 0.04 * math.sin(self._time * 0.02 + self._phase + orb.orbit_phase)
                )

            orb.angle += orb.orbit_speed * dt * speed * (1.0 - form_factor * 0.7)

            ox = cx + math.cos(orb.angle + orb.orbit_phase) * r_target
            oy = cy + math.sin(orb.angle + orb.orbit_phase) * r_target

            lean_x = (mx - cx) * mprox * 0.08
            lean_y = (my - cy) * mprox * 0.08
            ox += lean_x
            oy += lean_y

            fx, fy = formation[idx]
            if self._info_exchange and self._info_exchange["src"] == idx:
                dst = self._info_exchange["dst"]
                dfx, dfy = formation[dst]
                off = math.sin(self._info_exchange["phase"] * math.pi) ** 2
                fx += (dfx - fx) * off
                fy += (dfy - fy) * off
                orb.info_offset = self._lerp(orb.info_offset, off, 0.3)
            else:
                orb.info_offset = self._lerp(orb.info_offset, 0.0, 0.2)

            tx = ox * (1.0 - form_factor) + fx * form_factor
            ty = oy * (1.0 - form_factor) + fy * form_factor

            ax = (tx - orb.x) * 2.0
            ay = (ty - orb.y) * 2.0

            for jdx, other in enumerate(self._orbs):
                if jdx == idx:
                    continue
                dx = orb.x - other.x
                dy = orb.y - other.y
                d2 = dx * dx + dy * dy + 0.1
                threshold = (orb.size + other.size) * 1.4
                if d2 < threshold * threshold:
                    d = math.sqrt(d2)
                    rep = (threshold - d) / threshold
                    force = rep * base_r * 3.0
                    ax += (dx / d) * force
                    ay += (dy / d) * force
                elif comp < 0.3:
                    d = math.sqrt(d2)
                    if d > base_r * 0.8:
                        att = (d - base_r * 0.8) / (base_r * 0.8) * base_r * 0.05
                        ax -= (dx / d) * att
                        ay -= (dy / d) * att

            angle = _flow_angle(orb.x * 0.3, orb.y * 0.3, self._time * 0.15 + idx)
            ax += math.cos(angle) * base_r * 0.35
            ay += math.sin(angle) * base_r * 0.35

            orb.vx += ax * dt * speed
            orb.vy += ay * dt * speed
            orb.vx *= 0.94
            orb.vy *= 0.94

            max_v = base_r * 1.8
            v = math.hypot(orb.vx, orb.vy)
            if v > max_v:
                orb.vx *= max_v / v
                orb.vy *= max_v / v

            orb.x += orb.vx * dt
            orb.y += orb.vy * dt

            dx = orb.x - cx
            dy = orb.y - cy
            dist = math.hypot(dx, dy)
            max_dist = base_r * 1.15
            if dist > max_dist:
                orb.x = cx + dx / dist * max_dist
                orb.y = cy + dy / dist * max_dist

            # Thought pulse
            orb.thought_timer -= dt
            if orb.thought_timer <= 0:
                orb.thought_timer = 2.0 + random.random() * 6.0
                orb.thought_value = 1.0
            if orb.thought_value > 0:
                orb.thought_value = max(0.0, orb.thought_value - dt * 1.5)

            # Merge scale from information exchange and proximity
            target_merge = 1.0 + orb.info_offset * 0.8
            if not self._split_active:
                for jdx, other in enumerate(self._orbs):
                    if jdx <= idx:
                        continue
                    d = math.hypot(orb.x - other.x, orb.y - other.y)
                    threshold = (orb.size + other.size) * 1.45
                    if d < threshold:
                        merge = 1.0 + (threshold - d) / threshold * 0.22
                        target_merge = max(target_merge, merge)
                        other.merge_scale = self._lerp(other.merge_scale, max(other.merge_scale, merge), 0.3)

            orb.merge_scale = self._lerp(orb.merge_scale, target_merge, 0.2)

            pulse = 1.0 + 0.08 * math.sin(self._time * 1.1 + orb.pulse_phase)
            sz = base_r * 0.085 * pulse * (1.0 - hex_factor * 0.25)
            if self._state == "awaiting":
                sz *= 0.65
            orb.target_size = sz * orb.merge_scale
            orb.size += (orb.target_size - orb.size) * dt * 2.0

            if self._split_active:
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

            if self._tint is not None:
                orb.color = _blend_color(orb.color, self._tint, 1.0 - math.exp(-dt * 3.0))
            orb.core_color = _PRESENCE_CORE

            orb.hex_rotation += dt * orb.hex_rotation_speed * (0.3 + comp)
            orb.pulse_phase += dt * 0.5

            orb.trail.insert(0, (orb.x, orb.y))
            if len(orb.trail) > 8:
                orb.trail = orb.trail[:8]

        # Sub-orbs
        if self._split_active:
            self._update_sub_orbs(dt, cx, cy, base_r, speed)

    def _update_sub_orbs(self, dt, cx, cy, base_r, speed):
        converge = max(0.0, (self._split_phase - 0.5) * 2.0)
        for s in self._sub_orbs:
            old_x, old_y = s.x, s.y
            anchor = self._orbs[s.anchor]

            s.angle += s.speed * dt * (1.0 + 2.0 * (1.0 - converge)) * speed

            base_target = base_r * (0.12 + 0.22 * math.sin(self._time * 0.25 + s.pulse_phase))
            anchor_target = anchor.radius
            s.target_radius = base_target * (1.0 - converge) + anchor_target * converge
            s.radius += (s.target_radius - s.radius) * dt * 0.6

            s.x = cx + math.cos(s.angle) * s.radius
            s.y = cy + math.sin(s.angle) * s.radius

            s.vx = (s.x - old_x) / dt
            s.vy = (s.y - old_y) / dt

            s.size += (base_r * 0.038 - s.size) * dt * 1.5

            if self._split_phase < 0.2:
                a_target = 220
            elif self._split_phase > 0.7:
                a_target = int(220 * (1.0 - (self._split_phase - 0.7) / 0.3))
            else:
                a_target = 220
            s.alpha += (a_target - s.alpha) * dt * 2.0

            if self._tint is not None:
                s.color = _blend_color(s.color, self._tint, 0.1)
            s.core_color = _PRESENCE_CORE
            s.pulse_phase += dt * 0.7

            s.trail.insert(0, (s.x, s.y))
            if len(s.trail) > 5:
                s.trail = s.trail[:5]

    def _draw_energy_orb(self, painter, orb, glow_mult, hex_factor, comp, core_bright=1.0):
        size = max(1.0, orb.size * orb.merge_scale)
        alpha = max(0, min(255, int(orb.alpha * glow_mult)))
        if alpha <= 0:
            return
        center = QPointF(orb.x, orb.y)

        tint_strength = 0.22 + 0.35 * hex_factor
        base = _blend_color(_PRESENCE_GLOW, orb.color, tint_strength)
        core = _blend_color(_PRESENCE_CORE, orb.color, 0.12 + 0.20 * hex_factor)

        if orb.thought_value > 0:
            alpha = int(alpha * (1.0 + orb.thought_value * 0.45))
            base = _blend_color(base, QColor(255, 255, 255), orb.thought_value * 0.25)

        # Light trail
        if len(orb.trail) > 1:
            n = len(orb.trail)
            for i in range(1, n):
                t = i / n
                ta = int(alpha * 0.18 * (1.0 - t))
                if ta <= 0:
                    continue
                tx, ty = orb.trail[i]
                tr = size * (0.9 - t * 0.35)
                g = QRadialGradient(QPointF(tx, ty), tr * 1.8)
                g.setColorAt(0, QColor(base.red(), base.green(), base.blue(), ta))
                g.setColorAt(0.5, QColor(base.red(), base.green(), base.blue(), int(ta * 0.35)))
                g.setColorAt(1, QColor(base.red(), base.green(), base.blue(), 0))
                painter.setBrush(QBrush(g))
                painter.drawEllipse(QPointF(tx, ty), tr * 1.8, tr * 1.8)

        # Outer atmospheric halo
        r = size * 5.0
        g = QRadialGradient(center, r)
        g.setColorAt(0, QColor(base.red(), base.green(), base.blue(), int(alpha * 0.10)))
        g.setColorAt(0.35, QColor(base.red(), base.green(), base.blue(), int(alpha * 0.04)))
        g.setColorAt(0.75, QColor(base.red(), base.green(), base.blue(), int(alpha * 0.01)))
        g.setColorAt(1, QColor(base.red(), base.green(), base.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(g))
        painter.drawEllipse(center, r, r)

        # Middle volumetric glow
        r = size * 2.4
        g = QRadialGradient(center, r)
        g.setColorAt(0, QColor(base.red(), base.green(), base.blue(), int(alpha * 0.40)))
        g.setColorAt(0.5, QColor(base.red(), base.green(), base.blue(), int(alpha * 0.16)))
        g.setColorAt(1, QColor(base.red(), base.green(), base.blue(), 0))
        painter.drawEllipse(center, r, r)

        # Inner bright body
        r = size * 1.1
        g = QRadialGradient(center, r)
        g.setColorAt(0, QColor(base.red(), base.green(), base.blue(), int(alpha * 0.75)))
        g.setColorAt(0.55, QColor(base.red(), base.green(), base.blue(), int(alpha * 0.28)))
        g.setColorAt(1, QColor(base.red(), base.green(), base.blue(), 0))
        painter.drawEllipse(center, r, r)

        # Soft core
        r = size * 0.4
        ca = int(alpha * 0.95 * core_bright)
        g = QRadialGradient(center, r)
        g.setColorAt(0, QColor(core.red(), core.green(), core.blue(), ca))
        g.setColorAt(1, QColor(core.red(), core.green(), core.blue(), 0))
        painter.drawEllipse(center, r, r)

        # Iridescent outer shimmer
        if comp < 0.9:
            shimmer = 0.5 + 0.5 * math.sin(self._time * 1.2 + orb.pulse_phase)
            speed = math.hypot(orb.vx, orb.vy)
            iris_alpha = int(10 * shimmer * (1.0 - comp * 0.5) * (1.0 + speed * 0.03))
            if iris_alpha > 2:
                outer = size * 2.2
                inner = size * 1.3
                ring = QPainterPath()
                ring.addEllipse(center, outer, outer)
                hole = QPainterPath()
                hole.addEllipse(center, inner, inner)
                ring = ring.subtracted(hole)
                start = -((self._time * 4 + orb.pulse_phase * 30) % 360)
                conic = QConicalGradient(center, start)
                conic.setColorAt(0.0, QColor(_IRIS_WARM.red(), _IRIS_WARM.green(), _IRIS_WARM.blue(), iris_alpha))
                conic.setColorAt(0.25, QColor(base.red(), base.green(), base.blue(), 0))
                conic.setColorAt(0.5, QColor(_IRIS_COOL.red(), _IRIS_COOL.green(), _IRIS_COOL.blue(), iris_alpha))
                conic.setColorAt(0.75, QColor(base.red(), base.green(), base.blue(), 0))
                conic.setColorAt(1.0, QColor(_IRIS_WARM.red(), _IRIS_WARM.green(), _IRIS_WARM.blue(), iris_alpha))
                painter.setBrush(QBrush(conic))
                painter.drawPath(ring)

    def _draw_hex(self, painter, orb, hex_factor):
        if hex_factor <= 0.01:
            return
        size = max(1.0, orb.size * orb.merge_scale)
        hex_r = size * 0.9 * hex_factor
        if hex_r < 1.0:
            return

        base = orb.color
        edge = _blend_color(QColor(225, 222, 255), base, 0.35)

        painter.save()
        painter.translate(orb.x, orb.y)
        painter.rotate(math.degrees(orb.hex_rotation))

        def _hex(r, angle_offset):
            path = QPainterPath()
            for i in range(7):
                a = angle_offset + i * math.pi / 3
                px = math.cos(a) * r
                py = math.sin(a) * r
                if i == 0:
                    path.moveTo(px, py)
                else:
                    path.lineTo(px, py)
            path.closeSubpath()
            return path

        outer = _hex(hex_r, math.pi / 2)
        inner = _hex(hex_r * 0.55, math.pi / 2 + math.pi / 6)

        grad = QRadialGradient(0, 0, hex_r)
        grad.setColorAt(0, QColor(35, 36, 48, int(160 * hex_factor)))
        grad.setColorAt(0.7, QColor(22, 23, 30, int(120 * hex_factor)))
        grad.setColorAt(1, QColor(20, 20, 26, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(grad))
        painter.drawPath(outer)

        pen = QPen(edge, 1.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(pen)
        painter.drawPath(outer)

        inner_edge = QColor(edge.red(), edge.green(), edge.blue(), int(70 * hex_factor))
        painter.setPen(QPen(inner_edge, 0.8))
        painter.drawPath(inner)

        painter.restore()

    def _draw_connections(self, painter, orbs, conn_alpha):
        if conn_alpha <= 0.01:
            return
        pairs = [(0, 1), (1, 2), (2, 0)]
        for i, j in pairs:
            a = orbs[i]
            b = orbs[j]
            grad = QLinearGradient(a.x, a.y, b.x, b.y)
            c_mid = _blend_color(a.color, b.color, 0.5)
            grad.setColorAt(0.0, QColor(a.color.red(), a.color.green(), a.color.blue(), 0))
            grad.setColorAt(0.5, QColor(c_mid.red(), c_mid.green(), c_mid.blue(), int(80 * conn_alpha)))
            grad.setColorAt(1.0, QColor(b.color.red(), b.color.green(), b.color.blue(), 0))
            pen = QPen(QBrush(grad), 2.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawLine(QPointF(a.x, a.y), QPointF(b.x, b.y))

            core = QColor(215, 212, 255, int(35 * conn_alpha))
            painter.setPen(QPen(core, 0.7))
            painter.drawLine(QPointF(a.x, a.y), QPointF(b.x, b.y))

        # Data flow pulses
        for p in self._data_pulses:
            i = p["i"]
            j = p["j"]
            a = orbs[i]
            b = orbs[j]
            t = p["t"]
            px = a.x + (b.x - a.x) * t
            py = a.y + (b.y - a.y) * t
            pr = (a.size + b.size) * 0.3
            palpha = int(160 * (1.0 - abs(t - 0.5) * 2))
            color = p.get("color", QColor(210, 205, 255))
            g = QRadialGradient(QPointF(px, py), pr * 2.5)
            g.setColorAt(0, QColor(color.red(), color.green(), color.blue(), palpha))
            g.setColorAt(1, QColor(color.red(), color.green(), color.blue(), 0))
            painter.setBrush(QBrush(g))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(px, py), pr * 2.5, pr * 2.5)

        # Information exchange pulse
        if self._info_exchange:
            exc = self._info_exchange
            i = exc["src"]
            j = exc["dst"]
            a = orbs[i]
            b = orbs[j]
            phase = exc["phase"]
            t = phase
            px = a.x + (b.x - a.x) * t
            py = a.y + (b.y - a.y) * t
            pr = (a.size + b.size) * 0.45
            palpha = int(200 * math.sin(phase * math.pi))
            if palpha > 0:
                g = QRadialGradient(QPointF(px, py), pr * 2.5)
                g.setColorAt(0, QColor(240, 238, 255, palpha))
                g.setColorAt(1, QColor(240, 238, 255, 0))
                painter.setBrush(QBrush(g))
                painter.drawEllipse(QPointF(px, py), pr * 2.5, pr * 2.5)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        w, h = self.width(), self.height()
        side = min(w, h)
        cx, cy = w / 2.0, h / 2.0
        clip_r = side / 2.0 - 2

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

        comp = self._comp_progress
        form_factor = _smoothstep(0.0, 0.45, comp)
        conn_alpha = _smoothstep(0.25, 0.70, comp)
        hex_factor = _smoothstep(0.55, 1.0, comp)
        accent = self._tint if self._tint else _DEFAULT_TINT

        painter.setPen(Qt.PenStyle.NoPen)

        # Volumetric smoked-glass base
        grad_center = QRadialGradient(cx, cy, base_r * 0.6)
        grad_center.setColorAt(0, QColor(10, 10, 12, 255))
        grad_center.setColorAt(0.6, QColor(14, 15, 19, 230))
        grad_center.setColorAt(1, QColor(10, 10, 12, 0))
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

        # Top sheen
        sheen = QLinearGradient(cx - base_r * 0.5, cy - base_r * 0.6,
                                cx + base_r * 0.3, cy + base_r * 0.2)
        sheen.setColorAt(0, QColor(255, 255, 255, 5))
        sheen.setColorAt(0.6, QColor(255, 255, 255, 2))
        sheen.setColorAt(1, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(sheen))
        painter.drawEllipse(QPointF(cx, cy), base_r, base_r)

        # Energy orbs (additive blending)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)

        glow_mult = 1.0 - hex_factor * 0.55
        for orb in self._orbs:
            self._draw_energy_orb(painter, orb, glow_mult, hex_factor, comp)
        for sub in self._sub_orbs:
            self._draw_energy_orb(painter, sub, glow_mult * 0.85, hex_factor, comp, core_bright=0.85)

        # Merge glows between close primary orbs
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
                        alpha = int(min(a.alpha, b.alpha) * 0.40 * (1.0 - d / threshold) * glow_mult)
                        g = QRadialGradient(QPointF(mx, my), r)
                        g.setColorAt(0, QColor(merged.red(), merged.green(), merged.blue(), alpha))
                        g.setColorAt(0.5, QColor(merged.red(), merged.green(), merged.blue(), alpha // 3))
                        g.setColorAt(1, QColor(merged.red(), merged.green(), merged.blue(), 0))
                        painter.setBrush(QBrush(g))
                        painter.drawEllipse(QPointF(mx, my), r, r)

        # Luminous connections
        self._draw_connections(painter, self._orbs, conn_alpha)

        # Hexagonal computational forms drawn normally on top of the glow
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        for orb in self._orbs:
            self._draw_hex(painter, orb, hex_factor)
        for sub in self._sub_orbs:
            self._draw_hex(painter, sub, hex_factor * 0.8)

        # State flash / alert overlay
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

        # Vision emphasis flash
        if self._state == "vision" and self._time - getattr(self, "_vision_flash_time", -1) < 0.25:
            t = (self._time - self._vision_flash_time) / 0.25
            if t < 0:
                t = 0
            flash_r = base_r * (0.2 + 0.8 * (1.0 - t))
            g = QRadialGradient(cx, cy, flash_r)
            g.setColorAt(0, QColor(230, 230, 245, 120))
            g.setColorAt(0.5, QColor(230, 230, 245, 30))
            g.setColorAt(1, QColor(230, 230, 245, 0))
            painter.setBrush(QBrush(g))
            painter.drawEllipse(QPointF(cx, cy), flash_r, flash_r)

        # Click ripples
        for r in self._ripples:
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

        # Subtle field distortion during vision
        if self._state == "vision":
            dist_alpha = int(8 + self._proximity * 15)
            g = QRadialGradient(cx, cy, base_r)
            g.setColorAt(0, QColor(accent.red(), accent.green(), accent.blue(), 0))
            g.setColorAt(0.7, QColor(accent.red(), accent.green(), accent.blue(), 0))
            g.setColorAt(0.85, QColor(accent.red(), accent.green(), accent.blue(), dist_alpha))
            g.setColorAt(1, QColor(accent.red(), accent.green(), accent.blue(), 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(g))
            painter.drawEllipse(QPointF(cx, cy), base_r, base_r)

        painter.end()

    def set_state(self, state):
        self._previous_state = self._state
        self._state = state
        self.state_changed.emit(state)

        if state == "vision" and self._previous_state != "vision":
            self._vision_flash_time = self._time

        color = _STATE_COLORS.get(state)
        self._tint_target = color

        self._speed_target = 0.15
        self._scale_target = 0.5
        self._glow_target = 0.2
        self._comp_target = 0.0
        self._formation_speed_target = 0.02

        if state == "awaiting":
            self._speed_target = 0.08
            self._scale_target = 0.35
            self._glow_target = 0.05
        elif state == "portal_opening":
            self._portal_progress = 0.0
            self._speed_target = 0.9
            self._scale_target = 1.0
            self._glow_target = 0.45
        elif state == "portal_closing":
            self._portal_progress = 1.0
            self._speed_target = 0.5
            self._scale_target = 0.25
            self._glow_target = 0.10
        elif state == "idle":
            self._speed_target = 0.18
            self._scale_target = 1.0
            self._glow_target = 0.25
        elif state == "command":
            self._speed_target = 1.1
            self._scale_target = 1.05
            self._glow_target = 0.55
            self._comp_target = 1.0
            self._formation_speed_target = 0.08
        elif state == "terminal":
            self._speed_target = 1.2
            self._scale_target = 1.05
            self._glow_target = 0.55
            self._comp_target = 1.0
            self._formation_speed_target = 0.09
        elif state == "test_pulse":
            self._speed_target = 1.0
            self._scale_target = 1.0
            self._glow_target = 0.65
            self._comp_target = 1.0
            self._formation_speed_target = 0.10
        elif state == "paused":
            self._speed_target = 0.05
            self._scale_target = 0.55
            self._glow_target = 0.10
        elif state == "feedme":
            self._speed_target = 1.0
            self._scale_target = 1.0
            self._glow_target = 0.50
            self._comp_target = 1.0
            self._formation_speed_target = 0.10
        elif state == "vision":
            self._speed_target = 0.30
            self._scale_target = 1.0
            self._glow_target = 0.45
            self._comp_target = 1.0
            self._formation_speed_target = 0.03

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
        if self._orbs:
            orb = random.choice(self._orbs)
            orb.thought_value = 1.0

    def start_portal_opening(self):
        self._portal_progress = 0.0
        self.set_state("portal_opening")

    def start_portal_closing(self):
        self._portal_progress = 1.0
        self.set_state("portal_closing")

    def set_paused(self, paused):
        self.set_state("paused" if paused else "idle")
