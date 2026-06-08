"""EvidenceCollector -- captures screenshots, source dumps, and device state for each step."""
from __future__ import annotations

import logging
import os
import time

from app.automation.core.driver import DeviceDriver
from app.automation.core.models import Evidence

logger = logging.getLogger(__name__)


class EvidenceCollector:
    """Collect per-step evidence from a device driver and persist it to disk.

    Each ``capture()`` call produces:
    * A PNG screenshot
    * An XML UI-hierarchy dump
    * The current foreground app identifier
    * An optional OCR summary list
    * The elapsed wall-clock time in milliseconds
    """

    def __init__(self, driver: DeviceDriver, output_dir: str) -> None:
        self._driver = driver
        self._output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def capture(self, step_id: str, ocr_summary: list[str] | None = None) -> Evidence:
        """Run through every evidence source and return a populated ``Evidence``."""
        start = time.monotonic()

        screenshot_path = self._save_screenshot(step_id)
        source_dump_path = self._save_source(step_id)
        current_app = self._get_current_app()

        elapsed_ms = int((time.monotonic() - start) * 1000)

        return Evidence(
            screenshot_path=screenshot_path,
            source_dump_path=source_dump_path,
            ocr_summary=ocr_summary or [],
            current_app=current_app,
            duration_ms=elapsed_ms,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _save_screenshot(self, step_id: str) -> str:
        """Capture a PNG screenshot from the driver and write it to disk."""
        png_bytes = self._driver.screenshot()
        path = os.path.join(self._output_dir, f"{step_id}.png")
        with open(path, "wb") as f:
            f.write(png_bytes)
        return path

    def _save_source(self, step_id: str) -> str:
        """Dump the accessibility/UI hierarchy from the driver and write to disk."""
        source_xml = self._driver.dump_source()
        path = os.path.join(self._output_dir, f"{step_id}.xml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(source_xml)
        return path

    def _get_current_app(self) -> str:
        """Return the package (Android) or bundle identifier (iOS) of the foreground app."""
        info = self._driver.current_app()
        return info.get("package", "") or info.get("bundle_id", "")
