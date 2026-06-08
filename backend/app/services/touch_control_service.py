"""Touch control service using ADB input commands for real-time device interaction."""

from __future__ import annotations

import asyncio
import logging

from app.services.adb_service import ADBService
from app.services.realtime_adb_control_service import realtime_adb_control_service

logger = logging.getLogger(__name__)


class TouchControlError(RuntimeError):
    pass


class TouchControlService:
    """Real-time touch/key/text control for Android and iOS devices.

    Android: Uses `input motionevent` for fine-grained touch control
    (DOWN/MOVE/UP), enabling drag, swipe, and multi-touch gestures.

    iOS: Uses WDA (WebDriverAgent) for tap and swipe.  WDA does not
    support separate DOWN/MOVE/UP events, so touch_down delegates to
    tap and touch_move/touch_up are no-ops (swipe handles gestures).
    """

    def __init__(self, adb: ADBService | None = None) -> None:
        self.adb = adb or ADBService()

    # ── Android control (ADB input commands) ──────────────────────────

    async def touch_down(self, udid: str, x: int, y: int) -> None:
        """Send touch DOWN event at specified coordinates."""
        realtime_adb_control_service.send(udid, f"input motionevent DOWN {int(x)} {int(y)}")

    async def touch_move(self, udid: str, x: int, y: int) -> None:
        """Send touch MOVE event at specified coordinates."""
        realtime_adb_control_service.send(udid, f"input motionevent MOVE {int(x)} {int(y)}")

    async def touch_up(self, udid: str, x: int, y: int) -> None:
        """Send touch UP event at specified coordinates."""
        realtime_adb_control_service.send(udid, f"input motionevent UP {int(x)} {int(y)}")

    async def tap(self, udid: str, x: int, y: int) -> None:
        """Tap at specified coordinates."""
        realtime_adb_control_service.send(udid, f"input tap {int(x)} {int(y)}")

    async def swipe(
        self, udid: str, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300,
    ) -> None:
        """Swipe from (x1,y1) to (x2,y2) over duration_ms milliseconds."""
        realtime_adb_control_service.send(
            udid,
            f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration_ms)}",
        )

    async def long_press(self, udid: str, x: int, y: int, duration_ms: int = 800) -> None:
        """Long press at specified coordinates (uses swipe with same start/end)."""
        realtime_adb_control_service.send(udid, f"input swipe {int(x)} {int(y)} {int(x)} {int(y)} {int(duration_ms)}")

    async def key(self, udid: str, keycode: int) -> None:
        """Press a key by keycode."""
        realtime_adb_control_service.send(udid, f"input keyevent {int(keycode)}")

    async def text(self, udid: str, value: str) -> None:
        """Input text using ADB keyboard broadcast."""
        await asyncio.to_thread(self.adb.input_text, udid, value)

    # ── iOS control (WDA / WebDriverAgent) ────────────────────────────

    async def ios_tap(self, udid: str, x: int, y: int) -> None:
        """Tap at specified coordinates on iOS device via WDA."""
        from app.services import wda_service
        await asyncio.to_thread(wda_service.click, udid, x, y)

    async def ios_swipe(
        self, udid: str, x1: int, y1: int, x2: int, y2: int, duration: float = 0.3,
    ) -> None:
        """Swipe on iOS device via WDA."""
        from app.services import wda_service
        await asyncio.to_thread(wda_service.swipe, udid, x1, y1, x2, y2, duration=duration)

    async def ios_touch_down(self, udid: str, x: int, y: int) -> None:
        """Touch down on iOS device via WDA.

        WDA doesn't support separate DOWN/MOVE/UP, so we perform a tap
        (which is DOWN+UP atomically).  For drag, use ios_swipe instead.
        """
        from app.services import wda_service
        await asyncio.to_thread(wda_service.click, udid, x, y)

    async def ios_touch_up(self, udid: str, x: int, y: int) -> None:
        """Touch up on iOS device.

        No-op: WDA tap in ios_touch_down already completes the gesture.
        """

    async def ios_touch_move(self, udid: str, x: int, y: int) -> None:
        """Touch move on iOS device.

        No-op: WDA doesn't support continuous move events.
        Use ios_swipe for drag gestures at the caller level.
        """

    async def ios_key(self, udid: str, keycode: int) -> None:
        """Press key on iOS device via WDA.

        Maps common Android keycodes to WDA actions.
        For HOME, we use the WDA client's home() method.
        Other keys are not directly supported by WDA.
        """
        if keycode in (3, 4):  # HOME or BACK
            # WDA home button via HTTP API
            import requests
            from app.config import settings
            wda_url = getattr(settings, 'wda_url', None) or f"http://localhost:8100"
            try:
                await asyncio.to_thread(
                    requests.post, f"{wda_url}/wda/homescreen", timeout=5,
                )
            except Exception as exc:
                logger.debug("iOS home key failed: %s", exc)

    async def ios_text(self, udid: str, value: str) -> None:
        """Input text on iOS device via WDA.

        Uses WDA's type API for text input.
        """
        import requests
        from app.config import settings
        wda_url = getattr(settings, 'wda_url', None) or f"http://localhost:8100"
        try:
            await asyncio.to_thread(
                requests.post,
                f"{wda_url}/wda/keys",
                json={"value": list(value)},
                timeout=5,
            )
        except Exception as exc:
            logger.debug("iOS text input failed: %s", exc)
