# Screen Casting & Real-time Control Design

**Date:** 2026-06-02
**Status:** Draft
**Inspiration:** AutoGLM-GUI (Socket.IO + scrcpy + WebCodecs)

---

## Problem Statement

The current embedded screen casting in Mobile-AI-TestOps has two critical limitations:

1. **No interactive control** — users can only view the device screen; they cannot tap, swipe, or type on it
2. **High latency / low framerate** — the screencap → ffmpeg → MJPEG → WebSocket → `<img>` pipeline is slow (~2-5 fps, >500ms latency)

The goal is to implement real-time screen casting with interactive control, enabling both manual operation (like a remote desktop) and AI Agent-driven automation.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    Electron + Vue 3 Frontend                  │
│                                                               │
│  ┌──────────────────┐     ┌───────────────────────────┐     │
│  │  ScrcpyCanvas     │     │  ControlOverlay            │     │
│  │  (WebCodecs decode│◄────│  (pointer event capture)   │     │
│  │   H.264→Canvas)   │     │  mousedown/move/up→motion │     │
│  └──────────────────┘     └───────────┬───────────────┘     │
│           ▲                             │                     │
│           │ frame data                  │ control commands    │
│           │                             ▼                     │
│  ┌─────────────────────────────────────────────────────┐    │
│  │         Socket.IO Client (useScrcpyStream.ts)        │    │
│  └─────────────────────┬───────────────────────────────┘    │
└────────────────────────┼─────────────────────────────────────┘
                         │ Socket.IO (WebSocket)
┌────────────────────────┼─────────────────────────────────────┐
│                    Python Backend                              │
│  ┌─────────────────────┴───────────────────────────────┐    │
│  │          Socket.IO Server (socketio_server.py)        │    │
│  └───────┬──────────────────────────┬──────────────────┘    │
│          │                          │                        │
│  ┌───────▼────────┐      ┌──────────▼──────────┐           │
│  │ ScrcpyService   │      │  TouchControlService │           │
│  │ (launch scrcpy  │      │  (input motionevent  │           │
│  │  push H.264)    │      │   tap/swipe/type)    │           │
│  └───────┬────────┘      └──────────┬──────────┘           │
│          │                          │                        │
│  ┌───────▼──────────────────────────▼──────────┐           │
│  │              ADB (Android Debug Bridge)       │           │
│  └──────────────────────────────────────────────┘           │
└──────────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions

### 1. scrcpy server as video source

Replace `adb shell screencap` polling with scrcpy server's native H.264 video stream.

**Why:** scrcpy pushes hardware-encoded H.264 at 30-60 fps with <50ms capture latency. The current screencap pipeline achieves only 2-5 fps with 500ms+ latency.

**How:** Push `scrcpy-server.jar` via ADB, start via `app_process`, connect over `localabstract` socket to read H.264 NAL units.

### 2. Socket.IO for bidirectional communication

Replace the current single-direction WebSocket (video only) with Socket.IO.

**Why:**
- Socket.IO provides automatic reconnection, rooms, and event-based messaging out of the box
- Separates video frame events (`video-data`) from control events (`control-action`) on the same connection
- AutoGLM-GUI has already validated this approach
- Eliminates the need for separate REST API calls for control

**How:**
- `python-socketio[asyncio]` on the backend, mounted to FastAPI's ASGI app
- `socket.io-client` on the frontend
- Events: `connect-device`, `disconnect-device`, `video-metadata`, `video-data`, `control-action`

### 3. WebCodecs for H.264 decoding

Replace `<img>` + `createObjectURL` with WebCodecs `VideoDecoder` → Canvas rendering.

**Why:**
- WebCodecs provides hardware-accelerated H.264 decoding in Chromium (always available in Electron)
- Decoded frames render directly to Canvas via `VideoFrame` → `drawImage()` with zero copy
- The `<img>` approach requires full JPEG decode + blob URL creation per frame

**How:**
- `VideoDecoder` with `codec: "avc1.64001f"` (H.264 Baseline/Main/High)
- On `video-metadata` event, configure decoder with `description` (AVCC codec config)
- On `video-data` event, feed `EncodedVideoChunk` to decoder
- Decoder callback renders `VideoFrame` to canvas, then `frame.close()`

