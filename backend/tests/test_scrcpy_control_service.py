from __future__ import annotations

from app.services.scrcpy_control_service import (
    ANDROID_ACTION_DOWN,
    ANDROID_ACTION_UP,
    ANDROID_KEYEVENT_DOWN,
    PRESSURE_MAX,
    PRESSURE_NONE,
    SCRCPY_POINTER_ID_GENERIC_FINGER,
    ScrcpyControlClient,
    serialize_keycode_message,
    serialize_touch_message,
)


def test_serialize_touch_message_matches_scrcpy_protocol() -> None:
    payload = serialize_touch_message(
        action=ANDROID_ACTION_DOWN,
        x=123,
        y=456,
        screen_width=1080,
        screen_height=2400,
        pressure=PRESSURE_MAX,
    )

    assert len(payload) == 32
    assert payload[0] == 2
    assert payload[1] == ANDROID_ACTION_DOWN
    assert int.from_bytes(payload[2:10], "big") == SCRCPY_POINTER_ID_GENERIC_FINGER
    assert int.from_bytes(payload[10:14], "big", signed=True) == 123
    assert int.from_bytes(payload[14:18], "big", signed=True) == 456
    assert int.from_bytes(payload[18:20], "big") == 1080
    assert int.from_bytes(payload[20:22], "big") == 2400
    assert int.from_bytes(payload[22:24], "big") == PRESSURE_MAX
    assert int.from_bytes(payload[24:28], "big") == 0
    assert int.from_bytes(payload[28:32], "big") == 0


def test_serialize_touch_up_uses_zero_pressure() -> None:
    payload = serialize_touch_message(
        action=ANDROID_ACTION_UP,
        x=123,
        y=456,
        screen_width=1080,
        screen_height=2400,
        pressure=PRESSURE_NONE,
    )

    assert payload[1] == ANDROID_ACTION_UP
    assert int.from_bytes(payload[22:24], "big") == 0


def test_serialize_keycode_message_matches_scrcpy_protocol() -> None:
    payload = serialize_keycode_message(action=ANDROID_KEYEVENT_DOWN, keycode=4)

    assert len(payload) == 14
    assert payload[0] == 0
    assert payload[1] == ANDROID_KEYEVENT_DOWN
    assert int.from_bytes(payload[2:6], "big") == 4
    assert int.from_bytes(payload[6:10], "big") == 0
    assert int.from_bytes(payload[10:14], "big") == 0


def test_client_sends_swipe_as_native_touch_sequence() -> None:
    class FakeSocket:
        def __init__(self) -> None:
            self.payloads: list[bytes] = []

        def sendall(self, payload: bytes) -> None:
            self.payloads.append(payload)

    sock = FakeSocket()
    client = ScrcpyControlClient(sock, screen_width=1080, screen_height=2400)

    client.swipe(10, 20, 100, 200, duration_ms=80)

    assert sock.payloads[0][1] == ANDROID_ACTION_DOWN
    assert sock.payloads[-1][1] == ANDROID_ACTION_UP
    assert any(payload[1] == 2 for payload in sock.payloads[1:-1])
