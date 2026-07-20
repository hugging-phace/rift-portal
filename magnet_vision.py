"""
magnet_vision.py
Shared Vision streaming layer for Magnet Client and Magnet Agent.

Provides a low-latency, adaptive JPEG screen stream over a TCP socket.
The transport is message-framed so the socket can be swapped for WebRTC
or another low-latency channel later without changing the capture/encode
or display code.

Platform-specific capture is isolated behind the CaptureSource classes;
the networking pipeline is shared.
"""

import asyncio
import io
import json
import math
import os
import platform
import socket
import struct
import threading
import time
from dataclasses import dataclass
from typing import Optional

from PIL import Image, ImageGrab
from PySide6.QtCore import QThread, Signal

# ------------------------------------------------------------------
# Protocol constants
# ------------------------------------------------------------------
MSG_HELLO = 0x01
MSG_FRAME = 0x02
MSG_CONTROL = 0x10
MSG_ACK = 0x11

# ------------------------------------------------------------------
# Vision configuration
# ------------------------------------------------------------------
@dataclass
class VisionConfig:
    quality: int = 75
    scale: float = 0.75
    target_fps: float = 15.0
    paused: bool = False
    min_quality: int = 20
    max_quality: int = 95
    min_scale: float = 0.25
    max_scale: float = 1.0
    max_fps: float = 30.0
    min_fps: float = 1.0
    buffer_high_water: int = 256 * 1024
    buffer_low_water: int = 64 * 1024


