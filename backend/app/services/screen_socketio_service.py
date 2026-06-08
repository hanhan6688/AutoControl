"""SocketIO-based screen streaming and device control service.

Provides a unified SocketIO namespace ``/screen`` that handles both
Android (scrcpy H.264 / MJPEG) and iOS (WDA screenshot polling) streams,
plus real-time touch/key/text control — all over a single SocketIO connection.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time

import socketio

from app.config import settings
from app.services.adb_service import ADBService
from app.services.ios_stream_service import IosStreamService
from app.services.realtime_adb_control_service import realtime_adb_control_service
from app.services.scrcpy_control_service import ScrcpyControlClient, ScrcpyControlError, scrcpy_control_service
from app.services.screen_stream_service import ScreenStreamError, ScreenStreamIdle, ScreenStreamService
from app.services import wda_service
from app.utils import utc_iso

logger = logging.getLogger(__name__)

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

# Track active streams so we can clean up on disconnect
_active_streams: dict[str, dict] = {}


def _utc_now() -> str:
    return utc_iso()


# ── Android streaming ──────────────────────────────────────────────────


async def _stream_android_frames(sid: str, udid: str, session, max_fps: int) -> None:
    """Background task: read frames from Android stream session and emit to client."""
    min_interval = 1 / max(1, min(max_fps, 60))
    state = _active_streams.get(sid)
    if not state:
        return
    try:
        while state.get("running"):
            started_at = time.monotonic()
            frame = await asyncio.to_thread(session.read_frame)
            await sio.emit("frame", frame.payload, to=sid)
            elapsed = time.monotonic() - started_at
            if session.provider != "scrcpy-h264" and elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)
    except ScreenStreamIdle:
        # Stream is idle — normal, just wait
        await asyncio.sleep(0.1)
    except Exception as exc:
        logger.warning("Android stream error for %s: %s", udid, exc)
        await sio.emit("error", {"message": str(exc), "timestamp": _utc_now()}, to=sid)
    finally:
        state = _active_streams.get(sid)
        if state and state.get("session") is session:
            state["running"] = False


# ── iOS streaming ──────────────────────────────────────────────────────


async def _stream_ios_frames(sid: str, udid: str, stream: IosStreamService) -> None:
    """Background task: read JPEG frames from iOS WDA polling and emit to client."""
    state = _active_streams.get(sid)
    if not state:
        return
    try:
        async for jpeg_data in stream.iter_frames():
            if not state.get("running"):
                return
            await sio.emit("frame", jpeg_data, to=sid)
    except Exception as exc:
        logger.warning("iOS stream error for %s: %s", udid, exc)
        await sio.emit("error", {"message": str(exc), "timestamp": _utc_now()}, to=sid)
    finally:
        state = _active_streams.get(sid)
        if state and state.get("stream") is stream:
            state["running"] = False


# ── SocketIO namespace ─────────────────────────────────────────────────


@sio.on("connect", namespace="/screen")
async def on_connect(sid, environ):
    await sio.emit("connected", {"sid": sid}, to=sid)


@sio.on("start", namespace="/screen")
async def on_start(sid, data):
    """Start screen streaming for a device.

    Expected data: {udid, platform, provider?, max_fps?, max_size?, control?, wda_url?}
    """
    udid = data.get("udid", "")
    platform = data.get("platform", "android").strip().lower()
    provider = data.get("provider", "auto")
    max_fps = int(data.get("max_fps", 20))
    max_size = int(data.get("max_size", 720))
    control = data.get("control", True)
    wda_url = data.get("wda_url")

    if not udid:
        await sio.emit("error", {"message": "udid is required"}, to=sid)
        return

    # Clean up any existing stream for this sid
    await _stop_stream(sid)

    if platform == "ios":
        stream = IosStreamService(device_id=udid, target_fps=min(max_fps, 15))
        await stream.start()
        metadata = stream.get_metadata()
        width = metadata.width if metadata else 390
        height = metadata.height if metadata else 844

        _active_streams[sid] = {
            "running": True,
            "udid": udid,
            "platform": "ios",
            "stream": stream,
            "wda_url": wda_url,
        }

        await sio.emit("provider", {"provider": "ios-wda", "mime_type": "image/jpeg"}, to=sid)
        await sio.emit("device_info", {"screen_width": width, "screen_height": height}, to=sid)
        await sio.emit("control_mode", {"mode": "wda" if control else "none"}, to=sid)

        asyncio.create_task(_stream_ios_frames(sid, udid, stream))
    else:
        # Android
        stream_service = ScreenStreamService()
        session = stream_service.create_android_session(
            udid=udid, provider=provider, max_size=max_size, max_fps=max_fps, control=control,
        )
        try:
            await asyncio.to_thread(session.start)
        except Exception as exc:
            await sio.emit("error", {"message": f"Stream start failed: {exc}"}, to=sid)
            return

        adb = ADBService()
        try:
            screen_width, screen_height = await asyncio.to_thread(adb.get_screen_size, udid)
        except Exception:
            screen_width, screen_height = 1080, 1920

        scrcpy_client = scrcpy_control_service.get(udid) if control else None

        _active_streams[sid] = {
            "running": True,
            "udid": udid,
            "platform": "android",
            "session": session,
        }

        await sio.emit("provider", {"provider": session.provider, "mime_type": session.mime_type}, to=sid)
        await sio.emit("device_info", {"screen_width": screen_width, "screen_height": screen_height}, to=sid)
        await sio.emit(
            "control_mode",
            {"mode": "scrcpy" if scrcpy_client is not None else "adb_fallback"},
            to=sid,
        )

        asyncio.create_task(_stream_android_frames(sid, udid, session, max_fps))


async def _stop_stream(sid: str) -> None:
    """Stop and clean up the active stream for a session."""
    state = _active_streams.pop(sid, None)
    if not state:
        return
    state["running"] = False
    session = state.get("session")
    if session:
        await asyncio.to_thread(session.stop)
    stream = state.get("stream")
    if stream:
        stream.stop()
    udid = state.get("udid", "")
    if udid and state.get("platform") == "android":
        realtime_adb_control_service.close(udid)


@sio.on("disconnect", namespace="/screen")
async def on_disconnect(sid):
    await _stop_stream(sid)


# ── Control events (unified for Android & iOS) ─────────────────────────


@sio.on("touch_down", namespace="/screen")
async def on_touch_down(sid, data):
    await _handle_touch(sid, "touch_down", data)


@sio.on("touch_move", namespace="/screen")
async def on_touch_move(sid, data):
    await _handle_touch(sid, "touch_move", data)


@sio.on("touch_up", namespace="/screen")
async def on_touch_up(sid, data):
    await _handle_touch(sid, "touch_up", data)


@sio.on("tap", namespace="/screen")
async def on_tap(sid, data):
    await _handle_touch(sid, "tap", data)


@sio.on("swipe", namespace="/screen")
async def on_swipe(sid, data):
    state = _active_streams.get(sid)
    if not state:
        return
    x1, y1 = int(data["x1"]), int(data["y1"])
    x2, y2 = int(data["x2"]), int(data["y2"])
    duration = int(data.get("duration_ms", 300))
    await _send_swipe(state, x1, y1, x2, y2, duration)


@sio.on("drag", namespace="/screen")
async def on_drag(sid, data):
    state = _active_streams.get(sid)
    if not state:
        return
    x1, y1 = int(data["x1"]), int(data["y1"])
    x2, y2 = int(data["x2"]), int(data["y2"])
    duration = int(data.get("drag_duration_ms", data.get("duration_ms", 300)))
    await _send_swipe(state, x1, y1, x2, y2, duration)


@sio.on("key", namespace="/screen")
async def on_key(sid, data):
    state = _active_streams.get(sid)
    if not state:
        return
    keycode = int(data["keycode"])
    platform = state.get("platform", "android")
    if platform == "ios":
        client = wda_service.get_client(state["udid"], wda_url=state.get("wda_url"))
        if keycode == 3:
            await asyncio.to_thread(client.home)
        elif keycode == 4:
            size = client.window_size()
            await asyncio.to_thread(
                wda_service.swipe, state["udid"], 10, size.height // 2,
                size.width // 2, size.height // 2, duration=0.3,
                wda_url=state.get("wda_url"),
            )
    else:
        client = scrcpy_control_service.get(state["udid"])
        if client:
            await asyncio.to_thread(client.key, keycode)
        else:
            realtime_adb_control_service.send(state["udid"], f"input keyevent {keycode}")


@sio.on("text", namespace="/screen")
async def on_text(sid, data):
    state = _active_streams.get(sid)
    if not state:
        return
    text = data.get("text", "")
    if not text:
        return
    platform = state.get("platform", "android")
    if platform == "ios":
        client = wda_service.get_client(state["udid"], wda_url=state.get("wda_url"))
        await asyncio.to_thread(client.type_keys, text)
    else:
        client = scrcpy_control_service.get(state["udid"])
        if client:
            await asyncio.to_thread(client.text, text)
        else:
            await asyncio.to_thread(ADBService().input_text, state["udid"], text)


# ── Internal helpers ───────────────────────────────────────────────────


async def _handle_touch(sid: str, action: str, data: dict) -> None:
    state = _active_streams.get(sid)
    if not state:
        return
    x, y = int(data["x"]), int(data["y"])
    platform = state.get("platform", "android")
    udid = state["udid"]

    if platform == "ios":
        if action in ("touch_down", "tap"):
            await asyncio.to_thread(wda_service.click, udid, x, y, wda_url=state.get("wda_url"))
        # touch_move/touch_up are no-ops on iOS (WDA limitation)
    else:
        client = scrcpy_control_service.get(udid)
        if client:
            scrcpy_fn = {
                "touch_down": client.touch_down,
                "touch_move": client.touch_move,
                "touch_up": client.touch_up,
                "tap": client.tap,
            }.get(action)
            if scrcpy_fn:
                await asyncio.to_thread(scrcpy_fn, x, y)
                return
        # Fallback to ADB
        adb_cmd = {
            "touch_down": f"input motionevent DOWN {x} {y}",
            "touch_move": f"input motionevent MOVE {x} {y}",
            "touch_up": f"input motionevent UP {x} {y}",
            "tap": f"input tap {x} {y}",
        }.get(action)
        if adb_cmd:
            realtime_adb_control_service.send(udid, adb_cmd)


async def _send_swipe(state: dict, x1: int, y1: int, x2: int, y2: int, duration_ms: int) -> None:
    platform = state.get("platform", "android")
    udid = state["udid"]
    if platform == "ios":
        await asyncio.to_thread(
            wda_service.swipe, udid, x1, y1, x2, y2,
            duration=duration_ms / 1000.0, wda_url=state.get("wda_url"),
        )
    else:
        client = scrcpy_control_service.get(udid)
        if client:
            await asyncio.to_thread(client.swipe, x1, y1, x2, y2, duration_ms)
        else:
            realtime_adb_control_service.send(udid, f"input swipe {x1} {y1} {x2} {y2} {duration_ms}")