### 4. `input motionevent` for touch control

Replace no-control with `adb shell input motionevent` for real-time touch interaction.

**Why:**
- `input motionevent` supports DOWN/MOVE/UP events, enabling drag, swipe, and multi-touch
- `input tap` and `input swipe` are higher-level but can't express continuous gestures
- AutoGLM-GUI's `adb_plus/touch.py` has already validated this approach
- Latency: ~20-40ms per motionevent (acceptable for interactive use)

**How:**
- `input motionevent ACTION_DOWN <x> <y>` on pointerdown
- `input motionevent ACTION_MOVE <x> <y>` on pointermove (if button held)
- `input motionevent ACTION_UP <x> <y>` on pointerup
- Throttle MOVE events to max 60/sec to avoid ADB bottleneck

### 5. Dual control channel: Socket.IO + REST API

Keep existing REST API endpoints alongside Socket.IO control.

**Why:**
- AI Agent automation calls REST API (`/api/devices/{udid}/tap`, `/swipe`, `/key`)
- Real-time manual control uses Socket.IO (lower latency, bidirectional)
- Script recording/replay uses REST API (deterministic, replayable)
- Both channels use the same `TouchControlService` backend

### 6. Coordinate mapping

Map Canvas pixel coordinates to device pixel coordinates.

**Why:** The Canvas may be displayed at a different size than the device's native resolution.

**How:**
- Store device resolution from `video-metadata` event
- On pointer events, compute: `deviceX = (canvasX / canvasWidth) * deviceWidth`
- Account for CSS scaling and device pixel ratio

---

## Backend Changes

### New files

| File | Purpose |
|------|---------|
| `backend/app/services/socketio_server.py` | Socket.IO server, event handlers |
| `backend/app/services/scrcpy_stream.py` | scrcpy server lifecycle + frame reader |
| `backend/app/services/touch_control_service.py` | Touch/key/text control via `input` commands |

### Modified files

| File | Change |
|------|--------|
| `backend/app/main.py` | Mount Socket.IO ASGI app at `/socket.io` |
| `backend/app/routers/devices.py` | Add touch control REST endpoints (tap, swipe, key, type) — may already have some |

### socketio_server.py

```python
import socketio
from app.services.scrcpy_stream import ScrcpyStream
from app.services.touch_control_service import TouchControlService

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
sio_app = socketio.ASGIApp(sio)

# Active streams: device_id -> ScrcpyStream
streams: dict[str, ScrcpyStream] = {}

@sio.on("connect-device")
async def connect_device(sid, data):
    device_id = data["deviceId"]
    stream = ScrcpyStream(device_id)
    streams[device_id] = stream
    await stream.start()
    # Send metadata
    await sio.emit("video-metadata", stream.get_metadata(), to=sid)
    # Start frame pump
    asyncio.create_task(frame_pump(device_id, sid))

@sio.on("disconnect-device")
async def disconnect_device(sid, data):
    device_id = data["deviceId"]
    stream = streams.pop(device_id, None)
    if stream:
        await stream.stop()

@sio.on("control-action")
async def control_action(sid, data):
    device_id = data["deviceId"]
    action = data["action"]  # "touch_down", "touch_move", "touch_up", "tap", "swipe", "key", "text"
    params = data["params"]  # {x, y}, {x1, y1, x2, y2, duration}, {keycode}, {text}
    service = TouchControlService(device_id)
    handler = getattr(service, action, None)
    if handler:
        await handler(**params)

async def frame_pump(device_id: str, sid: str):
    stream = streams.get(device_id)
    if not stream:
        return
    async for frame in stream.iter_packets():
        if device_id not in streams:
            break
        await sio.emit("video-data", frame, to=sid)
```

### scrcpy_stream.py