# ------------------------------------------------------------------
# Utility: get a usable local IP address
# ------------------------------------------------------------------
def get_default_ip() -> str:
    """Return the IP used for the default route, or a fallback."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "127.0.0.1"


# ------------------------------------------------------------------
# Remote pointer / keyboard injection (client-side)
# ------------------------------------------------------------------
def _get_screen_size():
    """Return (width, height) for the primary screen in device pixels."""
    try:
        # Qt must be available in the client process
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            screen = app.primaryScreen()
            if screen is not None:
                geo = screen.geometry()
                return geo.width(), geo.height()
    except Exception:
        pass
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab()
        return img.size
    except Exception:
        pass
    return 1920, 1080


# Lazily loaded platform-specific injection helpers.
_injector = None

def _get_injector():
    global _injector
    if _injector is not None:
        return _injector
    system = platform.system()
    if system == "Windows":
        _injector = _WindowsInjector()
    elif system == "Linux":
        _injector = _LinuxInjector()
    elif system == "Darwin":
        _injector = _DarwinInjector()
    else:
        _injector = _NullInjector()
    return _injector


class _NullInjector:
    def move(self, x, y):
        pass
    def click(self, button, down):
        pass
    def key(self, text, down):
        pass
    def scroll(self, direction, clicks):
        pass


class _WindowsInjector:
    """Use the Windows SendInput API for pointer and keyboard events."""

    def __init__(self):
        import ctypes
        self._ctypes = ctypes
        self._user32 = ctypes.windll.user32
        self._SendInput = self._user32.SendInput

        self._INPUT_MOUSE = 0
        self._INPUT_KEYBOARD = 1
        self._MOUSEEVENTF_MOVE = 0x0001
        self._MOUSEEVENTF_ABSOLUTE = 0x8000
        self._MOUSEEVENTF_LEFTDOWN = 0x0002
        self._MOUSEEVENTF_LEFTUP = 0x0004
        self._MOUSEEVENTF_RIGHTDOWN = 0x0008
        self._MOUSEEVENTF_RIGHTUP = 0x0010
        self._MOUSEEVENTF_MIDDLEDOWN = 0x0020
        self._MOUSEEVENTF_MIDDLEUP = 0x0040
        self._MOUSEEVENTF_WHEEL = 0x0800
        self._MOUSEEVENTF_HWHEEL = 0x1000

        self._setup_structures()

    def _setup_structures(self):
        c = self._ctypes

        class _MOUSEINPUT(c.Structure):
            _fields_ = [
                ("dx", c.c_long),
                ("dy", c.c_long),
                ("mouseData", c.c_ulong),
                ("dwFlags", c.c_ulong),
                ("time", c.c_ulong),
                ("dwExtraInfo", c.c_void_p),
            ]

        class _KEYBDINPUT(c.Structure):
            _fields_ = [
                ("wVk", c.c_ushort),
                ("wScan", c.c_ushort),
                ("dwFlags", c.c_ulong),
                ("time", c.c_ulong),
                ("dwExtraInfo", c.c_void_p),
            ]

        class _INPUT_I(c.Union):
            _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]

        class _INPUT(c.Structure):
            _fields_ = [("type", c.c_ulong), ("ii", _INPUT_I)]

        self._INPUT = _INPUT
        self._MOUSEINPUT = _MOUSEINPUT
        self._KEYBDINPUT = _KEYBDINPUT
        self._SendInput.argtypes = [
            ctypes.c_uint,
            ctypes.POINTER(_INPUT),
            ctypes.c_int,
        ]
        self._SendInput.restype = ctypes.c_uint

    def _screen_size(self):
        try:
            return self._user32.GetSystemMetrics(0), self._user32.GetSystemMetrics(1)
        except Exception:
            return _get_screen_size()

    def move(self, x, y):
        w, h = self._screen_size()
        if w <= 0 or h <= 0:
            return
        # Convert 0..1 normalized coordinates to Windows absolute 0..65535.
        abs_x = int(x * 65535 + 0.5)
        abs_y = int(y * 65535 + 0.5)
        abs_x = max(0, min(65535, abs_x))
        abs_y = max(0, min(65535, abs_y))
        inp = self._INPUT()
        inp.type = self._INPUT_MOUSE
        inp.ii.mi = self._MOUSEINPUT(
            dx=abs_x,
            dy=abs_y,
            mouseData=0,
            dwFlags=self._MOUSEEVENTF_MOVE | self._MOUSEEVENTF_ABSOLUTE,
            time=0,
            dwExtraInfo=None,
        )
        self._SendInput(1, self._ctypes.byref(inp), self._ctypes.sizeof(self._INPUT))

    def click(self, button, down):
        flags = {
            "left": (self._MOUSEEVENTF_LEFTDOWN, self._MOUSEEVENTF_LEFTUP),
            "right": (self._MOUSEEVENTF_RIGHTDOWN, self._MOUSEEVENTF_RIGHTUP),
            "middle": (self._MOUSEEVENTF_MIDDLEDOWN, self._MOUSEEVENTF_MIDDLEUP),
        }.get(button, (self._MOUSEEVENTF_LEFTDOWN, self._MOUSEEVENTF_LEFTUP))
        flag = flags[0] if down else flags[1]
        inp = self._INPUT()
        inp.type = self._INPUT_MOUSE
        inp.ii.mi = self._MOUSEINPUT(
            dx=0, dy=0, mouseData=0, dwFlags=flag, time=0, dwExtraInfo=None
        )
        self._SendInput(1, self._ctypes.byref(inp), self._ctypes.sizeof(self._INPUT))

    def scroll(self, direction, clicks):
        delta = int(clicks * 120)
        if direction == "horizontal":
            data = delta << 16
            dwFlags = self._MOUSEEVENTF_HWHEEL
        else:
            data = delta
            dwFlags = self._MOUSEEVENTF_WHEEL
        inp = self._INPUT()
        inp.type = self._INPUT_MOUSE
        inp.ii.mi = self._MOUSEINPUT(
            dx=0, dy=0, mouseData=data, dwFlags=dwFlags, time=0, dwExtraInfo=None
        )
        self._SendInput(1, self._ctypes.byref(inp), self._ctypes.sizeof(self._INPUT))

    def key(self, text, down):
        if len(text) == 1:
            vk_full = self._user32.VkKeyScanA(self._ctypes.c_char(text.encode("latin1", "ignore")))
            if vk_full == -1:
                return
            vk = vk_full & 0xFF
        else:
            name_map = {
                "return": 0x0D, "enter": 0x0D, "tab": 0x09, "space": 0x20,
                "backspace": 0x08, "delete": 0x2E, "escape": 0x1B,
                "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
                "shift": 0x10, "ctrl": 0x11, "alt": 0x12, "win": 0x5B,
            }
            vk = name_map.get(text.lower())
            if vk is None:
                return
        keybdFlags = 0 if down else 0x0002
        inp = self._INPUT()
        inp.type = self._INPUT_KEYBOARD
        inp.ii.ki = self._KEYBDINPUT(
            wVk=vk, wScan=0, dwFlags=keybdFlags, time=0, dwExtraInfo=None
        )
        self._SendInput(1, self._ctypes.byref(inp), self._ctypes.sizeof(self._INPUT))


class _LinuxInjector:
    """Fallback Linux injector using xdotool so we don't require Xlib bindings."""

    def __init__(self):
        self._xdotool = "xdotool"

    def move(self, x, y):
        sw, sh = _get_screen_size()
        px = int(x * sw)
        py = int(y * sh)
        self._run([self._xdotool, "mousemove", "--sync", str(px), str(py)])

    def click(self, button, down):
        btn = {"left": "1", "right": "3", "middle": "2"}.get(button, "1")
        action = "mousedown" if down else "mouseup"
        self._run([self._xdotool, action, btn])

    def key(self, text, down):
        if text == " ":
            text = "space"
        action = "keydown" if down else "keyup"
        self._run([self._xdotool, action, text])

    def scroll(self, direction, clicks):
        button = "4" if clicks > 0 else "5"
        for _ in range(abs(int(clicks))):
            self._run([self._xdotool, "click", button])

    def _run(self, args):
        try:
            import subprocess
            subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except Exception:
            pass


