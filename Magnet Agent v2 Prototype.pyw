"""
Magnet Agent v2 Prototype

A self-contained UI/UX prototype for the MagnetOS Agent command center.
Demonstrates the new v2 design language: left sidebar with the connected
three-node hexagonal brand glyph at the bottom, premium dark glass panels,
large spacing, and a minimal main content area.

This file is intentionally self-contained and does not yet wire in the
existing Magnet Agent backend.
"""

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QUrl, QProcess
from PySide6.QtGui import (
    QColor, QPainter, QPainterPath, QBrush, QPen, QCursor, QMouseEvent,
    QDesktopServices,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QFrame, QSizePolicy, QGraphicsDropShadowEffect,
    QLineEdit, QTextEdit, QListWidget, QListWidgetItem, QMessageBox,
    QTreeWidget, QTreeWidgetItem, QSplitter, QFileDialog, QMenu,
    QHeaderView,
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
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(0, 0, 0, 85))
        shadow.setOffset(4, 4)
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
        self.resize(1200, 820)
        self.setMinimumSize(1000, 640)
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

        quick_row = QHBoxLayout()
        quick_row.setSpacing(8)
        quick_row.setContentsMargins(0, 0, 0, 0)
        for label in ("Screenshot", "Feed", "Pause", "Pulse", "Vision", "Files", "Terminal"):
            btn = self._quick_action_button(label)
            btn.clicked.connect(lambda checked=False, a=label: self._on_quick_action(a))
            quick_row.addWidget(btn)
        quick_row.addStretch()
        page._body.addLayout(quick_row)

        hbox = QHBoxLayout()
        hbox.setSpacing(20)
        hbox.setContentsMargins(0, 0, 0, 0)

        # Left column: file manager + manual commands button
        left_col = QWidget()
        left_layout = QVBoxLayout(left_col)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)

        self._file_manager = FileManagerWindow(self.theme, "~")
        left_layout.addWidget(self._file_manager, 1)

        manual_btn = QPushButton("Run manual Magnet commands")
        manual_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        manual_btn.setStyleSheet(
            f"QPushButton {{ background: {_css_color(self.theme.hover)}; color: {_css_color(self.theme.text)}; "
            f"border: none; border-radius: 6px; padding: 8px 14px; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {_css_color(self.theme.accent)}; }}"
        )
        manual_btn.clicked.connect(self._open_command_window)
        left_layout.addWidget(manual_btn)

        chat_panel, self._chat_output, self._chat_line = self._make_session_panel(
            "Chat", "Type a message...", "Atlas: ready for instructions.", self._on_chat_send
        )
        hbox.addWidget(left_col, 2)
        hbox.addWidget(chat_panel, 1)

        page._body.addLayout(hbox, 1)
        return page

    def _quick_action_button(self, label: str) -> QPushButton:
        t = self.theme
        btn = QPushButton(label)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setStyleSheet(
            f"QPushButton {{ background: {_css_color(t.hover)}; color: {_css_color(t.text)}; border: none; "
            f"border-radius: 6px; padding: 6px 12px; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {_css_color(t.accent)}; }}"
        )
        return btn

    def _on_quick_action(self, action: str):
        if action == "Vision":
            self._open_vision()
        elif action == "Screenshot":
            self._open_screenshot()
        elif action == "Files":
            self._open_file_manager()
        elif action == "Terminal":
            self._open_terminal()
        elif action == "Feed":
            self._file_manager._load_path(self._file_manager.feed_path)
        else:
            self.set_status(action.lower())

    def _make_session_panel(self, title: str, placeholder: str, output_text: str, on_send):
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
        btn.clicked.connect(lambda: on_send(line, output))
        input_row.addWidget(line, 1)
        input_row.addWidget(btn)
        layout.addLayout(input_row)

        shadow = QGraphicsDropShadowEffect(panel)
        shadow.setBlurRadius(18)
        shadow.setColor(QColor(0, 0, 0, 70))
        shadow.setOffset(0, 4)
        panel.setGraphicsEffect(shadow)

        return panel, output, line

    def _on_chat_send(self, line: QLineEdit, output: QTextEdit):
        text = line.text().strip()
        line.clear()
        if text:
            output.append(f"You: {text}")

    def _open_command_window(self):
        self._command_window = CommandWindow(self.theme, self)
        self._command_window.show()

    def _run_magnet_command(self, cmd: str) -> str:
        lower = cmd.lower().strip()
        if lower.startswith(".xnavigate") or lower == ".navigate":
            path = cmd[10:].strip() if lower.startswith(".xnavigate") else cmd[8:].strip()
            path = path or "~"
            self._file_manager._load_path(Path(os.path.expanduser(path)))
            return f"Opened folder view: {path}"
        elif lower.startswith(".xterminal") or lower == ".terminal":
            self._open_terminal()
            return "Opened Terminal window"
        elif lower.startswith(".vision"):
            self._open_vision()
            return "Opened Vision"
        elif lower.startswith(".screenshot"):
            self._open_screenshot()
            return "Opened Screenshot"
        elif lower.startswith(".feed"):
            self._file_manager._load_path(self._file_manager.feed_path)
            return "Opened Feed / Incoming location"
        else:
            return f"Sent to Atlas Workstation: {cmd}"

    def _open_vision(self):
        self._vision_window = VisionWindow(self.theme)
        self._vision_window.show()

    def _open_file_manager(self, path: str = "~"):
        self._file_window = FileManagerWindow(self.theme, path)
        self._file_window.show()

    def _open_terminal(self):
        self._terminal_window = TerminalWindow(self.theme)
        self._terminal_window.show()

    def _open_screenshot(self):
        self._screenshot_window = ScreenshotWindow(self.theme)
        self._screenshot_window.show()

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
# Pop-out windows
# ------------------------------------------------------------------
class VisionWindow(QWidget):
    """Pop-out Vision viewer with an Interact toggle for pointer/keyboard control."""

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setWindowTitle("Vision — Atlas Workstation")
        self.resize(1200, 800)
        self.setStyleSheet(f"background: {_css_color(theme.bg)};")
        self._interact = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Vision — Atlas Workstation")
        title.setStyleSheet(
            f"color: {_css_color(theme.panel)}; font-size: 18px; font-weight: 600;"
        )
        header.addWidget(title)
        header.addStretch()

        self.interact_btn = QPushButton("Interact")
        self.interact_btn.setCheckable(True)
        self.interact_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.interact_btn.setStyleSheet(
            f"QPushButton {{ background: {_css_color(theme.hover)}; color: {_css_color(theme.text)}; "
            f"border: none; border-radius: 6px; padding: 6px 14px; font-size: 12px; }}"
            f"QPushButton:checked {{ background: {_css_color(theme.accent)}; }}"
            f"QPushButton:hover {{ background: {_css_color(theme.accent)}; }}"
        )
        self.interact_btn.toggled.connect(self._toggle_interact)
        header.addWidget(self.interact_btn)
        layout.addLayout(header)

        self.video = QLabel("Vision stream placeholder")
        self.video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video.setStyleSheet(
            f"background: {_css_color(theme.panel)}; color: {_css_color(theme.text)}; "
            f"border-radius: 12px; font-size: 14px;"
        )
        self.video.setMinimumSize(800, 600)
        self.video.setMouseTracking(True)
        self.video.mouseMoveEvent = self._on_mouse_move
        self.video.mousePressEvent = self._on_mouse_press
        self.video.keyPressEvent = self._on_key_press
        self.video.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        layout.addWidget(self.video, 1)

        self.status = QLabel("Click Interact to control the remote pointer and keyboard.")
        self.status.setStyleSheet(f"color: {_css_color(theme.muted)}; font-size: 12px;")
        layout.addWidget(self.status)

    def _toggle_interact(self, checked: bool):
        self._interact = checked
        if checked:
            self.video.setCursor(QCursor(Qt.CursorShape.CrossCursor))
            self.status.setText("Interact mode ON — pointer and keyboard events are forwarded silently.")
        else:
            self.video.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self.status.setText("Click Interact to control the remote pointer and keyboard.")

    def _on_mouse_move(self, event):
        if self._interact:
            pos = event.position().toPoint()
            self.status.setText(f"Pointer at ({pos.x()}, {pos.y()}) — forwarding silently")
        else:
            QLabel.mouseMoveEvent(self.video, event)

    def _on_mouse_press(self, event):
        if self._interact:
            pos = event.position().toPoint()
            self.status.setText(f"Click at ({pos.x()}, {pos.y()}) — forwarding silently")
        else:
            QLabel.mousePressEvent(self.video, event)

    def _on_key_press(self, event):
        if self._interact:
            self.status.setText(f"Key pressed: {event.text()} — forwarding silently")
        else:
            QLabel.keyPressEvent(self.video, event)


