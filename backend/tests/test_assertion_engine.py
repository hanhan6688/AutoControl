from unittest.mock import MagicMock, patch

import numpy as np

from app.automation.assertions.engine import AssertionEngine, AssertionResult, TemplateMatch
from app.automation.core.driver import DeviceDriver, ElementRef
from app.automation.core.models import (
    AssertionSpec,
    AssertionType,
    Locator,
    LocatorType,
)


def _make_driver(
    found=True, text=None, app_pkg="com.demo.app", source='<node text="登录成功"/>'
):
    driver = MagicMock(spec=DeviceDriver)
    driver.find_element.return_value = ElementRef(
        found=found,
        locator_type="resource_id",
        locator_value="com.demo:id/btn",
        text=text,
    )
    driver.current_app.return_value = {"package": app_pkg}
    driver.dump_source.return_value = source
    return driver


class TestAssertionEngineExists:
    def test_exists_pass(self):
        driver = _make_driver(found=True)
        spec = AssertionSpec(
            type=AssertionType.EXISTS,
            locator=Locator(type=LocatorType.RESOURCE_ID, value="com.demo:id/btn"),
        )
        assert AssertionEngine(driver).evaluate(spec).passed is True

    def test_exists_fail(self):
        driver = _make_driver(found=False)
        spec = AssertionSpec(
            type=AssertionType.EXISTS,
            locator=Locator(
                type=LocatorType.RESOURCE_ID, value="com.demo:id/missing"
            ),
        )
        assert AssertionEngine(driver).evaluate(spec).passed is False


class TestAssertionEngineNotExists:
    def test_not_exists_pass(self):
        driver = _make_driver(found=False)
        spec = AssertionSpec(
            type=AssertionType.NOT_EXISTS,
            locator=Locator(type=LocatorType.RESOURCE_ID, value="loading"),
        )
        assert AssertionEngine(driver).evaluate(spec).passed is True

    def test_not_exists_fail(self):
        driver = _make_driver(found=True)
        spec = AssertionSpec(
            type=AssertionType.NOT_EXISTS,
            locator=Locator(type=LocatorType.RESOURCE_ID, value="loading"),
        )
        assert AssertionEngine(driver).evaluate(spec).passed is False


class TestAssertionEngineTextEquals:
    def test_match_pass(self):
        driver = _make_driver(found=True, text="首页")
        spec = AssertionSpec(
            type=AssertionType.TEXT_EQUALS,
            locator=Locator(type=LocatorType.RESOURCE_ID, value="title"),
            expected="首页",
        )
        assert AssertionEngine(driver).evaluate(spec).passed is True

    def test_mismatch_fail(self):
        driver = _make_driver(found=True, text="设置")
        spec = AssertionSpec(
            type=AssertionType.TEXT_EQUALS,
            locator=Locator(type=LocatorType.RESOURCE_ID, value="title"),
            expected="首页",
        )
        assert AssertionEngine(driver).evaluate(spec).passed is False


class TestAssertionEngineTextContains:
    def test_contains_pass(self):
        driver = _make_driver(found=True, text="登录成功，欢迎")
        spec = AssertionSpec(
            type=AssertionType.TEXT_CONTAINS,
            locator=Locator(type=LocatorType.RESOURCE_ID, value="msg"),
            expected="登录成功",
        )
        assert AssertionEngine(driver).evaluate(spec).passed is True


class TestAssertionEngineOcrContains:
    def test_found_in_source(self):
        driver = _make_driver(source='<node text="登录成功"/>')
        spec = AssertionSpec(
            type=AssertionType.OCR_CONTAINS, expected="登录成功"
        )
        assert AssertionEngine(driver).evaluate(spec).passed is True

    def test_not_found_in_source(self):
        driver = _make_driver(source='<node text="设置"/>')
        spec = AssertionSpec(
            type=AssertionType.OCR_CONTAINS, expected="登录成功"
        )
        assert AssertionEngine(driver).evaluate(spec).passed is False


class TestAssertionEngineAppForeground:
    def test_match(self):
        driver = _make_driver(app_pkg="com.demo.app")
        spec = AssertionSpec(
            type=AssertionType.APP_FOREGROUND, expected="com.demo.app"
        )
        assert AssertionEngine(driver).evaluate(spec).passed is True

    def test_mismatch(self):
        driver = _make_driver(app_pkg="com.other")
        spec = AssertionSpec(
            type=AssertionType.APP_FOREGROUND, expected="com.demo.app"
        )
        assert AssertionEngine(driver).evaluate(spec).passed is False


class TestAssertionEngineEvaluateAll:
    def test_evaluate_all(self):
        driver = _make_driver(found=True)
        specs = [
            AssertionSpec(
                type=AssertionType.EXISTS,
                locator=Locator(type=LocatorType.RESOURCE_ID, value="btn"),
            ),
            AssertionSpec(
                type=AssertionType.APP_FOREGROUND, expected="com.demo.app"
            ),
        ]
        results = AssertionEngine(driver).evaluate_all(specs)
        assert len(results) == 2
        assert all(r.passed for r in results)

    def test_evaluate_all_empty(self):
        results = AssertionEngine(
            MagicMock(spec=DeviceDriver)
        ).evaluate_all([])
        assert results == []


class TestAssertionEngineImageExists:
    def test_image_exists_pass(self):
        """When template matching returns a high score, assertion passes."""
        driver = _make_driver()
        spec = AssertionSpec(
            type=AssertionType.IMAGE_EXISTS,
            image_path="templates/button.png",
        )
        with patch("app.automation.assertions.engine._find_template_in_screenshot") as mock_find:
            mock_find.return_value = TemplateMatch(score=0.95, location=(50, 100))
            result = AssertionEngine(driver).evaluate(spec)
        assert result.passed is True
        assert "0.95" in result.message

    def test_image_exists_fail(self):
        """When template matching returns a low score, assertion fails."""
        driver = _make_driver()
        spec = AssertionSpec(
            type=AssertionType.IMAGE_EXISTS,
            image_path="templates/button.png",
        )
        with patch("app.automation.assertions.engine._find_template_in_screenshot") as mock_find:
            mock_find.return_value = TemplateMatch(score=0.45, location=None)
            result = AssertionEngine(driver).evaluate(spec)
        assert result.passed is False

    def test_image_exists_no_path(self):
        """When no image_path is provided, assertion fails with message."""
        driver = _make_driver()
        spec = AssertionSpec(type=AssertionType.IMAGE_EXISTS)
        result = AssertionEngine(driver).evaluate(spec)
        assert result.passed is False
        assert "No image_path" in result.message

    def test_image_exists_template_not_found(self):
        """When template file does not exist, assertion fails gracefully."""
        driver = _make_driver()
        spec = AssertionSpec(
            type=AssertionType.IMAGE_EXISTS,
            image_path="/nonexistent/template.png",
        )
        with patch("app.automation.assertions.engine._find_template_in_screenshot") as mock_find:
            mock_find.side_effect = FileNotFoundError("template not found")
            result = AssertionEngine(driver).evaluate(spec)
        assert result.passed is False
        assert "not found" in result.message