class _DarwinInjector:
    """macOS injector using AppleScript for simple pointer/keyboard events.
    Accessibility permissions are required."""

    def __init__(self):
        self._osascript = "osascript"

    def move(self, x, y):
        sw, sh = _get_screen_size()
        px = int(x * sw)
        py = int(y * sh)
        script = f'tell application "System Events" to set position of first application process whose frontmost is true to {{{px}, {py}}}'
        # Position setting is not a global cursor move; use CLI clic if available.
        self._run(["clic", "mm", str(px), str(py)])

    def click(self, button, down):
        # clic doesn't distinguish down/up well; use AppleScript click for a full click.
        if down:
            self._run(["clic", "cc"])

    def key(self, text, down):
        if len(text) == 1 and text.isalpha():
            key_code = ord(text.lower()) - 97 + 0
            if down:
                script = f'tell application "System Events" to key down (key code {key_code})'
            else:
                script = f'tell application "System Events" to key up (key code {key_code})'
            self._run(["osascript", "-e", script])
        else:
            name_map = {
                "return": "return", "enter": "return", "tab": "tab", "space": "space",
                "backspace": "delete", "delete": "forward delete", "escape": "escape",
            }
            key = name_map.get(text.lower(), text)
            if down:
                script = f'tell application "System Events" to key down "{key}"'
            else:
                script = f'tell application "System Events" to key up "{key}"'
            self._run(["osascript", "-e", script])

    def scroll(self, direction, clicks):
        # Not well supported without Quartz; no-op.
        pass

    def _run(self, args):
        try:
            import subprocess
            subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except Exception:
            pass


# ------------------------------------------------------------------
# Message framing: 1 byte type + 4 bytes length + payload
# ------------------------------------------------------------------
async def send_msg(writer, msg_type: int, payload: bytes) -> None:
    if writer.is_closing():
        raise ConnectionError("Writer is closing")
    header = struct.pack("!BI", msg_type, len(payload))
    writer.write(header + payload)
    await writer.drain()


async def recv_msg(reader) -> tuple[int, bytes]:
    header = await reader.readexactly(5)
    msg_type, length = struct.unpack("!BI", header)
    payload = await reader.readexactly(length)
    return msg_type, payload


# ------------------------------------------------------------------
# Capture sources — platform-specific screen grab isolated here
# ------------------------------------------------------------------
class CaptureSource:
    """Abstract screen capture source."""

    def __init__(self):
        self.width = 0
        self.height = 0

    def capture(self) -> Image.Image:
        raise NotImplementedError


