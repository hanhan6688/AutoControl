"""Device management and screen streaming API routes."""

import asyncio
import base64
import json
import re
import shutil
import socket
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from PIL import Image

from app.config import settings
from app.error_handler import handle_service_errors
from app.schemas import (
    DeviceConnectRequest,
    DeviceConnectResponse,
    DeviceControlRequest,
    DeviceControlResponse,
    DeviceDisconnectResponse,
    DeviceInfo,
    DeviceTapRequest,
    DeviceTextClickRequest,
    DeviceUiLocateRequest,
    DeviceUiLocateResponse,
    ScrcpyStartResponse,
    ScrcpyStopResponse,
    ScreenshotResponse,
    VisualClickResponse,
)
from app.services.adb_service import ADBError, ADBService
from app.services.ios_service import IOSError, IOSService
from app.services.harmony_service import HarmonyError, HarmonyService
from app.services.scrcpy_service import ScrcpyError, ScrcpyService
from app.services.screen_stream_service import ScreenStreamError, ScreenStreamIdle, ScreenStreamService, ScreenStreamSession
from app.services.realtime_adb_control_service import realtime_adb_control_service
from app.services.scrcpy_control_service import ScrcpyControlClient, ScrcpyControlError, scrcpy_control_service
from app.services.ui_element_service import UIElementError, UIElementService, UIElementService as BaseUIElementService
from app.services.visual_action_service import VisualActionError, VisualActionService
from app.services import wda_service
from app.services.ios_stream_service import IosStreamService
from app.utils import utc_iso

router = APIRouter(prefix="/api/devices", tags=["devices"])

# Error handler for device operations
handle_device_errors = handle_service_errors({
    ADBError: 502,
    IOSError: 502,
    HarmonyError: 502,
    ScrcpyError: 502,
    ScreenStreamError: 502,
    UIElementError: 500,
    VisualActionError: 500,
})

# Error handler for visual actions (validation errors return 400)
handle_visual_errors = handle_service_errors({
    ADBError: 502,
    VisualActionError: 400,
})

# Error handler for UI locate (validation errors return 400)
handle_ui_locate_errors = handle_service_errors({
    ADBError: 502,
    UIElementError: 400,
})


@handle_device_errors
@router.get("", response_model=list[DeviceInfo])
def list_devices() -> list[DeviceInfo]:
    devices: list[DeviceInfo] = []

    android_devices = [DeviceInfo.model_validate(device.__dict__) for device in ADBService().list_devices()]
    devices.extend(android_devices)

    try:
        ios_devices = [DeviceInfo.model_validate(device.__dict__) for device in IOSService().list_devices()]
        devices.extend(ios_devices)
    except IOSError:
        pass

    try:
        harmony_devices = [DeviceInfo.model_validate(device.__dict__) for device in HarmonyService().list_devices()]
        devices.extend(harmony_devices)
    except HarmonyError:
        pass

    return devices


@handle_device_errors
@router.post("/connect", response_model=DeviceConnectResponse)
def connect_device(payload: DeviceConnectRequest) -> DeviceConnectResponse:
    """Connect to a remote ADB device (emulator or network device).

    Supports:
    - Network devices: IP:port (e.g., "192.168.1.100:5555")
    - Emulators: emulator port (e.g., "emulator-5554")
    """
    adb = ADBService()
    udid, success = adb.connect(payload.address)
    if success:
        return DeviceConnectResponse(
            udid=udid,
            success=True,
            message=f"Connected to {payload.address}",
        )
    return DeviceConnectResponse(
        udid=udid,
        success=False,
        message=f"Failed to connect to {payload.address}",
    )


@handle_device_errors
@router.post("/disconnect/{address}", response_model=DeviceDisconnectResponse)
def disconnect_device(address: str) -> DeviceDisconnectResponse:
    """Disconnect from a remote ADB device."""
    adb = ADBService()
    success = adb.disconnect(address)
    return DeviceDisconnectResponse(
        address=address,
        success=success,
        message=f"Disconnected from {address}" if success else f"Failed to disconnect from {address}",
    )


@router.get("/stream/capabilities")
def stream_capabilities() -> dict[str, object]:
    return {
        "android": {
            "providers": ["auto", "scrcpy-h264", "scrcpy-ffmpeg-mjpeg", "scrcpy-webcodecs"],
            "default_provider": settings.android_stream_provider,
            "minicap_files_dir": str(settings.minicap_dir),
            "scrcpy_available": shutil.which(settings.resolved_scrcpy_path) is not None,
            "scrcpy_path": settings.resolved_scrcpy_path,
            "ffmpeg_available": shutil.which(settings.resolved_ffmpeg_path) is not None,
            "ffmpeg_path": settings.resolved_ffmpeg_path,
            "note": "scrcpy-h264 streams raw H.264 over WebSocket (WebCodecs decoder). scrcpy-ffmpeg-mjpeg decodes to MJPEG via ffmpeg for browsers without WebCodecs.",
        },
        "ios": {
            "provider": "go-ios",
            "go_ios_available": shutil.which(settings.resolved_ios_path) is not None,
            "go_ios_path": settings.resolved_ios_path,
            "note": "Device discovery is wired. Screen stream adapter is reserved for the iOS phase.",
        },
        "harmony": {
            "provider": "reserved",
            "note": "HarmonyOS device discovery and screen stream reserved for future extension.",
        },
        "maestro": {
            "available": shutil.which(settings.resolved_maestro_path) is not None,
            "path": settings.resolved_maestro_path,
            "note": "Execution service will use bundled Maestro first, then external PATH.",
        },
    }


