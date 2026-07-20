"""Loopback test for Vision remote control.

Starts a VisionServer, connects a VisionStreamer, sends pointer/keyboard
control messages, and prints the actions the client-side injector would
perform. Run manually; the stream is short-circuited so no real screen
capture happens.
"""

import asyncio
import sys
import time

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

import magnet_vision
from magnet_vision import VisionServer, VisionStreamer


class DummyInjector:
    actions = []

    def move(self, x, y):
        self.actions.append(("move", x, y))
        print(f"[injector] move({x:.3f}, {y:.3f})")

    def click(self, button, down):
        self.actions.append(("click", button, down))
        print(f"[injector] click({button}, down={down})")

    def key(self, text, down):
        self.actions.append(("key", text, down))
        print(f"[injector] key({text!r}, down={down})")

    def scroll(self, direction, clicks):
        self.actions.append(("scroll", direction, clicks))
        print(f"[injector] scroll({direction}, {clicks})")


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    dummy = DummyInjector()
    magnet_vision._injector = dummy

    server = VisionServer()
    streamer = VisionStreamer()

    orig_apply = magnet_vision.VisionStreamer._apply_control
    def debug_apply(self, data):
        print('[streamer] _apply_control received:', data)
        orig_apply(self, data)
    magnet_vision.VisionStreamer._apply_control = debug_apply

    # Don't actually send video frames; we only care about the control channel.
    async def noop_stream_loop(self, writer):
        while not streamer._stop_event.is_set():
            await asyncio.sleep(0.5)

    magnet_vision.VisionStreamer._stream_loop = noop_stream_loop

    def on_client_connected(sid):
        print("[server] client connected:", sid)
        QTimer.singleShot(500, send_controls)

    def send_controls():
        print("[server] sending control messages")
        server.send_control({"action": "mouse_move", "x": 0.5, "y": 0.5})
        server.send_control({"action": "mouse_click", "button": "left", "down": True})
        server.send_control({"action": "mouse_click", "button": "left", "down": False})
        server.send_control({"action": "key", "text": "a", "down": True})
        server.send_control({"action": "key", "text": "a", "down": False})
        QTimer.singleShot(1000, stop)

    def stop():
        streamer.stop_stream()
        server.stop_server()
        app.quit()

    server.client_connected.connect(on_client_connected)
    server.server_started.connect(lambda host, port: print(f"[server] listening on {host}:{port}"))

    server.start_server(port=0)
    time.sleep(0.2)
    host, port = server.get_endpoint()
    streamer.start_stream(host, port, "test-session")

    app.exec()
    print("\nReceived actions:")
    for a in dummy.actions:
        print(" ", a)
    return 0 if len(dummy.actions) >= 5 else 1


if __name__ == "__main__":
    sys.exit(main())
