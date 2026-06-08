from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


def test_control_expression_accepts_raw_keyevent() -> None:
    from app.routers.devices import _parse_control_expression

    assert _parse_control_expression("input keyevent 187") == "input keyevent 187"


def test_script_routes_reject_path_escape(tmp_path: Path, monkeypatch) -> None:
    from app.routers import scripts

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    monkeypatch.setattr(scripts, "SCRIPTS_DIR", scripts_dir)

    with pytest.raises(HTTPException) as exc_info:
        scripts._script_path("../outside.py")

    assert exc_info.value.status_code == 400


def test_run_script_uses_current_python_interpreter(tmp_path: Path, monkeypatch) -> None:
    from app import database
    from app.main import create_app
    from app.routers import scripts

    monkeypatch.setattr(database, "init_db", lambda: None)
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    monkeypatch.setattr(scripts, "SCRIPTS_DIR", scripts_dir)
    script_path = scripts_dir / "whoami.py"
    script_path.write_text(
        "import sys\n"
        "print(sys.executable)\n"
        "print(sys.argv[1])\n",
        encoding="utf-8",
    )

    client = TestClient(create_app())

    response = client.post("/api/scripts/whoami.py/run", params={"device_udid": "device-1"})

    assert response.status_code == 200
    body = response.json()
    assert sys.executable in body["stdout"]
    assert "device-1" in body["stdout"]


def test_query_run_routes_are_not_swallowed_by_script_catch_all(tmp_path: Path, monkeypatch) -> None:
    from app import database
    from app.main import create_app
    from app.routers import scripts

    monkeypatch.setattr(database, "init_db", lambda: None)
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    monkeypatch.setattr(scripts, "SCRIPTS_DIR", scripts_dir)
    script_path = scripts_dir / "smoke.py"
    script_path.write_text("print('script route ok')\n", encoding="utf-8")

    client = TestClient(create_app())

    sync_response = client.post(
        "/api/scripts/run",
        params={"path": "smoke.py", "device_udid": "device-1"},
    )
    stream_response = client.post(
        "/api/scripts/run-stream",
        params={"path": "smoke.py", "device_udid": "device-1", "python_env": sys.executable},
    )

    assert sync_response.status_code == 200
    assert sync_response.json()["returncode"] == 0
    assert "script route ok" in sync_response.json()["stdout"]
    assert stream_response.status_code == 200
    assert stream_response.json()["python_path"] == sys.executable
    assert stream_response.json()["run_id"]


def test_recorded_adb_dsl_script_gets_runtime_object(tmp_path: Path, monkeypatch) -> None:
    from app import database
    from app.main import create_app
    from app.routers import scripts

    monkeypatch.setattr(database, "init_db", lambda: None)
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    monkeypatch.setattr(scripts, "SCRIPTS_DIR", scripts_dir)
    script_path = scripts_dir / "recorded.py"
    script_path.write_text(
        "adb.click(10, 20)\n"
        "adb.swipe((10, 20), (30, 40), 120)\n"
        "adb.back()\n",
        encoding="utf-8",
    )
    commands: list[str] = []

    class FakeADBService:
        def shell(self, udid: str, command: str, timeout: int = 10):
            commands.append(f"{udid}:{command}")

    monkeypatch.setattr(scripts, "ADBService", FakeADBService)

    client = TestClient(create_app())

    response = client.post("/api/scripts/recorded.py/run", params={"device_udid": "device-1"})

    assert response.status_code == 200
    assert response.json()["returncode"] == 0
    assert commands == [
        "device-1:input tap 10 20",
        "device-1:input swipe 10 20 30 40 120",
        "device-1:input keyevent 4",
    ]


def test_recorded_ui_dsl_click_uses_selector_then_fallback(tmp_path: Path, monkeypatch) -> None:
    from app import database
    from app.main import create_app
    from app.routers import scripts

    monkeypatch.setattr(database, "init_db", lambda: None)
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    monkeypatch.setattr(scripts, "SCRIPTS_DIR", scripts_dir)
    script_path = scripts_dir / "ui_recorded.py"
    script_path.write_text(
        'ui.click(text="AI找房", resource_id="com.tencent.mm:id/ai_house", package="com.tencent.mm", fallback=(150, 240))\n',
        encoding="utf-8",
    )
    calls: list[dict] = []

    class FakeUIElementService:
        def click(self, **kwargs):
            calls.append(kwargs)
            return True

    monkeypatch.setattr(scripts, "UIElementService", FakeUIElementService)

    client = TestClient(create_app())

    response = client.post("/api/scripts/ui_recorded.py/run", params={"device_udid": "device-1"})

    assert response.status_code == 200
    assert response.json()["returncode"] == 0
    assert calls == [
        {
            "udid": "device-1",
            "text": "AI找房",
            "resource_id": "com.tencent.mm:id/ai_house",
            "content_desc": None,
            "class_name": None,
            "package": "com.tencent.mm",
            "xpath": None,
            "fallback": (150, 240),
            "ocr_text": None,
            "image_path": None,
            "timeout": 5.0,
        }
    ]


