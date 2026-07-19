"""
Magnet Agent v2 Prototype

A self-contained UI/UX prototype for the MagnetOS Agent command center.
Demonstrates the new v2 design language: left sidebar with the connected
three-node hexagonal brand glyph at the bottom, premium dark glass panels,
large spacing, and a minimal main content area.

This file is intentionally self-contained and does not yet wire in the
existing Magnet Agent backend.
"""

import sys

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QPainter, QPainterPath, QBrush, QPen, QCursor, QMouseEvent,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QFrame, QSizePolicy, QGraphicsDropShadowEffect,
    QLineEdit, QTextEdit,
)


from magnet_v2_glyph import Theme, GlyphRenderer, _is_dark_mode, _css_color


def _make_agent_theme(dark: bool) -> Theme:
    """Return an agent theme with a premium light/dark navy palette."""
    t = Theme(dark)
    if not dark:
        # Light mode: pale navy background with dark soft navy panels.
        t.bg = QColor(232, 240, 250)
        t.panel = QColor(44, 60, 88)
        t.text = QColor(248, 250, 252)
        t.muted = QColor(168, 182, 202)
        t.accent = QColor(95, 135, 255)
        t.glyph = QColor(190, 210, 255)
        t.glyph_tray = QColor(32, 38, 52)
        t.hover = QColor(58, 78, 112)
    return t


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

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setColor(QColor(0, 0, 0, 70))
        shadow.setOffset(0, 4)
        self.setGraphicsEffect(shadow)


class PageWidget(QWidget):
    def __init__(self, title: str, theme: Theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        title_color = _css_color(theme.text if theme.dark else theme.panel)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {title_color}; font-size: 24px; font-weight: 600;"
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


class SidebarPanel(QFrame):
    """A detached, floating sidebar panel with rounded corners and a soft shadow."""

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.setFixedWidth(260)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._apply_theme(theme)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setColor(QColor(0, 0, 0, 150))
        shadow.setOffset(10, 6)
        self.setGraphicsEffect(shadow)

    def _apply_theme(self, theme: Theme):
        self.setStyleSheet(
            f"background: {_css_color(theme.panel)}; "
            f"border-radius: 18px;"
        )


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
    def __init__(self, theme: Theme, glyph: GlyphRenderer, initial_view: int = 0, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.glyph = glyph
        self._drag_pos = None

        self.setWindowTitle("Magnet Agent")
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.resize(1100, 720)
        self.setMinimumSize(900, 560)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(self.backgroundRole(), theme.bg)
        self.setPalette(palette)

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
        body.setContentsMargins(20, 20, 0, 20)
        body.setSpacing(20)

        # Sidebar (detached floating panel)
        sidebar = SidebarPanel(self.theme)
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
            ("Atlas Workstation", self._build_active_session_page()),
        ]
        for idx, (label, page) in enumerate(views):
            btn = QPushButton(label)
            btn.setStyleSheet(self._nav_stylesheet(idx == initial_view))
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setCheckable(True)
            btn.setChecked(idx == initial_view)
            btn.clicked.connect(lambda checked, i=idx: self._switch_view(i))
            self._nav_btns.append(btn)
            sidebar_layout.addWidget(btn)
            self._stack.addWidget(page)

        self._switch_view(initial_view)

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

    def _build_active_session_page(self):
        page = PageWidget("Atlas Workstation", self.theme)

        hbox = QHBoxLayout()
        hbox.setSpacing(20)
        hbox.setContentsMargins(0, 0, 0, 0)

        cmd_panel = self._make_session_panel("Commands", "Type a command...", "> awaiting command...")
        chat_panel = self._make_session_panel("Chat", "Type a message...", "Atlas: ready for instructions.")
        hbox.addWidget(cmd_panel, 1)
        hbox.addWidget(chat_panel, 1)

        page._body.addLayout(hbox, 1)
        return page

    def _make_session_panel(self, title: str, placeholder: str, output_text: str) -> QFrame:
        panel = QFrame()
        panel.setStyleSheet(f"background: {_css_color(self.theme.panel)}; border-radius: 12px;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {_css_color(self.theme.text)}; font-size: 14px; font-weight: 600;"
        )
        layout.addWidget(title_lbl)

        output = QTextEdit()
        output.setReadOnly(True)
        output.setText(output_text)
        output.setStyleSheet(
            f"QTextEdit {{ background: {_css_color(self.theme.hover)}; "
            f"color: {_css_color(self.theme.text)}; border: none; border-radius: 8px; "
            f"padding: 8px; }}"
        )
        layout.addWidget(output, 1)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        line = QLineEdit()
        line.setPlaceholderText(placeholder)
        line.setStyleSheet(
            f"QLineEdit {{ background: {_css_color(self.theme.hover)}; "
            f"color: {_css_color(self.theme.text)}; border: none; border-radius: 6px; "
            f"padding: 6px; }}"
        )
        btn = QPushButton("Send")
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setStyleSheet(
            f"QPushButton {{ background: {_css_color(self.theme.accent)}; "
            f"color: {_css_color(self.theme.text)}; border: none; border-radius: 6px; "
            f"padding: 6px 12px; }}"
            f"QPushButton:hover {{ background: {_css_color(self.theme.hover)}; }}"
        )
        input_row.addWidget(line, 1)
        input_row.addWidget(btn)
        layout.addLayout(input_row)

        shadow = QGraphicsDropShadowEffect(panel)
        shadow.setBlurRadius(18)
        shadow.setColor(QColor(0, 0, 0, 70))
        shadow.setOffset(0, 4)
        panel.setGraphicsEffect(shadow)

        return panel

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
    def __init__(self, argv, force_light: bool = False, initial_view: int = 0):
        super().__init__(argv)

        self.theme = _make_agent_theme(not force_light and _is_dark_mode(self))
        self._initial_view = initial_view
        try:
            self.styleHints().colorSchemeChanged.connect(self._theme_changed)
        except Exception:
            pass

        self.glyph = GlyphRenderer(size=160)
        self.glyph.set_state("idle")

        self.window = AgentWindow(self.theme, self.glyph, initial_view=self._initial_view)
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
    view_map = {"sessions": 0, "commands": 1, "terminal": 2, "settings": 3, "active": 4}
    force_light = False
    initial_view = 0
    argv = []
    i = 0
    while i < len(sys.argv):
        a = sys.argv[i]
        if a == "--light":
            force_light = True
        elif a.startswith("--view="):
            initial_view = view_map.get(a.split("=", 1)[1], 0)
        elif a == "--view":
            i += 1
            if i < len(sys.argv):
                initial_view = view_map.get(sys.argv[i], 0)
        else:
            argv.append(a)
        i += 1

    app = MagnetAgentPrototype(argv, force_light=force_light, initial_view=initial_view)
    sys.exit(app.exec())

