from __future__ import annotations

import io
import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_session_pool: dict[str, Any] = {}


def _wda() -> Any:
    import wda
    return wda


def get_client(udid: str, wda_url: str | None = None) -> Any:
    resolved_wda_url = (wda_url or settings.autoglm_wda_url).rstrip("/")
    cache_key = f"{udid}@{resolved_wda_url}"
    if cache_key in _session_pool:
        return _session_pool[cache_key]

    client = _wda().Client(resolved_wda_url)
    _session_pool[cache_key] = client
    logger.info("wda connected to %s via %s", udid, resolved_wda_url)
    return client


def disconnect_client(udid: str) -> None:
    for key in list(_session_pool):
        if key == udid or key.startswith(f"{udid}@"):
            _session_pool.pop(key, None)


def dump_source(udid: str, wda_url: str | None = None) -> str:
    client = get_client(udid, wda_url=wda_url)
    source = client.source()
    if not source:
        raise RuntimeError(f"wda source returned empty for {udid}")
    logger.debug("wda source OK for %s (%d bytes)", udid, len(source))
    return source


def click(udid: str, x: int, y: int, wda_url: str | None = None) -> None:
    client = get_client(udid, wda_url=wda_url)
    client.tap(x, y)


def swipe(udid: str, sx: int, sy: int, ex: int, ey: int, duration: float = 0.5, wda_url: str | None = None) -> None:
    client = get_client(udid, wda_url=wda_url)
    client.swipe(sx, sy, ex, ey, duration)


def screenshot(udid: str, wda_url: str | None = None) -> bytes:
    client = get_client(udid, wda_url=wda_url)
    img = client.screenshot()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def launch_app(udid: str, bundle_id: str, wda_url: str | None = None) -> None:
    client = get_client(udid, wda_url=wda_url)
    if hasattr(client, "app_launch"):
        client.app_launch(bundle_id)
        return
    if hasattr(client, "session"):
        client.session(bundle_id)
        return
    raise RuntimeError("wda client does not support app launch")


def device_info(udid: str, wda_url: str | None = None) -> dict[str, Any]:
    client = get_client(udid, wda_url=wda_url)
    return client.info