def test_recorded_auto_execute_dsl_click_is_primary_name(tmp_path: Path, monkeypatch) -> None:
    from app import database
    from app.main import create_app
    from app.routers import scripts

    monkeypatch.setattr(database, "init_db", lambda: None)
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    monkeypatch.setattr(scripts, "SCRIPTS_DIR", scripts_dir)
    script_path = scripts_dir / "auto_execute_recorded.py"
    script_path.write_text(
        'auto_execute.click(text="AI找房", package="com.tencent.mm", fallback=(150, 240))\n',
        encoding="utf-8",
    )
    calls: list[dict] = []

    class FakeUIElementService:
        def click(self, **kwargs):
            calls.append(kwargs)
            return True

    monkeypatch.setattr(scripts, "UIElementService", FakeUIElementService)

    client = TestClient(create_app())

    response = client.post("/api/scripts/auto_execute_recorded.py/run", params={"device_udid": "device-1"})

    assert response.status_code == 200
    assert response.json()["returncode"] == 0
    assert calls[0]["udid"] == "device-1"
    assert calls[0]["text"] == "AI找房"
    assert calls[0]["package"] == "com.tencent.mm"
    assert calls[0]["fallback"] == (150, 240)


def test_recorded_auto_execute_input_calls_text_input(tmp_path: Path, monkeypatch) -> None:
    from app import database
    from app.main import create_app
    from app.routers import scripts

    monkeypatch.setattr(database, "init_db", lambda: None)
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    monkeypatch.setattr(scripts, "SCRIPTS_DIR", scripts_dir)
    script_path = scripts_dir / "auto_execute_input.py"
    script_path.write_text('auto_execute.input("深圳 AI 找房")\n', encoding="utf-8")
    calls: list[tuple[str, str]] = []

    class FakeADBService:
        def input_text(self, udid: str, value: str) -> None:
            calls.append((udid, value))

    monkeypatch.setattr(scripts, "ADBService", FakeADBService)

    client = TestClient(create_app())

    response = client.post("/api/scripts/auto_execute_input.py/run", params={"device_udid": "device-1"})

    assert response.status_code == 200
    assert response.json()["returncode"] == 0
    assert calls == [("device-1", "深圳 AI 找房")]


def test_recorded_auto_execute_input_can_target_xpath_before_text(tmp_path: Path, monkeypatch) -> None:
    from app import database
    from app.main import create_app
    from app.routers import scripts

    monkeypatch.setattr(database, "init_db", lambda: None)
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    monkeypatch.setattr(scripts, "SCRIPTS_DIR", scripts_dir)
    script_path = scripts_dir / "auto_execute_targeted_input.py"
    script_path.write_text(
        'auto_execute.input(xpath="/hierarchy/android.widget.FrameLayout[1]/android.widget.EditText[1]", text="1234564")\n',
        encoding="utf-8",
    )
    click_calls: list[dict] = []
    input_calls: list[tuple[str, str]] = []

    class FakeUIElementService:
        def click(self, **kwargs):
            click_calls.append(kwargs)
            return True

    class FakeADBService:
        def input_text(self, udid: str, value: str) -> None:
            input_calls.append((udid, value))

    monkeypatch.setattr(scripts, "UIElementService", FakeUIElementService)
    monkeypatch.setattr(scripts, "ADBService", FakeADBService)

    client = TestClient(create_app())

    response = client.post("/api/scripts/auto_execute_targeted_input.py/run", params={"device_udid": "device-1"})

    assert response.status_code == 200
    assert response.json()["returncode"] == 0
    assert click_calls[0]["xpath"] == "/hierarchy/android.widget.FrameLayout[1]/android.widget.EditText[1]"
    assert input_calls == [("device-1", "1234564")]


