"""RepairService — platform-side auto-repair strategies for checkpoint failures."""

from __future__ import annotations

from app.automation.core.driver import DeviceDriver


class RepairService:
    """Attempts to recover from checkpoint failures with limited retries."""

    def __init__(self, driver: DeviceDriver) -> None:
        self._driver = driver

    def repair_back(self) -> None:
        self._driver.press_key("back")

    def repair_home(self) -> None:
        self._driver.press_key("home")

    def repair_relaunch(self, app_id: str) -> None:
        self._driver.launch(app_id)

    def repair_wait(self, seconds: int = 3) -> None:
        import time
        time.sleep(seconds)
