"""Tests for RepairService — auto-repair strategies for checkpoint failures."""

from unittest.mock import MagicMock

from app.automation.autoglm.repair_service import RepairService
from app.automation.core.driver import DeviceDriver


def _make_driver() -> MagicMock:
    driver = MagicMock(spec=DeviceDriver)
    return driver


class TestRepairService:
    def test_back_repair(self):
        driver = _make_driver()
        service = RepairService(driver)
        service.repair_back()
        driver.press_key.assert_called_once_with("back")

    def test_home_repair(self):
        driver = _make_driver()
        service = RepairService(driver)
        service.repair_home()
        driver.press_key.assert_called_once_with("home")

    def test_relaunch_app(self):
        driver = _make_driver()
        service = RepairService(driver)
        service.repair_relaunch("com.demo.app")
        driver.launch.assert_called_once_with("com.demo.app")
