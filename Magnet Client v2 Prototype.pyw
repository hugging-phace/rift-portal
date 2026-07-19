"""
Magnet Client v2 Prototype

A standalone UI/UX prototype for MagnetOS v2. It demonstrates:
- A native system tray icon with a connected three-node hexagonal glyph.
- Subtle, state-driven glyph animations (idle, connected, viewing,
  processing, file_transfer, disconnected).
- Light / dark theme awareness for the tray icon.
- A rounded, frameless flyout panel as the primary UI surface.
- A control dialog to cycle states for review.

This file is intentionally self-contained and does not yet wire in the
existing Magnet Client backend.
"""

import sys

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QPainter, QPainterPath, QBrush, QPen, QIcon, QAction,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QSystemTrayIcon, QMenu, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QFrame,
)

from magnet_v2_glyph import Theme, GlyphRenderer, _is_dark_mode, _css_color
from magnet_v2_glyph import Theme, GlyphRenderer, _is_dark_mode, _css_color

# ------------------------------------------------------------------
# Flyout panel
# ------------------------------------------------------------------
class FlyoutPanel(QWidget):
    def __init__(self, theme: Theme, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.theme = theme
        self._corner_radius = 16

        self._build_ui()
        self.setFixedWidth(260)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        # Header: centered brand glyph above title for instant recognition.
        header_layout = QVBoxLayout()
        header_layout.setSpacing(8)
        header_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._glyph = GlyphRenderer(size=56)
        self._glyph.set_state("idle")
        self._glyph_lbl = QLabel()
        self._glyph_lbl.setFixedSize(56, 56)
        self._glyph_lbl.setPixmap(self._glyph.pixmap(self.theme, color=self.theme.glyph))
        header_layout.addWidget(self._glyph_lbl, alignment=Qt.AlignmentFlag.AlignCenter)
        self._title = QLabel("Magnet Client")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setStyleSheet(
            f"color: {_css_color(self.theme.text)}; font-size: 18px; font-weight: 600;"
        )
        header_layout.addWidget(self._title, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addLayout(header_layout)

        status_layout = QHBoxLayout()
        status_layout.setSpacing(6)
        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet(f"color: {_css_color(self.theme.accent)}; font-size: 10px;")
        self._status_text = QLabel("Connected to Atlas")
        self._status_text.setStyleSheet(f"color: {_css_color(self.theme.muted)}; font-size: 12px;")
        status_layout.addWidget(self._status_dot)
        status_layout.addWidget(self._status_text, alignment=Qt.AlignmentFlag.AlignVCenter)
        status_layout.addStretch()
        layout.addLayout(status_layout)

        sections = [
            ("Viewing Screen", self._on_viewing),
            ("File Transfer", self._on_file_transfer),
            ("Open Chat", self._on_chat),
            ("Settings", self._on_settings),
            ("Disconnect", self._on_disconnect),
        ]
        self._buttons = []
        for label, cb in sections:
            btn = QPushButton(label)
            btn.setStyleSheet(self._button_stylesheet())
            btn.clicked.connect(cb)
            self._buttons.append(btn)
            layout.addWidget(btn)

        self._chat = QTextEdit()
        self._chat.setPlaceholderText("Message Atlas...")
        self._chat.setVisible(False)
        self._chat.setFixedHeight(80)
        self._chat.setStyleSheet(
            f"color: {_css_color(self.theme.text)}; background: {_css_color(self.theme.panel)}; "
            f"border: 1px solid {_css_color(self.theme.muted)}; border-radius: 8px; padding: 6px;"
        )
        layout.addWidget(self._chat)

        self.setLayout(layout)

    def _button_stylesheet(self) -> str:
        t = self.theme
        bg = _css_color(QColor(t.panel.red() + 12, t.panel.green() + 12, t.panel.blue() + 12))
        hover = _css_color(QColor(t.panel.red() + 24, t.panel.green() + 24, t.panel.blue() + 24))
        text = _css_color(t.text)
        return (
            f"QPushButton {{ background: {bg}; color: {text}; border: none; "
            f"border-radius: 8px; padding: 10px 14px; font-size: 13px; text-align: left; }}"
            f"QPushButton:hover {{ background: {hover}; }}"
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(
            0, 0, self.width(), self.height(),
            self._corner_radius, self._corner_radius,
        )

        painter.fillPath(path, QBrush(self.theme.panel))

        border = QPen(QColor(self.theme.muted.red(), self.theme.muted.green(), self.theme.muted.blue(), 60))
        border.setWidthF(1)
        painter.setPen(border)
        painter.drawPath(path)

        # Subtle top highlight
        grad = QPainterPath()
        grad.addRoundedRect(
            1, 1, self.width() - 2, self.height() / 2,
            self._corner_radius - 1, self._corner_radius - 1,
        )
        painter.setClipPath(grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(255, 255, 255, 12 if self.theme.dark else 20)))
        painter.drawPath(grad)

        painter.end()

    def set_status(self, state: str, connected_to: str = "Atlas"):
        labels = {
            "idle": f"Idle — {connected_to}",
            "connected": f"Connected to {connected_to}",
            "viewing": f"Viewing screen — {connected_to}",
            "processing": f"Processing — {connected_to}",
            "file_transfer": f"Transferring files — {connected_to}",
            "disconnected": "Disconnected",
        }
        self._status_text.setText(labels.get(state, state.capitalize()))
        dot_color = self.theme.muted if state == "disconnected" else self.theme.accent
        self._status_dot.setStyleSheet(f"color: {_css_color(dot_color)}; font-size: 10px;")
        self._glyph.set_state(state)
        self._glyph_lbl.setPixmap(self._glyph.pixmap(self.theme, color=self.theme.glyph))

    def apply_theme(self, theme: Theme):
        self.theme = theme
        self._title.setStyleSheet(
            f"color: {_css_color(theme.text)}; font-size: 18px; font-weight: 600;"
        )
        self._status_text.setStyleSheet(f"color: {_css_color(theme.muted)}; font-size: 12px;")
        self._glyph_lbl.setPixmap(self._glyph.pixmap(self.theme, color=self.theme.glyph))
        for btn in self._buttons:
            btn.setStyleSheet(self._button_stylesheet())
        self._chat.setStyleSheet(
            f"color: {_css_color(theme.text)}; background: {_css_color(theme.panel)}; "
            f"border: 1px solid {_css_color(theme.muted)}; border-radius: 8px; padding: 6px;"
        )
        self.update()

    def _on_viewing(self):
        self.window().hide()

    def _on_file_transfer(self):
        pass

    def _on_chat(self):
        self._chat.setVisible(not self._chat.isVisible())
        if self._chat.isVisible():
            self._chat.setFocus()

    def _on_settings(self):
        pass

    def _on_disconnect(self):
        pass


# ------------------------------------------------------------------
# State control dialog
# ------------------------------------------------------------------
class StateControlDialog(QWidget):
    state_changed = Signal(str)
    flyout_requested = Signal()

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Magnet Client v2 — State Controls")
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

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet(f"color: {_css_color(theme.muted)};")
        layout.addWidget(divider)

        show_btn = QPushButton("Show Flyout")
        show_btn.setStyleSheet(self._button_stylesheet())
        show_btn.clicked.connect(lambda: self.flyout_requested.emit())
        self._buttons.append(show_btn)
        layout.addWidget(show_btn)

    def apply_theme(self, theme: Theme):
        self.theme = theme
        self.setStyleSheet(f"background: {_css_color(theme.bg)};")
        for btn in self._buttons:
            btn.setStyleSheet(self._button_stylesheet())

    def _button_stylesheet(self) -> str:
        t = self.theme
        bg = _css_color(t.panel)
        hover = _css_color(QColor(t.panel.red() + 18, t.panel.green() + 18, t.panel.blue() + 18))
        text = _css_color(t.text)
        return (
            f"QPushButton {{ background: {bg}; color: {text}; border: none; "
            f"border-radius: 6px; padding: 8px 12px; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {hover}; }}"
        )


# ------------------------------------------------------------------
# Main application
# ------------------------------------------------------------------
class MagnetClientPrototype(QApplication):
    def __init__(self, argv):
        super().__init__(argv)
        self.setQuitOnLastWindowClosed(False)

        self.theme = Theme(_is_dark_mode(self))
        try:
            self.styleHints().colorSchemeChanged.connect(self._theme_changed)
        except Exception:
            pass

        # Render the tray icon at the exact OS chrome sizes.
        self._glyphs = {size: GlyphRenderer(size=size) for size in (16, 18, 24, 32)}
        for g in self._glyphs.values():
            g.set_state("idle")

        self.flyout = FlyoutPanel(self.theme)
        self.flyout.set_status("idle")
        self.flyout.hide()

        self.tray = QSystemTrayIcon(self)
        self._setup_context_menu()
        self.tray.activated.connect(self._on_tray_activated)
        self._update_tray_icon()
        self.tray.show()

        self._control = StateControlDialog(self.theme)
        self._control.state_changed.connect(self.set_state)
        self._control.flyout_requested.connect(self._show_flyout)
        self._control.show()

        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._animate_glyph)
        self._animation_timer.start(100)

        # First launch: show the flyout briefly so the user learns where Magnet lives.
        QTimer.singleShot(300, self._show_flyout)

    def _setup_context_menu(self):
        menu = QMenu()
        show_action = QAction("Show", self)
        show_action.triggered.connect(self._show_flyout)
        menu.addAction(show_action)

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)

    def _update_tray_icon(self):
        icon = QIcon()
        for g in self._glyphs.values():
            pm = g.pixmap(self.theme, color=self.theme.glyph_tray)
            icon.addPixmap(pm)
        icon.setIsMask(sys.platform == "darwin")
        self.tray.setIcon(icon)

    def _animate_glyph(self):
        for g in self._glyphs.values():
            g.update(0.1)
        self._update_tray_icon()

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._toggle_flyout()
        elif reason == QSystemTrayIcon.ActivationReason.Context:
            pass  # native context menu handles this

    def _show_flyout(self):
        if self.flyout.isVisible():
            self.flyout.hide()
            return

        self.flyout.adjustSize()
        tray_geo = self.tray.geometry()
        screen = self.primaryScreen().availableGeometry()

        if tray_geo.isValid() and tray_geo.width() > 0:
            x = tray_geo.center().x() - self.flyout.width() // 2
            # macOS menu bar is at the top of the screen: show the flyout below it.
            # Windows/Linux tray is typically at the bottom: show the flyout above it.
            if sys.platform == "darwin":
                y = tray_geo.bottom() + 8
            else:
                y = tray_geo.top() - self.flyout.height() - 8
        else:
            # Fallback: center near the top of the screen for the prototype.
            x = screen.center().x() - self.flyout.width() // 2
            y = 120

        # Keep on screen.
        x = max(screen.left() + 8, min(x, screen.right() - self.flyout.width() - 8))
        y = max(screen.top() + 8, min(y, screen.bottom() - self.flyout.height() - 8))

        self.flyout.move(x, y)
        self.flyout.show()
        self.flyout.raise_()
        self.flyout.activateWindow()

    def _toggle_flyout(self):
        if self.flyout.isVisible():
            self.flyout.hide()
        else:
            self._show_flyout()

    def _theme_changed(self):
        self.theme = Theme(_is_dark_mode(self))
        self.flyout.apply_theme(self.theme)
        self._control.apply_theme(self.theme)
        self._update_tray_icon()

    def set_state(self, state: str):
        for g in self._glyphs.values():
            g.set_state(state)
        self.flyout.set_status(state)
        self._update_tray_icon()


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------
if __name__ == "__main__":
    app = MagnetClientPrototype(sys.argv)
    sys.exit(app.exec())
