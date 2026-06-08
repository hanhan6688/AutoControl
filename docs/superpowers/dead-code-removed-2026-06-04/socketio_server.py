"""Socket.IO server for scrcpy video streaming — legacy/compatibility path.

NOTE: This stream uses scrcpy CLI with --no-control (see scrcpy_stream.py).
Control commands via Socket.IO fall back to ADB motionevent, which has
higher latency (~50-100ms per event). For real-time control, use the
WebSocket path (/api/devices/{udid}/screen) which uses
ScrcpyH264StreamSession with control=true and scrcpy native control
socket (~1-5ms per event).

Events:
  connect-device   (up)   — client requests a device stream
  disconnect-device (up)   — client releases a device stream
  control-action   (up)   — client sends touch/key/text command
  video-metadata   (down) — server sends device resolution/codec
  video-data       (down) — server sends H.264 or JPEG frame
  error            (down) — server reports an error
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import Any

import socketio

from app.services.scrcpy_stream import ScrcpyStream, ScrcpyStreamError, ScrcpyVideoPacket
from app.services.touch_control_service import TouchControlService
from app.services.scrcpy_control_service import scrcpy_control_service, ScrcpyControlError

logger = logging.getLogger(__name__)

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*",
)
sio_app = socketio.ASGIApp(sio, socketio_path="/socket.io")

# ── State ────────────────────────────────────────────────────────────────────

# sid → stream object (ScrcpyStream or IosStreamService)
_streams: dict[str, Any] = {}
# sid → asyncio.Task for frame pump
_stream_tasks: dict[str, asyncio.Task[None]] = {}
# device_id → sid (one stream per device)
_device_sids: dict[str, str] = {}
# device_id → asyncio.Lock
_device_locks: dict[str, asyncio.Lock] = {}
# sid → frame send queue for backpressure control (max 2 frames)
_frame_queues: dict[str, asyncio.Queue[dict[str, Any] | None]] = {}
# sid → stats for logging
_stream_stats: dict[str, dict[str, int]] = {}


def _stop_stream_for_sid(sid: str) -> None:
    """Stop and clean up the stream for a given SID."""
    task = _stream_tasks.pop(sid, None)
    if task:
        task.cancel()
    stream = _streams.pop(sid, None)
    if stream:
        stream.stop()
    device_id = next((d for d, s in _device_sids.items() if s == sid), None)
    if device_id:
        _device_sids.pop(device_id, None)
    # Clean up backpressure queue
    queue = _frame_queues.pop(sid, None)
    if queue:
        try:
            queue.put_nowait(None)  # signal sender to stop
        except asyncio.QueueFull:
            pass
    _stream_stats.pop(sid, None)


# ── Connection lifecycle ─────────────────────────────────────────────────────

@sio.event
async def connect(sid: str, environ: dict[str, Any]) -> None:
    logger.info("Socket.IO client connected: %s", sid)


@sio.event
async def disconnect(sid: str) -> None:
    logger.info("Socket.IO client disconnected: %s", sid)
    _stop_stream_for_sid(sid)


# ── Device stream management ─────────────────────────────────────────────────

@sio.on("connect-device")
async def handle_connect_device(sid: str, data: dict[str, Any] | None) -> None:
    """Handle a client requesting to connect to a device's screen stream."""
    payload = data or {}
    device_id = payload.get("device_id") or payload.get("deviceId")
    if not device_id:
        await sio.emit("error", {"message": "device_id is required", "type": "invalid_request"}, to=sid)
        return

    platform = payload.get("platform", "android")
    max_size = int(payload.get("maxSize") or 720)
    bit_rate = int(payload.get("bitRate") or 2_000_000)
    max_fps = int(payload.get("maxFps") or 30)

    # Stop any existing stream for this SID
    _stop_stream_for_sid(sid)

    # Get or create device lock
    if device_id not in _device_locks:
        _device_locks[device_id] = asyncio.Lock()
    device_lock = _device_locks[device_id]

    async with device_lock:
        # Stop any existing stream for the same device from another SID
        existing_sid = _device_sids.get(device_id)
        if existing_sid and existing_sid != sid:
            logger.info("Stopping existing stream for device %s from sid %s", device_id, existing_sid)
            _stop_stream_for_sid(existing_sid)

        try:
            if platform == "ios":
                await _start_ios_stream(sid, device_id, max_fps)
            else:
                await _start_android_stream(sid, device_id, max_size, bit_rate, max_fps)
        except Exception as exc:
            logger.exception("Failed to start stream for %s (%s): %s", device_id, platform, exc)
            error_info = _classify_error(exc)
            await sio.emit("error", error_info, to=sid)


