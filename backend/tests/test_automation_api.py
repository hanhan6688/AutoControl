from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

class TestAutomationHealth:
    def test_health(self):
        resp = client.get("/api/automation/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestAutomationRuns:
    def test_create_run(self):
        response = client.post("/api/automation/runs", json={
            "udid": "emulator-5554",
            "platform": "android",
            "steps": [
                {"id": "s1", "title": "Tap", "action": {"type": "tap", "params": {"x": 100, "y": 200}}}
            ]
        })
        assert response.status_code == 200
        data = response.json()
        assert "run_id" in data

    def test_get_run(self):
        create_resp = client.post("/api/automation/runs", json={
            "udid": "emulator-5554",
            "platform": "android",
            "steps": []
        })
        run_id = create_resp.json()["run_id"]
        response = client.get(f"/api/automation/runs/{run_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["udid"] == "emulator-5554"

    def test_get_run_not_found(self):
        response = client.get("/api/automation/runs/nonexistent")
        assert response.status_code == 404

class TestLocatorPreview:
    @patch("app.routers.automation.LocatorResolver")
    @patch("app.routers.automation.AndroidDriver")
    def test_locator_preview_returns_result(self, mock_driver_cls, mock_resolver_cls):
        from app.automation.locators.resolver import ResolveResult
        from app.automation.core.models import Locator, LocatorType
        mock_resolver = MagicMock()
        mock_resolver.resolve.return_value = ResolveResult(found=True, resolved_locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/btn"), attempted_count=1)
        mock_resolver_cls.return_value = mock_resolver
        resp = client.post("/api/automation/locators/preview?udid=emulator-5554&platform=android", json={"primary": {"type": "resource_id", "value": "com.demo:id/btn"}, "fallbacks": []})
        assert resp.status_code == 200
        assert resp.json()["found"] is True

class TestAssertionValidate:
    @patch("app.routers.automation.AssertionEngine")
    @patch("app.routers.automation.AndroidDriver")
    def test_assertion_validate_returns_result(self, mock_driver_cls, mock_engine_cls):
        from app.automation.assertions.engine import AssertionResult
        from app.automation.core.models import AssertionType
        mock_engine = MagicMock()
        mock_engine.evaluate.return_value = AssertionResult(passed=True, assertion_type=AssertionType.EXISTS, message="Found")
        mock_engine_cls.return_value = mock_engine
        resp = client.post("/api/automation/assertions/validate?udid=emulator-5554&platform=android", json={"type": "exists", "locator": {"type": "resource_id", "value": "com.demo:id/btn"}})
        assert resp.status_code == 200
        assert resp.json()["passed"] is True
