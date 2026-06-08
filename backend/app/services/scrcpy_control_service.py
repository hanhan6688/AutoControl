from __future__ import annotations

import socket
import struct
import threading
import time


SCRCPY_CONTROL_TOUCH = 2
SCRCPY_CONTROL_KEYCODE = 0
SCRCPY_CONTROL_TEXT = 1

ANDROID_ACTION_DOWN = 0
ANDROID_ACTION_UP = 1
ANDROID_ACTION_MOVE = 2

ANDROID_KEYEVENT_DOWN = 0
ANDROID_KEYEVENT_UP = 1

SCRCPY_POINTER_ID_GENERIC_FINGER = (1 << 64) - 2
PRESSURE_MAX = 0xFFFF
PRESSURE_NONE = 0


class ScrcpyControlError(RuntimeError):
    pass


class ScrcpyControlClient:
    def __init__(self, sock: socket.socket, screen_width: int, screen_height: int) -> None:
        self.sock = sock
        self.screen_width = max(1, int(screen_width))
        self.screen_height = max(1, int(screen_height))
        self._lock = threading.Lock()

    def touch_down(self, x: int, y: int) -> None:
        self._send_touch(ANDROID_ACTION_DOWN, x, y, PRESSURE_MAX)

    def touch_move(self, x: int, y: int) -> None:
        self._send_touch(ANDROID_ACTION_MOVE, x, y, PRESSURE_MAX)

    def touch_up(self, x: int, y: int) -> None:
        self._send_touch(ANDROID_ACTION_UP, x, y, PRESSURE_NONE)

    def tap(self, x: int, y: int) -> None:
        self.touch_down(x, y)
        time.sleep(0.035)
        self.touch_up(x, y)

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        duration_ms = max(60, min(int(duration_ms), 2000))
        steps = max(4, min(24, duration_ms // 16))
        delay = duration_ms / steps / 1000
        self.touch_down(x1, y1)
        for index in range(1, steps):
            ratio = index / steps
            x = round(x1 + (x2 - x1) * ratio)
            y = round(y1 + (y2 - y1) * ratio)
            time.sleep(delay)
            self.touch_move(x, y)
        time.sleep(delay)
        self.touch_up(x2, y2)

    def key(self, keycode: int) -> None:
        self._send_key(ANDROID_KEYEVENT_DOWN, keycode)
        self._send_key(ANDROID_KEYEVENT_UP, keycode)

    def text(self, value: str) -> None:
        payload = value.encode("utf-8")[:300]
        self._send(bytes([SCRCPY_CONTROL_TEXT]) + len(payload).to_bytes(4, "big") + payload)

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def _send_touch(self, action: int, x: int, y: int, pressure: int) -> None:
        self._send(serialize_touch_message(
            action=action,
            x=x,
            y=y,
            screen_width=self.screen_width,
            screen_height=self.screen_height,
            pressure=pressure,
        ))

    def _send_key(self, action: int, keycode: int) -> None:
        self._send(serialize_keycode_message(action=action, keycode=keycode))

    def _send(self, payload: bytes) -> None:
        with self._lock:
            try:
                self.sock.sendall(payload)
            except OSError as exc:
                raise ScrcpyControlError(f"scrcpy control socket send failed: {exc}") from exc


class ScrcpyControlService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: dict[str, ScrcpyControlClient] = {}

    def register(self, udid: str, client: ScrcpyControlClient) -> None:
        with self._lock:
            previous = self._clients.get(udid)
            self._clients[udid] = client
        if previous is not None and previous is not client:
            previous.close()

    def unregister(self, udid: str, client: ScrcpyControlClient | None = None) -> None:
        with self._lock:
            current = self._clients.get(udid)
            if current is None:
                return
            if client is not None and current is not client:
                return
            self._clients.pop(udid, None)
        current.close()

    def get(self, udid: str) -> ScrcpyControlClient | None:
        with self._lock:
            return self._clients.get(udid)


def serialize_touch_message(
    *,
    action: int,
    x: int,
    y: int,
    screen_width: int,
    screen_height: int,
    pressure: int = PRESSURE_MAX,
    pointer_id: int = SCRCPY_POINTER_ID_GENERIC_FINGER,
    action_button: int = 0,
    buttons: int = 0,
) -> bytes:
    return struct.pack(
        ">BBQiiHHHII",
        SCRCPY_CONTROL_TOUCH,
        int(action),
        int(pointer_id),
        int(x),
        int(y),
        max(1, int(screen_width)),
        max(1, int(screen_height)),
        max(0, min(int(pressure), PRESSURE_MAX)),
        int(action_button),
        int(buttons),
    )


def serialize_keycode_message(*, action: int, keycode: int, repeat: int = 0, metastate: int = 0) -> bytes:
    return struct.pack(
        ">BBIII",
        SCRCPY_CONTROL_KEYCODE,
        int(action),
        int(keycode),
        int(repeat),
        int(metastate),
    )


scrcpy_control_service = ScrcpyControlService()
