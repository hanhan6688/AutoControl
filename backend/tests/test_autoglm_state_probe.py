"""Tests for StateProbe — multi-source state collection."""

from unittest.mock import MagicMock

from app.automation.autoglm.state_probe import StateProbe
from app.automation.core.driver import DeviceDriver


def _make_driver() -> MagicMock:
    driver = MagicMock(spec=DeviceDriver)
    driver.screenshot.return_value = b"\x89PNG"
    driver.dump_source.return_value = "<node text='登录'/>"
    driver.current_app.return_value = {"package": "com.demo.app"}
    return driver


class TestStateProbe:
    def test_probe_collects_screenshot(self):
        driver = _make_driver()
        probe = StateProbe(driver)
        state = probe.collect()
        assert state.screenshot_bytes == b"\x89PNG"

    def test_probe_collects_source(self):
        driver = _make_driver()
        probe = StateProbe(driver)
        state = probe.collect()
        assert "登录" in state.source_xml

    def test_probe_collects_current_app(self):
        driver = _make_driver()
        probe = StateProbe(driver)
        state = probe.collect()
        assert state.foreground_app == "com.demo.app"
