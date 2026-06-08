from __future__ import annotations

import logging
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_device_pool: dict[str, Any] = {}


def _u2() -> Any:
    import uiautomator2 as u2
    return u2


def get_device(udid: str) -> Any:
    if udid in _device_pool:
        return _device_pool[udid]

    device = _u2().connect(udid)
    _device_pool[udid] = device
    logger.info("u2 connected to %s", udid)
    return device


def disconnect_device(udid: str) -> None:
    _device_pool.pop(udid, None)


def dump_hierarchy(udid: str) -> str:
    device = get_device(udid)
    xml_content = device.dump_hierarchy()
    if not xml_content:
        raise RuntimeError(f"u2 dump_hierarchy returned empty for {udid}")
    logger.debug("u2 dump_hierarchy OK for %s (%d bytes)", udid, len(xml_content))
    return xml_content


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _selector_kwargs(
    *,
    text: str | None = None,
    resource_id: str | None = None,
    content_desc: str | None = None,
    class_name: str | None = None,
    package: str | None = None,
) -> dict[str, str]:
    kwargs: dict[str, str] = {}
    if value := _clean(resource_id):
        kwargs["resourceId"] = value
    if value := _clean(text):
        kwargs["text"] = value
    if value := _clean(content_desc):
        kwargs["description"] = value
    if value := _clean(class_name):
        kwargs["className"] = value
    if value := _clean(package):
        kwargs["packageName"] = value
    return kwargs


def has_stable_selector(
    *,
    text: str | None = None,
    resource_id: str | None = None,
    content_desc: str | None = None,
    xpath: str | None = None,
) -> bool:
    return any(_clean(value) for value in (xpath, resource_id, content_desc, text))


def _wait_target(target: Any, timeout: float) -> bool:
    wait = getattr(target, "wait", None)
    if callable(wait):
        try:
            return bool(wait(timeout=float(timeout)))
        except TypeError:
            return bool(wait(float(timeout)))

    exists = getattr(target, "exists", None)
    if callable(exists):
        try:
            return bool(exists(timeout=float(timeout)))
        except TypeError:
            return bool(exists())
    if exists is not None:
        return bool(exists)
    return True


def _click_target(target: Any, timeout: float) -> None:
    click_method = getattr(target, "click", None)
    if not callable(click_method):
        raise RuntimeError("u2 target does not support click")
    try:
        click_method(timeout=float(timeout))
    except TypeError:
        click_method()


def _target_by_selector(
    device: Any,
    *,
    text: str | None = None,
    resource_id: str | None = None,
    content_desc: str | None = None,
    class_name: str | None = None,
    package: str | None = None,
    xpath: str | None = None,
    timeout: float = 5.0,
) -> Any | None:
    if value := _clean(xpath):
        target = device.xpath(value)
        return target if _wait_target(target, timeout) else None

    kwargs = _selector_kwargs(
        text=text,
        resource_id=resource_id,
        content_desc=content_desc,
        class_name=class_name,
        package=package,
    )
    if not kwargs:
        return None
    target = device(**kwargs)
    return target if _wait_target(target, timeout) else None


def click_selector(
    udid: str,
    *,
    text: str | None = None,
    resource_id: str | None = None,
    content_desc: str | None = None,
    class_name: str | None = None,
    package: str | None = None,
    xpath: str | None = None,
    timeout: float = 5.0,
) -> bool:
    device = get_device(udid)
    target = _target_by_selector(
        device,
        text=text,
        resource_id=resource_id,
        content_desc=content_desc,
        class_name=class_name,
        package=package,
        xpath=xpath,
        timeout=timeout,
    )
    if target is None:
        return False
    _click_target(target, timeout)
    return True


def exists_selector(
    udid: str,
    *,
    text: str | None = None,
    resource_id: str | None = None,
    content_desc: str | None = None,
    class_name: str | None = None,
    package: str | None = None,
    xpath: str | None = None,
    timeout: float = 5.0,
) -> bool:
    device = get_device(udid)
    target = _target_by_selector(
        device,
        text=text,
        resource_id=resource_id,
        content_desc=content_desc,
        class_name=class_name,
        package=package,
        xpath=xpath,
        timeout=timeout,
    )
    return target is not None


def input_selector(
    udid: str,
    value: str,
    *,
    text: str | None = None,
    resource_id: str | None = None,
    content_desc: str | None = None,
    class_name: str | None = None,
    package: str | None = None,
    xpath: str | None = None,
    clear: bool = True,
    timeout: float = 5.0,
) -> bool:
    device = get_device(udid)
    target = _target_by_selector(
        device,
        text=text,
        resource_id=resource_id,
        content_desc=content_desc,
        class_name=class_name,
        package=package,
        xpath=xpath,
        timeout=timeout,
    )
    if target is None:
        return False

    if clear:
        clear_text = getattr(target, "clear_text", None)
        if callable(clear_text):
            clear_text()

    set_text = getattr(target, "set_text", None)
    if callable(set_text):
        set_text(value)
        return True

    _click_target(target, timeout)
    send_keys = getattr(device, "send_keys", None)
    if callable(send_keys):
        try:
            send_keys(value, clear=clear)
        except TypeError:
            send_keys(value)
        return True
    return False


def click(udid: str, x: int, y: int) -> None:
    device = get_device(udid)
    device.click(x, y)


def swipe(udid: str, sx: int, sy: int, ex: int, ey: int, duration: float = 0.5) -> None:
    device = get_device(udid)
    device.swipe(sx, sy, ex, ey, duration)


def screenshot(udid: str) -> bytes:
    device = get_device(udid)
    return device.screenshot()


def device_info(udid: str) -> dict[str, Any]:
    device = get_device(udid)
    return device.info
