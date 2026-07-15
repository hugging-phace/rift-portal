"""
Magnet Agent v2 Prototype

A self-contained UI/UX prototype for the MagnetOS Agent command center.
Demonstrates the new v2 design language: left sidebar with the connected
three-node hexagonal brand glyph at the bottom, premium dark glass panels,
large spacing, and a minimal main content area.

This file is intentionally self-contained and does not yet wire in the
existing Magnet Agent backend.
"""

import math
import sys

from PySide6.QtCore import Qt, QTimer, QPoint, QPointF, Signal
from PySide6.QtGui import (
    QColor, QPainter, QPainterPath, QBrush, QPen, QPixmap, QCursor, QFont,
    QMouseEvent,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QFrame, QSizePolicy,
)


# ------------------------------------------------------------------
# Theme helpers
# ------------------------------------------------------------------
def _is_dark_mode(app=None) -> bool:
    app = app or QApplication.instance()
    try:
        scheme = app.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Unknown:
            return True  # default to a dark command-center aesthetic when unknown
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
            self.glyph = QColor(190, 210, 255)
            self.hover = QColor(34, 34, 42)
        else:
            self.bg = QColor(245, 245, 247)
            self.panel = QColor(255, 255, 255)
            self.text = QColor(30, 30, 35)
            self.muted = QColor(110, 110, 120)
            self.accent = QColor(115, 103, 255)
            self.glyph = QColor(60, 80, 120)
            self.hover = QColor(235, 235, 240)


