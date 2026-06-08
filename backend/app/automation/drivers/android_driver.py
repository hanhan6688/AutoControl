"""Android-specific implementation of the DeviceDriver protocol.

Uses a u2-first, ADB-fallback strategy: when uiautomator2 is available,
operations delegate to it; on failure they fall back to raw ADB commands.
"""

from __future__ import annotations

import re

from app.automation.core.driver import DeviceDriver, ElementRef
from app.services import adb_service
from app.services import u2_service

_KEY_MAP: dict[str, int] = {
    "back": 4,
    "home": 3,
    "enter": 66,
    "recent": 187,
    "delete": 67,
    "tab": 61,
    "escape": 111,
    "space": 62,
    "volume_up": 24,
    "volume_down": 25,
    "power": 26,
}


class AndroidDriver(DeviceDriver):
    """Android device driver with u2-first / ADB-fallback strategy."""

    def __init__(self, udid: str) -> None:
        self._udid = udid
        self._adb = adb_service.ADBService()

    @property
    def platform(self) -> str:
        return "android"

    @property
    def udid(self) -> str:
        return self._udid

    # ------------------------------------------------------------------
    # App lifecycle
    # ------------------------------------------------------------------

    def launch(self, app_id: str) -> None:
        component = app_id if "/" in app_id else f"{app_id}/.MainActivity"
        self._adb.shell(self._udid, f"am start -n {component}")

    def stop_app(self, app_id: str) -> None:
        self._adb.shell(self._udid, f"am force-stop {app_id}")

    # ------------------------------------------------------------------
    # Touch / gesture
    # ------------------------------------------------------------------

    def tap(self, x: int, y: int) -> None:
        try:
            u2_service.click(self._udid, x, y)
        except Exception:
            self._adb.shell(self._udid, f"input tap {x} {y}")

    def long_press(self, x: int, y: int, duration_ms: int = 1000) -> None:
        self._adb.shell(self._udid, f"input swipe {x} {y} {x} {y} {duration_ms}")

    def swipe(self, sx: int, sy: int, ex: int, ey: int, duration_ms: int = 300) -> None:
        try:
            u2_service.swipe(self._udid, sx, sy, ex, ey, duration=duration_ms / 1000)
        except Exception:
            self._adb.shell(self._udid, f"input swipe {sx} {sy} {ex} {ey} {duration_ms}")

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------

    def input_text(self, text: str) -> None:
        self._adb.input_text(self._udid, text)

    def press_key(self, key: str) -> None:
        keycode = _KEY_MAP.get(key.lower())
        if keycode is not None:
            self._adb.shell(self._udid, f"input keyevent {keycode}")
        else:
            self._adb.shell(self._udid, f"input keyevent {key}")

    # ------------------------------------------------------------------
    # Screen / hierarchy
    # ------------------------------------------------------------------

    def screenshot(self) -> bytes:
        try:
            return u2_service.screenshot(self._udid)
        except Exception:
            return self._adb.capture_screen_png(self._udid)

    def dump_source(self) -> str:
        try:
            return u2_service.dump_hierarchy(self._udid)
        except Exception:
            return self._adb.dump_ui_hierarchy(self._udid)

    # ------------------------------------------------------------------
    # Device info
    # ------------------------------------------------------------------

    def current_app(self) -> dict[str, str]:
        result = self._adb.shell(
            self._udid, "dumpsys activity activities | grep mResumedActivity"
        )
        match = re.search(r"(\S+)/(\S+)\s", result.stdout)
        if not match:
            return {"package": "", "activity": ""}
        return {"package": match.group(1), "activity": match.group(2)}

    def screen_size(self) -> tuple[int, int]:
        return self._adb.get_screen_size(self._udid)

    # ------------------------------------------------------------------
    # Element search
    # ------------------------------------------------------------------

    def find_element(self, locator_type: str, locator_value: str, timeout: float = 10.0) -> ElementRef:
        result = u2_service.exists_selector(
            self._udid, **{locator_type: locator_value}, timeout=timeout
        )
        return ElementRef(found=result, locator_type=locator_type, locator_value=locator_value)

    def element_exists(self, locator_type: str, locator_value: str, timeout: float = 5.0) -> bool:
        return u2_service.exists_selector(
            self._udid, **{locator_type: locator_value}, timeout=timeout
        )
