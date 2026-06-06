from __future__ import annotations
import logging
import os
from dataclasses import dataclass
from typing import NamedTuple
from app.automation.core.driver import DeviceDriver
from app.automation.core.models import AssertionSpec, AssertionType

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class TemplateMatch(NamedTuple):
    score: float
    location: tuple[int, int] | None


def _match_template(source_image: np.ndarray, template_image: np.ndarray) -> TemplateMatch:
    """Match a template image against a source image using cv2.matchTemplate."""
    if source_image.shape[0] < template_image.shape[0] or source_image.shape[1] < template_image.shape[1]:
        return TemplateMatch(score=0.0, location=None)
    result = cv2.matchTemplate(source_image, template_image, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
    return TemplateMatch(score=float(max_val), location=max_loc if max_val >= 0.7 else None)


def _decode_image_bytes(image_bytes: bytes) -> np.ndarray | None:
    """Decode image bytes into a numpy array using cv2."""
    array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR)
    return image


def _find_template_in_screenshot(driver: DeviceDriver, image_path: str) -> TemplateMatch:
    """Load a template image and match it against the current device screenshot."""
    template_image = cv2.imread(image_path)
    if template_image is None:
        raise FileNotFoundError(f"Template image not found: {image_path}")
    screenshot_bytes = driver.screenshot()
    source_image = _decode_image_bytes(screenshot_bytes)
    if source_image is None:
        return TemplateMatch(score=0.0, location=None)
    return _match_template(source_image, template_image)


@dataclass(frozen=True)
class AssertionResult:
    passed: bool
    assertion_type: AssertionType
    message: str = ""


class AssertionEngine:
    def __init__(self, driver: DeviceDriver):
        self._driver = driver

    def evaluate(self, spec: AssertionSpec) -> AssertionResult:
        atype = spec.type
        if atype == AssertionType.EXISTS:
            return self._assert_exists(spec)
        if atype == AssertionType.NOT_EXISTS:
            return self._assert_not_exists(spec)
        if atype == AssertionType.TEXT_EQUALS:
            return self._assert_text_equals(spec)
        if atype == AssertionType.TEXT_CONTAINS:
            return self._assert_text_contains(spec)
        if atype == AssertionType.OCR_CONTAINS:
            return self._assert_ocr_contains(spec)
        if atype == AssertionType.APP_FOREGROUND:
            return self._assert_app_foreground(spec)
        if atype == AssertionType.IMAGE_EXISTS:
            return self._assert_image_exists(spec)
        if atype == AssertionType.AI_RESULT:
            return AssertionResult(
                passed=False,
                assertion_type=atype,
                message="AI_RESULT requires external evaluation",
            )
        return AssertionResult(
            passed=False, assertion_type=atype, message=f"Unsupported: {atype}"
        )

    def evaluate_all(self, specs: list[AssertionSpec]) -> list[AssertionResult]:
        return [self.evaluate(spec) for spec in specs]

    def _assert_exists(self, spec):
        if spec.locator is None:
            return AssertionResult(
                passed=False, assertion_type=spec.type, message="No locator"
            )
        ref = self._driver.find_element(
            spec.locator.type.value, spec.locator.value, timeout=2.0
        )
        if ref.found:
            return AssertionResult(
                passed=True, assertion_type=spec.type, message="Element found"
            )
        return AssertionResult(
            passed=False, assertion_type=spec.type, message="Element not found"
        )

    def _assert_not_exists(self, spec):
        if spec.locator is None:
            return AssertionResult(
                passed=True,
                assertion_type=spec.type,
                message="No locator — vacuously true",
            )
        ref = self._driver.find_element(
            spec.locator.type.value, spec.locator.value, timeout=2.0
        )
        if not ref.found:
            return AssertionResult(
                passed=True,
                assertion_type=spec.type,
                message="Element not found as expected",
            )
        return AssertionResult(
            passed=False, assertion_type=spec.type, message="Element still exists"
        )

    def _assert_text_equals(self, spec):
        if spec.locator is None:
            return AssertionResult(
                passed=False, assertion_type=spec.type, message="No locator"
            )
        ref = self._driver.find_element(
            spec.locator.type.value, spec.locator.value, timeout=2.0
        )
        if not ref.found:
            return AssertionResult(
                passed=False, assertion_type=spec.type, message="Element not found"
            )
        actual = ref.text or ""
        expected = spec.expected or ""
        if actual == expected:
            return AssertionResult(
                passed=True, assertion_type=spec.type, message="Text matches"
            )
        return AssertionResult(
            passed=False,
            assertion_type=spec.type,
            message=f"Expected '{expected}', got '{actual}'",
        )

    def _assert_text_contains(self, spec):
        if spec.locator is None:
            return AssertionResult(
                passed=False, assertion_type=spec.type, message="No locator"
            )
        ref = self._driver.find_element(
            spec.locator.type.value, spec.locator.value, timeout=2.0
        )
        if not ref.found:
            return AssertionResult(
                passed=False, assertion_type=spec.type, message="Element not found"
            )
        actual = ref.text or ""
        expected = spec.expected or ""
        if expected in actual:
            return AssertionResult(
                passed=True,
                assertion_type=spec.type,
                message="Text contains expected",
            )
        return AssertionResult(
            passed=False,
            assertion_type=spec.type,
            message=f"'{actual}' does not contain '{expected}'",
        )

    def _assert_ocr_contains(self, spec):
        expected = spec.expected or ""
        if not expected:
            return AssertionResult(
                passed=False, assertion_type=spec.type, message="No expected text"
            )
        source = self._driver.dump_source()
        if expected in source:
            return AssertionResult(
                passed=True,
                assertion_type=spec.type,
                message=f"'{expected}' found in source",
            )
        return AssertionResult(
            passed=False,
            assertion_type=spec.type,
            message=f"'{expected}' not found in source",
        )

    def _assert_app_foreground(self, spec):
        expected = spec.expected or ""
        app_info = self._driver.current_app()
        package = app_info.get("package", "") or app_info.get("bundle_id", "")
        if package == expected:
            return AssertionResult(
                passed=True,
                assertion_type=spec.type,
                message=f"App '{expected}' in foreground",
            )
        return AssertionResult(
            passed=False,
            assertion_type=spec.type,
            message=f"Expected '{expected}', got '{package}'",
        )

    def _assert_image_exists(self, spec: AssertionSpec) -> AssertionResult:
        image_path = spec.image_path
        if not image_path:
            return AssertionResult(
                passed=False,
                assertion_type=spec.type,
                message="No image_path provided for IMAGE_EXISTS assertion",
            )
        try:
            match = _find_template_in_screenshot(self._driver, image_path)
        except FileNotFoundError:
            return AssertionResult(
                passed=False,
                assertion_type=spec.type,
                message=f"Template image not found: {image_path}",
            )
        threshold = 0.9
        if match.score >= threshold:
            return AssertionResult(
                passed=True,
                assertion_type=spec.type,
                message=f"Image matched with score {match.score:.2f} at {match.location}",
            )
        return AssertionResult(
            passed=False,
            assertion_type=spec.type,
            message=f"Image not matched: score {match.score:.2f} below threshold {threshold}",
        )