@handle_device_errors
@router.post("/{udid}/screenshot", response_model=ScreenshotResponse)
def take_screenshot(udid: str, platform: str = "android", wda_url: str | None = None) -> ScreenshotResponse:
    normalized_platform = platform.strip().lower()
    if normalized_platform == "ios":
        file_path, url, created_at = _save_device_screenshot(
            udid=udid,
            image_bytes=wda_service.screenshot(udid, wda_url=wda_url),
            suffix=".png",
        )
    else:
        file_path, url, created_at = ADBService().take_screenshot(udid)
    return ScreenshotResponse(
        udid=udid,
        file_path=file_path.as_posix(),
        url=url,
        created_at=created_at,
    )


def _save_device_screenshot(*, udid: str, image_bytes: bytes, suffix: str = ".png") -> tuple[Path, str, datetime]:
    if not image_bytes:
        raise UIElementError("screenshot returned empty content")
    created_at = datetime.utcnow()
    safe_udid = re.sub(r"[^A-Za-z0-9_.-]", "_", udid)
    target_dir = settings.uploads_dir / "devices" / safe_udid
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{created_at.strftime('%Y%m%d%H%M%S')}_screenshot{suffix}"
    target_path.write_bytes(image_bytes)
    relative_path = target_path.relative_to(settings.static_dir).as_posix()
    return target_path, f"/static/{relative_path}", created_at


# ── Observation screenshot endpoint (lightweight, for AI consumption) ─────

@router.get("/{udid}/screenshot/observe")
def observe_screenshot(
    udid: str,
    max_size: int = 720,
    platform: str = "android",
) -> dict[str, object]:
    """Capture a device screenshot optimized for AI observation.

    Returns a base64-encoded JPEG at the requested max dimension.
    Lower resolution = faster transfer and AI processing.
    """
    try:
        png_bytes = ADBService().capture_screen_png(udid, timeout=10)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to capture screen: {exc}")

    img = Image.open(BytesIO(png_bytes))
    width, height = img.size
    if max(width, height) > max_size:
        ratio = max_size / max(width, height)
        new_size = (int(width * ratio), int(height * ratio))
        img = img.resize(new_size, Image.LANCZOS)
        width, height = new_size

    jpeg_buffer = BytesIO()
    img.save(jpeg_buffer, format="JPEG", quality=75, optimize=True)
    jpeg_bytes = jpeg_buffer.getvalue()

    return {
        "type": "observation_frame",
        "udid": udid,
        "image_base64": base64.b64encode(jpeg_bytes).decode("ascii"),
        "mime_type": "image/jpeg",
        "width": width,
        "height": height,
        "size_bytes": len(jpeg_bytes),
        "timestamp": utc_iso(),
    }


@handle_device_errors
@router.post("/{udid}/scrcpy/start", response_model=ScrcpyStartResponse)
def start_scrcpy(udid: str, max_size: int = 1280, max_fps: int = 30) -> ScrcpyStartResponse:
    session = ScrcpyService().start(udid=udid, max_size=max_size, max_fps=max_fps)
    return ScrcpyStartResponse(udid=session.udid, pid=session.pid, command=session.command)


@router.post("/{udid}/scrcpy/stop", response_model=ScrcpyStopResponse)
def stop_scrcpy(udid: str) -> ScrcpyStopResponse:
    stopped = ScrcpyService().stop(udid)
    return ScrcpyStopResponse(udid=udid, stopped=stopped)


@handle_device_errors
@router.get("/{udid}/current-app")
def get_current_app(udid: str) -> dict:
    """Get the current foreground app package name."""
    adb = ADBService()
    result = adb.shell(udid, "dumpsys window | grep mCurrentFocus", timeout=10)
    output = result.stdout or ""
    match = re.search(r"([a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+)/", output, re.IGNORECASE)
    if match:
        package_name = match.group(1)
        activity = output.split(match.group(0))[1].split()[0].rstrip("}") if match.group(0) in output else ""
        return {
            "udid": udid,
            "package_name": package_name,
            "activity": activity,
            "raw_output": output,
        }
    return {
        "udid": udid,
        "package_name": None,
        "activity": None,
        "raw_output": output,
    }