async def _start_android_stream(
    sid: str, device_id: str, max_size: int, bit_rate: int, max_fps: int,
) -> None:
    """Start an Android scrcpy H.264 stream."""
    stream = ScrcpyStream(
        device_id=device_id,
        max_size=max_size,
        bit_rate=bit_rate,
        max_fps=max_fps,
    )
    await stream.start()
    metadata = stream.get_metadata()
    if metadata:
        await sio.emit("video-metadata", {
            "deviceName": metadata.device_name,
            "width": metadata.width,
            "height": metadata.height,
            "codec": metadata.codec,
            "platform": "android",
        }, to=sid)

    _streams[sid] = stream
    _device_sids[device_id] = sid
    _stream_tasks[sid] = asyncio.create_task(_android_frame_pump(sid, stream))

    # Notify frontend of control mode
    # Note: ScrcpyStream uses scrcpy CLI with --no-control, so the scrcpy
    # control client is NOT available for Socket.IO streams. Socket.IO
    # control uses the ADB motionevent fallback path only.
    # WebSocket streams (devices.py) use ScrcpyH264StreamSession which
    # DOES register a control client.
    has_scrcpy_control = scrcpy_control_service.get(device_id) is not None
    await sio.emit("control-mode", {
        "mode": "scrcpy" if has_scrcpy_control else "adb_fallback",
        "device_id": device_id,
    }, to=sid)


async def _start_ios_stream(sid: str, device_id: str, max_fps: int) -> None:
    """Start an iOS WDA screenshot stream."""
    from app.services.ios_stream_service import IosStreamService

    stream = IosStreamService(
        device_id=device_id,
        target_fps=min(max_fps, 10),  # iOS caps at ~10fps
    )
    await stream.start()
    metadata = stream.get_metadata()
    if metadata:
        await sio.emit("video-metadata", {
            "deviceName": metadata.device_name,
            "width": metadata.width,
            "height": metadata.height,
            "codec": "mjpeg",
            "platform": "ios",
        }, to=sid)

    _streams[sid] = stream
    _device_sids[device_id] = sid
    _stream_tasks[sid] = asyncio.create_task(_ios_frame_pump(sid, stream))


@sio.on("disconnect-device")
async def handle_disconnect_device(sid: str, data: dict[str, Any] | None) -> None:
    """Handle a client requesting to disconnect from a device."""
    _stop_stream_for_sid(sid)


# ── Control commands ─────────────────────────────────────────────────────────

@sio.on("control-action")
async def handle_control_action(sid: str, data: dict[str, Any] | None) -> None:
    """Handle a touch/key/text control command from the client."""
    payload = data or {}
    device_id = payload.get("device_id") or payload.get("deviceId")
    action = payload.get("action", "")
    params = payload.get("params", {})
    platform = payload.get("platform", "android")

    if not device_id:
        return

    service = TouchControlService()

    try:
        if platform == "ios":
            await _dispatch_ios_control(service, device_id, action, params)
        else:
            await _dispatch_android_control(service, device_id, action, params)
    except Exception as exc:
        logger.warning("Control action %s failed for %s: %s", action, device_id, exc)
        await sio.emit(
            "control-error",
            {"message": str(exc), "action": action, "device_id": device_id},
            to=sid,
        )