```python
import asyncio
import struct
from app.core.adb import adb

class ScrcpyStream:
    def __init__(self, device_id: str, max_size: int = 800, bitrate: int = 4_000_000):
        self.device_id = device_id
        self.max_size = max_size
        self.bitrate = bitrate
        self._process = None
        self._reader = None
        self._metadata = {}

    async def start(self):
        # 1. Push scrcpy-server.jar
        await adb.push_scrcpy_server(self.device_id)
        # 2. Forward port
        await adb.forward(self.device_id, "localabstract:scrcpy", "tcp:0")
        # 3. Start app_process
        self._process = await adb.start_scrcpy_server(
            self.device_id, self.max_size, self.bitrate
        )
        # 4. Connect and read dummy byte
        self._reader = await adb.connect_scrcpy_socket(self.device_id)
        dummy = await self._reader.read(1)  # device writes 0 on ready
        # 5. Read metadata (device name + resolution)
        await self._read_metadata()

    async def _read_metadata(self):
        # Read device name (64 bytes, null-padded)
        name_bytes = await self._reader.readexactly(64)
        name = name_bytes.rstrip(b"\x00").decode("utf-8")
        # Read resolution (2x uint16)
        width, height = struct.unpack(">HH", await self._reader.readexactly(4))
        self._metadata = {"deviceName": name, "width": width, "height": height}

    def get_metadata(self) -> dict:
        return self._metadata

    async def iter_packets(self):
        """Yield H.264 NAL units as bytes."""
        while True:
            # scrcpy v1.x: PTS (8 bytes) + size (4 bytes) + payload
            header = await self._reader.readexactly(12)
            pts, size = struct.unpack(">QI", header)
            payload = await self._reader.readexactly(size)
            yield payload

    async def stop(self):
        if self._process:
            self._process.terminate()
            await self._process.wait()
        self._process = None
        self._reader = None
```

### touch_control_service.py

```python
from app.core.adb import adb

class TouchControlService:
    def __init__(self, device_id: str):
        self.device_id = device_id

    async def touch_down(self, x: int, y: int):
        await adb.shell(self.device_id, f"input motionevent DOWN {x} {y}")

    async def touch_move(self, x: int, y: int):
        await adb.shell(self.device_id, f"input motionevent MOVE {x} {y}")

    async def touch_up(self, x: int, y: int):
        await adb.shell(self.device_id, f"input motionevent UP {x} {y}")

    async def tap(self, x: int, y: int):
        await adb.shell(self.device_id, f"input tap {x} {y}")

    async def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300):
        await adb.shell(self.device_id, f"input swipe {x1} {y1} {x2} {y2} {duration}")

    async def key(self, keycode: int):
        await adb.shell(self.device_id, f"input keyevent {keycode}")

    async def text(self, text: str):
        # Use ADBKeyboard for Chinese/special characters
        await adb.shell(self.device_id, f"am broadcast -a ADB_INPUT_TEXT --es msg '{text}'")
```

---

## Frontend Changes

### New files

| File | Purpose |
|------|---------|
| `frontend/src/composables/useScrcpyStream.ts` | Socket.IO + WebCodecs composable |
| `frontend/src/components/screen/ScrcpyCanvas.vue` | Canvas-based scrcpy player with touch overlay |

### Modified files

| File | Change |
|------|--------|
| `frontend/src/components/device/ScreenPanel.vue` | Replace `useScreenStream` with `useScrcpyStream`, add element-info emission |
| `frontend/package.json` | Add `socket.io-client` dependency |

### useScrcpyStream.ts