def _image_is_black(img: Image.Image) -> bool:
    """Return True if the image is entirely (or near) black."""
    if img is None or img.size == (0, 0):
        return True
    if img.getbbox() is None:
        return True
    try:
        from PIL import ImageStat
        stat = ImageStat.Stat(img)
        # Mean across all bands; very dark display could legitimately be < 5,
        # but a failed capture is essentially zero.
        return (sum(stat.mean) / max(1, len(stat.mean))) < 1.0
    except Exception:
        return False


class PillowCaptureSource(CaptureSource):
    """Cross-platform capture using Pillow's ImageGrab.

    Works on Windows and macOS and on Linux with an accessible display.
    """

    def capture(self) -> Image.Image:
        # all_screens + include_layered_windows gives the broadest reliable
        # capture on multi-monitor Windows setups.
        img = ImageGrab.grab(all_screens=True, include_layered_windows=True)
        if _image_is_black(img):
            raise RuntimeError("PIL ImageGrab returned an empty/black image")
        if not self.width:
            self.width, self.height = img.size
        return img


class MSSCaptureSource(CaptureSource):
    """Fast cross-platform capture using the mss library (DXGI/GDI on Windows).

    mss generally handles multiple monitors and DPI scaling better than PIL.
    """

    def __init__(self):
        super().__init__()
        import mss
        self._sct = mss.mss()
        monitor = self._sct.monitors[1]  # primary monitor
        self.width = monitor["width"]
        self.height = monitor["height"]

    def capture(self) -> Image.Image:
        import mss
        if getattr(self, "_sct", None) is None:
            self._sct = mss.mss()
        raw = self._sct.grab(self._sct.monitors[1])
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        if _image_is_black(img):
            raise RuntimeError("mss returned an empty/black image")
        return img