@handle_device_errors
@router.get("/{udid}/screen-size")
def get_device_screen_size(udid: str) -> dict[str, object]:
    width, height = ADBService().get_screen_size(udid)
    return {
        "udid": udid,
        "width": width,
        "height": height,
    }


@router.post("/{udid}/control", response_model=DeviceControlResponse)
def control_device(udid: str, payload: DeviceControlRequest) -> DeviceControlResponse:
    adb = ADBService()
    try:
        shell_command = _parse_control_expression(payload.command)
        result = adb.shell(udid, shell_command, timeout=15)
    except (ADBError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return DeviceControlResponse(
        udid=udid,
        command=payload.command,
        stdout=result.stdout,
        stderr=result.stderr,
        success=result.returncode == 0,
    )


@handle_device_errors
@router.post("/{udid}/tap")
def tap_device(udid: str, payload: DeviceTapRequest) -> dict[str, object]:
    normalized_platform = payload.platform.strip().lower()
    if normalized_platform == "ios":
        wda_service.click(udid, int(payload.x), int(payload.y), wda_url=payload.wda_url)
    else:
        realtime_adb_control_service.send(udid, f"input tap {int(payload.x)} {int(payload.y)}")
    return {
        "udid": udid,
        "platform": normalized_platform,
        "x": int(payload.x),
        "y": int(payload.y),
        "success": True,
    }


@handle_device_errors
@router.post("/{udid}/key")
def press_device_key(udid: str, keycode: int, platform: str = "android") -> dict[str, object]:
    if platform.strip().lower() == "android":
        realtime_adb_control_service.send(udid, f"input keyevent {keycode}")
    return {"udid": udid, "keycode": keycode, "platform": platform, "success": True}


@handle_device_errors
@router.post("/{udid}/swipe")
def swipe_device(
    udid: str,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    duration_ms: int = 300,
    platform: str = "android",
    wda_url: str | None = None,
) -> dict[str, object]:
    if platform.strip().lower() == "ios":
        wda_service.swipe(udid, x1, y1, x2, y2, duration=duration_ms / 1000.0, wda_url=wda_url)
    else:
        realtime_adb_control_service.send(udid, f"input swipe {x1} {y1} {x2} {y2} {duration_ms}")
    return {"udid": udid, "x1": x1, "y1": y1, "x2": x2, "y2": y2, "duration_ms": duration_ms, "success": True}


@handle_device_errors
@router.post("/{udid}/input-text")
def input_device_text(udid: str, text: str, platform: str = "android", wda_url: str | None = None) -> dict[str, object]:
    if platform.strip().lower() == "ios":
        client = wda_service.get_client(udid, wda_url=wda_url)
        client.type_keys(text)
    else:
        ADBService().input_text(udid, text)
    return {"udid": udid, "text": text, "platform": platform, "success": True}


@handle_device_errors
@router.post("/{udid}/touch/down")
def touch_down(udid: str, x: int, y: int, platform: str = "android") -> dict[str, object]:
    """Send touch DOWN event for real-time drag support."""
    if platform.strip().lower() == "ios":
        wda_service.click(udid, int(x), int(y))
    else:
        realtime_adb_control_service.send(udid, f"input motionevent DOWN {int(x)} {int(y)}")
    return {"udid": udid, "x": int(x), "y": int(y), "action": "down", "success": True}


@handle_device_errors
@router.post("/{udid}/touch/move")
def touch_move(udid: str, x: int, y: int, platform: str = "android", wda_url: str | None = None) -> dict[str, object]:
    """Send touch MOVE event for real-time drag support."""
    if platform.strip().lower() == "ios":
        # WDA does not support separate MOVE events — no-op, use swipe for gestures
        pass
    else:
        realtime_adb_control_service.send(udid, f"input motionevent MOVE {int(x)} {int(y)}")
    return {"udid": udid, "x": int(x), "y": int(y), "action": "move", "success": True}


@handle_device_errors
@router.post("/{udid}/touch/up")
def touch_up(udid: str, x: int, y: int, platform: str = "android", wda_url: str | None = None) -> dict[str, object]:
    """Send touch UP event for real-time drag support."""
    if platform.strip().lower() == "ios":
        # WDA does not support separate UP events — no-op, use swipe for gestures
        pass
    else:
        realtime_adb_control_service.send(udid, f"input motionevent UP {int(x)} {int(y)}")
    return {"udid": udid, "x": int(x), "y": int(y), "action": "up", "success": True}


@handle_visual_errors
@router.post("/{udid}/visual/text-click", response_model=VisualClickResponse)
def click_device_text(udid: str, payload: DeviceTextClickRequest) -> VisualClickResponse:
    match = VisualActionService().click_text(udid=udid, text=payload.text, contains=payload.contains)
    return VisualClickResponse(
        udid=udid,
        found=match.found,
        x=match.x,
        y=match.y,
        score=match.score,
        text=match.text,
        message="clicked" if match.found else "text not found",
    )


@handle_visual_errors
@router.post("/{udid}/visual/template-click", response_model=VisualClickResponse)
async def click_device_template(
    udid: str,
    threshold: float = 0.92,
    file: UploadFile = File(...),
) -> VisualClickResponse:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="template file must be an image")

    template_png = await file.read()
    match = VisualActionService().click_template(udid=udid, template_png=template_png, threshold=threshold)
    return VisualClickResponse(
        udid=udid,
        found=match.found,
        x=match.x,
        y=match.y,
        score=match.score,
        width=match.width,
        height=match.height,
        message="clicked" if match.found else "template not found",
    )


