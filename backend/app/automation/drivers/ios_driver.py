"""iOS device driver — delegates to wda_service."""

from __future__ import annotations

import logging

from app.automation.core.driver import DeviceDriver, ElementRef
from app.services import wda_service

logger = logging.getLogger(__name__)


class IOSDriver(DeviceDriver):
    """iOS device driver backed by WebDriverAgent (WDA)."""

    def __init__(self, udid: str, wda_url: str) -> None:
        self._udid = udid
        self._wda_url = wda_url

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def platform(self) -> str:
        return "ios"

    @property
    def udid(self) -> str:
        return self._udid

    @property
    def wda_url(self) -> str:
        return self._wda_url

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _client(self):
        return wda_service.get_client(self._udid, self._wda_url)

    # ------------------------------------------------------------------
    # App lifecycle
    # ------------------------------------------------------------------

    def launch(self, app_id: str) -> None:
        wda_service.launch_app(self._udid, app_id, wda_url=self._wda_url)

    def stop_app(self, app_id: str) -> None:
        # WDA doesn't expose a direct terminate in current service.  Graceful no-op.
        logger.info("stop_app('%s') on iOS — not yet supported by WDA service", app_id)

    # ------------------------------------------------------------------
    # Touch / gesture
    # ------------------------------------------------------------------

    def tap(self, x: int, y: int) -> None:
        wda_service.click(self._udid, x, y, wda_url=self._wda_url)

    def long_press(self, x: int, y: int, duration_ms: int = 1000) -> None:
        client = self._client()
        client.tap_hold(x, y, duration_ms / 1000.0)

    def swipe(self, sx: int, sy: int, ex: int, ey: int, duration_ms: int = 300) -> None:
        wda_service.swipe(self._udid, sx, sy, ex, ey, duration=duration_ms / 1000.0, wda_url=self._wda_url)

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------

    def input_text(self, text: str) -> None:
        client = self._client()
        client.type_keys(text)

    def press_key(self, key: str) -> None:
        client = self._client()
        key_lower = key.lower()
        if key_lower == "home":
            client.home()
        elif key_lower == "back":
            # iOS has no universal back; simulate via swipe right from left edge
            size = client.window_size()
            client.swipe(10, size.height // 2, size.width // 2, size.height // 2, 0.3)
        else:
            logger.warning("Unsupported iOS key press: %s", key)

    # ------------------------------------------------------------------
    # Screen / hierarchy
    # ------------------------------------------------------------------

    def screenshot(self) -> bytes:
        return wda_service.screenshot(self._udid, self._wda_url)

    def dump_source(self) -> str:
        return wda_service.dump_source(self._udid, self._wda_url)

    # ------------------------------------------------------------------
    # Device info
    # ------------------------------------------------------------------

    def current_app(self) -> dict[str, str]:
        client = self._client()
        info = client.session_info()
        return {"bundle_id": info.get("bundleId", "")}

    def screen_size(self) -> tuple[int, int]:
        client = self._client()
        size = client.window_size()
        return (size.width, size.height)

    # ------------------------------------------------------------------
    # Element search
    # ------------------------------------------------------------------

    def find_element(self, locator_type: str, locator_value: str, timeout: float = 10.0) -> ElementRef:
        client = self._client()
        wda_locator = _map_locator(locator_type, locator_value)
        el = client.find_element(**wda_locator)
        found = el.exists if hasattr(el, "exists") else bool(el)
        bounds = None
        center = None
        if found:
            b = el.bounds
            bounds = {
                "x": b.get("x", 0),
                "y": b.get("y", 0),
                "width": b.get("width", 0),
                "height": b.get("height", 0),
            }
            center = (
                int(b.get("x", 0) + b.get("width", 0) / 2),
                int(b.get("y", 0) + b.get("height", 0) / 2),
            )
        return ElementRef(
            found=found,
            locator_type=locator_type,
            locator_value=locator_value,
            bounds=bounds,
            center=center,
        )

    def element_exists(self, locator_type: str, locator_value: str, timeout: float = 5.0) -> bool:
        result = self.find_element(locator_type, locator_value, timeout=timeout)
        return result.found


# ── Locator mapping ──────────────────────────────────────────────────────────


def _map_locator(locator_type: str, locator_value: str) -> dict:
    """Translate from canonical locator types to WDA kwarg names."""
    mapping = {
        "class_name": {"class_name": locator_value},
        "resource_id": {"accessibility_id": locator_value},
        "text": {"name": locator_value},
        "xpath": {"xpath": locator_value},
        "content_desc": {"accessibility_id": locator_value},
    }
    return mapping.get(locator_type, {"name": locator_value})