class DummyCaptureSource(CaptureSource):
    """Generate a synthetic frame when real capture is unavailable.

    Produces a charcoal gradient with a moving timestamp so the feed is
    obviously alive during testing.
    """

    def __init__(self, width: int = 1280, height: int = 720):
        super().__init__()
        self.width = width
        self.height = height
        self._t = 0.0

    def capture(self) -> Image.Image:
        self._t += 0.05
        img = Image.new("RGB", (self.width, self.height), color=(10, 10, 12))
        from PIL import ImageDraw, ImageFont
        draw = ImageDraw.Draw(img)
        # draw a soft moving bar
        x = int((math.sin(self._t) + 1) * 0.5 * (self.width - 200)) + 100
        draw.ellipse([x - 40, self.height // 2 - 40, x + 40, self.height // 2 + 40],
                     fill=(115, 103, 255))
        # timestamp text
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        except Exception:
            font = ImageFont.load_default()
        text = time.strftime("%H:%M:%S.", time.localtime()) + f"{int(time.time() * 1000) % 1000:03d}"
        draw.text((20, 20), text, fill=(232, 232, 245), font=font)
        draw.text((20, 60), "Vision dummy capture", fill=(138, 140, 155), font=font)
        return img


def make_capture_source() -> CaptureSource:
    """Factory: pick the best available capture source for this platform."""
    # Prefer mss (DXGI/GDI) where available; it is generally more robust than
    # PIL's GDI fallback on Windows multi-monitor setups.
    try:
        src = MSSCaptureSource()
        img = src.capture()
        if img and not _image_is_black(img):
            return src
    except Exception:
        pass

    try:
        src = PillowCaptureSource()
        img = src.capture()
        if img and not _image_is_black(img):
            return src
    except Exception:
        pass

    return DummyCaptureSource()


# ------------------------------------------------------------------
# JPEG encoding
# ------------------------------------------------------------------
def encode_frame(img: Image.Image, config: VisionConfig) -> bytes:
    w, h = img.size
    new_w = max(1, int(w * config.scale))
    new_h = max(1, int(h * config.scale))
    if new_w != w or new_h != h:
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    rgb = img.convert("RGB")
    bio = io.BytesIO()
    rgb.save(bio, "JPEG", quality=config.quality, optimize=True, progressive=False)
    return bio.getvalue()


# ------------------------------------------------------------------
# Vision Streamer — lives in Magnet Client
# ------------------------------------------------------------------
class VisionStreamer(QThread):
    """Background thread that captures the screen and streams JPEG frames."""

    state_changed = Signal(str)        # e.g. connecting/connected/disconnected/error
    error = Signal(str)
    stats = Signal(dict)               # fps/quality/scale/bytes

    def __init__(self, parent=None):
        super().__init__(parent)
        self._host = "127.0.0.1"
        self._port = 0
        self._session_id = ""
        self._config = VisionConfig()
        self._stop_event = threading.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._main_task: Optional[asyncio.Task] = None

    def start_stream(self, host: str, port: int, session_id: str):
        self._host = host
        self._port = port
        self._session_id = session_id
        self._stop_event.clear()
        self._config = VisionConfig()
        self.start()

    def stop_stream(self):
        self._stop_event.set()
        if self._loop and self._loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self._stop_loop(), self._loop)
            except Exception:
                pass

    def update_config(self, quality=None, scale=None, fps=None, paused=None):
        if quality is not None:
            self._config.quality = max(self._config.min_quality, min(self._config.max_quality, int(quality)))
        if scale is not None:
            self._config.scale = max(self._config.min_scale, min(self._config.max_scale, float(scale)))
        if fps is not None:
            self._config.target_fps = max(self._config.min_fps, min(self._config.max_fps, float(fps)))
        if paused is not None:
            self._config.paused = bool(paused)

    def run(self):
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._main_task = self._loop.create_task(self._main())
            self._loop.run_forever()
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if self._loop:
                try:
                    tasks = [t for t in asyncio.all_tasks(self._loop) if not t.done()]
                    for t in tasks:
                        t.cancel()
                    if tasks:
                        self._loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
                except Exception:
                    pass
                try:
                    self._loop.close()
                except Exception:
                    pass
                self._loop = None
            self.state_changed.emit("disconnected")

    async def _stop_loop(self):
        loop = asyncio.get_running_loop()
        try:
            tasks = [t for t in asyncio.all_tasks(loop) if not t.done() and t is not asyncio.current_task()]
            for t in tasks:
                t.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            pass
        finally:
            loop.stop()

    async def _open_connection_with_fallback(self):
        """Open a TCP connection, falling back to 127.0.0.1 for same-machine use.

        Windows Firewall often blocks inbound traffic on the LAN adapter even
        after the user clicks "Allow". Loopback is usually exempt, so if the
        client and agent are on the same machine this fallback gets through.
        """
        last_exc = None
        for host in (self._host, "127.0.0.1"):
            if not host:
                continue
            if host == "127.0.0.1" and self._host == "127.0.0.1":
                continue
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, self._port), timeout=8)
                return reader, writer
            except Exception as e:
                last_exc = e
        raise last_exc or ConnectionError(f"Could not connect to Vision server at {self._host}:{self._port}")

    async def _main(self):
        try:
            self.state_changed.emit("connecting")
            reader, writer = await self._open_connection_with_fallback()
            hello = json.dumps({
                "session_id": self._session_id,
                "platform": platform.system(),
            }).encode("utf-8")
            await send_msg(writer, MSG_HELLO, hello)
            msg_type, payload = await recv_msg(reader)
            if msg_type != MSG_ACK:
                raise ConnectionError("Server did not acknowledge HELLO")
            self.state_changed.emit("connected")
            recv_task = asyncio.create_task(self._recv_controls(reader))
            try:
                await self._stream_loop(writer)
            finally:
                recv_task.cancel()
                try:
                    await recv_task
                except asyncio.CancelledError:
                    pass
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.error.emit(str(e))

    async def _recv_controls(self, reader):
        while True:
            try:
                msg_type, payload = await recv_msg(reader)
                if msg_type == MSG_CONTROL:
                    data = json.loads(payload.decode("utf-8"))
                    self._apply_control(data)
            except asyncio.CancelledError:
                raise
            except Exception:
                break

    def _apply_control(self, data: dict):
        action = data.get("action")
        if action == "pause":
            self._config.paused = True
        elif action == "resume":
            self._config.paused = False
        elif action == "set_quality":
            q = int(data.get("quality", self._config.quality))
            self._config.quality = max(self._config.min_quality, min(self._config.max_quality, q))
        elif action == "set_scale":
            s = float(data.get("scale", self._config.scale))
            self._config.scale = max(self._config.min_scale, min(self._config.max_scale, s))
        elif action == "set_fps":
            f = float(data.get("fps", self._config.target_fps))
            self._config.target_fps = max(self._config.min_fps, min(self._config.max_fps, f))
        elif action == "stop":
            self.stop_stream()
        elif action in ("mouse_move", "pointer_move"):
            x = float(data.get("x", 0.0))
            y = float(data.get("y", 0.0))
            _get_injector().move(x, y)
        elif action in ("mouse_click", "pointer_click"):
            button = str(data.get("button", "left")).lower()
            down = bool(data.get("down", True))
            _get_injector().click(button, down)
        elif action == "key":
            text = str(data.get("text", ""))
            down = bool(data.get("down", True))
            if text:
                _get_injector().key(text, down)
        elif action == "scroll":
            direction = "vertical" if data.get("axis") != "horizontal" else "horizontal"
            clicks = float(data.get("clicks", 1.0))
            _get_injector().scroll(direction, clicks)

    async def _stream_loop(self, writer):
        capture = make_capture_source()
        loop = asyncio.get_event_loop()
        target_interval = 1.0 / self._config.target_fps
        last_frame_time = time.monotonic()
        fps_count = 0
        fps_start = time.monotonic()

        while not self._stop_event.is_set():
            now = time.monotonic()
            wait = target_interval - (now - last_frame_time)
            if wait > 0:
                await asyncio.sleep(wait)
            if self._stop_event.is_set():
                break
            if self._config.paused:
                await asyncio.sleep(0.05)
                continue

            frame_start = time.monotonic()
            try:
                img = await loop.run_in_executor(None, capture.capture)
                encoded = await loop.run_in_executor(None, encode_frame, img, self._config)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.error.emit(f"Capture/encode error: {e}")
                await asyncio.sleep(0.2)
                continue

            if self._stop_event.is_set():
                break

            try:
                await send_msg(writer, MSG_FRAME, encoded)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.error.emit(f"Send error: {e}")
                break

            send_done = time.monotonic()
            elapsed = send_done - frame_start
            self._adapt(elapsed, writer)
            target_interval = 1.0 / self._config.target_fps
            last_frame_time = send_done

            fps_count += 1
            if send_done - fps_start >= 1.0:
                self.stats.emit({
                    "fps": fps_count,
                    "quality": self._config.quality,
                    "scale": self._config.scale,
                    "target_fps": self._config.target_fps,
                    "last_frame_bytes": len(encoded),
                })
                fps_count = 0
                fps_start = send_done

    def _adapt(self, elapsed: float, writer):
        target_interval = 1.0 / self._config.target_fps
        buffer_size = 0
        try:
            buffer_size = writer.transport.get_write_buffer_size()
        except Exception:
            pass

        overloaded = elapsed > target_interval * 1.5 or buffer_size > self._config.buffer_high_water
        underloaded = elapsed < target_interval * 0.6 and buffer_size < self._config.buffer_low_water

        if overloaded:
            # Reduce quality first, then scale, then frame rate.
            if self._config.quality > self._config.min_quality + 5:
                self._config.quality -= 5
            elif self._config.scale > self._config.min_scale + 0.05:
                self._config.scale = round(max(self._config.min_scale, self._config.scale - 0.05), 2)
            else:
                self._config.target_fps = max(self._config.min_fps, self._config.target_fps - 1)
        elif underloaded:
            # Increase quality, then scale. Leave FPS alone until we are close to max quality.
            if self._config.quality < self._config.max_quality - 5:
                self._config.quality += 5
            elif self._config.scale < self._config.max_scale:
                self._config.scale = round(min(self._config.max_scale, self._config.scale + 0.05), 2)


