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


class TestImageCompare:
    @patch("app.routers.automation._find_template_in_screenshot")
    @patch("app.routers.automation.AndroidDriver")
    def test_image_compare_matched(self, mock_driver_cls, mock_find):
        from app.automation.assertions.engine import TemplateMatch
        mock_find.return_value = TemplateMatch(score=0.96, location=(120, 340))
        resp = client.post(
            "/api/automation/image/compare",
            params={"udid": "emulator-5554", "platform": "android"},
            json={"image_path": "templates/btn.png", "threshold": 0.9},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["matched"] is True
        assert data["score"] == 0.96

    @patch("app.routers.automation._find_template_in_screenshot")
    @patch("app.routers.automation.AndroidDriver")
    def test_image_compare_not_matched(self, mock_driver_cls, mock_find):
        from app.automation.assertions.engine import TemplateMatch
        mock_find.return_value = TemplateMatch(score=0.42, location=None)
        resp = client.post(
            "/api/automation/image/compare",
            params={"udid": "emulator-5554", "platform": "android"},
            json={"image_path": "templates/btn.png", "threshold": 0.9},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["matched"] is False

    @patch("app.routers.automation.AndroidDriver")
    def test_image_compare_no_path(self, mock_driver_cls):
        resp = client.post(
            "/api/automation/image/compare",
            params={"udid": "emulator-5554", "platform": "android"},
            json={"threshold": 0.9},
        )
        assert resp.status_code == 422  # Pydantic validation error for missing required field


class TestImageCaptureTemplate:
    @patch("app.routers.automation.AndroidDriver")
    def test_capture_template(self, mock_driver_cls):
        mock_driver = MagicMock()
        mock_driver.screenshot.return_value = b"\x89PNG_fake"
        mock_driver_cls.return_value = mock_driver
        resp = client.post(
            "/api/automation/image/capture-template",
            params={"udid": "emulator-5554", "platform": "android"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "template_path" in data


class TestAutoGLMPlan:
    def test_autoglm_plan_builds(self):
        resp = client.post(
            "/api/automation/autoglm/plan",
            json={
                "case_id": 123,
                "target_app": "贝壳找房",
                "platform": "android",
                "launch_app_id": "com.ke.app",
                "preconditions": ["应用已安装"],
                "steps": ["打开应用", "点击AI学区顾问"],
                "expected_result": "进入AI学区顾问页面",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["case_id"] == 123
        assert len(data["checkpoints"]) >= 1
        assert data["checkpoints"][0]["goal"] == "打开应用"


class TestAutoGLMValidateCheckpoint:
    @patch("app.routers.automation.CheckpointValidator")
    @patch("app.routers.automation.AndroidDriver")
    def test_validate_checkpoint_passes(self, mock_driver_cls, mock_validator_cls):
        from app.automation.autoglm.checkpoint_validator import ValidationResult
        mock_validator = MagicMock()
        mock_validator.validate.return_value = ValidationResult(passed=True, failed=False, message="Success signal matched")
        mock_validator_cls.return_value = mock_validator
        resp = client.post(
            "/api/automation/autoglm/validate-checkpoint",
            params={"udid": "emulator-5554", "platform": "android"},
            json={
                "id": "cp_1",
                "goal": "进入首页",
                "success_signals": ["首页"],
                "max_steps": 12,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is True


class TestRunEvents:
    def test_get_events_for_existing_run(self):
        create_resp = client.post("/api/automation/runs", json={
            "udid": "emulator-5554",
            "platform": "android",
            "steps": [],
        })
        run_id = create_resp.json()["run_id"]
        resp = client.get(f"/api/automation/runs/{run_id}/events")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_get_events_for_nonexistent_run(self):
        resp = client.get("/api/automation/runs/nonexistent/events")
        assert resp.status_code == 404
