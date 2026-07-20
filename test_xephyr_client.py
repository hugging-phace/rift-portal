"""Remote "client" process that runs on a secondary X display (e.g. :1).

It opens a small target window, connects to a VisionServer on the main display,
streams its screen, and injects pointer/keyboard events it receives back into its
own X display.
"""

import asyncio
import sys

from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, QTimer

import magnet_vision
from magnet_vision import VisionStreamer


class ClientWindow(QWidget):
    def __init__(self, host: str, port: int, session_id: str):
        super().__init__()
        self.setWindowTitle("Remote Desktop")
        self.resize(1024, 768)
        self.setStyleSheet("background-color: #1a1a2e;")

        layout = QVBoxLayout(self)
        self.status = QLabel("Waiting for remote control...")
        self.status.setStyleSheet("color: white; font-size: 24px;")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status)

        self.btn = QPushButton("Click me remotely")
        self.btn.setStyleSheet(
            "background-color: #e94560; color: white; font-size: 20px; padding: 20px;"
        )
        self.btn.setFixedSize(300, 80)
        self.btn.setDefault(True)
        self.btn.clicked.connect(self.on_click)
        layout.addWidget(self.btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self.key_label = QLabel("Last key: -")
        self.key_label.setStyleSheet("color: #a0a0c0; font-size: 18px;")
        self.key_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.key_label)

        self.cursor_label = QLabel("Pointer: -, -")
        self.cursor_label.setStyleSheet("color: #a0a0c0; font-size: 18px;")
        self.cursor_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.cursor_label)

        self.streamer = VisionStreamer()
        self.streamer.state_changed.connect(self.on_state)
        self.streamer.error.connect(lambda msg: self.status.setText(f"Vision error: {msg}"))

        # Update cursor position label so the agent can see pointer motion in the feed.
        self.setMouseTracking(True)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_cursor_pos)
        self.timer.start(100)

        QTimer.singleShot(200, lambda: self.streamer.start_stream(host, port, session_id))

    def on_click(self):
        self.status.setText("Button clicked remotely!")
        QTimer.singleShot(1500, lambda: self.status.setText("Waiting for remote control..."))

    def on_state(self, state: str):
        self.status.setText(f"Vision state: {state}")

    def update_cursor_pos(self):
        from PySide6.QtGui import QCursor
        pos = QCursor.pos()
        self.cursor_label.setText(f"Pointer: {pos.x()}, {pos.y()}")

    def keyPressEvent(self, event):
        self.key_label.setText(f"Last key: {event.text()!r}")
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.btn.click()
        super().keyPressEvent(event)


def main():
    if len(sys.argv) < 4:
        print("usage: test_xephyr_client.py <host> <port> <session_id>")
        return 1

    host = sys.argv[1]
    port = int(sys.argv[2])
    session_id = sys.argv[3]

    app = QApplication(sys.argv)

    orig_apply = magnet_vision.VisionStreamer._apply_control
    def debug_apply(self, data):
        print(f"[client] control received: {data}")
        orig_apply(self, data)
    magnet_vision.VisionStreamer._apply_control = debug_apply

    win = ClientWindow(host, port, session_id)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
