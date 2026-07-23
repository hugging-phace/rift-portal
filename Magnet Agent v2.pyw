"""
Magnet Agent v2 — production backend with the new MagnetOS v2 UI.

This file combines the v2 shell from `Magnet Agent v2 Prototype.pyw`
with the Firebase / command / Vision backend from `Magnet Agent.pyw`.

PyInstaller build target for the standalone Windows .exe and macOS .app.
"""

import importlib.machinery
import importlib.util
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import (
    Qt, QTimer, QThread, QSettings, QPropertyAnimation, QEasingCurve,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QMessageBox,
)

from magnet_v2_theme import apply_global_styles, backend_reset_stylesheet

# ------------------------------------------------------------------
# Load the v2 UI shell and the production backend from their .pyw files
# ------------------------------------------------------------------
def _load_module(name: str, path: str):
    # Use SourceFileLoader so .pyw files load correctly (spec_from_file_location
    # returns None for non-.py extensions on some Python builds).
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_repo_root = Path(__file__).resolve().parent
_v2 = _load_module("_v2_ui", str(_repo_root / "Magnet Agent v2 Prototype.pyw"))
_backend = _load_module("_backend", str(_repo_root / "Magnet Agent.pyw"))

AgentWindow = _v2.AgentWindow
PageWidget = _v2.PageWidget
Theme = _v2.Theme
GlyphRenderer = _v2.GlyphRenderer
_make_agent_theme = _v2._make_agent_theme
_is_dark_mode = _v2._is_dark_mode
_css_color = _v2._css_color

SessionListView = _backend.SessionListView
SessionDetailView = _backend.SessionDetailView
CommandListView = _backend.CommandListView
TerminalCommandsView = _backend.TerminalCommandsView
SettingsView = _backend.SettingsView

FileManagerWindow = _v2.FileManagerWindow
CommandWindow = _v2.CommandWindow
VisionWindow = _v2.VisionWindow
ScreenshotWindow = _v2.ScreenshotWindow
TerminalWindow = _v2.TerminalWindow


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
class BackendPage(PageWidget):
    """A PageWidget with the title hidden and a style reset for legacy backend widgets."""

    def __init__(self, theme: Theme, bg: QColor = None, parent=None):
        super().__init__("", theme, bg, parent)
        self.setObjectName("backendPage")
        # Hide the default title label so the embedded backend view is the full page.
        top_item = self.layout().itemAt(0)
        if top_item is not None:
            title_lbl = top_item.widget()
            if title_lbl is not None:
                title_lbl.setVisible(False)
        # Reset backend widgets to the v2 palette while keeping the page container style.
        self.setStyleSheet(backend_reset_stylesheet(theme))


class _OrbAdapter:
    """Map the old OrbWidget API to the new v2 GlyphRenderer."""

    STATE_MAP = {
        "awaiting": "idle",
        "idle": "idle",
        "command": "processing",
        "terminal": "processing",
        "scan": "processing",
        "screenshot": "processing",
        "test_pulse": "connected",
        "feedme": "file_transfer",
        "vision": "viewing",
        "paused": "idle",
        "disconnected": "disconnected",
    }

    def __init__(self, renderer: GlyphRenderer, label, status_label: QLabel):
        self._renderer = renderer
        self._label = label
        self._status = status_label
        self._state = "idle"
        self._paused = False
        self._flash_timer = None

    def _map(self, state):
        return self.STATE_MAP.get(state, "processing")

    def _apply(self, state):
        mapped = self._map(state)
        if self._paused and mapped == "idle":
            mapped = "connected"
        self._renderer.set_state(mapped)
        self._label.refresh()
        if self._status is not None:
            labels = {
                "idle": "IDLE",
                "connected": "CONNECTED",
                "viewing": "VIEWING",
                "processing": "PROCESSING",
                "file_transfer": "TRANSFERRING",
                "disconnected": "DISCONNECTED",
            }
            self._status.setText(labels.get(mapped, mapped.upper()))

    def set_state(self, state):
        self._state = state
        self._apply(state)

    def set_paused(self, paused: bool):
        self._paused = paused
        self._apply(self._state)

    def _flash(self, state, revert, duration_ms=700):
        self._apply(state)
        if self._flash_timer is not None:
            self._flash_timer.stop()
        self._flash_timer = QTimer()
        self._flash_timer.setSingleShot(True)
        self._flash_timer.timeout.connect(lambda: self._apply(revert))
        self._flash_timer.start(duration_ms)

    def flash_command(self):
        self._flash("processing", self._state, 600)

    def flash_terminal(self):
        self._flash("processing", self._state, 600)

    def flash_alert(self):
        self._flash("connected", self._state, 400)

    def trigger_pulse(self):
        self._flash("connected", self._state, 300)

    def start_portal_opening(self):
        self._renderer.set_state("connected")
        self._label.refresh()

    def start_portal_closing(self):
        self._renderer.set_state("idle")
        self._label.refresh()