@handle_ui_locate_errors
@router.post("/{udid}/ui/locate", response_model=DeviceUiLocateResponse)
def locate_device_ui_element(udid: str, payload: DeviceUiLocateRequest) -> DeviceUiLocateResponse:
    result = UIElementService().locate_device_point(
        udid=udid,
        x=payload.x,
        y=payload.y,
        platform=payload.platform,
        package_name=payload.package_name,
        strict_xpath_only=payload.strict_xpath_only,
        cache_ttl_ms=payload.cache_ttl_ms,
        wda_url=payload.wda_url,
    )
    return DeviceUiLocateResponse(
        udid=udid,
        found=result.found,
        element=_ui_element_to_dict(result.element) if result.element else None,
        generated_code=result.generated_code,
        message=result.message,
    )


@router.websocket("/{udid}/screen")
async def stream_screen(
    websocket: WebSocket,
    udid: str,
    platform: str = "android",
    provider: str = "auto",
    max_fps: int = 15,
    max_size: int = 1280,
    control: bool = True,
) -> None:
    await websocket.accept()

    if platform in ("ios",):
        await _stream_ios(websocket, udid, max_fps, control, wda_url=None)
        return

    if platform in ("harmony", "鸿蒙"):
        await _safe_send_text(
            websocket,
            json.dumps(
                {
                    "type": "error",
                    "message": f"{platform} screen stream is not yet implemented",
                    "timestamp": utc_iso(),
                }
            )
        )
        try:
            await websocket.close()
        except (RuntimeError, ConnectionError):
            pass
        return

    # ── Auto-prepare device: install ADB Keyboard in background ─────
    asyncio.create_task(_auto_prepare_device(udid, websocket))

    stream_service = ScreenStreamService()
    adb_service = ADBService()
    session: ScreenStreamSession | None = stream_service.create_android_session(
        udid=udid,
        provider=provider,
        max_size=max_size,
        max_fps=max_fps,
        control=control,
    )
    frame_index = 0
    min_frame_interval = 1 / max(1, min(max_fps, 60))
    control_task: asyncio.Task[None] | None = None
    startup_failure: dict[str, str] = {}

    try:
        session = await _start_session_or_fallback(
            websocket=websocket,
            stream_service=stream_service,
            session=session,
            requested_provider=provider,
            udid=udid,
            max_size=max_size,
            max_fps=max_fps,
            control=control,
            failure=startup_failure,
        )
        if session is None:
            await _safe_send_text(
                websocket,
                json.dumps(
                    {
                        "type": "error",
                        "message": startup_failure.get("message") or "screen stream startup failed",
                        "provider": startup_failure.get("provider") or provider,
                        "timestamp": utc_iso(),
                    }
                )
            )
            try:
                await websocket.close()
            except (RuntimeError, ConnectionError):
                pass
            return

        if not await _send_provider_message(websocket, session):
            return

        # Get device screen size for coordinate scaling
        try:
            screen_width, screen_height = await asyncio.to_thread(adb_service.get_screen_size, udid)
        except Exception:
            screen_width, screen_height = 1080, 1920  # fallback

        if not await _safe_send_text(
            websocket,
            json.dumps(
                {
                    "type": "device_info",
                    "screen_width": screen_width,
                    "screen_height": screen_height,
                    "timestamp": utc_iso(),
                }
            )
        ):
            return

        # Notify frontend of control mode — scrcpy native when control is enabled and ScrcpyH264StreamSession is active
        scrcpy_client = scrcpy_control_service.get(udid) if control else None
        if not await _safe_send_text(
            websocket,
            json.dumps({
                "type": "control_mode",
                "mode": "scrcpy" if scrcpy_client is not None else "none" if not control else "adb_fallback",
                "timestamp": utc_iso(),
            })
        ):
            return

        if control:
            control_task = asyncio.create_task(_consume_control_commands(websocket, udid, adb_service))

        while True:
            if control_task and control_task.done():
                return

            started_at = time.monotonic()
            try:
                frame = await asyncio.to_thread(session.read_frame)
            except Exception as exc:
                if _is_stream_idle_error(exc):
                    await asyncio.sleep(min_frame_interval)
                    continue
                if not _is_recoverable_stream_error(exc):
                    raise
                stream_failure: dict[str, str] = {}
                fallback_session = await _fallback_after_stream_error(
                    websocket=websocket,
                    stream_service=stream_service,
                    session=session,
                    requested_provider=provider,
                    message=str(exc),
                    udid=udid,
                    max_size=max_size,
                    max_fps=max_fps,
                    control=control,
                    failure=stream_failure,
                )
                if fallback_session is None:
                    await _safe_send_text(
                        websocket,
                        json.dumps(
                            {
                                "type": "error",
                                "message": stream_failure.get("message") or str(exc),
                                "provider": stream_failure.get("provider") or session.provider,
                                "timestamp": utc_iso(),
                            }
                        )
                    )
                    try:
                        await websocket.close()
                    except (RuntimeError, ConnectionError):
                        pass
                    return

                session = fallback_session
                if not await _send_provider_message(websocket, session):
                    return
                # Re-notify control mode after provider fallback — control
                # capability may change (e.g. scrcpy-h264 → adb has no scrcpy control)
                scrcpy_client = scrcpy_control_service.get(udid)
                if not await _safe_send_text(
                    websocket,
                    json.dumps({
                        "type": "control_mode",
                        "mode": "scrcpy" if scrcpy_client is not None else "adb_fallback",
                        "timestamp": utc_iso(),
                    })
                ):
                    return
                continue

            if not await _safe_send_bytes(websocket, frame.payload):
                return
            frame_index += 1

            elapsed = time.monotonic() - started_at
            if session.provider != "scrcpy-h264" and elapsed < min_frame_interval:
                await asyncio.sleep(min_frame_interval - elapsed)
    except WebSocketDisconnect:
        return
    finally:
        if control_task is not None:
            control_task.cancel()
        realtime_adb_control_service.close(udid)
        if session is not None:
            await asyncio.to_thread(session.stop)


