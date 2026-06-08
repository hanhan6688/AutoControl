from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient


def test_pc_agent_run_stream_returns_ndjson_events(monkeypatch) -> None:
    from app.main import create_app
    from app.routers import pc_browser

    class FakeAgent:
        async def iter_task_events(self, *, task, session=None, max_steps=8):
            yield {"event": "start", "phase": "agent", "message": task, "session": session, "max_steps": max_steps, "run_id": "fake-run-id"}
            yield {"event": "result", "phase": "result", "run_result": "passed", "message": "完成"}

    monkeypatch.setattr(pc_browser, "PCBrowserAgentService", lambda: FakeAgent())

    client = TestClient(create_app())
    with client.stream(
        "POST",
        "/api/pc-browser/agent/run/stream",
        json={"task": "打开首页并检查标题", "session": "pc", "max_steps": 3},
    ) as response:
        assert response.status_code == 200
        events = [json.loads(line) for line in response.iter_lines() if line]

    assert events[0]["event"] == "start"
    assert events[0]["session"] == "pc"
    assert events[0]["max_steps"] == 3
    assert events[-1]["event"] == "result"
    assert events[-1]["run_result"] == "passed"


def test_pc_agent_run_stream_requires_task() -> None:
    from app.main import create_app

    client = TestClient(create_app())
    response = client.post("/api/pc-browser/agent/run/stream", json={"task": "  "})

    assert response.status_code == 422


def test_pc_agent_model_config_endpoints(monkeypatch) -> None:
    from app.config import settings
    from app.main import create_app

    monkeypatch.setattr(settings, "pc_agent_enabled", True)
    monkeypatch.setattr(settings, "pc_agent_provider", "openai_compatible")
    monkeypatch.setattr(settings, "pc_agent_base_url", "https://old.example/v1")
    monkeypatch.setattr(settings, "pc_agent_model", "old-model")
    monkeypatch.setattr(settings, "pc_agent_api_key", "old-secret")

    client = TestClient(create_app())

    presets = client.get("/api/pc-browser/agent/model/presets")
    assert presets.status_code == 200
    assert any(item["id"] == "zhipu-glm" for item in presets.json()["presets"])

    update = client.put(
        "/api/pc-browser/agent/model/config",
        json={
            "enabled": True,
            "provider": "custom_openai",
            "base_url": "http://127.0.0.1:9000/v1",
            "model": "local-model",
            "api_key": "new-secret",
            "timeout_seconds": 41,
            "temperature": 0.2,
            "max_tokens": 901,
        },
    )
    assert update.status_code == 200
    payload = update.json()
    assert payload["provider"] == "custom_openai"
    assert payload["base_url"] == "http://127.0.0.1:9000/v1"
    assert payload["model"] == "local-model"
    assert payload["api_key_masked"] == "ne******et"
    assert "new-secret" not in json.dumps(payload)

    current = client.get("/api/pc-browser/agent/model/config")
    assert current.status_code == 200
    assert current.json()["model"] == "local-model"


def test_pc_agent_model_test_endpoint_uses_model_service(monkeypatch) -> None:
    from app.main import create_app
    from app.routers import pc_browser

    class FakeModelService:
        def decide(self, context):
            return {"action": "finish", "message": "连接成功"}

    monkeypatch.setattr(pc_browser, "PCAgentModelService", lambda: FakeModelService())

    client = TestClient(create_app())
    response = client.post("/api/pc-browser/agent/model/test", json={"task": "测试连接"})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["decision"]["action"] == "finish"


def test_pc_agent_model_test_endpoint_accepts_transient_config(monkeypatch) -> None:
    from app.main import create_app
    from app.routers import pc_browser

    captured = {}

    class FakeModelService:
        def __init__(self, config_provider=None):
            self.config_provider = config_provider

        def decide(self, context):
            config = self.config_provider()
            captured["provider"] = config.provider
            captured["model"] = config.model
            return {"action": "finish", "message": "连接成功"}

    monkeypatch.setattr(pc_browser, "PCAgentModelService", FakeModelService)

    client = TestClient(create_app())
    response = client.post(
        "/api/pc-browser/agent/model/test",
        json={
            "task": "测试连接",
            "config": {
                "enabled": True,
                "provider": "anthropic_compatible",
                "base_url": "https://api.minimaxi.com/anthropic",
                "model": "MiniMax-M2.7",
                "api_key": "temporary-secret",
                "timeout_seconds": 30,
                "temperature": 0.1,
                "max_tokens": 700,
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert captured == {"provider": "anthropic_compatible", "model": "MiniMax-M2.7"}


def test_leyoujia_auth_endpoints_use_fixed_state_path(tmp_path: Path, monkeypatch) -> None:
    from app.main import create_app
    from app.routers import pc_browser

    calls = []
    state_path = tmp_path / "leyoujia-prod.json"

    class FakeBrowserService:
        def open(self, url, session=None, headed=False):
            calls.append(("open", url, session, headed))
            return type("Session", (), {"session_id": session, "title": "登录", "url": url})()

        def save_state(self, path, session=None):
            calls.append(("save", Path(path), session))
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text("{}", encoding="utf-8")

        def load_state(self, path, session=None):
            calls.append(("load", Path(path), session))

    monkeypatch.setattr(pc_browser, "_browser_service", FakeBrowserService())
    monkeypatch.setattr(pc_browser, "_leyoujia_state_path", lambda env="test": state_path)

    client = TestClient(create_app())
    opened = client.post("/api/pc-browser/auth/leyoujia/open-login", json={"session": "pc-autoexecute", "env": "prod"})
    saved = client.post("/api/pc-browser/auth/leyoujia/save", json={"session": "pc-autoexecute", "env": "prod"})
    loaded = client.post("/api/pc-browser/auth/leyoujia/load", json={"session": "pc-autoexecute", "env": "prod"})

    assert opened.status_code == 200
    assert saved.status_code == 200
    assert loaded.status_code == 200
    assert saved.json()["env"] == "prod"
    assert saved.json()["target_url"] == "https://zero-ai.leyoujia.com/"
    assert calls == [
        ("open", pc_browser.LEYOUJIA_PROD_LOGIN_URL, "pc-autoexecute", True),
        ("save", state_path, "pc-autoexecute"),
        ("load", state_path, "pc-autoexecute"),
    ]


def test_resume_nonexistent_run_returns_404() -> None:
    from app.main import create_app

    client = TestClient(create_app())
    response = client.post("/api/pc-browser/agent/run/nonexistent-id/resume")
    assert response.status_code == 404


def test_cancel_nonexistent_run_returns_404() -> None:
    from app.main import create_app

    client = TestClient(create_app())
    response = client.post("/api/pc-browser/agent/run/nonexistent-id/cancel")
    assert response.status_code == 404