def test_recorded_auto_execute_input_prefers_u2_selector(tmp_path: Path, monkeypatch) -> None:
    from app import database
    from app.main import create_app
    from app.routers import scripts

    monkeypatch.setattr(database, "init_db", lambda: None)
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    monkeypatch.setattr(scripts, "SCRIPTS_DIR", scripts_dir)
    script_path = scripts_dir / "auto_execute_u2_input.py"
    script_path.write_text(
        'auto_execute.input(xpath="/hierarchy/android.widget.FrameLayout[1]/android.widget.EditText[1]", text="1234564")\n',
        encoding="utf-8",
    )
    u2_calls: list[dict] = []

    def fake_input_selector(udid: str, value: str, **kwargs) -> bool:
        u2_calls.append({"udid": udid, "value": value, **kwargs})
        return True

    class FakeADBService:
        def input_text(self, udid: str, value: str) -> None:
            raise AssertionError("ADBKeyboard should not be used when u2 selector input succeeds")

    monkeypatch.setattr(scripts.settings, "u2_enabled", True)
    monkeypatch.setattr(scripts.u2_service, "input_selector", fake_input_selector, raising=False)
    monkeypatch.setattr(scripts, "ADBService", FakeADBService)

    client = TestClient(create_app())

    response = client.post("/api/scripts/auto_execute_u2_input.py/run", params={"device_udid": "device-1"})

    assert response.status_code == 200
    assert response.json()["returncode"] == 0
    assert u2_calls == [
        {
            "udid": "device-1",
            "value": "1234564",
            "text": None,
            "resource_id": None,
            "content_desc": None,
            "class_name": None,
            "package": None,
            "xpath": "/hierarchy/android.widget.FrameLayout[1]/android.widget.EditText[1]",
            "clear": True,
            "timeout": 5.0,
        }
    ]


def test_ios_recorded_auto_execute_click_uses_wda_source_and_tap(tmp_path: Path, monkeypatch) -> None:
    from app import database
    from app.main import create_app
    from app.routers import scripts
    from app.services import ui_element_service, wda_service

    monkeypatch.setattr(database, "init_db", lambda: None)
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    monkeypatch.setattr(scripts, "SCRIPTS_DIR", scripts_dir)
    script_path = scripts_dir / "ios_auto_execute.py"
    script_path.write_text(
        'auto_execute.click(xpath="/AppiumAUT/XCUIElementTypeApplication[1]/XCUIElementTypeButton[1]")\n',
        encoding="utf-8",
    )
    ios_xml = """
    <AppiumAUT>
      <XCUIElementTypeApplication type="XCUIElementTypeApplication" name="Leyoujia" x="0" y="0" width="390" height="844">
        <XCUIElementTypeButton type="XCUIElementTypeButton" name="AI找房" label="AI找房" enabled="true" x="40" y="120" width="120" height="48" />
      </XCUIElementTypeApplication>
    </AppiumAUT>
    """
    wda_clicks: list[tuple[str, int, int]] = []

    class FakeGetResponse:
        status_code = 200
        text = ios_xml

    def fake_get(url, timeout, verify):
        return FakeGetResponse()

    def fake_wda_click(udid: str, x: int, y: int, wda_url: str | None = None) -> None:
        wda_clicks.append((udid, x, y))

    monkeypatch.setattr(ui_element_service.requests, "get", fake_get)
    monkeypatch.setattr(wda_service, "click", fake_wda_click)

    client = TestClient(create_app())

    response = client.post(
        "/api/scripts/ios_auto_execute.py/run",
        params={
            "device_udid": "ios-device",
            "platform": "ios",
            "wda_url": "http://127.0.0.1:8100",
        },
    )

    assert response.status_code == 200
    assert response.json()["returncode"] == 0
    assert len(wda_clicks) == 1
    assert wda_clicks[0][1] == 100
    assert wda_clicks[0][2] == 144


def test_recorded_auto_execute_launch_routes_by_platform(tmp_path: Path, monkeypatch) -> None:
    from app import database
    from app.main import create_app
    from app.routers import scripts
    from app.services import wda_service

    monkeypatch.setattr(database, "init_db", lambda: None)
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    monkeypatch.setattr(scripts, "SCRIPTS_DIR", scripts_dir)
    script_path = scripts_dir / "launch_ios.py"
    script_path.write_text('auto_execute.launch("com.example.ios")\n', encoding="utf-8")
    launched: list[tuple[str, str, str | None]] = []

    def fake_launch_app(udid: str, bundle_id: str, wda_url: str | None = None) -> None:
      launched.append((udid, bundle_id, wda_url))

    monkeypatch.setattr(wda_service, "launch_app", fake_launch_app)

    client = TestClient(create_app())
    response = client.post(
        "/api/scripts/launch_ios.py/run",
        params={
            "device_udid": "ios-device",
            "platform": "ios",
            "wda_url": "http://127.0.0.1:8100",
        },
    )

    assert response.status_code == 200
    assert response.json()["returncode"] == 0
    assert launched == [("ios-device", "com.example.ios", "http://127.0.0.1:8100")]
