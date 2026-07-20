"""Remote "agent" process that runs on the main X display.

It starts a VisionServer, spawns the Xephyr client on :1, displays the live
feed, and lets the admin enable "Interact" to control the remote pointer and
keyboard.
"""

import os
import subprocess
import sys
import time

from PySide6.QtCore import Qt, QPoint, QTimer, QEvent
from PySide6.QtGui import QPixmap, QCursor, QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
)

from magnet_vision import VisionServer


class AgentWindow(QWidget):
    def __init__(self, server: VisionServer):
        super().__init__()
        self.server = server
        self._interact = False

        self.setWindowTitle("Magnet Agent — Remote Desktop Demo")
        self.resize(1200, 900)
        self.setStyleSheet("background-color: #0f0f1a;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QHBoxLayout()
        self.status = QLabel("Waiting for client...")
        self.status.setStyleSheet("color: #a0a0c0; font-size: 14px;")
        header.addWidget(self.status)
        header.addStretch()

        self.interact_btn = QPushButton("Interact: OFF")
        self.interact_btn.setCheckable(True)
        self.interact_btn.setStyleSheet(
            "QPushButton { background: #2c3c58; color: white; border: none; "
            "border-radius: 6px; padding: 8px 16px; font-weight: 600; }"
            "QPushButton:checked { background: #e94560; }"
        )
        self.interact_btn.toggled.connect(self.on_interact)
        header.addWidget(self.interact_btn)
        layout.addLayout(header)

        self.feed = QLabel()
        self.feed.setStyleSheet("background-color: #161625; border-radius: 8px;")
        self.feed.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.feed.setMinimumSize(1000, 700)
        self.feed.setMouseTracking(True)
        self.feed.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.feed.installEventFilter(self)
        layout.addWidget(self.feed, 1)

        self.info = QLabel("Move the mouse, click, or type once Interact is ON.")
        self.info.setStyleSheet("color: #606080; font-size: 12px;")
        layout.addWidget(self.info)

        self.server.server_started.connect(self.on_server_started)
        self.server.client_connected.connect(self.on_client_connected)
        self.server.client_disconnected.connect(self.on_client_disconnected)
        self.server.frame_received.connect(self.on_frame)

    def on_server_started(self, host: str, port: int):
        self.status.setText(f"Server listening on {host}:{port}")
        # Start the remote client on display :1.
        client_env = os.environ.copy()
        client_env["DISPLAY"] = ":1"
        cmd = [sys.executable, "test_xephyr_client.py", host, str(port), "xephyr-session"]
        subprocess.Popen(cmd, env=client_env, cwd=os.path.dirname(__file__))

    def on_client_connected(self, session_id: str):
        self.status.setText(f"Client connected: {session_id}")
        self.interact_btn.setEnabled(True)

    def on_client_disconnected(self, session_id: str):
        self.status.setText("Client disconnected")
        self.interact_btn.setChecked(False)
        self.interact_btn.setEnabled(False)
        self.feed.clear()

    def on_frame(self, session_id: str, jpeg_bytes: bytes):
        pixmap = QPixmap()
        if pixmap.loadFromData(jpeg_bytes, "JPEG"):
            scaled = pixmap.scaled(
                self.feed.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.feed.setPixmap(scaled)

    def on_interact(self, checked: bool):
        self._interact = checked
        self.interact_btn.setText("Interact: ON" if checked else "Interact: OFF")
        if checked:
            self.feed.setCursor(QCursor(Qt.CursorShape.BlankCursor))
            self.feed.setFocus()
            self.info.setText("Interact ON — click/type into the feed to control the remote desktop.")
        else:
            self.feed.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self.info.setText("Move the mouse, click, or type once Interact is ON.")

    def eventFilter(self, watched, event):
        if watched is self.feed:
            print(f"[agent] event {event.type()} interact={self._interact}", flush=True)
        if watched is not self.feed or not self._interact:
            return super().eventFilter(watched, event)

        etype = event.type()
        if etype == QEvent.Type.MouseMove:
            print(f"[agent] MouseMove {event.pos().x()},{event.pos().y()}", flush=True)
            self.send_pointer(event.pos(), "mouse_move")
            return True
        elif etype in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
            down = etype == QEvent.Type.MouseButtonPress
            button = {1: "left", 2: "right", 4: "middle"}.get(
                event.button().value, "left"
            )
            print(f"[agent] MouseButton {button} down={down} pos={event.pos().x()},{event.pos().y()}", flush=True)
            self.send_pointer(event.pos(), "mouse_click", button, down)
            return True
        elif etype == QEvent.Type.Wheel:
            delta = event.angleDelta()
            if delta.x() != 0:
                axis, clicks = "horizontal", delta.x() / 120.0
            else:
                axis, clicks = "vertical", delta.y() / 120.0
            self.server.send_control({"action": "scroll", "axis": axis, "clicks": clicks})
            return True
        elif etype == QEvent.Type.KeyPress:
            self.send_key(event.key(), event.text(), True)
            return True
        elif etype == QEvent.Type.KeyRelease:
            self.send_key(event.key(), event.text(), False)
            return True

        return super().eventFilter(watched, event)

    def send_pointer(self, pos: QPoint, action: str, button: str = "left", down: bool = True):
        norm = self.normalize(pos)
        if norm is None:
            return
        print(f"[agent] send {action} norm={norm}", flush=True)
        if action == "mouse_move":
            self.server.send_control({"action": "mouse_move", "x": norm[0], "y": norm[1]})
        elif action == "mouse_click":
            self.server.send_control({"action": "mouse_click", "button": button, "down": down, "x": norm[0], "y": norm[1]})

    def send_key(self, key: int, text: str, down: bool):
        special = {
            Qt.Key.Key_Shift: "shift", Qt.Key.Key_Control: "ctrl",
            Qt.Key.Key_Alt: "alt", Qt.Key.Key_Meta: "win",
            Qt.Key.Key_Return: "return", Qt.Key.Key_Enter: "return",
            Qt.Key.Key_Space: "space", Qt.Key.Key_Backspace: "backspace",
            Qt.Key.Key_Delete: "delete", Qt.Key.Key_Escape: "escape",
            Qt.Key.Key_Tab: "tab",
        }
        if key in special:
            name = special[key]
        else:
            name = text if text else ""
        if name:
            self.server.send_control({"action": "key", "text": name, "down": down})

    def normalize(self, pos: QPoint):
        rect = self.feed.rect()
        w, h = rect.width(), rect.height()
        if w <= 0 or h <= 0:
            return None
        pm = self.feed.pixmap()
        if pm and not pm.isNull():
            pw, ph = pm.width(), pm.height()
            if pw > 0 and ph > 0:
                off_x = (w - pw) / 2.0
                off_y = (h - ph) / 2.0
                x = (pos.x() - off_x) / pw
                y = (pos.y() - off_y) / ph
            else:
                x = pos.x() / w
                y = pos.y() / h
        else:
            x = pos.x() / w
            y = pos.y() / h
        x = max(0.0, min(1.0, x))
        y = max(0.0, min(1.0, y))
        return (x, y)


def main():
    app = QApplication(sys.argv)
    server = VisionServer()
    win = AgentWindow(server)
    win.show()
    server.start_server(port=0)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
