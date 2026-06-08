from __future__ import annotations

import pytest

from app.services.touch_control_service import TouchControlService


@pytest.mark.asyncio
async def test_android_touch_control_uses_persistent_realtime_shell(monkeypatch) -> None:
    from app.services import touch_control_service

    calls: list[tuple[str, str]] = []

    class FakeRealtimeControl:
        def send(self, udid: str, command: str) -> None:
            calls.append((udid, command))

    class FakeADBService:
        def shell(self, *args, **kwargs):
            raise AssertionError("android realtime control should not spawn one adb shell per event")

    monkeypatch.setattr(touch_control_service, "realtime_adb_control_service", FakeRealtimeControl())

    service = TouchControlService(adb=FakeADBService())

    await service.touch_down("android-1", 1, 2)
    await service.touch_move("android-1", 3, 4)
    await service.touch_up("android-1", 5, 6)
    await service.tap("android-1", 7, 8)
    await service.swipe("android-1", 9, 10, 11, 12, 350)
    await service.long_press("android-1", 13, 14, 900)
    await service.key("android-1", 4)

    assert calls == [
        ("android-1", "input motionevent DOWN 1 2"),
        ("android-1", "input motionevent MOVE 3 4"),
        ("android-1", "input motionevent UP 5 6"),
        ("android-1", "input tap 7 8"),
        ("android-1", "input swipe 9 10 11 12 350"),
        ("android-1", "input swipe 13 14 13 14 900"),
        ("android-1", "input keyevent 4"),
    ]
