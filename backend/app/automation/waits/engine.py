from __future__ import annotations
import hashlib
import logging
import time
from dataclasses import dataclass
from app.automation.core.driver import DeviceDriver
from app.automation.core.models import WaitConditionType, WaitSpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WaitResult:
    met: bool
    elapsed_ms: int
    condition: WaitConditionType


class WaitEngine:
    def __init__(self, driver: DeviceDriver):
        self._driver = driver

    def wait(self, spec: WaitSpec, expected_app: str | None = None) -> WaitResult:
        start = time.monotonic()
        timeout = spec.timeout
        poll_interval = spec.poll_interval
        while True:
            met = self._evaluate(spec, expected_app)
            elapsed = time.monotonic() - start
            if met:
                return WaitResult(met=True, elapsed_ms=int(elapsed * 1000), condition=spec.type)
            if elapsed >= timeout:
                return WaitResult(met=False, elapsed_ms=int(elapsed * 1000), condition=spec.type)
            time.sleep(poll_interval)

    def _evaluate(self, spec: WaitSpec, expected_app: str | None = None) -> bool:
        cond = spec.type
        if cond == WaitConditionType.VISIBLE:
            return self._check_element_found(spec)
        if cond == WaitConditionType.EXISTS:
            return self._check_element_found(spec)
        if cond == WaitConditionType.GONE:
            return not self._check_element_found(spec)
        if cond == WaitConditionType.APP_FOREGROUND:
            return self._check_app_foreground(expected_app)
        if cond == WaitConditionType.SCREEN_CHANGED:
            return self._check_screen_changed()
        if cond == WaitConditionType.SOURCE_STABLE:
            return self._check_source_stable()
        if cond == WaitConditionType.ENABLED:
            return self._check_element_found(spec)
        if cond in (WaitConditionType.TEXT_EQUALS, WaitConditionType.TEXT_CONTAINS):
            return self._check_element_found(spec)
        if cond == WaitConditionType.OCR_CONTAINS:
            return False  # deferred to AssertionEngine
        logger.warning("Unhandled wait condition: %s", cond)
        return False

    def _check_element_found(self, spec: WaitSpec) -> bool:
        if spec.locator is None:
            return False
        ref = self._driver.find_element(spec.locator.type.value, spec.locator.value, timeout=0)
        return ref.found

    def _check_app_foreground(self, expected_app: str | None) -> bool:
        if expected_app is None:
            return True
        app_info = self._driver.current_app()
        package = app_info.get("package", "") or app_info.get("bundle_id", "")
        return package == expected_app

    _last_screenshot_hash: str | None = None

    def _check_screen_changed(self) -> bool:
        screenshot = self._driver.screenshot()
        current_hash = hashlib.md5(screenshot).hexdigest()
        if self._last_screenshot_hash is None:
            self._last_screenshot_hash = current_hash
            return False
        changed = current_hash != self._last_screenshot_hash
        self._last_screenshot_hash = current_hash
        return changed

    _last_source_hash: str | None = None

    def _check_source_stable(self) -> bool:
        source = self._driver.dump_source()
        current_hash = hashlib.md5(source.encode()).hexdigest()
        if self._last_source_hash is None:
            self._last_source_hash = current_hash
            return False
        stable = current_hash == self._last_source_hash
        self._last_source_hash = current_hash
        return stable
