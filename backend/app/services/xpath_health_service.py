"""Periodic health-check for the XPath recording pipeline (u2/wda → parse → locate)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.services import u2_service, wda_service

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 20 * 60  # 20 minutes

ANDROID_TEST_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" package="com.health.check" content-desc="" clickable="false" enabled="true" bounds="[0,0][1080,1920]">
    <node index="1" text="HealthCheck" resource-id="com.health.check:id/btn" class="android.widget.Button" package="com.health.check" content-desc="" clickable="true" enabled="true" bounds="[100,200][420,300]" />
  </node>
</hierarchy>
"""

IOS_TEST_XML = """
<AppiumAUT>
  <XCUIElementTypeApplication type="XCUIElementTypeApplication" name="HealthCheck" label="HealthCheck" x="0" y="0" width="390" height="844">
    <XCUIElementTypeButton type="XCUIElementTypeButton" name="Check" label="Check" enabled="true" x="40" y="120" width="120" height="48" />
  </XCUIElementTypeApplication>
</AppiumAUT>
"""


@dataclass
class XPathHealthResult:
    status: str = "unknown"
    android_parse_ok: bool = False
    android_locate_ok: bool = False
    ios_parse_ok: bool = False
    ios_locate_ok: bool = False
    u2_connected: bool = False
    wda_connected: bool = False
    duration_ms: int = 0
    errors: list[str] = field(default_factory=list)


def check_xpath_pipeline() -> XPathHealthResult:
    """Run a lightweight check of the XPath recording pipeline using canned XML."""
    from app.services.ui_element_service import UIElementService

    result = XPathHealthResult()
    start = time.monotonic()

    try:
        service = UIElementService()

        # --- Android parse ---
        try:
            elements = service.parse_generic_hierarchy(ANDROID_TEST_XML, platform="android")
            result.android_parse_ok = len(elements) > 0
        except Exception as e:
            result.errors.append(f"android_parse: {e}")

        # --- Android locate ---
        try:
            loc = service.locate_generic_xml(
                xml=ANDROID_TEST_XML,
                x=260,
                y=250,
                package_name="com.health.check",
                platform="android",
                strict_xpath_only=True,
            )
            result.android_locate_ok = loc.found and loc.element is not None
        except Exception as e:
            result.errors.append(f"android_locate: {e}")

        # --- iOS parse ---
        try:
            elements = service.parse_generic_hierarchy(IOS_TEST_XML, platform="ios")
            result.ios_parse_ok = len(elements) > 0
        except Exception as e:
            result.errors.append(f"ios_parse: {e}")

        # --- iOS locate ---
        try:
            loc = service.locate_generic_xml(
                xml=IOS_TEST_XML,
                x=100,
                y=144,
                platform="ios",
                strict_xpath_only=True,
            )
            result.ios_locate_ok = loc.found and loc.element is not None
        except Exception as e:
            result.errors.append(f"ios_locate: {e}")

        # --- u2 connectivity (only if enabled) ---
        if settings.u2_enabled:
            try:
                u2_service._u2()
                result.u2_connected = True
            except Exception as e:
                result.errors.append(f"u2_import: {e}")

        # --- wda connectivity (only if enabled) ---
        if settings.wda_enabled:
            try:
                wda_service._wda()
                result.wda_connected = True
            except Exception as e:
                result.errors.append(f"wda_import: {e}")

    except Exception as e:
        result.errors.append(f"fatal: {e}")

    result.duration_ms = int((time.monotonic() - start) * 1000)

    all_ok = (
        result.android_parse_ok
        and result.android_locate_ok
        and result.ios_parse_ok
        and result.ios_locate_ok
    )
    if all_ok and not result.errors:
        result.status = "healthy"
    elif all_ok:
        result.status = "degraded"
    else:
        result.status = "unhealthy"

    return result


async def xpath_health_loop() -> None:
    """Background loop that checks the XPath recording pipeline every 20 minutes."""
    while True:
        await asyncio.sleep(_INTERVAL_SECONDS)
        try:
            result = check_xpath_pipeline()
            if result.status == "healthy":
                logger.info(
                    "xpath health: OK (android=%s ios=%s u2=%s wda=%s %dms)",
                    result.android_locate_ok,
                    result.ios_locate_ok,
                    result.u2_connected,
                    result.wda_connected,
                    result.duration_ms,
                )
            else:
                logger.warning(
                    "xpath health: %s (android_parse=%s android_locate=%s ios_parse=%s ios_locate=%s u2=%s wda=%s errors=%s %dms)",
                    result.status,
                    result.android_parse_ok,
                    result.android_locate_ok,
                    result.ios_parse_ok,
                    result.ios_locate_ok,
                    result.u2_connected,
                    result.wda_connected,
                    result.errors,
                    result.duration_ms,
                )
        except Exception as e:
            logger.error("xpath health check crashed: %s", e)
