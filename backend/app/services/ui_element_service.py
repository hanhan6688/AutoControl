from __future__ import annotations

import re
import json
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import requests

from app.config import settings
from app.services import u2_service, wda_service
from app.services.adb_service import ADBError, ADBService


class UIElementError(RuntimeError):
    pass


@dataclass(frozen=True)
class MobileBounds:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.width // 2, self.top + self.height // 2)

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x <= self.right and self.top <= y <= self.bottom


@dataclass(frozen=True)
class MobileUiElement:
    platform: str
    package: str | None
    class_name: str
    text: str | None
    content_desc: str | None
    resource_id: str | None
    clickable: bool
    enabled: bool
    bounds: MobileBounds
    xpath: str
    hierarchy_xpath: str
    selector: dict[str, str]
    depth: int
    index: int


@dataclass(frozen=True)
class UiLocateResult:
    found: bool
    element: MobileUiElement | None
    generated_code: str
    message: str


class UIElementService:
    _hierarchy_cache: dict[str, tuple[float, str]] = {}
    _hierarchy_cache_lock = threading.RLock()

    def __init__(self, adb: ADBService | None = None) -> None:
        self.adb = adb or ADBService()

    def fetch_hierarchy(
        self,
        udid: str,
        *,
        platform: str = "android",
        wda_url: str | None = None,
        cache_ttl_ms: int = 0,
    ) -> str:
        normalized_platform = (platform or "android").strip().lower()
        if normalized_platform == "ios":
            return self._fetch_ios_source(
                udid=udid,
                wda_url=wda_url,
                cache_ttl_ms=cache_ttl_ms,
            )
        return self._dump_android_hierarchy(udid, cache_ttl_ms=cache_ttl_ms)

    def locate_device_point(
        self,
        *,
        udid: str,
        x: int,
        y: int,
        platform: str = "android",
        package_name: str | None = None,
        strict_xpath_only: bool = False,
        cache_ttl_ms: int = 0,
        wda_url: str | None = None,
    ) -> UiLocateResult:
        normalized_platform = platform.lower()
        if normalized_platform == "android":
            xml = self._dump_android_hierarchy(udid, cache_ttl_ms=cache_ttl_ms)
            return self.locate_generic_xml(
                xml=xml,
                x=x,
                y=y,
                platform="android",
                package_name=package_name,
                strict_xpath_only=strict_xpath_only,
            )
        if normalized_platform == "ios":
            xml = self._fetch_ios_source(
                udid=udid,
                wda_url=wda_url,
                cache_ttl_ms=cache_ttl_ms,
            )
            return self.locate_generic_xml(
                xml=xml,
                x=x,
                y=y,
                platform="ios",
                package_name=package_name,
                strict_xpath_only=strict_xpath_only,
            )
        if normalized_platform in {"harmony", "鸿蒙"}:
            raise UIElementError("Harmony UI hierarchy locating is not wired yet; use OCR/image/coordinate fallback.")
        raise UIElementError(f"Unsupported platform for UI locating: {platform}")

    def locate_generic_xml(
        self,
        *,
        xml: str,
        x: int,
        y: int,
        platform: str,
        package_name: str | None = None,
        strict_xpath_only: bool = False,
    ) -> UiLocateResult:
        elements = self.parse_generic_hierarchy(xml, platform=platform)
        element = self.pick_element_at(elements, x=x, y=y, package_name=package_name)
        if element is None:
            outside_target_package = bool(package_name and [item for item in elements if item.bounds.contains(int(x), int(y))])
            return UiLocateResult(
                found=False,
                element=None,
                generated_code="" if strict_xpath_only else f"adb.click({int(x)}, {int(y)})",
                message=(
                    "UI element at point is outside target package; strict XPath mode did not generate fallback"
                    if strict_xpath_only and outside_target_package
                    else "no UI element found at point; strict XPath mode did not generate fallback"
                    if strict_xpath_only
                    else "UI element at point is outside target package; generated coordinate fallback"
                    if outside_target_package
                    else "no UI element found at point; generated coordinate fallback"
                ),
            )
        return UiLocateResult(
            found=True,
            element=element,
            generated_code=self.build_click_code(
                element,
                fallback=(int(x), int(y)),
                strict_xpath_only=strict_xpath_only,
            ),
            message="element located",
        )

    def parse_generic_hierarchy(self, xml: str, *, platform: str) -> list[MobileUiElement]:
        cleaned_xml = self._extract_xml(xml)
        try:
            root = ET.fromstring(cleaned_xml)
        except ET.ParseError as exc:
            raise UIElementError(f"Invalid UI hierarchy XML: {exc}") from exc

        elements: list[MobileUiElement] = []

        def visit(node: ET.Element, depth: int, absolute_xpath: str) -> None:
            if node.tag in {"node", "XCUIElementTypeApplication", "XCUIElementTypeWindow"} or node.attrib:
                bounds = self._read_bounds(node.attrib)
                if bounds is not None and bounds.area > 0:
                    element = self._build_element(
                        attrs=node.attrib,
                        tag=node.tag,
                        platform=platform,
                        depth=depth,
                        index=len(elements),
                        bounds=bounds,
                        absolute_xpath=absolute_xpath,
                    )
                    elements.append(element)
            sibling_counts: dict[str, int] = {}
            for child in list(node):
                child_name = self._xpath_node_name(child)
                sibling_counts[child_name] = sibling_counts.get(child_name, 0) + 1
                visit(child, depth + 1, f"{absolute_xpath}/{child_name}[{sibling_counts[child_name]}]")

        visit(root, 0, f"/{self._xpath_node_name(root)}")
        return elements

    def pick_element_at(
        self,
        elements: list[MobileUiElement],
        *,
        x: int,
        y: int,
        package_name: str | None = None,
    ) -> MobileUiElement | None:
        candidates = [item for item in elements if item.bounds.contains(int(x), int(y))]
        package = (package_name or "").strip()
        if package:
            same_package = [item for item in candidates if item.package == package]
            if same_package:
                candidates = same_package
            else:
                return None
        if not candidates:
            return None

        return sorted(
            candidates,
            key=lambda item: (
                self._locator_rank(item),
                0 if item.enabled else 1,
                item.bounds.area,
                -item.depth,
            ),
        )[0]

    def find_element(
        self,
        elements: list[MobileUiElement],
        *,
        text: str | None = None,
        resource_id: str | None = None,
        content_desc: str | None = None,
        class_name: str | None = None,
        package: str | None = None,
        xpath: str | None = None,
    ) -> MobileUiElement | None:
        candidates = elements
        filters = {
            "text": text,
            "resource_id": resource_id,
            "content_desc": content_desc,
            "class_name": class_name,
            "package": package,
            "xpath": xpath,
        }
        for attr, expected in filters.items():
            value = (expected or "").strip()
            if not value:
                continue
            if attr == "xpath":
                candidates = [item for item in candidates if item.xpath == value or item.hierarchy_xpath == value]
            else:
                candidates = [item for item in candidates if (getattr(item, attr) or "") == value]
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: (0 if item.clickable else 1, item.bounds.area, -item.depth))[0]

    @staticmethod
    def _locator_rank(element: MobileUiElement) -> int:
        if element.resource_id:
            return 0
        if element.content_desc:
            return 1
        if element.text:
            return 2
        if element.clickable:
            return 3
        return 4

    def click(
        self,
        *,
        udid: str,
        text: str | None = None,
        resource_id: str | None = None,
        content_desc: str | None = None,
        class_name: str | None = None,
        package: str | None = None,
        xpath: str | None = None,
        fallback: tuple[int, int] | None = None,
        ocr_text: str | None = None,
        image_path: str | None = None,
        timeout: float = 5.0,
    ) -> bool:
        if settings.u2_enabled and u2_service.has_stable_selector(
            text=text,
            resource_id=resource_id,
            content_desc=content_desc,
            xpath=xpath,
        ):
            try:
                if u2_service.click_selector(
                    udid,
                    text=text,
                    resource_id=resource_id,
                    content_desc=content_desc,
                    class_name=class_name,
                    package=package,
                    xpath=xpath,
                    timeout=timeout,
                ):
                    return True
            except Exception:
                pass

        deadline = time.monotonic() + max(0.1, float(timeout))
        last_error: Exception | None = None
        while time.monotonic() <= deadline:
            try:
                xml = self._fetch_android_xml(udid)
                element = self.find_element(
                    self.parse_generic_hierarchy(xml, platform="android"),
                    text=text,
                    resource_id=resource_id,
                    content_desc=content_desc,
                    class_name=class_name,
                    package=package,
                    xpath=xpath,
                )
                if element is not None:
                    x, y = element.bounds.center
                    self._tap_device(udid, x, y)
                    return True
            except (ADBError, UIElementError) as exc:
                last_error = exc
            time.sleep(0.3)

        if ocr_text:
            from app.services.visual_action_service import VisualActionService

            if VisualActionService(adb=self.adb).click_text(udid, ocr_text).found:
                return True

        if image_path:
            from pathlib import Path
            from app.services.visual_action_service import VisualActionService

            template_path = Path(image_path)
            if not template_path.is_absolute():
                template_path = settings.scripts_dir / image_path
            if template_path.exists() and VisualActionService(adb=self.adb).click_template(
                udid=udid,
                template_png=template_path.read_bytes(),
            ).found:
                return True

        if fallback is not None:
            x, y = fallback
            self._tap_device(udid, int(x), int(y))
            return True

        if last_error is not None:
            raise UIElementError(str(last_error)) from last_error
        return False

    def dump(self, *, udid: str) -> list[dict[str, Any]]:
        xml = self._fetch_android_xml(udid)
        return [self.element_to_dict(item) for item in self.parse_generic_hierarchy(xml, platform="android")]

    @classmethod
    def clear_hierarchy_cache(cls) -> None:
        with cls._hierarchy_cache_lock:
            cls._hierarchy_cache.clear()

    def _dump_android_hierarchy(self, udid: str, *, cache_ttl_ms: int) -> str:
        ttl_seconds = max(0, int(cache_ttl_ms)) / 1000
        now = time.monotonic()
        cache_key = f"android:{udid}"
        if ttl_seconds > 0:
            with self._hierarchy_cache_lock:
                cached = self._hierarchy_cache.get(cache_key)
                if cached and now - cached[0] <= ttl_seconds:
                    return cached[1]

        xml = self._fetch_android_xml(udid)
        with self._hierarchy_cache_lock:
            self._hierarchy_cache[cache_key] = (time.monotonic(), xml)
        return xml

    def _fetch_android_xml(self, udid: str) -> str:
        if settings.u2_enabled:
            try:
                return u2_service.dump_hierarchy(udid)
            except Exception:
                pass
        return self.adb.dump_ui_hierarchy(udid)

    def _tap_device(self, udid: str, x: int, y: int) -> None:
        if settings.u2_enabled:
            try:
                u2_service.click(udid, x, y)
                return
            except Exception:
                pass
        self.adb.shell(udid, f"input tap {x} {y}")

    def build_click_code(
        self,
        element: MobileUiElement,
        *,
        fallback: tuple[int, int],
        strict_xpath_only: bool = False,
    ) -> str:
        if strict_xpath_only:
            return f"auto_execute.click(xpath={self._py_string(element.xpath or element.hierarchy_xpath)})"

        parts: list[str] = []
        for key in self._preferred_click_keys(element):
            value = getattr(element, key)
            if value:
                parts.append(f"{key}={self._py_string(value)}")
        if element.text:
            parts.append(f"ocr_text={self._py_string(element.text)}")
        parts.append(f"fallback=({int(fallback[0])}, {int(fallback[1])})")
        return f"auto_execute.click({', '.join(parts)})"

    def build_input_code(self, element: MobileUiElement, text: str) -> str:
        return (
            f"auto_execute.input(xpath={self._py_string(element.xpath or element.hierarchy_xpath)}, "
            f"text={self._py_string(text)})"
        )

    @staticmethod
    def is_text_input(element: MobileUiElement) -> bool:
        class_name = (element.class_name or "").lower()
        android_or_web_input = any(
            marker in class_name
            for marker in (
                "edittext",
                "autocompletetextview",
                "textarea",
                "input",
            )
        )
        ios_input = element.platform == "ios" and any(
            marker in class_name
            for marker in (
                "textfield",
                "securetextfield",
                "textview",
            )
        )
        return android_or_web_input or ios_input

    @staticmethod
    def element_to_dict(element: MobileUiElement) -> dict[str, Any]:
        return {
            "platform": element.platform,
            "package": element.package,
            "class_name": element.class_name,
            "text": element.text,
            "content_desc": element.content_desc,
            "resource_id": element.resource_id,
            "clickable": element.clickable,
            "enabled": element.enabled,
            "bounds": {
                "left": element.bounds.left,
                "top": element.bounds.top,
                "right": element.bounds.right,
                "bottom": element.bounds.bottom,
                "width": element.bounds.width,
                "height": element.bounds.height,
                "center_x": element.bounds.center[0],
                "center_y": element.bounds.center[1],
            },
            "xpath": element.xpath,
            "hierarchy_xpath": element.hierarchy_xpath,
            "selector": element.selector,
            "depth": element.depth,
            "index": element.index,
        }

    def _build_element(
        self,
        *,
        attrs: dict[str, str],
        tag: str,
        platform: str,
        depth: int,
        index: int,
        bounds: MobileBounds,
        absolute_xpath: str,
    ) -> MobileUiElement:
        class_name = attrs.get("class") or attrs.get("type") or tag
        text = self._clean_text(attrs.get("text") or attrs.get("label") or attrs.get("name") or attrs.get("value"))
        content_desc = self._clean_text(attrs.get("content-desc") or attrs.get("contentDescription") or attrs.get("name"))
        resource_id = self._clean_text(attrs.get("resource-id") or attrs.get("resourceId") or attrs.get("id"))
        package = self._clean_text(attrs.get("package") or attrs.get("bundleId"))
        clickable = self._bool_attr(attrs.get("clickable")) or self._bool_attr(attrs.get("enabled")) and class_name.endswith("Button")
        enabled = not attrs.get("enabled") or self._bool_attr(attrs.get("enabled"))
        selector = self._build_selector(
            text=text,
            resource_id=resource_id,
            content_desc=content_desc,
            class_name=class_name,
            package=package,
        )
        return MobileUiElement(
            platform=platform,
            package=package,
            class_name=class_name,
            text=text,
            content_desc=content_desc,
            resource_id=resource_id,
            clickable=clickable,
            enabled=enabled,
            bounds=bounds,
            xpath=self._build_xpath(class_name, selector, absolute_xpath=absolute_xpath),
            hierarchy_xpath=absolute_xpath,
            selector=selector,
            depth=depth,
            index=index,
        )

    @staticmethod
    def _build_selector(
        *,
        text: str | None,
        resource_id: str | None,
        content_desc: str | None,
        class_name: str,
        package: str | None,
    ) -> dict[str, str]:
        selector: dict[str, str] = {}
        if resource_id:
            selector["resource_id"] = resource_id
        if text:
            selector["text"] = text
        if content_desc:
            selector["content_desc"] = content_desc
        if class_name:
            selector["class_name"] = class_name
        if package:
            selector["package"] = package
        return selector

    @staticmethod
    def _preferred_click_keys(element: MobileUiElement) -> tuple[str, ...]:
        if element.resource_id:
            return ("resource_id", "package", "xpath")
        if element.content_desc:
            return ("content_desc", "package", "xpath")
        if element.text:
            return ("text", "package", "xpath")
        return ("class_name", "package", "xpath")

    @staticmethod
    def _build_xpath(class_name: str, selector: dict[str, str], *, absolute_xpath: str | None = None) -> str:
        """Build a stable xpath, falling back to a unique hierarchy path."""
        conditions: list[str] = []

        # Strong selectors should survive layout movement. Package alone is not a locator.
        if selector.get("resource_id"):
            conditions.append(f'@resource-id="{selector["resource_id"]}"')
        elif selector.get("content_desc"):
            conditions.append(f'@content-desc="{selector["content_desc"]}"')
            if selector.get("package"):
                conditions.append(f'@package="{selector["package"]}"')
        elif selector.get("text"):
            conditions.append(f'@text="{selector["text"]}"')
            if selector.get("package"):
                conditions.append(f'@package="{selector["package"]}"')

        if conditions:
            return f'//{class_name}[{" and ".join(conditions)}]'
        return absolute_xpath or f"//{class_name}"

    @staticmethod
    def _xpath_node_name(node: ET.Element) -> str:
        return node.attrib.get("class") or node.attrib.get("type") or node.tag

    @staticmethod
    def _read_bounds(attrs: dict[str, str]) -> MobileBounds | None:
        raw_bounds = attrs.get("bounds") or attrs.get("rect") or ""
        match = re.search(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", raw_bounds)
        if match:
            return MobileBounds(*(int(match.group(i)) for i in range(1, 5)))

        x = attrs.get("x")
        y = attrs.get("y")
        width = attrs.get("width")
        height = attrs.get("height")
        if x and y and width and height:
            left = int(float(x))
            top = int(float(y))
            return MobileBounds(left=left, top=top, right=left + int(float(width)), bottom=top + int(float(height)))
        return None

    @staticmethod
    def _extract_xml(value: str) -> str:
        start = value.find("<")
        end = value.rfind(">")
        if start == -1 or end == -1 or end <= start:
            raise UIElementError("UI hierarchy output does not contain XML")
        return value[start : end + 1]

    @staticmethod
    def _clean_text(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @staticmethod
    def _bool_attr(value: str | None) -> bool:
        return str(value or "").strip().lower() == "true"

    @staticmethod
    def _py_string(value: str) -> str:
        import json

        return json.dumps(value, ensure_ascii=False)

    @classmethod
    def _fetch_ios_source(
        cls,
        *,
        udid: str = "",
        wda_url: str | None = None,
        cache_ttl_ms: int = 0,
    ) -> str:
        cache_key = f"ios:{udid or wda_url or settings.autoglm_wda_url}"
        ttl_seconds = max(0, int(cache_ttl_ms)) / 1000
        if ttl_seconds > 0:
            now = time.monotonic()
            with cls._hierarchy_cache_lock:
                cached = cls._hierarchy_cache.get(cache_key)
                if cached and now - cached[0] <= ttl_seconds:
                    return cached[1]

        source = cls._fetch_ios_xml(udid=udid, wda_url=wda_url)
        if ttl_seconds > 0:
            with cls._hierarchy_cache_lock:
                cls._hierarchy_cache[cache_key] = (time.monotonic(), source)
        return source

    @classmethod
    def _fetch_ios_xml(cls, *, udid: str, wda_url: str | None) -> str:
        if settings.wda_enabled:
            try:
                return wda_service.dump_source(udid or "ios-default", wda_url=wda_url)
            except TypeError:
                try:
                    return wda_service.dump_source(udid or "ios-default")
                except Exception:
                    pass
            except Exception:
                pass
        return cls._fetch_ios_xml_http(wda_url=wda_url)

    @classmethod
    def _fetch_ios_xml_http(cls, *, wda_url: str | None) -> str:
        url = (wda_url or settings.autoglm_wda_url).rstrip("/") + "/source"
        response = requests.get(url, timeout=10, verify=False)
        if response.status_code >= 400:
            raise UIElementError(f"WDA source request failed: HTTP {response.status_code}")
        return cls._extract_source_payload(response.text)

    @staticmethod
    def _extract_source_payload(value: str) -> str:
        stripped = value.strip()
        if not stripped.startswith("{"):
            return value
        try:
            payload = json.loads(stripped)
        except ValueError:
            return value
        if not isinstance(payload, dict):
            return value
        source = payload.get("source") or payload.get("xml") or payload.get("hierarchy")
        return source if isinstance(source, str) else value