# ------------------------------------------------------------------
# Session detail view that mirrors chat and results to the v2 UI widgets
# ------------------------------------------------------------------
class MirroringSessionDetailView(SessionDetailView):
    """Hidden SessionDetailView that forwards results/chat to the visible v2 UI."""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self._owner = owner
        self.setVisible(False)

    def _format_result(self, result_type, title, content):
        if result_type == "file_drop":
            file_path = content.get("file", "") if isinstance(content, dict) else ""
            return f"File received: {Path(file_path).name or 'file'}"
        if result_type == "files":
            files = content.get("files", {}) if isinstance(content, dict) else {}
            return f"Files received: {len(files)} files"
        if result_type == "error":
            return f"Error — {title}:\n{content}"
        if isinstance(content, (dict, list)):
            try:
                body = _backend.json.dumps(content, indent=2)[:1200]
            except Exception:
                body = str(content)
            return f"{title}\n{body}"
        return f"{title}\n{content}"

    def add_result(self, result_type, title, content):
        text = self._format_result(result_type, title, content)
        self._owner._append_to_chat(text)
        self._owner._append_to_command_window(text)

    def add_screenshot(self, pixmap, title="Screenshot"):
        try:
            dialog = _backend.ImagePopoutDialog(pixmap, title, self._owner)
            dialog.show()
        except Exception:
            pass
        self._owner._append_to_chat(f"Screenshot received: {title}")

    def _add_chat_bubble(self, text, is_admin=False):
        super()._add_chat_bubble(text, is_admin)
        prefix = "You:" if is_admin else "Atlas:"
        self._owner._append_to_chat(f"{prefix} {text}")

    def set_vision_frame(self, pixmap):
        super().set_vision_frame(pixmap)
        self._owner._update_vision_window(pixmap)


