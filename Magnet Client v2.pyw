"""
Magnet Client v2
================
A matching MagnetOS v2 client for the support recipient.

- No orb; a quiet system-tray / menu-bar glyph with subtle motion.
- Clicking the tray icon opens a small rounded flyout.
- From the flyout the client can open Chat, Drop Files (feedme),
  allow screen viewing, pause, or quit.
- All pop-out windows share the same navy/pale palette, rounded corners,
  and soft shadows as the agent console.

Backend wiring (Firebase chat/command polling, file upload, vision stream)
uses the production logic from Magnet Client.pyw, adapted to drive the v2
flyout, glyph, chat, and drop windows.
"""

import importlib.machinery
import math
import sys
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QPainter, QBrush, QPen, QIcon, QCursor, QAction, QPainterPath, QColor
from PySide6.QtWidgets import (
    QApplication, QWidget, QSystemTrayIcon, QMenu,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QFrame, QTextEdit, QScrollArea, QListWidget, QSizePolicy,
    QGraphicsDropShadowEffect,
)

from magnet_v2_glyph import Theme, GlyphRenderer, _is_dark_mode, _css_color
from magnet_v2_theme import apply_global_styles, apply_shadow


# ------------------------------------------------------------------
# Chat bubble
# ------------------------------------------------------------------
class ChatBubble(QFrame):
    def __init__(self, text: str, is_atlas: bool, theme: Theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("background: transparent;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)
        if is_atlas:
            layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        else:
            layout.setAlignment(Qt.AlignmentFlag.AlignRight)

        sender = QLabel("Atlas" if is_atlas else "You")
        sender.setStyleSheet(
            f"color: {_css_color(theme.muted)}; font-size: 10px; background: transparent;"
        )
        bubble = QLabel(text)
        bubble.setWordWrap(True)
        bubble.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bubble.setStyleSheet(self._bubble_stylesheet(is_atlas))
        bubble.setMaximumWidth(260)

        align = Qt.AlignmentFlag.AlignLeft if is_atlas else Qt.AlignmentFlag.AlignRight
        layout.addWidget(sender, alignment=align)
        layout.addWidget(bubble, alignment=align)

    def _bubble_stylesheet(self, is_atlas: bool) -> str:
        t = self.theme
        if is_atlas:
            bg = _css_color(t.surface)
            fg = _css_color(t.text)
        else:
            bg = _css_color(t.accent)
            fg = _css_color(t.on_accent)
        return (
            f"QLabel {{ background: {bg}; color: {fg}; border-radius: 14px; "
            f"padding: 10px 12px; font-size: 13px; }}"
        )


# ------------------------------------------------------------------
# Chat pop-out window
# ------------------------------------------------------------------
class ChatWindow(QWidget):
    message_sent = Signal(str)

    def __init__(self, theme: Theme, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.theme = theme
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(360, 520)

        container = QFrame(self)
        container.setGeometry(8, 8, 344, 504)
        container.setStyleSheet(
            f"QFrame {{ background: {_css_color(theme.panel)}; border-radius: 18px; }}"
        )
        apply_shadow(container, theme, blur=22, offset=(0, 6), alpha=50)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # Header
        header = QWidget()
        header.setStyleSheet("background: transparent;")
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(0, 0, 0, 0)
        hlay.setSpacing(8)
        title = QLabel("Atlas")
        title.setStyleSheet(
            f"color: {_css_color(theme.text)}; font-size: 16px; font-weight: 600; background: transparent;"
        )
        hlay.addWidget(title)
        hlay.addStretch()
        close_btn = QPushButton("×")
        close_btn.setFixedSize(24, 24)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {_css_color(theme.muted)}; "
            f"border-radius: 12px; font-size: 16px; }}"
            f"QPushButton:hover {{ background: {_css_color(theme.error)}; color: white; }}"
        )
        close_btn.clicked.connect(self.hide)
        hlay.addWidget(close_btn)
        layout.addWidget(header)

        # Messages
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("border: none; background: transparent;")
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.messages = QWidget()
        self.messages_layout = QVBoxLayout(self.messages)
        self.messages_layout.setContentsMargins(4, 4, 4, 4)
        self.messages_layout.setSpacing(8)
        self.messages_layout.addStretch()
        self.messages.setStyleSheet("background: transparent;")
        self.scroll.setWidget(self.messages)
        layout.addWidget(self.scroll, 1)

        # Input
        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Message Atlas...")
        self.input.returnPressed.connect(self._send)
        send_btn = QPushButton(">")
        send_btn.setFixedSize(34, 34)
        send_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        send_btn.setStyleSheet(
            f"QPushButton {{ background: {_css_color(theme.accent)}; color: {_css_color(theme.on_accent)}; "
            f"border-radius: 17px; font-size: 13px; font-weight: 700; padding: 0; }}"
            f"QPushButton:hover {{ background: {_css_color(theme.accent_hover)}; }}"
        )
        send_btn.clicked.connect(self._send)
        input_row.addWidget(self.input, 1)
        input_row.addWidget(send_btn)
        layout.addLayout(input_row)

    def _send(self):
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self.message_sent.emit(text)

    def add_message(self, sender_or_text, text=None, is_atlas: bool = True):
        if text is None:
            text = sender_or_text
            sender = "Atlas" if is_atlas else "You"
        else:
            sender = sender_or_text
        bubble = ChatBubble(text, is_atlas, self.theme, self.messages)
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, bubble)
        QTimer.singleShot(10, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        vbar = self.scroll.verticalScrollBar()
        vbar.setValue(vbar.maximum())


# ------------------------------------------------------------------
# Feed-me drop window
# ------------------------------------------------------------------
class DropWindow(QWidget):
    file_dropped = Signal(str)

    def __init__(self, theme: Theme, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.theme = theme
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAcceptDrops(True)
        self.setFixedSize(420, 360)

        self.container = QFrame(self)
        self.container.setGeometry(8, 8, 404, 344)
        self.container.setStyleSheet(
            f"QFrame {{ background: {_css_color(theme.panel)}; border-radius: 18px; }}"
        )
        apply_shadow(self.container, theme, blur=24, offset=(0, 8), alpha=55)

        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header_lbl = QLabel("Send Files")
        header_lbl.setStyleSheet(
            f"color: {_css_color(theme.text)}; font-size: 16px; font-weight: 600; background: transparent;"
        )
        header.addWidget(header_lbl)
        header.addStretch()
        close_btn = QPushButton("×")
        close_btn.setFixedSize(24, 24)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {_css_color(theme.muted)}; "
            f"border-radius: 12px; font-size: 16px; }}"
            f"QPushButton:hover {{ background: {_css_color(theme.error)}; color: white; }}"
        )
        close_btn.clicked.connect(self.hide)
        header.addWidget(close_btn)
        layout.addLayout(header)

        self.drop_target = QTextEdit()
        self.drop_target.setReadOnly(True)
        self.drop_target.setAcceptDrops(False)
        self.drop_target.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_target.setText("Drop files here")
        self.drop_target.setStyleSheet(
            f"QTextEdit {{ background: {_css_color(theme.surface)}; color: {_css_color(theme.muted)}; "
            f"border-radius: 14px; padding: 12px; font-size: 15px; }}"
        )
        self.drop_target.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.drop_target, 1)

        self.file_list = QListWidget()
        self.file_list.setVisible(False)
        self.file_list.setStyleSheet(
            f"QListWidget {{ background: {_css_color(theme.surface)}; color: {_css_color(theme.text)}; "
            f"border-radius: 10px; padding: 6px; }}"
        )
        layout.addWidget(self.file_list, 1)

        done_btn = QPushButton("Done")
        done_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        done_btn.setObjectName("primary")
        done_btn.clicked.connect(self.hide)
        layout.addWidget(done_btn)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.drop_target.setText("Release to upload")
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.drop_target.setText("Drop files here")

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
        files = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile()]
        if not files:
            return
        self.drop_target.setVisible(False)
        self.file_list.setVisible(True)
        for f in files:
            self.file_list.addItem(Path(f).name)
            self.file_dropped.emit(f)

    def showEvent(self, event):
        super().showEvent(event)
        self.drop_target.setVisible(True)
        self.drop_target.setText("Drop files here")
        self.file_list.setVisible(False)
        self.file_list.clear()


