"""Tests for the EvidenceCollector."""

import os
import tempfile
from unittest.mock import MagicMock

from app.automation.core.driver import DeviceDriver
from app.automation.reports.evidence import EvidenceCollector


def _make_driver(
    screenshot: bytes = b"\x89PNG",
    source: str = "<hierarchy/>",
    app: str = "com.demo.app",
) -> MagicMock:
    driver = MagicMock(spec=DeviceDriver)
    driver.screenshot.return_value = screenshot
    driver.dump_source.return_value = source
    driver.current_app.return_value = {"package": app}
    return driver


class TestEvidenceCollectorCapture:
    """Verify that ``capture()`` produces all four fields correctly."""

    def test_saves_screenshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            driver = _make_driver()
            evidence = EvidenceCollector(driver, tmp).capture("step_1")

            assert evidence.screenshot_path.endswith("step_1.png")
            assert os.path.exists(evidence.screenshot_path)
            with open(evidence.screenshot_path, "rb") as f:
                assert f.read() == b"\x89PNG"

    def test_saves_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            driver = _make_driver(source="<node text='hello'/>")
            evidence = EvidenceCollector(driver, tmp).capture("step_2")

            assert evidence.source_dump_path.endswith("step_2.xml")
            with open(evidence.source_dump_path, "r") as f:
                assert f.read() == "<node text='hello'/>"

    def test_records_current_app(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            driver = _make_driver(app="com.test.app")
            evidence = EvidenceCollector(driver, tmp).capture("step_3")

            assert evidence.current_app == "com.test.app"

    def test_records_ocr_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = EvidenceCollector(_make_driver(), tmp).capture(
                "step_4", ocr_summary=["登录", "首页"]
            )

            assert evidence.ocr_summary == ["登录", "首页"]

    def test_records_duration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            evidence = EvidenceCollector(_make_driver(), tmp).capture("step_5")

            assert evidence.duration_ms >= 0

    def test_output_dir_created_if_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            subdir = os.path.join(tmp, "reports", "run_1")
            EvidenceCollector(_make_driver(), subdir).capture("step_6")

            assert os.path.isdir(subdir)