class FileManagerWindow(QWidget):
    """Agent-side remote file manager (.xnavigate)."""

    LOCATIONS = {}

    def __init__(self, theme: Theme, path: str = "~", parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setWindowTitle("File Manager — Atlas Workstation")
        self.resize(1000, 750)
        self.setStyleSheet(f"background: {_css_color(theme.bg)};")
        self.setAcceptDrops(True)

        self.feed_path = Path.home() / "MagnetOS" / "Incoming"
        self.feed_path.mkdir(parents=True, exist_ok=True)
        self.LOCATIONS = {
            "Feed / Incoming": self.feed_path,
            "Home": Path.home(),
            "Desktop": Path.home() / "Desktop",
            "Documents": Path.home() / "Documents",
            "Downloads": Path.home() / "Downloads",
            "Pictures": Path.home() / "Pictures",
            "Videos": Path.home() / "Videos",
            "Dropbox": Path.home() / "Dropbox",
            "OneDrive": Path.home() / "OneDrive",
        }

        self.current_path = Path(os.path.expanduser(path))
        self._clipboard = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        for label in ("Back", "Refresh", "Upload", "Download", "Delete", "New Folder"):
            btn = QPushButton(label)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setStyleSheet(
                f"QPushButton {{ background: {_css_color(theme.hover)}; color: {_css_color(theme.text)}; "
                f"border: none; border-radius: 6px; padding: 6px 12px; font-size: 12px; }}"
                f"QPushButton:hover {{ background: {_css_color(theme.accent)}; }}"
            )
            btn.clicked.connect(lambda checked=False, a=label: self._toolbar_action(a))
            toolbar.addWidget(btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Main splitter: locations on left, files on right
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Locations sidebar
        locations_panel = QWidget()
        locations_panel.setStyleSheet(
            f"background: {_css_color(theme.panel)}; border-radius: 12px;"
        )
        locations_layout = QVBoxLayout(locations_panel)
        locations_layout.setContentsMargins(10, 10, 10, 10)
        locations_layout.setSpacing(6)

        loc_title = QLabel("Locations")
        loc_title.setStyleSheet(
            f"color: {_css_color(theme.text)}; font-size: 13px; font-weight: 600;"
        )
        locations_layout.addWidget(loc_title)

        self.locations = QListWidget()
        self.locations.setStyleSheet(
            f"QListWidget {{ background: transparent; color: {_css_color(theme.text)}; border: none; }}"
            f"QListWidget::item {{ padding: 6px; border-radius: 4px; }}"
            f"QListWidget::item:selected {{ background: {_css_color(theme.accent)}; }}"
            f"QListWidget::item:hover {{ background: {_css_color(theme.hover)}; }}"
        )
        self.locations.itemClicked.connect(self._location_clicked)
        locations_layout.addWidget(self.locations, 1)
        splitter.addWidget(locations_panel)

        # Files view
        files_panel = QWidget()
        files_panel.setStyleSheet(
            f"background: {_css_color(theme.panel)}; border-radius: 12px;"
        )
        files_layout = QVBoxLayout(files_panel)
        files_layout.setContentsMargins(10, 10, 10, 10)
        files_layout.setSpacing(8)

        path_row = QHBoxLayout()
        self.path_label = QLabel()
        self.path_label.setStyleSheet(
            f"color: {_css_color(theme.text)}; font-size: 13px; font-weight: 600;"
        )
        path_row.addWidget(self.path_label)
        path_row.addStretch()

        search_row = QHBoxLayout()
        search_lbl = QLabel("Search")
        search_lbl.setStyleSheet(f"color: {_css_color(theme.muted)}; font-size: 11px;")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Narrows the list below as you type...")
        self.search_edit.setMaximumHeight(26)
        self.search_edit.setStyleSheet(
            f"QLineEdit {{ background: {_css_color(theme.hover)}; color: {_css_color(theme.text)}; "
            f"border: none; border-radius: 5px; padding: 3px 6px; font-size: 11px; }}"
        )
        self.search_edit.textChanged.connect(self._on_search)
        search_row.addWidget(search_lbl)
        search_row.addWidget(self.search_edit, 1)
        path_row.addLayout(search_row)

        files_layout.addLayout(path_row)

        self.files = QTreeWidget()
        self.files.setHeaderLabels(["Name", "Size", "Modified"])
        self.files.setStyleSheet(
            f"QTreeWidget {{ background: {_css_color(theme.hover)}; color: {_css_color(theme.text)}; "
            f"border: none; border-radius: 8px; }}"
            f"QTreeWidget::item {{ padding: 6px; }}"
            f"QTreeWidget::item:selected {{ background: {_css_color(theme.accent)}; }}"
        )
        self.files.setColumnWidth(0, 320)
        self.files.header().setStretchLastSection(False)
        self.files.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.files.setColumnWidth(1, 100)
        self.files.setColumnWidth(2, 160)
        self.files.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.files.customContextMenuRequested.connect(self._context_menu)
        self.files.itemDoubleClicked.connect(self._item_double_clicked)
        files_layout.addWidget(self.files, 1)
        splitter.addWidget(files_panel)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([200, 700])
        layout.addWidget(splitter, 1)

        # Status
        self.status = QLabel("Ready")
        self.status.setStyleSheet(f"color: {_css_color(theme.muted)}; font-size: 12px;")
        layout.addWidget(self.status)

        self._load_locations()
        self._load_path(self.current_path)

    def _load_locations(self):
        self.locations.clear()
        for name, p in self.LOCATIONS.items():
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, str(p))
            if not p.exists():
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                item.setForeground(QColor(255, 255, 255, 120))
            self.locations.addItem(item)

    def _load_path(self, path):
        if isinstance(path, str):
            path = Path(os.path.expanduser(path))
        self.current_path = path
        self.path_label.setText(str(path))
        self.files.clear()
        try:
            entries = sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
            for entry in entries:
                item = QTreeWidgetItem()
                item.setText(0, f"{'📁' if entry.is_dir() else '📄'}  {entry.name}")
                if entry.is_file():
                    item.setText(1, self._human_size(entry.stat().st_size))
                    item.setText(2, self._fmt_time(entry.stat().st_mtime))
                else:
                    item.setText(1, "--")
                    item.setText(2, "--")
                item.setData(0, Qt.ItemDataRole.UserRole, str(entry))
                self.files.addTopLevelItem(item)
            self.status.setText(f"{len(entries)} items")
        except Exception as e:
            self.status.setText(f"Unable to read path: {e}")

    def _location_clicked(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            self._load_path(Path(path))

    def _item_double_clicked(self, item):
        path_str = item.data(0, Qt.ItemDataRole.UserRole)
        if not path_str:
            return
        p = Path(path_str)
        if p.is_dir():
            self._load_path(p)
        else:
            self._open_file(p)

    def _open_file(self, p: Path):
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
        except Exception as e:
            self.status.setText(f"Open failed: {e}")

    def _context_menu(self, pos):
        item = self.files.itemAt(pos)
        if item:
            self.files.setCurrentItem(item)
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {_css_color(self.theme.panel)}; color: {_css_color(self.theme.text)}; border: none; padding: 4px; }}"
            f"QMenu::item {{ padding: 6px 12px; }}"
            f"QMenu::item:selected {{ background: {_css_color(self.theme.accent)}; }}"
        )
        menu.addAction("Open", self._ctx_open)
        menu.addAction("Download", self._ctx_download)
        menu.addAction("Copy", self._ctx_copy)
        if self._clipboard:
            menu.addAction("Paste", self._ctx_paste)
        menu.addAction("Delete", self._ctx_delete)
        menu.exec(self.files.mapToGlobal(pos))

    def _ctx_open(self):
        item = self.files.currentItem()
        if item:
            self._item_double_clicked(item)

    def _ctx_download(self):
        item = self.files.currentItem()
        if not item:
            return
        src = Path(item.data(0, Qt.ItemDataRole.UserRole))
        if not src.is_file():
            self.status.setText("Select a file to download")
            return
        dest = QFileDialog.getExistingDirectory(self, "Download to...")
        if dest:
            try:
                import shutil
                shutil.copy2(src, Path(dest) / src.name)
                self.status.setText(f"Downloaded {src.name}")
            except Exception as e:
                self.status.setText(f"Download failed: {e}")

    def _ctx_copy(self):
        item = self.files.currentItem()
        if item:
            self._clipboard = Path(item.data(0, Qt.ItemDataRole.UserRole))
            self.status.setText(f"Copied {self._clipboard.name} to clipboard")

    def _ctx_paste(self):
        if not self._clipboard:
            return
        try:
            import shutil
            dest = self.current_path / self._clipboard.name
            if self._clipboard.is_dir():
                shutil.copytree(self._clipboard, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(self._clipboard, dest)
            self._load_path(self.current_path)
            self.status.setText(f"Pasted {self._clipboard.name}")
        except Exception as e:
            self.status.setText(f"Paste failed: {e}")

    def _ctx_delete(self):
        item = self.files.currentItem()
        if not item:
            return
        src = Path(item.data(0, Qt.ItemDataRole.UserRole))
        reply = QMessageBox.question(
            self, "Delete", f"Delete {src.name}?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                import shutil
                if src.is_dir():
                    shutil.rmtree(src)
                else:
                    src.unlink()
                self._load_path(self.current_path)
                self.status.setText(f"Deleted {src.name}")
            except Exception as e:
                self.status.setText(f"Delete failed: {e}")

    def _toolbar_action(self, action: str):
        if action == "Back":
            parent = self.current_path.parent
            if parent != self.current_path:
                self._load_path(parent)
        elif action == "Refresh":
            self._load_path(self.current_path)
        elif action == "Upload":
            files, _ = QFileDialog.getOpenFileNames(self, "Upload files")
            for f in files:
                name = Path(f).name
                try:
                    import shutil
                    shutil.copy2(f, self.current_path / name)
                    self.status.setText(f"Uploaded {name}")
                except Exception as e:
                    self.status.setText(f"Upload failed: {e}")
            self._load_path(self.current_path)
        elif action == "Download":
            self._ctx_download()
        elif action == "Delete":
            self._ctx_delete()
        elif action == "New Folder":
            from PySide6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
            if ok and name:
                try:
                    (self.current_path / name).mkdir(exist_ok=True)
                    self._load_path(self.current_path)
                except Exception as e:
                    self.status.setText(f"Create folder failed: {e}")

    def _human_size(self, size: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if abs(size) < 1024:
                return f"{size:.1f} {unit}" if unit != "B" else f"{size} {unit}"
            size /= 1024
        return f"{size:.1f} PB"

    def _fmt_time(self, ts: float) -> str:
        try:
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return "--"

    def _on_search(self, text: str):
        query = text.strip().lower()
        for i in range(self.files.topLevelItemCount()):
            item = self.files.topLevelItem(i)
            name = item.text(0).lower()
            item.setHidden(query != "" and query not in name)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        event.acceptProposedAction()
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local:
                name = Path(local).name
                try:
                    import shutil
                    shutil.copy2(local, self.current_path / name)
                    self.status.setText(f"Uploaded {name}")
                except Exception as e:
                    self.status.setText(f"Upload failed: {e}")
        self._load_path(self.current_path)


class TerminalWindow(QWidget):
    """Agent-side remote terminal (.xterminal)."""

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self._cwd = str(Path.home())
        self.setWindowTitle("Terminal — Atlas Workstation")
        self.resize(900, 600)
        self.setStyleSheet(f"background: {_css_color(theme.bg)};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Terminal — Atlas Workstation")
        title.setStyleSheet(
            f"color: {_css_color(theme.panel)}; font-size: 16px; font-weight: 600;"
        )
        header.addWidget(title)
        header.addStretch()

        clear_btn = QPushButton("Clear")
        clear_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        clear_btn.setStyleSheet(
            f"QPushButton {{ background: {_css_color(theme.hover)}; color: {_css_color(theme.text)}; "
            f"border: none; border-radius: 6px; padding: 5px 12px; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {_css_color(theme.accent)}; }}"
        )
        clear_btn.clicked.connect(self._clear)
        header.addWidget(clear_btn)
        layout.addLayout(header)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setStyleSheet(
            f"QTextEdit {{ background: {_css_color(theme.panel)}; color: {_css_color(theme.text)}; "
            f"border: none; border-radius: 12px; padding: 10px; font-family: monospace; }}"
        )
        self.output.setText(
            "Remote terminal connected to Atlas Workstation.\n"
            "Type shell commands below (cd, pip, ls, etc.).\n"
            "In production these execute silently on the client.\n"
        )
        layout.addWidget(self.output, 1)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Enter command...")
        self.input.setStyleSheet(
            f"QLineEdit {{ background: {_css_color(theme.hover)}; color: {_css_color(theme.text)}; "
            f"border: none; border-radius: 6px; padding: 6px; font-family: monospace; }}"
        )
        self.input.returnPressed.connect(self._run_command)
        run_btn = QPushButton("Run")
        run_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        run_btn.setStyleSheet(
            f"QPushButton {{ background: {_css_color(theme.accent)}; color: {_css_color(theme.text)}; "
            f"border: none; border-radius: 6px; padding: 6px 14px; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {_css_color(theme.hover)}; }}"
        )
        run_btn.clicked.connect(self._run_command)
        input_row.addWidget(self.input, 1)
        input_row.addWidget(run_btn)
        layout.addLayout(input_row)

    def _run_command(self):
        cmd = self.input.text().strip()
        self.input.clear()
        if not cmd:
            return
        self.output.append(f"{self._cwd}> {cmd}")

        if cmd.lower().startswith("cd "):
            target = cmd[3:].strip()
            new_path = Path(target).expanduser()
            if not new_path.is_absolute():
                new_path = Path(self._cwd) / new_path
            new_path = new_path.resolve()
            if new_path.is_dir():
                self._cwd = str(new_path)
                self.output.append(f"[cwd {self._cwd}]")
            else:
                self.output.append(f"cd: {new_path}: No such directory")
            return

        try:
            result = subprocess.run(
                cmd, shell=True, cwd=self._cwd, capture_output=True, text=True, timeout=30
            )
            out = result.stdout.strip()
            err = result.stderr.strip()
            if out:
                self.output.append(out)
            if err:
                self.output.append(err)
            if result.returncode != 0 and not err:
                self.output.append(f"Exit code: {result.returncode}")
        except subprocess.TimeoutExpired:
            self.output.append("Command timed out after 30 seconds.")
        except Exception as e:
            self.output.append(f"Error: {e}")

    def _clear(self):
        self.output.setText(
            "Remote terminal connected to Atlas Workstation.\n"
            "Type shell commands below (cd, pip, ls, etc.).\n"
            "In production these execute silently on the client.\n"
        )


class ScreenshotWindow(QWidget):
    """Pop-out screenshot viewer."""

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setWindowTitle("Screenshot — Atlas Workstation")
        self.resize(1000, 750)
        self.setStyleSheet(f"background: {_css_color(theme.bg)};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Screenshot — Atlas Workstation")
        title.setStyleSheet(
            f"color: {_css_color(theme.panel)}; font-size: 18px; font-weight: 600;"
        )
        header.addWidget(title)
        header.addStretch()

        save_btn = QPushButton("Save")
        save_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        save_btn.setStyleSheet(
            f"QPushButton {{ background: {_css_color(theme.accent)}; color: {_css_color(theme.text)}; "
            f"border: none; border-radius: 6px; padding: 6px 14px; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {_css_color(theme.hover)}; }}"
        )
        save_btn.clicked.connect(self._save)
        header.addWidget(save_btn)
        layout.addLayout(header)

        self.image = QLabel("Screenshot captured")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setStyleSheet(
            f"background: {_css_color(theme.panel)}; color: {_css_color(theme.text)}; "
            f"border-radius: 12px; font-size: 14px;"
        )
        self.image.setMinimumSize(800, 600)
        layout.addWidget(self.image, 1)

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Screenshot", "atlas_screenshot.png")
        if path:
            self.image.setText(f"Saved to {path}")


class CommandWindow(QWidget):
    """Pop-out window for classic Magnet commands (.screenshot, .feed, etc.)."""

    def __init__(self, theme: Theme, agent=None, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.agent = agent
        self.setWindowTitle("Manual Commands — Atlas Workstation")
        self.resize(600, 500)
        self.setStyleSheet(f"background: {_css_color(theme.bg)};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Manual Magnet Commands")
        title.setStyleSheet(
            f"color: {_css_color(theme.panel)}; font-size: 18px; font-weight: 600;"
        )
        header.addWidget(title)
        header.addStretch()

        clear_btn = QPushButton("Clear")
        clear_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        clear_btn.setStyleSheet(
            f"QPushButton {{ background: {_css_color(theme.hover)}; color: {_css_color(theme.text)}; "
            f"border: none; border-radius: 6px; padding: 5px 12px; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {_css_color(theme.accent)}; }}"
        )
        clear_btn.clicked.connect(self._clear)
        header.addWidget(clear_btn)
        layout.addLayout(header)

        # Quick command chips
        chips = QHBoxLayout()
        chips.setSpacing(8)
        for label in (".screenshot", ".feed", ".pause", ".pulse", ".vision", ".xnavigate"):
            btn = QPushButton(label)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setStyleSheet(
                f"QPushButton {{ background: {_css_color(theme.hover)}; color: {_css_color(theme.text)}; "
                f"border: none; border-radius: 6px; padding: 5px 10px; font-size: 11px; }}"
                f"QPushButton:hover {{ background: {_css_color(theme.accent)}; }}"
            )
            btn.clicked.connect(lambda checked=False, c=label: self._send(c))
            chips.addWidget(btn)
        chips.addStretch()
        layout.addLayout(chips)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setStyleSheet(
            f"QTextEdit {{ background: {_css_color(theme.panel)}; color: {_css_color(theme.text)}; "
            f"border: none; border-radius: 12px; padding: 10px; font-family: monospace; }}"
        )
        self.output.setText("Enter a classic Magnet command below.\n")
        layout.addWidget(self.output, 1)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type .screenshot, .feed, .xnavigate, etc.")
        self.input.setStyleSheet(
            f"QLineEdit {{ background: {_css_color(theme.hover)}; color: {_css_color(theme.text)}; "
            f"border: none; border-radius: 6px; padding: 6px; font-family: monospace; }}"
        )
        self.input.returnPressed.connect(self._send_from_input)
        run_btn = QPushButton("Run")
        run_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        run_btn.setStyleSheet(
            f"QPushButton {{ background: {_css_color(theme.accent)}; color: {_css_color(theme.text)}; "
            f"border: none; border-radius: 6px; padding: 6px 14px; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {_css_color(theme.hover)}; }}"
        )
        run_btn.clicked.connect(self._send_from_input)
        input_row.addWidget(self.input, 1)
        input_row.addWidget(run_btn)
        layout.addLayout(input_row)

    def _send_from_input(self):
        cmd = self.input.text().strip()
        self.input.clear()
        self._send(cmd)

    def _send(self, cmd: str):
        if not cmd:
            return
        self.output.append(f"> {cmd}")
        if self.agent:
            try:
                result = self.agent._run_magnet_command(cmd)
                self.output.append(result)
            except Exception as e:
                self.output.append(f"Error: {e}")
        else:
            self.output.append(f"Sent to Atlas Workstation: {cmd}")

    def _clear(self):
        self.output.setText("Enter a classic Magnet command below.\n")


# ------------------------------------------------------------------
# Main application
# ------------------------------------------------------------------
class MagnetAgentPrototype(QApplication):
    def __init__(self, argv, force_light: bool = False, initial_view: int = 0):
        super().__init__(argv)

        self.theme = _make_agent_theme(not force_light and _is_dark_mode(self))
        self._initial_view = initial_view
        self._apply_scroll_style()
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
        self._apply_scroll_style()
        self.window._glyph_lbl.theme = self.theme
        self.window._glyph_lbl.refresh()
        self._control.apply_theme(self.theme)

    def _apply_scroll_style(self):
        t = self.theme
        self.setStyleSheet(
            "QScrollBar:vertical { background: " + _css_color(t.hover) + "; width: 8px; border-radius: 4px; }"
            "QScrollBar::handle:vertical { background: " + _css_color(t.accent) + "; border-radius: 4px; min-height: 24px; }"
            "QScrollBar::handle:vertical:hover { background: " + _css_color(t.text) + "; }"
            "QScrollBar:horizontal { background: " + _css_color(t.hover) + "; height: 8px; border-radius: 4px; }"
            "QScrollBar::handle:horizontal { background: " + _css_color(t.accent) + "; border-radius: 4px; min-width: 24px; }"
            "QScrollBar::handle:horizontal:hover { background: " + _css_color(t.text) + "; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical, "
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0px; height: 0px; }"
        )

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