async def _auto_prepare_device(udid: str, websocket: WebSocket | None = None) -> None:
    """Fire-and-forget: auto-install ADB Keyboard.

    Runs in a background thread so it never blocks screen streaming.
    Only does keyboard install — no screencap / dumpsys / full readiness
    check, to avoid competing with scrcpy for USB bandwidth.
    """
    import asyncio as _asyncio

    async def _install() -> None:
        try:
            loop = _asyncio.get_running_loop()
            # Run the blocking install in a thread to keep the event loop free
            result = await loop.run_in_executor(
                None,
                _install_adb_keyboard_blocking,
                udid,
            )
            if result and websocket:
                await _safe_send_text(websocket, json.dumps({
                    "type": "device_readiness",
                    "code": "ready",
                    "message": result,
                    "timestamp": utc_iso(),
                }))
        except Exception:
            pass

    _asyncio.create_task(_install())


def _install_adb_keyboard_blocking(udid: str) -> str | None:
    """Blocking helper: check + install + enable ADB Keyboard. Runs in thread."""
    from app.config import settings
    from pathlib import Path as _Path

    try:
        adb = ADBService()
    except Exception:
        return None

    apk_path = settings.resolved_adb_keyboard_apk_path
    if not apk_path or not apk_path.exists():
        return None

    # Already installed?
    result = adb.shell_raw(udid, "pm path com.android.adbkeyboard", timeout=8)
    if result.returncode != 0 or "package:" not in result.stdout:
        # Install
        try:
            adb.install_apk(udid, apk_path, timeout=30)
        except (ADBError, OSError, TimeoutError):
            return None

    # Enable IME
    ime = "com.android.adbkeyboard/.AdbIME"
    enabled = adb.shell_raw(udid, "ime list -s", timeout=8)
    if ime not in enabled.stdout:
        adb.shell_raw(udid, f"ime enable {ime}", timeout=8)

    return "ADB Keyboard ✓ 已就绪"


# ── iOS screen streaming via WDA screenshot polling ──────────────────


async def _stream_ios(
    websocket: WebSocket,
    udid: str,
    max_fps: int,
    control: bool,
    wda_url: str | None = None,
) -> None:
    """Stream iOS device screen using WDA screenshot polling over WebSocket."""
    stream = IosStreamService(device_id=udid, target_fps=min(max_fps, 15))
    await stream.start()

    metadata = stream.get_metadata()
    width = metadata.width if metadata else 390
    height = metadata.height if metadata else 844

    if not await _safe_send_text(
        websocket,
        json.dumps({
            "type": "provider",
            "provider": "ios-wda",
            "mime_type": "image/jpeg",
            "timestamp": utc_iso(),
        }),
    ):
        stream.stop()
        return

    if not await _safe_send_text(
        websocket,
        json.dumps({
            "type": "device_info",
            "screen_width": width,
            "screen_height": height,
            "timestamp": utc_iso(),
        }),
    ):
        stream.stop()
        return

    control_mode = "wda" if control else "none"
    if not await _safe_send_text(
        websocket,
        json.dumps({
            "type": "control_mode",
            "mode": control_mode,
            "timestamp": utc_iso(),
        }),
    ):
        stream.stop()
        return

    control_task: asyncio.Task[None] | None = None
    if control:
        control_task = asyncio.create_task(
            _consume_ios_control_commands(websocket, udid, wda_url),
        )

    min_interval = 1 / max(1, min(max_fps, 15))
    try:
        async for jpeg_data in stream.iter_frames():
            if control_task and control_task.done():
                return
            started_at = time.monotonic()
            if not await _safe_send_bytes(websocket, jpeg_data):
                return
            elapsed = time.monotonic() - started_at
            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)
    except WebSocketDisconnect:
        return
    finally:
        if control_task is not None:
            control_task.cancel()
        stream.stop()