async def _dispatch_android_control(
    service: TouchControlService, device_id: str, action: str, params: dict[str, Any],
) -> None:
    """Dispatch an Android control command.

    Prefers scrcpy native control client (low-latency) when available.
    Falls back to ADB `input motionevent` only when scrcpy is not active.
    """
    import asyncio as _asyncio

    client = scrcpy_control_service.get(device_id)
    use_scrcpy = client is not None

    if action == "touch_down":
        x, y = int(params.get("x", 0)), int(params.get("y", 0))
        if use_scrcpy:
            await _asyncio.to_thread(client.touch_down, x, y)
        else:
            await service.touch_down(device_id, x, y)
    elif action == "touch_move":
        x, y = int(params.get("x", 0)), int(params.get("y", 0))
        if use_scrcpy:
            await _asyncio.to_thread(client.touch_move, x, y)
        else:
            await service.touch_move(device_id, x, y)
    elif action == "touch_up":
        x, y = int(params.get("x", 0)), int(params.get("y", 0))
        if use_scrcpy:
            await _asyncio.to_thread(client.touch_up, x, y)
        else:
            await service.touch_up(device_id, x, y)
    elif action == "tap":
        x, y = int(params.get("x", 0)), int(params.get("y", 0))
        if use_scrcpy:
            await _asyncio.to_thread(client.tap, x, y)
        else:
            await service.tap(device_id, x, y)
    elif action == "swipe":
        x1, y1 = int(params.get("x1", 0)), int(params.get("y1", 0))
        x2, y2 = int(params.get("x2", 0)), int(params.get("y2", 0))
        duration = int(params.get("duration", 300))
        if use_scrcpy:
            await _asyncio.to_thread(client.swipe, x1, y1, x2, y2, duration)
        else:
            await service.swipe(device_id, x1, y1, x2, y2, duration)
    elif action == "long_press":
        x, y = int(params.get("x", 0)), int(params.get("y", 0))
        duration = int(params.get("duration", 800))
        if use_scrcpy:
            await _asyncio.to_thread(client.swipe, x, y, x, y, duration)
        else:
            await service.long_press(device_id, x, y, duration)
    elif action == "key":
        keycode = int(params.get("keycode", 0))
        if use_scrcpy:
            await _asyncio.to_thread(client.key, keycode)
        else:
            await service.key(device_id, keycode)
    elif action == "text":
        text = str(params.get("text", ""))
        if use_scrcpy and text:
            try:
                await _asyncio.to_thread(client.text, text)
                return
            except ScrcpyControlError:
                scrcpy_control_service.unregister(device_id, client)
                use_scrcpy = False
        await service.text(device_id, text)


async def _dispatch_ios_control(
    service: TouchControlService, device_id: str, action: str, params: dict[str, Any],
) -> None:
    """Dispatch an iOS control command via WDA."""
    if action == "touch_down":
        await service.ios_touch_down(device_id, int(params.get("x", 0)), int(params.get("y", 0)))
    elif action == "touch_move":
        await service.ios_touch_move(device_id, int(params.get("x", 0)), int(params.get("y", 0)))
    elif action == "touch_up":
        await service.ios_touch_up(device_id, int(params.get("x", 0)), int(params.get("y", 0)))
    elif action == "tap":
        await service.ios_tap(device_id, int(params.get("x", 0)), int(params.get("y", 0)))
    elif action == "swipe":
        await service.ios_swipe(
            device_id,
            int(params.get("x1", 0)), int(params.get("y1", 0)),
            int(params.get("x2", 0)), int(params.get("y2", 0)),
            float(params.get("duration", 0.3)),
        )
    elif action == "key":
        await service.ios_key(device_id, int(params.get("keycode", 0)))
    elif action == "text":
        await service.ios_text(device_id, str(params.get("text", "")))


# ── Frame pumps ──────────────────────────────────────────────────────────────

