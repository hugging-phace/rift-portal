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
import platform
import secrets
import shutil
import smtplib
import subprocess
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from PySide6.QtCore import (
    Qt, QPoint, QPointF, QTimer, Signal, QUrl, QProcess, QSettings,
    QPropertyAnimation, QSequentialAnimationGroup, QParallelAnimationGroup,
    QEasingCurve,
)
from PySide6.QtGui import (
    QColor, QPainter, QPainterPath, QBrush, QPen, QCursor, QMouseEvent,
    QDesktopServices, QPalette,
)
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedWidget, QFrame, QSizePolicy, QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect, QLineEdit, QTextEdit, QListWidget, QListWidgetItem,
    QMessageBox, QComboBox, QCheckBox,
    QTreeWidget, QTreeWidgetItem, QSplitter, QFileDialog, QMenu,
    QHeaderView,
)


from magnet_v2_glyph import Theme, GlyphRenderer, _is_dark_mode, _css_color
from magnet_v2_theme import apply_global_styles, apply_shadow, animate_shadow


def _make_agent_theme(dark: bool) -> Theme:
    """Return an agent theme with the modern MagnetOS v2 palette."""
    t = Theme(dark)
    if not dark:
        t.bg = QColor(232, 240, 250)
    return t


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _fade_show(widget: QWidget, duration: int = 260):
    """Fade a top-level widget in from transparent using an OutCubic easing."""
    widget.setWindowOpacity(0.0)
    widget._show_anim = QPropertyAnimation(widget, b"windowOpacity")
    widget._show_anim.setDuration(duration)
    widget._show_anim.setStartValue(0.0)
    widget._show_anim.setEndValue(1.0)
    widget._show_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    widget._show_anim.start()


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
    def __init__(self, title: str, body: str, theme: Theme, parent=None, callback=None):
        super().__init__(parent)
        self.theme = theme
        self.callback = callback
        self.setStyleSheet(
            f"background: {_css_color(theme.panel)};  border-radius: 14px;"
        )
        if callback:
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
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

        if callback:
            open_lbl = QLabel("Open →")
            open_lbl.setStyleSheet(
                f"color: {_css_color(theme.accent)}; font-size: 11px; font-weight: 600;"
            )
            layout.addWidget(open_lbl)

        apply_shadow(self, theme)

    def enterEvent(self, event):
        animate_shadow(self, self.theme, hover=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        animate_shadow(self, self.theme, hover=False)
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        if self.callback:
            self.callback()
        super().mousePressEvent(event)


class FormCard(QFrame):
    """A rounded panel with a title and a vertical form area."""

    def __init__(self, title: str, theme: Theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setStyleSheet(
            f"background: {_css_color(theme.panel)};  border-radius: 14px;"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {_css_color(theme.text)}; font-size: 14px; font-weight: 600;"
        )
        layout.addWidget(title_lbl)

        self._body = QVBoxLayout()
        self._body.setSpacing(10)
        layout.addLayout(self._body, 1)

        apply_shadow(self, theme)

    def enterEvent(self, event):
        animate_shadow(self, self.theme, hover=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        animate_shadow(self, self.theme, hover=False)
        super().leaveEvent(event)

    def add_row(self, widget):
        self._body.addWidget(widget)

    def add_layout(self, layout):
        self._body.addLayout(layout)


class PageWidget(QFrame):
    def __init__(self, title: str, theme: Theme, bg: QColor = None, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        bg_color = bg if bg is not None else theme.bg
        self._bg = QFrame(self)
        self._bg.setObjectName("pageBg")
        self._bg.setFrameShape(QFrame.Shape.NoFrame)
        self._bg.setStyleSheet(
            f"background-color: {_css_color(bg_color)};  border-radius: 18px;"
        )
        self._bg.setGeometry(self.rect())
        self._bg.lower()
        self.setAutoFillBackground(False)

        apply_shadow(self._bg, theme, blur=22, offset=(0, 6), alpha=50)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 24)
        layout.setSpacing(14)

        title_color = theme.text if bg_color.lightness() < 128 else theme.panel
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"color: {_css_color(title_color)}; font-size: 24px; font-weight: 600;"
        )
        layout.addWidget(title_lbl)

        self._body = QVBoxLayout()
        self._body.setSpacing(12)
        layout.addLayout(self._body, 1)

    def add_card(self, title: str, body: str, callback=None):
        card = Card(title, body, self.theme, self, callback=callback)
        card.setMinimumHeight(120)
        card.setMaximumHeight(140)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._body.addWidget(card, 0)

    def fade_in(self, duration=220):
        # Page cross-fade disabled: shadows and opacity effects cannot be nested.
        pass

    def fade_out(self, duration=160):
        pass

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_bg"):
            self._bg.setGeometry(self.rect())


class SidebarPanel(QFrame):
    """A detached, floating sidebar panel with rounded corners and a soft shadow."""

    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.setFixedWidth(260)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._apply_theme(theme)

        apply_shadow(self, theme, blur=26, offset=(6, 4), alpha=55)

    def _apply_theme(self, theme: Theme):
        self.setStyleSheet(
            f"background: {_css_color(theme.panel)}; "
            f" "
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
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        self._buttons = []
        for state in GlyphRenderer.STATES:
            btn = QPushButton(state.replace("_", " ").title())
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(lambda checked=False, s=state: self.state_changed.emit(s))
            self._buttons.append(btn)
            layout.addWidget(btn)

    def apply_theme(self, theme: Theme):
        self.theme = theme
        self.setStyleSheet(f"background: {_css_color(theme.bg)};")


# ------------------------------------------------------------------
# Agent window
# ------------------------------------------------------------------
class AgentWindow(QWidget):
    def __init__(self, theme: Theme, glyph: GlyphRenderer, settings: QSettings, initial_view: int = 0, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.glyph = glyph
        self.settings = settings
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

        # Title bar — thin; app name lives in the sidebar
        title_bar = QWidget()
        title_bar.setFixedHeight(32)
        title_bar.setStyleSheet(
            f"background: {_css_color(theme.surface)}; "
            f"border-bottom: 1px solid {_css_color(theme.border)};"
        )
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(12, 0, 12, 0)
        title_layout.setSpacing(6)

        title_layout.addStretch()

        for symbol, cb in (("−", self.showMinimized), ("□", self._toggle_max_restore), ("×", self.close)):
            btn = QPushButton(symbol)
            btn.setFixedSize(24, 24)
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {_css_color(theme.muted)}; "
                f"border-radius: 6px;  font-size: 13px; }}"
                f"QPushButton:hover {{ background: {_css_color(theme.hover)}; color: {_css_color(theme.text)}; }}"
            )
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(cb)
            title_layout.addWidget(btn)

        main_layout.addWidget(title_bar)

        # Body
        body = QHBoxLayout()
        body.setContentsMargins(20, 16, 20, 20)
        body.setSpacing(20)

        # Sidebar (detached floating panel)
        sidebar = SidebarPanel(self.theme)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(16, 16, 16, 16)
        sidebar_layout.setSpacing(12)

        # Connection status + app name
        status_row = QHBoxLayout()
        status_row.setSpacing(6)
        title_lbl = QLabel("Magnet Agent")
        title_lbl.setStyleSheet(
            f"color: {_css_color(theme.text)}; font-size: 12px; font-weight: 600;"
        )
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {_css_color(theme.accent)}; font-size: 10px;")
        status_text = QLabel("Connected")
        status_text.setStyleSheet(f"color: {_css_color(theme.muted)}; font-size: 12px;")
        status_row.addWidget(title_lbl)
        status_row.addWidget(dot)
        status_row.addWidget(status_text, alignment=Qt.AlignmentFlag.AlignVCenter)
        status_row.addStretch()
        sidebar_layout.addLayout(status_row)

        sidebar_layout.addSpacing(24)

        # Nav
        self._nav_btns = []
        self._stack = QStackedWidget()

        # Container for indented active-session sub-buttons under Sessions
        self._sessions_sub_container = QWidget()
        self._sessions_sub_layout = QVBoxLayout(self._sessions_sub_container)
        self._sessions_sub_layout.setContentsMargins(0, 0, 0, 0)
        self._sessions_sub_layout.setSpacing(4)
        self._sessions_sub_container.setStyleSheet("background: transparent;")
        self._sessions_sub_container.hide()
        self._session_sub_btn = None

        sessions_page = self._build_sessions_page()
        deploy_page = self._build_deploy_page()
        commands_page = self._build_commands_page()
        terminal_page = self._build_terminal_page()
        settings_page = self._build_settings_page()
        active_page = self._build_active_session_page()
        for p in (sessions_page, deploy_page, commands_page, terminal_page, settings_page, active_page):
            self._stack.addWidget(p)

        main_nav = ["Sessions", "Deploy", "Commands", "Terminal", "Settings"]
        for idx, label in enumerate(main_nav):
            btn = QPushButton(label)
            btn.setStyleSheet(self._nav_stylesheet(idx == initial_view))
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setCheckable(True)
            btn.setChecked(idx == initial_view)
            btn.clicked.connect(lambda checked, i=idx: self._switch_view(i))
            self._nav_btns.append(btn)
            sidebar_layout.addWidget(btn)
            if label == "Sessions":
                sidebar_layout.addWidget(self._sessions_sub_container)

        if initial_view == 5:
            self._open_active_session("Atlas Workstation")
        else:
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
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        self._stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        content_layout.addWidget(self._stack, 1)
        body.addWidget(content, 1)

        main_layout.addLayout(body, 1)

    def _nav_stylesheet(self, active: bool) -> str:
        t = self.theme
        bg = _css_color(t.accent if active else t.panel)
        fg = _css_color(t.on_accent if active else t.text)
        border = _css_color(t.accent if active else t.border)
        hover = _css_color(t.hover)
        return (
            f"QPushButton {{ background: {bg}; color: {fg};  "
            f"border-radius: 10px; padding: 10px 14px; font-size: 13px; font-weight: 600; text-align: left; }}"
            f"QPushButton:hover {{ background: {hover}; color: {_css_color(t.text)};  }}"
        )

    def _build_sessions_page(self):
        page = PageWidget("Active Sessions", self.theme)
        page.add_card(
            "Atlas Workstation",
            "Online — Windows 11\nLast seen: just now",
            callback=lambda: self._open_active_session("Atlas Workstation"),
        )
        page.add_card("Studio Mac", "Online — macOS\nLast seen: 2m ago")
        page._body.addStretch(1)
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

    def _build_deploy_page(self):
        page = PageWidget("Deploy Magnet Client", self.theme)

        form = FormCard("Customer invite", self.theme, page)
        t = self.theme
        label_style = f"color: {_css_color(t.muted)}; font-size: 12px;"
        input_style = (
            f"QLineEdit, QTextEdit, QComboBox {{ background: {_css_color(t.hover)}; "
            f"color: {_css_color(t.text)};  border-radius: 8px; padding: 8px; font-size: 13px; }}"
            f"QComboBox::drop-down {{  }}"
            f"QComboBox QAbstractItemView {{ background: {_css_color(t.panel)}; "
            f"color: {_css_color(t.text)}; selection-background-color: {_css_color(t.accent)}; }}"
        )

        email_lbl = QLabel("Customer email")
        email_lbl.setStyleSheet(label_style)
        email_input = QLineEdit()
        email_input.setPlaceholderText("support@customer.com")
        email_input.setStyleSheet(input_style)
        form.add_row(email_lbl)
        form.add_row(email_input)

        os_lbl = QLabel("Platform")
        os_lbl.setStyleSheet(label_style)
        os_combo = QComboBox()
        os_combo.addItems(["Windows", "macOS", "Linux"])
        os_combo.setStyleSheet(input_style)
        form.add_row(os_lbl)
        form.add_row(os_combo)

        note_lbl = QLabel("Personal note (optional)")
        note_lbl.setStyleSheet(label_style)
        note_input = QTextEdit()
        note_input.setPlaceholderText("Hi, click the link below to start the remote session...")
        note_input.setMaximumHeight(80)
        note_input.setStyleSheet(input_style)
        form.add_row(note_lbl)
        form.add_row(note_input)

        preview_lbl = QLabel("Email preview")
        preview_lbl.setStyleSheet(label_style)
        form.add_row(preview_lbl)
        preview = QTextEdit()
        preview.setReadOnly(True)
        preview.setStyleSheet(input_style)
        preview.setMinimumHeight(140)
        form.add_row(preview)

        send_real = QCheckBox("Send real email (requires SMTP in Settings)")
        send_real.setChecked(False)
        send_real.setStyleSheet(f"color: {_css_color(t.muted)}; font-size: 12px;")
        form.add_row(send_real)

        send_btn = QPushButton("Send invite")
        send_btn.setStyleSheet(
            f"QPushButton {{ background: {_css_color(t.accent)}; color: white;  "
            f"border-radius: 8px; padding: 10px 18px; font-size: 13px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {_css_color(t.hover)}; }}"
        )
        send_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        form.add_row(send_btn)

        page._body.addWidget(form)
        page._body.addStretch(1)

        # Keep references used by preview / send logic.
        self._deploy_email = email_input
        self._deploy_os = os_combo
        self._deploy_note = note_input
        self._deploy_preview = preview
        self._deploy_send_real = send_real

        email_input.textChanged.connect(self._update_invite_preview)
        note_input.textChanged.connect(self._update_invite_preview)
        os_combo.currentTextChanged.connect(self._update_invite_preview)
        send_btn.clicked.connect(self._send_invite)

        self._update_invite_preview()
        return page

    def _build_settings_page(self):
        page = PageWidget("Settings", self.theme)

        # SMTP credentials
        smtp_card = FormCard("Email sending (SMTP)", self.theme, page)
        t = self.theme
        label_style = f"color: {_css_color(t.muted)}; font-size: 12px;"
        input_style = (
            f"QLineEdit {{ background: {_css_color(t.hover)}; "
            f"color: {_css_color(t.text)};  border-radius: 8px; padding: 8px; font-size: 13px; }}"
        )

        host_lbl = QLabel("SMTP host")
        host_lbl.setStyleSheet(label_style)
        host_input = QLineEdit()
        host_input.setPlaceholderText("smtp.gmail.com")
        host_input.setStyleSheet(input_style)
        smtp_card.add_row(host_lbl)
        smtp_card.add_row(host_input)

        port_lbl = QLabel("SMTP port")
        port_lbl.setStyleSheet(label_style)
        port_input = QLineEdit()
        port_input.setPlaceholderText("587")
        port_input.setStyleSheet(input_style)
        smtp_card.add_row(port_lbl)
        smtp_card.add_row(port_input)

        user_lbl = QLabel("Email address / username")
        user_lbl.setStyleSheet(label_style)
        user_input = QLineEdit()
        user_input.setPlaceholderText("agent@company.com")
        user_input.setStyleSheet(input_style)
        smtp_card.add_row(user_lbl)
        smtp_card.add_row(user_input)

        pass_lbl = QLabel("App password")
        pass_lbl.setStyleSheet(label_style)
        pass_input = QLineEdit()
        pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        pass_input.setPlaceholderText("Stored locally in QSettings for this prototype")
        pass_input.setStyleSheet(input_style)
        smtp_card.add_row(pass_lbl)
        smtp_card.add_row(pass_input)

        save_status = QLabel("")
        save_status.setStyleSheet(f"color: {_css_color(t.accent)}; font-size: 12px;")
        smtp_card.add_row(save_status)

        save_btn = QPushButton("Save SMTP credentials")
        save_btn.setStyleSheet(
            f"QPushButton {{ background: {_css_color(t.accent)}; color: white;  "
            f"border-radius: 8px; padding: 10px 18px; font-size: 13px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {_css_color(t.hover)}; }}"
        )
        save_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        smtp_card.add_row(save_btn)

        save_btn.clicked.connect(
            lambda: self._save_smtp_settings(
                host_input.text(), port_input.text(), user_input.text(), pass_input.text(), save_status
            )
        )

        # Load saved values
        smtp = self._smtp_from_settings()
        host_input.setText(smtp.get("host", ""))
        port_input.setText(str(smtp.get("port", "")) if smtp.get("port") else "")
        user_input.setText(smtp.get("user", ""))
        pass_input.setText(smtp.get("password", ""))

        page._body.addWidget(smtp_card)

        # OAuth placeholders
        oauth_card = FormCard("Sign-in providers", self.theme, page)
        oauth_note = QLabel("OAuth sign-in lets each agent use their own email without managing SMTP credentials. These are placeholders while compiled installers are built.")
        oauth_note.setWordWrap(True)
        oauth_note.setStyleSheet(f"color: {_css_color(t.muted)}; font-size: 12px;")
        oauth_card.add_row(oauth_note)

        for provider, color in (
            ("Sign in with Google", "#4285F4"),
            ("Sign in with Apple", "#000000"),
            ("Sign in with Microsoft", "#2F2F2F"),
        ):
            btn = QPushButton(provider)
            btn.setStyleSheet(
                f"QPushButton {{ background: {color}; color: white;  "
                f"border-radius: 8px; padding: 10px 18px; font-size: 13px; font-weight: 600; }}"
                f"QPushButton:hover {{ background: #555555; }}"
            )
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.clicked.connect(self._oauth_coming_soon)
            oauth_card.add_row(btn)

        page._body.addWidget(oauth_card)
        page._body.addStretch(1)
        return page

    def _smtp_from_settings(self) -> dict:
        return {
            "host": self.settings.value("smtp/host", "", type=str),
            "port": self.settings.value("smtp/port", "", type=str),
            "user": self.settings.value("smtp/user", "", type=str),
            "password": self.settings.value("smtp/password", "", type=str),
        }

    def _save_smtp_settings(self, host: str, port: str, user: str, password: str, status_lbl: QLabel):
        self.settings.setValue("smtp/host", host)
        self.settings.setValue("smtp/port", port)
        self.settings.setValue("smtp/user", user)
        self.settings.setValue("smtp/password", password)
        self.settings.sync()
        status_lbl.setText("Credentials saved locally.")
        QTimer.singleShot(2500, lambda: status_lbl.setText(""))

    def _oauth_coming_soon(self):
        QMessageBox.information(
            self,
            "Coming soon",
            "OAuth sign-in will be enabled once the Magnet Client is distributed as signed installers.",
        )

    def _update_invite_preview(self, _=None):
        if not hasattr(self, "_deploy_preview"):
            return
        email = self._deploy_email.text().strip() or "support@customer.com"
        platform = self._deploy_os.currentText()
        note = self._deploy_note.toPlainText().strip()
        code = secrets.token_hex(4).upper()
        link = f"https://magnet.example.com/download/{platform.lower().replace(' ', '-')}?code={code}"

        body = (
            f"Hi,\n\n"
            f"{note if note else 'You have been invited to a Magnet remote support session.'}\n\n"
            f"Platform: {platform}\n"
            f"Session code: {code}\n"
            f"Download: {link}\n\n"
            f"Run the Magnet Client and enter the session code to connect.\n\n"
            f"— Magnet Support"
        )
        self._deploy_preview.setPlainText(
            f"To: {email}\nSubject: Magnet remote support invitation\n\n{body}"
        )

    def _send_invite(self):
        email = self._deploy_email.text().strip()
        if not email or "@" not in email:
            QMessageBox.warning(self, "Invalid email", "Please enter a valid customer email address.")
            return

        if not self._deploy_send_real.isChecked():
            QMessageBox.information(
                self,
                "Invite preview",
                "This is a prototype. Check \"Send real email\" and configure SMTP in Settings to actually send invites.",
            )
            return

        smtp = self._smtp_from_settings()
        missing = [k for k in ("host", "port", "user", "password") if not smtp.get(k)]
        if missing:
            QMessageBox.warning(
                self,
                "SMTP not configured",
                "Please save your SMTP credentials in Settings before sending invites.",
            )
            self._switch_view(4)
            return

        try:
            port = int(smtp.get("port") or 587)
            with smtplib.SMTP(smtp["host"], port, timeout=10) as server:
                server.starttls()
                server.login(smtp["user"], smtp["password"])
                msg = MIMEMultipart()
                msg["From"] = smtp["user"]
                msg["To"] = email
                msg["Subject"] = "Magnet remote support invitation"
                msg.attach(MIMEText(self._deploy_preview.toPlainText(), "plain"))
                server.sendmail(smtp["user"], email, msg.as_string())
            QMessageBox.information(self, "Sent", f"Invite sent to {email}.")
        except Exception as e:
            QMessageBox.critical(self, "Send failed", f"Could not send invite:\n{e}")

    def _get_system_info(self) -> dict:
        """Return a readable system-info snapshot for the connected client."""
        info = {"OS": "Unknown", "RAM": "Unknown", "Disk": "Unknown"}
        try:
            info["OS"] = f"{platform.system()} {platform.release()} {platform.machine()}"
        except Exception:
            pass
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        parts = line.split()
                        kb = int(parts[1])
                        info["RAM"] = f"{kb / (1024 * 1024):.1f} GB"
                        break
        except Exception:
            pass
        try:
            total, used, free = shutil.disk_usage(os.path.expanduser("~"))
            info["Disk"] = f"{free // (2**30)} GB free / {total // (2**30)} GB total"
        except Exception:
            pass
        return info

    def _build_active_session_page(self):
        page = PageWidget("Atlas Workstation", self.theme, bg=self.theme.panel)

        quick_row = QHBoxLayout()
        quick_row.setSpacing(8)
        quick_row.setContentsMargins(0, 0, 0, 0)
        for label in ("Screenshot", "Feed", "Pause", "Pulse", "Vision", "Files", "Terminal"):
            btn = self._quick_action_button(label)
            btn.clicked.connect(lambda checked=False, a=label: self._on_quick_action(a))
            quick_row.addWidget(btn)
        quick_row.addStretch()
        page._body.addLayout(quick_row)

        # System info bar
        sys_info = self._get_system_info()
        info_bar = QFrame()
        info_bar.setStyleSheet(
            f"background: {_css_color(self.theme.panel)}; border-radius: 10px; padding: 4px;"
        )
        info_layout = QHBoxLayout(info_bar)
        info_layout.setContentsMargins(12, 8, 12, 8)
        info_layout.setSpacing(16)
        for key, value in sys_info.items():
            col = QVBoxLayout()
            col.setSpacing(2)
            lbl_key = QLabel(key)
            lbl_key.setStyleSheet(f"color: {_css_color(self.theme.muted)}; font-size: 10px; font-weight: 600;")
            lbl_val = QLabel(value)
            lbl_val.setStyleSheet(f"color: {_css_color(self.theme.text)}; font-size: 12px;")
            col.addWidget(lbl_key)
            col.addWidget(lbl_val)
            info_layout.addLayout(col)
        info_layout.addStretch()
        page._body.addWidget(info_bar)

        hbox = QHBoxLayout()
        hbox.setSpacing(0)
        hbox.setContentsMargins(0, 0, 0, 0)

        # Left column: file manager + manual commands button
        left_col = QFrame()
        left_col.setFrameShape(QFrame.Shape.NoFrame)
        left_col.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        left_col.setStyleSheet(f"background: {_css_color(self.theme.panel)}; border-radius: 12px;")
        left_layout = QVBoxLayout(left_col)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(12)

        self._file_manager = FileManagerWindow(self.theme, "~")
        self._file_manager.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        left_layout.addWidget(self._file_manager, 1)

        manual_btn = QPushButton("Run manual Magnet commands")
        manual_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        manual_btn.setStyleSheet(
            f"QPushButton {{ background: {_css_color(self.theme.hover)}; color: {_css_color(self.theme.text)}; "
            f" border-radius: 6px; padding: 8px 14px; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {_css_color(self.theme.accent)}; }}"
        )
        manual_btn.clicked.connect(self._open_command_window)
        left_layout.addWidget(manual_btn)

        chat_panel, self._chat_output, self._chat_line = self._make_session_panel(
            "Chat", "Type a message...", "Atlas: ready for instructions.", self._on_chat_send
        )
        chat_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        hbox.addWidget(left_col, 2)
        hbox.addWidget(chat_panel, 1)

        page._body.addLayout(hbox, 1)
        return page

    def _quick_action_button(self, label: str) -> QPushButton:
        t = self.theme
        btn = QPushButton(label)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setStyleSheet(
            f"QPushButton {{ background: {_css_color(t.hover)}; color: {_css_color(t.text)};  "
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
            f"color: {_css_color(self.theme.text)};  border-radius: 8px; "
            f"padding: 8px; }}"
        )
        layout.addWidget(output, 1)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        line = QLineEdit()
        line.setPlaceholderText(placeholder)
        line.setStyleSheet(
            f"QLineEdit {{ background: {_css_color(self.theme.hover)}; "
            f"color: {_css_color(self.theme.text)};  border-radius: 6px; "
            f"padding: 6px; }}"
        )
        btn = QPushButton("Send")
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setStyleSheet(
            f"QPushButton {{ background: {_css_color(self.theme.accent)}; "
            f"color: {_css_color(self.theme.text)};  border-radius: 6px; "
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

    def _session_sub_stylesheet(self, active: bool) -> str:
        t = self.theme
        bg = _css_color(t.accent if active else t.panel)
        fg = _css_color(t.on_accent if active else t.text)
        border = _css_color(t.accent if active else t.border)
        hover = _css_color(t.hover)
        return (
            f"QPushButton {{ background: {bg}; color: {fg};  "
            f"border-radius: 8px; padding: 8px 14px 8px 28px; font-size: 12px; font-weight: 600; text-align: left; }}"
            f"QPushButton:hover {{ background: {hover}; color: {_css_color(t.text)};  }}"
        )

    def _make_session_sub_button(self, name: str) -> QPushButton:
        btn = QPushButton(name)
        btn.setCheckable(True)
        btn.setStyleSheet(self._session_sub_stylesheet(False))
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.clicked.connect(lambda checked: self._switch_view(5))
        return btn

    def _open_active_session(self, name: str):
        if self._session_sub_btn is None:
            self._session_sub_btn = self._make_session_sub_button(name)
            self._sessions_sub_layout.addWidget(self._session_sub_btn)
            self._sessions_sub_container.show()
        self._switch_view(5)

    def _switch_view(self, index: int):
        current = self._stack.currentWidget()
        target = self._stack.widget(index)
        if current == target:
            self._update_nav(index)
            return
        if current is None:
            self._stack.setCurrentIndex(index)
            self._update_nav(index)
            if isinstance(target, PageWidget):
                target.fade_in()
            return
        # Smooth cross-fade between pages.
        current.fade_out()
        QTimer.singleShot(180, lambda idx=index: self._finish_switch(idx))

    def _finish_switch(self, index: int):
        self._stack.setCurrentIndex(index)
        self._update_nav(index)
        target = self._stack.widget(index)
        if isinstance(target, PageWidget):
            target.fade_in()

    def _update_nav(self, index: int):
        for i, btn in enumerate(self._nav_btns):
            active = i == index
            btn.setChecked(active)
            btn.setStyleSheet(self._nav_stylesheet(active))
        if self._session_sub_btn is not None:
            is_active = index == 5
            self._session_sub_btn.setChecked(is_active)
            self._session_sub_btn.setStyleSheet(self._session_sub_stylesheet(is_active))

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

    def showEvent(self, event):
        super().showEvent(event)
        self.setWindowOpacity(0.0)
        self._show_anim = QPropertyAnimation(self, b"windowOpacity")
        self._show_anim.setDuration(300)
        self._show_anim.setStartValue(0.0)
        self._show_anim.setEndValue(1.0)
        self._show_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._show_anim.start()

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
        self._cursor_pos = None
        self._cursor_current = QPointF()
        self._cursor_target = None
        self._cursor_glyph = GlyphRenderer(48)
        self._cursor_glyph.set_state("viewing")

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
            f" border-radius: 6px; padding: 6px 14px; font-size: 12px; }}"
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

        self._cursor_overlay = QLabel(self.video)
        self._cursor_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._cursor_overlay.setStyleSheet("background: transparent;")
        self._cursor_overlay.setFixedSize(48, 48)
        self._cursor_overlay.hide()

        self._cursor_timer = QTimer(self)
        self._cursor_timer.timeout.connect(self._animate_cursor)

        self.status = QLabel("Click Interact to control the remote pointer and keyboard.")
        self.status.setStyleSheet(f"color: {_css_color(theme.muted)}; font-size: 12px;")
        layout.addWidget(self.status)

    def _toggle_interact(self, checked: bool):
        self._interact = checked
        if checked:
            self.video.setCursor(QCursor(Qt.CursorShape.BlankCursor))
            self._cursor_overlay.show()
            self._cursor_overlay.raise_()
            cx, cy = self.video.width() // 2, self.video.height() // 2
            self._cursor_current = QPointF(cx, cy)
            self._cursor_target = QPointF(cx, cy)
            self._cursor_pos = QPoint(cx, cy)
            self._cursor_timer.start(50)
            self.status.setText("Interact mode ON — pointer and keyboard events are forwarded silently.")
        else:
            self.video.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self._cursor_overlay.hide()
            self._cursor_timer.stop()
            self.status.setText("Click Interact to control the remote pointer and keyboard.")

    def _on_mouse_move(self, event):
        if self._interact:
            pos = event.position()
            self._cursor_target = QPointF(pos)
            self.status.setText(f"Pointer at ({int(pos.x())}, {int(pos.y())}) — forwarding silently")
        else:
            QLabel.mouseMoveEvent(self.video, event)

    def _move_cursor_overlay(self):
        if self._cursor_pos is None:
            return
        size = self._cursor_overlay.size()
        x = self._cursor_pos.x() - size.width() // 2
        y = self._cursor_pos.y() - size.height() // 2
        # Clamp so the overlay stays inside the video panel.
        x = max(0, min(x, self.video.width() - size.width()))
        y = max(0, min(y, self.video.height() - size.height()))
        self._cursor_overlay.move(x, y)

    def _animate_cursor(self):
        self._cursor_glyph.update(0.05)
        pm = self._cursor_glyph.pixmap(self.theme, self.theme.glyph)
        self._cursor_overlay.setPixmap(pm)
        if self._cursor_target is not None:
            self._cursor_current += (self._cursor_target - self._cursor_current) * 0.25
            self._cursor_pos = QPoint(int(self._cursor_current.x()), int(self._cursor_current.y()))
        self._move_cursor_overlay()

    def _on_mouse_press(self, event):
        if self._interact:
            pos = event.position()
            self._cursor_target = QPointF(pos)
            self._cursor_current = QPointF(pos)
            self._cursor_pos = QPoint(int(pos.x()), int(pos.y()))
            self._move_cursor_overlay()
            self.status.setText(f"Click at ({int(pos.x())}, {int(pos.y())}) — forwarding silently")
        else:
            QLabel.mousePressEvent(self.video, event)

    def _on_key_press(self, event):
        if self._interact:
            self.status.setText(f"Key pressed: {event.text()} — forwarding silently")
        else:
            QLabel.keyPressEvent(self.video, event)

    def showEvent(self, event):
        self.setWindowOpacity(0.0)
        super().showEvent(event)
        anim = QPropertyAnimation(self, b"windowOpacity")
        anim.setDuration(280)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()


class FileManagerWindow(QFrame):
    """Agent-side remote file manager (.xnavigate)."""

    LOCATIONS = {}

    def __init__(self, theme: Theme, path: str = "~", parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setWindowTitle("File Manager — Atlas Workstation")
        self.resize(1000, 750)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(f"background: {_css_color(theme.panel)}; border-radius: 12px;")
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
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        for label in ("Back", "Refresh", "Upload", "Download", "Delete", "New Folder"):
            btn = QPushButton(label)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setStyleSheet(
                f"QPushButton {{ background: {_css_color(theme.hover)}; color: {_css_color(theme.text)}; "
                f" border-radius: 6px; padding: 6px 12px; font-size: 12px; }}"
                f"QPushButton:hover {{ background: {_css_color(theme.accent)}; }}"
            )
            btn.clicked.connect(lambda checked=False, a=label: self._toolbar_action(a))
            toolbar.addWidget(btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        # Main splitter: locations on left, files on right
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Locations sidebar
        locations_panel = QFrame()
        locations_panel.setFrameShape(QFrame.Shape.NoFrame)
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
            f"QListView::item {{ padding: 6px; border-radius: 4px; background: transparent; }}"
            f"QListView::item:selected {{ background: {_css_color(theme.accent)}; }}"
            f"QListView::item:hover {{ background: {_css_color(theme.hover)}; }}"
        )
        loc_palette = self.locations.palette()
        loc_palette.setColor(QPalette.Base, theme.panel)
        loc_palette.setColor(QPalette.Text, theme.text)
        self.locations.setPalette(loc_palette)
        self.locations.setAutoFillBackground(True)
        self.locations.viewport().setPalette(loc_palette)
        self.locations.viewport().setAutoFillBackground(True)
        self.locations.itemClicked.connect(self._location_clicked)
        locations_layout.addWidget(self.locations, 1)
        splitter.addWidget(locations_panel)

        # Files view
        files_panel = QFrame()
        files_panel.setFrameShape(QFrame.Shape.NoFrame)
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
            f" border-radius: 5px; padding: 3px 6px; font-size: 11px; }}"
        )
        self.search_edit.textChanged.connect(self._on_search)
        search_row.addWidget(search_lbl)
        search_row.addWidget(self.search_edit, 1)
        path_row.addLayout(search_row)

        files_layout.addLayout(path_row)

        self.files = QTreeWidget()
        self.files.setHeaderLabels(["Name", "Size", "Modified"])
        self.files.setStyleSheet(
            f"QTreeView::item {{ padding: 6px; background: transparent; }}"
            f"QTreeView::item:selected {{ background: {_css_color(theme.accent)}; }}"
            f"QHeaderView::section {{ background: {_css_color(theme.hover)}; color: {_css_color(theme.text)}; "
            f" padding: 6px; font-weight: 600; }}"
        )
        files_palette = self.files.palette()
        files_palette.setColor(QPalette.Base, theme.hover)
        files_palette.setColor(QPalette.Text, theme.text)
        self.files.setPalette(files_palette)
        self.files.setAutoFillBackground(True)
        self.files.viewport().setPalette(files_palette)
        self.files.viewport().setAutoFillBackground(True)
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
        splitter.setStyleSheet(
            f"QSplitter::handle {{ background: {_css_color(theme.hover)}; }}"
            f"QSplitter::handle:horizontal {{ width: 4px; }}"
        )
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
            f"QMenu {{ background: {_css_color(self.theme.panel)}; color: {_css_color(self.theme.text)};  padding: 4px; }}"
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

    def showEvent(self, event):
        _fade_show(self)
        super().showEvent(event)


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
            f" border-radius: 6px; padding: 5px 12px; font-size: 12px; }}"
            f"QPushButton:hover {{ background: {_css_color(theme.accent)}; }}"
        )
        clear_btn.clicked.connect(self._clear)
        header.addWidget(clear_btn)
        layout.addLayout(header)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setStyleSheet(
            f"QTextEdit {{ background: {_css_color(theme.panel)}; color: {_css_color(theme.text)}; "
            f" border-radius: 12px; padding: 10px; font-family: monospace; }}"
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
            f" border-radius: 6px; padding: 6px; font-family: monospace; }}"
        )
        self.input.returnPressed.connect(self._run_command)
        run_btn = QPushButton("Run")
        run_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        run_btn.setStyleSheet(
            f"QPushButton {{ background: {_css_color(theme.accent)}; color: {_css_color(theme.text)}; "
            f" border-radius: 6px; padding: 6px 14px; font-size: 12px; }}"
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

    def showEvent(self, event):
        _fade_show(self)
        super().showEvent(event)


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
            f" border-radius: 6px; padding: 6px 14px; font-size: 12px; }}"
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

    def showEvent(self, event):
        _fade_show(self)
        super().showEvent(event)


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
            f" border-radius: 6px; padding: 5px 12px; font-size: 12px; }}"
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
                f" border-radius: 6px; padding: 5px 10px; font-size: 11px; }}"
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
            f" border-radius: 12px; padding: 10px; font-family: monospace; }}"
        )
        self.output.setText("Enter a classic Magnet command below.\n")
        layout.addWidget(self.output, 1)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Type .screenshot, .feed, .xnavigate, etc.")
        self.input.setStyleSheet(
            f"QLineEdit {{ background: {_css_color(theme.hover)}; color: {_css_color(theme.text)}; "
            f" border-radius: 6px; padding: 6px; font-family: monospace; }}"
        )
        self.input.returnPressed.connect(self._send_from_input)
        run_btn = QPushButton("Run")
        run_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        run_btn.setStyleSheet(
            f"QPushButton {{ background: {_css_color(theme.accent)}; color: {_css_color(theme.text)}; "
            f" border-radius: 6px; padding: 6px 14px; font-size: 12px; }}"
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

    def showEvent(self, event):
        _fade_show(self)
        super().showEvent(event)


# ------------------------------------------------------------------
# Main application
# ------------------------------------------------------------------
class MagnetAgentPrototype(QApplication):
    def __init__(self, argv, force_light: bool = False, initial_view: int = 0):
        super().__init__(argv)

        self.setOrganizationName("MagnetOS")
        self.setApplicationName("Magnet Agent v2")
        self.settings = QSettings()

        self.theme = _make_agent_theme(not force_light and _is_dark_mode(self))
        self._initial_view = initial_view
        apply_global_styles(self, self.theme)
        try:
            self.styleHints().colorSchemeChanged.connect(self._theme_changed)
        except Exception:
            pass

        self.glyph = GlyphRenderer(size=160)
        self.glyph.set_state("idle")

        self.window = AgentWindow(self.theme, self.glyph, self.settings, initial_view=self._initial_view)
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
        self.theme = _make_agent_theme(_is_dark_mode(self))
        apply_global_styles(self, self.theme)
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
    view_map = {"sessions": 0, "deploy": 1, "commands": 2, "terminal": 3, "settings": 4, "active": 5}
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

