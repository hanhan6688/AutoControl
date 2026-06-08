from __future__ import annotations

from fastapi.testclient import TestClient


async def test_safe_websocket_send_ignores_closed_connection() -> None:
    from app.routers.devices import _safe_send_bytes, _safe_send_text

    class ClosedWebSocket:
        async def send_text(self, value: str) -> None:
            raise RuntimeError("Unexpected ASGI message 'websocket.send', after sending 'websocket.close'")

        async def send_bytes(self, value: bytes) -> None:
            raise RuntimeError("Unexpected ASGI message 'websocket.send', after sending 'websocket.close'")

    websocket = ClosedWebSocket()

    assert await _safe_send_text(websocket, "x") is False
    assert await _safe_send_bytes(websocket, b"x") is False


def test_screenshot_route_can_capture_ios_via_wda(tmp_path, monkeypatch) -> None:
    from app import database
    from app.config import settings
    from app.main import create_app
    from app.services import wda_service

    monkeypatch.setattr(database, "init_db", lambda: None)
    monkeypatch.setattr(type(settings), "static_dir", property(lambda self: tmp_path))
    monkeypatch.setattr(wda_service, "screenshot", lambda udid, wda_url=None: b"png-bytes")

    client = TestClient(create_app())
    response = client.post(
        "/api/devices/ios-device/screenshot",
        params={"platform": "ios", "wda_url": "http://127.0.0.1:8100"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["udid"] == "ios-device"
    assert body["url"].startswith("/static/uploads/devices/ios-device/")
    assert (tmp_path / body["url"].removeprefix("/static/")).read_bytes() == b"png-bytes"


def test_tap_route_can_tap_ios_via_wda(monkeypatch) -> None:
    from app import database
    from app.main import create_app
    from app.services import wda_service

    monkeypatch.setattr(database, "init_db", lambda: None)
    taps: list[tuple[str, int, int, str | None]] = []
    monkeypatch.setattr(
        wda_service,
        "click",
        lambda udid, x, y, wda_url=None: taps.append((udid, x, y, wda_url)),
    )

    client = TestClient(create_app())
    response = client.post(
        "/api/devices/ios-device/tap",
        json={"x": 30, "y": 40, "platform": "ios", "wda_url": "http://127.0.0.1:8100"},
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert taps == [("ios-device", 30, 40, "http://127.0.0.1:8100")]


def test_touch_routes_are_registered_for_live_android_control(monkeypatch) -> None:
    from app import database
    from app.main import create_app
    from app.routers import devices

    monkeypatch.setattr(database, "init_db", lambda: None)
    calls: list[tuple[str, str]] = []

    class FakeRealtimeControl:
        def send(self, udid: str, command: str) -> None:
            calls.append((udid, command))

        def close(self, udid: str) -> None:
            pass

    class FakeADBService:
        def shell(self, udid: str, command: str, timeout: int = 10):
            raise AssertionError("touch routes should use persistent realtime control")

    monkeypatch.setattr(devices, "ADBService", FakeADBService)
    monkeypatch.setattr(devices, "realtime_adb_control_service", FakeRealtimeControl())

    client = TestClient(create_app())
    routes = [
        ("down", "DOWN", 5),
        ("move", "MOVE", 5),
        ("up", "UP", 5),
    ]

    for action, event_name, timeout in routes:
        response = client.post(
            f"/api/devices/android-device/touch/{action}",
            params={"x": 12, "y": 34, "platform": "android"},
        )
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert calls[-1] == ("android-device", f"input motionevent {event_name} 12 34")


async def test_websocket_drag_control_uses_single_swipe_command(monkeypatch) -> None:
    from app.routers import devices

    calls: list[tuple[str, str]] = []

    class FakeRealtimeControl:
        def send(self, udid: str, command: str) -> None:
            calls.append((udid, command))

    class FakeADBService:
        pass

    class FakeScrcpyControlService:
        def get(self, udid: str):
            return None

    monkeypatch.setattr(devices, "realtime_adb_control_service", FakeRealtimeControl())
    monkeypatch.setattr(devices, "scrcpy_control_service", FakeScrcpyControlService())

    await devices._handle_control_command(
        "android-device",
        FakeADBService(),
        {
            "type": "drag",
            "x1": 10,
            "y1": 20,
            "x2": 300,
            "y2": 400,
            "drag_duration_ms": 650,
        },
    )

    assert calls == [("android-device", "input swipe 10 20 300 400 650")]


async def test_websocket_control_prefers_scrcpy_native_client(monkeypatch) -> None:
    from app.routers import devices

    scrcpy_calls: list[tuple[str, tuple[int, ...]]] = []
    adb_calls: list[tuple[str, str]] = []

    class FakeScrcpyClient:
        def swipe(self, *args: int) -> None:
            scrcpy_calls.append(("swipe", args))

    class FakeScrcpyControlService:
        def get(self, udid: str):
            return FakeScrcpyClient()

        def unregister(self, udid: str, client) -> None:
            pass

    class FakeRealtimeControl:
        def send(self, udid: str, command: str) -> None:
            adb_calls.append((udid, command))

    class FakeADBService:
        pass

    monkeypatch.setattr(devices, "scrcpy_control_service", FakeScrcpyControlService())
    monkeypatch.setattr(devices, "realtime_adb_control_service", FakeRealtimeControl())

    await devices._handle_control_command(
        "android-device",
        FakeADBService(),
        {
            "type": "swipe",
            "x1": 10,
            "y1": 20,
            "x2": 300,
            "y2": 400,
            "duration_ms": 650,
        },
    )

    assert scrcpy_calls == [("swipe", (10, 20, 300, 400, 650))]
    assert adb_calls == []


async def test_websocket_tap_with_locator_prefers_ui_element_service(monkeypatch) -> None:
    from app.routers import devices

    ui_click_calls: list[dict] = []
    scrcpy_calls: list[tuple[str, tuple[int, ...]]] = []
    adb_calls: list[tuple[str, str]] = []

    class FakeUIElementService:
        def click(self, **kwargs):
            ui_click_calls.append(kwargs)
            return True

    class FakeScrcpyClient:
        def tap(self, *args: int) -> None:
            scrcpy_calls.append(("tap", args))

    class FakeScrcpyControlService:
        def get(self, udid: str):
            return FakeScrcpyClient()

        def unregister(self, udid: str, client) -> None:
            pass

    class FakeRealtimeControl:
        def send(self, udid: str, command: str) -> None:
            adb_calls.append((udid, command))

    class FakeADBService:
        def input_text(self, udid: str, value: str) -> None:
            raise AssertionError("locator tap should not route through adb text input")

    monkeypatch.setattr(devices, "UIElementService", FakeUIElementService)
    monkeypatch.setattr(devices, "scrcpy_control_service", FakeScrcpyControlService())
    monkeypatch.setattr(devices, "realtime_adb_control_service", FakeRealtimeControl())

    await devices._handle_control_command(
        "android-device",
        FakeADBService(),
        {
            "type": "tap",
            "x": 12,
            "y": 34,
            "locator": {
                "resource_id": "com.demo:id/login",
                "package": "com.demo",
                "fallback": [12, 34],
            },
        },
    )

    assert len(ui_click_calls) == 1
    assert ui_click_calls[0]["resource_id"] == "com.demo:id/login"
    assert ui_click_calls[0]["package"] == "com.demo"
    assert ui_click_calls[0]["fallback"] == (12, 34)
    assert scrcpy_calls == []
    assert adb_calls == []


async def test_websocket_tap_without_locator_keeps_scrcpy_path(monkeypatch) -> None:
    from app.routers import devices

    scrcpy_calls: list[tuple[str, tuple[int, ...]]] = []

    class FakeScrcpyClient:
        def tap(self, *args: int) -> None:
            scrcpy_calls.append(("tap", args))

    class FakeScrcpyControlService:
        def get(self, udid: str):
            return FakeScrcpyClient()

        def unregister(self, udid: str, client) -> None:
            pass

    class FakeRealtimeControl:
        def send(self, udid: str, command: str) -> None:
            raise AssertionError("plain tap should stay on scrcpy path")

    class FakeADBService:
        pass

    monkeypatch.setattr(devices, "scrcpy_control_service", FakeScrcpyControlService())
    monkeypatch.setattr(devices, "realtime_adb_control_service", FakeRealtimeControl())

    await devices._handle_control_command(
        "android-device",
        FakeADBService(),
        {"type": "tap", "x": 80, "y": 120},
    )

    assert scrcpy_calls == [("tap", (80, 120))]


def test_locate_ui_element_route_returns_generated_code(monkeypatch) -> None:
    from app import database
    from app.main import create_app
    from app.routers import devices
    from app.services.ui_element_service import MobileBounds, MobileUiElement, UiLocateResult

    monkeypatch.setattr(database, "init_db", lambda: None)

    class FakeUIElementService:
        def locate_device_point(self, **kwargs):
            return UiLocateResult(
                found=True,
                element=MobileUiElement(
                    platform="android",
                    package="com.tencent.mm",
                    class_name="android.widget.Button",
                    text="AI找房",
                    content_desc="AI找房入口",
                    resource_id="com.tencent.mm:id/ai_house",
                    clickable=True,
                    enabled=True,
                    bounds=MobileBounds(left=100, top=200, right=420, bottom=300),
                    xpath='//android.widget.Button[@resource-id="com.tencent.mm:id/ai_house"]',
                    hierarchy_xpath="/hierarchy/android.widget.FrameLayout[1]/android.widget.Button[1]",
                    selector={
                        "resource_id": "com.tencent.mm:id/ai_house",
                        "text": "AI找房",
                        "content_desc": "AI找房入口",
                        "class_name": "android.widget.Button",
                        "package": "com.tencent.mm",
                    },
                    depth=3,
                    index=2,
                ),
                generated_code='auto_execute.click(text="AI找房", resource_id="com.tencent.mm:id/ai_house", package="com.tencent.mm", fallback=(150, 240))',
                message="element located",
            )

    monkeypatch.setattr(devices, "UIElementService", FakeUIElementService)

    client = TestClient(create_app())
    response = client.post(
        "/api/devices/device-1/ui/locate",
        json={"x": 150, "y": 240, "platform": "android", "package_name": "com.tencent.mm"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["found"] is True
    assert body["element"]["text"] == "AI找房"
    assert body["generated_code"].startswith("auto_execute.click(")
