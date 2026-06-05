"""StateProbe — collects multi-source device state for checkpoint validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.automation.core.driver import DeviceDriver


@dataclass(frozen=True)
class DeviceState:
    foreground_app: str = ""
    visible_texts: list[str] = field(default_factory=list)
    source_summary: dict[str, Any] = field(default_factory=dict)
    screenshot_bytes: bytes = b""
    source_xml: str = ""


class StateProbe:
    """Collects screenshot, source, and app state from a DeviceDriver."""

    def __init__(self, driver: DeviceDriver) -> None:
        self._driver = driver

    def collect(self) -> DeviceState:
        screenshot = self._driver.screenshot()
        source = self._driver.dump_source()
        app_info = self._driver.current_app()
        return DeviceState(
            foreground_app=app_info.get("package", "") or app_info.get("bundle_id", ""),
            screenshot_bytes=screenshot,
            source_xml=source,
        )
