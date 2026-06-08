from __future__ import annotations

import asyncio
import json
import contextlib
import io
import os
import sys
import time
import threading
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.config import settings
from app.services.adb_service import ADBService
from app.services import u2_service, wda_service
from app.services.pc_browser_service import PCBrowserService
from app.services.ui_element_service import UIElementService, MobileUiElement
from app.services.visual_action_service import VisualActionService
from app.services.script_run_service import (
    create_run,
    get_run,
    remove_run,
    execute_script_streaming,
    cancel_run,
    get_python_envs,
)
from app.automation.core.driver import DeviceDriver, ElementRef
from app.automation.drivers.android_driver import AndroidDriver
from app.automation.drivers.ios_driver import IOSDriver


router = APIRouter(prefix="/api/scripts", tags=["scripts"])

SCRIPTS_DIR = settings.scripts_dir
SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)


# ── User Input Request System ───────────────────────────────────────────────

@dataclass
class UserInputRequest:
    """A pending user input request (e.g., verification code)."""
    id: str
    prompt: str
    input_type: str = "text"  # text, password, number
    timeout: float = 300.0  # seconds
    created_at: float = field(default_factory=time.time)
    response: str | None = None
    responded: threading.Event = field(default_factory=threading.Event)
    cancelled: bool = False


# Global storage for pending input requests
_pending_inputs: dict[str, UserInputRequest] = {}
_pending_inputs_lock = threading.Lock()


def _create_input_request(prompt: str, input_type: str = "text", timeout: float = 300.0) -> UserInputRequest:
    """Create a new user input request."""
    request_id = str(uuid.uuid4())[:8]
    request = UserInputRequest(
        id=request_id,
        prompt=prompt,
        input_type=input_type,
        timeout=timeout,
    )
    with _pending_inputs_lock:
        _pending_inputs[request_id] = request
    return request


def _wait_for_input(request: UserInputRequest) -> str | None:
    """Wait for user input response."""
    responded = request.responded.wait(timeout=request.timeout)
    with _pending_inputs_lock:
        if request.id in _pending_inputs:
            del _pending_inputs[request.id]
    if not responded:
        return None
    return request.response


# ── schemas ──────────────────────────────────────────────────────────────────

class ScriptFile(BaseModel):
    name: str
    path: str
    size: int
    modified_at: str
    platform: str | None = None


class ScriptContent(BaseModel):
    content: str


class ScriptRunResult(BaseModel):
    name: str
    stdout: str
    stderr: str
    returncode: int
    duration_ms: int


class ScriptRunStreamStart(BaseModel):
    run_id: str
    python_path: str


class PythonEnvInfo(BaseModel):
    name: str
    path: str


class PythonEnvsResponse(BaseModel):
    current: str
    default: str
    envs: list[PythonEnvInfo]


class UserInputRequestModel(BaseModel):
    id: str
    prompt: str
    input_type: str
    timeout: float
    created_at: float


class UserInputResponse(BaseModel):
    value: str


class CreateScriptRequest(BaseModel):
    name: str
    content: str = ""
    platform: str | None = None  # "android", "ios", "harmony" — auto-place in subfolder


class SaveScriptRequest(BaseModel):
    content: str


class CreateFolderRequest(BaseModel):
    path: str  # relative path like "subfolder" or "subfolder/nested"


class FileTreeItem(BaseModel):
    name: str
    path: str
    type: str  # "file" or "folder"
    size: int | None = None
    modified_at: str | None = None
    children: list["FileTreeItem"] | None = None
    platform: str | None = None  # "android", "ios", "harmony" for platform dirs/files


# ── helpers ──────────────────────────────────────────────────────────────────

def _rel(path: Path) -> str:
    return str(path.relative_to(SCRIPTS_DIR))


def _info(p: Path) -> ScriptFile:
    stat = p.stat()
    modified = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))
    # Infer platform from path
    platform: str | None = None
    try:
        rel = p.relative_to(SCRIPTS_DIR)
        first_part = rel.parts[0] if len(rel.parts) > 1 else None
        if first_part in PLATFORM_DIRS:
            platform = first_part
    except ValueError:
        pass
    return ScriptFile(name=p.name, path=_rel(p), size=stat.st_size, modified_at=modified, platform=platform)


def _tree_info(p: Path) -> FileTreeItem:
    """Create FileTreeItem for a file or folder."""
    if p.is_file():
        stat = p.stat()
        modified = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime))
        return FileTreeItem(
            name=p.name,
            path=_rel(p),
            type="file",
            size=stat.st_size,
            modified_at=modified,
            children=None,
        )
    else:
        return FileTreeItem(
            name=p.name,
            path=_rel(p),
            type="folder",
            size=None,
            modified_at=None,
            children=None,
        )


def _build_file_tree(root: Path, max_depth: int = 10) -> list[FileTreeItem]:
    """Build a recursive file tree structure. Platform subdirs always appear."""
    if max_depth <= 0:
        return []

    # At root level, ensure platform dirs exist on disk
    if root.resolve() == SCRIPTS_DIR.resolve():
        _ensure_platform_dirs()

    items: list[FileTreeItem] = []
    try:
        entries = sorted(root.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    except OSError:
        return []

    for entry in entries:
        # Skip hidden files/folders
        if entry.name.startswith("."):
            continue

        if entry.is_dir():
            folder_item = _tree_info(entry)
            folder_item.children = _build_file_tree(entry, max_depth - 1)
            folder_item.platform = entry.name if entry.name in PLATFORM_DIRS else None
            items.append(folder_item)
        elif entry.is_file() and entry.suffix == ".py":
            file_item = _tree_info(entry)
            # Infer platform from parent path relative to SCRIPTS_DIR
            try:
                rel = entry.relative_to(SCRIPTS_DIR)
                first_part = rel.parts[0] if len(rel.parts) > 1 else None
                file_item.platform = first_part if first_part in PLATFORM_DIRS else None
            except ValueError:
                pass
            items.append(file_item)

    return items


PLATFORM_DIRS = {"android", "ios", "harmony"}


def _ensure_platform_dirs() -> None:
    for p in PLATFORM_DIRS:
        (SCRIPTS_DIR / p).mkdir(parents=True, exist_ok=True)


def _script_path(path: str, *, must_exist: bool = True) -> Path:
    if not path.strip() or Path(path).is_absolute():
        raise HTTPException(status_code=400, detail="Invalid path")

    root = SCRIPTS_DIR.resolve()
    file_path = (root / path).resolve()
    if root != file_path and root not in file_path.parents:
        raise HTTPException(status_code=400, detail="Invalid path")
    if file_path.suffix != ".py":
        raise HTTPException(status_code=400, detail="Only .py scripts are supported")
    if must_exist and not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"Script not found: {path}")
    return file_path