async def _consume_ios_control_commands(
    websocket: WebSocket,
    udid: str,
    wda_url: str | None = None,
) -> None:
    """Handle touch/swipe/key/text commands from the web client for iOS."""
    while True:
        try:
            data = await websocket.receive()
        except WebSocketDisconnect:
            return

        if data.get("type") == "websocket.disconnect":
            return

        if "text" not in data:
            continue

        try:
            command = json.loads(data["text"])
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

        try:
            await _handle_ios_control_command(udid, wda_url, command)
        except Exception as exc:
            if not await _safe_send_text(
                websocket,
                json.dumps({
                    "type": "control_error",
                    "message": str(exc),
                    "command": command.get("type"),
                    "timestamp": utc_iso(),
                }),
            ):
                return


async def _handle_ios_control_command(
    udid: str,
    wda_url: str | None,
    command: dict,
) -> None:
    """Execute an iOS control command via WDA."""
    cmd_type = command.get("type")

    if cmd_type in ("touch_down", "tap"):
        x, y = int(command["x"]), int(command["y"])
        await asyncio.to_thread(wda_service.click, udid, x, y, wda_url=wda_url)

    elif cmd_type in ("touch_move", "touch_up"):
        # WDA does not support separate DOWN/MOVE/UP — these are no-ops.
        # Drag gestures use swipe instead.
        pass

    elif cmd_type in ("swipe", "drag"):
        x1, y1 = int(command["x1"]), int(command["y1"])
        x2, y2 = int(command["x2"]), int(command["y2"])
        duration = command.get("duration_ms", command.get("drag_duration_ms", 300)) / 1000.0
        await asyncio.to_thread(
            wda_service.swipe, udid, x1, y1, x2, y2, duration=duration, wda_url=wda_url,
        )

    elif cmd_type == "long_press":
        x, y = int(command["x"]), int(command["y"])
        duration_ms = command.get("duration_ms", 800)
        duration_s = duration_ms / 1000.0
        client = wda_service.get_client(udid, wda_url=wda_url)
        await asyncio.to_thread(client.tap_hold, x, y, duration_s)

    elif cmd_type == "key":
        keycode = int(command["keycode"])
        client = wda_service.get_client(udid, wda_url=wda_url)
        if keycode == 3:  # HOME
            await asyncio.to_thread(client.home)
        elif keycode == 4:  # BACK — iOS swipe right from left edge
            size = client.window_size()
            await asyncio.to_thread(
                wda_service.swipe, udid, 10, size.height // 2,
                size.width // 2, size.height // 2, duration=0.3, wda_url=wda_url,
            )

    elif cmd_type == "text":
        text = command.get("text", "")
        if text:
            client = wda_service.get_client(udid, wda_url=wda_url)
            await asyncio.to_thread(client.type_keys, text)


def _is_recoverable_stream_error(exc: Exception) -> bool:
    if _is_stream_idle_error(exc):
        return False
    return isinstance(exc, (ADBError, ScreenStreamError, TimeoutError, socket.timeout, OSError))


def _is_stream_idle_error(exc: Exception) -> bool:
    return isinstance(exc, ScreenStreamIdle)


async def _safe_send_text(websocket: WebSocket, value: str) -> bool:
    try:
        await websocket.send_text(value)
        return True
    except (WebSocketDisconnect, RuntimeError, ConnectionError):
        return False


async def _safe_send_bytes(websocket: WebSocket, value: bytes) -> bool:
    try:
        await websocket.send_bytes(value)
        return True
    except (WebSocketDisconnect, RuntimeError, ConnectionError):
        return False


def _ui_element_to_dict(element) -> dict[str, object]:
    bounds = element.bounds
    center_x, center_y = bounds.center
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
            "left": bounds.left,
            "top": bounds.top,
            "right": bounds.right,
            "bottom": bounds.bottom,
            "width": bounds.width,
            "height": bounds.height,
            "center_x": center_x,
            "center_y": center_y,
        },
        "xpath": element.xpath,
        "hierarchy_xpath": element.hierarchy_xpath,
        "selector": element.selector,
        "input_capable": BaseUIElementService.is_text_input(element),
        "depth": element.depth,
        "index": element.index,
    }