# ------------------------------------------------------------------
# Main flyout panel
# ------------------------------------------------------------------
class FlyoutPanel(QWidget):
    chat_requested = Signal()
    drop_requested = Signal()
    viewing_requested = Signal()
    pause_requested = Signal()
    quit_requested = Signal()

    def __init__(self, theme: Theme, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.theme = theme
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self._corner_radius = 18
        self.setFixedWidth(260)

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # Header: glyph + title + status
        header = QVBoxLayout()
        header.setSpacing(6)
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._glyph = GlyphRenderer(size=56)
        self._glyph.set_state("idle")
        self._glyph_lbl = QLabel()
        self._glyph_lbl.setFixedSize(56, 56)
        self._update_glyph_pixmap()
        header.addWidget(self._glyph_lbl, alignment=Qt.AlignmentFlag.AlignCenter)

        self._title = QLabel("Magnet Client")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setStyleSheet(
            f"color: {_css_color(self.theme.text)}; font-size: 17px; font-weight: 600; background: transparent;"
        )
        header.addWidget(self._title, alignment=Qt.AlignmentFlag.AlignCenter)

        # Status dot + text
        status_layout = QHBoxLayout()
        status_layout.setSpacing(6)
        status_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet(
            f"color: {_css_color(self.theme.accent)}; font-size: 10px; background: transparent;"
        )
        self._status_text = QLabel("Connected to Atlas")
        self._status_text.setStyleSheet(
            f"color: {_css_color(self.theme.muted)}; font-size: 11px; background: transparent;"
        )
        status_layout.addWidget(self._status_dot)
        status_layout.addWidget(self._status_text, alignment=Qt.AlignmentFlag.AlignVCenter)
        header.addLayout(status_layout)

        layout.addLayout(header)

        # Action buttons
        self._buttons = []
        actions = [
            ("Open Chat", self._open_chat),
            ("Send Files", self._open_drop),
            ("Share Screen", self._toggle_viewing),
            ("Pause", self._toggle_pause),
            ("Quit", self._quit),
        ]
        for label, cb in actions:
            btn = QPushButton(label)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setStyleSheet(self._button_stylesheet())
            btn.clicked.connect(cb)
            self._buttons.append(btn)
            layout.addWidget(btn)

        layout.addStretch()

    def _button_stylesheet(self) -> str:
        t = self.theme
        bg = _css_color(t.surface)
        hover = _css_color(t.accent)
        text = _css_color(t.text)
        return (
            f"QPushButton {{ background: {bg}; color: {text}; border-radius: 10px; "
            f"padding: 10px 14px; font-size: 13px; font-weight: 600; text-align: left; }}"
            f"QPushButton:hover {{ background: {hover}; }}"
        )

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), self._corner_radius, self._corner_radius)
        painter.fillPath(path, QBrush(self.theme.panel))

        pen = QPen(self.theme.border)
        pen.setWidth(1)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

        highlight = QPainterPath()
        highlight.addRoundedRect(1, 1, self.width() - 2, self.height() / 2.5,
                                 self._corner_radius - 1, self._corner_radius - 1)
        painter.setClipPath(highlight)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(255, 255, 255, 10 if self.theme.dark else 18)))
        painter.drawPath(highlight)
        painter.end()

    def _update_glyph_pixmap(self):
        self._glyph_lbl.setPixmap(
            self._glyph.pixmap(self.theme, color=self.theme.glyph).scaled(
                56, 56, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
        )

    def set_status(self, state: str, connected_to: str = "Atlas"):
        labels = {
            "idle": f"Idle — {connected_to}",
            "connected": f"Connected — {connected_to}",
            "viewing": f"Sharing screen — {connected_to}",
            "processing": f"Working — {connected_to}",
            "file_transfer": f"Sending files — {connected_to}",
            "disconnected": "Disconnected",
            "paused": f"Paused — {connected_to}",
        }
        self._status_text.setText(labels.get(state, state.capitalize()))
        dot_color = self.theme.muted if state in ("disconnected", "paused") else self.theme.accent
        self._status_dot.setStyleSheet(
            f"color: {_css_color(dot_color)}; font-size: 10px; background: transparent;"
        )
        self._glyph.set_state(state)
        self._update_glyph_pixmap()

    def set_status_text(self, text: str):
        self._status_text.setText(text)

    def update_glyph(self):
        self._glyph.update(0.1)
        self._update_glyph_pixmap()

    def apply_theme(self, theme: Theme):
        self.theme = theme
        self._title.setStyleSheet(
            f"color: {_css_color(theme.text)}; font-size: 17px; font-weight: 600; background: transparent;"
        )
        self._status_text.setStyleSheet(
            f"color: {_css_color(theme.muted)}; font-size: 11px; background: transparent;"
        )
        for btn in self._buttons:
            btn.setStyleSheet(self._button_stylesheet())
        self.update()

    def _open_chat(self):
        self._emit("chat_requested")

    def _open_drop(self):
        self._emit("drop_requested")

    def _toggle_viewing(self):
        self._emit("viewing_requested")

    def _toggle_pause(self):
        self._emit("pause_requested")

    def _quit(self):
        self._emit("quit_requested")

    def _emit(self, signal: str):
        getattr(self, signal).emit()


# ------------------------------------------------------------------
# Glyph stub that bridges the legacy backend orb to the v2 flyout glyph
# ------------------------------------------------------------------
class GlyphStub(QObject):
    clicked = Signal()
    state_changed = Signal(str)

    def __init__(self, owner: "ClientApp"):
        super().__init__(owner)
        self._owner = owner
        self._state = "idle"
        self._restore_timer = QTimer(self)
        self._restore_timer.setSingleShot(True)
        self._restore_timer.timeout.connect(self._do_restore)

    def _map_state(self, state: str) -> str:
        mapping = {
            "command": "processing",
            "terminal": "viewing",
            "alert": "file_transfer",
            "feedme": "file_transfer",
            "opening": "connected",
            "vision": "viewing",
        }
        return mapping.get(state, state)

    def _set_v2_state(self, state: str):
        mapped = self._map_state(state)
        self._owner.set_state(mapped)

    def set_state(self, state: str):
        self._state = state
        self._set_v2_state(state)
        self.state_changed.emit(state)

    def set_paused(self, paused: bool):
        if paused:
            self._set_v2_state("paused")
        else:
            self._set_v2_state(self._state if self._state not in ("paused",) else "connected")

    def _do_restore(self):
        self._set_v2_state(self._state)

    def _flash_state(self, state: str, ms: int):
        self._set_v2_state(state)
        self._restore_timer.start(ms)

    def flash_alert(self):
        self._flash_state("file_transfer", 900)

    def flash_command(self):
        self._flash_state("processing", 900)

    def flash_terminal(self):
        self._flash_state("viewing", 900)

    def start_portal_opening(self):
        self._flash_state("connected", 1200)


# ------------------------------------------------------------------
# Application
# ------------------------------------------------------------------
class ClientApp(QApplication):
    def __init__(self, argv):
        super().__init__(argv)
        self.setQuitOnLastWindowClosed(False)

        light = "--light" in argv
        dark = "--dark" in argv
        if light:
            self.theme = Theme(False)
        elif dark:
            self.theme = Theme(True)
        else:
            self.theme = Theme(_is_dark_mode(self))

        apply_global_styles(self, self.theme)

        # Tray glyph renderers at all OS chrome sizes
        self._glyphs = {size: GlyphRenderer(size=size) for size in (16, 18, 24, 32)}
        for g in self._glyphs.values():
            g.set_state("idle")

        self.flyout = FlyoutPanel(self.theme)
        self.flyout.set_status("connected")

        # Wire flyout buttons to actions
        self.flyout.chat_requested.connect(self._open_chat)
        self.flyout.drop_requested.connect(self._open_drop)
        self.flyout.viewing_requested.connect(self._toggle_viewing)
        self.flyout.pause_requested.connect(self._toggle_pause)
        self.flyout.quit_requested.connect(self._do_quit)

        self.chat = ChatWindow(self.theme)
        self.chat.message_sent.connect(self._on_chat_sent)

        self.drop = DropWindow(self.theme)
        self.drop.file_dropped.connect(self._on_file_dropped)

        self._paused = False
        self._viewing = False

        self.tray = QSystemTrayIcon(self)
        self._setup_context_menu()
        self.tray.activated.connect(self._on_tray_activated)
        self._update_tray_icon()
        self.tray.show()

        self._animation_timer = QTimer(self)
        self._animation_timer.timeout.connect(self._animate_glyph)
        self._animation_timer.start(100)

        # Introduce the flyout briefly on first launch
        QTimer.singleShot(300, self._show_flyout)

    def _setup_context_menu(self):
        menu = QMenu()
        show_action = QAction("Show Magnet Client", self)
        show_action.triggered.connect(self._show_flyout)
        menu.addAction(show_action)
        chat_action = QAction("Open Chat", self)
        chat_action.triggered.connect(self._open_chat)
        menu.addAction(chat_action)
        drop_action = QAction("Send Files", self)
        drop_action.triggered.connect(self._open_drop)
        menu.addAction(drop_action)
        menu.addSeparator()
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
        self.flyout.update_glyph()

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._toggle_flyout()

    def _show_flyout(self):
        if self.flyout.isVisible():
            return
        self.flyout.adjustSize()
        tray_geo = self.tray.geometry()
        screen = self.primaryScreen().availableGeometry()
        if tray_geo.isValid() and tray_geo.width() > 0:
            x = tray_geo.center().x() - self.flyout.width() // 2
            y = tray_geo.bottom() + 8 if sys.platform == "darwin" else tray_geo.top() - self.flyout.height() - 8
        else:
            x = screen.center().x() - self.flyout.width() // 2
            y = 120
        x = max(screen.left() + 8, min(x, screen.right() - self.flyout.width() - 8))
        y = max(screen.top() + 8, min(y, screen.bottom() - self.flyout.height() - 8))
        self.flyout.move(x, y)
        self.flyout.show()
        self.flyout.raise_()
        self.flyout.activateWindow()

    def _hide_flyout(self):
        self.flyout.hide()

    def _toggle_flyout(self):
        if self.flyout.isVisible():
            self._hide_flyout()
        else:
            self._show_flyout()

    def _open_chat(self):
        self._hide_flyout()
        self.chat.add_message("Atlas is connected and ready.", is_atlas=True)
        self._position_popout(self.chat)
        self.chat.show()
        self.chat.raise_()

    def _on_chat_sent(self, text: str):
        # Placeholder: echo Atlas reply and set state to processing briefly
        self.flyout.set_status("processing")
        QTimer.singleShot(1200, lambda: self.flyout.set_status("connected"))
        QTimer.singleShot(800, lambda: self.chat.add_message(f"Received: {text}", is_atlas=True))

    def _open_drop(self):
        self._hide_flyout()
        self.flyout.set_status("file_transfer")
        self._position_popout(self.drop)
        self.drop.show()
        self.drop.raise_()

    def _on_file_dropped(self, path: str):
        # Placeholder: real implementation will upload to Firebase
        self.chat.add_message(f"File queued: {Path(path).name}", is_atlas=True)

    def _toggle_viewing(self):
        self._hide_flyout()
        self._viewing = not self._viewing
        state = "viewing" if self._viewing else "connected"
        self.flyout.set_status(state)
        self.chat.add_message(
            "Atlas can now see your screen." if self._viewing else "Screen sharing stopped.",
            is_atlas=True,
        )

    def _toggle_pause(self):
        self._paused = not self._paused
        state = "paused" if self._paused else "connected"
        self.flyout.set_status(state)
        btn = self.flyout._buttons[3]
        btn.setText("Resume" if self._paused else "Pause")

    def _do_quit(self):
        self.quit()

    def _position_popout(self, window: QWidget):
        screen = self.primaryScreen().availableGeometry()
        tray_geo = self.tray.geometry()
        if tray_geo.isValid() and tray_geo.width() > 0:
            x = tray_geo.center().x() - window.width() // 2
            y = tray_geo.bottom() + 14 if sys.platform == "darwin" else tray_geo.top() - window.height() - 14
        else:
            x = screen.center().x() - window.width() // 2
            y = 120
        x = max(screen.left() + 8, min(x, screen.right() - window.width() - 8))
        y = max(screen.top() + 8, min(y, screen.bottom() - window.height() - 8))
        window.move(x, y)

    def set_state(self, state: str):
        for g in self._glyphs.values():
            g.set_state(state)
        self.flyout.set_status(state)
        self._update_tray_icon()


def main():
    app = ClientApp(sys.argv)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