class ScriptADB:
    def __init__(self, udid: str, adb_service: ADBService | None = None) -> None:
        self.udid = udid
        self.adb = adb_service or ADBService()

    def click(self, x: int, y: int) -> None:
        if settings.u2_enabled:
            try:
                u2_service.click(self.udid, x, y)
                return
            except Exception:
                pass
        self.adb.shell(self.udid, f"input tap {int(x)} {int(y)}")

    def tap(self, x: int, y: int) -> None:
        self.click(x, y)

    def swipe(self, start: tuple[int, int], end: tuple[int, int], duration: int = 300) -> None:
        x1, y1 = start
        x2, y2 = end
        dur = duration / 1000.0
        if settings.u2_enabled:
            try:
                u2_service.swipe(self.udid, x1, y1, x2, y2, dur)
                return
            except Exception:
                pass
        self.adb.shell(self.udid, f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration)}")

    def back(self) -> None:
        self.key(4)

    def home(self) -> None:
        self.key(3)

    def key(self, keycode: int) -> None:
        self.adb.shell(self.udid, f"input keyevent {int(keycode)}")

    def text(self, value: str) -> None:
        self.adb.input_text(self.udid, value)

    def input(self, value: str) -> None:
        self.text(value)

    def wait(self, seconds: float = 1.0) -> None:
        time.sleep(seconds)

    def screenshot(self) -> bytes:
        """Capture screen and return PNG bytes."""
        if settings.u2_enabled:
            try:
                return u2_service.screenshot(self.udid)
            except Exception:
                pass
        return self.adb.capture_screen_png(self.udid)


class ScriptOCR:
    """OCR-based actions for script execution."""

    def __init__(self, udid: str, visual_service: VisualActionService | None = None) -> None:
        self.udid = udid
        self.visual = visual_service or VisualActionService()

    def click(self, text: str, contains: bool = True) -> bool:
        """
        Click on text found on screen.

        Usage:
            ocr.click("登录")        # Click text containing "登录"
            ocr.click("登录", False)  # Click exact match "登录"
        """
        match = self.visual.click_text(self.udid, text, contains=contains)
        return match.found

    def find(self, text: str, contains: bool = True) -> dict | None:
        """
        Find text on screen without clicking.

        Returns dict with 'x', 'y', 'text', 'score' if found, else None.
        """
        screen_png = self.visual.adb.capture_screen_png(self.udid)
        blocks = self.visual._recognize_text_blocks(screen_png)
        target = text.strip()
        for block in blocks:
            block_text = str(block.get("text", ""))
            matched = target in block_text if contains else target == block_text
            if matched:
                x, y = self.visual._box_center(block.get("box"))
                return {
                    "x": x,
                    "y": y,
                    "text": block_text,
                    "score": float(block.get("score", 0)),
                }
        return None

    def find_all(self) -> list[dict]:
        """
        Find all text blocks on screen.

        Returns list of dicts with 'x', 'y', 'text', 'score'.
        """
        screen_png = self.visual.adb.capture_screen_png(self.udid)
        blocks = self.visual._recognize_text_blocks(screen_png)
        results = []
        for block in blocks:
            x, y = self.visual._box_center(block.get("box"))
            results.append({
                "x": x,
                "y": y,
                "text": str(block.get("text", "")),
                "score": float(block.get("score", 0)),
            })
        return results


def _resolve_template_file(template_path: str) -> Path:
    template_file = Path(template_path)
    if not template_file.exists():
        template_file = SCRIPTS_DIR / template_path
    if not template_file.exists():
        template_file = settings.project_root / template_path
    if not template_file.exists():
        raise FileNotFoundError(f"Template image not found: {template_path}")
    return template_file


class ScriptImage:
    """Template image matching actions for script execution."""

    def __init__(self, udid: str, visual_service: VisualActionService | None = None) -> None:
        self.udid = udid
        self.visual = visual_service or VisualActionService()

    def click(self, template_path: str, threshold: float = 0.92) -> bool:
        """
        Click on template image found on screen.

        Usage:
            image.click("templates/login_btn.png")  # Click with default threshold
            image.click("templates/icon.png", 0.85) # Click with lower threshold
        """
        template_file = _resolve_template_file(template_path)
        template_png = template_file.read_bytes()
        match = self.visual.click_template(self.udid, template_png, threshold=threshold)
        return match.found

    def find(self, template_path: str, threshold: float = 0.92) -> dict | None:
        """
        Find template image on screen without clicking.

        Returns dict with 'x', 'y', 'score', 'width', 'height' if found, else None.
        """
        template_file = _resolve_template_file(template_path)
        template_png = template_file.read_bytes()
        screen_png = self.visual.adb.capture_screen_png(self.udid)
        match = self.visual.find_template(screen_png, template_png, threshold=threshold)

        if match.found:
            return {
                "x": match.x,
                "y": match.y,
                "score": match.score,
                "width": match.width,
                "height": match.height,
            }
        return None

    def wait_for(self, template_path: str, timeout: float = 10.0, threshold: float = 0.92) -> bool:
        """
        Wait for template image to appear on screen.

        Usage:
            if image.wait_for("templates/success.png", timeout=5):
                print("Success!")
        """
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            if self.find(template_path, threshold):
                return True
            time.sleep(0.5)
        return False