async def _android_frame_pump(sid: str, stream: ScrcpyStream) -> None:
    """Continuously read H.264 frames from the scrcpy stream and emit them
    with backpressure control — a small queue (maxsize=2) prevents latency
    buildup when the client is slow."
    """
    import base64
    import time

    # Create backpressure queue
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=2)
    _frame_queues[sid] = queue
    _stream_stats[sid] = {"recv_frames": 0, "send_frames": 0, "dropped_frames": 0}

    async def _sender() -> None:
        """Drain the queue and send frames. Blocks when client is slow."""
        while True:
            packet = await queue.get()
            if packet is None:  # stop signal
                queue.task_done()
                return
            try:
                await sio.emit("video-data", packet, to=sid)
                _stream_stats[sid]["send_frames"] += 1
            except Exception:
                pass
            queue.task_done()

    sender_task = asyncio.create_task(_sender())

    try:
        async for raw_packet in stream.iter_packets():
            _stream_stats[sid]["recv_frames"] += 1

            b64_data = base64.b64encode(raw_packet.data).decode("ascii")
            packet = {
                "type": raw_packet.type,
                "data": b64_data,
                "encoding": "base64",
                "keyframe": raw_packet.keyframe,
                "pts": raw_packet.pts,
                "platform": "android",
            }

            # Non-blocking put — drop oldest frame if queue is full
            try:
                queue.put_nowait(packet)
            except asyncio.QueueFull:
                _stream_stats[sid]["dropped_frames"] += 1
                # Drop the oldest frame to make room for the new one
                try:
                    queue.get_nowait()
                    queue.task_done()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(packet)
                except asyncio.QueueFull:
                    pass

            # Log stats every 60 frames
            if _stream_stats[sid]["recv_frames"] % 60 == 0:
                stats = _stream_stats[sid]
                logger.debug(
                    "Stream stats sid=%s recv=%d send=%d dropped=%d queue=%d",
                    sid,
                    stats["recv_frames"],
                    stats["send_frames"],
                    stats["dropped_frames"],
                    queue.qsize(),
                )

    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("Android streaming failed for sid %s: %s", sid, exc)
        try:
            await sio.emit("error", {"message": str(exc), "type": "stream_error"}, to=sid)
        except Exception:
            pass
    finally:
        # Signal sender to stop
        try:
            queue.put_nowait(None)
        except asyncio.QueueFull:
            pass
        if sender_task and not sender_task.done():
            sender_task.cancel()
        _frame_queues.pop(sid, None)
        _stream_stats.pop(sid, None)
        _stop_stream_for_sid(sid)


async def _ios_frame_pump(sid: str, stream: Any) -> None:
    """Continuously read JPEG frames from the iOS stream and emit them
    with backpressure control."
    """
    import base64

    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=2)
    _frame_queues[sid] = queue

    async def _sender() -> None:
        while True:
            packet = await queue.get()
            if packet is None:
                queue.task_done()
                return
            try:
                await sio.emit("video-data", packet, to=sid)
            except Exception:
                pass
            queue.task_done()

    sender_task = asyncio.create_task(_sender())

    try:
        async for jpeg_data in stream.iter_frames():
            b64_data = base64.b64encode(jpeg_data).decode("ascii")
            packet = {
                "type": "jpeg",
                "data": b64_data,
                "encoding": "base64",
                "platform": "ios",
            }
            try:
                queue.put_nowait(packet)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.task_done()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(packet)
                except asyncio.QueueFull:
                    pass
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("iOS streaming failed for sid %s: %s", sid, exc)
        try:
            await sio.emit("error", {"message": str(exc), "type": "stream_error"}, to=sid)
        except Exception:
            pass
    finally:
        try:
            queue.put_nowait(None)
        except asyncio.QueueFull:
            pass
        if sender_task and not sender_task.done():
            sender_task.cancel()
        _frame_queues.pop(sid, None)
        _stop_stream_for_sid(sid)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _classify_error(exc: Exception) -> dict[str, Any]:
    """Classify error and return user-friendly message."""
    error_str = str(exc)
    if "Address already in use" in error_str or ("Port" in error_str and "occupied" in error_str):
        return {"message": "端口冲突，视频流端口仍被占用", "type": "port_conflict", "details": error_str}
    if "Device" in error_str and ("not available" in error_str or "not found" in error_str):
        return {"message": "设备无响应，请检查连接", "type": "device_offline", "details": error_str}
    if "timeout" in error_str.lower():
        return {"message": "连接超时，请检查设备连接", "type": "timeout", "details": error_str}
    return {"message": error_str, "type": "unknown", "details": error_str}


def stop_all_streams() -> None:
    """Stop all active streams (called on shutdown)."""
    for sid in list(_streams.keys()):
        _stop_stream_for_sid(sid)