```typescript
import { ref, onUnmounted } from "vue";
import { io, Socket } from "socket.io-client";
import { invoke } from "@tauri-apps/api/core"; // if needed

export interface ScrcpyMetadata {
  deviceName: string;
  width: number;
  height: number;
}

export function useScrcpyStream() {
  const socket = ref<Socket | null>(null);
  const canvasRef = ref<HTMLCanvasElement | null>(null);
  const metadata = ref<ScrcpyMetadata | null>(null);
  const fps = ref(0);
  const connected = ref(false);
  const decoder = ref<VideoDecoder | null>(null);

  let frameCount = 0;
  let lastFpsTime = Date.now();

  async function connect(udid: string) {
    socket.value = io(`${location.origin}`, {
      path: "/socket.io",
      transports: ["websocket"],
    });

    socket.value.on("connect", () => {
      connected.value = true;
      socket.value!.emit("connect-device", { deviceId: udid });
    });

    socket.value.on("video-metadata", (meta: ScrcpyMetadata) => {
      metadata.value = meta;
      initDecoder(meta);
    });

    socket.value.on("video-data", (frame: ArrayBuffer) => {
      feedDecoder(frame);
      frameCount++;
      const now = Date.now();
      if (now - lastFpsTime >= 1000) {
        fps.value = frameCount;
        frameCount = 0;
        lastFpsTime = now;
      }
    });

    socket.value.on("disconnect", () => {
      connected.value = false;
    });
  }

  function initDecoder(meta: ScrcpyMetadata) {
    if (decoder.value) decoder.value.close();
    decoder.value = new VideoDecoder({
      output: (frame: VideoFrame) => {
        const canvas = canvasRef.value;
        if (canvas) {
          const ctx = canvas.getContext("2d")!;
          canvas.width = meta.width;
          canvas.height = meta.height;
          ctx.drawImage(frame, 0, 0);
        }
        frame.close();
      },
      error: (e: Error) => console.error("Decoder error:", e),
    });
    decoder.value.configure({
      codec: "avc1.64001f",
      optimizeForLatency: true,
    });
  }

  function feedDecoder(data: ArrayBuffer) {
    if (!decoder.value || decoder.value.state === "closed") return;
    // Parse NAL unit type from header to determine keyframe vs delta
    const view = new Uint8Array(data);
    const nalType = view[4] & 0x1f; // H.264 NAL type from first byte after start code
    const isKeyframe = nalType === 5 || nalType === 7 || nalType === 8; // IDR, SPS, PPS
    const chunk = new EncodedVideoChunk({
      type: isKeyframe ? "key" : "delta",
      timestamp: 0, // will be populated from scrcpy PTS
      data,
    });
    decoder.value.decode(chunk);
  }

  // --- Control methods ---

  function sendControl(action: string, params: Record<string, any>) {
    socket.value?.emit("control-action", { action, params });
  }

  function touchDown(x: number, y: number) {
    sendControl("touch_down", { x, y });
  }
  function touchMove(x: number, y: number) {
    sendControl("touch_move", { x, y });
  }
  function touchUp(x: number, y: number) {
    sendControl("touch_up", { x, y });
  }
  function tap(x: number, y: number) {
    sendControl("tap", { x, y });
  }
  function swipe(x1: number, y1: number, x2: number, y2: number, duration = 300) {
    sendControl("swipe", { x1, y1, x2, y2, duration });
  }
  function key(keycode: number) {
    sendControl("key", { keycode });
  }
  function text(t: string) {
    sendControl("text", { text: t });
  }

  // --- Coordinate mapping ---

  function canvasToDevice(clientX: number, clientY: number): { x: number; y: number } {
    const canvas = canvasRef.value;
    const meta = metadata.value;
    if (!canvas || !meta) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    const x = Math.round(((clientX - rect.left) / rect.width) * meta.width);
    const y = Math.round(((clientY - rect.top) / rect.height) * meta.height);
    return { x, y };
  }

  function disconnect() {
    if (socket.value) {
      socket.value.emit("disconnect-device", { deviceId: metadata.value?.deviceName });
      socket.value.disconnect();
    }
    if (decoder.value && decoder.value.state !== "closed") {
      decoder.value.close();
    }
    connected.value = false;
  }

  onUnmounted(disconnect);

  return {
    socket,
    canvasRef,
    metadata,
    fps,
    connected,
    connect,
    disconnect,
    touchDown,
    touchMove,
    touchUp,
    tap,
    swipe,
    key,
    text,
    canvasToDevice,
  };
}
```

### ScrcpyCanvas.vue