class ScriptUI:
    """UI hierarchy based actions for replayable mobile regression scripts."""

    def __init__(
        self,
        udid: str,
        ui_service: UIElementService | None = None,
        adb_service: ADBService | None = None,
        *,
        platform: str = "android",
        wda_url: str | None = None,
    ) -> None:
        self.udid = udid
        self.ui = ui_service or UIElementService()
        self.adb = adb_service or ADBService()
        self.platform = platform.lower()
        self.wda_url = (wda_url or settings.autoglm_wda_url).rstrip("/")
        # V2: Create DeviceDriver for delegation
        if self.platform == "ios":
            self._driver = IOSDriver(udid=self.udid, wda_url=self.wda_url)
        else:
            self._driver = AndroidDriver(udid=self.udid)

    def _parse_selector(
        self,
        resource_id: str | None = None,
        text: str | None = None,
        content_desc: str | None = None,
        class_name: str | None = None,
        xpath: str | None = None,
    ) -> tuple[str | None, str | None]:
        """Parse selector kwargs into (locator_type, locator_value)."""
        if resource_id:
            return ("resource_id", resource_id)
        if text:
            return ("text", text)
        if content_desc:
            return ("content_desc", content_desc)
        if class_name:
            return ("class_name", class_name)
        if xpath:
            return ("xpath", xpath)
        return (None, None)

    def click(
        self,
        text: str | int | float | None = None,
        resource_id: str | int | float | None = None,
        content_desc: str | None = None,
        class_name: str | None = None,
        package: str | None = None,
        xpath: str | None = None,
        fallback: tuple[int, int] | None = None,
        ocr_text: str | None = None,
        image_path: str | None = None,
        timeout: float = 5.0,
    ) -> bool:
        """
        Click by mobile UI hierarchy first, then optional OCR/image/coordinate fallback.

        Usage:
            auto_execute.click(text="登录", package="com.example", fallback=(360, 820))
            auto_execute.click(resource_id="com.example:id/login", fallback=(360, 820))
            auto_execute.click(360, 820)
        """
        if isinstance(text, (int, float)) and isinstance(resource_id, (int, float)):
            x, y = int(text), int(resource_id)
            # V2: try driver first
            try:
                self._driver.tap(x, y)
                return True
            except Exception:
                pass
            # Legacy fallback
            if self.platform == "ios":
                wda_service.click(self.udid, x, y, wda_url=self.wda_url)
                return True
            if settings.u2_enabled:
                try:
                    u2_service.click(self.udid, x, y)
                    return True
                except Exception:
                    pass
            self.adb.shell(self.udid, f"input tap {x} {y}", timeout=10)
            return True

        if self.platform == "ios":
            return self._click_ios(
                text=str(text) if text is not None else None,
                resource_id=str(resource_id) if resource_id is not None else None,
                content_desc=content_desc,
                class_name=class_name,
                xpath=xpath,
                timeout=timeout,
            )

        return self.ui.click(
            udid=self.udid,
            text=str(text) if text is not None else None,
            resource_id=str(resource_id) if resource_id is not None else None,
            content_desc=content_desc,
            class_name=class_name,
            package=package,
            xpath=xpath,
            fallback=fallback,
            ocr_text=ocr_text,
            image_path=image_path,
            timeout=timeout,
        )

    def find(
        self,
        text: str | None = None,
        resource_id: str | None = None,
        content_desc: str | None = None,
        class_name: str | None = None,
        package: str | None = None,
        xpath: str | None = None,
    ) -> dict | None:
        if self.platform == "ios":
            xml = self.ui._fetch_ios_source(
                wda_url=self.wda_url,
                cache_ttl_ms=800,
            )
            elements = self.ui.parse_generic_hierarchy(xml, platform="ios")
        else:
            elements = self.ui.parse_generic_hierarchy(self.ui._fetch_android_xml(self.udid), platform="android")
        element = self.ui.find_element(
            elements,
            text=text,
            resource_id=resource_id,
            content_desc=content_desc,
            class_name=class_name,
            package=package,
            xpath=xpath,
        )
        return self.ui.element_to_dict(element) if element else None

    def dump(self) -> list[dict]:
        if self.platform == "ios":
            xml = self.ui._fetch_ios_source(
                udid=self.udid,
                wda_url=self.wda_url,
                cache_ttl_ms=800,
            )
            return [self.ui.element_to_dict(item) for item in self.ui.parse_generic_hierarchy(xml, platform="ios")]
        return self.ui.dump(udid=self.udid)

    def launch(self, app_id: str) -> bool:
        """Launch app by Android package name or iOS bundle id."""
        # V2: try driver first
        try:
            self._driver.launch(app_id)
            return True
        except Exception:
            pass
        # Legacy fallback
        if self.platform == "ios":
            wda_service.launch_app(self.udid, app_id, wda_url=self.wda_url)
            return True
        return _launch_app(self.udid, app_id)

    def swipe(self, start: tuple[int, int], end: tuple[int, int], duration: int = 300) -> None:
        """Swipe from start to end coordinates."""
        x1, y1 = start
        x2, y2 = end
        # V2: try driver first
        try:
            self._driver.swipe(x1, y1, x2, y2, duration_ms=duration)
            return
        except Exception:
            pass
        # Legacy fallback
        if self.platform == "ios":
            wda_service.swipe(self.udid, x1, y1, x2, y2, duration / 1000.0, wda_url=self.wda_url)
            return
        dur = duration / 1000.0
        if settings.u2_enabled:
            try:
                u2_service.swipe(self.udid, x1, y1, x2, y2, dur)
                return
            except Exception:
                pass
        self.adb.shell(self.udid, f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration)}")

    def swape(self, start: tuple[int, int], end: tuple[int, int], duration: int = 300) -> None:
        """Compatibility alias for misspelled swipe commands."""
        self.swipe(start, end, duration)

    def scroll_up(self, amount: int = 500, duration: int = 300) -> None:
        """Scroll up by given amount."""
        self.swipe((540, 1800), (540, 1800 - amount), duration)

    def scroll_down(self, amount: int = 500, duration: int = 300) -> None:
        """Scroll down by given amount."""
        self.swipe((540, 500), (540, 500 + amount), duration)

    def back(self) -> None:
        """Press back key."""
        if self.platform == "ios":
            wda_service.get_client(self.udid, wda_url=self.wda_url).back()
            return
        self.adb.shell(self.udid, "input keyevent 4")

    def home(self) -> None:
        """Press home key."""
        if self.platform == "ios":
            wda_service.get_client(self.udid, wda_url=self.wda_url).home()
            return
        self.adb.shell(self.udid, "input keyevent 3")

    def text(self, value: str) -> None:
        """Input text using ADBKeyboard (supports Chinese and special characters)."""
        if self.platform == "ios":
            self._input_ios(value)
            return
        self._input_with_keyboard(value)

    def input(
        self,
        value: str | None = None,
        *,
        text: str | None = None,
        resource_id: str | None = None,
        content_desc: str | None = None,
        class_name: str | None = None,
        package: str | None = None,
        xpath: str | None = None,
        clear: bool = True,
        timeout: float = 5.0,
    ) -> None:
        """Input text, optionally focusing a target field first.

        Args:
            clear: Clear existing text before typing (default True).
        """
        target_text = text if text is not None else value
        if target_text is None:
            return
        has_target = any([resource_id, content_desc, class_name, package, xpath])
        if (
            self.platform != "ios"
            and has_target
            and settings.u2_enabled
            and u2_service.has_stable_selector(
                text=None,
                resource_id=resource_id,
                content_desc=content_desc,
                xpath=xpath,
            )
        ):
            try:
                if u2_service.input_selector(
                    self.udid,
                    target_text,
                    text=None,
                    resource_id=resource_id,
                    content_desc=content_desc,
                    class_name=class_name,
                    package=package,
                    xpath=xpath,
                    clear=clear,
                    timeout=timeout,
                ):
                    return
            except Exception:
                pass
        if has_target:
            self.click(
                resource_id=resource_id,
                content_desc=content_desc,
                class_name=class_name,
                package=package,
                xpath=xpath,
                timeout=timeout,
            )
            time.sleep(0.15)
        self._input_with_keyboard(target_text, clear=clear)

    def _input_with_keyboard(self, value: str, *, clear: bool = True) -> None:
        """Input text via ADBKeyboard: switch IME → clear → type → restore IME."""
        if self.platform == "ios":
            self._input_ios(value)
            return
        ensure_keyboard = getattr(self.adb, "ensure_adb_keyboard", None)
        clear_text = getattr(self.adb, "clear_text", None)
        restore_keyboard = getattr(self.adb, "restore_keyboard", None)
        input_text = getattr(self.adb, "input_text", None)
        if not callable(input_text):
            raise AttributeError("ADBService.input_text is required for auto_execute.input")

        original_ime = ensure_keyboard(self.udid) if callable(ensure_keyboard) else None
        try:
            if clear and callable(clear_text):
                clear_text(self.udid)
                time.sleep(0.15)
            input_text(self.udid, value)
            time.sleep(0.1)
        finally:
            if original_ime and callable(restore_keyboard):
                restore_keyboard(self.udid, original_ime)

    def _click_ios(
        self,
        *,
        text: str | None,
        resource_id: str | None,
        content_desc: str | None,
        class_name: str | None,
        xpath: str | None,
        timeout: float,
    ) -> bool:
        deadline = time.monotonic() + max(0.1, float(timeout))
        while time.monotonic() <= deadline:
            xml = self.ui._fetch_ios_source(
                udid=self.udid,
                wda_url=self.wda_url,
                cache_ttl_ms=800,
            )
            element = self.ui.find_element(
                self.ui.parse_generic_hierarchy(xml, platform="ios"),
                text=text,
                resource_id=resource_id,
                content_desc=content_desc,
                class_name=class_name,
                xpath=xpath,
            )
            if element is not None:
                x, y = element.bounds.center
                wda_service.click(self.udid, x, y, wda_url=self.wda_url)
                return True
            time.sleep(0.3)
        return False

    def _input_ios(self, value: str) -> None:
        client = wda_service.get_client(self.udid, wda_url=self.wda_url)
        client.type(value)

    def wait(self, seconds: float = 1.0) -> None:
        """Wait for given seconds."""
        time.sleep(seconds)

    def wait_for_element(
        self,
        *,
        text: str | None = None,
        resource_id: str | None = None,
        content_desc: str | None = None,
        class_name: str | None = None,
        package: str | None = None,
        xpath: str | None = None,
        timeout: float = 10.0,
        poll_interval: float = 0.5,
    ) -> bool:
        """Poll until a matching UI element appears.

        Usage:
            if auto_execute.wait_for_element(text="登录", timeout=10):
                auto_execute.click(text="登录")
        """
        if (
            self.platform != "ios"
            and settings.u2_enabled
            and u2_service.has_stable_selector(
                text=text,
                resource_id=resource_id,
                content_desc=content_desc,
                xpath=xpath,
            )
        ):
            try:
                if u2_service.exists_selector(
                    self.udid,
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
        while time.monotonic() <= deadline:
            try:
                element = self._find_element(
                    text=text,
                    resource_id=resource_id,
                    content_desc=content_desc,
                    class_name=class_name,
                    package=package,
                    xpath=xpath,
                )
                if element is not None:
                    return True
            except Exception:
                pass
            remaining = deadline - time.monotonic()
            time.sleep(min(poll_interval, max(0.1, remaining)))
        return False

    def assert_element(
        self,
        *,
        text: str | None = None,
        resource_id: str | None = None,
        content_desc: str | None = None,
        class_name: str | None = None,
        package: str | None = None,
        xpath: str | None = None,
        expected_text: str | None = None,
        expected_enabled: bool | None = None,
        timeout: float = 5.0,
    ) -> dict[str, object]:
        """Assert element state — verify a UI element exists and optionally check its properties.

        Usage:
            result = auto_execute.assert_element(resource_id="com.example:id/title", expected_text="首页")
            assert result["found"], f"Element not found: {result}"
            assert result["text_matched"], f"Text mismatch: got {result['actual_text']}"

        Returns dict with keys: found, element, text_matched, enabled_matched, actual_text, actual_enabled, message.
        """
        found = self.wait_for_element(
            text=text,
            resource_id=resource_id,
            content_desc=content_desc,
            class_name=class_name,
            package=package,
            xpath=xpath,
            timeout=timeout,
        )
        if not found:
            return {
                "found": False,
                "element": None,
                "text_matched": False,
                "enabled_matched": False,
                "actual_text": None,
                "actual_enabled": None,
                "message": "element not found within timeout",
            }

        element = self._find_element(
            text=text,
            resource_id=resource_id,
            content_desc=content_desc,
            class_name=class_name,
            package=package,
            xpath=xpath,
        )
        element_dict = self.ui.element_to_dict(element) if element else None

        actual_text = element.text if element else None
        actual_enabled = element.enabled if element else None

        text_matched = expected_text is None or (actual_text or "") == expected_text
        enabled_matched = expected_enabled is None or actual_enabled == expected_enabled

        mismatches = []
        if not text_matched:
            mismatches.append(f"text: expected '{expected_text}', got '{actual_text}'")
        if not enabled_matched:
            mismatches.append(f"enabled: expected {expected_enabled}, got {actual_enabled}")

        return {
            "found": True,
            "element": element_dict,
            "text_matched": text_matched,
            "enabled_matched": enabled_matched,
            "actual_text": actual_text,
            "actual_enabled": actual_enabled,
            "message": "assertion passed" if not mismatches else "; ".join(mismatches),
        }

    def assert_text_visible(self, target_text: str, *, timeout: float = 5.0) -> dict[str, object]:
        """Check if text is visible on screen (UI hierarchy first, OCR fallback).

        Usage:
            result = auto_execute.assert_text_visible("登录成功", timeout=3)
            assert result["found"], "Login success text not visible"
        """
        found = self.wait_for_element(text=target_text, timeout=timeout / 2)
        if found:
            return {
                "found": True,
                "method": "ui_hierarchy",
                "text": target_text,
                "message": f"text '{target_text}' found in UI hierarchy",
            }

        remaining = timeout - (timeout / 2)
        deadline = time.monotonic() + max(0.1, remaining)
        visual = VisualActionService(adb=self.adb)
        while time.monotonic() <= deadline:
            try:
                screen_png = self.adb.capture_screen_png(self.udid)
                blocks = visual._recognize_text_blocks(screen_png)
                for block in blocks:
                    block_text = str(block.get("text", ""))
                    if target_text in block_text:
                        return {
                            "found": True,
                            "method": "ocr",
                            "text": target_text,
                            "matched_text": block_text,
                            "message": f"text '{target_text}' found via OCR",
                        }
            except Exception:
                pass
            time.sleep(0.5)

        return {
            "found": False,
            "method": None,
            "text": target_text,
            "message": f"text '{target_text}' not found on screen within {timeout}s",
        }

    def assert_element_exists(
        self,
        *,
        text: str | None = None,
        resource_id: str | None = None,
        content_desc: str | None = None,
        class_name: str | None = None,
        package: str | None = None,
        xpath: str | None = None,
        timeout: float = 5.0,
    ) -> dict[str, object]:
        """Compatibility wrapper for V2-generated scripts."""
        return self.assert_element(
            text=text,
            resource_id=resource_id,
            content_desc=content_desc,
            class_name=class_name,
            package=package,
            xpath=xpath,
            timeout=timeout,
        )

    def assert_ocr_contains(self, target_text: str, *, timeout: float = 5.0) -> dict[str, object]:
        target = (target_text or "").strip()
        if not target:
            return {"found": False, "text": target_text, "message": "target text is empty"}

        visual = VisualActionService(adb=self.adb)
        deadline = time.monotonic() + max(0.1, timeout)
        while time.monotonic() <= deadline:
            try:
                screen_png = self._driver.screenshot()
                blocks = visual._recognize_text_blocks(screen_png)
                for block in blocks:
                    block_text = str(block.get("text", ""))
                    if target in block_text:
                        return {
                            "found": True,
                            "text": target,
                            "matched_text": block_text,
                            "method": "ocr",
                            "message": f"text '{target}' found via OCR",
                        }
            except Exception:
                pass
            time.sleep(0.5)

        return {
            "found": False,
            "text": target,
            "method": "ocr",
            "message": f"text '{target}' not found via OCR within {timeout}s",
        }

    def assert_image_exists(
        self,
        template_path: str,
        *,
        threshold: float = 0.92,
        timeout: float = 5.0,
    ) -> dict[str, object]:
        visual = VisualActionService(adb=self.adb)
        template_png = _resolve_template_file(template_path).read_bytes()
        deadline = time.monotonic() + max(0.1, timeout)
        last_score = 0.0

        while time.monotonic() <= deadline:
            try:
                match = visual.find_template(self._driver.screenshot(), template_png, threshold=threshold)
            except Exception as exc:
                return {
                    "found": False,
                    "template_path": template_path,
                    "threshold": threshold,
                    "score": last_score,
                    "message": str(exc),
                }
            last_score = match.score
            if match.found:
                return {
                    "found": True,
                    "template_path": template_path,
                    "threshold": threshold,
                    "score": match.score,
                    "x": match.x,
                    "y": match.y,
                    "width": match.width,
                    "height": match.height,
                    "message": f"template '{template_path}' found",
                }
            time.sleep(0.5)

        return {
            "found": False,
            "template_path": template_path,
            "threshold": threshold,
            "score": last_score,
            "message": f"template '{template_path}' not found within {timeout}s",
        }

    def assert_app_foreground(self, app_id: str, *, timeout: float = 5.0) -> dict[str, object]:
        target = (app_id or "").strip()
        if not target:
            return {"found": False, "expected_app": app_id, "current_app": None, "message": "app id is empty"}

        deadline = time.monotonic() + max(0.1, timeout)
        last_app: str | None = None
        while time.monotonic() <= deadline:
            try:
                app_info = self._driver.current_app()
                last_app = app_info.get("package") or app_info.get("bundle_id") or app_info.get("app") or None
                if last_app == target:
                    return {
                        "found": True,
                        "expected_app": target,
                        "current_app": last_app,
                        "message": f"app '{target}' is in foreground",
                    }
            except Exception:
                pass
            time.sleep(0.5)

        return {
            "found": False,
            "expected_app": target,
            "current_app": last_app,
            "message": f"expected foreground app '{target}', got '{last_app}'",
        }

    def long_press(
        self,
        *,
        text: str | None = None,
        resource_id: str | None = None,
        content_desc: str | None = None,
        class_name: str | None = None,
        package: str | None = None,
        xpath: str | None = None,
        fallback: tuple[int, int] | None = None,
        duration: int = 800,
        timeout: float = 5.0,
    ) -> bool:
        """Long press on a UI element or coordinate fallback.

        Usage:
            auto_execute.long_press(text="消息", duration=1000)
            auto_execute.long_press(xpath="...", fallback=(360, 820))
        """
        deadline = time.monotonic() + max(0.1, float(timeout))
        while time.monotonic() <= deadline:
            try:
                element = self._find_element(
                    text=text,
                    resource_id=resource_id,
                    content_desc=content_desc,
                    class_name=class_name,
                    package=package,
                    xpath=xpath,
                )
                if element is not None:
                    x, y = element.bounds.center
                    if self.platform == "ios":
                        wda_service.get_client(self.udid, wda_url=self.wda_url).touch(x, y, duration / 1000.0)
                    else:
                        self.adb.shell(self.udid, f"input swipe {x} {y} {x} {y} {duration}")
                    return True
            except Exception:
                pass
            time.sleep(0.3)

        if fallback is not None:
            x, y = fallback
            if self.platform == "ios":
                wda_service.get_client(self.udid, wda_url=self.wda_url).touch(int(x), int(y), duration / 1000.0)
            else:
                self.adb.shell(self.udid, f"input swipe {int(x)} {int(y)} {int(x)} {int(y)} {duration}")
            return True

        return False

    def _find_element(
        self,
        *,
        text: str | None = None,
        resource_id: str | None = None,
        content_desc: str | None = None,
        class_name: str | None = None,
        package: str | None = None,
        xpath: str | None = None,
    ) -> MobileUiElement | None:
        if self.platform == "ios":
            xml = self.ui._fetch_ios_source(wda_url=self.wda_url, cache_ttl_ms=0)
            elements = self.ui.parse_generic_hierarchy(xml, platform="ios")
        else:
            elements = self.ui.parse_generic_hierarchy(self.ui._fetch_android_xml(self.udid), platform="android")
        return self.ui.find_element(
            elements,
            text=text,
            resource_id=resource_id,
            content_desc=content_desc,
            class_name=class_name,
            package=package,
            xpath=xpath,
        )


class ScriptInput:
    """User input prompts for script execution (e.g., verification codes)."""

    def prompt(self, message: str, input_type: str = "text", timeout: float = 300.0) -> str | None:
        """
        Prompt user for input. Shows a dialog in the frontend.

        Usage:
            code = input.prompt("请输入验证码")
            password = input.prompt("请输入密码", input_type="password")
            if code:
                adb.text(code)
            else:
                print("用户未输入或超时")
        """
        request = _create_input_request(message, input_type, timeout)
        print(f"[等待用户输入] {message} (ID: {request.id})")
        response = _wait_for_input(request)
        if response is None:
            print("[用户输入超时]")
        return response

    def verify_code(self, timeout: float = 300.0) -> str | None:
        """
        Convenience method for verification code input.

        Usage:
            code = input.verify_code()
        """
        return self.prompt("请输入验证码", input_type="text", timeout=timeout)

    def password(self, message: str = "请输入密码", timeout: float = 300.0) -> str | None:
        """
        Prompt for password input (masked).

        Usage:
            pwd = input.password()
        """
        return self.prompt(message, input_type="password", timeout=timeout)


class ScriptBrowser:
    """Browser automation actions for PC/Web script execution."""

    def __init__(self, session: str | None = None, browser_service: PCBrowserService | None = None) -> None:
        self.session = session or "script-browser"
        self.browser = browser_service or PCBrowserService()

    def open(self, url: str, headed: bool = False) -> dict:
        """Open browser and navigate to URL."""
        result = self.browser.open(url, session=self.session, headed=headed)
        return {"session_id": result.session_id, "url": result.url, "title": result.title}

    def close(self) -> None:
        """Close browser session."""
        self.browser.close(session=self.session)

    def click(self, element_ref: str, new_tab: bool = False) -> None:
        """Click element by ref (e.g., @e1)."""
        self.browser.click(element_ref, session=self.session, new_tab=new_tab)

    def fill(self, element_ref: str, text: str) -> None:
        """Fill input field (clear first)."""
        self.browser.fill(element_ref, text, session=self.session)

    def type_text(self, element_ref: str, text: str) -> None:
        """Type text into element (no clear)."""
        self.browser.type_text(element_ref, text, session=self.session)

    def press(self, key: str) -> None:
        """Press key (e.g., Enter, Tab, Escape)."""
        self.browser.press(key, session=self.session)

    def scroll(self, direction: str = "down", amount: int = 300) -> None:
        """Scroll page (up/down/left/right)."""
        self.browser.scroll(direction, amount, session=self.session)

    def wait_for_text(self, text: str, timeout_ms: int = 25000) -> None:
        """Wait for text to appear."""
        self.browser.wait_for_text(text, timeout_ms=timeout_ms, session=self.session)

    def wait_for_load(self, load_type: str = "networkidle") -> None:
        """Wait for page load (networkidle/domcontentloaded)."""
        self.browser.wait_for_load(load_type, session=self.session)

    def screenshot(self, path: str | Path, full_page: bool = False) -> Path:
        """Take screenshot."""
        return self.browser.screenshot(Path(path), full_page=full_page, session=self.session)

    def get_url(self) -> str:
        """Get current URL."""
        return self.browser.get_url(session=self.session)

    def get_title(self) -> str:
        """Get page title."""
        return self.browser.get_title(session=self.session)

    def snapshot(self, interactive_only: bool = True) -> list[dict]:
        """Get page snapshot with interactive elements."""
        elements = self.browser.snapshot(interactive_only=interactive_only, session=self.session)
        return [
            {"ref": e.ref, "tag": e.tag, "text": e.text, "attrs": e.attrs}
            for e in elements
        ]

    def find_and_click(self, text: str, exact: bool = False) -> None:
        """Find element by text and click."""
        self.browser.find_and_click(text, exact=exact, session=self.session)

    def find_and_fill(self, label: str, text: str) -> None:
        """Find input by label and fill."""
        self.browser.find_and_fill(label, text, session=self.session)

    def wait(self, seconds: float = 1.0) -> None:
        """Wait for given seconds."""
        time.sleep(seconds)


@dataclass(frozen=True)
class LocalScriptResult:
    stdout: str
    stderr: str
    returncode: int


def _launch_app(udid: str, package: str) -> bool:
    """Launch an app by package name."""
    adb = ADBService()
    result = adb.shell(udid, f"monkey -p {package} -c android.intent.category.LAUNCHER 1")
    return "Success" in result.stdout or "Events injected" in result.stdout


def _run_python_script(
    file_path: Path,
    device_udid: str,
    *,
    platform: str = "android",
    wda_url: str | None = None,
) -> LocalScriptResult:
    stdout = io.StringIO()
    stderr = io.StringIO()
    old_argv = sys.argv[:]
    old_path = os.environ.get("PATH", "")
    adb_dir = str(Path(settings.resolved_adb_path).resolve().parent)
    ui_runtime = ScriptUI(
        device_udid,
        platform=platform,
        wda_url=wda_url,
    )
    globals_dict = {
        "__builtins__": __builtins__,
        "__file__": str(file_path),
        "__name__": "__main__",
        "adb": ScriptADB(device_udid),
        "ocr": ScriptOCR(device_udid),
        "image": ScriptImage(device_udid),
        "auto_execute": ui_runtime,
        "ui": ui_runtime,
        "input": ScriptInput(),
        "launch": ui_runtime.launch,
    }

    try:
        sys.argv = [str(file_path), device_udid]
        os.environ["PATH"] = f"{adb_dir}{os.pathsep}{old_path}"
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exec(compile(file_path.read_text(encoding="utf-8"), str(file_path), "exec"), globals_dict)
        return LocalScriptResult(stdout=stdout.getvalue(), stderr=stderr.getvalue(), returncode=0)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        return LocalScriptResult(stdout=stdout.getvalue(), stderr=stderr.getvalue(), returncode=code)
    except Exception:
        traceback.print_exc(file=stderr)
        return LocalScriptResult(stdout=stdout.getvalue(), stderr=stderr.getvalue(), returncode=1)
    finally:
        sys.argv = old_argv
        os.environ["PATH"] = old_path


def _run_pc_script(file_path: Path, session: str | None = None) -> LocalScriptResult:
    """Execute a Python script for PC/Web automation."""
    stdout = io.StringIO()
    stderr = io.StringIO()
    old_argv = sys.argv[:]
    browser_runtime = ScriptBrowser(session)
    globals_dict = {
        "__builtins__": __builtins__,
        "__file__": str(file_path),
        "__name__": "__main__",
        "browser": browser_runtime,
        "web": browser_runtime,
        "input": ScriptInput(),
    }

    try:
        sys.argv = [str(file_path)]
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exec(compile(file_path.read_text(encoding="utf-8"), str(file_path), "exec"), globals_dict)
        return LocalScriptResult(stdout=stdout.getvalue(), stderr=stderr.getvalue(), returncode=0)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        return LocalScriptResult(stdout=stdout.getvalue(), stderr=stderr.getvalue(), returncode=code)
    except Exception:
        traceback.print_exc(file=stderr)
        return LocalScriptResult(stdout=stdout.getvalue(), stderr=stderr.getvalue(), returncode=1)
    finally:
        sys.argv = old_argv
        browser_runtime.close()


# ── routes ───────────────────────────────────────────────────────────────────


# ── User Input API ───────────────────────────────────────────────────────────

@router.get("/input/pending")
def get_pending_input_requests() -> list[UserInputRequestModel]:
    """Get all pending user input requests."""
    with _pending_inputs_lock:
        return [
            UserInputRequestModel(
                id=req.id,
                prompt=req.prompt,
                input_type=req.input_type,
                timeout=req.timeout,
                created_at=req.created_at,
            )
            for req in _pending_inputs.values()
            if not req.responded.is_set() and not req.cancelled
        ]


@router.post("/input/{request_id}/respond")
def respond_to_input_request(request_id: str, response: UserInputResponse) -> dict[str, str]:
    """Respond to a pending user input request."""
    with _pending_inputs_lock:
        request = _pending_inputs.get(request_id)
        if not request:
            raise HTTPException(status_code=404, detail="Input request not found")
        if request.responded.is_set():
            raise HTTPException(status_code=400, detail="Input request already responded")

        request.response = response.value
        request.responded.set()

    return {"status": "ok", "request_id": request_id}


@router.post("/input/{request_id}/cancel")
def cancel_input_request(request_id: str) -> dict[str, str]:
    """Cancel a pending user input request."""
    with _pending_inputs_lock:
        request = _pending_inputs.get(request_id)
        if not request:
            raise HTTPException(status_code=404, detail="Input request not found")

        request.cancelled = True
        request.responded.set()  # Unblock the waiting script

    return {"status": "cancelled", "request_id": request_id}


@router.get("/tree", response_model=list[FileTreeItem])
def list_script_tree() -> list[FileTreeItem]:
    """List scripts as a tree structure with folders."""
    if not SCRIPTS_DIR.exists():
        return []
    return _build_file_tree(SCRIPTS_DIR)


@router.post("/folder", response_model=FileTreeItem)
def create_folder(req: CreateFolderRequest) -> FileTreeItem:
    """Create a new folder in the scripts directory."""
    folder_path = req.path.strip().strip("/\\")
    if not folder_path:
        raise HTTPException(status_code=400, detail="Folder path cannot be empty")

    # Validate path
    root = SCRIPTS_DIR.resolve()
    target = (root / folder_path).resolve()
    if root != target and root not in target.parents:
        raise HTTPException(status_code=400, detail="Invalid folder path")

    if target.exists():
        raise HTTPException(status_code=409, detail=f"Folder already exists: {folder_path}")

    target.mkdir(parents=True, exist_ok=False)
    return _tree_info(target)


@router.delete("/folder/{path:path}")
def delete_folder(path: str) -> dict[str, str]:
    """Delete an empty folder."""
    folder_path = SCRIPTS_DIR / path

    if not folder_path.exists():
        raise HTTPException(status_code=404, detail=f"Folder not found: {path}")
    if not folder_path.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a folder: {path}")

    # Only allow deleting empty folders
    if any(folder_path.iterdir()):
        raise HTTPException(status_code=400, detail="Folder is not empty")

    folder_path.rmdir()
    return {"deleted": path}


@router.get("", response_model=list[ScriptFile])
def list_scripts() -> list[ScriptFile]:
    """List all .py scripts including those in platform subdirectories."""
    if not SCRIPTS_DIR.exists():
        return []
    results: list[ScriptFile] = []
    # Root-level scripts
    for p in SCRIPTS_DIR.iterdir():
        if p.is_file() and p.suffix == ".py":
            results.append(_info(p))
    # Scripts in platform subdirectories
    for platform_dir in PLATFORM_DIRS:
        sub = SCRIPTS_DIR / platform_dir
        if sub.is_dir():
            for p in sub.iterdir():
                if p.is_file() and p.suffix == ".py":
                    results.append(_info(p))
    return sorted(results, key=lambda s: s.path)


# ── Python Environments ───────────────────────────────────────────────────────

@router.get("/python-envs", response_model=PythonEnvsResponse)
def list_python_envs() -> PythonEnvsResponse:
    """Get available Python environments."""
    data = get_python_envs()
    return PythonEnvsResponse(
        current=data["current"],
        default=data["default"],
        envs=[PythonEnvInfo(**e) for e in data["envs"]],
    )


def _resolve_script_python(python_env: str | None) -> str:
    if not python_env:
        return settings.resolved_python_path
    candidate = Path(python_env)
    if not candidate.is_file():
        raise HTTPException(status_code=400, detail=f"Python executable not found: {python_env}")
    return str(candidate)


def _run_mobile_script_response(
    path: str,
    device_udid: str,
    *,
    platform: str = "android",
    wda_url: str | None = None,
) -> ScriptRunResult:
    file_path = _script_path(path)
    start = time.monotonic()
    result = _run_python_script(
        file_path,
        device_udid,
        platform=platform,
        wda_url=wda_url,
    )
    duration_ms = int((time.monotonic() - start) * 1000)
    return ScriptRunResult(
        name=path,
        stdout=result.stdout,
        stderr=result.stderr,
        returncode=result.returncode,
        duration_ms=duration_ms,
    )


def _run_pc_script_response(path: str, session: str | None = None) -> ScriptRunResult:
    file_path = _script_path(path)
    start = time.monotonic()
    result = _run_pc_script(file_path, session)
    duration_ms = int((time.monotonic() - start) * 1000)
    return ScriptRunResult(
        name=path,
        stdout=result.stdout,
        stderr=result.stderr,
        returncode=result.returncode,
        duration_ms=duration_ms,
    )


# ── Streaming Script Execution ───────────────────────────────────────────────

@router.websocket("/output/{run_id}")
async def script_output_websocket(websocket: WebSocket, run_id: str) -> None:
    """WebSocket endpoint for real-time script output."""
    await websocket.accept()

    run = get_run(run_id)
    if not run:
        await websocket.send_text(json.dumps({"type": "error", "message": "Run not found"}))
        await websocket.close()
        return

    run.ws_connections.append(websocket)

    try:
        while True:
            try:
                data = await websocket.receive()
                if data.get("type") == "websocket.disconnect":
                    break
            except WebSocketDisconnect:
                break
    finally:
        if websocket in run.ws_connections:
            run.ws_connections.remove(websocket)
        if run.status in ("completed", "failed", "cancelled") and not run.ws_connections:
            remove_run(run_id)


@router.post("/run/{run_id}/cancel")
def cancel_script_run(run_id: str) -> dict[str, str]:
    """Cancel a running script."""
    success = cancel_run(run_id)
    if success:
        return {"status": "cancelled", "run_id": run_id}
    raise HTTPException(status_code=404, detail="Run not found or not running")


@router.post("/run", response_model=ScriptRunResult)
def run_script_by_query(
    path: str,
    device_udid: str,
    platform: str = "android",
    wda_url: str | None = None,
) -> ScriptRunResult:
    """Execute a Python script by query path.

    This fixed route must stay before the catch-all script routes below.
    """
    return _run_mobile_script_response(
        path,
        device_udid,
        platform=platform,
        wda_url=wda_url,
    )


@router.post("/run-pc", response_model=ScriptRunResult)
def run_pc_script_by_query(path: str, session: str | None = None) -> ScriptRunResult:
    """Execute a PC/Web Python script by query path."""
    return _run_pc_script_response(path, session=session)


@router.post("/run-stream", response_model=ScriptRunStreamStart)
async def run_script_stream_by_query(
    path: str,
    device_udid: str,
    platform: str = "android",
    wda_url: str | None = None,
    python_env: str | None = None,
) -> ScriptRunStreamStart:
    """Start a mobile script run and stream output through /output/{run_id}."""
    file_path = _script_path(path)
    python_path = _resolve_script_python(python_env)
    run = create_run(
        path=path,
        device_udid=device_udid,
        platform=platform,
        python_path=python_path,
        wda_url=wda_url,
    )
    asyncio.create_task(execute_script_streaming(run, file_path, script_type="mobile"))
    return ScriptRunStreamStart(run_id=run.id, python_path=run.python_path)


@router.post("/run-pc-stream", response_model=ScriptRunStreamStart)
async def run_pc_script_stream_by_query(
    path: str,
    session: str | None = None,
    python_env: str | None = None,
) -> ScriptRunStreamStart:
    """Start a PC/Web script run and stream output through /output/{run_id}."""
    file_path = _script_path(path)
    python_path = _resolve_script_python(python_env)
    run = create_run(
        path=path,
        device_udid="",
        platform="pc",
        python_path=python_path,
        wda_url=None,
    )
    asyncio.create_task(execute_script_streaming(run, file_path, script_type="pc", session=session))
    return ScriptRunStreamStart(run_id=run.id, python_path=run.python_path)


@router.post("/{path:path}/run", response_model=ScriptRunResult)
def run_script(
    path: str,
    device_udid: str,
    platform: str = "android",
    wda_url: str | None = None,
) -> ScriptRunResult:
    """Execute a Python script with the given device UDID as argument."""
    return _run_mobile_script_response(
        path,
        device_udid,
        platform=platform,
        wda_url=wda_url,
    )


@router.post("/{path:path}/run-pc", response_model=ScriptRunResult)
def run_pc_script(path: str, session: str | None = None) -> ScriptRunResult:
    """Execute a Python script for PC/Web automation."""
    return _run_pc_script_response(path, session=session)


@router.get("/{path:path}", response_model=ScriptContent)
def read_script(path: str) -> ScriptContent:
    """Read the content of a script file."""
    file_path = _script_path(path)
    return ScriptContent(content=file_path.read_text(encoding="utf-8"))


@router.post("", response_model=ScriptFile)
def create_script(req: CreateScriptRequest) -> ScriptFile:
    """Create a new .py script. If platform is set, auto-place in platform subfolder."""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name cannot be empty")
    if not name.endswith(".py"):
        name += ".py"
    if req.platform and req.platform in PLATFORM_DIRS:
        name = f"{req.platform}/{name}"
    file_path = _script_path(name, must_exist=False)
    if file_path.exists():
        raise HTTPException(status_code=409, detail=f"Script already exists: {name}")
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(req.content or "# New script\n", encoding="utf-8")
    return _info(file_path)


@router.put("/{path:path}", response_model=ScriptFile)
def save_script(path: str, req: SaveScriptRequest) -> ScriptFile:
    """Overwrite an existing script file."""
    file_path = _script_path(path)
    file_path.write_text(req.content, encoding="utf-8")
    return _info(file_path)


@router.delete("/{path:path}")
def delete_script(path: str) -> dict[str, str]:
    """Delete a script file."""
    file_path = _script_path(path)
    file_path.unlink()
    return {"deleted": path}
