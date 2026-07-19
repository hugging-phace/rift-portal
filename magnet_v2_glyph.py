"""
Shared MagnetOS v2 brand glyph renderer.

Provides a platform-aware Theme and a GlyphRenderer that draws the
Connected Field icon: one larger hollow hexagon connected to two smaller
hollow hexagons.  The renderer is designed to remain legible at 16×16,
18×18, 24×24 and 32×32 pixels and keeps the system-tray/menu-bar icon
strictly monochrome.
"""

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QBrush, QPen, QPixmap


# ------------------------------------------------------------------
# Theme
# ------------------------------------------------------------------
def _is_dark_mode(app=None) -> bool:
    from PySide6.QtWidgets import QApplication
    app = app or QApplication.instance()
    try:
        scheme = app.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Unknown:
            return True
        return scheme == Qt.ColorScheme.Dark
    except Exception:
        pass
    bg = app.palette().window().color()
    return bg.lightnessF() < 0.5


def _css_color(c: QColor) -> str:
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {c.alphaF():.3f})"


class Theme:
    def __init__(self, dark: bool):
        self.dark = dark
        if dark:
            self.bg = QColor(10, 10, 12)
            self.panel = QColor(22, 22, 28)
            self.text = QColor(245, 245, 247)
            self.muted = QColor(130, 130, 145)
            self.accent = QColor(115, 103, 255)
            # In-app accent glyph color
            self.glyph = QColor(190, 210, 255)
            # Tray/menu-bar color: white/light on dark taskbar
            self.glyph_tray = QColor(245, 245, 247)
            self.hover = QColor(34, 34, 42)
        else:
            self.bg = QColor(245, 245, 247)
            self.panel = QColor(255, 255, 255)
            self.text = QColor(30, 30, 35)
            self.muted = QColor(110, 110, 120)
            self.accent = QColor(115, 103, 255)
            self.glyph = QColor(60, 80, 120)
            self.glyph_tray = QColor(30, 30, 35)
            self.hover = QColor(235, 235, 240)


# ------------------------------------------------------------------
# Glyph renderer
# ------------------------------------------------------------------
class GlyphRenderer:
    STATES = ("idle", "connected", "viewing", "processing", "file_transfer", "disconnected")

    def __init__(self, size: int = 64):
        self.size = size
        self.state = "idle"
        self._time = 0.0
        self._phase = 0.0

    def set_state(self, state: str):
        state = state if state in self.STATES else "idle"
        if self.state != state:
            self._phase = 0.0
        self.state = state

    def update(self, dt: float):
        self._time += dt
        # "connected" is a single one-shot pulse that then rests; the other
        # activity states keep animating while active.
        if self.state == "connected":
            if self._phase < 1.5:
                self._phase += dt
        elif self.state in ("viewing", "file_transfer", "processing"):
            self._phase += dt

    @staticmethod
    def _hex_path(cx: float, cy: float, r: float) -> QPainterPath:
        path = QPainterPath()
        for i in range(7):
            a = -math.pi / 2 + i * math.pi / 3
            px = cx + math.cos(a) * r
            py = cy + math.sin(a) * r
            if i == 0:
                path.moveTo(px, py)
            else:
                path.lineTo(px, py)
        path.closeSubpath()
        return path

    @staticmethod
    def _hex_boundary(radius: float, theta: float) -> float:
        """Distance from the center of a pointy-top regular hexagon to its boundary along angle theta."""
        delta = ((theta + math.pi / 6) % (math.pi / 3)) - math.pi / 6
        return radius * math.cos(math.pi / 6) / math.cos(delta)

    def _draw_node(self, painter: QPainter, x: float, y: float, r: float, color: QColor, line_width: float):
        path = self._hex_path(x, y, r)
        pen = QPen(color)
        pen.setWidthF(line_width)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def _connector_points(self, c1, c2, r1, r2):
        """Return boundary attachment points for the straight bar between two nodes."""
        x1, y1 = c1
        x2, y2 = c2
        dx = x2 - x1
        dy = y2 - y1
        dist = math.hypot(dx, dy)
        if dist == 0:
            return (x1, y1), (x2, y2)
        ux, uy = dx / dist, dy / dist
        theta = math.atan2(uy, ux)
        start = (x1 + ux * self._hex_boundary(r1, theta),
                 y1 + uy * self._hex_boundary(r1, theta))
        # Opposite direction uses the same boundary distance for a regular hexagon.
        end = (x2 - ux * self._hex_boundary(r2, theta),
               y2 - uy * self._hex_boundary(r2, theta))
        return start, end

    def pixmap(self, theme: Theme, color: QColor = None) -> QPixmap:
        pm = QPixmap(self.size, self.size)
        pm.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        base = QColor(color) if color is not None else QColor(theme.glyph)
        if self.state == "disconnected":
            base.setAlpha(110)

        cx = cy = self.size / 2.0
        big_r = self.size * 0.14
        small_r = self.size * 0.08
        line_width = max(1.0, self.size * 0.032)

        # Breathing animation for processing.
        breath = 1.0
        if self.state == "processing":
            breath = 1.0 + 0.035 * math.sin(self._phase * 2.0)
        big_r *= breath
        small_r *= breath

        big = (cx - self.size * 0.12, cy)
        small_top = (cx + self.size * 0.18, cy - self.size * 0.13)
        small_bot = (cx + self.size * 0.18, cy + self.size * 0.13)

        connectors = [
            (big, small_top, big_r, small_r),
            (big, small_bot, big_r, small_r),
        ]

        # Connector bars drawn first so node outlines sit on top.
        pen = QPen(base)
        pen.setWidthF(line_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        connector_segments = []
        for c1, c2, r1, r2 in connectors:
            start, end = self._connector_points(c1, c2, r1, r2)
            connector_segments.append((start, end))
            painter.drawLine(*start, *end)

        # State animations (all monochrome).
        if self.state == "connected":
            # A single subtle pulse travels once along the top connector.
            duration = 1.5
            if self._phase < duration:
                t = self._phase / duration
                t = 0.05 + 0.90 * t  # keep the dot clear of the node edges
                start, end = connector_segments[0]
                x = start[0] + (end[0] - start[0]) * t
                y = start[1] + (end[1] - start[1]) * t
                painter.setBrush(QBrush(base))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(x - line_width * 0.5, y - line_width * 0.5,
                                    line_width, line_width)

        elif self.state == "viewing":
            # Tiny movement along the top connector.
            start, end = connector_segments[0]
            t = 0.5 + 0.18 * math.sin(self._phase * 0.5)
            x = start[0] + (end[0] - start[0]) * t
            y = start[1] + (end[1] - start[1]) * t
            painter.setBrush(QBrush(base))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(x - line_width * 0.4, y - line_width * 0.4,
                                line_width * 0.8, line_width * 0.8)

        elif self.state == "file_transfer":
            # A small pulse moves from large node to each small node in turn.
            period = 2.0
            total = self._phase % (period * 2)
            idx = 0 if total < period else 1
            t = (total % period) / period
            t = 0.05 + 0.90 * t
            start, end = connector_segments[idx]
            x = start[0] + (end[0] - start[0]) * t
            y = start[1] + (end[1] - start[1]) * t
            painter.setBrush(QBrush(base))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(x - line_width * 0.55, y - line_width * 0.55,
                                line_width * 1.1, line_width * 1.1)

        # Node outlines.
        self._draw_node(painter, *big, big_r, base, line_width)
        self._draw_node(painter, *small_top, small_r, base, line_width)
        self._draw_node(painter, *small_bot, small_r, base, line_width)

        painter.end()
        return pm