```vue
<template>
  <canvas
    ref="canvasEl"
    class="scrcpy-canvas"
    @pointerdown="onPointerDown"
    @pointermove="onPointerMove"
    @pointerup="onPointerUp"
    @contextmenu.prevent
  />
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from "vue";
import { useScrcpyStream } from "@/composables/useScrcpyStream";

const props = defineProps<{ udid: string }>();
const emit = defineEmits<{
  "element-info": [info: any];
}>();

const canvasEl = ref<HTMLCanvasElement | null>(null);
const {
  canvasRef,
  metadata,
  fps,
  connected,
  connect,
  disconnect,
  touchDown,
  touchMove,
  touchUp,
  canvasToDevice,
} = useScrcpyStream();

// Bind canvas ref
watch(canvasEl, (el) => { canvasRef.value = el; });

onMounted(() => connect(props.udid));
onUnmounted(() => disconnect());

// --- Pointer events → touch control ---

let isDown = false;
let moveThrottle = 0;

function onPointerDown(e: PointerEvent) {
  isDown = true;
  const { x, y } = canvasToDevice(e.clientX, e.clientY);
  touchDown(x, y);
  e.preventDefault();
}

function onPointerMove(e: PointerEvent) {
  if (!isDown) return;
  const now = Date.now();
  if (now - moveThrottle < 16) return; // ~60/sec max
  moveThrottle = now;
  const { x, y } = canvasToDevice(e.clientX, e.clientY);
  touchMove(x, y);
}

function onPointerUp(e: PointerEvent) {
  if (!isDown) return;
  isDown = false;
  const { x, y } = canvasToDevice(e.clientX, e.clientY);
  touchUp(x, y);

  // After touch, query element info for script recording
  queryElementInfo(x, y);
}

async function queryElementInfo(x: number, y: number) {
  try {
    const resp = await fetch(`/api/devices/${props.udid}/ui/locate?x=${x}&y=${y}`);
    if (resp.ok) {
      const info = await resp.json();
      emit("element-info", info);
    }
  } catch { /* ignore */ }
}
</script>

<style scoped>
.scrcpy-canvas {
  width: 100%;
  height: 100%;
  object-fit: contain;
  touch-action: none;
  cursor: pointer;
}
</style>
```

---

## Interaction Flow

### Touch → Element Info Feedback

```
User clicks on screen (pointerdown)
  → useScrcpyStream.touchDown(x, y)          // Socket.IO uplink
  → Backend TouchControlService.touch_down()   // adb motionevent
  → Device executes touch

User releases (pointerup)
  → useScrcpyStream.touchUp(x, y)
  → Backend TouchControlService.touch_up()
  → Simultaneously: REST API /ui/locate?x&y
  → Returns element info (package, class, text, xpath, selector)
  → emit('element-info', info) → AutoExecutePanel
  → AutoExecutePanel generates script code
```

### Connection Flow

```
Frontend connect(udid)
  → Socket.IO "connect-device" event
  → Backend ScrcpyStream.start()
    → adb push scrcpy-server.jar
    → adb forward localabstract:scrcpy
    → start app_process
    → socket connect + dummy byte
  → Backend emits "video-metadata" (width, height, codec)
  → Frontend initializes WebCodecs decoder
  → Backend continuously emits "video-data" (H.264 frames)
  → Frontend decodes and renders to Canvas
```

---

## Backward Compatibility

1. **All existing REST API endpoints preserved** — `/tap`, `/swipe`, `/key`, `/input-text`, `/screenshot`, `/ui/locate`
2. **Existing WebSocket MJPEG stream preserved** — as fallback when scrcpy is unavailable
3. **Existing ScreenCanvas.vue preserved** — as fallback component
4. **Electron native surface takes priority** — existing logic preserved
5. **Browser environment uses Socket.IO + WebCodecs** — new path
6. **Configuration** — `settings.stream_provider` supports `socketio-scrcpy | websocket-mjpeg | scrcpy-native`

---

## Dependencies

### Backend (Python)

| Package | Version | Purpose |
|---------|---------|---------|
| `python-socketio[asyncio]` | ^5.10 | Socket.IO server |

### Frontend (npm)

| Package | Version | Purpose |
|---------|---------|---------|
| `socket.io-client` | ^4.7 | Socket.IO client |

### Bundled binary

| File | Purpose |
|------|---------|
| `scrcpy-server-v2.x.jar` | scrcpy server JAR (bundled in project) |

---

## Performance Targets

| Metric | Current | Target |
|--------|---------|--------|
| Framerate | 2-5 fps | 30-60 fps |
| Latency (capture→display) | 500ms+ | <100ms |
| Touch response | N/A | <50ms |
| Control channel latency | N/A (REST) | <30ms (Socket.IO) |