# ------------------------------------------------------------------
# Main window — v2 shell + production backend
# ------------------------------------------------------------------
class MagnetAgent(AgentWindow):
    def __init__(self, theme: Theme, glyph: GlyphRenderer, settings: QSettings, parent=None):
        # Backend state created before super().__init__ so page builders can use them.
        self._start_time = time.time()
        self._drag_pos = None
        self._sessions = []
        self._current_session = None
        self._new_session_dialog = None
        self._vision_interact = False
        self._vision_session_id = None
        self._vision_target_session_id = None
        self._orb_connected = False
        self._ambient_opening = False

        self._session_list = None
        self._session_detail = None
        self._command_list_view = None
        self._terminal_commands_view = None
        self._settings_view = None

        self.orb = None
        self._orb_status = None
        self._nav_buttons = []

        # Build the v2 UI (this calls our overridden _build_*_page methods).
        super().__init__(theme, glyph, settings, initial_view=0, parent=parent)

        # Orb aliases for backend methods.
        self._orb_status = self._glyph_status
        self.orb = _OrbAdapter(glyph, self._glyph_lbl, self._glyph_status)
        self.orb.set_state("awaiting")

        # The backend uses _nav_buttons for nav refresh helpers.
        self._nav_buttons = self._nav_btns

        # Ambient rift timer used by the production backend.
        self._ambient_timer = QTimer(self)
        self._ambient_timer.setSingleShot(True)

        # Animate the v2 glyph.
        self._glyph_timer = QTimer(self)
        self._glyph_timer.timeout.connect(self._animate_glyph)
        self._glyph_timer.start(100)

        # Start backend services and wire signals.
        self._setup_backend()

    def _animate_glyph(self):
        glyph = getattr(self, "glyph", None)
        if glyph is not None:
            glyph.update(0.1)
        if hasattr(self, "_glyph_lbl"):
            self._glyph_lbl.theme = self.theme
            self._glyph_lbl.refresh()

    # ---- Page builders: replace placeholder pages with real backend views ----
    def _build_sessions_page(self):
        page = BackendPage(self.theme, bg=self.theme.panel)
        self._session_list = SessionListView(page)
        page._body.addWidget(self._session_list, 1)
        return page

    def _build_deploy_page(self):
        # Reuse the v2 deploy composer.
        return super()._build_deploy_page()

    def _build_commands_page(self):
        page = BackendPage(self.theme, bg=self.theme.panel)
        self._command_list_view = CommandListView(page)
        page._body.addWidget(self._command_list_view, 1)
        return page

    def _build_terminal_page(self):
        page = BackendPage(self.theme, bg=self.theme.panel)
        self._terminal_commands_view = TerminalCommandsView(page)
        page._body.addWidget(self._terminal_commands_view, 1)
        return page

    def _build_settings_page(self):
        page = BackendPage(self.theme, bg=self.theme.panel)
        self._settings_view = SettingsView(page)
        page._body.addWidget(self._settings_view, 1)
        return page

    def _build_active_session_page(self):
        # Use the v2 prototype active-session layout (file manager, chat,
        # quick commands, manual commands button) and keep a hidden
        # SessionDetailView to drive the production backend.
        page = super()._build_active_session_page()
        self._session_detail = MirroringSessionDetailView(self, page)
        self._session_detail.setVisible(False)
        return page

    # ---- Backend wiring ----
    def _setup_backend(self):
        self._uptime_timer = QTimer(self)
        self._uptime_timer.timeout.connect(self._update_uptime)
        self._uptime_timer.start(1000)

        self._firebase_worker = _backend.FirebaseWorker()
        self._firebase_thread = QThread(self)
        self._firebase_worker.moveToThread(self._firebase_thread)
        self._firebase_worker.sessions_updated.connect(self._on_sessions_updated)
        self._firebase_worker.result_received.connect(self._on_result_received)
        self._firebase_worker.portal_opened.connect(self._on_portal_opened)
        self._firebase_worker.chat_received.connect(self._on_chat_received)
        self._firebase_worker.poll_status.connect(self._on_poll_status)
        self._firebase_worker.refresh.connect(self._firebase_worker._poll_all_sessions)
        self._firebase_thread.started.connect(self._firebase_worker.run)
        self._firebase_thread.start()

        self._vision_server = _backend.VisionServer(self)
        self._vision_server.server_started.connect(self._on_vision_server_started)
        self._vision_server.client_connected.connect(self._on_vision_client_connected)
        self._vision_server.client_disconnected.connect(self._on_vision_client_disconnected)
        self._vision_server.frame_received.connect(self._on_vision_frame)
        self._vision_server.error.connect(lambda msg: _backend._log(f"[Vision] {msg}"))

        self._session_list.session_selected.connect(self._open_session)
        self._session_list.new_session_requested.connect(self._show_new_session_dialog)
        self._session_list.cleanup_stale.connect(self._cleanup_stale_sessions)
        self._session_list.refresh_requested.connect(self._refresh_sessions)
        self._session_list.purge_closed.connect(self._purge_closed_sessions)
        self._session_list.session_deleted.connect(self._delete_session)

        self._session_detail.back_requested.connect(self._back_to_list)
        self._session_detail.command_sent.connect(self._on_command_sent)
        self._session_detail.quick_action.connect(self._on_quick_action)
        self._session_detail.portal_open_requested.connect(self._on_portal_open_requested)
        self._session_detail.close_session_requested.connect(self._close_session)
        self._session_detail.chat_sent.connect(self._on_chat_sent)
        self._session_detail.interact_toggled.connect(self._on_vision_interact_toggled)
        self._session_detail.pointer_event.connect(self._on_vision_pointer_event)
        self._session_detail.key_event.connect(self._on_vision_key_event)

        self._settings_view.theme_changed.connect(self._apply_theme)

        self._switch_view(0)

    # ---- Chat / quick action / manual command overrides ----
    def _on_chat_send(self, line, output):
        text = line.text().strip()
        line.clear()
        if not text or not self._current_session:
            return
        output.append(f"You: {text}")
        self._on_chat_sent(self._current_session.id, text)

    def _on_quick_action(self, *args):
        if not self._current_session:
            return
        if len(args) == 1:
            action = args[0]
            if action == "Files":
                self._open_file_manager()
                return
            if action == "Terminal":
                self._open_terminal()
                return
            if action == "Vision":
                self._open_vision()
            mapping = {
                "Screenshot": "screenshot",
                "Feed": "feedme",
                "Pause": "paused",
                "Pulse": "test_pulse",
                "Vision": "vision",
            }
            backend_action = mapping.get(action, action.lower())
        elif len(args) == 2:
            backend_action = args[1]
        else:
            return
        _backend.MagnetAgent._on_quick_action(self, self._current_session.id, backend_action)

    def _run_magnet_command(self, cmd):
        if not self._current_session:
            return "No active session"
        lower = cmd.lower().strip()
        if lower.startswith(".xnavigate") or lower == ".navigate":
            path = cmd[10:].strip() if lower.startswith(".xnavigate") else cmd[8:].strip()
            path = path or "~"
            self._file_manager._load_path(Path(os.path.expanduser(path)))
            return f"Opened folder view: {path}"
        if lower.startswith(".xterminal") or lower == ".terminal":
            self._open_terminal()
            return "Opened Terminal window"
        if lower.startswith(".vision"):
            self._on_quick_action("Vision")
            return "Vision request sent"
        if lower.startswith(".screenshot"):
            self._on_quick_action("Screenshot")
            return "Screenshot request sent"
        if lower.startswith(".feed"):
            self._on_quick_action("Feed")
            return "Feed request sent"
        if lower.startswith(".pause"):
            self._on_quick_action("Pause")
            return "Pause toggled"
        if lower.startswith(".pulse"):
            self._on_quick_action("Pulse")
            return "Pulse sent"
        self._on_command_sent(self._current_session.id, cmd)
        return f"Sent to {self._current_session.name or 'Atlas Workstation'}: {cmd}"

    def _open_vision(self):
        self._vision_window = VisionWindow(self.theme)
        self._vision_window.interact_btn.toggled.connect(self._on_vision_interact_toggled)
        self._vision_window.show()

    def _append_to_chat(self, text):
        if getattr(self, "_chat_output", None) is not None:
            self._chat_output.append(text)

    def _append_to_command_window(self, text):
        try:
            window = getattr(self, "_command_window", None)
            if window and window.isVisible():
                window.output.append(text)
        except Exception:
            pass

    def _update_vision_window(self, pixmap):
        try:
            window = getattr(self, "_vision_window", None)
            if window and window.isVisible():
                scaled = pixmap.scaled(
                    window.video.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                window.video.setPixmap(scaled)
        except Exception:
            pass

    # ---- Overrides for view switching and theming ----
    def _open_session(self, session_id):
        for s in self._sessions:
            if s.id == session_id:
                self._current_session = s
                self._session_detail.set_session(s)
                # Update the active-session page title.
                page = self._stack.widget(5)
                if page is not None:
                    layout = page.layout()
                    if layout is not None and layout.count() > 0:
                        title_lbl = layout.itemAt(0).widget()
                        if isinstance(title_lbl, QLabel):
                            title_lbl.setText(s.name or "Session")
                self._switch_view(5)
                self._firebase_worker.watch_results(session_id)
                self._firebase_worker.watch_chat(session_id)
                return

    def _apply_theme(self, name):
        """Apply a backend theme update and refresh the settings view."""
        _backend.apply_theme(name)
        if self._settings_view is not None:
            self._settings_view.refresh_theme()
        self.update()
        for child in self.findChildren(QWidget):
            child.update()

    def _delete_session(self, session_id: str):
        """Delete a single session from Firebase, regardless of stage."""
        try:
            _backend._firebase_delete(f"sessions/{session_id}")
        except Exception as e:
            _backend._log(f"Failed to delete session {session_id}: {e}")
        if self._current_session and self._current_session.id == session_id:
            self._firebase_worker.unwatch_results(session_id)
            self._firebase_worker.unwatch_chat(session_id)
            self._current_session = None
            self._switch_view(0)
        self._refresh_sessions()

    def _toggle_max_restore(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()


# ------------------------------------------------------------------
# Copy remaining backend methods from the production MagnetAgent class.
# We keep the v2 AgentWindow methods for drag, fade-ins and window chrome.
# ------------------------------------------------------------------
_METHODS_TO_SKIP = {
    "__init__",
    "_switch_view",
    "_finish_switch_view",
    "_apply_theme",
    "_open_session",
    "_toggle_max_restore",
    "_setup_backend",
    "_build_sessions_page",
    "_build_deploy_page",
    "_build_commands_page",
    "_build_terminal_page",
    "_build_settings_page",
    "_build_active_session_page",
    "_animate_glyph",
    "mousePressEvent",
    "mouseMoveEvent",
    "mouseReleaseEvent",
    "keyPressEvent",
    "resizeEvent",
    "changeEvent",
    "showEvent",
    "paintEvent",
    "eventFilter",
    "closeEvent",
}

_backend_magnet = _backend.MagnetAgent
for _name, _member in _backend_magnet.__dict__.items():
    if _name.startswith("__") or not callable(_member):
        continue
    if _name in _METHODS_TO_SKIP:
        continue
    # Do not overwrite methods that already exist on the v2 AgentWindow.
    if _name in AgentWindow.__dict__:
        continue
    setattr(MagnetAgent, _name, _member)

# Ensure we use the production closeEvent for clean thread shutdown.
MagnetAgent.closeEvent = _backend_magnet.closeEvent


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------
def main():
    app = QApplication(sys.argv)
    app.setOrganizationName("MagnetOS")
    app.setApplicationName("Magnet Agent")

    # Force the light pale-navy theme by default.
    theme = _make_agent_theme(False)
    apply_global_styles(app, theme)
    glyph = GlyphRenderer(size=160, weight=0.7)
    glyph.set_state("idle")

    settings = QSettings()
    window = MagnetAgent(theme, glyph, settings)
    window.set_status("idle")
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
