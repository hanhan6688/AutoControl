<script setup lang="ts">
import { Back, HomeFilled, Grid, Loading, Cellphone } from '@element-plus/icons-vue'
import { captureDeviceScreenshot, getAssetUrl, type DeviceInfo, type ScreenshotResponse, type DeviceUiLocateResponse } from '../../api'
import { useScreenStream, type ScreenStreamHandle } from '../../composables'
import { useScrcpyStream } from '../../composables/useScrcpyStream'
import ScrcpyCanvas from '../screen/ScrcpyCanvas.vue'
import { computed, ref, watch, onMounted, onUnmounted, inject } from 'vue'

const props = defineProps<{
  activeDevice: DeviceInfo | null
}>()

// Screen stream — shared singleton provided by App.vue
const screen = inject<ScreenStreamHandle>('screenStream')!
const scrcpy = useScrcpyStream()
const screenshotLoading = ref<string | null>(null)
const latestScreenshot = ref<ScreenshotResponse | null>(null)
const socketState = computed(() => scrcpy.state.value)
const nativeState = computed(() => screen.state.value)

// Detect environment and decide streaming mode
const electronAPI = typeof window !== 'undefined' ? (window as any).electronAPI : undefined
const isElectron = Boolean(electronAPI?.isElectron)
// Use Socket.IO scrcpy unless Electron native scrcpy is available
const useScrcpySocketIO = !isElectron || !electronAPI?.scrcpyNativeStart

const SCREEN_KEYCODE_MAP: Record<string, { expr: string; keycode: number }> = {
  Backspace: { expr: 'adb.key(67)', keycode: 67 },
  Enter: { expr: 'adb.key(66)', keycode: 66 },
  Tab: { expr: 'adb.key(61)', keycode: 61 },
  Escape: { expr: 'adb.key(111)', keycode: 111 },
}

const KEYCODE_MAP: Record<string, { expr: string; keycode: number }> = {
  BACK: { expr: 'adb.back()', keycode: 4 },
  HOME: { expr: 'adb.home()', keycode: 3 },
  APP_SWITCH: { expr: 'adb.key(187)', keycode: 187 },
}

const emit = defineEmits<{
  'send-key': [key: string]
  'screen-key-down': [event: KeyboardEvent]
  'screen-paste': [event: ClipboardEvent]
  'pointer-down': [event: PointerEvent]
  'pointer-up': [event: PointerEvent]
  'pointer-cancel': [event: PointerEvent]
  'append-command': [command: string]
  'element-info': [info: DeviceUiLocateResponse]
}>()

async function takeScreenshot() {
  if (!props.activeDevice) return
  screenshotLoading.value = props.activeDevice.udid
  try {
    latestScreenshot.value = await captureDeviceScreenshot(props.activeDevice.udid)
  } finally {
    screenshotLoading.value = null
  }
}

function sendKeyEvent(key: string) {
  if (!props.activeDevice) return
  if (useScrcpySocketIO && scrcpy.state.value.isConnected) {
    const mapping = KEYCODE_MAP[key] || SCREEN_KEYCODE_MAP[key]
    if (mapping) {
      scrcpy.key(mapping.keycode)
    }
    return
  }
  emit('send-key', key)
}

function handleScreenKeyDown(event: KeyboardEvent) {
  emit('screen-key-down', event)
}

function handleScreenPaste(event: ClipboardEvent) {
  emit('screen-paste', event)
}

function connectScreen(device: DeviceInfo) {
  if (device.status !== 'online') return

  if (useScrcpySocketIO) {
    if (
      scrcpy.state.value.udid === device.udid &&
      (scrcpy.state.value.isConnected || scrcpy.state.value.isLoading)
    ) {
      return
    }
    scrcpy.connect(device.udid, {
      maxFps: 30,
      maxSize: 800,
      platform: device.platform ?? 'android',
    })
  } else {
    if (
      screen.state.value.udid === device.udid &&
      (screen.state.value.isConnected || screen.state.value.isLoading)
    ) {
      return
    }
    screen.connect(device.udid, {
      platform: device.platform ?? 'android',
      provider: 'scrcpy-ffmpeg-mjpeg',
      maxFps: 15,
      maxSize: 960,
    })
  }
}

function disconnectScreen() {
  if (useScrcpySocketIO) {
    scrcpy.disconnect()
  } else {
    screen.disconnect()
  }
}

function handleElementInfo(info: DeviceUiLocateResponse) {
  emit('element-info', info)
}

// Auto-connect when activeDevice changes
watch(() => props.activeDevice, (device) => {
  if (device && device.status === 'online') {
    connectScreen(device)
  } else {
    disconnectScreen()
  }
}, { immediate: true })

onUnmounted(() => {
  disconnectScreen()
})

defineExpose({
  screen,
  scrcpy,
  connectScreen,
  disconnectScreen,
  takeScreenshot,
  SCREEN_KEYCODE_MAP,
  KEYCODE_MAP,
  useScrcpySocketIO,
})
</script>

