<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { Loading } from '@element-plus/icons-vue'
import { useScrcpyStream } from '../../composables/useScrcpyStream'
import type { DeviceUiLocateResponse } from '../../api'
import {
  shouldStartLiveTouch,
  TAP_DISTANCE_PX,
} from '../../utils/mobileGesture'

const props = defineProps<{
  udid: string
  maxFps?: number
  maxSize?: number
  platform?: string
}>()

const emit = defineEmits<{
  connected: []
  disconnected: []
  error: [message: string]
  'element-info': [info: DeviceUiLocateResponse]
}>()

const canvasEl = ref<HTMLCanvasElement | null>(null)
const {
  state,
  isIos,
  setCanvas,
  connect,
  disconnect,
  touchDown,
  touchMove,
  touchUp,
  tap,
  swipe,
  canvasToDevice,
  queryElementInfo,
  hasLiveControl,
} = useScrcpyStream()

// Bind canvas ref
watch(canvasEl, (el) => { setCanvas(el) })

onMounted(() => {
  if (props.udid) {
    connect(props.udid, { maxFps: props.maxFps, maxSize: props.maxSize, platform: props.platform ?? 'android' })
  }
})

onUnmounted(() => {
  disconnect()
})

watch(() => props.udid, (newUdid) => {
  if (newUdid) {
    connect(newUdid, { maxFps: props.maxFps, maxSize: props.maxSize, platform: props.platform ?? 'android' })
  } else {
    disconnect()
  }
})

// ── Pointer events → touch control ────────────────────────────────────
// When scrcpy control is connected, every pointer event is sent as a
// real-time touch_down/touch_move/touch_up. ADB swipe-on-mouseup is
// only used as fallback when scrcpy control is unavailable.

let isDown = false
let moved = false
let liveTouchActive = false
let startDeviceX = 0
let startDeviceY = 0
let startedAt = 0

function onPointerDown(e: PointerEvent) {
  if (!state.value.isConnected) return
  isDown = true
  moved = false
  liveTouchActive = false
  const point = canvasToDevice(e.clientX, e.clientY)
  startDeviceX = point.x
  startDeviceY = point.y
  startedAt = performance.now()
  const target = e.currentTarget as HTMLElement
  target.setPointerCapture(e.pointerId)
  e.preventDefault()

  // scrcpy live control: send touch_down immediately
  if (hasLiveControl()) {
    touchDown(startDeviceX, startDeviceY)
    liveTouchActive = true
  }
}

function onPointerMove(e: PointerEvent) {
  if (!isDown || !state.value.isConnected) return
  const { x, y } = canvasToDevice(e.clientX, e.clientY)
  const deviceDistance = Math.hypot(x - startDeviceX, y - startDeviceY)

  if (shouldStartLiveTouch(deviceDistance)) {
    moved = true
  }

  if (!liveTouchActive && hasLiveControl()) {
    // scrcpy live control: start touch on any significant movement
    if (!shouldStartLiveTouch(deviceDistance)) return
    touchDown(startDeviceX, startDeviceY)
    liveTouchActive = true
  }

  if (liveTouchActive) {
    touchMove(x, y)
  }
  e.preventDefault()
}

async function onPointerUp(e: PointerEvent) {
  if (!isDown) return
  isDown = false
  const { x, y } = canvasToDevice(e.clientX, e.clientY)

  if (liveTouchActive) {
    touchUp(x, y)
    liveTouchActive = false
    // Live touch handled the gesture — skip fallback
    if (!moved) {
      const info = await queryElementInfo(x, y)
      if (info) {
        emit('element-info', info)
      }
    }
    return
  }

  // ADB fallback: swipe-on-mouseup
  liveTouchActive = false
  const distance = Math.hypot(x - startDeviceX, y - startDeviceY)
  const duration = Math.max(80, Math.round(performance.now() - startedAt))
  if (distance >= TAP_DISTANCE_PX) {
    swipe(startDeviceX, startDeviceY, x, y, duration)
  } else {
    tap(x, y)
  }

  // After touch, query element info for script recording (only for taps, not drags)
  if (!moved) {
    const info = await queryElementInfo(x, y)
    if (info) {
      emit('element-info', info)
    }
  }
}

function onPointerCancel() {
  if (!isDown) return
  isDown = false
  if (liveTouchActive) {
    touchUp(startDeviceX, startDeviceY)
  }
  liveTouchActive = false
}

function onContextMenu(e: Event) {
  e.preventDefault()
}
</script>

<template>
  <div class="scrcpy-canvas-wrapper">
    <canvas
      ref="canvasEl"
      class="scrcpy-canvas"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @pointercancel="onPointerCancel"
      @contextmenu="onContextMenu"
    />
    <div v-if="state.isLoading" class="scrcpy-overlay">
      <el-icon class="is-loading" :size="32"><Loading /></el-icon>
      <span>连接中...</span>
    </div>
    <div v-else-if="state.error" class="scrcpy-overlay error">
      <span>{{ state.error }}</span>
    </div>
    <div v-if="state.isConnected" class="scrcpy-status">
      <el-tag :type="isIos ? 'warning' : 'success'" size="small">
        {{ isIos ? 'iOS' : 'Android' }}
      </el-tag>
      <el-tag
        :type="state.controlMode === 'scrcpy' ? 'success' : state.controlMode === 'adb_fallback' ? 'warning' : 'info'"
        size="small"
      >
        {{ state.controlMode === 'scrcpy' ? 'scrcpy 控制' : state.controlMode === 'adb_fallback' ? 'ADB 控制' : '等待控制' }}
      </el-tag>
      <span class="fps-counter">收 {{ state.fps }} / 解 {{ state.decodeFps }} fps</span>
    </div>
  </div>
</template>

<style scoped>
.scrcpy-canvas-wrapper {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  background: #000;
  border-radius: 6px;
  overflow: hidden;
}

.scrcpy-canvas {
  display: block;
  max-width: 100%;
  max-height: 100%;
  touch-action: none;
  cursor: crosshair;
  outline: none;
}

.scrcpy-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--text-muted, #999);
  background: rgba(0, 0, 0, 0.72);
  pointer-events: none;
  z-index: 1;
}

.scrcpy-overlay.error {
  color: var(--el-color-danger, #f56c6c);
}

.scrcpy-status {
  position: absolute;
  top: 8px;
  right: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
  z-index: 2;
}

.fps-counter {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.7);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}
</style>