# ------------------------------------------------------------------
# Glyph renderer (same connected three-node hexagon used by the client)
# ------------------------------------------------------------------
class GlyphRenderer:
    """Renders the Magnet three-node connected hexagon glyph as a QPixmap."""

    STATES = ("idle", "connected", "viewing", "processing", "file_transfer", "disconnected")

    def __init__(self, size: int = 64):
        self.size = size
        self.state = "idle"
        self._time = 0.0
        self._phase = 0.0
        self._pulse = 0.0
        self._last_state = "idle"

    def set_state(self, state: str):
        state = state if state in self.STATES else "idle"
        if self._last_state != state:
            self._last_state = state
            if state == "connected":
                self._pulse = 1.0
            elif state == "disconnected":
                self._pulse = 0.0
            self._phase = 0.0
        self.state = state

    def update(self, dt: float):
        self._time += dt
        if self._pulse > 0:
            self._pulse = max(0.0, self._pulse - dt * 1.8)
        if self.state in ("viewing", "file_transfer", "processing"):
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

    def _draw_node(self, painter: QPainter, x: float, y: float, r: float, color: QColor, line_width: float):
        path = self._hex_path(x, y, r)
        pen = QPen(color)
        pen.setWidthF(line_width)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    def pixmap(self, theme: Theme) -> QPixmap:
        pm = QPixmap(self.size, self.size)
        pm.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = cy = self.size / 2.0
        r = self.size * 0.30
        node_r = self.size * 0.10
        line_width = max(1.5, self.size * 0.032)

        glyph = QColor(theme.glyph)
        if self.state == "disconnected":
            glyph.setAlpha(110)

        points = []
        for i in range(3):
            a = -math.pi / 2 + i * 2 * math.pi / 3
            points.append((cx + math.cos(a) * r, cy + math.sin(a) * r))

        line_pen = QPen(glyph)
        line_pen.setWidthF(line_width)
        line_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        line_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(line_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for i in range(3):
            x1, y1 = points[i]
            x2, y2 = points[(i + 1) % 3]
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        for i, (px, py) in enumerate(points):
            scale = 1.0
            if self.state == "processing" and i == 0:
                scale = 1.0 + 0.13 * math.sin(self._phase * 3.0)
            self._draw_node(painter, px, py, node_r * scale, glyph, line_width)

        if self._pulse > 0.01:
            t = self._pulse
            alpha = int(255 * t * (1.0 - t))
            pen = QPen(QColor(glyph.red(), glyph.green(), glyph.blue(), alpha))
            pen.setWidthF(line_width)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            pulse_r = r + node_r + t * self.size * 0.14
            painter.drawEllipse(QPointF(cx, cy), pulse_r, pulse_r)

        if self.state == "viewing":
            t = (math.sin(self._phase * 0.8) + 1.0) / 2.0
            x1, y1 = points[0]
            x2, y2 = points[1]
            dot = QPointF(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)
            painter.setBrush(QBrush(glyph))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(dot, self.size * 0.055, self.size * 0.055)

        if self.state == "file_transfer":
            period = 1.0
            total = self._phase % (period * 3)
            edge = int(total / period)
            t = (total % period) / period
            i = edge % 3
            x1, y1 = points[i]
            x2, y2 = points[(i + 1) % 3]
            dot = QPointF(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)
            painter.setBrush(QBrush(glyph))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(dot, self.size * 0.06, self.size * 0.06)

        painter.end()
        return pm


# ------------------------------------------------------------------
# Reusable widgets
# ------------------------------------------------------------------
class GlyphLabel(QLabel):
    def __init__(self, renderer: GlyphRenderer, theme: Theme, parent=None):
        super().__init__(parent)
        self.renderer = renderer
        self.theme = theme
        self.setFixedSize(renderer.size, renderer.size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.refresh()

    def refresh(self):
        self.setPixmap(self.renderer.pixmap(self.theme))


class Card(QFrame):
    def __init__(self, title: str, body: str, theme: Theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setStyleSheet(
            f"background: {_css_color(theme.panel)}; border-radius: 12px;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {_css_color(theme.text)}; font-size: 14px; font-weight: 600;"
        )
        layout.addWidget(title_lbl)

        body_lbl = QLabel(body)
        body_lbl.setWordWrap(True)
        body_lbl.setStyleSheet(f"color: {_css_color(theme.muted)}; font-size: 12px;")
        body_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(body_lbl)


class PageWidget(QWidget):
    def __init__(self, title: str, theme: Theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {_css_color(theme.text)}; font-size: 24px; font-weight: 600;"
        )
        layout.addWidget(title_lbl)

        self._body = QVBoxLayout()
        self._body.setSpacing(16)
        layout.addLayout(self._body)
        layout.addStretch()

    def add_card(self, title: str, body: str):
        card = Card(title, body, self.theme, self)
        card.setMinimumHeight(120)
        self._body.addWidget(card)


# ------------------------------------------------------------------
# State control dialog
# ------------------------------------------------------------------
class StateControlDialog(QWidget):
    state_changed = Signal(str)

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Magnet Agent v2 — State Controls")
        self.theme = theme
        self.setStyleSheet(f"background: {_css_color(theme.bg)};")
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(14, 14, 14, 14)

        self._buttons = []
        for state in GlyphRenderer.STATES:
            btn = QPushButton(state.replace("_", " ").title())
            btn.setStyleSheet(self._button_stylesheet())
            btn.clicked.connect(lambda checked=False, s=state: self.state_changed.emit(s))
            self._buttons.append(btn)
            layout.addWidget(btn)

    def apply_theme(self, theme: Theme):
        self.theme = theme
        self.setStyleSheet(f"background: {_css_color(theme.bg)};")
        for btn in self._buttons:
            btn.setStyleSheet(self._button_stylesheet())

    def _button_stylesheet(self) -> str:
        t = self.theme
        bg = _css_color(t.panel)
        hover = _css_color(t.hover)
        text = _css_color(t.text)
        return (
            f"QPushButton {{ background: {bg}; color: {text}; border: none; "
            f"border-radius: 6px; padding: 8px 12px; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {hover}; }}"
        )


# ------------------------------------------------------------------
# Agent window
# ------------------------------------------------------------------
class AgentWindow(QWidget):
    def __init__(self, theme: Theme, glyph: GlyphRenderer, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.glyph = glyph
        self._drag_pos = None

        self.setWindowTitle("Magnet Agent")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.resize(1100, 720)
        self.setMinimumSize(900, 560)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Title bar
        title_bar = QWidget()
        title_bar.setFixedHeight(44)
        title_bar.setStyleSheet(f"background: {_css_color(theme.panel)};")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(16, 0, 12, 0)
        title_layout.setSpacing(8)

        title_lbl = QLabel("Magnet Agent")
        title_lbl.setStyleSheet(
            f"color: {_css_color(theme.text)}; font-size: 14px; font-weight: 600;"
        )
        title_layout.addWidget(title_lbl)
        title_layout.addStretch()

        for symbol, cb in (("−", self.showMinimized), ("□", self._toggle_max_restore), ("×", self.close)):
            btn = QPushButton(symbol)
            btn.setFixedSize(28, 28)
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {_css_color(theme.muted)}; "
                f"border-radius: 6px; border: none; font-size: 14px; }}"
                f"QPushButton:hover {{ background: {_css_color(theme.hover)}; color: {_css_color(theme.text)}; }}"
            )
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(cb)
            title_layout.addWidget(btn)

        main_layout.addWidget(title_bar)

        # Body
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # Sidebar
        sidebar = QWidget()
        sidebar.setFixedWidth(260)
        sidebar.setStyleSheet(f"background: {_css_color(theme.panel)};")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 16, 16, 16)
        sidebar_layout.setSpacing(12)

        # Connection status
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {_css_color(theme.accent)}; font-size: 10px;")
        status_text = QLabel("Connected")
        status_text.setStyleSheet(f"color: {_css_color(theme.muted)}; font-size: 12px;")
        status_row.addWidget(dot)
        status_row.addWidget(status_text, alignment=Qt.AlignmentFlag.AlignVCenter)
        status_row.addStretch()
        sidebar_layout.addLayout(status_row)

        sidebar_layout.addSpacing(24)

        # Nav
        self._nav_btns = []
        self._stack = QStackedWidget()
        views = [
            ("Sessions", self._build_sessions_page()),
            ("Commands", self._build_commands_page()),
            ("Terminal", self._build_terminal_page()),
            ("Settings", self._build_settings_page()),
        ]
        for idx, (label, page) in enumerate(views):
            btn = QPushButton(label)
            btn.setStyleSheet(self._nav_stylesheet(idx == 0))
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setCheckable(True)
            btn.setChecked(idx == 0)
            btn.clicked.connect(lambda checked, i=idx: self._switch_view(i))
            self._nav_btns.append(btn)
            sidebar_layout.addWidget(btn)
            self._stack.addWidget(page)

        sidebar_layout.addStretch()

        # Glyph at bottom of sidebar
        glyph_container = QWidget()
        glyph_layout = QVBoxLayout(glyph_container)
        glyph_layout.setContentsMargins(0, 0, 0, 0)
        glyph_layout.setSpacing(8)

        self._glyph_lbl = GlyphLabel(glyph, theme)
        glyph_layout.addWidget(self._glyph_lbl, alignment=Qt.AlignmentFlag.AlignCenter)

        self._glyph_status = QLabel("IDLE")
        self._glyph_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._glyph_status.setStyleSheet(
            f"color: {_css_color(theme.muted)}; font-size: 11px; font-weight: 600; letter-spacing: 1px;"
        )
        glyph_layout.addWidget(self._glyph_status)

        sidebar_layout.addWidget(glyph_container)

        body.addWidget(sidebar)

        # Main content
        content = QWidget()
        content.setStyleSheet(f"background: {_css_color(theme.bg)};")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self._stack, 1)
        body.addWidget(content, 1)

        main_layout.addLayout(body, 1)

    def _nav_stylesheet(self, active: bool) -> str:
        t = self.theme
        bg = _css_color(t.accent if active else t.panel)
        fg = _css_color(t.text if active else t.muted)
        hover = _css_color(t.hover)
        return (
            f"QPushButton {{ background: {bg}; color: {fg}; border: none; "
            f"border-radius: 8px; padding: 10px 14px; font-size: 13px; text-align: left; }}"
            f"QPushButton:hover {{ background: {hover}; color: {_css_color(t.text)}; }}"
        )

    def _build_sessions_page(self):
        page = PageWidget("Active Sessions", self.theme)
        page.add_card("Atlas Workstation", "Online — Windows 11\nLast seen: just now")
        page.add_card("Studio Mac", "Online — macOS\nLast seen: 2m ago")
        return page

    def _build_commands_page(self):
        page = PageWidget("Remote Commands", self.theme)
        page.add_card("Shell", "Execute remote shell commands on the selected session.")
        page.add_card("File Transfer", "Send or receive files from the connected client.")
        return page

    def _build_terminal_page(self):
        page = PageWidget("Terminal", self.theme)
        page.add_card("Command Output", "Remote command results and logs will appear here.")
        return page

    def _build_settings_page(self):
        page = PageWidget("Settings", self.theme)
        page.add_card("Appearance", "Light / dark mode follows the operating system.")
        page.add_card("Network", "Server endpoint and connection preferences.")
        return page

    def _switch_view(self, index: int):
        self._stack.setCurrentIndex(index)
        for i, btn in enumerate(self._nav_btns):
            btn.setChecked(i == index)
            btn.setStyleSheet(self._nav_stylesheet(i == index))

    def _toggle_max_restore(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition().toPoint() - self._drag_pos
            self.move(self.pos() + delta)
            self._drag_pos = event.globalPosition().toPoint()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = None
        super().mouseReleaseEvent(event)

    def set_status(self, state: str):
        labels = {
            "idle": "IDLE",
            "connected": "CONNECTED",
            "viewing": "VIEWING",
            "processing": "PROCESSING",
            "file_transfer": "TRANSFERRING",
            "disconnected": "DISCONNECTED",
        }
        self._glyph_status.setText(labels.get(state, state.upper()))


# ------------------------------------------------------------------
# Main application
# ------------------------------------------------------------------
class MagnetAgentPrototype(QApplication):
    def __init__(self, argv):
        super().__init__(argv)

        self.theme = Theme(_is_dark_mode(self))
        try:
            self.styleHints().colorSchemeChanged.connect(self._theme_changed)
        except Exception:
            pass

        self.glyph = GlyphRenderer(size=160)
        self.glyph.set_state("idle")

        self.window = AgentWindow(self.theme, self.glyph)
        self.window.set_status("idle")
        self.window.show()

        self._control = StateControlDialog(self.theme)
        self._control.state_changed.connect(self.set_state)
        self._control.show()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._animate)
        self._timer.start(100)

    def _animate(self):
        self.glyph.update(0.1)
        self.window._glyph_lbl.theme = self.theme
        self.window._glyph_lbl.refresh()

    def _theme_changed(self):
        self.theme = Theme(_is_dark_mode(self))
        # Re-apply styles by recreating the window would be simplest for a prototype;
        # here we update the glyph theme and control dialog.
        self.window._glyph_lbl.theme = self.theme
        self.window._glyph_lbl.refresh()
        self._control.apply_theme(self.theme)

    def set_state(self, state: str):
        self.glyph.set_state(state)
        self.window.set_status(state)
        self.window._glyph_lbl.refresh()


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------
if __name__ == "__main__":
    app = MagnetAgentPrototype(sys.argv)
    sys.exit(app.exec())