<template>
  <div class="screen-panel">
    <!-- Navigation bar -->
    <div class="android-nav-bar" v-if="activeDevice && (useScrcpySocketIO ? socketState.isConnected : nativeState.isConnected)">
      <el-tooltip content="返回 (Back)" placement="top">
        <el-button size="small" @click="sendKeyEvent('BACK')" :icon="Back" circle />
      </el-tooltip>
      <el-tooltip content="桌面 (Home)" placement="top">
        <el-button size="small" @click="sendKeyEvent('HOME')" :icon="HomeFilled" circle />
      </el-button>
      <el-tooltip content="任务窗 (App Switch)" placement="top">
        <el-button size="small" @click="sendKeyEvent('APP_SWITCH')" :icon="Grid" circle />
      </el-tooltip>
      <el-divider direction="vertical" />
      <el-tooltip content="截图" placement="top">
        <el-button
          size="small"
          :loading="screenshotLoading === activeDevice?.udid"
          @click="takeScreenshot"
          :icon="Cellphone"
          circle
        />
      </el-tooltip>
    </div>

    <!-- Screen display -->
    <div class="screen-container">
      <!-- Socket.IO scrcpy mode (primary) -->
      <div v-if="useScrcpySocketIO && activeDevice" class="screen-wrapper scrcpy-socket-wrapper">
        <ScrcpyCanvas
          :udid="activeDevice.udid"
          :max-fps="30"
          :max-size="800"
          :platform="activeDevice.platform ?? 'android'"
          @element-info="handleElementInfo"
        />
      </div>
      <!-- Electron native scrcpy mode (fallback) -->
      <div v-else-if="nativeState.mode === 'scrcpy-native' && activeDevice" class="screen-wrapper native-screen-wrapper">
        <div
          :ref="screen.setNativeHost"
          class="native-screen-host"
          tabindex="0"
          @pointerdown="$emit('pointer-down', $event)"
          @pointerup="$emit('pointer-up', $event)"
          @pointercancel="$emit('pointer-cancel', $event)"
          @keydown="handleScreenKeyDown"
          @paste="handleScreenPaste"
        >
          <div v-if="nativeState.isLoading" class="native-screen-overlay">
            <el-icon class="is-loading" :size="32"><Loading /></el-icon>
            <span>启动原生投屏...</span>
          </div>
          <div v-else-if="nativeState.error" class="native-screen-overlay error">
            <span>{{ nativeState.error }}</span>
          </div>
        </div>
      </div>
      <!-- MJPEG fallback mode -->
      <div v-else-if="nativeState.isLoading" class="screen-loading">
        <el-icon class="is-loading" :size="32"><Loading /></el-icon>
        <span>连接中...</span>
      </div>
      <div v-else-if="nativeState.error" class="screen-error">
        <el-alert :title="nativeState.error" type="error" show-icon />
      </div>
      <div v-else-if="!activeDevice" class="screen-empty">
        <el-icon :size="36"><Cellphone /></el-icon>
        <span>选择设备进行投屏</span>
      </div>
      <div v-else class="screen-wrapper">
        <canvas
          id="screen-canvas"
          :ref="screen.setCanvas"
          class="screen-canvas"
          tabindex="0"
          @pointerdown="$emit('pointer-down', $event)"
          @pointerup="$emit('pointer-up', $event)"
          @pointercancel="$emit('pointer-cancel', $event)"
          @keydown="handleScreenKeyDown"
          @paste="handleScreenPaste"
        />
      </div>
    </div>

    <!-- Status bar -->
    <div class="panel-footer" v-if="activeDevice">
      <div class="screen-meta">
        <el-tag v-if="useScrcpySocketIO" size="small" :type="socketState.isConnected ? 'success' : 'info'">
          {{ socketState.isConnected ? '已连接' : '未连接' }}
        </el-tag>
        <el-tag v-else size="small" :type="nativeState.isConnected ? 'success' : 'info'">
          {{ nativeState.isConnected ? '已连接' : '未连接' }}
        </el-tag>
        <span class="frame-count">{{ useScrcpySocketIO ? socketState.fps : nativeState.fps }} fps</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.screen-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 4px;
}

.android-nav-bar {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.screen-container {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: var(--el-bg-color-page, #f5f7fa);
  border-radius: 6px;
  min-height: 0;
}

.scrcpy-socket-wrapper {
  padding: 0;
  width: 100%;
  height: 100%;
}

.screen-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
}

.native-screen-wrapper {
  position: relative;
}

.native-screen-host {
  width: 100%;
  height: 100%;
  outline: none;
}

.native-screen-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--text-muted, #999);
  background: rgba(0, 0, 0, 0.72);
}

.native-screen-overlay.error {
  color: var(--el-color-danger, #f56c6c);
}

.screen-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  color: var(--text-muted, #999);
}

.screen-error {
  padding: 20px;
  width: 100%;
}

.screen-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  color: var(--text-muted, #999);
}

.screen-canvas {
  max-width: 100%;
  max-height: 100%;
  outline: none;
  touch-action: none;
}

.panel-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.screen-meta {
  display: flex;
  align-items: center;
  gap: 6px;
}

.frame-count {
  font-size: 11px;
  color: var(--text-muted, #999);
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}
</style>