async def _send_provider_message(websocket: WebSocket, session: ScreenStreamSession) -> bool:
    return await _safe_send_text(
        websocket,
        json.dumps(
            {
                "type": "provider",
                "provider": session.provider,
                "mime_type": session.mime_type,
                "timestamp": utc_iso(),
            }
        )
    )


async def _consume_control_commands(websocket: WebSocket, udid: str, adb_service: ADBService) -> None:
    while True:
        try:
            data = await websocket.receive()
        except WebSocketDisconnect:
            return

        if data.get("type") == "websocket.disconnect":
            return

        if "text" not in data:
            continue

        try:
            command = json.loads(data["text"])
        except (json.JSONDecodeError, KeyError, TypeError):
            continue

        try:
            await _handle_control_command(udid, adb_service, command)
        except (ADBError, KeyError, TypeError, ValueError) as exc:
            if not await _safe_send_text(
                websocket,
                json.dumps(
                    {
                        "type": "control_error",
                        "message": str(exc),
                        "command": command.get("type"),
                        "timestamp": utc_iso(),
                    }
                )
            ):
                return


async def _start_session_or_fallback(
    websocket: WebSocket,
    stream_service: ScreenStreamService,
    session: ScreenStreamSession,
    requested_provider: str,
    udid: str,
    max_size: int,
    max_fps: int,
    control: bool = True,
    failure: dict[str, str] | None = None,
) -> ScreenStreamSession | None:
    try:
        await asyncio.to_thread(session.start)
        return session
    except Exception as exc:
        if not _is_recoverable_stream_error(exc):
            raise
        return await _fallback_after_stream_error(
            websocket=websocket,
            stream_service=stream_service,
            session=session,
            requested_provider=requested_provider,
            message=str(exc),
            udid=udid,
            max_size=max_size,
            max_fps=max_fps,
            control=control,
            failure=failure,
        )


async def _fallback_after_stream_error(
    websocket: WebSocket,
    stream_service: ScreenStreamService,
    session: ScreenStreamSession,
    requested_provider: str,
    message: str,
    udid: str,
    max_size: int,
    max_fps: int,
    control: bool = True,
    failure: dict[str, str] | None = None,
) -> ScreenStreamSession | None:
    fallback_providers = ScreenStreamService.fallback_providers_after_failure(
        requested_provider=requested_provider,
        failed_provider=session.provider,
    )
    if not fallback_providers:
        if failure is not None:
            failure["message"] = message
            failure["provider"] = session.provider
        return None

    await asyncio.to_thread(session.stop)
    last_error = message
    last_provider = session.provider
    for fallback_provider in fallback_providers:
        if not await _safe_send_text(
            websocket,
            json.dumps(
                {
                    "type": "provider_fallback",
                    "from": last_provider,
                    "to": fallback_provider,
                    "message": last_error,
                    "timestamp": utc_iso(),
                }
            )
        ):
            return None
        fallback_session = stream_service.create_android_session(
            udid=udid,
            provider=fallback_provider,
            max_size=max_size,
            max_fps=max_fps,
            control=control,
        )
        try:
            await asyncio.to_thread(fallback_session.start)
            return fallback_session
        except Exception as exc:
            if not _is_recoverable_stream_error(exc):
                raise
            await asyncio.to_thread(fallback_session.stop)
            last_error = str(exc)
            last_provider = fallback_provider

    if failure is not None:
        failure["message"] = last_error
        failure["provider"] = last_provider
    return None