# ------------------------------------------------------------------
# Vision Server — lives in Magnet Agent
# ------------------------------------------------------------------
class VisionServer(QThread):
    """Background TCP server that receives the Vision stream."""

    server_started = Signal(str, int)      # advertise_host, port
    server_stopped = Signal()
    client_connected = Signal(str)       # session_id
    client_disconnected = Signal(str)
    frame_received = Signal(str, bytes)    # session_id, jpeg_bytes
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bind_host = "0.0.0.0"
        self._advertise_host = ""
        self._port = 0
        self._actual_port = 0
        self._stop_event = threading.Event()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._main_task: Optional[asyncio.Task] = None
        self._server: Optional[asyncio.Server] = None
        self._connected_writer: Optional[asyncio.StreamWriter] = None
        self._connected_session: Optional[str] = None
        self._handlers: set[asyncio.Task] = set()

    def start_server(self, port: int = 0, advertise_host: str = ""):
        self._port = port
        self._advertise_host = advertise_host or get_default_ip()
        self._stop_event.clear()
        self._connected_writer = None
        self._connected_session = None
        self._handlers.clear()
        self.start()

    def stop_server(self):
        self._stop_event.set()
        if self._loop and self._loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self._stop_loop(), self._loop)
            except Exception:
                pass

    def send_control(self, control: dict):
        """Queue a control message to the connected client (thread-safe)."""
        if self._loop and self._loop.is_running() and self._connected_writer:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._send_control(control), self._loop)
            except Exception:
                pass

    def get_endpoint(self) -> tuple[str, int]:
        return self._advertise_host, self._actual_port

    def run(self):
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._main_task = self._loop.create_task(self._serve())
            self._loop.run_forever()
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if self._loop:
                try:
                    tasks = [t for t in asyncio.all_tasks(self._loop) if not t.done()]
                    for t in tasks:
                        t.cancel()
                    if tasks:
                        self._loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
                except Exception:
                    pass
                try:
                    self._loop.close()
                except Exception:
                    pass
                self._loop = None
            self.server_stopped.emit()

    async def _stop_loop(self):
        loop = asyncio.get_running_loop()
        if self._server:
            try:
                self._server.close()
            except Exception:
                pass
        try:
            tasks = [t for t in asyncio.all_tasks(loop) if not t.done() and t is not asyncio.current_task()]
            for t in tasks:
                t.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            pass
        finally:
            loop.stop()

    async def _serve(self):
        try:
            self._server = await asyncio.start_server(
                self._handle_client, self._bind_host, self._port)
            sockets = self._server.sockets
            if sockets:
                _, port = sockets[0].getsockname()[:2]
                self._actual_port = port
                self.server_started.emit(self._advertise_host, port)
            async with self._server:
                await self._server.serve_forever()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.error.emit(str(e))

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        session_id = None
        try:
            msg_type, payload = await recv_msg(reader)
            if msg_type != MSG_HELLO:
                return
            info = json.loads(payload.decode("utf-8"))
            session_id = info.get("session_id", "unknown")
            self._connected_session = session_id
            self._connected_writer = writer
            self.client_connected.emit(session_id)
            ack = json.dumps({"ok": True}).encode("utf-8")
            await send_msg(writer, MSG_ACK, ack)

            while True:
                msg_type, payload = await recv_msg(reader)
                if msg_type == MSG_FRAME:
                    self.frame_received.emit(session_id, payload)
                elif msg_type == MSG_CONTROL:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if session_id:
                self.error.emit(f"Vision client {session_id}: {e}")
        finally:
            if session_id:
                self.client_disconnected.emit(session_id)
            self._connected_writer = None
            self._connected_session = None
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _send_control(self, control: dict):
        writer = self._connected_writer
        if not writer or writer.is_closing():
            return
        payload = json.dumps(control).encode("utf-8")
        await send_msg(writer, MSG_CONTROL, payload)