async def _handle_control_command(udid: str, adb: ADBService, command: dict) -> None:
    """Handle touch/swipe/zoom commands from the web client."""
    cmd_type = command.get("type")

    if cmd_type == "touch_down":
        x, y = command["x"], command["y"]
        await _send_scrcpy_or_adb(
            udid,
            lambda client: client.touch_down(int(x), int(y)),
            f"input motionevent DOWN {int(x)} {int(y)}",
        )

    elif cmd_type == "touch_move":
        x, y = command["x"], command["y"]
        await _send_scrcpy_or_adb(
            udid,
            lambda client: client.touch_move(int(x), int(y)),
            f"input motionevent MOVE {int(x)} {int(y)}",
        )

    elif cmd_type == "touch_up":
        x, y = command["x"], command["y"]
        await _send_scrcpy_or_adb(
            udid,
            lambda client: client.touch_up(int(x), int(y)),
            f"input motionevent UP {int(x)} {int(y)}",
        )

    elif cmd_type == "tap":
        x = command.get("x")
        y = command.get("y")
        locator = command.get("locator")
        fallback = None
        if x is not None and y is not None:
            fallback = (int(x), int(y))
        if isinstance(locator, dict) and locator:
            locator_handled = await _handle_locator_tap(udid, locator, fallback=fallback)
            if locator_handled:
                return
        if x is None or y is None:
            raise KeyError("tap command requires x/y when locator resolution fails")
        await _send_scrcpy_or_adb(
            udid,
            lambda client: client.tap(int(x), int(y)),
            f"input tap {int(x)} {int(y)}",
        )

    elif cmd_type == "swipe":
        x1, y1 = command["x1"], command["y1"]
        x2, y2 = command["x2"], command["y2"]
        duration = command.get("duration_ms", 300)
        await _send_scrcpy_or_adb(
            udid,
            lambda client: client.swipe(int(x1), int(y1), int(x2), int(y2), int(duration)),
            f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration)}",
        )

    elif cmd_type == "drag":
        x1, y1 = command["x1"], command["y1"]
        x2, y2 = command["x2"], command["y2"]
        duration = command.get("drag_duration_ms", command.get("duration_ms", 300))
        await _send_scrcpy_or_adb(
            udid,
            lambda client: client.swipe(int(x1), int(y1), int(x2), int(y2), int(duration)),
            f"input swipe {int(x1)} {int(y1)} {int(x2)} {int(y2)} {int(duration)}",
        )

    elif cmd_type == "long_press":
        x, y = command["x"], command["y"]
        duration = command.get("duration_ms", 800)
        await _send_scrcpy_or_adb(
            udid,
            lambda client: client.swipe(int(x), int(y), int(x), int(y), int(duration)),
            f"input swipe {int(x)} {int(y)} {int(x)} {int(y)} {int(duration)}",
        )

    elif cmd_type == "key":
        keycode = command["keycode"]
        await _send_scrcpy_or_adb(
            udid,
            lambda client: client.key(int(keycode)),
            f"input keyevent {int(keycode)}",
        )

    elif cmd_type == "text":
        text = command.get("text", "")
        if text:
            client = scrcpy_control_service.get(udid)
            if client is not None:
                try:
                    await asyncio.to_thread(client.text, str(text))
                    return
                except ScrcpyControlError:
                    scrcpy_control_service.unregister(udid, client)
            await asyncio.to_thread(adb.input_text, udid, str(text))


async def _handle_locator_tap(
    udid: str,
    locator: dict,
    *,
    fallback: tuple[int, int] | None = None,
) -> bool:
    fallback_raw = locator.get("fallback")
    resolved_fallback = fallback
    if isinstance(fallback_raw, (list, tuple)) and len(fallback_raw) == 2:
        resolved_fallback = (int(fallback_raw[0]), int(fallback_raw[1]))
    return await asyncio.to_thread(
        UIElementService().click,
        udid=udid,
        text=locator.get("text"),
        resource_id=locator.get("resource_id"),
        content_desc=locator.get("content_desc"),
        class_name=locator.get("class_name"),
        package=locator.get("package"),
        xpath=locator.get("xpath"),
        fallback=resolved_fallback,
        ocr_text=locator.get("ocr_text"),
        image_path=locator.get("image_path"),
    )


async def _send_scrcpy_or_adb(
    udid: str,
    scrcpy_send,
    adb_command: str,
) -> None:
    client: ScrcpyControlClient | None = scrcpy_control_service.get(udid)
    if client is not None:
        try:
            await asyncio.to_thread(scrcpy_send, client)
            return
        except ScrcpyControlError:
            scrcpy_control_service.unregister(udid, client)
    realtime_adb_control_service.send(udid, adb_command)


def _parse_control_expression(command: str) -> str:
    value = command.strip()
    if not value:
        raise ValueError("command is empty")

    patterns = [
        (r"^adb\.click\((\d+)\s*,\s*(\d+)\)$", lambda m: f"input tap {m.group(1)} {m.group(2)}"),
        (r"^adb\.tap\((\d+)\s*,\s*(\d+)\)$", lambda m: f"input tap {m.group(1)} {m.group(2)}"),
        (
            r"^adb\.swipe\(\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*,\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)(?:\s*,\s*(\d+))?\)$",
            lambda m: f"input swipe {m.group(1)} {m.group(2)} {m.group(3)} {m.group(4)} {m.group(5) or 300}",
        ),
        (
            r"^adb\.swipe\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*(\d+))?\)$",
            lambda m: f"input swipe {m.group(1)} {m.group(2)} {m.group(3)} {m.group(4)} {m.group(5) or 300}",
        ),
        (r"^adb\.key\((\d+)\)$", lambda m: f"input keyevent {m.group(1)}"),
        (r"^adb\.back\(\)$", lambda _m: "input keyevent 4"),
        (r"^adb\.home\(\)$", lambda _m: "input keyevent 3"),
        (r"^input\s+keyevent\s+(\d+)$", lambda m: f"input keyevent {m.group(1)}"),
    ]

    for pattern, build in patterns:
        match = re.match(pattern, value)
        if match:
            return build(match)

    raise ValueError(
        "unsupported command. Try adb.click(x,y), adb.swipe((x1,y1),(x2,y2),duration), adb.back(), adb.home()"
    )
